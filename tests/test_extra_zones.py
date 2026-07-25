# -*- coding: utf-8 -*-
"""The two areas beyond the chat: the game clock and the scoreboard.

Neither can be found automatically -- a match timer is five glyphs with no
signature to search for, and the scoreboard only exists while Tab is held -- so
pointing at them by hand is the feature, not a fallback. What is asserted here:

* one frame serves all three areas, and each keeps its own shape and readout;
* the clock is *read*: OCR text becomes a game time, and a game time becomes the
  clock the timers age their pings against;
* a clock read off the screen is only believed once a second reading agrees, since
  a single misread would move the reference forward where it would stick.
"""
import sys, io, os, threading, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_zonetest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

from PySide6.QtWidgets import QApplication

from chat_detector import ChatRegion
from message_parser import parse_clock
from riot_assets import RiotAssets
from settings import DEFAULTS, Settings
from timer_manager import (CLOCK_CONFIRM_TOLERANCE, PRIME_FRAMES, TimerManager)
from zone_overlay import (MIN_REGION, ZONE_CHAT, ZONE_CLOCK, ZONE_SCOREBOARD,
                          ZoneFrame)

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


# ------------------------------------------------------- reading a clock
for text, expected in (("12:34", 754), ("(3:07)", 187), ("0:00", 0),
                       ("l2:34", 754),          # l read for 1
                       ("12:3A", None),         # A is not a digit lookalike
                       ("99:99", None),         # 99 seconds is not a clock
                       ("", None), ("Ahri", None)):
    got = parse_clock(text)
    check(f"parse_clock({text!r}) -> {expected}", got == expected, str(got))

check("a clock is read out of a noisy line",
      parse_clock("KDA 3/1/7   12:34   350") == 754,
      str(parse_clock("KDA 3/1/7   12:34   350")))


# ------------------------------------------------- the frame knows its zone
app = QApplication.instance() or QApplication(sys.argv)

frames = {zone: ZoneFrame(zone) for zone in (ZONE_CHAT, ZONE_CLOCK, ZONE_SCOREBOARD)}
for zone, frame in frames.items():
    frame.start(ChatRegion(400, 200, 300, 120, source="manual", confirmed=True))

check("each frame carries its zone",
      all(frame.zone == zone for zone, frame in frames.items()))
check("the clock frame may be smaller than a chat line",
      MIN_REGION[ZONE_CLOCK][1] < MIN_REGION[ZONE_CHAT][1],
      f"{MIN_REGION[ZONE_CLOCK]} vs {MIN_REGION[ZONE_CHAT]}")

# A clock frame shrunk to nothing must still delimit something readable.
frames[ZONE_CLOCK].set_region((100, 20, 1, 1))
x, y, width, height = frames[ZONE_CLOCK].region_rect()
check("a clock frame cannot collapse", width >= MIN_REGION[ZONE_CLOCK][0]
      and height >= MIN_REGION[ZONE_CLOCK][1], f"{width}x{height}")

# The readout is judged on what each zone is for: rows for chat, a parsed value
# for the clock, any text at all for the scoreboard.
rows_clock = [((0, 0, 60, 20), "12:34", False)]
frames[ZONE_CLOCK].set_feedback(rows_clock, exploring=False)
summary, good, _detail = frames[ZONE_CLOCK]._readout()
check("the clock frame reports the value it read", good and "12:34" in summary,
      summary)

frames[ZONE_CLOCK].set_feedback([((0, 0, 60, 20), "N/A", False)], exploring=False)
summary, good, _detail = frames[ZONE_CLOCK]._readout()
check("and says so when there is no clock in it", not good, summary)

frames[ZONE_SCOREBOARD].set_feedback(
    [((0, 0, 200, 20), "Ahri 3/1/7", False),
     ((0, 30, 200, 20), "Darius 5/2/1", False)], exploring=False)
summary, good, _detail = frames[ZONE_SCOREBOARD]._readout()
check("the scoreboard frame reports what it read",
      good and "Ahri 3/1/7" in summary, summary)

frames[ZONE_SCOREBOARD].set_feedback([], exploring=False)
_summary, good, _detail = frames[ZONE_SCOREBOARD]._readout()
check("and says so when it read nothing", not good)

# Chat keeps the behaviour it had: rows counted, chat lines called out.
frames[ZONE_CHAT].set_feedback(
    [((0, 0, 300, 20), "(12:04) Ahri a utilise Saut eclair", True),
     ((0, 30, 300, 20), "scenery", False)], exploring=False)
summary, good, detail = frames[ZONE_CHAT]._readout()
check("the chat frame still counts rows and chat lines",
      good and "2" in summary and "Ahri" in detail, f"{summary} / {detail}")

for frame in frames.values():
    frame.close()


# ------------------------------------------ the clock drives the game time
assets = RiotAssets("fr_FR")
assets.bootstrap()

settings = Settings.__new__(Settings)
settings._path = None
settings._lock = threading.RLock()
settings._data = dict(DEFAULTS)
settings.save = lambda: None

manager = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    manager.note_frame()

check("no clock until something reads one",
      manager.estimated_game_time() is None)
check("a single reading is not believed", not manager.note_clock(754),
      str(manager.estimated_game_time()))
check("still no clock after one reading",
      manager.estimated_game_time() is None)

check("a second, agreeing reading is believed", manager.note_clock(754.5),
      str(manager.estimated_game_time()))
estimate = manager.estimated_game_time()
check("and it is the value that was read",
      estimate is not None and abs(estimate - 754.5) < 1.0, str(estimate))

# A misread that jumps forward must not be adopted on its own, because the
# reference only ever advances and a bad value would stick.
check("a wild jump is not believed on its own",
      not manager.note_clock(4354),      # "12:34" read as "72:34"
      str(manager.estimated_game_time()))
after = manager.estimated_game_time()
check("the clock is unharmed by it",
      after is not None and abs(after - 754.5) < 2.0, str(after))

# Two readings that disagree with each other never confirm anything.
check("two disagreeing readings confirm nothing",
      not manager.note_clock(3000) and not manager.note_clock(800),
      str(manager.estimated_game_time()))
check("the tolerance is the documented one",
      CLOCK_CONFIRM_TOLERANCE < 5.0, str(CLOCK_CONFIRM_TOLERANCE))

# Going backwards is a misread within a session; a real restart clears the
# reference through the session change instead.
manager.note_clock(100)
manager.note_clock(100.2)
back = manager.estimated_game_time()
check("the clock never walks backwards",
      back is not None and back > 700, str(back))

# What it is all for: a ping is aged against the clock, so the clock being right
# is what makes a late read cost nothing.
from message_parser import MessageParser
parser = MessageParser(assets)
manager.handle_events(parser.parse_lines(
    ["(12:30) Kevin (Jinx): Attendez Darius Saut eclair - 240 sec."]))
flash = next((t for t in manager.snapshot() if t.spell_key == "Flash"), None)
# Read at ~12:34 on the clock, so the ping is ~4s old: 240 - 4 = ~236 left.
check("a ping is aged against the clock read off the screen",
      flash is not None and 230 <= flash.remaining() <= 239,
      f"{flash.remaining():.0f}s" if flash else "none")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
