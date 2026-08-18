"""Transparent, click-through overlay showing enemy cooldowns.

Two Windows details matter for this to behave over a game:

*Click-through* needs more than Qt's ``WA_TransparentForMouseEvents``. The window
also gets ``WS_EX_TRANSPARENT`` so hit-testing passes through at the OS level,
and ``WS_EX_NOACTIVATE`` so clicking near it can never steal focus from the game
-- losing focus mid-fight would be worse than having no overlay at all.

*Staying on top* is not a one-time setting. Games re-assert their own topmost
status, so the overlay periodically re-applies its z-order.

Drawn in a single ``paintEvent`` rather than with child widgets: the content is a
handful of rows redrawn a few times a second, and doing it manually keeps full
control of the translucent look and costs less than a widget tree.
"""

from __future__ import annotations

import logging
from math import exp
from pathlib import Path
from time import monotonic
from typing import NamedTuple

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from i18n import tr
from timer_manager import ActiveTimer

log = logging.getLogger(__name__)

try:
    import win32con
    import win32gui
    HAVE_WIN32 = True
except ImportError:                                   # pragma: no cover
    HAVE_WIN32 = False

TOPMOST_REFRESH_MS = 2000
RESIZE_GRIP = 14
# Small enough for a vertical track, which is legitimately narrow: a portrait, a
# spell badge and a countdown beside them come to about 100 px at scale 1. The
# floor is there to stop the window being resized into something that cannot be
# grabbed again, not to impose a shape.
MIN_WIDTH, MIN_HEIGHT = 110, 46

# The three displays. Same data, three readings of it -- and no way to know from
# here which one suits a given player's screen and role, so all three ship and
# the choice is a setting.
LAYOUT_BAR = "bar"
LAYOUT_CARDS = "cards"
LAYOUT_LIST = "list"
LAYOUTS = (LAYOUT_BAR, LAYOUT_CARDS, LAYOUT_LIST)

# The track stood on its end. Not a fourth display -- it is the same display,
# reading the same way -- so it is a setting on the bar rather than a fourth tile
# to choose between. It *is* its own rectangle, though: see
# :meth:`Overlay.geometry_key`.
LAYOUT_BAR_V = "bar_vertical"

# Where each display puts itself the first time it is chosen, as a fraction of
# the screen's usable width plus a height in pixels. They differ because the
# shapes do: a track and a row of cards belong along the top edge where they
# cross nothing, while a tall column of rows belongs down a side.
#
# ``align`` is "top" (centred on the top edge) or "left" (down the left side,
# clear of the minimap and the item shop).
LAYOUT_DEFAULTS = {
    LAYOUT_BAR: {"fraction": 0.30, "height": 58, "align": "top"},
    LAYOUT_CARDS: {"fraction": 0.26, "height": 80, "align": "top"},
    LAYOUT_LIST: {"fraction": 0.13, "height": 300, "align": "left"},
    # Narrow and tall, down the left side: a vertical track is the same strip
    # turned on its end, and the countdowns sit to the right of the portraits.
    LAYOUT_BAR_V: {"fraction": 0.075, "height": 420, "align": "left"},
}
LAYOUT_DEFAULT_MARGIN = 6

# Default geometry for the bar layout: a wide, shallow strip at the top centre.
BAR_DEFAULT_WIDTH_FRACTION = LAYOUT_DEFAULTS[LAYOUT_BAR]["fraction"]
BAR_DEFAULT_HEIGHT = LAYOUT_DEFAULTS[LAYOUT_BAR]["height"]
BAR_DEFAULT_TOP = LAYOUT_DEFAULT_MARGIN

# Fallbacks, for a theme dict that predates the per-theme opacities -- a settings
# file written by a newer version, or a hand-edited one. The real values live in
# THEMES below, because a light panel and a dark panel cannot share them.
BAR_PANEL_ALPHA = 0.42
BAR_IDLE_ALPHA = 0.18

# Fraction of the spell badge that overlaps the champion portrait. Small, so the
# portrait stays recognisable -- it is the thing you identify at a glance.
BADGE_OVERLAP = 0.26

# Cards layout: the portrait is bigger than on the track because it carries the
# progress ring around it, and that ring is the readout.
CARD_PORTRAIT = 30
CARD_BADGE = 18
CARD_RING = 2.4
CARD_GAP = 5
CARD_PAD = 6

# The countdown ladder: one colour per state, and only four states in the whole
# program. Green while the spell is far off, amber once it is halfway back, red
# when it is about to land, green again once it is up. Nothing else in the
# overlay is allowed a colour of its own -- the interface colours (the unlocked
# outline, the rail, the portraits' fallback) are neutral or "edit" blue, so any
# colour the eye catches over a fight means exactly one thing.
#
# Two greens for two states is deliberate and not a mistake to be tidied away:
# the player asked for both ends of the ladder to be green, and the two are never
# confused because "ready" says READY in words and closes its ring completely.
#
# The three themes. Each one carries its own opacities, its own rail, its own
# badge disc and its own text shadow, and that is not tidiness: those four things
# cannot be shared between a light and a dark panel.
#
# The arithmetic that forced it, measured rather than guessed. A light panel at the
# dark theme's 0.42 opacity, laid over a very dark game, composites to #6e7175 --
# mid grey -- and dark text on mid grey scores 3.56:1, which is unreadable at a
# glance. The same panel at 0.80 composites to about #c8cacf whatever is behind it,
# where the same text scores over 10:1. So a light overlay is necessarily more
# opaque than a dark one: it hides a little more of the game and, in exchange, it is
# the only one of the three that stays legible from a cave to a victory screen.
#
# The shadow flips with it. A black shadow under dark text on a light panel just
# muddies it; what dark text needs is a *light* halo.
THEMES: dict[str, dict] = {
    "light": {
        "panel": (250, 251, 253, 255),
        "panel_alpha": 0.80,     # in play -- see the note above
        "idle_alpha": 0.30,      # at rest, with nothing on cooldown
        "border": (36, 48, 72, 110),
        "rail": (108, 120, 140, 200),
        "title": (20, 26, 36, 255),
        "role": (96, 106, 124, 255),
        "name": (20, 26, 36, 255),
        "spell": (74, 85, 102, 255),
        # The ladder. On a light panel every one of these has to be a *dark*
        # version of its colour: a screen-green or a screen-yellow on near-white
        # scores under 2:1 and is simply not there.
        #
        # Ratios below are against the panel as it actually composites over a
        # dark game (about #c8cacf), not against the panel colour on its own --
        # measured, because the numbers this file used to carry were the
        # flattering ones and the real figures were all near 4.0, i.e. under the
        # bar they claimed to clear. Every one of these is over 4.5.
        "far": (13, 97, 55, 255),       # 4.6:1  (7.3 on the panel alone)
        "mid": (117, 74, 0, 255),       # 4.7:1
        "near": (160, 33, 32, 255),     # 4.7:1
        "ready": (4, 99, 50, 255),      # 4.5:1
        "edit": (5, 84, 128, 255),      # 5.0:1 -- interface, never a state
        "row": (18, 28, 48, 20),
        "badge": (255, 255, 255, 250),
        "shadow": (255, 255, 255, 200),
    },
    "dark": {
        "panel": (14, 16, 22, 205),
        "panel_alpha": 0.42,
        "idle_alpha": 0.18,
        "border": (70, 80, 100, 190),
        "rail": (140, 152, 175, 150),
        "title": (225, 232, 245, 255),
        "role": (140, 152, 175, 255),
        "name": (232, 238, 248, 255),
        "spell": (168, 180, 200, 255),
        "far": (94, 214, 138, 255),
        "mid": (255, 199, 88, 255),
        "near": (255, 96, 92, 255),
        "ready": (126, 245, 166, 255),
        "edit": (90, 200, 255, 255),
        "row": (255, 255, 255, 12),
        "badge": (14, 16, 22, 238),
        "shadow": (0, 0, 0, 190),
    },
    "neon": {
        "panel": (8, 10, 24, 210),
        "panel_alpha": 0.50,
        "idle_alpha": 0.20,
        "border": (0, 214, 226, 170),
        "rail": (0, 214, 226, 150),
        "title": (0, 240, 255, 255),
        "role": (128, 148, 200, 255),
        "name": (226, 240, 255, 255),
        "spell": (0, 196, 214, 255),
        "far": (43, 240, 160, 255),
        "mid": (255, 214, 64, 255),
        "near": (255, 74, 74, 255),
        "ready": (110, 255, 195, 255),
        "edit": (0, 224, 255, 255),
        "row": (0, 220, 255, 16),
        "badge": (8, 10, 24, 240),
        "shadow": (0, 0, 0, 200),
    },
}

# Where the ladder changes colour. Both a time left *and* a share of the cooldown,
# whichever fires first, because neither alone is right for every spell: 45
# seconds is most of a Smite and a sixth of a Teleport, so a pure fraction calls a
# Smite urgent while a minute is still left, and a pure clock calls a Teleport
# urgent when it is barely halfway.
NEAR_SECONDS = 20.0
MID_SECONDS = 60.0
NEAR_PROGRESS = 0.85
MID_PROGRESS = 0.60

