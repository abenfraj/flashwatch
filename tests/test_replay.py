# -*- coding: utf-8 -*-
"""Replay: the app's own reading chain, run on a recorded game.

What the video generator shows has to be what Flashwatch would have shown. So
replay does not reimplement anything: it feeds video frames to the capture worker
the app runs and forwards its results to the same timer manager. These checks
hold it to that -- the two pings in the sample are found once each when they
appear mid-recording, and *not* timed when they are on screen from the first
frame, because the priming pass treats those as history in a game too.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import json
import tempfile
from pathlib import Path

import replay
import settings as settings_module
from replay import ReplayInputError, ReplaySession, iter_video_frames, video_info
from replay_fixture import make_fixture_video

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


scratch = Path(tempfile.mkdtemp(prefix="fw-replay-"))
real_settings = Path(settings_module.CONFIG_PATH)
real_mtime = real_settings.stat().st_mtime if real_settings.exists() else None

# ------------------------------------------------------------------ frames
video = make_fixture_video(scratch / "pings.mp4")
samples = list(iter_video_frames(video, fps=5.0))
times = [t for t, _ in samples]
check("6 s at 5 fps is 30 samples", len(samples) == 30, str(len(samples)))
check("sampled every 200 ms from zero",
      all(abs(t - i * 0.2) < 0.001 for i, t in enumerate(times)),
      str(times[:4] + times[-2:]))
check("each sample is a full frame",
      all(frame.shape == (1078, 1918, 3) for _, frame in samples),
      str(samples[0][1].shape if samples else None))
check("video_info reads the size, rate and length",
      video_info(video)[:2] == (1918, 1078) and video_info(video)[2] == 30
      and abs(video_info(video)[3] - 6.0) < 0.05, str(video_info(video)))

try:
    list(iter_video_frames(scratch / "missing.mp4"))
    check("a missing video is refused", False)
except ReplayInputError as exc:
    check("a missing video is refused", "missing.mp4" in str(exc), str(exc))


def run(path: Path, out: Path) -> ReplaySession:
    width, height, _, _ = video_info(path)
    session = ReplaySession(out, width=width, height=height)
    try:
        for t, frame in iter_video_frames(path, fps=5.0):
            session.step(t, frame)
    finally:
        session.close()
    return session


# ----------------------------------------------- pings that appear mid-game
session = run(video, scratch / "out")
found = [(r.champion_id, r.spell_key) for r in session.records]
for champion, spell in (("Yasuo", "Exhaust"), ("Karma", "Heal")):
    mine = [r for r in session.records
            if (r.champion_id, r.spell_key) == (champion, spell)]
    check(f"{champion} {spell} is read once", len(mine) == 1, str(found))
    if mine:
        check(f"{champion} {spell} is read when it appears, not before",
              mine[0].t >= 2.0, str(mine[0].t))
        timer = [r for r in session.timers
                 if (r.champion_id, r.spell_key) == (champion, spell)]
        check(f"{champion} {spell} starts a timer that ends later",
              len(timer) == 1 and timer[0].ready_t > mine[0].t,
              str(timer))

events_path = scratch / "out" / "events.json"
session.write(events_path, video=video, duration=6.0, fps=5.0)
data = json.loads(events_path.read_text("utf-8"))
check("events.json says where the chat was",
      isinstance(data.get("region"), list) and len(data["region"]) == 4
      and all(isinstance(v, int) for v in data["region"]), str(data.get("region")))
check("events.json carries the events and the timers",
      len(data.get("events", [])) == len(session.records)
      and len(data.get("timers", [])) == len(session.timers))
check("no roster came from a sidecar", data.get("roster_from_sidecar") is False)

# A replay times what the app would time. Neither fixture shows any chat before
# the two pings, so the chat area is only found in the very pass that reads them
# -- after the priming frames, which count from the start of the session, exactly
# as they do when the app is launched mid-game. Whether such a line is fresh or
# history cannot be told from the screen, so it is flagged for the generator.
check("lines read in the pass that found the chat are flagged first_read",
      session.records and all(r.first_read for r in session.records)
      and all(r.first_read for r in session.timers), str(session.records))
check("events.json carries the flag",
      all("first_read" in e for e in data.get("events", [])))

# -------------------------------------------- pings on screen from the start
still = make_fixture_video(scratch / "still.mp4", still_from_start=True)
primed = run(still, scratch / "out-still")
check("lines on screen from the first frame are flagged as possible history",
      primed.records and all(r.first_read for r in primed.records),
      str(primed.records))

# ------------------------------------------------------------- side effects
check("replay keeps its settings in the output folder",
      (scratch / "out" / "settings.json").is_file())
check("the user's own settings file is untouched",
      (real_settings.stat().st_mtime if real_settings.exists() else None)
      == real_mtime)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
