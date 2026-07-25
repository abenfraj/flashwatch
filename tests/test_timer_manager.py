# -*- coding: utf-8 -*-
"""Checks the two subtle behaviours in timer_manager: priming and age correction."""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")

from riot_assets import RiotAssets
from message_parser import MessageParser
from timer_manager import TimerManager, PRIME_FRAMES
from settings import Settings

assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)
settings = Settings.__new__(Settings)   # avoid touching the user's real config
import threading
settings._path = None
settings._lock = threading.RLock()
from settings import DEFAULTS
settings._data = dict(DEFAULTS)
# Pin the cooldown modifiers so these expectations test the timer logic rather
# than whatever the shipped defaults happen to be. Base cooldowns here.
settings._data["assume_cosmic_insight"] = False
settings._data["assume_ionian_boots"] = False
settings.save = lambda: None

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


# ---------------------------------------------------------------- priming
tm = TimerManager(assets, settings)
history = parser.parse_lines([
    "(4:12) Ahri a utilisé Saut éclair",
    "(4:30) Darius a utilisé Téléportation",
])
check("history lines parsed", len(history) == 2, f"{len(history)} events")
for _ in range(PRIME_FRAMES):
    tm.note_frame()
    tm.handle_events(history)
check("no timers created from pre-existing chat history", tm.active_count() == 0,
      f"active={tm.active_count()}")
check("priming finished", not tm.priming)

# The same lines must stay deduped after priming ends.
tm.handle_events(history)
check("primed lines stay suppressed after priming", tm.active_count() == 0,
      f"active={tm.active_count()}")


# ------------------------------------------------------- age correction
tm2 = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm2.note_frame()

# Establish the clock at 20:00 via a fresh event, then deliver an older cast.
tm2.handle_events(parser.parse_lines(["(20:00) Jinx a utilisé Soins"]))
est = tm2.estimated_game_time()
check("clock reference established", est is not None and abs(est - 1200) < 2,
      f"estimate={est}")

# A Flash cast at 19:00 is 60s old: 300 - 60 = ~240s should remain.
tm2.handle_events(parser.parse_lines(["(19:00) Ahri a utilisé Saut éclair"]))
flash = next((t for t in tm2.snapshot() if t.spell_key == "Flash"), None)
check("older cast produces a timer", flash is not None)
if flash:
    rem = flash.remaining()
    check("age back-dated correctly", abs(rem - 240) < 3, f"remaining={rem:.1f}s want ~240")

# A Flash cast at 10:00 is 600s old -- long expired, must not appear at all.
tm2.handle_events(parser.parse_lines(["(10:00) Lux a utilisé Saut éclair"]))
lux = next((t for t in tm2.snapshot() if t.champion_id == "Lux"), None)
check("fully expired cast creates no timer", lux is None)


# ------------------------------------------------------------- dedupe
tm3 = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm3.note_frame()
same = parser.parse_lines(["(12:00) Ahri a utilisé Saut éclair"])
for _ in range(20):                      # 20 frames re-reading the same line
    tm3.handle_events(same)
check("same line across 20 frames fires once", tm3.active_count() == 1,
      f"active={tm3.active_count()}")

# A later timestamp is a genuine recast and must restart the timer.
tm3.handle_events(parser.parse_lines(["(18:00) Ahri a utilisé Saut éclair"]))
flash3 = next(t for t in tm3.snapshot() if t.spell_key == "Flash")
check("later timestamp restarts the timer", flash3.remaining() > 290,
      f"remaining={flash3.remaining():.0f}s")


# ---------------------------------------------------- new game detection
tm4 = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm4.note_frame()
tm4.handle_events(parser.parse_lines(["(25:00) Ahri a utilisé Saut éclair"]))
check("timer active in game 1", tm4.active_count() == 1)
# Two separate early lines are required: one is a misread timestamp, and acting
# on a single one used to wipe live timers mid-game. See test_timer_stability.
tm4.handle_events(parser.parse_lines(["(0:40) Lux a utilisé Fatigue"]))
tm4.handle_events(parser.parse_lines(["(0:45) Darius a utilisé Châtiment"]))
ids = {t.champion_id for t in tm4.snapshot()}
check("new game wipes the previous game's timers", "Ahri" not in ids, f"ids={ids}")
check("the line that confirmed the new game still starts its timer",
      "Darius" in ids, f"ids={ids}")

