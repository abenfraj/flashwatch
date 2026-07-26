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

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QIcon, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import autostart
import chat_detector
import i18n
import settings as settings_module
import theme
import updater
from audio import Notifier
from chat_detector import ChatRegion
from i18n import tr
from message_parser import MessageParser
from ocr import CaptureWorker
from overlay import Overlay
from riot_assets import RiotAssets
from settings import Settings
from timer_manager import TimerManager
from ui import ControlWindow, RegionPicker
from version import __version__
from zone_overlay import (ZONE_CHAT, ZONE_CLOCK, ZONE_SCOREBOARD, ZONES,
                          ZoneFrame)

log = logging.getLogger(__name__)

UI_REFRESH_MS = 100          # overlay countdown smoothness
DRAIN_MS = 50                # how often the queue is emptied
LOG_PATH = settings_module.ASSETS_DIR / "flashwatch.log"

# How long after start-up the update check runs. Late enough that it never
# competes with loading Riot's data, early enough that the answer is there before
# the user has finished reading the settings window.
UPDATE_CHECK_DELAY_MS = 4000

# Where each hand-placed area is persisted.
SETTING_FOR_ZONE = {
    ZONE_CHAT: "chat_region",
    ZONE_CLOCK: "clock_region",
    ZONE_SCOREBOARD: "scoreboard_region",
}

