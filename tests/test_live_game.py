# -*- coding: utf-8 -*-
"""The game's data feed: reading it, and what it changes downstream.

Nothing here talks to a game. The feed's answers are built in the shape Riot
documents for ``/liveclientdata`` and handed to the parser, to a client wired to
a fake session, and from there to the message parser and the timers -- which is
where the feed earns its place: the right enemy, the right spell, the right
cooldown for *that* enemy.
"""
import sys, io, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import requests

import live_client
from live_client import (LiveClient, MODE_ARAM, MODE_ARENA, MODE_OTHER,
                         MODE_PRACTICE, MODE_RIFT, mode_category, parse_game)
from cooldowns import (apply_haste, get_cooldown, unleashed_teleport,
                       format_short)
from riot_assets import RiotAssets
from message_parser import MessageParser
from settings import DEFAULTS
from timer_manager import TimerManager, PRIME_FRAMES, ULT_KEY

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def spell(ddragon_id, name):
    return {"displayName": name,
            "rawDescription": f"GeneratedTip_SummonerSpell_{ddragon_id}_Description",
            "rawDisplayName": f"GeneratedTip_SummonerSpell_{ddragon_id}_DisplayName"}


def player(champion, team, spells, *, name=None, level=1, position="",
           items=(), trees=(8100, 8200), display=None):
    riot_name = name or f"P{champion}"
    return {
        "championName": display or champion,
        "rawChampionName": f"game_character_displayname_{champion}",
        "team": team,
        "level": level,
        "position": position,
        "isBot": False,
        "riotId": f"{riot_name}#EUW",
        "riotIdGameName": riot_name,
        "riotIdTagLine": "EUW",
        "summonerName": riot_name,
        "summonerSpells": {"summonerSpellOne": spell(*spells[0]),
                           "summonerSpellTwo": spell(*spells[1])},
        "items": [{"itemID": item, "displayName": str(item)} for item in items],
        "runes": {"keystone": {"id": 8112},
                  "primaryRuneTree": {"id": trees[0]},
                  "secondaryRuneTree": {"id": trees[1]}},
    }


FLASH = ("SummonerFlash", "Flash")
IGNITE = ("SummonerDot", "Ignite")
TP = ("SummonerTeleport", "Teleport")
TP_UP = ("S12_SummonerTeleportUpgrade", "Unleashed Teleport")
SMITE = ("SummonerSmiteAvatarOffensive", "Primal Smite")
HEAL = ("SummonerHeal", "Heal")
EXHAUST = ("SummonerExhaust", "Exhaust")
GHOST = ("SummonerHaste", "Ghost")

PLAYERS = [
    # ORDER: the player and their team.
    player("Garen", "ORDER", (FLASH, TP), name="Me", position="TOP"),
    player("Viego", "ORDER", (FLASH, ("SummonerSmite", "Smite"))),
    player("Ahri", "ORDER", (FLASH, IGNITE), position="MIDDLE"),
    player("Jinx", "ORDER", (FLASH, HEAL), position="BOTTOM"),
    player("Thresh", "ORDER", (FLASH, EXHAUST), position="UTILITY"),
    # CHAOS: the enemy, deliberately varied.
    player("Darius", "CHAOS", (FLASH, TP_UP), level=13, position="TOP",
           trees=(8000, 8300)),                       # Inspiration secondary
    player("LeeSin", "CHAOS", (SMITE, FLASH), level=11, display="Lee Sin",
           trees=(8100, 8000)),                       # no Inspiration
    player("MonkeyKing", "CHAOS", (FLASH, IGNITE), level=12, display="Wukong",
           position="MIDDLE", items=(3158,), trees=(8300, 8100)),
    player("Kaisa", "CHAOS", (FLASH, HEAL), level=11, display="Kai'Sa",
           position="BOTTOM", items=(3171,), trees=(8300, 8000)),
    player("Leona", "CHAOS", (FLASH, EXHAUST), level=9, position="UTILITY"),
]
STATS = {"gameMode": "CLASSIC", "gameTime": 754.2, "mapName": "Map11",
         "mapNumber": 11, "mapTerrain": "Default"}

assets = RiotAssets("en_US")
assets.bootstrap()

# ------------------------------------------------------------------ modes
print("-- modes")
for mode, map_number, expected in (
        ("CLASSIC", 11, MODE_RIFT), ("SWIFTPLAY", 11, MODE_RIFT),
        ("PRACTICETOOL", 11, MODE_PRACTICE), ("ARAM", 12, MODE_ARAM),
        ("KIWI", 12, MODE_ARAM), ("CHERRY", 30, MODE_ARENA),
        ("URF", 11, MODE_OTHER), ("ONEFORALL", 11, MODE_OTHER),
        ("STRAWBERRY", 33, MODE_OTHER), ("", 12, MODE_ARAM)):
    check(f"{mode or '(blank)'} on map {map_number} is {expected}",
          mode_category(mode, map_number) == expected,
          mode_category(mode, map_number))

