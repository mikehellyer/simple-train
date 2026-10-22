"""The Locos tab: the roster of every loco, with its details and the CVs
saved for it."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simple_train.core import decoder, nce
from simple_train.core.roster import Loco, export_loco, import_loco
from simple_train.gui.roster_store import RosterStore

SAVE_DELAY_MS = 600  # edits are saved this long after the last keypress


def _safe_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() or "loco"


class RosterPanel(QWidget):
    open_in_programmer = Signal(str)  # loco id
    restore_requested = Signal(str)  # loco id

    def __init__(self, roster: RosterStore, parent=None):
        super().__init__(parent)
        self._roster = roster
        self._loco_id: Optional[str] = None
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_details)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_details())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 800])
        layout.addWidget(splitter)

        roster.changed.connect(self._fill_list)
        self._fill_list()

    # --- building

    def _build_list(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Find a loco…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._fill_list)
        layout.addWidget(self._search)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selected)
        self._list.itemDoubleClicked.connect(lambda item: self.open_in_programmer.emit(item.data(Qt.UserRole)))
        layout.addWidget(self._list, stretch=1)
        buttons = QHBoxLayout()
        new = QPushButton("New loco")
        new.clicked.connect(self._new_loco)
        buttons.addWidget(new)
        self._delete = QPushButton("Delete…")
        self._delete.clicked.connect(self._delete_loco)
        buttons.addWidget(self._delete)
        layout.addLayout(buttons)
        files = QHBoxLayout()
        imp = QPushButton("Import…")
        imp.setToolTip("Add a loco from a file exported by Simple-Train")
        imp.clicked.connect(self._import)
        files.addWidget(imp)
        self._export = QPushButton("Export…")
        self._export.setToolTip("Save this loco and its CVs to a file of its own")
        self._export.clicked.connect(self._export_loco)
        files.addWidget(self._export)
        layout.addLayout(files)
        return box

    def _build_details(self) -> QWidget:
        self._details = QWidget()
        layout = QVBoxLayout(self._details)
        layout.setContentsMargins(12, 0, 0, 0)

        form = QFormLayout()
        self._name = QLineEdit()
        self._name.textEdited.connect(self._schedule_save)
        form.addRow("Name", self._name)
        self._road_number = QLineEdit()
        self._road_number.setPlaceholderText("e.g. 08 644")
        self._road_number.textEdited.connect(self._schedule_save)
        form.addRow("Running number", self._road_number)
        address_row = QHBoxLayout()
        self._address = QSpinBox()
        self._address.setRange(1, nce.MAX_LONG_ADDRESS)
        self._address.setMinimumWidth(90)
        self._address.valueChanged.connect(self._on_address)
        address_row.addWidget(self._address)
        self._long = QCheckBox("Long address")
        self._long.toggled.connect(self._schedule_save)
        address_row.addWidget(self._long)
        address_hint = QLabel("(what the decoder answers to — Read decoder fills this in)")
        address_hint.setStyleSheet("color: palette(placeholder-text);")
        address_row.addWidget(address_hint)
        address_row.addStretch(1)
        form.addRow("DCC address", address_row)
        self._decoder_model = QLineEdit()
        self._decoder_model.setPlaceholderText("e.g. Gaugemaster DCC22, ESU LokSound 5")
        self._decoder_model.textEdited.connect(self._schedule_save)
        form.addRow("Decoder", self._decoder_model)
        self._made_by = QLabel("—")
        form.addRow("Made by (CV8)", self._made_by)
        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText("Anything worth remembering: sound slots, function keys, quirks…")
        self._notes.setFixedHeight(80)
        self._notes.textChanged.connect(self._schedule_save)
        form.addRow("Notes", self._notes)
        layout.addLayout(form)

        cv_header = QHBoxLayout()
        self._cv_title = QLabel()
        self._cv_title.setStyleSheet("font-weight: 600;")
        cv_header.addWidget(self._cv_title)
        cv_header.addStretch(1)
        program = QPushButton("Open in programmer")
        program.setToolTip("Go to the programmer with this loco chosen")
        program.clicked.connect(lambda: self._loco_id and self.open_in_programmer.emit(self._loco_id))
        cv_header.addWidget(program)
        self._restore = QPushButton("Write saved CVs to decoder…")
        self._restore.clicked.connect(lambda: self._loco_id and self.restore_requested.emit(self._loco_id))
        cv_header.addWidget(self._restore)
        layout.addLayout(cv_header)

        self._cvs = QTableWidget(0, 5)
        self._cvs.setHorizontalHeaderLabels(["CV", "What it is", "Value", "Hex", "Bits"])
        self._cvs.verticalHeader().hide()
        self._cvs.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self._cvs.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self._cvs, stretch=1)

        self._empty = QLabel("No locos yet. Read a decoder in the Programmer and press “Save to roster…”, "
                             "or press New loco.")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet("color: palette(placeholder-text); font-size: 15px;")
        layout.addWidget(self._empty)

        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(self._details)
        return holder

    # --- the list

    @property
    def loco(self) -> Optional[Loco]:
        return self._roster.roster.get(self._loco_id)

    def select(self, loco_id: Optional[str]) -> None:
        self._loco_id = loco_id
        self._fill_list()

    def _fill_list(self) -> None:
        wanted = self._search.text().strip().lower()
        self._list.blockSignals(True)
        self._list.clear()
        current = None
        for loco in self._roster.roster.sorted():
            haystack = f"{loco.name} {loco.road_number} {loco.address} {loco.address_text} {loco.decoder_model}".lower()
            if wanted and wanted not in haystack:
                continue
            item = QListWidgetItem(loco.label)
            item.setData(Qt.UserRole, loco.id)
            item.setToolTip(loco.road_number or loco.name)
            self._list.addItem(item)
            if loco.id == self._loco_id:
                current = item
        if current is None and self._list.count() and not wanted:
            current = self._list.item(0)
        self._list.setCurrentItem(current)
        self._list.blockSignals(False)
        self._loco_id = current.data(Qt.UserRole) if current is not None else None
        self._show_loco()

    def _on_selected(self, item, _previous=None) -> None:
        self._flush()
        self._loco_id = item.data(Qt.UserRole) if item is not None else None
        self._show_loco()

    def _show_loco(self) -> None:
        loco = self.loco
        has = loco is not None
        for widget in (self._name, self._road_number, self._address, self._long, self._decoder_model,
                       self._notes, self._cvs, self._restore, self._delete, self._export):
            widget.setEnabled(has)
        self._empty.setVisible(not self._roster.roster.locos)
        self._cvs.setVisible(bool(self._roster.roster.locos))
        self._loading = True
        if not has:
            for edit in (self._name, self._road_number, self._decoder_model):
                edit.clear()
            self._notes.clear()
            self._made_by.setText("—")
            self._cv_title.setText("")
            self._cvs.setRowCount(0)
            self._loading = False
            return
        # Only where it differs, so a save while typing doesn't move the cursor.
        for edit, text in ((self._name, loco.name), (self._road_number, loco.road_number),
                           (self._decoder_model, loco.decoder_model)):
            if edit.text() != text:
                edit.setText(text)
        self._address.setValue(loco.address)
        self._long.setChecked(loco.long_address)
        self._long.setEnabled(not decoder.should_be_long(loco.address))
        made_by = loco.manufacturer or "—"
        if loco.decoder_version is not None:
            made_by += f", version {loco.decoder_version}"
        self._made_by.setText(made_by)
        if self._notes.toPlainText() != loco.notes:
            self._notes.setPlainText(loco.notes)
        self._cv_title.setText(f"{len(loco.cvs)} saved CVs" + (f" — {loco.cvs_saved_at}" if loco.cvs_saved_at else ""))
        self._restore.setEnabled(bool(loco.cvs))
        self._cvs.setRowCount(len(loco.cvs))
        for row, (cv, value) in enumerate(sorted(loco.cvs.items())):
            for column, text in enumerate([str(cv), decoder.cv_name(cv), str(value), *decoder.format_value(value)]):
                item = QTableWidgetItem(text)
                if column in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._cvs.setItem(row, column, item)
        self._loading = False

    # --- editing

    def _on_address(self) -> None:
        if decoder.should_be_long(self._address.value()):
            self._long.setChecked(True)
            self._long.setEnabled(False)
        else:
            self._long.setEnabled(True)
        self._schedule_save()

    def _schedule_save(self, *_) -> None:
        if not self._loading:
            self._save_timer.start()

    def _flush(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_details()

    def _save_details(self) -> None:
        loco = self.loco
        if loco is None:
            return
        loco.name = self._name.text().strip() or loco.name
        loco.road_number = self._road_number.text().strip()
        loco.address = self._address.value()
        loco.long_address = self._long.isChecked()
        loco.decoder_model = self._decoder_model.text().strip()
        loco.notes = self._notes.toPlainText()
        self._roster.save()

    def shutdown(self) -> None:
        self._flush()

    def _new_loco(self) -> None:
        self._flush()
        loco = self._roster.add(Loco(name=f"New loco {len(self._roster.roster.locos) + 1}"))
        self.select(loco.id)
        self._name.setFocus()
        self._name.selectAll()

    def _delete_loco(self) -> None:
        loco = self.loco
        if loco is None:
            return
        answer = QMessageBox.question(self, "Delete loco",
                                      f"Delete {loco.name} and its saved CVs from the roster?\n\n"
                                      "The decoder itself isn't changed.")
        if answer == QMessageBox.Yes:
            self._save_timer.stop()
            self._loco_id = None
            self._roster.remove(loco.id)

    def _export_loco(self) -> None:
        self._flush()
        loco = self.loco
        if loco is None:
            return
        start = str(Path.home() / f"{_safe_filename(loco.name)}.train.json")
        path, _ = QFileDialog.getSaveFileName(self, "Export loco", start, "Simple-Train loco (*.train.json)")
        if not path:
            return
        try:
            export_loco(loco, Path(path))
        except OSError as error:
            QMessageBox.warning(self, "Export loco", f"Couldn't save {path}: {error}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import loco", str(Path.home()),
                                              "Simple-Train loco (*.train.json *.json)")
        if not path:
            return
        try:
            loco = import_loco(Path(path))
        except ValueError as error:
            QMessageBox.warning(self, "Import loco", str(error))
            return
        self._roster.add(loco)
        self.select(loco.id)
