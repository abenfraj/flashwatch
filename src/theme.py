"""The control window's look, taken from the download page.

The page and the application are the same product, so they are given the same
palette rather than two that merely resemble each other. Every colour below is
lifted verbatim from the ``:root`` block in ``site/index.html``; change one there
and change it here.

Deliberately independent of the overlay's ``theme`` setting. That setting styles
the bar drawn over the game, where light and neon exist because the game behind
it is bright or dark; the control window is a desktop window with the site's
identity, and following the overlay would give the product two different faces
depending on an unrelated preference.

Qt stylesheets are not CSS. Three differences bite:

* there are no variables, so the palette is interpolated into one f-string;
* ``font-family`` takes a list, but only Qt 6 picks the first *available* one --
  which is what lets the page's Google fonts be named first and fall back to
  what Windows actually ships;
* a rule with no explicit background makes the widget transparent, so container
  widgets are set explicitly rather than left to inherit.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# The palette, verbatim from the site.
# ---------------------------------------------------------------------------
FIELD = "#0a0c11"
FIELD_2 = "#0e1117"
PANEL = "#12161f"
PANEL_2 = "#0c0f15"
LINE = "rgba(96, 112, 142, 0.28)"
LINE_STRONG = "rgba(120, 140, 175, 0.5)"
INK = "#e9eef8"
INK_DIM = "#8d99b0"
INK_FAINT = "#5d6779"
SIGNAL = "#5ac8ff"
READY = "#6ee28e"
SOON = "#ffb04a"
DANGER = "#ff6b6b"

# Named first for anyone who has them, then what Windows actually ships.
FONT_BODY = '"Barlow", "Segoe UI", sans-serif'
FONT_DISPLAY = '"Chakra Petch", "Segoe UI Semibold", "Segoe UI", sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'

# Tinted fills. Written out rather than computed: a stylesheet is read far more
# often than it is changed, and the literal value is the thing you want to see.
SIGNAL_WASH = "rgba(90, 200, 255, 0.07)"
SIGNAL_FILL = "rgba(90, 200, 255, 0.14)"
SIGNAL_EDGE = "rgba(90, 200, 255, 0.30)"
HOVER_WASH = "rgba(255, 255, 255, 0.04)"
INPUT_BG = "rgba(255, 255, 255, 0.03)"


CONTROL_QSS = f"""
/* ── the window itself ─────────────────────────────────────────────────── */
QWidget {{
    background: {FIELD};
    color: {INK_DIM};
    font-family: {FONT_BODY};
    font-size: 13px;
}}
QToolTip {{
    background: {PANEL};
    color: {INK};
    border: 1px solid {LINE_STRONG};
    padding: 5px 8px;
}}

/* ── tabs: the page's own .win-tabs, which are mono, spaced and upper ──── */
QTabWidget::pane {{
    border: 1px solid {LINE};
    border-radius: 6px;
    background: {PANEL_2};
    top: -1px;
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    font-family: {FONT_MONO};
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: {INK_FAINT};
    background: transparent;
    border: 1px solid {LINE};
    border-bottom: 0;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 7px 13px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {INK_DIM}; }}
QTabBar::tab:selected {{
    color: {SIGNAL};
    border-color: {LINE_STRONG};
    background: {SIGNAL_WASH};
}}

/* ── grouped sections ──────────────────────────────────────────────────── */
QGroupBox {{
    font-family: {FONT_DISPLAY};
    font-size: 13px;
    font-weight: 600;
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 7px;
    margin-top: 16px;
    padding: 14px 13px 12px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {PANEL}, stop:1 {PANEL_2});
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 11px;
    padding: 0 6px;
    color: {SIGNAL};
    font-family: {FONT_MONO};
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    background: {FIELD};
}}

QLabel {{ background: transparent; color: {INK_DIM}; }}
QLabel[role="value"] {{ font-family: {FONT_MONO}; color: {INK}; }}
QLabel[role="hint"] {{ color: {INK_FAINT}; font-size: 12px; }}

/* ── buttons ───────────────────────────────────────────────────────────── */
QPushButton {{
    font-family: {FONT_MONO};
    font-size: 11px;
    letter-spacing: 0.5px;
    color: {INK};
    background: {INPUT_BG};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {HOVER_WASH}; border-color: {LINE_STRONG}; }}
