"""Application entry point.

Threading model: the capture/OCR loop owns its own thread and never touches Qt.
It pushes results into a queue, and the Qt side drains that queue on a timer.
Passing plain data across one queue avoids the cross-thread signal and painting
hazards that a shared-widget design would invite.

    CaptureWorker thread            Qt main thread
    ------------------              --------------
    grab -> diff -> OCR      queue   drain -> TimerManager -> Overlay
    -> parse -> events      ------>  -> notifications -> audio
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from pathlib import Path

# Allow "import overlay" etc. when launched as a script from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import autostart
import chat_detector
import i18n
import self_test
import settings as settings_module
import single_instance
import theme
import updater
from audio import Notifier
from chat_detector import ChatRegion
from i18n import tr
from message_parser import MessageParser
from ocr import CaptureWorker
from onboarding import Onboarding
from overlay import Overlay
from riot_assets import RiotAssets
from roles import ROLES
from settings import Settings
from timer_manager import TimerManager
from ui import ControlWindow, RegionPicker
from version import __version__
from zone_overlay import (ZONE_CHAT, ZONE_CLOCK, ZONE_LOADING,
                          ZONE_SCOREBOARD, ZONES, ZoneFrame)

log = logging.getLogger(__name__)

UI_REFRESH_MS = 100          # overlay countdown smoothness
DRAIN_MS = 50                # how often the queue is emptied
LOG_PATH = settings_module.ASSETS_DIR / "flashwatch.log"

# How long after start-up the update check runs. Late enough that it never
# competes with loading Riot's data, early enough that the answer is there before
# the user has finished reading the settings window.
UPDATE_CHECK_DELAY_MS = 4000

# How long after start-up the first-run guide appears. Long enough that the tray
# icon and the windows exist first, short enough to read as part of launching.
GUIDE_DELAY_MS = 700

# How often the trial mode tops its fake cooldowns back up. Slow: it only has to
# replace entries that have run out, and the countdowns animate from the UI
# refresh like any others.
DEMO_TICK_MS = 2000

# Where each hand-placed area is persisted.
SETTING_FOR_ZONE = {
    ZONE_CHAT: "chat_region",
    ZONE_CLOCK: "clock_region",
    ZONE_SCOREBOARD: "scoreboard_region",
    ZONE_LOADING: "loading_region",
}

# The two areas the enemy team is listed in. Unlike the clock, these are read for
# the application's own sake and go on being read after the framing tool closes,
# so they are registered with the worker separately.
ROLE_ZONES = (ZONE_LOADING, ZONE_SCOREBOARD)

# Labels for the tray entries that open each frame.
TRAY_TEST_KEYS = {
    ZONE_CHAT: "tray.test_mode",
    ZONE_CLOCK: "ui.test_mode_clock",
    ZONE_SCOREBOARD: "ui.test_mode_scoreboard",
    ZONE_LOADING: "ui.test_mode_loading",
}


def configure_logging() -> None:
    settings_module.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
        handlers=handlers,
    )


# The mark itself is drawn in theme.py, next to the geometry it is drawn from.
# It is wanted in four places now -- the tray, the taskbar, both windows' headers
# -- and a copy per caller is exactly how the runtime icon and the one stamped on
# the executable drifted apart before.
make_mark = theme.mark_pixmap


def make_tray_icon() -> QIcon:
    """The mark as an icon, so no image file needs shipping."""
    return QIcon(make_mark())


class UiInvoker(QObject):
    """Runs a callable on the Qt thread, from any thread.

    A queued signal rather than ``QTimer.singleShot(0, callback)``, which is what
    this code used to do and which silently does nothing: the static ``singleShot``
    creates its timer in the *calling* thread, and a plain worker thread has no
    event loop to run it in, so the callback is never delivered. Emitting a signal
    across threads is queued to the receiver's thread instead, which is the one
    guarantee needed here.
    """

    posted = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        # Explicit rather than automatic: the connection type is the whole point,
        # and Qt's automatic choice depends on which thread emitted.
        self.posted.connect(self._run, Qt.QueuedConnection)

    def post(self, callback) -> None:
        self.posted.emit(callback)

    @staticmethod
    def _run(callback) -> None:
        try:
            callback()
        except Exception:                             # noqa: BLE001
            # A raise here would cross back into Qt's event loop, where it is
            # neither caught nor reported.
            log.exception("posted callback failed")


class Application:
    """Owns every component and the wiring between them."""

    def __init__(self) -> None:
        # Before the settings are read, since it is what may put them there: a
        # copy started for the first time in a new folder -- which is what a
        # manually downloaded update is -- takes over the previous install's
        # configuration instead of coming up as a fresh one.
        #
        # Packaged builds only. From source the data root is the checkout, and a
        # checkout adopting the settings of the .exe on the same machine (or the
        # other way round) is surprising in both directions.
        if getattr(sys, "frozen", False):
            settings_module.carry_config_forward()

        self.settings = Settings()
        settings_module.ensure_dirs()

        # Before anything with a label is built: the interface follows the League
        # client language chosen in the settings.
        i18n.set_language(str(self.settings.get("locale", "en_US")))

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        # Needs a QApplication to know the screen, and has to run before the
        # capture worker registers the clock probe from these values.
        if self.settings.fresh:
            self._seed_zones_for_screen()
        # Created with the application, so it belongs to the Qt thread: that is
        # what makes a posted callback arrive there.
        self._invoker = UiInvoker()
        # Set on the application, not on each window: it reaches the control
        # panel, the taskbar button and Alt-Tab in one go. Without it those all
        # fall back to Qt's own default icon, which is how the settings window
        # ended up wearing somebody else's logo.
        self.app.setWindowIcon(make_tray_icon())
        # Flashwatch is portable and people are told they can move the folder,
        # which would leave a startup entry booting a path that no longer
        # exists. Only rewrites an entry that is already there.
        autostart.refresh_if_moved()

        # The version this replaced, if an update ran last time. Now is the first
        # moment it is no longer the running image and can therefore go.
        self._exe = updater.installed_exe()
        if self._exe is not None:
            updater.cleanup(self._exe.parent)
        # The release currently being offered, and whether an install is running.
        self._pending_release: updater.Release | None = None
        self._update_busy = False
        self._update_percent = -1

        self.assets = RiotAssets(locale=str(self.settings.get("locale", "en_US")))
        self.notifier = Notifier(self.settings)

        # Built after assets load, since both need champion data.
        self.parser: MessageParser | None = None
        self.timers: TimerManager | None = None
        self.worker: CaptureWorker | None = None

        self.results: queue.Queue = queue.Queue(maxsize=64)
        self.overlay = Overlay(self.settings, self.assets)
        self.control = ControlWindow(self.settings, self.assets)
        self.picker: RegionPicker | None = None
        # The setup guide, while it is open. One at a time: two copies would be
        # writing the same settings behind each other's back.
        self.guide: Onboarding | None = None
        # True while the trial mode is running: fake cooldowns on screen, every
        # hide rule overridden, and no game in sight.
        self._demo = False
        # One test-mode frame per area being placed, keyed by zone.
        self.zone_frames: dict[str, ZoneFrame] = {}
        # What to put back if the chat test mode is cancelled.
        self._region_before_test: tuple[list[int] | None, bool] | None = None
        self._known_champions: set[str] = set()
        # The last team reading handed to the timers. Kept so a reading is
        # applied once rather than on every refresh, and so a roster that has
        # been cleared underneath us is noticed.
        self._applied_roles: dict[int, str] = {}
        self._boot_message = tr("boot.loading")

        self._connect_ui()
        self._build_tray()
        self._install_hotkeys()

        self.overlay.set_status(self._boot_message)
        # Not shown unconditionally: with the auto-hide on, the bar only appears
        # once League's in-game window is up.
        self.overlay.refresh_visibility()

        # Riot data needs the network; load it off the UI thread so the window
        # appears immediately.
        threading.Thread(target=self._bootstrap_assets, name="Bootstrap",
                         daemon=True).start()

        self.ui_timer = QTimer()
        self.ui_timer.setInterval(UI_REFRESH_MS)
        self.ui_timer.timeout.connect(self._refresh_ui)
        self.ui_timer.start()

        self.drain_timer = QTimer()
        self.drain_timer.setInterval(DRAIN_MS)
        self.drain_timer.timeout.connect(self._drain_results)
        self.drain_timer.start()

        # Somebody launching Flashwatch again is asking for its window, not for a
        # second copy. The one that stands down leaves a knock; this is what
        # picks it up. A stat on a file that is almost never there, less often
        # than once a second -- next to the capture loop it costs nothing.
        self.knock_timer = QTimer()
        self.knock_timer.setInterval(single_instance.POLL_MS)
        self.knock_timer.timeout.connect(self._answer_knock)
        self.knock_timer.start()

        # Only runs while the trial mode is on.
        self.demo_timer = QTimer()
        self.demo_timer.setInterval(DEMO_TICK_MS)
        self.demo_timer.timeout.connect(self._tick_demo)

        # Started from a timer on the UI thread, which has an event loop, so this
        # one does fire.
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self._start_update_check)

        # First run: walk through the four things that decide whether any of this
        # works, none of which can be discovered by looking at the interface.
        # Delayed a moment so the window arrives after the tray icon rather than
        # on top of a half-built application.
        if not self.settings.get("onboarding_done"):
            QTimer.singleShot(GUIDE_DELAY_MS, self._show_guide)
        else:
            # Only when the guide is not taking the first run over. Both windows
            # at once is clutter, and the guide *is* the introduction -- it hands
            # over to the settings window itself when it is done.
            self._open_window_if_wanted()

    def _open_window_if_wanted(self) -> None:
        """Put the window on screen if this launch is meant to.

        Not delayed, unlike the guide: this is the answer to a double-click and
        it has to feel like one. Everything it shows is built by the time this
        runs, and the tray icon exists a few lines above it.
        """
        if self._should_open_window():
            self._show_control()

    def _should_open_window(self) -> bool:
        """Whether this launch should put the window on screen.

        Two ways to say no, and they are different questions. A login is not a
        launch -- Windows started this copy so it would be running before a game,
        not so somebody could look at it -- and that is decided by the command
        line rather than by the setting. The setting is for somebody who launches
        Flashwatch by hand and wants it to go straight to the tray anyway.
        """
        if autostart.started_by_windows():
            log.info("started by Windows, staying in the notification area")
            return False
        return bool(self.settings.get("open_window_on_launch", True))

    # ------------------------------------------------------------------
    def _connect_ui(self) -> None:
        self.control.redetect_requested.connect(self._on_redetect)
        self.control.manual_region_requested.connect(self._on_pick_region)
        self.control.test_mode_toggled.connect(self._on_test_mode)
        self.control.region_cleared.connect(self._on_clear_region)
        self.control.reset_requested.connect(self._on_reset)
        self.control.overlay_visibility_toggled.connect(self._on_overlay_visible)
        self.control.overlay_lock_toggled.connect(self._on_overlay_locked)
        self.control.settings_changed.connect(self._on_settings_changed)
        self.control.hidden_to_tray.connect(self._on_hidden_to_tray)
        self.control.guide_requested.connect(self._show_guide)
        self.control.self_test_requested.connect(self._on_self_test)
        self.control.recentre_requested.connect(self._on_recentre)
        self.control.demo_toggled.connect(self._on_demo_toggled)
        self.control.language_changed.connect(self._on_language_changed)
        self.control.quit_requested.connect(self.quit)
        self.control.update_requested.connect(self._on_install_update)
        self.control.update_notes_requested.connect(self._on_update_notes)
        self.control.update_skipped.connect(self._on_update_skipped)
        self.control.update_check_requested.connect(
            lambda: self._start_update_check(manual=True))
        self.control.sfx_preview_requested.connect(self.notifier.preview)

    def _build_tray(self) -> None:
        """Build the tray icon and its menu.

        Every action is created through ``menu.addAction(...)`` so the menu owns
        it, and the menu itself is stored on the instance. Creating QActions as
        locals and passing them to ``addAction`` does *not* transfer ownership in
        PySide6, so they get garbage-collected the moment this method returns --
        which silently emptied most of this menu, including Quitter.
        """
        self.tray = QSystemTrayIcon(make_tray_icon(), self.app)
        self.tray_menu = QMenu()
        self._fill_tray_menu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _fill_tray_menu(self) -> None:
        """(Re)build the menu entries. Called again when the language changes."""
        # The version is in the tooltip and the log rather than in a dialog: the
        # first question when something misbehaves is which build it is.
        self.tray.setToolTip(f"{tr('app.tray_tooltip')}  v{__version__}")
        self.tray_menu.clear()

        self.action_overlay = self.tray_menu.addAction(tr("tray.overlay"))
        self.action_overlay.setCheckable(True)
        self.action_overlay.setChecked(bool(self.settings.get("overlay_visible")))
        self.action_overlay.toggled.connect(self._on_overlay_visible)

        self.action_lock = self.tray_menu.addAction(tr("tray.lock"))
        self.action_lock.setCheckable(True)
        self.action_lock.setChecked(bool(self.settings.get("overlay_locked")))
        self.action_lock.toggled.connect(self._on_overlay_locked)

        self.actions_test: dict[str, QAction] = {}
        for zone in ZONES:
            action = self.tray_menu.addAction(tr(TRAY_TEST_KEYS[zone]))
            action.setCheckable(True)
            action.setChecked(zone in self.zone_frames)
            action.toggled.connect(
                lambda checked, z=zone: self._on_test_mode_from_tray(z, checked))
            self.actions_test[zone] = action

        self.tray_menu.addSeparator()
        self.tray_menu.addAction(tr("tray.settings")).triggered.connect(
            self._show_control)
        self.tray_menu.addAction(tr("tray.guide")).triggered.connect(
            self._show_guide)
        self.tray_menu.addAction(tr("tray.recentre")).triggered.connect(
            self._on_recentre)
        self.action_demo = self.tray_menu.addAction(tr("tray.demo"))
        self.action_demo.setCheckable(True)
        self.action_demo.setChecked(self._demo)
        self.action_demo.toggled.connect(self._on_demo_toggled)
        self.tray_menu.addAction(tr("tray.redetect")).triggered.connect(
            self._on_redetect)
        self.tray_menu.addAction(tr("tray.reset")).triggered.connect(
            self._on_reset)

        self.tray_menu.addSeparator()
        self.tray_menu.addAction(tr("tray.quit")).triggered.connect(self.quit)

    def _on_hidden_to_tray(self) -> None:
        """Say where the window went, once.

        The close button hides rather than quits, which is only obvious if you
        already know the program lives in the tray. Shown a single time: after
        that the user knows, and a balloon on every close is nagging.
        """
        if self.settings.get("tray_hint_shown"):
            return
        self.settings.set("tray_hint_shown", True)
        self.tray.showMessage("Flashwatch", tr("notify.hidden_to_tray"),
                              self.tray.icon(), 6000)

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_control()

    def _show_control(self) -> None:
        self.control.show()
        self.control.raise_()
        self.control.activateWindow()

    def _answer_knock(self) -> None:
        """Another copy was launched: show this one's window instead.

        Deliberately the same thing a double-click on the tray icon does. A
        second launch and a double-click are the same request -- *let me see it*
        -- and answering them differently would be two behaviours to learn.
        """
        if single_instance.take_knock():
            self._show_control()

    # ------------------------------------------------------------------
    def _install_hotkeys(self) -> None:
        """Optional global shortcuts.

        Off by default and never required: the application is designed to need
        no key presses during a game. This only *listens* -- it never sends any
        input, so it cannot affect gameplay.
        """
        if not self.settings.get("hotkeys_enabled"):
            return
        try:
            import keyboard
        except ImportError:
            log.info("keyboard library unavailable, hotkeys disabled")
            return
        try:
            keyboard.add_hotkey(
                "f8", lambda: self._invoke_on_ui(
                    lambda: self._on_overlay_locked(
                        not bool(self.settings.get("overlay_locked")))))
            keyboard.add_hotkey(
                "f9", lambda: self._invoke_on_ui(self._on_reset))
            log.info("hotkeys active: F8 verrouillage, F9 reinitialisation")
        except Exception as exc:                      # noqa: BLE001
            # Registering global hooks can fail without elevation.
            log.warning("could not register hotkeys (%s)", exc)

    def _invoke_on_ui(self, callback) -> None:
        """Hop from the keyboard hook's thread onto the Qt thread."""
        self._invoker.post(callback)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    # Nothing here installs anything on its own. The check reports, the banner
    # offers, and the download only starts once the button is pressed -- a program
    # that watches the screen during a game is the last thing that should be
    # replacing its own executable unasked.
    def _start_update_check(self, *, manual: bool = False) -> None:
        if self._update_busy:
            # An install is already running. Reported rather than ignored: the
            # button disables itself when pressed and something has to put it back.
            if manual:
                self.control.set_check_result(tr("update.installing"))
            return
        if not manual and not self.settings.get("update_check_enabled"):
            return
        if self._exe is None:
            # Running from source: there is no packaged build to swap, and the
            # answer to an out-of-date checkout is git.
            if manual:
                self.control.set_check_result(tr("ui.update_from_source"))
            return
        threading.Thread(target=self._run_update_check, args=(manual,),
                         name="UpdateCheck", daemon=True).start()

    def _run_update_check(self, manual: bool) -> None:
        """One request to GitHub, off the UI thread."""
        release = updater.fetch_latest()
        self._invoker.post(lambda: self._on_check_finished(release, manual))

    def _on_check_finished(self, release, manual: bool) -> None:
        newer = (release is not None
                 and updater.is_newer(release.version, __version__))

        if manual:
            if release is None:
                self.control.set_check_result(tr("ui.update_unavailable"))
                return
            self.control.set_check_result(
                tr("update.available", version=release.version) if newer
                else tr("ui.update_up_to_date"))
        if not newer:
            return
        # A version the user passed on stays passed on -- but only that exact
        # one, and only for the automatic check. Asking explicitly overrides it.
        if not manual and release.version == str(
                self.settings.get("update_skipped_version") or ""):
            log.info("update %s was skipped by the user", release.version)
            return

        log.info("update available: %s (running %s)", release.version, __version__)
        self._pending_release = release
        self.control.show_update(release.version, __version__)
        if not manual:
            # The window is usually not open at start-up, so the balloon is the
            # only thing that would be seen.
            self.tray.showMessage(
                "Flashwatch", tr("update.available", version=release.version),
                self.tray.icon(), 8000)

    def _on_install_update(self) -> None:
        release = self._pending_release
        if release is None or self._update_busy or self._exe is None:
            return
        if not updater.can_install(self._exe):
            # Program Files, a network share, a read-only stick. Nothing to do
            # about it from here, so say where the file would have to go.
            self.control.set_update_message(
                tr("update.read_only", folder=str(self._exe.parent)))
            return
        self._update_busy = True
        self._update_percent = -1
        self.control.set_update_progress(0)
        threading.Thread(target=self._run_update, args=(release, self._exe),
                         name="UpdateInstall", daemon=True).start()

    def _run_update(self, release, target) -> None:
        """Download, verify, swap. Off the UI thread; reports back by posting."""
        try:
            staged = updater.download(release, updater.staged_path(target),
                                      progress=self._on_update_progress)
            self._invoker.post(
                lambda: self.control.set_update_message(tr("update.installing")))
            updater.install(staged, target)
        except updater.UpdateError as exc:
            log.warning("update to %s failed (%s)", release.version, exc)
            self._invoker.post(lambda message=str(exc):
                               self._on_update_failed(message))
            return
        self._invoker.post(lambda: self._finish_update(target))

    def _on_update_progress(self, done: int, total: int) -> None:
        """Called per chunk from the download thread; posts per whole percent.

        The difference matters: 80 MB in 256 KB chunks is a few hundred calls, and
        posting each one would queue that many repaints of a label that can only
        show a hundred distinct values.
        """
        percent = int(done * 100 / total) if total > 0 else 0
        if percent == self._update_percent:
            return
        self._update_percent = percent
        self._invoker.post(lambda value=percent:
                           self.control.set_update_progress(value))

    def _on_update_failed(self, message: str) -> None:
        self._update_busy = False
        self.control.set_update_message(
            f"{tr('update.failed', error=message)} {tr('update.failed_hint')}",
            offer=True)

    def _finish_update(self, target) -> None:
        """Hand over to the executable that has just taken this one's place."""
        self.overlay.save_geometry()
        self.settings.save()
        # Before the launch, not after: the replacement checks the same
        # single-instance token this copy is holding, and would refuse to start
        # while it is still held.
        release_single_instance()
        if updater.relaunch(target):
            self.control.set_update_message(tr("update.restarting"))
            log.info("restarting into %s", target)
            # Long enough for the message to be painted before the window goes.
            QTimer.singleShot(600, self.quit)
            return
        self.control.set_update_message(tr("update.restart_manually"))
        self._update_busy = False

    def _on_update_notes(self) -> None:
        release = self._pending_release
        QDesktopServices.openUrl(QUrl(
            release.page_url if release is not None else updater.RELEASES_PAGE))

    def _on_update_skipped(self) -> None:
        release = self._pending_release
        if release is not None:
            self.settings.set("update_skipped_version", release.version)
            log.info("%s will not be offered again", release.version)
        self.control.hide_update()

    # ------------------------------------------------------------------
    def _bootstrap_assets(self) -> None:
        """Load Riot data, then start the capture worker."""
        try:
            self.assets.bootstrap(progress=self._set_boot_message)
        except Exception as exc:                      # noqa: BLE001
            log.exception("asset bootstrap failed")
            self._set_boot_message(tr("boot.error", error=exc))
            return

        self.parser = MessageParser(self.assets)
        self.timers = TimerManager(self.assets, self.settings)
        self.worker = CaptureWorker(self.settings, self.parser, self.results)

        saved = self.settings.get("chat_region")
        if self.settings.get("chat_region_locked") and saved:
            try:
                x, y, w, h = (int(v) for v in saved)
                self.worker.set_manual_region(
                    ChatRegion(x, y, w, h, source="manual", confirmed=True))
            except (TypeError, ValueError):
                pass

        clock_region = self._saved_region("clock_region")
        if clock_region is not None:
            # A validated clock area is read from the start: its value is used, so
            # there is nothing to wait for.
            self.worker.set_probe(ZONE_CLOCK, clock_region)

        self._sync_role_zones()

        if self.zone_frames:
            # A frame was opened while the assets were still loading. Reading it
            # touches Qt, so hop back to the UI thread for that.
            QTimer.singleShot(0, self._resync_test_mode)

        self.worker.start()
        self._set_boot_message(tr("boot.waiting"))

        # Icons are only needed for display, so fetch them after capture starts.
        try:
            self.assets.download_icons(progress=self._set_boot_message)
        except Exception as exc:                      # noqa: BLE001
            log.warning("icon download failed (%s)", exc)
        self._set_boot_message(tr("boot.waiting"))

    def _set_boot_message(self, message: str) -> None:
        self._boot_message = message
        log.info("%s", message)

    # ------------------------------------------------------------------
    def _drain_results(self) -> None:
        if self.timers is None:
            return
        latest_status = None
        while True:
            try:
                payload = self.results.get_nowait()
            except queue.Empty:
                break

            if payload.get("session_changed"):
                self.timers.reset(reason="session changed")
                self._known_champions.clear()
                self._applied_roles = {}
                self.control.clear_team()

            if payload.get("frame_counted"):
                self.timers.note_frame()

            events = payload.get("events") or []
            if events:
                started = self.timers.handle_events(events)
                for timer in started:
                    # The "?" is spelled out here. The overlay draws it as a chip
                    # on the spell icon, which this list has no room for, and a
                    # plain text log of events should still say which ones were
                    # only inferred.
                    mark = "?" if timer.uncertain else ""
                    self.control.add_event(
                        f"{timer.champion_name} - {timer.spell_name} "
                        f"({mark}{timer.display()})")
                self._sync_team()
            latest_status = payload.get("status") or latest_status

        if latest_status is not None:
            self._latest_status = latest_status

    def _sync_team(self) -> None:
        if self.timers is None:
            return
        # The roster, not just the champions with a live timer: once the loading
        # screen has been read the whole enemy team is known, and the list is far
        # more useful five names deep than one.
        ids = self.timers.roster()
        fresh = [cid for cid in ids if cid not in self._known_champions]
        if fresh:
            self._known_champions.update(fresh)
            self.control.sync_team(fresh, self._on_role_changed)
        for champion_id in ids:
            role = self.timers.role_of(champion_id)
            if role:
                self.control.set_role_display(champion_id, role)

    def _on_role_changed(self, champion_id: str, role: str) -> None:
        if self.timers is not None:
            self.timers.set_role(champion_id, role)

    # ------------------------------------------------------------------
    # The enemy's lanes, read off the screen
    # ------------------------------------------------------------------
    def _sync_role_zones(self) -> None:
        """Point the worker at the loading screen and the scoreboard, or not.

        Called whenever the setting or either rectangle changes. Dropping the
        regions rather than leaving the worker to check the setting on every pass
        is what makes "off" cost nothing at all.
        """
        if self.worker is None:
            return
        wanted = bool(self.settings.get("auto_roles", True))
        for zone in ROLE_ZONES:
            region = (self._saved_region(SETTING_FOR_ZONE[zone]) if wanted
                      else None)
            self.worker.set_role_region(zone, region)

    def _apply_read_roles(self, status) -> None:
        """Take the lanes the worker read and give them to the timers.

        The worker only ever offers a reading two separate looks agreed on, so
        there is nothing left to vet here; what this decides is when to stop
        looking, which is as soon as the whole team is known.
        """
        if self.timers is None or not self.settings.get("auto_roles", True):
            return

        if self._applied_roles and not self.timers.roster():
            # The timers cleared themselves without going through this class --
            # a game restart worked out from the clock alone. The team we applied
            # belongs to the game that just ended, so forget it and ask for a
            # fresh look rather than putting the old one back.
            self._applied_roles = {}
            if self.worker is not None:
                self.worker.set_roles_wanted(True)
            return

        if not status.roles or status.roles == self._applied_roles:
            return
        self._applied_roles = dict(status.roles)
        if self.timers.set_roles(status.roles, source=status.roles_source):
            self._sync_team()
        if len(status.roles) >= len(ROLES) and self.worker is not None:
            # Every lane is filled in. Reading on would spend a capture and an
            # icon comparison every couple of seconds to learn nothing.
            self.worker.set_roles_wanted(False)

    # ------------------------------------------------------------------
    def _refresh_ui(self) -> None:
        if self.timers is None:
            self.overlay.set_status(self._boot_message)
            return

        for note in self.timers.tick():
            if note.kind == "warning":
                self.notifier.warning()
            else:
                self.notifier.ready()

        snapshot = self.timers.snapshot()
        self.overlay.set_timers(snapshot)

        status = getattr(self, "_latest_status", None)
        if status is None:
            self.overlay.set_status(self._boot_message)
            return

        self.overlay.set_game_active(bool(status.in_game))

        # A real game outranks the trial: from here on the screen has actual
        # cooldowns to show, and the overlay has to be click-through again.
        if self._demo and status.in_game:
            self._end_demo_for_game()

        if status.game_clock is not None:
            # The clock area was validated and reads cleanly: that is the game
            # time itself, so it outranks anything inferred from chat timestamps.
            self.timers.note_clock(status.game_clock)

        self._apply_read_roles(status)

        for zone, frame in self.zone_frames.items():
            if not frame.isVisible():
                continue
            rows = (status.rows if zone == ZONE_CHAT
                    else status.probe_rows.get(zone, []))
            frame.set_feedback(rows, exploring=status.exploring,
                               note=f"{status.last_ocr_ms:.0f} ms",
                               roles=status.role_notes.get(zone, ""))

        if snapshot:
            # Timers take over the display; a stale status line must not linger
            # on top of them.
            self.overlay.set_status("")
        elif not status.in_game:
            self.overlay.set_status(status.error or status.game)
        else:
            self.overlay.set_status(tr("overlay.nothing_yet"))

        if self.control.isVisible():
            clock = self.timers.estimated_game_time()
            clock_text = ("-" if clock is None
                          else f"{int(clock) // 60}:{int(clock) % 60:02d}")
            ocr_text = tr("ui.ocr_summary", runs=status.ocr_runs,
                          ms=status.last_ocr_ms,
                          skipped=status.skip_ratio * 100)
            self.control.update_status(
                game=status.error or status.game,
                region=status.region,
                ocr=ocr_text,
                timers=self.timers.active_count(),
                clock=clock_text,
                state=self._ui_state(status),
            )
            self.control.update_debug(status.lines, status.near_misses,
                                      status.colour_rejected)

    def _ui_state(self, status) -> str:
        """Which of the five states the control window's pill should show.

        Decided here rather than in the window: this is where the difference
        between "the client is up" and "nothing is running" is actually known.
        """
        if self._demo:
            # Said before anything else: what is on screen is not real, and that
            # is the one thing somebody reading this window has to know.
            return "demo"
        if self.timers is None or not self.assets.ready:
            return "loading"
        if status.error:
            return "error"
        if status.in_game:
            return "in_game"
        if status.client_running:
            return "client"
        return "waiting"

    # ------------------------------------------------------------------
    # The self-test
    # ------------------------------------------------------------------
    def _on_self_test(self, *, guide: bool = False) -> None:
        """Read the shipped sample frame, then start the timers it names.

        Handed to the capture worker rather than run here: it owns the loaded OCR
        engine, and reading the sample takes about a second -- long enough to
        freeze a window if it happened on the Qt thread.

        ``guide`` says which surface asked, and therefore which one is answered.
        Both offer the test and the verdict belongs where it was asked for.
        """
        if self.worker is None or self.timers is None or not self.assets.ready:
            # Reported through the same path as any other failure, so both
            # surfaces already know how to show it.
            self._report_self_test(
                self_test.SelfTestResult(error=tr("ui.test_not_ready")),
                guide=guide)
            return
        self.worker.request_self_test(
            lambda result: self._invoker.post(
                lambda: self._finish_self_test(result, guide=guide)))

    def _finish_self_test(self, result, *, guide: bool = False) -> None:
        """Back on the Qt thread with the verdict: start timers, then report."""
        if self.timers is None:
            return
        started: dict[tuple[str, str], str] = {}
        if result.events:
            # force: priming counts *captured* frames, so with League closed it
            # would never end and these events would be dropped in silence. Only
            # these -- a game's own chat history stays primed away.
            fresh = self.timers.handle_events(result.timer_events(), force=True)
            for timer in fresh:
                started[timer.key] = timer.display()
                self.control.add_event(f"{timer.champion_name} - "
                                       f"{timer.spell_name} ({timer.display()})")
            self._sync_team()
        self._report_self_test(result, started, guide=guide)

    def _report_self_test(self, result, started: dict | None = None, *,
                          guide: bool = False) -> None:
        """Show a verdict on whichever surface asked for it, if it is still open."""
        started = started or {}
        if guide:
            if self.guide is not None:
                self.guide.show_test_result(result, started)
            return
        self.control.show_test_result(result, started)

    # ------------------------------------------------------------------
    def _on_redetect(self) -> None:
        if self.worker is not None:
            self.settings.set("chat_region_locked", False)
            self.settings.set("chat_region", None)
            self.worker.set_manual_region(None)
            self.worker.request_redetect()

    def _on_clear_region(self) -> None:
        self.settings.set("chat_region", None)
        self.settings.set("chat_region_locked", False)
        if self.worker is not None:
            self.worker.set_manual_region(None)
            self.worker.request_redetect()

    def _on_pick_region(self) -> None:
        self.picker = RegionPicker()
        self.picker.region_selected.connect(self._on_region_selected)
        self.picker.start()

    def _on_region_selected(self, region: ChatRegion) -> None:
        self.settings.update({
            "chat_region": region.as_list(),
            "chat_region_locked": True,
        })
        if self.worker is not None:
            self.worker.set_manual_region(region)
        log.info("manual chat region set: %s", region.describe())

    # ------------------------------------------------------------------
    # Test mode: live frames the user drags onto the areas to read
    # ------------------------------------------------------------------
    # Four areas, one frame each, all placed the same way. Only the chat is
    # detected automatically; the clock, the scoreboard and the loading screen
    # have no reliable signature to search for -- and the loading screen is gone
    # before anything could confirm a guess about it -- so being able to point at
    # them by hand *is* the feature rather than a fallback.
    def _on_test_mode_from_tray(self, zone: str, enabled: bool) -> None:
        """Route the tray entry through the button, so both stay in step."""
        self.control.sync_test_mode(zone, enabled)
        self._on_test_mode(zone, enabled)

    def _on_test_mode(self, zone: str, enabled: bool) -> None:
        self._sync_test_action(zone, enabled)

        if zone == ZONE_CHAT and self.worker is not None:
            self.worker.set_test_mode(enabled)

        existing = self.zone_frames.get(zone)
        if not enabled:
            if existing is not None:
                # Closing routes through the frame's cancel path, which restores
                # whatever the region was before the test started.
                existing.cancelled.emit()
                existing.close()
            return
        if existing is not None:
            return

        if zone == ZONE_CHAT:
            self._region_before_test = (
                self.settings.get("chat_region"),
                bool(self.settings.get("chat_region_locked")))

        frame = ZoneFrame(zone)
        frame.region_changed.connect(
            lambda region, z=zone: self._on_test_region_changed(z, region))
        frame.applied.connect(
            lambda region, z=zone: self._on_test_applied(z, region))
        frame.cancelled.connect(lambda z=zone: self._on_test_cancelled(z))
        frame.closed.connect(lambda z=zone: self._on_test_frame_closed(z))
        self.zone_frames[zone] = frame
        frame.start(self._starting_region(zone))
        # The frame owns the region while it is up, so nothing else may move it
        # underneath the user.
        self._on_test_region_changed(zone, frame.region())

    def _sync_test_action(self, zone: str, enabled: bool) -> None:
        action = self.actions_test.get(zone)
        if action is None:
            return
        action.blockSignals(True)
        action.setChecked(enabled)
        action.blockSignals(False)

    def _saved_region(self, key: str) -> ChatRegion | None:
        saved = self.settings.get(key)
        if not isinstance(saved, (list, tuple)) or len(saved) != 4:
            return None
        try:
            x, y, w, h = (int(v) for v in saved)
        except (TypeError, ValueError):
            return None
        return ChatRegion(x, y, w, h, source="manual", confirmed=True)

    def _screen_rect(self) -> tuple[int, int, int, int]:
        """The primary screen in *native* pixels, as a window rect would be.

        Scaled by the device pixel ratio deliberately: everything read off the
        screen is captured in native pixels, so a 150%-scaled 4K desktop must
        report 3840 wide and not the 2560 Qt works in.
        """
        screen = self.app.primaryScreen()
        area = screen.geometry() if screen is not None else None
        if area is None:
            return (0, 0, 1920, 1080)
        ratio = float(screen.devicePixelRatio())
        return (int(area.x() * ratio), int(area.y() * ratio),
                int(area.width() * ratio), int(area.height() * ratio))

    def _seed_zones_for_screen(self) -> None:
        """Put the hand-placed areas where this screen keeps them, once.

        The shipped defaults are 1920x1080 pixel rectangles, so on any other
        screen they point at nothing: the clock probe would read empty pixels
        every 0.9s for the life of the install, and the framing tool would open
        far from the thing to frame. Both areas sit at a fixed *place* in League's
        HUD, so the fraction carries across resolutions where the pixel count
        does not.

        First run only, and only for the areas in the table -- a value the user
        has placed by hand is never touched, and the chat region is not scaled at
        all (see settings.ZONE_FRACTIONS for why a plausible wrong chat seed is
        worse than none).
        """
        window = self._screen_rect()
        values = {key: settings_module.scaled_region(key, window)
                  for key in settings_module.ZONE_FRACTIONS}
        if values == {key: list(self.settings.get(key) or [])
                      for key in values}:
            return
        self.settings.update(values)
        log.info("seeded the hand-placed areas for a %dx%d screen: %s",
                 window[2], window[3], values)

    def _starting_region(self, zone: str) -> ChatRegion:
        """Where to put a frame when it opens.

        Always the saved rectangle when there is one -- reopening a zone must
        land where the user left it. Otherwise a guess based on where that thing
        normally sits in the client area, which is only ever a starting point:
        the frame exists precisely because the app cannot know.
        """
        saved = self._saved_region(SETTING_FOR_ZONE[zone])
        if saved is not None:
            return saved

        status = getattr(self, "_latest_status", None)
        window = status.window_rect if status is not None else None
        if window is None:
            window = self._screen_rect()
        # The clock and the scoreboard have one guess each, and it is the same
        # table that seeds them on a fresh install: a frame that opened somewhere
        # else than where the shipped default points would be two answers to one
        # question. (It used to put the clock top *centre*, which is not where
        # League draws it -- the timer sits at the top right, beside the minimap.)
        scaled = settings_module.scaled_region(SETTING_FOR_ZONE[zone], window)
        if scaled is not None:
            x, y, w, h = scaled
            return ChatRegion(x, y, w, h, source="manual", confirmed=True)

        # Chat: what is being read right now beats any guess.
        if status is not None and status.region_rect:
            x, y, w, h = status.region_rect
            return ChatRegion(x, y, w, h, source="manual", confirmed=True)
        x, y, w, h = chat_detector.search_band(window)
        return ChatRegion(x, y, w, h, source="manual", confirmed=True)

    def _resync_test_mode(self) -> None:
        """Re-apply the open frames to a worker that only appeared afterwards."""
        if self.worker is None:
            return
        for zone, frame in self.zone_frames.items():
            if zone == ZONE_CHAT:
                self.worker.set_test_mode(True)
                self.worker.set_manual_region(frame.region())
            else:
                self.worker.set_probe(zone, frame.region())
                if zone in ROLE_ZONES:
                    self.worker.set_role_region(zone, frame.region())

    def _on_test_region_changed(self, zone: str, region: ChatRegion) -> None:
        """Point the worker at the frame, without persisting anything yet."""
        if self.worker is None:
            return
        if zone == ZONE_CHAT:
            self.worker.set_manual_region(region)
        else:
            self.worker.set_probe(zone, region)
        if zone in ROLE_ZONES:
            # The reader follows the frame too, so the footer can say which
            # champions the rectangle currently covers. Looking is switched back
            # on for the same reason: somebody framing this area wants to see it
            # working, whether or not the team is already known.
            self.worker.set_role_region(zone, region)
            self.worker.set_roles_wanted(True)

    def _on_test_applied(self, zone: str, region: ChatRegion) -> None:
        if zone == ZONE_CHAT:
            self.settings.update({
                "chat_region": region.as_list(),
                "chat_region_locked": True,
            })
            if self.worker is not None:
                self.worker.set_manual_region(region)
            self._region_before_test = None
        else:
            self.settings.set(SETTING_FOR_ZONE[zone], region.as_list())
            if self.worker is not None:
                self.worker.set_probe(zone, region)
            self._sync_role_zones()
        log.info("test mode: %s region validated %s", zone, region.describe())
        self.tray.showMessage(
            "Flashwatch",
            tr("notify.zone_saved", width=region.width, height=region.height),
            QSystemTrayIcon.Information, 3000)

    def _on_test_cancelled(self, zone: str) -> None:
        """Put back whatever was in use before the frame appeared."""
        if zone != ZONE_CHAT:
            # Nothing was persisted while dragging, so restoring is just a matter
            # of pointing the worker back at the saved rectangle, if any.
            if self.worker is not None:
                self.worker.set_probe(zone, self._probe_after_close(zone))
            self._sync_role_zones()
            log.info("test mode: %s cancelled", zone)
            return

        previous = self._region_before_test
        self._region_before_test = None
        if previous is None:
            return
        saved, locked = previous
        self.settings.update({"chat_region": saved, "chat_region_locked": locked})
        if self.worker is None:
            return
        if locked and isinstance(saved, (list, tuple)) and len(saved) == 4:
            x, y, w, h = (int(v) for v in saved)
            self.worker.set_manual_region(
                ChatRegion(x, y, w, h, source="manual", confirmed=True))
        else:
            self.worker.set_manual_region(None)
            self.worker.request_redetect()
        log.info("test mode: cancelled, previous region restored")

    def _probe_after_close(self, zone: str) -> ChatRegion | None:
        """What the worker should keep reading once a frame is closed.

        Only the clock. The two team areas are read as well, and go on being read
        after the frame closes -- but through the role reader rather than as
        probes, since a probe is an OCR pass and the scoreboard needs an icon
        comparison instead. See :meth:`_sync_role_zones`.
        """
        if zone != ZONE_CLOCK:
            return None
        return self._saved_region("clock_region")

    def _on_test_frame_closed(self, zone: str) -> None:
        self.zone_frames.pop(zone, None)
        if self.worker is not None:
            if zone == ZONE_CHAT:
                self.worker.set_test_mode(False)
            else:
                self.worker.set_probe(zone, self._probe_after_close(zone))
                self._sync_role_zones()
        self.control.sync_test_mode(zone, False)
        self._sync_test_action(zone, False)

    def _on_reset(self) -> None:
        if self.timers is not None:
            self.timers.reset(reason="manual reset")
        self._known_champions.clear()
        self._applied_roles = {}
        self.control.clear_team()
        # The reset cleared the roles with everything else, so start looking for
        # them again -- otherwise pressing it in a game whose team had already
        # been read would leave every lane unknown until the next match.
        if self.worker is not None:
            self.worker.set_roles_wanted(True)

    def _on_overlay_visible(self, visible: bool) -> None:
        self.settings.set("overlay_visible", visible)
        self.overlay.refresh_visibility()
        if visible and not self.overlay.isVisible():
            # Enabling it outside a game looks like nothing happened; say why.
            self.tray.showMessage("Flashwatch", tr("notify.bar_in_game_only"),
                                  QSystemTrayIcon.Information, 4000)
        self.action_overlay.setChecked(visible)
        self.control.sync_overlay_toggles(
            visible=visible, locked=bool(self.settings.get("overlay_locked")))

    def _on_overlay_locked(self, locked: bool) -> None:
        self.settings.set("overlay_locked", locked)
        self.overlay.apply_lock(locked)
        self.action_lock.setChecked(locked)
        self.control.sync_overlay_toggles(
            visible=bool(self.settings.get("overlay_visible")), locked=locked)

    def _on_recentre(self) -> None:
        self.overlay.place_default()
        self.overlay.update()

    # ------------------------------------------------------------------
    # The setup guide
    # ------------------------------------------------------------------
    def _show_guide(self, step: int = 0) -> None:
        """Open the guide, or bring the open one back to the front.

        One window at a time, kept on the instance: a second copy would be
        editing the same settings behind the first one's back.
        """
        if self.guide is None:
            self.guide = Onboarding(self.settings)
            self.guide.finished.connect(self._on_guide_finished)
            self.guide.language_changed.connect(self._on_language_changed)
            self.guide.layout_changed.connect(self._on_layout_changed)
            self.guide.settings_changed.connect(self._on_guide_tuned)
            self.guide.place_requested.connect(self._on_place_overlay)
            self.guide.chat_frame_requested.connect(
                lambda: self.control.button_test_mode.setChecked(True))
            self.guide.self_test_requested.connect(
                lambda: self._on_self_test(guide=True))
        if step:
            self.guide.show_step(step)
        self.guide.show()
        self.guide.raise_()
        self.guide.activateWindow()

    def _on_guide_finished(self) -> None:
        """Hand over to the settings window, on the page the guide left off at.

        Not a dead end: the last step is about the overlay, so the natural next
        move is the page that has the rest of its settings on it.
        """
        self.guide = None
        self.control.refresh_layout_choice()
        self.control.go_to_display_page()
        self._show_control()

    def _on_guide_tuned(self) -> None:
        """A knob was turned on the guide's tuning step.

        The settings window has to be told before the overlay is: it writes all
        of its controls in one go whenever any of them moves, so one left open
        behind the guide would undo this the next time it was touched.
        """
        self.control.refresh_display_settings()
        self._on_settings_changed()

    def _on_layout_changed(self, _key: str) -> None:
        """A display was picked: move the overlay onto its own geometry."""
        self.overlay.sync_layout()
        self.overlay.refresh_visibility()
        self.control.refresh_layout_choice()

    def _on_place_overlay(self) -> None:
        """Put the overlay on screen, unlocked, with something in it to aim at.

        Placing an empty display is possible but unpleasant -- there is nothing to
        judge the position against -- so this is the trial and the unlock
        together, which is what "place it now" means.

        Nothing races the user here. Unlocked, the overlay accepts mouse events,
        so a bar left unlocked *while playing* would swallow clicks over the game
        -- but that is a state to end when the game starts, which is exactly what
        happens, and not a reason to re-lock under somebody's cursor after twenty
        seconds.
        """
        if not self.settings.get("overlay_visible"):
            self._on_overlay_visible(True)
        self._on_demo_toggled(True)
        self._on_overlay_locked(False)
        self.overlay.raise_()

    # ------------------------------------------------------------------
    # Trial mode: judge and place the overlay with League closed
    # ------------------------------------------------------------------
    # This replaced a twenty-second "preview". Twenty seconds is enough to
    # confirm the overlay draws and nowhere near enough to do what somebody
    # actually opens it for -- compare the three displays, try a theme, drag the
    # thing where they want it and look at it again. So the trial simply stays on
    # until it is turned off, or until a real game arrives and takes over.
    def _on_demo_toggled(self, active: bool) -> None:
        if active and self.timers is None:
            # Riot's data is still downloading, so there are no champions to make
            # fake cooldowns out of. Said rather than ignored: a button that does
            # nothing reads as broken.
            self.control.sync_demo(False)
            self._sync_demo_action(False)
            self.tray.showMessage("Flashwatch", tr("notify.demo_loading"),
                                  QSystemTrayIcon.Information, 4000)
            return

        self._demo = active
        self.control.sync_demo(active)
        self._sync_demo_action(active)
        self.overlay.set_demo(active)

        if active:
            self.timers.add_demo(first=True)
            self.demo_timer.start()
        else:
            self.demo_timer.stop()
            if self.timers is not None:
                self.timers.clear_demo()
        if self.timers is not None:
            self.overlay.set_timers(self.timers.snapshot())
        self.overlay.update()
        log.info("trial mode %s", "on" if active else "off")

    def _tick_demo(self) -> None:
        """Keep the trial's cooldowns topped up, so the display stays alive.

        Entries that run out are purged like any other; putting them back with a
        full cooldown is what makes the trial a moving picture instead of a frozen
        one -- the colours keep crossing their thresholds while somebody watches.
        """
        if not self._demo or self.timers is None:
            return
        if self.timers.add_demo():
            self.overlay.set_timers(self.timers.snapshot())

    def _end_demo_for_game(self) -> None:
        """A real game appeared: the trial gets out of the way.

        This is also what puts the click-through back, which is why there is no
        timer racing the user any more: the risk was never "unlocked for too
        long", it was "unlocked while playing".
        """
        self._on_demo_toggled(False)
        if not self.settings.get("overlay_locked", True):
            self._on_overlay_locked(True)
        self.tray.showMessage("Flashwatch", tr("notify.demo_ended"),
                              QSystemTrayIcon.Information, 5000)

    def _sync_demo_action(self, active: bool) -> None:
        action = getattr(self, "action_demo", None)
        if action is None:
            return
        action.blockSignals(True)
        action.setChecked(active)
        action.blockSignals(False)

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------
    def _on_language_changed(self, language: str) -> None:
        """Apply a new language: rebuild the interface, reload Riot's data.

        Qt cannot re-translate labels in place, so the windows carrying them are
        rebuilt. The champion and spell names come from a different Data Dragon
        locale, which needs the network, so that part happens on a thread and is
        adopted when it lands -- the interface is already readable by then.
        """
        i18n.set_language(language)
        # Picking a language *inside the guide* is not the same event as picking
        # one in the settings, even though it is the same signal. In the guide it
        # is step one of seven: the reader is mid-sentence, and answering them
        # with a Windows toast and a settings window jumping to the front is the
        # application interrupting itself. So while the guide is up, the change
        # happens silently behind it.
        quiet = self.guide is not None and self.guide.isVisible()
        self._rebuild_interface(quiet=quiet)
        if not quiet:
            self.tray.showMessage("Flashwatch", tr("ui.language_reloading"),
                                  QSystemTrayIcon.Information, 3000)
        threading.Thread(target=self._reload_assets, name="Locale",
                         daemon=True).start()

    def _rebuild_interface(self, *, quiet: bool = False) -> None:
        """Replace the control window and tray menu with ones in the new language.

        ``quiet`` means: do it without anything coming to the front. The guide is
        on screen, it is the window the user is looking at, and it must still be
        the window the user is looking at when this returns.
        """
        previous = self.control
        was_visible = previous.isVisible()
        # Silence it first: its close event asks the application to quit, and a
        # window being replaced must not be able to do that. Blocking its signals
        # covers every route out of it, including that one.
        previous.blockSignals(True)
        previous.hide()
        previous.deleteLater()

        self.control = ControlWindow(self.settings, self.assets)
        self._connect_ui()
        # The team list starts empty again, so let the next sync refill it.
        self._known_champions.clear()
        self._applied_roles = {}
        self._sync_team()
        # A running trial belongs to the application, not to the window that
        # happened to start it: a fresh window would otherwise offer to start the
        # one already on screen.
        self.control.sync_demo(self._demo)
        # The banner belonged to the window that was just replaced. An offer the
        # user has not acted on has to survive changing language.
        if self._pending_release is not None and not self._update_busy:
            self.control.show_update(self._pending_release.version, __version__)
        if was_visible:
            if quiet:
                # Rebuilt, but left where it was: raising it would put it over
                # the guide the reader is still in the middle of.
                self.control.show()
            else:
                self._show_control()

        # The guide, if it is up, translates itself in place -- it draws every
        # word of itself at paint time, so there is nothing to rebuild and, more
        # to the point, nothing to close and reopen. It used to be replaced by a
        # fresh copy here, which is exactly what made choosing a language flash
        # the screen.
        if self.guide is not None:
            self.guide.retranslate()

        self._fill_tray_menu()
        self.overlay.icons.clear()
        self.overlay.update()

    def _reload_assets(self) -> None:
        """Fetch Riot's data in the new locale, off the UI thread."""
        locale = str(self.settings.get("locale", "en_US"))
        assets = RiotAssets(locale=locale)
        try:
            assets.bootstrap(progress=self._set_boot_message)
            assets.download_icons(progress=self._set_boot_message)
        except Exception as exc:                      # noqa: BLE001
            log.exception("could not reload assets for %s", locale)
            self._set_boot_message(tr("boot.error", error=exc))
            return
        # Posted, not QTimer.singleShot: this runs on a plain thread, where a
        # single-shot timer has no event loop to fire in and the newly loaded
        # assets were simply never adopted.
        self._invoker.post(lambda: self._adopt_assets(assets))

    def _adopt_assets(self, assets: RiotAssets) -> None:
        """Swap in freshly loaded data. Runs on the UI thread."""
        self.assets = assets
        if self.parser is not None:
            # A whole new parser rather than reindexing the live one: the capture
            # thread reads that index continuously, and swapping the reference is
            # atomic where rebuilding it in place would be read half-empty.
            self.parser = MessageParser(assets)
            if self.worker is not None:
                self.worker.parser = self.parser
        if self.timers is not None:
            self.timers.assets = assets
        self.overlay.assets = assets
        self.overlay.icons.clear()
        # Champion and spell names live on the timers themselves, so anything on
        # screen still carries the old language until it is re-read. Clearing is
        # honest: a stale name next to a live countdown looks like a bug.
        if self.timers is not None:
            self.timers.reset(reason="language changed")
        self._known_champions.clear()
        self._applied_roles = {}
        self._rebuild_interface()
        self._set_boot_message(tr("boot.waiting"))
        log.info("assets reloaded for %s", assets.locale)

    def _on_settings_changed(self) -> None:
        # Turning the role readers off has to actually stop them, not merely stop
        # the result being used: the point of the switch is the work it saves.
        self._sync_role_zones()
        # Before the repaint below, since it decides how tall a row is.
        self.overlay.sync_countdown_style()
        self.notifier.refresh()
        # Opacity is not set on the window any more -- it is painted into the
        # panel, so the repaint at the end of this method is what applies it.
        self.overlay.refresh_visibility()
        # Does nothing unless the chosen display actually changed, in which case
        # it files away the outgoing one's position and restores the new one's.
        self.overlay.sync_layout()
        self.overlay.update()

    # ------------------------------------------------------------------
    def run(self) -> int:
        return self.app.exec()

    def quit(self) -> None:
        log.info("shutting down")
        if self.worker is not None:
            self.worker.stop()
        self.overlay.save_geometry()
        self.settings.save()
        self.tray.hide()
        self.app.quit()


