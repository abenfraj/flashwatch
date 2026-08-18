# -*- coding: utf-8 -*-
"""The setup guide, and the window it hands over to.

The guide exists because four things decide whether Flashwatch works and none of
them can be found by poking at the interface: League's window mode, the client's
language, where the chat is, and where the user wants the overlay. What is tested
here is not the prose but the contract around it:

* it runs once and only once -- offering it again to somebody who skipped it is
  arguing with them, and never offering it is the old behaviour;
* every step draws, in both languages, including the figures (they are painted,
  so a bad rectangle is a crash rather than an ugly page);
* what it changes really is changed: the language and the chosen display are
  written to settings and announced, so the application can follow.

The new control window is checked on the same terms: the things main.py and the
rest of the suite reach for still exist, and the state pill says the right thing.
"""
import sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_guidetest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"
if settings_module.CONFIG_PATH.exists():
    settings_module.CONFIG_PATH.unlink()

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

import i18n
from i18n import ENGLISH, FRENCH, tr
from onboarding import (STEP_TUNE, STEPS, Onboarding, TuneScreen,
                        countdown_faces)
from overlay import FACE_AUTO, LAYOUT_BAR, LAYOUT_CARDS, LAYOUT_LIST
from settings import DEFAULTS, Settings
from ui import ControlWindow

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


class FakeAssets:
    champions: dict = {}

    def icon_for_champion(self, _cid):
        return None

    def icon_for_spell(self, _key):
        return None


app = QApplication.instance() or QApplication(sys.argv)

# ------------------------------------------------------------- shown once
settings = Settings()
check("a fresh install has not seen the guide",
      not settings.get("onboarding_done"))

guide = Onboarding(settings)
check("the guide opens on its first step", guide.step_index() == 0)
check("it walks the eight screens the mockups lay out, plus the tuning one",
      len(STEPS) == 8 and STEP_TUNE in STEPS, str(STEPS))

# Every step paints. The figures are drawn by hand, so this is the only thing
# that separates "the diagram is wrong" from "the window will not open".
for index, step in enumerate(STEPS):
    guide.show_step(index)
    app.processEvents()
    canvas = QPixmap(guide.size())
    try:
        guide.render(canvas)
        painted, error = True, ""
    except Exception as exc:                              # noqa: BLE001
        painted, error = False, repr(exc)
    check(f"step {index + 1} ({step}) paints", painted, error)

# Walking forwards and back must not fall off either end.
guide.show_step(0)
guide._on_back()
check("back on the first step stays on the first step", guide.step_index() == 0)
for _ in range(len(STEPS) + 3):
    guide._on_next()
check("next past the last step finishes rather than overflowing",
      guide.step_index() == len(STEPS) - 1, str(guide.step_index()))
check("finishing marks the guide as seen", settings.get("onboarding_done"))

# Skipping counts too: somebody who skipped made a decision.
settings.set("onboarding_done", False)
skipped = Onboarding(settings)
skipped._on_finish()
check("skipping also marks it seen", settings.get("onboarding_done"))

# ...and it is reported exactly once, however it ends -- the button closes the
# window, and closing the window is itself an answer.
settings.set("onboarding_done", False)
counted = {"n": 0}
once = Onboarding(settings)
once.finished.connect(lambda: counted.__setitem__("n", counted["n"] + 1))
once._on_finish()
once.close()
check("finishing is reported exactly once", counted["n"] == 1, str(counted["n"]))

# Being replaced (the language changed) is not the same as being finished.
settings.set("onboarding_done", False)
replaced = {"n": 0}
victim = Onboarding(settings)
victim.finished.connect(lambda: replaced.__setitem__("n", replaced["n"] + 1))
victim.discard()
check("a guide discarded for a rebuild reports nothing", replaced["n"] == 0)
check("and does not count as seen", not settings.get("onboarding_done"))

# ---------------------------------------------------- what the guide changes
settings.set("overlay_layout", LAYOUT_BAR)
picker = Onboarding(settings)
picker.show_step(len(STEPS) - 1)
announced = []
picker.layout_changed.connect(announced.append)
picker.pick_layout(LAYOUT_CARDS)
check("picking a display in the guide saves it",
      settings.get("overlay_layout") == LAYOUT_CARDS,
      str(settings.get("overlay_layout")))
