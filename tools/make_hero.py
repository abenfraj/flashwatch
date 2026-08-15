# -*- coding: utf-8 -*-
"""Prepare the site's hero background from the key art.

Run by hand when the artwork changes::

    python tools/make_hero.py

The source is Riot's own League of Legends key art -- the whole cast charging at
the camera -- kept in ``design/maquette/assets/`` and **served from site/**
rather than hotlinked from the wallpaper site it was found on. Two reasons, and
neither is pedantry: a wallpaper host can move a file, rename it or refuse
requests that did not come from its own pages, any of which turns the first
screen of this site into a flat colour; and a page should not spend somebody
else's bandwidth on its own background.

The output is downscaled and compressed hard because the page blurs it: at
1600 px and quality 72 the file is a third of the original and the blur cannot
tell the difference.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "maquette" / "assets" / "lol-key-art.jpg"
OUT = ROOT / "site" / "hero-champions.jpg"

WIDTH = 1600
QUALITY = 72


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"no artwork at {SOURCE}")
    art = Image.open(SOURCE).convert("RGB")
    height = round(WIDTH * art.height / art.width)
    art.resize((WIDTH, height), Image.LANCZOS).save(
        OUT, quality=QUALITY, optimize=True, progressive=True)
    print(f"{SOURCE.name} {art.size[0]}x{art.size[1]} "
          f"({SOURCE.stat().st_size // 1024} KB)")
    print(f"  -> {OUT.relative_to(ROOT)} {WIDTH}x{height} "
          f"({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
