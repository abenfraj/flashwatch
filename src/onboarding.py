# -*- coding: utf-8 -*-
"""The setup guide: eight screens, drawn to the mockups' own coordinates.

Four things decide whether Flashwatch works at all, and not one of them can be
worked out by poking at the interface: League has to be in **borderless**, the
**client's language** decides the wording looked for in chat, the **overlay** has
three shapes and goes anywhere on screen, and none of it can be *proved* outside
a game. So the first run says all four, in the Practice Tool, where each one can
actually be checked instead of promised. The fifth screen is the exception and
earns its place the same way: the appearance settings, offered where the preview
they change is already on screen rather than on the far side of the guide.

What is different about this window, and the reason it is built the way it is:
it is a **direct port of ``design/maquette/Onboarding *.dc.html``**, not an
interpretation of them. Those files are absolutely-positioned CSS on a fixed
1536 x 1024 canvas, so this draws on a fixed 1536 x 1024 canvas too, and every
number below -- 46, 158, 382, 896 -- is the number in the mockup. The whole
window is a single painted widget with one uniform scale applied at the top of
``paintEvent``: nothing is laid out by Qt, so nothing can drift from the design
when a translation runs long or a window is resized. It is the only way to be
able to say the screens *are* the mockups rather than that they resemble them.

Three consequences worth knowing:

* the face is **Mulish**, the mockups' own, embedded from ``assets/fonts``
  (SIL OFL, 212 KB) -- with sizes given in pixels, like the CSS, so a heading is
  42 px here because it is 42 px there;
* the window keeps the design's 3:2 shape and scales to whatever the screen
  allows, so the composition is identical on a 4K monitor and on a laptop;
* there are **no child widgets**, which is what lets the language be changed from
  inside the guide without the window being torn down and rebuilt -- every word
  is fetched from ``tr()`` at paint time, so switching language is a repaint.
  That is what used to make choosing English flash the screen and raise a toast.

The pictures are painted rather than shipped, and that is the one place this
deliberately departs from the maquettes: two of their four panels are
``image-slot`` placeholders for screenshots of League's client. A screenshot ages
with every patch, exists in one language, and would have to be carried inside an
executable that is already 99 MB, so those panels are redrawn as schematics
carrying the client's own labels -- the argument is made at length in
``design/09-onboarding-practice-tool.md``.

Everything moves, and not for decoration. A guide is read in one order, so the
stepper's line fills forwards, a screen slides in from the side it came from, and
each figure assembles in the order it should be read. Qt has no CSS transitions
(``design/CONTRAINTES-QT.md``), so each of those is a number animated by
:class:`Motion` and read inside a ``paintEvent``. The cost is watched: an
entrance lasts under a second and stops, and the one looping animation runs at
twelve frames a second and gives up after seven seconds. Nothing here spins while
League is being played.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QWidget

from i18n import ENGLISH, FRENCH, language_for, locale_for, tr
from overlay import (FACE_AUTO, LAYOUT_BAR, LAYOUT_CARDS, LAYOUT_LIST,
                     LAYOUTS, THEMES, available_countdown_faces)
from settings import DEFAULTS
from theme import GUIDE, menu_family

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The canvas everything is drawn on, in the mockups' own units.
# ---------------------------------------------------------------------------
DESIGN = QSize(1536, 1024)

# What the window opens at, as a fraction of that canvas. Every number in this
# file stays in the mockups' units; this is the single place the whole guide is
# scaled, so a quarter off here is a quarter off the window *and* off the
# apparent zoom, with the composition untouched.
OPEN_SCALE = 0.75

# The steps, in the order the mockups' stepper walks them.
STEP_LANGUAGE = "language"
STEP_WELCOME = "welcome"
STEP_BORDERLESS = "borderless"
STEP_LAYOUT = "layout"
STEP_TUNE = "tune"
STEP_PLACE = "place"
STEP_PROOF = "proof"
STEP_DONE = "done"
STEPS = (STEP_LANGUAGE, STEP_WELCOME, STEP_BORDERLESS, STEP_LAYOUT, STEP_TUNE,
         STEP_PLACE, STEP_PROOF, STEP_DONE)
STEP_NAV = {step: f"guide.nav_{step}" for step in STEPS}

# Chrome, from the mockups: header band, footer rule, footer button row.
HEADER_H = 158
FOOT_RULE = 896
FOOT_TOP = 920
FOOT_H = 74
EDGE = 40                      # the footer's side margin
COL_X = 46                     # the left column's left edge
COL_TOP = 196                  # ...and its top
COL_W = 480
PANEL_X = 604                  # the right-hand panel
PANEL_W = 888

# Animation. One number per gesture rather than one per element: a page slides,
# fades and assembles as a single movement, and the moment the three disagree it
# reads as three things happening.
SLIDE_MS = 320
FADE_MS = 240
REVEAL_MS = 700
LOOP_MS = 80
LOOP_TICKS = 88


# ---------------------------------------------------------------------------
# The face
# ---------------------------------------------------------------------------
_SERIF = "Georgia"


def family() -> str:
    """Mulish, the mockups' face, or whatever Windows has if it is missing.

    The loader itself moved to ``theme.py`` when the control window was rebuilt
    to the same maquettes: two surfaces drawn from one design cannot be allowed
    to each find their own font file, or a missing TTF makes one of them fall
    back and the product ends up wearing two faces.
    """
    return menu_family()


def px(size: float, weight: int = QFont.Normal, *, italic: bool = False,
       spacing: float = 0.0, serif: bool = False) -> QFont:
    """A font in *pixels*, because the mockups are written in pixels.

    Point sizes would put the design at the mercy of the screen's DPI: the whole
    canvas is scaled as a unit, so its type has to be measured in the same units
    as its rectangles.
    """
    font = QFont(_SERIF if serif else family())
    font.setPixelSize(max(1, int(round(size))))
    font.setWeight(weight)
    font.setItalic(italic)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


# ---------------------------------------------------------------------------
# Colour and easing helpers
# ---------------------------------------------------------------------------
def c(role: str, alpha: int | None = None) -> QColor:
    colour = QColor(GUIDE[role])
    if alpha is not None:
        colour.setAlpha(alpha)
    return colour


def mix(first: QColor, second: QColor, amount: float) -> QColor:
    """``first`` at 0, ``second`` at 1. What a CSS transition would have done."""
    amount = clamp(amount)
    return QColor(
        round(first.red() + (second.red() - first.red()) * amount),
        round(first.green() + (second.green() - first.green()) * amount),
        round(first.blue() + (second.blue() - first.blue()) * amount),
        round(first.alpha() + (second.alpha() - first.alpha()) * amount))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else (high if value > high else value)


def stage(reveal: float, start: float, span: float = 0.5) -> float:
    """One element's share of a screen's single reveal number.

    A staggered entrance normally means one animation per element, each with its
    own delay -- and a timer per element is a timer that can fire into a widget
    that has been deleted. Here the screen animates *one* number from 0 to 1 and
    every part of it reads its own slice out of it, which cannot desynchronise
    and cannot outlive the window that owns it.
    """
    if span <= 0:
        return 1.0
    return 1.0 - (1.0 - clamp((reveal - start) / span)) ** 3


# ---------------------------------------------------------------------------
# Drawing primitives, all in design coordinates
# ---------------------------------------------------------------------------
def box(painter: QPainter, rect: QRectF, radius: float, *,
        fill: QColor | QLinearGradient | None = None,
        edge: QColor | None = None, edge_width: float = 1.0) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    if fill is not None:
        painter.fillPath(path, fill)
    if edge is not None:
        painter.setPen(QPen(edge, edge_width))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


def shadow(painter: QPainter, rect: QRectF, radius: float, *, spread: float,
           drop: float = 0.0, alpha: int = 70) -> None:
    """A drop shadow, painted. Qt has no ``box-shadow``; this is three washes."""
    painter.setPen(Qt.NoPen)
    steps = 3
    for index in range(steps, 0, -1):
        grow = spread * index / steps
        painter.setBrush(QColor(0, 0, 0, int(alpha / steps)))
        painter.drawRoundedRect(rect.adjusted(-grow, -grow + drop, grow,
                                              grow + drop),
                                radius + grow, radius + grow)


def glow(painter: QPainter, rect: QRectF, radius: float, colour: QColor, *,
         spread: float = 40.0, alpha: int = 46) -> None:
    """The mockups' coloured halo around the big panels, as washed rings."""
    painter.setBrush(Qt.NoBrush)
    steps = 3
    for index in range(steps, 0, -1):
        width = spread * index / steps
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(),
                                   int(alpha / index)), width))
        painter.drawRoundedRect(rect.adjusted(-width / 2, -width / 2,
                                              width / 2, width / 2),
                                radius + width / 2, radius + width / 2)


def line(painter: QPainter, x: float, y: float, text: str, font: QFont,
         colour: QColor, *, align=Qt.AlignLeft) -> float:
    """One line of text, ``y`` being the top of its box as in CSS.

    Returns the advance, so a caller can put something after it.
    """
    metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(text)
    if align == Qt.AlignHCenter:
        x -= width / 2
    elif align == Qt.AlignRight:
        x -= width
    painter.setFont(font)
    painter.setPen(colour)
    painter.drawText(QPointF(x, y + metrics.ascent()), text)
    return width


def centred(painter: QPainter, rect: QRectF, text: str, font: QFont,
            colour: QColor) -> None:
    """Text centred in a box, both ways. For buttons, badges, pills."""
    metrics = QFontMetricsF(font)
    painter.setFont(font)
    painter.setPen(colour)
    painter.drawText(
        QPointF(rect.center().x() - metrics.horizontalAdvance(text) / 2,
                rect.center().y() + (metrics.ascent() - metrics.descent()) / 2),
        text)


def runs_of(text: str, font: QFont, colour: QColor, *,
            strong: QFont | None = None,
            strong_colour: QColor | None = None) -> list[tuple]:
    """Split a translation on ``<b>`` into styled runs.

    The catalogue marks *what* is emphasised; the screen decides what emphasis
    looks like. A translator writing a colour into a string is how a restyle
    turns into a hunt through two languages.
    """
    parts: list[tuple] = []
    rest = text
    while "<b>" in rest:
        before, _, rest = rest.partition("<b>")
        inside, _, rest = rest.partition("</b>")
        if before:
            parts.append((before, font, colour))
        if inside:
            parts.append((inside, strong or font, strong_colour or colour))
    if rest:
        parts.append((rest, font, colour))
    return parts


def flow(painter: QPainter, x: float, y: float, width: float, runs: list[tuple],
         leading: float, *, align=Qt.AlignLeft) -> float:
    """Wrap styled runs into a column, at the mockup's exact line-height.

    Qt's own word wrap uses the font's line spacing, which is not what the CSS
    says: a 25 px face on a 41 px line is a deliberate rhythm, and letting Qt
    choose would quietly compress every paragraph in the window. So the words are
    measured and placed by hand. Returns the y below the last line.
    """
    words: list[tuple] = []
    open_word = False
    for text, font, colour in runs:
        metrics = QFontMetricsF(font)
        space = metrics.horizontalAdvance(" ")
        # A run that begins where the last one ended mid-word continues that
        # word rather than starting a new one -- otherwise "<b>VIDEO</b>." comes
        # out as "VIDEO ." while "gauche. <b>Le" loses its space. Both halves of
        # the join have to agree, which is why it takes two flags.
        glue = open_word and not text.startswith(" ")
        open_word = bool(text) and not text.endswith(" ")
        for index, word in enumerate(text.split(" ")):
            if not word:
                continue
            words.append((word, font, colour, metrics.horizontalAdvance(word),
                          space, glue and index == 0))
    if not words:
        return y

    lines: list[tuple[list, float]] = []
    current: list = []
    used = 0.0
    for word in words:
        gap = 0.0 if word[5] else (current[-1][4] if current else 0.0)
        if current and not word[5] and used + gap + word[3] > width:
            lines.append((current, used))
            current, used = [word], word[3]
        else:
            used += gap + word[3]
            current.append(word)
    lines.append((current, used))

    for index, (items, total) in enumerate(lines):
        top = y + index * leading
        metrics = QFontMetricsF(items[0][1])
        baseline = top + (leading + metrics.ascent() - metrics.descent()) / 2
        pen_x = x + (width - total) / 2 if align == Qt.AlignHCenter else x
        previous_space = 0.0
        for word, font, colour, advance, space, glued in items:
            if not glued:
                pen_x += previous_space
            painter.setFont(font)
            painter.setPen(colour)
            painter.drawText(QPointF(pen_x, baseline), word)
            pen_x += advance
            previous_space = space
    return y + len(lines) * leading


def polyline(painter: QPainter, points: list[QPointF], grown: float) -> None:
    """Draw a stroke as if it were being written, ``grown`` of the way through."""
    grown = clamp(grown)
    if grown <= 0 or len(points) < 2:
        return
    lengths = []
    for index in range(len(points) - 1):
        delta = points[index + 1] - points[index]
        lengths.append((delta.x() ** 2 + delta.y() ** 2) ** 0.5)
    budget = sum(lengths) * grown
    for index, length in enumerate(lengths):
        if budget <= 0:
            break
        start, end = points[index], points[index + 1]
        if budget < length and length > 0:
            share = budget / length
            end = QPointF(start.x() + (end.x() - start.x()) * share,
                          start.y() + (end.y() - start.y()) * share)
        painter.drawLine(start, end)
        budget -= length


def _towards(origin: QPointF, target: QPointF, distance: float) -> QPointF:
    """``distance`` along the way from ``origin`` to ``target``, at most half."""
    delta = target - origin
    length = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
    if length <= 1e-6:
        return QPointF(origin)
    share = min(distance, length / 2.0) / length
    return QPointF(origin.x() + delta.x() * share, origin.y() + delta.y() * share)


def rounded(points: list[QPointF], radius: float, steps: int = 8) -> list[QPointF]:
    """The same run of segments, with every corner turned into a short arc.

    A callout that turns a square corner reads as two separate strokes that
    happen to meet: the eye is carried through a bend but stopped dead by a right
    angle. The radius is clamped to half of each adjoining segment, so a leg
    shorter than the radius curves gently rather than overshooting into the one
    before it.

    Points rather than a ``QPainterPath``, because :func:`polyline` draws by
    *length* -- what it grows along has to be measurable, and a curve is only
    measurable once flattened, which is what this is.
    """
    if len(points) < 3 or radius <= 0:
        return list(points)
    out = [points[0]]
    for index in range(1, len(points) - 1):
        before, corner, after = points[index - 1], points[index], points[index + 1]
        entry = _towards(corner, before, radius)
        exit_ = _towards(corner, after, radius)
        out.append(entry)
        for step in range(1, steps):
            t = step / steps
            inv = 1.0 - t
            out.append(QPointF(
                inv * inv * entry.x() + 2 * inv * t * corner.x() + t * t * exit_.x(),
                inv * inv * entry.y() + 2 * inv * t * corner.y() + t * t * exit_.y()))
        out.append(exit_)
    out.append(points[-1])
    return out


def tick(painter: QPainter, rect: QRectF, colour: QColor, grown: float = 1.0,
         width: float = 3.0) -> None:
    """The one checkmark shape in the window, drawn rather than faded in.

    A checkmark that appears is a checkmark; one that is *drawn* is something
    being ticked off, which is the sentence the last screen is trying to say.
    """
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    left, top, w, h = rect.left(), rect.top(), rect.width(), rect.height()
    polyline(painter, [QPointF(left + w * 0.16, top + h * 0.54),
                       QPointF(left + w * 0.40, top + h * 0.78),
                       QPointF(left + w * 0.86, top + h * 0.24)], grown)


def cross(painter: QPainter, rect: QRectF, colour: QColor,
          width: float = 3.0) -> None:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(rect.topLeft(), rect.bottomRight())
    painter.drawLine(rect.topRight(), rect.bottomLeft())


