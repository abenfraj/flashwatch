"""Replay, drawn: the app's own overlay rendered for every sampled frame.

The generator lays these frames over the footage, so they come from the real
:class:`overlay.Overlay`, fed exactly what ``main._refresh_ui`` feeds it, painted
offscreen and saved with their alpha. Nothing on them is drawn by hand.

Every frame of one replay has the same size, and the overlay sits at the same
corner of it, so an overlay composited over a video never shifts between frames.
The team display is sized for five enemies from the start (see
``Overlay._team_shape``), which makes that the natural case; a display that does
grow is clipped to the first frame's canvas at its anchor corner rather than
allowed to move.

Qt is imported only when a renderer is built, so a replay that asks for events
alone never starts a GUI application.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from replay import DEFAULT_FPS, ReplaySession, iter_video_frames, video_info

log = logging.getLogger(__name__)

# Frames are painted at this many pixels per screen pixel. The generator enlarges
# the overlay into an inset several times its size in a game (the team display
# is about 110 px wide at 1080p and fills most of a 1080 px Short), and text and
# icons painted large stay sharp where a 1x frame scaled up would blur.
DEFAULT_PIXEL_RATIO = 4


class _VideoScreen:
    """The screen the overlay believes it is on: the size of the video.

    ``Overlay.place_default`` sizes the bar, the cards and the list from the
    screen it is on, as the app does on the player's monitor. The offscreen
    platform's own screen is an arbitrary 800x600, so the overlay is pointed at
    one the size of the recording instead.
    """

    def __init__(self, width: int, height: int) -> None:
        from PySide6.QtCore import QRect
        self._rect = QRect(0, 0, width, height)

    def availableGeometry(self):
        return self._rect

    def geometry(self):
        return self._rect


class OverlayRenderer:
    """Draw the overlay of a :class:`ReplaySession` into numbered PNGs."""

    def __init__(self, session: ReplaySession, out_dir: Path, *,
                 layout: str = "team", theme: str = "clean",
                 fps: float = DEFAULT_FPS, start: float = 0.0,
                 pixel_ratio: int = DEFAULT_PIXEL_RATIO) -> None:
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            raise RuntimeError("replay renders offscreen only: set "
                               "QT_QPA_PLATFORM=offscreen before importing Qt")
        os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
        from PySide6.QtWidgets import QApplication

        from overlay import LAYOUT_TEAM, Overlay

        self._app = QApplication.instance() or QApplication([])
        self.session = session
        self.dir = Path(out_dir) / "overlay"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.layout = layout
        self.theme = theme
        self.fps = fps
        self.start = start
        self.pixel_ratio = max(1, int(pixel_ratio))
        self.count = 0

        session.settings.update({"overlay_layout": layout, "theme": theme})
        try:
            # What the app does once capture has started; without a network it
            # still draws, just without the icons it could not fetch.
            session.assets.download_icons()
        except Exception as exc:                      # noqa: BLE001
            log.warning("icon download failed (%s)", exc)

        self.overlay = Overlay(session.settings, session.assets)
        _, _, video_width, video_height = session.worker.detector.state.window_rect
        screen = _VideoScreen(video_width, video_height)
        self.overlay.screen = lambda: screen
        self.overlay.sync_layout()
        self.overlay.place_default(save=False)
        self._team = layout == LAYOUT_TEAM
        self.anchor = "top-right" if self._team else "top-left"
        size = self.overlay.size()
        self.logical_width, self.logical_height = size.width(), size.height()
        self.width = self.logical_width * self.pixel_ratio
        self.height = self.logical_height * self.pixel_ratio

    def render(self, t: float) -> Path:
        """Draw the overlay as it stands at video second ``t`` and save it."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QImage, QPainter

        timers = self.session.timer_manager
        self.overlay.set_timers(timers.snapshot())
        self.overlay.set_game_active(True)
        if self._team:
            self.overlay.set_team(timers.team())

        image = self._paint()
        if image.width() != self.width or image.height() != self.height:
            drawn = (image.width(), image.height())
            canvas = QImage(self.width, self.height,
                            QImage.Format_ARGB32_Premultiplied)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            x = self.width - image.width() if self.anchor == "top-right" else 0
            painter.drawImage(QPoint(x, 0), image)
            painter.end()
            image = canvas
            log.warning("overlay at %.1fs is %dx%d, clipped to the %dx%d canvas",
                        t, *drawn, self.width, self.height)

        index = int(round((t - self.start) * self.fps))
        path = self.dir / f"{index:06d}.png"
        if not image.save(str(path), "PNG"):
            raise OSError(f"could not write {path}")
        self.count += 1
        return path

    def _paint(self):
        """The overlay painted at ``pixel_ratio``, on a transparent image.

        ``QWidget.render`` into an image that carries the ratio, rather than
        ``grab()``: the paint code draws in screen pixels and Qt scales it, so
        text and shapes are drawn at the higher resolution, not enlarged.
        """
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QImage, QPainter, QRegion
        from PySide6.QtWidgets import QWidget

        size = self.overlay.size()
        image = QImage(size.width() * self.pixel_ratio,
                       size.height() * self.pixel_ratio,
                       QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.pixel_ratio)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self.overlay.render(painter, QPoint(0, 0), QRegion(),
                            QWidget.RenderFlag.DrawChildren)
        painter.end()
        image.setDevicePixelRatio(1)
        return image

    def write_manifest(self) -> Path:
        path = self.dir / "overlay.json"
        path.write_text(json.dumps({
            "fps": self.fps, "start": self.start, "count": self.count,
            "width": self.width, "height": self.height,
            "pixel_ratio": self.pixel_ratio,
            "logical_width": self.logical_width,
            "logical_height": self.logical_height,
            "layout": self.layout, "theme": self.theme, "anchor": self.anchor,
        }, indent=2), "utf-8")
        return path

    def close(self) -> None:
        self.overlay.hide()
        self.overlay.deleteLater()


def run_replay(video: Path, out_dir: Path, *, fps: float = DEFAULT_FPS,
               start: float = 0.0, end: float | None = None,
               locale: str = "en_US", layout: str = "team", theme: str = "clean",
               render: bool = True, sidecar: dict | None = None,
               pixel_ratio: int = DEFAULT_PIXEL_RATIO) -> dict:
    """Replay ``video`` into ``out_dir``: events.json, and the overlay frames."""
    video, out_dir = Path(video), Path(out_dir)
    width, height, _source_fps, _estimate = video_info(video)
    session = ReplaySession(out_dir, locale=locale, width=width, height=height,
                            sidecar=sidecar)
    renderer = None
    frames = 0
    last = None
    try:
        if render:
            renderer = OverlayRenderer(session, out_dir, layout=layout,
                                       theme=theme, fps=fps, start=start,
                                       pixel_ratio=pixel_ratio)
        for t, frame in iter_video_frames(video, fps=fps, start=start, end=end):
            session.step(t, frame)
            if renderer is not None:
                renderer.render(t)
            frames += 1
            last = t
        # What the replay covered, measured: the container's own length is an
        # estimate that variable-rate and unindexed files get wrong.
        covered = 0.0 if last is None else round(last + 1.0 / fps, 6)
        session.write(out_dir / "events.json", video=video, duration=covered,
                      fps=fps)
        if renderer is not None:
            renderer.write_manifest()
    finally:
        if renderer is not None:
            renderer.close()
        session.close()
    region = session.region
    return {"events": len(session.records), "timers": len(session.timers),
            "frames": frames,
            "region": list(region.rect) if region is not None else None}
