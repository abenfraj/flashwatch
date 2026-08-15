# -*- coding: utf-8 -*-
"""Draw the social card -- the picture Discord, Slack and the rest unfurl.

Run by hand when the card should change::

    python tools/make_og.py

Why a drawn card rather than the logo: an unfurl is the one place the product
gets a picture and a sentence and nothing else, and a square icon says only
"an application exists". This shows the bar doing its job, over the game, at the
size the card is actually displayed -- 1200 x 630, which is what every scraper
expects and what Discord fills edge to edge when the card is declared large.

Everything it draws already exists: the hero artwork, the shipped logo, the
champion and spell icons the program downloaded, and the countdown face the
overlay itself uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "design" / "maquette" / "assets" / "lol-key-art.jpg"
LOGO = ROOT / "resources" / "brand" / "flashwatch-round-256.png"
CACHE = ROOT / "assets" / "cache"
OUT = ROOT / "site" / "og-image.jpg"

SIZE = (1200, 630)
MULISH = ROOT / "resources" / "fonts" / "Mulish.ttf"
BAHNSCHRIFT = Path("C:/Windows/Fonts/bahnschrift.ttf")

# The ladder, from src/overlay.py's dark theme.
FAR, MID, NEAR, READY = ((94, 214, 138), (255, 199, 88),
                         (255, 96, 92), (126, 245, 166))
INK, DIM = (233, 238, 248), (169, 178, 200)

# Four cooldowns, one per rung, as the bar would have them.
ROW = [("Darius", "SummonerFlash", "3:41", FAR),
       ("Lux", "SummonerTeleport", "1:26", MID),
       ("Ahri", "SummonerFlash", "0:24", NEAR),
       ("Jinx", "SummonerHeal", "READY", READY)]


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def circle(image: Image.Image, size: int) -> Image.Image:
    out = image.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out.putalpha(mask)
    return out


def ground() -> Image.Image:
    """The key art, treated the way the site's first screen treats it."""
    art = Image.open(ART).convert("RGB")
    scale = max(SIZE[0] / art.width, SIZE[1] / art.height)
    art = art.resize((round(art.width * scale), round(art.height * scale)),
                     Image.LANCZOS)
    left = (art.width - SIZE[0]) // 2
    top = round((art.height - SIZE[1]) * 0.62)
    art = art.crop((left, top, left + SIZE[0], top + SIZE[1]))
    art = art.filter(ImageFilter.GaussianBlur(5))

    # Darkened, and darkest on the left where the words go.
    veil = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(veil)
    for x in range(SIZE[0]):
        share = x / SIZE[0]
        alpha = round(232 - 96 * min(1.0, share * 1.35))
        draw.line([(x, 0), (x, SIZE[1])], fill=(8, 11, 24, alpha))
    return Image.alpha_composite(art.convert("RGBA"), veil)


def main() -> int:
    for path in (ART, LOGO):
        if not path.exists():
            raise SystemExit(f"missing {path}")
    card = ground()
    draw = ImageDraw.Draw(card)

    logo = Image.open(LOGO).convert("RGBA").resize((104, 104), Image.LANCZOS)
    card.paste(logo, (72, 74), logo)
    draw.text((196, 84), "Flashwatch", font=font(MULISH, 60), fill=INK)
    draw.text((199, 152), "WINDOWS  ·  LEAGUE OF LEGENDS",
              font=font(MULISH, 20), fill=(196, 181, 253))

    draw.text((72, 246), "Enemy cooldowns,", font=font(MULISH, 66), fill=INK)
    draw.text((72, 322), "read off the screen.", font=font(MULISH, 66),
              fill=(196, 181, 253))
    draw.text((74, 424),
              "It reads the match chat and counts. No injection, no memory,",
              font=font(MULISH, 25), fill=DIM)
    draw.text((74, 462), "nothing to press during a game.",
              font=font(MULISH, 25), fill=DIM)

    # The bar, along the bottom: the product, not a description of it.
    bar = Image.new("RGBA", (1056, 108), (14, 16, 22, 150))
    card.paste(bar, (72, 500), bar)
    draw.rounded_rectangle([72, 500, 1128, 608], radius=12,
                           outline=(96, 110, 140, 120), width=1)
    draw.line([(112, 540), (1088, 540)], fill=(140, 152, 175, 120), width=2)
    draw.line([(1012, 540), (1088, 540)], fill=(52, 211, 153, 150), width=2)

    time_font = font(BAHNSCHRIFT, 30)
    for index, (champion, spell, text, colour) in enumerate(ROW):
        x = 150 + index * 236
        face = CACHE / "champions" / f"{champion}.png"
        icon = CACHE / "spells" / f"{spell}.png"
        if face.exists():
            portrait = circle(Image.open(face), 56)
            card.paste(portrait, (x - 28, 512), portrait)
        if icon.exists():
            badge = circle(Image.open(icon), 34)
            card.paste(badge, (x + 14, 534), badge)
        draw.text((x + 4, 576), text, font=time_font, fill=colour, anchor="mm")

    card.convert("RGB").save(OUT, quality=86, optimize=True, progressive=True)
    print(f"{OUT.relative_to(ROOT)}  {SIZE[0]}x{SIZE[1]}  "
          f"{OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
