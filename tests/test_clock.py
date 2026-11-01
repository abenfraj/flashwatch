# -*- coding: utf-8 -*-
"""The one clock the timers read, and why it can be replaced.

A replay drives the timer manager and the overlay from the video's time instead
of the machine's, so a countdown drawn for second 312 of a recording shows what it
showed at that second of the game. That only works if nothing in the timer path
reads ``time.monotonic()`` behind the clock's back -- which is what this file
checks, on a plain timer and on one the manager started itself.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import time

import clock
from message_parser import SpellEvent
from riot_assets import RiotAssets
from settings import DEFAULTS
from timer_manager import ActiveTimer, TimerManager

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


class FakeSettings:
    """Just the defaults, so the manager behaves as a fresh install would."""

    def __init__(self, **overrides):
        self._data = dict(DEFAULTS)
        self._data.update(overrides)

    def get(self, key, default=None):
        return self._data.get(key, default)


check("default is monotonic", abs(clock.now() - time.monotonic()) < 0.05)

# ------------------------------------------------------------- a plain timer
timer = ActiveTimer(champion_id="Ahri", champion_name="Ahri", kind="summoner",
                    spell_key="Flash", spell_name="Flash", duration=300.0,
                    started_at=1000.0)
clock.use(lambda: 1000.0)
check("a timer started now has its whole cooldown left",
      timer.remaining() == 300.0, str(timer.remaining()))
clock.use(lambda: 1060.0)
check("a minute later, a minute less", timer.remaining() == 240.0,
      str(timer.remaining()))

# ----------------------------------------------- one the manager started itself
assets = RiotAssets("en_US")
assets.bootstrap()
manager = TimerManager(assets, FakeSettings())
event = SpellEvent(champion_id="Yasuo", champion_name="Yasuo", kind="summoner",
                   spell_key="Exhaust", spell_name="Exhaust", game_time=617,
                   raw_line="(10:17) Yasuo used Exhaust",
                   signature="Yasuo|Exhaust|10:17")
clock.use(lambda: 500.0)
manager.handle_events([event], force=True)
started = manager.snapshot()
check("the manager starts a timer for the event", len(started) == 1,
      str(started))
if started:
    check("it is stamped on the replaceable clock",
          started[0].started_at <= 500.0, str(started[0].started_at))
    before = started[0].remaining()
    clock.use(lambda: 530.0)
    after = manager.snapshot()[0].remaining() if manager.snapshot() else None
    check("advancing the clock by 30 s takes exactly 30 s off",
          after is not None and abs((before - after) - 30.0) < 1e-9,
          f"{before} -> {after}")

clock.use(None)
check("use(None) puts the real clock back",
      abs(clock.now() - time.monotonic()) < 0.05)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
