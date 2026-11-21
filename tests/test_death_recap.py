# -*- coding: utf-8 -*-
"""The death recap: which enemy summoner spells the panel shows.

The panel appears at the top left when the player dies: one row per enemy who
dealt damage -- portrait in a red frame, damage, and the icons of what did it --
then the player's own row in a gold frame. A summoner spell in an enemy row was
used; one in the gold row is the player's and must never become a timer.

Two real frames from a ratirl stream. At 13:45: Taliyah, Zed and a non-champion
source above the player's Twitch, and no enemy summoner -- but Taliyah's Q icon
scores as high against Ghost as a real Ignite does against Ignite, which is why
only spells that deal damage are ever looked for. At 13:53: Thresh's row shows
his Ignite, the real positive. The other positives are the first frame with a
Data Dragon icon pasted where the panel draws them.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

import cv2
import numpy as np

import death_recap
import role_reader
from ocr import OcrEngine
from riot_assets import RiotAssets

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


FIXTURES = Path(__file__).resolve().parent / "fixtures"
PANEL = cv2.imread(str(FIXTURES / "death-recap-1080p.png"))
IGNITE_PANEL = cv2.imread(str(FIXTURES / "death-recap-ignite-1080p.png"))
NO_PANEL = cv2.imread(str(FIXTURES / "no-death-recap-1080p.png"))
WINDOW = (0, 0, 1920, 1080)

assets = RiotAssets("en_US")
assets.bootstrap()
# Icons are cached by whatever ran the app before; on a clean checkout (the
# release runner) fetch the missing ones, which is a no-op when all are there.
assets.download_icons()
champions = role_reader.IconMatcher(assets)
champions.build()
spells = death_recap.SpellIconMatcher(assets)
check("summoner icons indexed", spells.build() >= 9)
engine = OcrEngine()
engine.load()


def read_text(image):
    return engine.read_line(image)


ROSTER = {"Taliyah": frozenset({"Flash", "Ghost"}),
          "Zed": frozenset({"Flash", "Ignite"}),
          "Gangplank": frozenset({"Flash", "Ignite"}),
          "Ekko": frozenset({"Flash", "Ignite"}),
          "Thresh": frozenset({"Flash", "Ignite"})}

# ------------------------------------------------------------ the fight's length
check("24.7s", death_recap.parse_fight_seconds("24.7s") == 24.7)
check("a comma and a space", death_recap.parse_fight_seconds("24,7 s") == 24.7)
check("the first duration on a row wins",
      death_recap.parse_fight_seconds("24.7s 499 0.0s 0.0s") == 24.7)
check("zero is not a fight", death_recap.parse_fight_seconds("0.0s") is None)
check("a bare number is not a duration",
      death_recap.parse_fight_seconds("499") is None)

# ------------------------------------------------------------ where to look
x, y, w, h = death_recap.search_area(WINDOW)
check("the area is the window's top left", (x, y) == (0, 0) and w < 500 and h <= 540,
      str((x, y, w, h)))
check("the area follows the window",
      death_recap.search_area((100, 50, 2560, 1440))[:2] == (100, 50))

# ------------------------------------------------------------ the real panel
reading = death_recap.read(PANEL, champions, spells, ROSTER, read_text)
check("the panel is found", reading is not None)
if reading is not None:
    enemies = {row.champion_id for row in reading.rows if row.enemy}
    check("Taliyah and Zed are enemy rows", {"Taliyah", "Zed"} <= enemies,
          str(enemies))
    check("the player's own row is never an enemy",
          not any(row.champion_id == "Twitch" and row.enemy for row in reading.rows))
    check("no enemy summoner is shown", reading.enemy_spells == frozenset(),
          str(reading.enemy_spells))
    check("the fight lasted 24.7 s", reading.fight_seconds == 24.7,
          str(reading.fight_seconds))

open_field = death_recap.read(PANEL, champions, spells, None, read_text)
check("found without a roster too", open_field is not None)
if open_field is not None:
    check("without a roster the gold row is still the player's",
          not any(row.champion_id == "Twitch" and row.enemy
                  for row in open_field.rows))
    check("without a roster no enemy summoner either",
          open_field.enemy_spells == frozenset(), str(open_field.enemy_spells))

# ------------------------------------------------------------ pasted icons
def pasted(icon_path, at=(207, 166), size=22):
    """The panel with an icon drawn as the recap draws them: a small disc."""
    frame = PANEL.copy()
    icon = cv2.resize(cv2.imread(str(icon_path)), (size, size),
                      interpolation=cv2.INTER_AREA)
    mask = np.zeros((size, size), np.uint8)
    cv2.circle(mask, (size // 2, size // 2), size // 2 - 1, 255, -1)
    px, py = at
    region = frame[py:py + size, px:px + size]
    region[mask > 0] = icon[mask > 0]
    return frame


ignite = pasted(assets.icon_for_spell("SummonerDot"))
with_ignite = death_recap.read(ignite, champions, spells, ROSTER, read_text)
check("an Ignite in Zed's row is Zed's Ignite",
      with_ignite is not None and ("Zed", "Ignite") in with_ignite.enemy_spells,
      str(with_ignite.enemy_spells if with_ignite else None))
open_ignite = death_recap.read(ignite, champions, spells, None, read_text)
check("and without a roster as well",
      open_ignite is not None and ("Zed", "Ignite") in open_ignite.enemy_spells,
      str(open_ignite.enemy_spells if open_ignite else None))

zed = assets.champions["Zed"].ultimate
ult = death_recap.read(pasted(assets.icon_for_spell(zed.ddragon_id)),
                       champions, spells, None, read_text)
check("Zed's own ultimate is not a summoner spell",
      ult is not None and not any(c == "Zed" for c, _s in ult.enemy_spells),
      str(ult.enemy_spells if ult else None))

no_ignite = dict(ROSTER, Zed=frozenset({"Flash", "Teleport"}))
other = death_recap.read(ignite, champions, spells, no_ignite, read_text)
check("with a roster, a spell Zed did not take is not read for him",
      other is not None and not any(c == "Zed" for c, _s in other.enemy_spells),
      str(other.enemy_spells if other else None))

ghost = death_recap.read(pasted(assets.icon_for_spell("SummonerHaste")),
                         champions, spells, None, read_text)
check("a spell that deals no damage is never looked for",
      ghost is not None and not ghost.enemy_spells,
      str(ghost.enemy_spells if ghost else None))

# ------------------------------------------------------------ a real Ignite
real = death_recap.read(IGNITE_PANEL, champions, spells, ROSTER, read_text)
check("Thresh's real Ignite is read",
      real is not None and ("Thresh", "Ignite") in real.enemy_spells,
      real.describe() if real else "no panel")
check("and nothing else", real is not None
      and real.enemy_spells == frozenset({("Thresh", "Ignite")}),
      str(real.enemy_spells if real else None))
check("that fight lasted 13.7 s", real is not None and real.fight_seconds == 13.7,
      str(real.fight_seconds if real else None))
check("the enemy crossed out for being dead is still recognised (Ekko)",
      real is not None
      and "Ekko" in {row.champion_id for row in real.rows if row.enemy},
      real.describe() if real else "no panel")

# A larger HUD scale draws a larger panel in the same window, so the area
# looked at stays the same size while the panel grows inside it.
bigger = cv2.resize(IGNITE_PANEL, None, fx=1.4, fy=1.4,
                    interpolation=cv2.INTER_CUBIC)[0:540, 0:422]
scaled = death_recap.read(bigger, champions, spells, ROSTER, read_text)
check("a panel drawn 1.4 times larger is still read",
      scaled is not None and ("Thresh", "Ignite") in scaled.enemy_spells,
      scaled.describe() if scaled else "no panel")
real_open = death_recap.read(IGNITE_PANEL, champions, spells, None, read_text)
check("Thresh's real Ignite is read without a roster too",
      real_open is not None and ("Thresh", "Ignite") in real_open.enemy_spells,
      real_open.describe() if real_open else "no panel")

# ------------------------------------------------------------ no panel
check("the game world is not a panel",
      death_recap.read(NO_PANEL, champions, spells, ROSTER, read_text) is None)
check("nor without a roster",
      death_recap.read(NO_PANEL, champions, spells, None, read_text) is None)

# ------------------------------------------------------------ the capture loop
import queue
import clock
import ocr
import settings as settings_module
from game_detector import GameState
from message_parser import MessageParser
from settings import Settings

tmp = Path(os.environ["TEMP"]) / "flashwatch_recaptest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"
if settings_module.CONFIG_PATH.exists():
    settings_module.CONFIG_PATH.unlink()

now = [1000.0]
clock.use(lambda: now[0])
worker = ocr.CaptureWorker(Settings(), MessageParser(assets), queue.Queue())
worker.engine = engine
worker.icons = champions
worker.spell_icons = spells
worker._sct = object()
showing = [IGNITE_PANEL]


def fake_grab(monitor):
    area = death_recap.search_area(WINDOW)
    if (monitor["left"], monitor["top"], monitor["width"],
            monitor["height"]) == area:
        return showing[0]
    return np.zeros((max(10, monitor["height"]), max(20, monitor["width"]), 3),
                    np.uint8)


worker._grab = fake_grab


def look(seconds=1.1):
    """One pass of the recap reader, a little over its interval later."""
    now[0] += seconds
    worker._read_recap(WINDOW)
    taken = list(worker._recap_pending)
    worker._recap_pending.clear()
    return taken


first = look()
check("one reading is not enough", first == [], str(first))
second = look()
check("two that agree publish Thresh's Ignite once",
      [(c, s) for c, s, _t in second] == [("Thresh", "Ignite")], str(second))
if second:
    seen_at = now[0] - 1.1
    check("placed at the start of the 13.7 s fight",
          abs(second[0][2] - (seen_at - 13.7)) < 0.01,
          f"{second[0][2]:.1f} vs {seen_at - 13.7:.1f}")
check("the panel staying up publishes nothing more",
      look() == [] and look() == [])
showing[0] = NO_PANEL
for _ in range(4):
    look()
showing[0] = IGNITE_PANEL
look()
again = look()
check("the next death is a new appearance, published again",
      [(c, s) for c, s, _t in again] == [("Thresh", "Ignite")], str(again))

worker.set_recap_enabled(False)
calls = []
real_read = death_recap.read
death_recap.read = lambda *a, **k: calls.append(1) or real_read(*a, **k)
look()
look()
death_recap.read = real_read
check("switched off, the panel is not even read", calls == [])

worker.set_recap_enabled(True)

# Seen late -- the player alt-tabbed while dead -- the panel was up since some
# time after the last look that found none, and the cast is placed from there.
showing[0] = NO_PANEL
for _ in range(4):
    look()
absent_at = now[0]
now[0] += 20.0
showing[0] = IGNITE_PANEL
look()
late = look()
check("a panel first seen late is dated from the last look without it",
      late and abs(late[0][2] - (absent_at - 13.7)) < 0.01,
      f"{late[0][2]:.1f} vs {absent_at - 13.7:.1f}" if late else "nothing")

# One OCR slip on the fight's length must not make the timer late: the
# longest length read in the appearance is the one used.
lengths = iter(["3.7s", "13.7s", "13.7s", "13.7s"])
real_line = worker.engine.read_line
worker.engine.read_line = lambda image: next(lengths, "13.7s")
showing[0] = NO_PANEL
for _ in range(4):
    look()
absent_at = now[0]
showing[0] = IGNITE_PANEL
look()
longest = look()
worker.engine.read_line = real_line
check("the longest fight length read is the one used",
      longest and abs(longest[0][2] - (absent_at - 13.7)) < 0.01,
      f"{longest[0][2]:.1f} vs {absent_at - 13.7:.1f}" if longest else "nothing")

# Switching it off from the settings window must not touch the capture
# thread's state under it; the capture thread clears it itself.
before = worker._recap_since
worker.set_recap_enabled(False)
check("switching off leaves the reader's state to the capture thread",
      worker._recap_since == before and before is not None)
look()
check("which then forgets the panel", worker._recap_since is None)
worker.set_recap_enabled(True)

# A reading waiting for a full queue belongs to the game it was read in.
worker._recap_pending.append(("Thresh", "Ignite", now[0]))


class NewGame:
    def poll(self):
        return GameState(in_game=False, client_running=True), True


worker.detector = NewGame()
while not worker.results.empty():
    worker.results.get_nowait()
worker._iterate()
carried = []
while not worker.results.empty():
    carried += worker.results.get_nowait().get("recap") or []
check("a new game drops a reading still waiting from the last one",
      worker._recap_pending == [] and carried == [], str(carried))

# A failure in the recap reader costs the recap, not the chat read.
def broken(*_a, **_k):
    raise RuntimeError("boom")


death_recap.read = broken
worker.status.error = ""
try:
    look()
    survived = True
except RuntimeError:
    survived = False
death_recap.read = real_read
check("an error in the recap reader is contained",
      survived and worker.status.error == "", worker.status.error)

# Icons still downloading: no index is built from a partial set.
early = ocr.CaptureWorker(Settings(), MessageParser(assets), queue.Queue())
early._grab = fake_grab
early._sct = object()
assets.icons_ready = False
now[0] += 5.0
early._read_recap(WINDOW)
check("no champion index is built before the icons are all there",
      not early.icons.ready)

worker.set_recap_roster({"Thresh": frozenset({"Flash", "Heal"})})
showing[0] = NO_PANEL
for _ in range(4):
    look()
showing[0] = IGNITE_PANEL
look()
check("with a roster saying Thresh took Heal, his Ignite icon is not read",
      look() == [])

# ------------------------------------------------------------ the timers
import live_client
from timer_manager import PRIME_FRAMES, TimerManager

timers = TimerManager(assets, Settings())
for _ in range(PRIME_FRAMES):
    timers.note_frame()
cooldown = timers.summoner_cooldown("Ignite")
now[0] = 5000.0
timer = timers.note_recap("Thresh", "Ignite", 5000.0 - 13.7)
check("the recap starts Thresh's Ignite", timer is not None)
if timer is not None:
    check("marked uncertain", timer.uncertain)
    check("counted from the start of the fight",
          abs(timer.remaining() - (cooldown - 13.7)) < 0.01,
          f"{timer.remaining():.1f} vs {cooldown - 13.7:.1f}")
now[0] += 20.0
check("a running timer is left alone",
      timers.note_recap("Thresh", "Ignite", now[0] - 2.0) is None
      and abs(timers.snapshot()[0].remaining() - (cooldown - 33.7)) < 0.01)

parser = MessageParser(assets)
confirmed = parser.parse_line("01:30 Bob (Ahri): Thresh used Ignite")
timers.handle_events([confirmed])
running = [t for t in timers.snapshot() if t.champion_id == "Thresh"]
check("a confirmed chat line takes over and clears the question mark",
      len(running) == 1 and not running[0].uncertain, str(running))


def spell(ddragon_id, name):
    return {"displayName": name,
            "rawDisplayName": f"GeneratedTip_SummonerSpell_{ddragon_id}_DisplayName"}


def player(champion, team, one, two):
    return {"championName": champion,
            "rawChampionName": f"game_character_displayname_{champion}",
            "team": team, "level": 9, "position": "",
            "riotId": f"P{champion}#EUW", "riotIdGameName": f"P{champion}",
            "summonerSpells": {"summonerSpellOne": spell(*one),
                               "summonerSpellTwo": spell(*two)},
            "items": [], "runes": {}}


FLASH, HEAL = ("SummonerFlash", "Flash"), ("SummonerHeal", "Heal")
game = live_client.parse_game(
    {"gameMode": "CLASSIC", "mapNumber": 11, "gameTime": 900.0},
    [player("Twitch", "ORDER", FLASH, HEAL), player("Thresh", "CHAOS", FLASH, HEAL)],
    "PTwitch#EUW", champions=assets.champions)
fresh = TimerManager(assets, Settings())
for _ in range(PRIME_FRAMES):
    fresh.note_frame()
fresh.set_live_game(game)
check("an enemy who did not take the spell gets no timer from the recap",
      fresh.note_recap("Thresh", "Ignite", now[0] - 5.0) is None)
clock.use(None)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
