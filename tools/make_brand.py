# -*- coding: utf-8 -*-
"""Cut the shipped logo files out of the source artwork.

Run by hand when the artwork changes, not at build time: the outputs are small,
they are committed, and a build that regenerated them would need Pillow and the
1 MB original in every clone. ::

    python tools/make_brand.py

The source is ``design/brand/flashwatch-logo.png``: a square painting of the
mark on the brand's near-black ground. It is named rather than found. This used
to take the most recent PNG in the maquette's asset folder, which worked exactly
until a second image was dropped in there -- a folder sorted by modification
time is not a decision about which picture is the logo.

It lives under ``design/`` and not beside its own outputs, because ``build.py``
bundles every PNG in ``resources/brand/`` into the executable: the 1 MB painting
nothing reads at runtime would be a megabyte in everyone's download.

Three things happen to it here, and each one is for a place it has to work in:

* **the frame comes off.** The artwork is a mark floating in a lot of ground,
  and the ground is not the logo: at 16 pixels in a system tray, half an icon
  spent on empty navy is half of very little. So the ink is *measured* and the
  crop follows it, rather than a fixed share being taken off each edge -- which
  is what the previous artwork got, and what left this one a speck in a square;
* **an alpha-cut variant** is written for the window headers and the page, where
  the mark sits on a surface of its own and square corners would read as a
  screenshot rather than as an icon;
* **the .ico carries every size Windows asks for.** Left to scale one bitmap
  itself, Windows picks the nearest and does it badly.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "brand" / "flashwatch-logo.png"
OUT = ROOT / "resources" / "brand"
SITE = ROOT / "site"

# The ground the mark is painted on, sampled from the artwork's corners. Used to
# find the ink, not to repaint anything: every output keeps the ground it came
# with, so the tile in a taskbar is the picture the designer drew.
GROUND = (0, 6, 27)

# Anything this far from the ground counts as ink. Low, so the glow around the
# blue arc is measured as part of the mark: cropping to the hard edges alone
# clips the halo, which reads as a rendering fault at large sizes.
INK = 10

# How much ground is kept around the ink, as a share of the mark's own size. An
# icon needs to breathe or it looks like it has burst its tile; much more than
# this and it goes back to being a speck.
PAD = 0.16

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def ink_box(image: Image.Image) -> tuple[int, int, int, int]:
    """The smallest square, centred on the mark, that holds all of it.

    Square rather than tight: every output is square, and a rectangular crop
    stretched to fit would make the stopwatch an oval. Centred on the *ink*
    rather than on the frame, because the mark is not in the middle of its own
    painting -- it sits high and to the left, and cropping around the frame's
    centre would push it off its tile.
    """
    ground = Image.new("RGB", image.size, GROUND)
    lit = ImageChops.difference(image.convert("RGB"), ground).convert("L")
    box = lit.point(lambda value: 255 if value > INK else 0).getbbox()
    if box is None:                       # a blank painting; nothing to measure
        return (0, 0, image.width, image.height)
    left, top, right, bottom = box
    half = max(right - left, bottom - top) * (1 + PAD) / 2
    x, y = (left + right) / 2, (top + bottom) / 2
    # Kept inside the painting: past its edge there is no ground to show, and
    # Pillow would hand back a transparent border instead.
    half = min(half, x, y, image.width - x, image.height - y)
    return (round(x - half), round(y - half), round(x + half), round(y + half))


def trimmed(image: Image.Image) -> Image.Image:
    return image.crop(ink_box(image))


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
    if not SOURCE.exists():
        raise SystemExit(f"no artwork at {SOURCE.relative_to(ROOT)}")
    print(f"source: {SOURCE.name} ({SOURCE.stat().st_size // 1024} KB)")
    art = trimmed(Image.open(SOURCE).convert("RGBA"))
    print(f"cropped to the mark: {art.width}x{art.height}")

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
