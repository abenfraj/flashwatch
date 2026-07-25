# -*- coding: utf-8 -*-
"""Guards that stop a wrong chat region from being confirmed and persisted.

A single stray timestamped row in mid-screen once confirmed a region at x=593 of
1920. That region was saved and reused on every later launch, so the app read the
wrong pixels permanently and no ping ever registered again. Two cheap properties
prevent it: chat is left-aligned near the window edge, and a chat line carries a
message rather than just a clock.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")

import chat_detector
from message_parser import looks_like_chat_line

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


# ------------------------------------------------- position of the candidate
for label, width, height in (("1080p", 1920, 1080), ("1440p", 2560, 1440),
                             ("4K", 3840, 2160)):
    window = (0, 0, width, height)
    offset = chat_detector.explore_region(window)
    band_offset = (offset.x, offset.y)

    # Roughly a third of the way across: this is what went wrong.
    bogus = chat_detector.region_from_chat_rows(
        [(int(width * 0.31), 400, 350, 20)], band_offset, window)
    check(f"[{label}] mid-screen candidate rejected", bogus is None,
          bogus.describe() if bogus else "")

    # Chat against the left edge, and chat nudged slightly in, both accepted.
    for name, x in (("flush left", 2), ("slightly indented", int(width * 0.03))):
        good = chat_detector.region_from_chat_rows(
            [(x, 400, 350, 20)], band_offset, window)
        check(f"[{label}] {name} candidate accepted", good is not None,
              good.describe() if good else "")

    # The band has to reach the very bottom: the chat box can be dragged there.
    bottom = offset.y + offset.height
    check(f"[{label}] explore band reaches the bottom edge",
          bottom >= height - 12, f"band ends at y={bottom} of {height}")


# --------------------------------------------------- what counts as chat
NOT_CHAT = ["12:34", "(12:34)", "36:18", "00:3618", "T:00:36:18*",
            "x 3.. tiers", "IA", "(1)", "412", "24:13"]
IS_CHAT = [
    "(12:04) Ahri a utilisé Saut éclair",
    "Ayoub (Lux): Attendez Rengar Saut éclair - 245 sec.",
    "Attendez Rengar Saut éclair - 245 sec.",
    "Ayoub (Lux): gg wp",
    "Kevin (Jinx) : attention mid",
]
for text in NOT_CHAT:
    check(f"not chat: {text!r}", not looks_like_chat_line(text))
for text in IS_CHAT:
    check(f"is chat: {text[:44]!r}", looks_like_chat_line(text))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
