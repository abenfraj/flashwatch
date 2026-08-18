"""Persisted user settings.

Backed by a plain JSON file next to the assets cache so the config is easy to
inspect and delete. Everything the user can tweak lives here, including the
overlay geometry so it survives a restart.

It also has to survive an update, which for a portable .exe means surviving the
program moving house; :func:`carry_config_forward` at the bottom is what makes
that true whichever way the user updates.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("", "utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_root() -> Path:
    """Where settings, the icon cache and the log live.

    Running from source that is the repository. Frozen into a single .exe it must
    *not* be derived from ``__file__``: PyInstaller unpacks the bundle into a
    temporary directory that is deleted on exit, so settings and the 20 MB of
    cached icons would be thrown away after every run.

    Next to the .exe is what people expect from a portable program -- copy the
    folder, keep your settings. If that directory is read-only (Program Files, a
    network share, a zip opened in place), fall back to the user's own data
    directory rather than failing to save.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent

    beside_exe = Path(sys.executable).resolve().parent
    if _writable(beside_exe / "assets"):
        return beside_exe
    fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Flashwatch"
    log.info("%s is not writable, using %s", beside_exe, fallback)
    return fallback


ROOT = _data_root()
ASSETS_DIR = ROOT / "assets"
CACHE_DIR = ASSETS_DIR / "cache"
CHAMPION_ICON_DIR = CACHE_DIR / "champions"
SPELL_ICON_DIR = CACHE_DIR / "spells"
SFX_DIR = CACHE_DIR / "sfx"
CONFIG_PATH = ASSETS_DIR / "settings.json"

# A note of where the last run kept its data, written outside every candidate
# data root so it survives the one thing an update can change: which directory
# the program runs from. See :func:`carry_config_forward`.
BREADCRUMB_PATH = (Path(os.environ.get("LOCALAPPDATA", Path.home()))
                   / "Flashwatch" / "last-data-root.txt")

