"""The control window: what is happening, what to change, what to check.

A port of ``design/maquette/Flashwatch *.dc.html``, and a literal one. Every
length, every type size, every gap in this file is the number in those files:
the rail is 237 px because it is 237 px there, a card's corner is 12 px because
it is 12 px there, the home page's body text is 16 px on a 27 px line because
that is what the CSS says. The palette is :data:`theme.MENU`, filled the same
way, and the stylesheet is generated from it.

**One canvas, one scale.** The maquettes are a fixed 1448 x 1086 page, so this
window is a fixed 1448 x 1086 page too, fitted to whatever the screen allows
through a single multiplier -- exactly what ``onboarding.py`` does for the setup
guide. Nothing is elastic: at 100% it is the maquette pixel for pixel, and at 78%
it is the same drawing at 78%. That is why every number goes through
:meth:`ControlWindow.s` and why the stylesheet is rebuilt when the scale changes.

The four files disagree with each other about the frame -- they were drawn at
three different canvas sizes, with title bars of 47, 48, 50 and 52 px -- so the
frame comes from ``Flashwatch App.dc.html``, the largest and most complete of
them, and each page keeps its own numbers inside that frame.

Unlike the guide -- one painted canvas, no child widgets -- this is built from
**real widgets**, which is what ``design/08-maquette-html.md`` says a desktop
window is for. The guide can be painted because it has almost nothing to
operate; this window is nothing but controls, and a hand-drawn combo box is one
that cannot be typed into, tabbed to, or read by a screen reader.

Four things the maquettes draw that Qt will not style are done in Python, because
``design/CONTRAINTES-QT.md`` says they are otherwise silently ignored:

* **the switches** are painted (:class:`Switch`) -- QSS can colour a checkbox
  indicator but cannot slide a knob across it;
* **the chevrons and steppers** on fields are painted by the widgets that own
  them (:class:`Select`, :class:`Spin`, :class:`Scale`), because Qt's own arrows
  are style-drawn triangles no rule can recolour, and an ``image:`` would need a
  file this program does not ship;
* **the icons** come from :mod:`icons`, geometry for the same reason;
* **the window chrome** is ours (:class:`TitleBar`): the maquettes draw their own
  title bar, so the window is frameless.

The four places, in the order somebody needs them:

* **Accueil** answers "is it working", offers the guide, and gives the one line
  to paste into chat to prove the whole pipeline end to end.
* **Affichage** is the overlay: which of the three displays, and where it sits.
* **Reglages** is the rest of the preferences.
* **Depannage** is the zone frames and the raw OCR, which is where a real problem
  gets diagnosed -- it shows the lines read and the near misses, which is where a
  client's system-message wording becomes visible instead of guessed at.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (QEasingCurve, QPoint, QRect, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QIcon,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QDoubleSpinBox,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLayout, QListWidget, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QSpacerItem, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

import autostart
import icons
from chat_detector import ChatRegion
from i18n import ENGLISH, FRENCH, locale_for, tr
from overlay import LAYOUT_BAR, LAYOUT_CARDS, LAYOUT_LIST, LAYOUTS
from theme import (DANGER, INK, INK_FAINT, MENU, PAINT, READY, SIGNAL, SOON,
                   art_path, control_qss, mark_pixmap, menu_family)
from version import __version__
from zone_overlay import ZONE_CHAT, ZONE_CLOCK, ZONE_SCOREBOARD

log = logging.getLogger(__name__)

ROLES = ["", "TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
# Ordered with the default first: a selector that opens on something other than
# what is applied reads as a pending change.
THEME_KEYS = {"light": "ui.theme_light", "dark": "ui.theme_dark",
              "neon": "ui.theme_neon"}

# The state pill: (property suffix, translation key) per state name.
PILL_STATES = {
    "in_game": ("pill_ok", "ui.pill_in_game"),
    "demo": ("pill_warn", "ui.pill_demo"),
    "client": ("pill_warn", "ui.pill_client"),
    "waiting": ("pill", "ui.pill_waiting"),
    "loading": ("pill", "ui.pill_loading"),
    "error": ("pill_bad", "ui.pill_error"),
}
# The lit dot in front of it. The maquette gives it a box-shadow glow, which is a
# painted halo here.
PILL_DOTS = {"pill_ok": MENU["ok"], "pill_warn": MENU["warn"],
             "pill_bad": MENU["danger"], "pill": MENU["accent"]}

# The sentence the home page leads with, per state. Held here rather than in a
# chain of ifs so that adding a state cannot silently keep the previous one's
# headline on screen.
HEADLINES = {
    "loading": ("ui.home_headline_boot", "ui.home_headline_boot_hint"),
    "in_game": ("ui.home_headline_live", "ui.home_headline_live_hint"),
    "demo": ("ui.home_headline_demo", "ui.home_headline_demo_hint"),
}
HEADLINE_IDLE = ("ui.home_headline_idle", "ui.home_headline_idle_hint")

# ---------------------------------------------------------------------------
# The canvas, and the frame around it. All from `Flashwatch App.dc.html`.
# ---------------------------------------------------------------------------
CANVAS = QSize(1448, 1086)
TITLE_H = 48
RAIL_W = 237
NAV_H = 64

# Weights, mapped once. The maquettes speak CSS numbers; Qt has its own scale.
W500 = QFont.Medium
W600 = QFont.DemiBold
W700 = QFont.Bold
W800 = QFont.ExtraBold


# ---------------------------------------------------------------------------
# Drawing the three displays at thumbnail size
# ---------------------------------------------------------------------------
def paint_layout_sketch(painter: QPainter, rect: QRect, kind: str) -> None:
    """Sketch one overlay display inside ``rect``.

    A picture rather than a sentence, because the difference between the three is
    entirely visual: "the icon slides left to right" is a paragraph and a
    thumbnail at the same time, and only one of the two is read.

    Shared with the setup guide on purpose -- the guide shows the same three
    sketches the settings page does, so what was chosen there is recognised here.

    The three entries in every sketch are the overlay's own ladder, in its own
    order: green far off, amber halfway, red about to land. A thumbnail that
    coloured them any other way would be teaching the wrong reading of the thing
    it is a picture of.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    dim = QColor(INK_FAINT)
    ready = QColor(READY)
    ladder = (QColor(READY), QColor(SOON), QColor(DANGER))
    faint = QColor(INK_FAINT)
    faint.setAlpha(70)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(*PAINT["sketch_bg"]))
    painter.drawRoundedRect(rect, 4, 4)

    if kind == LAYOUT_BAR:
        # A rail with three tokens on it, spread the way progress spreads them.
        y = rect.center().y() - rect.height() // 6
        left = rect.left() + 10
        right = rect.right() - 10
        painter.setPen(QPen(faint, 2))
        painter.drawLine(left, y, right, y)
        painter.setPen(QPen(ready, 2))
        painter.drawLine(right - int((right - left) * 0.16), y, right, y)
        radius = max(3, rect.height() // 7)
        for fraction, colour in zip((0.12, 0.5, 0.88), ladder):
            x = int(left + (right - left) * fraction)
            painter.setBrush(colour)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRect(x - radius, y - radius,
                                      radius * 2, radius * 2))
            painter.setPen(QPen(colour, 2))
            painter.drawLine(x - radius, y + radius * 2 + 3,
                             x + radius, y + radius * 2 + 3)

    elif kind == LAYOUT_CARDS:
        # Three rings, evenly spaced, each with its number under it.
        radius = max(5, min(rect.height() // 4, rect.width() // 9))
        spacing = radius * 3
        centre_y = rect.center().y() - radius // 2
        start = rect.center().x() - spacing
        for index, (progress, colour) in enumerate(
                zip((0.25, 0.62, 0.92), ladder)):
            cx = start + index * spacing
            box = QRect(cx - radius, centre_y - radius, radius * 2, radius * 2)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(faint, 2))
            painter.drawEllipse(box)
            painter.setPen(QPen(colour, 2))
            painter.drawArc(box, 90 * 16, -int(360 * 16 * progress))
            painter.setPen(QPen(colour, 2))
            painter.drawLine(cx - radius + 1, box.bottom() + 6,
                             cx + radius - 1, box.bottom() + 6)

    else:
        # Three rows, each a portrait, a label, a number and a gauge.
        rows = 3
        pad = 7
        height = (rect.height() - pad * 2) // rows
        radius = max(3, height // 3)
        for index, colour in enumerate(ladder):
            top = rect.top() + pad + index * height
            middle = top + height // 2 - 2
            painter.setBrush(dim)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRect(rect.left() + pad, middle - radius,
                                      radius * 2, radius * 2))
            painter.setPen(QPen(dim, 2))
            text_left = rect.left() + pad + radius * 2 + 5
            painter.drawLine(text_left, middle, text_left + 22, middle)
            painter.setPen(QPen(colour, 2))
            painter.drawLine(rect.right() - pad - 14, middle,
                             rect.right() - pad, middle)
            painter.setPen(QPen(faint, 2))
            gauge_y = top + height - 3
            painter.drawLine(rect.left() + pad, gauge_y, rect.right() - pad,
                             gauge_y)
            painter.setPen(QPen(colour, 2))
            filled = int((rect.width() - pad * 2) * (0.3 + index * 0.3))
            painter.drawLine(rect.left() + pad, gauge_y,
                             rect.left() + pad + filled, gauge_y)

    painter.restore()


# ---------------------------------------------------------------------------
# The controls the maquettes draw that Qt does not have
# ---------------------------------------------------------------------------
class Switch(QAbstractButton):
    """The maquettes' toggle: a track, a white knob, a label beside it.

    A QCheckBox with a restyled ``::indicator`` gets most of the way there and
    then stops: the knob has to *travel*, and QSS has neither a transform nor a
    transition. So it is painted, and the travel is one animated number -- the
    same 200 ms the maquettes' CSS uses.

    It is a QAbstractButton, so everything that treated these as checkboxes still
    works: ``setChecked``, ``isChecked``, ``toggled``, ``blockSignals``.

    The three sizes come from the files: 46 x 26 with a 20 px knob on Reglages,
    44 x 24 with an 18 px knob on Affichage.
    """

    def __init__(self, text: str = "", *, track: QSize = QSize(46, 26),
                 knob: int = 20, gap: int = 16) -> None:
        super().__init__(None)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._track = track
        self._knob = knob
        self._gap = gap
        self._travel = 1.0 if self.isChecked() else 0.0
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(200)
        self._motion.setEasingCurve(QEasingCurve.OutCubic)
        self._motion.valueChanged.connect(self._on_travel)
        self.toggled.connect(self._on_toggled)

    def set_metrics(self, track: QSize, knob: int, gap: int) -> None:
        self._track = track
        self._knob = knob
        self._gap = gap
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        width = self._track.width()
        if self.text():
            width += self._gap + metrics.horizontalAdvance(self.text())
        return QSize(width, max(self._track.height(), metrics.height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(self._track.width(), self._track.height())

    def _on_toggled(self, checked: bool) -> None:
        # Nothing animates in a window nobody is looking at: a switch built
        # before the window is shown must *arrive* at its state rather than be
        # left mid-slide.
        if not self.isVisible():
            self._travel = 1.0 if checked else 0.0
            self.update()
            return
        self._motion.stop()
        self._motion.setStartValue(self._travel)
        self._motion.setEndValue(1.0 if checked else 0.0)
        self._motion.start()

    def _on_travel(self, value) -> None:
        self._travel = float(value)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        height = self._track.height()
        top = (self.height() - height) / 2
        track = QRectF(0, top, self._track.width(), height)

        off = QColor(MENU["track"])
        on = QColor(MENU["accent_deep"])
        blend = QColor(
            round(off.red() + (on.red() - off.red()) * self._travel),
            round(off.green() + (on.green() - off.green()) * self._travel),
            round(off.blue() + (on.blue() - off.blue()) * self._travel))
        painter.setPen(Qt.NoPen)
        painter.setBrush(blend)
        painter.drawRoundedRect(track, height / 2, height / 2)

        pad = (height - self._knob) / 2
        left = track.left() + pad + (track.width() - self._knob - pad * 2) * self._travel
        painter.setBrush(QColor(MENU["knob"] if self.isEnabled()
                                else MENU["dim_2"]))
        painter.drawEllipse(QRectF(left, top + pad, self._knob, self._knob))

        if self.text():
            painter.setPen(QColor(MENU["ink_2"] if self.isEnabled()
                                  else MENU["dim_2"]))
            painter.setFont(self.font())
            painter.drawText(
                QRectF(self._track.width() + self._gap, 0,
                       self.width() - self._track.width() - self._gap,
                       self.height()),
                Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def hitButton(self, _point) -> bool:
        # The label is part of the switch, as it is in the maquettes: a target
        # 46 px wide next to the words explaining it is a target people miss.
        return True


class Select(QComboBox):
    """A combo box wearing the maquettes' chevron.

    Qt's own arrow is drawn by the style, which means no rule in the stylesheet
    can recolour it, and pointing ``image:`` at a file is not an option in a
    program that ships no image files. The sub-control is blanked out in the QSS
    and the chevron is drawn here instead.
    """

    def __init__(self, chevron: int = 20, inset: int = 20) -> None:
        super().__init__(None)
        self._chevron = chevron
        self._inset = inset

    def set_chevron(self, size: int, inset: int) -> None:
        self._chevron = size
        self._inset = inset
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        colour = QColor(MENU["dim_2"] if self.isEnabled() else MENU["track"])
        icons.paint_icon(
            painter,
            QRectF(self.width() - self._inset - self._chevron,
                   (self.height() - self._chevron) / 2,
                   self._chevron, self._chevron),
            "chevron_down", colour)


class _Stepper:
    """The up/down chevrons the two spin boxes share.

    A mixin rather than a base class: :class:`QSpinBox` and
    :class:`QDoubleSpinBox` are siblings in Qt, and this is the only thing they
    would have had in common.
    """

    _chevron = 18
    _inset = 20

    def set_chevron(self, size: int, inset: int) -> None:
        self._chevron = size
        self._inset = inset
        self.update()

    def _paint_arrows(self, widget: QWidget) -> None:
        painter = QPainter(widget)
        colour = QColor(MENU["dim_2"] if widget.isEnabled() else MENU["track"])
        box = float(self._chevron)
        x = widget.width() - self._inset - box
        painter.save()
        painter.translate(x + box / 2, widget.height() * 0.30)
        painter.rotate(180)
        painter.translate(-box / 2, -box / 2)
        icons.paint_icon(painter, QRectF(0, 0, box, box), "chevron_down", colour)
        painter.restore()
        icons.paint_icon(painter, QRectF(x, widget.height() * 0.52, box, box),
                         "chevron_down", colour)


class Spin(QSpinBox, _Stepper):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_arrows(self)


class Scale(QDoubleSpinBox, _Stepper):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_arrows(self)


class Tile(QLabel):
    """The rounded square carrying a card's icon: 52 px, radius 12, icon 26."""

    def __init__(self, glyph: str, *, fill: str = MENU["tile"],
                 edge: str = MENU["tile_edge"]) -> None:
        super().__init__()
        self._glyph = glyph
        self._fill = fill
        self._edge = edge
        self._radius = 12.0
        self._icon = 26.0

    def set_metrics(self, size: int, radius: float, icon: float) -> None:
        self.setFixedSize(size, size)
        self._radius = radius
        self._icon = icon
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(QColor(self._edge), 1))
        painter.setBrush(QColor(self._fill))
        painter.drawRoundedRect(rect, self._radius, self._radius)
        centre = rect.center()
        icons.paint_icon(painter,
                         QRectF(centre.x() - self._icon / 2,
                                centre.y() - self._icon / 2,
                                self._icon, self._icon),
                         self._glyph, QColor(MENU["accent_pale"]))


class RingMark(QLabel):
    """The rail's brand: a 76 px ring at 3 px, with the mark inside it."""

    def __init__(self) -> None:
        super().__init__()
        self._stroke = 3.0

    def set_metrics(self, size: int, stroke: float) -> None:
        self.setFixedSize(size, size)
        self._stroke = stroke
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        half = self._stroke / 2

        # The logo fills the ring rather than sitting in the middle of it as a
        # small tile of its own. It arrives as a rounded square, so it is the
        # *square* cut that goes in here and this clip that shapes it: the
        # rounded one would leave four transparent bites inside the circle.
        inner = QRectF(self._stroke, self._stroke,
                       self.width() - self._stroke * 2,
                       self.height() - self._stroke * 2)
        clip = QPainterPath()
        clip.addEllipse(inner)
        painter.save()
        painter.setClipPath(clip)
        painter.drawPixmap(inner.toRect(),
                           mark_pixmap(round(inner.width()), square=True))
        painter.restore()

        painter.setPen(QPen(QColor(MENU["accent_deep"]), self._stroke))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(half, half, self.width() - self._stroke,
                                   self.height() - self._stroke))


class StatePill(QLabel):
    """The word for what the program is doing, with a lit dot in front of it."""

    def __init__(self) -> None:
        super().__init__(tr("ui.pill_loading").upper())
        self.setProperty("role", "pill")
        self._dot = 11.0
        self._inset = 22.0

    def set_metrics(self, dot: float, inset: float) -> None:
        self._dot = dot
        self._inset = inset
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        colour = QColor(PILL_DOTS.get(str(self.property("role")),
                                      MENU["accent"]))
        centre = QRectF(self._inset, (self.height() - self._dot) / 2,
                        self._dot, self._dot)
        # The maquettes' `box-shadow: 0 0 10px`, as two washes: QSS has none.
        for grow, alpha in ((self._dot * 0.5, 40), (self._dot * 0.25, 70)):
            halo = QColor(colour)
            halo.setAlpha(alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(centre.adjusted(-grow, -grow, grow, grow))
        painter.setBrush(colour)
        painter.drawEllipse(centre)


class HeroCard(QFrame):
    """A card with an illustration behind it, faded in from the right.

    The one place this window uses a picture rather than geometry, and it earns
    it: these are the two images the maquettes place behind the home page's
    headline and its enemies card, downscaled into ``resources/art`` at 640 px
    (58 KB and 17 KB -- next to a 99 MB executable, nothing).

    Painted *behind* the card's own children rather than laid out beside them,
    which is what the maquettes do (``position:absolute;right:0`` under a
    ``position:relative`` body), and the picture is faded out towards the text by
    erasing its own alpha rather than by laying a wash over it. A wash is the
    obvious way and it leaves a seam: the card behind is a gradient, so an opaque
    rectangle over it never quite matches at the join, and the eye finds that
    edge immediately.
    """

    def __init__(self, role: str, name: str = "", art_width: int = 520) -> None:
        super().__init__()
        self.setProperty("role", role)
        self._art_width = art_width
        self._pixmap = QPixmap()
        if name:
            path = art_path(name)
            if path.exists():
                self._pixmap = QPixmap(str(path))
            else:
                log.debug("no card art at %s", path)

    def set_art_width(self, width: int) -> None:
        self._art_width = width
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # the gradient and border, from the QSS
        if self._pixmap.isNull():
            return
        panel = QRect(self.width() - self._art_width, 0, self._art_width,
                      self.height())
        if panel.width() <= 0 or panel.height() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 13, 13)
        painter.setClipPath(clip)

        layer = QPixmap(panel.size())
        layer.fill(Qt.transparent)
        inner = QPainter(layer)
        inner.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled = self._pixmap.scaled(panel.size(), Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
        inner.drawPixmap(QRect((panel.width() - scaled.width()) // 2,
                               (panel.height() - scaled.height()) // 2,
                               scaled.width(), scaled.height()), scaled)
        inner.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask = QLinearGradient(0, 0, panel.width(), 0)
        mask.setColorAt(0.0, QColor(0, 0, 0, 0))
        mask.setColorAt(0.45, QColor(0, 0, 0, 70))
        mask.setColorAt(1.0, QColor(0, 0, 0, 225))
        inner.fillRect(layer.rect(), mask)
        inner.end()
        painter.drawPixmap(panel, layer)


class LayoutTile(QWidget):
    """One of the three displays: a radio, a thumbnail, a name, a sentence.

    Clickable anywhere, because the maquette makes the whole row the target --
    and because a 22 px radio beside a 132 px thumbnail is a needle to hit.
    """

    clicked = Signal(str)

    def __init__(self, key: str, title: str, hint: str) -> None:
        super().__init__()
        self.key = key
        self._checked = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._radio = 22.0
        self._thumb = QSize(132, 56)
        self._pad = 16.0
        self._gap = 18.0

        self.title = QLabel(title, self)
        self.title.setProperty("role", "h3")
        self.hint = QLabel(hint, self)
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)

    def set_metrics(self, radio: float, thumb: QSize, pad: float,
                    gap: float) -> None:
        self._radio = radio
        self._thumb = thumb
        self._pad = pad
        self._gap = gap
        self._lay_out()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The row is as tall as its own text, and its text only knows how tall it
        # is once it knows how wide it is -- which is here, not at build time.
        height = self.height_for(self.width())
        if height != self.height():
            self.setFixedHeight(height)
        self._lay_out()

    def _lay_out(self) -> None:
        """Place the two labels beside the thumbnail, at the maquette's offsets."""
        left = round(self._pad + self._radio + self._gap + self._thumb.width()
                     + self._gap)
        width = max(10, self.width() - left - round(self._pad))
        title_h = self.title.sizeHint().height()
        hint_h = self.hint.heightForWidth(width)
        top = round((self.height() - title_h - self._gap / 3 - hint_h) / 2)
        self.title.setGeometry(left, top, width, title_h)
        self.hint.setGeometry(left, round(top + title_h + self._gap / 3), width,
                              hint_h)

    def height_for(self, width: int) -> int:
        """What the maquette's row would be tall at this width: text plus 12+12."""
        left = round(self._pad + self._radio + self._gap + self._thumb.width()
                     + self._gap)
        inner = max(10, width - left - round(self._pad))
        text = (self.title.sizeHint().height() + round(self._gap / 3)
                + self.hint.heightForWidth(inner))
        return max(round(self._thumb.height() + self._pad * 1.5), text + round(self._pad * 1.5))

    def setChecked(self, checked: bool) -> None:
        if checked != self._checked:
            self._checked = checked
            self.update()

    def isChecked(self) -> bool:
        return self._checked

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        radius = self._pad * 0.625            # 10 on a 16 px padding
        body = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setBrush(QColor(MENU["accent_wash_2"] if self._checked
                                else MENU["field"]))
        edge = (MENU["accent_deep"] if self._checked
                else MENU["accent_btn"] if self._hover else "#232941")
        painter.setPen(QPen(QColor(edge), 1))
        painter.drawRoundedRect(body, radius, radius)

        ring = QRectF(self._pad, (self.height() - self._radio) / 2,
                      self._radio, self._radio)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(MENU["accent"] if self._checked
                                   else MENU["ring_off"]), self._radio / 11))
        painter.drawEllipse(ring)
        if self._checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(MENU["accent"]))
            dot = self._radio * 10 / 22
            painter.drawEllipse(QRectF(ring.center().x() - dot / 2,
                                       ring.center().y() - dot / 2, dot, dot))

        thumb = QRect(round(self._pad + self._radio + self._gap),
                      round((self.height() - self._thumb.height()) / 2),
                      self._thumb.width(), self._thumb.height())
        painter.setPen(QPen(QColor(MENU["track"]), 1))
        painter.setBrush(QColor("#161b31"))
        painter.drawRoundedRect(QRectF(thumb).adjusted(0.5, 0.5, -0.5, -0.5),
                                self._radio * 8 / 22, self._radio * 8 / 22)
        inset = round(self._pad * 0.7)
        paint_layout_sketch(painter, thumb.adjusted(inset, round(inset * 0.7),
                                                    -inset, -round(inset * 0.7)),
                            self.key)


