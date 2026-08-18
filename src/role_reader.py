"""Who plays where, read off the screen.

Knowing the enemy's lanes changes two things. The overlay can sort by role, which
is how people think about a map -- "is the jungler's Flash up?" is a question
about a lane, not about a champion -- and a teammate typing "jgl flash 950" can be
resolved to somebody at all.

Two places say it, and the app reads both because they are available at different
times:

* the **loading screen**, before the game starts. Five cards in a row, in lane
  order, each with the champion's name printed on it. Available for half a minute,
  once, and only to somebody who was watching from the start.
* the **scoreboard**, at any point during the game. Five rows in lane order, each
  led by the champion's portrait -- and the portrait is the *same square art* that
  Data Dragon serves and this application has already cached for the overlay. So
  identification is a comparison against 170 known images rather than an attempt
  to read text that is not there: the scoreboard prints summoner names, never
  champion names.

**Position is the role.** Neither surface labels the lanes; both list a team top,
jungle, mid, bot, support. So the framed area is cut into five cells and the cell
a champion is found in decides the role -- which is why every result here is
keyed by cell index and never by "the order they came out in". See
:func:`roles.assign_slots` for why closing a gap is the one thing that must not
happen.

**Nothing is adopted on one look.** A frame aimed at the loading screen still
contains the game world once the game starts, and a frame aimed at the scoreboard
contains it whenever Tab is not held. Both would occasionally match something.
The caller therefore asks twice and only believes an answer two readings agree on
-- the same rule the game clock is held to, for the same reason.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from roles import ROLES

log = logging.getLogger(__name__)

# One cell per lane, on both surfaces.
CELLS = len(ROLES)

# --- icon matching --------------------------------------------------------
# Each image is reduced to this many pixels a side and compared as a vector.
# 16 is small enough that 170 champions cost nothing to compare against and large
# enough to keep the features that separate them -- a hairline, a helmet, the
# colour of a cloak. Below 8 champions of the same palette start to collide.
DESCRIPTOR = 16

# Fraction trimmed off each edge before comparing. The scoreboard draws its
# portraits inside a frame and Data Dragon's icon has none, so the border is the
# single biggest difference between two pictures of the same champion; cropping
# both to their middles removes it and costs nothing, since the face is what
# identifies a champion anyway.
ICON_INSET = 0.14

# Cosine similarity a match must reach, and how far clear of the runner-up it
# must be. Measured over all 173 icons put through an unkind imitation of a
# scoreboard row -- odd resize, blur, dimmed as for a dead player, a gold frame
# round it -- against blurred noise standing in for a frame aimed at nothing:
#
#                        best score        margin over the runner-up
#   a real portrait      0.66 .. 0.99      0.15 .. 0.75
#   scenery              up to 0.76        up to 0.19
#
# The two ranges overlap, and no pair of thresholds separates them: set high
# enough to exclude every scene, they exclude a tenth of the champions too. So
# these are set to admit *every* real portrait, and the false matches that come
# with that are refused one layer up instead. Both of those layers are structural
# rather than statistical, which is why they work where a threshold cannot:
#
#   * MIN_CELLS -- a reading has to place at least three of the five. Measured at
#     these thresholds, 6% of scenery cells match something, but only one frame in
#     two hundred manages three at once;
#   * and the caller waits for a *second, identical* reading. Scenery moves, so
#     none of those two hundred frames agreed with the one before it. A scoreboard
#     does not move, which is the whole difference.
MIN_SCORE = 0.62
MIN_MARGIN = 0.13

# Where the portrait sits inside its cell, and how finely to look for it. The
# scoreboard's is at the left of a wide row; the loading screen's is in a tall
# card, above the name. Neither is at a fixed offset, and the frame around them is
# drawn by hand, so a square window is slid over the cell and the best position
# wins.
#
# The stride is a fraction of the window rather than a fixed count of steps,
# because a count would thin out as the frame grew: a window three pixels off a
# 48px portrait already drops some champions from 0.98 to 0.64, which is the
# difference between recognised and not, so the stride has to be a good deal finer
# than the comparison's own tolerance. The cap bounds what a frame drawn round the
# whole HUD can cost.
SEARCH_STRIDE = 0.10             # of the window's side
SEARCH_MAX_STEPS = 26
# How far along the cell's long axis to look, from its leading edge. The portrait
# leads its row on the scoreboard and its card on the loading screen, so the far
# end holds gold counts and item icons and is not worth examining.
SEARCH_SHARE = 0.55
# Window sizes, as a share of the cell's short side: the portrait is roughly as
# tall as its row, but "roughly" is doing real work across HUD scales. They stop
# well short of small, deliberately -- a frame drawn round twice as much as it
# should be then matches nothing instead of confidently reading two teams as one.
SEARCH_SCALES = (1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65)

# A reading has to place at least this many of the five before it is offered.
# Fewer than three confident cells is not a team; it is a coincidence.
MIN_CELLS = 3

# Brightness variance a window must have before it is worth comparing at all.
# A champion portrait is busy; the scoreboard panel around it is flat. Measured
# on the panel's own dark grey, which sits near zero, against a portrait's
# several hundred -- so this only ever throws away crops that could not have
# matched anything.
MIN_DETAIL = 40.0


def _descriptor(image_bgr: np.ndarray) -> np.ndarray | None:
    """One image reduced to a comparable vector, or None if it is unusable.

    Mean-subtracted and normalised, so the comparison is a cosine similarity and
    neither brightness nor contrast can carry it: the scoreboard dims a dead
    player's portrait, and that must not change who it is.
    """
    if image_bgr is None or image_bgr.ndim != 3:
        return None
    height, width = image_bgr.shape[:2]
    if height < 8 or width < 8:
        return None
    inset_y, inset_x = int(height * ICON_INSET), int(width * ICON_INSET)
    core = image_bgr[inset_y:height - inset_y, inset_x:width - inset_x]
    if core.size == 0:
        return None
    small = cv2.resize(core, (DESCRIPTOR, DESCRIPTOR),
                       interpolation=cv2.INTER_AREA)
    vector = small.astype(np.float32).reshape(-1)
    vector -= float(vector.mean())
    norm = float(np.linalg.norm(vector))
    if norm < 1e-6:
        return None
    return vector / norm


class IconMatcher:
    """Champion portraits, as vectors, ready to be compared against a crop.

    Built once from the icons already on disk for the overlay, so this costs a
    directory of small PNGs read at startup and nothing thereafter. Kept lazy: a
    user who has switched the role readers off never pays for it.
    """

    def __init__(self, assets) -> None:
        self.assets = assets
        self._ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._tried = False

    @property
    def ready(self) -> bool:
        return self._matrix is not None

    def build(self) -> int:
        """Load every cached champion icon. Returns how many were usable.

        A run that finds nothing does *not* latch: the icons are downloaded in
        the background just after the capture loop starts, so the first attempt
        can legitimately be too early, and giving up permanently there would
        leave the scoreboard unreadable for the whole session.
        """
        if self._tried:
            return len(self._ids)
        ids: list[str] = []
        vectors: list[np.ndarray] = []
        for champion in self.assets.champions.values():
            path = self.assets.icon_for_champion(champion.champion_id)
            if path is None:
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            vector = _descriptor(image)
            if vector is None:
                continue
            ids.append(champion.champion_id)
            vectors.append(vector)
        if len(vectors) < 2:
            log.info("no champion icons to match against yet")
            return 0
        self._tried = True
        self._ids = ids
        self._matrix = np.stack(vectors)
        log.info("role reader: %d champion icons indexed", len(ids))
        return len(ids)

    def forget(self) -> None:
        """Drop the index so it is rebuilt -- after a language or patch change."""
        self._ids, self._matrix, self._tried = [], None, False

    def match(self, crop: np.ndarray) -> tuple[str | None, float]:
        """The champion this crop shows, and how sure that is.

        Returns ``(None, score)`` when nothing is confident enough *or* when two
        champions are nearly as good as each other -- naming the wrong one puts a
        whole team's roles one lane out.
        """
        vector = _descriptor(crop)
        if vector is None:
            return None, 0.0
        return self.match_batch(np.stack([vector]))[0]

    def match_batch(self, vectors: np.ndarray
                    ) -> list[tuple[str | None, float]]:
        """:meth:`match` for many crops at once.

        One matrix product instead of hundreds, which is the difference between
        the search costing 60ms and 8ms: a cell is examined at several hundred
        window positions, and dotting 768 numbers against 173 champions is the
        bulk of that work.
        """
        if self._matrix is None or vectors.size == 0:
            return []
        scores = vectors @ self._matrix.T          # (windows, champions)
        if scores.shape[1] < 2:
            return [(None, 0.0)] * scores.shape[0]
        best = np.argmax(scores, axis=1)
        top = scores[np.arange(scores.shape[0]), best]
        second = np.partition(scores, -2, axis=1)[:, -2]
        good = (top >= MIN_SCORE) & (top - second >= MIN_MARGIN)
        return [(self._ids[best[index]] if good[index] else None,
                 float(top[index])) for index in range(scores.shape[0])]


def _offsets(span: int, side: int) -> list[int]:
    """Positions to try along one axis, from 0 to ``span`` inclusive."""
    if span <= 0:
        return [0]
    stride = max(3, int(round(side * SEARCH_STRIDE)))
    steps = min(SEARCH_MAX_STEPS, span // stride + 2)
    return [int(round(span * index / (steps - 1))) for index in range(steps)]


def _windows(cell: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """Square crops to try inside one cell.

    The window slides along both axes, and the second one is not optional. The
    long axis is the obvious one -- a scoreboard row is wide with its portrait
    somewhere near the left. But centring on the *short* axis assumes the frame
    was drawn tight around the portraits vertically, and measuring says that
    assumption is where this breaks: with the portrait centred, all 173 champions
    are recognised at every size from filling its cell down to 60% of it; with the
    portrait sitting a little high in a row half again too tall, and the window
    pinned to the centre, a twelfth of them come out as *another champion*. The
    frame is drawn by hand, so it is loose by definition.
    """
    x, y, width, height = cell
    if width <= 0 or height <= 0:
        return []
    horizontal = width >= height
    short = height if horizontal else width
    long_side = width if horizontal else height

    boxes: list[tuple[int, int, int, int]] = []
    for scale in SEARCH_SCALES:
        side = max(8, min(long_side, int(round(short * scale))))
        along = _offsets(max(0, int(long_side * SEARCH_SHARE) - side), side)
        across = _offsets(max(0, short - side), side)
        for offset in along:
            for cross in across:
                if horizontal:
                    boxes.append((x + offset, y + cross, side, side))
                else:
                    boxes.append((x + cross, y + offset, side, side))
    return boxes


def _cells(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """The five equal cells a framed team is cut into, in lane order."""
    if width >= height:
        # A row of cards: cut left to right.
        step = width / CELLS
        return [(int(round(index * step)), 0,
                 max(1, int(round(step))), height) for index in range(CELLS)]
    step = height / CELLS
    return [(0, int(round(index * step)), width,
             max(1, int(round(step)))) for index in range(CELLS)]


def _detail_map(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Integral images of a frame's brightness and its square.

    Used to reject a window in constant time. Most window positions in a
    scoreboard row sit on the flat dark panel, and a flat crop cannot be a
    champion whatever it is compared against; skipping those before the resize is
    what keeps a search of several hundred positions per cell affordable.
    """
    if frame is None or frame.ndim != 3 or frame.size == 0:
        return None
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    total, total_sq = cv2.integral2(grey)
    return total, total_sq


