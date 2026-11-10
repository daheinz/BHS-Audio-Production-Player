"""Main window: Show Mode + Edit Mode for the theatrical cue player.

Spec references: Sections 9, 10, 11, 12, 13, 14.

Show/Rehearse: full-height cue list, separate armed and bottom-aligned playing
containers, compact GO / STOP ALL, explicit mouse/keyboard arming,
bus levels, output device status.

Spacebar == GO, with keyboard auto-repeat ignored and text-field focus
protected (Section 14).
"""

from __future__ import annotations
from .theme import ViewingModeControl
from .audio_health import AudioHealthPanel
import logging

log = logging.getLogger("bhs_player.ui")

from PySide6.QtCore import Qt, QTimer, Signal, QEvent
from PySide6.QtGui import QColor, QKeyEvent, QIcon, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QSplitter,
    QProgressBar,
    QAbstractSpinBox,
    QAbstractItemView,
    QComboBox,
    QSlider,
    QCheckBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTextEdit,
    QPlainTextEdit,
    QApplication,
    QScrollArea,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from ..audio.engine import AudioEngine
from ..audio.stream import StreamingAudioBackend
from ..cues.engine import CueEngine
from ..cues.model import ActionType, AdvanceMode, Cue, CueExecutionState, CueSet
from .device_dialog import DeviceDialog
from .widgets import LevelMeter, format_time
from .cue_table import CueTable
from .save_changes import SaveState

REFRESH_MS = 40  # ~25 updates/sec (Section 9)

