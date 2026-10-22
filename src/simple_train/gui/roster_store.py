"""The roster, shared by the Locos tab and the programmer, with a signal
so each can show the other's changes."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from simple_train.core.roster import Loco, Roster


class RosterStore(QObject):
    changed = Signal()

    def __init__(self, roster: Optional[Roster] = None, parent=None):
        super().__init__(parent)
        self.roster = roster or Roster()

    def save(self) -> None:
        """Call after changing a loco in place."""
        self.roster.save()
        self.changed.emit()

    def add(self, loco: Loco) -> Loco:
        self.roster.add(loco)
        self.changed.emit()
        return loco

    def remove(self, loco_id: str) -> None:
        self.roster.remove(loco_id)
        self.changed.emit()