check("by default the overlay runs on the Rift and in the Practice Tool only",
      [m for m in live_client.MODES
       if DEFAULTS[live_client.MODE_SETTING[m]]] == [MODE_RIFT, MODE_PRACTICE])

# ------------------------------------------------------------------ parsing
print("-- parsing the feed")
game = parse_game(STATS, PLAYERS, "Me#EUW", champions=assets.champions,
                  fetched_at=100.0)
check("ten players read", len(game.players) == 10)
check("the active player's team is found from the riot id",
      game.active_team == "ORDER", game.active_team)
check("five enemies, none of them ours",
      sorted(p.champion_id for p in game.enemies)
      == ["Darius", "Kaisa", "LeeSin", "Leona", "MonkeyKing"],
      str([p.champion_id for p in game.enemies]))
check("Wukong is MonkeyKing, from the raw name rather than the display name",
      game.enemy("MonkeyKing") is not None)
lee = game.enemy("LeeSin")
check("an evolved Smite is still Smite", lee is not None and "Smite" in lee.spells,
      str(lee.spells if lee else None))
check("Unleashed Teleport is still Teleport",
      game.enemy("Darius").spells == ("Flash", "Teleport"),
      str(game.enemy("Darius").spells))
check("the feed's lanes are translated", game.enemy("Kaisa").position == "ADC"
      and game.enemy("Leona").position == "SUPPORT"
      and game.enemy("MonkeyKing").position == "MID")
check("the one Smite carrier is the jungler, when the feed leaves it blank",
      lee.position == "JUNGLE", lee.position)
check("an ally without a lane is not given one by its place in the list",
      [p for p in game.allies if p.champion_id == "Viego"][0].position == "JUNGLE"
      and all(p.position == "" for p in game.players
              if p.champion_id not in ("Garen", "Viego", "Ahri", "Jinx", "Thresh",
                                       "Darius", "LeeSin", "MonkeyKing", "Kaisa",
                                       "Leona")))
check("Inspiration is seen in either tree",
      game.enemy("Darius").may_have_cosmic_insight
      and game.enemy("MonkeyKing").may_have_cosmic_insight
      and not lee.may_have_cosmic_insight)
check("items are read as ids", game.enemy("MonkeyKing").items == (3158,))
check("the clock extrapolates between readings",
      abs(game.now(at=103.0) - 757.2) < 1e-6)

nobody = parse_game(STATS, PLAYERS, "", champions=assets.champions)
check("without an active player there is no enemy team (spectating)",
      nobody.enemies == () and len(nobody.players) == 10)


# ------------------------------------------------------------------ fetching
print("-- fetching")
class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, answers):
        self.answers, self.headers, self.calls = answers, {}, []
        self.trust_env, self.verify = True, True
    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        answer = self.answers.get(url.rsplit("/", 1)[-1])
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)
    def close(self):
        pass


session = FakeSession({"gamestats": STATS, "playerlist": PLAYERS,
                       "activeplayername": "Me#EUW"})
client = LiveClient(session=session)
fetched = client.fetch(champions=assets.champions)
check("a reading comes back from the three endpoints",
      fetched is not None and len(fetched.enemies) == 5)
check("only the loopback address is ever asked",
      all(url.startswith("https://127.0.0.1:2999/liveclientdata/")
          for url, _t in session.calls), str(session.calls[:1]))
check("environment proxies are ignored, the game's own certificate accepted",
      session.trust_env is False and session.verify is False)
check("every request is short", all(t is not None and t <= 1.0
                                   for _u, t in session.calls))

down = LiveClient(session=FakeSession({
    "gamestats": requests.ConnectionError("refused")}))
check("no game answering is None, not an exception",
      down.fetch(champions=assets.champions) is None)

loading = LiveClient(session=FakeSession({"gamestats": {}, "playerlist": "nope"}))
check("a half-ready feed is None", loading.fetch() is None)

