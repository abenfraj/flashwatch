# -*- coding: utf-8 -*-
"""What a replay writes down, on footage that is not as clean as the fixture.

Real recordings are noisy: the same chat line is read a little differently from
one frame to the next, an uncertain line is confirmed by a later one, the chat
goes quiet for minutes, the frame rate varies. events.json is what the video
generator picks its moments from, so it has to list what the app *acted on* --
once per thing the overlay showed -- and keep its times on the footage's own.
Each check below was a reviewer's finding before it was a test.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import settings as settings_module
from chat_detector import ChatRegion
from message_parser import SpellEvent
from ocr import PROBE_CLOCK
from replay import CLOCK_BASE, ReplaySession, iter_video_frames, load_sidecar

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


WIDTH, HEIGHT = 1918, 1078
REGION = ChatRegion(387, 362, 805, 242, source="explore", confirmed=True)
BLANK = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
scratch = Path(tempfile.mkdtemp(prefix="fw-replay-records-"))


def event(champion, spell, game_time, *, kind="summoner", certain=True,
          raw=None, signature=None):
    stamp = f"{game_time // 60}:{game_time % 60:02d}"
    return SpellEvent(champion_id=champion, champion_name=champion, kind=kind,
                      spell_key=spell, spell_name=spell, game_time=game_time,
                      raw_line=raw or f"({stamp}) {champion} used {spell}",
                      signature=signature or f"{champion}|{spell}|{stamp}",
                      certain=certain)


def feed(session, t, events):
    """Hand the session one worker payload, as the worker would publish it."""
    session._results.put({"session_changed": False, "frame_counted": True,
                          "events": events, "status": None})
    session.step(t, BLANK)


def find_in_next_pass(session):
    """Make the worker's next pass find the chat, as a successful search does."""
    original = session.worker._iterate

    def finding():
        session.worker._iterate = original
        session.worker._region = REGION
        original()
    session.worker._iterate = finding


def found_session(name, *, found_at=1.0):
    """A session whose chat area is found by searching, at ``found_at``."""
    session = ReplaySession(scratch / name, width=WIDTH, height=HEIGHT)
    t = 0.0
    while t < found_at - 1e-9:                 # the priming frames, nothing read
        session.step(t, BLANK)
        t = round(t + 0.2, 6)
    find_in_next_pass(session)
    return session, t


# ---------------------------------------- one line, read many ways: one record
session, t = found_session("variants")
variants = [event("Yasuo", "Exhaust", 617),
            event("Yasuo", "Exhaust", 617, raw="(I0:17) Yasuo used Exhaust"),
            event("Yasuo", "Exhaust", 617, raw="(10:17) Yasuo used Exhaust .")]
feed(session, t, variants[:1])
feed(session, round(t + 0.2, 6), variants[1:])
feed(session, round(t + 0.4, 6), [event("Ahri", "R", 620, kind="ultimate")])
session.close()
yasuo = [r for r in session.records if r.champion_id == "Yasuo"]
check("OCR variants of one line are recorded once", len(yasuo) == 1,
      str([r.raw_line for r in yasuo]))
check("an ultimate the app does not time is not recorded",
      not any(r.kind == "ultimate" for r in session.records),
      str([(r.champion_id, r.kind) for r in session.records]))
check("each record carries the line's signature",
      yasuo and getattr(yasuo[0], "signature", None) == "Yasuo|Exhaust|10:17",
      str(getattr(yasuo[0], "signature", None) if yasuo else None))

# --------------------------------- an inferred timer confirmed later: one timer
session, t = found_session("reanchor")
feed(session, t, [event("Ahri", "Flash", 600, certain=False,
                        raw="(10:00) Ahri Flash", signature="Ahri|Flash|10:00?")])
feed(session, round(t + 2.0, 6), [event("Ahri", "Flash", 620)])
live = [timer for timer in session.timer_manager.snapshot()
        if (timer.champion_id, timer.spell_key) == ("Ahri", "Flash")]
session.close()
ahri = [r for r in session.timers if (r.champion_id, r.spell_key) == ("Ahri", "Flash")]
check("a re-anchored timer stays one timer record", len(ahri) == 1,
      str(ahri))
if ahri and live:
    check("its ready_t is the one the overlay counts down to",
          abs(ahri[0].ready_t - (live[0].started_at + live[0].duration
                                 - CLOCK_BASE)) < 0.01,
          f"{ahri[0].ready_t} vs {live[0].started_at + live[0].duration - CLOCK_BASE}")
    check("and it is no longer marked uncertain", ahri[0].uncertain is False,
          str(ahri[0]))