check("and announces it so the overlay can follow", announced == [LAYOUT_CARDS],
      str(announced))
check("the picked display is the one drawn as chosen",
      picker.current_layout() == LAYOUT_CARDS
      and picker.weights.get(f"layout:{LAYOUT_CARDS}") > 0)
picker.pick_layout("nonsense")
check("an unknown display is refused",
      settings.get("overlay_layout") == LAYOUT_CARDS)

# The guide asks the question in English, because the question has to be written
# in something before anyone has answered it.
check("a fresh install starts the guide in English",
      picker.current_language() == ENGLISH, picker.current_language())

languages = []
picker.language_changed.connect(languages.append)
picker.pick_language(FRENCH)
check("choosing a language in the guide persists the League locale",
      settings.get("locale") == "fr_FR", str(settings.get("locale")))
check("and announces it", languages == [FRENCH], str(languages))
check("the picked language is the card drawn as chosen",
      picker.current_language() == FRENCH)
picker.pick_language(FRENCH)
check("picking the language already in use announces nothing twice",
      languages == [FRENCH], str(languages))

# The window translates itself rather than being replaced -- which is what makes
# choosing a language in step one not flash the screen.
i18n.set_language(ENGLISH)
picker.retranslate()
check("the guide can be retranslated in place",
      hasattr(picker, "retranslate") and picker.step_index() == len(STEPS) - 1)
i18n.set_language(FRENCH)

# The guide has to exist in English as well, figures included.
i18n.set_language(ENGLISH)
english_guide = Onboarding(settings)
ok = True
for index in range(len(STEPS)):
    english_guide.show_step(index)
    app.processEvents()
    try:
        english_guide.render(QPixmap(english_guide.size()))
    except Exception:                                     # noqa: BLE001
        ok = False
check("every step paints in English too", ok)
check("the step counter is translated, in the title bar",
      "step" in english_guide.windowTitle().lower(),
      english_guide.windowTitle())
i18n.set_language(FRENCH)
settings.set("locale", "fr_FR")

# ------------------------------------------------------- tuning the display
# Everything the settings window's appearance card offers, offered again on the
# step where the preview is already on screen. What is checked here is the wiring
# rather than the drawing: a control that paints but writes nothing is the whole
# failure mode of a window with no widgets in it.
i18n.set_language(ENGLISH)
settings.update({"locale": "en_US", "overlay_layout": LAYOUT_BAR}, save=False)
tuner = Onboarding(settings)
tuner.show_step(STEPS.index(STEP_TUNE))
app.processEvents()

tuned = []
tuner.settings_changed.connect(lambda: tuned.append(1))
spots = {spot.key: spot for spot in TuneScreen().hots(tuner)}
check("every setting on the step is reachable",
      not [key for key in ("tune:theme:neon", "tune:overlay_opacity",
                           "tune:overlay_scale", "tune:timer_font_scale",
                           "tune:face:+", "tune:sort_by_role",
                           "tune:bar_vertical", "tune:linger:+", "tune:reset")
           if key not in spots],
      str(sorted(spots)))

spots["tune:theme:neon"].action()
check("picking a theme writes it and announces it",
      settings.get("theme") == "neon" and tuned, str(settings.get("theme")))

before = bool(settings.get("sort_by_role"))
spots["tune:sort_by_role"].action()
check("a switch flips the setting it names",
      bool(settings.get("sort_by_role")) is not before)

spots["tune:linger:+"].action()
check("the stepper counts up", settings.get("ready_linger_seconds") == 6,
      str(settings.get("ready_linger_seconds")))

# The list of faces is whatever this machine has installed, so the check is
# that the cycler walks it and comes back round rather than that it lands on any
# particular font: a build agent with no fonts at all has only "automatic", and
# a cycler with one entry that stays put is right, not broken.
faces = countdown_faces()
spots["tune:face:+"].action()
check("the countdown face steps to the next one this machine has",
      settings.get("timer_font") == faces[1 % len(faces)],
      f"{settings.get('timer_font')} out of {faces}")
for _ in range(len(faces) - 1):
    spots["tune:face:+"].action()
