"""The interface's look: the drawing palette, and the window's own.

Two things live here, and they are not the same thing.

:data:`PALETTES` (with :data:`ACTIVE`) fills the constants used by everything
that is *painted* -- the display sketches, the zone frame, the guide's figures.

:data:`MENU` is the **control window's** palette, ported value by value from
``design/maquette/Flashwatch *.dc.html``, and :func:`control_qss` is the
stylesheet built from it. That window used to be light and is now dark, which is
the right way round for something opened during a game over a nearly-black
client. The painted constants stayed light: they are read at a glance off a game,
which is a different problem from reading a settings page.

Every colour is checked rather than eyeballed. On a light ground that is not
optional: the cyan the dark palette used for its accent scores 1.9 against white,
which is invisible, and the amber and green it used for "soon" and "ready" score
1.8 and 1.6. Each colour below clears **4.5:1** against both grounds it is drawn
on -- the ratios are in the palette's own comments, so a future edit can be checked
without rediscovering the arithmetic.

Deliberately independent of the overlay's ``theme`` setting. That setting styles the
bar drawn over the game, where the choice between light, dark and neon is about the
game behind it; this window is a desktop window and follows the product's identity.
The two happen to agree today -- both default to light -- and they are still not the
same switch.

Qt stylesheets are not CSS. Five differences bite:

* there are no variables, so the palette is interpolated into one f-string;
* ``font-family`` takes a list, but only Qt 6 picks the first *available* one --
  which is what lets the page's Google fonts be named first and fall back to
  what Windows actually ships;
* a rule with no explicit background makes the widget transparent, so container
  widgets are set explicitly rather than left to inherit;
* ``text-transform`` is parsed and then **ignored**. It looks like it works right
  up until a translation is written in lower case. Uppercase is applied in Python
  instead, at the call site;
* ``box-shadow`` and ``text-shadow`` do not exist at all. A shadow has to be
  painted (the overlay does that under its countdowns) or come from a
  ``QGraphicsDropShadowEffect``.

``letter-spacing``, on the other hand, does work, despite not being in Qt's
documented property list -- measured, not assumed: it takes a mono label from 88
to 133 pixels.

The full list of what can and cannot be reproduced lives in
``design/CONTRAINTES-QT.md``, which is what an art direction has to be checked
against before anyone starts drawing.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QFontDatabase, QPainter, QPen, QPixmap)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The palettes. Ratios in the comments are against the surface the colour is
# actually drawn on, computed rather than guessed.
# ---------------------------------------------------------------------------
PALETTES = {
    "light": {
        # Grounds. FIELD is the window, FIELD_2 the header and the side
        # navigation (a shade darker than the ground, so the content area reads
        # as the front-most surface), PANEL the cards.
        "field": "#eef1f6",
        "field_2": "#e6ebf3",
        "panel": "#ffffff",
        "panel_2": "#f7f9fc",
        # Inset areas: a read-only log, a field. A wash of the ink rather than a
        # lighter white, since there is nothing lighter than the card already is.
        "sunken": "rgba(20, 30, 55, 0.05)",
        "line": "rgba(24, 36, 62, 0.14)",
        "line_strong": "rgba(24, 36, 62, 0.30)",
        "ink": "#141a24",          # 17.5 on white
        "ink_dim": "#4a5566",      # 7.6
        "ink_faint": "#606b7e",    # 5.4 -- these carry real explanations, not
                                   # decoration, so they clear 4.5 too
        "signal": "#06699f",       # 6.0
        "signal_hover": "#05587f",
        "ready": "#0f6b3d",        # 6.6
        "soon": "#8a4d00",         # 6.7
        "danger": "#b02524",       # 6.7
        "signal_wash": "rgba(6, 105, 159, 0.06)",
        "signal_fill": "rgba(6, 105, 159, 0.12)",
        "signal_edge": "rgba(6, 105, 159, 0.34)",
        "ready_wash": "rgba(15, 107, 61, 0.10)",
        "ready_edge": "rgba(15, 107, 61, 0.34)",
        "soon_wash": "rgba(138, 77, 0, 0.10)",
        "soon_edge": "rgba(138, 77, 0, 0.34)",
        "danger_wash": "rgba(176, 37, 36, 0.09)",
        "danger_edge": "rgba(176, 37, 36, 0.32)",
        "hover_wash": "rgba(20, 30, 55, 0.06)",
        "input_bg": "rgba(20, 30, 55, 0.04)",
        # The switch. Its knob has to be visible against its own track, which on a
        # light ground means a mid grey knob rather than the pale one a dark
        # palette can use.
        "switch_knob": "#8b95a6",
        "switch_track": "rgba(20, 30, 55, 0.10)",
        "scroll_handle": "rgba(24, 36, 62, 0.22)",
        "scroll_handle_hover": "rgba(24, 36, 62, 0.38)",
        # Surfaces that are *painted* rather than styled -- the layout thumbnails,
        # the guide's figures, the region picker. As RGBA tuples, since QPainter
        # wants a QColor and not a CSS string. They live here because they were
        # scattered as literals across two modules, every one of them assuming a
        # dark ground, which is exactly what made going light a hunt rather than a
        # setting.
        "paint": {
            "sketch_bg": (255, 255, 255, 235),   # inset ground of a thumbnail
            "figure_bg": (255, 255, 255, 220),   # a guide figure's panel
            "hairline": (24, 36, 62, 70),        # a rule inside a painted figure
            "row_wash": (24, 36, 62, 14),        # a neutral row inside a figure
            "tile_on_fill": (6, 105, 159, 26),
            "tile_off_fill": (24, 36, 62, 12),
            "tile_edge": (24, 36, 62, 60),
            "step_dot_off": (185, 192, 204, 255),
            # A game screen drawn inside a diagram stays dark whatever the
            # interface does: it depicts League, not this program.
            "screen_bg": (16, 19, 27, 255),
            "game_tint": (30, 38, 52, 255),
            "chat_bg": (8, 10, 16, 210),
            "taskbar_bg": (12, 14, 20, 240),
            "taskbar_icon": (70, 80, 100, 150),
            # The region picker dims the whole desktop to make the selection
            # legible. Darkening is the point, so it does not follow the palette.
            "scrim": (0, 0, 0, 110),
            "scrim_ink": (255, 255, 255, 220),
        },
    },
    "dark": {
        # The original, lifted verbatim from the download page's :root block.
        "field": "#0a0c11",
        "field_2": "#0e1117",
        "panel": "#12161f",
        "panel_2": "#0c0f15",
        "sunken": "rgba(9, 11, 16, 0.66)",
        "line": "rgba(96, 112, 142, 0.28)",
        "line_strong": "rgba(120, 140, 175, 0.5)",
        "ink": "#e9eef8",
        "ink_dim": "#8d99b0",
        "ink_faint": "#5d6779",
        "signal": "#5ac8ff",
        "signal_hover": "#7ad4ff",
        "ready": "#6ee28e",
        "soon": "#ffb04a",
        "danger": "#ff6b6b",
        "signal_wash": "rgba(90, 200, 255, 0.07)",
        "signal_fill": "rgba(90, 200, 255, 0.14)",
        "signal_edge": "rgba(90, 200, 255, 0.30)",
        "ready_wash": "rgba(110, 226, 142, 0.13)",
        "ready_edge": "rgba(110, 226, 142, 0.34)",
        "soon_wash": "rgba(255, 176, 74, 0.13)",
        "soon_edge": "rgba(255, 176, 74, 0.34)",
        "danger_wash": "rgba(255, 107, 107, 0.12)",
        "danger_edge": "rgba(255, 107, 107, 0.32)",
        "hover_wash": "rgba(255, 255, 255, 0.04)",
        "input_bg": "rgba(255, 255, 255, 0.03)",
        "switch_knob": "#5d6779",
        "switch_track": "rgba(120, 140, 175, 0.18)",
        "scroll_handle": "rgba(120, 140, 175, 0.3)",
        "scroll_handle_hover": "rgba(120, 140, 175, 0.5)",
        "paint": {
            "sketch_bg": (9, 11, 16, 170),
            "figure_bg": (9, 11, 16, 190),
            "hairline": (96, 112, 142, 90),
            "row_wash": (255, 255, 255, 10),
            "tile_on_fill": (90, 200, 255, 26),
            "tile_off_fill": (255, 255, 255, 8),
            "tile_edge": (96, 112, 142, 90),
            "step_dot_off": (60, 70, 88, 255),
            "screen_bg": (16, 19, 27, 255),
            "game_tint": (30, 38, 52, 255),
            "chat_bg": (8, 10, 16, 210),
            "taskbar_bg": (12, 14, 20, 240),
            "taskbar_icon": (70, 80, 100, 150),
            "scrim": (0, 0, 0, 110),
            "scrim_ink": (255, 255, 255, 220),
        },
    },
}

ACTIVE = "light"
_P = PALETTES[ACTIVE]

FIELD = _P["field"]
FIELD_2 = _P["field_2"]
PANEL = _P["panel"]
PANEL_2 = _P["panel_2"]
SUNKEN = _P["sunken"]
LINE = _P["line"]
LINE_STRONG = _P["line_strong"]
INK = _P["ink"]
INK_DIM = _P["ink_dim"]
INK_FAINT = _P["ink_faint"]
SIGNAL = _P["signal"]
SIGNAL_HOVER = _P["signal_hover"]
READY = _P["ready"]
SOON = _P["soon"]
DANGER = _P["danger"]
SIGNAL_WASH = _P["signal_wash"]
SIGNAL_FILL = _P["signal_fill"]
SIGNAL_EDGE = _P["signal_edge"]
READY_WASH = _P["ready_wash"]
READY_EDGE = _P["ready_edge"]
SOON_WASH = _P["soon_wash"]
SOON_EDGE = _P["soon_edge"]
DANGER_WASH = _P["danger_wash"]
DANGER_EDGE = _P["danger_edge"]
HOVER_WASH = _P["hover_wash"]
INPUT_BG = _P["input_bg"]
SWITCH_KNOB = _P["switch_knob"]
SWITCH_TRACK = _P["switch_track"]
SCROLL_HANDLE = _P["scroll_handle"]
SCROLL_HANDLE_HOVER = _P["scroll_handle_hover"]
# RGBA tuples for the hand-painted surfaces; see the palette's "paint" block.
PAINT = _P["paint"]

# Named first for anyone who has them, then what Windows actually ships.
FONT_BODY = '"Barlow", "Segoe UI", sans-serif'
FONT_DISPLAY = '"Chakra Petch", "Segoe UI Semibold", "Segoe UI", sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'
# The guide's headline face. Georgia ships with Windows, so the one serif in the
# product is the one screen that is allowed to feel like a certificate.
FONT_SERIF = '"Georgia", "Times New Roman", serif'

# ---------------------------------------------------------------------------
# The setup guide's own palette
#
# The guide is the only dark surface left in a light product, and that is a
# decision rather than a leftover. It is shown once, full-window, before anything
# else exists; it is read from a chair rather than glanced at mid-fight; and every
# figure in it depicts *League*, which is dark. A light guide would have put a
# white page between a dark game and its dark screenshots.
#
# Ported value for value from ``design/maquette/Onboarding *.dc.html``, which is
# where the composition was decided. The names are the mockup's roles, not its
# hex codes, so a restyle stays a list of colours rather than a hunt.
# ---------------------------------------------------------------------------
GUIDE = {
    # The window's ground: a radial wash, brighter at the top left.
    "bg_core": "#131a33",
    "bg_mid": "#0a0e1c",
    "bg_edge": "#070a14",
    "header": "#0a0d19",
    "rule": "#161b2e",           # the two full-width divider lines
    "hairline": "#2a3050",       # a rule inside a figure, the stepper's spine
    # Surfaces.
    "panel": "#0c1122",          # the path card, the back button
    "panel_edge": "#262d49",
    "note": "#0d1224",           # an information note
    "note_edge": "#262c48",
    "card": "#0b0f1e",           # a pickable card at rest
    "card_edge": "#242a44",
    "card_on": "#171233",        # ...and picked, top of its gradient
    "card_on_2": "#100d24",
    "screen": "#0a1120",         # the big framed figure on the right
    "screen_edge": "#6c4be0",
    "inset": "#05070e",          # a thumbnail's ground
    "inset_edge": "#2b3252",
    # Ink.
    "ink": "#ffffff",
    "text": "#dbe0f0",
    "text_2": "#c2c9de",
    "text_3": "#b3bad3",
    "caption": "#c8cee3",
    "dim": "#a8b0cb",
    "dim_2": "#9aa3bf",
    "faint": "#8f97b6",
    # The accent, at the values the mockups actually use it at.
    "accent": "#7c3aed",
    "accent_btn": "#6d28d9",     # the primary button, the filled stepper node
    "accent_btn_2": "#5b21b6",   # ...on the last screen, one step deeper
    "accent_lit": "#8b5cf6",
    "accent_pale": "#c4b5fd",
    "accent_soft": "#a78bfa",
    "accent_deep": "#4c1d95",
    "accent_night": "#1a1240",   # the active stepper node's fill
    # The stepper's unvisited nodes.
    "step_bg": "#12172b",
    "step_ring": "#3a4166",
    "step_off": "#3a4062",
    "ring_off": "#4a5175",
    # Verdicts. Green for a box ticked, red for the one setting that cannot work.
    "ok": "#34d399",
    "bad": "#ef4444",
    # League's own gold, for the parts of a figure that depict its client. Kept
    # apart from the accent on purpose: purple is Flashwatch talking, gold is the
    # game being pointed at.
    "gold": "#c9a45b",
    "gold_lit": "#f0ddae",
    "gold_pale": "#e4c98a",
    "gold_deep": "#8b6b31",
    "gold_frame": "#6b5a34",
    "gold_text": "#e0b969",
    "parchment": "#f5e9ce",
    "teal": "#22d3ee",           # the overlay's own colour in a thumbnail
}
# ---------------------------------------------------------------------------
# The mark, as geometry rather than as a picture.
#
# It is drawn three times -- Qt for the tray and the windows, Pillow for the
# .ico that PyInstaller stamps on the executable -- and those two had already
# drifted apart: the runtime one had thin strokes and no hub, while build.py
# claimed in its docstring to be drawing "the same shape". Two renderers reading
# one set of numbers cannot drift; two renderers holding their own cannot help
# it.
#
# It stays a *dark* disc with a bright cyan rim even though the interface is now
# light, and that is deliberate: the mark also has to hold on the Windows taskbar
# and in the notification area, neither of which this program chooses the colour
# of. The rim is therefore the bright cyan that reads on a dark disc, while the
# interface's accent is the darker blue that reads on white -- the same hue, each
# at the value its own background needs.
#
# Coordinates are in the 64-unit box of the page's favicon, so the application
# and the site wear the same face down to the proportions. Scale with
# ``value * size / MARK_BOX``.
# ---------------------------------------------------------------------------
MARK_BOX = 64.0
MARK_CENTRE = (32.0, 32.0)
MARK_DISC_R = 27.0
MARK_DISC_STROKE = 3.0
# Two clock hands, long then short, as ((x1, y1), (x2, y2)).
MARK_HANDS = (((32.0, 32.0), (32.0, 17.0)),
              ((32.0, 32.0), (44.0, 38.0)))
MARK_HAND_STROKE = 3.5
MARK_HUB_R = 3.0

# RGB, for the two drawing libraries.
MARK_DISC_RGB = (22, 26, 36)        # #161a24
MARK_EDGE_RGB = (90, 200, 255)      # #5ac8ff, bright enough for the dark disc
MARK_HAND_RGB = (240, 248, 255)     # #f0f8ff


def brand_path(name: str) -> Path:
    """Where a shipped logo file is, from source or from the bundle.

    Beside the font and the illustrations, under ``resources/``, for the same
    reason: it is payload the program reads, never something it writes. Not
    ``assets/`` -- that one is gitignored, so a logo put there would be missing
    from every clone and from every build.
    """
    return _font_dir().parent / "brand" / name


_MARK: dict[bool, QPixmap] = {}


def mark_pixmap(size: int = 256, *, square: bool = False) -> QPixmap:
    """The application's logo, at ``size``.

    Two cuts of the same picture, because two shapes are asked of it. The
    rounded tile is the icon everywhere an icon goes -- tray, taskbar, window
    headers -- and the square one is for callers that clip it themselves, where
    rounded corners would leave four transparent bites out of the shape.

    The painted mark below it is the fallback, not the subject. It was the whole
    story while the program had no artwork -- geometry rather than a file, so the
    tray, the two windows and the .ico could not drift apart -- and it stays as
    the answer to a missing file, which is a clone without the binary or a build
    that forgot to bundle it. A program whose icon is absent should look plain,
    not fail to start.

    Loaded once and scaled per caller: the file is 80 KB and decoding it for
    every header repaint would be a waste.
    """
    if square not in _MARK:
        name = ("flashwatch-256.png" if square
                else "flashwatch-round-256.png")
        path = brand_path(name)
        loaded = QPixmap(str(path)) if path.exists() else QPixmap()
        if loaded.isNull():
            log.warning("no logo at %s, drawing the fallback mark", path)
            loaded = _drawn_mark()
        _MARK[square] = loaded
    mark = _MARK[square]
    if size == mark.width():
        return mark
    return mark.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _drawn_mark() -> QPixmap:
    """The mark as geometry, for when the picture is not there.

    Drawn at 256 and left for Qt to downscale, rather than drawn at the size
    asked for: a 3-unit stroke on a 64-unit box is under one pixel at tray size,
    and rounding it up by hand gives a different shape at every size.
    """
    source = 256
    scale = source / MARK_BOX
    pixmap = QPixmap(source, source)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    cx, cy = (value * scale for value in MARK_CENTRE)
    radius = MARK_DISC_R * scale
    painter.setBrush(QColor(*MARK_DISC_RGB))
    painter.setPen(QPen(QColor(*MARK_EDGE_RGB), MARK_DISC_STROKE * scale))
    painter.drawEllipse(QPointF(cx, cy), radius, radius)

    hands = QPen(QColor(*MARK_HAND_RGB), MARK_HAND_STROKE * scale)
    hands.setCapStyle(Qt.RoundCap)
    painter.setPen(hands)
    for (x1, y1), (x2, y2) in MARK_HANDS:
        painter.drawLine(QPointF(x1 * scale, y1 * scale),
                         QPointF(x2 * scale, y2 * scale))

    hub = MARK_HUB_R * scale
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(*MARK_EDGE_RGB))
    painter.drawEllipse(QPointF(cx, cy), hub, hub)
    painter.end()
    return pixmap


# ---------------------------------------------------------------------------
# The control window
# ---------------------------------------------------------------------------
# Its own palette, and not a variant of the one above. The overlay's palette is
# chosen for reading numbers off a game at a glance; this one is a *desktop
# window*, drawn to `design/maquette/Flashwatch *.dc.html`, and every value below
# is the value in those files. Naming them here rather than inlining hex into the
# stylesheet is what makes the port a translation instead of an interpretation --
# the same argument `design/08-maquette-html.md` makes for the rest of the kit.
#
# The window used to be light. The maquettes are dark, and that is the right way
# round for what it sits next to: it is opened during a game, over a client that
# is nearly black, and a white sheet in that context is a flashbang.
MENU = {
    # Grounds, front to back: the window, the title bar, the side rail.
    "window": "#0a0d1a",
    "chrome": "#0d1120",
    "chrome_line": "#1a2036",
    "chrome_hover": "#151a2c",
    "close_hover": "#c0392b",
    "rail": "#0b0f1c",
    "edge": "#1b2038",             # the window's own hairline
    # Cards. Two grounds because the maquettes use two: the plain card, and the
    # tinted one that carries a heading and an illustration.
    "card": "#0e1226",
    "card_2": "#10142a",
    "card_edge": "#232941",
    "card_edge_2": "#262c4c",
    "hero_a": "#141034",
    "hero_b": "#12132e",
    "hero_c": "#101a33",
    "hero_edge": "#2b2f55",
    # Inset things: fields, read-only logs, the pasted line.
    "sunken": "#0b0f1e",
    "field": "#0e1226",
    "field_edge": "#262d49",
    "field_hover": "#3a4268",
    # The rounded square that carries a card's icon.
    "tile": "#2b1a63",
    "tile_edge": "#4b3a94",
    # Navigation.
    "nav_on": "#1a1440",
    "nav_on_edge": "#3a2c7a",
    "nav_hover": "#141a2e",
    "rule": "#232a44",
    # Ink, brightest first. The maquettes use four weights of white and two of
    # grey, and the difference between them is what ranks a card's own heading
    # against the sentence under it.
    "ink": "#ffffff",
    "ink_2": "#e4e8f5",
    "ink_3": "#c6ccdf",
    "ink_4": "#b6bdd3",
    "dim": "#9ba3bd",
    "dim_2": "#8b93ad",
    # The accent, at the values the maquettes actually use it at.
    "accent": "#8B5CF6",
    "accent_deep": "#7C3AED",
    "accent_btn": "#6D28D9",
    "accent_pale": "#c4b5fd",
    "accent_ink": "#f0eefc",
    "accent_wash": "#1b1440",
    "accent_wash_2": "#150f34",
    # States.
    "danger": "#F87171",
    "danger_wash": "rgba(193, 0, 0, 0.06)",
    "danger_edge": "#4a2130",
    "danger_hover": "#7a2b3c",
    "warn": "#E9A23B",
    "ok": "#34D399",
    "info": "#38BDF8",
    "gold": "#c9a227",
    # Controls.
    "track": "#2a3150",
    "ring_off": "#4a5175",
    "knob": "#ffffff",
}

# The maquettes' own face, embedded under SIL OFL, and already shipped for the
# setup guide. Loaded once, on first use, because a QFontDatabase call before the
# QApplication exists is ignored.
FONT_MENU = "Mulish"
_MENU_FAMILY: str | None = None


def _font_dir() -> Path:
    """Where the embedded fonts are, running from source or from the .exe.

    ``resources/`` rather than ``assets/``: ``assets/`` is what the program
    *writes* -- settings, the icon cache, the log -- and is in .gitignore for
    that reason, so a font put there would be missing from every clone. Read-only
    payload comes out of PyInstaller's bundle rather than from ``settings.ROOT``,
    which resolves next to the executable where the writable data lives.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "resources" / "fonts"
    return Path(__file__).resolve().parent.parent / "resources" / "fonts"


