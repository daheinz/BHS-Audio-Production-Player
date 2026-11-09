"""Main window: Show Mode + Edit Mode for the theatrical cue player.

Spec references: Sections 9, 10, 11, 12, 13, 14.

Show Mode: Playing Stack, prominent ARMED cue, large GO, permanent STOP ALL,
cue list with selected/armed/playing/completed states, Back / ARM CUE,
bus levels, output device status.

Spacebar == GO, with keyboard auto-repeat ignored and text-field focus
protected (Section 14).
"""

from __future__ import annotations
from .theme import ViewingModeControl

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QTextEdit,
    QPlainTextEdit,
    QApplication,
    QScrollArea,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..audio.engine import AudioEngine
from ..audio.stream import StreamingAudioBackend
from ..cues.engine import CueEngine
from ..cues.model import ActionType, Cue, CueExecutionState, CueSet
from .device_dialog import DeviceDialog
from .widgets import LevelMeter, ProgressBar, format_time
from .cue_table import CueTable
from .save_changes import SaveState

REFRESH_MS = 40  # ~25 updates/sec (Section 9)

STATE_COLORS = {
    CueExecutionState.ARMED: QColor(40, 90, 40),
    CueExecutionState.PLAYING: QColor(90, 60, 20),
    CueExecutionState.TRIGGERED: QColor(90, 60, 20),
    CueExecutionState.COMPLETE: QColor(50, 50, 50),
    CueExecutionState.INTERRUPTED: QColor(90, 40, 40),
    CueExecutionState.IDLE: QColor(30, 30, 30),
}


