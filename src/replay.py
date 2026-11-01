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
import math
import queue
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

import chat_detector
import clock
from chat_detector import ChatRegion
from cooldowns import DDRAGON_SPELL_IDS
from game_detector import GameState
from live_client import parse_game
import settings as settings_module
from message_parser import MessageParser
from ocr import PROBE_CLOCK, CaptureWorker
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
# Everything the feed reports for an enemy. All but the lane are required: the
# feed never leaves them out, so a missing one would read as "known to be none"
# -- no boots, no Inspiration -- and change the cooldowns behind a claim that
# the roster came from the game.
ENEMY_FIELDS = ("champion", "spells", "level", "items", "rune_trees", "position")
ENEMY_REQUIRED = ("champion", "spells", "level", "items", "rune_trees")

# The player a replay "is": on the other team from every enemy in the sidecar.
REPLAY_RIOT_ID = "Replay#0"


class ReplayInputError(Exception):
    """A video, sidecar or output folder replay cannot work with."""


# How long after the chat is first found a line still counts as possibly older
# than the recording. The pass that finds the chat reads a wide band with caps,
# so a line already on screen can be parsed a pass or two later; ten passes
# covers that, and a ping that truly arrives in those two seconds only loses
# its "fresh" label, never its timer.
FIRST_READ_GRACE = 2.0


@dataclass
class ReplayRecord:
    """A line the app acted on -- started or confirmed a timer -- and when."""
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
    # The line's identity to the timer manager: OCR variants of one chat line
    # share it, which is why each appears here once.
    signature: str = ""
    # Read within FIRST_READ_GRACE of the first time the chat was found by
    # searching. The line may predate the recording -- the screen cannot say --
    # so the generator does not present it as a fresh ping. A chat area given in
    # a sidecar is known from the first frame, and then nothing is first_read.
    first_read: bool = False


@dataclass
class TimerRecord:
    """A timer as the overlay counts it, in video seconds.

    One per timer: when a later line re-anchors it (an inferred "?" confirmed),
    the record is updated in place, so ``ready_t`` is always the moment the
    overlay shows it coming back. ``t`` stays the first time it appeared.
    """
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


def video_info(path: Path) -> tuple[int, int, float, float | None]:
    """``(width, height, fps, duration_seconds)`` of a video, or ReplayInputError.

    The duration is the container's estimate (frames / average rate), which is
    approximate on variable-rate footage and missing (None) when the container
    does not know its own length; the replay measures what it actually covered.
    """
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
    duration = frames / fps if frames > 0 and math.isfinite(frames) else None
    return width, height, fps, duration


