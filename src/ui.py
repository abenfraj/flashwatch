"""Control window, settings, and the debug view.

The debug tab is not an afterthought: it shows the raw OCR lines and the
"near misses" (lines that named a champion but did not parse). If the client's
system-message wording differs from what message_parser expects, that tab is
where it becomes visible, and the wording can then be corrected without
guessing.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from chat_detector import ChatRegion
from i18n import ENGLISH, FRENCH, locale_for, tr
from theme import CONTROL_QSS
from version import __version__
from zone_overlay import ZONE_CHAT, ZONE_CLOCK, ZONE_SCOREBOARD

log = logging.getLogger(__name__)

ROLES = ["", "TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
THEME_KEYS = {"dark": "ui.theme_dark", "light": "ui.theme_light",
              "neon": "ui.theme_neon"}


class RegionPicker(QWidget):
    """Full-screen overlay for drawing the chat region by hand.

    The automatic detector is good but cannot be verified without a real game
    running, so a manual override is the guaranteed fallback.
    """

    region_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self._origin = None
        self._current = None

    def start(self) -> None:
        # Cover the whole virtual desktop so a region can be drawn on any monitor.
        geometry = None
        for screen in self.screen().virtualSiblings() if self.screen() else []:
            geometry = screen.geometry() if geometry is None else geometry.united(
                screen.geometry())
        if geometry is None and self.screen():
            geometry = self.screen().geometry()
        if geometry is not None:
            self.setGeometry(geometry)
        self.show()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._origin is None or self._current is None:
            self.close()
            return
        rect = QRect(self._origin, self._current).normalized()
        self._origin = self._current = None
        self.hide()
        if rect.width() >= 40 and rect.height() >= 20:
            offset = self.geometry().topLeft()
            self.region_selected.emit(ChatRegion(
                x=rect.x() + offset.x(), y=rect.y() + offset.y(),
                width=rect.width(), height=rect.height(),
                source="manual", confirmed=True,
            ))
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._origin = self._current = None
            self.close()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1, Qt.DashLine))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(self.rect().adjusted(0, 40, 0, 0),
                         Qt.AlignHCenter | Qt.AlignTop, tr("picker.hint"))
        if self._origin is not None and self._current is not None:
            rect = QRect(self._origin, self._current).normalized()
            painter.fillRect(rect, QColor(60, 170, 255, 60))
            painter.setPen(QPen(QColor(90, 200, 255), 2))
            painter.drawRect(rect)
        painter.end()


class ControlWindow(QWidget):
    """Status, settings, enemy roles and diagnostics."""

    redetect_requested = Signal()
    manual_region_requested = Signal()
    test_mode_toggled = Signal(str, bool)     # (zone, enabled)
    region_cleared = Signal()
    reset_requested = Signal()
    overlay_visibility_toggled = Signal(bool)
    overlay_lock_toggled = Signal(bool)
    settings_changed = Signal()
    recentre_requested = Signal()
    preview_requested = Signal()
    quit_requested = Signal()
    language_changed = Signal(str)

    def __init__(self, settings, assets) -> None:
        super().__init__(None)
        self.settings = settings
        self.assets = assets
        self._loading = True

        self.setWindowTitle(f"{tr('app.title')}  —  v{__version__}")
        self.resize(560, 660)
        # Applied to the window rather than the application: the overlay paints
        # itself and the zone frames are deliberately bare, so a stylesheet set
        # on QApplication would reach two surfaces that do not want one.
        self.setStyleSheet(CONTROL_QSS)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_status_tab(), tr("ui.tab_status"))
        tabs.addTab(self._build_settings_tab(), tr("ui.tab_settings"))
        tabs.addTab(self._build_team_tab(), tr("ui.tab_team"))
        tabs.addTab(self._build_debug_tab(), tr("ui.tab_debug"))

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        hide_button = QPushButton(tr("ui.hide_window"))
        hide_button.clicked.connect(self.hide)
        quit_button = QPushButton(tr("ui.quit"))
        quit_button.setProperty("role", "danger")
        quit_button.clicked.connect(self.quit_requested.emit)
        buttons.addWidget(hide_button)
        buttons.addStretch(1)
        buttons.addWidget(quit_button)
        layout.addLayout(buttons)

        self._loading = False

    # ------------------------------------------------------------------
    def _build_status_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox(tr("ui.state"))
        form = QFormLayout(group)
        self.label_game = QLabel("-")
        self.label_region = QLabel("-")
        self.label_ocr = QLabel("-")
        self.label_timers = QLabel("0")
        self.label_clock = QLabel("-")
        # These five are the page's .readout block: live values, so monospaced
        # and in full-strength ink against the dimmer labels naming them.
        for readout in (self.label_game, self.label_region, self.label_ocr,
                        self.label_timers, self.label_clock):
            readout.setProperty("role", "value")
        form.addRow(tr("ui.state_game"), self.label_game)
        form.addRow(tr("ui.state_region"), self.label_region)
        form.addRow(tr("ui.state_ocr"), self.label_ocr)
        form.addRow(tr("ui.state_timers"), self.label_timers)
        form.addRow(tr("ui.state_clock"), self.label_clock)
        layout.addWidget(group)

        actions = QGroupBox(tr("ui.actions"))
        grid = QGridLayout(actions)
        redetect = QPushButton(tr("ui.redetect"))
        redetect.clicked.connect(self.redetect_requested.emit)
        manual = QPushButton(tr("ui.manual_region"))
        manual.clicked.connect(self.manual_region_requested.emit)
        clear_region = QPushButton(tr("ui.forget_region"))
        clear_region.clicked.connect(self.region_cleared.emit)
        reset = QPushButton(tr("ui.reset_timers"))
        reset.clicked.connect(self.reset_requested.emit)
        grid.addWidget(redetect, 0, 0)
        grid.addWidget(manual, 0, 1)
        grid.addWidget(clear_region, 1, 0)
        grid.addWidget(reset, 1, 1)

        # One button per area the user can place by hand. Several can be open at
        # once: the clock and the scoreboard are usually framed in the same trip
        # into a game.
        self.buttons_test: dict[str, QPushButton] = {}
        for row, (zone, label_key, tip_key) in enumerate((
                (ZONE_CHAT, "ui.test_mode", "ui.test_mode_tip"),
                (ZONE_CLOCK, "ui.test_mode_clock", "ui.test_mode_clock_tip"),
                (ZONE_SCOREBOARD, "ui.test_mode_scoreboard",
                 "ui.test_mode_scoreboard_tip")), start=2):
            button = QPushButton(tr(label_key))
            button.setCheckable(True)
            button.setToolTip(tr(tip_key))
            button.toggled.connect(
                lambda checked, z=zone: self.test_mode_toggled.emit(z, checked))
            grid.addWidget(button, row, 0, 1, 2)
            self.buttons_test[zone] = button
        # The chat one is the original single button; keep the old name working.
        self.button_test_mode = self.buttons_test[ZONE_CHAT]
        layout.addWidget(actions)

        overlay_group = QGroupBox(tr("ui.overlay"))
        overlay_layout = QVBoxLayout(overlay_group)
        self.check_visible = QCheckBox(tr("ui.show_overlay"))
        self.check_visible.setChecked(bool(self.settings.get("overlay_visible")))
        self.check_visible.toggled.connect(self.overlay_visibility_toggled.emit)
        self.check_locked = QCheckBox(tr("ui.locked"))
        self.check_locked.setChecked(bool(self.settings.get("overlay_locked")))
        self.check_locked.toggled.connect(self.overlay_lock_toggled.emit)
        overlay_layout.addWidget(self.check_visible)
        overlay_layout.addWidget(self.check_locked)
        layout.addWidget(overlay_group)

        note = QLabel(tr("ui.borderless_tip"))
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Language first: it is what everything else on this page is written in.
        language = QGroupBox(tr("ui.language"))
        language_form = QFormLayout(language)
        self.combo_language = QComboBox()
        self.combo_language.addItem(tr("ui.language_fr"), FRENCH)
        self.combo_language.addItem(tr("ui.language_en"), ENGLISH)
        index = self.combo_language.findData(
            ENGLISH if str(self.settings.get("locale", "fr_FR")).lower()
            .startswith("en") else FRENCH)
        if index >= 0:
            self.combo_language.setCurrentIndex(index)
        self.combo_language.setToolTip(tr("ui.language_tip"))
        self.combo_language.currentIndexChanged.connect(self._on_language_changed)
        language_form.addRow(self.combo_language)
        layout.addWidget(language)

        appearance = QGroupBox(tr("ui.appearance"))
        form = QFormLayout(appearance)

        self.combo_layout = QComboBox()
        self.combo_layout.addItem(tr("ui.layout_bar"), "bar")
        self.combo_layout.addItem(tr("ui.layout_list"), "list")
        index = self.combo_layout.findData(
            str(self.settings.get("overlay_layout", "bar")))
        if index >= 0:
            self.combo_layout.setCurrentIndex(index)
        self.combo_layout.currentIndexChanged.connect(self._on_settings_changed)
        form.addRow(tr("ui.layout"), self.combo_layout)

        self.check_hide_until_game = QCheckBox(tr("ui.hide_until_in_game"))
        self.check_hide_until_game.setToolTip(tr("ui.hide_until_in_game_tip"))
        self.check_hide_until_game.setChecked(
            bool(self.settings.get("hide_until_in_game")))
        self.check_hide_until_game.toggled.connect(self._on_settings_changed)
        form.addRow(self.check_hide_until_game)

        self.check_idle_bar = QCheckBox(tr("ui.bar_when_idle"))
        self.check_idle_bar.setChecked(bool(self.settings.get("bar_show_when_idle")))
        self.check_idle_bar.toggled.connect(self._on_settings_changed)
        form.addRow(self.check_idle_bar)

        buttons_row = QHBoxLayout()
        recentre = QPushButton(tr("ui.recentre"))
        recentre.clicked.connect(self.recentre_requested.emit)
        preview = QPushButton(tr("ui.preview"))
        preview.clicked.connect(self.preview_requested.emit)
        buttons_row.addWidget(recentre)
        buttons_row.addWidget(preview)
        form.addRow(buttons_row)

        self.combo_theme = QComboBox()
        for key, label_key in THEME_KEYS.items():
            self.combo_theme.addItem(tr(label_key), key)
        current = str(self.settings.get("theme", "dark"))
        index = self.combo_theme.findData(current)
        if index >= 0:
            self.combo_theme.setCurrentIndex(index)
        self.combo_theme.currentIndexChanged.connect(self._on_settings_changed)
        form.addRow(tr("ui.theme"), self.combo_theme)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(35, 100)
        self.slider_opacity.setValue(int(float(self.settings.get("overlay_opacity", 0.92)) * 100))
        self.slider_opacity.valueChanged.connect(self._on_settings_changed)
        form.addRow(tr("ui.opacity"), self.slider_opacity)

        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.6, 2.0)
        self.spin_scale.setSingleStep(0.05)
        self.spin_scale.setValue(float(self.settings.get("overlay_scale", 1.0)))
        self.spin_scale.valueChanged.connect(self._on_settings_changed)
        form.addRow(tr("ui.scale"), self.spin_scale)

        self.check_sort_role = QCheckBox(tr("ui.sort_by_role"))
        self.check_sort_role.setChecked(bool(self.settings.get("sort_by_role")))
        self.check_sort_role.toggled.connect(self._on_settings_changed)
        form.addRow(self.check_sort_role)

        self.spin_ready_linger = QSpinBox()
        self.spin_ready_linger.setRange(0, 60)
        self.spin_ready_linger.setSuffix(" s")
        self.spin_ready_linger.setToolTip(tr("ui.ready_linger_tip"))
        self.spin_ready_linger.setValue(
            int(self.settings.get("ready_linger_seconds", 5)))
        self.spin_ready_linger.valueChanged.connect(self._on_settings_changed)
        form.addRow(tr("ui.ready_linger"), self.spin_ready_linger)

        self.check_hide_ready = QCheckBox(tr("ui.hide_ready"))
        self.check_hide_ready.setChecked(bool(self.settings.get("hide_ready_entries")))
        self.check_hide_ready.toggled.connect(self._on_settings_changed)
        form.addRow(self.check_hide_ready)
        layout.addWidget(appearance)

        tracking = QGroupBox(tr("ui.tracking"))
        tracking_form = QFormLayout(tracking)
        self.check_summoners = QCheckBox(tr("ui.track_summoners"))
        self.check_summoners.setChecked(bool(self.settings.get("track_summoners")))
        self.check_summoners.toggled.connect(self._on_settings_changed)
        self.check_ultimates = QCheckBox(tr("ui.track_ultimates"))
        self.check_ultimates.setChecked(bool(self.settings.get("track_ultimates")))
        self.check_ultimates.toggled.connect(self._on_settings_changed)
        tracking_form.addRow(self.check_summoners)
        tracking_form.addRow(self.check_ultimates)

        self.check_enemy_colour = QCheckBox(tr("ui.enemy_colour"))
        self.check_enemy_colour.setToolTip(tr("ui.enemy_colour_tip"))
        self.check_enemy_colour.setChecked(
            bool(self.settings.get("require_enemy_colour")))
        self.check_enemy_colour.toggled.connect(self._on_settings_changed)
        tracking_form.addRow(self.check_enemy_colour)

        self.check_cosmic = QCheckBox(tr("ui.cosmic"))
        self.check_cosmic.setChecked(bool(self.settings.get("assume_cosmic_insight")))
        self.check_cosmic.toggled.connect(self._on_settings_changed)
        self.check_ionian = QCheckBox(tr("ui.ionian"))
        self.check_ionian.setChecked(bool(self.settings.get("assume_ionian_boots")))
        self.check_ionian.toggled.connect(self._on_settings_changed)
        tracking_form.addRow(self.check_cosmic)
        tracking_form.addRow(self.check_ionian)

        note = QLabel(tr("ui.ultimate_note"))
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        tracking_form.addRow(note)
        layout.addWidget(tracking)

        audio = QGroupBox(tr("ui.notifications"))
        audio_form = QFormLayout(audio)
        self.check_audio = QCheckBox(tr("ui.audio"))
        self.check_audio.setChecked(bool(self.settings.get("audio_enabled")))
        self.check_audio.toggled.connect(self._on_settings_changed)
        self.check_audio_ready = QCheckBox(tr("ui.audio_ready"))
        self.check_audio_ready.setChecked(bool(self.settings.get("audio_on_ready")))
        self.check_audio_ready.toggled.connect(self._on_settings_changed)
        self.spin_warn = QSpinBox()
        self.spin_warn.setRange(0, 30)
        self.spin_warn.setSuffix(" s")
        self.spin_warn.setValue(int(self.settings.get("audio_warn_seconds", 5)))
        self.spin_warn.valueChanged.connect(self._on_settings_changed)
        audio_form.addRow(self.check_audio)
        audio_form.addRow(self.check_audio_ready)
        audio_form.addRow(tr("ui.audio_warn"), self.spin_warn)
        layout.addWidget(audio)

        capture = QGroupBox(tr("ui.capture"))
        capture_form = QFormLayout(capture)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(80, 1000)
        self.spin_interval.setSingleStep(20)
        self.spin_interval.setSuffix(" ms")
        self.spin_interval.setValue(int(self.settings.get("capture_interval_ms", 200)))
        self.spin_interval.valueChanged.connect(self._on_settings_changed)
        capture_form.addRow(tr("ui.interval"), self.spin_interval)
        layout.addWidget(capture)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    def _build_team_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        help_label = QLabel(tr("ui.team_help"))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.team_container = QWidget()
        self.team_layout = QFormLayout(self.team_container)
        layout.addWidget(self.team_container)
        layout.addStretch(1)
        self._role_combos: dict[str, QComboBox] = {}
        return page

    def sync_team(self, champion_ids: list[str], on_role_changed) -> None:
        """Add a role selector for each newly seen champion."""
        for champion_id in champion_ids:
            if champion_id in self._role_combos:
                continue
            champion = self.assets.champions.get(champion_id)
            name = champion.name if champion else champion_id
            combo = QComboBox()
            combo.addItems(ROLES)
            combo.currentTextChanged.connect(
                lambda role, cid=champion_id: on_role_changed(cid, role))
            self._role_combos[champion_id] = combo
            self.team_layout.addRow(name, combo)

    def set_role_display(self, champion_id: str, role: str) -> None:
        combo = self._role_combos.get(champion_id)
        if combo is None or combo.currentText() == role:
            return
        combo.blockSignals(True)
        combo.setCurrentText(role if role in ROLES else "")
        combo.blockSignals(False)

    def clear_team(self) -> None:
        while self.team_layout.rowCount():
            self.team_layout.removeRow(0)
        self._role_combos.clear()

    # ------------------------------------------------------------------
    def _build_debug_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(tr("ui.debug_lines")))
        self.text_lines = QPlainTextEdit()
        self.text_lines.setReadOnly(True)
        self.text_lines.setFont(QFont("Consolas", 9))
        layout.addWidget(self.text_lines, 2)

        label = QLabel(tr("ui.debug_misses"))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list_misses = QListWidget()
        self.list_misses.setFont(QFont("Consolas", 9))
        layout.addWidget(self.list_misses, 1)

        label = QLabel(tr("ui.debug_colour"))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list_colour = QListWidget()
        self.list_colour.setFont(QFont("Consolas", 9))
        layout.addWidget(self.list_colour, 1)

        layout.addWidget(QLabel(tr("ui.debug_events")))
        self.list_events = QListWidget()
        self.list_events.setFont(QFont("Consolas", 9))
        layout.addWidget(self.list_events, 1)
        return page

    def update_debug(self, lines: list[str], near_misses: list[str],
                     colour_rejected: list[str] | None = None) -> None:
        if not self.isVisible():
            return
        text = "\n".join(lines)
        if text != self.text_lines.toPlainText():
            self.text_lines.setPlainText(text)
        for widget, values in ((self.list_misses, near_misses),
                               (self.list_colour, colour_rejected or [])):
            current = [widget.item(i).text() for i in range(widget.count())]
            if current != values:
                widget.clear()
                widget.addItems(values)

    def add_event(self, description: str) -> None:
        self.list_events.insertItem(0, description)
        while self.list_events.count() > 60:
            self.list_events.takeItem(self.list_events.count() - 1)

    # ------------------------------------------------------------------
    def update_status(self, *, game: str, region: str, ocr: str,
                      timers: int, clock: str) -> None:
        self.label_game.setText(game)
        self.label_region.setText(region)
        self.label_ocr.setText(ocr)
        self.label_timers.setText(str(timers))
        self.label_clock.setText(clock)

    def _on_language_changed(self, *_args) -> None:
        """Persist the new language and let the application rebuild itself.

        Handled apart from the other settings because it cannot be applied in
        place: every label in this window was created in the old language, and
        the champion and spell names have to be downloaded again.
        """
        if self._loading:
            return
        language = self.combo_language.currentData() or FRENCH
        self.settings.set("locale", locale_for(language))
        self.language_changed.emit(language)

    def _on_settings_changed(self, *_args) -> None:
        if self._loading:
            return
        self.settings.update({
            "overlay_layout": self.combo_layout.currentData(),
            "hide_until_in_game": self.check_hide_until_game.isChecked(),
            "bar_show_when_idle": self.check_idle_bar.isChecked(),
            "theme": self.combo_theme.currentData(),
            "overlay_opacity": self.slider_opacity.value() / 100.0,
            "overlay_scale": self.spin_scale.value(),
            "sort_by_role": self.check_sort_role.isChecked(),
            "hide_ready_entries": self.check_hide_ready.isChecked(),
            "ready_linger_seconds": self.spin_ready_linger.value(),
            "track_summoners": self.check_summoners.isChecked(),
            "track_ultimates": self.check_ultimates.isChecked(),
            "require_enemy_colour": self.check_enemy_colour.isChecked(),
            "assume_cosmic_insight": self.check_cosmic.isChecked(),
            "assume_ionian_boots": self.check_ionian.isChecked(),
            "audio_enabled": self.check_audio.isChecked(),
            "audio_on_ready": self.check_audio_ready.isChecked(),
            "audio_warn_seconds": self.spin_warn.value(),
            "capture_interval_ms": self.spin_interval.value(),
        })
        self.settings_changed.emit()

    def sync_test_mode(self, zone: str, active: bool) -> None:
        """Keep a button in step when its frame is closed from the frame itself."""
        button = self.buttons_test.get(zone)
        if button is None:
            return
        button.blockSignals(True)
        button.setChecked(active)
        button.blockSignals(False)

    def sync_overlay_toggles(self, *, visible: bool, locked: bool) -> None:
        for widget, value in ((self.check_visible, visible),
                              (self.check_locked, locked)):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)

    def closeEvent(self, event) -> None:
        """Closing this window quits the application.

        This window carries the taskbar entry, so its close button (and the
        taskbar's right-click "Close window") are the routes a user will reach
        for to stop the program. Use "Masquer cette fenetre" to keep it running
        in the tray instead.
        """
        event.ignore()
        self.quit_requested.emit()