# Over a real socket, once: the plumbing a fake session cannot prove -- the
# request goes out, JSON comes back, a closed port is a quiet None.
import http.server, json as _json
class Feed(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        name = self.path.rsplit("/", 1)[-1]
        body = {"gamestats": STATS, "playerlist": PLAYERS,
                "activeplayername": "Me#EUW"}.get(name)
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if body is not None:
            self.wfile.write(_json.dumps(body).encode())
    def log_message(self, *args):
        pass
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Feed)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]
real = LiveClient(base_url=f"http://127.0.0.1:{port}/liveclientdata")
over_socket = real.fetch(champions=assets.champions)
check("a real local server is read end to end",
      over_socket is not None and len(over_socket.enemies) == 5)
server.shutdown()
server.server_close()
started = time.monotonic()
check("a closed port is None, and fast",
      real.fetch() is None and time.monotonic() - started < 2.5)

watch_session = FakeSession({"gamestats": STATS, "playerlist": PLAYERS,
                             "activeplayername": "Me#EUW"})
watcher = live_client.LiveWatcher(wanted=lambda: True,
                                  champions=lambda: assets.champions,
                                  client=LiveClient(session=watch_session))
watcher.poll_once()
check("the watcher keeps the latest reading", watcher.connected
      and watcher.game.category == MODE_RIFT)

# ------------------------------------------------------------------ cooldowns
print("-- cooldown arithmetic")
check("haste, not a percentage: Flash with Cosmic Insight is 254 s",
      get_cooldown("Flash", cosmic_insight=True) == 254,
      str(get_cooldown("Flash", cosmic_insight=True)))
check("rune and boots add up: 28 haste is 234 s",
      get_cooldown("Flash", cosmic_insight=True, ionian_boots=True) == 234)
check("Crimson Lucidity and the rune: 217 s", round(apply_haste(300, 38)) == 217)
check("Unleashed Teleport is 330 s at level 1 and 240 s at 18",
      unleashed_teleport(1) == 330 and unleashed_teleport(18) == 240)
check("the patch's own Teleport is used, not the old 360 s",
      assets.spells["Teleport"].cooldown == 300, str(assets.spells["Teleport"].cooldown))
check("Smite is timed on its 90 s recharge, not the 15 s lock-out",
      assets.spells["Smite"].cooldown == 90)
check("Ionian Boots and Crimson Lucidity are read from the item data",
      assets.item_summoner_haste.get(3158) == 10
      and assets.item_summoner_haste.get(3171) == 20,
      str({k: v for k, v in assets.item_summoner_haste.items()}))
check("countdowns on an icon drop the minutes under one",
      format_short(254) == "4:14" and format_short(47.2) == "48"
      and format_short(0) == "")

# ------------------------------------------------------------------ parser
print("-- the parser, with the roster")
parser = MessageParser(assets)
enemies = {p.champion_id: p.spells for p in game.enemies}
allies = [p.champion_id for p in game.allies]
open_field = parser.parse_line("12:34 Bob (Garen): Ahri used Flash")
check("without a roster an ally's ping is taken (nothing to tell)",
      open_field is not None)
parser.set_roster(enemies, allies)
check("with it, a line about an ally is refused",
      parser.parse_line("12:34 Bob (Garen): Ahri used Flash") is None)
check("an enemy's spell is taken",
      (event := parser.parse_line("12:34 Bob (Garen): Darius used Flash"))
      is not None and event.champion_id == "Darius" and event.spell_key == "Flash")
check("a spell the enemy did not take is refused",
      parser.parse_line("12:34 Bob (Garen): Darius used Ignite") is None
      and any("Ignite" in line for line in parser.roster_rejects),
      str(parser.roster_rejects))
check("a name the OCR bent past the open field is still the enemy",
      (bent := parser.parse_line("(12:34) Kalsa used Heal")) is not None
      and bent.champion_id == "Kaisa", str(bent and bent.champion_id))
check("...and a bent spell name, if it can only be one of theirs",
      (bent := parser.parse_line("(12:34) Leona used Exhst")) is not None
      and bent.spell_key == "Exhaust", str(bent and bent.spell_key))
check("the stated form follows the same rules",
      parser.parse_line("Bob (Garen): Wait Jinx Heal - 120 sec.") is None
      and parser.parse_line("Bob (Garen): Wait Leona Flash - 120 sec.") is not None)
check("an ultimate is never refused for not being a summoner",
      parser.parse_line(
          f"(12:34) Darius used {assets.champions['Darius'].ultimate.name}")
      is not None)
check("an upgraded spell is its family: Unleashed Teleport is Teleport",
      (up := parser.parse_line("12:34 Bob (Garen): Darius used Unleashed Teleport"))
      is not None and up.spell_key == "Teleport", str(up and up.spell_key))
check("and an evolved Smite is Smite",
      (up := parser.parse_line("12:34 Bob (Garen): Lee Sin used Primal Smite"))
      is not None and up.spell_key == "Smite", str(up and up.spell_key))
