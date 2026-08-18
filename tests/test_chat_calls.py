# -*- coding: utf-8 -*-
"""Timers a teammate calls in chat: "jgl flash 950".

Everything else this application reads is the client speaking, and the parser
spends most of its length telling that apart from a human. This is the one form
that is only ever human, so it is recognised by its shape -- a lane or a
champion, a spell, and a time -- and acted on because somebody typed it on
purpose.

What is asserted here, in order of what would hurt most if it broke:

* **no time, no timer.** "top no flash" is a statement about the world, not a
  cooldown, and starting five minutes on it would be worse than reading nothing;
* ordinary chat does not accidentally have the shape;
* the number is a point on the *game clock*, so the countdown ends there whether
  the line was read at once or ten seconds late;
* a lane resolves to whoever plays it, and to nothing at all when that is not
  known -- a wrong champion is worse than an absent timer;
* a call carries the "?" and yields to the game's own word.
"""
import sys, io, os, threading

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_calltest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

from message_parser import MessageParser
from riot_assets import RiotAssets
from settings import DEFAULTS, Settings
from timer_manager import PRIME_FRAMES, TimerManager

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)


def make_manager(**overrides):
    settings = Settings.__new__(Settings)
    settings._path = None
    settings._lock = threading.RLock()
    settings._data = dict(DEFAULTS)
    settings._data.update(overrides)
    settings.save = lambda: None
    manager = TimerManager(assets, settings)
    for _ in range(PRIME_FRAMES):
        manager.note_frame()
    # A clock the calls are measured against. Two agreeing readings, because one
    # is never believed.
    manager.note_clock(300)
    manager.note_clock(300.2)
    manager.set_roles({0: "Darius", 1: "Viego", 2: "Ahri", 3: "Jinx",
                       4: "Thresh"}, source="test")
    return manager


# ------------------------------------------------------------- the shape
CALLS = [
    ("(5:00) Bob (Ahri): jgl flash 950", "JUNGLE", "Flash", 590),
    ("(5:00) Bob (Ahri): jungle flash 9:50", "JUNGLE", "Flash", 590),
    ("(5:00) Bob (Ahri): jgl flash 9 50", "JUNGLE", "Flash", 590),
    ("(5:00) Bob (Ahri): jng flash 950", "JUNGLE", "Flash", 590),
    ("(5:00) Bob (Ahri): mid tp 14:30", "MID", "Teleport", 870),
    ("(5:00) Bob (Ahri): supp exhaust 830", "SUPPORT", "Exhaust", 510),
    ("(5:00) Bob (Ahri): bot heal 7", "ADC", "Heal", 420),
    # The spell first is just as common as the lane first.
    ("(5:00) Bob (Ahri): flash top 620", "TOP", "Flash", 380),
    # A localised spell name, typed in lower case, which the game's own forms
    # would refuse and this one must not.
    ("(5:00) Bob (Ahri): jgl saut eclair 950", "JUNGLE", "Flash", 590),
]
for line, role, spell, ready in CALLS:
    event = parser.parse_line(line)
    ok = (event is not None and event.is_call and event.target_role == role
          and event.spell_key == spell and event.ready_at_game == ready)
    check(f"call parsed: {line.split(': ', 1)[1]!r}", ok,
          "none" if event is None else
          f"{event.target_role}/{event.spell_key}/{event.ready_at_game}")

# A champion may be named instead of a lane.
event = parser.parse_line("(5:00) Bob (Ahri): jinx heal 730")
check("a call may name the champion instead of the lane",
      event is not None and event.champion_id == "Jinx"
      and event.spell_key == "Heal" and not event.target_role,
      "none" if event is None else f"{event.champion_id}/{event.spell_key}")

# ------------------------------------------------- what is NOT a call
NOT_CALLS = [
    # The one the feature must never get wrong: a statement, not a timer.
    "(5:00) Bob (Ahri): top no flash",
    "(5:00) Bob (Ahri): jgl flash",
    "(5:00) Bob (Ahri): mid a plus de flash",
    "(5:00) Bob (Ahri): gg wp 10",
    "(5:00) Bob (Ahri): ff at 15",
    "(5:00) Bob (Ahri): mid ss 30",
    "(5:00) Bob (Ahri): 950",
    "(5:00) Bob (Ahri): report jgl 950",
    "(5:00) Bob (Ahri): jgl flash 9:75",       # 75 seconds is not a clock
]
for line in NOT_CALLS:
    event = parser.parse_line(line)
    check(f"not a call: {line.split(': ', 1)[1]!r}", event is None,
          "" if event is None else f"{event.spell_key}@{event.ready_at_game}")

