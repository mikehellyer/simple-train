"""Drawing track plan tiles with QPainter, for the plan itself and for the
tool buttons' icons."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from simple_train.core import track_plan as tp

TRACK = QColor("#3b4048")
TRACK_SET = QColor("#1f5fa8")  # a point's route as set, in run mode
TRACK_UNSET = QColor("#b9bec6")
CLOSED_LAMP = QColor("#2e9e4f")
THROWN_LAMP = QColor("#e39b12")
LOOSE = QColor("#d64541")
LABEL_INK = QColor("#2b2f36")


def end_point(rect: QRectF, end: int) -> QPointF:
    dx, dy = tp.END_OFFSETS[end]
    centre = rect.center()
    return QPointF(centre.x() + dx * rect.width() / 2, centre.y() + dy * rect.height() / 2)


def _route_path(rect: QRectF, route: tuple[int, ...]) -> QPainterPath:
    centre = rect.center()
    path = QPainterPath()
    if len(route) == 1:  # a buffer stop: in from its end to the middle
        path.moveTo(end_point(rect, route[0]))
        path.lineTo(centre)
        return path
    a, b = route
    path.moveTo(end_point(rect, a))
    if (b - a) % 8 == 4:
        path.lineTo(end_point(rect, b))
    else:
        path.quadTo(centre, end_point(rect, b))
    return path


def _pen(colour: QColor, width: float) -> QPen:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def draw_tile(painter: QPainter, tile: tp.Tile, rect: QRectF, running: bool = False,
              loose_ends: Optional[list[int]] = None, show_address: bool = True) -> None:
    size = rect.width()
    width = max(2.0, size * 0.16)
    painter.setBrush(Qt.NoBrush)

    if tile.kind == tp.LABEL:
        font = QFont()
        font.setPixelSize(max(9, int(size * 0.5)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(LABEL_INK)
        text = tile.text or ("Label" if not running else "")
        wide = QRectF(rect.left() + size * 0.1, rect.top(), size * 12, rect.height())
        painter.drawText(wide, Qt.AlignLeft | Qt.AlignVCenter, text)
        return

    if tile.is_point:
        set_route = tile.routes()[0]
        for route in tile.routes(all_routes=True):
            if route == set_route:
                continue
            painter.setPen(_pen(TRACK_UNSET if running else TRACK, width * (0.7 if running else 1)))
            painter.drawPath(_route_path(rect, route))
        painter.setPen(_pen(TRACK_SET if running else TRACK, width))
        painter.drawPath(_route_path(rect, set_route))
        if running:
            lamp = max(3.0, size * 0.13)
            painter.setPen(Qt.NoPen)
            painter.setBrush(THROWN_LAMP if tile.thrown else CLOSED_LAMP)
            painter.drawEllipse(rect.center(), lamp, lamp)
            painter.setBrush(Qt.NoBrush)
        if show_address and size >= 22:
            font = QFont()
            font.setPixelSize(max(8, int(size * 0.28)))
            painter.setFont(font)
            painter.setPen(LOOSE if not tile.address else QColor("#5a6270"))
            painter.drawText(QRectF(rect.left() + 1, rect.top(), rect.width(), rect.height() * 0.4),
                             Qt.AlignLeft | Qt.AlignTop, str(tile.address) if tile.address else "?")
    else:
        painter.setPen(_pen(TRACK, width))
        for route in tile.routes():
            painter.drawPath(_route_path(rect, route))
        if tile.kind == tp.BUFFER:
            # A bar across the line at the middle of the square.
            dx, dy = tp.END_OFFSETS[tile.rotation]
            length = (dx * dx + dy * dy) ** 0.5
            nx, ny = -dy / length, dx / length
            half = size * 0.28
            centre = rect.center()
            painter.setPen(_pen(TRACK, width * 1.3))
            painter.drawLine(QPointF(centre.x() + nx * half, centre.y() + ny * half),
                             QPointF(centre.x() - nx * half, centre.y() - ny * half))

    if loose_ends:
        painter.setPen(Qt.NoPen)
        painter.setBrush(LOOSE)
        radius = max(2.0, size * 0.09)
        for end in loose_ends:
            painter.drawEllipse(end_point(rect, end), radius, radius)
        painter.setBrush(Qt.NoBrush)


def tile_icon(kind: str, rotation: int = 0, size: int = 32) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    tile = tp.Tile(0, 0, kind, rotation, text="Abc")
    if tile.is_point:
        tile.address = 0
    draw_tile(painter, tile, QRectF(2, 2, size - 4, size - 4), show_address=False)
    painter.end()
    return QIcon(pixmap)