class PlayingStackEntry(QWidget):
    """One active sound: progress, meter, STOP, FADE OUT (Section 7)."""

    def __init__(self, instance, voice, audio: AudioEngine, parent=None):
        super().__init__(parent)
        self.instance = instance
        self.voice = voice
        self.audio = audio

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        header = QHBoxLayout()
        status = "LOOPING" if voice.looping else ("FADING" if voice.fading else "PLAYING")
        self.title = QLabel(f"{instance.identifier}  {instance.name}   [{status}]")
        self.title.setStyleSheet("font-weight: bold;")
        header.addWidget(self.title)
        header.addStretch(1)
        self.time_lbl = QLabel("")
        header.addWidget(self.time_lbl)
        layout.addLayout(header)

        self.progress = ProgressBar()
        self.progress.set_voice(voice)
        layout.addWidget(self.progress)

        bottom = QHBoxLayout()
        self.meter = LevelMeter()
        bottom.addWidget(self.meter, 1)
        stop_btn = QPushButton("STOP")
        stop_btn.setToolTip("Immediately stop only this sound. Other sounds keep playing.")
        stop_btn.clicked.connect(self._stop)
        fade_btn = QPushButton("FADE OUT")
        fade_btn.setToolTip(
            "Fade only this sound to silence using its configured fade-out "
            "duration, then stop it. A zero duration stops immediately.")
        fade_btn.clicked.connect(self._fade)
        bottom.addWidget(stop_btn)
        bottom.addWidget(fade_btn)
        layout.addLayout(bottom)

    def _stop(self):
        self.audio.stop_instance(self.instance)

    def _fade(self):
        # configured fade-out duration; zero means immediate stop (Section 5)
        self.audio.fade_instance(self.instance, self.voice.fade_out_duration)

    def refresh(self):
        from ..audio.engine import _to_db
        v = self.voice
        status = "LOOPING" if v.looping else ("FADING" if v.fading else "PLAYING")
        self.title.setText(f"{self.instance.identifier}  {self.instance.name}   [{status}]")
        if v.looping:
            self.time_lbl.setText(
                f"loop {format_time(v.position_seconds)} | total {format_time(v.total_elapsed_seconds)}")
        else:
            self.time_lbl.setText(
                f"{format_time(v.position_seconds)} / {format_time(v.duration_seconds)}"
                f"  ({format_time(v.remaining_seconds)} left)")
        self.progress.update()
        # per-instance meter: this sound's own post-fade peaks (Section 8)
        self.meter.set_levels(_to_db(v.last_peak_l), _to_db(v.last_peak_r),
                              v.last_peak_l >= 1.0 or v.last_peak_r >= 1.0)


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
        self.resize(1500, 850)
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
        self.test_warning = QLabel("")
        self.test_warning.setWordWrap(True)
        self.test_warning.setProperty("tone", "warning")
        self.test_warning.setStyleSheet("font-weight: bold")
        root.addWidget(self.test_warning)
        # --- output status / AUDIO OUTPUT LOST banner (Section 15) ---
        self.output_banner = QLabel("")
        self.output_banner.setStyleSheet(
            "font-weight: bold; padding: 6px; background: #7d1a1a; color: white;")
        self.output_banner.setVisible(False)
        root.addWidget(self.output_banner)

        device_row = QHBoxLayout()
        self.device_lbl = QLabel("Output: (none)")
        self.device_lbl.setWordWrap(True)
        device_row.addWidget(self.device_lbl, 1)
        self.route_lbl = QLabel("PRIMARY")
        self.route_lbl.setObjectName("routeStatus")
        device_row.addWidget(self.route_lbl)
        self.switch_btn = QPushButton("Switch to Backup...")
        self.switch_btn.clicked.connect(self._switch_route)
        device_row.addWidget(self.switch_btn)
        root.addLayout(device_row)

        # --- PLAYING stack ---
        root.addWidget(QLabel("PLAYING"))
        self.stack_area = QVBoxLayout()
        stack_content = QWidget()
        stack_content.setLayout(self.stack_area)
        stack_scroll = QScrollArea()
        stack_scroll.setWidgetResizable(True)
        stack_scroll.setWidget(stack_content)
        root.addWidget(stack_scroll, 1)

        # --- ARMED + GO ---
        armed_row = QHBoxLayout()
        self.armed_lbl = QLabel("ARMED: (none)")
        self.armed_lbl.setWordWrap(True)
        self.armed_lbl.setStyleSheet(
            "font-size: 20px; font-weight: bold; padding: 8px;"
            "background: #1a3a1a; color: #cfe8cf;")
        armed_row.addWidget(self.armed_lbl, 1)
        self.go_btn = QPushButton("GO")
        self.go_btn.setStyleSheet(
            "font-size: 28px; font-weight: bold; padding: 16px 40px;"
            "background: #2e7d32; color: white;")
        self.go_btn.clicked.connect(self._go)
        armed_row.addWidget(self.go_btn)
        root.addLayout(armed_row)
        self.notes_lbl = QLabel("")
        self.notes_lbl.setWordWrap(True)
        root.addWidget(self.notes_lbl)

        # --- emergency stop ---
        ctrl = QHBoxLayout()
        stop_all = QPushButton("STOP ALL")
        stop_all.setStyleSheet(
            "font-weight: bold; padding: 10px 20px; background: #b71c1c; color: white;")
        stop_all.clicked.connect(self._stop_all)
        ctrl.addWidget(stop_all)
        root.addLayout(ctrl)

        self.bus_row = QHBoxLayout()
        self.bus_displays = {}
        for bus in cue_set.profile.buses:
            box = QVBoxLayout()
            label = QLabel(f"{bus.name} · {bus.shape} · {bus.level*100:g}% (locked)")
            label.setWordWrap(True)
            label.setStyleSheet("font-weight: bold")
            meter = LevelMeter()
            status = QLabel("Meter unavailable — output not prepared")
            status.setStyleSheet("font-size: 11px")
            box.addWidget(label)
            box.addWidget(meter)
            box.addWidget(status)
            self.bus_row.addLayout(box)
            self.bus_displays[bus.id] = (meter, status)
        root.addLayout(self.bus_row)
        # --- navigation ---
        nav = QHBoxLayout()
        back_btn = QPushButton("◀ BACK")
        back_btn.clicked.connect(self._back)
        nav.addWidget(back_btn)
        arm_btn = QPushButton("ARM CUE")
        arm_btn.clicked.connect(self._arm_selected)
        nav.addWidget(arm_btn)
        self.go_reason = QLabel("")
        nav.addWidget(self.go_reason)
        self.status_lbl = QLabel("")
        self.status_lbl.setProperty("tone", "error")
        nav.addWidget(self.status_lbl, 1)
        root.addLayout(nav)

        # --- cue list ---
        root.addWidget(QLabel("Cue Table - blue outline: selected / green: armed / amber: playing / gray: completed or interrupted"))
        self.cue_list = CueTable(cue_set)
        self.cue_table = self.cue_list
        self.cue_list.currentRowChanged.connect(lambda _r: self._refresh_nav())
        root.addWidget(self.cue_list, 2)
        self._rebuild_cue_list()

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
        if not result.ok:
            self.status_lbl.setText(result.reason)
        else:
            self.status_lbl.setText("")
        self._refresh()

    def _stop_all(self):
        self.engine.stop_all()
        self.status_lbl.setText("STOP ALL — playback stopped. Use ARM CUE if no cue is armed.")
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
        self.engine.interrupt_output(disarm=True)
        if self.routing:
            self.routing.backend.stop()
            self.audio.set_ready(False)
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

    def _arm_selected(self):
        row = self.cue_list.currentRow()
        if 0 <= row < len(self.cue_set.cues):
            cue = self.cue_set.cues[row]
            if self.engine.arm_cue(cue.internal_id):
                self.status_lbl.setText(f"Armed {cue.identifier}")
            self._refresh()

    # ---- refresh ---------------------------------------------------------
    def _rebuild_cue_list(self):
        self.cue_list.rebuild()

    def _sync_playing_stack(self):
        """Keep one persistent widget per active instance; create on arrival,
        remove on finish, refresh in place (Sections 7-9). Entries and their
        waveforms are NOT recreated every refresh tick."""
        active = self.audio.active_instances()
        active_ids = {id(inst) for inst in active}

        # remove entries whose instance is gone
        for inst_id, entry in list(self._stack_entries.items()):
            if inst_id not in active_ids:
                self.stack_area.removeWidget(entry)
                entry.deleteLater()
                del self._stack_entries[inst_id]

        # add new entries (most recent first in display order)
        for inst in reversed(active):
            if id(inst) not in self._stack_entries:
                voice = self.audio.voice_for(inst)
                if voice is None:
                    continue
                entry = PlayingStackEntry(inst, voice, self.audio)
                self._stack_entries[id(inst)] = entry
                self.stack_area.insertWidget(0, entry)

        # refresh all persistent entries in place
        for entry in self._stack_entries.values():
            entry.refresh()

    def _refresh(self):
        self._sync_playing_stack()

        # Armed cue (STOP/FADE cues show target and duration, Section 10)
        armed = self.engine.armed_cue
        if armed:
            detail = ""
            if armed.action in (ActionType.STOP, ActionType.FADE):
                target = (self.cue_set.by_internal_id(armed.target_internal_id)
                          if armed.target_internal_id else None)
                tname = target.identifier if target else "(no target)"
                detail = f"  ->  {armed.action.value} {tname}"
                if armed.action is ActionType.FADE:
                    detail += f" over {armed.fade_duration:.1f}s"
            self.armed_lbl.setText(
                f"ARMED: {armed.identifier}  {armed.name}  [{armed.action.value}]{detail}  ·  {self.cue_set.profile.bus_names(armed.bus_ids) if armed.is_play_sound() else 'Control cue'}")
        elif self.engine._waiting_on:
            waiting = self.cue_set.by_internal_id(self.engine._waiting_on)
            label = waiting.identifier if waiting else ""
            self.armed_lbl.setText(f"WAITING ({label} completing)")
        else:
            self.armed_lbl.setText("ARMED: (none)")

        # GO availability
        ok, reason = self.engine.go_available()
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
                self.device_lbl.setText(f"Output: {self.backend.stream.device_name}")
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

    def _refresh_nav(self):
        pass  # selection highlight handled by Qt; arming is explicit

    # ---- keyboard safety (Section 14) ------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space:
            # typing in a text field must not trigger GO
            if isinstance(self.focusWidget(), (QLineEdit, QTextEdit, QPlainTextEdit)) or QApplication.activeModalWidget() is not None:
                super().keyPressEvent(event)
                return
            # ignore auto-repeat: one physical press = one GO
            if event.isAutoRepeat() or self._space_held:
                return
            self._space_held = True
            self._go()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
        super().keyReleaseEvent(event)
