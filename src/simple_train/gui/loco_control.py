"""One shared record of every loco being driven, whoever is driving it:
the app's own throttles and the phones (Engine Driver) alike.

Each loco has a single LocoState here, so a throttle in the app and a
phone driving the same loco always agree, and "stop everything" really
means everything.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from simple_train.core.throttle import LocoState
from simple_train.gui.link import Link


class LocoControl(QObject):
    # (address, long), and whoever made the change (so they needn't redraw for it)
    changed = Signal(object, object)

    def __init__(self, link: Link, parent=None):
        super().__init__(parent)
        self.link = link
        self._states: dict[tuple[int, bool], LocoState] = {}

    @property
    def can_drive(self) -> bool:
        return self.link.connected and self.link.throttle is not None and not self.link.programming_track_busy

    def state(self, address: int, long: bool) -> LocoState:
        key = (address, long)
        if key not in self._states:
            self._states[key] = LocoState(address, long)
        return self._states[key]

    def drive(self, state: LocoState, source: Optional[object] = None) -> bool:
        """Send the loco's speed and direction (or emergency stop) as they now are."""
        if not self.can_drive:
            return False
        self.link.throttle.drive(state)
        self.changed.emit(state.key, source)
        return True

    def functions(self, state: LocoState, *numbers: int, source: Optional[object] = None) -> bool:
        if not self.can_drive:
            return False
        self.link.throttle.functions(state, *numbers)
        self.changed.emit(state.key, source)
        return True

    def set_speed(self, state: LocoState, speed: int, source: Optional[object] = None) -> bool:
        state.speed = max(0, min(126, speed))
        state.emergency = False
        return self.drive(state, source)

    def emergency_stop(self, state: LocoState, source: Optional[object] = None) -> bool:
        state.speed = 0
        state.emergency = True
        return self.drive(state, source)

    def moving(self) -> list[LocoState]:
        return [state for state in self._states.values() if state.speed > 0]

    def stop_moving(self, wait: float = 2.0) -> list[LocoState]:
        """Bring every moving loco to a normal stop; returns the ones stopped."""
        stopped = self.moving()
        for state in stopped:
            self.set_speed(state, 0)
        if stopped and self.link.throttle is not None:
            self.link.throttle.wait_until_sent(wait)
        return stopped

    def emergency_stop_all(self, keys: Optional[list[tuple[int, bool]]] = None) -> int:
        """Emergency-stop these locos (all known ones by default)."""
        states = [self._states[key] for key in (keys or list(self._states)) if key in self._states]
        for state in states:
            self.emergency_stop(state)
        return len(states)