# Mid-game scrollback must NOT be mistaken for a new game. Revealing unseen
# history from 3:00 while at 25:00 previously wiped every valid timer.
tm4b = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm4b.note_frame()
tm4b.handle_events(parser.parse_lines(["(25:00) Ahri a utilisé Saut éclair"]))
tm4b.handle_events(parser.parse_lines(["(3:00) Lux a utilisé Téléportation"]))
ids_b = {t.champion_id for t in tm4b.snapshot()}
check("scrolling to old chat history keeps existing timers", "Ahri" in ids_b,
      f"ids={ids_b}")
check("the revealed old cast creates no timer (already expired)",
      "Lux" not in ids_b, f"ids={ids_b}")


# --------------------------------------------------------------- ults
tm5 = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm5.note_frame()
ahri_ult = assets.champions["Ahri"].ultimate
# rank 1 before 12:00 -> 140s, flagged approximate
tm5.handle_events(parser.parse_lines([f"(5:00) Ahri a utilisé {ahri_ult.name}"]))
ult = next(t for t in tm5.snapshot() if t.spell_key == "ULT")
check("ult uses rank-1 cooldown early game", abs(ult.duration - 140) < 1,
      f"duration={ult.duration}")
check("ult is flagged approximate", ult.approximate)
check("ult display carries the ~ marker", ult.display().startswith("~"),
      ult.display())

tm6 = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm6.note_frame()
tm6.handle_events(parser.parse_lines([f"(25:00) Ahri a utilisé {ahri_ult.name}"]))
ult3 = next(t for t in tm6.snapshot() if t.spell_key == "ULT")
check("ult uses rank-3 cooldown late game", abs(ult3.duration - 100) < 1,
      f"duration={ult3.duration}")

# ability haste seam (what the future scoreboard reader will feed)
settings._data["ability_haste"] = {"Ahri": 25}
tm7 = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm7.note_frame()
tm7.handle_events(parser.parse_lines([f"(25:00) Ahri a utilisé {ahri_ult.name}"]))
ult_h = next(t for t in tm7.snapshot() if t.spell_key == "ULT")
expected = 100 * 100 / 125.0
check("ability haste reduces ult cooldown", abs(ult_h.duration - expected) < 0.5,
      f"duration={ult_h.duration:.1f} want {expected:.1f}")
settings._data["ability_haste"] = {}

# summoner spells stay exact
check("summoner timers are not approximate",
      not next(t for t in tm3.snapshot() if t.spell_key == "Flash").approximate)


# --------------------------------------------- READY lingers, then disappears
# A spell coming back up is worth a few seconds of READY as confirmation, but an
# entry that stays for good tells you nothing about what is currently down.
def with_flash(ready_seconds_ago):
    """A manager holding one Flash timer that came up `ready_seconds_ago`."""
    manager = TimerManager(assets, settings)
    for _ in range(PRIME_FRAMES):
        manager.note_frame()
    manager.handle_events(parser.parse_lines(["(12:00) Ahri a utilisé Saut éclair"]))
    timer = next(iter(manager._timers.values()))
    timer.started_at = time.monotonic() - timer.duration - ready_seconds_ago
    return manager


settings._data["ready_linger_seconds"] = 5

fresh = with_flash(2.0)
shown = fresh.snapshot()
check("a spell that just came up is still shown", len(shown) == 1,
      f"{len(shown)} shown")
check("and it reads READY", bool(shown) and shown[0].display() == "READY",
      shown[0].display() if shown else "nothing")
fresh.tick()
check("a tick within the linger keeps it", len(fresh.snapshot()) == 1)

old = with_flash(6.0)
check("past the linger it is gone from the display", old.snapshot() == [],
      str([t.display() for t in old.snapshot()]))
old.tick()
check("and dropped from the manager, not merely hidden", not old._timers)

running = with_flash(-30.0)               # still 30s to go
running.tick()
check("a timer still counting down is never purged",
      len(running.snapshot()) == 1 and running.active_count() == 1)

# 0 means "no confirmation at all", but the audio cue must still fire: it is the
# whole point of the setting for anyone who plays with sound.
settings._data["ready_linger_seconds"] = 0
instant = with_flash(0.2)
kinds = [note.kind for note in instant.tick()]
check("with no linger the ready cue is still announced", "ready" in kinds,
      str(kinds))
check("and the entry goes in the same tick", not instant._timers)

# The existing checkbox keeps its meaning: hide READY, whatever the linger says.
settings._data["ready_linger_seconds"] = 5
settings._data["hide_ready_entries"] = True
hidden = with_flash(1.0)
check("hiding ready entries still wins over the linger", hidden.snapshot() == [])
check("but the entry lives until its linger runs out",
      len(hidden._timers) == 1)
settings._data["hide_ready_entries"] = False

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
