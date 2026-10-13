# -*- coding: utf-8 -*-
"""What the capture loop does with what it is given, without a game or an OCR.

The four behaviours the overhaul added to the loop, each one a fix for something
that went wrong on a real install:

* a hand-drawn chat area too narrow to hold a line is widened -- one 249 px wide
  cut every line off before the spell, for two months, silently;
* a row running into the right edge of the area widens it further;
* an explore pass that finds nothing waits longer before the next one, so an
  empty chat at the start of a game no longer costs most of a core;
* a mode that is switched off captures nothing at all, and the team areas are
  only read in a game -- with only the client open they hold champion select.
"""
import sys, io, os, queue

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_capturetest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"
if settings_module.CONFIG_PATH.exists():
    settings_module.CONFIG_PATH.unlink()

import numpy as np

import chat_detector
import ocr
from chat_detector import ChatRegion
from game_detector import GameState
from message_parser import MessageParser
from riot_assets import RiotAssets
from settings import Settings

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


WINDOW = (0, 0, 1920, 1080)

# ------------------------------------------------------- hand-drawn areas
narrow = ChatRegion(48, 629, 249, 168, source="manual", confirmed=True)
fitted = chat_detector.fit_manual_region(narrow, WINDOW)
check("a hand-drawn area too narrow for a chat line is widened",
      fitted.width == int(1920 * chat_detector.MANUAL_MIN_WIDTH_FRACTION),
      fitted.describe())
check("its position and height are left as drawn",
      (fitted.x, fitted.y, fitted.height) == (48, 629, 168))
wide = ChatRegion(20, 600, 700, 200, source="manual", confirmed=True)
check("one already wide enough is left alone",
      chat_detector.fit_manual_region(wide, WINDOW).rect == wide.rect)
edge = ChatRegion(1800, 600, 60, 100, source="manual", confirmed=True)
check("widening never runs off the window",
      chat_detector.fit_manual_region(edge, WINDOW).x
      + chat_detector.fit_manual_region(edge, WINDOW).width <= 1920)
check("no window, nothing to measure against: unchanged",
      chat_detector.fit_manual_region(narrow, None).rect == narrow.rect)

# ------------------------------------------------------- the worker
assets = RiotAssets("en_US")
assets.bootstrap()
settings = Settings()
worker = ocr.CaptureWorker(settings, MessageParser(assets), queue.Queue())


class FakeDetector:
    def __init__(self, state):
        self.state = state

    def poll(self):
        return self.state, False


grabs = []


def fake_grab(monitor):
    grabs.append(dict(monitor))
    return np.zeros((max(10, monitor["height"]), max(20, monitor["width"]), 3),
                    np.uint8)


worker._grab = fake_grab
worker._sct = object()

# Rows running into the edge widen the area, and the change is saved.
region = ChatRegion(48, 629, 576, 168, source="manual", confirmed=True)
worker.set_manual_region(region)
worker._widen_if_cut(region, [(4, 40, 572, 14)], region.width, WINDOW)
check("a chat row cut off by the edge widens the area",
      worker.region.width > region.width, worker.region.describe())
check("and the wider area is what is saved",
      settings.get("chat_region") == worker.region.as_list(),
      str(settings.get("chat_region")))
before = worker.region.width
worker._widen_if_cut(worker.region, [(4, 40, 300, 14)], worker.region.width,
                     WINDOW)
check("a row ending well inside changes nothing", worker.region.width == before)
for _ in range(10):
    worker._widen_if_cut(worker.region, [(4, 40, worker.region.width, 14)],
                         worker.region.width, WINDOW)
check("widening stops at the band chat can occupy",
      worker.region.x + worker.region.width
      <= int(1920 * chat_detector.ZONE_RIGHT) + 1, worker.region.describe())
worker.set_test_mode(True)
held = worker.region.width
worker._widen_if_cut(ChatRegion(48, 629, 300, 168, source="manual",
                                confirmed=True), [(4, 40, 298, 14)], 300, WINDOW)
check("an area being placed in test mode is never resized under the cursor",
      worker.region.width == held)
worker.set_test_mode(False)

# Exploring an empty band backs off.
worker.set_manual_region(None)
settings.set("chat_region_locked", False)
worker.detector = FakeDetector(GameState(in_game=True, client_running=True,
                                         hwnd=1, window_rect=WINDOW,
                                         session_id="pid:1"))
worker.differ.changed = lambda frame: True
intervals = []
for _ in range(8):
    worker._last_explore = 0.0
    worker._iterate()
    intervals.append(round(worker._explore_interval, 2))
check("an explore pass that finds nothing waits longer before the next",
      intervals == sorted(intervals) and intervals[-1] == ocr.EXPLORE_MAX_INTERVAL,
      str(intervals))
check("but never longer than a chat line stays on screen",
      ocr.EXPLORE_MAX_INTERVAL <= 3.0)

# Paused: nothing is captured.
grabs.clear()
worker.set_paused(True)
for _ in range(3):
    worker._iterate()
check("a mode that is off captures nothing at all", not grabs, str(grabs[:1]))
check("and says so in the status", worker.status.region == "-")
worker.set_paused(False)
worker._last_explore = 0.0
worker._iterate()
check("resuming captures again", bool(grabs))

# The team areas: in a game only.
read = []
worker._read_roles = lambda: read.append(1)
worker.detector = FakeDetector(GameState(in_game=False, client_running=True))
worker._iterate()
check("with only the client open the team areas are not read", not read)
worker.detector = FakeDetector(GameState(in_game=True, client_running=True,
                                         hwnd=1, window_rect=WINDOW,
                                         session_id="pid:1"))
worker._iterate()
check("in a game they are", bool(read))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
