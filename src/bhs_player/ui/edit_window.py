"""Edit Mode window (Sections 12, 13).

Add/remove/update/reorder cues, assign audio (auto-import), audition/TEST,
and save versions. Editing a nonplaying cue never interrupts audio. Audition
playback is isolated from show advancement and labeled TEST.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..audio.engine import AudioEngine
from ..cues.model import ActionType, AdvanceMode, Cue, CueSet, OnGoBehavior
from ..storage.store import PlayFolder
from .cue_editor_dialog import CueEditorDialog


# ---- cue row display + tooltips (Sections 5, 11) --------------------------

_ADVANCE_LABEL = {
    AdvanceMode.ON_COMPLETE: "On Complete",
    AdvanceMode.ON_GO: "On GO",
}

_BEHAVIOR_LABEL = {
    OnGoBehavior.ADD_TO_STACK: "Add",
    OnGoBehavior.STOP_PREVIOUS: "Stop Prev",
    OnGoBehavior.STOP_ALL: "Stop All",
}


def format_cue_row(cue: Cue, cue_set: CueSet) -> str:
    """One-line cue summary: identifier, name, action, then fields to the
    right. Volume is shown as a percentage."""
    base = f"{cue.identifier}   {cue.name}   [{cue.action.value}]"
    if cue.action is ActionType.PLAY:
        parts = [f"Vol {cue.volume * 100:.0f}%"]
        if cue.fade_in > 0:
            parts.append(f"In {cue.fade_in:g}s")
        if cue.fade_out > 0:
            parts.append(f"Out {cue.fade_out:g}s")
        if cue.loop:
            parts.append("Loop")
        parts.append(_ADVANCE_LABEL[cue.advance_mode])
        parts.append(_BEHAVIOR_LABEL[cue.on_go_behavior])
        if cue.start_position is not None or cue.end_position is not None:
            start = f"{cue.start_position:g}" if cue.start_position is not None else "0"
            end = f"{cue.end_position:g}" if cue.end_position is not None else "end"
            parts.append(f"[{start} -> {end}]")
        parts.append(cue.audio_file or "(no file)")
        return base + "   |   " + "  ".join(parts)
    if cue.action in (ActionType.STOP, ActionType.FADE):
        target = cue_set.by_internal_id(cue.target_internal_id) if cue.target_internal_id else None
        tname = target.identifier if target else "(missing)"
        tail = f"Target {tname}"
        if cue.action is ActionType.FADE:
            tail += f"  Fade {cue.fade_duration:g}s"
        return base + "   |   " + tail
    return base


def cue_row_tooltip(cue: Cue, cue_set: CueSet) -> str:
    """Mouse-over help explaining the cue's fields."""
    lines = [f"Cue {cue.identifier} — {cue.name or '(unnamed)'}"]

    def add(label, value, expl):
        lines.append(f"{label}: {value} — {expl}")

    add("Action", cue.action.value, "what GO executes for this cue")
    if cue.action is ActionType.PLAY:
        add("Volume", f"{cue.volume * 100:.0f}%",
            "playback level relative to the Master Output Level")
        add("Fade-In", f"{cue.fade_in:g}s",
            "time to ramp from silence to full volume at start (0 = instant)")
        add("Fade-Out", f"{cue.fade_out:g}s",
            "default duration used by FADE OUT controls (0 = instant stop)")
        add("Loop", "On" if cue.loop else "Off",
            "repeat the segment until stopped/faded")
        add("Advance Mode", _ADVANCE_LABEL[cue.advance_mode],
            "On Complete waits for the sound to finish before arming the next "
            "cue; On GO arms the next cue immediately for overlap")
        add("On GO Behavior", _BEHAVIOR_LABEL[cue.on_go_behavior],
            "what happens to already-playing sounds when this cue starts")
        start = cue.start_position if cue.start_position is not None else 0.0
        end = cue.end_position if cue.end_position is not None else "file end"
        add("Segment", f"{start:g}s -> {end}",
            "optional portion of the file to play")
        add("Audio File", cue.audio_file or "(none)",
            "path relative to the play folder")
    elif cue.action in (ActionType.STOP, ActionType.FADE):
        target = cue_set.by_internal_id(cue.target_internal_id) if cue.target_internal_id else None
        add("Target", target.identifier if target else "(missing)",
            "the PLAY cue whose active sound this acts on")
        if cue.action is ActionType.FADE:
            add("Fade Duration", f"{cue.fade_duration:g}s",
                "time to fade the target to silence")
    else:
        lines.append("Stops every active sound and clears the Playing Stack.")
    if cue.notes:
        lines.append(f"Notes: {cue.notes}")
    return "\n".join(lines)