class Disclosure(QWidget):
    """A section that says what it is before it is opened.

    The expert switches live in these. Collapsed by default, so the page reads as
    the handful of decisions most people have, with the rest one click away
    rather than deleted.
    """

    def __init__(self, title: str, window: "ControlWindow") -> None:
        super().__init__()
        self._window = window
        self.button = QPushButton(f"   {title}")
        self.button.setProperty("role", "link")
        self.button.setCheckable(True)
        self.button.setCursor(Qt.PointingHandCursor)

        self.body = QWidget()
        self._body_layout = QVBoxLayout(self.body)
        self.body.setVisible(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.button)
        layout.addWidget(self.body)
        window.pad(layout, 0, 0, 0, 0)
        window.gap(layout, 0)
        window.pad(self._body_layout, 0, 14, 0, 0)
        window.gap(self._body_layout, 10)
        window.icon_on(self.button, "chevron_right", 9, MENU["accent_pale"])
        window.size_of(self.button, height=22)
        self.button.toggled.connect(self._on_toggled)

    def addWidget(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def addLayout(self, layout) -> None:
        self._body_layout.addLayout(layout)

    def _on_toggled(self, checked: bool) -> None:
        self.body.setVisible(checked)
        # The marker turns rather than changes: a "▸" would be a gamble on the
        # face having that glyph, and Mulish does not -- a missing one comes out
        # as nothing at all, so the section would lose its only sign that it
        # opens.
        self._window.icon_on(self.button,
                             "chevron_down" if checked else "chevron_right",
                             9, MENU["accent_pale"])


class RegionPicker(QWidget):
    """Full-screen overlay for drawing the chat region by hand.

    The automatic detector is good but cannot be verified without a real game
    running, so a manual override is the guaranteed fallback.
    """

    region_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self._origin = None
        self._current = None

    def start(self) -> None:
        # Cover the whole virtual desktop so a region can be drawn on any monitor.
        geometry = None
        for screen in QGuiApplication.screens():
            geometry = (screen.geometry() if geometry is None
                        else geometry.united(screen.geometry()))
        if geometry is not None:
            self.setGeometry(geometry)
        self._origin = self._current = None
        self.show()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._origin is None or self._current is None:
            self.close()
            return
        rect = QRect(self._origin, self._current).normalized()
        self._origin = self._current = None
        self.hide()
        if rect.width() >= 40 and rect.height() >= 20:
            offset = self.geometry().topLeft()
            self.region_selected.emit(ChatRegion(
                rect.left() + offset.x(), rect.top() + offset.y(),
                rect.width(), rect.height(), source="manuel"))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._origin = self._current = None
            self.hide()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        painter.setPen(QPen(QColor(MENU["accent"]), 2))
        font = QFont(menu_family())
        font.setPixelSize(18)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, 40, 0, 0),
                         Qt.AlignHCenter | Qt.AlignTop, tr("picker.hint"))
        if self._origin is None or self._current is None:
            return
        rect = QRect(self._origin, self._current).normalized()
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        path.addRect(QRectF(rect))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(MENU["accent"]), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)


