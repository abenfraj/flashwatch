# -*- coding: utf-8 -*-
"""Covers the real spell-tracker ping format observed in the Practice Tool:

    Joueur (Champion): Attendez Champion Summoner - X sec.

Notably the author prefix must be *stripped*, not treated as proof a human typed
the line -- the game attributes ping messages to the player who pinged.
"""
import sys, io, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from riot_assets import RiotAssets
from message_parser import MessageParser, looks_like_chat_line
from timer_manager import TimerManager, PRIME_FRAMES
from settings import Settings, DEFAULTS

assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)

settings = Settings.__new__(Settings)
settings._path = None
settings._lock = threading.RLock()
settings._data = dict(DEFAULTS)
settings._data["assume_cosmic_insight"] = False
settings._data["assume_ionian_boots"] = False
settings.save = lambda: None

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


flash = assets.spells["Flash"].name          # Saut éclair
tp = assets.spells["Teleport"].name          # Téléportation
smite = assets.spells["Smite"].name          # Châtiment
ahri_ult = assets.champions["Ahri"].ultimate.name

# ---------------------------------------------------------------- parsing
CASES = [
    # (line, expected champion, expected spell key, expected remaining)
    (f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec.", "Ahri", "Flash", 245),
    (f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec", "Ahri", "Flash", 245),
    (f"Joueur (Ahri): Attendez Darius {tp} - 12 sec.", "Darius", "Teleport", 12),
    (f"Bob (Jinx): Attendez Viego {smite} - 90 sec.", "Viego", "Smite", 90),
    # multi-word champion name
    (f"Bob (Jinx): Attendez Master Yi {smite} - 45 sec.", "MasterYi", "Smite", 45),
    # ultimate, which the stated number makes exact
    (f"Bob (Jinx): Attendez Ahri {ahri_ult} - 60 sec.", "Ahri", "ULT", 60),
    # no author prefix at all
    (f"Attendez Ahri {flash} - 300 sec.", "Ahri", "Flash", 300),
    # with a chat timestamp too
    (f"(14:23) Ayoub (Lux): Attendez Ahri {flash} - 30 sec.", "Ahri", "Flash", 30),
    # OCR mangling in the number and the name
    (f"Ayoub (Lux): Attendez Ahrl {flash} - 2O5 sec.", "Ahri", "Flash", 205),
    # no dash
    (f"Ayoub (Lux): Attendez Ahri {flash} 180 sec.", "Ahri", "Flash", 180),
    # unit clipped by OCR. Accepted only after a dash, which is strong enough
    # context; a bare "s" with no dash matches letters inside champion names.
    (f"Ayoub (Lux): Attendez Rengar {flash} - 245 s.", "Rengar", "Flash", 245),
    (f"Ayoub (Lux): Attendez Rengar {flash} - 245 s", "Rengar", "Flash", 245),
    # Names whose letters look like digits used to parse as a bogus count.
    (f"Ayoub (Lux): Attendez Aphelios {flash} - 245 sec.", "Aphelios", "Flash", 245),
    (f"Ayoub (Lux): Attendez Ziggs {flash} - 245 sec.", "Ziggs", "Flash", 245),
    (f"Ayoub (Lux): Attendez Miss Fortune {flash} - 245 sec.",
     "MissFortune", "Flash", 245),
]

for line, champ, spell_key, remaining in CASES:
    event = parser.parse_line(line)
    ok = (event is not None and event.champion_id == champ
          and event.spell_key == spell_key
          and event.remaining_seconds == remaining)
    detail = (f"{event.champion_id}/{event.spell_key} {event.remaining_seconds}s"
              if event else "no match")
    check(f"parse {line!r}", ok, detail)

REJECT = [
    "Ayoub (Lux): gg wp",
    "Ayoub (Lux): attendez les gars",             # no spell, no number
    "Ennemi manquant !",
    f"Ayoub (Lux): Attendez Ahri {flash} - 9999 sec.",   # implausible cooldown
    "Ayoub (Lux): Attendez 30 sec",                # no champion or spell
]
for line in REJECT:
    check(f"reject {line!r}", parser.parse_line(line) is None)

# ------------------------------------------------- chat-line recognition
# These lines carry no timestamp, so region detection must still recognise them.
check("wait line recognised as chat without a timestamp",
      looks_like_chat_line(f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec."))
check("plain player chat recognised as chat (for region detection)",
      looks_like_chat_line("Ayoub (Lux): gg wp"))
check("scenery noise not recognised as chat",
      not looks_like_chat_line("x 3.. tiers"))

# ------------------------------------------------------------- timers
tm = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm.note_frame()

tm.handle_events(parser.parse_lines([f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec."]))
timer = next((t for t in tm.snapshot() if t.spell_key == "Flash"), None)
check("stated cooldown creates a timer", timer is not None)
if timer:
    check("remaining matches the stated number", abs(timer.remaining() - 245) < 2,
          f"{timer.remaining():.0f}s")
    check("stated timers are exact, not approximate", not timer.approximate)
    check("full Flash cooldown is used as the duration",
          abs(timer.duration - 300) < 1, f"duration={timer.duration}")
    check("display has no ~ marker", not timer.display().startswith("~"),
          timer.display())

# Re-reading the same line must not disturb anything.
for _ in range(10):
    tm.handle_events(parser.parse_lines([f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec."]))
check("same line re-read does not duplicate", tm.active_count() == 1)

# A repeat ping reports a smaller number; it must NOT restart or nudge the
# running countdown -- the first ping is closest to the real cast.
running = next(t for t in tm.snapshot() if t.spell_key == "Flash")
before = running.remaining()
tm.handle_events(parser.parse_lines([f"Ayoub (Lux): Attendez Ahri {flash} - 240 sec."]))
after = next(t for t in tm.snapshot() if t.spell_key == "Flash").remaining()
check("a repeat ping leaves the timer untouched", abs(after - before) < 1.5,
      f"{before:.0f}s -> {after:.0f}s")
check("repeat ping does not add a second entry", tm.active_count() == 1)

# A genuine recast reports materially MORE time, and must take over.
tm.handle_events(parser.parse_lines([f"Ayoub (Lux): Attendez Ahri {flash} - 300 sec."]))
recast = next(t for t in tm.snapshot() if t.spell_key == "Flash")
check("a recast restarts the timer", abs(recast.remaining() - 300) < 2,
      f"{recast.remaining():.0f}s")

# An ultimate reported this way is exact too.
tm.handle_events(parser.parse_lines([f"Bob (Jinx): Attendez Ahri {ahri_ult} - 60 sec."]))
ult = next(t for t in tm.snapshot() if t.spell_key == "ULT")
check("stated ultimate is exact", not ult.approximate and abs(ult.remaining() - 60) < 2,
      f"{ult.remaining():.0f}s approx={ult.approximate}")

# "0 sec" is treated as a misread, not as "ready". OCR drops the leading digit of
# faded text ("100 sec" -> "00 sec"), and acting on that would wipe a live timer,
# so such a line is ignored and the running timer is preserved.
before_zero = next(t for t in tm.snapshot() if t.spell_key == "Flash").remaining()
tm.handle_events(parser.parse_lines([f"Ayoub (Lux): Attendez Ahri {flash} - 0 sec."]))
still = next((t for t in tm.snapshot() if t.spell_key == "Flash"), None)
check("a 0 sec reading is rejected, not trusted", still is not None)
check("the running timer survives a 0 sec misread",
      still is not None and abs(still.remaining() - before_zero) < 2,
      f"{before_zero:.0f}s -> {still.remaining():.0f}s" if still else "gone")

# ------------------------------------- late reads must not lose accuracy
# The point of the absolute ready-time model: a line read well after the ping
# should still produce the correct remaining time.
tm_late = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm_late.note_frame()

# Establish the game clock at 10:00 from an unrelated timestamped line, then
# deliver a ping stamped 9:30 -- i.e. read 30s late -- claiming 245s left.
tm_late.handle_events(parser.parse_lines([f"(10:00) Jinx a utilisé {smite}"]))
tm_late.handle_events(parser.parse_lines(
    [f"(9:30) Ayoub (Lux): Attendez Ahri {flash} - 245 sec."]))
late = next((t for t in tm_late.snapshot() if t.spell_key == "Flash"), None)
check("a ping read 30s late is corrected", late is not None
      and abs(late.remaining() - 215) < 3,
      f"{late.remaining():.0f}s want ~215" if late else "no timer")
check("absolute ready time is recorded", late is not None
      and late.ready_at_game is not None
      and abs(late.ready_at_game - (570 + 245)) < 1,
      f"ready_at={late.ready_at_game}" if late else "")

# The oldest ping wins: a newer ping for the same spell agrees on ready time and
# must not disturb the timer.
before_late = late.remaining()
tm_late.handle_events(parser.parse_lines(
    [f"(9:50) Ayoub (Lux): Attendez Ahri {flash} - 225 sec."]))
after_late = next(t for t in tm_late.snapshot() if t.spell_key == "Flash").remaining()
check("a consistent later ping does not disturb the timer",
      abs(after_late - before_late) < 2,
      f"{before_late:.0f}s -> {after_late:.0f}s")

# A ping whose cooldown already elapsed must not create a timer at all.
tm_late.handle_events(parser.parse_lines(
    [f"(2:00) Ayoub (Lux): Attendez Darius {tp} - 30 sec."]))
check("an already-expired ping creates no timer",
      all(t.champion_id != "Darius" for t in tm_late.snapshot()))

# --------------------------------------------- Cosmic Insight assumption
# With the rune assumed, Flash is 246s not 300s. The *stated* remaining time is
# still authoritative -- the rune only changes the full cooldown, which is what
# places the marker along the bar.
settings._data["assume_cosmic_insight"] = True
tm_rune = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm_rune.note_frame()
tm_rune.handle_events(parser.parse_lines(
    [f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec."]))
runed = next(t for t in tm_rune.snapshot() if t.spell_key == "Flash")
check("rune shortens the full cooldown", abs(runed.duration - 246) < 1,
      f"duration={runed.duration}")
check("stated remaining is still honoured with the rune",
      abs(runed.remaining() - 245) < 2, f"{runed.remaining():.0f}s")
# 245 of 246 elapsed = marker at the very start of the track, not 1/5 along.
progress = (runed.duration - runed.remaining()) / runed.duration
check("marker starts at the beginning of the track", progress < 0.02,
      f"progress={progress:.3f}")
settings._data["assume_cosmic_insight"] = False

# Pre-existing chat history must still not create timers.
tm2 = TimerManager(assets, settings)
history = parser.parse_lines([f"Ayoub (Lux): Attendez Darius {tp} - 200 sec."])
for _ in range(PRIME_FRAMES):
    tm2.note_frame()
    tm2.handle_events(history)
check("priming still suppresses pre-existing wait lines", tm2.active_count() == 0)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
