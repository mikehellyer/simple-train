"""The Track plan tab: draw the layout on a grid, then run it — click a
point to switch it through the NCE USB interface.

Editing:
  pick a piece from the palette and click a square to lay it; click it
  again to turn it 45°. Drag with the straight to lay a line of track.
  Right-click (or the eraser) removes. R / Shift+R turn the selected
  piece, Delete removes it, Ctrl+Z / Ctrl+Y undo and redo.
  Red dots mark track ends that don't meet anything.
Running:
  click a point to switch it. Green = closed (straight on), amber = thrown.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simple_train.core import track_plan as tp
from simple_train.gui.link import Link
from simple_train.gui.plan_drawing import draw_tile, tile_icon

CELL_SIZES = [16, 20, 24, 28, 32, 40, 48, 64]
DEFAULT_CELL = 32
SAVE_DELAY_MS = 500
UNDO_LIMIT = 200
SELECT = "select"
ERASE = "erase"
EDIT, RUN = "edit", "run"


class PlanCanvas(QWidget):
    selection_changed = Signal()
    edited = Signal()  # the plan changed in edit mode (after the undo snapshot)
    about_to_edit = Signal()  # take an undo snapshot now
    point_clicked = Signal(object)  # a point tile, in run mode

    def __init__(self, plan: tp.Plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.mode = EDIT
        self.tool = tp.STRAIGHT
        self.tool_rotation: dict[str, int] = {}
        self.cell = DEFAULT_CELL
        self.selected: Optional[tuple[int, int]] = None
        self._hover: Optional[tuple[int, int]] = None
        self._drag_start: Optional[tuple[int, int]] = None
        self._drag_base: Optional[tp.Plan] = None
        self._erasing = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._resize()

    # --- geometry

    def _resize(self) -> None:
        self.setFixedSize(self.plan.columns * self.cell + 1, self.plan.rows * self.cell + 1)

    def set_plan(self, plan: tp.Plan) -> None:
        self.plan = plan
        self.selected = None
        self._resize()
        self.update()
        self.selection_changed.emit()

    def zoom(self, step: int) -> None:
        index = CELL_SIZES.index(self.cell) if self.cell in CELL_SIZES else CELL_SIZES.index(DEFAULT_CELL)
        index = max(0, min(len(CELL_SIZES) - 1, index + step))
        self.cell = CELL_SIZES[index]
        self._resize()
        self.update()

    def square_at(self, pos: QPoint) -> Optional[tuple[int, int]]:
        column, row = int(pos.x() // self.cell), int(pos.y() // self.cell)
        if 0 <= column < self.plan.columns and 0 <= row < self.plan.rows:
            return column, row
        return None

    def rect_of(self, column: int, row: int) -> QRectF:
        return QRectF(column * self.cell, row * self.cell, self.cell, self.cell)

    @property
    def selected_tile(self) -> Optional[tp.Tile]:
        return self.plan.get(*self.selected) if self.selected else None

    # --- painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        area = event.rect()
        background = QColor("#f7f5f0") if self.mode == RUN else QColor("#fbfaf7")
        painter.fillRect(area, background)
        first_col, last_col = max(0, area.left() // self.cell), min(self.plan.columns, area.right() // self.cell + 1)
        first_row, last_row = max(0, area.top() // self.cell), min(self.plan.rows, area.bottom() // self.cell + 1)
        if self.mode == EDIT:
            painter.setPen(QPen(QColor("#e6e2d8"), 1))
            for column in range(first_col, last_col + 1):
                painter.drawLine(column * self.cell, first_row * self.cell, column * self.cell, last_row * self.cell)
            for row in range(first_row, last_row + 1):
                painter.drawLine(first_col * self.cell, row * self.cell, last_col * self.cell, row * self.cell)
        # Labels last, so their text runs over the track beside them.
        tiles = sorted(self.plan.tiles.values(), key=lambda tile: tile.kind == tp.LABEL)
        for tile in tiles:
            if not (first_col - 12 <= tile.column <= last_col and first_row - 1 <= tile.row <= last_row):
                continue
            loose = self.plan.loose_ends(tile) if self.mode == EDIT else None
            if loose and tile.kind == tp.BUFFER:
                loose = None  # a buffer's open side is the point of it
            draw_tile(painter, tile, self.rect_of(tile.column, tile.row), running=self.mode == RUN,
                      loose_ends=loose)
        highlight = self.palette().highlight().color()
        if self.selected and self.mode == EDIT:
            painter.setPen(QPen(highlight, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect_of(*self.selected).adjusted(1, 1, -1, -1))
        if self._hover:
            tile = self.plan.get(*self._hover)
            if self.mode == EDIT or (tile is not None and tile.is_point):
                colour = QColor(highlight)
                colour.setAlpha(50)
                painter.fillRect(self.rect_of(*self._hover), colour)

    # --- mouse

    def mousePressEvent(self, event) -> None:
        square = self.square_at(event.position().toPoint())
        if square is None:
            return
        tile = self.plan.get(*square)
        if self.mode == RUN:
            if event.button() == Qt.LeftButton and tile is not None and tile.is_point:
                self.point_clicked.emit(tile)
            return
        if event.button() == Qt.RightButton or self.tool == ERASE:
            self._erasing = True
            self._erase(square)
            return
        if event.button() != Qt.LeftButton:
            return
        if self.tool == SELECT:
            self.select(square)
            return
        self.about_to_edit.emit()
        if tile is not None and tile.kind == self.tool:
            tile.rotation = (tile.rotation + 1) % 8
            self.tool_rotation[self.tool] = tile.rotation
        elif tile is not None:
            self._place(square, self.tool, tile.rotation, keep=tile)
        else:
            self._place(square, self.tool, self.tool_rotation.get(self.tool, 0))
        if self.tool == tp.STRAIGHT:
            self._drag_start = square
            self._drag_base = self.plan.copy()
        self.select(square)
        self.edited.emit()

    def mouseMoveEvent(self, event) -> None:
        square = self.square_at(event.position().toPoint())
        if square != self._hover:
            self._hover = square
            self.update()
            tile = self.plan.get(*square) if square else None
            self.setToolTip(tile.label if tile is not None and (tile.is_point or self.mode == EDIT) else "")
        if square is None or self.mode == RUN:
            return
        if self._erasing:
            self._erase(square)
        elif self._drag_start is not None and square != self._drag_start and self._drag_base is not None:
            self._drag_line(square)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start = None
        self._drag_base = None
        self._erasing = False

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        else:
            super().wheelEvent(event)

    # --- editing

    def _place(self, square: tuple[int, int], kind: str, rotation: int, keep: Optional[tp.Tile] = None) -> None:
        tile = tp.Tile(square[0], square[1], kind, rotation)
        if keep is not None and keep.is_point and tile.is_point:
            tile.address, tile.name, tile.inverted = keep.address, keep.name, keep.inverted
        if kind == tp.LABEL:
            tile.text = keep.text if keep is not None and keep.kind == tp.LABEL else "Label"
        self.plan.put(tile)
        self._resize()

    def _drag_line(self, square: tuple[int, int]) -> None:
        """Lay straights from where the drag began to here, on the nearest
        straight or 45° line, replacing what the drag laid before."""
        base = self._drag_base.copy()
        line = list(tp.tiles_between(self._drag_start, square))
        step_c = (line[1][0] - line[0][0]) if len(line) > 1 else 1
        step_r = (line[1][1] - line[0][1]) if len(line) > 1 else 0
        rotation = tp.direction_of(step_c, step_r) % 4
        for column, row in line:
            if 0 <= column < base.columns and 0 <= row < base.rows:
                existing = base.get(column, row)
                if existing is None or existing.kind == tp.STRAIGHT:
                    base.put(tp.Tile(column, row, tp.STRAIGHT, rotation))
        self.plan.tiles = base.tiles
        self.plan.columns, self.plan.rows = max(self.plan.columns, base.columns), max(self.plan.rows, base.rows)
        self.tool_rotation[tp.STRAIGHT] = rotation
        self._resize()
        self.selected = line[-1]
        self.update()
        self.edited.emit()

    def _erase(self, square: tuple[int, int]) -> None:
        if self.plan.get(*square) is None:
            return
        self.about_to_edit.emit()
        self.plan.remove(*square)
        if self.selected == square:
            self.selected = None
            self.selection_changed.emit()
        self.update()
        self.edited.emit()

    def select(self, square: Optional[tuple[int, int]]) -> None:
        self.selected = square if square and self.plan.get(*square) else None
        self.update()
        self.selection_changed.emit()

    def rotate_selected(self, step: int) -> None:
        tile = self.selected_tile
        if tile is None:
            return
        self.about_to_edit.emit()
        tile.rotation = (tile.rotation + step) % 8
        self.tool_rotation[tile.kind] = tile.rotation
        self.update()
        self.edited.emit()

    def delete_selected(self) -> None:
        if self.selected:
            self._erase(self.selected)

    def keyPressEvent(self, event) -> None:
        if self.mode == EDIT:
            if event.key() == Qt.Key_R:
                self.rotate_selected(-1 if event.modifiers() & Qt.ShiftModifier else 1)
                return
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.delete_selected()
                return
        super().keyPressEvent(event)


@dataclass
class _PointRow:
    tile: tp.Tile
    button: QPushButton


class TrackPlanPanel(QWidget):
    point_set = Signal(int, bool)  # accessory address, thrown — however it was switched
    points_changed = Signal()  # points added, removed, renamed or readdressed

    def __init__(self, link: Link, path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.link = link
        self._path = path
        self.plan = tp.load(path)
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._loading = False
        self._point_rows: list[_PointRow] = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        self.canvas = PlanCanvas(self.plan)
        self.canvas.about_to_edit.connect(self._snapshot)
        self.canvas.edited.connect(self._on_edited)
        self.canvas.selection_changed.connect(self._show_selection)
        self.canvas.point_clicked.connect(self.switch_point)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body.addWidget(scroll, stretch=1)
        self._side = QStackedWidget()
        self._side.setFixedWidth(300)
        self._side.addWidget(self._build_properties())
        self._side.addWidget(self._build_points_list())
        body.addWidget(self._side)
        layout.addLayout(body, stretch=1)

        self._status = QLabel()
        self._status.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self._status)

        for keys, slot in ((QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo),
                           (QKeySequence("Ctrl+Y"), self.redo)):
            shortcut = QShortcut(keys, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

        link.connected_changed.connect(lambda _: self._refresh_status())
        link.programming_track_changed.connect(lambda _: self._refresh_status())
        link.throttle_message.connect(self._on_send_error)

        has_plan = bool(self.plan.tiles)
        self.set_mode(RUN if has_plan else EDIT)
        self._show_selection()

    # --- building

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._edit_button = QPushButton("Edit")
        self._run_button = QPushButton("Run")
        mode_group = QButtonGroup(self)
        for button, mode in ((self._edit_button, EDIT), (self._run_button, RUN)):
            button.setCheckable(True)
            button.setMinimumWidth(70)
            mode_group.addButton(button)
            button.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            bar.addWidget(button)
        bar.addSpacing(16)

        self._tools = QWidget()
        tools = QHBoxLayout(self._tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(2)
        self._tool_group = QButtonGroup(self)
        self._tool_buttons: dict[str, QToolButton] = {}
        palette = [(SELECT, "Select (click a piece to change it)"), *((kind, tp.KIND_NAMES[kind]) for kind in tp.KINDS),
                   (ERASE, "Eraser (or right-click)")]
        for tool, tip in palette:
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIconSize(QSize(28, 28))
            if tool == SELECT:
                button.setText("➚")
            elif tool == ERASE:
                button.setText("⌫")
            else:
                button.setIcon(tile_icon(tool))
            button.setStyleSheet("QToolButton { font-size: 18px; min-width: 32px; min-height: 32px; }")
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, t=tool: self.set_tool(t))
            self._tool_group.addButton(button)
            self._tool_buttons[tool] = button
            tools.addWidget(button)
        bar.addWidget(self._tools)
        self._tool_buttons[tp.STRAIGHT].setChecked(True)

        bar.addStretch(1)
        self._undo_button = QPushButton("Undo")
        self._undo_button.clicked.connect(self.undo)
        bar.addWidget(self._undo_button)
        self._redo_button = QPushButton("Redo")
        self._redo_button.clicked.connect(self.redo)
        bar.addWidget(self._redo_button)
        bar.addSpacing(12)
        for text, step in (("−", -1), ("+", 1)):
            button = QToolButton()
            button.setText(text)
            button.setToolTip("Zoom out" if step < 0 else "Zoom in" + " (or Ctrl + mouse wheel)")
            button.clicked.connect(lambda _=False, s=step: self.canvas.zoom(s))
            bar.addWidget(button)
        bar.addSpacing(12)
        export = QPushButton("Export…")
        export.clicked.connect(self._export)
        bar.addWidget(export)
        imp = QPushButton("Import…")
        imp.clicked.connect(self._import)
        bar.addWidget(imp)
        return bar

    def _build_properties(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 0, 0, 0)
        self._kind_label = QLabel()
        self._kind_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(self._kind_label)
        self._help = QLabel()
        self._help.setWordWrap(True)
        self._help.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self._help)

        self._turn_row = QWidget()
        turn = QHBoxLayout(self._turn_row)
        turn.setContentsMargins(0, 0, 0, 0)
        for text, step in (("⟲ Turn left", 1), ("Turn right ⟳", -1)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, s=step: self.canvas.rotate_selected(s))
            turn.addWidget(button)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.canvas_delete)
        turn.addWidget(remove)
        layout.addWidget(self._turn_row)

        self._point_box = QGroupBox("Point")
        form = QFormLayout(self._point_box)
        self._point_name = QLineEdit()
        self._point_name.setPlaceholderText("e.g. Yard entry")
        self._point_name.textEdited.connect(self._on_point_edit)
        form.addRow("Name", self._point_name)
        self._point_address = QSpinBox()
        self._point_address.setRange(0, tp.MAX_ACCESSORY)
        self._point_address.setSpecialValueText("none")
        self._point_address.setToolTip("The accessory address its point motor decoder is set to (1–2044)")
        self._point_address.valueChanged.connect(self._on_point_edit)
        form.addRow("Address", self._point_address)
        self._point_inverted = QCheckBox("Wired the other way round")
        self._point_inverted.setToolTip("Tick if “closed” throws this point, and “thrown” closes it")
        self._point_inverted.toggled.connect(self._on_point_edit)
        form.addRow("", self._point_inverted)
        test = QHBoxLayout()
        self._test_closed = QPushButton("Closed")
        self._test_closed.clicked.connect(lambda: self._test_point(False))
        self._test_thrown = QPushButton("Thrown")
        self._test_thrown.clicked.connect(lambda: self._test_point(True))
        test.addWidget(self._test_closed)
        test.addWidget(self._test_thrown)
        form.addRow("Try it", test)
        self._duplicate = QLabel()
        self._duplicate.setWordWrap(True)
        self._duplicate.setStyleSheet("color: #c0392b;")
        form.addRow(self._duplicate)
        layout.addWidget(self._point_box)

        self._label_box = QGroupBox("Label")
        label_form = QFormLayout(self._label_box)
        self._label_text = QLineEdit()
        self._label_text.textEdited.connect(self._on_label_edit)
        label_form.addRow("Text", self._label_text)
        layout.addWidget(self._label_box)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self._summary)
        layout.addStretch(1)
        return page

    def _build_points_list(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 0, 0, 0)
        title = QLabel("Points")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)
        hint = QLabel("Click a point on the plan, or its button here, to switch it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(hint)
        self._points = QTableWidget(0, 3)
        self._points.setHorizontalHeaderLabels(["Point", "Address", "Set to"])
        self._points.verticalHeader().hide()
        self._points.setEditTriggers(QTableWidget.NoEditTriggers)
        self._points.setSelectionMode(QTableWidget.NoSelection)
        header = self._points.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self._points, stretch=1)
        return page

    # --- modes and tools

    def set_mode(self, mode: str) -> None:
        self.canvas.mode = mode
        self._edit_button.setChecked(mode == EDIT)
        self._run_button.setChecked(mode == RUN)
        for widget in (self._tools, self._undo_button, self._redo_button):
            widget.setVisible(mode == EDIT)
        self._side.setCurrentIndex(0 if mode == EDIT else 1)
        if mode == RUN:
            self.canvas.selected = None
            self._fill_points()
        self.canvas.update()
        self._refresh_status()
        self._update_undo_buttons()

    def set_tool(self, tool: str) -> None:
        self.canvas.tool = tool
        self._tool_buttons[tool].setChecked(True)
        self.canvas.setCursor(Qt.ArrowCursor if tool == SELECT else Qt.CrossCursor)
        self.canvas.setFocus()

    def canvas_delete(self) -> None:
        self.canvas.delete_selected()

    # --- running

    @property
    def can_switch(self) -> bool:
        return self.link.connected and self.link.throttle is not None and not self.link.programming_track_busy

    def switch_point(self, tile: tp.Tile, thrown: Optional[bool] = None) -> None:
        """Set a point (to the other way if `thrown` isn't given)."""
        if not tile.address:
            self._status.setText(f"{tile.label}: give it an address in Edit mode first")
            return
        if not self.can_switch:
            self._refresh_status()
            return
        tile.thrown = (not tile.thrown) if thrown is None else thrown
        self.link.throttle.accessory(tile.address, tile.command(tile.thrown), tile.name or f"Point {tile.address}")
        self.point_set.emit(tile.address, tile.thrown)
        # Points sharing an address (a crossover) move together.
        for other in self.plan.points():
            if other is not tile and other.address == tile.address:
                other.thrown = tile.thrown
        self._status.setText(f"{tile.name or 'Point'} {tile.address}: {'thrown' if tile.thrown else 'closed'}")
        self.canvas.update()
        self._fill_points()
        self._schedule_save()

    def _fill_points(self) -> None:
        points = self.plan.points()
        if [row.tile for row in self._point_rows] != points:
            # Rebuild only when the points themselves change; a switch just updates its button.
            self._points.setRowCount(0)
            self._point_rows = []
            self._points.setRowCount(len(points))
            for row, tile in enumerate(points):
                button = QPushButton()
                button.clicked.connect(lambda _=False, t=tile: self.switch_point(t))
                self._points.setCellWidget(row, 2, button)
                self._point_rows.append(_PointRow(tile, button))
        for row, entry in enumerate(self._point_rows):
            tile = entry.tile
            self._points.setItem(row, 0, QTableWidgetItem(tile.name or f"Point at {tile.column},{tile.row}"))
            address = QTableWidgetItem(str(tile.address) if tile.address else "—")
            address.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._points.setItem(row, 1, address)
            colour = "#e39b12" if tile.thrown else "#2e9e4f"
            entry.button.setText("Thrown" if tile.thrown else "Closed")
            entry.button.setStyleSheet(f"QPushButton {{ color: white; background-color: {colour}; font-weight: 600; "
                                       "border-radius: 4px; padding: 2px 10px; }"
                                       "QPushButton:disabled { background-color: #b9bec6; }")
            entry.button.setEnabled(bool(tile.address) and self.can_switch)

    def _refresh_status(self) -> None:
        if self.canvas.mode == EDIT:
            self._status.setText("Pick a piece and click the grid to lay it; click it again to turn it. Drag the "
                                 "straight for a line. Right-click removes. Red dots: ends that don't meet.")
        elif not self.link.connected:
            self._status.setText("Connect to your NCE USB interface (above) to switch points.")
        elif self.link.programming_track_busy:
            self._status.setText("The programming track is in use — points can't be switched just now.")
        elif not self.plan.tiles:
            self._status.setText("No track yet: press Edit to draw your layout.")
        else:
            self._status.setText("Click a point to switch it. Green: closed (straight on). Amber: thrown.")
        if self.canvas.mode == RUN:
            self._fill_points()
        self._show_selection()

    def _on_send_error(self, text: str) -> None:
        if self.canvas.mode == RUN:
            self._status.setText(text)

    # --- the selected piece

    def _show_selection(self) -> None:
        tile = self.canvas.selected_tile
        self._loading = True
        if tile is None:
            self._kind_label.setText("Track plan")
            self._help.setText("Choose a piece from the palette above and click the grid. Use ➚ to pick a "
                               "piece and change it.")
        else:
            self._kind_label.setText(tp.KIND_NAMES[tile.kind])
            self._help.setText("R / Shift+R turns it, Delete removes it.")
        self._turn_row.setVisible(tile is not None)
        self._point_box.setVisible(tile is not None and tile.is_point)
        self._label_box.setVisible(tile is not None and tile.kind == tp.LABEL)
        if tile is not None and tile.is_point:
            if self._point_name.text() != tile.name:
                self._point_name.setText(tile.name)
            self._point_address.setValue(tile.address)
            self._point_inverted.setChecked(tile.inverted)
            for button in (self._test_closed, self._test_thrown):
                button.setEnabled(bool(tile.address) and self.can_switch)
            others = [other for other in self.plan.points() if other is not tile and tile.address
                      and other.address == tile.address]
            self._duplicate.setText(f"Another point also uses address {tile.address}: they'll move together "
                                    "(right for a crossover)." if others else "")
        if tile is not None and tile.kind == tp.LABEL and self._label_text.text() != tile.text:
            self._label_text.setText(tile.text)
        points = self.plan.points()
        missing = sum(1 for point in points if not point.address)
        summary = f"{len(self.plan.tiles)} pieces, {len(points)} points"
        if missing:
            summary += f" ({missing} without an address yet)"
        self._summary.setText(summary)
        self._loading = False

    def _on_point_edit(self, *_) -> None:
        tile = self.canvas.selected_tile
        if self._loading or tile is None or not tile.is_point:
            return
        self._snapshot()
        tile.name = self._point_name.text().strip()
        tile.address = self._point_address.value()
        tile.inverted = self._point_inverted.isChecked()
        self.canvas.update()
        self._on_edited(refresh=False)
        self._show_selection()

    def _on_label_edit(self) -> None:
        tile = self.canvas.selected_tile
        if self._loading or tile is None or tile.kind != tp.LABEL:
            return
        self._snapshot()
        tile.text = self._label_text.text()
        self.canvas.update()
        self._on_edited(refresh=False)

    def _test_point(self, thrown: bool) -> None:
        tile = self.canvas.selected_tile
        if tile is not None and tile.is_point:
            self.switch_point(tile, thrown)
            self._status.setText(f"Sent {'thrown' if thrown else 'closed'} to address {tile.address}")

    # --- undo, saving, files

    def _snapshot(self) -> None:
        state = json.dumps(self.plan.to_json())
        if self._undo and self._undo[-1] == state:
            return
        self._undo.append(state)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._update_undo_buttons()

    def _restore(self, state: str) -> None:
        selected = self.canvas.selected
        self.plan = tp.Plan.from_json(json.loads(state))
        self.canvas.set_plan(self.plan)
        if selected and self.plan.get(*selected):
            self.canvas.select(selected)
        self._on_edited()

    def undo(self) -> None:
        if self.canvas.mode != EDIT or not self._undo:
            return
        self._redo.append(json.dumps(self.plan.to_json()))
        self._restore(self._undo.pop())

    def redo(self) -> None:
        if self.canvas.mode != EDIT or not self._redo:
            return
        self._undo.append(json.dumps(self.plan.to_json()))
        self._restore(self._redo.pop())

    def _update_undo_buttons(self) -> None:
        self._undo_button.setEnabled(bool(self._undo))
        self._redo_button.setEnabled(bool(self._redo))

    def _on_edited(self, refresh: bool = True) -> None:
        self._schedule_save()
        self._update_undo_buttons()
        if refresh:
            self._show_selection()

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def save(self) -> None:
        self._save_timer.stop()
        try:
            tp.save(self.plan, self._path)
        except OSError as error:
            self._status.setText(f"Couldn't save the track plan: {error}")
        points = [(tile.address, tile.name) for tile in self.plan.points()]
        if points != getattr(self, "_saved_points", None):
            self._saved_points = points
            self.points_changed.emit()

    def points_by_address(self) -> dict[int, list[tp.Tile]]:
        """The points that have an address, grouped by it (a crossover shares one)."""
        grouped: dict[int, list[tp.Tile]] = {}
        for tile in self.plan.points():
            if tile.address:
                grouped.setdefault(tile.address, []).append(tile)
        return grouped

    def set_point(self, address: int, thrown: Optional[bool] = None) -> Optional[str]:
        """Switch the point(s) on an address (the other way if thrown is None),
        as a phone asks. An error message, or None."""
        tiles = self.points_by_address().get(address)
        if not tiles:
            return f"There's no point with address {address} on the track plan"
        if not self.can_switch:
            return ("The programming track is in use: points can't be switched just now"
                    if self.link.connected else "Simple-Train isn't connected to the NCE USB interface")
        self.switch_point(tiles[0], thrown)
        return None

    def shutdown(self) -> None:
        if self._save_timer.isActive():
            self.save()

    def _export(self) -> None:
        start = str(Path.home() / "track plan.train-plan.json")
        path, _ = QFileDialog.getSaveFileName(self, "Export track plan", start,
                                              "Simple-Train track plan (*.train-plan.json)")
        if path:
            try:
                tp.export_plan(self.plan, Path(path))
            except OSError as error:
                QMessageBox.warning(self, "Export track plan", f"Couldn't save {path}: {error}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import track plan", str(Path.home()),
                                              "Simple-Train track plan (*.train-plan.json *.json)")
        if not path:
            return
        try:
            plan = tp.import_plan(Path(path))
        except ValueError as error:
            QMessageBox.warning(self, "Import track plan", str(error))
            return
        if self.plan.tiles and QMessageBox.question(
                self, "Import track plan", "Replace the track plan you have with this one?\n\n"
                "(Undo in Edit mode brings yours back.)") != QMessageBox.Yes:
            return
        self._snapshot()
        self.plan = plan
        self.canvas.set_plan(plan)
        self._on_edited()
        self.set_mode(self.canvas.mode)

