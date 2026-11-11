"""Edit Mode window (Sections 12, 13).

Add/remove/update/reorder cues, assign audio (auto-import), audition/TEST,
and save versions. Editing a nonplaying cue never interrupts audio. Audition
playback is isolated from show advancement and labeled TEST.
"""

from __future__ import annotations
from .theme import ViewingModeControl
from .audio_health import show_diagnostics

from typing import Optional
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Slot, QThreadPool

from PySide6.QtWidgets import (
    QHBoxLayout,
    QSplitter,
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
from .cue_table import CueTable
from .save_changes import SaveState


# ---- cue row display + tooltips (Sections 5, 11) --------------------------

_ADVANCE_LABEL = {mode: mode.label for mode in AdvanceMode}

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
        return base + "   |   " + tail + "  " + _ADVANCE_LABEL[cue.advance_mode]
    return base


def cue_row_tooltip(cue: Cue, cue_set: CueSet) -> str:
    """Mouse-over help explaining the cue's fields."""
    lines = [f"Cue {cue.identifier} — {cue.name or '(unnamed)'}"]

    def add(label, value, expl):
        lines.append(f"{label}: {value} — {expl}")

    add("Action", cue.action.value, "what GO executes for this cue")
    if cue.action is ActionType.PLAY:
        add("Volume", f"{cue.volume * 100:.0f}%",
            "playback level before the assigned bus output level")
        add("Fade-In", f"{cue.fade_in:g}s",
            "time to ramp from silence to full volume at start (0 = instant)")
        add("Fade-Out", f"{cue.fade_out:g}s",
            "default duration used by FADE OUT controls (0 = instant stop)")
        add("Loop", "On" if cue.loop else "Off",
            "repeat the segment until stopped/faded")
        add("Next Cue Action", _ADVANCE_LABEL[cue.advance_mode],
            "Arm Next at End arms the next cue at natural end; GO on End "
            "arms it immediately and executes it at natural end; Arm Next Now arms it immediately for overlap")
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
        add("Next Cue Action", _ADVANCE_LABEL[cue.advance_mode],
            "arm immediately, arm after this action finishes, or automatically GO on completion")
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
                 on_save=None, parent=None, routing=None):
        super().__init__(parent)
        self.routing = routing
        self.cue_set = cue_set
        self.save_state = SaveState(cue_set)
        self.audio = audio
        self.play_folder = play_folder
        self.on_save = on_save
        self.setWindowTitle(f"Edit - {cue_set.play_name}")
        self.resize(1500, 860)
        self._test_instance = None
        self._test_request = 0
        self._test_cue_id: Optional[str] = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        heading = QLabel(f"{cue_set.play_name}  /  EDIT")
        heading.setStyleSheet("font-size: 25px; font-weight: bold; padding: 8px 0")
        root.addWidget(heading)
        viewing_row = QHBoxLayout()
        viewing_row.addWidget(ViewingModeControl(self))
        viewing_row.addStretch(1)
        root.addLayout(viewing_row)
        profile_row = QHBoxLayout()
        self.profile_label = QLabel("")
        self.profile_label.setWordWrap(True)
        profile_row.addWidget(self.profile_label, 1)
        profile_btn = QPushButton("Profile and Routing...")
        profile_btn.clicked.connect(self._profile)
        tester_btn = QPushButton("Pre-Audience Audio Test...")
        tester_btn.clicked.connect(self._audio_test)
        recheck_btn = QPushButton("Recheck Audio")
        recheck_btn.setToolTip("Force full validation of production audio, bypassing cached validation results.")
        recheck_btn.clicked.connect(self._recheck_audio)
        for btn in (profile_btn, tester_btn, recheck_btn):
            profile_row.addWidget(btn)
        root.addLayout(profile_row)
        self.routing_notice = QLabel("")
        self.routing_notice.setWordWrap(True)
        self._refresh_profile()

        self.list = CueTable(cue_set, editable=True, play_folder=play_folder, defer_audio=bool(getattr(audio, "nonblocking", False)))
        self.cue_table = self.list
        self.list.setMinimumHeight(140)
        self.list.cueChanged.connect(self._mark_edited)
        self.list.audioTestRequested.connect(self._audition)
        self.list.editRejected.connect(lambda message: self.status_lbl.setText(message))
        self.list.audioImportStatus.connect(lambda message: self.status_lbl.setText(message))
        self.list.currentRowChanged.connect(lambda _r: self._update_buttons())
        self.editor_splitter = QSplitter(Qt.Vertical)
        self.editor_splitter.addWidget(self.list)
        root.addWidget(self.editor_splitter, 1)
        from .clip_editor import ClipEditor
        self.clip_editor = ClipEditor(self)
        self.clip_editor.setMaximumHeight(260)
        self.clip_editor.plot.setMinimumHeight(100)
        self.clip_editor.edited.connect(self._apply_clip)
        self.list.currentRowChanged.connect(lambda _: self._sync_clip())
        self.list.cueChanged.connect(self._sync_clip)
        self.editor_splitter.addWidget(self.clip_editor)
        self.editor_splitter.setStretchFactor(0, 1)
        self.editor_splitter.setStretchFactor(1, 0)
        self.editor_splitter.setSizes([360, 240])

        root.addWidget(QLabel("Drag left-edge handles to reorder. Amber Cue IDs mark numeric reversals. Double-click cells to edit."))

        from .edit_dashboard import EditDashboard
        self.dashboard = EditDashboard(self)
        root.addWidget(self.dashboard)

        # ~25 Hz refresh for TEST progress/meters (Section 9)
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_test)
        self._timer.start(40)

        self._rebuild()
        self._update_buttons()
        if play_folder is not None and play_folder.latest_version() is None:
            self.save_state.force_unsaved = True

    def resizeEvent(self, event):
        # Preserve the normal waveform height on desktop windows while allowing
        # cue rows and controls to fit in narrower/shorter windows.
        if hasattr(self, "clip_editor"):
            compact = event.size().width() < 1300 or event.size().height() < 850
            self.clip_editor.plot.setMinimumHeight(100 if compact else 170)
        super().resizeEvent(event)

    def set_entry_busy(self, busy, rehearsal=False):
        self.show_btn.setEnabled(not busy)
        self.rehearse_btn.setEnabled(not busy)
        self.show_btn.setText("PLEASE WAIT..." if busy and not rehearsal else "ENTER SHOW MODE")
        self.rehearse_btn.setText("PLEASE WAIT..." if busy and rehearsal else "REHEARSE")
        # Override the normal green action styling while the action is unavailable.
        self.show_btn.setStyleSheet(
            "font-weight: bold; padding: 10px 24px; background: "
            + ("#454b54; color: #c9ced6;" if busy else "#2e7d32; color: white;"))
        if busy:
            self.entry_progress.begin(len(self.cue_set.cues), rehearsal)
        else:
            self.entry_progress.finish()

    def _refresh_profile(self):
        p = self.cue_set.profile
        self.profile_label.setText(f"Profile: {p.name}  ·  " + " / ".join(f"{b.name} ({b.shape}, {b.level*100:g}%)" for b in p.buses))
        notes = list(self.cue_set.migration_notes)
        if self.routing:
            notes.append(self.routing.unsupported() or "Stereo playback connected. Run the Pre-Audience Audio Test before Show.")
        else:
            notes.append("Output integration unavailable in this window.")
        self.routing_notice.setText("\n".join(notes))

    def _profile(self):
        from .profile_dialog import ProfileDialog
        from dataclasses import asdict
        dlg = ProfileDialog(self.cue_set, self)
        if dlg.exec() and asdict(dlg.profile) != asdict(self.cue_set.profile):
            self._stop_audition()
            self.cue_set.profile = dlg.profile
            if self.routing:
                self.routing.invalidate()
            self._mark_edited()
            self._rebuild()
        self._refresh_profile()

    def _audio_test(self):
        if not self.routing:
            self.status_lbl.setText("Output integration unavailable.")
            return
        self._stop_audition()
        from .audio_test_dialog import AudioTestDialog
        AudioTestDialog(self.routing, self).exec()
        self._refresh_profile()

    def _advanced(self):
        cue = self._selected_cue()
        if cue is None:
            self.status_lbl.setText("Select a cue first.")
            return
        from .cue_editor_dialog import CueEditorDialog
        from dataclasses import asdict
        before = asdict(cue)
        if CueEditorDialog(cue, self.cue_set, self.play_folder, self).exec() and asdict(cue) != before:
            self._mark_edited()
            self._rebuild()

    def _refresh_test(self) -> None:
        """Drive TEST progress/meter from the actual audition voice."""
        active = bool(self.audio.active_instances())
        self.audio_health.refresh(idle=not active)
        backend = getattr(self.routing, "backend", None)
        preview = bool(getattr(self.routing, "preview", False))
        lost = bool(getattr(backend, "output_lost", False))
        state = "Preview / no audio" if preview else "Error - output not ready" if lost or not self.audio.ready else "Playing" if active else "Ready - Idle"
        tone = "neutral" if preview else "error" if lost or not self.audio.ready else "success"
        self.engine_state.setText(state)
        if self.engine_state.property("tone") != tone:
            self.engine_state.setProperty("tone", tone)
            self.engine_state.style().unpolish(self.engine_state)
            self.engine_state.style().polish(self.engine_state)
        identity = getattr(backend, "selected_identity", None) or "No output selected"
        self.device_label.setText("Output: " + identity)
        self.device_label.setToolTip(identity)
        self.status_lbl.setToolTip(self.status_lbl.text())
        self.routing_notice.setToolTip(self.routing_notice.text())
        self._update_buttons()
        self.test_lbl.setVisible(bool(self.test_lbl.text()))
        if self._test_instance is None:
            return
        voice = self.audio.voice_for(self._test_instance)
        if voice is None or not voice.active:
            self._stop_audition()
            return
        from ..audio.engine import _to_db
        self.test_progress.update()
        if self.clip_editor.cue and self.clip_editor.cue.internal_id == self._test_cue_id:
            self.clip_editor.plot.playhead = (voice.cue.start_position or 0)+voice.position_seconds
            self.clip_editor.plot.update()
        self.test_meter.set_levels(_to_db(voice.last_peak_l),
                                   _to_db(voice.last_peak_r),
                                   voice.last_peak_l >= 1.0 or voice.last_peak_r >= 1.0)

    # ---- list -------------------------------------------------------------
    def _rebuild(self):
        self.list.rebuild()
        if hasattr(self, "clip_editor"):
            self._sync_clip()

    def _sync_clip(self):
        if hasattr(self, 'clip_editor'):
            self.clip_editor.set_cue(self._selected_cue(), self.cue_set, self.play_folder)

    def _apply_clip(self, values):
        cue = self._selected_cue()
        if cue is None or self.clip_editor.cue is not cue:
            return
        from dataclasses import replace
        import math
        keys = ('start_position', 'end_position', 'fade_in', 'fade_out') if cue.is_play_sound() else ('fade_duration',) if cue.action is ActionType.FADE else ()
        updates = {key: values[key] for key in keys}
        try:
            if any(value is not None and (not math.isfinite(value) or value < 0) for value in updates.values()):
                raise ValueError('Clip times must be finite and nonnegative.')
            candidate = replace(cue, **updates)
            data = self.clip_editor.data
            if cue.is_play_sound() and data and not candidate.segment_valid(data.duration):
                raise ValueError('Keep Start before End and within the source recording.')
            if not any(getattr(cue,key) != value for key,value in updates.items()):
                return
            for key, value in updates.items():
                setattr(cue, key, value)
            self._mark_edited()
            self.list.rebuild()
        except ValueError as exc:
            self.status_lbl.setText(str(exc))
        self._sync_clip()

    def _selected_index(self) -> int:
        return self.list.currentRow()

    def _selected_cue(self) -> Optional[Cue]:
        i = self._selected_index()
        return self.cue_set.cues[i] if 0 <= i < len(self.cue_set.cues) else None

    def _update_buttons(self):
        cue = self._selected_cue()
        row = self._selected_index()
        self.del_btn.setEnabled(cue is not None)
        self.up_btn.setEnabled(cue is not None and row > 0)
        self.down_btn.setEnabled(cue is not None and row < len(self.cue_set.cues)-1)
        self.test_btn.setEnabled(bool(cue and cue.is_play_sound() and cue.audio_file))
        self.import_btn.setEnabled(bool(cue and cue.is_play_sound()))
        self.advanced_btn.setEnabled(cue is not None)
        self.stop_test_btn.setEnabled(self._test_instance is not None or bool(self.test_lbl.text()))

    # ---- cue operations ----------------------------------------------------
    def _browse_audio(self):
        cue = self._selected_cue()
        if cue is None or not cue.is_play_sound():
            self.status_lbl.setText("Select a PLAY cue to assign audio.")
            return
        self.list.browse_audio(self._selected_index())

    def _add_cue(self):
        cue = Cue(identifier=self._next_identifier())
        while self.cue_set.by_identifier(cue.identifier):
            page, sub = cue.identifier.split('.')
            cue.identifier = f'{page}.{int(sub) + 1}'
        idx = self._selected_index()
        position = idx + 1 if idx >= 0 else len(self.cue_set.cues)
        self.cue_set.insert(cue, index=position)
        self._rebuild()
        self.list.setCurrentCell(position, 1)
        self.list.editItem(self.list.item(position, 1))
        self._mark_edited()

    def _remove_cue(self):
        cue = self._selected_cue()
        if cue is None:
            return
        # Referenced targets cannot be removed until links are reconciled.
        dependents = [c for c in self.cue_set.cues
                      if c.target_internal_id == cue.internal_id]
        if dependents:
            box = QMessageBox(self)
            box.setWindowTitle("Cue Is Linked")
            box.setText(f"Cannot remove {cue.identifier}. Linked cues: " + ", ".join(c.identifier for c in dependents))
            review = box.addButton("Review Linked Cues", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is review:
                from .linked_cues_dialog import LinkedCuesDialog
                LinkedCuesDialog(self.cue_set, cue, self._mark_edited, self).exec()
                self._rebuild()
            return
        msg = f"Remove cue {cue.identifier}?"
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
    def _audition(self, cue_internal_id=None):
        cue = self.cue_set.by_internal_id(cue_internal_id) if isinstance(cue_internal_id, str) else self._selected_cue()
        if cue is None or not cue.is_play_sound():
            self.status_lbl.setText("Select a PLAY cue to test.")
            return
        if not cue.audio_file:
            self.status_lbl.setText("Cue has no audio file.")
            return
        if self.routing is None or not self.routing.prepare("primary"):
            self.status_lbl.setText(self.routing.message if self.routing else "Configure an output in Profile & Routing first.")
            return
        self._stop_audition()
        self._attempt_audition(cue.internal_id, self._test_request)

    def _attempt_audition(self, cue_id, token):
        if token != self._test_request:
            return
        cue = self.cue_set.by_internal_id(cue_id)
        if cue is None or not cue.audio_file or not self.audio.ready:
            return
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
            if str(exc).startswith("Preparing audio"):
                self.test_lbl.setText("Preparing TEST audio...")
                QTimer.singleShot(50, self, lambda: self._attempt_audition(cue_id, token))
            else:
                self.test_lbl.setText("")
                self.status_lbl.setText(f"TEST failed: {exc}")

    def _stop_audition(self):
        self._test_request += 1
        self.test_lbl.setText("")
        if self._test_instance is not None:
            self.audio.stop_instance(self._test_instance)
            self._test_instance = None
            self.clip_editor.plot.playhead = None
            self.clip_editor.plot.update()
            self.test_lbl.setText("")
            self.test_progress.clear()
            self.test_progress.setVisible(False)
            self.test_meter.setVisible(False)

    # ---- save --------------------------------------------------------------
    def _save(self):
        # Finish any open inline editor before capturing the saved version.
        if self.list.has_pending_imports:
            self.status_lbl.setText("Wait for the audio import check to finish before saving.")
            return False
        self.list.setFocus()
        if self.play_folder is None:
            self.status_lbl.setText("No play folder; cannot save.")
            return False
        if not self.save_state.has_changes:
            self.status_lbl.setText("No changes to save.")
            return True
        try:
            path = self.play_folder.save_version(self.cue_set)
            self.save_state.mark_saved()
            self.status_lbl.setText(f"Saved: {path.name}")
            if self.on_save:
                self.on_save(self.cue_set)
            return True
        except Exception as exc:
            self.status_lbl.setText(f"Save failed: {exc}")
            return False

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
        self.list.setFocus()
        if self.save_state.has_changes and not self._save():
            QMessageBox.warning(self, "Save Required Before Exit", self.status_lbl.text())
            event.ignore()
            return
        self._timer.stop()
        self.list.cancel_imports()
        self._stop_audition()
        if self.routing:
            self.routing.audio.stop_all()
            self.routing.backend.stop()
        super().closeEvent(event)

    def _enter_show(self, rehearsal=False):
        """app.main assigns enter_show(); guard if run standalone."""
        fn = getattr(self, "enter_show", None)
        if callable(fn):
            fn(rehearsal=rehearsal)
        else:
            self.status_lbl.setText("Show Mode is launched by the main app.")

    def _recheck_audio(self):
        if getattr(self,'_recheck_job',None) is not None:
            return
        self._stop_audition()
        from ..audio.safe_decode import inspect_audio
        from .background import FileTask
        paths=[]
        for cue in self.cue_set.cues:
            if cue.is_play_sound() and cue.audio_file:
                path=Path(cue.audio_file)
                if self.play_folder and not path.is_absolute():path=self.play_folder.folder/path
                if path not in paths:paths.append(path)
        def check():
            issues=[]
            for path in paths:
                try:inspect_audio(path,full=True,force=True)
                except Exception as exc:issues.append(f"{path.name}: {exc}")
            return len(paths),issues
        self._recheck_job=FileTask(check)
        self._recheck_job.signals.done.connect(self._audio_rechecked)
        self.status_lbl.setText("Rechecking all audio files - full validation...")
        QThreadPool.globalInstance().start(self._recheck_job)

    @Slot(object,str)
    def _audio_rechecked(self,result,error):
        self._recheck_job=None
        if error:
            self.status_lbl.setText("Audio recheck failed: "+error[:220])
            return
        total,issues=result
        self.audio.clear_preparation()
        import logging
        for issue in issues:logging.getLogger('bhs_player.audio').error("MANUAL AUDIO RECHECK %s",issue)
        self.status_lbl.setText(f"Audio recheck: {total-len(issues)}/{total} files passed."+
                               (" "+issues[0][:180]+" See Diagnostics / Logs." if issues else ""))

    def _validate_show(self):
        """Explicit Validate Show control (Section 19)."""
        from ..validate.check import validate_show
        if getattr(self, '_readiness_job', None) is not None:
            return
        from copy import deepcopy
        from .background import FileTask
        cues = deepcopy(self.cue_set)
        folder = self.play_folder.folder if self.play_folder else None
        ready = self.audio.ready
        self._readiness_job = FileTask(lambda: validate_show(cues, folder, output_device_available=ready))
        self._readiness_job.signals.done.connect(self._readiness_checked)
        self.status_lbl.setText("Checking audio files for Show Readiness...")
        QThreadPool.globalInstance().start(self._readiness_job)

    @Slot(object, str)
    def _readiness_checked(self, report, error):
        self._readiness_job = None
        if error:
            self.status_lbl.setText("Readiness check failed: " + error[:220])
            return
        if self.routing:
            from ..validate.check import Severity
            reason = self.routing.unsupported()
            if reason:
                report.add(Severity.CRITICAL, None, reason)
            for name in self.routing.unconfirmed():
                report.add(Severity.WARNING, None, f"Audio not confirmed at board: {name}")
        profile = self.cue_set.profile
        version = self.play_folder.latest_version().name if self.play_folder and self.play_folder.latest_version() else "Not saved"
        summary = [f"Production: {self.cue_set.play_name}", f"Latest saved version: {version}",
                   f"Cues: {len(self.cue_set.cues)} | Verified audio: {report.verified_audio_files}",
                   f"Profile: {profile.name} | Buses: {len(profile.buses)}",
                   f"Primary device: {profile.primary_device or 'Not selected'}",
                   f"Backup device: {profile.backup_device or 'Not configured'}",
                   f"Changes: {'Unsaved / recovery' if self.save_state.has_changes else 'Saved'}"]
        if self.routing:
            summary.append(self.routing.message)
            summary.append("Backup audibility: " + ("Confirmed" if "backup" in self.routing.confirmations else "Not confirmed"))
        lines = [f"BLOCKER [{issue.cue_identifier or 'Production'}] {issue.message}" for issue in report.critical]
        lines += [f"Warning [{issue.cue_identifier or 'Production'}] {issue.message}" for issue in report.warnings]
        box = QMessageBox(self)
        box.setWindowTitle("Show Readiness")
        box.setText("\n".join(summary) + "\n\n" + ("\n".join(lines) or "Validation passed. Physical audibility and performance reliability still require testing."))
        profile_btn = box.addButton("Profile and Routing", QMessageBox.ActionRole)
        test_btn = box.addButton("Run Audio Test", QMessageBox.ActionRole)
        review_btn = box.addButton("Review Cues", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is profile_btn:
            self._profile()
        elif box.clickedButton() is test_btn:
            self._audio_test()
        elif box.clickedButton() is review_btn:
            issue = next((i for i in report.critical if i.cue_identifier), None)
            cue = self.cue_set.by_identifier(issue.cue_identifier) if issue else None
            if cue:
                self.list.setCurrentRow(self.cue_set.index_of(cue.internal_id))
            self.list.setFocus()
