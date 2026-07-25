"""Persisted user settings.

Backed by a plain JSON file next to the assets cache so the config is easy to
inspect and delete. Everything the user can tweak lives here, including the
overlay geometry so it survives a restart.
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

DEFAULTS: dict[str, Any] = {
    # --- overlay -------------------------------------------------------
    # "bar"  : discreet horizontal track at the top centre; each spell rides
    #          left to right as its cooldown runs down.
    # "list" : vertical panel listing each spell and its remaining time.
    "overlay_layout": "bar",
    # Set once the bar has been centred at the top of the screen, so a saved
    # position from the list layout is not reused for it.
    "bar_placed": False,
    # Draw the empty track when nothing is on cooldown. Without it the bar is
    # completely invisible at rest, which is maximally discreet but leaves no
    # sign the application is alive or where the bar sits.
    "bar_show_when_idle": True,
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
    "theme": "dark",                 # dark | light | neon
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
    "chat_region": None,             # [x, y, w, h] in virtual-screen coords
    "chat_region_locked": False,     # True == user pinned it manually
    # Client size the saved region was found at; it is discarded if the window
    # size changes, since the region would no longer line up.
    "chat_region_window": None,

    # Two further areas the user places by hand in test mode, both [x, y, w, h]
    # in virtual-screen coordinates.
    #
    # The clock is read and used: it is the game time itself, so it beats the
    # timestamps prefixing chat lines (which the player can switch off) and keeps
    # ping age-correction and ultimate ranks honest.
    "clock_region": None,
    # The scoreboard is read and shown but not yet interpreted; placing it now is
    # what the planned reader (enemy items -> real ability haste) will use.
    "scoreboard_region": None,

    # --- Riot data ------------------------------------------------------
    # Locale of the League client, chosen in the settings window. Drives three
    # things at once: the localised strings matched in chat, the champion and
    # spell names downloaded, and the language of the interface. "fr_FR" or
    # "en_US"; anything else falls back to French for the interface.
    "locale": "fr_FR",

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

    # --- misc -----------------------------------------------------------
    # Global hotkeys are opt-in: the `keyboard` library installs a system-wide
    # listener, which is unnecessary for normal use since the app needs no key
    # presses at all.
    "hotkeys_enabled": False,
}


class Settings:
    """Thread-safe dict-ish settings store with JSON persistence."""

    def __init__(self, path: Path | None = None) -> None:
        # Resolved here rather than as a default argument, which would freeze the
        # module-level path at import time: the tests point CONFIG_PATH at a
        # scratch file, and with a bound default they silently read and wrote the
        # user's real configuration instead.
        self._path = path if path is not None else CONFIG_PATH
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULTS)
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
                # Only accept known keys so a stale file cannot inject junk.
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self._data[key] = value

    def save(self) -> None:
        with self._lock:
            snapshot = dict(self._data)
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
        with self._lock:
            self._data = dict(DEFAULTS)
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
