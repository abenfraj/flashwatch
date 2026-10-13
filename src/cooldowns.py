"""Summoner spell cooldowns, haste, and name normalisation.

The base numbers come from Data Dragon at start-up -- ``summoner.json`` carries
every spell's cooldown for the current patch -- and the table below is only the
fallback for a first start with no network. It used to be the only source, and
it had drifted: Teleport was 360 s two years after Riot cut it to 300, Cleanse
210 s against the game's 240. A hand-kept table is a table that goes wrong one
patch at a time, silently.

Haste is the other half, and it used to be wrong in a different way. Runes and
boots were applied as a percentage off -- Flash x 0.82 with Cosmic Insight, which
is how cooldown reduction worked before 2020. League has used *haste* since:

    cooldown = base x 100 / (100 + haste)

Cosmic Insight is 18 summoner spell haste, so a Flash is 254 s, not 246 s, and
every timer built on the old rule came back eight seconds before the spell did.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Base cooldowns, in seconds. The fallback -- see the module docstring.
# --------------------------------------------------------------------------
COOLDOWNS: dict[str, int] = {
    "Flash": 300,
    "Ghost": 240,
    "Heal": 240,
    "Teleport": 300,
    "Ignite": 180,
    "Barrier": 180,
    "Cleanse": 240,
    "Exhaust": 240,
    # The recharge of a charge, which is what an enemy jungler's Smite timer is
    # about. Data Dragon lists 15 s, the lock-out between two charges, which is
    # why this one value always overrides the downloaded number.
    "Smite": 90,
    # ARAM-only spells. They never appear on Summoner's Rift, but the scoreboard
    # ping announces them with exactly the same wording as the others, so a
    # missing entry here is a line the parser reads correctly and then has to
    # throw away for want of a cooldown.
    "Snowball": 80,
    "Clarity": 240,
}

# Spells whose downloaded cooldown is not the one worth timing.
FIXED_COOLDOWNS = {"Smite": 90}

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
# Summoner spell haste. Additive with each other, then applied once.
# --------------------------------------------------------------------------
HASTE_COSMIC_INSIGHT = 18.0       # the Inspiration rune
HASTE_IONIAN_BOOTS = 10.0         # Ionian Boots of Lucidity (item 3158)
HASTE_CRIMSON_LUCIDITY = 20.0     # its upgrade (item 3171)

# Used only when Data Dragon's item file could not be read, so the two boots
# still count. The live table is parsed from the item descriptions.
FALLBACK_ITEM_SUMMONER_HASTE = {3158: HASTE_IONIAN_BOOTS,
                                3171: HASTE_CRIMSON_LUCIDITY}

# Teleport becomes Unleashed Teleport at 10:00, and from then its cooldown
# depends on the caster's level: 330 s at level 1 down to 240 s at 18.
UNLEASHED_TELEPORT_AT = 600.0
UNLEASHED_TELEPORT_RANGE = (330.0, 240.0)


def apply_haste(base: float, haste: float) -> float:
    """A cooldown after ``haste``: the formula League has used since 2020."""
    haste = max(0.0, float(haste or 0.0))
    return float(base) * 100.0 / (100.0 + haste)


def unleashed_teleport(level: int) -> float:
    """Unleashed Teleport's base cooldown for a champion at ``level``."""
    high, low = UNLEASHED_TELEPORT_RANGE
    level = max(1, min(18, int(level or 1)))
    return high - (high - low) * (level - 1) / 17.0


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
                 ionian_boots: bool = False, haste: float = 0.0,
                 base: float | None = None) -> int:
    """Cooldown in seconds for ``spell``, with summoner haste applied.

    ``base`` overrides the fallback table, and is what callers holding the
    downloaded number pass. ``cosmic_insight`` and ``ionian_boots`` are the two
    global assumptions the settings offer when nothing better is known; ``haste``
    is any further amount, already summed.
    """
    if base is None:
        base = COOLDOWNS.get(spell)
        if base is None:
            raise KeyError(f"unknown summoner spell: {spell!r}")
    total = float(haste or 0.0)
    if cosmic_insight:
        total += HASTE_COSMIC_INSIGHT
    if ionian_boots:
        total += HASTE_IONIAN_BOOTS
    return int(round(apply_haste(base, total)))


def format_remaining(seconds: float) -> str:
    """Format a countdown as ``m:ss``, matching the in-game clock style."""
    if seconds <= 0:
        return "READY"
    total = int(seconds + 0.999)  # show 5:00 for the first instant of a Flash
    return f"{total // 60}:{total % 60:02d}"


def format_short(seconds: float) -> str:
    """A countdown that fits on a spell icon: ``4:23`` down to a minute, then ``47``.

    The way the game's own HUD writes cooldowns, and for the same reason: on a
    20-pixel icon the minutes are noise once fewer than sixty seconds are left.
    """
    if seconds <= 0:
        return ""
    total = int(seconds + 0.999)
    if total < 60:
        return str(total)
    return f"{total // 60}:{total % 60:02d}"
