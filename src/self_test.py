"""The shipped self-test: the whole reading chain, on a real game frame.

Pressing Test runs exactly what a game runs, with one substitution -- the frame
comes from a file instead of from the screen:

    search band  ->  OCR  ->  rows that read as chat  ->  chat region
                                                            |
                     timers  <-  parsed events  <-  OCR of that region

So a pass means the OCR engine loaded, the segmentation found the text, the
region was derived from the timestamps, the wording parsed, the cooldown table
answered, and the overlay drew a countdown. It does *not* prove that capturing
*this* user's screen works, since no screen was captured -- that is what the chat
framing tool is for, and the card says so.

The sample is a real frame and a deliberately unkind one: chat box closed, so the
lines are drawn faint over moving scenery, at 13px. It is the case that made the
row segmentation get a second detector; see :meth:`OcrEngine.segment_rows`.

Free of Qt, so the test suite can run it headlessly -- which is the point, since
this doubles as the regression test for that segmentation work.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

import chat_detector
from chat_detector import ChatRegion
from message_parser import MessageParser, SpellEvent, looks_like_chat_line

log = logging.getLogger(__name__)

IMAGE_NAME = "chat-sample.png"
MANIFEST_NAME = "chat-sample.json"


def sample_dir() -> Path:
    """Where the sample lives, running from source or from the .exe.

    Under ``resources/`` beside the font and the illustrations, because it is
    shipped payload rather than something the program writes. Frozen, that means
    PyInstaller's bundle directory and not ``settings.ROOT``, which points at the
    writable data next to the executable.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "resources" / "test"
    return Path(__file__).resolve().parent.parent / "resources" / "test"


@dataclass
class Expectation:
    """One spell the sample is known to contain."""

    champion: str                  # Data Dragon id, e.g. "Yasuo"
    spell: str                     # canonical spell name, e.g. "Exhaust"
    line: str = ""                 # the chat line it comes from, for the report


@dataclass
class SelfTestResult:
    """What the test found, in enough detail to diagnose a failure.

    Reports the stages separately on purpose. "Nothing happened" is useless to
    somebody whose test fails; "the text was read but no region came out of it"
    names the broken step.
    """

    ok: bool = False
    error: str = ""
    image_size: tuple[int, int] = (0, 0)
    band_rows: int = 0             # rows read while exploring
    chat_rows: int = 0             # ...of which read as chat lines
    region: ChatRegion | None = None
    lines: list[str] = field(default_factory=list)
    events: list[SpellEvent] = field(default_factory=list)
    expected: list[Expectation] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def found(self) -> set[tuple[str, str]]:
        return {(event.champion_id, event.spell_key) for event in self.events}

    @property
    def missing(self) -> list[Expectation]:
        found = self.found
        return [want for want in self.expected
                if (want.champion, want.spell) not in found]

    def timer_events(self) -> list[SpellEvent]:
        """The events, made safe to feed to the live TimerManager.

        The clock is stripped from every one of them. The sample was recorded at
        10:18 of somebody else's game, and a timestamp is not inert: the manager
        advances its game-clock reference from it, and two lines agreeing on an
        early clock are exactly its signal that a *new game* started -- which
        would wipe the timers of a real game in progress. Without a timestamp the
        cooldown is simply counted from now, which is what a test wants anyway.
        """
        return [replace(event, game_time=None) for event in self.events]


def load_manifest(directory: Path | None = None) -> dict:
    directory = directory if directory is not None else sample_dir()
    return json.loads((directory / MANIFEST_NAME).read_text("utf-8"))


def sample_parser(assets, manifest: dict) -> MessageParser:
    """A parser for the sample's language, built over the user's own Riot data.

    Its own instance, never the live one: see
    :meth:`MessageParser.add_localised_spells` for why the live parser must not
    learn a second language's wording.
    """
    parser = MessageParser(assets)
    parser.add_localised_spells(manifest.get("spell_names") or {})
    return parser


def run(engine, assets, directory: Path | None = None) -> SelfTestResult:
    """Read the sample the way a game frame is read. Never raises.

    ``engine`` must be a loaded :class:`ocr.OcrEngine`; it is the caller's, so the
    test costs no second copy of the 100MB backend. Errors come back in the
    result rather than as exceptions, because every one of them is something the
    card has to display.
    """
    directory = directory if directory is not None else sample_dir()
    result = SelfTestResult()
    started = time.perf_counter()

    try:
        manifest = load_manifest(directory)
        result.expected = [Expectation(**{k: v for k, v in item.items()
                                          if k in ("champion", "spell", "line")})
                           for item in manifest.get("expected", [])]
        # imread cannot take a non-ASCII path on Windows, and the install
        # directory is the user's -- "C:\Users\Ayoub\Téléchargements" is enough to
        # break it. Reading the bytes ourselves sidesteps the locale entirely.
        raw = np.frombuffer((directory / IMAGE_NAME).read_bytes(), dtype=np.uint8)
        frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    except (OSError, ValueError, TypeError) as exc:
        result.error = f"{directory}: {exc}"
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result

    if frame is None or frame.size == 0:
        result.error = f"{directory / IMAGE_NAME}: unreadable image"
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result

    height, width = frame.shape[:2]
    result.image_size = (width, height)
    window_rect = (0, 0, width, height)

    # --- stage 1: read the generous band, exactly as exploring does ----
    explore = chat_detector.explore_region(window_rect)
    band = frame[explore.y:explore.y + explore.height,
                 explore.x:explore.x + explore.width]
    rows, _ms = engine.read_rows(
        band,
        max_rows=chat_detector.EXPLORE_MAX_ROWS,
        left_fraction=chat_detector.EXPLORE_LEFT_FRACTION,
        min_width_fraction=chat_detector.EXPLORE_MIN_ROW_WIDTH,
    )
    result.band_rows = len(rows)

    # --- stage 2: let the timestamps say where chat is -----------------
    chat_rows = [box for text, box in rows if looks_like_chat_line(text)]
    result.chat_rows = len(chat_rows)
    region = chat_detector.region_from_chat_rows(
        chat_rows, (explore.x, explore.y), window_rect)
    result.region = region
    if region is None:
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result

    # --- stage 3: read the narrowed region and parse it ----------------
    crop = frame[region.y:region.y + region.height,
                 region.x:region.x + region.width]
    lines, _ms = engine.read_lines(crop)
    result.lines = lines

    parser = sample_parser(assets, manifest)
    result.events = parser.parse_lines(lines)

    result.ok = bool(result.expected) and not result.missing
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    log.info("self-test: %s (%d chat rows, %d event(s), %.0fms)",
             "pass" if result.ok else "fail", result.chat_rows,
             len(result.events), result.elapsed_ms)
    return result
