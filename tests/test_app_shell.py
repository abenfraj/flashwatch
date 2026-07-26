# -*- coding: utf-8 -*-
"""Builds the real application and checks its shell: tray menu, overlay flags,
and the routes a user has to quit.

The tray-menu check exists because of a bug that no amount of reading caught:
QActions created as locals and handed to ``menu.addAction(action)`` are not owned
by the menu in PySide6, so they were garbage-collected the moment the builder
returned. The menu lost four entries including Quitter, leaving no way to stop
the program. Only an assertion that survives a GC pass catches that.
"""
import sys, io, os, gc, threading, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path

from pathlib import Path

# Keep the test out of the user's real config file.
import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_shelltest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"

from PySide6.QtCore import QThread, QTimer, Qt
import main as app_main
import updater

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")

# ------------------------------------------------- one instance at a time
# Packaged as a single .exe there is no window for the first seconds, so a second
# double-click is the natural thing to do; the second copy must stand down rather
# than OCR the same chat and draw a second overlay. Checked under a test-only
# name, so it passes whether or not the real app is running on this machine.
TOKEN_NAME = "FlashwatchShellTest.instance"
token = app_main.acquire_single_instance(TOKEN_NAME)
check("the first copy claims the instance token", token is not None)
check("a second copy is refused",
      app_main.acquire_single_instance(TOKEN_NAME) is None)

try:
    application = app_main.Application()
    check("application constructed", True)
except Exception:
    traceback.print_exc()
    check("application constructed", False)
    sys.exit(1)

# ------------------------------------------------------------ tray menu
# Force collection: this is what killed the menu entries before.
gc.collect(); gc.collect(); gc.collect()

menu = application.tray.contextMenu()
check("tray has a context menu", menu is not None)
labels = []
dead = False
for action in (menu.actions() if menu else []):
    try:
        labels.append("--" if action.isSeparator() else action.text())
    except RuntimeError:
        dead = True
check("no tray entry was garbage-collected", not dead)
check("tray menu still populated after GC", len(labels) >= 8, f"{len(labels)} entries")

def has(fragment):
    return any(fragment.lower() in label.lower() for label in labels)

check("tray offers a way to quit the process", has("quitter"), str(labels))
check("tray offers the settings window", has("parametres"))
check("tray offers chat re-detection", has("redetecter"))
check("tray offers a timer reset", has("reinitialiser"))
check("tray offers overlay visibility", has("overlay"))
check("tray icon is visible", application.tray.isVisible())

# ------------------------------------------------- routes to quit the app
asked = {"count": 0}
application.control.quit_requested.connect(
    lambda: asked.__setitem__("count", asked["count"] + 1))

# The close button hides the window and leaves the program running. Flashwatch
# is started before a game and forgotten, so that button is far more often "done
# reading this" than "done playing" -- and quitting a session by accident loses
# every timer in the running game, where hiding one by accident costs a click in
# the tray. Quitting stays reachable: the tray entry checked above says so in as
# many words, and so does the button in the window.
application.control.show()
application.control.close()
check("closing the settings window does not quit", asked["count"] == 0,
      f"{asked['count']} requests")
check("closing the settings window hides it",
      not application.control.isVisible())

# ...and the window must come back, or hiding it would be indistinguishable
# from losing it.
application.control.show()
check("the window can be reopened after closing",
      application.control.isVisible())

application.control.hide()
check("hiding the window does not quit either", asked["count"] == 0,
      f"{asked['count']} requests")