class PlayingStackEntry(QWidget):
    """Compact selectable card for one independently controlled playback."""

    selected = Signal(object)

    def __init__(self, instance, voice, audio: AudioEngine, parent=None):
        super().__init__(parent)
        self.setObjectName("playingStackCard")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.instance = instance
        self.voice = voice
        self.audio = audio

        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("selected", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        self.title = QLabel(self._title_text())
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold")
        layout.addWidget(self.title)
        self.time_lbl = QLabel("")
        self.time_lbl.setWordWrap(True)
        layout.addWidget(self.time_lbl)
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setToolTip("Playback position; not an audio level meter")
        bottom.addWidget(self.progress, 1)
        self.stop_btn = QPushButton()
        self.fade_btn = QPushButton()
        self.finish_btn = QPushButton()
        for button, fade, tooltip in ((self.stop_btn, False, "Stop this playback and run Next Cue Action"),
                                      (self.fade_btn, True, "Fade out this playback"),
                                      (self.finish_btn, True, "Fade out in 2 seconds, then complete normally (runs Next Cue Action)")):
            pixmap = QPixmap(20, 20)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor('#fff2df'), 2))
            if fade:
                painter.drawLine(3, 4, 7, 4)
                painter.drawLine(7, 4, 17, 16)
                painter.drawLine(3, 16, 17, 16)
                if button is self.finish_btn:
                    painter.fillRect(0, 8, 14, 12, QColor('#683b19'))
                    font = painter.font()
                    font.setPixelSize(10)
                    font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(0, 18, "2s")
            else:
                painter.fillRect(5, 5, 10, 10, QColor('#fff2df'))
            painter.end()
            button.setIcon(QIcon(pixmap))
            button.setFixedSize(30, 28)
            button.setStyleSheet("padding: 3px; background: #683b19; color: white")
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            bottom.addWidget(button)
        self.stop_btn.clicked.connect(self._stop)
        self.fade_btn.clicked.connect(self._fade)
        self.finish_btn.clicked.connect(self._finish)
        layout.addLayout(bottom)
        live = QHBoxLayout()
        live.setSpacing(5)
        live.addWidget(QLabel("Level"))
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(0, 400)
        self.level_slider.setValue(round(voice._gain * 100))
        self.level_slider.setAccessibleName("This playback output level")
        self.level_slider.setToolTip("This playback only, before bus level. 100% is unity; saved cue unchanged.")
        self.level_value = QLabel(f"{self.level_slider.value()}%")
        self.level_value.setMinimumWidth(34)
        self.repeat_check = QCheckBox("Repeat")
        self.repeat_check.setChecked(voice.looping)
        self.repeat_check.setToolTip("Repeat this playback's trimmed segment. Uncheck to finish the current pass. Saved cue unchanged.")
        self.level_slider.valueChanged.connect(self._set_level)
        self.level_slider.sliderReleased.connect(self._log_level)
        self.repeat_check.toggled.connect(self._set_repeat)
        live.addWidget(self.level_slider, 1)
        live.addWidget(self.level_value)
        live.addWidget(self.repeat_check)
        layout.addLayout(live)
        self.destination = QLabel("")
        self.destination.setWordWrap(True)
        layout.addWidget(self.destination)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.selected.emit(self)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self.selected.emit(self)
        super().focusInEvent(event)

    def _set_level(self, percent):
        if self.audio.set_instance_level(self.instance, percent / 100):
            self.level_value.setText(f"{percent}%")
            if not self.level_slider.isSliderDown():
                self._log_level()
        else:
            self.level_slider.setEnabled(False)

    def _log_level(self):
        log.info("PLAYBACK LEVEL cue=%s playback=%s percent=%s", self.instance.identifier,
                 self.instance.playback_number, self.level_slider.value())

    def _set_repeat(self, repeat):
        log.info("PLAYBACK REPEAT cue=%s playback=%s repeat=%s", self.instance.identifier, self.instance.playback_number, repeat)
        if not self.audio.set_instance_repeat(self.instance, repeat):
            self.repeat_check.setEnabled(False)
        self.refresh()

    def _title_text(self):
        number = getattr(self.instance, 'playback_number', 0)
        suffix = f" · playback #{number}" if number else ''
        return f"{self.instance.identifier}  {self.instance.name}  [{self._status()}]{suffix}"

    def _status(self):
        status = 'FADING' if self.voice.fading else 'PLAYING'
        if self.voice.looping:
            status += ' · LOOPING'
        return status

    def _stop(self):
        log.info("PLAYBACK STOP cue=%s playback=%s normal_completion=True", self.instance.identifier, self.instance.playback_number)
        self.audio.stop_instance(self.instance, complete_naturally=True)

    def _fade(self):
        log.info("PLAYBACK FADE cue=%s playback=%s duration=%s", self.instance.identifier, self.instance.playback_number, self.voice.fade_out_duration)
        # configured fade-out duration; zero means immediate stop (Section 5)
        self.audio.fade_instance(self.instance, self.voice.fade_out_duration)

    def _finish(self):
        if self.audio.finish_instance(self.instance):
            log.info("PLAYBACK FADE COMPLETE cue=%s playback=%s duration=2 normal_completion=True",
                     self.instance.identifier, self.instance.playback_number)
            self.finish_btn.setEnabled(False)
            self.refresh()

    def refresh(self):
        v = self.voice
        self.title.setText(self._title_text())
        if v.looping:
            self.time_lbl.setText(
                f"loop {format_time(v.position_seconds)} | total {format_time(v.total_elapsed_seconds)}")
        else:
            self.time_lbl.setText(
                f"{format_time(v.position_seconds)} / {format_time(v.duration_seconds)}"
                f"  ({format_time(v.remaining_seconds)} left)")
        self.progress.setValue(round(v.progress_fraction * 1000))