def _variance(maps: tuple[np.ndarray, np.ndarray],
              box: tuple[int, int, int, int]) -> float:
    total, total_sq = maps
    x, y, width, height = box
    x2, y2 = x + width, y + height
    count = float(width * height)
    if count <= 0:
        return 0.0
    summed = (total[y2, x2] - total[y, x2] - total[y2, x] + total[y, x])
    squared = (total_sq[y2, x2] - total_sq[y, x2]
               - total_sq[y2, x] + total_sq[y, x])
    mean = summed / count
    return max(0.0, squared / count - mean * mean)


def champion_in_cell(frame: np.ndarray, cell: tuple[int, int, int, int],
                     matcher: IconMatcher,
                     maps: tuple[np.ndarray, np.ndarray] | None = None
                     ) -> tuple[str | None, float]:
    """The best champion found anywhere inside one cell, and its score.

    Where the portrait sits inside its cell is the thing the reader does not
    know, so every square window is tried and the best wins. The sliding is not
    an optimisation to be tuned away: a window three pixels off a 48-pixel
    portrait drops some champions from 0.98 to 0.64, and one pinned to the middle
    of a row that was framed a little tall reads a twelfth of the roster as
    somebody else.
    """
    if maps is None:
        maps = _detail_map(frame)
    if maps is None:
        return None, 0.0

    boxes, vectors = [], []
    for box in _windows(cell):
        if _variance(maps, box) < MIN_DETAIL:
            continue
        x, y, side, _side = box
        vector = _descriptor(frame[y:y + side, x:x + side])
        if vector is not None:
            boxes.append(box)
            vectors.append(vector)
    if not vectors:
        return None, 0.0

    best_id, best_score = None, 0.0
    for champion_id, score in matcher.match_batch(np.stack(vectors)):
        if champion_id is not None and score > best_score:
            best_id, best_score = champion_id, score
    return best_id, best_score


