# -*- coding: utf-8 -*-
"""Spell-tracker pings, from rendered pixels through to a resolved event.

Pinging a spell that is *off* cooldown makes the game print the cast wording,
attributed to the player who pinged:

    02:21 Nelo Angelo (Ambessa): Morgana a utilise Saut eclair

That author prefix used to disqualify the line, which silently disabled the
entire ping path -- the parser resolved champion and spell correctly and then
threw the result away. The unit-level cases live in test_message_parser.py; this
suite exists because the replacement rule leans on *capitalisation* to tell the
game's wording from a player typing the same claim, and capitalisation is a
property of what OCR returns, not of a hand-typed string. Asserting it only on
literals would prove nothing about the real pipeline.

Lines are taken verbatim from a real game, kill feed and all, so the surrounding
noise has to stay unparsed at the same time.
"""
import sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _bootstrap  # noqa: F401,E402 -- puts src/ on the import path

from message_parser import MessageParser              # noqa: E402
from ocr import OcrEngine                             # noqa: E402
from riot_assets import RiotAssets                    # noqa: E402
from synthetic_frames import make_frame               # noqa: E402

CHAT = [
    "00:15 asian jesus (Sion) a choisi Chute d'Icathia.",
    "01:21 SlowGame (Vel'Koz) a fait couler le premier sang !",
    "02:04 Lorem Ipsen (Jhin) a tué Locke (Locke) et réussi un doublé !",
    "02:21 Nelo Angelo (Ambessa): Morgana a utilisé Saut éclair",
    "02:22 Nelo Angelo (Ambessa): Morgana a utilisé Boule de neige",
]

# Snowball is ARAM-only and was absent from the cooldown table, which is a
# second, independent reason this line produced nothing.
WANT = {("Morgana", "Flash"), ("Morgana", "Snowball")}

failures = 0


def check(name, cond, extra=""):
    global failures
    failures += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}{extra}")


assets = RiotAssets(locale="fr_FR")
assets.bootstrap(lambda _m: None)
parser = MessageParser(assets)
engine = OcrEngine()
engine.load()

for width, height in ((1920, 1080), (2560, 1440), (3840, 2160)):
    frame, (x, y, w, h) = make_frame(width, height, lines=CHAT)
    pad = 12
    crop = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    read, elapsed = engine.read_lines(crop)

    events = [event for event in (parser.parse_line(line) for line in read)
              if event is not None]
    got = {(event.champion_id, event.spell_key) for event in events}

    label = f"{width}x{height}"
    check(f"{label} pings resolved", WANT <= got,
          f"  << missing {sorted(WANT - got)} from {sorted(got)}"
          if not WANT <= got else f"  ({elapsed:.0f}ms)")
    # The kill feed names champions and the "a choisi" lines look chatty; both
    # must stay silent, or the overlay fills with timers nobody cast.
    check(f"{label} no phantom events", not (got - WANT),
          f"  << spurious {sorted(got - WANT)}" if got - WANT else "")

print(f"\n{'all good' if not failures else str(failures) + ' failing check(s)'}")
sys.exit(1 if failures else 0)
