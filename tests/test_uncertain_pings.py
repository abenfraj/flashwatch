# -*- coding: utf-8 -*-
"""The bare "<Champion> <Sort>" form, and its promotion to a confirmed timer.

Three chat forms feed the timers. Two of them assert a cast; this one only names
a spell:

    02:21 Nelo Angelo (Ambessa): Morgana Saut eclair

Nothing in it can be verified, and it has the same shape as a player typing two
words, so it starts a timer marked uncertain -- shown with a leading "?" -- and a
later confirmed line for the same spell clears the mark.

What is easy to get wrong, and therefore what this covers:

* the dedupe must not swallow the confirmation. Both lines describe one cast, so
  a signature keyed on champion+spell+timestamp alone would make the second a
  duplicate of the first and drop it;
* confirming must not restart a countdown that is already running correctly;
* evidence must only ever get stronger. A bare line arriving after a confirmed
  one must not put the question mark back.
"""
import sys, io, threading, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import _bootstrap  # noqa: F401,E402 -- puts src/ on the import path

from message_parser import MessageParser          # noqa: E402
from riot_assets import RiotAssets                # noqa: E402
from settings import DEFAULTS, Settings           # noqa: E402
from timer_manager import PRIME_FRAMES, TimerManager  # noqa: E402

assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def fresh_manager():
    """A primed manager on base cooldowns, so expectations are about the logic."""
    settings = Settings.__new__(Settings)
    settings._path = None
    settings._lock = threading.RLock()
    settings._data = dict(DEFAULTS)
    settings._data["assume_cosmic_insight"] = False
    settings._data["assume_ionian_boots"] = False
    settings.save = lambda: None
    manager = TimerManager(assets, settings)
    for _ in range(PRIME_FRAMES):
        manager.note_frame()
    return manager


def feed(manager, line):
    return manager.handle_events(parser.parse_lines([line]))


# ------------------------------------------------------------------ parsing
BARE = "02:21 Nelo Angelo (Ambessa): Morgana Saut éclair"
event = parser.parse_line(BARE)
check("bare line parses", event is not None)
if event:
    check("  resolves to Morgana/Flash",
          (event.champion_id, event.spell_key) == ("Morgana", "Flash"),
          f"{(event.champion_id, event.spell_key)}")
    check("  marked uncertain", event.certain is False)
    check("  timestamp survives", event.game_time == 141, f"{event.game_time}")

confirmed = parser.parse_line("02:21 Nelo Angelo (Ambessa): Morgana a utilisé Saut éclair")
check("confirmed line still certain", confirmed is not None and confirmed.certain)
check("the two forms get different signatures",
      event is not None and confirmed is not None
      and event.signature != confirmed.signature,
      f"{event.signature!r} vs {confirmed.signature!r}" if event and confirmed else "")

# The strict resolvers still have to hold, or every two-word message becomes a
# timer. These are what a player types, not what the game prints.
for junk in ("02:21 Nelo (Ambessa): morgana saut éclair",      # not capitalised
             "02:21 Nelo (Ambessa): Morgana son Saut éclair",  # determiner
             "02:21 Nelo (Ambessa): Morgana flash",            # English on a FR client
             "02:21 Nelo (Ambessa): jsp Morgana Saut éclair",  # extra words
             "02:04 Lorem Ipsen (Jhin) a tué Locke (Locke) et réussi un doublé !",
             "00:15 asian jesus (Sion) a choisi Chute d'Icathia."):
    check(f"rejected: {junk[:52]!r}", parser.parse_line(junk) is None)


# ------------------------------------------------- uncertain timer, then proof
tm = fresh_manager()
started = feed(tm, BARE)
check("bare line starts a timer", len(started) == 1, f"{len(started)} started")
timer = tm._timers.get(("Morgana", "Flash"))
check("timer is uncertain", timer is not None and timer.uncertain)
check("displayed with a question mark",
      timer is not None and timer.display().startswith("?"),
      timer.display() if timer else "")

before = timer.remaining()
started = feed(tm, "02:21 Nelo Angelo (Ambessa): Morgana a utilisé Saut éclair")
timer_after = tm._timers.get(("Morgana", "Flash"))
check("confirmation is not swallowed by the dedupe", len(started) == 1,
      f"{len(started)} returned")
check("same timer object, promoted in place", timer_after is timer)
check("question mark gone", timer_after is not None and not timer_after.uncertain)
check("no leading ? in the display",
      timer_after is not None and not timer_after.display().startswith("?"),
      timer_after.display() if timer_after else "")
check("countdown not restarted", timer_after is not None
      and abs(timer_after.remaining() - before) < 2.0,
      f"{before:.0f}s -> {timer_after.remaining():.0f}s" if timer_after else "")


# ---------------------------------------- a stated cooldown also confirms, and
#                                          replaces the guess with the exact one
tm = fresh_manager()
feed(tm, BARE)
feed(tm, "02:25 Nelo Angelo (Ambessa): Attendez Morgana Saut éclair - 120 sec.")
timer = tm._timers.get(("Morgana", "Flash"))
check("stated line clears the question mark",
      timer is not None and not timer.uncertain)
check("stated line wins over the guess even though it is shorter",
      timer is not None and timer.stated and timer.remaining() < 150,
      f"{timer.remaining():.0f}s left, stated={timer.stated}" if timer else "")


# ------------------------------------------- evidence must not weaken
tm = fresh_manager()
feed(tm, "02:21 Nelo Angelo (Ambessa): Morgana a utilisé Saut éclair")
feed(tm, BARE)
timer = tm._timers.get(("Morgana", "Flash"))
check("a bare line cannot put the question mark back",
      timer is not None and not timer.uncertain)


print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