SINGLE_INSTANCE_NAME = single_instance.NAME

# Held for the life of the process. Module-level rather than a local in main()
# because the updater has to be able to let go of it early: the replacement
# executable checks the same token, and would refuse to start while this copy
# still holds it.
_instance_guard = None


def acquire_single_instance(name: str = SINGLE_INSTANCE_NAME):
    """Claim the "only one running" token, or return None if it is taken.

    The mechanism, and why it is two mechanisms, is in ``single_instance.py``.
    """
    return single_instance.acquire(name)


def release_single_instance() -> None:
    """Give up the "only one running" token, so a replacement may start.

    Idempotent: called once by the updater just before it launches the new
    executable, and again on the way out of main().
    """
    global _instance_guard
    token, _instance_guard = _instance_guard, None
    if token is not None:
        token.release()


def _warn_already_running() -> None:
    """Say why nothing happened, when nothing happened.

    Only reached if the knock went unanswered: the token is held by something
    that is not listening, so there is no window for this copy to hand over to
    and the user is owed an explanation. When the running copy *does* answer,
    this is not shown -- its window coming up is the answer.
    """
    try:
        import win32api
        import win32con
        win32api.MessageBox(0, tr("app.already_running"), tr("app.title"),
                            win32con.MB_OK | win32con.MB_ICONINFORMATION)
    except Exception as exc:                          # noqa: BLE001
        log.debug("could not show the already-running notice (%s)", exc)


def main() -> int:
    configure_logging()
    log.info("starting Flashwatch v%s", __version__)

    # Before the guard, so its message is in the user's language.
    i18n.set_language(str(Settings().get("locale", "en_US")))
    global _instance_guard
    _instance_guard = acquire_single_instance()
    if _instance_guard is None:
        # Launching again is how somebody asks for the window: it lives in the
        # notification area with no taskbar button, so "it is already running"
        # is an answer to a question nobody asked. Hand the request over to the
        # copy that has a window, and only complain if nobody takes it.
        log.warning("another instance is already running")
        if not single_instance.knock():
            _warn_already_running()
        return 0

    application = Application()
    try:
        return application.run()
    finally:
        # Held until here on purpose: releasing it early would let a second copy
        # start while this one is still up. The one exception is an update, which
        # releases it deliberately so its replacement can take over.
        release_single_instance()


if __name__ == "__main__":
    sys.exit(main())
