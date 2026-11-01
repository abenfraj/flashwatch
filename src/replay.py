"""Replay: Flashwatch's reading chain, run on a recorded game.

The video generator shows Flashwatch at work over real footage, and what it
shows has to be what the program *would have shown* in that game -- not a
reconstruction of it. So nothing here re-reads chat or re-times spells. A frame
from the video goes to the same :class:`ocr.CaptureWorker` the app runs, through
the two seams the tests already use (the detector and the grab), and the worker's
results go to the same :class:`TimerManager` the way ``main._drain_results``
forwards them. Region finding, the enemy-colour check, deduplication and the
priming pass all apply exactly as in a game: a line on screen from the first
frame of a recording is history and starts no timer, as it would if the app were
launched mid-game.

Time is the one thing that differs. A recording is read as fast as the machine
can manage, so the session drives :mod:`clock` from the video's own seconds --
"how long ago was that Flash" is answered in the game's time, not the replay's.
"""

from __future__ import annotations

import json
import logging
import queue
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

import clock
from chat_detector import ChatRegion
from game_detector import GameState
from message_parser import MessageParser
from ocr import CaptureWorker
from riot_assets import RiotAssets
from settings import Settings
from timer_manager import TimerManager

log = logging.getLogger(__name__)

# The app captures every 200 ms; replay samples at the same rate by default so
# every throttle in the worker sees the cadence it was tuned for.
DEFAULT_FPS = 5.0

# Where video second 0 sits on the clock. Not zero, so that nothing measured
# against a zero-initialised field ("last seen at 0") looks recent by accident.
CLOCK_BASE = 10_000.0


class ReplayInputError(Exception):
    """A video, sidecar or output folder replay cannot work with."""


@dataclass
class ReplayRecord:
    """One line the chain recognised, and when in the video it did."""
    t: float
    champion_id: str
    champion_name: str
    spell_key: str
    kind: str
    raw_line: str
    certain: bool
    source: str
    game_time: int | None
    remaining_seconds: int | None
    # Read in the pass that first found the chat. The line may predate the
    # recording -- the screen cannot say -- so the generator does not present it
    # as a fresh ping. With a chat area given in a sidecar, nothing is first_read.
    first_read: bool = False


@dataclass
class TimerRecord:
    """A timer the manager started, in video seconds."""
    t: float
    champion_id: str
    spell_key: str
    duration: float
    ready_t: float
    uncertain: bool
    first_read: bool = False


def _open(path: Path) -> cv2.VideoCapture:
    if not path.is_file():
        raise ReplayInputError(f"video not found: {path}")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened() or capture.get(cv2.CAP_PROP_FPS) <= 0:
        capture.release()
        raise ReplayInputError(f"cannot read video: {path}")
    return capture


def video_info(path: Path) -> tuple[int, int, float, float]:
    """``(width, height, fps, duration_seconds)`` of a video, or ReplayInputError."""
    capture = _open(Path(path))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        capture.release()
    if width <= 0 or height <= 0:
        raise ReplayInputError(f"cannot read video: {path}")
    return width, height, fps, frames / fps


