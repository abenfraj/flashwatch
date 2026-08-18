"""Screen capture and OCR pipeline.

Reads pixels from the monitor and nothing else -- the same information a person
looking at the screen has.

The capture loop runs at the configured cadence (200ms), but recognition does
*not*. Three layers of avoided work keep this cheap enough to run beside a game,
each measured on this machine at 1080p:

  1. **Frame gate** (0.1ms) -- compare against the previous frame and do nothing
     if the text did not change. The comparison runs on a *brightness mask*
     rather than raw pixels, so the game world animating behind semi-transparent
     chat does not register as a change. This is the common case by far.

  2. **Own text segmentation instead of the detection network** (1ms vs 265ms) --
     RapidOCR's detector finds text boxes with a neural net; two cheap
     morphological masks plus a horizontal close find the same rows in chat,
     because chat is rigidly left-aligned horizontal text. Measured at
     480ms -> 168ms for a 5-line chat. See :meth:`OcrEngine.segment_rows` for why
     it takes two masks and not one.

  3. **Per-row recognition cache** (1.1ms for an unchanged region) -- rows are
     keyed by an *exact* hash of their pixels, so a static chat panel is almost
     free to re-read. See the ROW_CACHE_SIZE comment for why a tolerant key is
     unusable here.

Kept free of Qt so it can be exercised headlessly; results are handed to the UI
through a plain queue.
"""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import cv2
import numpy as np

import chat_detector
import role_reader
import self_test
from chat_detector import ChatRegion
from game_detector import GameDetector
from message_parser import (MessageParser, SpellEvent, looks_like_chat_line,
                            parse_clock)

log = logging.getLogger(__name__)

# Keep the OCR backend single-threaded. Left to its own devices onnxruntime
# spawns a thread per core and blows the CPU budget for no latency gain on
# images this small.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("ORT_NUM_THREADS", "1")

# Frame-diff sensitivity. Compared on a downscaled glyph mask, not raw pixels.
DIFF_WIDTH = 200
DIFF_PIXEL_THRESHOLD = 24        # per-pixel delta that counts as different
DIFF_MIN_CHANGED = 4             # changed pixels needed to trigger OCR
# Safety net for a change the gate misses. With the chat box closed, messages are
# drawn faint and unbacked over the game, so they can move fewer mask pixels than
# the gate needs; this bounds how long such a message can go unread.
FORCED_OCR_INTERVAL = 1.2

# Chat text is light on dark. Pixels at or above this share of the crop's
# dynamic range are treated as glyphs; everything dimmer is background and is
# ignored, which is what makes the frame gate immune to a moving game world.
#
# Deliberately not lowered to catch faint transient messages: dropping it to 0.50
# made a moving background trip the gate on every single frame, which would mean
# continuous OCR. Bounding the delay with FORCED_OCR_INTERVAL is the cheaper way
# to guarantee a faint message is read.
GLYPH_BRIGHTNESS = 0.60

# Every row is scaled to this height before fingerprinting or recognition.
# Normalising per row rather than per crop is what makes a fingerprint survive
# the region changing size: an extra chat line grows the box, and any scale
# derived from the box would then change for text that did not.
ROW_TARGET_HEIGHT = 32
MAX_ROW_WIDTH = 1600

# Row segmentation bounds in native pixels, covering 1080p through 4K.
MIN_SEGMENT_HEIGHT = 7
MAX_SEGMENT_HEIGHT = 120
MIN_SEGMENT_ASPECT = 2.0

# Word-gap bridging. The first pass uses a fixed gap just to discover how tall
# the text is, then a second pass bridges proportionally to that height, which
# keeps behaviour identical from 1080p to 4K.
INITIAL_BRIDGE = 25
BRIDGE_PER_HEIGHT = 2.6

# Second row detector: a white-hat that keeps thin structure brighter than its
# own surroundings. See :meth:`OcrEngine.stroke_segment_mask` for why a global
# threshold cannot find faint chat and this can.
#
# The kernel is deliberately narrower than the one used for judging name colour
# (STROKE_KERNEL, 5px): it has to respond to 13px glyphs on a 1080p stream as
# well as 26px ones at 4K, and measured at 5px it lost two of the nine rows in
# the real capture. The level is the white-hat response that counts as a stroke;
# 18 was the widest plateau in the sweep -- 10 welded rows together, 26 started
# dropping them.
STROKE_SEGMENT_KERNEL = 3
STROKE_SEGMENT_LEVEL = 18
# When the two detectors have found the same row twice: how much of the shorter
# box's height must overlap, and how far apart their left edges may sit.
ROW_OVERLAP_SHARE = 0.6
ROW_LEFT_SHARE = 0.5

# Row cache, keyed by an *exact* hash of the row's pixels.
#
# This was originally a fuzzy match: a downscaled glyph mask compared with a
# Hamming tolerance, so a line that merely scrolled or faded still hit. Measuring
# it showed that idea cannot work here. Two chat lines differing only in the
# seconds value ("- 245 sec." vs "- 240 sec.") are indistinguishable at any
# downscale, while the *same* line over a darker background moves further than
# they do. The similar and the different overlap, so no threshold separates them
# -- and a false hit means returning another line's text, which silently
# prevented new pings from ever being read.
#
# An exact hash cannot do that. It hits whenever the pixels really are identical
# (chat panel open over static art, a line still in place between frames) and
# simply misses otherwise, costing time instead of correctness.
ROW_CACHE_SIZE = 512

# Abandon a confirmed region and explore again if it stops yielding chat lines
# for this long. Generous, because chat is genuinely silent for long stretches and
# re-exploring costs more CPU than reading a small region.
CONFIRMED_TIMEOUT = 90.0

# Extra zones the user places by hand: the game clock, the scoreboard and the
# loading screen's enemy row.
PROBE_CLOCK = "clock"
PROBE_SCOREBOARD = "scoreboard"
PROBE_LOADING = "loading"
# How often one is re-read. The clock only needs to be right to the second, and
# the scoreboard barely changes, so this stays well below the chat cadence.
PROBE_INTERVAL = 0.9

# Reading the enemy's lanes. Slower again than a probe, and deliberately so: the
# answer changes once per game, and the scoreboard pass costs about 40ms because
# it examines several hundred window positions per lane. At this cadence that is
# under 2% of one core, and it stops altogether the moment the team is known.
ROLE_INTERVAL = 2.5

