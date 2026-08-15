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
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

from PySide6.QtWidgets import QApplication

import settings as settings_module
from pathlib import Path
tmp = Path(os.environ["TEMP"]) / "flashwatch_bartest"
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


# ------------------------------------------------------- the uncertainty chip
# The chip sits next to the countdown, and the countdown is the one thing on the
# bar that must be legible at a glance. So: never on the number, never outside the
# box the layout reserved, and big enough to be seen -- it is a warning that the
# spell is a guess, and a warning nobody notices is worse than none.
from PySide6.QtCore import QRectF, Qt                   # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics           # noqa: E402
from overlay import chip_extra, countdown_layout        # noqa: E402

for scale in (0.6, 1.0, 2.0):
    font = QFontMetrics(QFont("Consolas", max(6, int(9 * scale)), QFont.Bold))
    for align, name in ((Qt.AlignHCenter | Qt.AlignVCenter, "centred"),
                        (Qt.AlignRight | Qt.AlignVCenter, "right-aligned")):
        # A box exactly as wide as the layouts make it: the number plus the room
        # reserved for the chip.
        width = font.horizontalAdvance("4:23") + chip_extra(font, scale)
        box = QRectF(100, 50, width, font.height())
        chip, text = countdown_layout(box, "4:23", font, align, True, scale)
        check(f"the chip is beside the {name} number at scale {scale}",
              chip is not None and not chip.intersects(text),
              f"chip={chip.getRect()} text={text.getRect()}")
        check(f"  and stays inside the reserved box ({name}, {scale})",
              box.contains(chip) and text.right() <= box.right(),
              f"box={box.getRect()} chip={chip.getRect()} text={text.getRect()}")
        check(f"  and is as tall as the digits ({name}, {scale})",
              chip.width() >= max(6, int(font.ascent() * 0.9)),
              f"chip={chip.width()}px ascent={font.ascent()}px")

    # A certain cooldown is left exactly as it was: no chip, no shifted number.
    box = QRectF(100, 50, 60, font.height())
    chip, text = countdown_layout(box, "4:23", font, Qt.AlignHCenter, False, scale)
    check(f"a confirmed cooldown gets no chip at scale {scale}",
          chip is None and text == box, f"{chip} {text.getRect()}")

# --------------------------------------------- the countdown stays inside
# The row under the portraits was sized by a rule of thumb that suited one font,
# and a taller one hung off the bottom edge of the panel. What has to hold is a
# property, not a number: whatever the window's height and whatever the scale,
# nothing the track draws may fall outside it.
fit = []
for height in (46, 52, 58, 70, 78):
    for scale in (0.6, 1.0, 1.25, 1.5, 2.0):
        settings.set("overlay_scale", scale)
        overlay.resize(640, height)
        overlay.render(overlay.grab())      # a real paint applies the minimum
        overlay.snap_motion()
        for marker in overlay._bar_markers(scale):
            bottom = (marker.text.bottom() if marker.text.height() >= 8
                      else marker.rect.bottom())
            if bottom > overlay.height() or marker.rect.top() < 0:
                fit.append((height, scale, round(bottom, 1), overlay.height()))
check("the countdown never leaves the panel, at any height or scale",
      not fit, str(fit[:4]))
settings.set("overlay_scale", 1.0)
overlay.resize(640, 78)

# ------------------------------------------------------------- the glide
# Markers ease towards where the layout puts them instead of appearing there.
# What has to hold: a new marker starts where it belongs (a spell just used must
# not slide in from wherever the last one sat), an existing one moves part of the
# way each frame, it gets there, and a marker that is gone is forgotten rather
# than kept for a champion who might flash again in twenty minutes.
from math import exp                                    # noqa: E402
from time import monotonic                              # noqa: E402
from overlay import GLIDE_TAU                           # noqa: E402

one = [timer("Ahri", "SummonerFlash", 300, 10.0)]
overlay.snap_motion()
check("a new marker starts where the layout puts it",
      overlay._glide(one, [100.0]) == [100.0], str(overlay._glide(one, [100.0])))

overlay._glide_at = monotonic() - GLIDE_TAU        # pretend one time constant
moved = overlay._glide(one, [200.0])[0]
check("a marker that has moved eases rather than jumps",
      100.0 < moved < 200.0, f"{moved:.1f}")
check("  and covers about 63% of the way in one time constant",
      abs(moved - (100.0 + 100.0 * (1 - exp(-1)))) < 1.0, f"{moved:.1f}")

for _ in range(20):
    overlay._glide_at = monotonic() - 0.1
    settled = overlay._glide(one, [200.0])[0]
check("and arrives", abs(settled - 200.0) < 0.5, f"{settled:.3f}")

overlay._glide_at = monotonic()
still = overlay._glide(one, [200.0])[0]
check("a marker with nowhere to go stays put", still == settled, f"{still:.3f}")

# The flag behind the extra frames. Thirty repaints a second are worth their CPU
# while something is travelling and are pure waste once nothing is, so the layout
# says which of the two it currently is.
check("a settled track asks for no animation frames", overlay._gliding is False,
      str(overlay._gliding))
overlay._glide_at = monotonic() - 0.01
overlay._glide(one, [400.0])
check("and a track with a marker in transit asks for them",
      overlay._gliding is True, str(overlay._gliding))

overlay._glide([], [])
check("a marker that is gone is forgotten", overlay._glide_from == {},
      str(overlay._glide_from))

# Painting one must work with no icons loaded at all: FakeAssets returns None for
# every path, which is also what a first run before the icon download looks like.
overlay.set_timers([
    timer("Ahri", "SummonerFlash", 300, 10.0),
    ActiveTimer(champion_id="Lux", champion_name="Lux", kind="summoner",
                spell_key="SummonerBarrier", spell_name="Barriere",
                duration=180, started_at=now - 20.0, uncertain=True),
])
overlay.render(overlay.grab())            # no exception is the assertion
check("an uncertain marker paints without its icons", True)
check("and its countdown carries no question mark",
      not overlay._timers[-1].display().startswith("?"),
      overlay._timers[-1].display())

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
