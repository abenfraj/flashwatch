# -*- coding: utf-8 -*-
"""Checks the test-mode frame: geometry round-trip, the hole, and the signals.

The one property that really matters is that the frame *never paints inside the
rectangle it delimits*. Anything it drew there would be captured by the very
screenshot it is meant to aim, and fed straight back into the OCR. That is
enforced by the window mask, so this asserts the mask actually excludes the
region -- not just that it looks right.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from chat_detector import ChatRegion
from zone_overlay import MIN_REGION, ZONE_CHAT, ZoneFrame

# This file exercises the chat frame; the other zones live in test_extra_zones.py.
MIN_REGION_W, MIN_REGION_H = MIN_REGION[ZONE_CHAT]

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")

app = QApplication.instance() or QApplication(sys.argv)

frame = ZoneFrame()
frame.start(ChatRegion(300, 620, 780, 240, source="manual", confirmed=True))
app.processEvents()

# ------------------------------------------------------- geometry round-trip
got = frame.region_rect()
check("the hole lands on the requested region", got == (300, 620, 780, 240),
      f"got {got}")

region = frame.region()
check("region() reports a manual, confirmed rectangle",
      region.source == "manual" and region.confirmed)

frame.set_region((100, 200, 640, 180))
app.processEvents()
check("moving the frame moves the region",
      frame.region_rect() == (100, 200, 640, 180), str(frame.region_rect()))

frame.set_region((100, 200, 10, 5))
app.processEvents()
x, y, w, h = frame.region_rect()
check("a too-small region is clamped, never zero-sized",
      w >= MIN_REGION_W and h >= MIN_REGION_H, f"{w}x{h}")

# ------------------------------------------------------------- the empty hole
frame.set_region((400, 300, 500, 200))
app.processEvents()
frame.repaint()
mask = frame.mask()
hole_local = QRect(frame.width() // 2, frame.height() // 2, 1, 1)
check("the frame window has a mask", not mask.isEmpty())
check("the middle of the frame is outside the window",
      not mask.contains(hole_local.topLeft()),
      "the frame would be captured by its own screenshot")
check("the border of the frame is part of the window",
      mask.contains(QPoint(2, 2)))

# ------------------------------------------------------------------- signals
seen = {"changed": [], "applied": [], "cancelled": 0, "closed": 0}
frame.region_changed.connect(lambda r: seen["changed"].append(r))
frame.applied.connect(lambda r: seen["applied"].append(r))
frame.cancelled.connect(lambda: seen.__setitem__("cancelled", seen["cancelled"] + 1))
frame.closed.connect(lambda: seen.__setitem__("closed", seen["closed"] + 1))

before = frame.region_rect()
frame.keyPressEvent(_key := type("E", (), {
    "key": lambda self: Qt.Key_Right,
    "modifiers": lambda self: Qt.NoModifier,
})())
app.processEvents()
after = frame.region_rect()
check("the right arrow nudges the region right by a pixel",
      after[0] == before[0] + 1 and after[1] == before[1], f"{before} -> {after}")

# The nudge is debounced; give the timer a chance to fire.
import time
deadline = time.monotonic() + 1.0
while not seen["changed"] and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.02)
check("a nudge eventually publishes the new region", bool(seen["changed"]),
      f"{len(seen['changed'])} emissions")

# ------------------------------------------------------------- live feedback
rx, ry, rw, rh = frame.region_rect()
frame.set_feedback([
    ((rx + 8, ry + 20, 400, 18), "(14:23) Ahri a utilise Saut eclair", True),
    ((rx + 8, ry + 44, 120, 18), "bruit", False),
], exploring=False, note="12 ms")
frame.repaint()
check("feedback is accepted and repaints without error", True)

frame._on_apply()
app.processEvents()
check("Valider emits the region", len(seen["applied"]) == 1)
check("Valider closes the frame", seen["closed"] == 1 and not frame.isVisible())
check("Valider does not also cancel", seen["cancelled"] == 0)

# ---------------------------------------------------------------- cancelling
other = ZoneFrame()
cancelled = {"n": 0, "closed": 0}
other.cancelled.connect(lambda: cancelled.__setitem__("n", cancelled["n"] + 1))
other.closed.connect(lambda: cancelled.__setitem__("closed", cancelled["closed"] + 1))
other.start((500, 500, 400, 150))
app.processEvents()
other.keyPressEvent(type("E", (), {
    "key": lambda self: Qt.Key_Escape,
    "modifiers": lambda self: Qt.NoModifier,
})())
app.processEvents()
check("Echap cancels and closes", cancelled["n"] == 1 and cancelled["closed"] == 1,
      str(cancelled))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
