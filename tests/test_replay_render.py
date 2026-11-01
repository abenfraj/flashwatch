# -*- coding: utf-8 -*-
"""Replay: the overlay drawn for every sampled second of a recording.

The generator composites these frames over the footage, so three things matter
and are checked here: every frame has the same size (an overlay that changed size
would jump around in the video), nothing is drawn before there is anything to
show (the frame is transparent, not a dark box), and once the pings are read the
timers really are on the frame.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import inspect
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from replay import iter_video_frames
from replay_fixture import make_fixture_video
from replay_render import run_replay

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


check("frames are streamed, never all held at once",
      inspect.isgeneratorfunction(iter_video_frames))

scratch = Path(tempfile.mkdtemp(prefix="fw-replay-render-"))
video = make_fixture_video(scratch / "pings.mp4")
out = scratch / "out"
summary = run_replay(video, out, fps=5.0)
check("the summary counts every sampled frame", summary.get("frames") == 30,
      str(summary))
check("and the two pings", summary.get("events", 0) >= 2, str(summary))

frames = sorted((out / "overlay").glob("*.png"))
manifest = json.loads((out / "overlay" / "overlay.json").read_text("utf-8"))
check("one PNG per sampled frame", len(frames) == 30, str(len(frames)))
check("the manifest agrees", manifest.get("count") == 30, str(manifest))
check("the manifest says where the overlay is anchored",
      manifest.get("anchor") == "top-right" and manifest.get("layout") == "team",
      str(manifest))


def read(path: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)


images = [read(path) for path in frames]
sizes = {image.shape[:2] for image in images}
check("every frame has the same size", len(sizes) == 1, str(sizes))
check("and it is the size in the manifest",
      sizes == {(manifest.get("height"), manifest.get("width"))}, str(sizes))
check("frames keep their alpha channel",
      all(image.ndim == 3 and image.shape[2] == 4 for image in images))
check("before anything is read, the frame is fully transparent",
      images and int(images[0][:, :, 3].max()) == 0,
      str(int(images[0][:, :, 3].max()) if images else None))
drawn = int((images[-1][:, :, 3] > 128).sum()) if images else 0
check("once the pings are read, the timers are on the frame", drawn > 200,
      f"{drawn} opaque pixels")
check("events.json is written beside the frames", (out / "events.json").is_file())

# Drawn at a multiple of the screen's pixels: the generator enlarges the overlay
# into an inset many times its on-screen size, and 1x frames would blur.
ratio = manifest.get("pixel_ratio")
check("frames are drawn at the manifest's pixel ratio, 4 by default",
      ratio == 4 and manifest.get("width") == 4 * manifest.get("logical_width")
      and manifest.get("height") == 4 * manifest.get("logical_height"),
      str(manifest))

# The other displays are sized for the video's screen, as place_default sizes
# them for the player's, and the same on every run.
from overlay import LAYOUT_DEFAULTS, LAYOUT_BAR, MIN_WIDTH
bar_out = scratch / "bar"
run_replay(video, bar_out, fps=5.0, end=1.0, layout="bar")
bar = json.loads((bar_out / "overlay" / "overlay.json").read_text("utf-8"))
expected_width = max(MIN_WIDTH, int(1918 * LAYOUT_DEFAULTS[LAYOUT_BAR]["fraction"]))
check("the bar is as wide as it would be on a screen the video's size",
      bar.get("logical_width") == expected_width,
      f"{bar.get('logical_width')} vs {expected_width}")
for stale in (bar_out / "overlay").glob("*"):
    stale.unlink()
(bar_out / "events.json").unlink()
run_replay(video, bar_out, fps=5.0, end=1.0, layout="bar")
again = json.loads((bar_out / "overlay" / "overlay.json").read_text("utf-8"))
check("and the same size when replayed again into the same folder",
      (again.get("width"), again.get("height")) == (bar.get("width"), bar.get("height")),
      f"{again} vs {bar}")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
