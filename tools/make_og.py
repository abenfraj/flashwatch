# -*- coding: utf-8 -*-
"""Draw the social card -- the picture Discord, Slack and the rest unfurl.

Run by hand when the card should change::

    python tools/make_og.py

Why a drawn card rather than the logo: an unfurl is the one place the product
gets a picture and a sentence and nothing else, and a square icon says only
"an application exists". This shows the overlay doing its job, over the game,
at the size the card is actually displayed -- 1200 x 630, which is what every
scraper expects and what Discord fills edge to edge when the card is declared
large.

What it shows is the default display, the team display, painted the way
src/overlay.py paints it (``_paint_team``, ``_paint_team_spell``,
``team_timer_rect``, with ``team_timer_below`` on) and the way the page's hero
shows it: each enemy's round portrait, then their spells as rounded squares. A
spell that is down is greyed, lightly dimmed, and swept by a dark wedge over
the part of its cooldown still to run, with the countdown astride its bottom
edge -- white, amber under fifteen seconds. A spell just back wears a green
ring. An enemy with nothing down is drawn faint. Pillow rather than Qt, so the
card needs neither a screen nor the program's state; the constants below keep
the overlay's names, so a change there can be found here.

Everything it draws already exists: the hero artwork, the shipped logo, and the
champion and spell icons the program downloaded.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cooldowns import format_short  # noqa: E402  -- the overlay's own wording

ART = ROOT / "site" / "hero-champions.jpg"
LOGO = ROOT / "resources" / "brand" / "flashwatch-round-256.png"
CACHE = ROOT / "assets" / "cache"
OUT = ROOT / "site" / "og-image.jpg"

SIZE = (1200, 630)
MULISH = ROOT / "resources" / "fonts" / "Mulish.ttf"
BAHNSCHRIFT = Path("C:/Windows/Fonts/bahnschrift.ttf")

INK, DIM = (233, 238, 248), (169, 178, 200)

# The team display at scale 1, from src/overlay.py.
TEAM_PORTRAIT = 32
TEAM_SPELL = 30
TEAM_GAP = 3
TEAM_SPLIT = 5
TEAM_ROW_GAP = 5
TEAM_TIMER_STRIP = 14
TEAM_SOON_SECONDS = 15.0
TEAM_TEXT = (246, 248, 252, 255)
TEAM_TEXT_SOON = (255, 203, 87, 255)
TEAM_TEXT_HALO = (0, 0, 0, 235)
TEAM_COOLDOWN_SHADE_BELOW = (4, 6, 10, 120)
TEAM_COOLDOWN_DIM_BELOW = (4, 6, 10, 55)
TEAM_TEXT_WIDTH = 0.92
TEAM_TEXT_HEIGHT = 0.56
READY = (132, 250, 178, 255)      # THEMES["clean"]["ready"]: the ring
REST_OPACITY = 0.45               # the "team_rest_opacity" default
NUMBER_STYLE = "Bold SemiCondensed"   # the first of _TEAM_FACES

# The display's scale on the card. Discord shows a large card about a third of
# this wide, so a 30 px spell icon drawn at 75 px here comes out near 25 px on
# the unfurl: about the size of the real thing in a game.
SCALE = 2.5
# Pillow's shapes have no antialiasing of their own, so the display is drawn
# this many times over and scaled down.
SUPERSAMPLE = 4
# Room round the display on its sheet, for the ring, the strips and the halo.
SHEET_MARGIN = 10

# One moment of a game, the page hero's five enemies, chosen so every state the
# display has shows once: a Flash with minutes to go, a Smite in its last
# fifteen seconds (amber), an enemy with nothing down (faint), a Flash just
# back (the ring) and an Exhaust halfway through. Each spell is (icon, seconds
# left, full cooldown): None never cast, 0 back and still inside the READY
# linger. Summoner spells only -- no ultimates on the picture.
TEAM = [
    ("Darius", [("SummonerFlash", 192, 300), ("SummonerTeleport", None, 300)]),
    ("Viego", [("SummonerFlash", None, 300), ("SummonerSmite", 12, 90)]),
    ("Ahri", [("SummonerFlash", None, 300), ("SummonerDot", None, 180)]),
    ("Jinx", [("SummonerFlash", 0, 300), ("SummonerHeal", None, 240)]),
    ("Thresh", [("SummonerFlash", None, 300), ("SummonerExhaust", 107, 240)]),
]


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def number_font(pixels: int) -> ImageFont.FreeTypeFont:
    """team_number_font: Bahnschrift's narrow heavy cut, ``pixels`` to the em."""
    if not BAHNSCHRIFT.exists():
        return ImageFont.load_default(max(6, pixels))
    face = ImageFont.truetype(str(BAHNSCHRIFT), max(6, pixels))
    try:
        face.set_variation_by_name(NUMBER_STYLE)
    except (OSError, ValueError):
        pass
    return face


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


