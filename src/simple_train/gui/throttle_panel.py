"""The Throttles tab: a row of throttles, one loco each, for driving trains
from the computer — speed, direction, stop, emergency stop and the
function keys (F0–F28), named from the roster.

Keys, for the throttle that has the focus (click it first):
  Up / Down          faster / slower (Page Up / Page Down: in big steps)
  Left / Right       reverse / forward
  Space              stop
  Escape             emergency stop
  0–9                toggle F0–F9
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simple_train.core import decoder
from simple_train.core.roster import Loco
from simple_train.core.settings import SettingsStore
from simple_train.core.throttle import FUNCTION_COUNT, MAX_SPEED, LocoState
from simple_train.gui.address_spin import AddressSpin
from simple_train.gui.link import Link
from simple_train.gui.loco_control import LocoControl
from simple_train.gui.roster_store import RosterStore

MAX_THROTTLES = 6
BIG_STEP = 10
RED = "#c0392b"
GREEN = "#2e9e4f"
FUNCTION_ON = ("QPushButton:checked, QPushButton:pressed { background-color: #f5b82e; color: #1d1d1d; "
               "font-weight: 600; border: 1px solid #c98f10; border-radius: 4px; }")
OTHER = "other"  # the "Other address…" choice in a throttle's loco list


class _SideScroll(QScrollArea):
    """Scrolls side to side only, keeping its contents exactly as tall as
    itself, so each throttle scrolls its own function keys instead."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.widget() is not None:
            self.widget().setFixedHeight(self.viewport().height())


