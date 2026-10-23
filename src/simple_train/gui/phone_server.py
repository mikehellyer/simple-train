"""Phone throttles: a WiThrottle server, so Engine Driver (Android) or
WiThrottle (iPhone) on the same Wi-Fi can drive trains and switch points.

Each phone is a TCP connection (Qt's, on the GUI thread, so no locking),
with a core.withrottle.Session doing the talking. The server is announced
on the network with Zeroconf ("_withrottle._tcp"), which is how Engine
Driver lists it without typing an address.

Safety, as JMRI does it: a phone that turns heartbeats on and then goes
quiet for longer than the heartbeat time has its locos emergency-stopped;
a phone whose connection drops has its moving locos brought to a stop.
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from simple_train.core import withrottle as wt
from simple_train.core.throttle import LocoState
from simple_train.gui.loco_control import LocoControl
from simple_train.gui.roster_store import RosterStore

HEARTBEAT_GRACE = 2  # seconds past the heartbeat time before stopping a quiet phone's locos


def local_address() -> str:
    """This computer's address on the local network (what to type into a phone)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.254.254.254", 1))  # no packet is sent; it just picks the interface
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class _Phone(QObject):
    def __init__(self, server: "PhoneServer", sock: QTcpSocket):
        super().__init__(server)
        self.server = server
        self.socket = sock
        self.buffer = b""
        self.last_heard = time.monotonic()
        self.session = wt.Session(server, self.send, server_name=server.server_name)
        sock.readyRead.connect(self._on_ready_read)
        sock.disconnected.connect(self._on_disconnected)

    @property
    def label(self) -> str:
        return self.session.name or self.socket.peerAddress().toString()

    def send(self, line: str) -> None:
        if self.socket.state() == QTcpSocket.ConnectedState:
            self.socket.write((line + "\n").encode("utf-8"))

    def _on_ready_read(self) -> None:
        self.buffer += bytes(self.socket.readAll())
        self.last_heard = time.monotonic()
        # Any of \n, \r or \r\n ends a command.
        lines = self.buffer.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
        self.buffer = lines.pop()
        named = bool(self.session.name)
        for raw in lines:
            self.session.handle(raw.decode("utf-8", errors="replace"))
            if self.session.closed:
                self.socket.disconnectFromHost()
                break
        if self.session.name and not named:
            self.server.phones_changed.emit()

    def _on_disconnected(self) -> None:
        self.server._drop(self)


