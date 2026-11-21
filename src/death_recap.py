"""The death recap: enemy summoner spells the game shows when the player dies.

When the player dies, League draws a panel at the top left: the fight's length
("24.7s"), then one row per enemy who dealt damage -- portrait in a **red**
frame, damage, a damage-type bar, and on the right the icons of what did the
damage -- and last the player's own row in a **gold** frame. A summoner spell in
an enemy row was used, whether or not anybody pinged it. In practice that means
Ignite and Smite: the icons are sources of damage, so Flash, Exhaust and the rest
never appear.

Found by its frames rather than at a fixed place. The red and gold outlines are
the most distinctive thing on the panel and cost one colour mask to find; what is
inside a red one is then compared against champion portraits (the scoreboard's
matcher), and only what is to the right of it against summoner icons -- with the
game's roster, only that enemy's own two.

Observation only, like everything else here: pixels in, names out.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Where the panel can be, as a share of the game window from its top left.
# Generous: the HUD scale moves it, and the frame search below is what actually
# finds it.
SEARCH_WIDTH = 0.22
SEARCH_HEIGHT = 0.50

# A portrait's frame side, as a share of the search area's height. Measured at
# 32-36 px in a 540 px area at 1080p; the range leaves room for a HUD scale
# that draws the panel 1.4 times larger in the same window.
FRAME_MIN = 0.040
FRAME_MAX = 0.100
FRAME_ASPECT = 1.3              # a frame is square; bars and plates are not
# Share of a frame's outline that must have the frame's colour.
FRAME_RING = 0.55

# The two frame colours, in BGR: an enemy's is a dark saturated red (measured
# R 75-90 over G and B under 20), the player's a gold (R 110-150, G 85-120,
# B 25-50). Each test says what the colour is *not* as much as what it is.
def _red(image: np.ndarray) -> np.ndarray:
    b, g, r = (image[:, :, i].astype(np.int16) for i in range(3))
    return (r >= 55) & (r - g >= 40) & (r - b >= 40) & (g * 2 < r)


def _gold(image: np.ndarray) -> np.ndarray:
    b, g, r = (image[:, :, i].astype(np.int16) for i in range(3))
    return (r >= 80) & (g - b >= 35) & (r - b >= 50) & (g * 100 >= r * 55)


# The only summoner spells the panel can show: its icons are sources of damage.
# This is not a shortcut but the strongest test there is. Measured on real
# panels, Taliyah's Q icon scores 0.81 against Ghost and a real Ignite 0.80
# against Ignite -- no threshold separates those, and Taliyah does take Ghost.
# Ghost deals no damage, so it is never looked for.
DAMAGE_SPELLS = frozenset({"Ignite", "Smite"})

# Spell icons: drawn as discs to the right of the damage bar, about this share
# of the portrait's side, starting this many portrait sides from its left edge.
ICON_SIZES = (0.70, 0.76, 0.82, 0.88)
ICON_START = 4.0
# Masked correlation an icon must reach: a real Ignite measured 0.80, and the
# best any other icon on four real panels reached against Ignite was 0.64. A
# little higher without the roster, which would have ruled out an enemy who did
# not take the spell.
ICON_SCORE_ROSTER = 0.72
ICON_SCORE_OPEN = 0.75
# ...and how far clear of the other damage spell it must be in the open field.
ICON_MARGIN_OPEN = 0.08

# An enemy who died in the fight has a red cross drawn over the portrait. The
# cross is painted out before a second comparison, and against the five enemies
# the game named a lower score will do, the margin over the other four still
# being required: measured, Ekko crossed out scored 0.50 as drawn and 0.61 with
# the cross painted out, 0.27 clear of anyone else.
ROSTER_MIN_SCORE = 0.55

# The fight's length is written above the first row: "24.7s".
DURATION_RE = re.compile(r"(\d{1,3})\s*[.,]\s*(\d)\s*[sS]")
DURATION_RANGE = (0.5, 120.0)
# Where that text sits, in sides of the first row's frame from its top left:
# rows above it (from, to) and columns right of it (from, to). Read as one line
# with no row finding -- beside it are a clock icon and the damage ring, which a
# row finder welds to it.
DURATION_ROWS = (1.4, 0.6)
DURATION_COLUMNS = (0.5, 2.3)


@dataclass(frozen=True, slots=True)
class RecapRow:
    champion_id: str
    box: tuple[int, int, int, int]          # the frame, in area pixels
    enemy: bool                             # red frame; gold is the player
    spells: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RecapReading:
    rows: list[RecapRow] = field(default_factory=list)
    fight_seconds: float | None = None

    @property
    def enemy_spells(self) -> frozenset[tuple[str, str]]:
        return frozenset((row.champion_id, spell) for row in self.rows
                         if row.enemy for spell in row.spells)

    def describe(self) -> str:
        rows = ", ".join(
            f"{row.champion_id}{'' if row.enemy else ' (you)'}"
            f"{'[' + '/'.join(sorted(row.spells)) + ']' if row.spells else ''}"
            for row in self.rows)
        fight = ("?" if self.fight_seconds is None
                 else f"{self.fight_seconds:.1f}s")
        return f"fight {fight}: {rows}"


def search_area(window_rect: tuple[int, int, int, int]
                ) -> tuple[int, int, int, int]:
    """Where to look, on screen: the top left of the game window."""
    x, y, width, height = window_rect
    return (x, y, int(width * SEARCH_WIDTH), int(height * SEARCH_HEIGHT))


def parse_fight_seconds(text: str) -> float | None:
    """The first plausible "24.7s" on a line, or None."""
    for match in DURATION_RE.finditer(text or ""):
        value = int(match.group(1)) + int(match.group(2)) / 10.0
        if DURATION_RANGE[0] <= value <= DURATION_RANGE[1]:
            return value
    return None


def _frames(area: np.ndarray, mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Square outlines of portrait size in a colour mask, top to bottom."""
    height = area.shape[0]
    low, high = FRAME_MIN * height, FRAME_MAX * height
    binary = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (low <= w <= high and low <= h <= high):
            continue
        if max(w, h) > FRAME_ASPECT * min(w, h):
            continue
        ring = np.concatenate([mask[y, x:x + w], mask[y + h - 1, x:x + w],
                               mask[y:y + h, x], mask[y:y + h, x + w - 1]])
        # The outline is one or two pixels thick and the contour's box sits on
        # it, so look a pixel inside as well before deciding.
        inner = np.concatenate([mask[y + 1, x:x + w], mask[y + h - 2, x:x + w],
                                mask[y:y + h, x + 1], mask[y:y + h, x + w - 2]])
        if max(ring.mean(), inner.mean()) < FRAME_RING:
            continue
        found.append((x, y, w, h))
    found.sort(key=lambda box: box[1])
    return found