# How long into a session the loading-screen area is still worth reading. After
# that the frame holds the game world, and reading a card-sized band through the
# OCR is the most expensive thing this module does -- see EXPLORE_MIN_INTERVAL for
# the same problem on the chat band. The scoreboard has no such limit: it is
# matched against icons rather than read, which costs almost nothing, and Tab can
# be pressed at any point in a game.
LOADING_WINDOW = 150.0

# A region restored from a previous session, or one that has not produced a single
# chat line yet this session, gets far less patience: the HUD may have been moved
# or rescaled since, and there is nothing to lose by looking again.
UNVERIFIED_TIMEOUT = 30.0
# Faded transient chat scores lower than text on the opaque panel, so this is
# permissive; the parser is strict enough to discard the resulting noise.
MIN_OCR_CONFIDENCE = 0.32

# Enemy champion names are drawn red in chat; allies are not. That colour is the
# only on-screen evidence of which team a pinged champion is on -- the message
# text carries none, since "Attendez Ahri Saut eclair - 245 sec." reads the same
# whether Ahri is the enemy mid or the ally who pinged their own spell.
#
# Counting red pixels is not enough, and measuring proved it: chat can be drawn
# straight over the game with no backing panel, and over the red base or a
# particle burst *every* pixel of the row is red-dominant, including plain white
# text. Two ideas fix that.
#
# 1. Judge the *glyphs*, relatively. A white-hat transform isolates the text
#    strokes (thin bright structure on locally darker ground) whatever colour they
#    are, and a name counts as red only if it is markedly redder than the rest of
#    that line's own text. A red backdrop tints every word equally, so no word
#    stands out; a real red name leads the white text by ~140 levels.
#
# 2. Require the red to be *word-shaped*. A champion name is one cluster of
#    strokes, roughly glyph-tall, a fraction of the line wide, and sparse inside
#    its own box. Red scenery is either a full-row blob or scattered specks.
STROKE_KERNEL = 5                # a shade wider than a glyph stroke
STROKE_LEVEL = 22                # white-hat response that counts as a stroke
STROKE_MIN_PIXELS = 30           # fewer than this and the row is not text
RED_MARGIN = 45                  # how much redder than its own line a name must be
RED_MIN_DOMINANCE = 30           # ...and redder than neutral, in absolute terms
# Above this, the row's *text* is red across the board, i.e. the backdrop is red
# rather than the name. Nothing can be concluded from such a row.
BACKDROP_RED_BASELINE = 35
NAME_MIN_PIXELS = 30             # a name has strokes; a speck does not
NAME_HEIGHT_SHARE = (0.25, 0.95)  # of the row height
NAME_MAX_WIDTH_SHARE = 0.60      # of the row width
NAME_FILL_SHARE = (0.08, 0.80)   # strokes leave gaps; a solid blob does not

# Verdicts from :func:`name_colour_verdict`.
COLOUR_ENEMY = "enemy"
COLOUR_ALLY = "ally"
COLOUR_UNKNOWN = "unknown"

# Reading the whole explore band costs 0.6-1.3s, and the band contains the
# moving game world, so the frame gate cannot suppress much of it. Throttling
# keeps the exploring phase from monopolising a core. Chat lines persist on
# screen for several seconds, so nothing is missed by looking less often.
EXPLORE_MIN_INTERVAL = 0.7


def row_crop(frame_bgr: np.ndarray, box: tuple[int, int, int, int],
             pad: int = 3) -> np.ndarray:
    """The colour pixels of one text row, padded like the OCR crop."""
    height, width = frame_bgr.shape[:2]
    x, y, w, h = box
    y1, y2 = max(0, y - pad), min(height, y + h + pad)
    x1, x2 = max(0, x - pad), min(width, x + w + pad)
    return frame_bgr[y1:y2, x1:x2]


def stroke_mask(row_bgr: np.ndarray) -> np.ndarray:
    """Text strokes of a row, independent of their colour.

    Uses the max channel rather than luminance: red is dark in luma (a red name
    scores ~113 against white's 240), so a brightness gate drops exactly the text
    this module has to look at.
    """
    value = row_bgr.max(axis=2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                       (STROKE_KERNEL, STROKE_KERNEL))
    tophat = cv2.morphologyEx(value, cv2.MORPH_TOPHAT, kernel)
    return tophat >= STROKE_LEVEL


def name_colour_verdict(row_bgr: np.ndarray) -> str:
    """Whether this chat row names an enemy, an ally, or cannot say.

    Three outcomes, because two would be a lie. Over a red backdrop the colour
    carries no information at all, and answering "ally" there would silently drop
    real enemy pings; the caller retries such a row on a later frame instead,
    which costs nothing since a chat line stays on screen for seconds while the
    game moves behind it.
    """
    if row_bgr.size == 0 or row_bgr.ndim != 3:
        return COLOUR_UNKNOWN
    height, width = row_bgr.shape[:2]
    if height < 6 or width < 12:
        return COLOUR_UNKNOWN

    glyphs = stroke_mask(row_bgr)
    if int(np.count_nonzero(glyphs)) < STROKE_MIN_PIXELS:
        return COLOUR_UNKNOWN

    channels = row_bgr.astype(np.int16)
    dominance = (channels[:, :, 2]
                 - np.maximum(channels[:, :, 1], channels[:, :, 0]))
    # The 40th percentile stands for "this line's ordinary text colour". A median
    # would drift if the name were a large share of the strokes.
    baseline = float(np.percentile(dominance[glyphs], 40))
    if baseline >= BACKDROP_RED_BASELINE:
        return COLOUR_UNKNOWN

    mask = (glyphs & (dominance >= max(RED_MIN_DOMINANCE, baseline + RED_MARGIN))
            ).astype(np.uint8)
    # Weld the strokes of one word together without reaching the next one.
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (4, 3)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    for index in range(1, count):
        x, y, w, h, _area = stats[index]
        pixels = int(np.count_nonzero((labels[y:y + h, x:x + w] == index)
                                     & mask[y:y + h, x:x + w].astype(bool)))
        if pixels < NAME_MIN_PIXELS:
            continue
        if not NAME_HEIGHT_SHARE[0] <= h / height <= NAME_HEIGHT_SHARE[1]:
            continue
        if w / width > NAME_MAX_WIDTH_SHARE:
            continue
        if not (NAME_FILL_SHARE[0] <= pixels / float(w * h)
                <= NAME_FILL_SHARE[1]):
            continue
        return COLOUR_ENEMY
    return COLOUR_ALLY


