# -*- coding: utf-8 -*-
"""French and English interface.

The catalogue is checked as data rather than by reading it: a key present in one
language and missing in the other, or a `{placeholder}` that exists on one side
only, would crash or print a slug at exactly the wrong moment -- while a game is
running and the window is being drawn.

Then the plumbing: picking a language in the settings must persist the League
locale (which decides both the wordings looked for in chat and the champion names
downloaded) and announce the change, and a window built in English must actually
come out in English.
"""
import sys, io, os, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_langtest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

import i18n
from i18n import ENGLISH, FRENCH, STRINGS, language_for, locale_for, tr
from settings import Settings

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


PLACEHOLDER = re.compile(r"\{(\w+)")

# ------------------------------------------------------------- the catalogue
empty = [key for key, (fr, en) in STRINGS.items() if not fr.strip() or not en.strip()]
check("every string exists in both languages", not empty, str(empty[:5]))

mismatched = {key: (sorted(set(PLACEHOLDER.findall(fr))),
                    sorted(set(PLACEHOLDER.findall(en))))
              for key, (fr, en) in STRINGS.items()
              if set(PLACEHOLDER.findall(fr)) != set(PLACEHOLDER.findall(en))}
check("placeholders match across languages", not mismatched, str(mismatched))

# Anything still identical in both languages should be deliberate (a product
# name, a word that is spelled the same). Listed explicitly so a forgotten
# translation cannot hide among them.
SAME_ON_PURPOSE = {"app.title", "app.tray_tooltip", "ui.tab_debug",
                   "ui.theme_neon", "ui.notifications", "ui.actions",
                   "ui.overlay", "ui.capture",
                   # Words League itself does not translate.
                   "zone.name_chat", "zone.name_scoreboard"}
identical = {key for key, (fr, en) in STRINGS.items() if fr == en}
check("nothing is left untranslated by accident",
      identical <= SAME_ON_PURPOSE, str(sorted(identical - SAME_ON_PURPOSE)))
check("the deliberate list has no stale entries",
      SAME_ON_PURPOSE <= identical, str(sorted(SAME_ON_PURPOSE - identical)))

# ------------------------------------------------------------------ lookups
i18n.set_language(FRENCH)
check("French is served in French", tr("ui.tab_status") == "Statut",
      tr("ui.tab_status"))
i18n.set_language(ENGLISH)
check("English is served in English", tr("ui.tab_status") == "Status",
      tr("ui.tab_status"))
check("formatting works", tr("game.in_game", width=1920, height=1080)
      == "In game (1920x1080)", tr("game.in_game", width=1920, height=1080))
check("a missing key returns the key rather than raising",
      tr("nope.not.here") == "nope.not.here")
check("missing format arguments do not raise",
      isinstance(tr("game.in_game"), str))

check("a Riot locale maps to a language",
      language_for("en_US") == ENGLISH and language_for("fr_FR") == FRENCH)
check("a language maps back to a Riot locale",
      locale_for(ENGLISH) == "en_US" and locale_for(FRENCH) == "fr_FR")
check("an unknown locale falls back to French", language_for("de_DE") == FRENCH)
check("set_language accepts a locale as well as a code",
      i18n.set_language("en_US") == ENGLISH and i18n.current() == ENGLISH)

# --------------------------------------------------- the window and the switch
from PySide6.QtWidgets import QApplication

from ui import ControlWindow

app = QApplication.instance() or QApplication(sys.argv)


class FakeAssets:
    champions: dict = {}

    def icon_for_champion(self, _cid):
        return None

    def icon_for_spell(self, _key):
        return None


settings = Settings()
settings.update({"locale": "en_US"}, save=False)
i18n.set_language(ENGLISH)
english = ControlWindow(settings, FakeAssets())
check("a window built in English is in English",
      english.check_visible.text() == tr("ui.show_overlay")
      and "overlay" in english.check_visible.text().lower(),
      english.check_visible.text())
check("the language selector shows the saved language",
      english.combo_language.currentData() == ENGLISH)

# Switching must persist the locale and tell the application, which is what
# triggers the rebuild and the data reload.
announced = []
english.language_changed.connect(announced.append)
index = english.combo_language.findData(FRENCH)
english.combo_language.setCurrentIndex(index)
check("picking a language announces it", announced == [FRENCH], str(announced))
check("and persists the League locale",
      settings.get("locale") == "fr_FR", str(settings.get("locale")))

i18n.set_language(FRENCH)
french = ControlWindow(settings, FakeAssets())
check("a window built in French is in French",
      french.check_visible.text() == "Afficher l'overlay",
      french.check_visible.text())
check("the two windows really differ",
      french.check_locked.text() != english.check_locked.text())

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
