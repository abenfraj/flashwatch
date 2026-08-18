"""Turn raw OCR text into confirmed spell-usage events.

When a player pings a spell tracker, the *game* composes the chat line, but it
attributes it to the player who pinged. Observed in the Practice Tool:

    Joueur (Champion): Attendez Ahri Saut eclair - 245 sec.
    |___ author ____|  |wait|  |target| |_spell_|   |left|

Two things follow.

**The author prefix is not evidence of a human.** An earlier version of this
module rejected any line carrying `Nom (Champion):`, reasoning that only typed
messages have one. That threw away the real message. The prefix is stripped and
ignored; the structured wording is what identifies a system line, since a player
would not type "Attendez <champion> <sort> - <n> sec.".

**The remaining cooldown is stated outright.** That is better than a cast
announcement: there is nothing to infer from when the cast happened, and it makes
*ultimate* timers exact as well, because the game supplies the number instead of
this app guessing an ability rank and haste.

A second form, announcing the cast itself, is also accepted:

    (14:23) Ahri a utilise Saut eclair

This one *also* arrives attributed, and that cost us the feature for a while.
Pinging a spell that is off cooldown produces the cast wording rather than the
"Attendez" wording, so what the game actually prints is:

    02:21 Nelo Angelo (Ambessa): Morgana a utilise Saut eclair

An earlier version rejected the cast form outright whenever it carried an author
prefix, on the grounds that a teammate could type "Ahri a utilise son flash".
Since every ping is attributed, that rejected every ping -- the same mistake the
"Attendez" form had already been fixed for.

The prefix is therefore not what separates the two. The *wording* is: the game
prints the champion's name and the spell's localised name, on their own and
spelled out in full, while a player types loosely. So an attributed cast line is
held to the game's exact phrasing -- no determiner ("son flash"), nothing but the
name on the champion side, and the localised spell name rather than the English
one. Glyph-level fuzziness stays, since OCR still has to be forgiven.

A third form names a spell without claiming it was cast:

    02:21 Nelo Angelo (Ambessa): Morgana Saut eclair

There is no verb and no stated cooldown, so nothing in it can be verified, and it
is indistinguishable in shape from a player typing the same two words. It is
still worth having -- it is evidence, just not proof -- so it produces an event
marked ``certain=False``. The timer that follows is shown with a question mark,
and a later confirmed line for the same spell clears the mark without disturbing
the countdown. Being wrong about one of these costs a question mark rather than a
wrong timer presented as fact.

A fourth form is not the game speaking at all -- it is a teammate calling a
timer, which is how half of League communicates cooldowns:

    (12:04) Bob (Ahri): jgl flash 950
                        |tgt| |sll| |up at 9:50|

Everything above exists to tell the game's own wording apart from a human's.
This form is the exception that proves it: it is *only* ever human, so it is
recognised by its shape rather than by its trustworthiness -- a role or champion,
a spell, and a time -- and it is acted on because somebody deliberately typed it.
The number is a point on the game clock, not a duration: "950" means the spell is
back at 9:50, which is what players mean and what makes a call read late still
land on the right second. It can be switched off in the settings, since a team
that calls timers wrongly is worse than a team that does not call them at all.

Anything else -- ordinary player chat, emotes, the kill feed -- falls through and
is discarded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from cooldowns import COOLDOWNS, normalise_spell
from riot_assets import ChampionInfo, RiotAssets, fold, strip_accents
from roles import role_from_word

log = logging.getLogger(__name__)

# Verb phrases the game uses to announce a tracked cast. Folded before use, so
# accents and case are irrelevant. Extend this list to support more locales.
#
# Deliberately excludes possessives ("a utilise son"). Matching is done on the
# accent- and space-stripped form, where "a utilise Saut eclair" contains
# "autilisesa" -- so folding the possessive into the verb makes it swallow the
# first letters of the spell name. Possessives are stripped from the spell side
# by _strip_determiners instead.
SYSTEM_VERBS: tuple[str, ...] = (
    "autilise",       # fr_FR: "a utilise" / "a utilisé"
    "hasused",        # en_US: "Ahri has used Flash"
    # en_US also prints the simple past. Listed after "hasused" only for
    # readability -- the longest match at a position wins, so "has used" is never
    # split on the "used" inside it. A stray "used" in typed chat costs nothing:
    # a cast announcement is only trusted without an author prefix, and the split
    # still has to yield a champion on the left and a spell on the right.
    "used",           # en_US: "Ahri used Flash"
)

# Articles and possessives that may sit between the verb and the spell name.
DETERMINERS = frozenset({
    "son", "sa", "ses", "leur", "leurs", "le", "la", "les", "l",
    "his", "her", "their", "the", "a", "an",
})

# A chat timestamp, optionally wrapped in brackets or parens.
#
# Digit positions accept the glyphs OCR confuses with digits, otherwise a
# mangled "l4:23" matches as "4:23" and we silently lose the leading digit --
# which corrupts both the dedupe key and the ultimate-rank estimate. The
# captured text is repaired and validated below, so a false match is cheap.
# Conservative: used for timestamps, where a false match would corrupt the game
# clock and therefore every delay correction. Only the classic confusions.
_DIGIT = r"[0-9OolIiSsBZ]"
# Liberal: used only for the "- N sec." count, which sits in a rigid context and
# is range-checked afterwards, so a stray match costs nothing.
_DIGIT_LOOSE = r"[0-9OoDQlIij|SsBZzGTgq]"
TIMESTAMP_RE = re.compile(
    rf"(?<![0-9A-Za-z])[\[\(]?\s*({_DIGIT}{{1,2}})\s*[:;.]\s*({_DIGIT}{{2}})\s*[\]\)]?"
)

# An author prefix: "Bob (Ahri):" or "Bob:". Stripped, never used to reject --
# the game's own ping messages carry the pinging player's name. Only meaningful
# once the timestamp has been removed, since timestamps contain a colon too.
AUTHOR_PREFIX_RE = re.compile(r"^\s*[^:]{1,40}:\s*")

# "Attendez <champion> <sort> - 245 sec." and its English equivalent. Matched on
# the accent-stripped text, and the digits accept OCR's usual lookalikes.
#
# Two details keep the liberal digit class from firing inside a champion's name.
# The count must follow a separator, and its suffix must contain "ec" -- a bare
# "s" was enough before, so "Aphelios" parsed as "Apheli" + "o" (read as 0) + "s"
# (read as seconds), matched, and was then discarded as an implausible 0. Ziggs
# and Miss Fortune broke the same way.
_SEC_WORD = r"[s5S$]ec(?:onde?s?|ond?s?)?"
WAIT_RE = re.compile(
    rf"\b(?:attendez|attendre|wait)\s+(?P<middle>.{{2,60}}?)"
    rf"(?:"
    # Dashed form: "- 245 sec." or, because a dash is already strong context,
    # a bare "- 245 s" where OCR clipped the unit.
    rf"[\s:]*[-–—]\s*(?P<secs_dash>{_DIGIT_LOOSE}{{1,4}})\s*(?:{_SEC_WORD}|s)\b"
    rf"|"
    # No dash: the unit must contain "ec", otherwise a lone "s" inside a
    # champion's name passes for seconds.
    rf"[\s:]+(?P<secs_plain>{_DIGIT_LOOSE}{{1,4}})\s*{_SEC_WORD}\b"
    rf")",
    re.IGNORECASE,
)

# How many trailing words to try when splitting "<champion> <spell>". Sized from
# the actual data rather than guessed: the longest French ultimate name is six
# words ("Super roquette de la mort !"), and punctuation such as the colon in
# "Ordre : Onde de choc" tokenises separately, so a little headroom on top.
MAX_SPELL_WORDS = 8

# OCR routinely swaps these inside digit runs. Must cover every character the
# _DIGIT class below accepts, or a match is found and then fails to convert --
# "100" read as "io0" was matched and then thrown away for exactly that reason.
DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0",
                             "l": "1", "I": "1", "i": "1", "j": "1", "|": "1",
                             "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2",
                             "G": "6", "T": "7", "g": "9", "q": "9"})

MIN_CHAMPION_RATIO = 0.78
MIN_SPELL_RATIO = 0.80

# A chat line leads with the game clock. Allowing a few characters of slack
# covers an OCR'd bracket or stray speck before it.
CHAT_PREFIX_WINDOW = 10

# A timestamped row must carry this much text before it counts as a chat line.
# "(12:04)" on its own is a clock, not a message.
MIN_CHAT_LINE_LENGTH = 14

# ---------------------------------------------------------------- calls
# What a player types to say when a spell comes back: "jgl flash 950".
#
# Only real digits are accepted here, unlike every other number in this module.
# Elsewhere the text comes from the game's own rendering and OCR's confusions have
# to be forgiven; a call is short, typed, and its three parts each have to parse,
# so letting "9SO" through would buy nothing and would let ordinary chat in.
CALL_TIME_RE = re.compile(r"^(?:(\d{1,2})\s*[:.,;h]\s*(\d{2})|(\d{1,4}))$")

# How many words a call may be. Three is the shape ("jgl flash 950"); the slack
# covers a two-word champion, a two-word spell name and a stray token.
MAX_CALL_WORDS = 7

# Words that name an ultimate without naming the ability.
CALL_ULT_WORDS = frozenset({"ult", "ulti", "ultime", "ultimate", "r"})

# Longest cooldown in the game, plus room for a call typed a few seconds late.
# A call pointing further ahead than this is not a cooldown, it is a number that
# happened to sit at the end of a sentence.
MAX_CALL_LEAD = max(COOLDOWNS.values()) + 60


def parse_clock(text: str) -> int | None:
    """Read a ``mm:ss`` clock out of OCR text, in seconds.

    Shared with the chat parser on purpose: the game clock drawn at the top of
    the screen and the clock prefixing a chat line are the same glyphs read by
    the same engine, so they deserve the same tolerance for OCR's digit
    lookalikes and the same sanity limits.
    """
    match = TIMESTAMP_RE.search(text or "")
    if match is None:
        return None
    try:
        minutes = int(match.group(1).translate(DIGIT_FIXES))
        seconds = int(match.group(2).translate(DIGIT_FIXES))
    except ValueError:
        return None
    if seconds > 59 or minutes > 120:
        return None
    return minutes * 60 + seconds


def _letter_count(text: str) -> int:
    return sum(1 for char in text if char.isalpha())


def _starts_capitalised(text: str) -> bool:
    """Whether the first letter of ``text`` is upper case.

    The discriminator of last resort on an attributed line, and the only one left
    on an English client: there the localised spell name *is* the English one, so
    the game's "Ahri used Flash" and a player's "ahri used flash" differ in
    nothing else. The game always writes both names out properly capitalised.
    """
    for char in text:
        if char.isalpha():
            return char.isupper()
    return False


def looks_like_chat_line(text: str) -> bool:
    """Whether ``text`` has the shape of a chat line.

    This is how the chat area is located, so it keys on content rather than
    geometry: scenery cannot produce any of these forms.

    Chat timestamps are a client option and the spell-tracker pings do not
    necessarily carry one, so a clock alone is too narrow an anchor -- the
    author prefix and the cooldown wording count too.
    """
    if len(text) < 6:
        return False

    # A timestamp alone is not enough. Clocks appear elsewhere on screen, and a
    # lone one was enough to "confirm" a chat region in the middle of the screen.
    # A real chat line carries a message after its timestamp.
    match = TIMESTAMP_RE.search(text)
    if (match is not None and match.start() <= CHAT_PREFIX_WINDOW
            and len(text) >= MIN_CHAT_LINE_LENGTH):
        return True

    plain = strip_accents(text)
    if WAIT_RE.search(plain):
        return True

    # "Nom (Champion): quelque chose" -- an author prefix followed by content.
    # Both halves must contain letters: without that test "(12:34)" qualifies,
    # because "(12" passes for a name and "34)" for a message.
    prefix_match = AUTHOR_PREFIX_RE.match(text)
    if prefix_match is not None:
        author = prefix_match.group(0)
        remainder = text[prefix_match.end():].strip()
        if (_letter_count(author) >= 2 and len(remainder) >= 4
                and _letter_count(remainder) >= 2):
            return True

    folded = fold(text)
    return any(verb in folded for verb in SYSTEM_VERBS)


def _edit_budget(length: int) -> int:
    """How many wrong glyphs to forgive in a string of this length.

    A similarity ratio alone is unfair to short names: one bad glyph in "Ahri"
    scores 0.75 and would be rejected, while one bad glyph in "Teleportation"
    scores 0.92 and sails through. Budgeting by length treats them equally.
    """
    if length <= 6:
        return 1
    if length <= 12:
        return 2
    return 3


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, giving up once it provably exceeds ``limit``."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        best_in_row = i
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            best_in_row = min(best_in_row, value)
        if best_in_row > limit:
            return limit + 1
        previous = current
    return previous[-1]


@dataclass(slots=True)
class SpellEvent:
    """A game-confirmed spell state: either a cast, or a stated cooldown."""

    champion_id: str
    champion_name: str
    kind: str                 # "summoner" or "ultimate"
    spell_key: str            # canonical spell name, or "ULT"
    spell_name: str           # localised display name
    game_time: int | None     # seconds on the game clock, from the timestamp
    raw_line: str
    signature: str            # stable dedupe key
    # False for the bare "<Champion> <Sort>" form, which names a spell without
    # ever saying it was cast. Such an event still starts a timer, shown with a
    # question mark, and a later confirmed line clears the mark.
    certain: bool = True
    # Set when the game stated the cooldown outright ("- 245 sec."). Exact, and
    # preferred over deriving a timer from a cast time.
    remaining_seconds: int | None = None
    # The lane a player called, when they named one instead of a champion
    # ("jgl flash 950"). Resolved to a champion by the timer manager, which is
    # what knows who plays where; the parser has no business knowing that.
    target_role: str = ""
    # Absolute point on the game clock at which the spell is back up. A called
    # time is stated this way rather than as a duration, because that is what the
    # number in "jgl flash 950" is.
    ready_at_game: int | None = None
    # "game" for anything the client printed, "call" for a teammate's timer call.
    # The distinction decides whether the event may be acted on at all: calls are
    # a setting, since a team that calls timers badly is worse than one that does
    # not call them.
    source: str = "game"

    @property
    def is_ultimate(self) -> bool:
        return self.kind == "ultimate"

    @property
    def is_exact(self) -> bool:
        return self.remaining_seconds is not None

    @property
    def is_call(self) -> bool:
        return self.source == "call"


def _best_match(candidate: str, options: dict[str, str],
                threshold: float, *, allow_ratio: bool = True) -> str | None:
    """Fuzzy-match ``candidate`` against ``{folded_option: return_value}``.

    Accepts a match on either a similarity ratio or a length-aware edit budget,
    then rejects the result if a *different* value ties for best distance.
    Naming the wrong champion starts a wrong timer, which is worse than showing
    none at all, so ambiguity resolves to None.
    """
    if not candidate:
        return None
    if candidate in options:
        return options[candidate]

    budget = _edit_budget(len(candidate))
    best_value: str | None = None
    best_distance = budget + 1
    tied = False

    for folded, value in options.items():
        distance = _edit_distance(candidate, folded, budget)
        if distance > budget:
            continue
        if distance < best_distance:
            best_distance, best_value, tied = distance, value, False
        elif distance == best_distance and value != best_value:
            tied = True

    if best_value is not None and not tied:
        return best_value
    if tied:
        log.debug("ambiguous match for %r, ignoring", candidate)
        return None

    # Fall back to a ratio comparison, which catches transpositions and the
    # longer multi-word names that blow the edit budget. Callers that must not
    # tolerate an *extra word* switch it off: a ratio is a proportion, so it
    # forgives a stray "son" on a long name the way it forgives a bad glyph.
    if not allow_ratio:
        return None
    best_ratio = threshold
    for folded, value in options.items():
        ratio = SequenceMatcher(None, candidate, folded).ratio()
        if ratio > best_ratio:
            best_ratio, best_value = ratio, value
    return best_value


class MessageParser:
    """Parses OCR lines into :class:`SpellEvent` objects."""

    def __init__(self, assets: RiotAssets) -> None:
        self.assets = assets
        self._champion_index: dict[str, str] = {}
        self._summoner_index: dict[str, str] = {}
        # Localised spell names only. An attributed line is matched against this
        # rather than the full index: "Saut eclair" is the game's wording, while
        # the bare English "flash" is what a French-client player types.
        self._summoner_localised: dict[str, str] = {}
        self._ult_index: dict[str, str] = {}
        self.rebuild_index()
        # Lines that named a champion but failed to parse. Surfaced in the
        # debug panel: if the system wording differs from what we expect,
        # this is where it shows up.
        self.near_misses: list[str] = []

    def rebuild_index(self) -> None:
        """Build folded lookup tables from the loaded Riot data."""
        self._champion_index.clear()
        self._summoner_index.clear()
        self._summoner_localised.clear()
        self._ult_index.clear()

        for champion in self.assets.champions.values():
            for alias in champion.aliases:
                # Longer aliases win ties; avoids 'Yi' shadowing 'Master Yi'.
                existing = self._champion_index.get(alias)
                if existing is None or len(alias) > len(existing):
                    self._champion_index[alias] = champion.champion_id
            ult = champion.ultimate
            if ult and ult.name:
                self._ult_index[fold(ult.name)] = champion.champion_id

        for spell in self.assets.spells.values():
            self._summoner_index[fold(spell.name)] = spell.canonical
            self._summoner_localised[fold(spell.name)] = spell.canonical
            # Accept the English name too; some players run an EN client while
            # the rest of the UI is localised.
            self._summoner_index[fold(spell.canonical)] = spell.canonical

    def add_localised_spells(self, names: dict[str, str]) -> None:
        """Teach this parser spell names from another language.

        Only ever used by the shipped self-test, whose sample frame is in one
        fixed language while the client may be in another. Deliberately a
        separate call on a separate parser instance rather than something
        :meth:`rebuild_index` does for every locale at once: accepting every
        language's wording on the live parser would weaken the one test that makes
        an attributed cast line trustworthy -- that the spell is named the way
        *this* client names it, so "used Flash" on a French client is a human
        typing rather than the game reporting.
        """
        for canonical, name in names.items():
            if canonical not in self.assets.spells or not name:
                continue
            self._summoner_index[fold(name)] = canonical
            self._summoner_localised[fold(name)] = canonical

    # ------------------------------------------------------------------
    def parse_line(self, line: str) -> SpellEvent | None:
        text = " ".join(line.split())
        if len(text) < 6:
            return None

        game_time, without_time = self._extract_timestamp(text)

        stripped = without_time.strip()
        had_author = bool(AUTHOR_PREFIX_RE.match(stripped))
        body = AUTHOR_PREFIX_RE.sub("", stripped, count=1)

        # Form 1: the game states the remaining cooldown. Accepted with or
        # without an author prefix, because "Attendez <champion> <sort> - <n>
        # sec." is structurally unmistakable -- the trailing count is what makes
        # it self-verifying, so attribution does not matter.
        event = self._parse_wait(body, text, game_time)
        if event is not None:
            return event

        # Form 2: a cast announcement. Accepted attributed or not -- pinging an
        # available spell produces this wording, carrying the pinger's name --
        # but an attributed one is held to the game's exact phrasing, since that
        # is the only thing separating it from a teammate typing the same claim.
        split = self._split_on_verb(body)
        if split is None:
            # Form 3: "<Champion> <Sort>" with no verb at all. Weaker evidence
            # than the other two -- nothing in it says the spell was *cast* --
            # so it yields an uncertain event rather than nothing.
            event = self._parse_bare(body, text, game_time)
            if event is not None:
                return event
            # Form 4: a teammate calling a timer, "jgl flash 950". Tried last
            # because it is the only form that is *meant* to be a human, so it
            # must never get a line one of the game's own wordings could have
            # claimed.
            event = self._parse_call(body, text, game_time)
            if event is not None:
                return event
            if self._mentions_champion(body):
                self._record_near_miss(text)
            return None
        left, right = split

        if had_author:
            champion = self._resolve_champion_strict(left)
            resolved = (None if champion is None
                        else self._resolve_spell_strict(right, champion))
        else:
            champion = self._resolve_champion(left)
            resolved = (None if champion is None
                        else self._resolve_spell(right, champion))

        if champion is None or resolved is None:
            self._record_near_miss(text)
            return None
        kind, spell_key, spell_name = resolved

        stamp = "?" if game_time is None else f"{game_time // 60}:{game_time % 60:02d}"
        signature = f"{champion.champion_id}|{spell_key}|{stamp}"

        return SpellEvent(
            champion_id=champion.champion_id,
            champion_name=champion.name,
            kind=kind,
            spell_key=spell_key,
            spell_name=spell_name,
            game_time=game_time,
            raw_line=text,
            signature=signature,
        )

    def _parse_wait(self, body: str, raw: str,
                    game_time: int | None) -> SpellEvent | None:
        """Parse "Attendez <champion> <sort> - 245 sec." into an exact event."""
        plain = strip_accents(body)
        match = WAIT_RE.search(plain)
        if match is None:
            return None

        raw_secs = match.group("secs_dash") or match.group("secs_plain")
        try:
            remaining = int(raw_secs.translate(DIGIT_FIXES))
        except (ValueError, AttributeError):
            return None
        # Zero is always a misread, never a real message: the game does not tell
        # you to wait zero seconds, and a dropped leading digit turns "100 sec"
        # into "00 sec". Treating that as real would *clear* a live timer, so it
        # is rejected rather than trusted. The upper bound catches the same class
        # of error in the other direction.
        if not 1 <= remaining <= 600:
            self._record_near_miss(raw)
            return None

        middle = match.group("middle").strip(" -:.,")
        resolved = self._split_target_and_spell(middle)
        if resolved is None:
            self._record_near_miss(raw)
            return None
        champion, kind, spell_key, spell_name = resolved

        signature = f"{champion.champion_id}|{spell_key}|wait{remaining}"
        return SpellEvent(
            champion_id=champion.champion_id,
            champion_name=champion.name,
            kind=kind,
            spell_key=spell_key,
            spell_name=spell_name,
            game_time=game_time,
            raw_line=raw,
            signature=signature,
            remaining_seconds=remaining,
        )

    def _split_target_and_spell(self, middle: str, *, strict: bool = False):
        """Split "<champion> <spell>" by anchoring on the spell name.

        Anchoring on the spell is what makes this reliable: there is a handful of
        summoner spells plus one ultimate per champion, so the trailing words are
        matched against a small closed set, and whatever precedes them is the
        champion.

        ``strict`` selects the attributed-line resolvers. The "Attendez" form can
        afford the lenient ones because its trailing "- N sec." verifies it; the
        bare form has nothing to verify against, so it gets the strict pair.
        """
        words = middle.split()
        if len(words) < 2:
            return None

        resolve_champion = (self._resolve_champion_strict if strict
                            else self._resolve_champion)
        resolve_spell = (self._resolve_spell_strict if strict
                         else self._resolve_spell)

        for take in range(1, min(MAX_SPELL_WORDS, len(words) - 1) + 1):
            spell_text = " ".join(words[-take:])
            champion_text = " ".join(words[:-take])
            champion = resolve_champion(champion_text)
            if champion is None:
                continue
            resolved = resolve_spell(spell_text, champion)
            if resolved is None:
                continue
            kind, spell_key, spell_name = resolved
            return champion, kind, spell_key, spell_name
        return None

    def _parse_bare(self, body: str, raw: str,
                    game_time: int | None) -> SpellEvent | None:
        """Parse a bare "<Champion> <Sort>" line into an *uncertain* event.

        The game prints this when a spell is named without being announced as
        cast. It is the weakest of the three forms -- no verb, no stated
        cooldown, nothing to verify against -- and it is also exactly what a
        player typing "Morgana Saut eclair" produces. Hence two defences:

        * the strict resolvers, so the champion name must be the whole left side
          and the spell must be the localised name, capitalised and undetermined;
        * the resulting event is marked uncertain, and the overlay says so.

        The second is the real one. Being wrong here costs a question mark, not a
        wrong timer presented as fact.
        """
        resolved = self._split_target_and_spell(body, strict=True)
        if resolved is None:
            return None
        champion, kind, spell_key, spell_name = resolved

        stamp = "?" if game_time is None else f"{game_time // 60}:{game_time % 60:02d}"
        # Deliberately distinct from the confirmed form's signature for the same
        # cast. Sharing it would let the dedupe swallow the confirmation, which
        # is the one thing this form exists to receive.
        signature = f"{champion.champion_id}|{spell_key}|{stamp}|?"
        return SpellEvent(
            champion_id=champion.champion_id,
            champion_name=champion.name,
            kind=kind,
            spell_key=spell_key,
            spell_name=spell_name,
            game_time=game_time,
            raw_line=raw,
            signature=signature,
            certain=False,
        )

    # ------------------------------------------------------------------
    # Form 4: a teammate calling a timer
    # ------------------------------------------------------------------
    def _parse_call(self, body: str, raw: str,
                    game_time: int | None) -> SpellEvent | None:
        """Parse "jgl flash 950" -- a player saying when a spell is back.

        Recognised by shape rather than by wording, because there is no wording:
        every team spells it differently and half of them abbreviate. What makes
        it safe is that all three parts must parse -- a lane or a champion, a real
        spell, and a plausible clock time -- and ordinary chat almost never has
        all three. Order is not fixed either, since "flash jgl 950" is just as
        common as the other way round.

        Nothing is decided here about *who* the lane is. The parser knows
        champions and spells; who plays jungle is the timer manager's business,
        and it is the one thing about a call that can still be missing when the
        line is read.
        """
        words = [word for word in re.split(r"[\s,;]+", body.strip()) if word]
        if not 3 <= len(words) <= MAX_CALL_WORDS:
            return None

        ready, consumed = self._called_time(words)
        if ready is None:
            return None
        words = words[:-consumed]
        if len(words) < 2:
            return None

        # Every contiguous window as the spell, everything else as the target.
        # Two words each at most in practice, so the search is a dozen tries.
        for size in (1, 2, 3):
            for start in range(0, len(words) - size + 1):
                spell = self._called_spell(" ".join(words[start:start + size]))
                if spell is None:
                    continue
                rest = words[:start] + words[start + size:]
                target = self._called_target(rest)
                if target is None:
                    continue
                return self._build_call(target, spell, ready, raw, game_time)
        return None

    @staticmethod
    def _called_time(words: list[str]) -> tuple[int | None, int]:
        """The clock time a call ends with, and how many words it took.

        "950", "9:50" and "9 50" are the same call. The bare form is read the way
        a player means it: one or two digits are whole minutes, three or four are
        minutes and seconds run together.
        """
        def read(text: str) -> int | None:
            match = CALL_TIME_RE.match(text)
            if match is None:
                return None
            minutes_text, seconds_text, bare = match.groups()
            if bare is not None:
                if len(bare) <= 2:
                    minutes, seconds = int(bare), 0
                else:
                    minutes, seconds = int(bare[:-2]), int(bare[-2:])
            else:
                minutes, seconds = int(minutes_text), int(seconds_text)
            if seconds > 59 or minutes > 120:
                return None
            return minutes * 60 + seconds

        tail = words[-1].strip(".!?)")
        # "9 50" first, where the space is a typo or OCR split the token. Before
        # the single-token read and not after it, because "50" on its own is a
        # perfectly good call time (50:00) and would otherwise win, turning a
        # ten-minute Flash into a fifty-minute one.
        if len(words) >= 3 and re.fullmatch(r"\d{2}", tail) and \
                re.fullmatch(r"\d{1,2}", words[-2]):
            minutes, seconds = int(words[-2]), int(tail)
            if seconds <= 59 and minutes <= 120:
                return minutes * 60 + seconds, 2
        value = read(tail)
        if value is not None:
            return value, 1
        return None, 0

    def _called_spell(self, text: str) -> tuple[str, str, str] | None:
        """Resolve the spell half of a call into ``(kind, key, display name)``.

        Far more forgiving than :meth:`_resolve_spell_strict`: this text was typed
        by a human, so "flash" on a French client, "tp", "exh" and the localised
        name all have to work. That leniency is affordable because a call is only
        acted on when the *whole* shape parses.
        """
        folded = fold(text)
        if not folded:
            return None
        if folded in CALL_ULT_WORDS:
            # The champion's own ultimate; its name is filled in downstream, once
            # a lane has been resolved to a champion.
            return "ultimate", "ULT", ""

        canonical = self._summoner_index.get(folded) or normalise_spell(folded)
        if canonical is None:
            canonical = _best_match(folded, self._summoner_index,
                                    MIN_SPELL_RATIO, allow_ratio=False)
        if canonical is None or canonical not in COOLDOWNS:
            return None
        spell = self.assets.spells.get(canonical)
        return "summoner", canonical, spell.name if spell else canonical

    def _called_target(self, words: list[str]) -> tuple[str, str] | None:
        """Resolve who a call is about: ``("role", "JUNGLE")`` or a champion id.

        A lane wins over a champion when both could match, because a lane is
        what people actually type and no champion is called "mid".
        """
        if not words:
            return None
        for word in words:
            role = role_from_word(word)
            if role:
                return "role", role

        champion = self._resolve_called_champion(" ".join(words))
        if champion is None:
            return None
        return "champion", champion.champion_id

    def _resolve_called_champion(self, candidate: str) -> ChampionInfo | None:
        """A champion named in a call: the whole side, glyph errors forgiven.

        No ratio fallback and no trailing-word salvage. Both exist elsewhere to
        survive leftover HUD text around the game's own output; here the text is
        short and typed, and either salvage would happily find a champion inside
        an ordinary sentence that happened to end in a number.
        """
        folded = fold(candidate)
        if not folded:
            return None
        champion_id = self._champion_index.get(folded)
        if champion_id is None:
            champion_id = _best_match(folded, self._champion_index,
                                      MIN_CHAMPION_RATIO, allow_ratio=False)
        if champion_id is None:
            return None
        return self.assets.champions.get(champion_id)

    def _build_call(self, target: tuple[str, str], spell: tuple[str, str, str],
                    ready: int, raw: str, game_time: int | None
                    ) -> SpellEvent | None:
        kind, spell_key, spell_name = spell
        target_kind, target_value = target

        champion_id, champion_name, role = "", "", ""
        if target_kind == "role":
            role = target_value
        else:
            champion = self.assets.champions.get(target_value)
            if champion is None:
                return None
            champion_id, champion_name = champion.champion_id, champion.name
            if kind == "ultimate":
                ult = champion.ultimate
                spell_name = ult.name if ult is not None and ult.name else "ULT"

        # Keyed on the stated ready time, so re-reading the line is suppressed
        # while a corrected call -- a different number -- gets through.
        signature = f"{role or champion_id}|{spell_key}|call{ready}"
        return SpellEvent(
            champion_id=champion_id,
            champion_name=champion_name,
            kind=kind,
            spell_key=spell_key,
            spell_name=spell_name,
            game_time=game_time,
            raw_line=raw,
            signature=signature,
            # A call is somebody's word, not the client's. It gets the same "?"
            # the inferred form gets, and the same promotion when the game later
            # says the spell outright.
            certain=False,
            target_role=role,
            ready_at_game=ready,
            source="call",
        )

    def parse_lines(self, lines: list[str]) -> list[SpellEvent]:
        events = []
        for line in lines:
            event = self.parse_line(line)
            if event is not None:
                events.append(event)
        return events

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_timestamp(text: str) -> tuple[int | None, str]:
        """Pull the game clock out of a line, returning it and the remainder."""
        match = TIMESTAMP_RE.search(text)
        if match is None:
            return None, text
        minutes_raw = match.group(1).translate(DIGIT_FIXES)
        seconds_raw = match.group(2).translate(DIGIT_FIXES)
        try:
            minutes, seconds = int(minutes_raw), int(seconds_raw)
        except ValueError:
            return None, text
        if seconds > 59 or minutes > 120:
            return None, text
        remainder = (text[: match.start()] + " " + text[match.end():]).strip()
        return minutes * 60 + seconds, remainder

    @staticmethod
    def _split_on_verb(text: str) -> tuple[str, str] | None:
        """Split a line around the system verb phrase.

        Works on the folded form but returns slices of the original text, so we
        walk a folded-index map rather than folding each side separately.
        """
        plain = strip_accents(text).lower()
        # Map each position in the alnum-only string back to the original.
        folded_chars: list[str] = []
        positions: list[int] = []
        for index, char in enumerate(plain):
            if char.isalnum():
                folded_chars.append(char)
                positions.append(index)
        folded = "".join(folded_chars)

        best: tuple[int, int] | None = None
        for verb in SYSTEM_VERBS:
            at = folded.find(verb)
            if at == -1:
                continue
            # Prefer the longest verb match at the earliest position.
            if best is None or len(verb) > best[1]:
                best = (at, len(verb))
        if best is None:
            return None

        start_index, length = best
        end_index = start_index + length - 1
        if end_index >= len(positions):
            return None
        left = text[: positions[start_index]]
        right = text[positions[end_index] + 1:]
        return left.strip(" -:.,)("), right.strip(" -:.,)(")

    def _mentions_champion(self, text: str) -> bool:
        folded = fold(text)
        return any(
            alias in folded
            for alias in self._champion_index
            if len(alias) >= 5
        )

    def _resolve_champion(self, candidate: str) -> ChampionInfo | None:
        folded = fold(candidate)
        if not folded:
            return None
        champion_id = self._champion_index.get(folded)
        if champion_id is None:
            # The left side may carry leftover HUD text, so also try the
            # trailing words, which is where the name sits.
            words = strip_accents(candidate).split()
            for take in (3, 2, 1):
                if len(words) >= take:
                    tail = fold("".join(words[-take:]))
                    champion_id = self._champion_index.get(tail)
                    if champion_id:
                        break
        if champion_id is None:
            champion_id = _best_match(folded, self._champion_index,
                                      MIN_CHAMPION_RATIO)
        if champion_id is None:
            return None
        return self.assets.champions.get(champion_id)

    def _resolve_champion_strict(self, candidate: str) -> ChampionInfo | None:
        """Champion half of an attributed line: the whole side, or nothing.

        Drops the trailing-words salvage that :meth:`_resolve_champion` uses to
        survive leftover HUD text. On an attributed line the champion's name is
        the entire left side, and the salvage path would otherwise happily find a
        champion buried inside a sentence somebody typed. Glyph-level fuzziness
        is kept -- OCR still has to be forgiven -- but only as an edit budget,
        never as a similarity ratio: "Morgana son" scores 0.82 against "Morgana"
        and would otherwise sail through, taking the determiner in the middle of
        "Morgana son Saut eclair" with it.
        """
        if not _starts_capitalised(candidate):
            return None
        folded = fold(candidate)
        if not folded:
            return None
        champion_id = self._champion_index.get(folded)
        if champion_id is None:
            champion_id = _best_match(folded, self._champion_index,
                                      MIN_CHAMPION_RATIO, allow_ratio=False)
        if champion_id is None:
            return None
        return self.assets.champions.get(champion_id)

    @staticmethod
    def _strip_determiners(text: str) -> str:
        """Drop leading articles/possessives: "son Saut eclair" -> "Saut eclair"."""
        words = text.replace("'", " ").split()
        while words and fold(words[0]) in DETERMINERS:
            words.pop(0)
        return " ".join(words)

    def _resolve_spell(self, candidate: str,
                       champion: ChampionInfo) -> tuple[str, str, str] | None:
        """Resolve the spell half into ``(kind, spell_key, display_name)``."""
        folded = fold(self._strip_determiners(candidate))
        if not folded:
            return None

        # Summoner spells first: they are the exact-timer case.
        canonical = self._summoner_index.get(folded)
        if canonical is None:
            canonical = _best_match(folded, self._summoner_index, MIN_SPELL_RATIO)
        if canonical is not None:
            spell = self.assets.spells.get(canonical)
            name = spell.name if spell else canonical
            return "summoner", canonical, name

        # Then this champion's own ultimate.
        ult = champion.ultimate
        if ult is not None and ult.name:
            ult_folded = fold(ult.name)
            budget = _edit_budget(len(ult_folded))
            ratio = SequenceMatcher(None, folded, ult_folded).ratio()
            if (folded == ult_folded
                    or _edit_distance(folded, ult_folded, budget) <= budget
                    or ratio >= MIN_SPELL_RATIO):
                return "ultimate", "ULT", ult.name
            # Some clients announce the generic word rather than the ability
            # name; accept that too and let the champion identify the ult.
            if folded in {"ultime", "ultimate", "sonultime", "ult"}:
                return "ultimate", "ULT", ult.name

        return None

    def _resolve_spell_strict(self, candidate: str,
                              champion: ChampionInfo) -> tuple[str, str, str] | None:
        """Spell half of an attributed line: the game's own wording, verbatim.

        Two restrictions relative to :meth:`_resolve_spell`, and they are what
        make an attributed line trustworthy:

        * a leading determiner is fatal rather than stripped. The game writes
          "a utilise Saut eclair"; "a utilise *son* flash" is a human;
        * only the localised name is accepted. On a French client the game never
          prints "Flash", so a line that does was typed;
        * the name must be capitalised, which on an English client -- where the
          localised name and the English one coincide -- is the only thing left
          that separates "used Flash" from "used flash".

        The generic "son ultime" wording is likewise refused here: the game names
        the ability, so an unnamed ult on an attributed line is not evidence.
        """
        words = candidate.replace("'", " ").split()
        if not words or fold(words[0]) in DETERMINERS:
            return None
        if not _starts_capitalised(candidate):
            return None
        folded = fold(candidate)
        if not folded:
            return None

        canonical = self._summoner_localised.get(folded)
        if canonical is None:
            canonical = _best_match(folded, self._summoner_localised,
                                    MIN_SPELL_RATIO)
        if canonical is not None:
            spell = self.assets.spells.get(canonical)
            return "summoner", canonical, spell.name if spell else canonical

        ult = champion.ultimate
        if ult is not None and ult.name:
            ult_folded = fold(ult.name)
            budget = _edit_budget(len(ult_folded))
            ratio = SequenceMatcher(None, folded, ult_folded).ratio()
            if (folded == ult_folded
                    or _edit_distance(folded, ult_folded, budget) <= budget
                    or ratio >= MIN_SPELL_RATIO):
                return "ultimate", "ULT", ult.name

        return None

    def champion_named(self, text: str) -> str | None:
        """The champion a short label names, or None. For the role readers.

        The loading screen prints a champion's name under each portrait and
        nothing else, so the whole label has to resolve -- no salvage from
        trailing words, no similarity ratio. Both of those exist to survive
        leftover HUD text around the game's own sentences, and here they would
        turn the summoner name on the card above into a champion.
        """
        folded = fold(text or "")
        if len(folded) < 3:
            return None
        champion_id = self._champion_index.get(folded)
        if champion_id is None:
            champion_id = _best_match(folded, self._champion_index,
                                      MIN_CHAMPION_RATIO, allow_ratio=False)
        return champion_id

    def _record_near_miss(self, text: str) -> None:
        if text in self.near_misses:
            return
        self.near_misses.append(text)
        del self.near_misses[:-30]