DEFAULTS: dict[str, Any] = {
    # --- overlay -------------------------------------------------------
    # Which of the three displays is drawn. None is "the right one": a 4K
    # ultrawide and a 1080p laptop, a jungler watching two enemies and a support
    # watching five, do not want the same thing, so the choice is the user's.
    #
    # "bar"   : horizontal track at the top centre; each spell rides left to
    #           right as its cooldown runs down, so position *is* progress.
    # "cards" : one fixed card per cooldown -- portrait, progress ring, spell
    #           badge, countdown. Nothing moves, which is what makes it readable
    #           mid-fight.
    # "list"  : compact rows, one per spell, each with a progress gauge.
    "overlay_layout": "bar",
    # Geometry per layout: {"bar": [x, y, w, h], ...}. Kept apart because the
    # three shapes have nothing in common -- a position and size that suit a wide
    # top strip would put the vertical rows half off screen, and switching
    # display must never lose where the previous one was placed.
    "layout_geometry": {},
    # Legacy. Superseded by layout_geometry above and only read once, to carry a
    # position saved by an older version into the new per-layout store.
    "bar_placed": False,
    # Draw the empty track when nothing is on cooldown. Without it the bar is
    # completely invisible at rest, which is maximally discreet but leaves no
    # sign the application is alive or where the bar sits.
    "bar_show_when_idle": True,
    # Stand the track on its end: cooldowns run top to bottom down a side of the
    # screen instead of left to right along the top, with the countdown beside
    # each portrait rather than under it. Only affects the "bar" display, and it
    # keeps its own rectangle, since the two shapes have nothing in common.
    "bar_vertical": False,
    # Keep the overlay off screen until League's in-game window is up. Outside a
    # game the bar has nothing to say and would sit over the client or the
    # desktop; it still appears while unlocked, so it can be positioned.
    "hide_until_in_game": True,
    "overlay_x": 40,
    "overlay_y": 120,
    "overlay_width": 260,
    "overlay_height": 420,
    "overlay_visible": True,
    "overlay_locked": True,          # locked == click-through
    "overlay_opacity": 0.92,
    "overlay_scale": 1.0,
    # Light by default: it is the product's face, and the light overlay is the
    # only one of the three that stays legible over a bright game as well as a
    # dark one -- at the cost of being a little more opaque. dark | light | neon
    "theme": "light",
    # The countdown's face. "auto" takes the first of the built-in preferences
    # this machine actually has (Bahnschrift, then Segoe UI, then a mono); any
    # other value names one of the faces offered in the settings, and is ignored
    # if that font is not installed. Only the *countdown* -- the champion and
    # spell labels stay on the interface's own face, because they are text and
    # the countdown is a readout.
    "timer_font": "auto",
    # Size of that readout, as a multiple of the size everything else is drawn
    # from. Half by default: the countdown was sized to be readable from across
    # the room, which in practice makes the overlay much larger than the
    # information in it warrants, and every layout measures its rows through this
    # so a smaller number shrinks the block rather than leaving a hole in it.
    "timer_font_scale": 0.5,
    "sort_by_role": True,
    "hide_ready_entries": False,
    # How long a spell keeps showing READY once it is back up, before its entry
    # disappears. Long enough to be read as a confirmation, short enough that the
    # bar does not fill up with spells that are no longer news. 0 removes the
    # entry the moment it is ready; the entry is never kept forever, since a bar
    # of READY badges says nothing about what is actually down.
    "ready_linger_seconds": 5,

    # --- capture / OCR -------------------------------------------------
    "capture_interval_ms": 200,
    "ocr_lines_kept": 40,
    # [x, y, w, h] in virtual-screen coords. Seeded with a working 1920x1080
    # layout so a fresh install has somewhere sensible to start rather than
    # exploring the whole screen on its first game.
    #
    # This does *not* hardcode the chat position. The seed is paired with
    # chat_region_window below and is only honoured while the League window
    # actually is that size; on any other resolution or in windowed mode the
    # restore path discards it and detection runs normally. Left deliberately
    # unlocked for the same reason -- locking would pin it unconditionally.
    "chat_region": [39, 537, 556, 285],
    "chat_region_locked": False,     # True == user pinned it manually
    # Client size the saved region was found at; it is discarded if the window
    # size changes, since the region would no longer line up.
    "chat_region_window": [1920, 1080],

    # Two further areas the user places by hand in test mode, both [x, y, w, h]
    # in virtual-screen coordinates. The values here are the 1920x1080 ones;
    # a fresh install rescales them to its own screen through ZONE_FRACTIONS
    # below, so these are the fallback rather than the answer.
    #
    # Neither is guarded by a window size the way the chat region is, because
    # neither is ever searched for: there is nothing to fall back to, so the user
    # places it by hand if the seed is wrong. The clock is the one that matters,
    # and a misplaced one is cheap: a reading is only adopted once a second one
    # agrees with it, and anything that is not a plausible mm:ss is dropped.
    #
    # The clock is read and used: it is the game time itself, so it beats the
    # timestamps prefixing chat lines (which the player can switch off) and keeps
    # ping age-correction and ultimate ranks honest.
    "clock_region": [1852, 8, 56, 18],
    # The enemy team's five portraits in the scoreboard (Tab), as a narrow column
    # rather than the whole panel: the reader identifies each portrait by matching
    # it against the champion icons already cached for the overlay, and a frame
    # wide enough to hold names and items would spend its time sliding a window
    # across gold counts.
    "scoreboard_region": [330, 507, 116, 272],
    # The enemy row on the loading screen, where the champion names are printed.
    # Wide and shallow: five cards side by side.
    "loading_region": [336, 545, 1248, 260],

    # --- Riot data ------------------------------------------------------
    # Locale of the League client, chosen in the settings window. Drives three
    # things at once: the localised strings matched in chat, the champion and
    # spell names downloaded, and the language of the interface. "fr_FR" or
    # "en_US"; anything else falls back to English for the interface.
    #
    # English until the guide asks, because the question itself has to be
    # written in some language and that is the one most players read.
    "locale": "en_US",

    # --- what to track --------------------------------------------------
    "track_summoners": True,
    "track_ultimates": True,
    # Only start a timer when the champion named on the line is drawn in the
    # enemy colour (red).
    #
    # Off by default, and the reason is what each wording actually is. In a real
    # game the only line that appears is the cast announcement ("Ahri a utilise
    # Saut eclair"), which the game prints for enemies only -- it never needs
    # vetting, and it is never filtered by this option anyway. The stated-cooldown
    # form ("Attendez Ahri Saut eclair - 245 sec.") is in practice a line you type
    # yourself to check that the OCR reads your chat, and typed text is not drawn
    # red -- so leaving this on would reject exactly the line used for testing.
    "require_enemy_colour": False,
    # Act on timers teammates type in chat: "jgl flash 950" puts the jungler's
    # Flash back up at 9:50. On by default -- it is how League communicates
    # cooldowns, and the app knowing what the team already knows costs nothing.
    # A call always shows the "?" mark, since it is somebody's word rather than
    # the client's, and a line with no time in it never starts anything.
    "chat_calls": True,
    # Work out the enemy's lanes from the loading screen and the scoreboard,
    # which both list a team in lane order. Feeds the sort-by-role display and is
    # what makes a call naming a lane resolvable at all. Off means the roles are
    # whatever the user picks in the Enemies list, as before.
    "auto_roles": True,

    # --- cooldown modifiers -------------------------------------------
    # Cosmic Insight (18% summoner haste) is near-universal, so it is assumed by
    # default. It matters less than it looks: when the game states the remaining
    # time the number is authoritative regardless. It affects the cast-announcement
    # path, and the full cooldown used to place a marker on the bar -- with the
    # rune a Flash is 246s, so a ping reporting 245s left correctly puts the
    # marker at the very start of the track instead of a fifth of the way along.
    "assume_cosmic_insight": True,
    "assume_ionian_boots": False,
    # Per-champion ability haste, keyed by champion id, e.g. {"Ahri": 20}.
    # Populated by hand for now; the planned scoreboard reader will fill this
    # in automatically from the enemy's items.
    "ability_haste": {},
    # Game-clock thresholds (seconds) at which we assume the enemy has put
    # rank 2 and rank 3 into their ultimate. Used only when the true rank is
    # unknown, which is always the case until the scoreboard reader lands.
    "ult_rank2_after": 720,          # 12:00
    "ult_rank3_after": 1260,         # 21:00

    # --- notifications -------------------------------------------------
    "audio_enabled": True,
    "audio_warn_seconds": 5,
    "audio_on_ready": True,
    # Which of the voices in audio.PRESETS the two cues are played in. They are
    # synthesised on demand rather than shipped, so the choice costs a tenth of a
    # second and no disk. "chime" is the original.
    "audio_sfx": "chime",

    # Shown once, the first time the close button hides the window instead of
    # quitting, so the disappearance is not mistaken for a crash.
    "tray_hint_shown": False,

    # Open the Flashwatch window when the program is launched, rather than going
    # straight to the notification area. On, because a program that appears to do
    # nothing when you double-click it is a program you double-click again.
    #
    # A login does not count as a launch, however this is set: the autostart entry
    # carries a flag (see autostart.STARTUP_FLAG) and a boot always stays in the
    # tray. Starting with Windows exists so Flashwatch is *already running* when a
    # game begins, and a settings window every morning is the opposite of that.
    "open_window_on_launch": True,

    # --- first run -------------------------------------------------------
    # The setup guide runs itself once. What it covers cannot be discovered by
    # poking at the interface -- League has to be in borderless, the client's
    # language decides what is looked for in chat, and the bar has to be put
    # somewhere the user actually wants it -- so the first run walks through it
    # rather than waiting to be asked. Set when the guide is finished *or*
    # skipped: offering it again would be nagging, and it stays one click away.
    "onboarding_done": False,

    # --- updates --------------------------------------------------------
    # One request to GitHub's release API at start-up. On by default: the program
    # is distributed as a bare .exe with no installer and no package manager
    # behind it, so a copy that never looks is a copy that stays on whatever
    # version it was downloaded at. It only ever *offers* -- nothing downloads or
    # installs itself without the button being pressed.
    "update_check_enabled": True,
    # A version the user chose to pass on. Only that exact one is silenced; the
    # release after it is offered again.
    "update_skipped_version": "",

    # --- misc -----------------------------------------------------------
    # Global hotkeys are opt-in: the `keyboard` library installs a system-wide
    # listener, which is unnecessary for normal use since the app needs no key
    # presses at all.
    "hotkeys_enabled": False,
}


