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
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
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
MIN_WIDTH, MIN_HEIGHT = 170, 60

# Default geometry for the bar layout: a wide, shallow strip at the top centre.
BAR_DEFAULT_WIDTH_FRACTION = 0.34
BAR_DEFAULT_HEIGHT = 78
BAR_DEFAULT_TOP = 6

# How much of the theme's panel opacity the bar actually uses. The bar sits over
# the game permanently, so it stays largely see-through rather than masking it.
BAR_PANEL_ALPHA = 0.42
BAR_IDLE_ALPHA = 0.18

# Fraction of the spell badge that overlaps the champion portrait. Small, so the
# portrait stays recognisable -- it is the thing you identify at a glance.
BADGE_OVERLAP = 0.26

THEMES: dict[str, dict[str, tuple[int, int, int, int]]] = {
    "dark": {
        "panel": (14, 16, 22, 205),
        "border": (70, 80, 100, 190),
        "title": (225, 232, 245, 255),
        "role": (140, 152, 175, 255),
        "name": (232, 238, 248, 255),
        "spell": (168, 180, 200, 255),
        "time": (240, 244, 252, 255),
        "soon": (255, 176, 74, 255),
        "ready": (110, 226, 142, 255),
        "row": (255, 255, 255, 14),
    },
    "light": {
        "panel": (246, 247, 250, 225),
        "border": (120, 130, 150, 200),
        "title": (26, 30, 40, 255),
        "role": (96, 106, 126, 255),
        "name": (20, 24, 34, 255),
        "spell": (78, 88, 108, 255),
        "time": (16, 20, 28, 255),
        "soon": (198, 106, 12, 255),
        "ready": (22, 138, 66, 255),
        "row": (0, 0, 0, 14),
    },
    "neon": {
        "panel": (8, 10, 24, 210),
        "border": (0, 214, 226, 200),
        "title": (0, 240, 255, 255),
        "role": (128, 148, 200, 255),
        "name": (226, 240, 255, 255),
        "spell": (0, 196, 214, 255),
        "time": (240, 250, 255, 255),
        "soon": (255, 138, 200, 255),
        "ready": (60, 255, 170, 255),
        "row": (0, 220, 255, 18),
    },
}

SOON_THRESHOLD = 30.0


class BarMarker(NamedTuple):
    """One cooldown placed on the bar's track.

    ``left``/``span`` delimit the slot the countdown text is centred in;
    ``rect`` is the portrait plus its spell badge, i.e. the box that must never
    meet another marker's.
    """

    timer: ActiveTimer
    left: int
    span: int
    icon_x: int
    icon_y: int
    overlap: int
    rect: QRect


def _colour(theme: dict, key: str) -> QColor:
    return QColor(*theme.get(key, (255, 255, 255, 255)))


