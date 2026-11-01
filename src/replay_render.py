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


class OverlayRenderer:
    """Draw the overlay of a :class:`ReplaySession` into numbered PNGs."""

    def __init__(self, session: ReplaySession, out_dir: Path, *,
                 layout: str = "team", theme: str = "clean",
                 fps: float = DEFAULT_FPS, start: float = 0.0) -> None:
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
        self.count = 0

        session.settings.update({"overlay_layout": layout, "theme": theme})
        try:
            # What the app does once capture has started; without a network it
            # still draws, just without the icons it could not fetch.
            session.assets.download_icons()
        except Exception as exc:                      # noqa: BLE001
            log.warning("icon download failed (%s)", exc)

        self.overlay = Overlay(session.settings, session.assets)
        self.overlay.sync_layout()
        self._team = layout == LAYOUT_TEAM
        self.anchor = "top-right" if self._team else "top-left"
        size = self.overlay.size()
        self.width, self.height = size.width(), size.height()

    def render(self, t: float) -> Path:
        """Draw the overlay as it stands at video second ``t`` and save it."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QImage, QPainter

        timers = self.session.timer_manager
        self.overlay.set_timers(timers.snapshot())
        self.overlay.set_game_active(True)
        if self._team:
            self.overlay.set_team(timers.team())

        image = self.overlay.grab().toImage().convertToFormat(
            QImage.Format_ARGB32_Premultiplied)
        if image.width() != self.width or image.height() != self.height:
            canvas = QImage(self.width, self.height,
                            QImage.Format_ARGB32_Premultiplied)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            x = self.width - image.width() if self.anchor == "top-right" else 0
            painter.drawImage(QPoint(x, 0), image)
            painter.end()
            image = canvas

        index = int(round((t - self.start) * self.fps))
        path = self.dir / f"{index:06d}.png"
        if not image.save(str(path), "PNG"):
            raise OSError(f"could not write {path}")
        self.count += 1
        return path

    def write_manifest(self) -> Path:
        path = self.dir / "overlay.json"
        path.write_text(json.dumps({
            "fps": self.fps, "start": self.start, "count": self.count,
            "width": self.width, "height": self.height,
            "layout": self.layout, "theme": self.theme, "anchor": self.anchor,
        }, indent=2), "utf-8")
        return path

    def close(self) -> None:
        self.overlay.hide()
        self.overlay.deleteLater()


def run_replay(video: Path, out_dir: Path, *, fps: float = DEFAULT_FPS,
               start: float = 0.0, end: float | None = None,
               locale: str = "en_US", layout: str = "team", theme: str = "clean",
               render: bool = True) -> dict:
    """Replay ``video`` into ``out_dir``: events.json, and the overlay frames."""
    video, out_dir = Path(video), Path(out_dir)
    width, height, _source_fps, duration = video_info(video)
    session = ReplaySession(out_dir, locale=locale, width=width, height=height)
    renderer = None
    frames = 0
    try:
        if render:
            renderer = OverlayRenderer(session, out_dir, layout=layout,
                                       theme=theme, fps=fps, start=start)
        for t, frame in iter_video_frames(video, fps=fps, start=start, end=end):
            session.step(t, frame)
            if renderer is not None:
                renderer.render(t)
            frames += 1
        session.write(out_dir / "events.json", video=video, duration=duration,
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