@dataclass
class PipelineStatus:
    """Snapshot of what the worker is doing, for the status/debug UI.

    Carries the geometry as well as the text, so the zone overlay can draw
    exactly what was captured and which rows were read. Seeing that is the
    difference between diagnosing a detection problem and guessing at it.
    """

    game: str = "League of Legends non detecte"
    in_game: bool = False
    # The client is up but no game is on screen. Reported as its own flag rather
    # than left to be read back out of ``game``: the control window turns this
    # into a state pill, and parsing a translated sentence to find out what it
    # said would break the moment the wording changed.
    client_running: bool = False
    region: str = "-"
    last_ocr_ms: float = 0.0
    frames: int = 0
    ocr_runs: int = 0
    skipped: int = 0
    lines: list[str] = field(default_factory=list)
    near_misses: list[str] = field(default_factory=list)
    # Lines that parsed as a spell but named a champion drawn in an ally colour,
    # so no timer was started. Surfaced in the debug tab: if the colour test ever
    # misfires it would otherwise look like the OCR simply stopped working.
    colour_rejected: list[str] = field(default_factory=list)
    error: str = ""

    # --- geometry, all in screen coordinates ---------------------------
    window_rect: tuple[int, int, int, int] | None = None
    band_rect: tuple[int, int, int, int] | None = None
    region_rect: tuple[int, int, int, int] | None = None
    region_source: str = ""
    region_confirmed: bool = False
    exploring: bool = True
    # (rect, recognised text, whether it looked like a chat line)
    rows: list[tuple[tuple[int, int, int, int], str, bool]] = field(
        default_factory=list)
    # Same, per extra zone ("clock", "scoreboard"), for the frames that place them.
    probe_rows: dict[str, list[tuple[tuple[int, int, int, int], str, bool]]] = field(
        default_factory=dict)
    # Game clock read from the clock zone, in seconds, when it read cleanly.
    game_clock: float | None = None
    # The enemy team as last read: ``{lane index: champion id}``, keyed by
    # position because position is the role. Empty until two readings agree.
    roles: dict[int, str] = field(default_factory=dict)
    roles_source: str = ""
    # One short line per role zone, for its framing tool: what the last look at
    # that rectangle actually recognised.
    role_notes: dict[str, str] = field(default_factory=dict)

    @property
    def skip_ratio(self) -> float:
        return self.skipped / self.frames if self.frames else 0.0