# Labels for the tray entries that open each frame.
TRAY_TEST_KEYS = {
    ZONE_CHAT: "tray.test_mode",
    ZONE_CLOCK: "ui.test_mode_clock",
    ZONE_SCOREBOARD: "ui.test_mode_scoreboard",
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


def make_mark(size: int = 256) -> QPixmap:
    """Draw the Flashwatch mark, the same one the download page uses.

    Geometry comes from theme.py so this and the .ico drawn by build.py cannot
    say different things -- they had, quietly: this one used to have hairline
    strokes and no hub, which at 16px in the tray read as a smudged ring.

    Drawn at 256 and let Qt downscale, rather than drawn at 16: a 3-unit stroke
    on a 64-unit box is under one pixel at tray size, and rounding it up by hand
    gives a different shape at every size.
    """
    scale = size / theme.MARK_BOX
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    cx, cy = (v * scale for v in theme.MARK_CENTRE)
    radius = theme.MARK_DISC_R * scale
    painter.setBrush(QColor(*theme.MARK_DISC_RGB))
    painter.setPen(QPen(QColor(*theme.MARK_EDGE_RGB),
                        theme.MARK_DISC_STROKE * scale))
    painter.drawEllipse(QPointF(cx, cy), radius, radius)

    hands = QPen(QColor(*theme.MARK_HAND_RGB), theme.MARK_HAND_STROKE * scale)
    hands.setCapStyle(Qt.RoundCap)
    painter.setPen(hands)
    for (x1, y1), (x2, y2) in theme.MARK_HANDS:
        painter.drawLine(QPointF(x1 * scale, y1 * scale),
                         QPointF(x2 * scale, y2 * scale))

    hub = theme.MARK_HUB_R * scale
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(*theme.MARK_EDGE_RGB))
    painter.drawEllipse(QPointF(cx, cy), hub, hub)

    painter.end()
    return pixmap


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
        self.settings = Settings()
        settings_module.ensure_dirs()

        # Before anything with a label is built: the interface follows the League
        # client language chosen in the settings.
        i18n.set_language(str(self.settings.get("locale", "fr_FR")))

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
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

        self.assets = RiotAssets(locale=str(self.settings.get("locale", "fr_FR")))
        self.notifier = Notifier(self.settings)

        # Built after assets load, since both need champion data.
        self.parser: MessageParser | None = None
        self.timers: TimerManager | None = None
        self.worker: CaptureWorker | None = None

        self.results: queue.Queue = queue.Queue(maxsize=64)
        self.overlay = Overlay(self.settings, self.assets)
        self.control = ControlWindow(self.settings, self.assets)
        self.picker: RegionPicker | None = None
        # One test-mode frame per area being placed, keyed by zone.
        self.zone_frames: dict[str, ZoneFrame] = {}
        # What to put back if the chat test mode is cancelled.
        self._region_before_test: tuple[list[int] | None, bool] | None = None
        self._known_champions: set[str] = set()
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

        # Started from a timer on the UI thread, which has an event loop, so this
        # one does fire.
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self._start_update_check)

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
        self.control.recentre_requested.connect(self._on_recentre)
        self.control.preview_requested.connect(self._on_preview)
        self.control.language_changed.connect(self._on_language_changed)
        self.control.quit_requested.connect(self.quit)
        self.control.update_requested.connect(self._on_install_update)
        self.control.update_notes_requested.connect(self._on_update_notes)
        self.control.update_skipped.connect(self._on_update_skipped)
        self.control.update_check_requested.connect(
            lambda: self._start_update_check(manual=True))

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
        self.tray_menu.addAction(tr("tray.recentre")).triggered.connect(
            self._on_recentre)
        self.tray_menu.addAction(tr("tray.preview")).triggered.connect(
            self._on_preview)
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
                self.control.clear_team()

            if payload.get("frame_counted"):
                self.timers.note_frame()

            events = payload.get("events") or []
            if events:
                started = self.timers.handle_events(events)
                for timer in started:
                    self.control.add_event(
                        f"{timer.champion_name} - {timer.spell_name} "
                        f"({timer.display()})")
                self._sync_team()
            latest_status = payload.get("status") or latest_status

        if latest_status is not None:
            self._latest_status = latest_status

    def _sync_team(self) -> None:
        if self.timers is None:
            return
        ids = [t.champion_id for t in self.timers.snapshot()]
        fresh = [cid for cid in ids if cid not in self._known_champions]
        if fresh:
            self._known_champions.update(fresh)
            self.control.sync_team(fresh, self._on_role_changed)
        # Reflect roles the manager inferred, e.g. Smite implies jungle.
        for timer in self.timers.snapshot():
            if timer.role:
                self.control.set_role_display(timer.champion_id, timer.role)

    def _on_role_changed(self, champion_id: str, role: str) -> None:
        if self.timers is not None:
            self.timers.set_role(champion_id, role)

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

        if status.game_clock is not None:
            # The clock area was validated and reads cleanly: that is the game
            # time itself, so it outranks anything inferred from chat timestamps.
            self.timers.note_clock(status.game_clock)

        for zone, frame in self.zone_frames.items():
            if not frame.isVisible():
                continue
            rows = (status.rows if zone == ZONE_CHAT
                    else status.probe_rows.get(zone, []))
            frame.set_feedback(rows, exploring=status.exploring,
                               note=f"{status.last_ocr_ms:.0f} ms")

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
            )
            self.control.update_debug(status.lines, status.near_misses,
                                      status.colour_rejected)

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
    # Three areas, one frame each, all placed the same way. Only the chat is
    # detected automatically; the game clock and the scoreboard have no reliable
    # signature to search for, so being able to point at them by hand *is* the
    # feature rather than a fallback.
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
            screen = self.app.primaryScreen()
            area = screen.geometry() if screen is not None else None
            ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
            if area is None:
                window = (0, 0, 1920, 1080)
            else:
                window = (int(area.x() * ratio), int(area.y() * ratio),
                          int(area.width() * ratio), int(area.height() * ratio))
        left, top, width, height = window

        if zone == ZONE_CLOCK:
            # Top centre: the match timer sits in the middle of the top bar.
            box_w, box_h = int(width * 0.07), int(height * 0.035)
            return ChatRegion(left + (width - box_w) // 2, top + int(height * 0.01),
                              box_w, box_h, source="manual", confirmed=True)
        if zone == ZONE_SCOREBOARD:
            # The Tab panel covers the middle of the screen.
            box_w, box_h = int(width * 0.66), int(height * 0.5)
            return ChatRegion(left + (width - box_w) // 2,
                              top + int(height * 0.22), box_w, box_h,
                              source="manual", confirmed=True)

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

    def _on_test_region_changed(self, zone: str, region: ChatRegion) -> None:
        """Point the worker at the frame, without persisting anything yet."""
        if self.worker is None:
            return
        if zone == ZONE_CHAT:
            self.worker.set_manual_region(region)
        else:
            self.worker.set_probe(zone, region)

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

        The clock keeps being read, because its value is used. The scoreboard is
        stored but has no consumer yet, so reading it after the user has finished
        placing it would be pure cost.
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
        self.control.sync_test_mode(zone, False)
        self._sync_test_action(zone, False)

    def _on_reset(self) -> None:
        if self.timers is not None:
            self.timers.reset(reason="manual reset")
        self._known_champions.clear()
        self.control.clear_team()

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
        self.overlay.centre_at_top()
        self.overlay.update()

    def _on_preview(self) -> None:
        """Show fake timers briefly, so the overlay can be checked without a game."""
        if self.timers is None:
            return
        if not self.settings.get("overlay_visible"):
            self._on_overlay_visible(True)
        count = self.timers.add_preview()
        self.overlay.set_timers(self.timers.snapshot())
        if count:
            self.tray.showMessage("Flashwatch", tr("notify.preview"),
                                  QSystemTrayIcon.Information, 4000)

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
        self._rebuild_interface()
        self.tray.showMessage("Flashwatch", tr("ui.language_reloading"),
                              QSystemTrayIcon.Information, 3000)
        threading.Thread(target=self._reload_assets, name="Locale",
                         daemon=True).start()

    def _rebuild_interface(self) -> None:
        """Replace the control window and tray menu with ones in the new language."""
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
        # The team tab starts empty again, so let the next sync refill it.
        self._known_champions.clear()
        self._sync_team()
        # The banner belonged to the window that was just replaced. An offer the
        # user has not acted on has to survive changing language.
        if self._pending_release is not None and not self._update_busy:
            self.control.show_update(self._pending_release.version, __version__)
        if was_visible:
            self._show_control()

        self._fill_tray_menu()
        self.overlay.icons.clear()
        self.overlay.update()

    def _reload_assets(self) -> None:
        """Fetch Riot's data in the new locale, off the UI thread."""
        locale = str(self.settings.get("locale", "fr_FR"))
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
        self._rebuild_interface()
        self._set_boot_message(tr("boot.waiting"))
        log.info("assets reloaded for %s", assets.locale)

    def _on_settings_changed(self) -> None:
        self.overlay.setWindowOpacity(float(self.settings.get("overlay_opacity", 0.92)))
        self.overlay.refresh_visibility()
        if (self.settings.get("overlay_layout") == "bar"
                and not self.settings.get("bar_placed")):
            # Switched to the bar for the first time: give it sensible geometry
            # rather than the vertical panel's.
            self.overlay.centre_at_top()
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


