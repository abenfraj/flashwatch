# -*- coding: utf-8 -*-
"""Three overlay displays, each with its own place on screen.

Two properties are worth a test here, and neither can be seen by looking at a
screenshot:

*Every cooldown is visible.* Whichever display is chosen, no entry may be drawn
on top of another and none may fall outside the window -- a hidden champion is
worse than no overlay, because it reads as "that spell is up".

*Choosing a display never loses a placement.* The three shapes have nothing in
common: a rectangle that suits a wide top strip puts the vertical rows half off
screen. So each keeps its own geometry, and trying one must not overwrite
another's -- including for somebody upgrading, whose single saved position has to
survive into the new per-display store.
"""
import sys, io, os, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_displaytest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"
if settings_module.CONFIG_PATH.exists():
    settings_module.CONFIG_PATH.unlink()

from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from overlay import (LAYOUT_BAR, LAYOUT_BAR_V, LAYOUT_CARDS, LAYOUT_DEFAULTS,
                     LAYOUT_LIST, LAYOUTS, Overlay)
from settings import Settings
from timer_manager import ActiveTimer

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


class FakeAssets:
    champions: dict = {}

    def icon_for_champion(self, _cid):
        return None

    def icon_for_spell(self, _key):
        return None


app = QApplication.instance() or QApplication(sys.argv)


def timers(count):
    """``count`` cooldowns at evenly spread points of their own cooldowns."""
    now = time.monotonic()
    names = ["Ahri", "Darius", "Jinx", "Thresh", "Viego", "Lux", "Yasuo",
             "Sona", "Teemo", "Zed"]
    roles = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
    made = []
    for index in range(count):
        duration = 300.0
        elapsed = duration * (index / max(1, count - 1)) if count > 1 else 0.0
        made.append(ActiveTimer(
            champion_id=names[index % len(names)],
            champion_name=names[index % len(names)],
            kind="summoner", spell_key="Flash", spell_name="Saut eclair",
            duration=duration, started_at=now - elapsed,
            role=roles[index % len(roles)]))
    return made


def overlapping(rects):
    """First pair of rectangles that intersect, or None."""
    for first in range(len(rects)):
        for second in range(first + 1, len(rects)):
            if rects[first].intersects(rects[second]):
                return (first, second)
    return None


settings = Settings()
overlay = Overlay(settings, FakeAssets())

# ------------------------------------------------------- every display paints
# A layout that raises while a game is running is a layout that shows nothing,
# and the paths differ enough (a track, wrapped cards, scrolling rows) that each
# needs exercising with real content in it.
for layout, size in ((LAYOUT_BAR, QSize(560, 78)),
                     (LAYOUT_CARDS, QSize(420, 104)),
                     (LAYOUT_LIST, QSize(300, 320))):
    settings.set("overlay_layout", layout)
    overlay.sync_layout()
    overlay.resize(size)
    for count in (0, 1, 5, 10):
        overlay.set_timers(timers(count))
        canvas = QPixmap(overlay.size())
        try:
            overlay.render(canvas)
            painted = True
            error = ""
        except Exception as exc:                          # noqa: BLE001
            painted = False
            error = repr(exc)
        check(f"{layout} paints with {count} cooldown(s)", painted, error)

# ---------------------------------------------------- cards never collide
# Same property the track is held to, for the display where it is decided by
# wrapping rather than by spreading: cards are laid out into fixed slots, and a
# window too small for the lot has to drop the tail rather than stack it.
settings.set("overlay_layout", LAYOUT_CARDS)
overlay.sync_layout()
for width, height, count in ((420, 104, 4), (420, 104, 10), (200, 104, 6),
                             (420, 220, 10), (180, 70, 3)):
    overlay.resize(QSize(width, height))
    overlay.set_timers(timers(count))
    rects = overlay._card_rects()
    clash = overlapping(rects)
    check(f"cards do not overlap at {width}x{height} with {count}",
          clash is None, str(clash))
    inside = all(0 <= r.left() and r.right() <= width
                 and 0 <= r.top() and r.bottom() <= height for r in rects)
    check(f"cards stay inside the window at {width}x{height}", inside,
          str([r.getRect() for r in rects][:3]))
    check(f"cards are dropped rather than squeezed at {width}x{height}",
          len(rects) <= count, f"{len(rects)} cards for {count} cooldowns")

overlay.resize(QSize(420, 104))
overlay.set_timers(timers(4))
check("a card is drawn for every cooldown that fits",
      len(overlay._card_rects()) == 4, str(len(overlay._card_rects())))