class OcrEngine:
    """Thin wrapper over RapidOCR with chat-specific preprocessing."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        # Exact pixel hash -> recognised text. "" records a row known to be
        # unreadable, which is safe to cache because the key is exact.
        self._row_cache: "OrderedDict[bytes, str]" = OrderedDict()
        self.cache_hits = 0
        self.cache_misses = 0

    def load(self) -> None:
        """Import and construct the engine. Slow, so done off the UI thread."""
        if self._engine is not None:
            return
        from rapidocr_onnxruntime import RapidOCR  # imported late: ~1s and 100MB

        try:
            self._engine = RapidOCR(intra_op_num_threads=1)
        except TypeError:
            # Older builds do not accept the thread hint.
            self._engine = RapidOCR()
        log.info("OCR engine ready")

    @staticmethod
    def preprocess(image_bgr: np.ndarray) -> np.ndarray:
        """Locally equalise chat text, at native resolution.

        Chat is light text with a dark drop shadow over arbitrary game art, so a
        fixed binarisation would destroy it on bright backgrounds. CLAHE lifts
        local contrast instead, which survives both cases.

        Deliberately does *not* rescale: scaling happens per row, in
        :meth:`normalise_row`, so that it depends only on the row's own height.
        """
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        # A firmer clip limit than the default: the faded messages shown when the
        # chat box is closed have little contrast to begin with.
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    @staticmethod
    def normalise_row(row_gray: np.ndarray) -> np.ndarray:
        """Scale one text row to a fixed height, preserving aspect ratio."""
        height, width = row_gray.shape[:2]
        if height <= 0 or width <= 0:
            return row_gray
        scale = ROW_TARGET_HEIGHT / float(height)
        target_w = max(8, min(MAX_ROW_WIDTH, int(round(width * scale))))
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        return cv2.resize(row_gray, (target_w, ROW_TARGET_HEIGHT),
                          interpolation=interpolation)

    @staticmethod
    def _rows_from_mask(binary: np.ndarray,
                        bridge_width: int) -> list[tuple[int, int, int, int]]:
        """Bounding boxes of the text rows in a binary glyph mask."""
        # The bridging kernel is one pixel tall on purpose: it can only join
        # glyphs sitting on the same rows, so it can never weld two chat lines
        # together. An earlier attempt to reunite fragments by unioning boxes
        # vertically did exactly that -- it chained through scenery blobs until a
        # 20px text row became a 50px box, and squashing that to a fixed height
        # turned the text into mush.
        bridge = cv2.getStructuringElement(cv2.MORPH_RECT, (bridge_width, 1))
        merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, bridge)
        contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        found: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if h < MIN_SEGMENT_HEIGHT or h > MAX_SEGMENT_HEIGHT:
                continue
            if w < h * MIN_SEGMENT_ASPECT:
                continue
            found.append((x, y, w, h))
        return found

    @classmethod
    def _rebridge(cls, binary: np.ndarray,
                  rows: list[tuple[int, int, int, int]]
                  ) -> list[tuple[int, int, int, int]]:
        """Re-run a mask's rows, bridged by the size of the text it just found.

        A fixed word gap is wrong across resolutions, and too small a gap splits
        faint text mid-sentence -- recognising one fragment of a ping yields a
        useless partial line. So the first pass only has to discover how tall the
        text is; this one bridges proportionally to that.
        """
        if not rows:
            return rows
        heights = sorted(row[3] for row in rows)
        median = heights[len(heights) // 2]
        wider = max(INITIAL_BRIDGE, min(220, int(median * BRIDGE_PER_HEIGHT)))
        if wider > INITIAL_BRIDGE:
            rows = cls._rows_from_mask(binary, wider) or rows
        return rows

    @classmethod
    def gradient_rows(cls, gray: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Rows found from glyph edges, thresholded globally.

        Same primitive as chat_detector: a morphological gradient responds to
        glyph edges regardless of text colour.
        """
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        gradient = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)

        _, binary = cv2.threshold(gradient, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        rows = cls._rows_from_mask(binary, INITIAL_BRIDGE)

        if not rows:
            # Otsu picks a global split, so a faint message over busy art can end
            # up below it and vanish entirely. Retry once from the gradient's own
            # statistics before concluding there is no text.
            level = float(gradient.mean() + gradient.std())
            _, binary = cv2.threshold(gradient, max(8.0, level), 255,
                                      cv2.THRESH_BINARY)
            rows = cls._rows_from_mask(binary, INITIAL_BRIDGE)

        return cls._rebridge(binary, rows)

    @staticmethod
    def stroke_segment_mask(image_bgr: np.ndarray) -> np.ndarray:
        """Thin bright strokes, judged against their own neighbourhood.

        The gradient mask above is thresholded *globally*, and that is what it
        cannot do anything about: one bright HUD element or a sunlit patch of
        terrain raises the single threshold above the response of faint chat
        drawn elsewhere in the same band, so the text is not merely missed, it is
        invisible. Measured on a real 1080p frame with the chat box closed: Otsu
        settled at 69 while the chat's own gradient sat below it, and no global
        level separated the two -- lowering it welded the whole area into blobs
        several lines tall.

        A white-hat transform has no global threshold to get wrong. It keeps only
        structure brighter than its own surroundings and thinner than the kernel,
        which is what a glyph stroke is whatever sits behind it. The same
        primitive already decides the colour of champion names in
        :func:`stroke_mask`; this is it applied to finding the rows.

        Computed on the max channel rather than the CLAHE grey: measured, the
        equalised image loses exactly this case (0 chat rows found against 9), as
        equalising a large band lifts the scenery along with the text.
        """
        value = image_bgr.max(axis=2)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (STROKE_SEGMENT_KERNEL, STROKE_SEGMENT_KERNEL))
        hat = cv2.morphologyEx(value, cv2.MORPH_TOPHAT, kernel)
        return ((hat >= STROKE_SEGMENT_LEVEL).astype(np.uint8) * 255)

    @staticmethod
    def _covers(box: tuple[int, int, int, int],
                other: tuple[int, int, int, int]) -> bool:
        """Whether two row boxes are the same row found twice."""
        x, y, w, h = box
        ox, oy, ow, oh = other
        overlap = min(y + h, oy + oh) - max(y, oy)
        return (overlap > ROW_OVERLAP_SHARE * min(h, oh)
                and abs(x - ox) < max(w, ow) * ROW_LEFT_SHARE)

    @classmethod
    def segment_rows(cls, gray: np.ndarray, image_bgr: np.ndarray
                     ) -> list[tuple[int, int, int, int]]:
        """Find text rows without the detection network.

        Two detectors, unioned, because neither alone finds every chat line and
        each fails where the other works. Both were measured against the
        synthetic suite (1080p to 4K, three HUD scales, windowed) *and* a real
        capture of faint 13px chat:

            gradient only  --  6/6 synthetic, 0 of 9 real rows
            strokes only   --  1/6 synthetic, 9 of 9 real rows
            both           --  6/6 synthetic, 9 of 9 real rows

        So the stroke mask is an addition and never a replacement: on the
        synthetic frames it splits or drops rows the gradient reads cleanly.

        The union is not the cost it looks like. It offers ~2 more rows per band,
        and the second mask's rows are often *tighter* than the gradient's, which
        makes recognition -- the expensive step by far -- cheaper rather than
        dearer: measured 338ms against 476ms at 1080p, 487ms against 908ms at
        1440p.
        """
        rows = cls.gradient_rows(gray)
        mask = cls.stroke_segment_mask(image_bgr)
        strokes = cls._rebridge(mask, cls._rows_from_mask(mask, INITIAL_BRIDGE))
        rows.extend(candidate for candidate in strokes
                    if not any(cls._covers(candidate, known) for known in rows))
        rows.sort(key=lambda box: box[1])       # top to bottom == chat order
        return rows

    @staticmethod
    def row_key(row_gray: np.ndarray) -> bytes:
        """Exact key for a text row: a hash of its pixels.

        Exactness is the whole point. Any tolerant comparison risks returning a
        different line's text, and two pings of the same spell differ only in the
        seconds they report -- precisely the difference a downscaled comparison
        cannot see.
        """
        if row_gray.size == 0:
            return b""
        digest = hashlib.blake2b(row_gray.tobytes(), digest_size=16)
        # Shape matters too: identical bytes at a different width are a
        # different row.
        digest.update(repr(row_gray.shape).encode())
        return digest.digest()

    def _cache_lookup(self, key: bytes) -> str | None:
        text = self._row_cache.get(key)
        if text is not None:
            self._row_cache.move_to_end(key)
        return text

    def _cache_store(self, key: bytes, text: str) -> None:
        self._row_cache[key] = text
        while len(self._row_cache) > ROW_CACHE_SIZE:
            self._row_cache.popitem(last=False)

    def _recognise(self, row_bgr: np.ndarray) -> tuple[str, float] | None:
        """Run recognition only -- no detection, no angle classification."""
        try:
            with self._lock:
                result, _ = self._engine(row_bgr, use_det=False, use_cls=False)
        except Exception as exc:                      # noqa: BLE001 - backend varies
            log.debug("recognition failed (%s)", exc)
            return None
        if not result:
            return None
        entry = result[0]
        # Shape differs between rec-only ([text, score]) and full ([box, text,
        # score]) calls, so accept either.
        if len(entry) >= 3:
            text, score = entry[1], entry[2]
        elif len(entry) == 2:
            text, score = entry[0], entry[1]
        else:
            return None
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = 1.0
        return str(text), confidence

    def read_rows(self, image_bgr: np.ndarray, *, max_rows: int | None = None,
                  left_fraction: float | None = None,
                  min_width_fraction: float | None = None
                  ) -> tuple[list[tuple[str, tuple[int, int, int, int]]], float]:
        """OCR an image, returning each line together with where it was found.

        The boxes are in the coordinates of ``image_bgr``, which is what lets
        the caller derive the chat region from the rows that actually read as
        chat lines.

        ``left_fraction`` restricts reading to rows starting in the left part of
        the image, ``min_width_fraction`` drops rows too short to be a chat line,
        and ``max_rows`` caps how many are recognised. All three exist to bound
        the cost of scanning a large area while the chat is still being located:
        recognition is the expensive step, so the cheapest filters are the ones
        applied before it.
        """
        if self._engine is None:
            return [], 0.0
        started = time.perf_counter()
        gray = self.preprocess(image_bgr)
        rows = self.segment_rows(gray, image_bgr)

        if not rows:
            return [], (time.perf_counter() - started) * 1000.0

        height, width = gray.shape[:2]
        if left_fraction is not None:
            limit = width * left_fraction
            rows = [row for row in rows if row[0] <= limit]
        if min_width_fraction is not None:
            # A chat line is a long run of text; most scenery blobs are short.
            minimum = width * min_width_fraction
            rows = [row for row in rows if row[2] >= minimum]
        if max_rows is not None and len(rows) > max_rows:
            # Keep the bottom-most rows: chat grows upward from the input box,
            # so the newest messages are the lowest ones.
            rows = rows[-max_rows:]

        pad = 3
        results: list[tuple[str, tuple[int, int, int, int]]] = []
        for x, y, w, h in rows:
            y1, y2 = max(0, y - pad), min(height, y + h + pad)
            x1, x2 = max(0, x - pad), min(width, x + w + pad)
            row_gray = gray[y1:y2, x1:x2]
            if row_gray.size == 0:
                continue

            row = self.normalise_row(row_gray)
            key = self.row_key(row)

            cached = self._cache_lookup(key)
            if cached is not None:
                self.cache_hits += 1
                if cached:
                    results.append((cached, (x, y, w, h)))
                continue

            recognised = self._recognise(cv2.cvtColor(row, cv2.COLOR_GRAY2BGR))
            self.cache_misses += 1
            text = ""
            if recognised is not None:
                candidate, confidence = recognised
                if confidence >= MIN_OCR_CONFIDENCE and candidate.strip():
                    text = candidate.strip()
            # Unreadable rows are cached as "" too, so we do not retry them
            # every single frame.
            self._cache_store(key, text)
            if text:
                results.append((text, (x, y, w, h)))

        return results, (time.perf_counter() - started) * 1000.0

    def read_lines(self, image_bgr: np.ndarray) -> tuple[list[str], float]:
        """OCR an image into text lines. Returns ``(lines, elapsed_ms)``."""
        rows, elapsed = self.read_rows(image_bgr)
        return [text for text, _box in rows], elapsed

    def clear_cache(self) -> None:
        self._row_cache.clear()