class EditWindow(QMainWindow):
    """Cue editor. Emits no signals; app polls or uses on_saved callback."""

    def __init__(self, cue_set: CueSet, audio: AudioEngine,
                 play_folder: Optional[PlayFolder] = None,
                 on_save=None, parent=None):
        super().__init__(parent)
        self.cue_set = cue_set
        self.audio = audio
        self.play_folder = play_folder
        self.on_save = on_save
        self.setWindowTitle(f"Edit - {cue_set.play_name}")
        self.resize(760, 620)
        self._test_instance = None
        self._test_cue_id: Optional[str] = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addWidget(QLabel(f"Cue List — {cue_set.play_name}"))

        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _r: self._update_buttons())
        root.addWidget(self.list, 1)

        # cue actions
        row1 = QHBoxLayout()
        add_btn = QPushButton("Add Cue")
        add_btn.clicked.connect(self._add_cue)
        edit_btn = QPushButton("Edit Cue")
        edit_btn.clicked.connect(self._edit_cue)
        del_btn = QPushButton("Remove Cue")
        del_btn.clicked.connect(self._remove_cue)
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(lambda: self._move(-1))
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(lambda: self._move(1))
        for b in (add_btn, edit_btn, del_btn, up_btn, down_btn):
            row1.addWidget(b)
        validate_btn = QPushButton("Validate Show")
        validate_btn.clicked.connect(self._validate_show)
        row1.addWidget(validate_btn)
        root.addLayout(row1)
        self.edit_btn, self.del_btn, self.up_btn, self.down_btn = edit_btn, del_btn, up_btn, down_btn

        # audition / TEST (Section 13) with progress + meter
        row2 = QHBoxLayout()
        self.test_btn = QPushButton("TEST Selected Cue")
        self.test_btn.clicked.connect(self._audition)
        self.stop_test_btn = QPushButton("Stop TEST")
        self.stop_test_btn.clicked.connect(self._stop_audition)
        self.test_lbl = QLabel("")
        self.test_lbl.setStyleSheet("color: #d0a040; font-weight: bold;")
        for w in (self.test_btn, self.stop_test_btn, self.test_lbl):
            row2.addWidget(w)
        row2.addStretch(1)
        root.addLayout(row2)

        # TEST progress + meter row (Sections 8, 13)
        from .widgets import LevelMeter, ProgressBar
        test_row = QHBoxLayout()
        self.test_progress = ProgressBar()
        self.test_progress.setVisible(False)
        test_row.addWidget(self.test_progress, 2)
        self.test_meter = LevelMeter()
        self.test_meter.setVisible(False)
        test_row.addWidget(self.test_meter, 1)
        root.addLayout(test_row)

        # master level (Section 6A) — Edit Mode control, persisted per play
        from PySide6.QtWidgets import QSlider
        from PySide6.QtCore import Qt
        master_row = QHBoxLayout()
        master_row.addWidget(QLabel("Master"))
        self.master_slider = QSlider(Qt.Horizontal)
        self.master_slider.setRange(0, 100)
        self.master_slider.setValue(int(round(cue_set.master_level * 100)))
        self.audio.mixer.set_master_level(cue_set.master_level)
        self.master_slider.valueChanged.connect(self._master_changed)
        master_row.addWidget(self.master_slider, 1)
        root.addLayout(master_row)

        # save + enter show
        row3 = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #8fc98f;")
        row3.addWidget(self.status_lbl, 1)
        save_btn = QPushButton("Save Version")
        save_btn.setStyleSheet("font-weight: bold; padding: 8px 20px;")
        save_btn.clicked.connect(self._save)
        row3.addWidget(save_btn)
        show_btn = QPushButton("ENTER SHOW MODE")
        show_btn.setStyleSheet(
            "font-weight: bold; padding: 10px 24px; background: #2e7d32; color: white;")
        show_btn.clicked.connect(self._enter_show)
        row3.addWidget(show_btn)
        root.addLayout(row3)

        # ~25 Hz refresh for TEST progress/meters (Section 9)
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_test)
        self._timer.start(40)

        self._rebuild()
        self._update_buttons()

    def _master_changed(self, value: int) -> None:
        level = value / 100.0
        self.audio.mixer.set_master_level(level)
        self.cue_set.master_level = level
        self._mark_edited()

    def _refresh_test(self) -> None:
        """Drive TEST progress/meter from the actual audition voice."""
        if self._test_instance is None:
            return
        voice = self.audio.voice_for(self._test_instance)
        if voice is None or not voice.active:
            self._stop_audition()
            return
        from ..audio.engine import _to_db
        self.test_progress.update()
        self.test_meter.set_levels(_to_db(voice.last_peak_l),
                                   _to_db(voice.last_peak_r),
                                   voice.last_peak_l >= 1.0 or voice.last_peak_r >= 1.0)

    # ---- list -------------------------------------------------------------
    def _rebuild(self):
        self.list.blockSignals(True)
        self.list.clear()
        for cue in self.cue_set.cues:
            item = QListWidgetItem(format_cue_row(cue, self.cue_set))
            item.setToolTip(cue_row_tooltip(cue, self.cue_set))
            self.list.addItem(item)
        self.list.blockSignals(False)

    def _selected_index(self) -> int:
        return self.list.currentRow()

    def _selected_cue(self) -> Optional[Cue]:
        i = self._selected_index()
        return self.cue_set.cues[i] if 0 <= i < len(self.cue_set.cues) else None

    def _update_buttons(self):
        has = self._selected_cue() is not None
        for b in (self.edit_btn, self.del_btn, self.up_btn, self.down_btn, self.test_btn):
            b.setEnabled(has)

    # ---- cue operations ----------------------------------------------------
    def _add_cue(self):
        cue = Cue(identifier=self._next_identifier())
        dlg = CueEditorDialog(cue, self.cue_set, self.play_folder, self)
        if dlg.exec():
            # insert after current selection, else append (explicit placement)
            idx = self._selected_index()
            self.cue_set.insert(cue, index=(idx + 1) if idx >= 0 else None)
            self._rebuild()
            self._mark_edited()

    def _edit_cue(self):
        cue = self._selected_cue()
        if cue is None:
            return
        dlg = CueEditorDialog(cue, self.cue_set, self.play_folder, self)
        if dlg.exec():
            self._rebuild()
            self._mark_edited()

    def _remove_cue(self):
        cue = self._selected_cue()
        if cue is None:
            return
        # warn if this cue is targeted by a STOP/FADE cue (Section 12)
        dependents = [c for c in self.cue_set.cues
                      if c.target_internal_id == cue.internal_id]
        msg = f"Remove cue {cue.identifier}?"
        if dependents:
            names = ", ".join(c.identifier for c in dependents)
            msg += f"\n\nIt is the target of: {names}. Those cues will need retargeting."
        if QMessageBox.question(self, "Remove Cue", msg) == QMessageBox.Yes:
            self.cue_set.remove(cue.internal_id)
            self._rebuild()
            self._mark_edited()

    def _move(self, delta: int):
        i = self._selected_index()
        cue = self._selected_cue()
        if cue is None:
            return
        new_index = i + delta
        if 0 <= new_index <= len(self.cue_set.cues) - 1:
            self.cue_set.move(cue.internal_id, new_index)
            self._rebuild()
            self.list.setCurrentRow(new_index)
            self._mark_edited()

    def _next_identifier(self) -> str:
        """Suggest the next script-page identifier after the last cue."""
        if not self.cue_set.cues:
            return "1.0"
        last = self.cue_set.cues[-1].identifier
        try:
            page, sub = last.split(".")
            return f"{page}.{int(sub) + 1}"
        except Exception:
            return f"{last}.0"

    # ---- audition / TEST (Section 13) --------------------------------------
    def _audition(self):
        cue = self._selected_cue()
        if cue is None or not cue.is_play_sound():
            self.status_lbl.setText("Select a PLAY cue to test.")
            return
        if not cue.audio_file:
            self.status_lbl.setText("Cue has no audio file.")
            return
        self._stop_audition()
        try:
            # isolated audition: does NOT touch show state or armed cue
            path = (self.play_folder.folder / cue.audio_file) if self.play_folder else cue.audio_file
            inst = self.audio.start_from_path(str(path), cue)
            self._test_instance = inst
            self._test_cue_id = cue.internal_id
            voice = self.audio.voice_for(inst)
            if voice is not None:
                self.test_progress.set_voice(voice)
            self.test_progress.setVisible(True)
            self.test_meter.setVisible(True)
            self.test_lbl.setText(f"TEST playing: {cue.identifier}")
        except Exception as exc:
            self.status_lbl.setText(f"TEST failed: {exc}")

    def _stop_audition(self):
        if self._test_instance is not None:
            self.audio.stop_instance(self._test_instance)
            self._test_instance = None
            self.test_lbl.setText("")
            self.test_progress.clear()
            self.test_progress.setVisible(False)
            self.test_meter.setVisible(False)

    # ---- save --------------------------------------------------------------
    def _save(self):
        if self.play_folder is None:
            self.status_lbl.setText("No play folder; cannot save.")
            return
        try:
            path = self.play_folder.save_version(self.cue_set)
            self.status_lbl.setText(f"Saved: {path.name}")
            if self.on_save:
                self.on_save(self.cue_set)
        except Exception as exc:
            self.status_lbl.setText(f"Save failed: {exc}")

    def _mark_edited(self):
        # recovery autosave (Section 18) - separate from permanent history;
        # failures are shown, never silently discarded
        if self.play_folder is not None:
            try:
                self.play_folder.save_recovery(self.cue_set)
                self.status_lbl.setText("Unsaved changes")
            except Exception as exc:
                self.status_lbl.setText(f"Recovery autosave failed: {exc}")
        else:
            self.status_lbl.setText("Unsaved changes")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_audition()
        super().closeEvent(event)

    def _enter_show(self):
        """app.main assigns enter_show(); guard if run standalone."""
        fn = getattr(self, "enter_show", None)
        if callable(fn):
            fn()
        else:
            self.status_lbl.setText("Show Mode is launched by the main app.")

    def _validate_show(self):
        """Explicit Validate Show control (Section 19)."""
        from ..validate.check import validate_show
        report = validate_show(
            self.cue_set,
            play_folder=self.play_folder.folder if self.play_folder else None,
            output_device_available=self.audio.ready,
        )
        if report.show_ready and not report.warnings:
            self.status_lbl.setText(
                f"Validate Show: OK ({report.verified_audio_files} audio files verified)")
            return
        lines = []
        for issue in report.critical:
            lines.append(f"CRITICAL [{issue.cue_identifier or '-'}] {issue.message}")
        for issue in report.warnings:
            lines.append(f"warning [{issue.cue_identifier or '-'}] {issue.message}")
        QMessageBox.warning(self, "Validate Show", "\n".join(lines))
