# -*- coding: utf-8 -*-
"""Cut the shipped logo files out of the source artwork.

Run by hand when the artwork changes, not at build time: the outputs are small,
they are committed, and a build that regenerated them would need Pillow and the
1.4 MB original in every clone. ::

    python tools/make_brand.py

The source is a square painting on a near-black ground with a wide margin. Three
things happen to it here, and each one is for a place it has to work in:

* **the margin comes off.** At 16 pixels in a system tray, a tenth of the icon
  spent on empty ground is a tenth of very little;
* **an alpha-cut variant** is written for the window headers, where the mark sits
  on the interface's own panel and a navy tile around it would read as a
  screenshot rather than as an icon;
* **the .ico carries every size Windows asks for.** Left to scale one bitmap
  itself, Windows picks the nearest and does it badly.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "maquette" / "assets"
OUT = ROOT / "resources" / "brand"
SITE = ROOT / "site"

# What is cropped off each edge, as a share of the source. Measured off the
# artwork rather than guessed: below this the glow around the stopwatch starts
# being clipped, which reads as a rendering fault at large sizes.
MARGIN = 0.055

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def newest_source() -> Path:
    """The most recent PNG in the maquette's asset folder.

    Named by whatever produced it -- the file that arrived is called
    ``ChatGPT Image 15 aout 2026, 21_03_33.png`` -- so it is found by date
    rather than by a name nobody will remember to keep.
    """
    candidates = sorted(SOURCE.glob("*.png"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(f"no artwork in {SOURCE}")
    return candidates[-1]


def trimmed(image: Image.Image) -> Image.Image:
    cut = round(min(image.size) * MARGIN)
    return image.crop((cut, cut, image.width - cut, image.height - cut))


def rounded(image: Image.Image, radius_share: float = 0.22) -> Image.Image:
    """The same picture with its corners cut, for use over the interface.

    A square tile is right on a taskbar, where every icon is one. It is wrong in
    a window header beside text, where the eye reads the tile before the mark.
    """
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, image.width - 1, image.height - 1],
        radius=round(image.width * radius_share), fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def main() -> int:
    source = newest_source()
    print(f"source: {source.name} ({source.stat().st_size // 1024} KB)")
    art = trimmed(Image.open(source).convert("RGBA"))

    OUT.mkdir(parents=True, exist_ok=True)
    square = art.resize((256, 256), Image.LANCZOS)
    square.save(OUT / "flashwatch-256.png", optimize=True)
    rounded(art).resize((256, 256), Image.LANCZOS).save(
        OUT / "flashwatch-round-256.png", optimize=True)
    art.resize((512, 512), Image.LANCZOS).save(OUT / "flashwatch-512.png",
                                               optimize=True)
    square.save(OUT / "flashwatch.ico",
                sizes=[(size, size) for size in ICO_SIZES])

    # The page is deployed from site/, so its copies live there rather than
    # being reached for across the repository. Two sizes, because the big one is
    # for the social card and the header would otherwise pull 300 KB down to
    # draw a 26 px mark.
    art.resize((512, 512), Image.LANCZOS).save(SITE / "logo.png", optimize=True)
    rounded(art).resize((96, 96), Image.LANCZOS).save(SITE / "logo-96.png",
                                                      optimize=True)
    square.save(SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    rounded(art).resize((180, 180), Image.LANCZOS).save(
        SITE / "apple-touch-icon.png", optimize=True)

    for path in sorted(OUT.glob("*")) + [SITE / "logo.png",
                                         SITE / "logo-96.png",
                                         SITE / "favicon.ico",
                                         SITE / "apple-touch-icon.png"]:
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
