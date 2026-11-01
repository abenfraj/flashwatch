# -*- coding: utf-8 -*-
"""The team display's numbers, drawn whole.

The countdown on a spell icon is drawn as a path -- a dark stroke, then the
fill -- and Bahnschrift, the face it asks for first, is a variable font whose
glyphs are built from overlapping contours: the bar and the stem of a 4, the
foot of a 1. A path fills even-odd by default, which leaves every overlap
empty, so the numbers came out with a checker of holes along their lower half
(seen first in a 4x replay frame, there at 1x on screen too). Each glyph is
checked here against the same outline filled the way a glyph is meant to be:
everything inside its outline, overlaps included.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QFontMetricsF, QImage, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

import overlay
from overlay import TEAM_TEXT_HALO, TEAM_TEXT_WIDTH, Overlay, team_number_font

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


RATIO = 4
RECT = QRectF(4.0, 4.0, 40.0, 40.0)
INK = QColor(245, 247, 250)


def canvas() -> QImage:
    image = QImage(48 * RATIO, 48 * RATIO, QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(RATIO)
    image.fill(QColor(40, 50, 60))
    return image


def drawn_by_overlay(text: str) -> QImage:
    image = canvas()
    painter = QPainter(image)
    Overlay._paint_icon_number(None, painter, RECT, text, INK, RECT.center().y(),
                               max_height=RECT.height() * 0.5, scale=1.0)
    painter.end()
    return image


def drawn_whole(text: str) -> QImage:
    """The same outline, sized the same way, filled by its winding."""
    height = RECT.height() * 0.5
    font = team_number_font(height)
    metrics = QFontMetricsF(font)
    while metrics.horizontalAdvance(text) > RECT.width() * TEAM_TEXT_WIDTH \
            and height > 6:
        height -= 0.5
        font = team_number_font(height)
        metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(text)
    cap = metrics.capHeight() or metrics.ascent() * 0.7
    path = QPainterPath()
    path.addText(RECT.center().x() - width / 2.0, RECT.center().y() + cap / 2.0,
                 font, text)
    path.setFillRule(Qt.WindingFill)
    image = canvas()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    stroke = QPen(QColor(*TEAM_TEXT_HALO), 2.6)
    stroke.setJoinStyle(Qt.RoundJoin)
    painter.strokePath(path, stroke)
    painter.fillPath(path, INK)
    painter.end()
    return image


def differing_pixels(a: QImage, b: QImage) -> int:
    count = 0
    for y in range(a.height()):
        for x in range(a.width()):
            pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
            if max(abs(pa.red() - pb.red()), abs(pa.green() - pb.green()),
                   abs(pa.blue() - pb.blue())) > 40:
                count += 1
    return count


print(f"countdown face: {team_number_font(20).family()}")
for text in ("4:14", "1:01", "4", "11", "2:39"):
    holes = differing_pixels(drawn_by_overlay(text), drawn_whole(text))
    check(f"'{text}' is drawn whole, no holes where its strokes overlap",
          holes == 0, f"{holes} pixels differ")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