def arrow_head(painter: QPainter, tip: QPointF, direction: QPointF,
               size: float, colour: QColor) -> None:
    """A solid triangle at the end of a pointer, aimed along ``direction``."""
    length = max(1e-6, (direction.x() ** 2 + direction.y() ** 2) ** 0.5)
    ux, uy = direction.x() / length, direction.y() / length
    painter.setPen(Qt.NoPen)
    painter.setBrush(colour)
    painter.drawPolygon(QPolygonF([
        tip,
        QPointF(tip.x() - ux * size - uy * size * 0.55,
                tip.y() - uy * size + ux * size * 0.55),
        QPointF(tip.x() - ux * size + uy * size * 0.55,
                tip.y() - uy * size - ux * size * 0.55)]))


def pointer(painter: QPainter, points: list[QPointF], grown: float,
            colour: QColor, *, width: float = 2.6, head: float = 14.0,
            dashed: bool = False, offset: float = 0.0,
            corner: float = 16.0, halo: bool = True) -> None:
    """The mockups' callout: a run of segments that grows, then gets a head.

    Three things keep it readable, and none of them is decoration. The corners
    are rounded, and the last leg has to be long enough to carry the head -- an
    arrowhead that starts before the bend it follows makes the stroke look as
    though it changes direction at its own tip. The ends are round, because a
    flat cap on a 2.6 px line reads as a cut-off rather than as a start. And the
    whole stroke is laid down twice: a wide translucent wash of its own colour,
    then the line itself on top.

    That wash is what makes these visible at all. A one-pixel-ish line has to
    cross a near-black background *and* League's gold panels in the same journey,
    and a colour that survives one of those is lost on the other; the halo gives
    the line its own ground to sit on, so it is legible over both without being
    thickened into something crude.
    """
    grown = clamp(grown)
    if grown <= 0.01 or len(points) < 2:
        return
    points = rounded(points, corner)
    painter.setBrush(Qt.NoBrush)
    if halo:
        wash = QPen(QColor(colour.red(), colour.green(), colour.blue(), 44),
                    width * 3.4)
        wash.setCapStyle(Qt.RoundCap)
        wash.setJoinStyle(Qt.RoundJoin)
        if dashed:
            # Dashes measured in the halo's own width, or the wash comes out as a
            # row of fat lozenges with the thin line threading between them.
            wash.setDashPattern([1.9, 1.9])
            wash.setDashOffset(offset / 2.6)
        painter.setPen(wash)
        polyline(painter, points, grown)
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    if dashed:
        pen.setDashPattern([5.0, 5.0])
        pen.setDashOffset(offset)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    polyline(painter, points, grown)
    if grown > 0.985 and head:
        aim = points[-1] - points[-2]
        if halo:
            arrow_head(painter, points[-1], aim, head * 1.5,
                       QColor(colour.red(), colour.green(), colour.blue(), 44))
        arrow_head(painter, points[-1], aim, head, colour)


def badge(painter: QPainter, centre: QPointF, text: str, grown: float,
          radius: float = 17.0) -> None:
    """A numbered purple disc: the mockups' way of pointing at one control."""
    if grown <= 0.02:
        return
    painter.save()
    painter.setOpacity(painter.opacity() * grown)
    size = radius * (0.72 + 0.28 * grown)
    rect = QRectF(centre.x() - size, centre.y() - size, size * 2, size * 2)
    painter.setPen(Qt.NoPen)
    painter.setBrush(c("accent_btn", 90))
    painter.drawEllipse(rect.adjusted(-5, -5, 5, 5))
    painter.setBrush(c("accent_btn"))
    painter.drawEllipse(rect)
    centred(painter, rect, text, px(17, QFont.ExtraBold), c("ink"))
    painter.restore()


def choice_mark(painter: QPainter, rect: QRectF, weight: float) -> None:
    """The 38 px ring that becomes a filled tick as a card is picked."""
    painter.setPen(Qt.NoPen)
    painter.setBrush(mix(QColor(0, 0, 0, 0), c("accent_btn"), weight))
    painter.drawEllipse(rect)
    if weight < 0.99:
        painter.setPen(QPen(c("ring_off", int(255 * (1 - weight))), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)
    if weight > 0.02:
        tick(painter, rect.adjusted(11, 11, -11, -11), c("ink"), weight, 3.0)


def flag(painter: QPainter, rect: QRectF, language: str) -> None:
    """Two flags out of rectangles. No asset, no licence question, any DPI."""
    shadow(painter, rect, 6, spread=9, drop=6, alpha=110)
    painter.save()
    path = QPainterPath()
    path.addRoundedRect(rect, 6, 6)
    painter.setClipPath(path)
    painter.setPen(Qt.NoPen)
    if language == FRENCH:
        third = rect.width() / 3.0
        for index, colour in enumerate(("#0b3b8c", "#f5f5f5", "#d6262f")):
            painter.setBrush(QColor(colour))
            painter.drawRect(QRectF(rect.left() + index * third, rect.top(),
                                    third + 1, rect.height()))
    else:
        stripe = rect.height() / 13.0
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(rect)
        painter.setBrush(QColor("#b22234"))
        for index in range(0, 13, 2):
            painter.drawRect(QRectF(rect.left(), rect.top() + index * stripe,
                                    rect.width(), stripe))
        canton = QRectF(rect.left(), rect.top(), rect.width() * 0.44,
                        stripe * 7)
        painter.setBrush(QColor("#3c3b6e"))
        painter.drawRect(canton)
        painter.setBrush(QColor("#ffffff"))
        step_x = canton.width() / 6.0
        step_y = canton.height() / 5.0
        for row in range(5):
            for column in range(6):
                if (row + column) % 2:
                    continue
                painter.drawEllipse(
                    QPointF(canton.left() + step_x * (column + 0.5),
                            canton.top() + step_y * (row + 0.5)),
                    step_x * 0.16, step_x * 0.16)
    painter.restore()


def glyph(painter: QPainter, rect: QRectF, kind: str, colour: QColor, *,
          width: float = 2.6) -> None:
    """The line-art icons. Geometry, because nothing here is shipped as a file."""
    painter.save()
    painter.setBrush(Qt.NoBrush)
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    centre = rect.center()
    if kind == "play":
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawPolygon(QPolygonF([
            QPointF(rect.left() + rect.width() * 0.26, rect.top()),
            QPointF(rect.right(), centre.y()),
            QPointF(rect.left() + rect.width() * 0.26, rect.bottom())]))
    elif kind == "branch":
        painter.drawLine(QPointF(rect.left(), centre.y()),
                         QPointF(centre.x(), centre.y()))
        painter.drawLine(QPointF(centre.x(), centre.y()),
                         QPointF(rect.right(), rect.top()))
        painter.drawLine(QPointF(centre.x(), centre.y()),
                         QPointF(rect.right(), rect.bottom()))
        painter.setBrush(colour)
        for point in (QPointF(rect.right(), rect.top()),
                      QPointF(rect.right(), rect.bottom()),
                      QPointF(rect.left(), centre.y())):
            painter.drawEllipse(point, width, width)
    elif kind == "gear":
        radius = rect.width() * 0.28
        painter.drawEllipse(centre, radius, radius)
        for step in range(6):
            painter.save()
            painter.translate(centre)
            painter.rotate(step * 60.0)
            painter.drawLine(QPointF(radius + 1, 0),
                             QPointF(radius + rect.width() * 0.18, 0))
            painter.restore()
    elif kind == "monitor":
        screen = QRectF(rect.left(), rect.top() + rect.height() * 0.06,
                        rect.width(), rect.height() * 0.66)
        painter.drawRoundedRect(screen, 4, 4)
        painter.drawLine(QPointF(centre.x(), screen.bottom()),
                         QPointF(centre.x(), rect.bottom() - width))
        painter.drawLine(QPointF(centre.x() - rect.width() * 0.20,
                                 rect.bottom() - width),
                         QPointF(centre.x() + rect.width() * 0.20,
                                 rect.bottom() - width))
    elif kind == "window":
        frame = QRectF(rect.left(), rect.top() + rect.height() * 0.10,
                       rect.width(), rect.height() * 0.78)
        painter.drawRoundedRect(frame, 4, 4)
        painter.drawLine(
            QPointF(frame.left(), frame.top() + frame.height() * 0.26),
            QPointF(frame.right(), frame.top() + frame.height() * 0.26))
    elif kind == "move":
        radius = rect.width() * 0.24
        painter.drawEllipse(centre, radius, radius)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            painter.drawLine(
                QPointF(centre.x() + dx * (radius + 3),
                        centre.y() + dy * (radius + 3)),
                QPointF(centre.x() + dx * (radius + rect.width() * 0.22),
                        centre.y() + dy * (radius + rect.height() * 0.22)))
    elif kind == "chat":
        bubble = QRectF(rect.left(), rect.top(), rect.width(),
                        rect.height() * 0.70)
        painter.drawRoundedRect(bubble, 5, 5)
        painter.drawLine(
            QPointF(rect.left() + rect.width() * 0.26, bubble.bottom()),
            QPointF(rect.left() + rect.width() * 0.22, rect.bottom()))
    elif kind == "settings":
        radius = rect.width() * 0.26
        painter.drawEllipse(centre, radius, radius)
        painter.setBrush(colour)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            painter.drawEllipse(
                QPointF(centre.x() + dx * (radius + 5),
                        centre.y() + dy * (radius + 5)), 3.2, 3.2)
    elif kind == "sliders":
        for index, at in enumerate((0.32, 0.68)):
            y = rect.top() + rect.height() * at
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setBrush(colour)
            painter.drawEllipse(
                QPointF(rect.left() + rect.width() * (0.66 if index else 0.34),
                        y), width * 1.3, width * 1.3)
            painter.setBrush(Qt.NoBrush)
    elif kind == "sparkle":
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        for reach, angle in ((1.0, 0.0), (1.0, 90.0), (0.62, 45.0),
                             (0.62, 135.0)):
            painter.save()
            painter.translate(centre)
            painter.rotate(angle)
            half = rect.width() * 0.5 * reach
            painter.drawPolygon(QPolygonF([
                QPointF(0, -half), QPointF(half * 0.16, 0),
                QPointF(0, half), QPointF(-half * 0.16, 0)]))
            painter.restore()
    painter.restore()


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------
class Motion(QVariantAnimation):
    """One animated float, handed to a callback, owned by the widget it drives.

    Qt's property animations want a declared Qt property; everything animated in
    this window is a number only a ``paintEvent`` reads, so a property per effect
    would be ceremony for a value with no business being public. Parented to its
    widget, so it dies with it -- and it stops itself if the widget goes away
    mid-flight.
    """

    def __init__(self, owner: QWidget, apply, *, duration: int = 280,
                 easing=QEasingCurve.OutCubic) -> None:
        super().__init__(owner)
        self._apply = apply
        self.setDuration(int(duration))
        self.setEasingCurve(easing)
        self.setStartValue(0.0)
        self.setEndValue(1.0)

    def updateCurrentValue(self, value) -> None:      # noqa: N802 -- Qt's name
        try:
            self._apply(float(value))
        except RuntimeError:
            self.stop()

    def run(self, start: float, end: float) -> None:
        self.stop()
        self.setStartValue(float(start))
        self.setEndValue(float(end))
        try:
            self._apply(float(start))
        except RuntimeError:
            return
        self.start()


class Weights:
    """A bag of animated 0..1 numbers, keyed by name.

    Selection and hover are the same shape repeated a dozen times -- a card, a
    row, a button -- and each one needs its own easing rather than a shared one,
    or picking a card would drag the hover state of the other one with it.
    """

    def __init__(self, owner: QWidget, *, duration: int = 200) -> None:
        self._owner = owner
        self._duration = duration
        self._values: dict[str, float] = {}
        self._motions: dict[str, Motion] = {}

    def get(self, key: str) -> float:
        return self._values.get(key, 0.0)

    def set(self, key: str, target: float, *, animate: bool = True) -> None:
        target = clamp(target)
        if abs(self.get(key) - target) < 0.001:
            return
        # Nothing animates in a window nobody is looking at: the state has to be
        # *arrived at* rather than left mid-transition, or a guide built before
        # being shown would open half-way through its own entrance.
        if not self._owner.isVisible():
            animate = False
        motion = self._motions.get(key)
        if motion is None:
            motion = Motion(self._owner, lambda value, k=key: self._land(k, value),
                            duration=self._duration)
            self._motions[key] = motion
        if animate:
            motion.run(self.get(key), target)
        else:
            motion.stop()
            self._land(key, target)

    def _land(self, key: str, value: float) -> None:
        self._values[key] = value
        self._owner.update()


class Hot:
    """A clickable rectangle in design coordinates.

    ``drag`` is what makes a slider possible in a window with no widgets in it:
    a spot that has one is fed the pointer on press and again on every move
    until the button comes up, and it is *not* fired on release -- the value was
    already applied on the way past, and applying it twice would fight the last
    position the pointer was actually at.
    """

    __slots__ = ("rect", "action", "key", "drag")

    def __init__(self, rect: QRectF, action, key: str = "", drag=None) -> None:
        self.rect = rect
        self.action = action
        self.key = key
        self.drag = drag


# ---------------------------------------------------------------------------
# The controls
#
# The settings window has real widgets for all of these; this window has none,
# on purpose (see the module docstring), so the four shapes it needs are painted
# from the same palette as everything else and driven by :class:`Hot`. They are
# deliberately the *same* four shapes the maquettes use -- a pill, a chip, a
# track with a knob, a pair of steppers -- so a setting looks like itself
# wherever it is met.
# ---------------------------------------------------------------------------
def switch_pill(painter: QPainter, rect: QRectF, on: float,
                hover: float = 0.0) -> None:
    """The toggle, at the settings window's own proportions."""
    radius = rect.height() / 2
    box(painter, rect, radius, fill=mix(c("inset"), c("accent_btn"), on),
        edge=mix(c("card_edge"), c("accent"), max(on, hover * 0.7)),
        edge_width=1.0 + 0.4 * on)
    knob = radius - 4
    travel = rect.width() - 8 - knob * 2
    painter.setPen(Qt.NoPen)
    painter.setBrush(mix(c("dim"), c("ink"), max(on, 0.55)))
    painter.drawEllipse(QPointF(rect.left() + 4 + knob + travel * on,
                                rect.center().y()), knob, knob)


def chip(painter: QPainter, rect: QRectF, text: str, on: float,
         hover: float = 0.0) -> None:
    """One choice out of a short row of them."""
    box(painter, rect, 9, fill=mix(c("card"), c("accent_btn"), on),
        edge=mix(c("card_edge"), c("accent"), max(on, hover * 0.7)),
        edge_width=1.0 + 0.4 * on)
    centred(painter, rect, text, px(17, QFont.DemiBold),
            mix(c("text"), c("ink"), on))


def slider(painter: QPainter, rect: QRectF, fraction: float,
           hover: float = 0.0) -> None:
    """A track with a knob on it. ``rect`` is the whole grabbable strip."""
    fraction = clamp(fraction)
    y = rect.center().y()
    left, right = rect.left() + 11, rect.right() - 11
    pen = QPen(c("inset"), 6.0)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(left, y), QPointF(right, y))
    at = left + (right - left) * fraction
    pen = QPen(c("accent_btn"), 6.0)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(left, y), QPointF(at, y))
    painter.setPen(QPen(mix(c("accent"), c("accent_lit"), hover), 1.6))
    painter.setBrush(c("ink"))
    painter.drawEllipse(QPointF(at, y), 10.0, 10.0)


def stepper(painter: QPainter, rect: QRectF, text: str, *,
            back: float = 0.0, forward: float = 0.0,
            arrows: tuple[str, str] = ("−", "+")) -> None:
    """A value with a button on each side of it. ``rect`` is all three."""
    box(painter, rect, 9, fill=c("card"), edge=c("card_edge"))
    for side, hover, mark in ((0, back, arrows[0]), (1, forward, arrows[1])):
        button = stepper_button(rect, side)
        box(painter, button, 8, fill=mix(QColor(0, 0, 0, 0), c("accent_btn"),
                                         hover * 0.55))
        centred(painter, button, mark, px(20, QFont.ExtraBold),
                mix(c("text"), c("ink"), hover))
    centred(painter, rect, text, px(17, QFont.DemiBold), c("ink"))


def stepper_button(rect: QRectF, side: int) -> QRectF:
    """Where one of a stepper's two buttons is. Shared by paint and hit test."""
    size = rect.height() - 8
    x = rect.left() + 4 if side == 0 else rect.right() - 4 - size
    return QRectF(x, rect.top() + 4, size, size)


