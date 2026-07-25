# -*- coding: utf-8 -*-
"""Reading team colour off the screen, for the one wording that needs it.

Two forms reach the parser and they are not equal. A real game only ever prints
the cast announcement ("Ahri a utilise Saut eclair"), and only for enemies, so it
is taken at face value. The stated-cooldown form ("Attendez Ahri Saut eclair -
245 sec.") states a time without saying whose it is; the only thing on screen that
distinguishes an enemy is that the game draws enemy champion names red.

That form is also what a player types by hand to check the OCR reads their chat --
and typed text is not red. Hence the option, and hence it being off by default;
both directions are asserted at the bottom of this file.

Three outcomes are asserted, not two. The hard case is chat drawn straight over
the game with no backing panel: over the red base or a particle burst every pixel
of the row is red-dominant, plain white text included. Answering "ally" there
would silently drop real enemy pings, so such a row is declared unreadable and
retried on a later frame instead.
"""
import sys, io, os, queue

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_colourtest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

from message_parser import MessageParser
from ocr import (COLOUR_ALLY, COLOUR_ENEMY, COLOUR_UNKNOWN, CaptureWorker,
                 name_colour_verdict, row_crop)
from riot_assets import RiotAssets
from settings import Settings

FONT = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 17)
ENEMY_RED = (232, 64, 56)          # enemy champion name
ALLY_BLUE = (120, 190, 240)        # ally champion name
CHAT_WHITE = (238, 240, 245)
ROW_W, ROW_H = 520, 34

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def backdrop(kind):
    """What sits behind the text: a dark panel, or actual game art."""
    if kind == "dark":
        return np.full((ROW_H, ROW_W, 3), 14, np.uint8)
    if kind == "red":                    # base / lava: broad red, plus thin bars
        art = np.full((ROW_H, ROW_W, 3), (34, 28, 150), np.uint8)
        cv2.rectangle(art, (0, 4), (ROW_W, 12), (40, 40, 205), -1)
        cv2.rectangle(art, (60, 20), (300, 24), (30, 30, 230), -1)
        return cv2.GaussianBlur(art, (0, 0), 1.2)
    if kind == "redspeck":               # a red particle burst over the chat
        art = np.full((ROW_H, ROW_W, 3), (34, 28, 150), np.uint8)
        rng = np.random.default_rng(3)
        for _ in range(40):
            x, y = int(rng.integers(0, ROW_W)), int(rng.integers(0, ROW_H))
            cv2.circle(art, (x, y), int(rng.integers(2, 6)), (60, 60, 245), -1)
        return art
    if kind == "bright":                 # bright, non-red terrain
        return cv2.GaussianBlur(
            np.full((ROW_H, ROW_W, 3), (120, 190, 150), np.uint8), (0, 0), 1.5)
    raise ValueError(kind)


def make_row(segments, kind="dark", opacity=1.0, panel=False):
    """One chat row; ``segments`` is [(text, rgb), ...] drawn left to right."""
    base = backdrop(kind)
    if panel:                            # translucent dark chat panel over the art
        base = cv2.addWeighted(base, 0.45, np.full_like(base, 10), 0.55, 0)
    image = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))
    layer = image.copy()
    draw = ImageDraw.Draw(layer)
    x = 4
    for text, colour in segments:
        draw.text((x + 1, 7), text, font=FONT, fill=(0, 0, 0))   # drop shadow
        draw.text((x, 6), text, font=FONT, fill=colour)
        x += int(FONT.getlength(text))
    image = Image.blend(image, layer, max(0.05, min(1.0, opacity)))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


PING = [("Kevin (Jinx): Attendez ", CHAT_WHITE), ("Darius", ENEMY_RED),
        (" Saut eclair - 245 sec.", CHAT_WHITE)]
ALLY = [("Kevin (Jinx): Attendez ", CHAT_WHITE), ("Lux", ALLY_BLUE),
        (" Barriere - 150 sec.", CHAT_WHITE)]
PLAIN = [("Kevin (Jinx): Attendez Ahri Saut eclair - 120 sec.", CHAT_WHITE)]

CASES = [
    # A red name must be recognised through every way chat gets drawn.
    ("enemy ping on the chat panel",     make_row(PING, "dark"),            COLOUR_ENEMY),
    ("enemy ping, faded transient",      make_row(PING, "dark", 0.65),      COLOUR_ENEMY),
    ("enemy ping over bright terrain",   make_row(PING, "bright", 0.9),     COLOUR_ENEMY),
    ("enemy ping, panel over the base",  make_row(PING, "red", 1.0, panel=True), COLOUR_ENEMY),
    # No red name: an ally's cooldown, whoever pinged it.
    ("ally name in the ally colour",     make_row(ALLY, "dark"),            COLOUR_ALLY),
    ("no coloured name at all",          make_row(PLAIN, "dark"),           COLOUR_ALLY),
    # Red backdrop, no panel: the colour proves nothing either way.
    ("enemy ping over the red base",     make_row(PING, "red", 0.9),        COLOUR_UNKNOWN),
    ("ally line over the red base",      make_row(ALLY, "red", 0.75),       COLOUR_UNKNOWN),
    ("ally line over red particles",     make_row(ALLY, "redspeck", 0.75),  COLOUR_UNKNOWN),
    ("white line over the red base",     make_row(PLAIN, "red", 0.75),      COLOUR_UNKNOWN),
    ("white line over red particles",    make_row(PLAIN, "redspeck", 0.8),  COLOUR_UNKNOWN),
]

