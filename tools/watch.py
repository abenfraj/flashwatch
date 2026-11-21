"""Run Flashwatch on a stream or a recorded game playing full screen in a window.

    .venv\\Scripts\\python.exe tools\\watch.py [--title Twitch] [--data DIR]

The window whose title contains ``--title`` stands in for League's: the chat is
found, read and timed exactly as in a game, and the overlay is drawn over it.
Development only. It keeps its own settings, log and trace under ``--data``
(private/watch by default), so the chat area it finds on a streamer's layout
never replaces the one placed for real games; it claims an instance token of its
own, so it runs beside the everyday copy; and it never touches the startup
entry. The game's data feed is off, since a stream has none to offer.

Every line the OCR reads, and what became of it, goes to DATA/assets/trace.log.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# What a watching copy needs to differ on. Everything else is the default.
WATCH_SETTINGS = {
    "onboarding_done": True,
    "open_window_on_launch": False,
    "update_check_enabled": False,
    # No game, so no feed: waiting for one would hold the overlay back.
    "live_client": False,
    # Typing to whoever is watching means the stream is not in front.
    "hide_when_unfocused": False,
    "chat_region_locked": False,
    "tray_hint_shown": True,
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="watch")
    parser.add_argument("--title", default="Twitch")
    parser.add_argument("--data", type=Path, default=ROOT / "private" / "watch")
    args = parser.parse_args()

    data = args.data.resolve()
    assets = data / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    config = assets / "settings.json"
    if not config.exists():
        # Copied from the everyday settings for the look of the overlay, then
        # overridden where a stream differs from a game.
        everyday = ROOT / "assets" / "settings.json"
        values = (json.loads(everyday.read_text("utf-8"))
                  if everyday.exists() else {})
        for key in ("chat_region", "chat_region_window", "clock_region",
                    "scoreboard_region", "loading_region"):
            values.pop(key, None)
        values.update(WATCH_SETTINGS)
        config.write_text(json.dumps(values, indent=2), "utf-8")
    cache = ROOT / "assets" / "cache"
    if cache.is_dir() and not (assets / "cache").exists():
        # Riot's icons, so they are not fetched a second time.
        shutil.copytree(cache, assets / "cache")

    os.environ["FLASHWATCH_WATCH"] = args.title
    os.environ["FLASHWATCH_DATA"] = str(data)
    os.environ["FLASHWATCH_INSTANCE"] = "Flashwatch.watch"
    sys.path.insert(0, str(ROOT / "src"))
    sys.argv = [str(ROOT / "src" / "main.py")]
    import main as app
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
