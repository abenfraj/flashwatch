# -*- coding: utf-8 -*-
"""Reading the enemy's lanes off the loading screen and the scoreboard.

Both surfaces list a team in lane order and neither labels the lanes, so the
*position* is the role. Everything here follows from that:

* a cell that reads nothing has to leave a hole. Closing the gap would rename
  four champions rather than one, which is why the readers are keyed by cell
  index and never by the order results happened to come out in;
* the scoreboard has no champion names in it -- it prints summoner names -- so
  its portraits are matched against the icons already cached for the overlay.
  That match is measured here against all 173 champions put through an unkind
  imitation of a scoreboard row, and against blurred noise standing in for the
  game world behind a frame aimed at nothing;
* the loading screen does print names, so it is read.

The thresholds in role_reader are the interesting part, and they are pinned from
both ends. Every champion must be recognised across the range of shapes a
hand-drawn frame actually takes, and no champion may ever be mistaken for
another -- a confidently wrong lane is worse than an unknown one, and it is the
failure a threshold set for accuracy alone quietly produces. Scenery is held to
the weaker promise the reader really makes: not that it never matches a cell, but
that it never produces a full enough reading twice running, which is what the
capture loop requires before believing anything.
"""
import sys, io, os, threading, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_roletest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

import cv2
import numpy as np

import role_reader
from message_parser import MessageParser
from riot_assets import RiotAssets
from roles import ROLES, assign_slots, role_from_word
from settings import DEFAULTS, Settings
from timer_manager import TimerManager

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


# ----------------------------------------------------------- the words
for word, expected in (("jgl", "JUNGLE"), ("jungle", "JUNGLE"), ("JG", "JUNGLE"),
                       ("top", "TOP"), ("Milieu", "MID"), ("bot", "ADC"),
                       ("adc", "ADC"), ("supp", "SUPPORT"), ("sup", "SUPPORT"),
                       # Teleport, to everyone, everywhere.
                       ("tp", ""), ("flash", ""), ("gg", "")):
    got = role_from_word(word)
    check(f"role_from_word({word!r}) -> {expected!r}", got == expected, got)


# ---------------------------------------------------- position is the role
check("five champions in order become five lanes",
      assign_slots(dict(enumerate(["Darius", "Viego", "Ahri", "Jinx", "Thresh"])))
      == {"Darius": "TOP", "Viego": "JUNGLE", "Ahri": "MID", "Jinx": "ADC",
          "Thresh": "SUPPORT"})
# The whole reason the readers are keyed by index: an unreadable mid must cost
# one unknown lane, not four wrong ones.
holed = assign_slots({0: "Darius", 1: "Viego", 3: "Jinx", 4: "Thresh"})
check("a hole leaves the lanes after it alone",
      holed == {"Darius": "TOP", "Viego": "JUNGLE", "Jinx": "ADC",
                "Thresh": "SUPPORT"}, str(holed))
check("the same champion in two cells throws the whole reading away",
      assign_slots({0: "Ahri", 1: "Ahri", 2: "Jinx"}) == {})
check("a sixth cell is not a lane", "SUPPORT" in assign_slots(
    {0: "Darius", 1: "Viego", 2: "Ahri", 3: "Jinx", 4: "Thresh", 5: "Lux"}).values())


# -------------------------------------------------- matching the portraits
assets = RiotAssets("fr_FR")
assets.bootstrap()
matcher = role_reader.IconMatcher(assets)
indexed = matcher.build()
check("the cached champion icons are indexed", indexed > 100, str(indexed))


def scoreboard_row(champion_id, *, width=150, height=52):
    """An unkind imitation of one scoreboard row.

    Deliberately not a clean paste of the reference icon: a real portrait is
    drawn at whatever size the HUD scale asks for, softened by that resize, dimmed
    while the player is dead, and set in a frame. If the match only survives a
    pixel-perfect copy it is not a match, it is a checksum.
    """
    icon = cv2.resize(cv2.imread(str(assets.icon_for_champion(champion_id))),
                      (41, 41))
    icon = cv2.GaussianBlur(icon, (3, 3), 0)
    icon = np.clip(icon.astype(np.int16) * 0.78 + 14, 0, 255).astype(np.uint8)
    row = np.full((height, width, 3), 26, np.uint8)
    cv2.rectangle(row, (4, 3), (50, 49), (120, 110, 80), 2)
    row[5:46, 7:48] = icon
    return row