def _portrait(area: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    inset = max(2, int(round(min(w, h) * 0.08)))
    return area[y + inset:y + h - inset, x + inset:x + w - inset]


def _without_cross(crop: np.ndarray) -> np.ndarray:
    """The portrait with the dead-enemy cross (its red pixels) painted out."""
    red = _red(crop)
    if not red.any() or crop.shape[0] < 4 or crop.shape[1] < 4:
        return crop
    return cv2.inpaint(crop, red.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)


def _identify(crop: np.ndarray, champions, enemies) -> str | None:
    """Who a red-framed portrait is: as drawn first, then with any cross out."""
    for attempt in (crop, _without_cross(crop)):
        if enemies:
            champion_id, _score = champions.match_among(
                attempt, set(enemies), min_score=ROSTER_MIN_SCORE)
        else:
            champion_id, _score = champions.match(attempt)
        if champion_id is not None:
            return champion_id
    return None


class SpellIconMatcher:
    """Data Dragon's summoner icons, ready to be looked for as discs."""

    def __init__(self, assets) -> None:
        self.assets = assets
        self._icons: dict[str, np.ndarray] = {}

    @property
    def ready(self) -> bool:
        return bool(self._icons)

    def build(self) -> int:
        """Load the icons on disk. Returns how many; safe to call again."""
        if self._icons:
            return len(self._icons)
        for canonical in self.assets.spells:
            path = self.assets.icon_for_spell(canonical)
            if path is None:
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None:
                self._icons[canonical] = image
        return len(self._icons)

    def find(self, band: np.ndarray, candidates, sizes) -> dict[str, float]:
        """Best masked correlation of each candidate spell anywhere in ``band``."""
        scores: dict[str, float] = {}
        for canonical in candidates:
            icon = self._icons.get(canonical)
            if icon is None:
                continue
            best = -1.0
            for size in sizes:
                if size < 8 or size > band.shape[0] or size > band.shape[1]:
                    continue
                template = cv2.resize(icon, (size, size),
                                      interpolation=cv2.INTER_AREA)
                mask = np.zeros((size, size), np.uint8)
                cv2.circle(mask, (size // 2, size // 2), max(2, size // 2 - 2),
                           255, -1)
                result = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED,
                                           mask=mask)
                result = np.nan_to_num(result, nan=-1.0, posinf=-1.0,
                                       neginf=-1.0)
                best = max(best, float(result.max()))
            scores[canonical] = best
        return scores


def _row_spells(area: np.ndarray, box: tuple[int, int, int, int],
                spells: SpellIconMatcher, theirs: frozenset[str] | None
                ) -> frozenset[str]:
    x, y, w, h = box
    side = min(w, h)
    pad = max(2, side // 6)
    left = min(area.shape[1] - 1, x + int(ICON_START * side))
    band = area[max(0, y - pad):min(area.shape[0], y + h + pad), left:]
    if band.size == 0:
        return frozenset()
    sizes = sorted({int(round(side * share)) for share in ICON_SIZES})
    if theirs is not None:
        scores = spells.find(band, theirs & DAMAGE_SPELLS, sizes)
        return frozenset(spell for spell, score in scores.items()
                         if score >= ICON_SCORE_ROSTER)
    scores = spells.find(band, DAMAGE_SPELLS, sizes)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < ICON_SCORE_OPEN:
        return frozenset()
    runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
    if ranked[0][1] - runner_up < ICON_MARGIN_OPEN:
        return frozenset()
    return frozenset({ranked[0][0]})


def read(area: np.ndarray, champions, spells: SpellIconMatcher,
         enemies: dict[str, frozenset[str]] | None,
         read_text: Callable[[np.ndarray], str] | None = None
         ) -> RecapReading | None:
    """Read the panel in ``area`` (see :func:`search_area`), or None if absent.

    ``enemies`` is the game's roster -- champion id to the two spells it took --
    and narrows both comparisons to it; None compares against everything.
    ``read_text`` recognises an image cropped to one line, for the fight's
    length; without it the length stays unknown.
    """
    if area is None or area.size == 0 or not champions.ready:
        return None
    rows: list[RecapRow] = []
    red_frames = _frames(area, _red(area))
    for enemy, frames in ((True, red_frames),
                          (False, _frames(area, _gold(area)))):
        for box in frames:
            crop = _portrait(area, box)
            if enemy:
                champion_id = _identify(crop, champions, enemies)
            else:
                champion_id, _score = champions.match(crop)
            if champion_id is None:
                continue
            theirs = (frozenset(enemies.get(champion_id, ()))
                      if enemies else None)
            found = (_row_spells(area, box, spells, theirs)
                     if enemy else frozenset())
            rows.append(RecapRow(champion_id, box, enemy, found))
    enemy_rows = [row for row in rows if row.enemy]
    if not enemy_rows:
        return None
    rows.sort(key=lambda row: row.box[1])

    fight = None
    if read_text is not None:
        # The topmost red frame, matched or not: a dead enemy's portrait is
        # crossed out and may not match, but its frame still anchors the text.
        x, y, w, h = red_frames[0]
        side = min(w, h)
        crop = area[max(0, y - int(DURATION_ROWS[0] * side)):
                    max(0, y - int(DURATION_ROWS[1] * side)),
                    x + int(DURATION_COLUMNS[0] * side):
                    x + int(DURATION_COLUMNS[1] * side)]
        if crop.size:
            fight = parse_fight_seconds(read_text(crop))
    return RecapReading(rows=rows, fight_seconds=fight)
