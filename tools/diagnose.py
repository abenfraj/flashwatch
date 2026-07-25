# -*- coding: utf-8 -*-
"""Diagnostic capture. Run this during a game, then ping a summoner spell.

Answers the questions a log cannot:

  1. Does pinging a spell actually write a line into chat?
  2. If so, what is the exact wording?
  3. Where on screen is it?

It saves real screenshots plus every line the OCR can read from the lower-left
of the screen, so the detector can be tuned against actual pixels instead of
synthetic ones.

Usage
-----
    .venv\\Scripts\\python tools\\diagnose.py

Then, in a custom game:
    - make sure a summoner spell gets used
    - ping it
    - open the chat box too (Enter) so any message is clearly visible
    - let it run ~20 more seconds, then press Ctrl+C

Everything lands in assets/diagnostics/<timestamp>/.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import cv2
import mss
import numpy as np

import game_detector
from ocr import OcrEngine
from message_parser import MessageParser, TIMESTAMP_RE
from riot_assets import RiotAssets

# Generous lower-left area: everything chat could possibly occupy.
ZONE = {"left": 0.0, "right": 0.62, "top": 0.34, "bottom": 0.97}

POLL_SECONDS = 0.4
FULL_FRAME_EVERY = 5.0
MAX_FULL_FRAMES = 80


def zone_rect(window_rect):
    left, top, width, height = window_rect
    return {
        "left": left + int(width * ZONE["left"]),
        "top": top + int(height * ZONE["top"]),
        "width": int(width * (ZONE["right"] - ZONE["left"])),
        "height": int(height * (ZONE["bottom"] - ZONE["top"])),
    }


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "assets" / "diagnostics" / stamp
    (out / "frames").mkdir(parents=True, exist_ok=True)
    log_path = out / "ocr.log"
    log = log_path.open("w", encoding="utf-8")

    def say(message: str) -> None:
        print(message, flush=True)
        log.write(message + "\n")
        log.flush()

    say(f"Sortie : {out}")
    say("Chargement des donnees Riot et du moteur OCR...")

    assets = RiotAssets("fr_FR")
    assets.bootstrap()
    parser = MessageParser(assets)
    engine = OcrEngine()
    engine.load()
    say("Pret. En attente d'une partie...\n")
    say("Dans la partie : faites utiliser un sort, pingez-le, ouvrez le chat.")
    say("Ctrl+C pour arreter.\n")

    detector = game_detector.GameDetector()
    sct = mss.mss()

    seen: set[str] = set()
    frame_index = 0
    full_frames = 0
    last_full = 0.0
    last_state = None
    in_game_since = None

    try:
        while True:
            loop_started = time.monotonic()
            state, changed = detector.poll()

            if state.describe() != last_state:
                say(f"[{time.strftime('%H:%M:%S')}] etat : {state.describe()}")
                last_state = state.describe()

            if not state.in_game or state.window_rect is None:
                in_game_since = None
                time.sleep(1.0)
                continue

            if in_game_since is None:
                in_game_since = time.monotonic()
                say(f"[{time.strftime('%H:%M:%S')}] fenetre de jeu : "
                    f"{state.window_rect}")

            monitor = zone_rect(state.window_rect)
            raw = np.asarray(sct.grab(monitor))
            crop = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

            # Full screenshots, throttled, so the chat can be located by eye.
            now = time.monotonic()
            if now - last_full >= FULL_FRAME_EVERY and full_frames < MAX_FULL_FRAMES:
                full = np.asarray(sct.grab({
                    "left": state.window_rect[0], "top": state.window_rect[1],
                    "width": state.window_rect[2], "height": state.window_rect[3]}))
                cv2.imwrite(str(out / "frames" / f"full_{full_frames:03d}.png"),
                            cv2.cvtColor(full, cv2.COLOR_BGRA2BGR))
                full_frames += 1
                last_full = now

            lines, elapsed = engine.read_lines(crop)
            fresh = [line for line in lines if line not in seen]
            seen.update(lines)

            if fresh:
                frame_index += 1
                # Keep the crop that produced new text: these are the pixels
                # that matter for tuning detection.
                cv2.imwrite(str(out / "frames" / f"zone_{frame_index:03d}.png"), crop)
                say(f"\n[{time.strftime('%H:%M:%S')}] "
                    f"{len(fresh)} nouvelle(s) ligne(s), OCR {elapsed:.0f}ms "
                    f"-> zone_{frame_index:03d}.png")
                for line in fresh:
                    marks = []
                    if TIMESTAMP_RE.search(line):
                        marks.append("HORODATAGE")
                    event = parser.parse_line(line)
                    if event is not None:
                        marks.append(f"INTERPRETE={event.champion_id}/"
                                     f"{event.spell_key}")
                    suffix = ("   <<< " + " ".join(marks)) if marks else ""
                    say(f"    {line!r}{suffix}")

            time.sleep(max(0.0, POLL_SECONDS - (time.monotonic() - loop_started)))

    except KeyboardInterrupt:
        say("\nArret demande.")
    finally:
        say(f"\n{len(seen)} lignes distinctes lues au total.")
        say(f"Captures : {out / 'frames'}")
        say(f"Journal  : {log_path}")
        log.close()
        sct.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