# One row per champion, read through the same sliding search the real thing uses.
# Deliberately not a hand-cut crop handed to match(): where the portrait sits
# inside its cell is exactly what the reader does not know, and a test that
# aligns the window for it would pass while the search stride was far too coarse
# to find anything. That is not hypothetical -- it is what a stride of a fifth of
# the window did, and it cost half the roster.
missed, wrong = [], []
for champion_id in list(assets.champions):
    row = scoreboard_row(champion_id)
    found, _score = role_reader.champion_in_cell(
        row, (0, 0, row.shape[1], row.shape[0]), matcher)
    if found is None:
        missed.append(champion_id)
    elif found != champion_id:
        wrong.append((champion_id, found))
check("no champion is mistaken for another", not wrong, str(wrong[:4]))
check("every champion is recognised from a degraded portrait", not missed,
      f"{len(missed)} missed: {missed[:6]}")

# The frame is drawn by hand, so it is never the same shape twice. What is pinned
# here is the envelope it works over: the portrait filling anywhere from two
# thirds of its cell to all of it, and sitting anywhere in it rather than politely
# centred. That last part is the one that was wrong -- a window pinned to the
# middle of the cell read a twelfth of the roster as somebody else.
def placed(champion_id, side, cell_h, cell_w, top, left):
    icon = cv2.resize(cv2.imread(str(assets.icon_for_champion(champion_id))),
                      (side, side))
    icon = cv2.GaussianBlur(icon, (3, 3), 0)
    icon = np.clip(icon.astype(np.int16) * 0.8 + 12, 0, 255).astype(np.uint8)
    row = np.full((cell_h, cell_w, 3), 26, np.uint8)
    row[top:top + side, left:left + side] = icon
    return row


for side, cell_h, cell_w, top, left in ((41, 52, 150, 5, 7),
                                        (41, 56, 160, 5, 7),
                                        (41, 60, 170, 4, 7),
                                        (48, 56, 160, 4, 6),
                                        (56, 60, 180, 2, 10)):
    missed, wrong = [], []
    for champion_id in list(assets.champions):
        found, _score = role_reader.champion_in_cell(
            placed(champion_id, side, cell_h, cell_w, top, left),
            (0, 0, cell_w, cell_h), matcher)
        if found is None:
            missed.append(champion_id)
        elif found != champion_id:
            wrong.append((champion_id, found))
    check(f"a {side}px portrait in a {cell_w}x{cell_h} cell: all recognised, "
          f"none confused", not missed and not wrong,
          f"{len(missed)} missed, {wrong[:3]}")


# A full column, read the way the scoreboard is read.
team = ["Darius", "Viego", "Ahri", "Jinx", "Thresh"]
column = np.vstack([scoreboard_row(cid, width=160, height=56) for cid in team])
slots = role_reader.champions_by_icon(column, matcher)
check("a column of five reads as five lanes in order",
      slots == dict(enumerate(team)), str(slots))
check("and that reading is usable", role_reader.usable(slots))

# The same column with one row blanked: a hole, not a shift.
gapped = column.copy()
gapped[2 * 56:3 * 56] = 26
slots = role_reader.champions_by_icon(gapped, matcher)
check("an unreadable row leaves its lane empty and moves no other",
      slots.get(0) == "Darius" and slots.get(3) == "Jinx" and 2 not in slots,
      str(slots))