# ------------------------------- first_read: history around the first find only
session, t = found_session("first-read", found_at=1.0)
feed(session, t, [event("Karma", "Heal", 618)])                 # the find pass
feed(session, round(t + 0.4, 6), [event("Yasuo", "Exhaust", 617)])  # next passes
feed(session, round(t + 5.0, 6), [event("Ahri", "Flash", 630)])  # well after
records = {r.champion_id: r for r in session.records}
check("a line read in the pass that found the chat is first_read",
      records.get("Karma") is not None and records["Karma"].first_read,
      str(records.get("Karma")))
check("so is one parsed a pass or two later: it was on screen too",
      records.get("Yasuo") is not None and records["Yasuo"].first_read,
      str(records.get("Yasuo")))
check("a line read seconds later is fresh",
      records.get("Ahri") is not None and not records["Ahri"].first_read,
      str(records.get("Ahri")))

# The chat goes quiet, is dropped, and is found again: a ping that brings it
# back cannot predate the recording.
session.worker._region = None
session.step(round(t + 100.0, 6), BLANK)
find_in_next_pass(session)
feed(session, round(t + 100.2, 6), [event("Jinx", "Heal", 731)])
records = {r.champion_id: r for r in session.records}
check("a chat found again after a quiet stretch flags nothing as history",
      records.get("Jinx") is not None and not records["Jinx"].first_read,
      str(records.get("Jinx")))

# ...and the area found earlier is still what events.json reports.
session.worker._region = None
session.step(round(t + 200.0, 6), BLANK)
session.close()
session.write(scratch / "first-read" / "events.json", video=Path("x.mp4"),
              duration=200.0, fps=5.0)
written = json.loads((scratch / "first-read" / "events.json").read_text("utf-8"))
check("events.json keeps the chat area after the chat went quiet",
      written.get("region") == list(REGION.rect), str(written.get("region")))

# --------------------------------------------------- the clock in the corner
plain = ReplaySession(scratch / "probe", width=WIDTH, height=HEIGHT)
plain.close()
expected = settings_module.scaled_region("clock_region", (0, 0, WIDTH, HEIGHT))
probe = plain.worker._probes.get(PROBE_CLOCK)
check("without a feed, the app's clock area is read, scaled to the video",
      probe is not None and list(probe.rect) == expected,
      f"{probe.rect if probe is not None else None} vs {expected}")

sidecar = scratch / "feed.json"
sidecar.write_text(json.dumps({"game_clock_offset": 600, "enemies": [
    {"champion": name, "spells": ["Flash", "Ignite"], "level": 6, "items": [],
     "rune_trees": ["Precision", "Resolve"], "position": ""}
    for name in ("Ahri", "Darius", "Viego", "Jinx", "Thresh")]}), "utf-8")
fed = ReplaySession(scratch / "feed", width=WIDTH, height=HEIGHT,
                    sidecar=load_sidecar(sidecar))
fed.close()
check("with a feed giving the clock, the clock area is not read",
      not fed.worker.has_probe(PROBE_CLOCK))

# ------------------------------------------------ variable frame rate footage
ffmpeg = shutil.which("ffmpeg")
if ffmpeg is None:
    print("SKIP  variable frame rate: ffmpeg is not on PATH")
else:
    vfr = scratch / "vfr.mp4"
    # One red second at 30 fps, then three blue seconds at 10 fps: the average
    # rate (15 fps) puts the last red frame at 1.93 s if frames are counted.
    subprocess.run([ffmpeg, "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=red:s=64x48:r=30:d=1",
                    "-f", "lavfi", "-i", "color=blue:s=64x48:r=10:d=3",
                    "-filter_complex", "[0][1]concat=n=2:v=1",
                    "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(vfr)], check=True)
    samples = dict(iter_video_frames(vfr, fps=5.0))

    def colour(frame):
        b, g, r = frame.reshape(-1, 3).mean(axis=0)
        return "red" if r > b else "blue"

    check("on variable-rate footage, 0.8 s is still the red second",
          0.8 in samples and colour(samples[0.8]) == "red")
    check("and 1.4 s is already blue, as the footage shows",
          1.4 in samples and colour(samples[1.4]) == "blue",
          colour(samples[1.4]) if 1.4 in samples else "missing")
    check("the samples cover the whole four seconds",
          max(samples) >= 3.8, str(max(samples)))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