# --------------------------------------------------- the track, stood on end
# Vertical is the same display turned through ninety degrees, so it is held to
# the same property: one visible marker per cooldown, none on top of another,
# all of them inside the window. It is worth its own case because the axis the
# markers are spread along changes and the countdown moves from under the
# portrait to beside it -- two chances for a marker to be laid out against one
# axis and drawn against the other.
settings.set("overlay_layout", LAYOUT_BAR)
settings.set("bar_vertical", True)
overlay.sync_layout()
for width, height, count in ((150, 420, 5), (150, 420, 10), (200, 640, 3)):
    overlay.resize(QSize(width, height))
    overlay.set_timers(timers(count))
    # Where it settles, not the fifth of a second it spends easing into place.
    overlay.snap_motion()
    rects = overlay._bar_marker_rects()
    check(f"the vertical track places every cooldown at {width}x{height}",
          len(rects) == count, f"{len(rects)} of {count}")
    clash = overlapping(rects)
    check(f"vertical markers do not overlap at {width}x{height}",
          clash is None, str(clash))
    check(f"vertical markers stay inside the window at {width}x{height}",
          all(0 <= r.left() and r.right() <= width
              and 0 <= r.top() and r.bottom() <= height for r in rects),
          str([r.getRect() for r in rects][:3]))

# Eight cooldowns in 200 pixels: they cannot all be separated, and the promise
# then is the same one the horizontal track makes -- the crowding is shared and
# every marker keeps a distinct place, rather than a few landing exactly on top
# of each other and the rest looking fine.
overlay.resize(QSize(120, 200))
overlay.set_timers(timers(8))
overlay.snap_motion()
crowded = overlay._bar_marker_rects()
check("an overcrowded vertical track keeps every marker at a distinct place",
      len({r.top() for r in crowded}) == 8, str([r.top() for r in crowded]))
check("and still inside the window",
      all(0 <= r.top() and r.bottom() <= 200 for r in crowded),
      str([(r.top(), r.bottom()) for r in crowded]))

# Down the axis, in order of progress: the whole point of the display is that
# position *is* how far through the cooldown a spell is.
overlay.resize(QSize(150, 420))
overlay.set_timers(timers(5))
overlay.snap_motion()
tops_in_order = [r.top() for r in overlay._bar_marker_rects()]
check("the vertical track runs from just-used to back-up, top to bottom",
      tops_in_order == sorted(tops_in_order), str(tops_in_order))

settings.set("bar_vertical", False)
overlay.sync_layout()

# ------------------------------------------------- geometry, per display
# The heart of it: place each display somewhere of its own, then switch between
# them and check that nobody's rectangle was taken by anybody else.
# Kept inside a small screen on purpose: an off-screen rectangle is pulled back
# by the on-screen guard, which would make this a test of that instead.
placements = {LAYOUT_BAR: (300, 4, 700, 80),
              LAYOUT_CARDS: (120, 300, 480, 110),
              LAYOUT_LIST: (20, 120, 260, 420)}
for layout, (x, y, width, height) in placements.items():
    settings.set("overlay_layout", layout)
    overlay.sync_layout()
    overlay.setGeometry(x, y, width, height)
    overlay.save_geometry()

kept = {}
for layout in LAYOUTS:
    settings.set("overlay_layout", layout)
    overlay.sync_layout()
    rect = overlay.geometry()
    kept[layout] = (rect.x(), rect.y(), rect.width(), rect.height())

check("each display comes back to its own rectangle", kept == placements,
      str(kept))
check("and all three are on disk",
      set(settings.get("layout_geometry")) >= set(LAYOUTS),
      str(settings.get("layout_geometry")))
# The vertical track keeps a slot of its own beside them, since standing the bar
# on its end changes its shape rather than its display.
check("and the vertical track has a slot of its own",
      LAYOUT_BAR_V in settings.get("layout_geometry"),
      str(sorted(settings.get("layout_geometry"))))

# Switching away and back must not need a save of its own: the geometry in use
# belongs to the outgoing display and is filed under it automatically.
settings.set("overlay_layout", LAYOUT_BAR)
overlay.sync_layout()
overlay.setGeometry(511, 7, 640, 78)
settings.set("overlay_layout", LAYOUT_LIST)
overlay.sync_layout()
settings.set("overlay_layout", LAYOUT_BAR)
overlay.sync_layout()
rect = overlay.geometry()
check("moving a display then switching away keeps the move",
      (rect.x(), rect.y()) == (511, 7), f"{rect.x()},{rect.y()}")

# Same promise across the orientation switch, which is the reason the vertical
# track has its own slot: a strip 640 wide and 78 tall, stood on its end, is not
# a usable vertical track, and coming back to a track squeezed into 150x420 is
# not a usable horizontal one.
settings.set("bar_vertical", True)
overlay.sync_layout()
overlay.setGeometry(12, 140, 150, 420)
overlay.save_geometry()
settings.set("bar_vertical", False)
overlay.sync_layout()
rect = overlay.geometry()
check("turning the track vertical and back keeps the horizontal placement",
      (rect.x(), rect.y(), rect.width(), rect.height()) == (511, 7, 640, 78),
      str(rect.getRect()))