# What the frame holds when Tab is not held, or when it is aimed at nothing.
#
# The thresholds admit every real portrait, which means the odd scene cell gets
# through them too -- see role_reader for why no pair of thresholds separates the
# two. So what is pinned here is what the reader actually promises: scenery does
# not produce a *usable* reading, and never the same one twice running, which is
# the pair of conditions the capture loop requires before a lane is believed.
rng = np.random.default_rng(4)
usable_scenes = repeated = 0
previous = None
for seed in range(60):
    scenery = cv2.GaussianBlur(
        rng.integers(0, 255, (280, 160, 3), dtype=np.uint8), (0, 0),
        int(rng.integers(3, 16)))
    slots = role_reader.champions_by_icon(scenery, matcher)
    usable_scenes += role_reader.usable(slots)
    repeated += bool(slots) and slots == previous
    previous = slots
check("scenery hardly ever produces a full enough reading to offer",
      usable_scenes <= 1, f"{usable_scenes} of 60 frames")
check("and never the same reading twice running, which is what is required",
      repeated == 0, f"{repeated} repeats")

# The search is several hundred window positions per lane, which is exactly why
# the cadence it runs at is measured in seconds. Pinned generously -- this is a
# guard against the search growing by an order of magnitude, not a benchmark.
started = time.perf_counter()
for _ in range(5):
    role_reader.champions_by_icon(column, matcher)
elapsed_ms = (time.perf_counter() - started) * 1000 / 5
check("a full five-lane read stays well inside its cadence", elapsed_ms < 250,
      f"{elapsed_ms:.0f} ms")


# ------------------------------------------------ reading the loading screen
parser = MessageParser(assets)
WIDTH, HEIGHT = 1250, 260
STEP = WIDTH // 5


def name_row(index, text):
    """One OCR row, placed under the card in cell ``index``."""
    return (text, (index * STEP + 40, 200, 120, 22))


slots = role_reader.champions_by_name(
    [name_row(i, name) for i, name in enumerate(
        ["Darius", "Viego", "Ahri", "Jinx", "Thresh"])],
    WIDTH, HEIGHT, parser.champion_named)
check("champion names read left to right become the five lanes",
      slots == dict(enumerate(team)), str(slots))

# The names are localised and OCR mangles them; both have to survive.
slots = role_reader.champions_by_name(
    [name_row(0, "Dari us"), name_row(2, "Ahrl"), name_row(4, "Thresh")],
    WIDTH, HEIGHT, parser.champion_named)
check("a mangled name still lands in its own cell",
      slots == {0: "Darius", 2: "Ahri", 4: "Thresh"}, str(slots))

# Summoner names sit on the same cards and must resolve to nobody.
slots = role_reader.champions_by_name(
    [name_row(0, "xXShadowSlayerXx"), name_row(1, "Bob le jardinier")],
    WIDTH, HEIGHT, parser.champion_named)
check("a summoner name is not a champion", slots == {}, str(slots))
check("nor is a two-letter fragment",
      parser.champion_named("ah") is None
      and parser.champion_named("") is None)


# ------------------------------------------------ handing it to the timers
settings = Settings.__new__(Settings)
settings._path = None
settings._lock = threading.RLock()
settings._data = dict(DEFAULTS)
settings.save = lambda: None
manager = TimerManager(assets, settings)

check("the manager takes a reading and returns what was new",
      manager.set_roles(dict(enumerate(team)), source="loading") == len(team))
check("...and learns nothing from the same reading twice",
      manager.set_roles(dict(enumerate(team)), source="scoreboard") == 0)
check("a lane resolves to the champion who plays it",
      manager.champion_for_role("JUNGLE") == "Viego",
      str(manager.champion_for_role("JUNGLE")))
check("the roster is the whole team, in lane order",
      manager.roster() == team, str(manager.roster()))

# The user's own answer is better information than the screen's.
manager.set_role("Ahri", "SUPPORT")
manager.set_roles({0: "Darius", 1: "Viego", 2: "Ahri", 3: "Jinx", 4: "Thresh"},
                  source="scoreboard")
check("a role set by hand is never overwritten by a reader",
      manager.role_of("Ahri") == "SUPPORT", manager.role_of("Ahri"))

check("a new game forgets the roles with everything else",
      (manager.reset(reason="test"), manager.roster())[1] == [],
      str(manager.roster()))
check("every lane in the table is one the sort order knows",
      all(role in ROLES for role in
          {"TOP", "JUNGLE", "MID", "ADC", "SUPPORT"}))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