# The "?" chip, which marks a cooldown whose *spell* was only guessed at.
#
# It lives next to the countdown, sized against the countdown's own letters so it
# reads as its equal rather than as a speck. Room for it is reserved whether or
# not anything is uncertain, so an entry that becomes uncertain does not shove
# the display sideways.
#
# It sits *beside* the number and never over it: "?4:23" reads as part of the
# time, and the time is the one thing that has to be legible at a glance.
CHIP_MIN = 10                 # px at scale 1, whatever the font does
CHIP_TEXT_RATIO = 0.95        # diameter, as a share of the countdown's ascent
CHIP_GAP = 3                  # px at scale 1, between the chip and the number


# The countdown's face, in order of preference, with the size multiplier that
# makes each one come out at the same optical size as the others.
#
# Two properties are non-negotiable and everything else is taste. The digits must
# be **tabular** -- all the same width -- or a countdown twitches on every tick as
# 1s and 4s trade places, which is unbearable in the corner of the eye. And the
# face has to hold up small, bold and coloured over an unpredictable background.
#
# Bahnschrift is Windows' DIN: signage, drawn to be read at a glance and from an
# angle, with open counters and unmistakable digits. It is narrow, so the same
# slot fits a bigger number. Its figures are proportional by default, hence the
# "tnum" feature below -- without it a Bahnschrift countdown is exactly the
# twitch this comment opens with.
#
# Consolas, the coding mono this used to use, is last on purpose: it is tabular
# by construction and always present, which makes it the right floor and the
# wrong ceiling.
COUNTDOWN_FACES = (
    ("Bahnschrift", 1.28, QFont.Bold),        # Windows 10 1709 and later
    ("Segoe UI Variable", 1.15, QFont.Black),
    ("Segoe UI", 1.15, QFont.Black),          # tabular already, no feature needed
    ("Cascadia Mono", 1.0, QFont.Bold),
    ("Consolas", 1.0, QFont.Bold),
)

# Faces the user may pick instead, beyond the automatic chain above. Same two
# rules -- steady digits, legible small and bold -- so the list is short and every
# entry is a face Windows actually ships. Each carries the multiplier that brings
# it to the same optical size as the others, which is what lets the size setting
# mean one thing across all of them.
#
# The interface's own face is deliberately in here and deliberately not first: it
# is the most *coherent* choice and not the most legible one, since it is a text
# face rather than a signage face.
EXTRA_COUNTDOWN_FACES = (
    ("Tahoma", 1.15, QFont.Bold),
    ("Verdana", 1.10, QFont.Bold),
    ("Trebuchet MS", 1.18, QFont.Bold),
    ("Franklin Gothic Medium", 1.20, QFont.Bold),
    ("Calibri", 1.25, QFont.Bold),
    ("Arial", 1.15, QFont.Bold),
    ("Lucida Console", 1.02, QFont.Bold),
    ("Courier New", 1.10, QFont.Bold),
)

# The value meaning "whichever of COUNTDOWN_FACES this machine has".
FACE_AUTO = "auto"

_COUNTDOWN_FACE: tuple[str, float, int] | None = None
# What the settings currently ask for. Held on the module rather than passed
# down, because `countdown_font` is called from a dozen places inside the paint
# and layout code, and threading a preference through all of them would be a
# change to every one of those call sites for a value that never varies within a
# frame. Set by the overlay when the settings change; see `set_countdown_style`.
_CHOSEN_FACE = FACE_AUTO
_CHOSEN_SCALE = 1.0


def available_countdown_faces() -> list[tuple[str, float, int]]:
    """Every face on this machine that the countdown may be drawn in.

    Filtered against the font database rather than offered blind: a list that
    lets somebody pick a font they do not have is a list that silently draws
    something else.
    """
    from PySide6.QtGui import QFontDatabase
    available = set(QFontDatabase.families())
    return [face for face in COUNTDOWN_FACES + EXTRA_COUNTDOWN_FACES
            if face[0] in available]


def set_countdown_style(family: str, scale: float) -> None:
    """Choose the countdown's face and size. ``family`` may be ``FACE_AUTO``."""
    global _CHOSEN_FACE, _CHOSEN_SCALE
    _CHOSEN_FACE = str(family or FACE_AUTO)
    try:
        _CHOSEN_SCALE = max(0.3, min(3.0, float(scale)))
    except (TypeError, ValueError):
        _CHOSEN_SCALE = 1.0


def countdown_face() -> tuple[str, float, int]:
    """The face to draw countdowns in: the chosen one, or the best available.

    The automatic answer is resolved once and cached. Deferred rather than
    computed at import: the font database is empty until a QApplication exists,
    and a chooser that runs too early always picks the last entry.
    """
    global _COUNTDOWN_FACE
    if _CHOSEN_FACE != FACE_AUTO:
        for face in COUNTDOWN_FACES + EXTRA_COUNTDOWN_FACES:
            if face[0] == _CHOSEN_FACE:
                return face
        # A face named in the settings that this machine does not have. Falling
        # through to the automatic chain draws something legible instead of
        # something arbitrary.
    if _COUNTDOWN_FACE is None:
        from PySide6.QtGui import QFontDatabase
        available = set(QFontDatabase.families())
        _COUNTDOWN_FACE = next(
            (face for face in COUNTDOWN_FACES if face[0] in available),
            COUNTDOWN_FACES[-1])
        log.debug("countdown face: %s", _COUNTDOWN_FACE[0])
    return _COUNTDOWN_FACE


def countdown_font(points: float) -> QFont:
    """The countdown's font at a size given in Consolas-equivalent points.

    Callers keep asking for the size they always asked for; the multiplier in
    :data:`COUNTDOWN_FACES` is what makes a face that draws small at 9 points
    come out the same height as one that draws large, and the user's own size
    setting is applied here for the same reason -- every layout in this file
    measures its rows through this function, so a countdown that shrinks takes
    the space reserved for it with it instead of leaving a hole.
    """
    family, factor, weight = countdown_face()
    font = QFont(family)
    # The floor is a floor on legibility, not on validity: below about four
    # points a countdown is a smudge whatever the face. Low enough that the size
    # setting keeps doing something across its whole range at ordinary overlay
    # scales, rather than silently bottoming out halfway along the slider.
    font.setPointSizeF(max(4.0, points * factor * _CHOSEN_SCALE))
    font.setWeight(weight)
    # Tabular figures, on the faces that need asking. Qt 6.7 and later; on
    # anything older the fallback chain is what keeps the digits steady.
    if hasattr(font, "setFeature"):
        try:
            font.setFeature(QFont.Tag("tnum"), 1)
        except Exception:                             # noqa: BLE001
            pass
    return font


def chip_extra(metrics: QFontMetrics, scale: float) -> int:
    """Width a "?" chip adds to a countdown: the disc, its gap, and a pixel.

    One source for it, because two places need the number and they need the same
    one: the layout, which reserves the room, and the painter, which fills it.
    """
    return (max(int(CHIP_MIN * scale), int(metrics.ascent() * CHIP_TEXT_RATIO))
            + max(2, int(CHIP_GAP * scale)) + 1)


def countdown_layout(rect, text: str, metrics: QFontMetrics, align,
                     uncertain: bool,
                     scale: float) -> tuple[QRectF | None, QRectF]:
    """Split a countdown's box into the "?" chip and the number itself.

    Pure geometry, and kept apart from the painting for the same reason the bar's
    marker placement is: "the chip is beside the number, never on it" is the
    property that decides whether the time can be read at all, and it can be
    checked without a screen.

    The box returned for the number is exactly as wide as the number, so drawing
    it with the caller's own alignment lands it where this function put it.

    Float boxes throughout -- an integer rectangle passed in is widened to one --
    because on the track this whole group slides, and it slides slowly enough
    that whole pixels would read as a stutter rather than as movement.
    """
    box = QRectF(rect)
    if not uncertain:
        return None, box
    size = float(max(int(CHIP_MIN * scale),
                     int(metrics.ascent() * CHIP_TEXT_RATIO)))
    gap = float(max(2, int(CHIP_GAP * scale)))
    width = float(metrics.horizontalAdvance(text))
    group = size + gap + 1.0 + width
    if align & Qt.AlignRight:
        left = box.right() - group
    elif align & Qt.AlignHCenter:
        left = box.x() + (box.width() - group) / 2.0
    else:
        left = box.x()
    left = max(box.x(), left)
    chip = QRectF(left, box.y() + (box.height() - size) / 2.0, size, size)
    return chip, QRectF(chip.right() + gap + 1.0, box.y(), width, box.height())


# How fast a marker catches up with where the layout puts it. One time constant,
# in seconds: after TAU it has covered 63 % of the distance, after three TAU it is
# there. A fifth of a second reads as movement rather than as a jump, and is short
# enough that the position never lies about the cooldown by anything that matters.
GLIDE_TAU = 0.20

# The overlay's own repaint rate while a marker is travelling, and how close it
# has to get before it is called still.
#
# Extra frames are only worth their CPU during the *eased* movements -- a
# crossing, a re-spread, a spell appearing -- which last about a fifth of a
# second. The rest of the time a marker drifts at under two pixels a second, and
# what makes that smooth is drawing it at fractional coordinates, not asking for
# it more often: the application's ten repaints a second already advance it by
# two tenths of a pixel each, which no eye resolves as a step. So the timer runs
# when something is actually moving and stops when nothing is.
GLIDE_FRAME_MS = 33
GLIDE_SETTLED = 0.4