def champions_by_icon(frame: np.ndarray,
                      matcher: IconMatcher) -> dict[int, str]:
    """Find a champion portrait in each of the five cells of ``frame``.

    A cell that finds nothing confident is simply absent from the result, which
    is what keeps one unreadable row from shifting the other four into the wrong
    lanes.
    """
    if frame is None or frame.ndim != 3 or not matcher.ready:
        return {}
    height, width = frame.shape[:2]
    maps = _detail_map(frame)
    found: dict[int, str] = {}
    for index, cell in enumerate(_cells(width, height)):
        champion_id, _score = champion_in_cell(frame, cell, matcher, maps)
        if champion_id is not None:
            found[index] = champion_id
    return found


def champions_by_name(rows, width: int, height: int,
                      resolve) -> dict[int, str]:
    """Find a champion *name* in each of the five cells of a framed area.

    ``rows`` is the pipeline's ``(text, box)`` list in frame-local coordinates and
    ``resolve`` maps a label onto a champion id. Used on the loading screen, which
    prints the names; the scoreboard does not, which is why it gets icons instead.
    """
    cells = _cells(width, height)
    found: dict[int, str] = {}
    for text, box in rows or ():
        champion_id = resolve(text)
        if not champion_id:
            continue
        centre_x = box[0] + box[2] / 2.0
        centre_y = box[1] + box[3] / 2.0
        for index, (x, y, cell_w, cell_h) in enumerate(cells):
            if x <= centre_x < x + cell_w and y <= centre_y < y + cell_h:
                # First name wins the cell. On a loading card the champion's name
                # sits under the portrait and nothing else in the cell resolves,
                # so a second hit means the frame is too wide rather than that
                # this one is better.
                found.setdefault(index, champion_id)
                break
    return found


def read_team(frame: np.ndarray, rows, matcher: IconMatcher,
              resolve=None) -> dict[int, str]:
    """Read one team out of a framed area, by name if possible and by icon if not.

    Names first, because a name that reads is unambiguous in a way a picture never
    quite is. Icons are not a fallback for a *bad* name read though -- they are
    what the scoreboard needs, since it has no names at all -- so both are tried
    and the fuller answer wins.
    """
    if frame is None or frame.ndim != 3:
        return {}
    height, width = frame.shape[:2]

    named: dict[int, str] = {}
    if resolve is not None and rows:
        named = champions_by_name(rows, width, height, resolve)
    if len(named) >= CELLS:
        return named

    by_icon = champions_by_icon(frame, matcher)
    if len(by_icon) > len(named):
        return by_icon
    return named


def usable(slots: dict[int, str]) -> bool:
    """Whether a reading is worth offering to the timers at all."""
    return len(slots) >= MIN_CELLS and len(set(slots.values())) == len(slots)