# Where the two hand-placed areas sit, as fractions of the client area. These are
# the 1920x1080 seeds above divided by 1920x1080, so they reproduce them exactly
# on that screen and put the same *place* on any other one.
#
# Why fractions at all: unlike the chat region, neither of these is ever searched
# for, so a seed left at 1080p coordinates is simply wrong on a 1440p or 4K screen
# -- the clock probe then spends a read every 0.9s on empty pixels and the framing
# tool opens nowhere near the thing it is meant to frame. Scaling costs nothing and
# is right far more often than not, because both sit at a fixed spot in League's
# HUD rather than at a fixed number of pixels.
#
# The chat region is deliberately *not* in here. It is guarded by the window size
# it was found at, and a wrong-but-plausible chat seed is worse than none: it is
# adopted as confirmed and read for 30 seconds before the timeout sends detection
# back to exploring, where a discarded seed would have started exploring at once.
ZONE_FRACTIONS: dict[str, tuple[float, float, float, float]] = {
    # Top right, beside the minimap: League's match timer.
    "clock_region": (1852 / 1920, 8 / 1080, 56 / 1920, 18 / 1080),
    # The lower half of the Tab panel, at its left edge: the enemy portraits.
    "scoreboard_region": (330 / 1920, 507 / 1080, 116 / 1920, 272 / 1080),
    # The lower row of cards on the loading screen: the enemy team.
    "loading_region": (336 / 1920, 545 / 1080, 1248 / 1920, 260 / 1080),
}