def art_path(name: str) -> Path:
    """Where a card's illustration is, from source or from the bundle.

    The only pictures in the program. They live beside the font, under
    ``resources/``, for the same reason: they are shipped, not written.
    """
    return _font_dir().parent / "art" / name


def menu_family() -> str:
    """Mulish, or whatever Windows has if the file is missing.

    The fallback is deliberate rather than fatal: a missing font file should make
    the window look ordinary, not stop it opening. Shared with the setup guide --
    one loader, so the two surfaces cannot end up wearing different faces.
    """
    global _MENU_FAMILY
    if _MENU_FAMILY is None:
        _MENU_FAMILY = "Segoe UI"
        path = _font_dir() / f"{FONT_MENU}.ttf"
        if path.exists():
            handle = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(handle)
            if families:
                _MENU_FAMILY = families[0]
            else:
                log.warning("could not load %s", path)
        else:
            log.warning("no interface font at %s", path)
    return _MENU_FAMILY


def control_qss(scale: float = 1.0, nav_padding: float = 18.0) -> str:
    """The window's stylesheet, built from :data:`MENU` at a given scale.

    A function rather than a constant, for two reasons. It names the font family,
    and the family is only knowable once a QApplication exists to load it -- read
    at import time it would always come out as the fallback. And every length in
    it is a maquette length **times the window's scale**: the window draws a
    fixed 1448 x 1086 canvas fitted to the screen, so a 10 px radius has to become
    8 px at 80% or the corners stop matching the rest of the drawing.

    What is *not* here is type size. Every piece of text in this window is set
    from the maquette that owns it -- 27 px on the home page's headline, 22 px on
    Affichage's card titles -- and those differ per page, so the sizes are applied
    per widget (see ``ui.py``'s ``font``) rather than guessed at from a role.

    Two Qt facts shape the rest, both from ``design/CONTRAINTES-QT.md``:
    ``box-shadow`` does not exist (the maquettes' ``inset 0 0 0 1px`` is a plain
    border), and neither does ``text-transform`` (anything upper-case is
    upper-cased in Python).
    """
    body = menu_family()

    def px(value: float) -> str:
        return f"{max(1, round(value * scale))}px"

    def raw(value: float) -> int:
        return max(1, round(value * scale))

    return f"""
/* ── grounds ───────────────────────────────────────────────────────────── */
QWidget {{
    background: transparent;
    color: {MENU["ink_3"]};
    font-family: "{body}", "Segoe UI", sans-serif;
}}
QWidget#Shell {{
    background: {MENU["window"]};
    border: 1px solid {MENU["edge"]};
}}
QToolTip {{
    background: {MENU["card"]};
    color: {MENU["ink_2"]};
    border: 1px solid {MENU["field_edge"]};
    padding: {px(6)} {px(9)};
}}

/* ── the title bar ─────────────────────────────────────────────────────── */
QWidget#TitleBar {{
    background: {MENU["chrome"]};
    border-bottom: 1px solid {MENU["chrome_line"]};
}}
QLabel#TitleText {{ color: {MENU["ink_2"]}; }}
QPushButton[role="chrome"] {{
    background: transparent;
    border: 0;
    border-radius: 0;
    color: {MENU["dim_2"]};
    padding: 0;
}}
QPushButton[role="chrome"]:hover {{ background: {MENU["chrome_hover"]}; }}
QPushButton[role="chrome_close"]:hover {{ background: {MENU["close_hover"]}; }}

/* ── the side rail ─────────────────────────────────────────────────────── */
QWidget#Rail {{
    background: {MENU["rail"]};
    border-right: 1px solid {MENU["chrome_line"]};
}}
QLabel#RailName {{ color: #f2f4fb; }}
QLabel#RailVersion {{ color: {MENU["accent"]}; }}
QLabel#RailTagline {{ color: {MENU["dim"]}; }}
QFrame#RailRule {{ background: {MENU["rule"]}; border: 0; }}
/* The one place a maquette number could not be kept: its rail buttons are
   `padding: 0 20px` inside a 205 px button, and "Quitter le programme" at 16 px
   with a 22 px icon does not fit that -- the HTML overflows its own rail, which
   a button cannot do. 12 px, and 15 px type, is what makes the sentence fit. */
QWidget#Rail QPushButton {{ padding: 0 {px(12)}; }}

/* The navigation. The maquette puts a 4 px violet bar down the left edge of the
   selected row; here it is that row's left border, which is the one way to get a
   bar flush to the edge of a rounded rectangle without a second widget. */
QPushButton[role="nav"] {{
    background: transparent;
    border: 1px solid transparent;
    border-left: {px(4)} solid transparent;
    border-radius: {px(10)};
    color: {MENU["dim_2"]};
    padding: 0 {px(nav_padding)};
    text-align: left;
}}
QPushButton[role="nav"]:hover {{ background: {MENU["nav_hover"]}; }}
QPushButton[role="nav"]:checked {{
    background: {MENU["nav_on"]};
    border: 1px solid {MENU["nav_on_edge"]};
    border-left: {px(4)} solid {MENU["accent"]};
    color: {MENU["ink"]};
}}

/* ── cards ─────────────────────────────────────────────────────────────── */
QFrame[role="card"] {{
    background: {MENU["card"]};
    border: 1px solid {MENU["card_edge"]};
    border-radius: {px(12)};
}}
QFrame[role="card_2"] {{
    background: {MENU["card_2"]};
    border: 1px solid {MENU["card_edge_2"]};
    border-radius: {px(12)};
}}
/* The home page's two grounds: the wide banner across the top, and the pair of
   panels under it, which the maquette tilts the other way. */
QFrame[role="hero"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0.18,
        stop:0 {MENU["hero_a"]}, stop:0.42 {MENU["hero_b"]},
        stop:1 {MENU["hero_c"]});
    border: 1px solid {MENU["hero_edge"]};
    border-radius: {px(14)};
}}
QFrame[role="hero_2"] {{
    background: qlineargradient(x1:0, y1:0, x2:0.7, y2:1,
        stop:0 #161135, stop:1 #0f1226);
    border: 1px solid {MENU["hero_edge"]};
    border-radius: {px(14)};
}}
QFrame[role="hero_3"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0.18,
        stop:0 {MENU["hero_a"]}, stop:0.55 {MENU["hero_b"]}, stop:1 #161a3a);
    border: 1px solid {MENU["hero_edge"]};
    border-radius: {px(14)};
}}
QFrame[role="inset"] {{
    background: rgba(9, 12, 28, 0.55);
    border: 1px solid {MENU["card_edge_2"]};
    border-radius: {px(12)};
}}
QFrame[role="sunken"] {{
    background: {MENU["sunken"]};
    border: 1px solid {MENU["card_edge"]};
    border-radius: {px(8)};
}}
QFrame[role="hr"] {{ background: {MENU["card_edge"]}; border: 0; }}
QFrame[role="hr_2"] {{ background: #242a48; border: 0; }}

/* ── type ──────────────────────────────────────────────────────────────── */
QLabel {{ background: transparent; color: {MENU["ink_3"]}; }}
QLabel[role="h1"], QLabel[role="h2"], QLabel[role="h3"] {{ color: {MENU["ink"]}; }}
QLabel[role="body"] {{ color: {MENU["ink_3"]}; }}
QLabel[role="hint"] {{ color: {MENU["ink_4"]}; }}
QLabel[role="dim"] {{ color: {MENU["dim"]}; }}
QLabel[role="eyebrow"] {{ color: {MENU["dim_2"]}; letter-spacing: {px(1.2)}; }}
QLabel[role="value"] {{ color: {MENU["ink_2"]}; }}
QLabel[role="value_warn"] {{ color: {MENU["warn"]}; }}
QLabel[role="value_off"] {{ color: {MENU["dim_2"]}; }}
QLabel[role="mono"] {{ color: {MENU["ink_3"]}; font-family: {FONT_MONO}; }}
QLabel[role="field_label"] {{ color: {MENU["ink_2"]}; }}

/* The state pill. Room on the left for the lit dot, which is painted rather than
   styled: QSS has no box-shadow to glow with and no pseudo-element to put it in. */
QLabel[role="pill"], QLabel[role="pill_ok"], QLabel[role="pill_warn"],
QLabel[role="pill_bad"] {{
    background: #0f1428;
    border: 1px solid {MENU["track"]};
    border-radius: {px(10)};
    color: {MENU["ink_2"]};
    letter-spacing: {px(0.6)};
    padding: 0 {px(22)} 0 {px(45)};
}}

/* ── buttons ───────────────────────────────────────────────────────────── */
QPushButton {{
    background: {MENU["sunken"]};
    border: 1px solid {MENU["field_edge"]};
    border-radius: {px(10)};
    color: {MENU["ink_2"]};
    padding: 0 {px(20)};
    text-align: center;
}}
QPushButton:hover {{ border-color: {MENU["field_hover"]}; }}
QPushButton:pressed {{ background: {MENU["nav_hover"]}; }}
QPushButton:disabled {{ color: {MENU["dim_2"]}; border-color: {MENU["card_edge"]}; }}
QPushButton[role="primary"] {{
    background: {MENU["accent_btn"]};
    border: 1px solid {MENU["accent_btn"]};
    color: #ffffff;
}}
QPushButton[role="primary"]:hover {{ background: {MENU["accent_deep"]}; }}
QPushButton[role="primary"]:disabled {{ background: #2a2350; border-color: #2a2350; }}
QPushButton[role="accent"] {{
    background: {MENU["accent_wash"]};
    border: 1px solid {MENU["accent_btn"]};
    color: {MENU["accent_ink"]};
}}
QPushButton[role="accent"]:hover {{ border-color: {MENU["accent"]}; }}
QPushButton[role="accent"]:checked {{
    background: {MENU["accent_btn"]};
    border-color: {MENU["accent_btn"]};
    color: #ffffff;
}}
QPushButton[role="ghost"] {{ background: #0d1224; color: {MENU["ink_3"]}; }}
QPushButton[role="ghost"]:checked {{
    background: {MENU["accent_wash_2"]};
    border-color: {MENU["accent_btn"]};
    color: {MENU["accent_ink"]};
}}
QPushButton[role="danger"] {{
    background: {MENU["danger_wash"]};
    border: 1px solid {MENU["danger_edge"]};
    color: {MENU["danger"]};
}}
QPushButton[role="danger"]:hover {{ border-color: {MENU["danger_hover"]}; }}
QPushButton[role="quiet"] {{
    background: transparent;
    border: 0;
    border-radius: {px(6)};
    color: #9aa2c0;
    padding: 0;
}}
QPushButton[role="quiet"]:hover {{ background: #151b31; color: {MENU["ink"]}; }}
QPushButton[role="link"] {{
    background: transparent;
    border: 0;
    color: {MENU["accent_pale"]};
    padding: 0;
    text-align: left;
}}
QPushButton[role="link"]:hover {{ color: {MENU["ink"]}; }}

/* ── fields ────────────────────────────────────────────────────────────── */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {MENU["sunken"]};
    border: 1px solid {MENU["field_edge"]};
    border-radius: {px(8)};
    color: {MENU["ink_2"]};
    padding: 0 {px(20)};
    selection-background-color: {MENU["accent_btn"]};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {MENU["field_hover"]};
}}
/* The chevrons and the steppers are painted by the widgets themselves (see
   ui.py): Qt's own arrows are style-drawn triangles that cannot be recoloured
   from here, and an `image:` would need a file on disk, which this program does
   not ship. So the sub-controls are blanked out and their room is reserved. */
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: 0;
    width: {px(44)};
}}
QComboBox::down-arrow, QSpinBox::up-arrow, QSpinBox::down-arrow,
QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {MENU["card"]};
    border: 1px solid {MENU["field_edge"]};
    border-radius: {px(8)};
    color: {MENU["ink_2"]};
    outline: 0;
    padding: {px(6)};
    selection-background-color: {MENU["nav_on"]};
    selection-color: {MENU["ink"]};
}}

/* ── the opacity slider ────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {MENU["track"]};
    border-radius: {px(3)};
    height: {px(5)};
}}
QSlider::sub-page:horizontal {{
    background: {MENU["accent"]};
    border-radius: {px(3)};
    height: {px(5)};
}}
QSlider::handle:horizontal {{
    background: {MENU["knob"]};
    border-radius: {px(9)};
    height: {px(18)};
    margin: -{px(7)} 0;
    width: {px(18)};
}}

/* ── read-only logs ────────────────────────────────────────────────────── */
QPlainTextEdit, QListWidget {{
    background: {MENU["sunken"]};
    border: 1px solid {MENU["card_edge"]};
    border-radius: {px(8)};
    color: #7e879f;
    font-family: {FONT_MONO};
    padding: {px(12)} {px(16)};
    selection-background-color: {MENU["accent_btn"]};
}}
QListWidget::item {{ padding: {px(2)} 0; }}
QListWidget::item:selected {{ background: {MENU["nav_on"]}; color: {MENU["ink"]}; }}

/* ── scrollbars ────────────────────────────────────────────────────────── */
QScrollArea {{ background: transparent; border: 0; }}
QScrollBar:vertical {{
    background: transparent;
    border: 0;
    margin: 0;
    width: {px(12)};
}}
QScrollBar::handle:vertical {{
    background: {MENU["field_edge"]};
    border-radius: {px(5)};
    margin: {px(2)};
    min-height: {raw(40)}px;
}}
QScrollBar::handle:vertical:hover {{ background: {MENU["field_hover"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; border: 0; height: {px(12)}; }}
QScrollBar::handle:horizontal {{
    background: {MENU["field_edge"]};
    border-radius: {px(5)};
    margin: {px(2)};
    min-width: {raw(40)}px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""