QPushButton:pressed {{ background: {SIGNAL_WASH}; }}
QPushButton:checked {{
    color: {SIGNAL};
    border-color: {SIGNAL_EDGE};
    background: {SIGNAL_FILL};
}}
QPushButton:disabled {{ color: {INK_FAINT}; border-color: {LINE}; }}
QPushButton[role="primary"] {{
    color: {FIELD};
    background: {SIGNAL};
    border-color: {SIGNAL};
    font-weight: 700;
}}
QPushButton[role="primary"]:hover {{ background: #7ad4ff; }}
QPushButton[role="danger"]:hover {{ color: {DANGER}; border-color: {DANGER}; }}

/* ── checkboxes: the page draws a pill, so this draws a pill ───────────── */
QCheckBox {{ spacing: 9px; color: {INK_DIM}; background: transparent; }}
QCheckBox:hover {{ color: {INK}; }}
/* The knob is faked with a hard-stop gradient. Qt has no ::after to put a
   second shape inside a sub-control, and the alternative -- shipping four
   little PNGs -- is a lot of machinery for a switch. A hard stop under a
   border-radius reads as a knob sitting at one end, which is the whole
   affordance: the position says on or off, not just the colour. */
QCheckBox::indicator {{
    width: 32px;
    height: 17px;
    border-radius: 9px;
    border: 1px solid {LINE};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0    {INK_FAINT},
        stop:0.52 {INK_FAINT},
        stop:0.52 rgba(120, 140, 175, 0.18),
        stop:1    rgba(120, 140, 175, 0.18));
}}
QCheckBox::indicator:hover {{ border-color: {LINE_STRONG}; }}
QCheckBox::indicator:checked {{
    border-color: {SIGNAL_EDGE};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0    {SIGNAL_FILL},
        stop:0.48 {SIGNAL_FILL},
        stop:0.48 {SIGNAL},
        stop:1    {SIGNAL});
}}
QCheckBox::indicator:disabled {{ border-color: {LINE}; background: {INPUT_BG}; }}

/* ── inputs ────────────────────────────────────────────────────────────── */
QComboBox, QSpinBox, QDoubleSpinBox {{
    font-family: {FONT_MONO};
    font-size: 11px;
    color: {INK};
    background: {INPUT_BG};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 4px 9px;
    min-height: 19px;
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {LINE_STRONG};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {SIGNAL_EDGE};
}}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QComboBox::down-arrow {{
    /* Qt has no glyph of its own here; a small triangle drawn from a border is
       the standard trick and needs no asset shipped alongside. */
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {INK_DIM};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    color: {INK};
    border: 1px solid {LINE_STRONG};
    selection-background-color: {SIGNAL_FILL};
    selection-color: {SIGNAL};
    outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border-left: 1px solid {LINE};
    width: 14px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0; height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {INK_DIM};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0; height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {INK_DIM};
}}

/* ── slider: a hairline track with a signal-coloured handle ────────────── */
QSlider::groove:horizontal {{
    height: 2px;
    background: {LINE_STRONG};
    border-radius: 1px;
}}
QSlider::sub-page:horizontal {{ background: {SIGNAL}; border-radius: 1px; }}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 6px;
    background: {INK};
    border: 1px solid {FIELD};
}}
QSlider::handle:horizontal:hover {{ background: {SIGNAL}; }}

/* ── lists and the debug log ───────────────────────────────────────────── */
QListWidget, QPlainTextEdit {{
    font-family: {FONT_MONO};
    font-size: 11px;
    color: {INK_DIM};
    background: rgba(9, 11, 16, 0.66);
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 6px;
    selection-background-color: {SIGNAL_FILL};
    selection-color: {SIGNAL};
}}
QListWidget::item {{ padding: 3px 4px; border-radius: 3px; }}
QListWidget::item:hover {{ background: {HOVER_WASH}; }}
QListWidget::item:selected {{ background: {SIGNAL_FILL}; color: {SIGNAL}; }}

/* ── scrollbars: thin, and invisible until there is something to scroll ── */
QScrollBar:vertical {{
    background: transparent; width: 9px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(120, 140, 175, 0.3);
    border-radius: 4px;
    min-height: 26px;
}}
QScrollBar::handle:vertical:hover {{ background: {LINE_STRONG}; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: rgba(120, 140, 175, 0.3);
    border-radius: 4px;
    min-width: 26px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
