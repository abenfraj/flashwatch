# -*- coding: utf-8 -*-
"""Synthetic League-like frames for testing capture, detection and OCR.

Importable with no side effects, so benchmarks and tests can share it.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = r"C:\Windows\Fonts\arial.ttf"

CHAT_LINES = [
    "(12:04) Ahri a utilisé Saut éclair",
    "(12:31) Darius a utilisé Téléportation",
    "(13:02) Viego a utilisé Châtiment",
    "Kevin (Jinx) : attention mid",
    "(13:40) Lux a utilisé Fatigue",
]


def make_frame(width: int, height: int, hud_scale: float = 1.0,
               lines: list[str] | None = None, clutter: bool = True,
               panel: bool = True, text_opacity: float = 1.0):
    """Return ``(frame_bgr, text_bbox)`` where text_bbox tightly bounds the chat.

    The bbox is the extent of the glyphs, not the panel behind them, since that
    is what a correct detector should return.

    ``clutter`` adds heavy high-frequency detail across the frame -- edges,
    bright specks, and decoy text. A smooth background is unrealistic and let an
    earlier, shape-based chat detector pass these tests while failing completely
    against real game footage, where terrain, minions, health bars and particles
    all produce row-shaped edge blobs.

    ``panel=False`` with ``text_opacity`` below 1.0 reproduces the harder case:
    the transient messages League shows with the chat box *closed*, drawn faint
    and directly over the game with no backing panel. Those are the ones that go
    unread, so they need covering explicitly.
    """
    lines = CHAT_LINES if lines is None else lines
    rng = np.random.default_rng(7)

    # Busy, mid-brightness "game art" so detection cannot cheat off a flat bg.
    bg = rng.integers(20, 90, size=(height, width, 3), dtype=np.uint8)
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=width / 120)
    for _ in range(18):
        cx, cy = int(rng.integers(0, width)), int(rng.integers(0, height))
        radius = int(rng.integers(width // 40, width // 8))
        colour = tuple(int(c) for c in rng.integers(30, 150, size=3))
        cv2.circle(bg, (cx, cy), radius, colour, -1)
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=width / 300)

    if clutter:
        # Sharp clutter everywhere, including the lower left where chat lives.
        for _ in range(220):
            x1 = int(rng.integers(0, width)); y1 = int(rng.integers(0, height))
            w = int(rng.integers(width // 90, width // 12))
            h = int(rng.integers(2, max(4, height // 70)))
            colour = tuple(int(c) for c in rng.integers(90, 245, size=3))
            cv2.rectangle(bg, (x1, y1), (x1 + w, y1 + h), colour,
                          -1 if rng.random() < 0.4 else 1)
        for _ in range(120):
            p1 = (int(rng.integers(0, width)), int(rng.integers(0, height)))
            p2 = (p1[0] + int(rng.integers(-140, 140)),
                  p1[1] + int(rng.integers(-40, 40)))
            colour = tuple(int(c) for c in rng.integers(80, 230, size=3))
            cv2.line(bg, p1, p2, colour, 1)

    image = Image.fromarray(cv2.cvtColor(bg, cv2.COLOR_BGR2RGB))

    font_size = max(11, int(height * 0.0155 * hud_scale))
    font = ImageFont.truetype(FONT_PATH, font_size)
    line_height = int(font_size * 1.45)

    chat_x = int(width * 0.028)
    chat_bottom = int(height * 0.855)
    chat_top = chat_bottom - line_height * len(lines)

    # Semi-transparent dark panel, as when the chat box is open.
    if panel:
        backing = image.copy()
        ImageDraw.Draw(backing).rectangle(
            [chat_x - int(width * 0.012), chat_top - int(height * 0.008),
             chat_x + int(width * 0.30), chat_bottom + int(height * 0.006)],
            fill=(8, 10, 18),
        )
        image = Image.blend(image, backing, 0.55)
    draw = ImageDraw.Draw(image)

    # Faded text is drawn by compositing at reduced strength, as the game does
    # when a message ages out.
    opacity = max(0.05, min(1.0, text_opacity))
    text_layer = image.copy()
    text_draw = ImageDraw.Draw(text_layer)

    widest = 0
    for index, line in enumerate(lines):
        y = chat_top + index * line_height
        text_draw.text((chat_x + 1, y + 1), line, font=font, fill=(0, 0, 0))
        text_draw.text((chat_x, y), line, font=font, fill=(238, 240, 245))
        widest = max(widest, int(font.getlength(line)))
    image = Image.blend(image, text_layer, opacity)
    draw = ImageDraw.Draw(image)

    # Decoys: other on-screen text that must not be mistaken for chat.
    big = ImageFont.truetype(FONT_PATH, int(font_size * 1.2))
    draw.text((int(width * 0.47), int(height * 0.04)), "24:13", font=big,
              fill=(230, 230, 230))
    for i in range(5):
        draw.text((int(width * 0.80), int(height * (0.30 + i * 0.045))),
                  f"Champion{i}  7/2/9", font=font, fill=(220, 220, 220))
    draw.text((int(width * 0.52), int(height * 0.44)), "412", font=big,
              fill=(255, 220, 120))

    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    text_bbox = (chat_x, chat_top, widest, chat_bottom - chat_top)
    return frame, text_bbox
