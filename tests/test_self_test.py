# -*- coding: utf-8 -*-
"""The shipped self-test, and the segmentation work that made it possible.

Two things are checked here, and the second is why this file matters more than it
looks. The obvious one is that pressing Test works: the sample frame is read, the
chat is located in it, both spells are recognised and both produce timers.

The other is a regression guard on row segmentation. The sample is a real capture
with the chat box closed -- faint 13px lines drawn straight over moving scenery --
and the gradient mask that finds rows everywhere else finds *nothing* in it: Otsu
settles on a global threshold above the chat's own response. That is what the
second, white-hat mask exists for. Neither mask alone passes both this file and
test_capture_pipeline.py, so a well-meant simplification back to one of them
breaks a real case, and the numbers below are what says so.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

import cv2
import numpy as np

import chat_detector
import self_test
from cooldowns import COOLDOWNS, MODIFIER_COSMIC_INSIGHT
from message_parser import looks_like_chat_line
from ocr import OcrEngine
from riot_assets import RiotAssets
from settings import DEFAULTS
from timer_manager import TimerManager

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


# --------------------------------------------------------------- the sample
directory = self_test.sample_dir()
check("the sample ships with the program",
      (directory / self_test.IMAGE_NAME).is_file()
      and (directory / self_test.MANIFEST_NAME).is_file(), str(directory))

manifest = self_test.load_manifest(directory)
check("the manifest says what language the sample's chat is in",
      manifest.get("locale") == "en_US", str(manifest.get("locale")))
check("the manifest lists what the sample contains",
      len(manifest.get("expected", [])) >= 2)

engine = OcrEngine()
engine.load()

# ------------------------------------------------- it reads, in either client
# Run for both client locales, because the sample's chat is in one language while
# the interface may be in the other: the verdict has to be the same either way,
# or the test would pass or fail according to a setting that has nothing to do
# with whether the program works.
for locale in ("fr_FR", "en_US"):
    assets = RiotAssets(locale)
    assets.bootstrap()
    result = self_test.run(engine, assets, directory)

    check(f"[{locale}] the test passes", result.ok,
          f"error={result.error!r} chat_rows={result.chat_rows} "
          f"events={sorted(result.found)}")
    check(f"[{locale}] the chat area was derived from the timestamps",
          result.region is not None and result.region.confirmed,
          result.region.describe() if result.region else "none")
    check(f"[{locale}] every expected spell was recognised", not result.missing,
          str([(m.champion, m.spell) for m in result.missing]))
    check(f"[{locale}] no spell was invented",
          result.found == {(item["champion"], item["spell"])
                           for item in manifest["expected"]},
          str(sorted(result.found)))
    # The names shown come from the user's own Riot data, not from the sample's
    # language: a French client must not be told "Exhaust".
    names = {event.spell_name for event in result.events}
    if locale == "fr_FR":
        check("[fr_FR] the spell names are the client's, not the sample's",
              "Exhaust" not in names, str(sorted(names)))
    else:
        check("[en_US] the spell names are the client's",
              "Exhaust" in names, str(sorted(names)))

# ------------------------------------------------------ the region it found
# Where the chat actually sits in the sample, measured by hand off the image.
# The region has to cover it: a region that merely exists is not enough, since
# the next read happens inside it.
CHAT = (425, 435, 320, 130)               # x, y, w, h
region = result.region
covers = (region.x <= CHAT[0] and region.y <= CHAT[1]
          and region.x + region.width >= CHAT[0] + CHAT[2]
          and region.y + region.height >= CHAT[1] + CHAT[3])
check("the region covers the chat text", covers,
      f"got {region.rect} vs text {CHAT}")

# --------------------------------------------- both masks are load-bearing
raw = np.frombuffer((directory / self_test.IMAGE_NAME).read_bytes(), dtype=np.uint8)
frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
height, width = frame.shape[:2]
explore = chat_detector.explore_region((0, 0, width, height))
band = frame[explore.y:explore.y + explore.height,
             explore.x:explore.x + explore.width]
grey = engine.preprocess(band)

# Chat rows in band-local coordinates, from the same hand measurement.
top, bottom = CHAT[1] - explore.y, CHAT[1] + CHAT[3] - explore.y
left = CHAT[0] - explore.x


def in_chat(rows):
    return [box for box in rows
            if top - 8 <= box[1] <= bottom and abs(box[0] - left) < 60
            and box[2] > 60]


gradient_only = in_chat(OcrEngine.gradient_rows(grey))
both = in_chat(OcrEngine.segment_rows(grey, band))
check("the gradient mask alone does not find this chat",
      len(gradient_only) == 0,
      f"{len(gradient_only)} rows -- if this now passes, the second mask may be "
      f"removable, but check test_capture_pipeline.py first")
check("with the stroke mask the chat rows are found",
      len(both) >= 8, f"{len(both)} rows")
check("and they are separate rows, not one welded block",
      all(box[3] <= 24 for box in both),
      str(sorted(box[3] for box in both)))

# The rows are only useful if they read as chat lines: that is what locates the
# area, so a row found but unreadable would leave detection exactly where it was.
texts, _ms = engine.read_rows(
    band, max_rows=chat_detector.EXPLORE_MAX_ROWS,
    left_fraction=chat_detector.EXPLORE_LEFT_FRACTION,
    min_width_fraction=chat_detector.EXPLORE_MIN_ROW_WIDTH)
chat_lines = [text for text, _box in texts if looks_like_chat_line(text)]
check("the rows read as chat lines", len(chat_lines) >= 8,
      f"{len(chat_lines)} of {len(texts)}")

# --------------------------------------------------------- feeding the timers
# The sample was recorded at 10:18 of somebody else's game. Handing that
# timestamp to the manager would move its clock reference, and two lines agreeing
# on an early clock are its signal that a *new game* started -- which would wipe
# the timers of a real game in progress.
stripped = result.timer_events()
check("the sample's clock is stripped before the timers see it",
      all(event.game_time is None for event in stripped)
      and any(event.game_time is not None for event in result.events),
      str([event.game_time for event in result.events]))

primed = TimerManager(assets, FakeSettings())
check("a fresh manager is priming, so it would ignore these events",
      primed.priming)
check("...and does", not primed.handle_events(result.timer_events()))
# A dropped event is still *remembered* -- that is what priming means, and it is
# why the forced call below needs its own manager rather than reusing this one:
# feeding the same lines twice is deduped whatever priming says.
check("...and remembers them, so replaying them changes nothing",
      not primed.handle_events(result.timer_events(), force=True))

# The bypass is per call, not a switch on the manager: a test pressed in the first
# seconds of a real game must not turn that game's chat history into timers.
manager = TimerManager(assets, FakeSettings())
started = manager.handle_events(result.timer_events(), force=True)
check("forcing lets the test's events start timers",
      len(started) == len(result.events), f"{len(started)} timer(s)")
check("and the manager is still priming afterwards", manager.priming)
check("the timers name the sample's champions",
      {timer.champion_id for timer in started} == {"Yasuo", "Karma"},
      str(sorted(timer.champion_id for timer in started)))

# Both spells are 240s base, and Cosmic Insight is assumed by default.
want = round(COOLDOWNS["Exhaust"] * MODIFIER_COSMIC_INSIGHT)
for timer in started:
    remaining = timer.remaining()
    check(f"{timer.champion_id}'s timer runs the full cooldown",
          abs(remaining - want) <= 2, f"{remaining:.0f}s, expected ~{want}s")

check("the overlay would show them", manager.active_count() == 2,
      str(manager.active_count()))

# ------------------------------------------------------- failure is reported
missing = self_test.run(engine, assets, Path(os.environ["TEMP"]) / "no-such-dir")
check("a missing sample is reported rather than raised",
      bool(missing.error) and not missing.ok, missing.error[:80])

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
