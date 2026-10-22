"""The app's one connection to the command station, and the queue of jobs
that use it.

Everything that talks to the command station blocks, so it runs on a
background thread; only one job runs at a time, and the GUI shows its
progress and offers to stop it.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from simple_train.core import nce
from simple_train.core.ports import DEMO_PORT
from simple_train.core.programmer import Programmer, Progress
from simple_train.core.simulator import SimulatedCommandStation
from simple_train.gui.workers import BackgroundRunner

PROGRESS_POLL_MS = 150
DEMO_DELAY_SECONDS = 0.25  # per CV, so the demo feels like a real decoder

INFO = "info"
GOOD = "good"
ERROR = "error"


def _open(port: str, baud: int, command_station: str):
    if port == DEMO_PORT:
        transport = SimulatedCommandStation(command_station, delay=DEMO_DELAY_SECONDS)
    else:
        transport = nce.SerialTransport(port, baud)
    connection = nce.NceConnection(transport)
    try:
        connection.check()
        version = connection.version()
    except Exception:
        transport.close()
        raise
    return connection, version


class Link(QObject):
    connected_changed = Signal(bool)
    busy_changed = Signal(bool)
    progress_changed = Signal(str)  # e.g. "Reading CV 3 (2 of 6)…"; "" when idle
    message = Signal(str, str)  # text, INFO / GOOD / ERROR
    command_station_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runner = BackgroundRunner(self)
        self._connection: Optional[nce.NceConnection] = None
        self.programmer: Optional[Programmer] = None
        self.command_station = nce.POWER_CAB
        self.port = ""
        self.version: Optional[nce.Version] = None
        self._busy = False
        self._progress: Optional[Progress] = None
        self._poll = QTimer(self)
        self._poll.setInterval(PROGRESS_POLL_MS)
        self._poll.timeout.connect(self._show_progress)

    @property
    def connected(self) -> bool:
        return self._connection is not None

    @property
    def busy(self) -> bool:
        return self._busy

    # --- connecting

    def connect_to(self, port: str, baud: int, command_station: str) -> None:
        if self._busy:
            return
        self.disconnect()
        self.command_station = command_station
        self._set_busy(True, "Connecting…")
        self._runner.run(lambda: _open(port, baud, command_station),
                         lambda result: self._on_opened(port, result), self._on_open_failed)

    def _on_opened(self, port: str, result) -> None:
        self._connection, self.version = result
        self.port = port
        self.programmer = Programmer(self._connection, self.command_station)
        self._set_busy(False)
        where = "the demo command station" if port == DEMO_PORT else port
        self.message.emit(f"Connected to {where} — NCE USB interface version {self.version}", GOOD)
        self.connected_changed.emit(True)

    def _on_open_failed(self, error: Exception) -> None:
        self._set_busy(False)
        text = str(error) if isinstance(error, nce.NceError) else f"Couldn't connect: {error}"
        self.message.emit(text, ERROR)
        self.connected_changed.emit(False)

    def disconnect(self) -> None:
        if self._connection is None:
            return
        if self._progress is not None:
            self._progress.stop()
        self._runner.shutdown(int(nce.PAGED_TIMEOUT * 1000))
        self._connection.close()
        self._connection = None
        self.programmer = None
        self.message.emit("Disconnected", INFO)
        self.connected_changed.emit(False)

    def set_command_station(self, command_station: str) -> None:
        self.command_station = command_station
        if self.programmer is not None:
            self.programmer.command_station = command_station
        self.command_station_changed.emit(command_station)

    # --- jobs

    def run_job(self, job: Callable[[Programmer, Progress], object], on_done: Callable[[object], None],
                on_error: Optional[Callable[[Exception], None]] = None) -> bool:
        """job(programmer, progress) runs in the background; on_done(result)
        or on_error(error) back on the GUI thread. False if it couldn't start."""
        if self._busy or self.programmer is None:
            return False
        programmer = self.programmer
        progress = Progress()
        self._progress = progress
        self._set_busy(True, "Working…")
        self._poll.start()

        def finished(result):
            self._end_job()
            on_done(result)

        def failed(error):
            self._end_job()
            text = str(error) if isinstance(error, nce.NceError) else f"Something went wrong: {error!r}"
            self.message.emit(text, ERROR)
            if on_error is not None:
                on_error(error)

        self._runner.run(lambda: job(programmer, progress), finished, failed)
        return True

    def stop_job(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self.progress_changed.emit("Stopping after this CV…")

    def _end_job(self) -> None:
        self._poll.stop()
        self._progress = None
        self._set_busy(False)

    def _show_progress(self) -> None:
        progress = self._progress
        if progress is None or progress.stopping or not progress.current:
            return
        count = f" ({progress.done + 1} of {progress.total})" if progress.total > 1 else ""
        self.progress_changed.emit(f"{progress.current}{count}…")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.progress_changed.emit(text if busy else "")
        self.busy_changed.emit(busy)

    def shutdown(self) -> None:
        self.disconnect()
        self._runner.shutdown(int(nce.PAGED_TIMEOUT * 1000))
