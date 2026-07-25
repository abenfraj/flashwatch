"""Summoner spell cooldown table and name normalisation.

Single source of truth for every cooldown used by the application. Values are
the base (unmodified) cooldowns in seconds.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Base cooldowns, in seconds.
# --------------------------------------------------------------------------
COOLDOWNS: dict[str, int] = {
    "Flash": 300,
    "Ghost": 240,
    "Heal": 240,
    "Teleport": 360,
    "Ignite": 180,
    "Barrier": 180,
    "Cleanse": 210,
    "Exhaust": 240,
    "Smite": 90,
    # ARAM-only spells. They never appear on Summoner's Rift, but the scoreboard
    # ping announces them with exactly the same wording as the others, so a
    # missing entry here is a line the parser reads correctly and then has to
    # throw away for want of a cooldown.
    "Snowball": 80,
    "Clarity": 240,
}

SPELL_NAMES: tuple[str, ...] = tuple(COOLDOWNS)

# Data Dragon asset id for each spell, used to fetch the icon.
DDRAGON_SPELL_IDS: dict[str, str] = {
    "Flash": "SummonerFlash",
    "Ghost": "SummonerHaste",
    "Heal": "SummonerHeal",
    "Teleport": "SummonerTeleport",
    "Ignite": "SummonerDot",
    "Barrier": "SummonerBarrier",
    "Cleanse": "SummonerBoost",
    "Exhaust": "SummonerExhaust",
    "Smite": "SummonerSmite",
    "Snowball": "SummonerSnowball",
    "Clarity": "SummonerMana",
}

# Aliases and common OCR mangles. Keys are lower-case, stripped of spaces.
# OCR routinely swaps 0/o, 1/l/i, 5/s and drops the last glyph of a word, so a
# handful of hand-written variants buys a lot of reliability before the fuzzy
# matcher in message_parser has to guess.
ALIASES: dict[str, str] = {
    # Flash
    "flash": "Flash", "flas": "Flash", "fla5h": "Flash", "flashh": "Flash",
    "f1ash": "Flash", "flash!": "Flash", "fl": "Flash", "flsh": "Flash",
    # Ghost
    "ghost": "Ghost", "gho5t": "Ghost", "ghos": "Ghost",
    "haste": "Ghost", "gh": "Ghost",
    # Heal
    "heal": "Heal", "hea1": "Heal", "hea": "Heal",
    # Teleport
    "teleport": "Teleport", "telepor": "Teleport", "te1eport": "Teleport",
    "tp": "Teleport", "teley": "Teleport",
    # Ignite
    "ignite": "Ignite", "ignit": "Ignite", "1gnite": "Ignite", "ign": "Ignite",
    # Barrier
    "barrier": "Barrier", "barier": "Barrier", "barrie": "Barrier",
    # Cleanse
    "cleanse": "Cleanse", "cleans": "Cleanse", "c1eanse": "Cleanse",
    # Exhaust
    "exhaust": "Exhaust", "exhau5t": "Exhaust", "exhaus": "Exhaust",
    "exh": "Exhaust",
    # Smite
    "smite": "Smite", "5mite": "Smite", "smit": "Smite",
    # Snowball -- "Boule de neige" in French, "Mark" in English.
    "snowball": "Snowball", "5nowball": "Snowball", "snowbal": "Snowball",
    "bouledeneige": "Snowball", "bouledeneig": "Snowball",
    "mark": "Snowball", "marque": "Snowball",
    # Clarity
    "clarity": "Clarity", "c1arity": "Clarity", "clarte": "Clarity",
    "clart": "Clarity",
}

# --------------------------------------------------------------------------
# Optional cooldown modifiers. Multiplicative on the base cooldown.
# Riot's summoner-spell haste sources stack multiplicatively with each other.
# --------------------------------------------------------------------------
MODIFIER_COSMIC_INSIGHT = 0.82   # Cosmic Insight rune: 18% summoner haste
MODIFIER_IONIAN_BOOTS = 0.88     # Ionian Boots of Lucidity: 12% summoner haste


def normalise_spell(raw: str) -> str | None:
    """Map an OCR'd token onto a canonical spell name, or None."""
    if not raw:
        return None
    key = "".join(ch for ch in raw.lower() if ch.isalnum())
    if not key:
        return None
    hit = ALIASES.get(key)
    if hit:
        return hit
    for name in SPELL_NAMES:
        if key == name.lower():
            return name
    return None


def get_cooldown(spell: str, *, cosmic_insight: bool = False,
                 ionian_boots: bool = False) -> int:
    """Cooldown in seconds for ``spell``, with optional haste sources applied."""
    base = COOLDOWNS.get(spell)
    if base is None:
        raise KeyError(f"unknown summoner spell: {spell!r}")
    value = float(base)
    if cosmic_insight:
        value *= MODIFIER_COSMIC_INSIGHT
    if ionian_boots:
        value *= MODIFIER_IONIAN_BOOTS
    return int(round(value))


def format_remaining(seconds: float) -> str:
    """Format a countdown as ``m:ss``, matching the in-game clock style."""
    if seconds <= 0:
        return "READY"
    total = int(seconds + 0.999)  # show 5:00 for the first instant of a Flash
    return f"{total // 60}:{total % 60:02d}"
