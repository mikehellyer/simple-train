"""The WiThrottle protocol, so phone throttles (Engine Driver on Android,
WiThrottle on iPhone) can drive trains and switch points.

It's JMRI's text protocol over TCP (port 12090 by default), one command a
line; see https://www.jmri.org/help/en/package/jmri/jmrit/withrottle/Protocol.shtml.
This module only turns lines into actions and actions into lines: the
sockets, timers and the real railway live in gui.phone_server, behind the
Railway interface below, so all of this can be tested without either.

What a session understands:
  N<name> / HU<id>     the phone's name and id (answered with *<seconds>)
  * / *+ / *-          heartbeat; turn heartbeat checking on / off
  M<t>+<key><;><addr>  add a loco to throttle <t>: addr is S3 / L144, or E<roster name>
  M<t>-<key><;>r       release a loco (or * for all of them)
  M<t>A<key><;><act>   drive: V<speed> R<dir> X(stop now) I(idle) F<1|0><n> (key down/up)
                       f<1|0><n> (force) m<1|0><n> (momentary) q<V|R> (query) s<mode>
  PTA<C|T|2><name>     set a point closed / thrown / the other way
  PPA<0|1>             track power: the NCE USB interface can't, so we say so
  Q                    the phone is leaving
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from simple_train.core.throttle import FUNCTION_COUNT, LocoState

VERSION = "2.0"
DEFAULT_PORT = 12090
HEARTBEAT_SECONDS = 10
SERVICE_TYPE = "_withrottle._tcp.local."

ENTRY = "]\\["  # between the entries of a list
FIELD = "}|{"  # between the fields of an entry
PART = "<;>"  # between the parts of a throttle command

POINT_CLOSED = 2
POINT_THROWN = 4
POINT_UNKNOWN = 1


@dataclass
class RosterEntry:
    name: str
    address: int
    long: bool


@dataclass
class PointEntry:
    system_name: str  # e.g. "NT12"
    user_name: str
    thrown: Optional[bool]  # None: not known


class Railway(Protocol):
    """What a session needs from the rest of the app."""

    def roster(self) -> list[RosterEntry]: ...

    def function_labels(self, address: int, long: bool) -> list[str]: ...

    def is_momentary(self, address: int, long: bool, number: int) -> bool: ...

    def loco(self, address: int, long: bool) -> LocoState: ...

    def drive(self, state: LocoState, session: "Session") -> Optional[str]:
        """Send speed/direction; an error message if it can't be done now."""
        ...

    def functions(self, state: LocoState, number: int, session: "Session") -> Optional[str]: ...

    def points(self) -> list[PointEntry]: ...

    def set_point(self, name: str, action: str) -> Optional[str]:
        """action: "C" closed, "T" thrown, "2" the other way. An error message, or None."""
        ...


def _snapshot(state: LocoState) -> tuple:
    return (-1 if state.emergency else state.speed, state.forward, tuple(state.functions))


def key_of(address: int, long: bool) -> str:
    return f"{'L' if long else 'S'}{address}"


def parse_key(text: str) -> Optional[tuple[int, bool]]:
    """"L144" -> (144, True); "S3" -> (3, False)."""
    if len(text) < 2 or text[0] not in "LS" or not text[1:].isdigit():
        return None
    address = int(text[1:])
    long = text[0] == "L"
    if address < 1 or address > (10239 if long else 127):
        return None
    return address, long


def roster_line(entries: list[RosterEntry]) -> str:
    return f"RL{len(entries)}" + "".join(
        f"{ENTRY}{entry.name}{FIELD}{entry.address}{FIELD}{'L' if entry.long else 'S'}" for entry in entries)


def point_titles_line() -> str:
    return f"PTT{ENTRY}Points{FIELD}Point{ENTRY}Closed{FIELD}{POINT_CLOSED}{ENTRY}Thrown{FIELD}{POINT_THROWN}"


def point_state(thrown: Optional[bool]) -> int:
    return POINT_UNKNOWN if thrown is None else (POINT_THROWN if thrown else POINT_CLOSED)


def points_line(points: list[PointEntry]) -> str:
    return "PTL" + "".join(f"{ENTRY}{p.system_name}{FIELD}{p.user_name}{FIELD}{point_state(p.thrown)}"
                           for p in points)


def point_change_line(system_name: str, thrown: Optional[bool]) -> str:
    return f"PTA{point_state(thrown)}{system_name}"


