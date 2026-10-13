"""Data Dragon asset and metadata loader.

This is the only component that talks to the network, and it only ever talks to
Riot's public Data Dragon CDN (static game data and icons). Nothing here
touches the game client, a live match, or any account endpoint.

Everything is fetched in the locale configured by the user so the strings we
later match against OCR output are exactly the strings the game prints. A
French client says "Saut eclair", not "Flash", and hardcoding either would be
wrong -- we ask Riot instead.

Cached on disk under assets/cache/, keyed by patch version, so a restart is
offline and instant. Files left by earlier patches are removed once the current
one has loaded: at two to three megabytes a patch and a patch a fortnight, the
cache otherwise grew by tens of megabytes a year for nobody's benefit.

Three files per patch: the spells (names, cooldowns), the champions (names,
ultimates) and the items -- the last only for the haste they grant, which is what
turns an enemy's boots into the right Flash timer. Items are always read in
English, because that is the wording the haste is parsed out of; nothing from
them is ever shown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from cooldowns import (COOLDOWNS, DDRAGON_SPELL_IDS,
                       FALLBACK_ITEM_SUMMONER_HASTE, FIXED_COOLDOWNS)
from i18n import tr
from settings import CACHE_DIR, CHAMPION_ICON_DIR, SPELL_ICON_DIR, ensure_dirs

log = logging.getLogger(__name__)

DDRAGON = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON}/api/versions.json"
REQUEST_TIMEOUT = 15
ICON_CONCURRENCY = 12

# Ultimates are always the 4th ability in Data Dragon's spell list.
ULTIMATE_INDEX = 3

# Summoner's Rift, in Data Dragon's per-map item availability.
RIFT_MAP = "11"

# How haste reads in an English item description. Two shapes, both real:
# "<attention>20</attention> Ability Haste" in the stats block, and
# "Gain 10 Summoner Spell Haste." in a passive.
_ABILITY_HASTE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:</attention>)?\s*Ability Haste", re.IGNORECASE)
_SUMMONER_HASTE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:</attention>)?\s*Summoner Spell Haste", re.IGNORECASE)

# Every cache file name carries the patch it belongs to, right after the kind.
_CACHE_FILE_RE = re.compile(r"^(?:championFull|summoner|item)-(?P<version>[^-]+)-")


def strip_accents(text: str) -> str:
    """Fold accents away: 'Saut eclair' == 'Saut éclair' as far as OCR cares.

    OCR reliably mangles diacritics at chat font sizes, so every comparison in
    this project happens on the folded form.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold(text: str) -> str:
    """Aggressive normalisation for fuzzy matching: accent-free, lower, alnum."""
    folded = strip_accents(text).lower()
    return "".join(ch for ch in folded if ch.isalnum())


@dataclass(slots=True)
class SpellInfo:
    """A summoner spell, with both its canonical and localised names."""

    canonical: str                 # English key used everywhere internally
    ddragon_id: str                # e.g. SummonerFlash
    name: str                      # localised display name
    cooldown: float                # seconds, base, from this patch's data
    icon_path: Path | None = None


@dataclass(slots=True)
class UltimateInfo:
    """A champion ultimate. Cooldown varies by rank, hence the list."""

    name: str                      # localised display name
    ddragon_id: str                # spell image id, e.g. AhriTumble
    cooldown_by_rank: list[float]  # index 0 == rank 1
    icon_path: Path | None = None

    def cooldown_for_rank(self, rank: int) -> float:
        if not self.cooldown_by_rank:
            return 0.0
        index = max(0, min(rank - 1, len(self.cooldown_by_rank) - 1))
        return self.cooldown_by_rank[index]

    def rank_at_level(self, level: int) -> int:
        """The rank this ultimate most likely has at champion ``level``.

        Almost every ultimate unlocks at 6 and ranks up at 11 and 16. The few
        with a fourth rank (Karma, Jayce, Elise, Nidalee...) have it from level 1,
        on the same 5-level rhythm. A player can delay a rank, but almost nobody
        does, and it is still far better than guessing from the game clock.
        """
        level = max(1, min(18, int(level or 1)))
        ranks = len(self.cooldown_by_rank)
        thresholds = (1, 6, 11, 16) if ranks >= 4 else (6, 11, 16)
        rank = sum(1 for threshold in thresholds if level >= threshold)
        return max(1, min(max(1, ranks), rank))


