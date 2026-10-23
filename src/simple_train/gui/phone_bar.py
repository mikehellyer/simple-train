"""The "Phones" strip on the Throttles tab: let phones drive, and how to
connect one."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from simple_train.core.settings import SettingsStore
from simple_train.gui.phone_server import PhoneServer, local_address


class PhoneBar(QWidget):
    def __init__(self, server: PhoneServer, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._server = server
        self._store = store
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._enable = QCheckBox("Let phones drive (Engine Driver, WiThrottle)")
        self._enable.setToolTip("Phones on the same Wi-Fi can drive trains and switch points")
        self._enable.toggled.connect(self._on_toggled)
        layout.addWidget(self._enable)
        self._status = QLabel()
        self._status.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self._status, stretch=1)
        self._problem = ""
        server.phones_changed.connect(self._show)
        server.message.connect(self._on_message)
        self._enable.setChecked(store.settings.phones)  # starts the server if it was on last time
        self._show()

    def _on_toggled(self, on: bool) -> None:
        self._store.update(phones=on)
        self._problem = ""
        if on:
            self._problem = self._server.start(self._store.settings.phone_port) or ""
            if self._problem:
                self._enable.blockSignals(True)
                self._enable.setChecked(False)
                self._enable.blockSignals(False)
        else:
            self._server.stop()
        self._show()

    def _on_message(self, text: str) -> None:
        self._problem = text
        self._show()

    def _show(self) -> None:
        if not self._server.running:
            self._status.setText(self._problem)
            return
        phones = self._server.phones
        who = (f"{len(phones)} connected: {', '.join(phones)}" if phones else "no phones connected yet")
        where = f"Engine Driver finds it by itself, or connect to {local_address()} port {self._server.port}"
        text = f"{where} · {who}"
        if self._problem:
            text += f" · {self._problem}"
        self._status.setText(text)

    def shutdown(self) -> None:
        self._server.stop()
