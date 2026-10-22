"""Driving locos on the main: speed, direction and functions.

Everything goes through NCE's 0xA2 loco command (the USB interface can't
send raw DCC packets):
  0xA2 adH adL 0x04 speed   forward, 128 speed steps (speed 0–126)
  0xA2 adH adL 0x03 speed   reverse, 128 speed steps
  0xA2 adH adL 0x06 0       emergency stop, facing forward (0x05 facing reverse)
  0xA2 adH adL 0x07 bits    F0–F4   (F0 = 0x10, F1–F4 = bits 0–3)
  0xA2 adH adL 0x08 bits    F5–F8
  0xA2 adH adL 0x09 bits    F9–F12
  0xA2 adH adL 0x15 bits    F13–F20
  0xA2 adH adL 0x16 bits    F21–F28
The command station keeps repeating the last speed and functions to the
loco by itself. Speed 127 can crash a Power Cab (JMRI notes this), so 126
is the top. Like JMRI, a speed command goes before each function command,
which resets the command station's consist pointer.

128 speed steps work for every decoder set to 28/128 steps in CV29, which is
nearly all of them.

Commands are sent by a ThrottleSender on its own thread, which only ever
sends each loco's latest state: dragging a speed slider makes dozens of
changes a second, but the loco is sent just the newest one.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from simple_train.core import nce
from simple_train.core.decoder import address_text

MAX_SPEED = 126
FUNCTION_COUNT = 29  # F0–F28

FORWARD_128 = 0x04
REVERSE_128 = 0x03
ESTOP_FORWARD = 0x06
ESTOP_REVERSE = 0x05
# (sub-command, first function, last function)
FUNCTION_GROUPS = [(0x07, 0, 4), (0x08, 5, 8), (0x09, 9, 12), (0x15, 13, 20), (0x16, 21, 28)]


def group_of(function: int) -> int:
    """Which of FUNCTION_GROUPS a function is sent in."""
    for index, (_, first, last) in enumerate(FUNCTION_GROUPS):
        if first <= function <= last:
            return index
    raise ValueError(f"F{function} is out of range (F0–F28)")


def _command(address: int, long: bool, sub: int, data: int) -> bytes:
    return bytes((nce.LOCO_COMMAND,)) + nce.loco_address_bytes(address, long) + bytes((sub, data))


def speed_command(address: int, long: bool, speed: int, forward: bool) -> bytes:
    speed = max(0, min(MAX_SPEED, speed))
    return _command(address, long, FORWARD_128 if forward else REVERSE_128, speed)


def emergency_stop_command(address: int, long: bool, forward: bool) -> bytes:
    return _command(address, long, ESTOP_FORWARD if forward else ESTOP_REVERSE, 0)


def function_command(address: int, long: bool, group: int, functions: list[bool]) -> bytes:
    sub, first, last = FUNCTION_GROUPS[group]
    if group == 0:  # F0 is bit 4, F1–F4 bits 0–3
        bits = (0x10 if functions[0] else 0) | sum(1 << (n - 1) for n in range(1, 5) if functions[n])
    else:
        bits = sum(1 << (n - first) for n in range(first, last + 1) if functions[n])
    return _command(address, long, sub, bits)


@dataclass
class LocoState:
    """What one loco has been told to do."""

    address: int
    long: bool
    speed: int = 0
    forward: bool = True
    emergency: bool = False
    functions: list[bool] = field(default_factory=lambda: [False] * FUNCTION_COUNT)

    @property
    def key(self) -> tuple[int, bool]:
        return self.address, self.long

    def copy(self) -> "LocoState":
        return LocoState(self.address, self.long, self.speed, self.forward, self.emergency, list(self.functions))


@dataclass
class _Pending:
    state: LocoState
    drive: bool = False  # speed, direction or emergency stop changed
    groups: set[int] = field(default_factory=set)


class ThrottleSender:
    """Sends loco commands from its own thread, newest state first-come.

    on_error(text) is called on the sender's thread: hand it to the GUI
    through a Qt signal on a QObject that lives there.
    """

    def __init__(self, connection: nce.NceConnection, on_error: Optional[Callable[[str], None]] = None):
        self._connection = connection
        self._on_error = on_error
        self._pending: dict[tuple[int, bool], _Pending] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="throttle-sender", daemon=True)
        self._thread.start()

    def drive(self, state: LocoState) -> None:
        """Send the loco's speed, direction (or emergency stop)."""
        self._queue(state, drive=True)

    def functions(self, state: LocoState, *functions: int) -> None:
        """Send the groups holding these functions."""
        self._queue(state, groups={group_of(n) for n in functions})

    def _queue(self, state: LocoState, drive: bool = False, groups: Optional[set[int]] = None) -> None:
        with self._lock:
            pending = self._pending.get(state.key)
            if pending is None:
                pending = self._pending[state.key] = _Pending(state.copy())
            pending.state = state.copy()
            pending.drive |= drive
            pending.groups |= groups or set()
            self._idle.clear()
        self._wake.set()

    def wait_until_sent(self, timeout: float = 5.0) -> bool:
        return self._idle.wait(timeout)

    def stop(self, timeout: float = 5.0) -> None:
        """Send what's still waiting, then end the thread."""
        self.wait_until_sent(timeout)
        self._stopping = True
        self._wake.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._pending:
                        self._idle.set()
                        break
                    key = next(iter(self._pending))
                    pending = self._pending.pop(key)
                try:
                    self._send(pending)
                except nce.NceError as error:
                    if self._on_error is not None:
                        self._on_error(f"Loco {address_text(pending.state.address, pending.state.long)}: {error}")
                except Exception as error:  # never let the thread die
                    if self._on_error is not None:
                        self._on_error(f"Loco {address_text(pending.state.address, pending.state.long)}: {error!r}")
            if self._stopping:
                return

    def _send(self, pending: _Pending) -> None:
        state = pending.state
        if state.emergency:
            self._connection.loco_command(emergency_stop_command(state.address, state.long, state.forward))
        elif pending.drive or pending.groups:
            # Speed first even for a function change: NCE wants it (see above).
            self._connection.loco_command(speed_command(state.address, state.long, state.speed, state.forward))
        for group in sorted(pending.groups):
            self._connection.loco_command(function_command(state.address, state.long, group, state.functions))