# ---------------------------------------------------------------------------
# The figures
# ---------------------------------------------------------------------------
def paint_client(painter: QPainter, rect: QRectF, guide) -> None:
    """League's client, schematically, with the path to the Practice Tool lit.

    Drawn rather than screenshotted, and drawn in League's gold rather than in
    the accent: gold is the game being pointed at, purple is Flashwatch pointing.
    Keeping those apart is what lets a badge read as an instruction rather than
    as part of the client.
    """
    painter.save()
    path = QPainterPath()
    path.addRoundedRect(rect, 6, 6)
    painter.setClipPath(path)

    wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    wash.setColorAt(0.0, QColor("#0b1424"))
    wash.setColorAt(1.0, QColor("#111d2e"))
    painter.fillRect(rect, wash)

    reveal = guide.reveal
    top = QRectF(rect.left(), rect.top(), rect.width(), 64)
    painter.fillRect(top, QColor("#080d18"))
    painter.setPen(QPen(c("hairline", 130), 1.0))
    painter.drawLine(top.bottomLeft(), top.bottomRight())

    # The PLAY button, the client's one gold thing.
    play = QRectF(rect.left() + 112, top.center().y() - 17, 168, 34)
    box(painter, play, 4, fill=QColor("#0a1524"), edge=c("gold", 200),
        edge_width=1.6)
    centred(painter, play, tr("guide.shot_play"),
            px(17, QFont.ExtraBold, spacing=1.4), c("gold_text"))
    x = play.right() + 34
    for label in ("LOL", "CLASSIC", "TFT"):
        x += line(painter, x, top.center().y() - 9, label,
                  px(15, QFont.DemiBold, spacing=0.8), c("faint")) + 28
    painter.setPen(Qt.NoPen)
    painter.setBrush(c("hairline", 150))
    for index in range(6):
        painter.drawRoundedRect(
            QRectF(rect.right() - 48 - index * 42, top.center().y() - 11,
                   22, 22), 4, 4)

    # The queue tabs, with TRAINING picked out.
    tabs = QRectF(rect.left(), top.bottom(), rect.width(), 52)
    painter.setBrush(QColor("#070c16"))
    painter.setPen(Qt.NoPen)
    painter.drawRect(tabs)
    x = rect.left() + 56
    training = QRectF()
    for label, live in ((("PVP"), False), ("COOP VS IA", False),
                        (tr("guide.shot_training"), True)):
        font = px(15, QFont.ExtraBold if live else QFont.Medium, spacing=1.0)
        width = QFontMetricsF(font).horizontalAdvance(label)
        line(painter, x, tabs.center().y() - 10, label, font,
             c("ink") if live else c("faint"))
        if live:
            training = QRectF(x, tabs.top(), width, tabs.height())
            painter.setPen(QPen(c("gold"), 2.0))
            painter.drawLine(QPointF(x - 6, tabs.bottom() - 8),
                             QPointF(x + width + 6, tabs.bottom() - 8))
        x += width + 44
    painter.setPen(Qt.NoPen)
    painter.setBrush(c("hairline", 110))
    for index in range(2):
        painter.drawRoundedRect(QRectF(x + index * 200, tabs.center().y() - 5,
                                       168, 10), 5, 5)

    # The two training modes, the second one being where the reader is going.
    board = QRectF(rect.left(), tabs.bottom(), rect.width(),
                   rect.bottom() - tabs.bottom())
    painter.setPen(QPen(c("hairline", 45), 1.4))
    for index in range(4):
        y = board.top() + board.height() * (0.42 + index * 0.15)
        painter.drawLine(QPointF(board.left(), y),
                         QPointF(board.right(), y - board.height() * 0.05))

    practice = QRectF()
    for label, share, live in ((tr("guide.shot_tutorial"), 0.33, False),
                               (tr("guide.shot_practice"), 0.66, True)):
        cx = board.left() + board.width() * share
        icon = QRectF(cx - 46, board.top() + 74, 92, 92)
        if live:
            painter.setPen(Qt.NoPen)
            painter.setBrush(c("accent", 46))
            painter.drawEllipse(icon.adjusted(-16, -16, 16, 16))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(c("gold_lit") if live else c("gold", 150), 3.0))
        painter.save()
        painter.translate(icon.center())
        painter.rotate(45)
        half = icon.width() * 0.36
        painter.drawRect(QRectF(-half, -half, half * 2, half * 2))
        painter.restore()
        if live:
            painter.setPen(Qt.NoPen)
            painter.setBrush(c("gold", 110))
            painter.drawEllipse(icon.center(), 15, 15)
        font = px(21, QFont.ExtraBold if live else QFont.Medium, spacing=1.2)
        width = QFontMetricsF(font).horizontalAdvance(label)
        line(painter, cx, icon.bottom() + 26, label, font,
             c("ink") if live else c("gold", 170), align=Qt.AlignHCenter)
        if live:
            practice = QRectF(cx - width / 2, icon.bottom() + 26, width, 28)
            painter.setPen(QPen(c("gold", 120), 1.2))
            painter.drawLine(QPointF(cx - width / 2, icon.bottom() + 62),
                             QPointF(cx + width / 2, icon.bottom() + 62))
            # The client's blurb under the mode it is describing.
            flow(painter, cx - width / 2, icon.bottom() + 78, width,
                 [(tr("guide.welcome_blurb"), px(15), c("dim"))], 24)

    confirm = QRectF(board.center().x() - 110, rect.bottom() - 78, 220, 42)
    box(painter, confirm, 4, fill=QColor("#0a1524"), edge=c("gold", 180),
        edge_width=1.4)
    centred(painter, confirm, tr("guide.shot_confirm"),
            px(16, QFont.ExtraBold, spacing=1.6), c("gold_text"))

    # The three callouts, at the mockup's own anchor points.
    if not training.isNull():
        badge(painter, QPointF(rect.left() + 41, rect.top() + 46), "1",
              stage(reveal, 0.30, 0.3))
        # Starting at the badge's own edge rather than a comfortable distance
        # from it: the gap to the button is short, and what it was spending on
        # that margin the shaft needed to not be mostly arrowhead.
        pointer(painter, [QPointF(rect.left() + 63, rect.top() + 46),
                          QPointF(play.left() - 6, rect.top() + 46)],
                stage(reveal, 0.36, 0.25), c("accent_lit"))

        # The lane this one runs along sits well clear of the tabs rather than
        # just under them: the leg that carries the head has to be longer than
        # the head, or the arrow appears to break at its own point.
        lane = tabs.bottom() + 46
        anchor = QPointF(rect.left() + 41, tabs.bottom() + 98)
        badge(painter, anchor, "2", stage(reveal, 0.46, 0.3))
        pointer(painter, [QPointF(anchor.x(), anchor.y() - 22),
                          QPointF(anchor.x(), lane),
                          QPointF(training.center().x(), lane),
                          QPointF(training.center().x(), tabs.bottom() - 2)],
                stage(reveal, 0.52, 0.3), c("accent_lit"))
    if not practice.isNull():
        badge(painter, QPointF(rect.right() - 48, practice.center().y()), "3",
              stage(reveal, 0.62, 0.3))
        pointer(painter, [QPointF(rect.right() - 83, practice.center().y()),
                          QPointF(practice.right() + 16,
                                  practice.center().y())],
                stage(reveal, 0.68, 0.25), c("accent_lit"))
    # 4 -- the button that actually starts the game. The path is only a path if
    # it ends somewhere, and three badges stopping at the mode left the last
    # click unsaid. It comes in down the right edge like 3, so the two read as
    # one column of instructions rather than as two unrelated arrows.
    badge(painter, QPointF(rect.right() - 48, confirm.center().y()), "4",
          stage(reveal, 0.72, 0.3))
    pointer(painter, [QPointF(rect.right() - 83, confirm.center().y()),
                      QPointF(confirm.right() + 18, confirm.center().y())],
            stage(reveal, 0.78, 0.22), c("accent_lit"))
    painter.restore()


def paint_options(painter: QPainter, rect: QRectF, guide) -> None:
    """League's video options, redrawn, with the one control that matters ringed.

    The labels are the client's own words -- ``Mode fenêtré``, ``Sans bord`` --
    because that is what has to be found on a screen this program never sees.
    """
    reveal = guide.reveal
    painter.save()
    box(painter, rect, 6, fill=QColor("#071019"), edge=c("gold", 130),
        edge_width=2.0)
    painter.setClipRect(rect)
    box(painter, rect.adjusted(6, 6, -6, -6), 4, edge=c("gold", 60))

    title = QRectF(rect.left(), rect.top() + 12, rect.width(), 54)
    centred(painter, title, tr("guide.shot_options"),
            px(34, QFont.Bold, spacing=4.0), c("gold_lit"))
    painter.setPen(QPen(c("gold", 90), 1.2))
    painter.drawLine(QPointF(rect.left() + 20, title.bottom()),
                     QPointF(rect.right() - 20, title.bottom()))
    # The close button, which is what makes the panel read as a window.
    close = QRectF(rect.right() - 66, rect.top() + 18, 44, 44)
    painter.setBrush(QColor("#0a1524"))
    painter.setPen(QPen(c("gold", 190), 2.0))
    painter.drawEllipse(close)
    cross(painter, close.adjusted(13, 13, -13, -13), c("gold_lit"), 2.6)

    nav_w = rect.width() * 0.24
    nav = QRectF(rect.left() + 18, title.bottom() + 16, nav_w,
                 rect.height() - title.height() - 96)
    entries = (("guide.shot_tab_hotkeys", False),
               ("guide.shot_tab_camera", False),
               ("guide.shot_tab_video", True),
               ("guide.shot_tab_audio", False),
               ("guide.shot_tab_interface", False),
               ("guide.shot_tab_game", False))
    row_h = 46.0
    video = QRectF()
    for index, (key, live) in enumerate(entries):
        row = QRectF(nav.left(), nav.top() + index * row_h, nav.width(), row_h)
        if live:
            video = row
            painter.setPen(Qt.NoPen)
            painter.setBrush(c("gold", 26))
            painter.drawRect(row)
            painter.setBrush(c("gold_text"))
            painter.drawPolygon(QPolygonF([
                QPointF(row.left() + 8, row.center().y() - 7),
                QPointF(row.left() + 18, row.center().y()),
                QPointF(row.left() + 8, row.center().y() + 7)]))
        line(painter, row.left() + 28, row.center().y() - 12, tr(key),
             px(19, QFont.DemiBold if live else QFont.Medium, spacing=1.0),
             c("gold_text") if live else c("faint"))
    painter.setPen(QPen(c("gold", 60), 1.2))
    painter.drawLine(QPointF(nav.right() + 16, title.bottom() + 16),
                     QPointF(nav.right() + 16, rect.bottom() - 96))

    body = QRectF(nav.right() + 40, title.bottom() + 20,
                  rect.right() - nav.right() - 62, 0)
    line(painter, body.left(), body.top(), tr("guide.shot_general"),
         px(20, QFont.DemiBold), c("gold_text"))

    field_w = (body.width() - 40) / 2
    combo_top = body.top() + 62
    mode = QRectF()
    for index, (label, value, live) in enumerate((
            (tr("guide.shot_resolution"), "1920x1080", False),
            (tr("guide.shot_mode"), tr("guide.shot_borderless"), True))):
        left = body.left() + index * (field_w + 40)
        line(painter, left, combo_top - 30, label, px(17), c("dim"))
        field = QRectF(left, combo_top, field_w, 42)
        box(painter, field, 2, fill=QColor("#0a1a26"), edge=c("gold", 150),
            edge_width=1.4)
        centred(painter, field, value,
                px(19, QFont.DemiBold if live else QFont.Medium),
                c("gold_lit") if live else c("dim"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(c("gold", 190))
        painter.drawPolygon(QPolygonF([
            QPointF(field.right() - 30, field.center().y() - 4),
            QPointF(field.right() - 14, field.center().y() - 4),
            QPointF(field.right() - 22, field.center().y() + 5)]))
        if live:
            mode = field
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(c("accent"), 2.4))
            painter.drawRoundedRect(field.adjusted(-7, -7, 7, 7), 5, 5)

    # Two rows of the panel's checkboxes, as furniture: they are what make the
    # figure recognisable as the real page rather than as a form.
    for row in range(2):
        for column in range(2):
            mark = QRectF(body.left() + column * (field_w + 40),
                          combo_top + 74 + row * 38, 20, 20)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(c("gold", 120), 1.4))
            painter.drawRect(mark)
            if row == 0 and column == 1:
                painter.setBrush(c("gold", 200))
                painter.setPen(Qt.NoPen)
                painter.drawRect(mark.adjusted(5, 5, -5, -5))
            painter.setPen(QPen(c("hairline", 150), 9))
            painter.drawLine(QPointF(mark.right() + 16, mark.center().y()),
                             QPointF(mark.right() + 16 + field_w * 0.62,
                                     mark.center().y()))

    # The graphics block, which is what sits under the window mode in the real
    # panel. Leaving it out makes the figure read as a dialog nobody has seen.
    quality = QRectF(body.left(), combo_top + 168, body.width(), 96)
    line(painter, body.left(), quality.top() - 34, tr("guide.shot_graphics"),
         px(20, QFont.DemiBold), c("gold_text"))
    box(painter, quality, 2, fill=QColor("#08131d"), edge=c("gold", 90))
    centred(painter, QRectF(quality.left(), quality.top() + 6, quality.width(),
                            34), tr("guide.shot_quality"), px(18), c("dim"))
    track = QRectF(quality.left() + 16, quality.top() + 52,
                   quality.width() - 32, 18)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(c("gold", 140), 1.4))
    painter.drawRect(track)
    painter.setPen(Qt.NoPen)
    painter.setBrush(c("gold"))
    painter.drawRect(QRectF(track.right() - 22, track.top() - 2, 18, 22))

    buttons = QRectF(body.left(), rect.bottom() - 70, body.width(), 44)
    for index, key in enumerate(("guide.shot_save", "guide.shot_cancel")):
        button = QRectF(buttons.right() - (2 - index) * 200 + 16, buttons.top(),
                        184, 44)
        box(painter, button, 2, edge=c("gold", 170), edge_width=1.4)
        centred(painter, button, tr(key), px(18), c("gold_text"))

    painter.restore()

    # The two callouts sit *outside* the panel, as they do in the mockup.
    if not video.isNull():
        # The badge stands further off than the mockup's, and the stroke runs all
        # the way to the edge of the highlighted row: a 58 px shaft carrying a
        # 14 px head is mostly head, and it stopped short of the tab, pointing at
        # the panel's border instead of at the thing to click.
        anchor = QPointF(rect.left() - 104, video.center().y())
        badge(painter, anchor, "1", stage(reveal, 0.30, 0.3))
        pointer(painter, [QPointF(anchor.x() + 26, anchor.y()),
                          QPointF(video.left() - 2, anchor.y())],
                stage(reveal, 0.36, 0.25), c("accent_lit"))
    if not mode.isNull():
        # Straight in from the right, at the field's own height, and the mirror
        # of callout 1 on the other side. It used to come down from the corner in
        # two diagonals: the first ran underneath the caption bubble, which meant
        # the one stroke that matters on this screen was half hidden by the
        # sentence explaining it, and neither leg was square to anything. The
        # bubble is placed below this line by ``BorderlessScreen`` -- the two have
        # to be read together, so they are positioned together.
        anchor = QPointF(mode.right() + 118, mode.center().y())
        badge(painter, anchor, "2", stage(reveal, 0.44, 0.3))
        pointer(painter, [QPointF(anchor.x() - 26, anchor.y()),
                          QPointF(mode.right() + 12, anchor.y())],
                stage(reveal, 0.50, 0.3), c("accent_lit"))