# ------------------------------------------------------ turning into a timer
manager = make_manager()
started = manager.handle_events(parser.parse_lines(
    ["(5:00) Bob (Ahri): jgl flash 950"]))
timer = started[0] if started else None
check("a call starts a timer on whoever plays that lane",
      timer is not None and timer.champion_id == "Viego"
      and timer.spell_key == "Flash",
      "none" if timer is None else timer.champion_id)
# The clock stands at 5:00 and the call says 9:50, so 290 seconds are left.
check("and it ends at the time that was called",
      timer is not None and 285 <= timer.remaining() <= 291,
      f"{timer.remaining():.0f}s" if timer else "-")
check("a called timer carries the question mark",
      timer is not None and timer.uncertain)
check("and it is not marked approximate, since a number was given",
      timer is not None and not timer.approximate)
check("the lane is on the timer, so the display can group by it",
      timer is not None and timer.role == "JUNGLE",
      timer.role if timer else "-")

# Reading the same line again must not restart anything.
again = manager.handle_events(parser.parse_lines(
    ["(5:00) Bob (Ahri): jgl flash 950"]))
check("re-reading the same call changes nothing", not again)

# Read late: the countdown is anchored to the game clock, not to when we looked.
late = make_manager()
late.note_clock(360)
late.note_clock(360.2)
started = late.handle_events(parser.parse_lines(
    ["(5:00) Bob (Ahri): jgl flash 950"]))
check("a call read a minute late ends at the same moment",
      started and 225 <= started[0].remaining() <= 231,
      f"{started[0].remaining():.0f}s" if started else "-")

# ------------------------------------------------------------ the guards
manager = make_manager()
check("a call for a time already past starts nothing",
      not manager.handle_events(parser.parse_lines(
          ["(5:00) Bob (Ahri): jgl flash 430"])))
check("a call further ahead than any cooldown starts nothing",
      not manager.handle_events(parser.parse_lines(
          ["(5:00) Bob (Ahri): jgl flash 2200"])))

unknown = make_manager()
unknown.reset(reason="forget the roles")
for _ in range(PRIME_FRAMES):
    unknown.note_frame()
unknown.note_clock(300)
unknown.note_clock(300.2)
check("a lane nobody is known to play resolves to nothing",
      not unknown.handle_events(parser.parse_lines(
          ["(5:00) Bob (Ahri): jgl flash 950"])))
check("...while a call naming the champion still works without any roles",
      unknown.handle_events(parser.parse_lines(
          ["(5:00) Bob (Ahri): viego flash 950"])))

blind = make_manager()
blind._clock_ref = None
started = blind.handle_events(parser.parse_lines(
    ["(5:00) Bob (Ahri): jgl flash 950"]))
check("with no clock of its own, a call falls back to the line's timestamp",
      started and 285 <= started[0].remaining() <= 291,
      f"{started[0].remaining():.0f}s" if started else "-")

off = make_manager(chat_calls=False)
check("the setting really switches calls off",
      not off.handle_events(parser.parse_lines(
          ["(5:00) Bob (Ahri): jgl flash 950"])))

# --------------------------------------------- the game outranks a caller
manager = make_manager()
manager.handle_events(parser.parse_lines(["(5:00) Bob (Ahri): jgl flash 950"]))
manager.handle_events(parser.parse_lines(
    ["(5:10) Bob (Ahri): Attendez Viego Saut eclair - 100 sec."]))
timer = next((t for t in manager.snapshot()
              if t.champion_id == "Viego" and t.spell_key == "Flash"), None)
check("the client's own number replaces a called one",
      timer is not None and 90 <= timer.remaining() <= 101,
      f"{timer.remaining():.0f}s" if timer else "-")
check("and the question mark goes with it",
      timer is not None and not timer.uncertain)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