class Sheet:
    """A transparent sheet for the display, in card pixels, drawn oversampled.

    Coordinates are the card's, from the display's top-left corner; every
    shape is laid on a fresh layer and composited, because drawing straight
    onto an RGBA image replaces its pixels instead of blending into them.
    """

    def __init__(self, width: float, height: float) -> None:
        self.k = SUPERSAMPLE
        self.margin = SHEET_MARGIN
        self.size = (round((width + 2 * self.margin) * self.k),
                     round((height + 2 * self.margin) * self.k))
        self.image = Image.new("RGBA", self.size, (0, 0, 0, 0))

    def px(self, value: float) -> int:
        return round(value * self.k)

    def box(self, x0: float, y0: float, x1: float, y1: float) -> list[int]:
        m = self.margin
        return [self.px(x0 + m), self.px(y0 + m),
                self.px(x1 + m) - 1, self.px(y1 + m) - 1]

    def layer(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        top = Image.new("RGBA", self.size, (0, 0, 0, 0))
        return top, ImageDraw.Draw(top)

    def rounded_mask(self, rect: tuple, radius: float) -> Image.Image:
        mask = Image.new("L", self.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(self.box(*rect),
                                               radius=self.px(radius), fill=255)
        return mask

    def icon(self, path: Path, rect: tuple, *, grey: bool = False,
             radius: float | None = None, round_: bool = False) -> Image.Image:
        """The icon at ``path`` cut to ``rect``, on a layer of its own."""
        box = self.box(*rect)
        side = box[2] - box[0] + 1
        art = Image.open(path).convert("RGBA").resize((side, side), Image.LANCZOS)
        if grey:
            # As the game shows an ability on cooldown; the icons are opaque.
            art = art.convert("L").convert("RGBA")
        cut = Image.new("L", (side, side), 0)
        if round_:
            ImageDraw.Draw(cut).ellipse([0, 0, side - 1, side - 1], fill=255)
        else:
            ImageDraw.Draw(cut).rounded_rectangle(
                [0, 0, side - 1, side - 1], radius=self.px(radius or 0), fill=255)
        art.putalpha(ImageChops.multiply(art.getchannel("A"), cut))
        top, _draw = self.layer()
        top.alpha_composite(art, (box[0], box[1]))
        return top

    def finish(self) -> Image.Image:
        width = round(self.size[0] / self.k)
        height = round(self.size[1] / self.k)
        return self.image.resize((width, height), Image.LANCZOS)


def stroke_box(rect: tuple, inset: float, width: float) -> tuple:
    """The box Pillow needs to centre a ``width`` line ``inset`` inside ``rect``.

    Qt strokes a path down its middle; Pillow draws an outline inwards from its
    box. So the box is the path pushed out by half the line.
    """
    grow = width / 2.0 - inset
    return (rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow)


def paint_number(sheet: Sheet, member: Image.Image, strip: tuple, text: str,
                 colour: tuple, max_height: float, scale: float) -> None:
    """_paint_icon_number: as large as fits across the strip, outlined."""
    k = sheet.k
    room = (strip[2] - strip[0]) * TEAM_TEXT_WIDTH * k
    height = max_height
    face = number_font(round(height * k))
    while face.getlength(text) > room and height > 6:
        height -= 0.5
        face = number_font(round(height * k))
    width = face.getlength(text)
    cap = -face.getbbox("H", anchor="ls")[1]
    centre_x = sheet.px((strip[0] + strip[2]) / 2.0 + sheet.margin)
    centre_y = sheet.px((strip[1] + strip[3]) / 2.0 + sheet.margin)
    top, draw = sheet.layer()
    # The halo first and the figures over it, as the overlay strokes the
    # glyphs' path and then fills it.
    draw.text((centre_x - width / 2.0, centre_y + cap / 2.0), text, font=face,
              fill=colour, anchor="ls",
              stroke_width=sheet.px(max(1.0, 1.3 * scale)),
              stroke_fill=TEAM_TEXT_HALO)
    member.alpha_composite(top)


def paint_spell(sheet: Sheet, member: Image.Image, rect: tuple, spell: str,
                left: float | None, full: float, scale: float,
                gap: float, strip: float) -> None:
    """_paint_team_spell, with the countdown below."""
    corner = max(2.0, 4.0 * scale)
    down = left is not None and left > 0
    path = CACHE / "spells" / f"{spell}.png"
    if path.exists():
        member.alpha_composite(sheet.icon(path, rect, grey=down, radius=corner))

    if down:
        top, draw = sheet.layer()
        draw.rounded_rectangle(sheet.box(*rect), radius=sheet.px(corner),
                               fill=TEAM_COOLDOWN_DIM_BELOW)
        member.alpha_composite(top)

        # The part still to run: from the hand, clockwise round to twelve.
        progress = max(0.0, min(1.0, 1.0 - left / full))
        reach = (rect[2] - rect[0]) * 0.5
        top, draw = sheet.layer()
        draw.pieslice(sheet.box(rect[0] - reach, rect[1] - reach,
                                rect[2] + reach, rect[3] + reach),
                      start=-90.0 + 360.0 * progress, end=270.0,
                      fill=TEAM_COOLDOWN_SHADE_BELOW)
        top.putalpha(ImageChops.multiply(top.getchannel("A"),
                                         sheet.rounded_mask(rect, corner)))
        member.alpha_composite(top)
    elif left is not None:
        # Back up, and still inside the READY linger: the green ring.
        width = max(1.5, 2.0 * scale)
        ring = stroke_box(rect, -1.0, width)
        top, draw = sheet.layer()
        draw.rounded_rectangle(sheet.box(*ring),
                               radius=sheet.px(corner + 1.0 + width / 2.0),
                               outline=READY, width=sheet.px(width))
        member.alpha_composite(top)

    # The edge that keeps an icon an icon over any background.
    width = max(1.0, 1.0 * scale)
    top, draw = sheet.layer()
    draw.rounded_rectangle(sheet.box(*stroke_box(rect, 0.5, width)),
                           radius=sheet.px(corner), outline=(0, 0, 0, 160),
                           width=sheet.px(width))
    member.alpha_composite(top)

    if down:
        # team_timer_rect: centred on the bottom edge, the icon's width plus
        # half the gap on either side.
        band = (rect[0] - gap / 2.0, rect[3] - strip / 2.0,
                rect[2] + gap / 2.0, rect[3] + strip / 2.0)
        colour = TEAM_TEXT_SOON if left <= TEAM_SOON_SECONDS else TEAM_TEXT
        paint_number(sheet, member, band, format_short(left), colour,
                     (rect[2] - rect[0]) * TEAM_TEXT_HEIGHT, scale)


def team_display(scale: float) -> tuple[Image.Image, float, float]:
    """The display at ``scale``: its sheet, and the width and height it fills.

    The geometry is team_cells' for the vertical layout, with the strip under
    the spells counted into each enemy's block as _team_block counts it.
    """
    portrait = round(TEAM_PORTRAIT * scale)
    spell = round(TEAM_SPELL * scale)
    gap = max(1, round(TEAM_GAP * scale))
    split = max(2, round(TEAM_SPLIT * scale))
    row_gap = max(2, round(TEAM_ROW_GAP * scale))
    strip = round(TEAM_TIMER_STRIP * scale)
    under = round(TEAM_TIMER_STRIP * scale / 2.0) + max(1, round(scale))
    slots = max(len(spells) for _champion, spells in TEAM)
    base = max(portrait, spell)
    block_h = round(max(base, (base - spell) / 2.0 + spell + under))
    width = portrait + split + slots * spell + (slots - 1) * gap
    height = len(TEAM) * block_h + (len(TEAM) - 1) * row_gap

    sheet = Sheet(width, height)
    for index, (champion, spells) in enumerate(TEAM):
        member, draw = sheet.layer()
        top = index * (block_h + row_gap)

        face_rect = (0, top + (base - portrait) / 2.0,
                     portrait, top + (base - portrait) / 2.0 + portrait)
        face = CACHE / "champions" / f"{champion}.png"
        if face.exists():
            member.alpha_composite(sheet.icon(face, face_rect, round_=True))
        ring = max(1.0, 1.2 * scale)
        edge, draw = sheet.layer()
        draw.ellipse(sheet.box(*stroke_box(face_rect, 0.5, ring)),
                     outline=(0, 0, 0, 170), width=sheet.px(ring))
        member.alpha_composite(edge)

        x = portrait + split
        y = top + (base - spell) / 2.0
        for icon, left, full in spells:
            paint_spell(sheet, member, (x, y, x + spell, y + spell), icon,
                        left, full, scale, gap, strip)
            x += spell + gap

        # An enemy with nothing down and nothing just back is drawn faint.
        if all(left is None for _icon, left, _full in spells):
            member.putalpha(member.getchannel("A").point(
                lambda a: round(a * REST_OPACITY)))
        sheet.image.alpha_composite(member)
    return sheet.finish(), width, height


def main() -> int:
    for path in (ART, LOGO):
        if not path.exists():
            raise SystemExit(f"missing {path}")
    card = ground()
    draw = ImageDraw.Draw(card)

    # The words on the left, centred on the card's height now that nothing
    # runs along the bottom.
    logo = Image.open(LOGO).convert("RGBA").resize((104, 104), Image.LANCZOS)
    card.paste(logo, (72, 110), logo)
    draw.text((196, 120), "Flashwatch", font=font(MULISH, 60), fill=INK)
    draw.text((199, 188), "WINDOWS  ·  LEAGUE OF LEGENDS",
              font=font(MULISH, 20), fill=(196, 181, 253))

    draw.text((72, 282), "Enemy cooldowns,", font=font(MULISH, 66), fill=INK)
    draw.text((72, 358), "read off the screen.", font=font(MULISH, 66),
              fill=(196, 181, 253))
    draw.text((74, 460),
              "It reads the match chat and counts. No injection, no memory,",
              font=font(MULISH, 25), fill=DIM)
    draw.text((74, 498), "nothing to press during a game.",
              font=font(MULISH, 25), fill=DIM)

    # The display, against the right edge as it sits in a game: the product,
    # not a description of it.
    display, width, height = team_display(SCALE)
    left = SIZE[0] - 72 - width
    top = (SIZE[1] - height) / 2.0
    card.alpha_composite(display, (round(left - SHEET_MARGIN),
                                   round(top - SHEET_MARGIN)))

    card.convert("RGB").save(OUT, quality=86, optimize=True, progressive=True)
    print(f"{OUT.relative_to(ROOT)}  {SIZE[0]}x{SIZE[1]}  "
          f"{OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
