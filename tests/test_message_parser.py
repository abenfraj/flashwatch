# -*- coding: utf-8 -*-
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from riot_assets import RiotAssets
from message_parser import MessageParser

t0 = time.time()
assets = RiotAssets(locale="fr_FR")
assets.bootstrap(lambda m: print("  [boot]", m))
print(f"  bootstrap took {time.time()-t0:.1f}s\n")

parser = MessageParser(assets)

# Sanity: what does Data Dragon call Ahri's ult in French?
ahri = assets.champions["Ahri"]
print("Ahri ult:", ahri.ultimate.name, ahri.ultimate.cooldown_by_rank)
darius = assets.champions["Darius"]
print("Darius ult:", darius.ultimate.name, darius.ultimate.cooldown_by_rank)
print()

ahri_ult = ahri.ultimate.name          # "Assaut spirituel"
darius_ult = darius.ultimate.name      # "Guillotine noxienne"

# (line, should_match, expected_game_time or None to skip the check)
CASES = [
    ("(14:23) Ahri a utilise Saut eclair", True, 863),
    ("[14:23] Ahri a utilisé Saut éclair", True, 863),
    ("14:23 Darius a utilisé Téléportation", True, 863),
    ("(2:05) Jinx a utilisé Soins", True, 125),
    ("(21:14) Lux a utilisé Fatigue", True, 1274),
    ("(9:31) Viego a utilisé Châtiment", True, 571),
    (f"(31:02) Ahri a utilisé {ahri_ult}", True, 1862),        # ult by real name
    (f"(31:02) Darius a utilisé {darius_ult}", True, 1862),
    ("(31:02) Ahri a utilisé son ultime", True, 1862),         # generic wording
    ("(7:00) Ahri has used Flash", True, 420),                 # EN client
    ("(7:00) Ahri a utilisé son Saut éclair", True, 420),
    # --- must be rejected ---
    ("Bob (Ahri) : ahri a utilisé son flash", False, None),    # player typing
    ("Bob : darius flash top", False, None),
    ("(12:00) Ahri utilise Saut eclair", False, None),         # not system wording
    ("Ennemi manquant !", False, None),
    ("(3:12) Vous avez tué Ahri", False, None),
    ("Kevin (Jinx) : gg wp", False, None),
    ("(5:00) a utilisé Saut éclair", False, None),             # no champion
    ("(31:02) Ahri a utilisé Guillotine noxienne", False, None),  # not Ahri's ult
    # --- OCR noise, should still match, timestamp must survive intact ---
    ("(l4:23) Ahri a utilise Saut eclair", True, 863),         # l -> 1
    ("(14:23)  Ahrl  a  utilisé  Saut  éclalr", True, 863),    # mangled glyphs
    ("(l4:2S) Ahri a utilisé Saut éclair", True, 865),         # S -> 5
]

# Every line above that should match, with the (champion_id, spell_key) it must
# resolve to. Asserting only "did it match" is what let the verb-split bug hide.
EXPECT_KEYS = {
    "(14:23) Ahri a utilise Saut eclair": ("Ahri", "Flash"),
    "[14:23] Ahri a utilisé Saut éclair": ("Ahri", "Flash"),
    "14:23 Darius a utilisé Téléportation": ("Darius", "Teleport"),
    "(2:05) Jinx a utilisé Soins": ("Jinx", "Heal"),
    "(21:14) Lux a utilisé Fatigue": ("Lux", "Exhaust"),
    "(9:31) Viego a utilisé Châtiment": ("Viego", "Smite"),
    f"(31:02) Ahri a utilisé {ahri_ult}": ("Ahri", "ULT"),
    f"(31:02) Darius a utilisé {darius_ult}": ("Darius", "ULT"),
    "(31:02) Ahri a utilisé son ultime": ("Ahri", "ULT"),
    "(7:00) Ahri has used Flash": ("Ahri", "Flash"),
    "(7:00) Ahri a utilisé son Saut éclair": ("Ahri", "Flash"),
    "(l4:23) Ahri a utilise Saut eclair": ("Ahri", "Flash"),
    "(14:23)  Ahrl  a  utilisé  Saut  éclalr": ("Ahri", "Flash"),
    "(l4:2S) Ahri a utilisé Saut éclair": ("Ahri", "Flash"),
}

ok = 0
for line, expected, expected_time in CASES:
    ev = parser.parse_line(line)
    got = ev is not None
    good = got == expected
    note = ""
    if good and ev:
        if expected_time is not None and ev.game_time != expected_time:
            good, note = False, f"  << TIME got {ev.game_time}, want {expected_time}"
        want_keys = EXPECT_KEYS.get(line)
        if want_keys and (ev.champion_id, ev.spell_key) != want_keys:
            good = False
            note += f"  << KEYS got {(ev.champion_id, ev.spell_key)}, want {want_keys}"
    mark = "PASS" if good else "FAIL"
    ok += good
    detail = ""
    if ev:
        detail = f" -> {ev.champion_id}/{ev.spell_key} ({ev.spell_name}) t={ev.game_time}"
    print(f"{mark}  {line!r}{detail}{note}")

print(f"\n{ok}/{len(CASES)} cases behaved as expected")
print("\nnear misses recorded:")
for nm in parser.near_misses:
    print("   ", nm)

sys.exit(0 if ok == len(CASES) else 1)
