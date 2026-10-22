"""The decoder programmer: read and write a loco's CVs on the programming
track (or write them on the main), with pages for the things you change
most — the address, the CV29 options, and the speed and motor settings —
and a table of every CV."""
from __future__ import annotations

import html
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QInputDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from simple_train.core import decoder, nce
from simple_train.core.roster import Loco
from simple_train.core.settings import SettingsStore
from simple_train.gui.address_spin import AddressSpin
from simple_train.gui.link import ERROR, GOOD, INFO, Link
from simple_train.gui.roster_store import RosterStore

LOG_COLOURS = {INFO: None, GOOD: "#2e9e4f", ERROR: "#c0392b"}
PENDING = QColor(255, 200, 60, 90)
DIFFERENT = QColor(90, 160, 255, 70)  # differs from the copy saved in the roster

MODE_TIPS = {
    nce.DIRECT: "Reads and writes each CV directly. The quickest, and what every modern decoder uses.",
    nce.PAGED: "Reaches CVs through a page register. Slower, but some older decoders (and some sound "
               "decoders on a Power Cab) only answer this way.",
    nce.REGISTER: "The oldest method, from the first DCC decoders: only CVs 1–4, 7, 8 and 29.",
    nce.MAIN: "Programs a loco out on the layout by its address, without moving it to the programming "
              "track. NCE can write this way but not read.",
}

# The speed and motor page: (CV, label, what it does)
SPEED_CVS = [
    (2, "Start voltage", "How much power the motor gets at speed step 1 — raise it if the loco won't creep away"),
    (6, "Mid voltage", "Power at half speed (0 = a straight line from start to top)"),
    (5, "Top voltage", "Power at full speed — lower it for a realistic top speed (0 = full)"),
    (3, "Acceleration", "How slowly the loco speeds up (0 = at once; bigger = longer)"),
    (4, "Deceleration", "How slowly the loco slows down (0 = at once; bigger = longer)"),
]
TABLE_LAST_CV = 106  # the table always lists the named CVs up to here


def _spin(low: int, high: int, value: int = 0) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setValue(value)
    spin.setMinimumWidth(80)
    return spin