settings.set("bar_vertical", True)
overlay.sync_layout()
rect = overlay.geometry()
check("and the vertical one keeps its own",
      (rect.x(), rect.y(), rect.width(), rect.height()) == (12, 140, 150, 420),
      str(rect.getRect()))
settings.set("bar_vertical", False)
overlay.sync_layout()

# ------------------------------------------------------------ first run
# A display never chosen before has to land somewhere sensible on its own: a
# track along the top edge, rows down a side. Anything else and the first thing a
# new user does is hunt for the overlay.
fresh_path = tmp / "fresh.json"
if fresh_path.exists():
    fresh_path.unlink()
fresh = Settings(fresh_path)
fresh_overlay = Overlay(fresh, FakeAssets())
tops = {}
for layout in LAYOUTS:
    fresh.set("overlay_layout", layout)
    fresh_overlay.sync_layout()
    tops[layout] = fresh_overlay.geometry()

check("the track starts at the top of the screen", tops[LAYOUT_BAR].y() < 80,
      f"y={tops[LAYOUT_BAR].y()}")
check("the cards start at the top too", tops[LAYOUT_CARDS].y() < 80,
      f"y={tops[LAYOUT_CARDS].y()}")
check("the rows start down a side, not across the top",
      tops[LAYOUT_LIST].height() > tops[LAYOUT_LIST].width(),
      f"{tops[LAYOUT_LIST].width()}x{tops[LAYOUT_LIST].height()}")
check("each display got its own default rectangle",
      len({(r.x(), r.y(), r.width(), r.height()) for r in tops.values()}) == 3,
      str({k: v.getRect() for k, v in tops.items()}))

# ------------------------------------------- carried over from an older build
# Somebody updating has one saved rectangle and no per-display store. It belongs
# to whichever display they were using, and it must not be thrown away.
legacy_path = tmp / "legacy.json"
if legacy_path.exists():
    legacy_path.unlink()
legacy = Settings(legacy_path)
legacy.update({"overlay_layout": LAYOUT_LIST, "overlay_x": 77, "overlay_y": 321,
               "overlay_width": 288, "overlay_height": 460,
               "layout_geometry": {}})
legacy_overlay = Overlay(legacy, FakeAssets())
rect = legacy_overlay.geometry()
check("an older build's position is adopted by the display that had it",
      (rect.x(), rect.y(), rect.width(), rect.height()) == (77, 321, 288, 460),
      str(rect.getRect()))
check("and is filed under that display",
      legacy.get("layout_geometry").get(LAYOUT_LIST) == [77, 321, 288, 460],
      str(legacy.get("layout_geometry")))

# The bar is the exception: an older version wrote overlay_x for the vertical
# panel and flagged the bar separately, so a bar that was never placed must take
# its default instead of inheriting a panel's rectangle.
never_path = tmp / "never.json"
if never_path.exists():
    never_path.unlink()
never = Settings(never_path)
never.update({"overlay_layout": LAYOUT_BAR, "overlay_x": 40, "overlay_y": 900,
              "overlay_width": 260, "overlay_height": 420,
              "bar_placed": False, "layout_geometry": {}})
never_overlay = Overlay(never, FakeAssets())
rect = never_overlay.geometry()
# Its own default rather than the 260x420 panel in the file. Checked on the
# height, which is a fixed number the bar owns; the width is a fraction of
# whatever screen the test happens to run on, so it says nothing on a small one.
check("a bar that was never placed is centred at the top rather than inheriting",
      rect.y() < 80 and rect.height() == LAYOUT_DEFAULTS[LAYOUT_BAR]["height"],
      str(rect.getRect()))

# ------------------------------------------------------ unknown setting value
# A settings file written by a newer version, or edited by hand, must not leave
# the overlay drawing nothing at all.
odd_path = tmp / "odd.json"
if odd_path.exists():
    odd_path.unlink()
odd = Settings(odd_path)
odd.set("overlay_layout", "hexagons")
odd_overlay = Overlay(odd, FakeAssets())
check("an unknown display falls back to the track",
      odd_overlay.current_layout() == LAYOUT_BAR, odd_overlay.current_layout())
odd_overlay.set_timers(timers(3))
try:
    odd_overlay.render(QPixmap(odd_overlay.size()))
    check("and it paints", True)
except Exception as exc:                                  # noqa: BLE001
    check("and it paints", False, repr(exc))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