@dataclass
class _Throttle:
    locos: dict[str, LocoState] = field(default_factory=dict)  # key ("L144") -> state


class Session:
    """One connected phone."""

    def __init__(self, railway: Railway, send: Callable[[str], None], server_name: str = "Simple-Train"):
        self.railway = railway
        self._send = send
        self.server_name = server_name
        self.name = ""
        self.device_id = ""
        self.heartbeat_on = False
        self.closed = False
        self._throttles: dict[str, _Throttle] = {}
        self._momentary: dict[tuple[str, int], bool] = {}  # (key, function) -> overridden by the phone
        # What this phone has last been told about each loco, so only changes are sent.
        self._seen: dict[tuple[str, str], tuple] = {}  # (throttle id, key) -> snapshot

    # --- the conversation

    def greet(self) -> None:
        """What a phone is told as soon as it connects."""
        self._send(f"VN{VERSION}")
        self._send(roster_line(self.railway.roster()))
        self._send("PPA2")  # track power: not known (the USB interface can't switch it)
        self._send(point_titles_line())
        self._send(points_line(self.railway.points()))
        self._send("RCC0")
        self._send("HTSimple-Train")
        self._send(f"Ht{self.server_name}")
        self._send(f"*{HEARTBEAT_SECONDS}")

    def handle(self, line: str) -> None:
        line = line.strip()
        if not line or self.closed:
            return
        kind = line[0]
        if kind == "*":
            if line == "*+":
                self.heartbeat_on = True
            elif line == "*-":
                self.heartbeat_on = False
        elif kind == "N":
            self.name = line[1:].strip()
            self._send(f"*{HEARTBEAT_SECONDS}")
        elif line.startswith("HU"):
            self.device_id = line[2:].strip()
        elif kind == "M" and len(line) >= 3:
            self._throttle_command(line[1], line[2], line[3:])
        elif line.startswith("PTA") and len(line) > 4:
            error = self.railway.set_point(line[4:], line[3])
            if error:
                self.alert(error)
        elif line.startswith("PPA"):
            self.alert("Simple-Train can't switch track power through the NCE USB interface. "
                       "Use Stop on each throttle, or Stop all in the app.")
        elif kind == "Q":
            self.closed = True
        # Anything else (routes, consists, D packets…) isn't supported: ignored, as the protocol asks.

    def alert(self, text: str) -> None:
        self._send(f"HM{text}")

    def info(self, text: str) -> None:
        self._send(f"Hm{text}")

    @property
    def locos(self) -> list[LocoState]:
        return [state for throttle in self._throttles.values() for state in throttle.locos.values()]

    def drives(self, address: int, long: bool) -> list[tuple[str, str]]:
        """(throttle id, key) for each of this phone's throttles with the loco."""
        key = key_of(address, long)
        return [(tid, key) for tid, throttle in self._throttles.items() if key in throttle.locos]

    # --- throttle commands

    def _throttle_command(self, tid: str, command: str, rest: str) -> None:
        key, _, extra = rest.partition(PART)
        throttle = self._throttles.setdefault(tid, _Throttle())
        if command == "+":
            self._add(tid, throttle, key, extra)
        elif command == "-":
            self._remove(tid, throttle, key)
        elif command == "A":
            targets = list(throttle.locos.items()) if key == "*" else (
                [(key, throttle.locos[key])] if key in throttle.locos else [])
            for loco_key, state in targets:
                self._action(tid, loco_key, state, extra)

    def _add(self, tid: str, throttle: _Throttle, key: str, extra: str) -> None:
        wanted = None
        if extra.startswith("E"):
            name = extra[1:]
            entry = next((e for e in self.railway.roster() if e.name == name), None)
            if entry is not None:
                wanted = (entry.address, entry.long)
        else:
            wanted = parse_key(extra or key)
        if wanted is None:
            self.alert(f"Simple-Train: can't drive '{extra or key}' — check the address")
            return
        address, long = wanted
        key = key_of(address, long)
        state = self.railway.loco(address, long)
        throttle.locos[key] = state
        prefix = f"M{tid}"
        self._send(f"{prefix}+{key}{PART}")
        labels = self.railway.function_labels(address, long)
        labels = (labels + [""] * FUNCTION_COUNT)[:FUNCTION_COUNT]
        self._send(f"{prefix}L{key}{PART}{ENTRY}" + ENTRY.join(labels) + ENTRY)
        for number in range(FUNCTION_COUNT):
            self._send(f"{prefix}A{key}{PART}F{1 if state.functions[number] else 0}{number}")
        self._send(f"{prefix}A{key}{PART}V{-1 if state.emergency else state.speed}")
        self._send(f"{prefix}A{key}{PART}R{1 if state.forward else 0}")
        self._send(f"{prefix}A{key}{PART}s1")  # 128 speed steps
        self._seen[(tid, key)] = _snapshot(state)

    def _remove(self, tid: str, throttle: _Throttle, key: str) -> None:
        keys = list(throttle.locos) if key == "*" else ([key] if key in throttle.locos else [])
        for loco_key in keys:
            del throttle.locos[loco_key]
            self._seen.pop((tid, loco_key), None)
            self._send(f"M{tid}-{loco_key}{PART}")

    def _momentary_for(self, key: str, state: LocoState, number: int) -> bool:
        if (key, number) in self._momentary:
            return self._momentary[(key, number)]
        return self.railway.is_momentary(state.address, state.long, number)

    def _action(self, tid: str, key: str, state: LocoState, action: str) -> None:
        if not action:
            return
        code, value = action[0], action[1:]
        if code == "V" and value.lstrip("-").isdigit():
            speed = int(value)
            if speed < 0:
                state.speed, state.emergency = 0, True
            else:
                state.speed, state.emergency = min(126, speed), False
            self._drive(state)
        elif code == "R":
            state.forward = value != "0"
            state.emergency = False
            self._drive(state)
        elif code == "X":
            state.speed, state.emergency = 0, True
            self._drive(state)
        elif code == "I":
            state.speed, state.emergency = 0, False
            self._drive(state)
        elif code in "Ff" and len(value) >= 2 and value[1:].isdigit():
            number = int(value[1:])
            if number >= FUNCTION_COUNT:
                return
            down = value[0] == "1"
            if code == "f":  # forced on or off
                self._set_function(state, number, down)
            elif self._momentary_for(key, state, number):
                self._set_function(state, number, down)
            elif down:  # a latching key toggles when pressed; its release does nothing
                self._set_function(state, number, not state.functions[number])
        elif code == "m" and len(value) >= 2 and value[1:].isdigit():
            self._momentary[(key, int(value[1:]))] = value[0] == "1"
        elif code == "q":
            if value == "V":
                self._send(f"M{tid}A{key}{PART}V{state.speed}")
            elif value == "R":
                self._send(f"M{tid}A{key}{PART}R{1 if state.forward else 0}")
        elif code == "s":
            self._send(f"M{tid}A{key}{PART}s1")  # always 128 steps through NCE
        elif code in "rd":
            throttle = self._throttles.get(tid)
            if throttle is not None:
                self._remove(tid, throttle, key)

    def _drive(self, state: LocoState) -> None:
        error = self.railway.drive(state, self)
        if error:
            self.alert(error)
        # Tell every throttle of ours with this loco (the railway tells other phones).
        self.sync(state, force_speed=True)

    def _set_function(self, state: LocoState, number: int, on: bool) -> None:
        state.functions[number] = on
        error = self.railway.functions(state, number, self)
        if error:
            self.alert(error)
        self.sync(state)

    # --- telling the phone about changes

    def sync(self, state: LocoState, force_speed: bool = False) -> None:
        """Tell the phone whatever has changed about a loco since it was last
        told, on each of its throttles that has the loco. (force_speed: send
        the speed even if unchanged, as the answer to the phone's own command.)"""
        now = _snapshot(state)
        for tid, key in self.drives(state.address, state.long):
            before = self._seen.get((tid, key))
            prefix = f"M{tid}A{key}{PART}"
            if before is None or before[0] != now[0] or force_speed:
                self._send(f"{prefix}V{now[0]}")
            if before is None or before[1] != now[1]:
                self._send(f"{prefix}R{1 if now[1] else 0}")
            for number, on in enumerate(now[2]):
                if before is None or before[2][number] != on:
                    self._send(f"{prefix}F{1 if on else 0}{number}")
            self._seen[(tid, key)] = now

    def roster_changed(self) -> None:
        self._send(roster_line(self.railway.roster()))

    def points_changed(self) -> None:
        self._send(points_line(self.railway.points()))

    def point_changed(self, system_name: str, thrown: Optional[bool]) -> None:
        self._send(point_change_line(system_name, thrown))
