"""Test mode: place the OCR frame by hand and watch it read, live.

The automatic detector cannot be verified without a real game on screen, and
"Definir la zone manuellement" is a blind, one-shot rubber band: you draw a
rectangle and only find out later whether it was right. This is the other half
of that -- a frame that stays on screen, follows the mouse, feeds the capture
worker as it moves, and reports what came back out of the OCR.

Two design constraints drive the odd shape of this widget:

*The middle must stay empty.* Whatever the frame draws inside the region gets
captured by the very screenshot it is meant to help aim, and would then be fed
to the OCR. So the window is a **ring**: it is inflated past the region on all
sides, and every pixel it paints sits outside the rectangle actually captured.
The interior is cut out with :meth:`QWidget.setMask`, which also means clicks in
the middle reach the game -- the user can keep playing while the frame is up.

*Coordinates are physical, not logical.* The rest of the pipeline (win32 window
rects, mss captures) works in real device pixels, while Qt geometry is in
logical ones; on a 125%/150% display those differ. Rather than converting back
and forth and hoping, the frame positions itself through ``SetWindowPos`` and
reads itself back through ``GetWindowRect``, both physical, so what the user
sees is exactly what gets grabbed. Without pywin32 it falls back to Qt geometry
scaled by the device pixel ratio, which is correct at 100%.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QPainter, QPen,
                           QRegion)
from PySide6.QtWidgets import QWidget

from chat_detector import ChatRegion
from i18n import tr
from message_parser import parse_clock

log = logging.getLogger(__name__)

try:
    import win32api
    import win32con
    import win32gui
    HAVE_WIN32 = True
except ImportError:                                   # pragma: no cover
    HAVE_WIN32 = False

# Ring thickness, in logical pixels. The sides are only as wide as a grab
# handle needs; the top and bottom carry the readouts.
MARGIN = 16
HEADER = 30
FOOTER = 52

# How close to an outer edge a press counts as "resize this edge".
EDGE_GRAB = 14

# Floor on the captured area, per zone: see MIN_REGION below. A zero-sized
# region would make mss raise, and each zone has its own sensible smallest shape.

# Dragging emits a region a few hundred times; the worker only needs the latest.
# Long enough to coalesce a drag, short enough that the OCR result feels like a
# response to the movement.
APPLY_DEBOUNCE_MS = 180

# Keyboard nudge, in physical pixels.
NUDGE = 1
NUDGE_FAST = 10

PANEL = QColor(12, 14, 20, 232)
BORDER_IDLE = QColor(90, 200, 255)
BORDER_READING = QColor(110, 226, 142)
BORDER_EXPLORING = QColor(255, 176, 74)
TEXT = QColor(232, 238, 248)
TEXT_DIM = QColor(150, 162, 184)
CHAT_TICK = QColor(110, 226, 142)
OTHER_TICK = QColor(120, 132, 152)
BUTTON = QColor(38, 44, 58, 240)
BUTTON_OK = QColor(30, 96, 60, 240)


ZONE_CHAT = "chat"
ZONE_CLOCK = "clock"
ZONE_SCOREBOARD = "scoreboard"
ZONE_LOADING = "loading"
ZONES = (ZONE_CHAT, ZONE_CLOCK, ZONE_SCOREBOARD, ZONE_LOADING)

# Smallest sensible rectangle per zone, in physical pixels. The chat needs room
# for several lines; the clock is five glyphs and forcing a chat-sized box around
# it would drag in the minimap and the scoreboard button.
#
# The two team areas are shaped like what they hold: the scoreboard's enemy
# portraits are a narrow column of five, the loading screen's cards a wide row of
# five. Both are cut into five equal cells, so a frame that is the wrong way round
# would put every lane in the wrong cell -- hence minimums that make the intended
# shape the obvious one.
MIN_REGION = {
    ZONE_CHAT: (120, 48),
    ZONE_CLOCK: (56, 18),
    ZONE_SCOREBOARD: (48, 120),
    ZONE_LOADING: (240, 60),
}


class ZoneFrame(QWidget):
    """Draggable, resizable frame delimiting one captured area.

    Emits :attr:`region_changed` while it is being moved so the caller can point
    the capture worker at the new rectangle immediately; :attr:`applied` and
    :attr:`cancelled` end the test mode.

    The same frame serves every area -- chat, game clock, loading screen,
    scoreboard -- and ``zone`` decides what it is called and what its readout
    means. Sharing the widget is what keeps the fiddly part (physical pixels, the
    hollow middle, the edge grabbing) in one place.
    """

    region_changed = Signal(object)     # ChatRegion
    applied = Signal(object)            # ChatRegion
    cancelled = Signal()
    closed = Signal()                   # always last, whichever way it ended

    def __init__(self, zone: str = ZONE_CHAT) -> None:
        super().__init__(None)
        self.zone = zone if zone in ZONES else ZONE_CHAT
        self.setWindowTitle(tr("zone.title"))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # Unlike the timer overlay this one *wants* focus: the arrow keys are the
        # only way to place the frame to the pixel.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self._drag_mode = ""
        self._drag_cursor = QPoint()
        self._drag_rect = (0, 0, 0, 0)
        self._rows: list[tuple[tuple[int, int, int, int], str, bool]] = []
        self._exploring = False
        self._ocr_note = ""
        self._last_chat = ""
        # For the clock zone: the value parsed out of what was read, or "".
        self._clock_text = ""
        # For the two team zones: the lanes the reader recognised, or "".
        self._role_summary = ""
        self._button_apply = QRect()
        self._button_cancel = QRect()

        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(APPLY_DEBOUNCE_MS)
        self._emit_timer.timeout.connect(self._emit_region)

    # ------------------------------------------------------------------
    # Physical <-> logical geometry
    # ------------------------------------------------------------------
    @property
    def _ratio(self) -> float:
        try:
            return float(self.devicePixelRatioF()) or 1.0
        except Exception:                             # noqa: BLE001
            return 1.0

    def _insets(self) -> tuple[int, int, int]:
        """Ring thickness in *physical* pixels: (side, header, footer)."""
        ratio = self._ratio
        return (int(round(MARGIN * ratio)), int(round(HEADER * ratio)),
                int(round(FOOTER * ratio)))

    def _window_rect(self) -> tuple[int, int, int, int]:
        """Outer window rectangle in physical screen pixels."""
        if HAVE_WIN32 and self.winId():
            try:
                left, top, right, bottom = win32gui.GetWindowRect(int(self.winId()))
                return (left, top, right - left, bottom - top)
            except Exception as exc:                  # noqa: BLE001
                log.debug("GetWindowRect failed (%s)", exc)
        ratio = self._ratio
        geometry = self.geometry()
        return (int(round(geometry.x() * ratio)), int(round(geometry.y() * ratio)),
                int(round(geometry.width() * ratio)),
                int(round(geometry.height() * ratio)))

    def _set_window_rect(self, x: int, y: int, width: int, height: int) -> None:
        if HAVE_WIN32 and self.winId():
            try:
                win32gui.SetWindowPos(
                    int(self.winId()), win32con.HWND_TOPMOST, int(x), int(y),
                    int(width), int(height), win32con.SWP_NOACTIVATE)
                return
            except Exception as exc:                  # noqa: BLE001
                log.debug("SetWindowPos failed (%s)", exc)
        ratio = self._ratio
        self.setGeometry(int(round(x / ratio)), int(round(y / ratio)),
                         int(round(width / ratio)), int(round(height / ratio)))

    # ------------------------------------------------------------------
    # The region itself
    # ------------------------------------------------------------------
    def _min_region(self) -> tuple[int, int]:
        return MIN_REGION.get(self.zone, MIN_REGION[ZONE_CHAT])

    def region_rect(self) -> tuple[int, int, int, int]:
        """The captured rectangle: the hole in the middle of the frame."""
        side, header, footer = self._insets()
        x, y, width, height = self._window_rect()
        return (x + side, y + header,
                max(1, width - 2 * side), max(1, height - header - footer))

    def region(self) -> ChatRegion:
        x, y, width, height = self.region_rect()
        return ChatRegion(x=x, y=y, width=width, height=height,
                          source="manual", confirmed=True)

    def set_region(self, region: ChatRegion | tuple[int, int, int, int]) -> None:
        """Place the frame so its hole lands exactly on ``region``."""
        if isinstance(region, ChatRegion):
            rect = region.rect
        else:
            rect = tuple(int(v) for v in region)
        x, y, width, height = rect
        min_w, min_h = self._min_region()
        width = max(min_w, width)
        height = max(min_h, height)
        side, header, footer = self._insets()
        self._set_window_rect(x - side, y - header,
                              width + 2 * side, height + header + footer)
        self.update()

    def start(self, region: ChatRegion | tuple[int, int, int, int]) -> None:
        self.show()
        # winId only exists once shown, and the physical path needs it.
        self.set_region(region)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)

    # ------------------------------------------------------------------
    # Live feedback from the capture worker
    # ------------------------------------------------------------------
    def set_feedback(self, rows, *, exploring: bool, note: str = "",
                     roles: str = "") -> None:
        """Show what the last OCR pass found inside the frame.

        ``rows`` is the pipeline's ``(rect, text, is_chat_line)`` list, in screen
        coordinates. Only the vertical position is drawn -- as ticks in the left
        margin -- because anything drawn inside the hole would end up in the next
        screenshot.
        """
        self._rows = list(rows or [])
        self._exploring = exploring
        self._ocr_note = note
        self._role_summary = roles
        if self.zone == ZONE_CLOCK:
            clock = parse_clock(" ".join(text for _r, text, _c in self._rows))
            self._clock_text = ("" if clock is None
                               else f"{int(clock) // 60}:{int(clock) % 60:02d}")
        for _rect, text, is_chat in reversed(self._rows):
            if is_chat:
                self._last_chat = text
                break
        self.update()

    # ------------------------------------------------------------------
    # Mask: keep the middle out of the window entirely
    # ------------------------------------------------------------------
    def _hole(self) -> QRect:
        return QRect(MARGIN, HEADER, max(1, self.width() - 2 * MARGIN),
                     max(1, self.height() - HEADER - FOOTER))

    def _apply_mask(self) -> None:
        self.setMask(QRegion(self.rect()).subtracted(QRegion(self._hole())))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_mask()

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------
    def _hit_test(self, pos: QPoint) -> str:
        left = pos.x() <= EDGE_GRAB
        right = pos.x() >= self.width() - EDGE_GRAB
        top = pos.y() <= EDGE_GRAB
        bottom = pos.y() >= self.height() - EDGE_GRAB
        vertical = "top" if top else ("bottom" if bottom else "")
        horizontal = "left" if left else ("right" if right else "")
        return (vertical + horizontal) or "move"

    _CURSORS = {
        "move": Qt.SizeAllCursor,
        "left": Qt.SizeHorCursor, "right": Qt.SizeHorCursor,
        "top": Qt.SizeVerCursor, "bottom": Qt.SizeVerCursor,
        "topleft": Qt.SizeFDiagCursor, "bottomright": Qt.SizeFDiagCursor,
        "topright": Qt.SizeBDiagCursor, "bottomleft": Qt.SizeBDiagCursor,
    }

    @staticmethod
    def _cursor_position() -> QPoint:
        """Pointer position in physical pixels."""
        if HAVE_WIN32:
            try:
                x, y = win32api.GetCursorPos()
                return QPoint(int(x), int(y))
            except Exception:                         # noqa: BLE001
                pass
        return QCursor.pos()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        if self._button_apply.contains(pos):
            self._on_apply()
            return
        if self._button_cancel.contains(pos):
            self.cancelled.emit()
            self.close()
            return
        self._drag_mode = self._hit_test(pos)
        self._drag_cursor = self._cursor_position()
        self._drag_rect = self._window_rect()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag_mode:
            pos = event.position().toPoint()
            if (self._button_apply.contains(pos)
                    or self._button_cancel.contains(pos)):
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(self._CURSORS.get(self._hit_test(pos),
                                                 Qt.ArrowCursor))
            return

        cursor = self._cursor_position()
        dx = cursor.x() - self._drag_cursor.x()
        dy = cursor.y() - self._drag_cursor.y()
        x, y, width, height = self._drag_rect
        side, header, footer = self._insets()
        floor_w, floor_h = self._min_region()
        min_w = floor_w + 2 * side
        min_h = floor_h + header + footer

        if self._drag_mode == "move":
            x, y = x + dx, y + dy
        else:
            if "left" in self._drag_mode:
                dx = min(dx, width - min_w)
                x, width = x + dx, width - dx
            if "right" in self._drag_mode:
                width = max(min_w, width + dx)
            if "top" in self._drag_mode:
                dy = min(dy, height - min_h)
                y, height = y + dy, height - dy
            if "bottom" in self._drag_mode:
                height = max(min_h, height + dy)

        self._set_window_rect(x, y, max(min_w, width), max(min_h, height))
        self._emit_timer.start()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if not self._drag_mode:
            return
        self._drag_mode = ""
        # Fire immediately on release rather than waiting out the debounce: this
        # is the moment the user is looking for a result.
        self._emit_timer.stop()
        self._emit_region()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._on_apply()
            return

        step = NUDGE_FAST if event.modifiers() & Qt.ShiftModifier else NUDGE
        step = int(round(step * self._ratio))
        # Ctrl turns the arrows into a resize of the bottom-right corner, which
        # keeps the top-left anchored where the user placed it.
        resizing = bool(event.modifiers() & Qt.ControlModifier)
        x, y, width, height = self._window_rect()
        side, header, footer = self._insets()
        floor_w, floor_h = self._min_region()
        min_w, min_h = floor_w + 2 * side, floor_h + header + footer

        deltas = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
                  Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if key not in deltas:
            super().keyPressEvent(event)
            return
        dx, dy = deltas[key]
        if resizing:
            width, height = max(min_w, width + dx), max(min_h, height + dy)
        else:
            x, y = x + dx, y + dy
        self._set_window_rect(x, y, width, height)
        self._emit_timer.start()
        self.update()

    # ------------------------------------------------------------------
    def _emit_region(self) -> None:
        self.region_changed.emit(self.region())

    def _on_apply(self) -> None:
        self._emit_timer.stop()
        region = self.region()
        self.applied.emit(region)
        self.close()

    def closeEvent(self, event) -> None:
        self._emit_timer.stop()
        super().closeEvent(event)
        self.closed.emit()

    # ------------------------------------------------------------------
    # Painting -- everything here lands on the ring, never inside the hole
    # ------------------------------------------------------------------
    def _border_colour(self) -> QColor:
        if self._exploring:
            return BORDER_EXPLORING
        if any(is_chat for _rect, _text, is_chat in self._rows):
            return BORDER_READING
        return BORDER_IDLE

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # The mask clips this to the ring, so a full-rect fill paints the frame
        # and leaves the captured area untouched.
        painter.fillRect(self.rect(), PANEL)

        hole = self._hole()
        colour = self._border_colour()
        painter.setPen(QPen(colour, 2))
        painter.drawRect(hole.adjusted(-1, -1, 0, 0))
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(), 90), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        self._paint_handles(painter, colour)
        self._paint_header(painter)
        self._paint_row_ticks(painter, hole)
        self._paint_footer(painter)
        painter.end()

    def _paint_handles(self, painter: QPainter, colour: QColor) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        size = 8
        rect = self.rect().adjusted(0, 0, -1, -1)
        xs = (rect.left(), rect.center().x() - size // 2, rect.right() - size)
        ys = (rect.top(), rect.center().y() - size // 2, rect.bottom() - size)
        for row, y in enumerate(ys):
            for column, x in enumerate(xs):
                if row == 1 and column == 1:
                    continue
                painter.drawRect(QRect(x, y, size, size))
        painter.setBrush(Qt.NoBrush)

    def _paint_header(self, painter: QPainter) -> None:
        x, y, width, height = self.region_rect()
        # Only the chat area is searched for automatically; the other two are
        # wherever the user puts them, so "searching" would be a lie there.
        state = (tr("zone.searching" if self._exploring else "zone.fixed")
                 if self.zone == ZONE_CHAT else tr(f"zone.name_{self.zone}"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.setPen(TEXT)
        painter.drawText(QRect(MARGIN, 4, self.width() - 2 * MARGIN, HEADER - 8),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         tr("zone.header", width=width, height=height, x=x, y=y,
                            state=state))
        if self._ocr_note:
            painter.setPen(TEXT_DIM)
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(QRect(MARGIN, 4, self.width() - 2 * MARGIN, HEADER - 8),
                             Qt.AlignRight | Qt.AlignVCenter, self._ocr_note)

    def _paint_row_ticks(self, painter: QPainter, hole: QRect) -> None:
        """Mark, in the left margin, where each recognised row sits.

        The rows themselves cannot be outlined -- that ink would be inside the
        captured area -- but their heights are what tells the user whether the
        frame is too short or catching the scoreboard instead of the chat.
        """
        if not self._rows:
            return
        region_x, region_y, _w, region_h = self.region_rect()
        ratio = self._ratio
        for (rx, ry, _rw, rh), _text, is_chat in self._rows:
            top = hole.top() + int((ry - region_y) / ratio)
            bottom = hole.top() + int((ry - region_y + rh) / ratio)
            top = max(hole.top(), min(hole.bottom(), top))
            bottom = max(hole.top(), min(hole.bottom(), bottom))
            if bottom - top < 2:
                bottom = top + 2
            painter.fillRect(QRect(3, top, MARGIN - 6, bottom - top),
                             CHAT_TICK if is_chat else OTHER_TICK)

    def _readout(self) -> tuple[str, bool, str]:
        """What this zone found: ``(summary, is_good, detail)``.

        Each zone is judged on what it is *for*. Counting rows tells you nothing
        about the clock -- five glyphs are one row whether they read "12:34" or
        "l2;3A" -- so there the summary is the parsed value or nothing.
        """
        if self.zone == ZONE_CLOCK:
            if self._clock_text:
                return (tr("zone.clock_read", value=self._clock_text), True,
                        tr("zone.clock_hint"))
            return tr("zone.clock_unreadable"), False, tr("zone.clock_hint")

        if self.zone in (ZONE_SCOREBOARD, ZONE_LOADING):
            # Judged on the lanes it produced, not on the text it saw. The
            # scoreboard has no champion names in it to read at all -- its
            # portraits are matched against the cached icons -- so counting rows
            # there would report success while nothing was recognised.
            hint = tr(f"zone.{self.zone}_hint")
            if self._role_summary:
                return tr("zone.roles_read", roles=self._role_summary), True, hint
            return tr("zone.roles_none"), False, hint

        chat_rows = sum(1 for _r, _t, is_chat in self._rows if is_chat)
        # Labelled as the *last* line rather than the current one: it is kept on
        # screen after the rows scroll away, so without the label a stale line
        # next to a "0 reconnue(s)" count reads as a contradiction.
        detail = (tr("zone.last_chat", line=self._last_chat) if self._last_chat
                  else tr("zone.no_chat"))
        return (tr("zone.rows", rows=len(self._rows), chat=chat_rows),
                bool(chat_rows), detail)

    def _paint_footer(self, painter: QPainter) -> None:
        top = self.height() - FOOTER
        summary, good, last = self._readout()
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(CHAT_TICK if good else TEXT_DIM)
        painter.drawText(QRect(MARGIN, top + 3, self.width() - 2 * MARGIN, 14),
                         Qt.AlignLeft | Qt.AlignVCenter, summary)

        painter.setPen(TEXT_DIM)
        metrics = QFontMetrics(painter.font())
        available = self.width() - 2 * MARGIN - 190
        painter.drawText(QRect(MARGIN, top + 18, max(40, available), 14),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(last, Qt.ElideRight, max(40, available)))

        painter.setPen(TEXT_DIM)
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRect(MARGIN, top + 33, self.width() - 2 * MARGIN, 14),
                         Qt.AlignLeft | Qt.AlignVCenter, tr("zone.keys"))

        self._paint_buttons(painter, top)

    def _paint_buttons(self, painter: QPainter, top: int) -> None:
        width, height = 84, 22
        right = self.width() - MARGIN
        self._button_apply = QRect(right - width, top + 6, width, height)
        self._button_cancel = QRect(right - 2 * width - 8, top + 6, width, height)
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        for rect, label, background in (
                (self._button_apply, tr("zone.apply"), BUTTON_OK),
                (self._button_cancel, tr("zone.cancel"), BUTTON)):
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(TEXT)
            painter.drawText(rect, Qt.AlignCenter, label)
