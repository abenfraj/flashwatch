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
from cooldowns import DDRAGON_SPELL_IDS
from game_detector import GameState
from live_client import parse_game
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

# What a sidecar may say, and how it is spelled. The rune trees are Riot's ids,
# the ones the data feed reports; positions are the feed's own words.
LOCALES = ("en_US", "fr_FR")
RUNE_TREES = {"precision": 8000, "domination": 8100, "sorcery": 8200,
              "inspiration": 8300, "resolve": 8400}
POSITIONS = ("", "TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
SIDECAR_FIELDS = ("locale", "chat_region", "game_clock_offset", "enemies")

# The player a replay "is": on the other team from every enemy in the sidecar.
REPLAY_RIOT_ID = "Replay#0"


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


def load_sidecar(path: Path, assets: RiotAssets | None = None) -> dict:
    """Read and check a sidecar, or raise ReplayInputError naming the field.

    Champions are checked against Riot's data (``assets``, bootstrapped here if
    not given), spells against the cooldown table, so a typo is refused here
    rather than silently timing nobody.
    """
    path = Path(path)
    if not path.is_file():
        raise ReplayInputError(f"sidecar not found: {path}")
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ReplayInputError(f"sidecar {path}: not valid JSON ({exc})") from exc

    def bad(field: str, why: str) -> ReplayInputError:
        return ReplayInputError(f"sidecar {path}: {field}: {why}")

    if not isinstance(data, dict):
        raise bad("sidecar", "expected a JSON object")
    for key in data:
        if key not in SIDECAR_FIELDS:
            raise bad(key, f"unknown field (known: {', '.join(SIDECAR_FIELDS)})")

    out: dict = {}
    locale = data.get("locale", "en_US")
    if locale not in LOCALES:
        raise bad("locale", f"must be en_US or fr_FR, not {locale!r}")
    if "locale" in data:
        # Only when the sidecar says so: otherwise the caller's choice stands.
        out["locale"] = locale

    if "chat_region" in data:
        region = data["chat_region"]
        if (not isinstance(region, list) or len(region) != 4
                or not all(isinstance(v, int) and not isinstance(v, bool)
                           for v in region)
                or region[0] < 0 or region[1] < 0 or region[2] <= 0
                or region[3] <= 0):
            raise bad("chat_region", "four whole numbers in video pixels: "
                                     "x, y, width, height")
        out["chat_region"] = region

    if "game_clock_offset" in data:
        offset = data["game_clock_offset"]
        if not isinstance(offset, (int, float)) or isinstance(offset, bool):
            raise bad("game_clock_offset", "a number of seconds")
        out["game_clock_offset"] = float(offset)

    if "enemies" in data:
        if "game_clock_offset" not in data:
            raise bad("game_clock_offset", "required with enemies: the game "
                                           "clock is video seconds + offset")
        enemies = data["enemies"]
        if not isinstance(enemies, list) or not 1 <= len(enemies) <= 5:
            raise bad("enemies", "a list of one to five enemies")
        if assets is None:
            assets = RiotAssets(locale)
            assets.bootstrap()
        spells_by_name = {name.lower(): name for name in DDRAGON_SPELL_IDS}
        out["enemies"] = []
        for index, enemy in enumerate(enemies):
            where = f"enemies[{index}]"
            if not isinstance(enemy, dict):
                raise bad(where, "expected an object")
            info = assets.champion_by_name(str(enemy.get("champion", "")))
            if info is None:
                raise bad(f"{where}.champion",
                          f"unknown champion {enemy.get('champion')!r}")
            spells = enemy.get("spells")
            if (not isinstance(spells, list) or not 1 <= len(spells) <= 2
                    or not all(isinstance(s, str) and s.lower() in spells_by_name
                               for s in spells)):
                raise bad(f"{where}.spells", "one or two of "
                          + ", ".join(DDRAGON_SPELL_IDS))
            level = enemy.get("level", 1)
            if not isinstance(level, int) or isinstance(level, bool) \
                    or not 1 <= level <= 18:
                raise bad(f"{where}.level", "a whole number from 1 to 18")
            items = enemy.get("items", [])
            if not isinstance(items, list) or not all(
                    isinstance(i, int) and not isinstance(i, bool) for i in items):
                raise bad(f"{where}.items", "a list of item ids")
            trees = enemy.get("rune_trees", [])
            if not isinstance(trees, list) or not all(
                    isinstance(t, str) and t.lower() in RUNE_TREES for t in trees):
                raise bad(f"{where}.rune_trees", "names among "
                          + ", ".join(name.title() for name in RUNE_TREES))
            position = enemy.get("position", "")
            if position not in POSITIONS:
                raise bad(f"{where}.position", "one of "
                          + ", ".join(p for p in POSITIONS if p))
            out["enemies"].append({
                "champion_id": info.champion_id, "champion_name": info.name,
                "spells": [spells_by_name[s.lower()] for s in spells],
                "level": level, "items": items,
                "rune_trees": [t.lower() for t in trees], "position": position})
    return out


def _feed_players(enemies: list[dict]) -> list[dict]:
    """The sidecar's enemies as the data feed would list them, plus the player."""
    def spell(name: str) -> dict:
        ddragon = DDRAGON_SPELL_IDS[name]
        return {"displayName": name,
                "rawDisplayName": f"GeneratedTip_SummonerSpell_{ddragon}_DisplayName"}

    players = [{"championName": "", "team": "ORDER", "riotId": REPLAY_RIOT_ID,
                "riotIdGameName": REPLAY_RIOT_ID.split("#")[0],
                "summonerSpells": {}, "items": [], "runes": {}, "level": 1}]
    for index, enemy in enumerate(enemies):
        slots = dict(zip(("summonerSpellOne", "summonerSpellTwo"),
                         (spell(name) for name in enemy["spells"])))
        trees = [RUNE_TREES[name] for name in enemy["rune_trees"]]
        runes = dict(zip(("primaryRuneTree", "secondaryRuneTree"),
                         ({"id": tree} for tree in trees)))
        players.append({
            "championName": enemy["champion_name"],
            "rawChampionName": f"game_character_displayname_{enemy['champion_id']}",
            "team": "CHAOS", "level": enemy["level"],
            "position": enemy["position"],
            "riotId": f"Enemy{index}#0", "riotIdGameName": f"Enemy{index}",
            "summonerSpells": slots,
            "items": [{"itemID": item} for item in enemy["items"]],
            "runes": runes})
    return players


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
                 height: int, sidecar: dict | None = None) -> None:
        sidecar = sidecar or {}
        locale = sidecar.get("locale", locale)
        region = sidecar.get("chat_region")
        if region is not None and (region[0] + region[2] > width
                                   or region[1] + region[3] > height):
            raise ReplayInputError(f"chat_region {region} reaches outside the "
                                   f"{width}x{height} video")
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

        if region is not None:
            # As the app does with a chat area the user framed and locked: kept
            # across the session start, and read from the very first frame.
            self.settings.update({"chat_region": list(region),
                                  "chat_region_locked": True})
            self.worker.set_manual_region(ChatRegion(*region, source="manual",
                                                     confirmed=True))
        self._players = _feed_players(sidecar.get("enemies") or [])
        self._clock_offset = sidecar.get("game_clock_offset")
        self.roster_from_sidecar = len(self._players) > 1
        self._roster_applied = False

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
        if self.roster_from_sidecar:
            self._apply_feed(t)
        chat_known = self.region is not None
        self.worker._iterate()
        self._drain(t, first_read=not chat_known)
        self.timer_manager.tick()

    def _apply_feed(self, t: float) -> None:
        """What ``main._sync_live`` does with a reading of the feed, every step.

        Applied before the frame is read, as in an app whose feed was polled
        before the ping arrived: the roster gates the parser and the clock
        back-dates what is read.
        """
        game = parse_game({"gameMode": "CLASSIC", "mapNumber": 11,
                           "gameTime": t + self._clock_offset},
                          self._players, REPLAY_RIOT_ID,
                          champions=self.assets.champions, fetched_at=clock.now())
        self.timer_manager.set_live_game(game)
        if not self._roster_applied:
            self.parser.set_roster({p.champion_id: p.spells for p in game.enemies},
                                   [p.champion_id for p in game.allies
                                    if p.champion_id])
            self._roster_applied = True

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
            "roster_from_sidecar": self.roster_from_sidecar,
            "events": [asdict(record) for record in self.records],
            "timers": [asdict(record) for record in self.timers],
        }
        Path(path).write_text(json.dumps(data, indent=2), "utf-8")

    def close(self) -> None:
        """Hand the real clock back."""
        clock.use(None)