class PhoneServer(QObject):
    phones_changed = Signal()  # a phone connected, left, or said its name
    message = Signal(str)  # something worth showing (a quiet phone stopped, etc.)

    def __init__(self, control: LocoControl, roster: RosterStore, track_plan, parent=None):
        super().__init__(parent)
        self.control = control
        self.roster_store = roster
        self.track_plan = track_plan
        self.server_name = f"Simple-Train on {socket.gethostname()}"
        self.port = wt.DEFAULT_PORT
        self._server: Optional[QTcpServer] = None
        self._phones: list[_Phone] = []
        self._zeroconf = None
        self._service = None
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(1000)
        self._heartbeat.timeout.connect(self._check_heartbeats)
        self.announce = True  # tell the network with Zeroconf (tests turn it off)

        control.changed.connect(self._on_loco_changed)
        roster.changed.connect(lambda: self._each(lambda s: s.roster_changed()))
        track_plan.points_changed.connect(lambda: self._each(lambda s: s.points_changed()))
        track_plan.point_set.connect(self._on_point_set)

    # --- starting and stopping

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.isListening()

    @property
    def phones(self) -> list[str]:
        return [phone.label for phone in self._phones]

    def start(self, port: int = wt.DEFAULT_PORT) -> Optional[str]:
        """Start listening; an error message if it can't."""
        self.stop()
        self.port = port
        server = QTcpServer(self)
        if not server.listen(QHostAddress.Any, port):
            error = server.errorString()
            server.deleteLater()
            return f"Couldn't open port {port} for phones: {error}"
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        self.port = server.serverPort()  # the real one, if 0 asked for any free port
        self._heartbeat.start()
        if self.announce:
            threading.Thread(target=self._announce, args=(self.port,), name="zeroconf", daemon=True).start()
        self.phones_changed.emit()
        return None

    def stop(self) -> None:
        for phone in list(self._phones):
            phone.socket.disconnectFromHost()
            self._drop(phone)
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        self._heartbeat.stop()
        zeroconf, service = self._zeroconf, self._service
        self._zeroconf = self._service = None
        if zeroconf is not None:
            try:
                if service is not None:
                    zeroconf.unregister_service(service)
                zeroconf.close()
            except Exception:
                pass
        self.phones_changed.emit()

    def _announce(self, port: int) -> None:
        """Tell the network where we are (on its own thread: it takes a moment)."""
        try:
            from zeroconf import ServiceInfo, Zeroconf

            address = local_address()
            info = ServiceInfo(
                wt.SERVICE_TYPE,
                f"{self.server_name}.{wt.SERVICE_TYPE}",
                addresses=[socket.inet_aton(address)],
                port=port,
                properties={"jmriversion": "Simple-Train"},
                server=f"{socket.gethostname()}.local.",
            )
            zeroconf = Zeroconf()
            zeroconf.register_service(info, allow_name_change=True)
            if self._server is None:  # stopped meanwhile
                zeroconf.unregister_service(info)
                zeroconf.close()
                return
            self._zeroconf, self._service = zeroconf, info
        except Exception as error:  # phones can still connect by typing the address
            self.message.emit(f"Couldn't announce Simple-Train on the network ({error}); "
                              "type the address into the phone instead")

    # --- phones coming and going

    def _on_new_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            phone = _Phone(self, self._server.nextPendingConnection())
            self._phones.append(phone)
            phone.session.greet()
            self.phones_changed.emit()

    def _drop(self, phone: _Phone) -> None:
        if phone not in self._phones:
            return
        self._phones.remove(phone)
        stopped = [state for state in phone.session.locos if state.speed > 0 and not self._driven_elsewhere(state, phone)]
        for state in stopped:
            self.control.set_speed(state, 0, source=phone.session)
        if stopped:
            self.message.emit(f"{phone.label} left: stopped its locos")
        phone.deleteLater()
        self.phones_changed.emit()

    def _driven_elsewhere(self, state: LocoState, phone: _Phone) -> bool:
        return any(other is not phone and other.session.drives(state.address, state.long) for other in self._phones)

    def _check_heartbeats(self) -> None:
        now = time.monotonic()
        for phone in list(self._phones):
            session = phone.session
            if session.heartbeat_on and now - phone.last_heard > wt.HEARTBEAT_SECONDS + HEARTBEAT_GRACE:
                moving = [state for state in session.locos if state.speed > 0]
                for state in moving:
                    self.control.emergency_stop(state, source=None)
                if moving:
                    self.message.emit(f"Lost touch with {phone.label}: its locos were stopped")
                phone.last_heard = now  # once is enough until it's heard from again

    def _each(self, action) -> None:
        for phone in self._phones:
            action(phone.session)

    def _on_loco_changed(self, key, source) -> None:
        state = self.control.state(*key)
        for phone in self._phones:
            if phone.session is not source:
                phone.session.sync(state)

    def _on_point_set(self, address: int, thrown: bool) -> None:
        self._each(lambda session: session.point_changed(f"NT{address}", thrown))

    # --- the Railway that sessions talk to

    def roster(self) -> list[wt.RosterEntry]:
        return [wt.RosterEntry(loco.name, loco.address, loco.long_address)
                for loco in self.roster_store.roster.sorted()]

    def _roster_loco(self, address: int, long: bool):
        return self.roster_store.roster.find_by_address(address, long)

    def function_labels(self, address: int, long: bool) -> list[str]:
        loco = self._roster_loco(address, long)
        if loco is None:
            return ["Lights"]
        return [loco.function_name(number) for number in range(29)]

    def is_momentary(self, address: int, long: bool, number: int) -> bool:
        loco = self._roster_loco(address, long)
        return loco is not None and loco.is_momentary(number)

    def loco(self, address: int, long: bool) -> LocoState:
        return self.control.state(address, long)

    def _why_not(self) -> str:
        if not self.control.link.connected:
            return "Simple-Train isn't connected to the NCE USB interface"
        return "The programming track is in use — try again in a moment"

    def drive(self, state: LocoState, session) -> Optional[str]:
        return None if self.control.drive(state, source=session) else self._why_not()

    def functions(self, state: LocoState, number: int, session) -> Optional[str]:
        return None if self.control.functions(state, number, source=session) else self._why_not()

    def points(self) -> list[wt.PointEntry]:
        entries = []
        for address, tiles in sorted(self.track_plan.points_by_address().items()):
            names = [tile.name for tile in tiles if tile.name]
            entries.append(wt.PointEntry(f"NT{address}", " / ".join(names) or f"Point {address}", tiles[0].thrown))
        return entries

    def set_point(self, name: str, action: str) -> Optional[str]:
        digits = name[2:] if name.upper().startswith("NT") else name
        if not digits.isdigit():
            return f"There's no point called {name}"
        thrown = {"C": False, "T": True}.get(action.upper())  # "2": the other way
        return self.track_plan.set_point(int(digits), thrown)