def iter_video_frames(path: Path, fps: float = DEFAULT_FPS, start: float = 0.0,
                      end: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """Yield ``(video_seconds, frame_bgr)`` every ``1/fps`` seconds.

    Frames are decoded in order and each sample time gets the frame nearest to
    it, so only one frame is ever held: a thirty-minute VOD costs no more memory
    than a ten-second clip.
    """
    capture = _open(Path(path))
    try:
        source_fps = capture.get(cv2.CAP_PROP_FPS)
        index = int(start * source_fps)
        if index > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        half = 0.5 / source_fps
        step = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                return
            at = index / source_fps
            index += 1
            while True:
                t = start + step / fps
                if end is not None and t >= end - 1e-9:
                    return
                if t > at + half:
                    break
                if t >= at - half:
                    yield round(t, 6), frame
                step += 1
    finally:
        capture.release()


class _ReplayDetector:
    """The game is always on screen; the first poll is the start of a session."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self._started = False

    def poll(self) -> tuple[GameState, bool]:
        started, self._started = not self._started, True
        return self.state, started


class ReplaySession:
    """The app's capture worker and timer manager, fed one video frame at a time."""

    def __init__(self, out_dir: Path, *, locale: str = "en_US", width: int,
                 height: int) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._now = CLOCK_BASE
        # Before anything is built: the worker and the manager stamp fields at
        # construction, and those stamps must be on the video's clock.
        clock.use(lambda: self._now)

        self.settings = Settings(self.out_dir / "settings.json")
        # The videos never show ultimates; see the generator's content rules.
        self.settings.update({"track_ultimates": False, "locale": locale})
        self.assets = RiotAssets(locale)
        self.assets.bootstrap()
        self.parser = MessageParser(self.assets)
        self.timer_manager = TimerManager(self.assets, self.settings)

        self._results: queue.Queue = queue.Queue()
        self.worker = CaptureWorker(self.settings, self.parser, self._results)
        self.worker.detector = _ReplayDetector(GameState(
            in_game=True, client_running=True, hwnd=1,
            window_rect=(0, 0, width, height), session_id="replay",
            foreground=True))
        self.worker._sct = object()
        self.worker._grab = self._grab
        self.worker.engine.load()
        self._frame: np.ndarray | None = None

        self.records: list[ReplayRecord] = []
        self.timers: list[TimerRecord] = []

    # ------------------------------------------------------------------
    @property
    def region(self) -> ChatRegion | None:
        region = self.worker.region
        return region if region is not None and region.confirmed else None

    def _grab(self, monitor: dict) -> np.ndarray | None:
        if self._frame is None:
            return None
        left, top = max(0, monitor["left"]), max(0, monitor["top"])
        crop = self._frame[top:monitor["top"] + monitor["height"],
                           left:monitor["left"] + monitor["width"]]
        return np.ascontiguousarray(crop)

    def step(self, t: float, frame: np.ndarray) -> None:
        """Show the worker the frame at video second ``t`` and pass on what it read."""
        self._now = CLOCK_BASE + t
        self._frame = frame
        chat_known = self.region is not None
        self.worker._iterate()
        self._drain(t, first_read=not chat_known)
        self.timer_manager.tick()

    def _drain(self, t: float, *, first_read: bool) -> None:
        # The same order as main._drain_results, so the manager sees a replay
        # exactly as it sees a game.
        while True:
            try:
                payload = self._results.get_nowait()
            except queue.Empty:
                break
            if payload.get("session_changed"):
                self.timer_manager.reset(reason="session changed")
            if payload.get("frame_counted"):
                self.timer_manager.note_frame()
            events = payload.get("events") or []
            for event in events:
                self.records.append(ReplayRecord(
                    t=t, champion_id=event.champion_id,
                    champion_name=event.champion_name,
                    spell_key=event.spell_key, kind=event.kind,
                    raw_line=event.raw_line, certain=event.certain,
                    source=event.source, game_time=event.game_time,
                    remaining_seconds=event.remaining_seconds,
                    first_read=first_read))
            if events:
                for timer in self.timer_manager.handle_events(events):
                    self.timers.append(TimerRecord(
                        t=t, champion_id=timer.champion_id,
                        spell_key=timer.spell_key, duration=timer.duration,
                        ready_t=round(timer.started_at + timer.duration
                                      - CLOCK_BASE, 3),
                        uncertain=timer.uncertain, first_read=first_read))
            status = payload.get("status")
            if (status is not None and status.game_clock is not None
                    and self.timer_manager.live is None):
                self.timer_manager.note_clock(status.game_clock)

    # ------------------------------------------------------------------
    def write(self, path: Path, *, video: Path, duration: float,
              fps: float) -> None:
        """Write ``events.json``: what was read, what was timed, and where."""
        region = self.region
        data = {
            "video": str(video),
            "width": int(self.worker.detector.state.window_rect[2]),
            "height": int(self.worker.detector.state.window_rect[3]),
            "fps": fps,
            "duration": duration,
            "region": [int(v) for v in region.rect] if region is not None else None,
            "roster_from_sidecar": False,
            "events": [asdict(record) for record in self.records],
            "timers": [asdict(record) for record in self.timers],
        }
        Path(path).write_text(json.dumps(data, indent=2), "utf-8")

    def close(self) -> None:
        """Hand the real clock back."""
        clock.use(None)
