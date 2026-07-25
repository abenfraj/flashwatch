# -*- coding: utf-8 -*-
"""Checks the bar never draws two markers on top of each other.

Two enemies pinging a summoner in the same second share the exact same point on
the track, and a batch of spells coming back up at the same time all crowd the
right-hand end. Both cases used to stack portraits, hiding every champion but
the last one drawn. The properties asserted here are the ones a player relies on:
one visible marker per cooldown, all of them inside the bar.
"""
import sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

from PySide6.QtWidgets import QApplication

import settings as settings_module
from pathlib import Path
tmp = Path(os.environ["TEMP"]) / "loltimer_bartest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

from overlay import Overlay
from settings import Settings
from timer_manager import ActiveTimer

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def spans_overlap(lefts, spans, gap=0):
    """First pair of markers that touch, or None."""
    order = sorted(range(len(lefts)), key=lambda i: lefts[i])
    for a, b in zip(order, order[1:]):
        if lefts[b] < lefts[a] + spans[a] + gap:
            return (a, b)
    return None


# ------------------------------------------------------- the placement rule
# _spread is pure, so the awkward cases can be stated directly.
spread = Overlay._spread

# Same target: three spells announced in the same second.
spans = [40, 40, 40]
lefts = spread(spans, [100, 100, 100], 0, 600, 3)
check("markers sharing a target are separated",
      spans_overlap(lefts, spans) is None, str(lefts))

# Everything nearly ready: targets crowd the right edge, past the boundary.
spans = [46, 46, 46, 46]
lefts = spread(spans, [560, 575, 590, 605], 0, 600, 3)
check("markers crowding the right edge stay separated",
      spans_overlap(lefts, spans) is None, str(lefts))
check("markers crowding the right edge stay inside the bar",
      all(l >= 0 for l in lefts) and max(l + s for l, s in zip(lefts, spans)) <= 600,
      str(lefts))

# Targets before the left edge.
spans = [46, 46]
lefts = spread(spans, [-30, -25], 0, 600, 3)
check("markers before the left edge stay separated",
      spans_overlap(lefts, spans) is None, str(lefts))
check("markers before the left edge stay inside the bar",
      all(l >= 0 for l in lefts), str(lefts))

# Ten cooldowns on a bar with room for six: nothing can be perfectly separated,
# but the crowding must be shared rather than dropping markers on one another.
spans = [46] * 10
lefts = spread(spans, [i * 30 for i in range(10)], 0, 300, 3)
check("an overcrowded bar keeps every marker at a distinct position",
      len(set(lefts)) == 10, str(lefts))
check("an overcrowded bar keeps every marker inside",
      all(0 <= l and l + 46 <= 300 for l in lefts), str(lefts))
gaps = [b - a for a, b in zip(lefts, lefts[1:])]
check("an overcrowded bar spreads the crowding evenly",
      max(gaps) - min(gaps) <= 1, str(gaps))

# The ordinary case must be left alone: markers sitting where their progress says.
spans = [40, 40]
lefts = spread(spans, [100, 400], 0, 600, 3)
check("markers that already fit are not moved", lefts == [100, 400], str(lefts))


# --------------------------------------------------- through the real widget
app = QApplication.instance() or QApplication(sys.argv)
settings = Settings()
settings.update({"overlay_layout": "bar", "overlay_scale": 1.0,
                 "hide_until_in_game": False}, save=False)


class FakeAssets:
    champions: dict = {}

    def icon_for_champion(self, _cid):
        return None

    def icon_for_spell(self, _key):
        return None


overlay = Overlay(settings, FakeAssets())
overlay.resize(640, 78)

now = time.monotonic()


def timer(cid, spell, duration, elapsed):
    return ActiveTimer(champion_id=cid, champion_name=cid, kind="summoner",
                       spell_key=spell, spell_name=spell, duration=duration,
                       started_at=now - elapsed)


# Two different champions flashing at the same moment, plus a pair coming back
# up together at the other end of the track.
overlay.set_timers([
    timer("Ahri", "SummonerFlash", 300, 0.2),
    timer("Darius", "SummonerFlash", 300, 0.2),
    timer("Jinx", "SummonerHeal", 240, 239.0),
    timer("Lux", "SummonerBarrier", 180, 179.5),
])

placed = overlay._bar_marker_rects()
check("the bar places one marker per cooldown", len(placed) == 4,
      f"{len(placed)} placed")
collision = None
for i in range(len(placed)):
    for j in range(i + 1, len(placed)):
        if placed[i].intersects(placed[j]):
            collision = (i, j)
check("no two portraits overlap on the bar", collision is None,
      f"{collision} in {[ (r.x(), r.width()) for r in placed ]}")
check("every marker is inside the bar",
      all(r.left() >= 0 and r.right() <= overlay.width() for r in placed),
      str([(r.left(), r.right()) for r in placed]))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