class IconCache:
    """Loads and scales champion/spell icons once."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], QPixmap] = {}

    def get(self, path: Path | None, size: int) -> QPixmap | None:
        if path is None:
            return None
        key = (str(path), size)
        hit = self._cache.get(key)
        if hit is not None:
            return hit if not hit.isNull() else None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._cache[key] = pixmap
            return None
        scaled = pixmap.scaled(size, size, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        self._cache[key] = scaled
        return scaled

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
        self._drag_origin: QPoint | None = None
        self._resize_origin: tuple[QPoint, QSize] | None = None

        self.setWindowTitle("LoL Timers")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                    # keeps it out of the taskbar/alt-tab
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.restore_geometry()
        self.apply_lock(bool(self.settings.get("overlay_locked", True)))
        self.setWindowOpacity(float(self.settings.get("overlay_opacity", 0.92)))

        # Games reclaim topmost; re-assert ours on a slow timer.
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(TOPMOST_REFRESH_MS)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        self._topmost_timer.start()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def restore_geometry(self) -> None:
        if (self.settings.get("overlay_layout") == "bar"
                and not self.settings.get("bar_placed")):
            # First run in bar layout: a position saved for the vertical panel is
            # meaningless here, so centre it at the top instead.
            self.centre_at_top(save=True)
            return
        width = max(MIN_WIDTH, int(self.settings.get("overlay_width", 260)))
        height = max(MIN_HEIGHT, int(self.settings.get("overlay_height", 420)))
        x = int(self.settings.get("overlay_x", 40))
        y = int(self.settings.get("overlay_y", 120))
        self.setGeometry(x, y, width, height)
        self._ensure_on_screen()

    def centre_at_top(self, *, save: bool = True) -> None:
        """Put the bar in the middle of the top edge of the primary screen."""
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen()
        available = (screen.availableGeometry() if screen is not None
                     else self.geometry())
        width = max(MIN_WIDTH, int(available.width() * BAR_DEFAULT_WIDTH_FRACTION))
        height = BAR_DEFAULT_HEIGHT
        x = available.left() + (available.width() - width) // 2
        y = available.top() + BAR_DEFAULT_TOP
        self.setGeometry(x, y, width, height)
        if save:
            self.settings.set("bar_placed", True)
            self.save_geometry()

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

    def save_geometry(self) -> None:
        rect = self.geometry()
        self.settings.update({
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

    def should_be_visible(self) -> bool:
        """The show/hide rule, in one place.

        Outside a game the bar has nothing to display and would sit over the
        client or the desktop, so it stays away. Two exceptions keep it usable:
        while unlocked it must be visible to be moved, and if timers exist --
        the preview, or the moments right after a game ends -- there is
        something worth showing.
        """
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
        self.update()

    def set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.update()

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
    def paintEvent(self, _event) -> None:
        theme = THEMES.get(str(self.settings.get("theme", "dark")), THEMES["dark"])
        scale = max(0.6, min(2.0, float(self.settings.get("overlay_scale", 1.0))))
        locked = bool(self.settings.get("overlay_locked", True))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        if self.settings.get("overlay_layout") == "bar":
            self._paint_bar(painter, theme, scale, locked)
        else:
            self._paint_list(painter, theme, scale, locked)
        painter.end()

    # ------------------------------------------------------------------
    def _paint_bar(self, painter: QPainter, theme: dict, scale: float,
                   locked: bool) -> None:
        """Discreet top-centre track; each spell rides left to right.

        Position along the track is how much of the cooldown has elapsed, so a
        marker enters at the left the moment a spell is used and arrives at the
        right as it comes back up. That makes "who is nearly back" readable at a
        glance without reading any numbers.
        """
        idle = not self._timers
        show_idle = bool(self.settings.get("bar_show_when_idle", True))
        # At rest, draw the bare track and nothing else: enough to show the app
        # is running and where it sits, without a placeholder message over the
        # game. Fully invisible is opt-in. Unlocked always draws, so the bar can
        # be found and moved.
        if idle and locked and not show_idle:
            return

        icon_size = int(24 * scale)
        badge = int(14 * scale)
        pad = int(9 * scale)
        text_height = int(13 * scale)
        row_height = icon_size + text_height + int(5 * scale)

        # At rest the backing is drawn much fainter: enough to locate the bar and
        # confirm the app is running, without putting a solid box over the game.
        body = QRect(0, 0, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(body, 9.0 * scale, 9.0 * scale)
        panel = QColor(_colour(theme, "panel"))
        panel.setAlpha(int(panel.alpha()
                           * (BAR_IDLE_ALPHA if (idle and locked)
                              else BAR_PANEL_ALPHA)))
        painter.fillPath(path, panel)
        if not locked:
            painter.setPen(QPen(_colour(theme, "soon"), 2.0))
            painter.drawPath(path)

        track_left = pad + icon_size // 2
        track_right = self.width() - pad - icon_size // 2
        track_y = pad + int(4 * scale)
        if track_right <= track_left:
            return

        # The track itself, plus a tick at each end. Drawn as a dark hairline with
        # a lighter line over it, so it stays visible whether the game behind is
        # bright or dark -- a single mid-tone line disappears against mid tones.
        tick = int(3 * scale)
        width = max(1.0, 1.6 * scale)
        for offset, colour in ((1, QColor(0, 0, 0, 120)),
                               (0, _colour(theme, "border"))):
            pen = QPen(colour)
            pen.setWidthF(width)
            painter.setPen(pen)
            y = track_y + offset
            painter.drawLine(track_left, y, track_right, y)
            painter.drawLine(track_left, y - tick, track_left, y + tick)
            painter.drawLine(track_right, y - tick, track_right, y + tick)

        if idle:
            if not locked:
                painter.setFont(QFont("Segoe UI", int(7.5 * scale)))
                painter.setPen(_colour(theme, "role"))
                painter.drawText(
                    QRect(0, track_y + tick, self.width(), text_height * 2),
                    Qt.AlignCenter, tr("overlay.unlocked_hint"))
            self._paint_grip(painter, theme, locked)
            return

        time_font = QFont("Consolas", int(9 * scale), QFont.Bold)

        for marker in self._bar_markers(scale):
            timer = marker.timer
            left, span = marker.left, marker.span
            label = timer.display()
            self._paint_marker(painter, theme, timer, marker.icon_x,
                               marker.icon_y, icon_size, badge,
                               marker.overlap, scale)

            remaining = timer.remaining()
            if remaining <= 0:
                colour = _colour(theme, "ready")
            elif remaining <= SOON_THRESHOLD:
                colour = _colour(theme, "soon")
            else:
                colour = _colour(theme, "time")
            painter.setFont(time_font)
            text_rect = QRect(left, marker.icon_y + icon_size + int(1 * scale),
                              span, text_height)
            # Shadow first: with a see-through panel the countdown can otherwise
            # land on bright game art and become unreadable.
            painter.setPen(QColor(0, 0, 0, 190))
            painter.drawText(text_rect.translated(1, 1),
                             Qt.AlignHCenter | Qt.AlignVCenter, label)
            painter.setPen(colour)
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, label)

        self._paint_grip(painter, theme, locked)

    def _bar_markers(self, scale: float) -> list[BarMarker]:
        """Where each cooldown sits on the track, left to right.

        Separate from the painting so the placement can be checked without a
        screen: "no two markers on the same pixels" is a geometry property, and
        it is the one that decides whether a champion is visible at all.
        """
        if not self._timers:
            return []
        icon_size = int(24 * scale)
        badge = int(14 * scale)
        pad = int(9 * scale)
        gap = int(3 * scale)
        track_left = pad + icon_size // 2
        track_right = self.width() - pad - icon_size // 2
        if track_right <= track_left:
            return []
        icon_y = pad + int(4 * scale) + int(6 * scale)

        # The badge sits mostly outside the portrait, so a marker is wider than
        # the portrait alone. Spacing has to use the full width, or a badge
        # would end up over the next portrait.
        overlap = int(badge * BADGE_OVERLAP)
        marker_width = icon_size + badge - overlap

        metrics = QFontMetrics(QFont("Consolas", int(9 * scale), QFont.Bold))
        ordered = sorted(self._timers, key=self._progress)
        # Each marker owns a slot wide enough for both the portrait and the
        # countdown underneath it; keeping slots apart keeps both apart.
        spans = [max(marker_width, metrics.horizontalAdvance(timer.display()))
                 + int(6 * scale) for timer in ordered]
        # Two spells used in the same breath share a point on the track, so the
        # whole row is laid out at once rather than one marker at a time: the
        # exact pixel is not the readout, the countdown text is, and a few
        # pixels of drift costs nothing next to a hidden champion.
        targets = [int(track_left + (track_right - track_left)
                       * self._progress(timer)) - span // 2
                   for timer, span in zip(ordered, spans)]
        lefts = self._spread(spans, targets, pad // 2,
                             self.width() - pad // 2, gap)

        markers = []
        for timer, span, left in zip(ordered, spans, lefts):
            icon_x = left + (span - marker_width) // 2
            markers.append(BarMarker(
                timer=timer, left=left, span=span, icon_x=icon_x, icon_y=icon_y,
                overlap=overlap,
                rect=QRect(icon_x, icon_y, marker_width, icon_size)))
        return markers

    def _bar_marker_rects(self) -> list[QRect]:
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

    @staticmethod
    def _progress(timer: ActiveTimer) -> float:
        """How far through the cooldown, 0 at cast and 1 when ready."""
        if timer.duration <= 0:
            return 1.0
        elapsed = timer.duration - timer.remaining()
        return max(0.0, min(1.0, elapsed / timer.duration))

    def _paint_marker(self, painter: QPainter, theme: dict, timer: ActiveTimer,
                      icon_x: int, icon_y: int, icon_size: int, badge: int,
                      overlap: int, scale: float) -> None:
        """Champion portrait with the spell icon badged off its right edge."""
        champion_icon = self.icons.get(
            self.assets.icon_for_champion(timer.champion_id), icon_size)

        if champion_icon is not None:
            # Clip to a circle so the marker reads as a token on the track.
            clip = QPainterPath()
            clip.addEllipse(icon_x, icon_y, icon_size, icon_size)
            painter.save()
            painter.setClipPath(clip)
            painter.drawPixmap(icon_x, icon_y, champion_icon)
            painter.restore()
        else:
            painter.setBrush(_colour(theme, "row"))
            painter.setPen(QPen(_colour(theme, "border"), 1.0))
            painter.drawEllipse(icon_x, icon_y, icon_size, icon_size)
            painter.setFont(QFont("Segoe UI", int(7 * scale), QFont.Bold))
            painter.setPen(_colour(theme, "name"))
            painter.drawText(QRect(icon_x, icon_y, icon_size, icon_size),
                             Qt.AlignCenter, timer.champion_name[:2].upper())

        ring = QPen(_colour(theme, "ready" if timer.is_ready() else "border"))
        ring.setWidthF(max(1.0, 1.4 * scale))
        painter.setPen(ring)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(icon_x, icon_y, icon_size, icon_size)

        spell_icon = self.icons.get(self._spell_icon_path(timer), badge)
        if spell_icon is not None:
            # Clear of the portrait apart from a small overlap, so the champion
            # stays fully readable.
            bx = icon_x + icon_size - overlap
            by = icon_y + icon_size - badge
            # Opaque disc behind it: the panel is see-through, and the badge
            # needs to read against whatever the game is drawing.
            backing = QColor(_colour(theme, "panel"))
            backing.setAlpha(235)
            painter.setBrush(backing)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(bx - 1, by - 1, badge + 2, badge + 2)
            clip = QPainterPath()
            clip.addEllipse(bx, by, badge, badge)
            painter.save()
            painter.setClipPath(clip)
            painter.drawPixmap(bx, by, spell_icon)
            painter.restore()

    # ------------------------------------------------------------------
    def _paint_list(self, painter: QPainter, theme: dict, scale: float,
                    locked: bool) -> None:
        radius = 10.0 * scale
        body = QRect(0, 0, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        painter.fillPath(path, _colour(theme, "panel"))
        pen = QPen(_colour(theme, "border"))
        pen.setWidthF(1.4 if locked else 2.4)
        painter.setPen(pen)
        painter.drawPath(path)

        pad = int(10 * scale)
        y = pad

        title_font = QFont("Segoe UI", int(9 * scale), QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(_colour(theme, "title"))
        painter.drawText(QRect(pad, y, self.width() - pad * 2, int(18 * scale)),
                         Qt.AlignLeft | Qt.AlignVCenter, tr("overlay.enemy_spells"))
        if not locked:
            painter.setPen(_colour(theme, "soon"))
            painter.drawText(QRect(pad, y, self.width() - pad * 2, int(18 * scale)),
                             Qt.AlignRight | Qt.AlignVCenter, tr("overlay.unlocked"))
        y += int(20 * scale)

        if not self._timers:
            painter.setFont(QFont("Segoe UI", int(8 * scale)))
            painter.setPen(_colour(theme, "role"))
            message = self._status or tr("overlay.waiting")
            painter.drawText(QRect(pad, y, self.width() - pad * 2,
                                   self.height() - y - pad),
                             Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                             message)
            self._paint_grip(painter, theme, locked)
            return

        icon_size = int(26 * scale)
        spell_size = int(17 * scale)
        row_height = max(icon_size + int(8 * scale), int(34 * scale))
        name_font = QFont("Segoe UI", int(8.5 * scale), QFont.DemiBold)
        small_font = QFont("Segoe UI", int(7.5 * scale))
        time_font = QFont("Consolas", int(10.5 * scale), QFont.Bold)
        metrics = QFontMetrics(time_font)
        show_roles = bool(self.settings.get("sort_by_role"))
        current_role = None

        for timer in self._timers:
            if y + row_height > self.height() - pad:
                break

            if show_roles and timer.role and timer.role != current_role:
                current_role = timer.role
                painter.setFont(small_font)
                painter.setPen(_colour(theme, "role"))
                painter.drawText(QRect(pad, y, self.width() - pad * 2,
                                       int(14 * scale)),
                                 Qt.AlignLeft | Qt.AlignVCenter, timer.role)
                y += int(15 * scale)
                if y + row_height > self.height() - pad:
                    break

            row = QRect(pad // 2, y, self.width() - pad, row_height)
            row_path = QPainterPath()
            row_path.addRoundedRect(row, 6.0 * scale, 6.0 * scale)
            painter.fillPath(row_path, _colour(theme, "row"))

            x = pad
            champion_icon = self.icons.get(
                self.assets.icon_for_champion(timer.champion_id), icon_size)
            if champion_icon is not None:
                painter.drawPixmap(x, y + (row_height - icon_size) // 2,
                                   champion_icon)
            x += icon_size + int(6 * scale)

            spell_icon = self.icons.get(self._spell_icon_path(timer), spell_size)
            if spell_icon is not None:
                painter.drawPixmap(x, y + (row_height - spell_size) // 2,
                                   spell_icon)
            x += spell_size + int(6 * scale)

            remaining = timer.remaining()
            text = timer.display()
            if remaining <= 0:
                time_colour = _colour(theme, "ready")
            elif remaining <= SOON_THRESHOLD:
                time_colour = _colour(theme, "soon")
            else:
                time_colour = _colour(theme, "time")

            time_width = metrics.horizontalAdvance("READY") + int(6 * scale)
            text_width = max(10, self.width() - pad - time_width - x)

            painter.setFont(name_font)
            painter.setPen(_colour(theme, "name"))
            painter.drawText(QRect(x, y + int(3 * scale), text_width,
                                   int(15 * scale)),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(timer.champion_name,
                                                Qt.ElideRight, text_width))
            painter.setFont(small_font)
            painter.setPen(_colour(theme, "spell"))
            painter.drawText(QRect(x, y + int(16 * scale), text_width,
                                   int(13 * scale)),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(timer.spell_name,
                                                Qt.ElideRight, text_width))

            painter.setFont(time_font)
            painter.setPen(time_colour)
            painter.drawText(QRect(self.width() - pad - time_width, y,
                                   time_width, row_height),
                             Qt.AlignRight | Qt.AlignVCenter, text)

            y += row_height + int(3 * scale)

        self._paint_grip(painter, theme, locked)

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
        painter.setPen(QPen(_colour(theme, "border"), 1.6))
        grip = self._grip_rect()
        for offset in (3, 7, 11):
            painter.drawLine(grip.right() - offset, grip.bottom(),
                             grip.right(), grip.bottom() - offset)
