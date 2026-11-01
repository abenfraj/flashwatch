"""Replay a recorded game through Flashwatch's reading chain.

    .venv\\Scripts\\python.exe tools\\replay.py VIDEO --out DIR
        [--sidecar FILE] [--fps 5] [--start SECONDS] [--end SECONDS]
        [--layout team|bar|cards|list] [--theme clean|light|dark|neon]
        [--locale en_US|fr_FR] [--pixel-ratio 4] [--no-render] [--force]

Writes DIR/events.json (what was read and timed, in video seconds) and, unless
--no-render, DIR/overlay/ (the overlay drawn for every sampled frame, as
transparent PNGs, with overlay.json). The video generator runs this; see
docs/how-it-works.md, "Replay mode".

Exit codes: 0 done (including a video in which no chat was found), 2 a problem
with the input or the output folder that a person can fix, 1 anything else.
Nothing is ever shown on screen.
"""

from __future__ import annotations

import os
import sys

# Before anything imports Qt: replay is headless, and the offscreen platform
# has no fonts of its own.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import argparse
import shutil
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

NO_CHAT = ('no chat area found in this video; give "chat_region" in a sidecar '
           'to point at it')


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="replay", description="Replay a recorded game through Flashwatch.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--layout", choices=("team", "bar", "cards", "list"),
                        default="team")
    parser.add_argument("--theme", choices=("clean", "light", "dark", "neon"),
                        default="clean")
    parser.add_argument("--locale", choices=("en_US", "fr_FR"), default="en_US")
    parser.add_argument("--pixel-ratio", type=int, default=4,
                        help="overlay pixels per screen pixel (sharp insets)")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    from replay import ReplayInputError, load_sidecar

    try:
        if not args.video.is_file():
            raise ReplayInputError(f"video not found: {args.video}")
        if args.fps <= 0:
            raise ReplayInputError(f"--fps must be above 0, not {args.fps}")
        if args.pixel_ratio < 1:
            raise ReplayInputError(f"--pixel-ratio must be 1 or more, not "
                                   f"{args.pixel_ratio}")
        if args.end is not None and args.end <= args.start:
            raise ReplayInputError(f"--end ({args.end}) must come after "
                                   f"--start ({args.start})")
        events = args.out / "events.json"
        if events.exists() and not args.force:
            raise ReplayInputError(f"{events} already exists; pass --force to "
                                   f"replace this replay")
        sidecar = load_sidecar(args.sidecar) if args.sidecar else None
        if args.force:
            # A replay is replaced whole: frames left from a longer or denser
            # run would otherwise sit among the new ones.
            events.unlink(missing_ok=True)
            shutil.rmtree(args.out / "overlay", ignore_errors=True)

        from replay_render import run_replay

        summary = run_replay(args.video, args.out, fps=args.fps, start=args.start,
                             end=args.end, locale=args.locale, layout=args.layout,
                             theme=args.theme, render=not args.no_render,
                             sidecar=sidecar, pixel_ratio=args.pixel_ratio)
    except ReplayInputError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    except Exception:                                 # noqa: BLE001
        traceback.print_exc()
        return 1

    print(f"events: {summary['events']}")
    print(f"timers: {summary['timers']}")
    print(f"frames: {summary['frames']}")
    if summary["region"] is None:
        print(NO_CHAT)
    else:
        print("region: " + ",".join(str(v) for v in summary["region"]))
    print(f"output: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
