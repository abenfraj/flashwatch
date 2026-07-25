"""Active cooldown tracking.

Two problems here are less obvious than they look.

**Stale chat history.** Chat lines stay on screen long after the cast, and
reopening chat redisplays old ones. If the app launches mid-game it will read a
"(4:12) Ahri a utilise Saut eclair" from twelve minutes ago and, naively, start
a fresh 5-minute Flash timer for a Flash that is already back up. Two defences:

  * a *priming* pass -- for the first few frames of a session we record what is
    already on screen without starting any timers, so pre-existing history can
    never produce a timer, and
  * *age correction* -- the newest timestamp we have ever seen, plus the wall
    time since we saw it, estimates the current game clock. An event's age is
    then `estimated_now - its timestamp`, and the timer starts already partly
    elapsed. A spell whose cooldown has fully expired never becomes a timer.

**Duplicates.** The same line is re-read every frame. The game's own timestamp
makes each cast uniquely identifiable, so `champion|spell|mm:ss` is a stable
signature: identical timestamp means the same cast, a later timestamp means a
genuine recast.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from cooldowns import format_remaining, get_cooldown
from message_parser import SpellEvent
from riot_assets import RiotAssets

log = logging.getLogger(__name__)

# Frames to observe before we trust that a line is new rather than history.
PRIME_FRAMES = 3

# Without a readable timestamp we cannot identify a cast, so fall back to
# suppressing repeats of the same champion+spell within this window.
BLIND_DEDUPE_WINDOW = 12.0

# A repeat ping of the same spell must imply at least this much *extra* time
# before it is treated as a genuine recast rather than someone pinging again.
# Below the margin the existing timer is left completely untouched: re-pinging
# should never nudge a running countdown, and the first (oldest) ping is the
# one closest to the actual cast, so it is the one worth keeping.
RECAST_MARGIN = 15.0

# New-game detection from the clock alone is a *last resort*, because chat
# history legitimately contains old timestamps: if the user scrolls up to reveal
# lines we have never read, a naive "clock went backwards" rule would wipe every
# valid timer mid-game. Age correction already handles stale history correctly
# (old casts compute as expired), so the primary reset signal is the game
# process exiting, reported by game_detector.
#
# This only fires for the unmistakable shape of a fresh game: a brand-new clock
# while we believed we were deep into a match.
NEW_GAME_MAX_CLOCK = 90.0        # the new line is within the first 1:30
NEW_GAME_MIN_PREVIOUS = 420.0    # and we thought we were past 7:00

# ...and it must be seen more than once. A single mangled timestamp used to be
# enough to wipe every timer: OCR dropping the leading digit of "10:45" yields
# "0:45", which fits the shape above exactly. Two separate lines agreeing on an
# early clock is a real game restart; one is a misread. Reaching zero
# confirmations costs nothing, because a genuinely new game changes the game
# process too, and that is the primary reset signal.
NEW_GAME_CONFIRMATIONS = 2
NEW_GAME_CONFIRM_WINDOW = 90.0   # how long an unconfirmed hint stays relevant

# A clock read off the screen is believed once a second reading agrees with it.
CLOCK_CONFIRM_WINDOW = 12.0      # how long the first reading stays usable
CLOCK_CONFIRM_TOLERANCE = 2.5    # seconds of slack, on top of the time elapsed

ROLE_ORDER = {"TOP": 0, "JUNGLE": 1, "MID": 2, "ADC": 3, "SUPPORT": 4, "": 5}


@dataclass(slots=True)
class ActiveTimer:
    """One spell on cooldown."""

    champion_id: str
    champion_name: str
    kind: str                     # "summoner" | "ultimate"
    spell_key: str
    spell_name: str
    duration: float
    started_at: float             # monotonic, already back-dated by age
    approximate: bool = False     # True for ultimates (rank/haste are guesses)
    # True when the game stated the remaining time. Such a timer outranks
    # anything derived from a base cooldown, so nothing recomputed may overwrite
    # it while it runs.
    stated: bool = False
    role: str = ""
    warned: bool = False
    announced_ready: bool = False
    # Absolute game-clock time at which the spell comes back up, when the game
    # told us. Independent of when we happened to read the message, so a late
    # read costs no accuracy and repeat pings agree instead of fighting.
    ready_at_game: float | None = None

    def remaining(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, self.duration - (now - self.started_at))

    def is_ready(self, now: float | None = None) -> bool:
        return self.remaining(now) <= 0

    def display(self, now: float | None = None) -> str:
        text = format_remaining(self.remaining(now))
        if self.approximate and text != "READY":
            return f"~{text}"
        return text

    @property
    def key(self) -> tuple[str, str]:
        return (self.champion_id, self.spell_key)


@dataclass(slots=True)
class Notification:
    """Something the audio/toast layer may want to announce."""

    kind: str                     # "warning" | "ready"
    timer: ActiveTimer


class TimerManager:
    """Owns every active timer. Deliberately free of Qt so it stays testable."""

    def __init__(self, assets: RiotAssets, settings) -> None:
        self.assets = assets
        self.settings = settings
        self._timers: dict[tuple[str, str], ActiveTimer] = {}
        self._seen: set[str] = set()
        self._last_blind: dict[tuple[str, str], float] = {}
        self._roles: dict[str, str] = {}
        self._frames_seen = 0
        # (game_time, monotonic when observed) -- our estimate of the game clock.
        self._clock_ref: tuple[float, float] | None = None
        # When each unconfirmed "the clock looks like a new game" hint was seen.
        self._new_game_hints: list[float] = []
        # (value, monotonic) of the last clock read off the screen, awaiting a
        # second reading to confirm it.
        self._clock_candidate: tuple[float, float] | None = None
        self.history: list[tuple[float, SpellEvent]] = []

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def reset(self, *, reason: str = "") -> None:
        """Clear everything. Called when a game ends or a new one starts."""
        if self._timers or self._seen:
            log.info("resetting timers (%s)", reason or "unspecified")
        self._timers.clear()
        self._seen.clear()
        self._last_blind.clear()
        self._frames_seen = 0
        self._clock_ref = None
        self._new_game_hints.clear()
        self._clock_candidate = None
        self.history.clear()

    @property
    def priming(self) -> bool:
        return self._frames_seen < PRIME_FRAMES

    def note_frame(self) -> None:
        """Record that a capture frame was processed."""
        if self._frames_seen < PRIME_FRAMES:
            self._frames_seen += 1

    # ------------------------------------------------------------------
    # Game clock estimation
    # ------------------------------------------------------------------
    def estimated_game_time(self) -> float | None:
        if self._clock_ref is None:
            return None
        seen_at_game, seen_at_wall = self._clock_ref
        return seen_at_game + (time.monotonic() - seen_at_wall)

    def note_clock(self, seconds: float) -> bool:
        """Adopt a game clock read off the screen. Returns True if it was taken.

        Two consistent readings are required before the reference moves. The
        clock is read by the same OCR as everything else, and a single misread
        ("12:34" as "72:34") would otherwise jump the reference forward, where it
        would stick -- the reference only ever advances, so a bad value cannot be
        walked back. Two readings a moment apart, agreeing to within a couple of
        seconds *after* accounting for the time between them, cannot both be the
        same accident.
        """
        now = time.monotonic()
        candidate = self._clock_candidate
        self._clock_candidate = (float(seconds), now)
        if candidate is None:
            return False
        previous, seen_at = candidate
        elapsed = now - seen_at
        if elapsed > CLOCK_CONFIRM_WINDOW:
            return False
        if abs((previous + elapsed) - seconds) > CLOCK_CONFIRM_TOLERANCE:
            log.debug("screen clock %.0fs does not confirm %.0fs (+%.1fs)",
                      seconds, previous, elapsed)
            return False

        estimate = self.estimated_game_time()
        if estimate is not None and seconds <= estimate:
            # Nothing to correct: our own extrapolation is already there or ahead.
            return False
        self._clock_ref = (float(seconds), now)
        log.debug("game clock from the screen: %.0fs", seconds)
        return True

    def _confirm_new_game(self, now: float) -> bool:
        """Whether enough separate lines agree that the game restarted.

        Called only for lines that already have the shape of a fresh game. The
        counter is what keeps a single mangled timestamp from wiping the board;
        each caller is a distinct chat line, since repeats are deduped before
        reaching here.
        """
        self._new_game_hints = [seen for seen in self._new_game_hints
                                if now - seen <= NEW_GAME_CONFIRM_WINDOW]
        self._new_game_hints.append(now)
        if len(self._new_game_hints) < NEW_GAME_CONFIRMATIONS:
            log.info("early clock seen (%d/%d) -- waiting for a second line "
                     "before assuming a new game", len(self._new_game_hints),
                     NEW_GAME_CONFIRMATIONS)
            return False
        self._new_game_hints.clear()
        return True

    def _update_clock(self, game_time: int) -> bool:
        """Advance the clock reference. Returns True if a new game was detected.

        Note the asymmetry: the clock only ever moves *forward* here. An old
        history line cannot drag it back, which is what makes stale chat safe.
        """
        now = time.monotonic()
        estimate = self.estimated_game_time()

        if (estimate is not None
                and game_time <= NEW_GAME_MAX_CLOCK
                and estimate >= NEW_GAME_MIN_PREVIOUS
                and self._confirm_new_game(now)):
            self.reset(reason="clock restarted near zero, new game")
            self._clock_ref = (float(game_time), now)
            # Skip re-priming: a game this young has no stale history to guard
            # against, and the event that got us here is genuinely fresh, so it
            # deserves a timer rather than being primed away.
            self._frames_seen = PRIME_FRAMES
            return True

        if estimate is None or game_time > estimate:
            self._clock_ref = (float(game_time), now)
        return False

    # ------------------------------------------------------------------
    # Event intake
    # ------------------------------------------------------------------
    def handle_events(self, events: list[SpellEvent]) -> list[ActiveTimer]:
        """Feed parsed events in. Returns the timers that were newly started."""
        started: list[ActiveTimer] = []
        # Oldest first, so the clock reference advances monotonically.
        for event in sorted(events, key=lambda e: (e.game_time is None, e.game_time or 0)):
            timer = self._handle_event(event)
            if timer is not None:
                started.append(timer)
        return started

    def _handle_event(self, event: SpellEvent) -> ActiveTimer | None:
        if event.kind == "summoner" and not self.settings.get("track_summoners"):
            return None
        if event.kind == "ultimate" and not self.settings.get("track_ultimates"):
            return None

        # Captured *before* this event advances the clock. The comparison of the
        # ping's own timestamp against where we already believed the game clock
        # to be is what reveals how late we read the line -- once the reference
        # has moved to this event, that information is gone.
        estimate_before = self.estimated_game_time()

        if event.game_time is not None:
            if self._update_clock(event.game_time):
                # reset() wiped _seen, so this event is legitimately new again.
                pass
            if event.signature in self._seen:
                return None
            self._seen.add(event.signature)
        elif event.remaining_seconds is not None:
            # The signature carries the stated seconds, so re-reading the same
            # line is suppressed while a fresh ping -- which reports a different
            # number -- is allowed through to refine the timer.
            if event.signature in self._seen:
                return None
            self._seen.add(event.signature)
        else:
            # Neither a timestamp nor a stated cooldown: fall back to a window.
            now = time.monotonic()
            last = self._last_blind.get((event.champion_id, event.spell_key))
            if last is not None and now - last < BLIND_DEDUPE_WINDOW:
                return None
            self._last_blind[(event.champion_id, event.spell_key)] = now

        if self.priming:
            # Already-visible history: remembered, but never timed.
            log.debug("priming, ignoring %r", event.raw_line)
            return None

        if event.remaining_seconds is not None:
            return self._apply_stated_cooldown(event, estimate_before)

        duration, approximate = self._duration_for(event)
        if duration <= 0:
            return None

        age = self._age_of(event)
        if age >= duration:
            log.debug("%s %s already expired (age %.0fs)", event.champion_id,
                      event.spell_key, age)
            return None

        key = (event.champion_id, event.spell_key)
        previous = self._timers.get(key)
        if previous is not None:
            if previous.stated and not previous.is_ready():
                # A ping stated this cooldown outright; this line only implies one
                # from a base cooldown plus assumptions about runes and boots.
                # Recomputing over the top of the exact number can only make it
                # worse, and moves a countdown the user was already reading.
                log.info("keeping the pinged timer for %s %s, ignoring %r",
                         event.champion_name, event.spell_name, event.raw_line)
                return None
            if not self._is_recast(previous, duration - age, None):
                log.debug("%s %s: %r does not extend the running timer",
                          event.champion_name, event.spell_name, event.raw_line)
                return None

        timer = ActiveTimer(
            champion_id=event.champion_id,
            champion_name=event.champion_name,
            kind=event.kind,
            spell_key=event.spell_key,
            spell_name=event.spell_name,
            duration=duration,
            started_at=time.monotonic() - age,
            approximate=approximate,
            role=self._role_for(event),
        )
        self._timers[timer.key] = timer
        self.history.append((time.time(), event))
        del self.history[:-100]
        log.info("timer: %s %s for %.0fs (age %.1fs%s)", timer.champion_name,
                 timer.spell_name, duration, age,
                 ", approx" if approximate else "")
        return timer

    def _apply_stated_cooldown(self, event: SpellEvent,
                               estimate_before: float | None) -> ActiveTimer | None:
        """Handle an event where the game stated the remaining time.

        The number is authoritative, so nothing about rank or haste is guessed
        and ultimate timers come out exact too.

        The subtlety is *when* the number was true. It described the cooldown at
        the moment of the ping, not the moment we managed to read it, so the
        anchor used here is the absolute game time at which the spell returns:

            ready_at = ping_timestamp + stated_seconds

        Reading the line several seconds late then costs no accuracy, and every
        later ping of the same spell computes the same ready_at instead of
        restarting the countdown from a stale number.
        """
        stated = float(event.remaining_seconds or 0)
        remaining = stated
        ready_at_game: float | None = None

        if event.game_time is not None:
            ready_at_game = event.game_time + stated
            if estimate_before is not None:
                # How long ago the ping actually happened.
                delay = estimate_before - event.game_time
                if delay > 0:
                    remaining = stated - delay
                    log.debug("ping was %.1fs old, %.0fs -> %.0fs",
                              delay, stated, remaining)

        key = (event.champion_id, event.spell_key)
        previous = self._timers.get(key)
        if previous is not None and not self._is_recast(previous, remaining,
                                                       ready_at_game):
            # Leave the running timer completely alone. The first ping is the
            # closest to the real cast, so it stays the source of truth.
            #
            # Checked *before* the "nothing left to time" case below, and that
            # order is the whole point: a line revealed by scrollback, or a ping
            # whose timestamp the OCR mangled into an earlier one, computes a
            # negative remaining. Acting on that used to delete a perfectly good
            # running timer -- the reported "timers sometimes vanish". A report
            # that does not extend the countdown can now only be ignored.
            log.debug("ignoring repeat/stale ping for %s %s (%.0fs vs %.0fs)",
                      event.champion_name, event.spell_name, remaining,
                      previous.remaining())
            return None

        if remaining <= 0:
            # Read too late for anything to be left of this cooldown. There is
            # nothing to start, and nothing to remove either: any timer that does
            # exist has been left alone above.
            log.debug("%s %s: nothing left of the stated %ss (from %r)",
                      event.champion_name, event.spell_name,
                      event.remaining_seconds, event.raw_line)
            return None

        full, _approximate = self._duration_for(event)
        if full < remaining:
            full = remaining

        now = time.monotonic()
        timer = ActiveTimer(
            champion_id=event.champion_id,
            champion_name=event.champion_name,
            kind=event.kind,
            spell_key=event.spell_key,
            spell_name=event.spell_name,
            duration=full,
            started_at=now - (full - remaining),
            approximate=False,          # the game stated it
            stated=True,
            role=self._role_for(event),
            ready_at_game=ready_at_game,
        )
        # The raw line is logged with every timer: when a timer looks wrong, the
        # only useful question is what the OCR actually read, and reconstructing
        # that after the fact is impossible without it.
        log.info("timer: %s %s %.0fs remaining%s | stated=%s from %r",
                 timer.champion_name, timer.spell_name, remaining,
                 " (recast)" if previous is not None else "",
                 event.remaining_seconds, event.raw_line)

        self._timers[key] = timer
        self.history.append((time.time(), event))
        del self.history[:-100]
        return timer

    @staticmethod
    def _is_recast(previous: ActiveTimer, remaining: float,
                   ready_at_game: float | None) -> bool:
        """Whether a new report means the spell was used again.

        Compared on absolute ready time when both sides have it, since that is
        immune to when either message was read.
        """
        if ready_at_game is not None and previous.ready_at_game is not None:
            return ready_at_game > previous.ready_at_game + RECAST_MARGIN
        return remaining > previous.remaining() + RECAST_MARGIN

    def _age_of(self, event: SpellEvent) -> float:
        """Seconds elapsed since the cast, from the game clock estimate."""
        if event.game_time is None:
            return 0.0
        estimate = self.estimated_game_time()
        if estimate is None:
            return 0.0
        return max(0.0, estimate - event.game_time)

    def _duration_for(self, event: SpellEvent) -> tuple[float, bool]:
        """Cooldown in seconds, and whether it is only an approximation."""
        if event.kind == "summoner":
            return float(get_cooldown(
                event.spell_key,
                cosmic_insight=bool(self.settings.get("assume_cosmic_insight")),
                ionian_boots=bool(self.settings.get("assume_ionian_boots")),
            )), False

        champion = self.assets.champions.get(event.champion_id)
        ult = champion.ultimate if champion else None
        if ult is None or not ult.cooldown_by_rank:
            return 0.0, True

        rank = self._estimate_ult_rank(event.game_time)
        base = ult.cooldown_for_rank(rank)
        # Ability haste is not visible on screen yet; the planned scoreboard
        # reader will populate this map from the enemy's items.
        haste_map = self.settings.get("ability_haste") or {}
        try:
            haste = float(haste_map.get(event.champion_id, 0) or 0)
        except (TypeError, ValueError):
            haste = 0.0
        if haste > 0:
            base *= 100.0 / (100.0 + haste)
        return base, True

    def _estimate_ult_rank(self, game_time: int | None) -> int:
        """Guess ultimate rank from the game clock.

        Enemy levels are not visible, so this is a heuristic and the reason
        ultimate timers are flagged approximate.
        """
        if game_time is None:
            return 1
        if game_time >= float(self.settings.get("ult_rank3_after") or 1260):
            return 3
        if game_time >= float(self.settings.get("ult_rank2_after") or 720):
            return 2
        return 1

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------
    def set_role(self, champion_id: str, role: str) -> None:
        self._roles[champion_id] = role.upper()
        for timer in self._timers.values():
            if timer.champion_id == champion_id:
                timer.role = role.upper()

    def _role_for(self, event: SpellEvent) -> str:
        known = self._roles.get(event.champion_id)
        if known:
            return known
        # Smite is a reliable jungle tell; nothing else is worth guessing from.
        if event.spell_key == "Smite":
            self._roles[event.champion_id] = "JUNGLE"
            return "JUNGLE"
        return ""

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def _ready_linger(self) -> float:
        """Seconds a READY entry stays on screen before it is dropped."""
        try:
            return max(0.0, float(self.settings.get("ready_linger_seconds", 5)))
        except (TypeError, ValueError):
            return 5.0

    @staticmethod
    def _overdue(timer: ActiveTimer, now: float) -> float:
        """How long ago this timer came back up. Negative while still counting."""
        return (now - timer.started_at) - timer.duration

    def purge_finished(self, now: float | None = None) -> int:
        """Drop entries that have shown READY for long enough.

        Derived from the timer's own clock rather than from when it was first
        noticed: a ping arriving late is already back-dated, so a spell that came
        up before we ever read the line is dropped instead of announcing itself as
        fresh news.
        """
        now = time.monotonic() if now is None else now
        linger = self._ready_linger()
        stale = [key for key, timer in self._timers.items()
                 if self._overdue(timer, now) >= linger]
        for key in stale:
            del self._timers[key]
        return len(stale)

    def tick(self) -> list[Notification]:
        """Advance state and return anything worth announcing."""
        now = time.monotonic()
        warn_at = float(self.settings.get("audio_warn_seconds") or 0)
        notifications: list[Notification] = []

        for timer in self._timers.values():
            remaining = timer.remaining(now)
            if (not timer.warned and warn_at > 0
                    and 0 < remaining <= warn_at):
                timer.warned = True
                notifications.append(Notification("warning", timer))
            if not timer.announced_ready and remaining <= 0:
                timer.announced_ready = True
                timer.warned = True
                notifications.append(Notification("ready", timer))

        # After the announcements, never before: with no linger at all a timer
        # would otherwise be dropped in the same tick it came up, and the cue
        # telling the user about it would be lost with it.
        self.purge_finished(now)
        return notifications

    def snapshot(self) -> list[ActiveTimer]:
        """Timers for display, ordered for the overlay."""
        now = time.monotonic()
        timers = list(self._timers.values())
        # Filtered as well as purged in tick(): a snapshot can be taken between
        # ticks, right after an event, and must not show a stale READY.
        linger = self._ready_linger()
        timers = [t for t in timers if self._overdue(t, now) < linger]
        if self.settings.get("hide_ready_entries"):
            timers = [t for t in timers if not t.is_ready(now)]
        if self.settings.get("sort_by_role"):
            timers.sort(key=lambda t: (ROLE_ORDER.get(t.role, 5),
                                       t.champion_name, t.remaining(now)))
        else:
            timers.sort(key=lambda t: (t.remaining(now), t.champion_name))
        return timers

    def add_preview(self) -> int:
        """Insert short fake timers so the overlay can be checked without a game.

        Durations are deliberately tiny (20s) rather than real cooldowns: it
        spreads markers across the whole track immediately, and the displayed
        times are small enough that a preview can never be mistaken for real
        data. They expire on their own.
        """
        samples = [
            # (champion, spell, duration, remaining) -> left, middle, right
            ("Ahri", "Flash", 20.0, 19.0),
            ("Darius", "Teleport", 20.0, 10.0),
            ("Jinx", "Heal", 20.0, 2.5),
        ]
        now = time.monotonic()
        added = 0
        for champion_id, spell_key, duration, remaining in samples:
            champion = self.assets.champions.get(champion_id)
            spell = self.assets.spells.get(spell_key)
            if champion is None or spell is None:
                continue
            self._timers[(champion_id, spell_key)] = ActiveTimer(
                champion_id=champion_id,
                champion_name=champion.name,
                kind="summoner",
                spell_key=spell_key,
                spell_name=spell.name,
                duration=duration,
                started_at=now - (duration - remaining),
                # Suppress the audio cues; this is a visual check.
                warned=True,
                announced_ready=True,
            )
            added += 1
        log.info("preview: %d timers added", added)
        return added

    def active_count(self) -> int:
        now = time.monotonic()
        return sum(1 for t in self._timers.values() if not t.is_ready(now))