# ------------------------------------------------------------- overlay
check("locked overlay is click-through",
      application.overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
application._on_overlay_locked(False)
check("unlock disables click-through",
      not application.overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
application._on_overlay_locked(True)
check("re-lock restores click-through",
      application.overlay.testAttribute(Qt.WA_TransparentForMouseEvents))

# Auto-hide: between games the bar has nothing to say and must not sit on the
# desktop or over the client. Unlocking is the exception -- it is how the bar
# gets moved, so it has to be on screen for that.
check("the bar stays hidden while no game is on screen",
      not application.overlay.isVisible())
application._on_overlay_locked(False)
check("unlocking shows the bar so it can be moved",
      application.overlay.isVisible())
application._on_overlay_locked(True)
application.overlay.set_game_active(True)
check("the bar appears once the game window is up",
      application.overlay.isVisible())
application.overlay.set_game_active(False)
check("the bar hides again when the game goes away",
      not application.overlay.isVisible())

check("overlay defaults to the bar layout",
      application.settings.get("overlay_layout") == "bar")
geometry = application.overlay.geometry()
check("bar was placed at the top of the screen", geometry.y() < 80,
      f"y={geometry.y()}")

# ------------------------------------------- background pipeline starts
state = {}
def finish():
    state["assets"] = application.assets.ready
    state["worker"] = application.worker is not None and application.worker.is_alive()
    state["parser"] = application.parser is not None
    state["status"] = getattr(application, "_latest_status", None)

    # ------------------------------------------------- test mode round-trip
    # Opening the frame must repoint the worker at it, and cancelling must put
    # back exactly what was there before -- otherwise a look at the zone would
    # silently leave the app reading a hand-drawn rectangle for good.
    if application.worker is not None:
        saved_before = application.settings.get("chat_region")
        locked_before = application.settings.get("chat_region_locked")
        application.control.button_test_mode.setChecked(True)
        frame = application.zone_frames.get("chat")
        state["frame_shown"] = frame is not None and frame.isVisible()
        state["worker_follows_frame"] = (
            frame is not None and application.worker.region is not None
            and application.worker.region.rect == frame.region_rect())
        state["worker_in_test_mode"] = application.worker._test_mode
        state["tray_synced"] = application.actions_test["chat"].isChecked()

        frame_rect = frame.region_rect() if frame is not None else None
        application.control.button_test_mode.setChecked(False)
        state["frame_closed"] = "chat" not in application.zone_frames
        state["test_mode_off"] = not application.worker._test_mode
        restored = application.worker.region
        state["not_pinned_to_frame"] = (restored is None
                                        or restored.rect != frame_rect)
        state["settings_untouched"] = (
            application.settings.get("chat_region") == saved_before
            and application.settings.get("chat_region_locked") == locked_before)
        state["tray_unchecked"] = not application.actions_test["chat"].isChecked()

        # ------------------------------------------- the clock and scoreboard
        # Same machinery, different areas: each frame must point the worker at
        # its own rectangle without disturbing the chat, and closing must leave
        # only the clock being read -- the scoreboard has no consumer yet, so
        # reading it once placed would be pure cost.
        clock_saved = application.settings.get("clock_region")
        board_saved = application.settings.get("scoreboard_region")
        chat_region_now = application.worker.region

        application.control.buttons_test["clock"].setChecked(True)
        application.control.buttons_test["scoreboard"].setChecked(True)
        clock_frame = application.zone_frames.get("clock")
        board_frame = application.zone_frames.get("scoreboard")
        state["clock_frame_shown"] = (clock_frame is not None
                                      and clock_frame.isVisible())
        state["board_frame_shown"] = (board_frame is not None
                                      and board_frame.isVisible())
        probes = application.worker._probes
        state["clock_probed"] = (
            clock_frame is not None and "clock" in probes
            and probes["clock"].rect == clock_frame.region_rect())
        state["board_probed"] = (
            board_frame is not None and "scoreboard" in probes
            and probes["scoreboard"].rect == board_frame.region_rect())
        state["chat_untouched_by_probes"] = (
            application.worker.region == chat_region_now)

        # Validating the clock stores it and keeps it being read. The rectangle is
        # read *before* applying: applying closes the frame, and a closed window's
        # geometry is no longer what it delimited.
        expected_clock = list(clock_frame.region_rect()) if clock_frame else None
        if clock_frame is not None:
            clock_frame._on_apply()
        state["clock_persisted"] = (
            expected_clock is not None
            and application.settings.get("clock_region") == expected_clock)
        state["clock_still_probed"] = "clock" in application.worker._probes

        # Cancelling the scoreboard stores nothing and stops reading it.
        application.control.buttons_test["scoreboard"].setChecked(False)
        state["board_not_persisted"] = (
            application.settings.get("scoreboard_region") == board_saved)
        state["board_probe_off"] = "scoreboard" not in application.worker._probes
        state["board_frame_closed"] = "scoreboard" not in application.zone_frames

        # Leave the config as it was found.
        application.settings.update({"clock_region": clock_saved,
                                     "scoreboard_region": board_saved})
        application.worker.set_probe("clock", None)

    # ------------------------------------------------------------ updates
    # The banner is the one thing in this window that appears by itself, so what
    # it does with a release matters more than how it looks. Nothing here touches
    # the network: the release is handed straight to the handler the check calls.
    # isHidden rather than isVisible: the settings window itself is closed at this
    # point, and no child of a hidden window is "visible" whatever it was told.
    # The question here is what the banner was asked to do.
    def banner_offered():
        return not application.control.update_banner.isHidden()

    state["banner_hidden_at_rest"] = not banner_offered()

    offered = updater.Release(version="99.0.0", tag="v99.0.0", notes="",
                              download_url="https://example.invalid/exe",
                              size=0, page_url="https://example.invalid")
    application._on_check_finished(offered, False)
    state["banner_shown"] = banner_offered()
    state["release_pending"] = application._pending_release is offered
    state["banner_names_the_version"] = (
        "99.0.0" in application.control.label_update.text())

    # Running from source there is no packaged build to swap, so pressing the
    # button must do nothing rather than download 80 MB into a checkout.
    state["nothing_to_replace_from_source"] = application._exe is None
    application._on_install_update()
    state["install_declined_from_source"] = not application._update_busy

    # Skipping silences that exact version, and only for the automatic check.
    application.control.update_skipped.emit()
    state["banner_dismissed"] = not banner_offered()
    state["skip_persisted"] = (
        application.settings.get("update_skipped_version") == "99.0.0")
    application._on_check_finished(offered, False)
    state["skipped_not_reoffered"] = not banner_offered()
    application._on_check_finished(offered, True)
    state["asking_overrides_the_skip"] = banner_offered()
    application.settings.set("update_skipped_version", "")

    # ------------------------------------------------- language round-trip
    # Switching language replaces the settings window and refills the tray menu.
    # The window being discarded must not be able to quit the application on its
    # way out -- its close event asks for exactly that.
    quits_before = asked["count"]
    previous_window = application.control
    combo = application.control.combo_language
    combo.setCurrentIndex(combo.findData("en"))
    state["window_replaced"] = application.control is not previous_window
    state["locale_persisted"] = application.settings.get("locale") == "en_US"
    entries = [a.text() for a in application.tray.contextMenu().actions()
               if not a.isSeparator()]
    state["tray_in_english"] = any("quit (" in e.lower() for e in entries)
    state["tray_still_complete"] = len(entries) >= 8
    state["rebuild_did_not_quit"] = asked["count"] == quits_before

    # An offer the user has not acted on belongs to the application, not to the
    # window that happened to be showing it.
    state["offer_survives_the_rebuild"] = (
        not application.control.update_banner.isHidden())

    # Put French back, so the saved settings are left as they were found.
    combo = application.control.combo_language
    combo.setCurrentIndex(combo.findData("fr"))
    state["back_to_french"] = any(
        "quitter" in a.text().lower()
        for a in application.tray.contextMenu().actions() if not a.isSeparator())

    # The thread -> UI hop everything above reports through. Checked from a plain
    # worker thread because that is the case that used to fail silently:
    # QTimer.singleShot creates its timer in the calling thread, which has no
    # event loop, so the callback was simply never delivered.
    state["hop_thread"] = None
    ui_thread = QThread.currentThread()

    def from_worker():
        application._invoker.post(
            lambda: state.__setitem__("hop_thread", QThread.currentThread()))

    threading.Thread(target=from_worker, name="HopProbe").start()
    # Returning lets the event loop run, which is the only way the posted
    # callback can arrive; the result is read once it has had the chance.
    QTimer.singleShot(500, lambda: (
        state.__setitem__("hop_on_ui_thread", state["hop_thread"] is ui_thread),
        application.quit()))

QTimer.singleShot(9000, finish)
application.run()

check("Riot assets loaded", state.get("assets"),
      f"{len(application.assets.champions)} champions")
check("parser built", state.get("parser"))
check("capture worker running", state.get("worker"))
status = state.get("status")
check("worker published a status", status is not None,
      f"game={status.game!r} region={status.region!r}" if status else "none")
check("worker reported no error", not (status and status.error),
      (status.error if status else ""))

# ------------------------------------------------------------- test mode
check("test mode shows the zone frame", state.get("frame_shown"))
check("the worker reads exactly what the frame delimits",
      state.get("worker_follows_frame"))
check("the worker knows it is in test mode", state.get("worker_in_test_mode"))
check("the tray entry follows the button", state.get("tray_synced"))
check("leaving test mode closes the frame", state.get("frame_closed"))
check("leaving test mode clears the worker flag", state.get("test_mode_off"))
check("cancelling does not leave the frame's rectangle behind",
      state.get("not_pinned_to_frame"))
check("cancelling persists nothing", state.get("settings_untouched"))
check("the tray entry unchecks itself", state.get("tray_unchecked"))

# ------------------------------------------------- clock and scoreboard zones
check("the game-clock frame opens", state.get("clock_frame_shown"))
check("the scoreboard frame opens", state.get("board_frame_shown"))
check("the worker reads exactly what the clock frame delimits",
      state.get("clock_probed"))
check("the worker reads exactly what the scoreboard frame delimits",
      state.get("board_probed"))
check("placing them does not disturb the chat area",
      state.get("chat_untouched_by_probes"))
check("validating the clock area saves it", state.get("clock_persisted"))
check("and it keeps being read afterwards", state.get("clock_still_probed"))
check("cancelling the scoreboard persists nothing",
      state.get("board_not_persisted"))
check("and stops reading it", state.get("board_probe_off"))
check("its frame is closed", state.get("board_frame_closed"))

# ------------------------------------------------------------- language
check("switching language rebuilds the settings window",
      state.get("window_replaced"))
check("switching language saves the League locale",
      state.get("locale_persisted"))
check("the tray menu follows the language", state.get("tray_in_english"))
check("the tray menu is still complete after the rebuild",
      state.get("tray_still_complete"))
check("replacing the window does not quit the application",
      state.get("rebuild_did_not_quit"))
check("switching back restores French", state.get("back_to_french"))

# ------------------------------------------------------------- updates
check("no banner until there is something to say",
      state.get("banner_hidden_at_rest"))
check("a newer release raises the banner", state.get("banner_shown"))
check("and is remembered so the button has something to install",
      state.get("release_pending"))
check("the banner says which version", state.get("banner_names_the_version"))
check("running from source there is no executable to replace",
      state.get("nothing_to_replace_from_source"))
check("so the install button does nothing rather than download",
      state.get("install_declined_from_source"))
check("skipping dismisses the banner", state.get("banner_dismissed"))
check("and remembers the version passed on", state.get("skip_persisted"))
check("a skipped version is not offered again", state.get("skipped_not_reoffered"))
check("but asking explicitly overrides the skip",
      state.get("asking_overrides_the_skip"))
check("an unanswered offer survives a language change",
      state.get("offer_survives_the_rebuild"))

# ------------------------------------------------------- thread -> UI hop
check("a callback posted from a worker thread arrives on the Qt thread",
      state.get("hop_on_ui_thread"),
      f"landed on {state.get('hop_thread')}")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