def paint_game(painter: QPainter, rect: QRectF, guide, mode: str) -> None:
    """The Practice Tool, with whatever this step is about drawn on top of it.

    One backdrop for three steps -- pick a display, place it, prove it -- because
    they are three things happening on the same screen, and drawing them on three
    different grounds would say they were not.
    """
    painter.save()
    path = QPainterPath()
    path.addRoundedRect(rect, 6, 6)
    painter.setClipPath(path)

    wash = QLinearGradient(rect.topLeft(), rect.bottomRight())
    wash.setColorAt(0.0, QColor("#223a2a"))
    wash.setColorAt(0.5, QColor("#1b2c2c"))
    wash.setColorAt(1.0, QColor("#16222a"))
    painter.fillRect(rect, wash)

    # A rift, in the loosest possible terms: a river band and two lanes, so the
    # panel reads as a game rather than as an empty box.
    painter.setPen(QPen(QColor(255, 255, 255, 14), 46))
    painter.drawLine(QPointF(rect.left(), rect.bottom() - rect.height() * 0.24),
                     QPointF(rect.right(), rect.top() + rect.height() * 0.16))
    painter.setPen(QPen(QColor(0, 0, 0, 40), 30))
    painter.drawLine(QPointF(rect.left() + rect.width() * 0.18, rect.bottom()),
                     QPointF(rect.right() - rect.width() * 0.10, rect.top()))
    painter.setBrush(QColor(0, 0, 0, 45))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(rect.left() + rect.width() * 0.30,
                                rect.top() + rect.height() * 0.30), 70, 44)
    painter.drawEllipse(QPointF(rect.right() - rect.width() * 0.24,
                                rect.bottom() - rect.height() * 0.34), 84, 52)

    # The HUD: a health bar with the champion under it, the minimap in the
    # corner, the ability row along the bottom.
    hud = QRectF(rect.left() + rect.width() * 0.18, rect.bottom() - 118,
                 rect.width() * 0.46, 92)
    box(painter, hud, 4, fill=QColor(6, 12, 18, 210), edge=c("gold", 120))
    for index in range(5):
        slot = QRectF(hud.left() + 12 + index * 54, hud.top() + 10, 46, 46)
        box(painter, slot, 3, fill=QColor("#1a2430"), edge=c("gold", 90))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#3fae5a"))
    painter.drawRect(QRectF(hud.left() + 12, hud.bottom() - 30,
                            hud.width() - 24, 10))
    painter.setBrush(QColor("#3f7fd6"))
    painter.drawRect(QRectF(hud.left() + 12, hud.bottom() - 18,
                            hud.width() - 24, 10))
    minimap = QRectF(rect.right() - 172, rect.bottom() - 172, 154, 154)
    box(painter, minimap, 4, fill=QColor(8, 14, 20, 210), edge=c("gold", 110))
    painter.setPen(QPen(QColor(255, 255, 255, 30), 2))
    painter.drawLine(minimap.bottomLeft() + QPointF(10, -10),
                     minimap.topRight() + QPointF(-10, 10))

    reveal = guide.reveal
    kind = guide.current_layout()
    placed = QRectF(rect.left() + rect.width() * 0.24, rect.top() + 26,
                    rect.width() * 0.52, 74)
    if mode == "proof":
        placed = QRectF(rect.left() + rect.width() * 0.30, rect.top() + 26,
                        rect.width() * 0.40, 74)
    elif mode == "place":
        # Lower, so the arrow that comes out of its top edge has somewhere to go:
        # an arrowhead clipped by the frame reads as a drawing that ran out of
        # room rather than as a direction.
        placed = QRectF(rect.left() + rect.width() * 0.24, rect.top() + 88,
                        rect.width() * 0.52, 74)
    # The rectangle back out of it, because a scale or a vertical track moves
    # the overlay off the one it was handed -- and the frame, the arrows and the
    # labels below all point at where it really landed.
    placed = paint_overlay(painter, placed, kind, mode == "proof",
                           guide.overlay_style())
    painter.setPen(QPen(c("accent"), 2.0))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(placed.adjusted(-5, -5, 5, 5), 8, 8)

    if mode == "place":
        # Four arrows out of it: it moves in every direction. One gap and one
        # reach for all four, rather than a pair of numbers per axis: four arrows
        # saying the same thing have to be the same length, or the short ones
        # read as a weaker direction -- and the shortest of them was barely
        # longer than its own head.
        grown = stage(reveal, 0.32, 0.35)
        centre = placed.center()
        for dx, dy in ((-1, 0), (1, 0), (0, 1), (0, -1)):
            start = QPointF(centre.x() + dx * (placed.width() / 2 + 14),
                            centre.y() + dy * (placed.height() / 2 + 14))
            end = QPointF(start.x() + dx * 46, start.y() + dy * 46)
            pointer(painter, [start, end], grown, c("accent_lit"), head=11)
        ghost = QRectF(rect.right() - rect.width() * 0.44 - 130,
                       rect.bottom() - 250, rect.width() * 0.40, 64)
        pen = QPen(c("accent_pale", 150), 2.0)
        pen.setDashPattern([5.0, 5.0])
        pen.setDashOffset(guide.march * 20.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(ghost, 8, 8)
        painter.save()
        painter.setOpacity(painter.opacity() * 0.5 * stage(reveal, 0.5, 0.35))
        paint_overlay(painter, ghost.adjusted(4, 4, -4, -4), kind, False,
                      guide.overlay_style())
        painter.restore()
        line(painter, ghost.left(), ghost.bottom() + 8,
             tr("guide.place_anywhere"), px(16), c("dim"))

    if mode == "proof":
        # The chat, framed, with the pasted line lit and a pointer up to the one
        # timer it produced: the whole chain, on one screen.
        chat = QRectF(rect.left() + 30, rect.bottom() - 250,
                      rect.width() * 0.44, 132)
        box(painter, chat, 5, fill=QColor(8, 10, 16, 215), edge=c("ok"),
            edge_width=2.4)
        line(painter, chat.left(), chat.top() - 30, tr("guide.shot_chat"),
             px(16), c("ok"))
        for index in range(3):
            y = chat.top() + 30 + index * 34
            grown = stage(reveal, 0.34 + index * 0.08, 0.3)
            live = index == 2
            painter.setPen(QPen(c("bad") if live else c("faint"), 5))
            painter.drawLine(
                QPointF(chat.left() + 20, y),
                QPointF(chat.left() + 20
                        + (chat.width() - 60) * (0.9 if live else 0.62) * grown,
                        y))
            if live:
                painter.setPen(QPen(c("ok"), 5))
                painter.drawLine(QPointF(chat.left() - 16, y),
                                 QPointF(chat.left() - 6, y))
        line(painter, chat.left(), chat.bottom() + 10,
             f"1 {tr('guide.proof_read')}", px(16), c("ok"))
        line(painter, placed.right(), placed.bottom() + 12, tr("guide.shot_bar"),
             px(16), c("accent_pale"), align=Qt.AlignRight)

        # Far enough right that the two bends stay two bends: closer in, the
        # horizontal run was shorter than the corners eating it from both ends
        # and the whole thing collapsed into one lazy S.
        elbow = chat.right() + 104
        grown = stage(reveal, 0.55, 0.4)
        # It leaves from the lit line rather than from thin air beside the frame:
        # the whole point of the drawing is that *this* message became *that*
        # timer, and a tail that starts in the grass says only "something above".
        pointer(painter, [QPointF(chat.right() + 12, chat.top() + 98),
                          QPointF(elbow, chat.top() + 98),
                          QPointF(elbow, placed.bottom() + 60),
                          QPointF(placed.center().x(), placed.bottom() + 60),
                          QPointF(placed.center().x(), placed.bottom() + 14)],
                grown, c("accent_lit"), dashed=True,
                offset=-guide.march * 20.0)
    painter.restore()


_FACES: list[str] | None = None


def countdown_faces() -> list[str]:
    """The countdown faces this machine has, "auto" first.

    Cached: the answer comes from the font database, which is a set built out of
    every family installed, and this is read while painting.
    """
    global _FACES
    if _FACES is None:
        _FACES = [FACE_AUTO] + [face[0] for face in available_countdown_faces()]
    return _FACES


def face_name(chosen: str) -> str:
    """The family the countdown is actually drawn in, "auto" resolved."""
    faces = countdown_faces()
    if chosen != FACE_AUTO and chosen in faces:
        return chosen
    return faces[1] if len(faces) > 1 else family()


def overlay_style(settings) -> dict:
    """Everything about the overlay's look, read off the settings.

    Gathered in one place and handed to :func:`paint_overlay` rather than read
    inside it: the same picture is drawn from live settings on the tuning step
    and from nothing at all in the little thumbnails, and a function that
    reached for the settings itself could not do both.
    """
    theme = THEMES.get(str(settings.get("theme", "light")), THEMES["light"])
    return {
        "theme": theme,
        "opacity": float(settings.get("overlay_opacity", 0.92)),
        "scale": float(settings.get("overlay_scale", 1.0)),
        "face": face_name(str(settings.get("timer_font", FACE_AUTO))),
        "timer_scale": float(settings.get("timer_font_scale", 0.5)),
        "vertical": bool(settings.get("bar_vertical", False)),
    }


def _themed(theme: dict, key: str) -> QColor:
    return QColor(*theme[key])


def paint_overlay(painter: QPainter, rect: QRectF, kind: str,
                  single: bool, style: dict | None = None) -> QRectF:
    """Flashwatch's own bar, drawn on the game the way it really looks.

    A near-opaque light panel carrying dark numerals -- the product's actual
    face, measured for contrast in ``theme.py`` -- rather than the mockup's
    placeholder cyan blocks. This is the one thing on these screens the reader
    will see again five minutes later, so it is the one thing that must not be a
    stand-in.

    With a ``style`` from :func:`overlay_style` it stops being a fixed picture
    and becomes the settings themselves: the theme's own colours, the panel at
    the opacity it will really composite at, the size and the face the countdown
    will really be drawn in, and the track stood on its end if that is what is
    asked for. That is the whole point of the tuning step -- a preview that does
    not move when the setting does is worse than no preview at all, because it
    is read as the setting having done nothing.

    Returns the rectangle it actually drew in, which is not the one it was given
    once a scale or a vertical track has had its say: the caller frames it.
    """
    painter.save()
    theme = style["theme"] if style else None
    vertical = bool(style and style["vertical"] and kind == LAYOUT_BAR)
    # Everything inside is sized from the panel's own height, because this is
    # drawn at two very different sizes: 74 px tall over the game, and 38 px tall
    # inside a row's thumbnail. Fixed type would be legible at one and a smear at
    # the other -- which is exactly what the first version of these rows did.
    k = clamp(rect.height() / 74.0, 0.42, 1.4)
    if style:
        grown = clamp(style["scale"], 0.5, 2.4)
        centre = rect.center()
        if vertical:
            # The track on its end keeps its top-left corner, the way the real
            # window does: it is the same overlay in another shape, not a second
            # one somewhere else. It is also as wide as the countdown beside
            # each portrait needs it to be -- the real window sizes itself to
            # its contents, and a strip that clipped its own numerals would be
            # showing a bug rather than a setting.
            room = max(1.0, clamp(style["timer_scale"] / 0.5, 0.4, 2.6))
            rect = QRectF(rect.left(), rect.top(),
                          108 * grown * min(room, 1.9), 252 * grown)
            k = clamp(grown, 0.42, 1.4)
        else:
            rect = QRectF(centre.x() - rect.width() * grown / 2,
                          centre.y() - rect.height() * grown / 2,
                          rect.width() * grown, rect.height() * grown)
            k = clamp(rect.height() / 74.0, 0.42, 1.4)
    shadow(painter, rect, 8 * k, spread=10 * k, drop=4 * k, alpha=90)
    if theme is None:
        fill = QColor(238, 241, 246, 235)
        edge = QColor(24, 36, 62, 90)
    else:
        # The real composite, not a flattering one: panel alpha times the
        # theme's own share times the opacity setting is what lands on the game,
        # and a preview drawn at full strength would make the slider look broken.
        fill = _themed(theme, "panel")
        fill.setAlpha(max(0, min(255, int(fill.alpha()
                                          * theme.get("panel_alpha", 0.8)
                                          * clamp(style["opacity"], 0.1, 1.0)))))
        edge = _themed(theme, "border")
    box(painter, rect, 8 * k, fill=fill, edge=edge)

    ink = _themed(theme, "far") if theme else QColor("#141a24")
    faint = _themed(theme, "rail") if theme else QColor("#606b7e")
    hair = _themed(theme, "border") if theme else QColor(24, 36, 62, 50)
    ready = _themed(theme, "ready") if theme else QColor("#0f6b3d")
    soon = _themed(theme, "mid") if theme else QColor("#8a4d00")
    entries = [("4:23", soon, 0.55), ("1:12", ready, 0.85), ("2:41", ink, 0.3)]
    if single:
        entries = [("4:23", soon, 0.55)]

    def numerals(size: float) -> QFont:
        """The countdown's own face and size, or the window's if untuned."""
        if not style:
            return px(size, QFont.Bold)
        font = QFont(style["face"])
        font.setPixelSize(max(1, int(round(
            size * clamp(style["timer_scale"] / 0.5, 0.4, 2.6)))))
        font.setWeight(QFont.Bold)
        return font

    if kind == LAYOUT_LIST:
        row_h = rect.height() / max(1, len(entries))
        for index, (value, colour, progress) in enumerate(entries):
            row = QRectF(rect.left() + 10 * k, rect.top() + index * row_h,
                         rect.width() - 20 * k, row_h)
            painter.setBrush(faint)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(row.left() + 14 * k, row.center().y()),
                                11 * k, 11 * k)
            painter.setPen(QPen(faint, 3 * k))
            painter.drawLine(QPointF(row.left() + 34 * k, row.center().y()),
                             QPointF(row.left() + 84 * k, row.center().y()))
            line(painter, row.right() - 8 * k, row.center().y() - 12 * k, value,
                 numerals(19 * k), colour, align=Qt.AlignRight)
    elif kind == LAYOUT_CARDS:
        step = rect.width() / max(1, len(entries))
        for index, (value, colour, progress) in enumerate(entries):
            cx = rect.left() + step * (index + 0.5)
            ring = QRectF(cx - 20 * k, rect.top() + 10 * k, 40 * k, 40 * k)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(hair, 4 * k))
            painter.drawEllipse(ring)
            painter.setPen(QPen(colour, 4 * k))
            painter.drawArc(ring, 90 * 16, -int(360 * 16 * progress))
            line(painter, cx, ring.bottom() + 4 * k, value,
                 numerals(17 * k), colour, align=Qt.AlignHCenter)
    elif vertical:
        # Position is still progress, only downwards: the same reading, turned
        # a quarter turn, which is the whole of what the setting does.
        x = rect.left() + 26 * k
        top, bottom = rect.top() + 22 * k, rect.bottom() - 22 * k
        painter.setPen(QPen(hair, 3 * k))
        painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        for value, colour, progress in entries:
            cy = top + (bottom - top) * (0.5 if single else progress)
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawEllipse(QPointF(x, cy), 9 * k, 9 * k)
            line(painter, x + 16 * k, cy - 11 * k, value, numerals(18 * k),
                 colour)
    else:
        y = rect.center().y() - 6 * k
        painter.setPen(QPen(hair, 3 * k))
        painter.drawLine(QPointF(rect.left() + 22 * k, y),
                         QPointF(rect.right() - 22 * k, y))
        for index, (value, colour, progress) in enumerate(entries):
            cx = rect.left() + 22 * k + (rect.width() - 44 * k) * (
                progress if not single else 0.5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawEllipse(QPointF(cx, y), 9 * k, 9 * k)
            line(painter, cx, y + 12 * k, value, numerals(16 * k), colour,
                 align=Qt.AlignHCenter)
    painter.restore()
    return rect


# ---------------------------------------------------------------------------
# The screens
# ---------------------------------------------------------------------------
class Screen:
    """One step. Paints itself in design coordinates and says what is clickable.

    The two halves are deliberately separate: a screen that decided what was
    clickable while painting would have its hit boxes go stale the moment a
    translation reflowed a paragraph.
    """

    key = ""

    def paint(self, painter: QPainter, guide) -> None:
        raise NotImplementedError

    def hots(self, guide) -> list[Hot]:
        return []

    # -- shared furniture ----------------------------------------------
    @staticmethod
    def heading(painter: QPainter, guide, x: float, y: float, icon: str,
                title: str, *, tile: bool = True, mark: str = "") -> float:
        """The step's glyph and its 42 px title, as every mockup opens."""
        grown = stage(guide.reveal, 0.0, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        size = 62.0
        if tile:
            rect = QRectF(x, y, size, size)
            box(painter, rect, 14, fill=c("accent_deep"), edge=c("accent"))
            if mark:
                # The mockup's own glyph for this one: two scripts side by side,
                # which says "language" without a flag having to pick a side.
                centred(painter, rect, mark, px(26, QFont.ExtraBold), c("ink"))
            else:
                glyph(painter, rect.adjusted(17, 17, -17, -17), icon,
                      c("accent_pale"), width=2.8)
        else:
            rect = QRectF(x, y + 10, 34, 34)
            glyph(painter, rect, icon, c("accent_soft"), width=3.0)
        line(painter, rect.right() + 24, y + size / 2 - 30, title,
             px(42, QFont.ExtraBold, spacing=-0.8), c("ink"))
        painter.restore()
        return y + size

    @staticmethod
    def note(painter: QPainter, guide, x: float, y: float, width: float,
             text: str, *, delay: float = 0.5) -> float:
        """The information box: a violet disc, a sentence, a quiet ground."""
        grown = stage(guide.reveal, delay, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        font = px(19, QFont.Medium)
        text_x = x + 26 + 38 + 20
        text_w = width - (text_x - x) - 26
        # Measured before it is drawn: the box goes behind the sentence, and the
        # sentence is what decides how tall the box is.
        lines = _count_lines(text, font, text_w)
        height = max(82.0, lines * 30 + 44)
        rect = QRectF(x, y, width, height)
        box(painter, rect, 12, fill=c("note"), edge=c("note_edge"))
        disc = QRectF(x + 26, y + height / 2 - 19, 38, 38)
        painter.setBrush(c("accent_deep"))
        painter.setPen(QPen(c("accent"), 1.2))
        painter.drawEllipse(disc)
        centred(painter, disc, "i", px(20, QFont.ExtraBold), c("accent_pale"))
        flow(painter, text_x, y + (height - lines * 30) / 2, text_w,
             [(text, font, c("text_2"))], 30)
        painter.restore()
        return y + height

    @staticmethod
    def caption(painter: QPainter, guide, x: float, y: float,
                text: str) -> float:
        line(painter, x, y, text, px(21, QFont.Medium), c("caption"))
        return y + 30


def _count_lines(text: str, font: QFont, width: float) -> int:
    """How many lines ``text`` needs at ``width``. Same rule as :func:`flow`."""
    metrics = QFontMetricsF(font)
    space = metrics.horizontalAdvance(" ")
    lines, used = 1, 0.0
    for word in text.replace("<b>", "").replace("</b>", "").split(" "):
        if not word:
            continue
        advance = metrics.horizontalAdvance(word)
        if used and used + space + advance > width:
            lines += 1
            used = advance
        else:
            used += (space if used else 0) + advance
    return lines


class LanguageScreen(Screen):
    """1 -- the client's language. Two cards, and the flag says which is which."""

    key = STEP_LANGUAGE

    def paint(self, painter: QPainter, guide) -> None:
        x, y = 48, 232
        strong = px(25, QFont.DemiBold)
        y = self.heading(painter, guide, x, y, "", tr("guide.language_title"),
                         mark="文A")
        y = flow(painter, x, y + 38, 430,
                 runs_of(tr("guide.language_lead"), px(25, QFont.Medium),
                         c("text"), strong=strong, strong_colour=c("accent_lit")),
                 41)
        y = flow(painter, x, y + 34, 430,
                 [(tr("guide.language_lead_2"), px(25, QFont.Medium), c("text"))],
                 41)
        self.note(painter, guide, x, y + 38, 430, tr("guide.language_note"))

        head = QRectF(552, 242, 890, 34)
        painter.save()
        painter.setOpacity(painter.opacity() * stage(guide.reveal, 0.1, 0.4))
        centred(painter, head, tr("guide.language_pick"),
                px(24, QFont.ExtraBold), c("ink"))
        painter.restore()
        for language, rect in self._cards():
            self._card(painter, guide, rect, language)

    @staticmethod
    def _cards() -> list[tuple[str, QRectF]]:
        width = (890 - 30) / 2
        return [(FRENCH, QRectF(552, 320, width, 382)),
                (ENGLISH, QRectF(552 + width + 30, 320, width, 382))]

    def _card(self, painter: QPainter, guide, rect: QRectF,
              language: str) -> None:
        weight = guide.weights.get(f"lang:{language}")
        hover = guide.weights.get(f"hover:lang:{language}")
        grown = stage(guide.reveal, 0.18 + (0.08 if language == ENGLISH else 0),
                      0.45)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        painter.translate(0, (1 - grown) * 14)

        wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        wash.setColorAt(0.0, mix(c("card"), c("card_on"), weight))
        wash.setColorAt(1.0, mix(c("card"), c("card_on_2"), weight))
        box(painter, rect, 14, fill=wash,
            edge=mix(c("card_edge"), c("accent"), max(weight, hover * 0.75)),
            edge_width=1.0 + weight)

        choice_mark(painter, QRectF(rect.right() - 60, rect.top() + 22, 38, 38),
                    weight)
        flag(painter, QRectF(rect.center().x() - 59, rect.top() + 52, 118, 78),
             language)
        name = tr(f"guide.language_{language}_name")
        line(painter, rect.center().x(), rect.top() + 52 + 78 + 34, name,
             px(28, QFont.ExtraBold), c("ink"), align=Qt.AlignHCenter)
        line(painter, rect.center().x(), rect.top() + 52 + 78 + 34 + 40 + 14,
             tr(f"guide.language_{language}_sub"), px(20, QFont.Medium),
             c("text_3"), align=Qt.AlignHCenter)
        painter.restore()

    def hots(self, guide) -> list[Hot]:
        return [Hot(rect, lambda lang=language: guide.pick_language(lang),
                    f"lang:{language}") for language, rect in self._cards()]


class WelcomeScreen(Screen):
    """2 -- where to go in the client. The one instruction that is navigation."""

    key = STEP_WELCOME

    def paint(self, painter: QPainter, guide) -> None:
        x, y = 48, 200
        y = self.heading(painter, guide, x, y, "sparkle",
                         tr("guide.welcome_title"), tile=False)
        y = flow(painter, x, y - 4, 410,
                 runs_of(tr("guide.welcome_lead"), px(23, QFont.Medium),
                         c("text"), strong=px(23, QFont.ExtraBold),
                         strong_colour=c("accent_soft")), 34)
        y = flow(painter, x, y + 22, 410,
                 [(tr("guide.welcome_path"), px(20, QFont.Medium), c("dim"))],
                 31)
        y = self._path_card(painter, guide, x, y + 26, 410)
        self._small_note(painter, guide, x, y + 26, 410,
                         tr("guide.welcome_note"))

        panel = QRectF(485, 163, 1020, 722)
        glow(painter, panel, 6, c("screen_edge"), spread=40, alpha=40)
        box(painter, panel, 6, fill=c("screen"))
        paint_client(painter, panel, guide)
        box(painter, panel, 6, edge=c("screen_edge"), edge_width=2.0)

    @staticmethod
    def _path_card(painter: QPainter, guide, x: float, y: float,
                   width: float) -> float:
        rows = ((tr("guide.welcome_path_play"), "play"),
                (tr("guide.welcome_path_training"), "branch"),
                (tr("guide.welcome_path_tool"), "gear"))
        height = 22 * 2 + 62 * 3 + 36 * 2
        rect = QRectF(x, y, width, height)
        box(painter, rect, 12, fill=c("panel"), edge=QColor("#232a45"))
        for index, (label, icon) in enumerate(rows):
            grown = stage(guide.reveal, 0.28 + index * 0.12, 0.45)
            painter.save()
            painter.setOpacity(painter.opacity() * grown)
            top = y + 22 + index * (62 + 36)
            tile = QRectF(x + 24, top, 62, 62)
            box(painter, tile, 8, fill=QColor("#0a0f1e"), edge=c("gold_frame"))
            glyph(painter, tile.adjusted(17, 17, -17, -17), icon,
                  c("gold_text"), width=2.8)
            line(painter, tile.right() + 22, top + 20, label,
                 px(21, QFont.ExtraBold, spacing=0.4), c("gold_text"))
            painter.restore()
            if index < len(rows) - 1:
                painter.setPen(QPen(QColor("#2a3150"), 1.2))
                painter.drawLine(QPointF(x + 24 + 30, tile.bottom()),
                                 QPointF(x + 24 + 30, tile.bottom() + 36))
                line(painter, x + 24 + 34, tile.bottom() + 8, "↓", px(16),
                     c("faint"))
        return y + height

    @staticmethod
    def _small_note(painter: QPainter, guide, x: float, y: float, width: float,
                    text: str) -> None:
        grown = stage(guide.reveal, 0.55, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        disc = QRectF(x, y + 2, 24, 24)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c("accent_btn"))
        painter.drawEllipse(disc)
        centred(painter, disc, "i", px(14, QFont.ExtraBold), c("ink"))
        flow(painter, x + 38, y, width - 38,
             [(text, px(17, QFont.Medium), c("dim_2"))], 26)
        painter.restore()


class BorderlessScreen(Screen):
    """3 -- League's window mode. The one setting nothing here can work around."""

    key = STEP_BORDERLESS

    def paint(self, painter: QPainter, guide) -> None:
        panel = QRectF(232, 186, 1072, 560)
        paint_options(painter, panel, guide)

        # The two callout captions, in the mockup's own bubbles. The right-hand
        # one sits *below* the arrow that goes with it rather than across it:
        # where it was, the callout into the window-mode field had to duck under
        # it, and the bubble won. Both now read the same way round -- badge and
        # stroke first, the sentence about them underneath.
        self._bubble(painter, guide, QRectF(16, 452, 250, 96),
                     tr("guide.borderless_step_1"), 0.34)
        self._bubble(painter, guide, QRectF(1316, 424, 210, 128),
                     tr("guide.borderless_step_2"), 0.46)

        # ...and the two cards under the window: what to avoid, and why the other
        # one is safe.
        self._avoid(painter, guide, QRectF(232, 774, 720, 108))
        self._note_card(painter, guide, QRectF(984, 774, 320, 108))

    @staticmethod
    def _bubble(painter: QPainter, guide, rect: QRectF, text: str,
                delay: float) -> None:
        grown = stage(guide.reveal, delay, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        box(painter, rect, 8, fill=c("panel"), edge=c("panel_edge"))
        flow(painter, rect.left() + 18, rect.top() + 16, rect.width() - 36,
             runs_of(text, px(18, QFont.Medium), c("text"),
                     strong=px(18, QFont.ExtraBold),
                     strong_colour=c("accent_soft")), 28)
        painter.restore()

    @staticmethod
    def _avoid(painter: QPainter, guide, rect: QRectF) -> None:
        grown = stage(guide.reveal, 0.6, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        box(painter, rect, 10, fill=QColor(239, 68, 68, 26), edge=c("bad", 190))
        disc = QRectF(rect.left() + 22, rect.center().y() - 19, 38, 38)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c("bad"))
        painter.drawEllipse(disc)
        cross(painter, disc.adjusted(12, 12, -12, -12), c("ink"), 2.6)
        # The setting itself, crossed out: the mockup's own way of saying it.
        field = QRectF(rect.right() - 250, rect.center().y() - 21, 210, 42)
        line(painter, disc.right() + 20, rect.top() + 18,
             tr("guide.borderless_avoid"), px(21, QFont.ExtraBold), c("bad"))
        # Measured against the crossed-out field rather than fixed: the English
        # sentence is longer than the French one and ran straight under it.
        flow(painter, disc.right() + 20, rect.top() + 50,
             field.left() - disc.right() - 44,
             [(tr("guide.borderless_avoid_body"), px(17, QFont.Medium),
               c("text_2"))], 26)
        line(painter, field.left(), field.top() - 26, tr("guide.shot_mode"),
             px(15), c("dim"))
        # Struck out by a mark the size of a glyph, on the corner, rather than by
        # a stroke drawn across the whole control: a cross as wide as the thing
        # it cancels lands on the very word it is pointing at, and a value that
        # cannot be read is not a value anybody can be told to avoid. So the
        # field is dimmed -- the way a setting that is not the one to pick should
        # look -- and the cross is small, round-capped and given room to sit in.
        box(painter, field, 2, fill=QColor(10, 26, 38, 190), edge=c("gold", 80))
        centred(painter, field, tr("guide.shot_fullscreen"), px(18), c("faint"))
        mark = QRectF(0, 0, 30, 30)
        mark.moveCenter(QPointF(field.right() - 2, field.top() + 2))
        shadow(painter, mark, 15, spread=5, drop=2, alpha=90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c("bad"))
        painter.drawEllipse(mark)
        cross(painter, mark.adjusted(9, 9, -9, -9), c("ink"), 2.4)
        painter.restore()

    @staticmethod
    def _note_card(painter: QPainter, guide, rect: QRectF) -> None:
        grown = stage(guide.reveal, 0.68, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        box(painter, rect, 10, fill=QColor(124, 58, 237, 30),
            edge=c("accent", 160))
        disc = QRectF(rect.left() + 20, rect.center().y() - 17, 34, 34)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c("accent_btn"))
        painter.drawEllipse(disc)
        centred(painter, disc, "i", px(17, QFont.ExtraBold), c("ink"))
        flow(painter, disc.right() + 18, rect.top() + 20,
             rect.width() - (disc.right() - rect.left()) - 38,
             [(tr("guide.borderless_note"), px(17, QFont.Medium), c("text_2"))],
             24)
        painter.restore()


class LayoutScreen(Screen):
    """4 -- pick a display, and watch the panel on the right become it."""

    key = STEP_LAYOUT
    ROWS = ((LAYOUT_BAR, "ui.layout_bar"), (LAYOUT_CARDS, "ui.layout_cards"),
            (LAYOUT_LIST, "ui.layout_list"))

    def paint(self, painter: QPainter, guide) -> None:
        y = self.heading(painter, guide, COL_X, COL_TOP, "monitor",
                         tr("guide.layout_title"))
        y = flow(painter, COL_X, y + 26, COL_W,
                 runs_of(tr("guide.layout_lead"), px(24, QFont.Medium),
                         c("text"), strong=px(24, QFont.DemiBold),
                         strong_colour=c("accent_lit")), 39)
        rows = self._rows(guide)
        for index, (key, rect) in enumerate(rows):
            self._row(painter, guide, rect, key, index)
        bottom = rows[-1][1].bottom() if rows else y
        self.note(painter, guide, COL_X, bottom + 20, COL_W,
                  tr("guide.layout_note"), delay=0.62)

        # The connector: the mockup's one piece of pure connective tissue, and it
        # earns its place -- it is what makes the panel read as the *consequence*
        # of the row rather than as a second, unrelated picture.
        target = guide.connector_y
        if target > 0:
            painter.setPen(QPen(c("accent_btn"), 2.0))
            painter.drawLine(QPointF(527, target), QPointF(619, target))
            painter.setPen(Qt.NoPen)
            painter.setBrush(c("accent_btn"))
            painter.drawEllipse(QPointF(622, target), 5, 5)

        self.caption(painter, guide, PANEL_X, COL_TOP, tr("guide.layout_result"))
        panel = QRectF(PANEL_X, COL_TOP + 52, PANEL_W, 600)
        box(painter, panel, 8, fill=c("screen"))
        paint_game(painter, panel, guide, "layout")
        box(painter, panel, 8, edge=c("accent_btn"), edge_width=2.0)

    def _rows(self, guide) -> list[tuple[str, QRectF]]:
        """Where the three rows are. Measured from the paragraph above them."""
        font = px(24, QFont.Medium)
        lines = _count_lines(tr("guide.layout_lead"), font, COL_W)
        top = COL_TOP + 62 + 26 + lines * 39 + 22
        return [(key, QRectF(COL_X, top + index * 120, COL_W, 106))
                for index, (key, _) in enumerate(self.ROWS)]

    def _row(self, painter: QPainter, guide, rect: QRectF, key: str,
             index: int) -> None:
        weight = guide.weights.get(f"layout:{key}")
        hover = guide.weights.get(f"hover:layout:{key}")
        grown = stage(guide.reveal, 0.2 + index * 0.09, 0.45)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        painter.translate(0, (1 - grown) * 12)

        wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        wash.setColorAt(0.0, mix(c("card"), c("card_on"), weight))
        wash.setColorAt(1.0, mix(c("card"), c("card_on_2"), weight))
        box(painter, rect, 12, fill=wash,
            edge=mix(c("card_edge"), c("accent"), max(weight, hover * 0.75)),
            edge_width=1.0 + weight)

        thumb = QRectF(rect.left() + 18, rect.center().y() - 39, 112, 78)
        box(painter, thumb, 6, fill=c("inset"), edge=c("inset_edge"))
        paint_overlay(painter, thumb.adjusted(8, 20, -8, -20), key, False)

        label_key = dict(self.ROWS)[key]
        line(painter, thumb.right() + 18, rect.center().y() - 15,
             tr(label_key), px(21, QFont.DemiBold), c("ink"))
        if key == LAYOUT_BAR:
            pill_font = px(15, QFont.Bold)
            text = tr("guide.layout_recommended")
            width = QFontMetricsF(pill_font).horizontalAdvance(text) + 28
            pill = QRectF(thumb.right() + 18, rect.center().y() + 14, width, 30)
            box(painter, pill, 15, fill=c("accent_btn"))
            centred(painter, pill, text, pill_font, c("ink"))
        choice_mark(painter, QRectF(rect.right() - 60, rect.center().y() - 19,
                                    38, 38), weight)
        painter.restore()

    def hots(self, guide) -> list[Hot]:
        return [Hot(rect, lambda k=key: guide.pick_layout(k), f"layout:{key}")
                for key, rect in self._rows(guide)]


class TuneScreen(Screen):
    """5 -- every knob the display has, with the result turning as they turn.

    The settings were on the far side of the guide: someone finished it, landed
    in the settings window and met the same display again with a dozen controls
    around it. So they are here instead, on the step after the shape is chosen,
    where the Practice Tool panel is already on screen and can answer each one
    immediately -- which is the only honest way to offer an opacity slider.

    Two halves, and the split is what they *are* rather than what they look
    like: the left column is how the overlay looks (theme, opacity, size, the
    countdown's face and size), the right is what it shows (idle, order, spells
    that are back up, and how long READY stays). Everything here exists in the
    settings window too, under the same words, because a setting met twice under
    two names is two settings as far as the reader is concerned.
    """

    key = STEP_TUNE

    LABEL_W = 172.0
    ROW_H = 46.0
    ROW_PITCH = 58.0

    # value key, label key, and how the number is worded
    THEME_CHIPS = (("light", "ui.theme_light"), ("dark", "ui.theme_dark"),
                   ("neon", "ui.theme_neon"))
    # setting, label, low, high, step, and how to write the value out
    SLIDERS = (
        ("overlay_opacity", "ui.opacity", 0.35, 1.0, 0.01,
         lambda value: f"{round(value * 100)} %"),
        ("overlay_scale", "ui.scale", 0.6, 2.0, 0.05,
         lambda value: f"{value:.2f}x"),
        ("timer_font_scale", "ui.timer_size", 0.4, 2.0, 0.05,
         lambda value: f"{value:.2f}x"),
    )
    # Top to bottom in the left column. The face sits between its own size and
    # the sizes above it because that is the order the row labels read in.
    FIELDS = ("theme", "overlay_opacity", "overlay_scale", "timer_font",
              "timer_font_scale")
    # The right-hand grid, in reading order. The vertical track is last because
    # it belongs to the track alone and is left out for the other two displays:
    # a switch that does nothing reads as broken rather than as inapplicable,
    # and dropping the last cell of a grid reads as the end of the list.
    SWITCHES = (("bar_show_when_idle", "ui.bar_when_idle"),
                ("sort_by_role", "ui.sort_by_role"),
                ("hide_ready_entries", "ui.hide_ready"),
                ("hide_until_in_game", "ui.hide_until_in_game"),
                ("bar_vertical", "ui.bar_vertical"))

    # Everything this screen owns, which is also everything its reset button
    # puts back. The display itself is not in it: that was the step before, and
    # a reset that undid it would be answering a question nobody asked.
    OWNED = ("theme", "overlay_opacity", "overlay_scale", "timer_font",
             "timer_font_scale", "bar_show_when_idle", "sort_by_role",
             "hide_ready_entries", "hide_until_in_game", "bar_vertical",
             "ready_linger_seconds")

    # -- geometry ------------------------------------------------------
    @classmethod
    def _plan(cls, guide) -> dict:
        """Where everything is. One answer, shared by the paint and the hits.

        Measured from the paragraph rather than written down, for the reason the
        base class gives: a hit box placed at a remembered offset is a hit box
        that misses the moment a translation runs one line longer.
        """
        lines = _count_lines(tr("guide.tune_lead"), px(22, QFont.Medium), COL_W)
        top = COL_TOP + 62 + 24 + lines * 34 + 22
        fields = {name: QRectF(COL_X, top + index * cls.ROW_PITCH, COL_W,
                               cls.ROW_H)
                  for index, name in enumerate(cls.FIELDS)}
        note_top = top + len(cls.FIELDS) * cls.ROW_PITCH - 12
        # The note's height is its sentence's, so the button under it has to be
        # measured rather than placed: the French note runs a line longer than
        # the English one and a fixed offset put the two on top of each other.
        note = tr("guide.tune_note")
        note_h = max(82.0, _count_lines(note, px(19, QFont.Medium),
                                        COL_W - 110) * 30 + 44)

        panel = QRectF(PANEL_X, COL_TOP + 52, PANEL_W, 400)
        cells: list[QRectF] = []
        width = (PANEL_W - 48) / 2
        for index in range(6):
            cells.append(QRectF(PANEL_X + (index % 2) * (width + 48),
                                panel.bottom() + 58 + (index // 2) * 48,
                                width, 44))
        return {"fields": fields, "note_top": note_top, "panel": panel,
                "grid_caption": panel.bottom() + 24, "cells": cells,
                "reset_top": note_top + note_h + 26}

    @classmethod
    def _slider_rect(cls, field: QRectF) -> QRectF:
        """The grabbable strip. The value is written to the right of it."""
        left = field.left() + cls.LABEL_W
        return QRectF(left, field.top(), field.width() - cls.LABEL_W - 78, 44)

    @classmethod
    def _control_rect(cls, field: QRectF) -> QRectF:
        return QRectF(field.left() + cls.LABEL_W, field.top() + 3,
                      field.width() - cls.LABEL_W, 40)

    @classmethod
    def _chip_rect(cls, field: QRectF, index: int) -> QRectF:
        area = cls._control_rect(field)
        width = (area.width() - 16) / 3
        return QRectF(area.left() + index * (width + 8), area.top(), width,
                      area.height())

    @staticmethod
    def _switch_rect(cell: QRectF) -> QRectF:
        return QRectF(cell.right() - 52, cell.center().y() - 14, 52, 28)

    @staticmethod
    def _linger_rect(cell: QRectF) -> QRectF:
        return QRectF(cell.right() - 132, cell.center().y() - 19, 132, 38)

    @classmethod
    def _reset_rect(cls, plan: dict) -> QRectF:
        return QRectF(COL_X, plan["reset_top"], 320, 58)

    @classmethod
    def _confirm_rects(cls, plan: dict) -> tuple[QRectF, QRectF]:
        top = plan["reset_top"]
        return (QRectF(COL_X, top, 190, 58), QRectF(COL_X + 202, top, 150, 58))

    # -- painting ------------------------------------------------------
    def paint(self, painter: QPainter, guide) -> None:
        plan = self._plan(guide)
        self.heading(painter, guide, COL_X, COL_TOP, "sliders",
                     tr("guide.tune_title"))
        flow(painter, COL_X, COL_TOP + 62 + 24, COL_W,
             runs_of(tr("guide.tune_lead"), px(22, QFont.Medium), c("text"),
                     strong=px(22, QFont.DemiBold),
                     strong_colour=c("accent_lit")), 34)

        fields = plan["fields"]
        self._paint_theme(painter, guide, fields["theme"])
        for index, (key, label, low, high, _step, wording) in enumerate(
                self.SLIDERS):
            self._paint_slider(painter, guide, fields[key], key, label, low,
                               high, wording, 0.24 + index * 0.06)
        self._paint_face(painter, guide, fields["timer_font"], 0.42)
        self.note(painter, guide, COL_X, plan["note_top"], COL_W,
                  tr("guide.tune_note"), delay=0.5)
        self._paint_reset(painter, guide, plan)

        self.caption(painter, guide, PANEL_X, COL_TOP, tr("guide.layout_result"))
        panel = plan["panel"]
        box(painter, panel, 8, fill=c("screen"))
        paint_game(painter, panel, guide, "layout")
        box(painter, panel, 8, edge=c("accent_btn"), edge_width=2.0)

        self.caption(painter, guide, PANEL_X, plan["grid_caption"],
                     tr("guide.tune_behaviour"))
        for index, (key, label) in enumerate(self._cells(guide)):
            self._paint_cell(painter, guide, plan, index, key, label)

    def _field_label(self, painter: QPainter, field: QRectF, key: str) -> None:
        line(painter, field.left(), field.center().y() - 11, tr(key),
             px(17, QFont.Medium), c("text_2"))

    def _grown(self, guide, delay: float) -> float:
        return stage(guide.reveal, delay, 0.4)

    def _paint_theme(self, painter: QPainter, guide, field: QRectF) -> None:
        painter.save()
        painter.setOpacity(painter.opacity() * self._grown(guide, 0.18))
        self._field_label(painter, field, "ui.theme")
        current = str(guide.settings.get("theme", "light"))
        for index, (value, label) in enumerate(self.THEME_CHIPS):
            chip(painter, self._chip_rect(field, index), tr(label),
                 1.0 if value == current else 0.0,
                 guide.weights.get(f"hover:tune:theme:{value}"))
        painter.restore()

    def _paint_slider(self, painter: QPainter, guide, field: QRectF, key: str,
                      label: str, low: float, high: float, wording,
                      delay: float) -> None:
        painter.save()
        painter.setOpacity(painter.opacity() * self._grown(guide, delay))
        self._field_label(painter, field, label)
        value = float(guide.settings.get(key, low))
        strip = self._slider_rect(field)
        slider(painter, strip, (value - low) / max(1e-6, high - low),
               guide.weights.get(f"hover:tune:{key}"))
        line(painter, field.right(), field.center().y() - 10, wording(value),
             px(17, QFont.Bold), c("ink"), align=Qt.AlignRight)
        painter.restore()

    def _paint_face(self, painter: QPainter, guide, field: QRectF,
                    delay: float) -> None:
        painter.save()
        painter.setOpacity(painter.opacity() * self._grown(guide, delay))
        self._field_label(painter, field, "ui.timer_font")
        chosen = str(guide.settings.get("timer_font", FACE_AUTO))
        name = tr("ui.timer_font_auto") if chosen == FACE_AUTO else chosen
        stepper(painter, self._control_rect(field), name,
                back=guide.weights.get("hover:tune:face:-"),
                forward=guide.weights.get("hover:tune:face:+"),
                arrows=("\u2039", "\u203a"))
        painter.restore()

    def _cells(self, guide) -> list[tuple[str, str]]:
        """The right-hand grid's contents, in order."""
        rows = [(key, label) for key, label in self.SWITCHES
                if key != "bar_vertical"
                or guide.current_layout() == LAYOUT_BAR]
        rows.append(("ready_linger_seconds", "ui.ready_linger"))
        return rows

    def _paint_cell(self, painter: QPainter, guide, plan: dict, index: int,
                    key: str, label: str) -> None:
        cell = plan["cells"][index]
        painter.save()
        painter.setOpacity(painter.opacity()
                           * self._grown(guide, 0.3 + index * 0.05))
        line(painter, cell.left(), cell.center().y() - 11, tr(label),
             px(18, QFont.Medium), c("text_2"))
        if key == "ready_linger_seconds":
            stepper(painter, self._linger_rect(cell),
                    f"{int(guide.settings.get(key, 5))} s",
                    back=guide.weights.get("hover:tune:linger:-"),
                    forward=guide.weights.get("hover:tune:linger:+"))
        else:
            switch_pill(painter, self._switch_rect(cell),
                        1.0 if guide.settings.get(key) else 0.0,
                        guide.weights.get(f"hover:tune:{key}"))
        painter.restore()

    def _paint_reset(self, painter: QPainter, guide, plan: dict) -> None:
        grown = self._grown(guide, 0.6)
        if guide.confirm_reset:
            line(painter, COL_X, plan["reset_top"] - 36,
                 tr("guide.tune_reset_ask"), px(19, QFont.DemiBold), c("ink"))
            yes, no = self._confirm_rects(plan)
            paint_button(painter, yes, tr("guide.tune_reset_yes"),
                         hover=guide.weights.get("hover:tune:reset_yes"),
                         primary=True, grown=grown)
            paint_button(painter, no, tr("guide.tune_reset_no"),
                         hover=guide.weights.get("hover:tune:reset_no"),
                         grown=grown)
        else:
            paint_button(painter, self._reset_rect(plan),
                         tr("guide.tune_reset"),
                         hover=guide.weights.get("hover:tune:reset"),
                         grown=grown)

    # -- what can be clicked -------------------------------------------
    def hots(self, guide) -> list[Hot]:
        plan = self._plan(guide)
        fields = plan["fields"]
        spots: list[Hot] = []

        for index, (value, _label) in enumerate(self.THEME_CHIPS):
            spots.append(Hot(
                self._chip_rect(fields["theme"], index),
                lambda v=value: guide.apply_setting("theme", v),
                f"tune:theme:{value}"))

        for key, _label, low, high, step, _wording in self.SLIDERS:
            strip = self._slider_rect(fields[key])
            spots.append(Hot(
                strip, lambda: None, f"tune:{key}",
                drag=lambda point, k=key, r=strip, lo=low, hi=high, st=step:
                    guide.drag_setting(k, point, r, lo, hi, st)))

        control = self._control_rect(fields["timer_font"])
        for side, sign in ((0, -1), (1, 1)):
            spots.append(Hot(
                stepper_button(control, side),
                lambda d=sign: guide.cycle_face(d),
                f"tune:face:{'-' if sign < 0 else '+'}"))

        for index, (key, _label) in enumerate(self._cells(guide)):
            cell = plan["cells"][index]
            if key == "ready_linger_seconds":
                linger = self._linger_rect(cell)
                for side, sign in ((0, -1), (1, 1)):
                    spots.append(Hot(
                        stepper_button(linger, side),
                        lambda d=sign: guide.bump_linger(d),
                        f"tune:linger:{'-' if sign < 0 else '+'}"))
            else:
                # The whole row, not just the pill: a line of text with a switch
                # at the end of it is one control, and aiming at the switch is
                # the reader doing the interface's work for it.
                spots.append(Hot(cell, lambda k=key: guide.toggle_setting(k),
                                 f"tune:{key}"))

        if guide.confirm_reset:
            yes, no = self._confirm_rects(plan)
            spots.append(Hot(yes, guide.reset_tune, "tune:reset_yes"))
            spots.append(Hot(no, guide.cancel_reset, "tune:reset_no"))
        else:
            spots.append(Hot(self._reset_rect(plan), guide.ask_reset,
                             "tune:reset"))
        return spots


class PlaceScreen(Screen):
    """6 -- put it where you want it. The overlay is a window, not a header."""

    key = STEP_PLACE

    def paint(self, painter: QPainter, guide) -> None:
        y = self.heading(painter, guide, COL_X, COL_TOP, "move",
                         tr("guide.place_title"))
        y = flow(painter, COL_X, y + 26, COL_W,
                 runs_of(tr("guide.place_lead"), px(24, QFont.Medium),
                         c("text"), strong=px(24, QFont.DemiBold),
                         strong_colour=c("accent_lit")), 39)
        rect = self._button(guide)
        paint_button(painter, rect, tr("guide.place_action"),
                     hover=guide.weights.get("hover:place"), primary=True,
                     grown=stage(guide.reveal, 0.3, 0.4))
        self.note(painter, guide, COL_X, rect.bottom() + 26, COL_W,
                  tr("guide.place_note"), delay=0.45)

        self.caption(painter, guide, PANEL_X, COL_TOP, tr("guide.layout_result"))
        panel = QRectF(PANEL_X, COL_TOP + 52, PANEL_W, 600)
        box(painter, panel, 8, fill=c("screen"))
        paint_game(painter, panel, guide, "place")
        box(painter, panel, 8, edge=c("accent_btn"), edge_width=2.0)

    @staticmethod
    def _button(guide) -> QRectF:
        lines = _count_lines(tr("guide.place_lead"), px(24, QFont.Medium), COL_W)
        top = COL_TOP + 62 + 26 + lines * 39 + 26
        return QRectF(COL_X, top, 300, 62)

    def hots(self, guide) -> list[Hot]:
        return [Hot(self._button(guide), guide.place_requested.emit, "place")]


class ProofScreen(Screen):
    """7 -- the whole chain, demonstrated on a real frame that ships with it.

    One press, no game required and nothing to type: the program reads a real
    captured frame the way it reads a live one and starts the timers it finds. It
    used to hand over a line to paste into the Practice Tool instead, which asked
    the reader to have League open at this exact moment and to trust that a line
    they typed themselves proved anything about reading the game's own wording.
    """

    key = STEP_PROOF

    def paint(self, painter: QPainter, guide) -> None:
        y = self.heading(painter, guide, COL_X, COL_TOP, "chat",
                         tr("guide.proof_title"))
        y = flow(painter, COL_X, y + 26, COL_W,
                 runs_of(tr("guide.proof_lead"), px(24, QFont.Medium),
                         c("text"), strong=px(24, QFont.DemiBold),
                         strong_colour=c("accent_lit")), 39)

        grown = stage(guide.reveal, 0.3, 0.4)
        run, frame_button = self._button_rects(guide)
        paint_button(painter, run,
                     tr("guide.proof_running") if guide.test_running
                     else tr("guide.proof_action"),
                     hover=guide.weights.get("hover:test"), primary=True,
                     grown=grown)
        # The remedy, next to the test that reveals the need for it. Framing the
        # chat by hand is not a step everybody walks through -- the area is found
        # on its own, and asking a new user to draw a rectangle around something
        # the program already located would be busywork. It belongs exactly here:
        # the one moment where a reader discovers that nothing appeared.
        paint_button(painter, frame_button, tr("ui.test_mode"),
                     hover=guide.weights.get("hover:frame"), primary=False,
                     grown=grown)

        top = run.bottom() + 22
        # The verdict, once there is one. Painted where the reader is already
        # looking -- directly under the button they just pressed. Kept to two
        # entries because everything below it still has to fit above the footer.
        for text, colour in guide.test_lines:
            font = px(19, QFont.Medium)
            flow(painter, COL_X, top, COL_W, [(text, font, c(colour))], 28)
            top += _count_lines(text, font, COL_W) * 28 + 10
        if guide.test_lines:
            top += 10

        # A quiet line rather than a second note box: two boxes stacked do not
        # fit the column, and this is a remedy for a minority, not a warning.
        hint = px(17, QFont.Medium)
        rows = _count_lines(tr("guide.proof_frame"), hint, COL_W)
        painter.save()
        painter.setOpacity(painter.opacity() * stage(guide.reveal, 0.5, 0.4))
        flow(painter, COL_X, top, COL_W,
             [(tr("guide.proof_frame"), hint, c("text_2"))], 26)
        painter.restore()
        self.note(painter, guide, COL_X, top + rows * 26 + 20, COL_W,
                  tr("guide.proof_note"), delay=0.55)

        self.caption(painter, guide, PANEL_X, COL_TOP, tr("guide.layout_result"))
        panel = QRectF(PANEL_X, COL_TOP + 52, PANEL_W, 600)
        box(painter, panel, 8, fill=c("screen"))
        paint_game(painter, panel, guide, "proof")
        box(painter, panel, 8, edge=c("accent_btn"), edge_width=2.0)

    @staticmethod
    def _button_rects(guide) -> tuple[QRectF, QRectF]:
        """The test button, and the framing one beside it rather than under it.

        The two together are 476 wide against the column's 480 -- the same 4px of
        slack the copy button and this one used to share. Side by side rather than
        stacked because the column also has to hold the verdict, the remedy line
        and the safety note above the window's own footer.
        """
        lines = _count_lines(tr("guide.proof_lead"), px(24, QFont.Medium), COL_W)
        top = COL_TOP + 62 + 26 + lines * 39 + 26
        run = QRectF(COL_X, top, 260, 62)
        return run, QRectF(run.right() + 16, top, 200, 62)

    def hots(self, guide) -> list[Hot]:
        run, frame_button = self._button_rects(guide)
        return [Hot(run, guide.run_self_test, "test"),
                Hot(frame_button, guide.chat_frame_requested.emit, "frame")]


class DoneScreen(Screen):
    """7 -- the receipt. Three lines naming the three decisions, each ticked."""

    key = STEP_DONE

    def paint(self, painter: QPainter, guide) -> None:
        centre = DESIGN.width() / 2
        self._medallion(painter, guide, QPointF(centre, 262))

        grown = stage(guide.reveal, 0.25, 0.4)
        painter.save()
        painter.setOpacity(painter.opacity() * grown)
        line(painter, centre, 366, tr("guide.done_title"),
             px(58, QFont.Bold, spacing=0.5, serif=True), c("parchment"),
             align=Qt.AlignHCenter)

        # The divider: two fading rules and a diamond, the mockup's one flourish.
        y = 452
        for left, right, fade_in in ((centre - 280, centre - 12, False),
                                     (centre + 12, centre + 280, True)):
            gradient = QLinearGradient(QPointF(left, y), QPointF(right, y))
            gradient.setColorAt(0.0, c("gold", 0 if fade_in else 150))
            gradient.setColorAt(1.0, c("gold", 150 if fade_in else 0))
            painter.setPen(QPen(gradient, 1.2))
            painter.drawLine(QPointF(left, y), QPointF(right, y))
        painter.save()
        painter.translate(QPointF(centre, y))
        painter.rotate(45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c("gold"))
        painter.drawRect(QRectF(-5.5, -5.5, 11, 11))
        painter.restore()

        flow(painter, centre - 320, 472, 640,
             [(tr("guide.done_lead"), px(23, QFont.Medium), QColor("#d5dbec"))],
             34, align=Qt.AlignHCenter)
        painter.restore()

        card = QRectF(centre - 270, 552, 540, 222)
        box(painter, card, 10, fill=QColor(10, 16, 30, 140),
            edge=QColor("#1e2540"))
        rows = (("monitor", tr("guide.done_check_display")),
                ("window", tr("guide.done_check_borderless")),
                ("settings", tr("guide.done_check_settings")))
        for index, (icon, label) in enumerate(rows):
            grown = stage(guide.reveal, 0.42 + index * 0.12, 0.4)
            row = QRectF(card.left() + 34, card.top() + index * 74,
                         card.width() - 68, 74)
            painter.save()
            painter.setOpacity(painter.opacity() * grown)
            glyph(painter, QRectF(row.left(), row.center().y() - 17, 34, 34),
                  icon, c("accent_lit"), width=2.4)
            line(painter, row.left() + 60, row.center().y() - 14, label,
                 px(21, QFont.Medium), QColor("#e4e8f5"))
            tick(painter, QRectF(row.right() - 26, row.center().y() - 12, 26, 24),
                 c("ok"), grown, 3.4)
            painter.restore()
            if index < len(rows) - 1:
                painter.setPen(QPen(QColor("#1b2138"), 1.0))
                painter.drawLine(QPointF(row.left(), row.bottom()),
                                 QPointF(row.right(), row.bottom()))

        painter.save()
        painter.setOpacity(painter.opacity() * stage(guide.reveal, 0.78, 0.4))
        flow(painter, centre - 230, 798, 460,
             runs_of(tr("guide.done_footer"), px(20, QFont.Medium),
                     QColor("#b7bed6"), strong=px(20, QFont.Bold),
                     strong_colour=c("accent_lit")), 32, align=Qt.AlignHCenter)
        painter.restore()

    @staticmethod
    def _medallion(painter: QPainter, guide, centre: QPointF) -> None:
        """A ring that closes and a tick that is drawn: the gesture is completion."""
        reveal = guide.reveal
        breath = abs(guide.march * 2 - 1)
        radius = 80.0
        painter.save()
        for spread, alpha in ((44.0, 24), (26.0, 30), (12.0, 34)):
            painter.setPen(QPen(QColor(43, 120, 200,
                                       int(alpha * (0.5 + 0.5 * breath))),
                                spread))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(centre, radius + spread / 2, radius + spread / 2)

        disc = QRectF(centre.x() - radius, centre.y() - radius,
                      radius * 2, radius * 2)
        wash = QLinearGradient(disc.topLeft(), disc.bottomRight())
        wash.setColorAt(0.0, QColor("#0d2b52"))
        wash.setColorAt(1.0, QColor("#050b16"))
        painter.setBrush(wash)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(disc)

        sweep = stage(reveal, 0.0, 0.5)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(c("gold"), 3.0))
        painter.drawArc(disc, 90 * 16, -int(360 * 16 * sweep))
        painter.setPen(QPen(c("gold_deep"), 2.0))
        painter.drawEllipse(disc.adjusted(-9, -9, 9, 9))

        for index, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
            grown = stage(reveal, 0.3 + index * 0.05, 0.3)
            if grown <= 0:
                continue
            size = (7.0 if index % 2 else 8.0) * grown
            painter.save()
            painter.translate(QPointF(centre.x() + dx * (radius + 9),
                                      centre.y() + dy * (radius + 9)))
            painter.rotate(45)
            painter.setBrush(c("gold_pale") if index % 2 == 0 else c("gold"))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(-size, -size, size * 2, size * 2))
            painter.restore()

        tick(painter, QRectF(centre.x() - 42, centre.y() - 34, 84, 68),
             c("gold_lit"), stage(reveal, 0.4, 0.45), 13.0)
        painter.restore()


SCREENS = {screen.key: screen for screen in (
    LanguageScreen(), WelcomeScreen(), BorderlessScreen(), LayoutScreen(),
    TuneScreen(), PlaceScreen(), ProofScreen(), DoneScreen())}


def paint_button(painter: QPainter, rect: QRectF, text: str, *,
                 hover: float = 0.0, primary: bool = False,
                 enabled: bool = True, grown: float = 1.0,
                 icon_before: str = "", icon_after: str = "") -> None:
    """The mockups' two buttons, at their two sizes."""
    if grown <= 0.02:
        return
    painter.save()
    painter.setOpacity(painter.opacity() * grown * (1.0 if enabled else 0.45))
    if primary:
        fill = mix(c("accent_btn"), c("accent_lit"), hover)
        if hover > 0:
            glow(painter, rect, 10, c("accent_btn"), spread=22,
                 alpha=int(70 * hover))
        box(painter, rect, 10, fill=fill)
        colour = c("ink")
    else:
        box(painter, rect, 10, fill=c("panel"),
            edge=mix(c("panel_edge"), QColor("#3a4268"), hover))
        colour = c("text")
    font = px(24 if primary else 23, QFont.Bold if primary else QFont.DemiBold)
    label = text
    if icon_before:
        label = f"{icon_before}  {text}"
    if icon_after:
        label = f"{text}  {icon_after}"
    centred(painter, rect, label, font, colour)
    painter.restore()


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
class Onboarding(QWidget):
    """The guide window. Owns nothing; asks the application to act."""

    finished = Signal()                   # done or skipped, either way
    language_changed = Signal(str)        # same contract as the settings window
    layout_changed = Signal(str)          # a display was picked
    place_requested = Signal()            # show the overlay, unlocked, to be moved
    chat_frame_requested = Signal()       # open the chat zone frame
    self_test_requested = Signal()        # read the shipped sample frame
    settings_changed = Signal()           # a knob on the tuning step was turned

    def __init__(self, settings) -> None:
        super().__init__(None)
        self.settings = settings
        self._index = 0
        self._finished = False
        # The proof step's state: whether a run is in flight, and the verdict as
        # (text, theme colour key) lines to paint under the button.
        self.test_running = False
        self.test_lines: list[tuple[str, str]] = []
        # The tuning step's one piece of state: whether its reset button has
        # been pressed once and is waiting to be meant. Kept on the window
        # rather than on the screen because the screens are singletons shared by
        # every guide ever opened, and a half-asked question must not outlive
        # the window that asked it.
        self.confirm_reset = False

        # Animated state, all read inside paintEvent.
        self.reveal = 1.0
        self.march = 0.0
        self.slide = 0.0
        self.fade = 1.0
        self.stepper_pos = 0.0
        self.connector_y = 0.0
        self.weights = Weights(self)
        self._hover = ""
        self._pressed = ""
        self._dragging: Hot | None = None

        family()                          # load Mulish before the first paint
        self.setWindowTitle(tr("guide.title"))

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._size_to_screen()

        self._slide_motion = Motion(self, self._set_slide, duration=SLIDE_MS)
        self._fade_motion = Motion(self, self._set_fade, duration=FADE_MS)
        self._reveal_motion = Motion(self, self._set_reveal, duration=REVEAL_MS)
        self._stepper_motion = Motion(self, self._set_stepper, duration=440,
                                      easing=QEasingCurve.InOutCubic)
        self._connector_motion = Motion(self, self._set_connector, duration=260,
                                        easing=QEasingCurve.InOutCubic)
        # The one thing that keeps moving once a screen has settled, and it stops
        # itself: a window left open on a desk must not cost the game frames.
        self._loop = QTimer(self)
        self._loop.setInterval(LOOP_MS)
        self._loop.timeout.connect(self._tick)
        self._ticks = 0

        self._sync_language(animate=False)
        self._sync_layout(animate=False)
        self._enter(1)

    # -- animated setters ----------------------------------------------
    def _set_slide(self, value: float) -> None:
        self.slide = value
        self.update()

    def _set_fade(self, value: float) -> None:
        self.fade = value
        self.update()

    def _set_reveal(self, value: float) -> None:
        self.reveal = value
        self.update()

    def _set_stepper(self, value: float) -> None:
        self.stepper_pos = value
        self.update()

    def _set_connector(self, value: float) -> None:
        self.connector_y = value
        self.update()

    def _tick(self) -> None:
        self._ticks += 1
        if self._ticks > LOOP_TICKS:
            self._loop.stop()
            return
        self.march = (self.march + 0.02) % 1.0
        self.update()

    # -- geometry ------------------------------------------------------
    def _size_to_screen(self) -> None:
        """Open at the design's own shape, at three quarters of its own size.

        The composition is 1536 x 1024 and it is scaled as a whole, so the window
        keeps that 3:2 shape: the alternative is letterboxing, which would put
        two dead bands around a design that was drawn to fill its frame.

        It opens at ``OPEN_SCALE`` rather than at 1:1 because the mockups were
        drawn on a canvas the size of a small laptop screen, and a window that
        fills the monitor reads as zoomed-in rather than as large -- the type is
        set in pixels, so 1:1 puts a 42 px heading on a screen where nothing else
        is near that size. Everything below still speaks the mockups' own
        coordinates; only the one multiplier at the top of ``paintEvent`` moves.
        """
        scale = OPEN_SCALE
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry()
            scale = min((room.width() - 60) / DESIGN.width(),
                        (room.height() - 60) / DESIGN.height(), OPEN_SCALE)
            scale = max(scale, 0.42)
        size = QSize(int(DESIGN.width() * scale), int(DESIGN.height() * scale))
        self.setMinimumSize(int(DESIGN.width() * 0.40),
                            int(DESIGN.height() * 0.40))
        self.resize(size)
        if screen is not None:
            room = screen.availableGeometry()
            self.move(room.left() + (room.width() - size.width()) // 2,
                      room.top() + (room.height() - size.height()) // 2)

    def _scale(self) -> float:
        return min(self.width() / DESIGN.width(),
                   self.height() / DESIGN.height())

    def _origin(self) -> QPointF:
        scale = self._scale()
        return QPointF((self.width() - DESIGN.width() * scale) / 2,
                       (self.height() - DESIGN.height() * scale) / 2)

    def _to_design(self, point) -> QPointF:
        scale = max(1e-6, self._scale())
        origin = self._origin()
        return QPointF((point.x() - origin.x()) / scale,
                       (point.y() - origin.y()) / scale)

    # -- painting ------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), c("bg_edge"))

        origin = self._origin()
        painter.translate(origin)
        painter.scale(self._scale(), self._scale())
        painter.setClipRect(QRectF(0, 0, DESIGN.width(), DESIGN.height()))

        self._paint_ground(painter)
        painter.save()
        painter.translate(self.slide, 0)
        painter.setOpacity(self.fade)
        SCREENS[STEPS[self._index]].paint(painter, self)
        painter.restore()
        self._paint_stepper(painter)
        self._paint_footer(painter)
        painter.end()

    @staticmethod
    def _paint_ground(painter: QPainter) -> None:
        # radial-gradient(1200px 700px at 20% -10%) -- an ellipse in CSS, so the
        # painter is squashed rather than the gradient being faked round.
        painter.save()
        painter.translate(DESIGN.width() * 0.20, DESIGN.height() * -0.10)
        painter.scale(1.0, 700 / 1200)
        wash = QRadialGradient(QPointF(0, 0), 1200)
        wash.setColorAt(0.0, c("bg_core"))
        wash.setColorAt(0.55, c("bg_mid"))
        wash.setColorAt(1.0, c("bg_edge"))
        painter.fillRect(QRectF(-2400, -2400, 4800, 4800), wash)
        painter.restore()

    def _paint_stepper(self, painter: QPainter) -> None:
        painter.fillRect(QRectF(0, 0, DESIGN.width(), HEADER_H), c("header"))
        count = len(STEPS)
        column = (DESIGN.width() - 92) / count
        radius = 28.0
        cy = 30.0 + radius
        breath = abs(self.march * 2 - 1)

        for index in range(count - 1):
            x1 = 46 + column * (index + 0.5) + radius + 14
            x2 = 46 + column * (index + 1.5) - radius - 14
            painter.setPen(QPen(c("hairline"), 1.4))
            painter.drawLine(QPointF(x1, cy), QPointF(x2, cy))
            filled = clamp(self.stepper_pos - index)
            if filled > 0:
                painter.setPen(QPen(c("accent"), 2.0))
                painter.drawLine(QPointF(x1, cy),
                                 QPointF(x1 + (x2 - x1) * filled, cy))

        for index, step in enumerate(STEPS):
            cx = 46 + column * (index + 0.5)
            past = clamp(self.stepper_pos - index)
            here = clamp(1.0 - abs(self.stepper_pos - index))
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

            if here > 0.05:
                painter.setBrush(Qt.NoBrush)
                for spread, alpha in ((12.0, 24), (6.0, 40)):
                    painter.setPen(QPen(c("accent", int(alpha * here
                                                        * (0.6 + 0.4 * breath))),
                                        spread))
                    painter.drawEllipse(rect.adjusted(-spread / 2, -spread / 2,
                                                      spread / 2, spread / 2))
            painter.setBrush(mix(mix(c("step_bg"), c("accent_night"), here),
                                 c("accent_btn"), past))
            painter.setPen(QPen(mix(c("step_ring"), c("accent"),
                                    max(past, here)), 1.2 + 1.2 * here))
            painter.drawEllipse(rect)

            if past > 0.02:
                tick(painter, rect.adjusted(7, 7, -7, -7), c("ink"), past, 3.4)
            if past < 0.98:
                painter.save()
                painter.setOpacity(painter.opacity() * (1.0 - past))
                centred(painter, rect, str(index + 1),
                        px(24, QFont.ExtraBold if here > 0.4 else QFont.Medium),
                        mix(c("faint"), c("ink"), here))
                painter.restore()

            flow(painter, cx - column / 2 + 8, cy + radius + 16, column - 16,
                 [(tr(STEP_NAV[step]),
                   px(19, QFont.ExtraBold if here > 0.5 else QFont.Medium),
                   mix(c("dim"), c("ink"), here))], 24, align=Qt.AlignHCenter)

    def _paint_footer(self, painter: QPainter) -> None:
        painter.setPen(QPen(c("rule"), 1.0))
        painter.drawLine(QPointF(0, FOOT_RULE), QPointF(DESIGN.width(),
                                                        FOOT_RULE))
        paint_button(painter, self._back_rect(), tr("guide.back"),
                     hover=self.weights.get("hover:back"),
                     enabled=self._index > 0, icon_before="←")
        last = self._index == len(STEPS) - 1
        paint_button(painter, self._next_rect(),
                     tr("guide.finish") if last else tr("guide.next"),
                     hover=self.weights.get("hover:next"), primary=True,
                     icon_after="✓" if last else "→")

        spacing = 29.0
        left = DESIGN.width() / 2 - (len(STEPS) - 1) * spacing / 2
        cy = FOOT_TOP + FOOT_H / 2
        painter.setPen(Qt.NoPen)
        for index in range(len(STEPS)):
            painter.setBrush(c("step_off"))
            painter.drawEllipse(QPointF(left + index * spacing, cy), 6.5, 6.5)
        painter.setBrush(c("accent"))
        painter.drawEllipse(QPointF(left + self.stepper_pos * spacing, cy),
                            7.5, 7.5)

    @staticmethod
    def _back_rect() -> QRectF:
        return QRectF(EDGE, FOOT_TOP, 210, FOOT_H)

    @staticmethod
    def _next_rect() -> QRectF:
        return QRectF(DESIGN.width() - EDGE - 230, FOOT_TOP, 230, FOOT_H)

    # -- interaction ---------------------------------------------------
    def _hotspots(self) -> list[Hot]:
        spots = [Hot(self._next_rect(), self._on_next, "next")]
        if self._index > 0:
            spots.append(Hot(self._back_rect(), self._on_back, "back"))
        spots.extend(SCREENS[STEPS[self._index]].hots(self))
        return spots

    def _hit(self, position) -> Hot | None:
        point = self._to_design(position)
        for spot in self._hotspots():
            if spot.rect.contains(point):
                return spot
        return None

    def mouseMoveEvent(self, event) -> None:
        if self._dragging is not None:
            # Deliberately not re-hit: a slider being dragged keeps the pointer
            # even once it has left the strip, which is what makes the ends of
            # the range reachable without threading a needle.
            self._dragging.drag(self._to_design(event.position()))
            return
        spot = self._hit(event.position())
        key = spot.key if spot is not None else ""
        if key != self._hover:
            if self._hover:
                self.weights.set(f"hover:{self._hover}", 0.0)
            self._hover = key
            if key:
                self.weights.set(f"hover:{key}", 1.0)
            self.setCursor(Qt.PointingHandCursor if key else Qt.ArrowCursor)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hover:
            self.weights.set(f"hover:{self._hover}", 0.0)
            self._hover = ""
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        spot = self._hit(event.position())
        self._pressed = spot.key if spot is not None else ""
        if spot is not None and spot.drag is not None:
            self._dragging = spot
            spot.drag(self._to_design(event.position()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._dragging is not None:
            # Every step of the drag was written into the settings unsaved, so
            # that a slider does not rewrite the file sixty times on its way
            # across. This is the one write.
            self._dragging = None
            self._pressed = ""
            self.settings.save()
            return
        spot = self._hit(event.position())
        if spot is not None and spot.key == self._pressed:
            spot.action()
        self._pressed = ""

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter,
                           Qt.Key_Space):
            self._on_next()
        elif event.key() in (Qt.Key_Left, Qt.Key_Backspace):
            self._on_back()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    def showEvent(self, event) -> None:
        # Played on the way in rather than at construction: the window is built,
        # then shown a moment later, and an entrance that ran while it was hidden
        # is an entrance nobody saw.
        super().showEvent(event)
        self._enter(1)

    # -- state ---------------------------------------------------------
    def current_language(self) -> str:
        return language_for(str(self.settings.get("locale", "en_US")))

    def current_layout(self) -> str:
        value = str(self.settings.get("overlay_layout", LAYOUT_BAR))
        return value if value in LAYOUTS else LAYOUT_BAR

    def _sync_language(self, *, animate: bool = True) -> None:
        current = self.current_language()
        for language in (FRENCH, ENGLISH):
            self.weights.set(f"lang:{language}", 1.0 if language == current
                             else 0.0, animate=animate)

    def _sync_layout(self, *, animate: bool = True) -> None:
        current = self.current_layout()
        for key in LAYOUTS:
            self.weights.set(f"layout:{key}", 1.0 if key == current else 0.0,
                             animate=animate)
        self._aim_connector(animate=animate)

    def _aim_connector(self, *, animate: bool = True) -> None:
        """Point the connector at the row that is picked.

        Asked of the screen rather than remembered: the rows move when a
        translation wraps, and a line drawn at a remembered offset is a line
        pointing at the wrong display.
        """
        screen = SCREENS[STEP_LAYOUT]
        target = 0.0
        for key, rect in screen._rows(self):
            if key == self.current_layout():
                target = rect.center().y()
        if target <= 0:
            return
        if animate and self.connector_y > 0:
            self._connector_motion.run(self.connector_y, target)
        else:
            self._connector_motion.stop()
            self._set_connector(target)

    def pick_language(self, language: str) -> None:
        """Apply a language here and now, so the rest of the guide is in it.

        The application reloads Riot's data on this signal and rebuilds its other
        windows; this one needs neither, because it draws every word of itself
        from ``tr()`` at paint time. That is the whole reason the window is
        painted rather than built out of widgets: step one changes the language
        of steps two to eight, and it must not cost a rebuild.
        """
        if language not in (FRENCH, ENGLISH) or language == self.current_language():
            return
        self.settings.set("locale", locale_for(language))
        self._sync_language()
        self._refresh_title()
        self.language_changed.emit(language)
        self.update()

    # -- the tuning step -----------------------------------------------
    def overlay_style(self) -> dict:
        """How the overlay currently looks, for the panels that draw it."""
        return overlay_style(self.settings)

    def apply_setting(self, key: str, value, *, save: bool = True) -> None:
        """Write one setting and let the application follow it, now.

        The point of tuning it here is watching it land, so nothing is deferred
        to a Next button: the overlay itself is already on screen behind this
        window and moves with the slider.
        """
        self.settings.set(key, value, save=save)
        self.settings_changed.emit()
        self.update()

    def toggle_setting(self, key: str) -> None:
        self.apply_setting(key, not bool(self.settings.get(key)))

    def drag_setting(self, key: str, point: QPointF, strip: QRectF,
                     low: float, high: float, step: float) -> None:
        """Where the pointer is along ``strip``, in the setting's own units."""
        span = max(1.0, strip.width() - 22)
        share = clamp((point.x() - strip.left() - 11) / span)
        value = low + (high - low) * share
        value = round(round(value / step) * step, 4)
        self.apply_setting(key, min(high, max(low, value)), save=False)

    def cycle_face(self, direction: int) -> None:
        """The next countdown face along, wrapping. "Automatic" is one of them."""
        faces = countdown_faces()
        current = str(self.settings.get("timer_font", FACE_AUTO))
        index = faces.index(current) if current in faces else 0
        self.apply_setting("timer_font",
                           faces[(index + direction) % len(faces)])

    def bump_linger(self, direction: int) -> None:
        value = int(self.settings.get("ready_linger_seconds", 5)) + direction
        self.apply_setting("ready_linger_seconds", max(0, min(60, value)))

    def ask_reset(self) -> None:
        """First press asks. Nothing is undone until the second one answers."""
        self.confirm_reset = True
        self.update()

    def cancel_reset(self) -> None:
        self.confirm_reset = False
        self.update()

    def reset_tune(self) -> None:
        """Put back exactly what this screen can change, and nothing else."""
        self.confirm_reset = False
        self.settings.update({key: DEFAULTS[key] for key in TuneScreen.OWNED},
                             save=True)
        self.settings_changed.emit()
        self.update()

    def pick_layout(self, key: str) -> None:
        if key not in LAYOUTS:
            return
        self.settings.set("overlay_layout", key)
        self._sync_layout()
        self.layout_changed.emit(key)
        self.update()

    def run_self_test(self) -> None:
        """Ask for the sample frame to be read. Ignored while one is in flight."""
        if self.test_running:
            return
        self.test_running = True
        self.test_lines = []
        self.update()
        self.self_test_requested.emit()

    def show_test_result(self, result, started: dict) -> None:
        """The verdict, in the two entries this column has room for.

        Shorter than the control window's report on purpose, and not only for
        space: a reader in the guide needs to know whether it worked and what to
        do if it did not, where somebody in Troubleshooting wants the geometry of
        the region and the timing.
        """
        self.test_running = False
        lines: list[tuple[str, str]] = []
        if result.error:
            lines.append((tr("ui.test_error", error=result.error), "bad"))
        elif result.ok:
            lines.append((tr("guide.proof_pass", count=len(result.events)), "ok"))
            # One line for every spell rather than one line each: the countdown is
            # the proof, and it is what the lead promised would appear.
            spells = []
            for event in result.events:
                mark = started.get((event.champion_id, event.spell_key))
                spells.append(f"{event.champion_name} - {event.spell_name}"
                              + (f" ({mark})" if mark else ""))
            lines.append((", ".join(spells), "text"))
        elif result.region is None:
            lines.append((tr("ui.test_fail_region"), "bad"))
        else:
            lines.append((tr("ui.test_fail_parse"), "bad"))
        self.test_lines = lines
        self.update()

    def retranslate(self) -> None:
        """The language changed under us. Nothing to rebuild -- just repaint."""
        self._refresh_title()
        self._sync_language(animate=False)
        self.update()

    def _refresh_title(self) -> None:
        """The one piece of this window Qt draws rather than it: the title bar.

        It carries the step count, which the mockups do not put on the canvas --
        and it is the only place left where a language change has to be applied
        rather than simply repainted.
        """
        self.setWindowTitle(
            f"{tr('guide.title')}  -  "
            f"{tr('guide.step', step=self._index + 1, total=len(STEPS))}")

    # -- walking the steps ---------------------------------------------
    def step_index(self) -> int:
        return self._index

    def show_step(self, index: int) -> None:
        """Jump to a step. Used to reopen the guide where it was left."""
        previous = self._index
        self._index = max(0, min(len(STEPS) - 1, index))
        self._enter(1 if self._index >= previous else -1)

    def _enter(self, direction: int) -> None:
        # A verdict belongs to the visit that produced it: coming back to the step
        # should offer the test again rather than show a stale pass.
        self.test_running = False
        self.test_lines = []
        self.confirm_reset = False
        self._slide_motion.run(46.0 * direction, 0.0)
        self._fade_motion.run(0.0, 1.0)
        self._reveal_motion.run(0.0, 1.0)
        self._stepper_motion.run(self.stepper_pos, float(self._index))
        if STEPS[self._index] == STEP_LAYOUT:
            self._aim_connector(animate=False)
        self._ticks = 0
        self._loop.start()
        self._refresh_title()
        self.update()

    def _on_back(self) -> None:
        if self._index > 0:
            self.show_step(self._index - 1)

    def _on_next(self) -> None:
        if self._index < len(STEPS) - 1:
            self.show_step(self._index + 1)
            return
        self._on_finish()

    def discard(self) -> None:
        """Close without counting as seen.

        For the one case that is neither finishing nor giving up: the window has
        to go away without the guide being marked as done.
        """
        self._finished = True
        self.close()

    def _on_finish(self) -> None:
        """Finished or closed -- the same thing as far as offering it again.

        Someone who closed the guide made a decision; showing it again on the
        next launch would be arguing with them. It stays one click away on the
        home page.
        """
        if self._finished:
            return
        self._finished = True
        self.settings.set("onboarding_done", True)
        self.finished.emit()
        self.close()

    def stop_animations(self) -> None:
        """Bring everything that is moving to a halt.

        Not housekeeping: a running :class:`Motion` calls back into Python on
        every frame, and a window that is closed and then collected while one is
        mid-flight is a callback into a half-deleted widget. That crashes the
        process at shutdown rather than raising -- which is how it was found.
        """
        self._loop.stop()
        for motion in self.findChildren(QVariantAnimation):
            motion.stop()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.stop_animations()

    def closeEvent(self, event) -> None:
        self.stop_animations()
        super().closeEvent(event)
        self._on_finish()