check("but only a spell the enemy took: nobody here has an upgraded Ghost",
      parser.parse_line("12:34 Bob (Garen): Darius used Spectral Ghost") is None)
parser.set_roster(None)
check("forgetting the roster restores the open field",
      parser.parse_line("12:34 Bob (Garen): Ahri used Flash") is not None)

# ------------------------------------------------------------------ timers
print("-- timers for that enemy")
settings = type("S", (), {})()
settings._data = dict(DEFAULTS)
settings.get = lambda key, default=None: settings._data.get(key, default)
settings.set = lambda key, value, **_: settings._data.__setitem__(key, value)

tm = TimerManager(assets, settings)
for _ in range(PRIME_FRAMES):
    tm.note_frame()
live_now = parse_game(STATS, PLAYERS, "Me#EUW", champions=assets.champions)
check("the roster is applied once", tm.set_live_game(live_now)
      and not tm.set_live_game(live_now))
check("the game clock is the feed's", abs(tm.estimated_game_time() - 754.2) < 1.0)
check("roles come from the feed", tm.role_of("Kaisa") == "ADC"
      and tm.role_of("LeeSin") == "JUNGLE")
check("the roster is the five enemies, by lane",
      tm.roster() == ["Darius", "LeeSin", "MonkeyKing", "Kaisa", "Leona"],
      str(tm.roster()))

p = MessageParser(assets)
p.set_roster(enemies, allies)
def time_line(line):
    event = p.parse_line(line)
    started = tm.handle_events([event]) if event else []
    return started[0] if started else None

lee_flash = time_line("(12:34) Lee Sin used Flash")
check("Flash without Inspiration: the full 300 s",
      lee_flash is not None and lee_flash.duration == 300,
      str(lee_flash and lee_flash.duration))
dar_flash = time_line("(12:34) Darius used Flash")
check("Flash with Inspiration: Cosmic Insight assumed, 254 s",
      dar_flash is not None and dar_flash.duration == 254,
      str(dar_flash and dar_flash.duration))
wu_flash = time_line("(12:34) Wukong used Flash")
check("Ionian Boots and Inspiration: 234 s",
      wu_flash is not None and wu_flash.duration == 234,
      str(wu_flash and wu_flash.duration))
kai_heal = time_line("(12:34) Kai'Sa used Heal")
check("Crimson Lucidity and Inspiration on Heal: 174 s",
      kai_heal is not None and kai_heal.duration == round(apply_haste(240, 38)),
      str(kai_heal and kai_heal.duration))
dar_tp = time_line("(12:34) Darius used Teleport")
check("Teleport after 10:00 is Unleashed, by Darius's level 13",
      dar_tp is not None
      and dar_tp.duration == round(apply_haste(unleashed_teleport(13), 18)),
      str(dar_tp and dar_tp.duration))
leona_ult = time_line(
    f"(12:34) Leona used {assets.champions['Leona'].ultimate.name}")
ult = assets.champions["Leona"].ultimate
check("an ultimate's rank comes from the level (9 -> rank 1)",
      leona_ult is not None and abs(leona_ult.duration - ult.cooldown_for_rank(1)) < 1,
      str(leona_ult and leona_ult.duration))
check("an ally's line never becomes a timer, even if it reaches the manager",
      tm.handle_events([open_field]) == [])

team = tm.team()
check("the team display has all five, summoners first, then the ult",
      len(team) == 5 and [s.spell_key for s in team[0].slots]
      == ["Flash", "Teleport", ULT_KEY], str([s.spell_key for s in team[0].slots]))
check("a spell on cooldown carries its timer, one that is up does not",
      team[1].slots[1].timer is not None and team[1].slots[0].timer is None,
      str([(s.spell_key, bool(s.timer)) for s in team[1].slots]))

settings._data["assume_cosmic_insight"] = False
check("the rune assumption can still be switched off",
      tm.summoner_cooldown("Flash", game.enemy("Darius")) == 300)
settings._data["assume_cosmic_insight"] = True

tm.set_live_game(None)
check("without the feed, the global assumptions stand in again",
      tm.summoner_cooldown("Flash") == 254)

restart = TimerManager(assets, settings)
restart.set_live_game(live_now)
restart._timers[("Darius", "Flash")] = dar_flash
early = parse_game({**STATS, "gameTime": 3.0}, PLAYERS, "Me#EUW",
                   champions=assets.champions)
restart.set_live_game(early)
check("the feed's clock jumping back to the start clears the board",
      restart.active_count() == 0 and restart.estimated_game_time() < 10)

failed = [r for r in results if not r]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
