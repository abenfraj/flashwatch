# -*- coding: utf-8 -*-
"""The hand-placed areas are seeded for the screen, not for 1920x1080.

Two areas are never searched for -- the match timer and the scoreboard -- so
whatever ships as their default is what a fresh install reads until somebody
places them by hand. Shipped as 1080p pixel rectangles they pointed at nothing on
any other screen: the clock probe spent a read every 0.9s on empty pixels for the
life of the install.

Also pins the two things that made this subtle. The chat region is deliberately
*not* scaled, and the framing tool must open exactly where the seed points --
otherwise the program holds two different opinions about where the clock is.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

from settings import DEFAULTS, ZONE_FRACTIONS, Settings, scaled_region

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


# ------------------------------------------------- the fractions are the seeds
# The table is written as the 1080p seed divided by 1080p, so on that screen it
# has to reproduce the shipped rectangle exactly. If it ever does not, one of the
# two was edited without the other.
for key in ZONE_FRACTIONS:
    check(f"{key} scales back to its shipped 1080p value",
          scaled_region(key, (0, 0, 1920, 1080)) == list(DEFAULTS[key]),
          f"{scaled_region(key, (0, 0, 1920, 1080))} vs {DEFAULTS[key]}")

check("the chat region is not in the table",
      "chat_region" not in ZONE_FRACTIONS)

# ------------------------------------------------------- other resolutions
# The clock sits at the top right of League's HUD, beside the minimap, at every
# resolution. What must hold on every screen is that it stays inside it, stays at
# the top right, and stays big enough to hold "10:51".
for width, height in ((2560, 1440), (3840, 2160), (1600, 900), (1920, 1200)):
    rect = scaled_region("clock_region", (0, 0, width, height))
    x, y, w, h = rect
    check(f"[{width}x{height}] the clock area is on screen",
          0 <= x and x + w <= width and 0 <= y and y + h <= height, str(rect))
    check(f"[{width}x{height}] the clock area is at the top right",
          x > width * 0.9 and y < height * 0.05, str(rect))
    check(f"[{width}x{height}] the clock area is big enough to read",
          w >= 40 and h >= 12, str(rect))

    board = scaled_region("scoreboard_region", (0, 0, width, height))
    bx, by, bw, bh = board
    check(f"[{width}x{height}] the scoreboard area is on screen",
          0 <= bx and bx + bw <= width and 0 <= by and by + bh <= height,
          str(board))
    # A tall, narrow column: the five enemy portraits, one above the other. The
    # shape matters as much as the position, because the reader cuts whatever it
    # is given into five cells along its longer side -- a wide seed would slice a
    # single row into five lanes.
    check(f"[{width}x{height}] the scoreboard area is a column of five",
          bh > bw * 1.5 and bh > height * 0.2, str(board))

    loading = scaled_region("loading_region", (0, 0, width, height))
    lx, ly, lw, lh = loading
    check(f"[{width}x{height}] the loading area is on screen",
          0 <= lx and lx + lw <= width and 0 <= ly and ly + lh <= height,
          str(loading))
    # ...and the loading screen's is the other way round: a row of five cards.
    check(f"[{width}x{height}] the loading area is a row of five",
          lw > lh * 1.5 and lw > width * 0.4, str(loading))

# A second monitor's offset has to survive: these are virtual-screen coordinates.
offset = scaled_region("clock_region", (1920, 0, 1920, 1080))
check("a screen offset is carried into the seed",
      offset == [1920 + DEFAULTS["clock_region"][0],
                 DEFAULTS["clock_region"][1], DEFAULTS["clock_region"][2],
                 DEFAULTS["clock_region"][3]], str(offset))

check("an untabled key has no seed", scaled_region("chat_region",
                                                  (0, 0, 2560, 1440)) is None)

# ------------------------------------------------------------- first run only
tmp = Path(os.environ["TEMP"]) / "flashwatch_seedtest"
tmp.mkdir(parents=True, exist_ok=True)
path = tmp / "settings.json"
if path.exists():
    path.unlink()

fresh = Settings(path)
check("a run with no settings file knows it is the first", fresh.fresh)
fresh.set("clock_region", [1, 2, 3, 4])       # as if the user had placed it

again = Settings(path)
check("a run that found settings knows it is not the first", not again.fresh)
check("...and keeps what was placed by hand",
      again.get("clock_region") == [1, 2, 3, 4], str(again.get("clock_region")))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