class BarMarker(NamedTuple):
    """One cooldown placed on the bar's track.

    ``left``/``span`` delimit the slot along the track's axis -- an x and a width
    when the track is horizontal, a y and a height when it is vertical. ``rect``
    is the portrait plus its spell badge, i.e. the box that must never meet
    another marker's, and ``text`` is where the countdown goes: under the
    portrait on a horizontal track, beside it on a vertical one.
    """

    timer: ActiveTimer
    left: float
    span: int
    icon_x: float
    icon_y: float
    overlap: int
    rect: QRectF
    text: QRectF


class CardSlot(NamedTuple):
    """One cooldown's card in the fixed-cards display.

    ``rect`` is the whole card, which is the box that must never meet another
    card's; the three inner rectangles are where its parts are drawn.
    """

    timer: ActiveTimer
    rect: QRect
    portrait: QRect
    badge: QRect
    text: QRect


def _colour(theme: dict, key: str) -> QColor:
    return QColor(*theme.get(key, (255, 255, 255, 255)))


class IconCache:
    """Loads, scales and rounds champion/spell icons once.

    Every icon in the overlay is drawn inside a circle, and the obvious way to do
    that -- set a clip path, blit, restore -- is paid on every icon of every
    frame. With the track repainting thirty times a second that was the single
    most expensive thing the program did. Cutting the circle once, at the size it
    will be drawn, turns each icon back into a plain blit.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, bool], QPixmap] = {}

    def get(self, path: Path | None, size: int, *,
            round_: bool = False) -> QPixmap | None:
        if path is None or size <= 0:
            return None
        key = (str(path), size, round_)
        hit = self._cache.get(key)
        if hit is not None:
            return hit if not hit.isNull() else None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._cache[key] = pixmap
            return None
        scaled = pixmap.scaled(size, size, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        if round_:
            scaled = self._rounded(scaled, size)
        self._cache[key] = scaled
        return scaled

    @staticmethod
    def _rounded(pixmap: QPixmap, size: int) -> QPixmap:
        out = QPixmap(size, size)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addEllipse(QRectF(0, 0, size, size))
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return out

    def clear(self) -> None:
        self._cache.clear()


class Overlay(QWidget):
    """The always-on-top cooldown display."""

    geometry_changed = Signal()

    def __init__(self, settings, assets) -> None:
        super().__init__(None)
        self.settings = settings
        self.assets = assets
        self.icons = IconCache()
        self._timers: list[ActiveTimer] = []
        self._status = ""
        self._game_active = False
        # True while the trial mode is running, which overrides every hide rule.
        self._demo = False
        self._drag_origin: QPoint | None = None
        self._resize_origin: tuple[QPoint, QSize] | None = None
        # Where each marker currently *is*, as opposed to where the layout says
        # it belongs; see :meth:`_glide`.
        self._glide_from: dict[tuple[str, str], float] = {}
        self._glide_at = monotonic()
        # Whether anything is still travelling, decided by the last layout pass
        # and read by the frame timer.
        self._gliding = False
        # Frames for the track's glide, and only for it: it runs while markers
        # are actually moving on screen and is stopped the rest of the time.
        # Nothing else in the overlay moves between one countdown and the next,
        # so nothing else is worth a repaint the application did not ask for.
        # Built here, before anything that can ask for it: applying the lock
        # settles visibility, and visibility is one of the things it follows.
        self._glide_timer = QTimer(self)
        self._glide_timer.setInterval(GLIDE_FRAME_MS)
        self._glide_timer.timeout.connect(self.update)
        # The display currently on screen, so a change of setting can be told
        # apart from a repaint and the outgoing one's position filed away.
        self._layout = self.geometry_key()

        self.setWindowTitle("Flashwatch")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                    # keeps it out of the taskbar/alt-tab
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # Before the first paint, and before restore_geometry, which measures a
        # row to decide how tall a window has to be.
        self.sync_countdown_style()
        self.restore_geometry()
        self.apply_lock(bool(self.settings.get("overlay_locked", True)))
        # Full window opacity, always: the setting is applied to the panel while
        # painting, so the champions and the countdowns stay at full strength
        # however faint the box behind them is asked to be.
        self.setWindowOpacity(1.0)

        # Games reclaim topmost; re-assert ours on a slow timer.
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(TOPMOST_REFRESH_MS)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        self._topmost_timer.start()

        self._sync_glide_timer()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    # Each display remembers its own rectangle. Sharing one, as this used to,
    # meant that trying the vertical rows and going back left the track 260px
    # wide and 420 tall on the left edge -- the user's placement of one display
    # destroyed by looking at another.
    def current_layout(self) -> str:
        """The chosen display, normalised. Unknown values fall back to the bar."""
        value = str(self.settings.get("overlay_layout", LAYOUT_BAR))
        return value if value in LAYOUTS else LAYOUT_BAR

    def geometry_key(self) -> str:
        """Which rectangle the window is currently using.

        Usually the display, but a vertical track is a different *shape* from a
        horizontal one -- narrow and tall against wide and shallow -- so it gets
        its own slot. Turning the setting on and off would otherwise leave a
        strip 600 px wide and 58 tall standing on its end.
        """
        layout = self.current_layout()
        if layout == LAYOUT_BAR and self.bar_is_vertical():
            return LAYOUT_BAR_V
        return layout

    def _geometry_store(self) -> dict:
        stored = self.settings.get("layout_geometry")
        return dict(stored) if isinstance(stored, dict) else {}

    @staticmethod
    def _valid_rect(value) -> tuple[int, int, int, int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            x, y, width, height = (int(v) for v in value)
        except (TypeError, ValueError):
            return None
        return (x, y, max(MIN_WIDTH, width), max(MIN_HEIGHT, height))

    def restore_geometry(self) -> None:
        """Place the window where this display was last left, or by default."""
        self._migrate_geometry()
        rect = self._valid_rect(self._geometry_store().get(self.geometry_key()))
        if rect is None:
            self.place_default(save=True)
            return
        self.setGeometry(*rect)
        self._ensure_on_screen()

    def _migrate_geometry(self) -> None:
        """Adopt a position saved before geometry was kept per display.

        Runs once: as soon as anything is in the store this does nothing. The
        bar is the one exception -- an older version wrote overlay_x/y for the
        vertical panel and flagged the bar separately, so a bar that was never
        placed keeps its default rather than inheriting the panel's rectangle.
        """
        if self._geometry_store():
            return
        layout = self.geometry_key()
        if layout in (LAYOUT_BAR, LAYOUT_BAR_V) and not self.settings.get("bar_placed"):
            return
        rect = self._valid_rect([self.settings.get("overlay_x", 40),
                                 self.settings.get("overlay_y", 120),
                                 self.settings.get("overlay_width", 260),
                                 self.settings.get("overlay_height", 420)])
        if rect is not None:
            self.settings.set("layout_geometry", {layout: list(rect)})

    def place_default(self, *, save: bool = True, layout: str | None = None) -> None:
        """Put this display where it belongs on a screen it has never seen."""
        from PySide6.QtWidgets import QApplication

        layout = layout or self.geometry_key()
        spec = LAYOUT_DEFAULTS.get(layout, LAYOUT_DEFAULTS[LAYOUT_BAR])
        screen = self.screen() or QApplication.primaryScreen()
        available = (screen.availableGeometry() if screen is not None
                     else self.geometry())

        width = max(MIN_WIDTH, int(available.width() * spec["fraction"]))
        height = max(MIN_HEIGHT, int(spec["height"]))
        if spec["align"] == "left":
            x = available.left() + int(available.width() * 0.012)
            y = available.top() + int(available.height() * 0.16)
        else:
            x = available.left() + (available.width() - width) // 2
            y = available.top() + LAYOUT_DEFAULT_MARGIN
        self.setGeometry(x, y, width, height)
        if save:
            self.save_geometry()

    # Kept under its old name: the tray entry, the settings button and the tests
    # all ask for "recentre at the top", which is what placing a top-aligned
    # display by default does.
    def centre_at_top(self, *, save: bool = True) -> None:
        self.place_default(save=save)

    def sync_countdown_style(self) -> None:
        """Push the chosen countdown face and size into the drawing code.

        A method on the overlay rather than something the settings window does
        directly: the module-level preference is an implementation detail of how
        the paint code reads it, and this is the object that owns the painting.
        """
        set_countdown_style(str(self.settings.get("timer_font", FACE_AUTO)),
                            self.settings.get("timer_font_scale", 1.0))

    def sync_layout(self) -> None:
        """Follow a change of display, carrying each one's position with it.

        Called after the setting changes. The rectangle in use belongs to the
        display that was showing, so it is filed under that one before the new
        display's own is restored.
        """
        wanted = self.geometry_key()
        if wanted == self._layout:
            return
        self.save_geometry(layout=self._layout)
        self._layout = wanted
        self.restore_geometry()
        self._sync_glide_timer()
        self.update()

    def _ensure_on_screen(self) -> None:
        """Pull the window back if a saved position is now off-screen.

        Monitor layouts change; a position saved on a monitor that is no longer
        attached would leave the overlay invisible with no way to find it.
        """
        screen = self.screen() or (self.windowHandle().screen()
                                   if self.windowHandle() else None)
        if screen is None:
            return
        available = screen.availableGeometry()
        rect = self.geometry()
        if available.intersects(rect):
            return
        rect.moveTo(available.left() + 40, available.top() + 80)
        self.setGeometry(rect)

    def save_geometry(self, *, layout: str | None = None) -> None:
        """Record the current rectangle, both per display and in the flat keys.

        The flat overlay_x/y/width/height are kept up to date because they are
        what an older build reads: someone who tries a newer version and goes
        back should find their overlay where they left it.
        """
        rect = self.geometry()
        store = self._geometry_store()
        store[layout or self.geometry_key()] = [rect.x(), rect.y(),
                                          rect.width(), rect.height()]
        self.settings.update({
            "layout_geometry": store,
            "overlay_x": rect.x(),
            "overlay_y": rect.y(),
            "overlay_width": rect.width(),
            "overlay_height": rect.height(),
        })

    # ------------------------------------------------------------------
    # Click-through
    # ------------------------------------------------------------------
    def apply_lock(self, locked: bool) -> None:
        """Locked means click-through; unlocked lets the user move/resize it."""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, locked)
        self._apply_native_flags(locked)
        self.setCursor(Qt.ArrowCursor if locked else Qt.OpenHandCursor)
        # Unlocking is how the bar gets moved, so it has to be on screen for it
        # even when the auto-hide would otherwise keep it away.
        self.refresh_visibility()
        self.update()

    def _apply_native_flags(self, locked: bool) -> None:
        if not HAVE_WIN32 or not self.winId():
            return
        try:
            hwnd = int(self.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            # NOACTIVATE always: the overlay must never take focus from the game.
            style |= win32con.WS_EX_LAYERED | win32con.WS_EX_NOACTIVATE
            if locked:
                style |= win32con.WS_EX_TRANSPARENT
            else:
                style &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        except Exception as exc:                      # noqa: BLE001
            log.debug("could not apply native window flags (%s)", exc)

    def _reassert_topmost(self) -> None:
        if not self.isVisible() or not HAVE_WIN32:
            return
        try:
            hwnd = int(self.winId())
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                | win32con.SWP_NOACTIVATE,
            )
        except Exception as exc:                      # noqa: BLE001
            log.debug("could not re-assert topmost (%s)", exc)

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------
    def set_game_active(self, active: bool) -> None:
        """Tell the overlay whether the in-game window is currently on screen."""
        if active == self._game_active:
            return
        self._game_active = active
        self.refresh_visibility()

    def set_demo(self, active: bool) -> None:
        """Trial mode: show the display whatever the hide rules say.

        It overrides *both* switches, including "Afficher l'overlay". Somebody who
        pressed "Essayer sans partie" asked to see the thing; a trial that obeys a
        checkbox they set weeks ago and shows nothing is a bug report waiting to
        happen. The switches are untouched, so the normal rule comes straight back
        when the trial ends.
        """
        if active == self._demo:
            return
        self._demo = active
        self.refresh_visibility()
        self.update()

    def should_be_visible(self) -> bool:
        """The show/hide rule, in one place.

        Outside a game the bar has nothing to display and would sit over the
        client or the desktop, so it stays away. Three exceptions keep it usable:
        the trial mode, which exists precisely to be looked at without a game;
        being unlocked, since it must be on screen to be dragged; and any timer
        still running, e.g. in the moments right after a game ends.
        """
        if self._demo:
            return True
        if not self.settings.get("overlay_visible"):
            return False
        if not self.settings.get("hide_until_in_game", True):
            return True
        return (self._game_active
                or not self.settings.get("overlay_locked", True)
                or bool(self._timers))

    def refresh_visibility(self) -> None:
        """Apply the rule. Cheap and idempotent, so call it after any change."""
        wanted = self.should_be_visible()
        if wanted == self.isVisible():
            return
        self.setVisible(wanted)
        if wanted:
            # Coming back from hidden, the click-through style and the z-order
            # both have to be re-asserted rather than waited for: the bar must
            # be on top of the game and transparent to clicks immediately.
            self._apply_native_flags(bool(self.settings.get("overlay_locked", True)))
            self._reassert_topmost()
        self._sync_glide_timer()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_timers(self, timers: list[ActiveTimer]) -> None:
        # Skip the repaint when there is nothing to animate. Countdowns need a
        # redraw every tick, but an empty overlay does not, and this runs 10x a
        # second for as long as the app is open.
        if not timers and not self._timers:
            return
        had_timers = bool(self._timers)
        self._timers = timers
        if bool(timers) != had_timers:
            # Gaining or losing every timer can flip the auto-hide, e.g. the
            # preview shown with League closed.
            self.refresh_visibility()
            self._sync_glide_timer()
        self.update()

    def set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.update()

    def resizeEvent(self, event) -> None:
        """A resize re-lays the track out; it does not move the cooldowns.

        Without this the markers would ease from where they sat in the old
        rectangle to where they belong in the new one -- a slide that means
        nothing, and that can put a marker briefly outside a window that has just
        been made smaller. Dropping the eased positions makes the next frame draw
        the new layout exactly.
        """
        super().resizeEvent(event)
        self.snap_motion()

    def snap_motion(self) -> None:
        """Forget where the markers were, so the next frame is the layout itself.

        Used whenever a move would be meaningless (a resize, a change of
        display), and by the tests, which are about where the track *settles*
        rather than about the fifth of a second it takes to get there.
        """
        self._glide_from.clear()

    def _sync_glide_timer(self) -> None:
        """Run the animation frames only when something is actually sliding."""
        wanted = (self._gliding and self.current_layout() == LAYOUT_BAR
                  and bool(self._timers) and self.isVisible())
        if wanted == self._glide_timer.isActive():
            return
        if wanted:
            # From now, not from whenever the track was last on screen: an
            # elapsed time measured across a hidden window would land every
            # marker on its target in a single frame.
            self._glide_at = monotonic()
            self._glide_timer.start()
        else:
            self._glide_timer.stop()

    # ------------------------------------------------------------------
    # Mouse (only reached when unlocked)
    # ------------------------------------------------------------------
    def _grip_rect(self) -> QRect:
        return QRect(self.width() - RESIZE_GRIP, self.height() - RESIZE_GRIP,
                     RESIZE_GRIP, RESIZE_GRIP)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._grip_rect().contains(event.position().toPoint()):
            self._resize_origin = (QCursor.pos(), self.size())
        else:
            self._drag_origin = QCursor.pos() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._resize_origin is not None:
            origin, size = self._resize_origin
            delta = QCursor.pos() - origin
            self.resize(max(MIN_WIDTH, size.width() + delta.x()),
                        max(MIN_HEIGHT, size.height() + delta.y()))
        elif self._drag_origin is not None:
            self.move(QCursor.pos() - self._drag_origin)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_origin is not None or self._resize_origin is not None:
            self.save_geometry()
            self.geometry_changed.emit()
        self._drag_origin = None
        self._resize_origin = None
        self.setCursor(Qt.OpenHandCursor)
        event.accept()


    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    # Three displays, one painter. What they have in common is factored out --
    # the backing, the portrait, the progress ring, the spell badge, the
    # countdown -- so a change to how a cooldown *looks* lands in all three at
    # once instead of letting them drift into three different products.
    def paintEvent(self, _event) -> None:
        theme = THEMES.get(str(self.settings.get("theme", "dark")), THEMES["dark"])
        scale = max(0.6, min(2.0, float(self.settings.get("overlay_scale", 1.0))))
        locked = bool(self.settings.get("overlay_locked", True))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        # The track places its portraits at fractional coordinates so they drift
        # rather than tick; without this hint a fractional blit is resampled the
        # cheap way and the drift comes back as a shimmer.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        self._apply_minimum_height(scale)

        layout = self.current_layout()
        if layout == LAYOUT_CARDS:
            self._paint_cards(painter, theme, scale, locked)
        elif layout == LAYOUT_LIST:
            self._paint_list(painter, theme, scale, locked)
        else:
            self._paint_bar(painter, theme, scale, locked)
        painter.end()
        # Decided by the pass that has just run: the layout knows whether any
        # marker is still short of where it belongs, and nothing else does.
        self._sync_glide_timer()

    # ------------------------------------------------------------------
    # Shared pieces
    # ------------------------------------------------------------------
    @staticmethod
    def _progress(timer: ActiveTimer) -> float:
        """How far through the cooldown, 0 at cast and 1 when ready."""
        if timer.duration <= 0:
            return 1.0
        elapsed = timer.duration - timer.remaining()
        return max(0.0, min(1.0, elapsed / timer.duration))

    @classmethod
    def _state(cls, timer: ActiveTimer) -> str:
        """Which rung of the ladder a cooldown is on. See the thresholds above."""
        remaining = timer.remaining()
        if remaining <= 0:
            return "ready"
        progress = cls._progress(timer)
        if remaining <= NEAR_SECONDS or progress >= NEAR_PROGRESS:
            return "near"
        if remaining <= MID_SECONDS or progress >= MID_PROGRESS:
            return "mid"
        return "far"

    @classmethod
    def _state_colour(cls, theme: dict, timer: ActiveTimer) -> QColor:
        """One meaning per colour, the same in all three displays."""
        return _colour(theme, cls._state(timer))

    def opacity(self) -> float:
        """The user's opacity setting, clamped to what the slider can produce.

        It is applied to the **panel only** -- see :meth:`_paint_backing`. It used
        to be ``setWindowOpacity``, which fades the window and therefore
        everything drawn in it: at 40 % the grey box was pleasantly discreet and
        so were the champions, the countdowns and the colours, which is the
        opposite of what the slider is for. What somebody reaches for that slider
        to hide is the box, not the information.
        """
        try:
            value = float(self.settings.get("overlay_opacity", 0.92))
        except (TypeError, ValueError):
            return 0.92
        return max(0.0, min(1.0, value))

    def _paint_backing(self, painter: QPainter, theme: dict, scale: float,
                       locked: bool, *, idle: bool, radius: float,
                       alpha: float | None = None) -> None:
        """The panel the display sits on, plus the outline that says "unlocked".

        At rest and locked the backing is drawn very faint: enough to find the
        display and see that the program is alive, without putting a solid box
        over the game. Unlocked it is outlined, because that is the moment the
        window has to be findable and grabbable -- so that outline is the one
        thing here the opacity setting does not touch.
        """
        body = QRect(0, 0, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        panel = QColor(_colour(theme, "panel"))
        share = alpha if alpha is not None else (
            theme.get("idle_alpha", BAR_IDLE_ALPHA) if (idle and locked)
            else theme.get("panel_alpha", BAR_PANEL_ALPHA))
        share *= self.opacity()
        panel.setAlpha(max(0, min(255, int(panel.alpha() * share))))
        painter.fillPath(path, panel)
        if not locked:
            pen = QPen(_colour(theme, "edit"))
            pen.setWidthF(1.6)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def _paint_unlocked_hint(self, painter: QPainter, theme: dict, scale: float,
                             rect: QRect) -> None:
        painter.setFont(QFont("Segoe UI", max(6, int(7.5 * scale))))
        painter.setPen(_colour(theme, "role"))
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap,
                         tr("overlay.unlocked_hint"))

    @staticmethod
    def _paint_progress_ring(painter: QPainter, rect: QRectF, width: float,
                             progress: float, colour: QColor,
                             track: QColor) -> None:
        """A ring that closes as the cooldown runs down.

        Drawn from the top and clockwise, which is the direction every cooldown
        sweep in the game itself turns -- so the ring is read without being
        learned. Qt puts 0 degrees at three o'clock and counts counter-clockwise
        in sixteenths of a degree, hence the 90 and the negative span.
        """
        painter.setBrush(Qt.NoBrush)
        pen = QPen(track)
        pen.setWidthF(width)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        if progress <= 0:
            return
        pen = QPen(colour)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * min(1.0, progress)))

    def _paint_portrait(self, painter: QPainter, theme: dict,
                        timer: ActiveTimer, rect: QRectF) -> None:
        """The champion, clipped to a circle. Initials when the icon is missing.

        The fallback matters more than it looks: icons are downloaded on the
        first run, so the very first game after an install can have none of them,
        and a row of empty circles would read as a broken program.

        The rectangle is a float one because on the track it moves, and it moves
        slowly enough that whole pixels would be a series of small jumps. The
        pixmap is cached at a whole-pixel size and *placed* at a fractional one,
        which is the cheap half of the deal: one cache entry per size, and the
        smoothing happens at blit time.
        """
        icon = self.icons.get(self.assets.icon_for_champion(timer.champion_id),
                              round(rect.width()), round_=True)
        if icon is not None:
            painter.drawPixmap(rect.topLeft(), icon)
            return

        painter.setBrush(_colour(theme, "row"))
        painter.setPen(QPen(_colour(theme, "border"), 1.0))
        painter.drawEllipse(rect)
        painter.setBrush(Qt.NoBrush)
        font = QFont("Segoe UI", 1, QFont.Bold)
        font.setPixelSize(max(7, int(rect.width() * 0.36)))
        painter.setFont(font)
        painter.setPen(_colour(theme, "name"))
        painter.drawText(rect, Qt.AlignCenter, timer.champion_name[:2].upper())

    def _paint_spell_badge(self, painter: QPainter, theme: dict,
                           timer: ActiveTimer, rect: QRectF,
                           scale: float) -> None:
        """The spell, on an opaque disc so it reads over anything behind it."""
        painter.setBrush(_colour(theme, "badge"))
        painter.setPen(QPen(_colour(theme, "border"), max(1.0, 0.8 * scale)))
        painter.drawEllipse(rect.adjusted(-1.0, -1.0, 1.0, 1.0))
        painter.setBrush(Qt.NoBrush)

        icon = self.icons.get(self._spell_icon_path(timer), round(rect.width()),
                              round_=True)
        if icon is not None:
            painter.drawPixmap(rect.topLeft(), icon)
        else:
            font = QFont("Segoe UI", 1, QFont.Bold)
            font.setPixelSize(max(6, int(rect.height() * 0.66)))
            painter.setFont(font)
            painter.setPen(_colour(theme, "spell"))
            painter.drawText(rect, Qt.AlignCenter,
                             (timer.spell_name or "?")[:1].upper())

    def _paint_countdown(self, painter: QPainter, theme: dict, rect: QRectF,
                         text: str, colour: QColor, font: QFont,
                         align=Qt.AlignHCenter | Qt.AlignVCenter, *,
                         uncertain: bool = False, scale: float = 1.0) -> None:
        """The number, with a halo under it, and the "?" chip when there is one.

        The backing is see-through by design, so the countdown regularly lands on
        game art of an unpredictable brightness; without the halo it disappears
        exactly when a fight makes the screen busiest.

        The halo's colour comes from the theme rather than being black, because
        under the light theme's dark numerals a black shadow only muddies them --
        what dark text needs is a light halo, which is the same trick inverted.
        """
        chip, box = countdown_layout(rect, text, QFontMetrics(font), align,
                                     uncertain, scale)
        painter.setFont(font)
        painter.setPen(_colour(theme, "shadow"))
        painter.drawText(box.translated(1, 1), align, text)
        painter.setPen(colour)
        painter.drawText(box, align, text)
        if chip is not None:
            self._paint_uncertain_mark(painter, theme, chip, scale)

    def _paint_uncertain_mark(self, painter: QPainter, theme: dict,
                              rect: QRectF, scale: float) -> None:
        """A "?" chip, drawn in the box :func:`countdown_layout` reserved for it.

        It rode the spell icon's corner for a while, and the spell badge is too
        small to carry it: a chip that fits inside a 13 px badge is a chip nobody
        sees mid-fight, and one big enough to see swallows the spell it is
        supposed to be qualifying. Beside the countdown it can be as big as the
        countdown's own digits, with nothing underneath it to hide.
        """
        # Neutral ink on the panel colour rather than a colour from the ladder:
        # green, amber and red each already mean one thing here, and a fourth
        # meaning in the same palette would be read as one of them.
        painter.setBrush(_colour(theme, "badge"))
        painter.setPen(QPen(_colour(theme, "border"), max(1.0, 0.9 * scale)))
        painter.drawEllipse(rect)
        painter.setBrush(Qt.NoBrush)

        # In pixels, not points, unlike the rest of the overlay: the chip is
        # already proportional to the icon, and a glyph sized independently of it
        # outgrows it at some scales.
        font = QFont("Segoe UI", 1, QFont.Bold)
        font.setPixelSize(max(8, int(rect.width() * 0.92)))
        painter.setFont(font)
        painter.setPen(_colour(theme, "name"))
        # Centred in a *larger* box than the disc. A glyph asked for at nearly the
        # disc's width needs more line height than the disc has, and Qt clips text
        # to the rectangle it is given -- which would take the top off the "?"
        # exactly at the sizes this is meant to help. Growing the box symmetrically
        # leaves the centre, and so the glyph, where it was.
        painter.drawText(rect.adjusted(-3.0, -3.0, 3.0, 3.0), Qt.AlignCenter, "?")

    def _spell_icon_path(self, timer: ActiveTimer) -> Path | None:
        if timer.kind == "ultimate":
            champion = self.assets.champions.get(timer.champion_id)
            ult = champion.ultimate if champion else None
            if ult is not None and ult.icon_path and ult.icon_path.exists():
                return ult.icon_path
            return None
        return self.assets.icon_for_spell(timer.spell_key)

    def _paint_grip(self, painter: QPainter, theme: dict, locked: bool) -> None:
        if locked:
            return
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_colour(theme, "border"), 1.6))
        grip = self._grip_rect()
        for offset in (3, 7, 11):
            painter.drawLine(grip.right() - offset, grip.bottom(),
                             grip.right(), grip.bottom() - offset)

    def _draw_nothing_at_rest(self, locked: bool) -> bool:
        """Whether an empty display should draw absolutely nothing.

        Fully invisible is opt-in: without the empty backing there is no sign the
        program is alive or where the display sits. Unlocked always draws, or the
        window could not be found in order to be moved.
        """
        return locked and not bool(self.settings.get("bar_show_when_idle", True))

    # ------------------------------------------------------------------
    # Display 1: the chrono track
    # ------------------------------------------------------------------
    # The track runs one of two ways, and everything below is written in terms of
    # *along* (the direction cooldowns travel) and *across* (the thickness of the
    # thing). Horizontal is the default and vertical is a setting, because which
    # one fits is a question about a player's screen -- a wide monitor has room
    # along the top edge, an ultrawide has more room down a side than it knows
    # what to do with, and neither answer is right for both.
    def bar_is_vertical(self) -> bool:
        return bool(self.settings.get("bar_vertical", False))

    def _bar_metrics(self, scale: float, *, vertical: bool) -> dict:
        """One source for the track's numbers.

        The layout and the painting each used to hold their own copy of these,
        which is how a badge ends up over the next portrait: the two agreed only
        as long as both were edited together.

        ``rail`` is the across-axis position of the line -- a y when the track is
        horizontal, an x when it is vertical -- and the portraits are centred on
        it. They used to hang below it on a stem, which put the one thing this
        display is *for* (a champion at a point on the track) next to the track
        instead of on it.
        """
        icon = int(24 * scale)
        badge = int(17 * scale)
        pad = int(6 * scale)
        time_pt = 8.5 * scale
        # Asked of the font rather than assumed. A row sized by a rule of thumb
        # fits exactly one face: this one was 12 px, which suited the mono it was
        # written for and cropped the taller face that replaced it -- and, worse,
        # made the whole block think it was shorter than it is, which is how a
        # countdown ends up drawn past the bottom of its own panel.
        text = QFontMetrics(countdown_font(time_pt)).height()
        metrics = {
            "icon": icon,
            "badge": badge,
            "pad": pad,
            "gap": int(3 * scale),
            "text": text,
            "overlap": int(badge * BADGE_OVERLAP),
            "ring": max(1.2, 1.6 * scale),
            # Here rather than at the two call sites: the layout measures the
            # countdown to size a slot and the painter draws it, and a slot
            # measured with one font and filled with another is how a time ends
            # up clipped.
            "time_pt": time_pt,
            # Portrait plus the badge hanging off it: the box that must never
            # meet the next marker's.
            "marker": icon + badge - int(badge * BADGE_OVERLAP),
        }
        if vertical:
            # Hard against the left edge, countdowns to its right. Centring the
            # rail in the window would put a column of numbers on both sides of
            # it, or acres of nothing on one.
            metrics["rail"] = pad + icon // 2
        else:
            # Centred on whatever height the window has been dragged to, so a bar
            # left over from an older, taller default is not all dead space --
            # and never so low that the countdown hangs off the bottom, which is
            # what a plain centring does as soon as the content is taller than
            # the window it was measured against.
            content = icon + int(1 * scale) + text
            room = self.height() - pad - content
            metrics["rail"] = max(pad, min((self.height() - content) // 2,
                                           room)) + icon // 2
        return metrics

    def _paint_bar(self, painter: QPainter, theme: dict, scale: float,
                   locked: bool) -> None:
        """A track the cooldowns ride, from "just used" to "back up".

        Position along the track is how much of the cooldown has elapsed, so a
        marker enters at the start the moment a spell is used and arrives at the
        end as it comes back up. That makes "who is nearly back" readable without
        reading any numbers -- the far end is the answer.

        Left to right by default, top to bottom when the vertical setting is on;
        the arithmetic is the same either way, which is why it is written once.
        """
        idle = not self._timers
        if idle and self._draw_nothing_at_rest(locked):
            return

        vertical = self.bar_is_vertical()
        metrics = self._bar_metrics(scale, vertical=vertical)
        self._paint_backing(painter, theme, scale, locked, idle=idle,
                            radius=8.0 * scale)

        start, end = self._bar_track_ends(metrics, vertical)
        if end <= start:
            return
        self._paint_track(painter, theme, scale, metrics, start, end, vertical)

        if idle:
            if not locked:
                hint = (QRect(metrics["rail"] + metrics["icon"], 0,
                              max(10, self.width() - metrics["rail"]
                                  - metrics["icon"]), self.height())
                        if vertical else
                        QRect(0, metrics["rail"] + metrics["icon"] // 2,
                              self.width(), metrics["text"] * 2))
                self._paint_unlocked_hint(painter, theme, scale, hint)
            self._paint_grip(painter, theme, locked)
            return

        time_font = countdown_font(metrics["time_pt"])
        align = ((Qt.AlignLeft | Qt.AlignVCenter) if vertical
                 else (Qt.AlignHCenter | Qt.AlignVCenter))
        for marker in self._bar_markers(scale):
            timer = marker.timer
            portrait = QRect(marker.icon_x, marker.icon_y,
                             metrics["icon"], metrics["icon"])
            colour = self._state_colour(theme, timer)

            # The ring repeats in colour what the position already says: the eye
            # catches green long before it measures a distance along a track.
            self._paint_portrait(painter, theme, timer, portrait)
            pen = QPen(colour if timer.is_ready() else _colour(theme, "border"))
            pen.setWidthF(metrics["ring"])
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(portrait)

            badge = QRect(marker.icon_x + metrics["icon"] - marker.overlap,
                          marker.icon_y + metrics["icon"] - metrics["badge"],
                          metrics["badge"], metrics["badge"])
            self._paint_spell_badge(painter, theme, timer, badge, scale)

            # A window too short for its own contents gets the portraits and no
            # numbers, rather than numbers outside the panel. The minimum height
            # above normally makes this unreachable; it is here because "nothing
            # is ever drawn outside the frame" should not depend on that.
            if marker.text.height() >= 8:
                self._paint_countdown(painter, theme, marker.text,
                                      timer.display(), colour, time_font, align,
                                      uncertain=timer.uncertain, scale=scale)

        self._paint_grip(painter, theme, locked)

    def _apply_minimum_height(self, scale: float) -> None:
        """Stop the window being shorter than the display drawn in it.

        The horizontal track is the one with a fixed vertical budget -- a
        portrait, then a countdown under it -- and that budget grows with the
        scale setting. Left to itself a window saved at one scale and reopened at
        a larger one has the countdown hanging off the bottom edge, which is
        exactly the bug this exists to make impossible: Qt refuses the resize and
        repairs a saved rectangle that was already too short.

        Cheap enough to do from the paint: ``setMinimumHeight`` with the value it
        already has does nothing, and the value only changes when the scale or
        the display does.
        """
        if self.current_layout() != LAYOUT_BAR or self.bar_is_vertical():
            self.setMinimumHeight(MIN_HEIGHT)
            return
        metrics = self._bar_metrics(scale, vertical=False)
        needed = (metrics["icon"] + int(1 * scale) + metrics["text"]
                  + 2 * metrics["pad"])
        self.setMinimumHeight(max(MIN_HEIGHT, needed))

    def _bar_track_ends(self, metrics: dict, vertical: bool) -> tuple[int, int]:
        """First and last point of the rail, along whichever axis it runs."""
        length = self.height() if vertical else self.width()
        return (metrics["pad"] + metrics["icon"] // 2,
                length - metrics["pad"] - metrics["icon"] // 2)

    def _paint_track(self, painter: QPainter, theme: dict, scale: float,
                     metrics: dict, start: int, end: int,
                     vertical: bool) -> None:
        """The rail the markers ride, with the arrival end marked.

        A hairline and nothing more. It used to be a dark capsule under a lighter
        one, with a tick at each end, and all of that was drawn every frame to
        hold up a line the markers already explain: the portraits are what is
        read, and the rail is only the thing they sit on. What is left is the one
        piece that carries meaning -- the green segment at the far end, which
        says which way the markers travel and what waits for them there.
        """
        thickness = max(2, int(2.4 * scale))
        across = metrics["rail"] - thickness // 2
        rail = (QRect(across, start, thickness, end - start) if vertical
                else QRect(start, across, end - start, thickness))
        radius = thickness / 2.0

        painter.setPen(Qt.NoPen)
        body = QPainterPath()
        body.addRoundedRect(rail, radius, radius)
        # Its own colour in the theme: the "border" tone disappears against a
        # mid-tone game, and what reads on a dark panel is not what reads on a
        # light one.
        painter.fillPath(body, _colour(theme, "rail"))

        run = rail.height() if vertical else rail.width()
        cap_run = max(int(8 * scale), min(int(run * 0.14), int(40 * scale)))
        cap = QPainterPath()
        cap.addRoundedRect(
            QRect(rail.x(), rail.bottom() - cap_run, thickness, cap_run)
            if vertical else
            QRect(rail.right() - cap_run, rail.y(), cap_run, thickness),
            radius, radius)
        ready = QColor(_colour(theme, "ready"))
        ready.setAlpha(150)
        painter.fillPath(cap, ready)
        painter.setBrush(Qt.NoBrush)

    def _bar_markers(self, scale: float) -> list[BarMarker]:
        """Where each cooldown sits on the track, in order of progress.

        Separate from the painting so the placement can be checked without a
        screen: "no two markers on the same pixels" is a geometry property, and
        it is the one that decides whether a champion is visible at all.
        """
        if not self._timers:
            return []
        vertical = self.bar_is_vertical()
        metrics = self._bar_metrics(scale, vertical=vertical)
        start, end = self._bar_track_ends(metrics, vertical)
        if end <= start:
            return []

        text = QFontMetrics(countdown_font(metrics["time_pt"]))
        chip = chip_extra(text, scale)
        ordered = sorted(self._timers, key=self._progress)

        # Each marker owns a slot along the axis, and keeping slots apart keeps
        # the markers apart. Across the axis the two orientations differ: laid
        # out horizontally the countdown goes under the portrait, so the slot has
        # to hold the wider of the two; laid out vertically it goes beside the
        # portrait, so the slot only has to be as tall as the taller of them.
        #
        # The room for a "?" chip is reserved on every slot, not just the
        # uncertain ones, so a ping being confirmed cannot shuffle the track.
        if vertical:
            spans = [max(metrics["icon"], text.height()) + int(4 * scale)
                     for _ in ordered]
        else:
            spans = [max(metrics["marker"],
                         text.horizontalAdvance(timer.display()) + chip)
                     + int(6 * scale) for timer in ordered]
        # Two spells used in the same breath share a point on the track, so the
        # whole row is laid out at once rather than one marker at a time: the
        # exact pixel is not the readout, the countdown text is, and a few
        # pixels of drift costs nothing next to a hidden champion.
        targets = [int(start + (end - start) * self._progress(timer)) - span // 2
                   for timer, span in zip(ordered, spans)]
        length = self.height() if vertical else self.width()
        lefts = self._spread(spans, targets, metrics["pad"] // 2,
                             length - metrics["pad"] // 2, metrics["gap"])
        lefts = self._glide(ordered, lefts)

        markers = []
        for timer, span, left in zip(ordered, spans, lefts):
            if vertical:
                icon_x = metrics["rail"] - metrics["icon"] / 2.0
                icon_y = left + (span - metrics["icon"]) / 2.0
                text_x = icon_x + metrics["marker"] + int(5 * scale)
                text_rect = QRectF(text_x, left,
                                   max(10.0, self.width() - metrics["pad"] - text_x),
                                   span)
            else:
                icon_x = left + (span - metrics["marker"]) / 2.0
                icon_y = metrics["rail"] - metrics["icon"] / 2.0
                text_y = icon_y + metrics["icon"] + int(1 * scale)
                # Whatever room is left under the portraits, and not a pixel
                # more. On a window too short for the whole block the number is
                # cropped inside the panel, which is a bad look; drawn past the
                # panel's edge it is a bug report.
                text_rect = QRectF(left, text_y, span,
                                   max(0.0, min(float(metrics["text"]),
                                                self.height() - metrics["pad"]
                                                - text_y)))
            markers.append(BarMarker(
                timer=timer, left=left, span=span, icon_x=icon_x,
                icon_y=icon_y, overlap=metrics["overlap"],
                rect=QRectF(icon_x, icon_y, metrics["marker"], metrics["icon"]),
                text=text_rect))
        return markers

    def _glide(self, ordered: list[ActiveTimer],
               targets: list[float]) -> list[float]:
        """Ease each marker towards where the layout says it belongs.

        Three things make a bare layout jump rather than move, and no frame rate
        fixes any of them: two markers crossing swap slots outright; a marker
        crowded by its neighbour is shoved a slot's width sideways; and a spell
        appearing or expiring re-spreads the whole row. Easing absorbs all three
        into a glide of about a fifth of a second.

        The rest of the smoothness is that these are floats. A 300-second
        cooldown crosses a 570-pixel track at under two pixels a second, so on
        integer coordinates every icon sits still for half a second and then
        jumps a whole pixel -- a tick the eye catches precisely because nothing
        else on the track is moving. Sub-pixel positions turn that into what it
        physically is: continuous, slow drift.

        Time-based rather than per-frame, so the speed of the glide does not
        depend on how often anything repaints -- and so calling this twice in one
        frame (the painter and a test asking for the same layout) advances it by
        the zero seconds that have actually passed.
        """
        now = monotonic()
        elapsed = min(0.5, max(0.0, now - self._glide_at))
        self._glide_at = now
        share = 1.0 - exp(-elapsed / GLIDE_TAU) if elapsed > 0.0 else 0.0

        eased: list[float] = []
        live: dict[tuple[str, str], float] = {}
        travelling = False
        for timer, target in zip(ordered, targets):
            key = (timer.champion_id, timer.spell_key)
            current = self._glide_from.get(key)
            # A marker that has just appeared starts where it belongs: sliding in
            # from wherever the previous occupant of that key sat would be an
            # animation of something that never happened.
            value = float(target) if current is None else (
                current + (target - current) * share)
            travelling = travelling or abs(target - value) > GLIDE_SETTLED
            live[key] = value
            eased.append(value)
        self._glide_from = live
        self._gliding = travelling
        return eased

    def _bar_marker_rects(self) -> list[QRectF]:
        """Portrait+badge boxes as currently laid out. Used by the tests."""
        scale = max(0.6, min(2.0, float(self.settings.get("overlay_scale", 1.0))))
        return [marker.rect for marker in self._bar_markers(scale)]

    @staticmethod
    def _spread(spans: list[int], targets: list[int], min_left: int,
                max_right: int, gap: int) -> list[int]:
        """Place markers near their target x without letting them overlap.

        ``targets`` must be non-decreasing (they come from the cooldown
        progress, sorted). Two spells used at the same moment share a target,
        and clamping each one to the bar's edges separately used to stack them:
        markers piling up at the right end were all pushed back onto the same
        pixel, hiding every portrait but the last.

        Forward pass pushes overlapping markers rightwards, backward pass pushes
        the run back inside the right edge. When the markers cannot all fit --
        a narrow bar with many cooldowns running -- they are spread evenly over
        the whole width, so the crowding is shared instead of two icons landing
        exactly on top of each other.
        """
        count = len(spans)
        if count == 0:
            return []
        available = max_right - min_left
        needed = sum(spans) + gap * (count - 1)
        if count > 1 and needed > available:
            step = (available - max(spans)) / (count - 1)
            return [min_left + int(index * step) for index in range(count)]

        lefts: list[int] = []
        cursor = min_left
        for span, target in zip(spans, targets):
            left = max(target, cursor)
            lefts.append(left)
            cursor = left + span + gap

        cursor = max_right
        for index in range(count - 1, -1, -1):
            left = max(min_left, min(lefts[index], cursor - spans[index]))
            lefts[index] = left
            cursor = left - gap
        return lefts

    # ------------------------------------------------------------------
    # Display 2: fixed cards
    # ------------------------------------------------------------------
    @staticmethod
    def _card_font(scale: float) -> QFont:
        return countdown_font(9 * scale)

    def _card_metrics(self, scale: float) -> dict:
        portrait = int(CARD_PORTRAIT * scale)
        badge = int(CARD_BADGE * scale)
        # From the font, for the reason the track's is: a row shorter than the
        # letters it holds crops them, and a card shorter than its own contents
        # puts the last line outside the panel.
        text = QFontMetrics(self._card_font(scale)).height()
        # A card is as wide as the widest thing in it, and that is not always the
        # portrait: READY plus a "?" chip overruns a portrait and its badge. The
        # room is reserved on every card and at every moment -- cards are the
        # display whose whole point is that nothing moves, so a width that
        # depended on what is currently uncertain would defeat it.
        widest = QFontMetrics(self._card_font(scale))
        return {
            "portrait": portrait,
            "badge": badge,
            "ring": max(1.6, CARD_RING * scale),
            "text": text,
            "width": max(portrait + badge // 2 + int(3 * scale),
                         widest.horizontalAdvance("READY")
                         + chip_extra(widest, scale)),
            "height": portrait + int(1 * scale) + text,
            "gap": int(CARD_GAP * scale),
            "pad": int(CARD_PAD * scale),
        }

    def _card_slots(self, scale: float) -> list[CardSlot]:
        """One card per cooldown, in fixed slots, wrapped to the window's width.

        Laid out apart from the painting for the same reason the track is: the
        property that matters -- every card visible, none on top of another, all
        of them inside the window -- is geometry, and geometry can be checked
        without a screen.

        Order is whatever the timer manager handed over (by role, or by time
        left), so a card stays where the eye last found it instead of sliding as
        the cooldown runs down. That stillness is the point of this display.
        """
        if not self._timers:
            return []
        metrics = self._card_metrics(scale)
        usable = self.width() - 2 * metrics["pad"]
        if usable < metrics["width"]:
            return []
        columns = max(1, (usable + metrics["gap"])
                      // (metrics["width"] + metrics["gap"]))
        rows = max(1, (self.height() - 2 * metrics["pad"] + metrics["gap"])
                   // (metrics["height"] + metrics["gap"]))

        slots: list[CardSlot] = []
        total = len(self._timers)
        for index, timer in enumerate(self._timers):
            row, column = divmod(index, columns)
            if row >= rows:
                # More cooldowns than the window has room for. Dropping the tail
                # is the honest failure: half a card is not information, and the
                # window can be made bigger.
                break
            in_row = min(columns, total - row * columns)
            row_width = in_row * metrics["width"] + (in_row - 1) * metrics["gap"]
            x = ((self.width() - row_width) // 2
                 + column * (metrics["width"] + metrics["gap"]))
            y = metrics["pad"] + row * (metrics["height"] + metrics["gap"])

            # The portrait and the badge overhanging it are centred on the card
            # rather than pinned to its left edge: the card is now as wide as its
            # countdown needs, which is wider than the two of them.
            group = metrics["portrait"] + int(metrics["badge"] * 0.55)
            portrait = QRect(x + (metrics["width"] - group) // 2, y,
                             metrics["portrait"], metrics["portrait"])
            slots.append(CardSlot(
                timer=timer,
                rect=QRect(x, y, metrics["width"], metrics["height"]),
                portrait=portrait,
                badge=QRect(portrait.right() - int(metrics["badge"] * 0.45),
                            portrait.bottom() - metrics["badge"] + 1,
                            metrics["badge"], metrics["badge"]),
                text=QRect(x, portrait.bottom() + int(1 * scale),
                           metrics["width"], metrics["text"])))
        return slots

    def _card_rects(self) -> list[QRect]:
        """Card boxes as currently laid out. Used by the tests."""
        scale = max(0.6, min(2.0, float(self.settings.get("overlay_scale", 1.0))))
        return [slot.rect for slot in self._card_slots(scale)]

    def _paint_cards(self, painter: QPainter, theme: dict, scale: float,
                     locked: bool) -> None:
        """A card per cooldown, at a place that never moves.

        The track is clever but it moves, and a moving thing has to be found
        before it can be read. Here the portrait stays put and the ring around it
        closes instead -- the same sweep every cooldown in the game itself draws,
        so this display is read rather than learned.
        """
        idle = not self._timers
        if idle and self._draw_nothing_at_rest(locked):
            return

        metrics = self._card_metrics(scale)
        self._paint_backing(painter, theme, scale, locked, idle=idle,
                            radius=8.0 * scale)

        if idle:
            if not locked:
                self._paint_unlocked_hint(painter, theme, scale, self.rect())
            self._paint_grip(painter, theme, locked)
            return

        time_font = self._card_font(scale)
        # The unfilled part of the ring has to be visible, or a cooldown that has
        # barely started shows a tick of colour and no ring at all -- which reads
        # as a rendering fault rather than as "just used".
        track = _colour(theme, "rail")
        # The gap between the ring and the portrait is what makes the ring
        # readable, and it is wider than it looks like it needs to be on purpose.
        # Champion artwork is mostly dark, so a dark ring drawn tight against it
        # merges into it -- which is exactly what happened when the light theme
        # turned the neutral ring from near-white to near-black. Let the panel show
        # through between the two and each is seen against its own ground.
        inset = int(metrics["ring"]) + 3

        for slot in self._card_slots(scale):
            timer = slot.timer
            colour = self._state_colour(theme, timer)

            if timer.is_ready():
                # A wash inside the ring, so a spell that is back up is caught by
                # the eye before any number is read.
                glow = QColor(_colour(theme, "ready"))
                glow.setAlpha(52)
                painter.setBrush(glow)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(slot.portrait)
                painter.setBrush(Qt.NoBrush)

            self._paint_portrait(painter, theme, timer,
                                 slot.portrait.adjusted(inset, inset,
                                                        -inset, -inset))
            self._paint_progress_ring(
                painter, slot.portrait.adjusted(1, 1, -1, -1), metrics["ring"],
                self._progress(timer), colour, track)
            self._paint_spell_badge(painter, theme, timer, slot.badge, scale)
            self._paint_countdown(painter, theme, slot.text, timer.display(),
                                  colour, time_font,
                                  uncertain=timer.uncertain, scale=scale)

        self._paint_grip(painter, theme, locked)

    # ------------------------------------------------------------------
    # Display 3: compact rows
    # ------------------------------------------------------------------
    def _paint_list(self, painter: QPainter, theme: dict, scale: float,
                    locked: bool) -> None:
        """One row per cooldown: champion, spell, time left, and a gauge.

        The most legible of the three, and it earns that by being a table rather
        than a picture. One line per champion: the two-line row that spelled out
        the spell's name under the champion's cost a third of the height to
        repeat what the badge beside it already shows.

        The gauge under each row is what makes it more than a table: it answers
        "nearly back?" without the number having to be compared against a
        cooldown the player would need to know by heart.
        """
        idle = not self._timers
        radius = 8.0 * scale
        self._paint_backing(painter, theme, scale, locked, idle=idle,
                            radius=radius, alpha=1.0)
        # The outline is the panel's edge, so it fades with the panel: turning
        # the opacity down to hide the box and being left with a rectangle drawn
        # round the rows would defeat the point. Unlocked it is exempt, like the
        # rest of the placement chrome.
        edge = QColor(_colour(theme, "border" if locked else "edit"))
        if locked:
            edge.setAlpha(max(0, min(255, int(edge.alpha() * self.opacity()))))
        pen = QPen(edge)
        pen.setWidthF(1.2 if locked else 2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        outline = QPainterPath()
        outline.addRoundedRect(QRect(0, 0, self.width() - 1, self.height() - 1),
                               radius, radius)
        painter.drawPath(outline)

        pad = int(7 * scale)
        y = pad

        # The title is worth a row when there is nothing else to show, or while
        # the window is being moved. It is not worth one in a fight.
        if idle or not locked:
            painter.setFont(QFont("Segoe UI", max(6, int(8 * scale)),
                                  QFont.DemiBold))
            painter.setPen(_colour(theme, "title"))
            header = QRect(pad, y, self.width() - pad * 2, int(16 * scale))
            painter.drawText(header, Qt.AlignLeft | Qt.AlignVCenter,
                             tr("overlay.enemy_spells"))
            if not locked:
                painter.setPen(_colour(theme, "edit"))
                painter.drawText(header, Qt.AlignRight | Qt.AlignVCenter,
                                 tr("overlay.unlocked"))
            y += int(18 * scale)

        if idle:
            painter.setFont(QFont("Segoe UI", max(6, int(8 * scale))))
            painter.setPen(_colour(theme, "role"))
            message = self._status or tr("overlay.waiting")
            painter.drawText(QRect(pad, y, self.width() - pad * 2,
                                   self.height() - y - pad),
                             Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                             message)
            self._paint_grip(painter, theme, locked)
            return

        icon_size = int(22 * scale)
        spell_size = int(19 * scale)
        gauge_height = max(2, int(2.2 * scale))
        row_height = max(icon_size + int(6 * scale), int(28 * scale))
        name_font = QFont("Segoe UI", max(6, int(8 * scale)), QFont.DemiBold)
        time_font = countdown_font(9.5 * scale)
        time_metrics = QFontMetrics(time_font)
        name_metrics = QFontMetrics(name_font)
        # The "?" chip's room is part of the column, always: a countdown that
        # widened the moment a ping was confirmed would drag every champion's
        # name along with it.
        time_width = (time_metrics.horizontalAdvance("READY")
                      + chip_extra(time_metrics, scale) + int(6 * scale))

        for timer in self._timers:
            if y + row_height > self.height() - pad:
                break

            colour = self._state_colour(theme, timer)
            row = QRect(pad // 2, y, self.width() - pad, row_height)
            row_path = QPainterPath()
            row_path.addRoundedRect(row, 5.0 * scale, 5.0 * scale)
            painter.fillPath(row_path, _colour(theme, "row"))

            # Everything but the gauge sits on this band, so the name and the
            # countdown centre on the same line instead of each finding its own.
            band = QRect(row.x(), y, row.width(), row_height - gauge_height)

            x = pad
            self._paint_portrait(
                painter, theme, timer,
                QRect(x, band.y() + (band.height() - icon_size) // 2,
                      icon_size, icon_size))
            x += icon_size + int(5 * scale)

            self._paint_spell_badge(
                painter, theme, timer,
                QRect(x, band.y() + (band.height() - spell_size) // 2,
                      spell_size, spell_size), scale)
            x += spell_size + int(6 * scale)

            text_width = max(10, self.width() - pad - time_width - x)
            painter.setFont(name_font)
            painter.setPen(_colour(theme, "name"))
            painter.drawText(QRect(x, band.y(), text_width, band.height()),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             name_metrics.elidedText(timer.champion_name,
                                                     Qt.ElideRight, text_width))

            self._paint_countdown(
                painter, theme,
                QRect(self.width() - pad - time_width, band.y(), time_width,
                      band.height()),
                timer.display(), colour, time_font,
                Qt.AlignRight | Qt.AlignVCenter,
                uncertain=timer.uncertain, scale=scale)

            self._paint_gauge(
                painter, theme, timer, colour,
                QRect(row.x() + int(3 * scale),
                      row.bottom() - gauge_height - int(1 * scale),
                      row.width() - int(6 * scale), gauge_height))
            y += row_height + int(2 * scale)

        self._paint_grip(painter, theme, locked)

    def _paint_gauge(self, painter: QPainter, theme: dict, timer: ActiveTimer,
                     colour: QColor, rect: QRect) -> None:
        """A hairline under a row that fills as the cooldown runs down."""
        radius = rect.height() / 2.0
        painter.setPen(Qt.NoPen)
        base = QPainterPath()
        base.addRoundedRect(rect, radius, radius)
        painter.fillPath(base, _colour(theme, "rail"))

        filled = int(rect.width() * self._progress(timer))
        if filled <= 0:
            return
        done = QPainterPath()
        done.addRoundedRect(QRect(rect.x(), rect.y(), filled, rect.height()),
                            radius, radius)
        painter.fillPath(done, colour)