class FrameDiffer:
    """Decides whether a frame is different enough to be worth OCRing."""

    def __init__(self) -> None:
        self._previous: np.ndarray | None = None
        self._last_forced = 0.0

    def reset(self) -> None:
        self._previous = None
        self._last_forced = 0.0

    @staticmethod
    def _fingerprint(image_bgr: np.ndarray) -> np.ndarray:
        """Downscaled *glyph mask* of the crop.

        Comparing raw pixels would fire on every frame whenever chat is drawn
        over the moving game world, defeating the whole gate. Masking to the
        bright end of the crop's dynamic range keeps the text and discards the
        scenery behind it.
        """
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        normalised = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        _, mask = cv2.threshold(normalised, int(255 * GLYPH_BRIGHTNESS), 255,
                                cv2.THRESH_BINARY)
        height, width = mask.shape[:2]
        if width > DIFF_WIDTH:
            scale = DIFF_WIDTH / width
            mask = cv2.resize(mask, (DIFF_WIDTH, max(1, int(height * scale))),
                              interpolation=cv2.INTER_AREA)
        return mask

    def changed(self, image_bgr: np.ndarray) -> bool:
        now = time.monotonic()
        current = self._fingerprint(image_bgr)

        if self._previous is None or self._previous.shape != current.shape:
            self._previous = current
            self._last_forced = now
            return True

        delta = cv2.absdiff(self._previous, current)
        changed_pixels = int(np.count_nonzero(delta > DIFF_PIXEL_THRESHOLD))
        self._previous = current

        if changed_pixels >= DIFF_MIN_CHANGED:
            self._last_forced = now
            return True
        if now - self._last_forced >= FORCED_OCR_INTERVAL:
            self._last_forced = now
            return True
        return False


