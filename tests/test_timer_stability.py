# -*- coding: utf-8 -*-
"""A timer, once set, must not move on its own.

Every check here is a way timers were observed to vanish or jump mid-game. They
are grouped by the thing that used to touch a running timer:

1. a stale or mangled ping computing a negative remaining, which *deleted* it;
2. a cast announcement recomputing a cooldown over the top of a pinged one;
3. one misread timestamp looking like a brand-new game and wiping everything;
4. the game window not answering for a moment, read as "the game ended".

The fourth is not OCR at all and was the most frequent: alt-tab, a loading
screen, or an unlucky EnumWindows ended the session, cleared the board, and
started a "new" session on the next poll.
"""
import sys, io, os, threading, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")

import game_detector
from game_detector import GameDetector
from message_parser import MessageParser
from riot_assets import RiotAssets
from settings import DEFAULTS, Settings
from timer_manager import PRIME_FRAMES, NEW_GAME_CONFIRMATIONS, TimerManager

assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)

settings = Settings.__new__(Settings)          # never touch the real config
settings._path = None
settings._lock = threading.RLock()
settings._data = dict(DEFAULTS)
settings._data["assume_cosmic_insight"] = False
settings._data["assume_ionian_boots"] = False
settings.save = lambda: None

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def primed():
    manager = TimerManager(assets, settings)
    for _ in range(PRIME_FRAMES):
        manager.note_frame()
    return manager


def feed(manager, *lines):
    return manager.handle_events(parser.parse_lines(list(lines)))


def flash_of(manager):
    return next((t for t in manager.snapshot() if t.spell_key == "Flash"), None)


# ------------------------------------------ 1. a stale ping must not delete
manager = primed()
feed(manager, "(12:00) Kevin (Jinx): Attendez Darius Saut eclair - 240 sec.")
live = flash_of(manager)
check("a ping starts a timer", live is not None and live.stated,
      f"{live.remaining():.0f}s" if live else "none")
before = live.remaining()

# Scrollback reveals an older ping for the same spell, never read until now: it
# describes a cooldown that has long since ended. It must not touch this one.
feed(manager, "(4:00) Kevin (Jinx): Attendez Darius Saut eclair - 30 sec.")
after = flash_of(manager)
check("an older ping revealed by scrollback leaves the timer alone",
      after is not None and abs(after.remaining() - before) < 2,
      f"{after.remaining():.0f}s vs {before:.0f}s" if after else "deleted")

# The same line with its timestamp mangled into an earlier one -- the OCR failure
# that made the remaining time come out negative and popped the entry.
feed(manager, "(2:00) Kevin (Jinx): Attendez Darius Saut eclair - 241 sec.")
after = flash_of(manager)
check("a ping with a mangled early timestamp does not delete the timer",
      after is not None, "deleted" if after is None else f"{after.remaining():.0f}s")

# A genuine recast, on the other hand, must be picked up.
feed(manager, "(14:00) Kevin (Jinx): Attendez Darius Saut eclair - 300 sec.")
recast = flash_of(manager)
check("a real recast still restarts the timer",
      recast is not None and recast.remaining() > before + 15,
      f"{recast.remaining():.0f}s vs {before:.0f}s" if recast else "none")


# --------------------------- 2. an estimate must not overwrite a stated one
manager = primed()
feed(manager, "(12:00) Kevin (Jinx): Attendez Ahri Saut eclair - 100 sec.")
pinged = flash_of(manager)
check("the pinged timer is marked as stated", pinged is not None and pinged.stated)
stated_remaining = pinged.remaining()

# The cast line for the same Flash, read afterwards. Its cooldown is a guess
# (base 300s here, since the rune assumptions are off), 200s longer than the
# number the game actually gave us.
feed(manager, "(12:00) Ahri a utilise Saut eclair")
kept = flash_of(manager)
check("a cast announcement does not overwrite a pinged cooldown",
      kept is not None and abs(kept.remaining() - stated_remaining) < 2,
      f"{kept.remaining():.0f}s want ~{stated_remaining:.0f}s" if kept else "none")

# With no ping in play, a cast announcement is still the source of a timer.
manager = primed()
feed(manager, "(12:00) Ahri a utilise Saut eclair")
check("a cast announcement alone does start a timer", flash_of(manager) is not None)
first = flash_of(manager).remaining()
# ...and re-reading the same cast a few frames later must not nudge it.
feed(manager, "(12:00) Ahri a utilise Saut eclair")
check("re-reading it does not nudge the countdown",
      abs(flash_of(manager).remaining() - first) < 2,
      f"{flash_of(manager).remaining():.0f}s vs {first:.0f}s")


# ------------------------- 3. one early timestamp is not a new game by itself
manager = primed()
feed(manager, "(20:00) Ahri a utilise Saut eclair")
check("timer running deep into the game", flash_of(manager) is not None)

# "10:45" misread as "0:45": exactly the shape of a fresh game.
feed(manager, "(0:45) Kevin (Jinx): Attendez Lux Barriere - 150 sec.")
check("a single early timestamp does not wipe the board",
      flash_of(manager) is not None,
      "everything was cleared" if flash_of(manager) is None else "kept")

# A second, independent line agreeing on an early clock is a real restart.
feed(manager, "(0:50) Viego a utilise Chatiment")
check("two agreeing early lines do reset the game",
      flash_of(manager) is None,
      f"{[t.champion_id for t in manager.snapshot()]}")
check("the confirmation threshold is what the test assumes",
      NEW_GAME_CONFIRMATIONS == 2, str(NEW_GAME_CONFIRMATIONS))


# --------------------- 4. a window that stops answering is not a finished game
class FakeWindow:
    """Stands in for the two win32 calls the detector makes."""

    def __init__(self):
        self.visible = True

    def find(self):
        return 4242 if self.visible else 0

    def rect(self, hwnd):
        return (0, 0, 1920, 1080) if self.visible and hwnd else None


fake = FakeWindow()
game_detector.find_game_window = fake.find
game_detector._client_rect_on_screen = fake.rect

detector = GameDetector()
detector._poll_processes = lambda *, force=False: (True, 9876)   # game is listed
state, changed = detector.poll()
check("the game is detected", state.in_game and changed, state.describe())
session = state.session_id

fake.visible = False                       # alt-tab, loading screen, bad luck
state, changed = detector.poll()
check("a window that goes missing does not end the session",
      not changed and state.session_id == session,
      f"changed={changed} session={state.session_id!r}")
check("but nothing is captured while it is missing", not state.in_game)

fake.visible = True
state, changed = detector.poll()
check("the same session resumes when the window answers again",
      not changed and state.in_game and state.session_id == session,
      f"changed={changed} session={state.session_id!r}")

# The process disappearing *and* the grace period elapsing is a finished game.
detector._poll_processes = lambda *, force=False: (False, 0)
fake.visible = False
detector._window_last_seen -= game_detector.WINDOW_LOSS_GRACE + 1
state, changed = detector.poll()
check("a game that really ended does end the session",
      changed and not state.session_id,
      f"changed={changed} session={state.session_id!r}")

# A new game is still a new session, so timers are cleared for it.
detector._poll_processes = lambda *, force=False: (True, 1234)
fake.visible = True
state, changed = detector.poll()
check("a new game starts a new session", changed and state.in_game,
      state.session_id)
check("and it is identified by the new process", state.session_id == "pid:1234",
      state.session_id)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