@dataclass(slots=True)
class ChampionInfo:
    """A champion plus the data needed to render and time them."""

    champion_id: str               # Data Dragon id, e.g. "MonkeyKing"
    key: str                       # numeric key as string
    name: str                      # localised display name
    ultimate: UltimateInfo | None = None
    icon_path: Path | None = None
    aliases: set[str] = field(default_factory=set)


class RiotAssets:
    """Loads, caches and exposes the static game data the app needs."""

    def __init__(self, locale: str = "en_US") -> None:
        self.locale = locale
        self.version: str | None = None
        self.champions: dict[str, ChampionInfo] = {}     # champion_id -> info
        self.spells: dict[str, SpellInfo] = {}           # canonical -> info
        # Haste each item grants, by item id, on Summoner's Rift.
        self.item_summoner_haste: dict[int, float] = dict(FALLBACK_ITEM_SUMMONER_HASTE)
        self.item_ability_haste: dict[int, float] = {}
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "flashwatch/1.0"
        # As many pooled connections as there are parallel icon downloads.
        # urllib3's default of ten under twelve workers threw a connection away
        # on every burst, and said so in the log each time.
        adapter = requests.adapters.HTTPAdapter(pool_connections=4,
                                                pool_maxsize=ICON_CONCURRENCY)
        self._session.mount("https://", adapter)
        self.ready = False
        self.icons_ready = False

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _get_json(self, url: str) -> Any:
        response = self._session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def _cached_json(self, cache_name: str, url: str) -> Any:
        """Fetch ``url``, or fall back to the on-disk copy if the network fails.

        Cache files are version-stamped by the caller, so a hit is always for
        the right patch and we never serve stale champion data.
        """
        path = CACHE_DIR / cache_name
        if path.exists():
            try:
                return json.loads(path.read_text("utf-8"))
            except ValueError:
                log.warning("cache %s is corrupt, refetching", path)
        data = self._get_json(url)
        try:
            path.write_text(json.dumps(data), "utf-8")
        except OSError as exc:
            log.warning("could not cache %s (%s)", path, exc)
        return data

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    def bootstrap(self, progress: Callable[[str], None] | None = None) -> None:
        """Resolve the patch version and load champion + spell metadata.

        Blocking, but only ever called from a worker thread. Falls back to any
        cached patch if the CDN is unreachable so the app still starts offline.
        """
        ensure_dirs()
        report = progress or (lambda _msg: None)

        report(tr("assets.version"))
        self.version = self._resolve_version()
        report(tr("assets.patch", version=self.version, locale=self.locale))

        self._load_summoner_spells()
        report(tr("assets.spells", count=len(self.spells)))

        self._load_champions()
        report(tr("assets.champions", count=len(self.champions)))
        # Optional: without it the two boots still count, from the fallback
        # table, and nothing else depends on the file.
        try:
            self._load_items()
        except (requests.RequestException, ValueError, OSError) as exc:
            log.warning("item data unavailable, using the built-in haste table "
                        "(%s)", exc)
        self.ready = True
        self.prune_cache()

    def _resolve_version(self) -> str:
        marker = CACHE_DIR / "version.txt"
        try:
            versions = self._get_json(VERSIONS_URL)
            if isinstance(versions, list) and versions:
                version = str(versions[0])
                marker.write_text(version, "utf-8")
                return version
        except (requests.RequestException, ValueError, OSError) as exc:
            log.warning("could not resolve latest patch (%s)", exc)
        if marker.exists():
            cached = marker.read_text("utf-8").strip()
            if cached:
                log.info("falling back to cached patch %s", cached)
                return cached
        raise RuntimeError(tr("assets.offline"))

    def _load_summoner_spells(self) -> None:
        url = f"{DDRAGON}/cdn/{self.version}/data/{self.locale}/summoner.json"
        data = self._cached_json(f"summoner-{self.version}-{self.locale}.json", url)
        by_id = {
            entry["id"]: entry
            for entry in data.get("data", {}).values()
            if isinstance(entry, dict) and "id" in entry
        }

        for canonical, ddragon_id in DDRAGON_SPELL_IDS.items():
            entry = by_id.get(ddragon_id)
            if entry is None:
                log.warning("summoner spell %s missing from Data Dragon", ddragon_id)
                continue
            self.spells[canonical] = SpellInfo(
                canonical=canonical,
                ddragon_id=ddragon_id,
                name=str(entry.get("name") or canonical),
                cooldown=self._patch_cooldown(canonical, entry),
            )

    @staticmethod
    def _patch_cooldown(canonical: str, entry: dict[str, Any]) -> float:
        """This patch's cooldown for a spell, from its Data Dragon entry.

        The table in cooldowns.py is the fallback, not the source. A value that
        does not parse, or one too small to be real, is a data problem and not a
        free spell, so the table answers instead.
        """
        fixed = FIXED_COOLDOWNS.get(canonical)
        if fixed is not None:
            return float(fixed)
        try:
            value = float((entry.get("cooldown") or [0])[0])
        except (TypeError, ValueError, IndexError):
            value = 0.0
        if value < 5:
            return float(COOLDOWNS[canonical])
        if value != COOLDOWNS[canonical]:
            log.info("%s cooldown this patch: %.0fs", canonical, value)
        return value

    def _load_items(self) -> None:
        """The haste every Summoner's Rift item grants, read from its tooltip.

        Data Dragon's ``stats`` block has no field for haste, so the number is
        taken from the description, which is why this file is always the English
        one: the pattern is English, and the numbers are the same in every
        language.
        """
        url = f"{DDRAGON}/cdn/{self.version}/data/en_US/item.json"
        data = self._cached_json(f"item-{self.version}-en_US.json", url)
        summoner: dict[int, float] = {}
        ability: dict[int, float] = {}
        for item_id, entry in (data.get("data") or {}).items():
            if not isinstance(entry, dict):
                continue
            maps = entry.get("maps") or {}
            if maps and not maps.get(RIFT_MAP, False):
                continue
            try:
                key = int(item_id)
            except (TypeError, ValueError):
                continue
            description = str(entry.get("description") or "")
            found = _SUMMONER_HASTE_RE.search(description)
            if found:
                summoner[key] = float(found.group(1))
            found = _ABILITY_HASTE_RE.search(description)
            if found:
                ability[key] = float(found.group(1))
        if summoner:
            self.item_summoner_haste = summoner
        self.item_ability_haste = ability
        log.info("items: %d grant summoner haste, %d ability haste",
                 len(summoner), len(ability))

    def summoner_haste(self, items) -> float:
        """Summoner spell haste from a list of item ids."""
        return float(sum(self.item_summoner_haste.get(int(item), 0.0)
                         for item in items or ()))

    def ability_haste(self, items) -> float:
        """Ability haste from a list of item ids. Items only: runes are hidden."""
        return float(sum(self.item_ability_haste.get(int(item), 0.0)
                         for item in items or ()))

    def prune_cache(self) -> int:
        """Delete data files for patches other than the one now loaded.

        Every locale of the current patch is kept -- switching language should
        not have to download again -- and icons are not touched, since they are
        keyed by name rather than patch and are mostly the same from one to the
        next. Never raises: a file in use or a read-only folder only means the
        old copy stays a little longer.
        """
        if not self.version:
            return 0
        removed = 0
        try:
            candidates = list(CACHE_DIR.glob("*.json"))
        except OSError:
            return 0
        for path in candidates:
            match = _CACHE_FILE_RE.match(path.name)
            if match is None or match.group("version") == self.version:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                log.debug("could not remove %s (%s)", path, exc)
        if removed:
            log.info("removed %d data file(s) from earlier patches", removed)
        return removed

    def _load_champions(self) -> None:
        """Load every champion, including ultimate data, in one request.

        championFull.json is a few megabytes but replaces ~170 per-champion
        requests, and it is cached after the first run.
        """
        url = f"{DDRAGON}/cdn/{self.version}/data/{self.locale}/championFull.json"
        data = self._cached_json(f"championFull-{self.version}-{self.locale}.json", url)

        for champion_id, entry in data.get("data", {}).items():
            if not isinstance(entry, dict):
                continue
            ultimate = self._parse_ultimate(entry)
            info = ChampionInfo(
                champion_id=champion_id,
                key=str(entry.get("key", "")),
                name=str(entry.get("name") or champion_id),
                ultimate=ultimate,
            )
            info.aliases = self._champion_aliases(info)
            self.champions[champion_id] = info

    @staticmethod
    def _parse_ultimate(entry: dict[str, Any]) -> UltimateInfo | None:
        spells = entry.get("spells")
        if not isinstance(spells, list) or len(spells) <= ULTIMATE_INDEX:
            return None
        ult = spells[ULTIMATE_INDEX]
        if not isinstance(ult, dict):
            return None
        raw_cooldowns = ult.get("cooldown")
        cooldowns: list[float] = []
        if isinstance(raw_cooldowns, list):
            for value in raw_cooldowns:
                try:
                    cooldowns.append(float(value))
                except (TypeError, ValueError):
                    continue
        image_id = ult.get("id") or ""
        return UltimateInfo(
            name=str(ult.get("name") or "Ultime"),
            ddragon_id=str(image_id),
            cooldown_by_rank=cooldowns,
        )

    @staticmethod
    def _champion_aliases(info: ChampionInfo) -> set[str]:
        """Folded strings that should resolve to this champion.

        Includes the localised name, the Data Dragon id, and each word of a
        multi-word name, since OCR often clips 'Nunu et Willump' down to a
        single token.
        """
        aliases = {fold(info.name), fold(info.champion_id)}
        for part in strip_accents(info.name).replace("'", " ").split():
            token = fold(part)
            # Skip French joining words, they identify nothing on their own.
            if len(token) >= 4 and token not in {"and", "willump"}:
                aliases.add(token)
        aliases.discard("")
        return aliases

    # ------------------------------------------------------------------
    # Icons
    # ------------------------------------------------------------------
    async def _download_icons_async(
        self, progress: Callable[[str], None] | None = None
    ) -> None:
        report = progress or (lambda _msg: None)
        jobs: list[tuple[str, Path]] = []

        for spell in self.spells.values():
            path = SPELL_ICON_DIR / f"{spell.ddragon_id}.png"
            spell.icon_path = path
            if not path.exists():
                jobs.append(
                    (f"{DDRAGON}/cdn/{self.version}/img/spell/{spell.ddragon_id}.png", path)
                )

        for champion in self.champions.values():
            path = CHAMPION_ICON_DIR / f"{champion.champion_id}.png"
            champion.icon_path = path
            if not path.exists():
                jobs.append(
                    (f"{DDRAGON}/cdn/{self.version}/img/champion/{champion.champion_id}.png", path)
                )
            ult = champion.ultimate
            if ult and ult.ddragon_id:
                ult_path = SPELL_ICON_DIR / f"{ult.ddragon_id}.png"
                ult.icon_path = ult_path
                if not ult_path.exists():
                    jobs.append(
                        (f"{DDRAGON}/cdn/{self.version}/img/spell/{ult.ddragon_id}.png", ult_path)
                    )

        if not jobs:
            self.icons_ready = True
            report(tr("assets.icons_cached"))
            return

        report(tr("assets.icons_downloading", count=len(jobs)))
        semaphore = asyncio.Semaphore(ICON_CONCURRENCY)
        done = 0

        async def fetch(url: str, path: Path) -> None:
            nonlocal done
            async with semaphore:
                await asyncio.to_thread(self._download_file, url, path)
            done += 1
            if done % 25 == 0 or done == len(jobs):
                report(tr("assets.icons_progress", done=done, total=len(jobs)))

        await asyncio.gather(*(fetch(url, path) for url, path in jobs))
        self.icons_ready = True

    def _download_file(self, url: str, path: Path) -> None:
        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            log.debug("icon download failed for %s (%s)", url, exc)
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(response.content)
            tmp.replace(path)
        except OSError as exc:
            log.debug("could not save icon %s (%s)", path, exc)

    def download_icons(self, progress: Callable[[str], None] | None = None) -> None:
        """Blocking wrapper around the async icon fetch."""
        asyncio.run(self._download_icons_async(progress))

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def champion_by_name(self, name: str) -> ChampionInfo | None:
        target = fold(name)
        if not target:
            return None
        for champion in self.champions.values():
            if target in champion.aliases:
                return champion
        return None

    def spell_by_localised_name(self, name: str) -> SpellInfo | None:
        target = fold(name)
        if not target:
            return None
        for spell in self.spells.values():
            if fold(spell.name) == target:
                return spell
        return None

    def champion_names(self) -> Iterable[str]:
        return (champion.name for champion in self.champions.values())

    def icon_for_champion(self, champion_id: str) -> Path | None:
        """Where this champion's square icon is, if it has been downloaded.

        Falls back to the conventional path, the way the spell lookup below
        already does. ``icon_path`` is only filled in by the download pass, so
        without this an icon cached by a *previous* run is invisible until the
        current one has been through :meth:`download_icons` -- which is what left
        the role reader with nothing to match against on start-up.
        """
        champion = self.champions.get(champion_id)
        if champion and champion.icon_path and champion.icon_path.exists():
            return champion.icon_path
        path = CHAMPION_ICON_DIR / f"{champion_id}.png"
        return path if path.exists() else None

    def icon_for_spell(self, canonical_or_ddragon_id: str) -> Path | None:
        spell = self.spells.get(canonical_or_ddragon_id)
        ddragon_id = spell.ddragon_id if spell else canonical_or_ddragon_id
        path = SPELL_ICON_DIR / f"{ddragon_id}.png"
        return path if path.exists() else None