class MainWindow(QMainWindow):
    returnedToEdit = Signal()
    def __init__(self, cue_set: CueSet, engine: CueEngine, audio: AudioEngine,
                 backend: StreamingAudioBackend | None = None, parent=None,
                 version_name: str = "", play_folder=None, save_state=None,
                 confirm_close: bool = True, routing=None, rehearsal=False, preview=False):
        super().__init__(parent)
        self.routing, self.rehearsal, self.preview = routing, rehearsal, preview
        self.cue_set = cue_set
        self.save_state = save_state if save_state is not None else SaveState(cue_set)
        self.confirm_close = confirm_close
        self.engine = engine
        self.audio = audio
        self.backend = backend
        self.play_folder = play_folder
        title = f"BHS Cue Player - {cue_set.play_name}"
        if version_name:
            title += f"  [{version_name}]"
        self.setWindowTitle(title)
        self.resize(1500, 920)
        self._space_held = False
        self._stack_entries: dict = {}  # id(instance) -> PlayingStackEntry

        if self.backend is not None and routing is None:
            self.backend.on_output_lost = self._on_output_lost

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        mode = "REHEARSAL" if rehearsal else "SHOW MODE"
        if preview:
            mode += " / GUI PREVIEW - NO AUDIO"
        heading = QHBoxLayout()
        mode_label = QLabel(f"{cue_set.play_name}  /  {mode}")
        mode_label.setWordWrap(True)
        mode_label.setStyleSheet("font-size: 24px; font-weight: bold; padding: 6px")
        heading.addWidget(mode_label, 1)
        back_edit = QPushButton("Return to Edit — Stop Playback")
        back_edit.clicked.connect(self.close)
        heading.addWidget(ViewingModeControl(self))
        heading.addWidget(back_edit)
        root.addLayout(heading)
        # Main work area: cue list and independent armed/playing containers.
        self.main_splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        cue_layout = QVBoxLayout(left)
        cue_layout.setContentsMargins(0, 0, 0, 0)
        cue_legend = QLabel("CUES · yellow: armed · orange: playing · blue outline: selected")
        cue_legend.setWordWrap(True)
        cue_layout.addWidget(cue_legend)
        self.cue_list = CueTable(cue_set, armable=True)
        self.cue_table = self.cue_list
        self.cue_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._followed_cue_id = None
        self.cue_list.cueArmRequested.connect(self._arm_by_id)
        self.cue_list.currentRowChanged.connect(lambda _r: self._refresh_nav())
        cue_layout.addWidget(self.cue_list, 1)
        navigation = QHBoxLayout()
        back_btn = QPushButton("◀ BACK")
        back_btn.clicked.connect(self._back)
        navigation.addWidget(back_btn)
        navigation_hint = QLabel("↑ / ↓ select · Enter arms · row ARM also arms")
        navigation_hint.setWordWrap(True)
        navigation.addWidget(navigation_hint, 1)
        cue_layout.addLayout(navigation)
        self.main_splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.armed_panel = QFrame()
        self.armed_panel.setObjectName("armedContainer")
        armed_layout = QVBoxLayout(self.armed_panel)
        armed_heading = QLabel("ARMED CUE")
        armed_heading.setObjectName("performanceSectionTitle")
        armed_heading.setWordWrap(True)
        armed_layout.addWidget(armed_heading)
        self.armed_card = QFrame()
        self.armed_card.setObjectName("armedStackCard")
        self.armed_card.setAttribute(Qt.WA_StyledBackground)
        armed_card_layout = QVBoxLayout(self.armed_card)
        armed_card_layout.setContentsMargins(8, 6, 8, 6)
        armed_card_layout.setSpacing(3)
        self.armed_lbl = QLabel("No cue armed")
        self.armed_lbl.setWordWrap(True)
        self.armed_lbl.setObjectName("armedCue")
        self.armed_lbl.setStyleSheet("font-weight: bold")
        armed_card_layout.addWidget(self.armed_lbl)
        self.armed_detail = QLabel("")
        self.armed_detail.setWordWrap(True)
        armed_card_layout.addWidget(self.armed_detail)
        self.notes_lbl = QLabel("")
        self.notes_lbl.setWordWrap(True)
        armed_card_layout.addWidget(self.notes_lbl)
        armed_layout.addWidget(self.armed_card)
        right_layout.addWidget(self.armed_panel)
        self.playing_panel = QFrame()
        self.playing_panel.setObjectName("playingContainer")
        playing_layout = QVBoxLayout(self.playing_panel)
        self.stack_heading = QLabel("PLAYING STACK · 0 sounds")
        self.stack_heading.setObjectName("performanceSectionTitle")
        self.stack_heading.setWordWrap(True)
        playing_layout.addWidget(self.stack_heading)
        self.stack_help = QLabel("Newest above oldest · select a card for Ctrl+F")
        self.stack_help.setWordWrap(True)
        playing_layout.addWidget(self.stack_help)
        self.stack_empty = QLabel("No sounds playing")
        playing_layout.addWidget(self.stack_empty)
        self.stack_area = QVBoxLayout()
        self.stack_area.setContentsMargins(0, 0, 0, 0)
        self.stack_area.setSpacing(6)
        self.stack_area.setAlignment(Qt.AlignBottom)
        stack_content = QWidget()
        stack_content.setLayout(self.stack_area)
        self.stack_scroll = QScrollArea()
        self.stack_scroll.setMinimumSize(0, 0)
        self.stack_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack_scroll.setWidgetResizable(True)
        self.stack_scroll.setWidget(stack_content)
        playing_layout.addWidget(self.stack_scroll, 1)
        right_layout.addWidget(self.playing_panel, 1)
        self.main_splitter.addWidget(right)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([960, 480])
        root.addWidget(self.main_splitter, 1)

        # Compact full-width status / execution / master-meter strip.
        self.bottom_panel = QWidget()
        bottom = QHBoxLayout(self.bottom_panel)
        bottom.setContentsMargins(0, 4, 0, 0)
        system = QVBoxLayout()
        system.setSpacing(2)
        self.device_lbl = QLabel("Output: (none)")
        self.device_lbl.setWordWrap(True)
        self.route_lbl = QLabel("PRIMARY")
        self.test_warning = QLabel("Board and backup confirmation unavailable")
        self.test_warning.setWordWrap(True)
        self.test_warning.setProperty("tone", "warning")
        self.output_banner = QLabel("")
        self.output_banner.setWordWrap(True)
        self.output_banner.setProperty("tone", "error")
        self.go_reason = QLabel("")
        self.go_reason.setWordWrap(True)
        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setProperty("tone", "error")
        for label in (self.route_lbl, self.device_lbl, self.test_warning,
                      self.output_banner, self.go_reason, self.status_lbl):
            system.addWidget(label)
        self.switch_btn = QPushButton("Switch to Backup…")
        self.switch_btn.clicked.connect(self._switch_route)
        system.addWidget(self.switch_btn, 0, Qt.AlignLeft)
        bottom.addLayout(system, 1)
        self.audio_health = AudioHealthPanel(self, backend, preview)
        bottom.addWidget(self.audio_health)
        self.go_btn = QPushButton()
        self.go_btn.setAccessibleName("GO, Space")
        go_layout = QVBoxLayout(self.go_btn)
        go_layout.setContentsMargins(4, 4, 4, 4)
        go_layout.setSpacing(0)
        for text, size in (("GO", 20), ("Space", 11)):
            label = QLabel(text)
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            label.setStyleSheet(f"QLabel {{ font-size: {size}px; background: transparent; color: white; }} QLabel:disabled {{ color: #8993a0; }}")
            go_layout.addWidget(label)
        self.go_btn.setFixedSize(100, 64)
        self.go_btn.setStyleSheet("QPushButton { font-size: 18px; font-weight: bold; background: #2e7d32; color: white; } QPushButton:disabled { background: #30343b; color: #8993a0; }")
        self.go_btn.clicked.connect(self._go)
        bottom.addWidget(self.go_btn)
        self.stop_all_btn = QPushButton("STOP ALL\nCtrl+Shift+S")
        self.stop_all_btn.setFixedSize(126, 64)
        self.stop_all_btn.setStyleSheet("font-weight: bold; background: #a92323; color: white")
        self.stop_all_btn.clicked.connect(self._stop_all)
        bottom.addWidget(self.stop_all_btn)
        self.bus_row = QHBoxLayout()
        self.bus_displays = {}
        for bus in cue_set.profile.buses:
            box = QVBoxLayout()
            label = QLabel(f"{bus.name} · {bus.shape} · {bus.level*100:g}% (locked)")
            label.setWordWrap(True)
            box.addWidget(label)
            meter = LevelMeter()
            box.addWidget(meter)
            status = QLabel("Meter unavailable — output not prepared")
            status.setWordWrap(True)
            status.setMaximumWidth(185)
            status.setStyleSheet("font-size: 11px")
            box.addWidget(status)
            self.bus_row.addLayout(box)
            self.bus_displays[bus.id] = (meter, status)
        meter_content = QWidget()
        meter_content.setLayout(self.bus_row)
        self.meter_scroll = QScrollArea()
        self.meter_scroll.setWidgetResizable(True)
        self.meter_scroll.setWidget(meter_content)
        self.meter_scroll.setMinimumWidth(200)
        self.meter_scroll.setMaximumWidth(400)
        self.meter_scroll.setMaximumHeight(140)
        self.meter_scroll.setFrameShape(QFrame.NoFrame)
        bottom.addWidget(self.meter_scroll)
        root.addWidget(self.bottom_panel)
        self._selected_playback = None
        self._rebuild_cue_list()
        QApplication.instance().installEventFilter(self)

        # --- refresh timer (~25 Hz, driven by actual playback) ---
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(REFRESH_MS)

        self._refresh()

    # ---- output device (Section 15) --------------------------------------
    def _on_output_lost(self, reason: str) -> None:
        # called from the audio callback thread; marshal to the UI thread
        QTimer.singleShot(0, lambda: self._show_output_lost(reason))

    def _show_output_lost(self, reason: str) -> None:
        self.output_banner.setText(f"AUDIO OUTPUT LOST: {reason}. Select a replacement device.")
        self.output_banner.setVisible(True)
        self._refresh()

    def _change_output(self) -> None:
        if self.backend is None:
            self.status_lbl.setText("No streaming backend configured")
            return
        dlg = DeviceDialog(self, reason="Select the output device for this show.")
        if dlg.exec() and dlg.selected_device() is not None:
            dev = dlg.selected_device()
            if self.backend.select_device(dev.index):
                self.device_lbl.setText(f"Output: {dev.name}")
                self.output_banner.setVisible(False)
                self.status_lbl.setText("")
            else:
                self._show_output_lost(self.backend.output_lost_reason or "failed")
        self._refresh()

    # ---- actions --------------------------------------------------------
    def _go(self):
        if self.preview:
            return
        result = self.engine.go()
        log.log(logging.INFO if result.ok else logging.ERROR,
                "MANUAL GO cue=%s ok=%s reason=%s active=%s",
                result.cue.identifier if result.cue else None, result.ok, result.reason,
                [(i.identifier, i.playback_number) for i in self.audio.active_instances()])
        if not result.ok:
            self.status_lbl.setText(result.reason)
        else:
            self.status_lbl.setText("")
        self._refresh()

    def _stop_all(self):
        log.info("STOP ALL")
        self.engine.stop_all()
        self.status_lbl.setText("STOP ALL — playback stopped. Click a row’s ARM button to arm a cue.")
        self._refresh()

    def _save_version(self):
        if self.play_folder is None:
            self.status_lbl.setText("No play folder; cannot save.")
            return False
        if not self.save_state.has_changes:
            return True
        try:
            path = self.play_folder.save_version(self.cue_set)
            self.save_state.mark_saved()
            self.status_lbl.setText(f"Saved: {path.name}")
            return True
        except Exception as exc:
            self.status_lbl.setText(f"Save failed: {exc}")
            return False

    def closeEvent(self, event) -> None:
        if self.confirm_close and self.save_state.has_changes and not self._save_version():
            event.ignore()
            return
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.engine.interrupt_output(disarm=True)
        # Keep a prepared stream pumping silence between modes. Reopening a
        # wireless/device stream for every rehearsal can lose its initial audio.
        # Voices and pending advancement have already been stopped/disarmed.
        self.returnedToEdit.emit()
        super().closeEvent(event)

    def _switch_route(self):
        if self.routing is None or self.preview:
            return
        route = "backup" if self.routing.route == "primary" else "primary"
        if QMessageBox.question(self, "Switch Output?", f"Stop current sounds and prepare {route}? Interrupted sounds will not restart. A separately armed cue stays armed.", QMessageBox.Yes | QMessageBox.Cancel) == QMessageBox.Yes:
            self.routing.prepare(route)
            self.status_lbl.setText(self.routing.message)
            self._refresh()

    def _back(self):
        if not self.engine.back():
            self.status_lbl.setText("Already at the top of the cue list")
        self._refresh()

    def _arm_by_id(self, cue_id):
        cue = self.cue_set.by_internal_id(cue_id)
        if cue is not None and self.engine.arm_cue(cue_id):
            self.status_lbl.setText(f"Armed {cue.identifier} — press GO to execute")
            self._refresh()

    def _arm_selected(self):
        row = self.cue_list.currentRow()
        if 0 <= row < len(self.cue_set.cues):
            self._arm_by_id(self.cue_set.cues[row].internal_id)

    # ---- refresh ---------------------------------------------------------
    def _rebuild_cue_list(self):
        self.cue_list.rebuild()

    def _sync_playing_stack(self):
        """Keep one persistent widget per active instance; create on arrival,
        remove on finish, refresh in place (Sections 7-9). Entries and their
        waveforms are NOT recreated every refresh tick."""
        active = self.audio.active_instances()
        active_ids = {id(inst) for inst in active}
        self.stack_heading.setText(f"PLAYING STACK · {len(active)} sound{'s' if len(active) != 1 else ''} · newest first")
        self.stack_empty.setVisible(not active)
        self.stack_scroll.setVisible(True)

        # remove entries whose instance is gone
        for inst_id, entry in list(self._stack_entries.items()):
            if inst_id not in active_ids:
                if self._selected_playback is entry:
                    self._selected_playback = None
                self.stack_area.removeWidget(entry)
                entry.deleteLater()
                del self._stack_entries[inst_id]

        # add new entries (most recent first in display order)
        for inst in active:
            if id(inst) not in self._stack_entries:
                voice = self.audio.voice_for(inst)
                if voice is None:
                    continue
                entry = PlayingStackEntry(inst, voice, self.audio)
                cue = self.cue_set.by_internal_id(inst.cue_internal_id)
                entry.destination.setText("Bus: " + self.cue_set.profile.bus_names(cue.bus_ids) if cue else "Destination unavailable")
                entry.selected.connect(self._select_playback)
                self._stack_entries[id(inst)] = entry
                self.stack_area.insertWidget(0, entry)

        # Retain per-cue bus identity; route switching retains existing engine semantics.
        for entry in self._stack_entries.values():
            cue = self.cue_set.by_internal_id(entry.instance.cue_internal_id)
            buses = self.cue_set.profile.bus_names(cue.bus_ids) if cue else "Unavailable"
            route = self.routing.route.title() if self.routing else "Configured output"
            entry.destination.setText(f"Bus: {buses} | {route}")
            entry.refresh()

    def _refresh(self):
        if not self.preview and QApplication.activeModalWidget() is None:
            result = self.engine.process_pending_auto_go()
            if result is not None:
                log.log(logging.INFO if result.ok else logging.ERROR, "AUTOMATIC GO cue=%s ok=%s reason=%s",
                        result.cue.identifier if result.cue else None, result.ok, result.reason)
                self.status_lbl.setText(f"Automatic GO: {result.cue.identifier}" if result.ok else f"Automatic GO stopped: {result.reason}")
        self._sync_playing_stack()
        self.audio_health.refresh()

        armed = self.engine.armed_cue
        self.armed_detail.setToolTip("")
        state = 'idle'
        if armed:
            state = 'armed'
            self.armed_lbl.setText(f"ARMED: {armed.identifier}  —  {armed.name}")
            if armed.is_play_sound():
                self.armed_detail.setText(f"GO → PLAY · {self.cue_set.profile.bus_names(armed.bus_ids)} · {armed.advance_mode.label}")
            elif armed.action in (ActionType.STOP, ActionType.FADE):
                target = self.cue_set.by_internal_id(armed.target_internal_id)
                target_name = f"{target.identifier} {target.name}" if target else '(no target)'
                duration = f" over {armed.fade_duration:g}s" if armed.action is ActionType.FADE else ''
                self.armed_detail.setText(f"GO → {armed.action.value} {target_name}{duration} · {armed.advance_mode.label}")
            else:
                self.armed_detail.setText("GO → STOP ALL sounds")
        elif self.engine.waiting_cue:
            waiting = self.engine.waiting_cue
            next_cue = self.cue_set.next_after(waiting.internal_id)
            automatic = waiting.advance_mode is AdvanceMode.ON_COMPLETE_GO
            state = 'automatic' if automatic else 'waiting'
            self.armed_lbl.setText("No cue armed")
            self.armed_detail.setToolTip(f"Waiting for {waiting.identifier} {waiting.name}")
            if next_cue:
                self.armed_detail.setText(f"Waiting for {waiting.identifier}. AUTO GO → {next_cue.identifier} {next_cue.name} at natural completion" if automatic else f"Waiting for {waiting.identifier}. Next: {next_cue.identifier} {next_cue.name} — will arm, then wait for GO")
            else:
                self.armed_detail.setText(f"Waiting for {waiting.identifier}. End of cue list - nothing follows this cue")
        else:
            self.armed_lbl.setText("No cue armed")
            self.armed_detail.setText("Click a row's ARM button, then GO. Arming never starts playback.")
        if armed and self.engine.waiting_cue is not None:
            source = self.engine.waiting_cue
            if source.advance_mode is AdvanceMode.ON_COMPLETE_GO:
                self.armed_detail.setText(
                    f"AUTO GO on end of {source.identifier} -> {armed.identifier} | " + self.armed_detail.text())
        if self.armed_lbl.property('cueState') != state:
            self.armed_lbl.setProperty('cueState', state)
            self.armed_lbl.style().unpolish(self.armed_lbl)
            self.armed_lbl.style().polish(self.armed_lbl)
            self.armed_card.setProperty('cueState', state)
            for widget in (self.armed_card, self.armed_lbl, self.armed_detail, self.notes_lbl):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

        # Prepare the armed cue first, then use spare work for one successor.
        ok, reason = self.engine.go_available()
        if armed and getattr(self.audio,'nonblocking',False) and not self.preview:
            following=self.cue_set.next_after(armed.internal_id)
            if following and following.is_play_sound() and following.audio_file:
                self.audio.prepare_async(following,refresh=False)
        self.go_btn.setEnabled(ok and not self.preview)
        self.go_btn.setToolTip(reason if not ok else "Execute the armed cue (Spacebar)")
        self.notes_lbl.setText(armed.notes if armed else "")
        self.notes_lbl.setVisible(bool(armed and armed.notes))
        self.switch_btn.setEnabled(False)
        if self.routing:
            self.route_lbl.setText(self.routing.route.upper() + (" READY" if self.audio.ready else " NOT READY"))
            self.device_lbl.setText(self.routing.message)
            route = "backup" if self.routing.route == "primary" else "primary"
            reason_switch = self.routing.unsupported(route)
            self.switch_btn.setText(f"Switch to {route.title()}…")
            self.switch_btn.setEnabled(not reason_switch and not self.preview)
            self.switch_btn.setToolTip(reason_switch or "Deliberate route switch; drops current sounds.")
            missing = self.routing.unconfirmed()
            warnings = ["Unconfirmed at board: " + ", ".join(missing)] if missing else []
            if "backup" not in self.routing.confirmations:
                warnings.append("Backup not confirmed")
            self.test_warning.setText(" · ".join(warnings))
        self.go_reason.setText("GUI preview: playback disabled" if self.preview else reason if not ok else "Ready for GO")

        # output device status (Section 15)
        if self.backend is not None:
            if self.backend.output_lost:
                self.output_banner.setVisible(True)
                if not self.output_banner.text():
                    self.output_banner.setText(
                        f"AUDIO OUTPUT LOST: {self.backend.output_lost_reason}")
            if self.backend.stream is not None and self.backend.stream.running:
                identity = getattr(self.cue_set.profile, self.routing.route + '_device') if self.routing else self.backend.stream.device_name
                self.device_lbl.setText(f"Output: {identity} · channels 1 / 2")
        if self.audio.ready and not (self.backend and self.backend.output_lost):
            self.output_banner.setVisible(False)
        elif not (self.backend and self.backend.output_lost):
            self.output_banner.setText("Audio engine not ready - select an output")
            self.output_banner.setVisible(True)

        # Only the supported one-bus primary adapter exposes a real bus meter.
        for bus in self.cue_set.profile.buses:
            meter, status = self.bus_displays[bus.id]
            available = self.audio.ready and len(self.cue_set.profile.buses) == 1 and (not self.routing or self.routing.route == "primary") and not self.preview
            meter.setEnabled(available)
            if available:
                m = self.audio.mixer.last_meter
                meter.set_levels(m.left_db, m.right_db, m.clipped)
                status.setText(f"L {m.left_db:.1f} / R {m.right_db:.1f} dBFS")
            else:
                meter.set_levels(float('-inf'), float('-inf'), False)
                status.setText("Bus meter unavailable" + (" on combined backup" if self.routing and self.routing.route == "backup" else " — output not prepared"))

        active_ids = {inst.cue_internal_id for inst in self.audio.active_instances()}
        next_cue = armed
        self.cue_list.highlight(active_ids, next_cue.internal_id if next_cue else None)
        current = armed or self.engine.waiting_cue
        self._follow_current_cue(current)

    def _follow_current_cue(self, cue):
        """Follow advancement once per cue; leave manual browsing alone between GOs."""
        cue_id = cue.internal_id if cue is not None else None
        if cue_id == self._followed_cue_id:
            return
        self._followed_cue_id = cue_id
        if cue is None:
            return
        row = self.cue_set.index_of(cue_id)
        if row is None:
            return
        item = self.cue_list.item(row, 0)
        rect = self.cue_list.visualItemRect(item)
        middle = self.cue_list.viewport().height() // 2
        if rect.center().y() >= middle or rect.bottom() < 0:
            horizontal = self.cue_list.horizontalScrollBar().value()
            self.cue_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            self.cue_list.horizontalScrollBar().setValue(horizontal)


    def _refresh_nav(self):
        pass  # selection highlight handled by Qt; arming is explicit

    def _select_playback(self, selected):
        self._selected_playback = selected
        for entry in self._stack_entries.values():
            entry.setProperty("selected", entry is selected)
            entry.style().unpolish(entry)
            entry.style().polish(entry)

    def _shortcut_context_blocked(self):
        focus = QApplication.focusWidget()
        while focus is not None:
            if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return True
            if isinstance(focus, QComboBox) and focus.isEditable():
                return True
            focus = focus.parentWidget()
        return QApplication.activeModalWidget() is not None

    def _handle_show_key(self, event):
        if self._shortcut_context_blocked():
            return False
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key_Space and mods == Qt.NoModifier:
            if not event.isAutoRepeat() and not self._space_held:
                self._space_held = True
                if self.go_btn.isEnabled():
                    self._go()
            return True
        if key == Qt.Key_S and mods == (Qt.ControlModifier | Qt.ShiftModifier):
            if not event.isAutoRepeat():
                self._stop_all()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and mods == Qt.NoModifier:
            if self.cue_list.hasFocus() or self.cue_list.isAncestorOf(QApplication.focusWidget()):
                if not event.isAutoRepeat():
                    self._arm_selected()
                return True
        if key in (Qt.Key_Up, Qt.Key_Down) and mods == Qt.NoModifier:
            if self.cue_list.hasFocus():
                step = -1 if key == Qt.Key_Up else 1
                row = max(0, min(self.cue_list.rowCount()-1, self.cue_list.currentRow()+step))
                if self.cue_list.rowCount():
                    self.cue_list.setCurrentRow(row)
                    self.cue_list.scrollToItem(self.cue_list.item(row, 0))
                return True
        if key == Qt.Key_F and mods == Qt.ControlModifier:
            entry = self._selected_playback
            if entry is not None and (entry.hasFocus() or entry.isAncestorOf(QApplication.focusWidget())):
                if not event.isAutoRepeat():
                    entry._fade()
                return True
        return False

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
            if event.type() in (QEvent.WindowDeactivate, QEvent.FocusOut):
                self._space_held = False
            if event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space and not event.isAutoRepeat():
                self._space_held = False
            if event.type() == QEvent.KeyPress and self._handle_show_key(event):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if not self._handle_show_key(event):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
        super().keyReleaseEvent(event)
