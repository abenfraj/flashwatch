"""Locates the in-game chat area on screen, without hardcoded coordinates.

Chat position and size depend on resolution, HUD scale, and whether the game is
fullscreen, borderless or windowed, so pixel offsets are not an option.

An earlier version tried to recognise chat by its *shape*: cluster the
left-aligned rows of glyph edges in the lower-left and take the biggest group.
Against real game footage that failed badly -- terrain, minions, health bars and
particles produce plenty of row-shaped edge blobs, and it happily locked onto a
patch of scenery in the middle of the screen, reporting a different answer every
few seconds. Synthetic test backgrounds were far too clean to expose it.

What replaced it keys on content instead of shape. Every chat line begins with
the game clock in parentheses:

    (14:23) Ahri a utilise Saut eclair

So the app *reads* the generous lower-left area first and lets the timestamps
say where chat is: the rows whose text starts with a clock define the region.
Scenery cannot fake that, and it needs no assumptions about resolution or HUD
scale.

Three tiers of trust:

    manual   -- the user drew the region, always wins
    auto     -- derived from rows that actually contained chat timestamps
    explore  -- generous lower-left band, read until timestamps are found

Crucially the explore band is what gets OCR'd while unconfirmed. Trusting an
unverified narrow guess is what made the first version read the wrong pixels and
find nothing at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Explore band as fractions of the client area: everywhere chat could sit.
ZONE_LEFT = 0.0
ZONE_RIGHT = 0.62
ZONE_TOP = 0.34
# Down to the very bottom edge: the chat box can be dragged right against it, and
# the input line sits below the messages.
ZONE_BOTTOM = 0.995

# Chat is left-aligned near the window edge, so while exploring we only bother
# reading rows that start in the left part of the band. This bounds the cost of
# reading a large area.
EXPLORE_LEFT_FRACTION = 0.55
EXPLORE_MAX_ROWS = 20

# Minimum row width, as a fraction of the band width, for a row to be worth
# recognising while exploring. A tracker ping ("Joueur (Champion): Attendez
# Champion Sort - 245 sec.") is a long run of text; most scenery blobs are short,
# so this discards them before the expensive recognition step.
EXPLORE_MIN_ROW_WIDTH = 0.10

# Same idea once the region is confirmed. With the chat box closed the region
# shows the moving game world, so without this every periodic re-read would pay
# recognition on a handful of scenery blobs. Lower than the explore threshold
# because the confirmed region is much narrower than the search band.
CONFIRMED_MIN_ROW_WIDTH = 0.14

# Once found, the region is padded generously around the chat lines: messages
# arrive below and scroll upward, so the band must cover where the next ones
# will land, not just where the current text sits.
PAD_LINES_ABOVE = 6
PAD_LINES_BELOW = 3
MIN_REGION_WIDTH_FRACTION = 0.42

# Chat is left-aligned near the window's left edge, whatever the resolution or
# HUD scale. A confirmation whose text starts past this fraction of the window is
# something else -- a single stray timestamped row in mid-screen once "confirmed"
# a region at x=593 of 1920 (31% across), which was then saved and reused across
# sessions, leaving the app permanently reading the wrong pixels. The real chat
# starts within a few percent of the edge, so this still leaves ample room.
MAX_CHAT_LEFT_FRACTION = 0.25


@dataclass(slots=True)
class ChatRegion:
    """A screen rectangle believed to contain the chat, in screen coordinates."""

    x: int
    y: int
    width: int
    height: int
    source: str = "fallback"        # manual | auto | fallback
    confirmed: bool = False        # a game timestamp has been read inside it
    rows: int = 0                  # text rows detected when found

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    @property
    def monitor(self) -> dict[str, int]:
        """In the shape mss expects for a capture."""
        return {"left": self.x, "top": self.y,
                "width": self.width, "height": self.height}

    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]

    def describe(self) -> str:
        state = "confirme" if self.confirmed else "non confirme"
        return (f"{self.width}x{self.height} @ {self.x},{self.y} "
                f"[{self.source}, {state}]")


def explore_region(window_rect: tuple[int, int, int, int]) -> ChatRegion:
    """The generous lower-left band that gets read until chat is confirmed."""
    zx, zy, zw, zh = _search_zone(window_rect)
    return ChatRegion(x=zx, y=zy, width=zw, height=zh, source="explore")


def search_band(window_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """The explore band as a plain rectangle, for the status/debug display."""
    return _search_zone(window_rect)


def _search_zone(window_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left, top, width, height = window_rect
    zx = left + int(width * ZONE_LEFT)
    zy = top + int(height * ZONE_TOP)
    zw = int(width * (ZONE_RIGHT - ZONE_LEFT))
    zh = int(height * (ZONE_BOTTOM - ZONE_TOP))
    return (zx, zy, zw, zh)


def region_from_chat_rows(
    chat_rows: list[tuple[int, int, int, int]],
    zone_offset: tuple[int, int],
    window_rect: tuple[int, int, int, int],
) -> ChatRegion | None:
    """Build the chat region from rows that were *read* as chat lines.

    ``chat_rows`` are bounding boxes, in capture-local pixels, of rows whose
    recognised text began with a game clock. Because the evidence is the text
    itself, this cannot be fooled by scenery.

    The result is padded by whole line heights above and below: chat fills
    upward as messages arrive, so the band has to cover where the next lines
    will appear, not merely where the current ones are.
    """
    if not chat_rows:
        return None
    left, top, width, height = window_rect
    offset_x, offset_y = zone_offset

    xs = [row[0] for row in chat_rows]

    # Reject a candidate that does not start near the left edge. Cheap, and it is
    # the difference between a stray row confirming a bogus region and staying in
    # exploration until the real chat is found.
    text_left = offset_x + min(xs)
    if text_left - left > width * MAX_CHAT_LEFT_FRACTION:
        log.info("ignoring chat candidate at x=%d: too far right for chat",
                 text_left)
        return None

    ys = [row[1] for row in chat_rows]
    y2s = [row[1] + row[3] for row in chat_rows]
    line_height = max(8, int(round(sum(row[3] for row in chat_rows) / len(chat_rows))))

    x1 = max(0, min(xs) - line_height)
    y1 = min(ys) - line_height * PAD_LINES_ABOVE
    y2 = max(y2s) + line_height * PAD_LINES_BELOW

    # Chat lines vary a lot in length, so do not trim the right edge to the
    # longest line we happen to have seen.
    region_width = max(int(width * MIN_REGION_WIDTH_FRACTION),
                       max(row[0] + row[2] for row in chat_rows) - x1 + line_height)

    region = ChatRegion(
        x=offset_x + x1,
        y=offset_y + y1,
        width=region_width,
        height=max(line_height * 4, y2 - y1),
        source="auto",
        confirmed=True,
        rows=len(chat_rows),
    )
    return clamp_to_window(region, window_rect)


def clamp_to_window(region: ChatRegion,
                    window_rect: tuple[int, int, int, int]) -> ChatRegion:
    """Keep a region inside the game window, so a stale saved rect stays usable."""
    left, top, width, height = window_rect
    x = max(left, min(region.x, left + width - 40))
    y = max(top, min(region.y, top + height - 20))
    w = max(40, min(region.width, left + width - x))
    h = max(20, min(region.height, top + height - y))
    return ChatRegion(x=x, y=y, width=w, height=h, source=region.source,
                      confirmed=region.confirmed, rows=region.rows)