def scaled_region(key: str, window_rect: tuple[int, int, int, int]
                  ) -> list[int] | None:
    """Where ``key``'s area sits in a client of this size, or None if untabled."""
    fractions = ZONE_FRACTIONS.get(key)
    if fractions is None:
        return None
    left, top, width, height = window_rect
    x, y, w, h = fractions
    return [left + int(round(width * x)), top + int(round(height * y)),
            max(8, int(round(width * w))), max(6, int(round(height * h)))]


class Settings:
    """Thread-safe dict-ish settings store with JSON persistence."""

    def __init__(self, path: Path | None = None) -> None:
        # Resolved here rather than as a default argument, which would freeze the
        # module-level path at import time: the tests point CONFIG_PATH at a
        # scratch file, and with a bound default they silently read and wrote the
        # user's real configuration instead.
        self._path = path if path is not None else CONFIG_PATH
        # Whether this run found no settings of its own, i.e. is a first run. Read
        # by the one thing that has to know: seeding the hand-placed areas for the
        # screen, which must happen once and never over a value the user has set.
        # Recorded before load() rather than asked afterwards, since load() is what
        # makes the answer unavailable.
        self.fresh = not self._path.exists()
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULTS)
        # Keys on disk that this version knows nothing about. Kept aside and
        # written back untouched; see load().
        self._foreign: dict[str, Any] = {}
        self.load()

    # -- persistence ----------------------------------------------------
    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("could not read %s (%s); using defaults", self._path, exc)
            return
        if isinstance(raw, dict):
            with self._lock:
                # Only known keys become settings, so a stale file cannot inject
                # junk into the running program. The rest is not discarded
                # though: it is written back out on save, so a settings file that
                # has been through a newer version -- one that renamed a key, or
                # added one -- is not quietly stripped of it by an older one.
                # Whichever version the user ends up on keeps what it understands.
                self._foreign = {}
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self._data[key] = value
                    else:
                        self._foreign[key] = value

    def save(self) -> None:
        with self._lock:
            # Known keys last: if a future version turns one of these into a real
            # setting, the live value is the one that wins.
            snapshot = {**self._foreign, **self._data}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snapshot, indent=2), "utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("could not write %s (%s)", self._path, exc)

    # -- access ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        with self._lock:
            if self._data.get(key) == value:
                return
            self._data[key] = value
        if save:
            self.save()

    def update(self, values: dict[str, Any], *, save: bool = True) -> None:
        with self._lock:
            self._data.update(values)
        if save:
            self.save()

    def reset(self) -> None:
        # Foreign keys go too: this is the user asking for a clean slate, and
        # leaving behind values from a version they are no longer running would
        # not be one.
        with self._lock:
            self._data = dict(DEFAULTS)
            self._foreign = {}
        self.save()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    __getitem__ = get

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)


