# -*- coding: utf-8 -*-
"""The window's icons, drawn rather than shipped.

The maquettes call icons out of a design system by name -- ``X24Ic24Home24``,
``X24Ic24Scanner24`` -- which is a component library this program does not have
and could not carry: ``design/CONTRAINTES-QT.md`` is explicit that nothing here
is delivered as an image file, the executable is already 99 MB, and an icon font
would drag a licence question behind it. So each one is a few lines of geometry
on a 24 x 24 grid, drawn at whatever size is asked for and cached as a pixmap.

Two consequences worth knowing:

* they are **monochrome by design**. Every icon takes its colour from the caller,
  which is what lets the same glyph sit dim in a resting navigation row and pale
  violet in the selected one without a second file;
* they are **stroked, not filled**, at a weight of 2/24 of the box. That is the
  maquettes' own weight, and it is what keeps a 20 px icon beside 16 px text from
  reading as a blob.

The cache is keyed on name, size and colour, and there are a few dozen of those
in a run -- the whole set at every size the window uses is well under a hundred
small pixmaps.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# name -> pixmap, keyed by (name, size, colour, device ratio).
_CACHE: dict[tuple, QPixmap] = {}

BOX = 24.0                     # the grid every path below is written on
WEIGHT = 2.0                   # ...and the stroke weight on that grid


def _pen(painter: QPainter, colour: QColor, weight: float = WEIGHT) -> None:
    pen = QPen(colour, weight)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)


def _chevron(painter: QPainter, centre: QPointF, reach: float,
             angle: float) -> None:
    """One corner of a square, rotated: the arrow head every chevron is made of."""
    painter.save()
    painter.translate(centre)
    painter.rotate(angle)
    painter.drawPolyline(QPolygonF([QPointF(-reach, -reach), QPointF(0, 0),
                                    QPointF(-reach, reach)]))
    painter.restore()


# ---------------------------------------------------------------------------
# The glyphs. Each draws inside 0..24 with the pen already set.
# ---------------------------------------------------------------------------
def _home(painter: QPainter) -> None:
    painter.drawPolyline(QPolygonF([QPointF(3.5, 10.5), QPointF(12, 3.5),
                                    QPointF(20.5, 10.5)]))
    painter.drawPolyline(QPolygonF([QPointF(5.6, 9.4), QPointF(5.6, 20.5),
                                    QPointF(18.4, 20.5), QPointF(18.4, 9.4)]))
    painter.drawPolyline(QPolygonF([QPointF(9.6, 20.5), QPointF(9.6, 14.2),
                                    QPointF(14.4, 14.2), QPointF(14.4, 20.5)]))


def _eye(painter: QPainter) -> None:
    path = QPainterPath(QPointF(2.5, 12))
    path.quadTo(QPointF(12, 3.6), QPointF(21.5, 12))
    path.quadTo(QPointF(12, 20.4), QPointF(2.5, 12))
    painter.drawPath(path)
    painter.drawEllipse(QPointF(12, 12), 3.2, 3.2)


def _eye_off(painter: QPainter) -> None:
    _eye(painter)
    painter.drawLine(QPointF(4.5, 4.5), QPointF(19.5, 19.5))


def _gear(painter: QPainter) -> None:
    # Teeth that start *on* the rim rather than floating clear of it: with a gap
    # between the two, eight strokes around a small circle read as a sun.
    painter.drawEllipse(QPointF(12, 12), 5.0, 5.0)
    for step in range(8):
        painter.save()
        painter.translate(QPointF(12, 12))
        painter.rotate(step * 45.0)
        painter.drawLine(QPointF(0, -5.0), QPointF(0, -8.4))
        painter.restore()


def _alert(painter: QPainter) -> None:
    painter.drawPolyline(QPolygonF([QPointF(12, 3.4), QPointF(21.6, 20),
                                    QPointF(2.4, 20), QPointF(12, 3.4)]))
    painter.drawLine(QPointF(12, 9.6), QPointF(12, 14.6))
    painter.drawPoint(QPointF(12, 17.6))


def _play(painter: QPainter) -> None:
    painter.drawPolyline(QPolygonF([QPointF(6.5, 4), QPointF(19.5, 12),
                                    QPointF(6.5, 20), QPointF(6.5, 4)]))


def _refresh(painter: QPainter) -> None:
    rect = QRectF(3.6, 3.6, 16.8, 16.8)
    painter.drawArc(rect, 60 * 16, 260 * 16)
    painter.drawPolyline(QPolygonF([QPointF(15.4, 3.2), QPointF(20.4, 6.6),
                                    QPointF(16.6, 10.6)]))


def _bell(painter: QPainter) -> None:
    path = QPainterPath(QPointF(5.4, 17))
    path.lineTo(QPointF(5.4, 11.2))
    path.quadTo(QPointF(5.4, 4.4), QPointF(12, 4.4))
    path.quadTo(QPointF(18.6, 4.4), QPointF(18.6, 11.2))
    path.lineTo(QPointF(18.6, 17))
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(9.8, 19.8), QPointF(14.2, 19.8))


def _scanner(painter: QPainter) -> None:
    for x_sign in (-1, 1):
        for y_sign in (-1, 1):
            painter.drawPolyline(QPolygonF([
                QPointF(12 + x_sign * 8.6, 12 + y_sign * 4.6),
                QPointF(12 + x_sign * 8.6, 12 + y_sign * 8.6),
                QPointF(12 + x_sign * 4.6, 12 + y_sign * 8.6)]))
    painter.drawLine(QPointF(3.4, 12), QPointF(20.6, 12))


def _report(painter: QPainter) -> None:
    painter.drawPolyline(QPolygonF([QPointF(14.2, 3.4), QPointF(5.4, 3.4),
                                    QPointF(5.4, 20.6), QPointF(18.6, 20.6),
                                    QPointF(18.6, 8)]))
    painter.drawPolyline(QPolygonF([QPointF(13.8, 3.4), QPointF(18.6, 8.2),
                                    QPointF(13.8, 8.2), QPointF(13.8, 3.4)]))
    for index in range(2):
        y = 13 + index * 3.6
        painter.drawLine(QPointF(8.6, y), QPointF(15.4, y))


def _person(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(12, 8.6), 3.9, 3.9)
    path = QPainterPath(QPointF(4.6, 20.4))
    path.quadTo(QPointF(5.6, 14.4), QPointF(12, 14.4))
    path.quadTo(QPointF(18.4, 14.4), QPointF(19.4, 20.4))
    painter.drawPath(path)


def _copy(painter: QPainter) -> None:
    painter.drawRoundedRect(QRectF(8.4, 3.4, 12.2, 14.2), 2.4, 2.4)
    painter.drawPolyline(QPolygonF([QPointF(15.6, 20.6), QPointF(3.4, 20.6),
                                    QPointF(3.4, 6.8)]))


def _target(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(12, 12), 6.4, 6.4)
    painter.drawEllipse(QPointF(12, 12), 1.4, 1.4)
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        painter.drawLine(QPointF(12 + dx * 8.2, 12 + dy * 8.2),
                         QPointF(12 + dx * 5.0, 12 + dy * 5.0))


def _info(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(12, 12), 8.6, 8.6)
    painter.drawLine(QPointF(12, 11.2), QPointF(12, 16.6))
    painter.drawPoint(QPointF(12, 7.8))


def _globe(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(12, 12), 8.6, 8.6)
    painter.drawLine(QPointF(3.4, 12), QPointF(20.6, 12))
    path = QPainterPath(QPointF(12, 3.4))
    path.quadTo(QPointF(6.6, 12), QPointF(12, 20.6))
    path.quadTo(QPointF(17.4, 12), QPointF(12, 3.4))
    painter.drawPath(path)


def _branch(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(6.4, 6.2), 2.6, 2.6)
    painter.drawEllipse(QPointF(6.4, 18.2), 2.6, 2.6)
    painter.drawEllipse(QPointF(17.6, 12.2), 2.6, 2.6)
    painter.drawLine(QPointF(6.4, 8.8), QPointF(6.4, 15.6))
    painter.drawPolyline(QPolygonF([QPointF(6.4, 12.2), QPointF(15, 12.2)]))


def _power(painter: QPainter) -> None:
    # Everything but the top: the gap is where the upright goes through.
    painter.drawArc(QRectF(4.4, 5.4, 15.2, 15.2), 120 * 16, 300 * 16)
    painter.drawLine(QPointF(12, 3.4), QPointF(12, 11.4))


def _exit(painter: QPainter) -> None:
    painter.drawPolyline(QPolygonF([QPointF(13.4, 4.4), QPointF(4.6, 4.4),
                                    QPointF(4.6, 19.6), QPointF(13.4, 19.6)]))
    painter.drawLine(QPointF(10.2, 12), QPointF(20.4, 12))
    _chevron(painter, QPointF(20.4, 12), 3.4, 0)


def _close(painter: QPainter) -> None:
    painter.drawLine(QPointF(5.4, 5.4), QPointF(18.6, 18.6))
    painter.drawLine(QPointF(18.6, 5.4), QPointF(5.4, 18.6))


def _trash(painter: QPainter) -> None:
    painter.drawLine(QPointF(3.8, 6.6), QPointF(20.2, 6.6))
    painter.drawPolyline(QPolygonF([QPointF(9, 6.6), QPointF(9, 4),
                                    QPointF(15, 4), QPointF(15, 6.6)]))
    painter.drawPolyline(QPolygonF([QPointF(6.2, 6.6), QPointF(7.2, 20.4),
                                    QPointF(16.8, 20.4), QPointF(17.8, 6.6)]))


def _dashed_box(painter: QPainter) -> None:
    pen = painter.pen()
    pen.setDashPattern([2.4, 2.2])
    painter.setPen(pen)
    painter.drawRoundedRect(QRectF(3.6, 3.6, 16.8, 16.8), 3.0, 3.0)


def _check(painter: QPainter) -> None:
    painter.drawPolyline(QPolygonF([QPointF(4.6, 12.6), QPointF(9.8, 17.8),
                                    QPointF(19.4, 6.6)]))


def _check_circle(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(12, 12), 8.6, 8.6)
    painter.drawPolyline(QPolygonF([QPointF(7.8, 12.2), QPointF(10.9, 15.4),
                                    QPointF(16.4, 9.2)]))


def _chevron_down(painter: QPainter) -> None:
    _chevron(painter, QPointF(12, 14.4), 4.6, 90)


def _chevron_right(painter: QPainter) -> None:
    _chevron(painter, QPointF(14.4, 12), 4.6, 0)


def _clock(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(12, 12), 8.6, 8.6)
    painter.drawPolyline(QPolygonF([QPointF(12, 6.8), QPointF(12, 12.4),
                                    QPointF(16.2, 14.6)]))


def _move(painter: QPainter) -> None:
    painter.drawLine(QPointF(12, 4), QPointF(12, 20))
    painter.drawLine(QPointF(4, 12), QPointF(20, 12))
    for angle in (0, 90, 180, 270):
        painter.save()
        painter.translate(QPointF(12, 12))
        painter.rotate(angle)
        painter.drawPolyline(QPolygonF([QPointF(-2.8, -5.6), QPointF(0, -8.4),
                                        QPointF(2.8, -5.6)]))
        painter.restore()


GLYPHS = {
    "home": _home,
    "eye": _eye,
    "eye_off": _eye_off,
    "gear": _gear,
    "alert": _alert,
    "play": _play,
    "refresh": _refresh,
    "bell": _bell,
    "scanner": _scanner,
    "report": _report,
    "person": _person,
    "copy": _copy,
    "target": _target,
    "info": _info,
    "globe": _globe,
    "branch": _branch,
    "power": _power,
    "exit": _exit,
    "close": _close,
    "trash": _trash,
    "dashed_box": _dashed_box,
    "check": _check,
    "check_circle": _check_circle,
    "chevron_down": _chevron_down,
    "chevron_right": _chevron_right,
    "clock": _clock,
    "move": _move,
}


def paint_icon(painter: QPainter, rect: QRectF, name: str, colour: QColor,
               weight: float = WEIGHT) -> None:
    """Draw one glyph inside ``rect``, in ``colour``.

    For a caller that is already painting -- the window's own chrome. Anything
    that wants a widget icon should ask :func:`icon` for a pixmap instead, so the
    geometry is walked once rather than on every repaint.
    """
    glyph = GLYPHS.get(name)
    if glyph is None:
        return
    scale = min(rect.width(), rect.height()) / BOX
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(rect.center().x() - BOX * scale / 2,
                      rect.center().y() - BOX * scale / 2)
    painter.scale(scale, scale)
    # The pen is set *inside* the scaled space, so the stroke keeps its 2/24
    # proportion at every size rather than thinning out as the icon grows.
    _pen(painter, colour, weight)
    glyph(painter)
    painter.restore()


def icon(name: str, size: int, colour: str, *, weight: float = WEIGHT,
         ratio: float = 2.0) -> QPixmap:
    """One glyph as a pixmap, cached.

    Drawn at ``ratio`` times the asked size and marked as such, so it stays crisp
    on a 150% display -- the same trick the tray icon uses. Qt scales it back
    down for the widget.
    """
    key = (name, size, colour, weight, ratio)
    found = _CACHE.get(key)
    if found is not None:
        return found
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    paint_icon(painter, QRectF(0, 0, size, size), name, QColor(colour), weight)
    painter.end()
    _CACHE[key] = pixmap
    return pixmap
