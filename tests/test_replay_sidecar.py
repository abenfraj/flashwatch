# -*- coding: utf-8 -*-
"""Replay with a sidecar: what a person read off the footage.

A recording has no data feed, so on its own a replay times every spell with the
app's default assumptions. A sidecar supplies what the feed would have: the
enemies with their spells, levels, items and rune trees, the game clock, and
where the chat is. Checked here: the roster changes the cooldowns the way the
feed does (boots shorten Heal), a chat area known from the first frame makes the
priming pass work as in a game, and a malformed sidecar is refused by name.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

import json
import tempfile
from pathlib import Path

from replay import (ReplayInputError, ReplaySession, iter_video_frames,
                    load_sidecar, video_info)
from replay_fixture import make_fixture_video

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


scratch = Path(tempfile.mkdtemp(prefix="fw-replay-sidecar-"))
pings = make_fixture_video(scratch / "pings.mp4")
still = make_fixture_video(scratch / "still.mp4", still_from_start=True)


def run(path: Path, out: Path, sidecar: dict | None) -> ReplaySession:
    width, height, _, _ = video_info(path)
    session = ReplaySession(out, width=width, height=height, sidecar=sidecar)
    try:
        for t, frame in iter_video_frames(path, fps=5.0):
            session.step(t, frame)
    finally:
        session.close()
    return session


def write(name: str, data: dict) -> Path:
    path = scratch / name
    path.write_text(json.dumps(data), "utf-8")
    return path


# Where a plain replay finds the chat in this fixture.
plain = run(pings, scratch / "plain", None)
region = list(plain.region.rect) if plain.region is not None else None
check("a plain replay finds the chat", region is not None, str(region))

# (10:17) is on screen from second 2.0 of the fixture.
ENEMIES = [{"champion": "Darius", "spells": ["Flash", "Teleport"], "level": 9,
            "items": [], "rune_trees": ["Precision", "Resolve"], "position": "TOP"},
           {"champion": "Viego", "spells": ["Smite", "Flash"], "level": 9,
            "items": [], "rune_trees": ["Domination", "Precision"],
            "position": "JUNGLE"},
           {"champion": "Yasuo", "spells": ["Exhaust", "Flash"], "level": 9,
            "items": [], "rune_trees": ["Precision", "Resolve"],
            "position": "MIDDLE"},
           {"champion": "Jinx", "spells": ["Flash", "Heal"], "level": 9,
            "items": [], "rune_trees": ["Precision", "Sorcery"],
            "position": "BOTTOM"},
           {"champion": "Karma", "spells": ["Heal", "Flash"], "level": 9,
            "items": [], "rune_trees": ["Sorcery", "Resolve"],
            "position": "UTILITY"}]
BOOTED = ENEMIES[:4] + [dict(ENEMIES[4], items=[3158])]

base = load_sidecar(write("base.json", {"locale": "en_US", "chat_region": region,
                                        "game_clock_offset": 615.0,
                                        "enemies": ENEMIES}))
booted = load_sidecar(write("booted.json", dict(base, enemies=BOOTED)))

with_roster = run(pings, scratch / "roster", base)
found = sorted((r.champion_id, r.spell_key) for r in with_roster.records)
check("with the roster, the same two pings are read",
      found == [("Karma", "Heal"), ("Yasuo", "Exhaust")], str(found))
check("the chat area is known from the first step",
      with_roster.region is not None and list(with_roster.region.rect) == region,
      str(with_roster.region))
check("so nothing read is flagged first_read",
      with_roster.records and not any(r.first_read for r in with_roster.records)
      and not any(r.first_read for r in with_roster.timers))

with_boots = run(pings, scratch / "boots", booted)


def heal(session: ReplaySession) -> float | None:
    durations = [r.duration for r in session.timers
                 if (r.champion_id, r.spell_key) == ("Karma", "Heal")]
    return durations[0] if durations else None


check("Ionian Boots shorten Karma's Heal, as the feed would",
      heal(with_roster) is not None and heal(with_boots) is not None
      and heal(with_boots) < heal(with_roster),
      f"{heal(with_roster)} -> {heal(with_boots)}")

events_path = scratch / "roster" / "events.json"
with_roster.write(events_path, video=pings, duration=6.0, fps=5.0)
check("events.json says the roster came from a sidecar",
      json.loads(events_path.read_text("utf-8")).get("roster_from_sidecar") is True)

# The chat read from the first frame: the priming pass sees history, as in a game.
primed = run(still, scratch / "primed", load_sidecar(write("region.json", {
    "chat_region": region})))
check("lines on screen from the first frame start no timer when the chat is known",
      primed.timers == [], str(primed.timers))

# A hand-placed area narrower than a chat line is widened, as the app does.
import chat_detector
from chat_detector import ChatRegion
narrow = [region[0], region[1], 300, region[3]]
widened = run(pings, scratch / "narrow", load_sidecar(write("narrow.json", {
    "chat_region": narrow})))
expected = chat_detector.fit_manual_region(
    ChatRegion(*narrow, source="manual", confirmed=True), (0, 0, 1918, 1078))
check("a narrow chat_region is widened the way the app widens it",
      widened.region is not None and widened.region.rect == expected.rect
      and expected.width > 300, f"{widened.region} vs {expected}")

# Refused, each by the field at fault.
for name, data, field in (
        ("no-clock.json", {"enemies": ENEMIES}, "game_clock_offset"),
        ("locale.json", {"locale": "de_DE"}, "locale"),
        ("region3.json", {"chat_region": [1, 2, 3]}, "chat_region"),
        ("spell.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            dict(ENEMIES[4], spells=["Heal", "Fly"])]}, "spells"),
        ("champion.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            dict(ENEMIES[4], champion="Nobody")]}, "champion"),
        ("three.json", {"game_clock_offset": 0, "enemies": ENEMIES[:3]},
         "five"),
        ("no-items.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            {k: v for k, v in ENEMIES[4].items() if k != "items"}]}, "items"),
        ("no-runes.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            {k: v for k, v in ENEMIES[4].items() if k != "rune_trees"}]},
         "rune_trees"),
        ("no-level.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            {k: v for k, v in ENEMIES[4].items() if k != "level"}]}, "level"),
        ("typo.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            dict(ENEMIES[4], item=[3158])]}, "item"),
        ("three-trees.json", {"game_clock_offset": 0, "enemies": ENEMIES[:4] + [
            dict(ENEMIES[4], rune_trees=["Sorcery", "Resolve", "Inspiration"])]},
         "rune_trees")):
    try:
        load_sidecar(write(name, data))
        check(f"{name} is refused", False)
    except ReplayInputError as exc:
        check(f"{name} is refused, naming {field}", field in str(exc), str(exc))

try:
    load_sidecar(scratch / "missing.json")
    check("a missing sidecar is refused", False)
except ReplayInputError as exc:
    check("a missing sidecar is refused", "missing.json" in str(exc), str(exc))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