def iter_video_frames(path: Path, fps: float = DEFAULT_FPS, start: float = 0.0,
                      end: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """Yield ``(video_seconds, frame_bgr)`` every ``1/fps`` seconds.

    Each sample gets the frame whose own timestamp is nearest to it. The
    timestamp is the frame's, not its index over the average rate: on
    variable-rate footage (screen recorders often are) counting frames drifts
    by seconds. At most two frames are held at once, so a thirty-minute VOD
    costs no more memory than a ten-second clip.
    """
    capture = _open(Path(path))
    try:
        interval = 1.0 / capture.get(cv2.CAP_PROP_FPS)
        if start > 0:
            capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
        step = 0
        previous: tuple[float, np.ndarray] | None = None

        def due() -> float:
            return round(start + step / fps, 6)

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            at = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if previous is not None and not at > previous[0]:
                # A backend that reports no usable timestamp: fall back to
                # the average rate from the last good one.
                at = previous[0] + interval
            if previous is not None:
                # Every sample closer to the previous frame than to this one.
                boundary = (previous[0] + at) / 2.0
                while due() < boundary:
                    if end is not None and due() >= end - 1e-9:
                        return
                    yield due(), previous[1]
                    step += 1
            previous = (at, frame)
        if previous is not None:
            # The last frame stands for half an average interval past itself.
            while due() <= previous[0] + interval / 2.0:
                if end is not None and due() >= end - 1e-9:
                    return
                yield due(), previous[1]
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
        if not isinstance(enemies, list) or len(enemies) != 5:
            # The feed always lists all five, and the parser refuses a ping on
            # anybody it does not list: a partial roster would silently drop
            # every ping on the enemies left out.
            raise bad("enemies", "all five enemies, as the game's feed lists them")
        if assets is None:
            assets = RiotAssets(locale)
            assets.bootstrap()
        spells_by_name = {name.lower(): name for name in DDRAGON_SPELL_IDS}
        out["enemies"] = []
        for index, enemy in enumerate(enemies):
            where = f"enemies[{index}]"
            if not isinstance(enemy, dict):
                raise bad(where, "expected an object")
            for key in enemy:
                if key not in ENEMY_FIELDS:
                    raise bad(f"{where}.{key}", "unknown field (known: "
                              + ", ".join(ENEMY_FIELDS) + ")")
            for key in ENEMY_REQUIRED:
                if key not in enemy:
                    raise bad(f"{where}.{key}", "required: the feed always "
                                                "gives it ([] for none)")
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
            level = enemy["level"]
            if not isinstance(level, int) or isinstance(level, bool) \
                    or not 1 <= level <= 18:
                raise bad(f"{where}.level", "a whole number from 1 to 18")
            items = enemy["items"]
            if not isinstance(items, list) or not all(
                    isinstance(i, int) and not isinstance(i, bool) for i in items):
                raise bad(f"{where}.items", "a list of item ids")
            trees = enemy["rune_trees"]
            if not isinstance(trees, list) or len(trees) != 2 or not all(
                    isinstance(t, str) and t.lower() in RUNE_TREES for t in trees):
                raise bad(f"{where}.rune_trees", "the primary and secondary "
                          "trees, two names among "
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

        # Fresh every run: a replay is the app as installed, not as the last
        # replay into this folder left it (saved positions, a framed area).
        (self.out_dir / "settings.json").unlink(missing_ok=True)
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
            # As the app does with a chat area the user framed and locked:
            # widened to hold a whole line (main._fitted_chat_region), kept
            # across the session start, and read from the very first frame.
            fitted = chat_detector.fit_manual_region(
                ChatRegion(*region, source="manual", confirmed=True),
                (0, 0, width, height))
            self.settings.update({"chat_region": fitted.as_list(),
                                  "chat_region_locked": True})
            self.worker.set_manual_region(fitted)
        self._players = _feed_players(sidecar.get("enemies") or [])
        self._clock_offset = sidecar.get("game_clock_offset")
        self.roster_from_sidecar = len(self._players) > 1
        self._roster_applied = False

        if not self.roster_from_sidecar:
            # Without the feed the app reads the game clock in the top-right
            # corner, at the shipped default area scaled to the screen
            # (main._seed_zones_for_screen, then a probe while no feed gives the
            # clock -- main._sync_clock_probe). Lines are back-dated by it.
            clock_area = settings_module.scaled_region("clock_region",
                                                       (0, 0, width, height))
            self.settings.set("clock_region", clock_area)
            self.worker.set_probe(PROBE_CLOCK, ChatRegion(
                *clock_area, source="manual", confirmed=True))

        # A chat area known from the first frame was not found by searching,
        # so nothing read through it is "first_read".
        self._first_found_t: float | None = None if region is None else -1.0
        self._last_region: ChatRegion | None = None
        self.records: list[ReplayRecord] = []
        self.timers: list[TimerRecord] = []
        self._recorded: set[str] = set()
        self._timer_index: dict[int, int] = {}

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
        self.worker._iterate()
        region = self.region
        if region is not None:
            # Kept: the worker drops the area after a quiet minute and a half,
            # but the chat was found, and events.json should say where.
            self._last_region = region
            if self._first_found_t is None:
                self._first_found_t = t
        # Only around the *first* find: a chat found again after a quiet
        # stretch is found because a new line appeared, not one from before.
        first_read = (self._first_found_t is not None
                      and self._first_found_t >= 0
                      and t <= self._first_found_t + FIRST_READ_GRACE + 1e-9)
        self._drain(t, first_read=first_read)
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
            if events:
                acted = self.timer_manager.handle_events(events)
                self._record(t, events, acted, first_read)
            status = payload.get("status")
            if (status is not None and status.game_clock is not None
                    and self.timer_manager.live is None):
                self.timer_manager.note_clock(status.game_clock)

    def _record(self, t: float, events: list, acted: list,
                first_read: bool) -> None:
        """Write down what the manager acted on, as the app's own log does.

        ``main._drain_results`` lists the timers ``handle_events`` returned and
        nothing else: an OCR variant of a line already timed, an ultimate with
        ultimates off, a line the roster refused -- none of them reach the
        overlay, so none of them are recorded. A timer returned again (an
        inferred one confirmed by a later line) is the same timer, updated.
        """
        acted_keys = {(timer.champion_id, timer.spell_key) for timer in acted}
        for event in events:
            if ((event.champion_id, event.spell_key) not in acted_keys
                    or event.signature in self._recorded):
                continue
            self._recorded.add(event.signature)
            self.records.append(ReplayRecord(
                t=t, champion_id=event.champion_id,
                champion_name=event.champion_name, spell_key=event.spell_key,
                kind=event.kind, raw_line=event.raw_line, certain=event.certain,
                source=event.source, game_time=event.game_time,
                remaining_seconds=event.remaining_seconds,
                signature=event.signature, first_read=first_read))
        for timer in acted:
            ready_t = round(timer.started_at + timer.duration - CLOCK_BASE, 3)
            index = self._timer_index.get(id(timer))
            if index is not None and self.timers[index].champion_id \
                    == timer.champion_id:
                record = self.timers[index]
                record.duration = timer.duration
                record.ready_t = ready_t
                record.uncertain = timer.uncertain
                continue
            self._timer_index[id(timer)] = len(self.timers)
            self.timers.append(TimerRecord(
                t=t, champion_id=timer.champion_id, spell_key=timer.spell_key,
                duration=timer.duration, ready_t=ready_t,
                uncertain=timer.uncertain, first_read=first_read))

    # ------------------------------------------------------------------
    def write(self, path: Path, *, video: Path, duration: float,
              fps: float) -> None:
        """Write ``events.json``: what was read, what was timed, and where."""
        region = self.region or self._last_region
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