check("...and wraps back round to automatic",
      settings.get("timer_font") == FACE_AUTO, str(settings.get("timer_font")))

# The sliders are dragged rather than clicked, and the pointer is allowed to
# leave the strip: that is what makes both ends reachable.
strip = spots["tune:overlay_opacity"]
strip.drag(QPointF(strip.rect.right() + 200, strip.rect.center().y()))
check("a slider dragged past its end lands on the maximum",
      settings.get("overlay_opacity") == 1.0,
      str(settings.get("overlay_opacity")))
strip.drag(QPointF(strip.rect.left() - 200, strip.rect.center().y()))
check("...and past the other end, on the minimum",
      settings.get("overlay_opacity") == 0.35,
      str(settings.get("overlay_opacity")))

# The vertical track belongs to the track. Choosing another display takes the
# switch away rather than leaving one that does nothing.
tuner.pick_layout(LAYOUT_LIST)
check("the vertical switch is offered for the track only",
      "tune:bar_vertical" not in {spot.key for spot in TuneScreen().hots(tuner)})
tuner.pick_layout(LAYOUT_BAR)

# Reset asks first, and the question does not survive leaving the step.
tuner.ask_reset()
check("the reset button asks before it does anything",
      tuner.confirm_reset and settings.get("theme") == "neon")
confirm = {spot.key for spot in TuneScreen().hots(tuner)}
check("and offers both answers",
      {"tune:reset_yes", "tune:reset_no"} <= confirm, str(sorted(confirm)))
tuner.cancel_reset()
check("cancelling changes nothing",
      not tuner.confirm_reset and settings.get("theme") == "neon")
tuner.ask_reset()
tuner.show_step(STEPS.index(STEP_TUNE) + 1)
check("and walking away from the step drops the question",
      not tuner.confirm_reset)

tuner.show_step(STEPS.index(STEP_TUNE))
tuner.ask_reset()
tuner.reset_tune()
check("confirming puts every setting on the step back",
      not [key for key in TuneScreen.OWNED
           if settings.get(key) != DEFAULTS[key]],
      str([key for key in TuneScreen.OWNED
           if settings.get(key) != DEFAULTS[key]]))
check("...and only those: the display picked before it is untouched",
      settings.get("overlay_layout") == LAYOUT_BAR)
check("the question is answered once", not tuner.confirm_reset)

# The settings window has to be able to re-read what the guide wrote, or it
# would put its own stale values back the next time anything in it moved.
settings.update({"theme": "neon", "overlay_opacity": 0.5,
                 "ready_linger_seconds": 11}, save=False)
window = ControlWindow(settings, FakeAssets())
settings.update({"theme": "dark", "overlay_opacity": 0.75,
                 "ready_linger_seconds": 3}, save=False)
window.refresh_display_settings()
check("the settings window re-reads what the guide changed",
      window.combo_theme.currentData() == "dark"
      and window.slider_opacity.value() == 75
      and window.spin_ready_linger.value() == 3,
      f"{window.combo_theme.currentData()}/{window.slider_opacity.value()}/"
      f"{window.spin_ready_linger.value()}")
window._on_settings_changed()
check("...so writing from the window keeps the new values",
      settings.get("theme") == "dark"
      and round(float(settings.get("overlay_opacity")), 2) == 0.75,
      str(settings.get("theme")))

i18n.set_language(FRENCH)
settings.set("locale", "fr_FR", save=False)

# -------------------------------------------------- the control window's API
# Everything main.py and the rest of the suite reach for, in one place: a rename
# in the window would otherwise only show up as a crash mid-game.
control = ControlWindow(settings, FakeAssets())
for name in ("check_visible", "check_locked", "combo_language", "combo_theme",
             "slider_opacity", "spin_scale", "check_sort_role",
             "check_hide_ready", "spin_ready_linger", "check_summoners",
             "check_ultimates", "check_enemy_colour", "check_cosmic",
             "check_ionian", "check_audio", "check_audio_ready", "spin_warn",
             "spin_interval", "check_updates", "check_autostart",
             "label_autostart", "button_check_now", "label_update_state",
             "update_banner", "label_update", "button_update",
             "button_test_mode", "buttons_test", "text_lines", "list_misses",
             "list_colour", "list_events", "button_move", "button_demo",
             "layout_tiles"):
    check(f"the window still has {name}", hasattr(control, name))