class ThrottleCard(QFrame):
    """One throttle."""

    close_requested = Signal(object)  # self
    loco_changed = Signal()

    def __init__(self, panel: "ThrottlePanel", parent=None):
        super().__init__(parent)
        self._panel = panel
        self.state: Optional[LocoState] = None
        self.loco_id: Optional[str] = None
        self.setFrameShape(QFrame.StyledPanel)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedWidth(300)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)

        top = QHBoxLayout()
        self._choice = QComboBox()
        self._choice.setFocusPolicy(Qt.ClickFocus)
        self._choice.activated.connect(self._on_choice)
        top.addWidget(self._choice, stretch=1)
        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Close this throttle (stops its loco)")
        close.setAutoRaise(True)
        close.clicked.connect(lambda: self.close_requested.emit(self))
        top.addWidget(close)
        layout.addLayout(top)

        self._other_row = QWidget()
        other = QHBoxLayout(self._other_row)
        other.setContentsMargins(0, 0, 0, 0)
        other.addWidget(QLabel("Address"))
        self._address = AddressSpin(3)
        other.addWidget(self._address)
        self._long = QCheckBox("Long")
        self._long.toggled.connect(self._address.set_long)
        other.addWidget(self._long)
        use = QPushButton("Drive")
        use.clicked.connect(self._use_address)
        other.addWidget(use)
        self._address.valueChanged.connect(self._on_other_address)
        self._other_row.hide()
        layout.addWidget(self._other_row)

        self._name = QLabel("No loco")
        name_font = QFont()
        name_font.setPointSizeF(name_font.pointSizeF() * 1.35)
        name_font.setBold(True)
        self._name.setFont(name_font)
        self._name.setWordWrap(True)
        layout.addWidget(self._name)
        self._detail = QLabel("Choose a loco above")
        self._detail.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self._detail)

        middle = QHBoxLayout()
        self._slider = QSlider(Qt.Vertical)
        self._slider.setRange(0, MAX_SPEED)
        self._slider.setPageStep(BIG_STEP)
        self._slider.setMinimumHeight(230)
        self._slider.setFocusPolicy(Qt.NoFocus)  # the card takes the keys
        self._slider.setStyleSheet("QSlider::groove:vertical { width: 14px; }"
                                   "QSlider::handle:vertical { height: 28px; margin: 0 -10px; }")
        self._slider.valueChanged.connect(self._on_speed)
        middle.addWidget(self._slider)
        readout = QVBoxLayout()
        readout.addStretch(1)
        self._speed = QLabel("0%")
        speed_font = QFont()
        speed_font.setPointSizeF(speed_font.pointSizeF() * 2.6)
        speed_font.setBold(True)
        self._speed.setFont(speed_font)
        self._speed.setAlignment(Qt.AlignCenter)
        readout.addWidget(self._speed)
        self._step = QLabel("step 0 of 126")
        self._step.setAlignment(Qt.AlignCenter)
        self._step.setStyleSheet("color: palette(placeholder-text);")
        readout.addWidget(self._step)
        readout.addStretch(1)
        middle.addLayout(readout, stretch=1)
        layout.addLayout(middle)

        directions = QHBoxLayout()
        self._reverse = QPushButton("◀  Reverse")
        self._forward = QPushButton("Forward  ▶")
        group = QButtonGroup(self)
        for button in (self._reverse, self._forward):
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setMinimumHeight(32)
            group.addButton(button)
            directions.addWidget(button)
        self._forward.setChecked(True)
        self._reverse.clicked.connect(lambda: self.set_direction(False))
        self._forward.clicked.connect(lambda: self.set_direction(True))
        layout.addLayout(directions)

        stops = QHBoxLayout()
        self._stop = QPushButton("Stop")
        self._stop.setToolTip("Slow to a stop, as the decoder's deceleration (CV4) allows (Space)")
        self._stop.clicked.connect(self.stop)
        self._estop = QPushButton("Emergency stop")
        self._estop.setToolTip("Stop at once, ignoring the deceleration (Esc)")
        self._estop.setStyleSheet(f"QPushButton {{ color: white; background-color: {RED}; font-weight: 600; "
                                  "padding: 6px; border-radius: 4px; } QPushButton:disabled { background-color: #d8a29b; }")
        self._estop.clicked.connect(self.emergency_stop)
        for button in (self._stop, self._estop):
            button.setFocusPolicy(Qt.NoFocus)
            button.setMinimumHeight(34)
            stops.addWidget(button)
        layout.addLayout(stops)

        functions_box = QWidget()
        grid = QGridLayout(functions_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._function_buttons: list[QPushButton] = []
        for number in range(FUNCTION_COUNT):
            button = QPushButton(f"F{number}")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setMinimumHeight(28)
            button.setStyleSheet(FUNCTION_ON)
            button.pressed.connect(lambda n=number: self._on_function_pressed(n))
            button.released.connect(lambda n=number: self._on_function_released(n))
            button.clicked.connect(lambda checked, n=number: self._on_function_clicked(n, checked))
            self._function_buttons.append(button)
            grid.addWidget(button, number // 3, number % 3)
        scroll = QScrollArea()
        scroll.setWidget(functions_box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll, stretch=1)

        self.fill_choices()
        self.refresh()

    # --- choosing the loco

    def fill_choices(self) -> None:
        self._choice.blockSignals(True)
        self._choice.clear()
        self._choice.addItem("Choose a loco…", None)
        for loco in self._panel.roster.roster.sorted():
            self._choice.addItem(loco.label, loco.id)
        self._choice.addItem("Other address…", OTHER)
        if self.loco_id is not None:
            index = self._choice.findData(self.loco_id)
        elif self.state is not None:
            index = self._choice.findData(OTHER)
        else:
            index = 0
        self._choice.setCurrentIndex(max(0, index))
        self._choice.blockSignals(False)
        self._other_row.setVisible(self._choice.currentData() == OTHER)

    def _on_choice(self) -> None:
        choice = self._choice.currentData()
        if choice == OTHER:
            self._other_row.show()
            if self.state is not None:
                self._address.setValue(self.state.address)
                self._long.setChecked(self.state.long)
            return
        self._other_row.hide()
        if choice is None:
            self.release()
            return
        loco = self._panel.roster.roster.get(choice)
        if loco is not None:
            self.take(loco.address, loco.long_address, loco.id)

    def _on_other_address(self) -> None:
        if decoder.should_be_long(self._address.value()):
            self._long.setChecked(True)
            self._long.setEnabled(False)
        else:
            self._long.setEnabled(True)

    def _use_address(self) -> None:
        address, long = self._address.value(), self._long.isChecked()
        loco = self._panel.roster.roster.find_by_address(address, long)
        self.take(address, long, loco.id if loco else None)

    def take(self, address: int, long: bool, loco_id: Optional[str]) -> None:
        """Drive this loco. Nothing is sent until the user does something,
        so a loco already running from the handset carries on as it was."""
        other = self._panel.card_for(address, long)
        if other is not None and other is not self:
            self._panel.say(f"Loco {decoder.address_text(address, long)} is already on another throttle")
            other.setFocus()
            self.fill_choices()
            return
        self.stop_if_moving()
        self.state = self._panel.control.state(address, long)
        self.loco_id = loco_id
        self.fill_choices()
        self.refresh()
        self.setFocus()
        self.loco_changed.emit()

    def release(self) -> None:
        self.stop_if_moving()
        self.state = None
        self.loco_id = None
        self.fill_choices()
        self.refresh()
        self.loco_changed.emit()

    @property
    def loco(self) -> Optional[Loco]:
        return self._panel.roster.roster.get(self.loco_id)

    # --- driving

    def _send_drive(self) -> None:
        if self.state is not None:
            self._panel.control.drive(self.state, source=self)

    def _on_speed(self, value: int) -> None:
        if self.state is None:
            return
        self.state.speed = value
        self.state.emergency = False
        self._send_drive()
        self._show_speed()

    def change_speed(self, delta: int) -> None:
        self._slider.setValue(self._slider.value() + delta)

    def set_direction(self, forward: bool) -> None:
        if self.state is None:
            return
        self.state.forward = forward
        self.state.emergency = False
        self._send_drive()
        self._show_direction()

    def stop(self) -> None:
        if self.state is None:
            return
        if self._slider.value() == 0:
            self._on_speed(0)  # send it anyway: the loco may have been running from the handset
        self._slider.setValue(0)

    def stop_if_moving(self) -> None:
        if self.state is not None and self.state.speed > 0 and self._panel.can_drive:
            self.stop()

    def emergency_stop(self) -> None:
        if self.state is None:
            return
        self._slider.blockSignals(True)
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self.state.speed = 0
        self.state.emergency = True
        self._send_drive()
        self._show_speed()

    def toggle_function(self, number: int) -> None:
        button = self._function_buttons[number]
        if button.isEnabled():
            button.click()

    def _on_function_clicked(self, number: int, checked: bool) -> None:
        if self.state is None or self._is_momentary(number):
            return
        self._set_function(number, checked)

    def _on_function_pressed(self, number: int) -> None:
        if self._is_momentary(number):
            self._set_function(number, True)

    def _on_function_released(self, number: int) -> None:
        if self._is_momentary(number):
            self._set_function(number, False)

    def _set_function(self, number: int, on: bool) -> None:
        if self.state is None:
            return
        self.state.functions[number] = on
        self._panel.control.functions(self.state, number, source=self)
        button = self._function_buttons[number]
        button.blockSignals(True)
        button.setChecked(on)
        button.blockSignals(False)

    def _is_momentary(self, number: int) -> bool:
        loco = self.loco
        return loco is not None and loco.is_momentary(number)

    # --- showing

    def refresh(self) -> None:
        state, loco = self.state, self.loco
        if state is None:
            self._name.setText("No loco")
            self._detail.setText("Choose a loco above")
        else:
            address = decoder.address_text(state.address, state.long)
            if loco is not None:
                self._name.setText(loco.name)
                extra = f" · {loco.road_number}" if loco.road_number else ""
                self._detail.setText(f"Address {address}{extra}")
            else:
                self._name.setText(f"Loco {address}")
                self._detail.setText("Not in the roster: its functions have no names")
        ready = state is not None and self._panel.can_drive
        for widget in (self._slider, self._reverse, self._forward, self._stop, self._estop):
            widget.setEnabled(ready)
        for number, button in enumerate(self._function_buttons):
            name = loco.function_name(number) if loco is not None else ("Lights" if number == 0 else "")
            momentary = self._is_momentary(number)
            button.setText(f"F{number} {name}".strip() if len(name) <= 9 else f"F{number} {name[:8]}…")
            tip = f"F{number}" + (f": {name}" if name else "") + (" — only while held" if momentary else "")
            button.setToolTip(tip + (f"  (key {number})" if number <= 9 else ""))
            button.setCheckable(not momentary)
            button.setEnabled(ready)
            button.blockSignals(True)
            button.setChecked(bool(state and state.functions[number]) and not momentary)
            button.blockSignals(False)
        self._slider.blockSignals(True)
        self._slider.setValue(state.speed if state else 0)
        self._slider.blockSignals(False)
        self._show_speed()
        self._show_direction()

    def _show_speed(self) -> None:
        speed = self.state.speed if self.state else 0
        if self.state is not None and self.state.emergency:
            self._speed.setText("STOP")
            self._speed.setStyleSheet(f"color: {RED};")
            self._step.setText("emergency stop")
            return
        self._speed.setStyleSheet("")
        self._speed.setText(f"{round(speed * 100 / MAX_SPEED)}%")
        self._step.setText(f"step {speed} of {MAX_SPEED}")

    def _show_direction(self) -> None:
        forward = self.state.forward if self.state else True
        self._forward.setChecked(forward)
        self._reverse.setChecked(not forward)
        for button, on in ((self._forward, forward), (self._reverse, not forward)):
            button.setStyleSheet(f"QPushButton:checked {{ background-color: {GREEN}; color: white; "
                                 "font-weight: 600; border-radius: 4px; }" if on else "")

    # --- keys

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.state is None or not self._panel.can_drive:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key_Up:
            self.change_speed(1 if event.isAutoRepeat() is False else 2)
        elif key == Qt.Key_Down:
            self.change_speed(-1 if event.isAutoRepeat() is False else -2)
        elif key == Qt.Key_PageUp:
            self.change_speed(BIG_STEP)
        elif key == Qt.Key_PageDown:
            self.change_speed(-BIG_STEP)
        elif key == Qt.Key_Left:
            self.set_direction(False)
        elif key == Qt.Key_Right:
            self.set_direction(True)
        elif key == Qt.Key_Space:
            self.stop()
        elif key == Qt.Key_Escape:
            self.emergency_stop()
        elif Qt.Key_0 <= key <= Qt.Key_9 and not event.isAutoRepeat():
            number = key - Qt.Key_0
            if self._is_momentary(number):
                self._set_function(number, True)
            else:
                self.toggle_function(number)
        else:
            return super().keyPressEvent(event)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if (self.state is not None and Qt.Key_0 <= key <= Qt.Key_9 and not event.isAutoRepeat()
                and self._is_momentary(key - Qt.Key_0)):
            self._set_function(key - Qt.Key_0, False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusInEvent(self, event) -> None:
        self.setStyleSheet("ThrottleCard { border: 2px solid palette(highlight); border-radius: 6px; }")
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.setStyleSheet("")
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        super().mousePressEvent(event)

    # --- saving the layout

    def setting(self) -> str:
        if self.loco_id is not None:
            return f"r:{self.loco_id}"
        if self.state is not None:
            return f"a:{self.state.address}:{'L' if self.state.long else 'S'}"
        return "-"


class ThrottlePanel(QWidget):
    def __init__(self, link: Link, store: SettingsStore, roster: RosterStore, control: LocoControl,
                 parent=None):
        super().__init__(parent)
        self.link = link
        self.control = control
        self.roster = roster
        self._store = store
        self._cards: list[ThrottleCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 10)
        bar = QHBoxLayout()
        self._add = QPushButton("Add throttle")
        self._add.clicked.connect(lambda: self.add_card(focus=True))
        bar.addWidget(self._add)
        self._status = QLabel()
        self._status.setStyleSheet("color: palette(placeholder-text);")
        bar.addWidget(self._status, stretch=1)
        self._stop_all = QPushButton("Stop all")
        self._stop_all.setToolTip("Emergency stop every loco on these throttles")
        self._stop_all.setStyleSheet(f"QPushButton {{ color: white; background-color: {RED}; font-weight: 700; "
                                     "padding: 6px 18px; border-radius: 4px; }"
                                     "QPushButton:disabled { background-color: #d8a29b; }")
        self._stop_all.clicked.connect(self.stop_all)
        bar.addWidget(self._stop_all)
        layout.addLayout(bar)

        self._extras = QHBoxLayout()  # e.g. the phones strip
        layout.addLayout(self._extras)

        self._row = QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.addStretch(1)
        holder = QWidget()
        holder.setLayout(self._row)
        scroll = _SideScroll()
        scroll.setWidget(holder)
        layout.addWidget(scroll, stretch=1)

        hint = QLabel("Click a throttle, then: ↑ ↓ speed · ← → direction · Space stop · Esc emergency stop · "
                      "0–9 functions F0–F9")
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(hint)

        link.connected_changed.connect(lambda _: self._refresh_all())
        link.programming_track_changed.connect(lambda _: self._refresh_all())
        link.programming_track_starting.connect(self._before_programming_track)
        link.about_to_disconnect.connect(self.stop_moving)
        link.throttle_message.connect(self.say)
        roster.changed.connect(self._on_roster_changed)
        control.changed.connect(self._on_loco_changed)

        self._restore_layout()
        self._refresh_all()

    def add_strip(self, widget: QWidget) -> None:
        """Put a widget in a row under the throttles' toolbar."""
        self._extras.addWidget(widget)

    @property
    def can_drive(self) -> bool:
        return self.control.can_drive

    def _on_loco_changed(self, key, source) -> None:
        """Someone else (a phone, say) changed a loco one of these throttles has."""
        for card in self._cards:
            if card is not source and card.state is not None and card.state.key == key:
                card.refresh()

    @property
    def cards(self) -> list[ThrottleCard]:
        return list(self._cards)

    def say(self, text: str) -> None:
        self._status.setText(text)

    def card_for(self, address: int, long: bool) -> Optional[ThrottleCard]:
        return next((card for card in self._cards if card.state is not None
                     and card.state.key == (address, long)), None)

    def add_card(self, focus: bool = False) -> Optional[ThrottleCard]:
        if len(self._cards) >= MAX_THROTTLES:
            return None
        card = ThrottleCard(self)
        card.close_requested.connect(self._close_card)
        card.loco_changed.connect(self._save_layout)
        self._cards.append(card)
        self._row.insertWidget(self._row.count() - 1, card)
        self._add.setEnabled(len(self._cards) < MAX_THROTTLES)
        if focus:
            card.setFocus()
            self._save_layout()
        return card

    def drive(self, loco: Loco) -> None:
        """Put a roster loco on a throttle (one already driving it, an empty one, or a new one)."""
        card = self.card_for(loco.address, loco.long_address)
        if card is None:
            card = next((c for c in self._cards if c.state is None), None) or self.add_card()
        if card is None:
            self.say(f"All {MAX_THROTTLES} throttles are in use — close one first")
            return
        if card.state is None:
            card.take(loco.address, loco.long_address, loco.id)
        card.setFocus()

    def _close_card(self, card: ThrottleCard) -> None:
        card.stop_if_moving()
        self._cards.remove(card)
        card.deleteLater()
        self._add.setEnabled(True)
        self._save_layout()

    def stop_all(self) -> None:
        """Emergency-stop every loco being driven: here, and from phones."""
        if self.control.emergency_stop_all():
            self.say("Emergency stop: every loco on these throttles and the phones")
        for card in self._cards:
            card.refresh()

    def stop_moving(self) -> None:
        """Bring moving locos to a stop (on disconnect, or quitting) — phones' too."""
        self.control.stop_moving()
        for card in self._cards:
            card.refresh()

    def _before_programming_track(self) -> None:
        moving = self.control.moving()
        self.stop_moving()
        if moving:
            self.say("Stopped the locos: the programming track is in use")

    def _refresh_all(self) -> None:
        if not self.link.connected:
            self.say("Connect to your NCE USB interface (above) to drive.")
        elif self.link.programming_track_busy:
            self.say("The programming track is in use — the throttles are paused.")
        elif self._status.text().startswith(("Connect to", "The programming track")):
            self.say("")
        self._stop_all.setEnabled(self.can_drive)
        for card in self._cards:
            card.refresh()

    def _on_roster_changed(self) -> None:
        for card in self._cards:
            if card.loco_id is not None and card.loco is None:
                card.loco_id = None  # deleted from the roster: keep driving it by address
            elif card.loco is not None and card.state is not None:
                loco = card.loco
                if card.state.key != (loco.address, loco.long_address):
                    card.state = self.control.state(loco.address, loco.long_address)
            card.fill_choices()
            card.refresh()
        self._save_layout()

    def _save_layout(self) -> None:
        self._store.update(throttles=";".join(card.setting() for card in self._cards) or "-")

    def _restore_layout(self) -> None:
        for entry in (self._store.settings.throttles or "-").split(";")[:MAX_THROTTLES]:
            card = self.add_card()
            if entry.startswith("r:"):
                loco = self.roster.roster.get(entry[2:])
                if loco is not None:
                    card.state = self.control.state(loco.address, loco.long_address)
                    card.loco_id = loco.id
            elif entry.startswith("a:"):
                try:
                    _, address, kind = entry.split(":")
                    card.state = self.control.state(int(address), kind == "L")
                except ValueError:
                    pass
            card.fill_choices()
        if not self._cards:
            self.add_card()

    def shutdown(self) -> None:
        self.stop_moving()