SINGLE_INSTANCE_NAME = "Flashwatch.instance"

# Held for the life of the process. Module-level rather than a local in main()
# because the updater has to be able to let go of it early: the replacement
# executable checks the same token, and would refuse to start while this copy
# still holds it.
_instance_guard = None


def acquire_single_instance(name: str = SINGLE_INSTANCE_NAME):
    """Claim the "only one running" token, or return None if it is taken.

    Two copies would both OCR the same chat and both draw an overlay, and the
    second one is easy to start by accident: packaged as a single .exe there is
    no window and no cursor feedback for the first few seconds, so a second
    double-click while waiting is the obvious thing to do.

    A named mutex in the session namespace, so it disappears with the process
    however it dies -- a lock file would survive a crash and lock the user out.
    """
    try:
        import win32api
        import win32event
        import winerror
    except ImportError:                               # pragma: no cover
        return object()                               # cannot check; allow it
    handle = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        # A handle comes back even when the mutex already existed; closing it
        # keeps the refused copy from holding a reference to the token.
        if handle:
            win32api.CloseHandle(handle)
        return None
    return handle


def release_single_instance() -> None:
    """Give up the "only one running" token, so a replacement may start.

    Idempotent: called once by the updater just before it launches the new
    executable, and again on the way out of main().
    """
    global _instance_guard
    handle, _instance_guard = _instance_guard, None
    if handle is None:
        return
    try:
        import win32api
        win32api.CloseHandle(handle)
        log.info("single-instance token released")
    except Exception as exc:                          # noqa: BLE001
        # Includes the no-pywin32 case, where the "handle" is a plain sentinel.
        log.debug("could not release the single-instance token (%s)", exc)


def _warn_already_running() -> None:
    """Say why nothing happened. Silence would just get double-clicked again."""
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
    i18n.set_language(str(Settings().get("locale", "fr_FR")))
    global _instance_guard
    _instance_guard = acquire_single_instance()
    if _instance_guard is None:
        log.warning("another instance is already running, exiting")
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