for name, image, expected in CASES:
    got = name_colour_verdict(image)
    check(f"{name} -> {expected}", got == expected, f"got {got}")

# Degenerate inputs must never claim to know.
check("an empty crop is unreadable",
      name_colour_verdict(np.zeros((0, 0, 3), np.uint8)) == COLOUR_UNKNOWN)
check("a flat crop with no text is unreadable",
      name_colour_verdict(np.full((30, 200, 3), 40, np.uint8)) == COLOUR_UNKNOWN)

# --------------------------------------------------------- the worker's decision
assets = RiotAssets(locale="fr_FR")
assets.bootstrap()
parser = MessageParser(assets)
settings = Settings()
settings.set("require_enemy_colour", True, save=False)
worker = CaptureWorker(settings, parser, queue.Queue())

ENEMY_LINE = "(12:34) Kevin (Jinx): Attendez Darius Saut eclair - 245 sec."
ALLY_LINE = "(12:34) Kevin (Jinx): Attendez Lux Barriere - 150 sec."
enemy_row = make_row(PING, "dark")
ally_row = make_row(ALLY, "dark")
unreadable_row = make_row(PING, "red", 0.9)
full_box = (0, 0, ROW_W, ROW_H)

event, decided = worker._event_for_row(enemy_row, ENEMY_LINE, full_box)
check("an enemy ping starts a timer",
      event is not None and event.champion_id == "Darius" and decided,
      str(event.champion_name if event else None))

# A cast announcement is printed by the game for enemies only, so it is taken at
# face value whatever colour it is drawn in -- there is no ally version of it.
CAST_LINE = "(12:34) Darius a utilise Saut eclair"
event, decided = worker._event_for_row(ally_row, CAST_LINE, full_box)
check("a cast announcement needs no red name",
      event is not None and event.champion_id == "Darius" and decided,
      str(event.champion_name if event else None))

event, decided = worker._event_for_row(ally_row, ALLY_LINE, full_box)
check("an ally's cooldown starts nothing", event is None)
check("and the line is settled, not retried", decided)
check("the ignored line is reported for the debug tab",
      ALLY_LINE in worker.status.colour_rejected, str(worker.status.colour_rejected))

event, decided = worker._event_for_row(unreadable_row, ENEMY_LINE, full_box)
check("an unreadable line starts nothing for now", event is None)
check("but is left to be judged again on a later frame", not decided)
check("and is not paraded as an ally in the debug tab",
      len(worker.status.colour_rejected) == 1, str(worker.status.colour_rejected))

# --------------------------------------------------- what the default must be
# In a real game the only line that appears is the cast announcement, which the
# game prints for enemies only. The stated-cooldown wording is in practice typed
# by hand to check that the OCR reads the chat -- and typed text is never drawn
# red, so a colour test left on would reject exactly the line used for testing.
from settings import DEFAULTS

check("the colour test is off by default",
      DEFAULTS["require_enemy_colour"] is False)
settings.set("require_enemy_colour", DEFAULTS["require_enemy_colour"],
             save=False)
typed = make_row([("Ayoub (Lux): Attendez Darius Saut eclair - 245 sec.",
                   CHAT_WHITE)])
check("a hand-typed test line is not red",
      name_colour_verdict(typed) == COLOUR_ALLY)
event, decided = worker._event_for_row(typed, ENEMY_LINE, full_box)
check("but with the defaults it still starts a timer",
      event is not None and decided,
      "the OCR test line would be rejected" if event is None else "")

# The option is the escape hatch when the wording *is* about somebody's own
# cooldown: unchecking it restores the plain behaviour.
settings.set("require_enemy_colour", False, save=False)
event, decided = worker._event_for_row(ally_row, ALLY_LINE, full_box)
check("unchecking the option accepts the line again",
      event is not None and event.champion_id == "Lux" and decided,
      str(event.champion_name if event else None))
settings.set("require_enemy_colour", True, save=False)

# The row's box is where the colour is read from, so it has to be honoured.
frame = np.zeros((200, 600, 3), np.uint8)
frame[120:120 + ROW_H, 40:40 + ROW_W] = enemy_row
event, _decided = worker._event_for_row(
    frame, ENEMY_LINE, (40, 120, ROW_W, ROW_H))
check("the colour is read at the row's own position, wherever that is",
      event is not None)
event, decided = worker._event_for_row(frame, ENEMY_LINE, (40, 5, 100, 20))
check("a box pointing at blank pixels yields no timer", event is None)
check("row_crop clamps a box that runs past the frame edge",
      row_crop(frame, (595, 195, 40, 40)).size > 0)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
