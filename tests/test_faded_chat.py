# -*- coding: utf-8 -*-
"""The case that failed in a real game: a ping read with the chat box CLOSED.

With chat closed, League draws recent messages faint and unbacked directly over
the game. Reported symptom: pinging twice registered nothing until the chat box
was opened by hand.

Two separate defects were involved, both covered here:

  * the row cache keyed rows on a tolerant image fingerprint, and two chat lines
    differing only in their seconds value are indistinguishable that way, so a
    new ping could be served another line's cached text and never read; and
  * faint text can fall below a global Otsu split during row segmentation, so it
    was not even offered to recognition.
"""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
sys.path.insert(0, r"C:\Users\ayoub\dev\flashwatch\tests")

import cv2

import chat_detector
from riot_assets import RiotAssets
from message_parser import MessageParser, looks_like_chat_line
from ocr import OcrEngine
from synthetic_frames import make_frame

OUT = os.path.join(os.environ.get("TEMP", "."), "flashwatch_debug")
os.makedirs(OUT, exist_ok=True)        # debug images for a failing run

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")

assets = RiotAssets("fr_FR"); assets.bootstrap()
parser = MessageParser(assets)
engine = OcrEngine(); engine.load()

flash = assets.spells["Flash"].name
tp = assets.spells["Teleport"].name
W, H = 1920, 1080
WR = (0, 0, W, H)

PING = f"Ayoub (Lux): Attendez Ahri {flash} - 245 sec."
PING2 = f"Ayoub (Lux): Attendez Ahri {flash} - 240 sec."
OTHER = f"Ayoub (Lux): Attendez Darius {tp} - 100 sec."


def read_region(frame):
    """Locate chat then read it, exactly as CaptureWorker does."""
    ex = chat_detector.explore_region(WR)
    band = frame[ex.y:ex.y + ex.height, ex.x:ex.x + ex.width]
    rows, _ = engine.read_rows(
        band, max_rows=chat_detector.EXPLORE_MAX_ROWS,
        left_fraction=chat_detector.EXPLORE_LEFT_FRACTION,
        min_width_fraction=chat_detector.EXPLORE_MIN_ROW_WIDTH)
    chat_rows = [b for t, b in rows if looks_like_chat_line(t)]
    region = chat_detector.region_from_chat_rows(chat_rows, (ex.x, ex.y), WR)
    if region is None:
        return None, [], rows
    crop = frame[region.y:region.y + region.height,
                 region.x:region.x + region.width]
    lines, _ = engine.read_rows(
        crop, min_width_fraction=chat_detector.CONFIRMED_MIN_ROW_WIDTH)
    return region, [t for t, _ in lines], rows


# ---------------------------------------------- faded, unbacked chat text
for opacity in (1.0, 0.75, 0.55, 0.40):
    engine.clear_cache()
    frame, _ = make_frame(W, H, lines=[PING], panel=False,
                          text_opacity=opacity)
    region, lines, band_rows = read_region(frame)
    found = region is not None
    check(f"faded {opacity:.2f}: chat located without a panel", found,
          region.describe() if region else f"{len(band_rows)} band rows")
    if not found:
        cv2.imwrite(os.path.join(OUT, f"faded_fail_{opacity:.2f}.png"), frame)
        continue
    events = parser.parse_lines(lines)
    got = {(e.champion_id, e.spell_key, e.remaining_seconds) for e in events}
    check(f"faded {opacity:.2f}: ping parsed", ("Ahri", "Flash", 245) in got,
          f"lines={lines}")


# ------------------------------------- the cache must not serve stale text
# Two pings differing only in the number. A tolerant cache key returned the
# first one's text for the second, so the repeat ping was never seen.
engine.clear_cache()
frame_a, _ = make_frame(W, H, lines=[PING], panel=False, text_opacity=0.7)
_, lines_a, _ = read_region(frame_a)
frame_b, _ = make_frame(W, H, lines=[PING2], panel=False, text_opacity=0.7)
_, lines_b, _ = read_region(frame_b)

secs_a = {e.remaining_seconds for e in parser.parse_lines(lines_a)}
secs_b = {e.remaining_seconds for e in parser.parse_lines(lines_b)}
check("first ping reads 245", 245 in secs_a, str(secs_a))
check("second ping reads 240, not the cached 245", 240 in secs_b, str(secs_b))
check("the two pings are not confused", secs_a != secs_b,
      f"{secs_a} vs {secs_b}")

# A different champion's ping right after must not inherit cached text either.
# The guarantee is "correct or rejected, never another line's text": a dropped
# digit ("100" recognised as "00") has to fail closed, because trusting a zero
# would clear a live timer.
frame_c, _ = make_frame(W, H, lines=[OTHER], panel=False, text_opacity=0.7)
_, lines_c, _ = read_region(frame_c)
events_c = parser.parse_lines(lines_c)
got_c = {(e.champion_id, e.spell_key, e.remaining_seconds) for e in events_c}
check("a different ping never inherits cached text",
      all(champ == "Darius" and key == "Teleport" and secs == 100
          for champ, key, secs in got_c),
      str(got_c) or "rejected (digit lost in recognition)")
check("no ping is ever reported with a zero cooldown",
      all(e.remaining_seconds != 0 for e in events_c))


# --------------------------------- several messages, chat closed and faded
many = [PING, OTHER, "Kevin (Jinx) : attention mid"]

# Fading alone, isolated from occlusion: every ping must be read.
engine.clear_cache()
frame_f, _ = make_frame(W, H, lines=many, panel=False, text_opacity=0.6,
                        clutter=False)
region_f, lines_f, _ = read_region(frame_f)
check("multiple faded lines: chat located", region_f is not None)
if region_f is not None:
    got_f = {(e.champion_id, e.spell_key) for e in parser.parse_lines(lines_f)}
    check("fading alone: both pings parsed",
          {("Ahri", "Flash"), ("Darius", "Teleport")} <= got_f,
          str(sorted(got_f)))

# Faded *and* over heavy clutter. Bright scenery can physically overlap a line
# and merge with it into one connected blob, which no amount of thresholding
# recovers -- that line is unreadable in that frame. It is not lost, though:
# chat lines persist for seconds while the scene moves, and the confirmed region
# is re-read at least every FORCED_OCR_INTERVAL, so a later frame gets it. The
# requirement is therefore that occlusion costs a frame, never a wrong reading.
engine.clear_cache()
frame_m, _ = make_frame(W, H, lines=many, panel=False, text_opacity=0.6)
region_m, lines_m, _ = read_region(frame_m)
events_m = parser.parse_lines(lines_m)
got_m = {(e.champion_id, e.spell_key) for e in events_m}
check("faded over clutter: at least one ping still read", len(got_m) >= 1,
      str(sorted(got_m)))
check("faded over clutter: nothing is misreported",
      all(e.remaining_seconds in (245, 100) for e in events_m),
      str([(e.champion_id, e.spell_key, e.remaining_seconds) for e in events_m]))
cv2.imwrite(os.path.join(OUT, "faded_multi.png"), frame_m)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
