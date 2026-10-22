"""A spin box for a DCC address that shows long addresses the NCE way,
with four digits (0144)."""
from __future__ import annotations

from PySide6.QtWidgets import QSpinBox

from simple_train.core import nce
from simple_train.core.decoder import address_text


class AddressSpin(QSpinBox):
    def __init__(self, value: int = 3, parent=None):
        super().__init__(parent)
        self._long = False
        self.setRange(1, nce.MAX_LONG_ADDRESS)
        self.setValue(value)
        self.setMinimumWidth(90)

    def set_long(self, long: bool) -> None:
        if long != self._long:
            self._long = long
            # Redraw the number in the new style without changing the value.
            self.lineEdit().setText(self.textFromValue(self.value()))

    def textFromValue(self, value: int) -> str:
        return address_text(value, self._long or value > nce.MAX_SHORT_ADDRESS)

    def valueFromText(self, text: str) -> int:
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else self.minimum()
