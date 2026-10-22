"""The strip along the top: which port the NCE USB interface is on, what
it's plugged into, and connect / disconnect."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from simple_train.core import nce
from simple_train.core.ports import DEMO_PORT, list_ports, permission_problem
from simple_train.core.settings import SettingsStore
from simple_train.gui.link import ERROR, Link

GREEN = "#2e9e4f"
GREY = "#8a8f98"


class ConnectionBar(QWidget):
    def __init__(self, link: Link, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._link = link
        self._store = store
        settings = store.settings

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        self._lamp = QLabel("●")
        self._lamp.setStyleSheet(f"color: {GREY}; font-size: 16px;")
        layout.addWidget(self._lamp)

        layout.addWidget(QLabel("NCE USB on"))
        self._ports = QComboBox()
        self._ports.setMinimumWidth(280)
        layout.addWidget(self._ports, stretch=1)

        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Look for serial ports again")
        refresh.clicked.connect(self.refresh_ports)
        layout.addWidget(refresh)

        layout.addSpacing(12)
        layout.addWidget(QLabel("Baud"))
        self._baud = QComboBox()
        for baud in nce.BAUD_RATES:
            self._baud.addItem(str(baud), baud)
        self._baud.setCurrentIndex(max(0, self._baud.findData(settings.baud)))
        self._baud.setToolTip("The NCE USB interface runs at 9600 baud unless its switches have been changed")
        layout.addWidget(self._baud)

        layout.addSpacing(12)
        layout.addWidget(QLabel("Plugged into"))
        self._station = QComboBox()
        for key, name in nce.COMMAND_STATIONS.items():
            self._station.addItem(name, key)
        self._station.setCurrentIndex(max(0, self._station.findData(settings.command_station)))
        self._station.setToolTip("Through the USB interface, only a Power Cab or Twin has a programming track")
        self._station.currentIndexChanged.connect(self._on_station_changed)
        layout.addWidget(self._station)

        layout.addSpacing(12)
        self._button = QPushButton("Connect")
        self._button.setMinimumWidth(110)
        self._button.clicked.connect(self._on_button)
        layout.addWidget(self._button)

        link.connected_changed.connect(self._show_state)
        link.busy_changed.connect(lambda busy: self._show_state(link.connected))
        self.refresh_ports()
        self._show_state(False)

    def refresh_ports(self) -> None:
        wanted = self._ports.currentData() or self._store.settings.port
        self._ports.clear()
        ports = list_ports()
        for port in ports:
            self._ports.addItem(port.label, port.device)
        index = self._ports.findData(wanted)
        if index < 0:  # nothing chosen yet: the first likely NCE port, else the first port
            index = 0
        self._ports.setCurrentIndex(index)

    def connect_now(self) -> None:
        port = self._ports.currentData()
        if not port:
            return
        problem = permission_problem(port)
        if problem:
            self._link.message.emit(problem, ERROR)
            return
        baud = self._baud.currentData()
        station = self._station.currentData()
        self._store.update(port=port, baud=baud, command_station=station)
        self._link.connect_to(port, baud, station)

    def _on_button(self) -> None:
        if self._link.connected:
            self._link.disconnect()
        else:
            self.connect_now()

    def _on_station_changed(self) -> None:
        station = self._station.currentData()
        self._store.update(command_station=station)
        self._link.set_command_station(station)

    def _show_state(self, connected: bool) -> None:
        busy = self._link.busy
        self._lamp.setStyleSheet(f"color: {GREEN if connected else GREY}; font-size: 16px;")
        self._lamp.setToolTip("Connected" if connected else "Not connected")
        self._button.setText("Disconnect" if connected else "Connect")
        self._button.setEnabled(not busy)
        for widget in (self._ports, self._baud):
            widget.setEnabled(not connected and not busy)
        self._baud.setEnabled(not connected and not busy and self._ports.currentData() != DEMO_PORT)
