# -*- coding: utf-8 -*-
"""End-to-end check of the explore -> confirm -> read flow on synthetic frames.

Mirrors what CaptureWorker does:

    read the generous explore band
      -> keep rows whose text starts with a game clock
      -> derive the chat region from those rows
      -> read the narrowed region and parse events

The frames carry heavy high-frequency clutter on purpose. The previous
shape-based detector passed a clean-background version of this test and then
failed completely on real game footage, locking onto scenery in the middle of
the screen.
"""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\tests")

import cv2

import chat_detector
from riot_assets import RiotAssets
from message_parser import MessageParser, looks_like_chat_line
from ocr import OcrEngine
from synthetic_frames import make_frame

OUT = (r"C:\Users\ayoub\AppData\Local\Temp\claude"
       r"\C--Users-ayoub-dev-lol-auto-timers"
       r"\24acedf8-9d33-495b-ab44-b102dc631275\scratchpad")

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)
engine = OcrEngine()
engine.load()

CASES = [
    ("1080p", 1920, 1080, 1.0),
    ("1440p", 2560, 1440, 1.0),
    ("4K",    3840, 2160, 1.0),
    ("1080p-largeHUD", 1920, 1080, 1.35),
    ("1080p-smallHUD", 1920, 1080, 0.8),
    ("1600x900-windowed", 1600, 900, 1.0),
]

WANT = {("Ahri", "Flash"), ("Darius", "Teleport"),
        ("Viego", "Smite"), ("Lux", "Exhaust")}

for label, width, height, hud in CASES:
    print(f"--- {label} ({width}x{height}, HUD {hud}) ---")
    frame, text_bbox = make_frame(width, height, hud)
    window_rect = (0, 0, width, height)

    # --- phase 1: read the generous explore band -----------------------
    explore = chat_detector.explore_region(window_rect)
    band = frame[explore.y:explore.y + explore.height,
                 explore.x:explore.x + explore.width]
    engine.clear_cache()
    t = time.perf_counter()
    rows, _ = engine.read_rows(band,
                               max_rows=chat_detector.EXPLORE_MAX_ROWS,
                               left_fraction=chat_detector.EXPLORE_LEFT_FRACTION)
    explore_ms = (time.perf_counter() - t) * 1000

    chat_rows = [box for text, box in rows if looks_like_chat_line(text)]
    # One timestamped row is enough to locate chat; the explore pass is lossy by
    # design (it caps rows and filters by left edge to bound its cost) and only
    # has to find the area, not read every message.
    check(f"[{label}] chat lines found while exploring", len(chat_rows) >= 1,
          f"{len(chat_rows)} of {len(rows)} rows, {explore_ms:.0f}ms")

    # Clutter must not be mistaken for a chat line.
    bogus = [text for text, _ in rows
             if looks_like_chat_line(text) and "utilis" not in text.lower()
             and ":" not in text]
    check(f"[{label}] no clutter accepted as chat", not bogus, str(bogus[:3]))

    # --- phase 2: derive the region from those rows --------------------
    region = chat_detector.region_from_chat_rows(
        chat_rows, (explore.x, explore.y), window_rect)
    check(f"[{label}] region derived from timestamps", region is not None,
          region.describe() if region else "none")
    if region is None:
        continue
    check(f"[{label}] region is marked confirmed", region.confirmed)

    tx, ty, tw, th = text_bbox
    covers = (region.x <= tx + 8 and region.y <= ty + 8
              and region.x + region.width >= tx + tw - 8
              and region.y + region.height >= ty + th - 8)
    check(f"[{label}] region covers the chat text", covers,
          f"got {region.rect} vs text {text_bbox}")

    ratio = region.area() / float(width * height)
    check(f"[{label}] region stays reasonable", ratio < 0.30,
          f"{ratio*100:.1f}% of screen")

    # --- phase 3: read the narrowed region ----------------------------
    crop = frame[region.y:region.y + region.height,
                 region.x:region.x + region.width]
    engine.clear_cache()
    lines, ocr_ms = engine.read_lines(crop)
    events = parser.parse_lines(lines)
    got = {(e.champion_id, e.spell_key) for e in events}

    check(f"[{label}] all four casts parsed from narrowed region", got == WANT,
          f"ocr {ocr_ms:.0f}ms, got {sorted(got)}")
    check(f"[{label}] player chat line ignored",
          all(e.champion_id != "Jinx" for e in events))

    cv2.imwrite(os.path.join(OUT, f"frame_{label}.png"), frame)
    cv2.imwrite(os.path.join(OUT, f"crop_{label}.png"), crop)
    if got != WANT:
        print("     OCR lines from narrowed region:")
        for line in lines:
            print("       ", repr(line))
    print()

print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
