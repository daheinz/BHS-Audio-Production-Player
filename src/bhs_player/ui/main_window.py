"""Main window: Show Mode + Edit Mode for the theatrical cue player.

Spec references: Sections 9, 10, 11, 12, 13, 14.

Show Mode: Playing Stack, prominent ARMED cue, large GO, permanent STOP ALL,
cue list with selected/armed/playing/completed states, Back / ARM CUE,
master level, output device status.

Spacebar == GO, with keyboard auto-repeat ignored and text-field focus
protected (Section 14).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
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
    def __init__(self, cue_set: CueSet, engine: CueEngine, audio: AudioEngine,
                 backend: StreamingAudioBackend | None = None, parent=None,
                 version_name: str = "", play_folder=None):
        super().__init__(parent)
        self.cue_set = cue_set
        self.engine = engine
        self.audio = audio
        self.backend = backend
        self.play_folder = play_folder
        title = f"BHS Cue Player - {cue_set.play_name}"
        if version_name:
            title += f"  [{version_name}]"
        self.setWindowTitle(title)
        self.resize(900, 700)
        self._space_held = False
        self._stack_entries: dict = {}  # id(instance) -> PlayingStackEntry

        if self.backend is not None:
            self.backend.on_output_lost = self._on_output_lost

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- output status / AUDIO OUTPUT LOST banner (Section 15) ---
        self.output_banner = QLabel("")
        self.output_banner.setStyleSheet(
            "font-weight: bold; padding: 6px; background: #7d1a1a; color: white;")
        self.output_banner.setVisible(False)
        root.addWidget(self.output_banner)

        device_row = QHBoxLayout()
        self.device_lbl = QLabel("Output: (none)")
        device_row.addWidget(self.device_lbl, 1)
        change_btn = QPushButton("Change Output…")
        change_btn.clicked.connect(self._change_output)
        device_row.addWidget(change_btn)
        root.addLayout(device_row)

        # --- PLAYING stack ---
        root.addWidget(QLabel("PLAYING"))
        self.stack_area = QVBoxLayout()
        root.addLayout(self.stack_area, 1)

        # --- ARMED + GO ---
        armed_row = QHBoxLayout()
        self.armed_lbl = QLabel("ARMED: (none)")
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

        # --- master level + emergency stop ---
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Master"))
        self.master_slider = QSlider(Qt.Horizontal)
        self.master_slider.setRange(0, 100)
        # per-play master level (Section 6A); slider drives the mixer and the
        # value is saved with the cue set
        self.master_slider.setValue(int(round(cue_set.master_level * 100)))
        self.audio.mixer.set_master_level(cue_set.master_level)
        self.master_slider.valueChanged.connect(self._master_changed)
        ctrl.addWidget(self.master_slider, 1)
        self.master_meter = LevelMeter()
        ctrl.addWidget(self.master_meter, 1)
        stop_all = QPushButton("STOP ALL")
        stop_all.setStyleSheet(
            "font-weight: bold; padding: 10px 20px; background: #b71c1c; color: white;")
        stop_all.clicked.connect(self._stop_all)
        ctrl.addWidget(stop_all)
        # Save is allowed in Show Mode: it creates a new history version
        # without interrupting audio (Section 13 amendment).
        save_btn = QPushButton("Save Version")
        save_btn.clicked.connect(self._save_version)
        ctrl.addWidget(save_btn)
        root.addLayout(ctrl)

        # --- navigation ---
        nav = QHBoxLayout()
        back_btn = QPushButton("◀ BACK")
        back_btn.clicked.connect(self._back)
        nav.addWidget(back_btn)
        arm_btn = QPushButton("ARM CUE")
        arm_btn.clicked.connect(self._arm_selected)
        nav.addWidget(arm_btn)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #d8a0a0;")
        nav.addWidget(self.status_lbl, 1)
        root.addLayout(nav)

        # --- cue list ---
        self.cue_list = QListWidget()
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
        result = self.engine.go()
        if not result.ok:
            self.status_lbl.setText(result.reason)
        else:
            self.status_lbl.setText("")
        self._refresh()

    def _stop_all(self):
        self.engine.stop_all()
        self.status_lbl.setText("STOP ALL - nothing armed; select and ARM a cue")
        self._refresh()

    def _save_version(self):
        if self.play_folder is None:
            self.status_lbl.setText("No play folder; cannot save.")
            return
        try:
            path = self.play_folder.save_version(self.cue_set)
            self.status_lbl.setText(f"Saved: {path.name}")
        except Exception as exc:
            self.status_lbl.setText(f"Save failed: {exc}")

    def _master_changed(self, value: int) -> None:
        level = value / 100.0
        self.audio.mixer.set_master_level(level)
        self.cue_set.master_level = level

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
        from .edit_window import cue_row_tooltip, format_cue_row
        self.cue_list.blockSignals(True)
        self.cue_list.clear()
        for cue in self.cue_set.cues:
            item = QListWidgetItem(format_cue_row(cue, self.cue_set))
            item.setToolTip(cue_row_tooltip(cue, self.cue_set))
            self.cue_list.addItem(item)
        self.cue_list.blockSignals(False)

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
                f"ARMED: {armed.identifier}  {armed.name}  [{armed.action.value}]{detail}")
        elif self.engine._waiting_on:
            waiting = self.cue_set.by_internal_id(self.engine._waiting_on)
            label = waiting.identifier if waiting else ""
            self.armed_lbl.setText(f"WAITING ({label} completing)")
        else:
            self.armed_lbl.setText("ARMED: (none)")

        # GO availability
        ok, reason = self.engine.go_available()
        self.go_btn.setEnabled(ok)

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

        # master meter (post-master signal)
        m = self.audio.mixer.last_meter
        self.master_meter.set_levels(m.left_db, m.right_db, m.clipped)

        # cue list row colors
        for i, cue in enumerate(self.cue_set.cues):
            item = self.cue_list.item(i)
            if item:
                item.setBackground(STATE_COLORS.get(
                    cue.execution_state, QColor(30, 30, 30)))

    def _refresh_nav(self):
        pass  # selection highlight handled by Qt; arming is explicit

    # ---- keyboard safety (Section 14) ------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space:
            # typing in a text field must not trigger GO
            if isinstance(self.focusWidget(), QLineEdit):
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
