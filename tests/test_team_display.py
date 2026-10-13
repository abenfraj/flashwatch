# -*- coding: utf-8 -*-
"""The enemy-team display: everybody, every spell, nothing on top of anything.

What is checked is what decides whether it can be read in a fight:

* geometry -- every portrait and every spell inside the window and clear of every
  other, in both orientations and across the scale range;
* the window sizes itself to the team and keeps the edge it was put against;
* states -- a spell that is down is drawn darker than one that is up, an enemy
  with nothing down is drawn fainter than one with something down;
* a refresh that changes nothing visible does not repaint;
* the overhaul's one-time switch of existing installs onto this display.
"""
import sys, io, os, json, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_teamtest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"
if settings_module.CONFIG_PATH.exists():
    settings_module.CONFIG_PATH.unlink()

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

import live_client
from message_parser import MessageParser
from overlay import LAYOUT_TEAM, THEMES, Overlay
from riot_assets import RiotAssets
from settings import SETTINGS_VERSION, Settings
from timer_manager import PRIME_FRAMES, TimerManager, ULT_KEY

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


app = QApplication.instance() or QApplication(sys.argv)
assets = RiotAssets("en_US")
assets.bootstrap()


def spell(ddragon_id, name):
    return {"displayName": name,
            "rawDisplayName": f"GeneratedTip_SummonerSpell_{ddragon_id}_DisplayName"}


def player(champion, team, one, two, *, name=None, position=""):
    riot = name or f"P{champion}"
    return {"championName": champion,
            "rawChampionName": f"game_character_displayname_{champion}",
            "team": team, "level": 10, "position": position,
            "riotId": f"{riot}#EUW", "riotIdGameName": riot,
            "summonerSpells": {"summonerSpellOne": spell(*one),
                               "summonerSpellTwo": spell(*two)},
            "items": [], "runes": {}}


FLASH, TP = ("SummonerFlash", "Flash"), ("SummonerTeleport", "Teleport")
IGNITE, HEAL = ("SummonerDot", "Ignite"), ("SummonerHeal", "Heal")
SMITE, EXH = ("SummonerSmite", "Smite"), ("SummonerExhaust", "Exhaust")
PLAYERS = [player("Garen", "ORDER", FLASH, TP, name="Me"),
           player("Darius", "CHAOS", FLASH, TP, position="TOP"),
           player("Viego", "CHAOS", SMITE, FLASH, position="JUNGLE"),
           player("Ahri", "CHAOS", FLASH, IGNITE, position="MIDDLE"),
           player("Jinx", "CHAOS", FLASH, HEAL, position="BOTTOM"),
           player("Thresh", "CHAOS", FLASH, EXH, position="UTILITY")]
game = live_client.parse_game({"gameMode": "CLASSIC", "mapNumber": 11,
                               "gameTime": 600.0}, PLAYERS, "Me#EUW",
                              champions=assets.champions)

settings = Settings()
settings.set("overlay_layout", LAYOUT_TEAM)
timers = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    timers.note_frame()
timers.set_live_game(game)
parser = MessageParser(assets)
parser.set_roster({p.champion_id: p.spells for p in game.enemies},
                  [p.champion_id for p in game.allies])
for line in ("(9:58) Darius used Flash", "(9:59) Ahri used Ignite"):
    timers.handle_events([parser.parse_line(line)])

team = timers.team()
check("five enemies, in lane order",
      [m.champion_id for m in team] == ["Darius", "Viego", "Ahri", "Jinx", "Thresh"],
      str([m.champion_id for m in team]))
check("each has both summoners and the ultimate",
      all([s.kind for s in m.slots] == ["summoner", "summoner", "ultimate"]
          for m in team))
check("the spells down are the ones that were used",
      [(m.champion_id, s.spell_key) for m in team for s in m.slots if s.timer]
      == [("Darius", "Flash"), ("Ahri", "Ignite")])

overlay = Overlay(settings, assets)
overlay.set_team(team)


def all_rects(cells):
    rects = []
    for _member, portrait, spells in cells:
        rects.append(portrait)
        rects.extend(spells)
    return rects


for horizontal in (False, True):
    settings.set("team_horizontal", horizontal)
    for scale in (0.6, 1.0, 1.6, 2.0):
        settings.set("overlay_scale", scale)
        overlay._fit_team_window()
        cells = overlay.team_cells()
        rects = all_rects(cells)
        frame = QRectF(0, 0, overlay.width(), overlay.height())
        inside = all(frame.contains(r) for r in rects)
        overlapping = [(i, j) for i in range(len(rects))
                       for j in range(i + 1, len(rects))
                       if rects[i].intersected(rects[j]).width() > 0.01
                       and rects[i].intersected(rects[j]).height() > 0.01]
        tag = f"{'row' if horizontal else 'column'} at x{scale}"
        check(f"[{tag}] everything inside the window", inside,
              f"{overlay.width()}x{overlay.height()}")
        check(f"[{tag}] nothing on top of anything", not overlapping,
              str(overlapping[:3]))