def ensure_dirs() -> None:
    for directory in (CACHE_DIR, CHAMPION_ICON_DIR, SPELL_ICON_DIR, SFX_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------- updates
#
# Settings live in ``assets`` beside the executable, so the in-app update -- which
# renames a new .exe over the old one in the same directory -- keeps them without
# anything having to be done about it.
#
# What loses them is the *other* way people update: downloading the .exe from the
# releases page and running it from wherever the browser put it. That is a new
# data root with no settings.json in it, so a copy that had been positioned,
# themed and pointed at the right chat area comes up as a fresh install.
#
# So each run leaves a note of where its data lives, in a fixed place no update
# can move, and a start-up that finds no settings of its own reads that note and
# copies the previous ones in. Copies rather than moves: the old install stays
# exactly as it was, which matters when the "new" copy turns out to be the one
# the user throws away.


def remember_data_root(root: Path, breadcrumb: Path) -> bool:
    """Record ``root`` as where this run keeps its data. Never raises."""
    try:
        breadcrumb.parent.mkdir(parents=True, exist_ok=True)
        breadcrumb.write_text(str(root), "utf-8")
        return True
    except OSError as exc:
        log.info("could not write %s (%s)", breadcrumb, exc)
        return False


def previous_config(current: Path, breadcrumb: Path) -> Path | None:
    """A usable settings file left by an earlier install, or None.

    None whenever there is nothing to do: no note, the note points at where we
    already are, the file is gone (an install that was deleted), or it does not
    parse. That last check is what stops a truncated or hand-mangled file being
    carried forward and taking out the new copy as well.
    """
    try:
        recorded = breadcrumb.read_text("utf-8").strip()
    except (OSError, ValueError):
        return None
    if not recorded:
        return None

    candidate = Path(recorded) / "assets" / "settings.json"
    try:
        if candidate.resolve() == current.resolve():
            return None
        if not candidate.is_file():
            return None
        if not isinstance(json.loads(candidate.read_text("utf-8")), dict):
            return None
    except (OSError, ValueError) as exc:
        log.info("ignoring the settings at %s (%s)", candidate, exc)
        return None
    return candidate


def carry_config_forward(current: Path | None = None,
                         breadcrumb: Path | None = None,
                         root: Path | None = None) -> bool:
    """Adopt an earlier install's settings, then note where this one keeps its own.

    Returns whether anything was adopted. Called once at start-up, before the
    settings are read.

    Only ever fills a *gap*: an existing settings.json is never overwritten, so
    this cannot reach across and clobber a copy the user is actively configuring.
    The icon cache is deliberately not copied -- it is 20 MB of files that the
    first run downloads by itself, and a slow first start is a much smaller loss
    than a wrong one.

    Paths are arguments rather than module-level defaults because binding them at
    import time is what once had the tests reading the real configuration.
    """
    current = current if current is not None else CONFIG_PATH
    breadcrumb = breadcrumb if breadcrumb is not None else BREADCRUMB_PATH
    root = root if root is not None else ROOT

    adopted = False
    if not current.exists():
        source = previous_config(current, breadcrumb)
        if source is not None:
            try:
                current.parent.mkdir(parents=True, exist_ok=True)
                current.write_bytes(source.read_bytes())
                log.info("carried settings forward from %s", source)
                adopted = True
            except OSError as exc:
                log.warning("could not carry settings forward from %s (%s)",
                            source, exc)

    remember_data_root(root, breadcrumb)
    return adopted
