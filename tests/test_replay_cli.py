# -*- coding: utf-8 -*-
"""The replay command, as the video generator calls it.

The generator runs ``tools/replay.py`` as a separate process and reads its exit
code, so the contract is checked from the outside: 0 with a summary when it
worked (including when the video simply has no chat), 2 with the file named when
the input is wrong or a finished replay would be overwritten, and never a crash
for something a person can fix.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import json
import subprocess
import tempfile
from pathlib import Path

from replay_fixture import make_fixture_video

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


TOOL = Path(_bootstrap.ROOT) / "tools" / "replay.py"
# The venv's own launcher when there is one: on Windows sys.executable can name
# the base interpreter, which does not see the venv's packages.
VENV_PYTHON = Path(sys.prefix) / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable
scratch = Path(tempfile.mkdtemp(prefix="fw-replay-cli-"))
pings = make_fixture_video(scratch / "pings.mp4")
blind = make_fixture_video(scratch / "blind.mp4", blurred_seconds=3.0,
                           clear_seconds=0.0)


def replay(*args) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)          # the tool must set it itself
    return subprocess.run([PYTHON, str(TOOL), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)


out = scratch / "out"
first = replay(pings, "--out", out, "--no-render")
check("a replay of the fixture exits 0", first.returncode == 0,
      first.stderr[-400:])
check("and says it read the two pings", "events: 2" in first.stdout,
      first.stdout)
check("events.json is written", (out / "events.json").is_file())

again = replay(pings, "--out", out, "--no-render")
check("replaying into a finished output is refused with exit 2",
      again.returncode == 2, f"{again.returncode} {again.stderr}")
check("and the message says how to overwrite", "--force" in again.stderr,
      again.stderr)
forced = replay(pings, "--out", out, "--no-render", "--force")
check("--force overwrites it", forced.returncode == 0, forced.stderr[-400:])

drawn = scratch / "drawn"
render = replay(pings, "--out", drawn)
manifest = drawn / "overlay" / "overlay.json"
check("without --no-render the overlay frames are drawn",
      render.returncode == 0 and manifest.is_file()
      and json.loads(manifest.read_text("utf-8")).get("count") == 30,
      render.stderr[-400:])

no_chat = replay(blind, "--out", scratch / "blind", "--no-render")
check("a video with no chat still exits 0", no_chat.returncode == 0,
      no_chat.stderr[-400:])
check("and says no chat area was found",
      'no chat area found in this video; give "chat_region" in a sidecar'
      in no_chat.stdout, no_chat.stdout)
events = json.loads((scratch / "blind" / "events.json").read_text("utf-8"))
check("with an empty event list", events.get("events") == [], str(events))

missing = replay(scratch / "nope.mp4", "--out", scratch / "nope")
check("a missing video exits 2 naming it",
      missing.returncode == 2 and "nope.mp4" in missing.stderr,
      f"{missing.returncode} {missing.stderr}")

bad = scratch / "bad.json"
bad.write_text(json.dumps({"locale": "de_DE"}), "utf-8")
refused = replay(pings, "--out", scratch / "bad", "--sidecar", bad)
check("a malformed sidecar exits 2 naming the field",
      refused.returncode == 2 and "locale" in refused.stderr,
      f"{refused.returncode} {refused.stderr}")

region = json.loads((out / "events.json").read_text("utf-8"))["region"]
good = scratch / "good.json"
good.write_text(json.dumps({"chat_region": region}), "utf-8")
sided = replay(pings, "--out", scratch / "sided", "--no-render", "--sidecar", good)
check("a sidecar is passed through to the replay",
      sided.returncode == 0
      and f"region: {','.join(map(str, region))}" in sided.stdout,
      sided.stdout + sided.stderr[-400:])

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