class CaptureWorker(threading.Thread):
    """Owns the capture -> OCR -> parse loop on its own thread."""

    def __init__(self, settings, parser: MessageParser, results: queue.Queue) -> None:
        super().__init__(name="CaptureWorker", daemon=True)
        self.settings = settings
        self.parser = parser
        self.results = results
        self.detector = GameDetector()
        self.engine = OcrEngine()
        self.differ = FrameDiffer()
        self.status = PipelineStatus()
        self._stop = threading.Event()
        self._region: ChatRegion | None = None
        self._last_chat_seen = 0.0
        self._last_explore = 0.0
        # False until a chat line has actually been read from the current region
        # in this session; a restored region starts unproven.
        self._verified_this_session = False
        self._seen_lines: set[str] = set()
        self._force_redetect = threading.Event()
        self._test_mode = False
        self._sct = None
        # Extra rectangles to read besides the chat: the game clock and the
        # scoreboard. Registered by the UI, either because the user is placing one
        # or -- for the clock -- because a saved one is in use.
        self._probes: dict[str, ChatRegion] = {}
        self._probe_read_at: dict[str, float] = {}
        # Where the enemy team is listed, and the state of reading it. Kept apart
        # from the probes above: a probe is read for the user to look at while
        # they place it, whereas these are read for the application's own sake and
        # must go on being read once the framing tool is closed.
        self._role_regions: dict[str, ChatRegion] = {}
        self._role_read_at: dict[str, float] = {}
        # The previous reading of each zone, awaiting a second one that agrees.
        self._role_candidate: dict[str, dict[int, str]] = {}
        # Cleared when the application has learnt the whole team, so a settled
        # game stops looking. Restored on every session change.
        self._roles_wanted = True
        self._session_started = time.monotonic()
        self.icons = role_reader.IconMatcher(parser.assets)
        # Self-test runs waiting to be served, with the callback to answer on.
        self._self_tests: list = []
        self._self_test_lock = threading.Lock()

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def request_self_test(self, callback) -> None:
        """Ask for the shipped sample to be read, and answer ``callback``.

        Served on this thread rather than the caller's for two reasons: the OCR
        backend lives here already, so the test costs no second copy of it, and
        reading the sample takes about half a second -- long enough to freeze a
        window if it ran on the UI thread. The callback therefore arrives on the
        capture thread, and it is the caller's job to hop back.
        """
        with self._self_test_lock:
            self._self_tests.append(callback)

    def _serve_self_tests(self) -> None:
        with self._self_test_lock:
            pending, self._self_tests = self._self_tests, []
        for callback in pending:
            try:
                result = self_test.run(self.engine, self.parser.assets)
            except Exception as exc:                  # noqa: BLE001 - must answer
                log.exception("self-test failed")
                result = self_test.SelfTestResult(error=str(exc))
            try:
                callback(result)
            except Exception:                         # noqa: BLE001
                log.exception("self-test callback failed")

    def request_redetect(self) -> None:
        """Ask for the chat region to be located again from scratch."""
        self._force_redetect.set()

    def set_test_mode(self, active: bool) -> None:
        """While the test frame is up, read the manual region unconditionally."""
        self._test_mode = active
        self.differ.reset()

    def set_probe(self, zone: str, region: ChatRegion | None) -> None:
        """Register (or drop) an extra rectangle to read every so often.

        Kept separate from the chat region: these are read for their own sake and
        must never influence chat detection, which keys on finding timestamped
        lines and would be thrown off by scoreboard text.
        """
        if region is None:
            self._probes.pop(zone, None)
            self._probe_read_at.pop(zone, None)
            self.status.probe_rows.pop(zone, None)
            if zone == PROBE_CLOCK:
                self.status.game_clock = None
        else:
            self._probes[zone] = region
        log.info("probe %s: %s", zone,
                 region.describe() if region is not None else "off")

    def set_role_region(self, zone: str, region: ChatRegion | None) -> None:
        """Register (or drop) an area the enemy team is listed in."""
        if region is None:
            self._role_regions.pop(zone, None)
            self._role_read_at.pop(zone, None)
            self._role_candidate.pop(zone, None)
            self.status.role_notes.pop(zone, None)
        else:
            self._role_regions[zone] = region

    def set_roles_wanted(self, wanted: bool) -> None:
        """Stop (or restart) looking, once the team is known or a game ends.

        Starting again forgets what was found, and that is the point rather than
        tidiness: the only reason to ask for another look is that the previous
        answer no longer applies, and leaving it published would let the caller
        re-adopt the *previous* game's team while waiting for the new one.
        """
        if wanted and not self._roles_wanted:
            self._role_candidate.clear()
            self.status.roles = {}
            self.status.roles_source = ""
        self._roles_wanted = wanted

    def set_manual_region(self, region: ChatRegion | None) -> None:
        self._region = region
        self.differ.reset()
        # Rows are reported in screen coordinates, so the ones read from the
        # previous rectangle would be drawn in the wrong place by the test frame
        # until the next OCR pass replaces them.
        self.status.rows = []
        if region is not None:
            self.status.region_rect = region.rect
            self.status.region_source = region.source
            self.status.region_confirmed = region.confirmed

    @property
    def region(self) -> ChatRegion | None:
        return self._region

    # ------------------------------------------------------------------
    def run(self) -> None:
        import mss  # thread-local: an mss instance must not be shared

        try:
            self.engine.load()
        except Exception as exc:                      # noqa: BLE001
            log.exception("could not start OCR engine")
            self.status.error = f"OCR indisponible: {exc}"
            self._publish(session_changed=False, events=[])
            return

        self._sct = mss.mss()
        # Needs the window size to validate a saved region, so poll once first.
        state, _ = self.detector.poll()
        self._restore_saved_region(state.window_rect)

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                # Before the iteration, so a test asked for while League is absent
                # is served on the very next tick rather than behind an early
                # return.
                self._serve_self_tests()
                self._iterate()
            except Exception as exc:                  # noqa: BLE001 - loop must survive
                log.exception("capture iteration failed")
                self.status.error = str(exc)

            interval = max(0.05, float(self.settings.get("capture_interval_ms", 200)) / 1000.0)
            self._stop.wait(max(0.0, interval - (time.monotonic() - started)))

        try:
            self._sct.close()
        except Exception:                             # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def _iterate(self) -> None:
        state, session_changed = self.detector.poll()
        self.status.game = state.describe()
        self.status.in_game = state.in_game
        self.status.client_running = state.client_running

        if session_changed:
            # New game or game closed: forget everything about the old one.
            self._seen_lines.clear()
            self.status.colour_rejected.clear()
            self.differ.reset()
            self.engine.clear_cache()
            self._verified_this_session = False
            if not self.settings.get("chat_region_locked"):
                self._region = None
            # A new game is a new enemy team, and the loading screen for it is
            # about to be on screen. Both halves of that matter: looking starts
            # again, and the window in which the loading area is worth reading
            # opens from here.
            self._session_started = time.monotonic()
            self._roles_wanted = True
            self._role_candidate.clear()
            self.status.roles = {}
            self.status.roles_source = ""
            self.status.role_notes.clear()

        self.status.window_rect = state.window_rect

        # Before any of the chat early-returns below: a zone the user is placing
        # has to keep reporting what it reads even with League absent, exactly as
        # the chat frame does, and the clock is worth reading whenever it is
        # configured.
        self._read_probes()
        if state.running:
            # Before the chat early-returns as well, and for a reason of its own:
            # the loading screen is the only chance to learn the lanes, and no
            # chat exists on it yet.
            self._read_roles()

        # A hand-placed region needs no window: in test mode the user is aiming
        # the frame at whatever is on screen (a replay, a screenshot, the client)
        # and expects it to read, League detected or not.
        manual = (self._region if self._region is not None
                  and self._region.source == "manual" else None)
        if not state.in_game or state.window_rect is None:
            if not (self._test_mode and manual is not None):
                self.status.region = "-"
                self.status.band_rect = None
                self.status.region_rect = None
                self.status.rows = []
                self._publish(session_changed=session_changed, events=[])
                return

        region = manual if state.window_rect is None else self._ensure_region(
            state.window_rect)
        self.status.region = region.describe()
        exploring = not region.confirmed
        self.status.band_rect = (chat_detector.search_band(state.window_rect)
                                 if state.window_rect is not None else None)
        self.status.region_rect = region.rect
        self.status.region_source = region.source
        self.status.region_confirmed = region.confirmed
        self.status.exploring = exploring

        frame = self._grab(region.monitor)
        if frame is None:
            self._publish(session_changed=session_changed, events=[])
            return

        self.status.frames += 1
        if not self.differ.changed(frame):
            self.status.skipped += 1
            self._publish(session_changed=session_changed, events=[], counted=True)
            return

        now = time.monotonic()
        if exploring and now - self._last_explore < EXPLORE_MIN_INTERVAL:
            self.status.skipped += 1
            self._publish(session_changed=session_changed, events=[], counted=True)
            return

        # While exploring we are reading a large band, so cap the work; once the
        # region is confirmed it is small enough to read in full.
        if exploring:
            self._last_explore = now
            rows, elapsed_ms = self.engine.read_rows(
                frame,
                max_rows=chat_detector.EXPLORE_MAX_ROWS,
                left_fraction=chat_detector.EXPLORE_LEFT_FRACTION,
                min_width_fraction=chat_detector.EXPLORE_MIN_ROW_WIDTH,
            )
        else:
            rows, elapsed_ms = self.engine.read_rows(
                frame,
                min_width_fraction=chat_detector.CONFIRMED_MIN_ROW_WIDTH,
            )

        self.status.ocr_runs += 1
        self.status.last_ocr_ms = elapsed_ms
        lines = [text for text, _box in rows]
        self.status.lines = lines[-int(self.settings.get("ocr_lines_kept", 40)):]
        # Row boxes come back in capture-local pixels; the UI needs them on
        # screen, where the test frame can line them up with what it drew.
        self.status.rows = [((region.x + box[0], region.y + box[1], box[2], box[3]),
                             text, looks_like_chat_line(text))
                            for text, box in rows]

        chat_rows = [box for text, box in rows if looks_like_chat_line(text)]
        if chat_rows:
            self._last_chat_seen = time.monotonic()
            self._verified_this_session = True

        if exploring and chat_rows and state.window_rect is not None:
            # The timestamps themselves tell us where chat is.
            narrowed = chat_detector.region_from_chat_rows(
                chat_rows, (region.x, region.y), state.window_rect)
            if narrowed is not None:
                log.info("chat confirmed by %d timestamped line(s): %s",
                         len(chat_rows), narrowed.describe())
                self._region = narrowed
                self.differ.reset()
                self._save_region(narrowed)

        fresh = {line for line in lines if line not in self._seen_lines}

        # Parsed row by row rather than in bulk: the row's box is what makes the
        # colour of the name available, and that is the only thing distinguishing
        # an enemy's cooldown from a teammate announcing their own.
        events: list[SpellEvent] = []
        undecided: set[str] = set()
        for text, box in rows:
            if text not in fresh:
                continue
            event, decided = self._event_for_row(frame, text, box)
            if event is not None:
                events.append(event)
            elif not decided:
                undecided.add(text)

        # A line whose colour could not be judged is deliberately *not* recorded,
        # so the next frame reads it again.
        self._seen_lines.update(line for line in lines if line not in undecided)
        if len(self._seen_lines) > 400:
            self._seen_lines = set(lines) - undecided

        self.status.near_misses = list(self.parser.near_misses[-12:])

        self._publish(session_changed=session_changed, events=events, counted=True)

    # ------------------------------------------------------------------
    def _read_probes(self) -> None:
        """Read the extra zones, slowly, and parse the clock out of its own.

        Throttled per zone rather than gated by the frame differ: these regions
        are tiny compared with the chat band, and the clock *always* changes, so a
        differ would fire on every single frame and buy nothing.
        """
        now = time.monotonic()
        for zone, region in list(self._probes.items()):
            if now - self._probe_read_at.get(zone, 0.0) < PROBE_INTERVAL:
                continue
            self._probe_read_at[zone] = now
            frame = self._grab(region.monitor)
            if frame is None:
                continue
            rows, _elapsed = self.engine.read_rows(frame)
            self.status.probe_rows[zone] = [
                ((region.x + box[0], region.y + box[1], box[2], box[3]),
                 text, False)
                for text, box in rows]
            if zone == PROBE_CLOCK:
                clock = parse_clock(" ".join(text for text, _box in rows))
                self.status.game_clock = clock
                if clock is None and rows:
                    log.debug("clock zone read %r, no clock in it",
                              [text for text, _b in rows])

    # ------------------------------------------------------------------
    def _read_roles(self) -> None:
        """Look for the enemy team in the loading screen and the scoreboard.

        Neither area is guaranteed to be showing what it is meant to show: the
        loading screen is replaced by the game, and the scoreboard exists only
        while Tab is held. So a reading is a *candidate* until an independent one
        agrees with it, and only then does it reach the timers. That is the same
        rule the game clock is held to, and for the same reason -- one look at a
        moving background can produce anything.
        """
        if not self._role_regions or not self._roles_wanted:
            return
        if not self.settings.get("auto_roles", True):
            return

        now = time.monotonic()
        for zone, region in list(self._role_regions.items()):
            if now - self._role_read_at.get(zone, 0.0) < ROLE_INTERVAL:
                continue
            if (zone == PROBE_LOADING
                    and now - self._session_started > LOADING_WINDOW):
                continue
            self._role_read_at[zone] = now
            frame = self._grab(region.monitor)
            if frame is None:
                continue

            rows = None
            resolve = None
            if zone == PROBE_LOADING:
                # The loading screen prints champion names, so read them. The
                # scoreboard does not, and putting it through the OCR would cost
                # the most expensive pass in the module to recognise item names.
                read, _elapsed = self.engine.read_rows(frame)
                rows = read
                resolve = self.parser.champion_named
            elif not self.icons.ready:
                self.icons.build()

            slots = role_reader.read_team(frame, rows, self.icons, resolve)
            self.status.role_notes[zone] = self._describe_roles(slots)
            if not role_reader.usable(slots):
                self._role_candidate.pop(zone, None)
                continue

            if self._role_candidate.get(zone) != slots:
                self._role_candidate[zone] = slots
                log.debug("%s zone: %s, waiting for a second reading to agree",
                          zone, slots)
                continue

            if self.status.roles != slots:
                log.info("enemy team from the %s: %s", zone, slots)
            self.status.roles = dict(slots)
            self.status.roles_source = zone

    @staticmethod
    def _describe_roles(slots: dict[int, str]) -> str:
        if not slots:
            return ""
        return " ".join(f"{role_reader.ROLES[index][:3]}={slots[index]}"
                        for index in sorted(slots))

    def _event_for_row(self, frame: np.ndarray, text: str,
                       box: tuple[int, int, int, int]
                       ) -> tuple[SpellEvent | None, bool]:
        """Parse one row. Returns ``(event, decided)``.

        ``decided`` is False when the colour of the name could not be judged, and
        tells the caller to leave the line unremembered so a later frame -- with
        the game world moved on behind translucent chat -- can judge it again.

        The colour test runs *after* parsing, so it costs nothing on the ordinary
        line: chat is mostly player talk, and none of that gets this far.
        """
        event = self.parser.parse_line(text)
        if event is None:
            return None, True
        if not self.settings.get("require_enemy_colour", False):
            return event, True
        if not event.is_exact:
            # A cast announcement ("Ahri a utilise Saut eclair") is the wording a
            # real game produces, and it is printed for enemies only -- the game
            # does not narrate your own team's casts -- so the name it carries
            # needs no vetting. Only the stated-cooldown form is checked, and that
            # one is in practice typed by hand to test the OCR, which is why this
            # option is off by default.
            return event, True

        verdict = name_colour_verdict(row_crop(frame, box))
        if verdict == COLOUR_ENEMY:
            return event, True
        if verdict == COLOUR_UNKNOWN:
            log.debug("deferring %r: the name's colour is unreadable here", text)
            return None, False
        # Not an error: a teammate announcing their own cooldown produces exactly
        # this. Logged and surfaced anyway, because a colour test that stopped
        # matching would look identical to chat having gone quiet.
        log.info("ignoring %r: champion name is not drawn in the enemy colour",
                 text)
        if text not in self.status.colour_rejected:
            self.status.colour_rejected.append(text)
            del self.status.colour_rejected[:-12]
        return None, True

    # ------------------------------------------------------------------
    def _grab(self, monitor: dict[str, int]) -> np.ndarray | None:
        if monitor["width"] < 20 or monitor["height"] < 10:
            return None
        try:
            raw = self._sct.grab(monitor)
        except Exception as exc:                      # noqa: BLE001 - mss raises broadly
            log.debug("capture failed (%s)", exc)
            return None
        frame = np.asarray(raw)                       # BGRA
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def _ensure_region(self, window_rect: tuple[int, int, int, int]) -> ChatRegion:
        """The region to capture: manual, confirmed, or the explore band."""
        if self._force_redetect.is_set():
            self._force_redetect.clear()
            self._region = None
            self._last_chat_seen = 0.0
            self._verified_this_session = False
            self.engine.clear_cache()
            self.differ.reset()

        if self._region is not None and self._region.source == "manual":
            return self._region

        if self._region is not None and self._region.confirmed:
            # If a confirmed region stops producing chat lines the HUD probably
            # moved or the resolution changed, so go back to exploring. A region
            # that has not yet proved itself *this session* is given much less
            # time, since it may simply be stale.
            limit = (CONFIRMED_TIMEOUT if self._verified_this_session
                     else UNVERIFIED_TIMEOUT)
            stale = (self._last_chat_seen
                     and time.monotonic() - self._last_chat_seen > limit)
            if not stale:
                return self._region
            log.info("no chat read for %.0fs from %s, exploring again",
                     limit, self._region.describe())
            self._region = None
            self._last_chat_seen = 0.0
            self.engine.clear_cache()
            self.differ.reset()

        if self._region is None or self._region.source != "explore":
            self._region = chat_detector.explore_region(window_rect)
            log.info("exploring for chat in %s", self._region.describe())
            self.differ.reset()
        return self._region

    # ------------------------------------------------------------------
    def _restore_saved_region(self, window_rect: tuple[int, int, int, int] | None
                              ) -> None:
        """Reuse a region confirmed in an earlier session.

        Restored as *confirmed*, which skips the explore phase entirely -- that
        phase reads a large band and is by far the slowest part of startup. It
        was previously restored unconfirmed and then immediately thrown away, so
        every launch paid for exploring again. Guarded by the window size it was
        found at, since a resolution change invalidates it, and if it turns out to
        be wrong the confirmed-timeout sends us back to exploring anyway.
        """
        saved = self.settings.get("chat_region")
        if not (isinstance(saved, (list, tuple)) and len(saved) == 4):
            return
        try:
            x, y, w, h = (int(v) for v in saved)
        except (TypeError, ValueError):
            return

        manual = bool(self.settings.get("chat_region_locked"))
        if not manual and window_rect is not None:
            stored = self.settings.get("chat_region_window")
            if (isinstance(stored, (list, tuple)) and len(stored) == 2
                    and [int(stored[0]), int(stored[1])]
                    != [window_rect[2], window_rect[3]]):
                log.info("saved chat region was for a %sx%s window, ignoring",
                         stored[0], stored[1])
                return

        self._region = ChatRegion(x, y, w, h,
                                  source="manual" if manual else "auto",
                                  confirmed=True)
        self._last_chat_seen = time.monotonic()
        log.info("reusing saved chat region: %s", self._region.describe())

    def _save_region(self, region: ChatRegion) -> None:
        if self.settings.get("chat_region_locked"):
            return
        values: dict = {"chat_region": region.as_list()}
        state = self.detector.state
        if state.window_rect is not None:
            values["chat_region_window"] = [state.window_rect[2],
                                            state.window_rect[3]]
        self.settings.update(values)

    def _publish(self, *, session_changed: bool, events: list[SpellEvent],
                 counted: bool = False) -> None:
        payload = {
            "session_changed": session_changed,
            "events": events,
            "status": self.status,
            "frame_counted": counted,
        }
        try:
            self.results.put_nowait(payload)
        except queue.Full:
            pass