check("all four pages were built", control.stack.count() == 4,
      str(control.stack.count()))
check("and each has a way to reach it",
      len(control.nav_buttons) == control.stack.count())

# The pill is the answer to "is it working?", so each state has to say something
# different from the others.
seen = {}
for state in ("loading", "waiting", "client", "in_game", "error"):
    control.set_state(state)
    seen[state] = (control.label_pill.text(), control.label_headline.text())
check("every state says something of its own",
      len({text for text, _ in seen.values()}) == 5, str(seen))
check("being in a game reads differently from waiting for one",
      seen["in_game"][1] != seen["waiting"][1], str(seen["in_game"]))
check("an unknown state does not crash the pill",
      (control.set_state("something-else") is None
       and bool(control.label_pill.text())), control.label_pill.text())

# The readouts still land where main.py puts them.
control.update_status(game="En jeu", region="500x200", ocr="12 analyses",
                      timers=3, clock="7:21", state="in_game")
check("the readouts are filled from update_status",
      control.label_timers.text() == "3" and control.label_clock.text() == "7:21",
      f"{control.label_timers.text()} / {control.label_clock.text()}")

# Picking a display writes the setting and tells the application.
changes = []
control.settings_changed.connect(lambda: changes.append(True))
control._on_layout_picked(LAYOUT_LIST)
check("picking a display in the settings window saves it",
      settings.get("overlay_layout") == LAYOUT_LIST,
      str(settings.get("overlay_layout")))
check("and reports the change", bool(changes))
check("the tile shows which one is chosen",
      control.layout_tiles[LAYOUT_LIST].isChecked())

# Something else changed it (the guide): the window has to catch up.
settings.set("overlay_layout", LAYOUT_BAR)
control.refresh_layout_choice()
check("the window follows a display chosen elsewhere",
      control.layout_tiles[LAYOUT_BAR].isChecked()
      and not control.layout_tiles[LAYOUT_LIST].isChecked())

# "Move it" and the lock are two views of one state, and they must not disagree.
locks = []
control.overlay_lock_toggled.connect(locks.append)
control.button_move.setChecked(True)
check("the move button asks for the overlay to be unlocked", locks == [False],
      str(locks))
control.sync_overlay_toggles(visible=True, locked=True)
check("locking from elsewhere puts the move button back",
      not control.button_move.isChecked() and control.check_locked.isChecked())
check("and the button offers to move again",
      control.button_move.text() == tr("ui.move_start"),
      control.button_move.text())
check("syncing does not echo the change back", locks == [False], str(locks))

# The trial switch: it says what it will do, then what it will undo, and it can
# be driven from the tray without echoing a request back at the application.
trials = []
control.demo_toggled.connect(trials.append)
check("the trial button offers to start one",
      control.button_demo.text() == tr("ui.demo_start"),
      control.button_demo.text())
control.button_demo.setChecked(True)
check("pressing it asks for the trial", trials == [True], str(trials))
check("and it then offers to stop it",
      control.button_demo.text() == tr("ui.demo_stop"),
      control.button_demo.text())
control.sync_demo(False)
check("the application ending the trial releases the button",
      not control.button_demo.isChecked()
      and control.button_demo.text() == tr("ui.demo_start"))
check("and that sync is not echoed back as a request", trials == [True],
      str(trials))

# The enemies card is empty until a spell has been read, and says so. isHidden
# rather than isVisible: this window was never shown, and no child of a hidden
# window is "visible" whatever it was told -- the question here is what it was
# asked to do.
control.clear_team()
check("with no enemy the card explains why it is empty",
      not control.label_team_empty.isHidden() and control.team_container.isHidden())
control.sync_team(["Ahri"], lambda _cid, _role: None)
check("a champion appears once one is seen",
      not control.team_container.isHidden() and control.label_team_empty.isHidden())

# The guide has to be reachable from the window, or somebody who skipped it on
# the first run has lost it for good.
asked = []
control.guide_requested.connect(lambda: asked.append(True))
control.guide_requested.emit()
check("the window can ask for the guide", asked == [True], str(asked))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