settings.set("team_horizontal", False)
settings.set("overlay_scale", 1.0)
overlay._fit_team_window()
small = (overlay.width(), overlay.height())
check("a column is taller than it is wide", small[1] > small[0], str(small))
settings.set("team_horizontal", True)
overlay._fit_team_window()
check("a row is wider than it is tall", overlay.width() > overlay.height(),
      f"{overlay.width()}x{overlay.height()}")
settings.set("team_horizontal", False)

# Against the right edge, growing must keep it there.
screen = app.primaryScreen().geometry()
overlay._fit_team_window()
overlay.move(screen.right() - overlay.width() + 1, 100)
right_edge = overlay.geometry().right()
settings.set("overlay_scale", 1.6)
overlay._fit_team_window()
check("a panel against the right edge stays against it when it grows",
      overlay.geometry().right() == right_edge,
      f"{overlay.geometry().right()} vs {right_edge}")
settings.set("overlay_scale", 1.0)
overlay._fit_team_window()

# ------------------------------------------------------------ repainting
calls = []
overlay.update = lambda *a: calls.append(1)
overlay._team_signature = None
overlay.set_team(timers.team())
first = len(calls)
overlay.set_team(timers.team())
check("a refresh that changes nothing does not repaint",
      len(calls) == first, f"{first} then {len(calls)}")
del overlay.update

# ------------------------------------------------------------ drawing
settings.set("team_rest_opacity", 0.4)
for theme in THEMES:
    settings.set("theme", theme)
    overlay.set_team(timers.team())
    image = overlay.grab().toImage()
    check(f"the {theme} theme draws", not image.isNull() and image.width() > 0)

settings.set("theme", "clean")
overlay._team_signature = None
overlay.set_team(timers.team())
image = overlay.grab().toImage()
cells = {member.champion_id: (portrait, spells)
         for member, portrait, spells in overlay.team_cells()}


def brightness(rect):
    total, count = 0.0, 0
    for x in range(int(rect.left()) + 3, int(rect.right()) - 2, 2):
        for y in range(int(rect.top()) + 3, int(rect.bottom()) - 2, 2):
            colour = image.pixelColor(x, y)
            total += (colour.red() + colour.green() + colour.blue()) * colour.alphaF()
            count += 1
    return total / max(1, count)


darius_flash, darius_tp = cells["Darius"][1][0], cells["Darius"][1][1]
check("a spell that is down is drawn darker than one that is up",
      brightness(darius_flash) < brightness(darius_tp) * 0.8,
      f"{brightness(darius_flash):.0f} vs {brightness(darius_tp):.0f}")
resting = brightness(cells["Jinx"][0])
timers.handle_events([parser.parse_line("(9:59) Jinx used Heal")])
overlay.set_team(timers.team())
image = overlay.grab().toImage()
busy = brightness(cells["Jinx"][0])
check("an enemy with nothing down is drawn fainter than once a spell is used",
      resting < busy * 0.6, f"{resting:.0f} at rest vs {busy:.0f}")
timers._timers.pop(("Jinx", "Heal"), None)
overlay.set_team(timers.team())
image = overlay.grab().toImage()

settings.set("team_hide_rested", True)
overlay._team_signature = None
overlay.set_team(timers.team())
image = overlay.grab().toImage()
check("with resting enemies hidden, Jinx is not drawn at all",
      brightness(cells["Jinx"][0]) < 1.0, f"{brightness(cells['Jinx'][0]):.1f}")
settings.set("team_hide_rested", False)

# ------------------------------------------------------------ without a game
demo = TimerManager(assets, settings)
demo.add_demo(first=True)
demo_team = demo.team()
check("the trial fills the team display with whole rows",
      len(demo_team) == 5 and all(len(m.slots) == 3 for m in demo_team),
      str([(m.champion_id, [s.spell_key for s in m.slots]) for m in demo_team]))
check("the trial's rows are in lane order",
      [m.role for m in demo_team] == ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"],
      str([m.role for m in demo_team]))
demo.clear_demo()
check("and leaves nothing behind", demo.team() == [])

plain = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    plain.note_frame()
plain.handle_events([MessageParser(assets).parse_line("(9:58) Darius used Flash")])
check("without the game's data, an enemy appears once a spell is seen",
      [(m.champion_id, [s.spell_key for s in m.slots]) for m in plain.team()]
      == [("Darius", ["Flash", ULT_KEY])],
      str([(m.champion_id, [s.spell_key for s in m.slots]) for m in plain.team()]))

# ------------------------------------------------------------ the migration
old = tmp / "old-settings.json"
old.write_text(json.dumps({"overlay_layout": "bar", "theme": "neon",
                           "overlay_scale": 1.6, "audio_sfx": "choir"}), "utf-8")
migrated = Settings(old)
check("an older install is moved onto the team display and the clean theme",
      migrated.get("overlay_layout") == LAYOUT_TEAM
      and migrated.get("theme") == "clean"
      and migrated.get("overlay_scale") == 1.0)
check("everything else it had is kept", migrated.get("audio_sfx") == "choir")
check("and the move is written down, so it happens once",
      json.loads(old.read_text("utf-8")).get("settings_version") == SETTINGS_VERSION)
migrated.set("overlay_layout", "bar")
again = Settings(old)
check("a choice made after the move is respected",
      again.get("overlay_layout") == "bar")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
