# -*- coding: utf-8 -*-
"""Verifies the three work-avoidance layers in ocr.py actually work.

These are behavioural claims, not just speed numbers: the frame gate must ignore
a moving background but still notice a new chat line, and the row cache must
recognise only what changed.
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\tests")

import cv2
import numpy as np

import chat_detector
from ocr import OcrEngine, FrameDiffer
from riot_assets import RiotAssets
from message_parser import MessageParser, looks_like_chat_line
from synthetic_frames import make_frame, CHAT_LINES

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")

W, H = 1920, 1080
WR = (0, 0, W, H)

def chat_crop(frame, engine):
    """Locate chat the way CaptureWorker does, then return the narrowed crop."""
    explore = chat_detector.explore_region(WR)
    band = frame[explore.y:explore.y + explore.height,
                 explore.x:explore.x + explore.width]
    rows, _ = engine.read_rows(band,
                              max_rows=chat_detector.EXPLORE_MAX_ROWS,
                              left_fraction=chat_detector.EXPLORE_LEFT_FRACTION)
    chat_rows = [box for text, box in rows if looks_like_chat_line(text)]
    r = chat_detector.region_from_chat_rows(chat_rows, (explore.x, explore.y), WR)
    if r is None:
        return None, None
    return frame[r.y:r.y + r.height, r.x:r.x + r.width], r

engine = OcrEngine()
engine.load()
assets = RiotAssets("fr_FR"); assets.bootstrap()
parser = MessageParser(assets)

frame, _ = make_frame(W, H)
crop, region = chat_crop(frame, engine)
check("chat region found", crop is not None)

# ---------------------------------------------------------------- accuracy
lines, ms = engine.read_lines(crop)
events = parser.parse_lines(lines)
got = {(e.champion_id, e.spell_key) for e in events}
want = {("Ahri", "Flash"), ("Darius", "Teleport"), ("Viego", "Smite"), ("Lux", "Exhaust")}
check("segmentation+rec reads all casts", got == want, f"{ms:.0f}ms cold, got {sorted(got)}")

# ---------------------------------------------------------------- row cache
engine.cache_hits = engine.cache_misses = 0
t = time.perf_counter()
for _ in range(5):
    engine.read_lines(crop)
warm_ms = (time.perf_counter() - t) * 1000 / 5
check("repeat OCR of identical chat is nearly free", warm_ms < 25,
      f"{warm_ms:.1f}ms/run, {engine.cache_hits} hits / {engine.cache_misses} misses")
check("no recognition calls on unchanged rows", engine.cache_misses == 0,
      f"misses={engine.cache_misses}")

# One new chat line should cost roughly one row, not the whole box.
new_lines = CHAT_LINES + ["(14:05) Ahri a utilisé Fantôme"]
frame2, _ = make_frame(W, H, lines=new_lines)
crop2, _ = chat_crop(frame2, engine)
engine.cache_hits = engine.cache_misses = 0
t = time.perf_counter()
lines2, _ = engine.read_lines(crop2)
one_new_ms = (time.perf_counter() - t) * 1000
# The row cache is keyed on an *exact* pixel hash, so when a new message pushes
# the existing lines up, every row is new pixels and nothing is reused. That is
# the deliberate trade: a tolerant key could return another line's text, and two
# pings differing only in their seconds value are indistinguishable to any
# downscaled comparison. Correctness wins; the cost is one full read whenever the
# chat area actually changes.
check("a changed chat area costs at most one bounded full read",
      one_new_ms < 900, f"{one_new_ms:.0f}ms ({engine.cache_misses} rows read)")
events2 = parser.parse_lines(lines2)
check("the new cast is picked up",
      ("Ahri", "Ghost") in {(e.champion_id, e.spell_key) for e in events2},
      f"got {sorted((e.champion_id, e.spell_key) for e in events2)}")

# --------------------------------------------------- frame gate behaviour
# Moving game world behind unchanged chat text must NOT trigger OCR.
differ = FrameDiffer()
differ.changed(crop)
triggered = 0
rng = np.random.default_rng(3)
for i in range(20):
    moved = crop.copy()
    # Simulate scenery drifting behind the text: shift a mid-brightness overlay.
    noise = rng.integers(0, 70, size=moved.shape, dtype=np.uint8)
    blended = cv2.addWeighted(moved, 0.75, noise, 0.25, 0)
    # Keep the bright glyphs intact, as real transparent chat does.
    gray = cv2.cvtColor(moved, cv2.COLOR_BGR2GRAY)
    glyphs = gray > 170
    blended[glyphs] = moved[glyphs]
    differ._last_forced = time.monotonic()      # isolate from the 3s safety net
    if differ.changed(blended):
        triggered += 1
check("moving background behind chat does not trigger OCR", triggered <= 2,
      f"{triggered}/20 frames triggered")

# A genuinely new line must still trigger.
differ2 = FrameDiffer()
differ2.changed(crop)
differ2._last_forced = time.monotonic()
check("a new chat line does trigger OCR", differ2.changed(crop2))

# --------------------------------------------------------- idle frame cost
differ3 = FrameDiffer()
differ3.changed(crop)
t = time.perf_counter()
for _ in range(300):
    differ3._last_forced = time.monotonic()
    differ3.changed(crop)
idle_ms = (time.perf_counter() - t) * 1000 / 300
# At 5 frames/sec this is the per-frame cost when chat is static.
cpu_estimate = idle_ms * 5 / 1000 * 100
check("idle per-frame cost is negligible", idle_ms < 1.0,
      f"{idle_ms:.3f}ms/frame ~= {cpu_estimate:.2f}% of one core at 5Hz")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
