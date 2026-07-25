"""Data Dragon asset and metadata loader.

This is the only component that talks to the network, and it only ever talks to
Riot's public Data Dragon CDN (static game data and icons). Nothing here
touches the game client, a live match, or any account endpoint.

Everything is fetched in the locale configured by the user so the strings we
later match against OCR output are exactly the strings the game prints. A
French client says "Saut eclair", not "Flash", and hardcoding either would be
wrong -- we ask Riot instead.

Cached on disk under assets/cache/, keyed by patch version, so a restart is
offline and instant.
"""

from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from cooldowns import COOLDOWNS, DDRAGON_SPELL_IDS
from i18n import tr
from settings import CACHE_DIR, CHAMPION_ICON_DIR, SPELL_ICON_DIR, ensure_dirs

log = logging.getLogger(__name__)

DDRAGON = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON}/api/versions.json"
REQUEST_TIMEOUT = 15
ICON_CONCURRENCY = 12

# Ultimates are always the 4th ability in Data Dragon's spell list.
ULTIMATE_INDEX = 3


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
    cooldown: int                  # seconds, base
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

    def __init__(self, locale: str = "fr_FR") -> None:
        self.locale = locale
        self.version: str | None = None
        self.champions: dict[str, ChampionInfo] = {}     # champion_id -> info
        self.spells: dict[str, SpellInfo] = {}           # canonical -> info
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "lol-auto-timers/1.0"
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
        self.ready = True

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
                cooldown=COOLDOWNS[canonical],
            )

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
        champion = self.champions.get(champion_id)
        if champion and champion.icon_path and champion.icon_path.exists():
            return champion.icon_path
        return None

    def icon_for_spell(self, canonical_or_ddragon_id: str) -> Path | None:
        spell = self.spells.get(canonical_or_ddragon_id)
        ddragon_id = spell.ddragon_id if spell else canonical_or_ddragon_id
        path = SPELL_ICON_DIR / f"{ddragon_id}.png"
        return path if path.exists() else None
