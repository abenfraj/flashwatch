# -*- coding: utf-8 -*-
"""Every champion x every summoner spell, plus every champion's ultimate.

Spot-checking a handful of champions is not enough. A liberal digit class,
introduced to recover "100" misread as "io0", made the cooldown pattern fire
inside champion names whose letters look like digits: "Aphelios" parsed as
"Apheli" + "o" (a zero) + "s" (seconds), and Ziggs and Miss Fortune broke the
same way -- silently, for all nine spells. Only a sweep over the whole roster
surfaces that class of bug.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ayoub\dev\lol-auto-timers\src")

from riot_assets import RiotAssets
from message_parser import MessageParser

assets = RiotAssets("fr_FR")
assets.bootstrap()
parser = MessageParser(assets)

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def report(label, failures, total):
    check(f"{label}: all {total} combinations parse", not failures,
          f"{len(failures)} failed")
    for name, spell, got in failures[:15]:
        print(f"       {name:24s} + {spell:22s} -> {got}")
    if len(failures) > 15:
        print(f"       ... and {len(failures) - 15} more")


# ------------------------------------- summoner spells, with author prefix
failures = []
count = 0
for champion_id, champion in assets.champions.items():
    for key, spell in assets.spells.items():
        count += 1
        event = parser.parse_line(
            f"Ayoub (Lux): Attendez {champion.name} {spell.name} - 245 sec.")
        if (event is None or event.champion_id != champion_id
                or event.spell_key != key or event.remaining_seconds != 245):
            failures.append((champion.name, spell.name,
                             (event.champion_id, event.spell_key,
                              event.remaining_seconds) if event else None))
report("summoner spells", failures, count)

# --------------------------------------------------- ultimates by name
ult_failures = []
ult_count = 0
for champion_id, champion in assets.champions.items():
    ult = champion.ultimate
    if ult is None or not ult.name:
        continue
    ult_count += 1
    event = parser.parse_line(
        f"Ayoub (Lux): Attendez {champion.name} {ult.name} - 60 sec.")
    if (event is None or event.champion_id != champion_id
            or event.spell_key != "ULT" or event.remaining_seconds != 60):
        ult_failures.append((champion.name, ult.name,
                             (event.champion_id, event.spell_key)
                             if event else None))
report("ultimates", ult_failures, ult_count)

# ------------------------------------------- a spread of realistic numbers
number_failures = []
number_count = 0
for seconds in (1, 5, 9, 12, 45, 99, 100, 137, 245, 246, 299, 300, 360, 600):
    for champion_id in ("Ahri", "Rengar", "Aphelios", "Ziggs", "MissFortune",
                        "MasterYi", "Kaisa", "Nunu", "Chogath", "LeeSin"):
        champion = assets.champions.get(champion_id)
        if champion is None:
            continue
        number_count += 1
        event = parser.parse_line(
            f"Ayoub (Lux): Attendez {champion.name} "
            f"{assets.spells['Flash'].name} - {seconds} sec.")
        if event is None or event.remaining_seconds != seconds:
            number_failures.append((champion.name, f"{seconds}s",
                                    event.remaining_seconds if event else None))
report("cooldown values", number_failures, number_count)

# ------------------------- champion names must not be read as the count
# Names full of digit-lookalike letters are the risky ones.
for champion_id in ("Aphelios", "Ziggs", "MissFortune", "Sion", "Sona",
                    "Singed", "Soraka", "Zoe", "Zilean", "Garen", "Gnar",
                    "Qiyana", "Quinn", "Jax", "Jinx", "Illaoi", "Ivern"):
    champion = assets.champions.get(champion_id)
    if champion is None:
        continue
    event = parser.parse_line(
        f"Ayoub (Lux): Attendez {champion.name} "
        f"{assets.spells['Flash'].name} - 245 sec.")
    check(f"{champion.name}: name not mistaken for the count",
          event is not None and event.remaining_seconds == 245
          and event.champion_id == champion_id,
          f"{(event.champion_id, event.remaining_seconds) if event else None}")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
