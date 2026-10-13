"""What the game itself says about the match it is running.

League serves a read-only JSON feed on the player's own machine while a game is
on -- Riot's *Live Client Data API*, ``https://127.0.0.1:2999/liveclientdata/``.
It exists for companion programs like this one, and it is the one thing here
that is not a pixel:

    gamestats     -> the mode, the map and the exact game clock
    playerlist    -> every champion, its team, its two summoner spells, its
                     level, its items and its rune trees
    activeplayer  -> which of them is the person at the keyboard

Every one of those is on the scoreboard already (Tab), which is why using it
changes nothing about what the player can know. It changes how *well* the rest
of the program can work:

* **The mode.** ARAM and Arena have nothing to time, and the overlay used to
  appear in them anyway. Now each mode is a setting.
* **The roster.** Five enemies and their ten spells, known from the first second
  instead of pieced together from pings. A chat line naming an ally, or a spell
  the champion did not take, can only be a misread -- so it is dropped.
* **The cooldowns.** Boots and runes are visible per enemy, so a Flash is 300 s
  on the jungler without Inspiration and 254 s on the mid laner with Cosmic
  Insight, instead of one guess for everybody.
* **The clock.** The real one, to the tenth of a second, instead of a clock read
  off the top of the screen by OCR.

What this module does *not* do: it never writes anything, never sends input,
never opens the game's process, never reads its memory and never talks to a
Riot server. The address is the loopback interface; the request goes no further
than this machine.

The game serves the feed over HTTPS with a certificate of its own. It is not
verified, deliberately and only here: the host is 127.0.0.1, so there is no
network for anybody to sit on, and no credential is ever sent. Proxies from the
environment are ignored for the same reason -- a corporate proxy has no business
seeing a request to the loopback address, and some refuse it.

Kept free of Qt, so the whole thing is tested against recorded answers.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import warnings
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

import requests

from cooldowns import DDRAGON_SPELL_IDS
from riot_assets import fold

log = logging.getLogger(__name__)

BASE_URL = "https://127.0.0.1:2999/liveclientdata"

# The one warning this module expects: an unverified HTTPS request to the game's
# own loopback address. Filtered once, here, for that host only -- set at import
# rather than around each request, because ``warnings.catch_warnings`` swaps the
# process-wide filter list and is not safe from a background thread.
warnings.filterwarnings(
    "ignore", message=r"Unverified HTTPS request is being made to host "
                      r"'127\.0\.0\.1'")

# Short, because the answer is local: a game that is up answers in a couple of
# milliseconds, and one that is not refuses the connection at once. The timeout
# only matters for the loading screen, where the port is sometimes open before
# the game is ready to say anything.
REQUEST_TIMEOUT = 0.8

# How often the feed is read while a game window is up. Levels and items change
# on the scale of seconds, and the clock in between is extrapolated, so once a
# second is plenty; the cost is three small local requests.
POLL_INTERVAL = 1.0

# How often to look while no game is running. The answer is "connection refused"
# and costs nothing, but there is also nothing to learn.
IDLE_INTERVAL = 2.0

# Inspiration, the rune tree Cosmic Insight lives in. The feed names every
# player's two trees but not the minor runes inside them, so this is as close as
# it gets: no Inspiration means no Cosmic Insight, for certain.
INSPIRATION_TREE = 8300

# Data Dragon puts the champion's id after this prefix in ``rawChampionName``.
_CHAMPION_PREFIX = "game_character_displayname_"
_SPELL_ID_RE = re.compile(r"SummonerSpell_(?P<id>.+?)_DisplayName", re.IGNORECASE)

# The feed's lane names, mapped onto the ones used everywhere else here.
_POSITIONS = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLE",
    "MIDDLE": "MID",
    "MID": "MID",
    "BOTTOM": "ADC",
    "BOT": "ADC",
    "UTILITY": "SUPPORT",
    "SUPPORT": "SUPPORT",
}

# -------------------------------------------------------------- modes
#
# What the player can switch on and off. Grouped by what matters to somebody
# timing summoner spells rather than by Riot's internal names, which change
# every event: what decides it is the map and whether a real enemy team is on it.
MODE_RIFT = "rift"            # Summoner's Rift: ranked, normals, Swiftplay
MODE_PRACTICE = "practice"    # the Practice Tool, where everybody tests
MODE_ARAM = "aram"            # Howling Abyss, ARAM and its variants
MODE_ARENA = "arena"          # 2v2v2v2
MODE_OTHER = "other"          # URF, One for All, Nexus Blitz, Swarm, ...
MODES = (MODE_RIFT, MODE_PRACTICE, MODE_ARAM, MODE_ARENA, MODE_OTHER)

# The setting that switches each one, and where it starts. Summoner's Rift and
# the Practice Tool only: the player asked for nothing to appear in ARAM or
# Arena, and nobody times Flash in Swarm.
MODE_SETTING = {mode: f"mode_{mode}" for mode in MODES}
MODE_DEFAULTS = {
    MODE_RIFT: True,
    MODE_PRACTICE: True,
    MODE_ARAM: False,
    MODE_ARENA: False,
    MODE_OTHER: False,
}

# Riot's gameMode strings that are Summoner's Rift with the ordinary rules.
_RIFT_MODES = {"CLASSIC", "SWIFTPLAY"}
# ARAM and the ARAM variants (KIWI is ARAM: Mayhem).
_ARAM_MODES = {"ARAM", "KIWI", "KIWI_JADE"}
_ARENA_MODES = {"CHERRY"}
_SUMMONERS_RIFT_MAPS = {11}
_ARAM_MAPS = {12, 14}
_ARENA_MAPS = {30}


def mode_category(game_mode: str, map_number: int | None) -> str:
    """Which of :data:`MODES` a game belongs to."""
    mode = (game_mode or "").strip().upper()
    if mode == "PRACTICETOOL":
        return MODE_PRACTICE
    if mode in _ARENA_MODES or map_number in _ARENA_MAPS:
        return MODE_ARENA
    if mode in _ARAM_MODES or map_number in _ARAM_MAPS:
        return MODE_ARAM
    if mode in _RIFT_MODES and (map_number in _SUMMONERS_RIFT_MAPS
                                or not map_number):
        return MODE_RIFT
    return MODE_OTHER


def mode_enabled(settings, category: str) -> bool:
    key = MODE_SETTING.get(category)
    if key is None:
        return False
    return bool(settings.get(key, MODE_DEFAULTS.get(category, False)))


# ------------------------------------------------------------- the data
@dataclass(frozen=True, slots=True)
class LivePlayer:
    """One champion in the game, as the feed describes it."""

    riot_id: str
    champion_id: str              # Data Dragon id ("MonkeyKing"), "" if unknown
    champion_name: str            # as the client prints it, in its language
    team: str                     # "ORDER" or "CHAOS"
    level: int = 1
    position: str = ""            # one of roles.ROLES, or "" when not given
    # Canonical spell keys ("Flash", "Teleport"...), in the order the player set
    # them. A spell this program has no table entry for (Arena's) is left out.
    spells: tuple[str, ...] = ()
    items: tuple[int, ...] = ()
    rune_trees: frozenset[int] = frozenset()
    is_bot: bool = False

    @property
    def may_have_cosmic_insight(self) -> bool:
        return INSPIRATION_TREE in self.rune_trees


@dataclass(frozen=True, slots=True)
class LiveGame:
    """One reading of the feed."""

    mode: str
    map_number: int
    category: str
    game_time: float
    # monotonic time the reading was taken, so the clock can be extrapolated
    # between two of them instead of standing still for a second.
    fetched_at: float
    players: tuple[LivePlayer, ...] = ()
    active_riot_id: str = ""
    active_team: str = ""

    def now(self, at: float | None = None) -> float:
        """The game clock as of ``at`` (default: now)."""
        at = time.monotonic() if at is None else at
        return self.game_time + max(0.0, at - self.fetched_at)

    @property
    def enemies(self) -> tuple[LivePlayer, ...]:
        """The other team, or nothing if we cannot tell which one that is.

        Nothing rather than everybody: a spectated game, or a feed that has not
        said who is playing, has no "enemy", and guessing would put five allies
        in the list.
        """
        if not self.active_team:
            return ()
        return tuple(player for player in self.players
                     if player.team and player.team != self.active_team)

    @property
    def allies(self) -> tuple[LivePlayer, ...]:
        if not self.active_team:
            return ()
        return tuple(player for player in self.players
                     if player.team == self.active_team)

    def enemy(self, champion_id: str) -> LivePlayer | None:
        for player in self.enemies:
            if player.champion_id == champion_id:
                return player
        return None

    def roster_key(self) -> tuple:
        """What has to change before the roster is worth re-applying."""
        return tuple((p.champion_id, p.team, p.position, p.spells)
                     for p in self.players)


# ------------------------------------------------------------- parsing
def champion_id_for(raw_name: str, display_name: str,
                    champions: dict[str, Any] | None) -> str:
    """The Data Dragon id of a champion the feed names.

    ``rawChampionName`` carries it ("game_character_displayname_MonkeyKing"),
    which is the only reliable route: the display name is in the client's
    language, and Wukong is not called MonkeyKing in any of them.
    """
    champions = champions or {}
    raw = (raw_name or "").strip()
    if raw.lower().startswith(_CHAMPION_PREFIX):
        candidate = raw[len(_CHAMPION_PREFIX):]
        if candidate in champions or not champions:
            return candidate
        lowered = candidate.lower()
        for champion_id in champions:
            if champion_id.lower() == lowered:
                return champion_id
    wanted = fold(display_name or "")
    if wanted:
        for champion_id, info in champions.items():
            if fold(getattr(info, "name", "")) == wanted or fold(champion_id) == wanted:
                return champion_id
    return ""


_CANONICAL_BY_DDRAGON = {ddragon.lower(): canonical
                         for canonical, ddragon in DDRAGON_SPELL_IDS.items()}


def spell_key_for(entry: dict | None,
                  localised: dict[str, str] | None = None) -> str:
    """The canonical key of one ``summonerSpellOne``/``Two`` entry, or "".

    The raw name carries Data Dragon's id. Upgraded forms keep the family in
    their id -- Unleashed Teleport, the evolved Smites -- so those are matched on
    the family. The localised display name is the last resort.
    """
    if not isinstance(entry, dict):
        return ""
    raw = str(entry.get("rawDisplayName") or "")
    match = _SPELL_ID_RE.search(raw)
    if match:
        spell_id = match.group("id").lower()
        hit = _CANONICAL_BY_DDRAGON.get(spell_id)
        if hit:
            return hit
        # Families whose id changes as the spell upgrades during a game.
        for family, canonical in (("smite", "Smite"), ("teleport", "Teleport"),
                                  ("flash", "Flash")):
            if family in spell_id and "cherry" not in spell_id:
                return canonical
    name = fold(str(entry.get("displayName") or ""))
    if name and localised:
        return localised.get(name, "")
    return ""


def _riot_id(entry: dict) -> str:
    riot_id = str(entry.get("riotId") or "").strip()
    if riot_id:
        return riot_id
    name = str(entry.get("riotIdGameName") or "").strip()
    tag = str(entry.get("riotIdTagLine") or "").strip()
    if name and tag:
        return f"{name}#{tag}"
    return name or str(entry.get("summonerName") or "").strip()


def _names_of(entry: dict) -> set[str]:
    """Every name the feed might use for one player, folded for comparison."""
    names = {_riot_id(entry), str(entry.get("riotIdGameName") or ""),
             str(entry.get("summonerName") or "")}
    return {fold(name) for name in names if name}


def parse_player(entry: dict, champions: dict | None = None,
                 localised_spells: dict[str, str] | None = None) -> LivePlayer:
    spells_entry = entry.get("summonerSpells") or {}
    spells = []
    for slot in ("summonerSpellOne", "summonerSpellTwo"):
        key = spell_key_for(spells_entry.get(slot), localised_spells)
        if key and key not in spells:
            spells.append(key)

    items: list[int] = []
    for item in entry.get("items") or ():
        try:
            items.append(int(item.get("itemID")))
        except (AttributeError, TypeError, ValueError):
            continue

    trees: set[int] = set()
    runes = entry.get("runes") or {}
    for tree in ("primaryRuneTree", "secondaryRuneTree"):
        try:
            trees.add(int((runes.get(tree) or {}).get("id")))
        except (TypeError, ValueError):
            continue

    try:
        level = int(entry.get("level") or 1)
    except (TypeError, ValueError):
        level = 1

    return LivePlayer(
        riot_id=_riot_id(entry),
        champion_id=champion_id_for(str(entry.get("rawChampionName") or ""),
                                    str(entry.get("championName") or ""),
                                    champions),
        champion_name=str(entry.get("championName") or ""),
        team=str(entry.get("team") or "").upper(),
        level=max(1, min(18, level)),
        position=_POSITIONS.get(str(entry.get("position") or "").upper(), ""),
        spells=tuple(spells),
        items=tuple(items),
        rune_trees=frozenset(trees),
        is_bot=bool(entry.get("isBot")),
    )


def parse_game(stats: dict, players: Iterable[dict], active_name: str,
               *, champions: dict | None = None,
               localised_spells: dict[str, str] | None = None,
               fetched_at: float | None = None) -> LiveGame:
    """Turn the three answers into one :class:`LiveGame`. Pure."""
    raw_players = [entry for entry in players if isinstance(entry, dict)]
    parsed = tuple(parse_player(entry, champions, localised_spells)
                   for entry in raw_players)

    active = fold(active_name or "")
    active_team = ""
    if active:
        for entry, player in zip(raw_players, parsed):
            if active in _names_of(entry):
                active_team = player.team
                break

    try:
        map_number = int(stats.get("mapNumber") or 0)
    except (TypeError, ValueError):
        map_number = 0
    try:
        game_time = float(stats.get("gameTime") or 0.0)
    except (TypeError, ValueError):
        game_time = 0.0
    mode = str(stats.get("gameMode") or "")
    return LiveGame(
        mode=mode,
        map_number=map_number,
        category=mode_category(mode, map_number),
        game_time=max(0.0, game_time),
        fetched_at=time.monotonic() if fetched_at is None else fetched_at,
        players=_with_inferred_positions(parsed),
        active_riot_id=active_name or "",
        active_team=active_team,
    )


def _with_inferred_positions(players: tuple[LivePlayer, ...]
                             ) -> tuple[LivePlayer, ...]:
    """Fill in lanes the feed left blank, where they can be known.

    The feed gives a ``position`` in games with assigned roles and leaves it
    empty elsewhere. Only one thing is inferred, and only when it is certain:
    the one player on a team carrying Smite is that team's jungler. Order in the
    list is *not* used -- it is the order players joined, not their lanes, and a
    wrong lane is worse than an unknown one because "jgl flash 950" would then
    time the wrong champion.
    """
    result = list(players)
    for team in {player.team for player in players}:
        members = [i for i, p in enumerate(result) if p.team == team]
        taken = {result[i].position for i in members if result[i].position}
        smiters = [i for i in members if "Smite" in result[i].spells]
        if (len(smiters) == 1 and not result[smiters[0]].position
                and "JUNGLE" not in taken):
            result[smiters[0]] = replace(result[smiters[0]], position="JUNGLE")
    return tuple(result)


# ------------------------------------------------------------- fetching
class LiveClient:
    """Reads the feed. One instance per thread; it holds a session."""

    def __init__(self, base_url: str = BASE_URL,
                 session: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        # See the module docstring: loopback only, no proxy, own certificate.
        self._session.trust_env = False
        self._session.verify = False
        self._session.headers["User-Agent"] = "flashwatch"

    def _get(self, path: str) -> Any:
        response = self._session.get(f"{self.base_url}/{path}",
                                     timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch(self, *, champions: dict | None = None,
              localised_spells: dict[str, str] | None = None) -> LiveGame | None:
        """One reading, or None when no game is answering."""
        try:
            stats = self._get("gamestats")
            players = self._get("playerlist")
        except (requests.RequestException, ValueError) as exc:
            log.debug("live client not answering (%s)", exc)
            return None
        if not isinstance(stats, dict) or not isinstance(players, list):
            return None
        try:
            active = self._get("activeplayername")
        except (requests.RequestException, ValueError):
            # Spectating, or a feed that has not caught up. Still a game; it just
            # has no "enemy" -- see LiveGame.enemies.
            active = ""
        return parse_game(stats, players, str(active or ""),
                          champions=champions,
                          localised_spells=localised_spells)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:                             # noqa: BLE001
            pass


class LiveWatcher(threading.Thread):
    """Polls the feed on its own thread and keeps the latest reading.

    Its own thread because a request, however local, must never hold up the
    capture loop: the loading screen is exactly when the port is open and the
    game is too busy to answer, and that is also when chat is first read.
    """

    def __init__(self, *, wanted: Callable[[], bool],
                 champions: Callable[[], dict] | None = None,
                 localised_spells: Callable[[], dict[str, str]] | None = None,
                 client: LiveClient | None = None) -> None:
        super().__init__(name="LiveClient", daemon=True)
        self._wanted = wanted
        self._champions = champions or (lambda: {})
        self._localised = localised_spells or (lambda: {})
        self._client = client
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._game: LiveGame | None = None
        self._last_answer = 0.0

    # ------------------------------------------------------------------
    @property
    def game(self) -> LiveGame | None:
        """The latest reading, or None if the feed is not answering now."""
        with self._lock:
            return self._game

    @property
    def connected(self) -> bool:
        return self.game is not None

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> LiveGame | None:
        """Take one reading on the calling thread. Used by run() and the tests."""
        if self._client is None:
            self._client = LiveClient()
        game = self._client.fetch(champions=self._champions(),
                                  localised_spells=self._localised())
        with self._lock:
            previous, self._game = self._game, game
        if game is not None:
            self._last_answer = time.monotonic()
            if previous is None:
                log.info("live game data: %s on map %d (%s), %d players, "
                         "%d enemies", game.mode, game.map_number, game.category,
                         len(game.players), len(game.enemies))
        elif previous is not None:
            log.info("live game data stopped answering")
        return game

    def run(self) -> None:
        while not self._stop.is_set():
            wanted = False
            try:
                wanted = bool(self._wanted())
            except Exception:                         # noqa: BLE001
                wanted = False
            if wanted:
                try:
                    self.poll_once()
                except Exception:                     # noqa: BLE001 - must survive
                    log.exception("live client poll failed")
                self._stop.wait(POLL_INTERVAL)
            else:
                with self._lock:
                    self._game = None
                self._stop.wait(IDLE_INTERVAL)
        if self._client is not None:
            self._client.close()