class TitleBar(QWidget):
    """The window's own chrome, because the maquettes draw their own.

    48 px tall, the mark and the name at 18 px in from the left, and three 56 px
    buttons -- the numbers in ``Flashwatch App.dc.html``. Dragging it moves the
    window and a double-click maximises it, which is what the frame it replaces
    did.
    """

    def __init__(self, window: "ControlWindow") -> None:
        super().__init__()
        self.setObjectName("TitleBar")
        self._window = window
        self._press: QPoint | None = None

        layout = QHBoxLayout(self)
        window.pad(layout, 18, 0, 0, 0)
        window.gap(layout, 12)
        window.size_of(self, height=TITLE_H)

        self.mark = QLabel()
        window.size_of(self.mark, 20, 20)
        self.title = QLabel(f"Flashwatch — v{__version__}")
        self.title.setObjectName("TitleText")
        window.font(self.title, 17, W600)
        layout.addWidget(self.mark)
        layout.addWidget(self.title)
        layout.addStretch(1)

        self.buttons: list[QPushButton] = []
        for glyph, slot, role in (
                ("minimise", window.showMinimized, "chrome"),
                ("maximise", window.toggle_max, "chrome"),
                ("close", window.close, "chrome_close")):
            button = QPushButton()
            button.setProperty("role", role)
            button.setProperty("chrome", glyph)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(slot)
            window.size_of(button, 56, TITLE_H)
            layout.addWidget(button)
            self.buttons.append(button)

    def rescale(self, scale: float) -> None:
        """Redraw the mark and the three glyphs at the window's scale."""
        size = max(8, round(20 * scale))
        self.mark.setPixmap(mark_pixmap(size))
        for button in self.buttons:
            button.setIcon(self._chrome_icon(str(button.property("chrome")),
                                             scale))
            button.setIconSize(QSize(max(8, round(16 * scale)),
                                     max(8, round(16 * scale))))

    @staticmethod
    def _chrome_icon(kind: str, scale: float) -> QIcon:
        """The three window glyphs, drawn: a dash, a square, a cross."""
        size = max(8, round(16 * scale))
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(size / 16.0, size / 16.0)
        pen = QPen(QColor(MENU["dim_2"]), 1.4)
        pen.setCapStyle(Qt.SquareCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if kind == "minimise":
            painter.drawLine(3, 8, 13, 8)
        elif kind == "maximise":
            painter.drawRect(QRectF(3.5, 3.5, 9, 9))
        else:
            painter.drawLine(3, 3, 13, 13)
            painter.drawLine(13, 3, 3, 13)
        painter.end()
        return QIcon(pixmap)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = (event.globalPosition().toPoint()
                           - self._window.frameGeometry().topLeft())

    def mouseMoveEvent(self, event) -> None:
        if self._press is None or not (event.buttons() & Qt.LeftButton):
            return
        # Dragging it is the user placing it, so it stops being centred.
        self._window._placed = True
        self._window.move(event.globalPosition().toPoint() - self._press)

    def mouseReleaseEvent(self, _event) -> None:
        self._press = None

    def mouseDoubleClickEvent(self, _event) -> None:
        self._window.toggle_max()


class ControlWindow(QWidget):
    """Status, the overlay's look and position, preferences, diagnostics."""

    redetect_requested = Signal()
    manual_region_requested = Signal()
    test_mode_toggled = Signal(str, bool)     # (zone, enabled)
    region_cleared = Signal()
    reset_requested = Signal()
    overlay_visibility_toggled = Signal(bool)
    overlay_lock_toggled = Signal(bool)
    settings_changed = Signal()
    recentre_requested = Signal()
    demo_toggled = Signal(bool)                # trial mode, on or off
    quit_requested = Signal()
    language_changed = Signal(str)
    hidden_to_tray = Signal()
    guide_requested = Signal()                # (re)open the setup guide
    update_requested = Signal()               # install the offered version
    update_notes_requested = Signal()         # open the release page
    update_skipped = Signal()                 # do not offer this one again
    update_check_requested = Signal()         # look now, from the settings page

    def __init__(self, settings, assets) -> None:
        super().__init__(None)
        self.settings = settings
        self.assets = assets
        self._loading = True
        self._layout_key = self._current_layout()
        self._role_combos: dict[str, QComboBox] = {}
        # Everything the scale touches, recorded as it is built and replayed
        # whenever the scale changes. Without this the window could be drawn at
        # one size only: there is no elastic layout to fall back on, by design.
        self._scaled: list[tuple] = []
        self._scale = 1.0
        self._maximised = False
        self._placed = False

        self.setWindowTitle(f"{tr('app.title')}  —  v{__version__}")
        # Frameless, because the maquettes draw the title bar. The window keeps
        # its taskbar button and Alt-Tab entry -- it is a plain top-level window,
        # not a Qt.Tool.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        self.shell = QWidget(self)
        self.shell.setObjectName("Shell")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.shell)

        self.stack = QStackedWidget()
        pages = [
            ("home", tr("ui.nav_home"), self._build_home_page()),
            ("eye", tr("ui.nav_display"), self._build_display_page()),
            ("gear", tr("ui.nav_settings"), self._build_settings_page()),
            ("alert", tr("ui.nav_help"), self._build_help_page()),
        ]
        for _glyph, _label, page in pages:
            self.stack.addWidget(self._scrollable(page))

        self.title_bar = TitleBar(self)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail(pages))
        body.addWidget(self._build_content(), 1)

        layout = QVBoxLayout(self.shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar)
        layout.addLayout(body, 1)

        self.nav_buttons[0].setChecked(True)
        self._apply_scale(self._fitted_scale())
        self._loading = False

    # ------------------------------------------------------------------
    # One canvas, one scale
    # ------------------------------------------------------------------
    def s(self, value: float) -> int:
        """A maquette length, in this window's pixels."""
        return max(0, round(value * self._scale))

    def _fitted_scale(self) -> float:
        """The largest scale whose canvas still fits the screen it opens on."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1.0
        room = screen.availableGeometry()
        return max(0.5, min((room.width() - 40) / CANVAS.width(),
                            (room.height() - 40) / CANVAS.height(), 1.0))

    def _maximised_scale(self) -> float:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return 1.0
        room = screen.availableGeometry()
        return max(0.5, min(room.width() / CANVAS.width(),
                            room.height() / CANVAS.height()))

    def centre(self) -> None:
        """Put the window in the middle of the screen it is on.

        A frameless window is never placed by Windows -- there is no frame for
        the window manager to position, so it opens at the top-left corner and
        stays there. The guide does the same thing for the same reason.
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        room = screen.availableGeometry()
        self.move(room.left() + (room.width() - self.width()) // 2,
                  room.top() + (room.height() - self.height()) // 2)

    def toggle_max(self) -> None:
        """Grow the canvas to fill the screen, or put it back.

        Not ``showMaximized``: the window is a fixed-ratio drawing, and a
        maximised frame would stretch its frame around a canvas that cannot
        stretch. Growing the scale is the same gesture done properly.
        """
        self._maximised = not self._maximised
        self._apply_scale(self._maximised_scale() if self._maximised
                          else self._fitted_scale())
        self.centre()

    def showEvent(self, event) -> None:
        """Centre it the first time, and only the first time.

        After that its position is the user's: somebody who dragged it to their
        second monitor and closed it wants it back where they left it, not back
        in the middle.
        """
        super().showEvent(event)
        if not self._placed:
            self._placed = True
            self.centre()

    # -- the registry --------------------------------------------------
    def size_of(self, widget: QWidget, width: float | None = None,
                height: float | None = None) -> QWidget:
        self._scaled.append(("size", widget, (width, height)))
        return widget

    def pad(self, layout: QLayout, left: float, top: float, right: float,
            bottom: float) -> QLayout:
        self._scaled.append(("pad", layout, (left, top, right, bottom)))
        return layout

    def gap(self, layout: QLayout, value: float) -> QLayout:
        self._scaled.append(("gap", layout, (value,)))
        return layout

    def space(self, layout, value: float) -> QSpacerItem:
        """A fixed gap, the way the maquettes' ``margin-top`` reads."""
        item = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.addItem(item)
        self._scaled.append(("space", item, (value,)))
        return item

    def font(self, widget: QWidget, size: float, weight=W500, *,
             mono: bool = False, spacing: float = 0.0,
             italic: bool = False) -> QWidget:
        self._scaled.append(("font", widget, (size, weight, mono, spacing,
                                              italic)))
        return widget

    def icon_on(self, widget: QWidget, glyph: str, size: float,
                colour: str) -> QWidget:
        """An icon that is redrawn when the scale changes, on a label or button."""
        self._scaled.append(("icon", widget, (glyph, size, colour)))
        return widget

    def custom(self, widget: QWidget, apply) -> QWidget:
        """Anything else that needs the scale: ``apply(widget, s)``."""
        self._scaled.append(("custom", widget, (apply,)))
        return widget

    def _fit_nav(self, scale: float) -> tuple[int, float]:
        """How many spaces before a nav label, and how much padding around it.

        The maquette's row is padding 18, gap 18, a 24 px icon and 19 px type
        inside 205 px, which leaves 127 px for the word. "Dépannage" is 95 and
        fits; "Troubleshooting" is about 150 and does not -- the HTML would not
        hold it either. Rather than shrink the type, which is the part of the
        design anybody would notice, the gap gives way, and only as far as it has
        to: French keeps the maquette's numbers exactly, English tightens by a
        few pixels. Returns the pair the caller must then apply -- the gap is
        spaces because Qt has no icon-to-text spacing to set.
        """
        font = QFont(menu_family())
        font.setPixelSize(max(6, round(19 * scale)))
        font.setWeight(W700)                       # the selected row is the wide one
        metrics = QFontMetrics(font)
        labels = [tr(key) for key in ("ui.nav_home", "ui.nav_display",
                                      "ui.nav_settings", "ui.nav_help")]
        icon = max(6, round(24 * scale)) + 6       # Qt's own icon/text spacing
        for spaces, padding in ((4, 18.0), (2, 14.0), (1, 12.0)):
            room = (round(RAIL_W * scale) - 2 * round(16 * scale)
                    - 2 * round(padding * scale) - icon)
            widest = max(metrics.horizontalAdvance(" " * spaces + text)
                         for text in labels)
            if widest <= room:
                return spaces, padding
        return 1, 12.0

    def _apply_scale(self, scale: float) -> None:
        """Redraw the whole canvas at ``scale``. The only place sizes are set."""
        self._scale = scale
        spaces, nav_padding = self._fit_nav(scale)
        self.setStyleSheet(control_qss(scale, nav_padding))
        for button in getattr(self, "nav_buttons", ()):
            button.setText(" " * spaces + str(button.property("label")))
        family = menu_family()
        for kind, target, args in self._scaled:
            try:
                if kind == "size":
                    width, height = args
                    if width is not None:
                        target.setFixedWidth(self.s(width))
                    if height is not None:
                        target.setFixedHeight(self.s(height))
                elif kind == "maxw":
                    target.setMaximumWidth(self.s(args[0]))
                elif kind == "pad":
                    target.setContentsMargins(*(self.s(v) for v in args))
                elif kind == "gap":
                    target.setSpacing(self.s(args[0]))
                elif kind == "space":
                    target.changeSize(0, self.s(args[0]), QSizePolicy.Minimum,
                                      QSizePolicy.Fixed)
                elif kind == "font":
                    size, weight, mono, spacing, italic = args
                    font = QFont("Consolas" if mono else family)
                    font.setPixelSize(max(6, round(size * scale)))
                    font.setWeight(weight)
                    font.setItalic(italic)
                    if spacing:
                        font.setLetterSpacing(QFont.AbsoluteSpacing,
                                              spacing * scale)
                    target.setFont(font)
                    # A spin box does not pass its font to the line edit it is
                    # built from, so the number inside it stays at the
                    # application default while its suffix follows the widget.
                    editor = getattr(target, "lineEdit", None)
                    if callable(editor) and editor() is not None:
                        editor().setFont(font)
                elif kind == "icon":
                    glyph, size, colour = args
                    pixels = max(6, round(size * scale))
                    pixmap = icons.icon(glyph, pixels, colour)
                    if isinstance(target, QAbstractButton):
                        target.setIcon(QIcon(pixmap))
                        target.setIconSize(QSize(pixels, pixels))
                    else:
                        target.setPixmap(pixmap)
                elif kind == "custom":
                    args[0](target, scale)
            except RuntimeError:                      # pragma: no cover
                continue                              # a widget already gone
        self.title_bar.rescale(scale)
        self.setFixedSize(self.s(CANVAS.width()), self.s(CANVAS.height()))
        self._sync_nav_icons()

    # ------------------------------------------------------------------
    # Small builders
    # ------------------------------------------------------------------
    def _current_layout(self) -> str:
        value = str(self.settings.get("overlay_layout", LAYOUT_BAR))
        return value if value in LAYOUTS else LAYOUT_BAR

    def label(self, text: str, size: float, weight=W500, *, role: str = "",
              width: float | None = None, max_width: float | None = None,
              line: float | None = None, wrap: bool = True, mono: bool = False,
              spacing: float = 0.0, italic: bool = False) -> QLabel:
        """One piece of text, at the maquette's size, weight and line height.

        ``line`` is the CSS ``line-height``: 16 px type on a 27 px line is a
        deliberate rhythm and Qt's default leading is nowhere near it, so a
        paragraph that needs one is set as rich text with the line height in it.
        That is the same reason the guide measures its own paragraphs by hand.

        ``width`` and ``max_width`` are not the same thing, and the difference is
        worth spelling out because getting it wrong is invisible until it is
        glaring. CSS ``max-width`` is a *cap*: the paragraph stays against the
        left edge of a column that is still full width. A fixed width caps the
        column too -- a QVBoxLayout can be no wider than its narrowest child's
        maximum -- and the row above then has space left over, which Qt spreads
        around the items. That is how the home page's icon and headline ended up
        floating in the middle of a card instead of sitting against its edge.
        """
        widget = QLabel()
        if role:
            widget.setProperty("role", role)
        widget.setWordWrap(wrap)
        widget.setTextInteractionFlags(Qt.NoTextInteraction)
        if width is not None:
            self.size_of(widget, width=width)
        if max_width is not None:
            self._scaled.append(("maxw", widget, (max_width,)))
        self.font(widget, size, weight, mono=mono, spacing=spacing,
                  italic=italic)
        if line:
            self.custom(widget, lambda w, s, t=text, ln=line:
                        w.setText(f'<div style="line-height:{round(ln * s)}px">'
                                  f'{_escape(t)}</div>'))
        else:
            widget.setText(text)
        return widget

    def button(self, text: str, glyph: str = "", *, role: str = "",
               height: float = 56, size: float = 16, weight=W600,
               icon: float = 20, colour: str = "", width: float | None = None,
               gap: float = 14) -> QPushButton:
        """A button at the maquette's height, type size and icon size."""
        button = QPushButton(text)
        if role:
            button.setProperty("role", role)
        button.setCursor(Qt.PointingHandCursor)
        self.size_of(button, width, height)
        self.font(button, size, weight)
        if glyph:
            self.icon_on(button, glyph, icon, colour or MENU["dim_2"])
        return button

    def _scrollable(self, page: QWidget) -> QScrollArea:
        """A page behind a scroll area.

        The canvas is fixed, so this is not there to make the window elastic --
        it is there because two of the four maquettes are taller than the frame
        they are drawn in (Affichage is 1370 px against a 1086 px window), and
        the maquette's own container says ``overflow-y:auto``.
        """
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        return area

    def _page(self, left: float, top: float, right: float,
              bottom: float, gap: float) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.pad(layout, left, top, right, bottom)
        self.gap(layout, gap)
        return page, layout

    def _card(self, role: str, padding: tuple[float, float, float, float],
              gap: float = 0) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("role", role)
        layout = QVBoxLayout(card)
        self.pad(layout, *padding)
        self.gap(layout, gap)
        return card, layout

    def _row(self, gap: float, *, margins=(0, 0, 0, 0)) -> QHBoxLayout:
        row = QHBoxLayout()
        self.pad(row, *margins)
        self.gap(row, gap)
        return row

    def _column(self, gap: float = 0, *, margins=(0, 0, 0, 0)) -> QVBoxLayout:
        column = QVBoxLayout()
        self.pad(column, *margins)
        self.gap(column, gap)
        return column

    def _rule(self, role: str = "hr", *, vertical: bool = False) -> QFrame:
        line = QFrame()
        line.setProperty("role", role)
        if vertical:
            self.size_of(line, width=1)
        else:
            self.size_of(line, height=1)
        return line

    # ------------------------------------------------------------------
    # The shell
    # ------------------------------------------------------------------
    def _build_rail(self, pages) -> QWidget:
        """The side rail: who this is, where to go, and the two ways out.

        ``Flashwatch App.dc.html``: 237 wide, padding 32/16/22, a 76 px ring, the
        name at 27/700, nav rows of 64 at 19 px, and two 60 px buttons at the
        bottom.
        """
        rail = QWidget()
        rail.setObjectName("Rail")
        self.size_of(rail, width=RAIL_W)
        layout = QVBoxLayout(rail)
        self.pad(layout, 16, 32, 16, 22)
        self.gap(layout, 0)

        brand = self._column(0, margins=(18, 0, 18, 0))
        ring = RingMark()
        self.custom(ring, lambda w, s: w.set_metrics(max(20, round(76 * s)),
                                                     max(1.0, 3 * s)))
        brand.addWidget(ring)
        self.space(brand, 24)
        name = self.label("Flashwatch", 27, W700, wrap=False, spacing=-0.2)
        name.setObjectName("RailName")
        brand.addWidget(name)
        self.space(brand, 6)
        version = self.label(f"v{__version__}", 16, W600, wrap=False)
        version.setObjectName("RailVersion")
        brand.addWidget(version)
        self.space(brand, 16)
        rule = QFrame()
        rule.setObjectName("RailRule")
        self.size_of(rule, height=1)
        brand.addWidget(rule)
        self.space(brand, 16)
        tagline = self.label(tr("ui.tagline"), 15, W500, line=24)
        tagline.setObjectName("RailTagline")
        brand.addWidget(tagline)
        layout.addLayout(brand)

        self.space(layout, 30)
        self.nav_buttons: list[QPushButton] = []
        nav = self._column(6)
        for index, (glyph, label, _page) in enumerate(pages):
            button = QPushButton(f"    {label}")
            button.setProperty("role", "nav")
            button.setProperty("glyph", glyph)
            button.setProperty("label", label)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.PointingHandCursor)
            self.size_of(button, height=NAV_H)
            self.font(button, 19, W500)
            self.icon_on(button, glyph, 24, MENU["dim_2"])
            button.toggled.connect(self._on_nav_toggled)
            button.clicked.connect(
                lambda _checked=False, i=index: self.stack.setCurrentIndex(i))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        layout.addLayout(nav)

        layout.addStretch(1)

        bottom = self._column(14)
        hide_button = self.button(tr("ui.hide_window"), "eye_off", role="ghost",
                                  height=60, size=15, icon=22)
        hide_button.setToolTip(tr("ui.hide_window_tip"))
        hide_button.clicked.connect(self.hide)
        quit_button = self.button(tr("ui.quit_rail"), "close", role="danger",
                                  height=60, size=15, icon=22,
                                  colour=MENU["danger"])
        quit_button.clicked.connect(self.quit_requested.emit)
        bottom.addWidget(hide_button)
        bottom.addWidget(quit_button)
        layout.addLayout(bottom)
        return rail

    def _on_nav_toggled(self, _checked: bool) -> None:
        self._sync_nav_icons()

    def _sync_nav_icons(self) -> None:
        """A selected row's icon goes pale violet, as it does in the maquettes.

        Qt cannot recolour an icon from a stylesheet, so the pixmap is swapped
        when the state changes. Both are cached, so this is a lookup.
        """
        size = max(6, round(24 * self._scale))
        for button in getattr(self, "nav_buttons", ()):
            colour = (MENU["accent_pale"] if button.isChecked()
                      else MENU["dim_2"])
            button.setIcon(QIcon(icons.icon(str(button.property("glyph")),
                                            size, colour)))
            button.setIconSize(QSize(size, size))

    def _build_content(self) -> QWidget:
        """The right-hand side: padding 22/28, the pages, and the update strip."""
        content = QWidget()
        layout = QVBoxLayout(content)
        self.pad(layout, 28, 22, 28, 0)
        self.gap(layout, 0)

        # The pill belongs to the frame, not to a page. All four maquettes carry
        # it, each in a slightly different spot; the frame is the App file's, so
        # this is the App file's: the content column's own top-right corner.
        pill_row = self._row(0)
        pill_row.addStretch(1)
        self.label_pill = self._pill(44, 22, 11, 15)
        pill_row.addWidget(self.label_pill)
        layout.addLayout(pill_row)
        self.space(layout, 14)

        # Above the pages, not inside one: an update the user has not seen yet is
        # the one thing in this window worth reading before whatever they opened
        # it for. It occupies no space at all until there is something to say.
        layout.addWidget(self._build_update_banner())
        layout.addWidget(self.stack, 1)
        return content

    def _build_update_banner(self) -> QWidget:
        """The strip that offers a newer version. Hidden until there is one."""
        self.update_banner, layout = self._card("hero", (26, 20, 30, 22), 0)
        self.update_banner.setVisible(False)

        self.label_update = self.label("", 24, W600, role="h2")
        layout.addWidget(self.label_update)
        self.space(layout, 12)
        # Said up front rather than in a dialog afterwards: "will this lose my
        # settings?" is the question that stops someone pressing the button.
        self.label_update_hint = self.label(tr("update.keeps_settings"), 16,
                                            W500, role="body", line=27)
        layout.addWidget(self.label_update_hint)
        self.space(layout, 20)

        buttons = self._row(16)
        self.button_update = self.button(tr("update.install"), "refresh",
                                         role="primary", height=56, size=17,
                                         colour="#ffffff")
        self.button_update.clicked.connect(self.update_requested.emit)
        self.button_update_notes = self.button(tr("update.notes"), height=56,
                                               size=17)
        self.button_update_notes.clicked.connect(self.update_notes_requested.emit)
        self.button_update_skip = self.button(tr("update.skip"), height=56,
                                              size=17)
        self.button_update_skip.clicked.connect(self.update_skipped.emit)
        buttons.addWidget(self.button_update)
        buttons.addWidget(self.button_update_notes)
        buttons.addStretch(1)
        buttons.addWidget(self.button_update_skip)
        layout.addLayout(buttons)
        return self.update_banner

    def _tile(self, glyph: str, size: float = 52, radius: float = 12,
              icon: float = 26, *, fill: str = MENU["tile"],
              edge: str = MENU["tile_edge"]) -> Tile:
        tile = Tile(glyph, fill=fill, edge=edge)
        self.custom(tile, lambda w, s: w.set_metrics(max(12, round(size * s)),
                                                     radius * s, icon * s))
        return tile

    def _pill(self, height: float, padding_left: float, dot: float,
              size: float) -> StatePill:
        pill = StatePill()
        self.size_of(pill, height=height)
        self.font(pill, size, W700, spacing=0.6)
        self.custom(pill, lambda w, s: w.set_metrics(dot * s, padding_left * s))
        return pill

    # ------------------------------------------------------------------
    # Page 1: Accueil  --  Flashwatch App.dc.html
    # ------------------------------------------------------------------
    def _build_home_page(self) -> QWidget:
        page, layout = self._page(0, 0, 0, 22, 0)

        # The headline card: what the program is doing, in a sentence, with the
        # five readouts that are the detail behind it.
        hero = HeroCard("hero", "home-hero.jpg", 520)
        self.custom(hero, lambda w, s: w.set_art_width(round(520 * s)))
        hero_layout = QVBoxLayout(hero)
        self.pad(hero_layout, 26, 26, 30, 26)
        self.gap(hero_layout, 0)

        head = self._row(22)
        head.addWidget(self._tile("play"), 0, Qt.AlignTop)
        column = self._column(0)
        self.label_headline = self.label(tr("ui.home_headline_boot"), 27, W600,
                                         role="h1", spacing=-0.2)
        column.addWidget(self.label_headline)
        self.space(column, 16)
        self.label_headline_hint = self.label(tr("ui.home_headline_boot_hint"),
                                              16, W500, role="body", line=27,
                                              width=680)
        column.addWidget(self.label_headline_hint)
        column.addStretch(1)
        head.addLayout(column, 1)
        # The maquette's text block is capped (`max-width:680`), which caps the
        # column with it -- and a row of items that cannot fill their row is a
        # row Qt spreads out. The leftover is handed to a spacer on the right so
        # the icon and the headline stay against the card's own padding. Stretch
        # *zero*, deliberately: the spacer must take only what the column cannot,
        # and a stretch of one would split the row in half instead.
        head.addStretch(0)
        hero_layout.addLayout(head)
        self.space(hero_layout, 22)
        hero_layout.addWidget(self._build_readouts())
        layout.addWidget(hero)
        self.space(layout, 22)

        # The guide and the self-test, side by side as the maquette has them.
        pair = self._row(22)
        pair.addWidget(self._build_guide_card(), 1)
        pair.addWidget(self._build_test_card(), 1)
        layout.addLayout(pair)
        self.space(layout, 22)

        # Roles used to be a tab of their own, which meant a permanently empty
        # tab: nothing can be in it until a spell has been read. It belongs with
        # the live state instead.
        enemies = HeroCard("hero_3", "enemies.jpg", 460)
        self.custom(enemies, lambda w, s: w.set_art_width(round(460 * s)))
        enemies_row = QHBoxLayout(enemies)
        self.pad(enemies_row, 26, 26, 30, 28)
        self.gap(enemies_row, 22)
        enemies_row.addWidget(self._tile("person"), 0, Qt.AlignTop)
        enemies_column = self._column(0)
        enemies_column.addWidget(self.label(tr("ui.enemies"), 24, W600,
                                            role="h2", width=660))
        self.space(enemies_column, 16)
        enemies_column.addWidget(self.label(tr("ui.team_help"), 16, W500,
                                            role="body", line=27, width=660))
        self.space(enemies_column, 20)
        self.label_team_empty = self.label(tr("ui.team_empty"), 16, W500,
                                           role="dim", line=27, width=660)
        enemies_column.addWidget(self.label_team_empty)
        self.team_container = QWidget()
        self.team_layout = QGridLayout(self.team_container)
        self.pad(self.team_layout, 0, 6, 0, 0)
        self.gap(self.team_layout, 12)
        self.team_container.setVisible(False)
        enemies_column.addWidget(self.team_container)
        enemies_row.addLayout(enemies_column, 1)
        enemies_row.addStretch(0)
        layout.addWidget(enemies)
        self.space(layout, 22)

        footer = self._row(20)
        footer.addStretch(1)
        reset = self.button(tr("ui.reset_timers"), "refresh", role="ghost",
                            height=62, size=18, icon=22)
        reset.clicked.connect(self.reset_requested.emit)
        quit_button = self.button(tr("ui.quit"), "exit", role="primary",
                                  height=62, size=18, weight=W700, icon=22,
                                  colour="#ffffff")
        quit_button.clicked.connect(self.quit_requested.emit)
        footer.addWidget(reset)
        footer.addWidget(quit_button)
        layout.addLayout(footer)
        layout.addStretch(1)
        return page

    def _build_readouts(self) -> QWidget:
        """The five live values, in the maquette's two-column inset panel."""
        panel = QFrame()
        panel.setProperty("role", "inset")
        row = QHBoxLayout(panel)
        self.pad(row, 0, 0, 0, 0)
        self.gap(row, 0)
        self.size_of(panel, width=1090)

        self.label_game = self.label("-", 16, W600, role="value", wrap=False)
        self.label_region = self.label("-", 16, W500, role="value_off",
                                       wrap=False)
        self.label_ocr = self.label("-", 16, W500, role="value", wrap=False)
        self.label_timers = self.label("0", 16, W600, role="value", wrap=False)
        self.label_clock = self.label("-", 16, W500, role="value_off",
                                      wrap=False)

        halves = (
            (18, 120, (("play", MENU["gold"], "ui.state_game", self.label_game),
                       ("bell", MENU["accent"], "ui.state_region",
                        self.label_region),
                       ("clock", MENU["warn"], "ui.state_timers",
                        self.label_timers))),
            (24, 160, (("clock", MENU["accent"], "ui.state_clock",
                        self.label_clock),
                       ("scanner", MENU["info"], "ui.state_ocr",
                        self.label_ocr))),
        )
        for index, (gap, label_width, rows) in enumerate(halves):
            if index:
                row.addWidget(self._rule("hr_2", vertical=True))
            column = self._column(gap, margins=(26, 20, 26, 20))
            for glyph, colour, key, value in rows:
                line = self._row(16)
                mark = QLabel()
                self.size_of(mark, 20, 20)
                self.icon_on(mark, glyph, 20, colour)
                line.addWidget(mark, 0, Qt.AlignVCenter)
                line.addWidget(self.label(tr(key), 16, W500, role="field_label",
                                          width=label_width, wrap=False), 0,
                               Qt.AlignVCenter)
                line.addWidget(value, 1, Qt.AlignVCenter)
                column.addLayout(line)
            column.addStretch(1)
            row.addLayout(column, 1)
        return panel

    def _build_guide_card(self) -> QWidget:
        card, layout = self._card("hero_2", (28, 26, 28, 26), 0)
        row = self._row(22)
        row.addWidget(self._tile("report"), 0, Qt.AlignTop)
        column = self._column(0)
        column.addWidget(self.label(tr("ui.guide_card"), 24, W600, role="h2"))
        self.space(column, 16)
        column.addWidget(self.label(tr("ui.guide_card_hint"), 16, W500,
                                    role="body", line=27))
        self.space(column, 22)
        button_row = self._row(0)
        guide_button = self.button(tr("ui.guide_open"), "exit", role="accent",
                                   height=56, size=17, colour=MENU["accent_pale"])
        guide_button.clicked.connect(self.guide_requested.emit)
        button_row.addWidget(guide_button)
        button_row.addStretch(1)
        column.addLayout(button_row)
        column.addStretch(1)
        row.addLayout(column, 1)
        layout.addLayout(row)
        return card

    def _build_test_card(self) -> QWidget:
        """The one-line self-test.

        It separates the two halves of the pipeline: if a timer appears, capture
        and OCR work and the only thing left is waiting for a real enemy; if it
        does not, the area or the language is wrong.
        """
        card, layout = self._card("hero_2", (28, 26, 28, 26), 0)
        row = self._row(22)
        row.addWidget(self._tile("check_circle"), 0, Qt.AlignTop)
        column = self._column(0)
        column.addWidget(self.label(tr("ui.test_line_title"), 24, W600,
                                    role="h2"))
        self.space(column, 14)
        column.addWidget(self.label(tr("ui.test_line_hint"), 16, W500,
                                    role="body", line=27))
        self.space(column, 20)

        line_row = self._row(16)
        line_box, line_layout = self._card("sunken", (20, 0, 20, 0), 0)
        self.size_of(line_box, height=56)
        line = self.label(tr("ui.test_line"), 15, W500, role="mono", wrap=False,
                          mono=True)
        # Allowed to be narrower than its own text and clipped rather than
        # wrapped -- the maquette's `white-space:nowrap;overflow:hidden`.
        line.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        line_layout.addWidget(line)
        self.button_copy = self.button(tr("ui.copy"), "copy", role="primary",
                                       height=56, size=17, colour="#ffffff")
        self.button_copy.clicked.connect(self._on_copy_test_line)
        line_row.addWidget(line_box, 1)
        line_row.addWidget(self.button_copy)
        column.addLayout(line_row)
        column.addStretch(1)
        row.addLayout(column, 1)
        layout.addLayout(row)
        return card

    def _on_copy_test_line(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(tr("ui.test_line"))
        # Confirmed on the button itself: a copy that says nothing is
        # indistinguishable from a click that missed.
        self.button_copy.setText(tr("ui.copied"))

    # ------------------------------------------------------------------
    # Page 2: Affichage  --  Flashwatch Affichage.dc.html
    # ------------------------------------------------------------------
    def _build_display_page(self) -> QWidget:
        page, layout = self._page(0, 0, 0, 20, 12)

        # First on the page, because everything under it is a decision that
        # cannot be made from a description: which of the three displays, where
        # it sits, which theme, how big.
        trial, trial_layout = self._card("card_2", (20, 18, 20, 18), 0)
        row = self._row(20)
        row.addWidget(self._tile("scanner", 52, 12, 24, fill="#241a4d",
                                 edge="#453a80"), 0, Qt.AlignTop)
        column = self._column(0)
        column.addWidget(self.label(tr("ui.demo"), 23, W600, role="h2"))
        self.space(column, 10)
        column.addWidget(self.label(tr("ui.demo_hint"), 14, W500, role="body",
                                    line=22))
        self.space(column, 16)
        self.button_demo = self.button(tr("ui.demo_start"), "scanner",
                                       role="primary", height=44, size=16,
                                       icon=20, colour="#ffffff")
        self.button_demo.setCheckable(True)
        self.button_demo.toggled.connect(self._on_demo_toggled)
        demo_row = self._row(0)
        demo_row.addWidget(self.button_demo)
        demo_row.addStretch(1)
        column.addLayout(demo_row)
        row.addLayout(column, 1)
        trial_layout.addLayout(row)
        layout.addWidget(trial)

        chooser, chooser_layout = self._card("card_2", (20, 18, 20, 18), 0)
        chooser_layout.addWidget(self.label(tr("ui.display_choose"), 22, W600,
                                            role="h2"))
        self.space(chooser_layout, 10)
        chooser_layout.addWidget(self.label(tr("ui.display_choose_hint"), 14,
                                            W500, role="body"))
        self.space(chooser_layout, 14)
        rows = self._column(10)
        self.layout_tiles: dict[str, LayoutTile] = {}
        for key, title_key, hint_key in (
                (LAYOUT_BAR, "ui.layout_bar", "ui.layout_bar_hint"),
                (LAYOUT_CARDS, "ui.layout_cards", "ui.layout_cards_hint"),
                (LAYOUT_LIST, "ui.layout_list", "ui.layout_list_hint")):
            tile = LayoutTile(key, tr(title_key), tr(hint_key))
            self.font(tile.title, 19, W600)
            self.font(tile.hint, 14, W500)
            self.custom(tile, lambda w, s: (
                w.set_metrics(22 * s, QSize(round(132 * s), round(56 * s)),
                              16 * s, 18 * s),
                w.setFixedHeight(w.height_for(w.width() or 800))))
            tile.clicked.connect(self._on_layout_picked)
            rows.addWidget(tile)
            self.layout_tiles[key] = tile
        chooser_layout.addLayout(rows)
        self._sync_layout_tiles()
        layout.addWidget(chooser)

        position, position_layout = self._card("card_2", (20, 18, 20, 18), 0)
        position_layout.addWidget(self.label(tr("ui.position"), 22, W600,
                                             role="h2"))
        self.space(position_layout, 10)
        position_layout.addWidget(self.label(tr("ui.position_hint"), 14, W500,
                                             role="body"))
        self.space(position_layout, 14)
        moves = self._column(10)
        self.button_move = self.button(tr("ui.move_start"), "move",
                                       role="ghost", height=46, size=16,
                                       icon=20)
        self.button_move.setCheckable(True)
        self.button_move.setChecked(
            not bool(self.settings.get("overlay_locked", True)))
        self.button_move.toggled.connect(self._on_move_toggled)
        recentre = self.button(tr("ui.recentre"), "refresh", role="ghost",
                               height=46, size=16, icon=20)
        recentre.setToolTip(tr("ui.recentre_tip"))
        recentre.clicked.connect(self.recentre_requested.emit)
        moves.addWidget(self.button_move)
        moves.addWidget(recentre)
        position_layout.addLayout(moves)
        self.space(position_layout, 12)
        self.label_move_state = self.label(tr("ui.move_active"), 15, W500,
                                           role="dim", line=24)
        self.label_move_state.setVisible(self.button_move.isChecked())
        position_layout.addWidget(self.label_move_state)
        tip = self._row(12)
        mark = QLabel()
        self.size_of(mark, 20, 20)
        self.icon_on(mark, "info", 20, MENU["accent"])
        tip.addWidget(mark, 0, Qt.AlignTop)
        tip.addWidget(self.label(tr("ui.borderless_tip"), 15, W500, role="dim",
                                 line=24), 1)
        position_layout.addLayout(tip)
        layout.addWidget(position)

        look, look_layout = self._card("card_2", (20, 18, 20, 16), 0)
        look_layout.addWidget(self.label(tr("ui.appearance"), 22, W600,
                                         role="h2"))
        self.space(look_layout, 16)

        self.combo_theme = Select()
        for key, label_key in THEME_KEYS.items():
            self.combo_theme.addItem(tr(label_key), key)
        index = self.combo_theme.findData(str(self.settings.get("theme", "dark")))
        if index >= 0:
            self.combo_theme.setCurrentIndex(index)
        self.combo_theme.currentIndexChanged.connect(self._on_settings_changed)
        self.size_of(self.combo_theme, height=42)
        self.font(self.combo_theme, 16, W500)
        self.custom(self.combo_theme,
                    lambda w, s: w.set_chevron(round(20 * s), round(18 * s)))
        look_layout.addLayout(self._labelled(tr("ui.theme"), self.combo_theme,
                                             78, 22))
        self.space(look_layout, 10)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(35, 100)
        self.slider_opacity.setValue(
            int(float(self.settings.get("overlay_opacity", 0.92)) * 100))
        self.slider_opacity.valueChanged.connect(self._on_settings_changed)
        self.slider_opacity.valueChanged.connect(self._sync_opacity_label)
        self.size_of(self.slider_opacity, height=42)
        self.label_opacity = self.label(f"{self.slider_opacity.value()}%", 15,
                                        W600, role="value", wrap=False)
        self.label_opacity.setAlignment(Qt.AlignCenter)
        self.label_opacity.setProperty("role", "value")
        opacity_box, opacity_layout = self._card("sunken", (0, 0, 0, 0), 0)
        self.size_of(opacity_box, 66, 36)
        opacity_layout.addWidget(self.label_opacity)
        opacity_row = self._labelled(tr("ui.opacity"), self.slider_opacity, 78,
                                     22)
        opacity_row.addWidget(opacity_box)
        look_layout.addLayout(opacity_row)
        self.space(look_layout, 10)

        self.spin_scale = Scale()
        self.spin_scale.setRange(0.6, 2.0)
        self.spin_scale.setSingleStep(0.05)
        self.spin_scale.setValue(float(self.settings.get("overlay_scale", 1.0)))
        self.spin_scale.valueChanged.connect(self._on_settings_changed)
        self.size_of(self.spin_scale, height=42)
        self.font(self.spin_scale, 16, W500)
        self.custom(self.spin_scale,
                    lambda w, s: w.set_chevron(round(16 * s), round(16 * s)))
        look_layout.addLayout(self._labelled(tr("ui.scale"), self.spin_scale,
                                             78, 22))
        self.space(look_layout, 16)

        switches = self._column(10)
        self.check_visible = self._switch(tr("ui.show_overlay"), small=True)
        self.check_visible.setChecked(bool(self.settings.get("overlay_visible")))
        self.check_visible.toggled.connect(self.overlay_visibility_toggled.emit)
        self.check_hide_until_game = self._switch(tr("ui.hide_until_in_game"),
                                                  small=True)
        self.check_hide_until_game.setToolTip(tr("ui.hide_until_in_game_tip"))
        self.check_hide_until_game.setChecked(
            bool(self.settings.get("hide_until_in_game")))
        self.check_hide_until_game.toggled.connect(self._on_settings_changed)
        self.check_idle_bar = self._switch(tr("ui.bar_when_idle"), small=True)
        self.check_idle_bar.setToolTip(tr("ui.bar_when_idle_hint"))
        self.check_idle_bar.setChecked(bool(self.settings.get("bar_show_when_idle")))
        self.check_idle_bar.toggled.connect(self._on_settings_changed)
        # Only the track can be stood on its end, so the switch follows which
        # display is chosen rather than sitting there greyed out with no
        # explanation -- see :meth:`_sync_layout_tiles`.
        self.check_bar_vertical = self._switch(tr("ui.bar_vertical"), small=True)
        self.check_bar_vertical.setToolTip(tr("ui.bar_vertical_hint"))
        self.check_bar_vertical.setChecked(bool(self.settings.get("bar_vertical")))
        self.check_bar_vertical.setVisible(self._layout_key == LAYOUT_BAR)
        self.check_bar_vertical.toggled.connect(self._on_settings_changed)
        self.check_sort_role = self._switch(tr("ui.sort_by_role"), small=True)
        self.check_sort_role.setChecked(bool(self.settings.get("sort_by_role")))
        self.check_sort_role.toggled.connect(self._on_settings_changed)
        for box in (self.check_visible, self.check_hide_until_game,
                    self.check_idle_bar, self.check_bar_vertical,
                    self.check_sort_role):
            switches.addWidget(box)
        look_layout.addLayout(switches)
        self.space(look_layout, 14)

        advanced = Disclosure(tr("ui.advanced"), self)
        self.font(advanced.button, 16, W500)
        self.check_locked = self._switch(tr("ui.locked"), small=True)
        self.check_locked.setToolTip(tr("ui.locked_hint"))
        self.check_locked.setChecked(bool(self.settings.get("overlay_locked")))
        self.check_locked.toggled.connect(self._on_locked_box)
        self.check_hide_ready = self._switch(tr("ui.hide_ready"), small=True)
        self.check_hide_ready.setChecked(
            bool(self.settings.get("hide_ready_entries")))
        self.check_hide_ready.toggled.connect(self._on_settings_changed)
        advanced.addWidget(self.check_locked)
        advanced.addWidget(self.label(tr("ui.locked_hint"), 15, W500,
                                      role="dim", line=24))
        advanced.addWidget(self.check_hide_ready)
        self.spin_ready_linger = Spin()
        self.spin_ready_linger.setRange(0, 60)
        self.spin_ready_linger.setSuffix(" s")
        self.spin_ready_linger.setToolTip(tr("ui.ready_linger_tip"))
        self.spin_ready_linger.setValue(
            int(self.settings.get("ready_linger_seconds", 5)))
        self.spin_ready_linger.valueChanged.connect(self._on_settings_changed)
        self.size_of(self.spin_ready_linger, height=42)
        self.font(self.spin_ready_linger, 16, W500)
        advanced.addLayout(self._labelled(tr("ui.ready_linger"),
                                          self.spin_ready_linger, 140, 22))
        look_layout.addWidget(advanced)
        layout.addWidget(look)

        layout.addStretch(1)
        return page

    def _labelled(self, text: str, widget: QWidget, width: float,
                  gap: float) -> QHBoxLayout:
        """A label of fixed width and the control it names, on one line."""
        row = self._row(gap)
        row.addWidget(self.label(text, 15, W500, role="field_label",
                                 width=width, wrap=False), 0, Qt.AlignVCenter)
        row.addWidget(widget, 1)
        return row

    def _switch(self, text: str, *, small: bool = False) -> Switch:
        """A toggle at one of the two sizes the maquettes use."""
        switch = Switch(text)
        self.font(switch, 16, W500)
        if small:
            self.custom(switch, lambda w, s: (
                w.set_metrics(QSize(round(44 * s), round(24 * s)),
                              round(18 * s), round(16 * s)),
                w.setFixedHeight(round(26 * s))))
        else:
            self.custom(switch, lambda w, s: (
                w.set_metrics(QSize(round(46 * s), round(26 * s)),
                              round(20 * s), round(16 * s)),
                w.setFixedHeight(round(28 * s))))
        return switch

    def _sync_opacity_label(self, value: int) -> None:
        self.label_opacity.setText(f"{value}%")

    def _on_layout_picked(self, key: str) -> None:
        if key not in LAYOUTS or key == self._layout_key:
            return
        self._layout_key = key
        self._sync_layout_tiles()
        self._on_settings_changed()

    def _sync_layout_tiles(self) -> None:
        for key, tile in self.layout_tiles.items():
            tile.setChecked(key == self._layout_key)
        # The vertical switch belongs to the track. Shown only with the track
        # chosen, because a switch that does nothing is worse than no switch: it
        # is read as broken rather than as inapplicable.
        vertical = getattr(self, "check_bar_vertical", None)
        if vertical is not None:
            vertical.setVisible(self._layout_key == LAYOUT_BAR)

    def _on_demo_toggled(self, checked: bool) -> None:
        self.button_demo.setText(tr("ui.demo_stop") if checked
                                 else tr("ui.demo_start"))
        if not self._loading:
            self.demo_toggled.emit(checked)

    def sync_demo(self, active: bool) -> None:
        """Follow the trial being started or stopped from somewhere else.

        The tray has the same switch, and the application stops the trial by
        itself when a real game appears -- a button still reading "stop" after
        that would be the interface lying about what is on screen.
        """
        self.button_demo.blockSignals(True)
        self.button_demo.setChecked(active)
        self.button_demo.blockSignals(False)
        self.button_demo.setText(tr("ui.demo_stop") if active
                                 else tr("ui.demo_start"))

    def _on_move_toggled(self, checked: bool) -> None:
        """The button is "move it", so it asks for the overlay to be unlocked."""
        self.button_move.setText(tr("ui.move_done") if checked
                                 else tr("ui.move_start"))
        self.label_move_state.setVisible(checked)
        if not self._loading:
            self.overlay_lock_toggled.emit(not checked)

    def _on_locked_box(self, locked: bool) -> None:
        if not self._loading:
            self.overlay_lock_toggled.emit(locked)

    # ------------------------------------------------------------------
    # Page 3: Reglages  --  Flashwatch Reglages.dc.html
    # ------------------------------------------------------------------
    def _build_settings_page(self) -> QWidget:
        page, layout = self._page(0, 0, 0, 20, 14)

        # Language first: it is what everything else in this window is written in.
        language, language_column = self._settings_card(
            "globe", tr("ui.language"), tr("ui.language_tip"))
        self.combo_language = Select()
        self.combo_language.addItem(tr("ui.language_fr"), FRENCH)
        self.combo_language.addItem(tr("ui.language_en"), ENGLISH)
        index = self.combo_language.findData(
            ENGLISH if str(self.settings.get("locale", "fr_FR")).lower()
            .startswith("en") else FRENCH)
        if index >= 0:
            self.combo_language.setCurrentIndex(index)
        self.combo_language.currentIndexChanged.connect(self._on_language_changed)
        self.size_of(self.combo_language, height=48)
        self.font(self.combo_language, 16, W500)
        self.space(language_column, 16)
        language_column.addWidget(self.combo_language)
        layout.addWidget(language)

        tracking, tracking_column = self._settings_card("branch",
                                                        tr("ui.tracking"))
        self.space(tracking_column, 14)
        switches = self._column(10)
        self.check_summoners = self._switch(tr("ui.track_summoners"))
        self.check_summoners.setChecked(bool(self.settings.get("track_summoners")))
        self.check_summoners.toggled.connect(self._on_settings_changed)
        self.check_ultimates = self._switch(tr("ui.track_ultimates"))
        self.check_ultimates.setChecked(bool(self.settings.get("track_ultimates")))
        self.check_ultimates.toggled.connect(self._on_settings_changed)
        switches.addWidget(self.check_summoners)
        switches.addWidget(self.check_ultimates)
        tracking_column.addLayout(switches)
        self.space(tracking_column, 14)
        tracking_column.addWidget(self.label(tr("ui.ultimate_note"), 15, W500,
                                             role="dim", line=24))
        self.space(tracking_column, 14)
        tracking_column.addWidget(self._rule())
        self.space(tracking_column, 14)

        tracking_advanced = Disclosure(tr("ui.advanced"), self)
        self.font(tracking_advanced.button, 16, W500)
        self.check_enemy_colour = self._switch(tr("ui.enemy_colour"))
        self.check_enemy_colour.setToolTip(tr("ui.enemy_colour_tip"))
        self.check_enemy_colour.setChecked(
            bool(self.settings.get("require_enemy_colour")))
        self.check_enemy_colour.toggled.connect(self._on_settings_changed)
        self.check_cosmic = self._switch(tr("ui.cosmic"))
        self.check_cosmic.setChecked(bool(self.settings.get("assume_cosmic_insight")))
        self.check_cosmic.toggled.connect(self._on_settings_changed)
        self.check_ionian = self._switch(tr("ui.ionian"))
        self.check_ionian.setChecked(bool(self.settings.get("assume_ionian_boots")))
        self.check_ionian.toggled.connect(self._on_settings_changed)
        for box in (self.check_enemy_colour, self.check_cosmic, self.check_ionian):
            box.setToolTip(box.toolTip() or box.text())
            tracking_advanced.addWidget(box)
        # Uppercased here rather than in the stylesheet: Qt parses
        # `text-transform` and then ignores it, so a label relying on it comes
        # out in whatever case the translation happened to be written in.
        tracking_advanced.addWidget(self.label(tr("ui.capture").upper(), 12,
                                               W700, role="eyebrow",
                                               spacing=1.2))
        self.spin_interval = Spin()
        self.spin_interval.setRange(80, 1000)
        self.spin_interval.setSingleStep(20)
        self.spin_interval.setSuffix(" ms")
        self.spin_interval.setValue(
            int(self.settings.get("capture_interval_ms", 200)))
        self.spin_interval.valueChanged.connect(self._on_settings_changed)
        self.size_of(self.spin_interval, height=48)
        self.font(self.spin_interval, 16, W500)
        tracking_advanced.addLayout(self._labelled(tr("ui.interval"),
                                                   self.spin_interval, 140, 20))
        tracking_column.addWidget(tracking_advanced)
        layout.addWidget(tracking)

        audio, audio_column = self._settings_card("bell", tr("ui.notifications"))
        self.space(audio_column, 14)
        audio_switches = self._column(10)
        self.check_audio = self._switch(tr("ui.audio"))
        self.check_audio.setChecked(bool(self.settings.get("audio_enabled")))
        self.check_audio.toggled.connect(self._on_settings_changed)
        self.check_audio_ready = self._switch(tr("ui.audio_ready"))
        self.check_audio_ready.setChecked(bool(self.settings.get("audio_on_ready")))
        self.check_audio_ready.toggled.connect(self._on_settings_changed)
        audio_switches.addWidget(self.check_audio)
        audio_switches.addWidget(self.check_audio_ready)
        audio_column.addLayout(audio_switches)
        self.space(audio_column, 16)
        self.spin_warn = Spin()
        self.spin_warn.setRange(0, 30)
        self.spin_warn.setSuffix(" s")
        self.spin_warn.setValue(int(self.settings.get("audio_warn_seconds", 5)))
        self.spin_warn.valueChanged.connect(self._on_settings_changed)
        self.size_of(self.spin_warn, height=48)
        self.font(self.spin_warn, 16, W500)
        audio_column.addLayout(self._labelled(tr("ui.audio_warn"),
                                              self.spin_warn, 110, 20))
        layout.addWidget(audio)

        startup, startup_column = self._settings_card("power", tr("ui.startup"))
        self.space(startup_column, 14)
        self.check_autostart = self._switch(tr("ui.autostart"))
        # Checked from the registry rather than from settings.json. The user can
        # remove the entry from Task Manager's Startup tab without telling us,
        # and a box reading its own stored answer would then be wrong.
        self.check_autostart.setChecked(autostart.is_enabled())
        self.check_autostart.toggled.connect(self._on_autostart_toggled)
        startup_column.addWidget(self.check_autostart)
        self.space(startup_column, 14)
        self.label_autostart = self.label(tr("ui.autostart_note"), 15, W500,
                                          role="dim", line=24, width=1000)
        startup_column.addWidget(self.label_autostart)
        layout.addWidget(startup)

        updates, updates_column = self._settings_card("refresh",
                                                      tr("ui.updates"))
        top = self._row(20)
        left = self._column(0)
        self.space(left, 14)
        self.check_updates = self._switch(tr("ui.update_check"))
        self.check_updates.setToolTip(tr("ui.update_check_tip"))
        self.check_updates.setChecked(bool(self.settings.get("update_check_enabled")))
        self.check_updates.toggled.connect(self._on_settings_changed)
        left.addWidget(self.check_updates)
        self.space(left, 16)
        version_row = self._row(10)
        version_row.addWidget(self.label(tr("ui.update_installed"), 15, W500,
                                         role="dim", wrap=False))
        version_row.addWidget(self.label(__version__, 15, W500, role="value",
                                         wrap=False, mono=True))
        version_row.addStretch(1)
        left.addLayout(version_row)
        top.addLayout(left, 1)
        self.button_check_now = self.button(tr("ui.update_check_now"), "refresh",
                                            role="accent", height=52, size=16,
                                            colour=MENU["accent_pale"])
        self.button_check_now.clicked.connect(self._on_check_now)
        top.addWidget(self.button_check_now, 0, Qt.AlignTop)
        updates_column.addLayout(top)
        self.label_update_state = self.label("", 15, W500, role="dim", line=24)
        updates_column.addWidget(self.label_update_state)
        layout.addWidget(updates)

        layout.addStretch(1)
        return page

    def _settings_card(self, glyph: str, title: str,
                       body: str = "") -> tuple[QFrame, QVBoxLayout]:
        """The Reglages shape: a 34 px accent icon, a 24 px heading, a column.

        No tile on this page. The maquette gives the filled square to Accueil and
        Affichage, where a card is a thing being offered, and a bare glyph here,
        where it is a heading in a list of settings.
        """
        card, layout = self._card("card", (22, 18, 22, 18), 0)
        row = self._row(20)
        mark = QLabel()
        self.size_of(mark, 34, 30)
        self.icon_on(mark, glyph, 28, MENU["accent"])
        mark.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        row.addWidget(mark, 0, Qt.AlignTop)
        column = self._column(0)
        column.addWidget(self.label(title, 24, W500, role="h2"))
        if body:
            self.space(column, 10)
            column.addWidget(self.label(body, 15, W500, role="hint",
                                        line=24, width=1000))
        row.addLayout(column, 1)
        row.addStretch(0)
        layout.addLayout(row)
        return card, column

    # ------------------------------------------------------------------
    # Page 4: Depannage  --  Flashwatch Depannage.dc.html
    # ------------------------------------------------------------------
    def _build_help_page(self) -> QWidget:
        page, layout = self._page(0, 0, 0, 20, 0)

        head = self._row(22)
        mark = QLabel()
        self.size_of(mark, 34, 34)
        self.icon_on(mark, "alert", 30, MENU["accent"])
        head.addWidget(mark, 0, Qt.AlignTop)
        head_column = self._column(0)
        head_column.addWidget(self.label(tr("ui.nav_help"), 26, W500, role="h2"))
        self.space(head_column, 10)
        head_column.addWidget(self.label(tr("ui.help_intro"), 15, W500,
                                         role="hint"))
        head.addLayout(head_column, 1)
        layout.addLayout(head)
        self.space(layout, 24)

        region, region_layout = self._card("card", (20, 18, 20, 18), 0)
        region_layout.addLayout(self._card_head("bell", tr("ui.chat_area")))
        self.space(region_layout, 12)
        region_layout.addWidget(self.label(tr("ui.chat_area_hint"), 15, W500,
                                           role="hint"))
        self.space(region_layout, 16)
        grid = self._row(16)
        redetect = self.button(tr("ui.redetect"), "target", role="accent",
                               height=52, size=16, weight=W500,
                               colour=MENU["accent_pale"])
        redetect.clicked.connect(self.redetect_requested.emit)
        manual = self.button(tr("ui.manual_region"), "dashed_box", height=52,
                             size=16, weight=W500)
        manual.clicked.connect(self.manual_region_requested.emit)
        grid.addWidget(redetect, 1)
        grid.addWidget(manual, 1)
        region_layout.addLayout(grid)
        self.space(region_layout, 16)
        forget = self.button(tr("ui.forget_region"), "trash", height=52,
                             size=16, weight=W500)
        forget.clicked.connect(self.region_cleared.emit)
        region_layout.addWidget(forget)
        layout.addWidget(region)
        self.space(layout, 20)

        zones, zones_layout = self._card("card", (20, 18, 20, 18), 0)
        zones_layout.addLayout(self._card_head("scanner", tr("ui.zones")))
        self.space(zones_layout, 12)
        zones_layout.addWidget(self.label(tr("ui.zones_hint"), 15, W500,
                                          role="hint"))
        self.space(zones_layout, 16)
        # One button per area the user can place by hand. Several can be open at
        # once: the clock and the scoreboard are usually framed in the same trip
        # into a game.
        zone_row = self._row(16)
        self.buttons_test: dict[str, QPushButton] = {}
        for zone, label_key, tip_key, glyph in (
                (ZONE_CHAT, "ui.test_mode", "ui.test_mode_tip", "bell"),
                (ZONE_CLOCK, "ui.test_mode_clock", "ui.test_mode_clock_tip",
                 "clock"),
                (ZONE_SCOREBOARD, "ui.test_mode_scoreboard",
                 "ui.test_mode_scoreboard_tip", "report")):
            button = self.button(tr(label_key), glyph, role="ghost", height=52,
                                 size=16, weight=W500)
            button.setCheckable(True)
            button.setToolTip(tr(tip_key))
            button.toggled.connect(
                lambda checked, z=zone: self.test_mode_toggled.emit(z, checked))
            zone_row.addWidget(button, 1)
            self.buttons_test[zone] = button
        zones_layout.addLayout(zone_row)
        # The chat one is the original single button; keep the old name working.
        self.button_test_mode = self.buttons_test[ZONE_CHAT]
        layout.addWidget(zones)
        self.space(layout, 20)

        reads, reads_layout = self._card("card", (20, 18, 20, 20), 0)
        reads_layout.addLayout(self._card_head("report", tr("ui.diagnostics")))
        self.space(reads_layout, 16)
        self.text_lines = QPlainTextEdit()
        self.text_lines.setReadOnly(True)
        self.list_misses = QListWidget()
        self.list_colour = QListWidget()
        self.list_events = QListWidget()
        panes = self._column(12)
        for key, widget, height in (("ui.debug_lines", self.text_lines, 120),
                                    ("ui.debug_misses", self.list_misses, 120),
                                    ("ui.debug_colour", self.list_colour, 120),
                                    ("ui.debug_events", self.list_events, 78)):
            pane, pane_layout = self._card("sunken", (16, 12, 16, 12), 0)
            # The maquette puts a copy button in each pane's top-right corner,
            # and it is the useful gesture here: what somebody reporting "it does
            # not read my chat" has to send is exactly what is in these boxes.
            head = self._row(12)
            head.addWidget(self.label(tr(key), 14, W500, role="hint"), 1)
            copy = QPushButton()
            copy.setProperty("role", "quiet")
            copy.setCursor(Qt.PointingHandCursor)
            self.size_of(copy, 34, 34)
            self.icon_on(copy, "copy", 20, "#9aa2c0")
            copy.setToolTip(tr("ui.copy"))
            copy.clicked.connect(lambda _c=False, w=widget: self._copy_pane(w))
            head.addWidget(copy, 0, Qt.AlignTop)
            pane_layout.addLayout(head)
            self.space(pane_layout, 10)
            self.font(widget, 14, W500)
            self.size_of(widget, height=height)
            pane_layout.addWidget(widget)
            panes.addWidget(pane)
        reads_layout.addLayout(panes)
        layout.addWidget(reads)
        self.space(layout, 18)

        footer = self._row(0)
        footer.addStretch(1)
        quit_button = self.button(tr("ui.quit"), "exit", role="primary",
                                  height=54, size=17, icon=22, colour="#ffffff")
        quit_button.clicked.connect(self.quit_requested.emit)
        footer.addWidget(quit_button)
        layout.addLayout(footer)
        layout.addStretch(1)
        return page

    @staticmethod
    def _copy_pane(widget: QWidget) -> None:
        """Put one read-out pane on the clipboard, list or text alike."""
        if isinstance(widget, QPlainTextEdit):
            text = widget.toPlainText()
        else:
            text = "\n".join(widget.item(row).text()
                             for row in range(widget.count()))
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _card_head(self, glyph: str, title: str) -> QHBoxLayout:
        """A card's own heading: a 24 px accent icon and a 20 px name."""
        row = self._row(16)
        mark = QLabel()
        self.size_of(mark, 24, 24)
        self.icon_on(mark, glyph, 24, MENU["accent"])
        row.addWidget(mark, 0, Qt.AlignVCenter)
        row.addWidget(self.label(title, 20, W600, role="h3", wrap=False), 1,
                      Qt.AlignVCenter)
        return row

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def show_update(self, version: str, current: str) -> None:
        """Offer ``version``. Called from the check, which runs off the UI thread."""
        self.label_update.setText(tr("update.banner", version=version,
                                     current=current))
        self.label_update_hint.setVisible(True)
        self.button_update.setText(tr("update.install"))
        for button in (self.button_update, self.button_update_notes,
                       self.button_update_skip):
            button.setEnabled(True)
            button.setVisible(True)
        self.update_banner.setVisible(True)

    def set_update_progress(self, percent: int) -> None:
        """Report progress on the button itself, so the banner does not resize."""
        self.button_update.setText(tr("update.downloading", percent=percent))
        for button in (self.button_update, self.button_update_skip):
            button.setEnabled(False)

    def set_update_message(self, message: str, *, offer: bool = False) -> None:
        """Replace the banner's text -- installing, installed, or failed.

        ``offer`` puts the buttons back, which is what a failure wants: the
        update did not happen, so the thing to do about it is still available.
        """
        self.label_update.setText(message)
        self.label_update_hint.setVisible(False)
        self.button_update.setText(tr("update.install"))
        self.button_update.setVisible(offer)
        self.button_update.setEnabled(offer)
        self.button_update_notes.setVisible(offer)
        self.button_update_skip.setVisible(offer)
        self.button_update_skip.setEnabled(offer)
        self.update_banner.setVisible(True)

    def hide_update(self) -> None:
        self.update_banner.setVisible(False)

    def _on_check_now(self) -> None:
        """Look for an update on demand, and say so while it happens."""
        self.button_check_now.setEnabled(False)
        self.label_update_state.setText(tr("ui.update_checking"))
        self.update_check_requested.emit()

    def set_check_result(self, message: str) -> None:
        """Report what the on-demand check found, and re-arm the button."""
        self.label_update_state.setText(message)
        self.button_check_now.setEnabled(True)

    # ------------------------------------------------------------------
    # The enemies and their roles
    # ------------------------------------------------------------------
    def sync_team(self, champion_ids: list[str], on_role_changed) -> None:
        """Add a role selector for each newly seen champion."""
        for champion_id in champion_ids:
            if champion_id in self._role_combos:
                continue
            champion = self.assets.champions.get(champion_id)
            name = champion.name if champion else champion_id
            combo = Select()
            combo.addItems(ROLES)
            combo.currentTextChanged.connect(
                lambda role, cid=champion_id: on_role_changed(cid, role))
            self.size_of(combo, 200, 42)
            self.font(combo, 15, W500)
            combo.setFont(self.font_at(15, W500))
            combo.setFixedSize(self.s(200), self.s(42))
            label = self.label(name, 16, W500, role="value", wrap=False)
            label.setFont(self.font_at(16, W500))
            row = self.team_layout.rowCount()
            self.team_layout.addWidget(label, row, 0)
            self.team_layout.addWidget(combo, row, 1)
            self._role_combos[champion_id] = combo
        self._refresh_team_visibility()

    def font_at(self, size: float, weight=W500) -> QFont:
        """A font at the window's current scale, for something built later."""
        font = QFont(menu_family())
        font.setPixelSize(max(6, round(size * self._scale)))
        font.setWeight(weight)
        return font

    def set_role_display(self, champion_id: str, role: str) -> None:
        combo = self._role_combos.get(champion_id)
        if combo is None or combo.currentText() == role:
            return
        combo.blockSignals(True)
        combo.setCurrentText(role if role in ROLES else "")
        combo.blockSignals(False)

    def clear_team(self) -> None:
        while self.team_layout.count():
            item = self.team_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._role_combos.clear()
        self._refresh_team_visibility()

    def _refresh_team_visibility(self) -> None:
        known = bool(self._role_combos)
        self.team_container.setVisible(known)
        self.label_team_empty.setVisible(not known)

    # ------------------------------------------------------------------
    # Live state
    # ------------------------------------------------------------------
    def update_debug(self, lines: list[str], near_misses: list[str],
                     colour_rejected: list[str] | None = None) -> None:
        if not self.isVisible():
            return
        text = "\n".join(lines)
        if text != self.text_lines.toPlainText():
            self.text_lines.setPlainText(text)
        for widget, values in ((self.list_misses, near_misses),
                               (self.list_colour, colour_rejected or [])):
            current = [widget.item(i).text() for i in range(widget.count())]
            if current != values:
                widget.clear()
                widget.addItems(values)

    def add_event(self, description: str) -> None:
        self.list_events.insertItem(0, description)
        while self.list_events.count() > 60:
            self.list_events.takeItem(self.list_events.count() - 1)

    def update_status(self, *, game: str, region: str, ocr: str,
                      timers: int, clock: str, state: str = "") -> None:
        self.label_game.setText(game)
        self.label_region.setText(region)
        self.label_ocr.setText(ocr)
        self.label_timers.setText(str(timers))
        self.label_clock.setText(clock)
        if state:
            self.set_state(state, timers)

    def set_state(self, state: str, timers: int = 0) -> None:
        """Say in one word, and one sentence, what is going on.

        The five readouts underneath are the detail; this is the answer. Somebody
        who opens this window mid-game wants to know whether to trust the bar,
        and "3 timers actifs" is not that answer -- "en train de lire votre
        chat" is.
        """
        role, key = PILL_STATES.get(state, PILL_STATES["waiting"])
        self.label_pill.setText(tr(key).upper())
        if self.label_pill.property("role") != role:
            self.label_pill.setProperty("role", role)
            # Qt does not re-evaluate a stylesheet when a property it selects on
            # changes; the polish has to be asked for.
            self.label_pill.style().unpolish(self.label_pill)
            self.label_pill.style().polish(self.label_pill)
            self.label_pill.update()

        headline, hint = HEADLINES.get(state, HEADLINE_IDLE)
        self.label_headline.setText(tr(headline))
        self.label_headline_hint.setText(tr(hint))

    # ------------------------------------------------------------------
    # Settings plumbing
    # ------------------------------------------------------------------
    def _on_language_changed(self, *_args) -> None:
        """Persist the new language and let the application rebuild itself.

        Handled apart from the other settings because it cannot be applied in
        place: every label in this window was created in the old language, and
        the champion and spell names have to be downloaded again.
        """
        if self._loading:
            return
        language = self.combo_language.currentData() or FRENCH
        self.settings.set("locale", locale_for(language))
        self.language_changed.emit(language)

    def _on_autostart_toggled(self, checked: bool) -> None:
        """Write the Run entry, then show what the registry actually did.

        Not routed through _on_settings_changed: this one lives in the registry,
        not in settings.json, and it can fail -- a machine under policy can
        refuse the write. Rather than leaving a box ticked over a change that
        never happened, the state is read back and the box corrected.
        """
        if autostart.set_enabled(checked):
            self.label_autostart.setText(tr("ui.autostart_note"))
            return

        log.warning("autostart could not be set to %s", checked)
        self.label_autostart.setText(tr("ui.autostart_failed"))
        actual = autostart.is_enabled()
        if actual != checked:
            blocked = self.check_autostart.blockSignals(True)
            self.check_autostart.setChecked(actual)
            self.check_autostart.blockSignals(blocked)

    def _on_settings_changed(self, *_args) -> None:
        if self._loading:
            return
        self.settings.update({
            "overlay_layout": self._layout_key,
            "hide_until_in_game": self.check_hide_until_game.isChecked(),
            "bar_show_when_idle": self.check_idle_bar.isChecked(),
            "bar_vertical": self.check_bar_vertical.isChecked(),
            "theme": self.combo_theme.currentData(),
            "overlay_opacity": self.slider_opacity.value() / 100.0,
            "overlay_scale": self.spin_scale.value(),
            "sort_by_role": self.check_sort_role.isChecked(),
            "hide_ready_entries": self.check_hide_ready.isChecked(),
            "ready_linger_seconds": self.spin_ready_linger.value(),
            "track_summoners": self.check_summoners.isChecked(),
            "track_ultimates": self.check_ultimates.isChecked(),
            "require_enemy_colour": self.check_enemy_colour.isChecked(),
            "assume_cosmic_insight": self.check_cosmic.isChecked(),
            "assume_ionian_boots": self.check_ionian.isChecked(),
            "audio_enabled": self.check_audio.isChecked(),
            "audio_on_ready": self.check_audio_ready.isChecked(),
            "audio_warn_seconds": self.spin_warn.value(),
            "capture_interval_ms": self.spin_interval.value(),
            "update_check_enabled": self.check_updates.isChecked(),
        })
        self.settings_changed.emit()

    def sync_test_mode(self, zone: str, active: bool) -> None:
        """Keep a button in step when its frame is closed from the frame itself."""
        button = self.buttons_test.get(zone)
        if button is None:
            return
        button.blockSignals(True)
        button.setChecked(active)
        button.blockSignals(False)

    def sync_overlay_toggles(self, *, visible: bool, locked: bool) -> None:
        for widget, value in ((self.check_visible, visible),
                              (self.check_locked, locked),
                              (self.button_move, not locked)):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        # The button's label and the hint under it are not part of its checked
        # state, so they are set explicitly rather than left to the blocked
        # toggle handler.
        self.button_move.setText(tr("ui.move_start") if locked
                                 else tr("ui.move_done"))
        self.label_move_state.setVisible(not locked)

    def go_to_display_page(self) -> None:
        """Show the Affichage page. Used when the guide hands over to it."""
        if len(self.nav_buttons) > 1:
            self.nav_buttons[1].setChecked(True)
            self.stack.setCurrentIndex(1)

    def refresh_layout_choice(self) -> None:
        """Re-read the chosen display, after something else changed it."""
        self._layout_key = self._current_layout()
        self._sync_layout_tiles()

    def closeEvent(self, event) -> None:
        """Closing this window hides it; the program keeps running.

        It used to quit outright, on the reasoning that this window carries the
        taskbar entry and its close button is what someone reaches for to stop
        the program. That gets the cost backwards. Flashwatch is meant to be
        started before a game and forgotten, so the close button is far more
        often "I am done reading this" than "I am done playing" -- and the two
        mistakes are not equal: hiding a window you meant to close costs one
        click in the tray, while quitting a session you meant to keep going
        loses every timer in the running game.

        Safe to reverse because quitting is not hidden: the tray menu and the
        button in the rail both say "Quitter le programme" in as many words.
        """
        event.ignore()
        self.hide()
        self.hidden_to_tray.emit()


def _escape(text: str) -> str:
    """Enough escaping for a label set as rich text to carry a line height."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br>"))
