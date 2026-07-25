# -*- coding: utf-8 -*-
"""The same messages, on an English client.

Riot's data is downloaded per locale, so an English client names spells "Flash"
and "Teleport" where a French one says "Saut éclair" and "Téléportation". The
wordings around them differ too, and the game prints the cast announcement in the
simple past ("Ahri used Flash") as well as with "has used".

Rejections are asserted alongside the matches: "used" is an ordinary English word,
and accepting it as a system verb must not turn typed chat into timers.
"""
import sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from message_parser import MessageParser
from riot_assets import RiotAssets

started = time.time()
assets = RiotAssets(locale="en_US")
assets.bootstrap()
print(f"  en_US data ready in {time.time() - started:.1f}s "
      f"({len(assets.champions)} champions)\n")
parser = MessageParser(assets)

ahri_ult = assets.champions["Ahri"].ultimate.name          # "Spirit Rush"

# (line, expected (champion_id, spell_key) or None to reject, game time or None)
CASES = [
    # --- cast announcements: printed by the game, for enemies only ------
    ("(7:00) Ahri used Flash", ("Ahri", "Flash"), 420),
    ("(7:00) Ahri has used Flash", ("Ahri", "Flash"), 420),
    ("(12:31) Darius used Teleport", ("Darius", "Teleport"), 751),
    ("(13:02) Viego used Smite", ("Viego", "Smite"), 782),
    ("(2:05) Jinx used Heal", ("Jinx", "Heal"), 125),
    ("(9:31) Lee Sin used Smite", ("LeeSin", "Smite"), 571),
    (f"(31:02) Ahri used {ahri_ult}", ("Ahri", "ULT"), 1862),
    ("(31:02) Ahri used her ultimate", ("Ahri", "ULT"), 1862),
    # --- cooldown pings: the game states the number ---------------------
    ("(12:34) Kevin (Jinx): Wait Darius Flash - 245 sec.",
     ("Darius", "Flash"), 754),
    ("(12:34) Kevin (Jinx): Wait for Darius Flash - 245 sec.",
     ("Darius", "Flash"), 754),
    ("(12:34) Kevin (Jinx): Wait Darius's Flash - 245 sec.",
     ("Darius", "Flash"), 754),
    ("(12:34) Kevin (Jinx): Wait Miss Fortune Teleport - 300 seconds",
     ("MissFortune", "Teleport"), 754),
    # --- must be rejected ------------------------------------------------
    ("Kevin (Jinx): gg wp", None, None),
    ("Kevin (Jinx): ahri used flash", None, None),       # a player typing it
    ("Kevin (Jinx): that flash used to be up", None, None),
    ("(5:00) used Flash", None, None),                   # no champion
    ("(12:00) Ahri uses Flash", None, None),             # not the system wording
    ("Enemy missing!", None, None),
    ("(3:12) You have slain Ahri", None, None),
]

REMAINING = {
    "(12:34) Kevin (Jinx): Wait Darius Flash - 245 sec.": 245,
    "(12:34) Kevin (Jinx): Wait for Darius Flash - 245 sec.": 245,
    "(12:34) Kevin (Jinx): Wait Darius's Flash - 245 sec.": 245,
    "(12:34) Kevin (Jinx): Wait Miss Fortune Teleport - 300 seconds": 300,
}

ok = 0
for line, expected, game_time in CASES:
    event = parser.parse_line(line)
    good = (event is not None) == (expected is not None)
    note = ""
    if good and event is not None:
        if (event.champion_id, event.spell_key) != expected:
            good = False
            note += (f"  << got {(event.champion_id, event.spell_key)}, "
                     f"want {expected}")
        if game_time is not None and event.game_time != game_time:
            good = False
            note += f"  << time {event.game_time}, want {game_time}"
        want_left = REMAINING.get(line)
        if want_left is not None and event.remaining_seconds != want_left:
            good = False
            note += f"  << left {event.remaining_seconds}, want {want_left}"
    ok += good
    detail = ""
    if event is not None:
        detail = (f" -> {event.champion_id}/{event.spell_key} "
                  f"({event.spell_name}) t={event.game_time}"
                  f" left={event.remaining_seconds}")
    print(f"{'PASS' if good else 'FAIL'}  {line!r}{detail}{note}")

# Spell names of the *other* locale still resolve: the index carries the English
# canonical name whatever data was downloaded, which is what lets a player run an
# English client with the app left on French data.
french = RiotAssets(locale="fr_FR")
french.bootstrap()
cross = MessageParser(french).parse_line("(7:00) Ahri has used Flash")
ok += bool(cross and (cross.champion_id, cross.spell_key) == ("Ahri", "Flash"))
print(f"{'PASS' if cross else 'FAIL'}  English spell name read with French data"
      f" -> {cross.spell_name if cross else None}")

total = len(CASES) + 1
print(f"\n{ok}/{total} cases behaved as expected")
sys.exit(0 if ok == total else 1)