class ProgrammerPanel(QWidget):
    def __init__(self, link: Link, store: SettingsStore, roster: RosterStore, parent=None):
        super().__init__(parent)
        self._link = link
        self._store = store
        self._roster = roster
        self._loco_id: Optional[str] = None  # the roster loco on the programming track, if known
        self._values: dict[int, int] = {}  # what we know of this decoder's CVs
        self._pending: dict[int, int] = {}  # CV table edits not yet written
        self._filling_table = False
        self._action_buttons: list[QPushButton] = []
        self._read_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.addWidget(self._build_loco_row())
        layout.addWidget(self._build_mode_row())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_decoder_page(), "Decoder")
        self._tabs.addTab(self._build_options_page(), "Options (CV29)")
        self._tabs.addTab(self._build_speed_page(), "Speed && motor")
        self._tabs.addTab(self._build_table_page(), "All CVs")
        layout.addWidget(self._tabs, stretch=1)

        progress_row = QHBoxLayout()
        self._progress = QLabel()
        self._progress.setStyleSheet("font-weight: 600;")
        progress_row.addWidget(self._progress, stretch=1)
        self._stop = QPushButton("Stop")
        self._stop.clicked.connect(link.stop_job)
        self._stop.hide()
        progress_row.addWidget(self._stop)
        layout.addLayout(progress_row)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFixedHeight(130)
        layout.addWidget(self._log_view)

        link.connected_changed.connect(lambda _: self._update_enabled())
        link.busy_changed.connect(self._on_busy)
        link.progress_changed.connect(self._progress.setText)
        link.message.connect(self.log)
        link.command_station_changed.connect(lambda _: self._apply_command_station())
        roster.changed.connect(self._fill_loco_combo)

        self._fill_loco_combo()

        self._apply_command_station()
        self._refresh()
        self._update_enabled()

    # --- building

    def _build_loco_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 4)
        row.addWidget(QLabel("Loco"))
        self._loco_combo = QComboBox()
        self._loco_combo.setMinimumWidth(260)
        self._loco_combo.setToolTip("Which loco from your roster this is. Read decoder picks it by address.")
        self._loco_combo.currentIndexChanged.connect(self._on_loco_chosen)
        row.addWidget(self._loco_combo)
        self._save_loco = QPushButton("Save to roster…")
        self._save_loco.setToolTip("Keep a copy of every CV read or written so far with this loco in the roster")
        self._save_loco.clicked.connect(self._save_to_roster)
        row.addWidget(self._save_loco)
        self._restore_loco = self._action("Write saved CVs to decoder…", lambda: self.restore(self.loco))
        row.addWidget(self._restore_loco)
        self._loco_info = QLabel()
        self._loco_info.setStyleSheet("color: palette(placeholder-text);")
        row.addWidget(self._loco_info)
        row.addStretch(1)
        return box

    def _build_mode_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Program"))
        self._mode = QComboBox()
        for mode in nce.MODES:
            label = nce.MODE_NAMES[mode]
            self._mode.addItem(label if mode == nce.MAIN else f"On the programming track — {label.lower()}", mode)
            self._mode.setItemData(self._mode.count() - 1, MODE_TIPS[mode], Qt.ToolTipRole)
        self._mode.setCurrentIndex(max(0, self._mode.findData(self._store.settings.programming_mode)))
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        row.addWidget(self._mode)

        self._main_label = QLabel("Loco address")
        row.addWidget(self._main_label)
        self._main_address = AddressSpin(self._store.settings.main_address)
        self._main_address.valueChanged.connect(self._on_main_address)
        row.addWidget(self._main_address)
        self._main_long = QCheckBox("Long")
        self._main_long.toggled.connect(self._main_address.set_long)
        self._main_long.setToolTip("Addresses over 127 are always long; tick this for a long address of 127 or less")
        row.addWidget(self._main_long)

        self._verify = QCheckBox("Check each write by reading it back")
        self._verify.setChecked(self._store.settings.verify_writes)
        self._verify.toggled.connect(lambda on: self._store.update(verify_writes=on))
        row.addWidget(self._verify)
        row.addStretch(1)
        self._mode_hint = QLabel()
        self._mode_hint.setStyleSheet("color: palette(placeholder-text);")
        row.addWidget(self._mode_hint)
        self._on_main_address()
        return box

    def _action(self, text: str, slot, reads: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        self._action_buttons.append(button)
        if reads:
            self._read_buttons.append(button)
        return button

    def _build_decoder_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        left = QVBoxLayout()
        read = self._action("Read decoder", self._read_decoder, reads=True)
        read.setMinimumHeight(36)
        left.addWidget(read)
        facts = QGroupBox("This decoder")
        form = QFormLayout(facts)
        self._facts = {}
        for key, label in (("manufacturer", "Made by"), ("version", "Version (CV7)"), ("address", "Answers to"),
                           ("short", "Short address (CV1)"), ("long", "Long address (CV17/18)"),
                           ("steps", "Speed steps"), ("direction", "Direction"), ("dc", "Runs on DC")):
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if key == "address":
                font = value.font()
                font.setPointSizeF(font.pointSizeF() * 1.6)
                font.setBold(True)
                value.setFont(font)
            self._facts[key] = value
            form.addRow(label, value)
        left.addWidget(facts)
        left.addStretch(1)
        layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        change = QGroupBox("Change the address")
        grid = QGridLayout(change)
        grid.addWidget(QLabel("New address"), 0, 0)
        self._new_address = AddressSpin(3)
        self._new_address.valueChanged.connect(self._on_new_address)
        grid.addWidget(self._new_address, 0, 1)
        self._new_long = QCheckBox("Long address")
        self._new_long.toggled.connect(self._new_address.set_long)
        self._new_long.setToolTip("1–127 can be short or long; 128 and up are always long")
        grid.addWidget(self._new_long, 0, 2)
        explain = QLabel("Short addresses are 1–127 (CV1). Long addresses go up to 10239 (CV17 and CV18), "
                         "often the loco's running number. CV29 is updated to match, keeping its other options.")
        explain.setWordWrap(True)
        explain.setStyleSheet("color: palette(placeholder-text);")
        grid.addWidget(explain, 1, 0, 1, 3)
        grid.addWidget(self._action("Write address", self._write_address), 2, 0, 1, 3)
        right.addWidget(change)

        reset = QGroupBox("Factory reset")
        reset_layout = QVBoxLayout(reset)
        note = QLabel("Puts every CV back as it came from the factory (writes 8 to CV8, which most decoders "
                      "understand). The address goes back to 3.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        reset_layout.addWidget(note)
        reset_layout.addWidget(self._action("Reset decoder…", self._reset_decoder))
        right.addWidget(reset)
        right.addStretch(1)
        layout.addLayout(right, stretch=1)
        self._on_new_address()
        return page

    def _build_options_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._opt_reversed = QCheckBox("Swap forward and reverse (for a loco that runs the wrong way)")
        steps_row = QHBoxLayout()
        steps_row.addWidget(QLabel("Speed steps"))
        self._opt_steps = QComboBox()
        self._opt_steps.addItem("28 or 128 (usual)", True)
        self._opt_steps.addItem("14 (very old decoders)", False)
        steps_row.addWidget(self._opt_steps)
        steps_row.addStretch(1)
        self._opt_analogue = QCheckBox("Allow running on DC (analogue) layouts")
        self._opt_railcom = QCheckBox("RailCom on (sends information back to RailCom detectors)")
        self._opt_table = QCheckBox("Use the speed table (CV67–94) instead of start/mid/top voltage")
        self._opt_long = QCheckBox("Use the long address (CV17/18) instead of the short one (CV1)")
        for widget in (self._opt_reversed,):
            layout.addWidget(widget)
        layout.addLayout(steps_row)
        for widget in (self._opt_analogue, self._opt_railcom, self._opt_table, self._opt_long):
            layout.addWidget(widget)
        for box in (self._opt_reversed, self._opt_analogue, self._opt_railcom, self._opt_table, self._opt_long):
            box.toggled.connect(self._show_cv29)
        self._opt_steps.currentIndexChanged.connect(self._show_cv29)
        self._cv29_label = QLabel()
        self._cv29_label.setStyleSheet("font-family: monospace;")
        layout.addWidget(self._cv29_label)
        self._cv29_other = 0
        buttons = QHBoxLayout()
        buttons.addWidget(self._action("Read CV29", lambda: self._read([29]), reads=True))
        buttons.addWidget(self._action("Write CV29", lambda: self._write([(29, self._config().cv29())])))
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _build_speed_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        grid = QGridLayout()
        self._speed_spins: dict[int, QSpinBox] = {}
        for row, (cv, label, help_text) in enumerate(SPEED_CVS):
            grid.addWidget(QLabel(f"<b>{label}</b> (CV{cv})"), row, 0)
            spin = _spin(0, 255)
            self._speed_spins[cv] = spin
            grid.addWidget(spin, row, 1)
            help_label = QLabel(help_text)
            help_label.setStyleSheet("color: palette(placeholder-text);")
            grid.addWidget(help_label, row, 2)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        note = QLabel("Acceleration and deceleration: the time to go from stop to full speed is roughly "
                      "the value × 0.9 seconds ÷ the number of speed steps used — try 5–20 to start with.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addWidget(self._action("Read all", lambda: self._read([cv for cv, *_ in SPEED_CVS]), reads=True))
        buttons.addWidget(self._action(
            "Write all", lambda: self._write([(cv, self._speed_spins[cv].value()) for cv, *_ in SPEED_CVS])))
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _build_table_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        single = QHBoxLayout()
        single.addWidget(QLabel("CV"))
        self._one_cv = _spin(1, nce.MAX_CV, 1)
        single.addWidget(self._one_cv)
        single.addWidget(QLabel("Value"))
        self._one_value = _spin(0, 255)
        single.addWidget(self._one_value)
        single.addWidget(self._action("Read", lambda: self._read([self._one_cv.value()]), reads=True))
        single.addWidget(self._action("Write", lambda: self._write([(self._one_cv.value(), self._one_value.value())])))
        single.addSpacing(24)
        single.addWidget(QLabel("Read CVs"))
        self._range_from = _spin(1, nce.MAX_CV, 1)
        self._range_to = _spin(1, nce.MAX_CV, 30)
        single.addWidget(self._range_from)
        single.addWidget(QLabel("to"))
        single.addWidget(self._range_to)
        single.addWidget(self._action("Read range", self._read_range, reads=True))
        single.addStretch(1)
        layout.addLayout(single)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["CV", "What it is", "Value", "Hex", "Bits", "Saved"])
        self._table.verticalHeader().hide()
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._table.itemChanged.connect(self._on_table_edit)
        self._table.currentCellChanged.connect(self._on_table_row)
        layout.addWidget(self._table, stretch=1)

        bottom = QHBoxLayout()
        hint = QLabel("Double-click a value to change it, then write the changes.")
        hint.setStyleSheet("color: palette(placeholder-text);")
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self._write_changes = self._action("Write changes", self._write_pending)
        bottom.addWidget(self._write_changes)
        forget = QPushButton("Forget changes")
        forget.clicked.connect(self._forget_pending)
        bottom.addWidget(forget)
        layout.addLayout(bottom)
        return page

    # --- state

    @property
    def mode(self) -> str:
        return self._mode.currentData()

    def _main_target(self) -> tuple[int, Optional[bool]]:
        return self._main_address.value(), self._main_long.isChecked()

    def _apply_command_station(self) -> None:
        """Through USB, an SB3/SB5/Power Pro can only program on the main."""
        track = nce.has_programming_track(self._link.command_station)
        model = self._mode.model()
        for row in range(self._mode.count()):
            if self._mode.itemData(row) != nce.MAIN:
                item = model.item(row)
                item.setEnabled(track)
        if not track and self.mode != nce.MAIN:
            self._mode.setCurrentIndex(self._mode.findData(nce.MAIN))
        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        mode = self.mode
        self._store.update(programming_mode=mode)
        main = mode == nce.MAIN
        for widget in (self._main_label, self._main_address, self._main_long):
            widget.setVisible(main)
        self._verify.setVisible(not main)
        if main and not nce.has_programming_track(self._link.command_station):
            name = nce.COMMAND_STATIONS[self._link.command_station]
            self._mode_hint.setText(f"Through USB a {name} can only program on the main, and can't read CVs")
        elif main:
            self._mode_hint.setText("Writes only: NCE can't read CVs back on the main")
        elif mode == nce.REGISTER:
            self._mode_hint.setText("For old decoders: only CVs 1–4, 7, 8 and 29")
        else:
            self._mode_hint.setText("Put the loco on the programming track")
        self._update_enabled()

    def _on_main_address(self) -> None:
        address = self._main_address.value()
        self._store.update(main_address=address)
        if decoder.should_be_long(address):
            self._main_long.setChecked(True)
            self._main_long.setEnabled(False)
        else:
            self._main_long.setEnabled(True)

    def _on_new_address(self) -> None:
        if decoder.should_be_long(self._new_address.value()):
            self._new_long.setChecked(True)
            self._new_long.setEnabled(False)
        else:
            self._new_long.setEnabled(True)

    def _on_busy(self, busy: bool) -> None:
        self._stop.setVisible(busy and self._link.connected)
        self._update_enabled()

    def _update_enabled(self) -> None:
        ready = self._link.connected and not self._link.busy
        readable = nce.can_read(self.mode)
        for button in self._action_buttons:
            button.setEnabled(ready and (readable or button not in self._read_buttons))
            if button in self._read_buttons:
                button.setToolTip("" if readable else "NCE can only read CVs on the programming track")
        self._write_changes.setEnabled(ready and bool(self._pending))
        loco = self.loco
        self._restore_loco.setEnabled(ready and loco is not None and bool(loco.cvs))
        self._mode.setEnabled(not self._link.busy)
        if not self._link.connected and not self._link.busy:
            self._progress.setText("Connect to your NCE USB interface (above) to start programming.")
        elif ready:
            self._progress.setText("")

    def log(self, text: str, level: str = INFO) -> None:
        colour = LOG_COLOURS.get(level)
        stamp = time.strftime("%H:%M:%S")
        body = html.escape(text)
        if colour:
            body = f"<span style='color:{colour}'>{body}</span>"
        self._log_view.append(f"<span style='color:gray'>{stamp}</span>&nbsp; {body}")

    # --- jobs

    def _read(self, cvs: list[int], keep_going: bool = False, then=None) -> None:
        mode = self.mode

        def done(results):
            found = {cv: value for cv, value in results.items() if isinstance(value, int)}
            missing = [cv for cv, value in results.items() if not isinstance(value, int)]
            self._learn(found)
            if found:
                self.log(", ".join(f"CV{cv} = {value}" for cv, value in found.items()), GOOD)
            if missing:
                self.log(f"No answer for CV {', '.join(map(str, missing))} (not used by this decoder?)", INFO)
            if then is not None:
                then()

        self._link.run_job(lambda programmer, progress: programmer.read_cvs(cvs, mode, progress, keep_going), done)

    def _write(self, writes: list[tuple[int, int]], then=None) -> None:
        mode = self.mode
        address, long = self._main_target()
        verify = self._verify.isChecked()

        def done(_):
            self._learn(dict(writes))
            checked = " and checked" if verify and nce.can_read(mode) else ""
            where = f" on loco {decoder.address_text(address, bool(long) or address > 127)}" if mode == nce.MAIN else ""
            self.log(f"Wrote{checked}{where}: " + ", ".join(f"CV{cv} = {value}" for cv, value in writes), GOOD)
            if then is not None:
                then()

        self._link.run_job(
            lambda programmer, progress: programmer.write_cvs(writes, mode, address, long, verify, progress), done)

    def _read_decoder(self) -> None:
        mode = self.mode

        def done(info: decoder.DecoderInfo):
            self._values.clear()
            self._pending.clear()
            learnt = {1: info.cv1, 7: info.cv7, 8: info.cv8, 29: info.cv29}
            if info.cv17 is not None and info.cv18 is not None:
                learnt.update({17: info.cv17, 18: info.cv18})
            self._learn(learnt)
            address, long = info.address
            raw = ", ".join(f"CV{cv} = {value}" for cv, value in sorted(learnt.items()))
            if address is None:
                self.log(f"Found a decoder made by {info.manufacturer} (version {info.cv7}). CV29 says it uses "
                         "a long address, but CV17/18 didn't read back — try paged mode", ERROR)
                self.log(raw, INFO)
                return
            self._new_address.setValue(address)
            self._new_long.setChecked(long)
            self._match_loco(address, long)
            self._main_address.setValue(address)  # ready for programming it on the main too
            self._main_long.setChecked(long)
            self.log(f"Found a decoder made by {info.manufacturer} (version {info.cv7}), on "
                     f"{'long' if long else 'short'} address {decoder.address_text(address, long)}", GOOD)
            self.log(raw, INFO)

        self._link.run_job(lambda programmer, progress: programmer.identify(mode, progress), done)

    def _write_address(self) -> None:
        address = self._new_address.value()
        long = self._new_long.isChecked()
        mode = self.mode
        verify = self._verify.isChecked()
        if mode == nce.MAIN:
            # Can't read CV29 on the main, so its other options come from the Options page.
            cv29 = self._config().cv29()
            old = self._main_address.text()
            answer = QMessageBox.question(
                self, "Change address on the main",
                f"Give loco {old} the new address {decoder.address_text(address, long)}?\n\nCV29 will be written as {cv29} — check the "
                "Options (CV29) page shows this loco's settings first, as NCE can't read them on the main.")
            if answer != QMessageBox.Yes:
                return
            writes = decoder.address_writes(address, long, cv29)
            main_address, main_long = self._main_target()

            def job(programmer, progress):
                programmer.write_cvs(writes, mode, main_address, main_long, False, progress)
        else:
            def job(programmer, progress):
                # CV29 is read fresh, so its other options are kept exactly as they are.
                cv29 = programmer.read_cvs([29], mode, progress)[29]
                writes = decoder.address_writes(address, long, cv29)
                programmer.write_cvs(writes, mode, verify=verify, progress=progress)
                return writes

        def done(writes):
            writes = writes or decoder.address_writes(address, long, self._config().cv29())
            self._learn(dict(writes))
            self.log(f"The loco now answers to {'long' if long else 'short'} address "
                     f"{decoder.address_text(address, long)}", GOOD)
            if mode == nce.MAIN:
                self._main_address.setValue(address)
                self._main_long.setChecked(long)

        if mode == nce.REGISTER and long:
            self.log("Register mode can't reach CV17/18 — use direct or paged mode for a long address", ERROR)
            return
        self._link.run_job(job, done)

    def _reset_decoder(self) -> None:
        answer = QMessageBox.warning(
            self, "Reset decoder",
            "Reset this decoder to its factory settings?\n\nEvery CV you've changed (address, speeds, "
            "sounds, function mapping…) goes back to how it came.",
            QMessageBox.Reset | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Reset:
            return
        mode = self.mode
        address, long = self._main_target()

        def done(_):
            self._values.clear()
            self._pending.clear()
            self._refresh()
            self.log("Decoder reset to factory settings — read it again to see its CVs", GOOD)

        # A reset can't be checked by reading CV8 back: it reads as the manufacturer ID.
        self._link.run_job(lambda programmer, progress: programmer.write_cvs([(8, 8)], mode, address, long,
                                                                             False, progress), done)

    # --- the roster

    @property
    def loco(self) -> Optional[Loco]:
        return self._roster.roster.get(self._loco_id)

    def link_loco(self, loco_id: Optional[str]) -> None:
        """Say which roster loco is on the track (e.g. "Open in programmer")."""
        self._loco_id = loco_id if self._roster.roster.get(loco_id) else None
        loco = self.loco
        if loco is not None:
            self._main_address.setValue(loco.address)
            self._main_long.setChecked(loco.long_address)
        self._fill_loco_combo()
        self._refresh()

    def _match_loco(self, address: int, long: bool) -> None:
        loco = self._roster.roster.find_by_address(address, long)
        previous = self._loco_id
        self._loco_id = loco.id if loco else None
        self._fill_loco_combo()
        if loco is not None and loco.id != previous:
            self.log(f"This is {loco.name} from your roster", INFO)

    def _fill_loco_combo(self) -> None:
        if self._roster.roster.get(self._loco_id) is None:
            self._loco_id = None
        self._loco_combo.blockSignals(True)
        self._loco_combo.clear()
        self._loco_combo.addItem("Not in the roster", None)
        for loco in self._roster.roster.sorted():
            self._loco_combo.addItem(loco.label, loco.id)
        self._loco_combo.setCurrentIndex(max(0, self._loco_combo.findData(self._loco_id)))
        self._loco_combo.blockSignals(False)
        self._show_loco_info()

    def _on_loco_chosen(self) -> None:
        self.link_loco(self._loco_combo.currentData())

    def _show_loco_info(self) -> None:
        loco = self.loco
        if loco is None:
            self._loco_info.setText("")
            self._save_loco.setText("Save to roster…")
        else:
            saved = f"{len(loco.cvs)} CVs saved {loco.cvs_saved_at}" if loco.cvs else "no CVs saved yet"
            self._loco_info.setText(saved)
            self._save_loco.setText("Save CVs to roster")
        self._update_enabled()

    def _save_to_roster(self) -> None:
        if not self._values:
            self.log("Nothing to save yet — read the decoder (or some CVs) first", ERROR)
            return
        loco = self.loco
        if loco is None:
            address, long = decoder.active_address(self._values.get(1, 3), self._values.get(17),
                                                   self._values.get(18), self._values.get(29, 0))
            if address is None:
                address, long = self._main_address.value(), self._main_long.isChecked()
            suggestion = f"Loco {address:04d}" if long else f"Loco {address}"
            name, ok = QInputDialog.getText(self, "Add to roster", "Name for this loco:", text=suggestion)
            if not ok or not name.strip():
                return
            loco = Loco(name=name.strip(), address=address, long_address=long)
            loco.take_cvs(self._values)
            self._roster.add(loco)
            self._loco_id = loco.id
            self._fill_loco_combo()
            self.log(f"Added {loco.name} to the roster with {len(self._values)} CVs", GOOD)
        else:
            loco.take_cvs(self._values)
            self._roster.save()
            self.log(f"Saved {len(self._values)} CVs to {loco.name} in the roster", GOOD)
        if len(loco.cvs) < 20:
            self.log("Tip: for a full backup, read CVs 1 to 106 on the All CVs page, then save again", INFO)
        self._refresh()

    def restore(self, loco: Optional[Loco]) -> None:
        """Write a roster loco's saved CVs back to the decoder."""
        if loco is None or not self._link.connected or self._link.busy:
            return
        writes = loco.restore_writes()
        if not writes:
            self.log(f"{loco.name} has no saved CVs to write", ERROR)
            return
        if self.mode == nce.MAIN:
            target = f"loco {self._main_address.text()} on the main"
        else:
            target = "the decoder on the programming track"
        answer = QMessageBox.question(
            self, "Write saved CVs",
            f"Write {len(writes)} saved CVs from {loco.name} to {target}?\n\n"
            "This replaces what's on the decoder now. Do it after a reset or a decoder swap, "
            "or to undo changes.")
        if answer != QMessageBox.Yes:
            return
        self._loco_id = loco.id
        self._fill_loco_combo()
        self._write(writes)

    def _read_range(self) -> None:
        low, high = sorted((self._range_from.value(), self._range_to.value()))
        self._tabs.setCurrentIndex(3)
        self._read(list(range(low, high + 1)), keep_going=True)

    def _write_pending(self) -> None:
        writes = sorted(self._pending.items())
        if not writes:
            return

        def then():
            self._pending.clear()
            self._refresh()

        self._write(writes, then)

    def _forget_pending(self) -> None:
        self._pending.clear()
        self._refresh()
        self._update_enabled()

    # --- showing what we know

    def _learn(self, values: dict[int, int]) -> None:
        self._values.update(values)
        for cv in values:
            self._pending.pop(cv, None)
        self._refresh()
        self._update_enabled()

    def _config(self) -> decoder.Config:
        return decoder.Config(
            reversed=self._opt_reversed.isChecked(),
            speed_steps_28=bool(self._opt_steps.currentData()),
            analogue=self._opt_analogue.isChecked(),
            railcom=self._opt_railcom.isChecked(),
            speed_table=self._opt_table.isChecked(),
            long_address=self._opt_long.isChecked(),
            other_bits=self._cv29_other,
        )

    def _show_cv29(self) -> None:
        value = self._config().cv29()
        known = self._values.get(29)
        state = "" if known is None else (" — as on the decoder" if known == value else
                                          f" — the decoder has {known}: write to change it")
        self._cv29_label.setText(f"CV29 = {value}  (0x{value:02X}, bits {value:08b}){state}")

    def _refresh(self) -> None:
        values = self._values
        # Decoder page
        if 8 in values:
            self._facts["manufacturer"].setText(decoder.manufacturer_name(values[8]))
        else:
            self._facts["manufacturer"].setText("—")
        self._facts["version"].setText(str(values[7]) if 7 in values else "—")
        self._facts["short"].setText(str(values[1]) if 1 in values else "—")
        if 17 in values and 18 in values:
            unused = 29 in values and not values[29] & decoder.LONG_ADDRESS
            self._facts["long"].setText(f"{decoder.address_text(decoder.long_address_from(values[17], values[18]), True)}"
                                        f"{'  (not in use)' if unused else ''}")
        else:
            self._facts["long"].setText("—")
        if 29 in values and 1 in values:
            address, long = decoder.active_address(values[1], values.get(17), values.get(18), values[29])
            if address is None:
                self._facts["address"].setText("long — couldn't read CV17/18")
            else:
                self._facts["address"].setText(f"{decoder.address_text(address, long)}  ({'long' if long else 'short'})")
        else:
            self._facts["address"].setText("—")
        if 29 in values:
            config = decoder.Config.from_cv29(values[29])
            self._facts["steps"].setText("28 / 128" if config.speed_steps_28 else "14")
            self._facts["direction"].setText("Swapped" if config.reversed else "Normal")
            self._facts["dc"].setText("Yes" if config.analogue else "No")
            self._set_options(config)
        else:
            for key in ("steps", "direction", "dc"):
                self._facts[key].setText("—")
        # Speed page
        for cv, spin in self._speed_spins.items():
            if cv in values:
                spin.setValue(values[cv])
        # CV table
        if self._one_cv.value() in values:
            self._one_value.setValue(values[self._one_cv.value()])
        self._fill_table()
        self._show_cv29()

    def _set_options(self, config: decoder.Config) -> None:
        widgets = (self._opt_reversed, self._opt_analogue, self._opt_railcom, self._opt_table, self._opt_long,
                   self._opt_steps)
        for widget in widgets:
            widget.blockSignals(True)
        self._opt_reversed.setChecked(config.reversed)
        self._opt_steps.setCurrentIndex(0 if config.speed_steps_28 else 1)
        self._opt_analogue.setChecked(config.analogue)
        self._opt_railcom.setChecked(config.railcom)
        self._opt_table.setChecked(config.speed_table)
        self._opt_long.setChecked(config.long_address)
        self._cv29_other = config.other_bits
        for widget in widgets:
            widget.blockSignals(False)

    def _fill_table(self) -> None:
        loco = self.loco
        saved = loco.cvs if loco is not None else {}
        cvs = sorted(set(cv for cv in decoder.CV_NAMES if cv <= TABLE_LAST_CV) | set(self._values)
                     | set(self._pending) | set(saved))
        self._table.setColumnHidden(5, loco is None)
        self._filling_table = True
        self._table.setRowCount(len(cvs))
        bold = QFont()
        bold.setBold(True)
        for row, cv in enumerate(cvs):
            value = self._pending.get(cv, self._values.get(cv))
            cells = [str(cv), decoder.cv_name(cv), "" if value is None else str(value)]
            cells += list(decoder.format_value(value)) if value is not None else ["", ""]
            cells.append(str(saved[cv]) if cv in saved else "")
            differs = cv in saved and value is not None and saved[cv] != value
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, cv)
                if column == 2:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column in (0, 2, 3, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if column == 4 or column == 3:
                    item.setFont(QFont("monospace"))
                if cv in self._pending:
                    item.setBackground(QBrush(PENDING))
                elif differs:
                    item.setBackground(QBrush(DIFFERENT))
                    item.setToolTip(f"The roster has {saved[cv]} for this CV")
                    if column == 2:
                        item.setFont(bold)
                self._table.setItem(row, column, item)
        self._filling_table = False

    def _on_table_edit(self, item: QTableWidgetItem) -> None:
        if self._filling_table or item.column() != 2:
            return
        cv = item.data(Qt.UserRole)
        text = item.text().strip()
        try:
            value = int(text, 0)
        except ValueError:
            value = -1
        if not 0 <= value <= 255:
            if text:
                self.log(f"CV{cv}: “{text}” isn't a value from 0 to 255", ERROR)
            self._pending.pop(cv, None)
        elif value == self._values.get(cv):
            self._pending.pop(cv, None)
        else:
            self._pending[cv] = value
        # Not straight away: this runs inside the table's own signal for the item being replaced.
        QTimer.singleShot(0, self._fill_table)
        self._update_enabled()

    def _on_table_row(self, row: int, *_) -> None:
        item = self._table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        cv = item.data(Qt.UserRole)
        self._one_cv.setValue(cv)
        value = self._pending.get(cv, self._values.get(cv))
        if value is not None:
            self._one_value.setValue(value)
