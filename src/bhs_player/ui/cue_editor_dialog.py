"""Cue editor dialog: edit all properties of a single cue (Sections 5, 11).

Identifier is validated as script-page TEXT. STOP/FADE cues pick a target
PLAY cue. Audio file can be chosen from the play folder or imported.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace, fields
from typing import Optional

from PySide6.QtCore import Slot, QThreadPool
from .background import FileTask

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QScrollArea,
    QWidget,
)

from ..cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueSet,
    OnGoBehavior,
    validate_identifier,
)
from ..storage.store import PlayFolder


class CueEditorDialog(QDialog):
    """Edit one cue. On accept, applies fields onto the cue object."""

    def __init__(self, cue: Cue, cue_set: CueSet,
                 play_folder: Optional[PlayFolder] = None, parent=None):
        super().__init__(parent)
        self.cue = cue
        self.cue_set = cue_set
        self.play_folder = play_folder
        self.setWindowTitle(f"Advanced Cue Editor — {cue.identifier or '(new)'}")
        self.setModal(True)
        self.resize(900, 780)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow(QLabel("GENERAL"))

        self.ident_edit = QLineEdit(cue.identifier)
        self.ident_edit.setToolTip(
            "Cue number based on the script page: page.subcue (e.g. 12.0, 12.1, "
            "47.21). Stored as text; 12.10 stays 12.10.")
        form.addRow("Cue Identifier", self.ident_edit)

        self.name_edit = QLineEdit(cue.name)
        self.name_edit.setToolTip("Human-readable cue name shown in the cue list "
                                  "and on the Show Mode ARMED display.")
        form.addRow("Cue Name", self.name_edit)

        self.action_combo = QComboBox()
        for a in ActionType:
            self.action_combo.addItem(a.value, a)
        self.action_combo.setCurrentIndex(list(ActionType).index(cue.action))
        self.action_combo.currentIndexChanged.connect(self._update_enabled)
        self.action_combo.setToolTip(
            "PLAY: start an audio file. STOP: stop a target sound now. "
            "FADE: fade a target sound to silence. STOP ALL: stop everything.")
        form.addRow("Action Type", self.action_combo)

        self.notes_edit = QLineEdit(cue.notes)
        self.notes_edit.setToolTip("Free-form notes for the operator "
                                   "(e.g. 'after the second gunshot').")
        form.addRow("Notes", self.notes_edit)

        form.addRow(QLabel("PLAYBACK - used by PLAY cues"))
        # --- audio file (PLAY cues) ---
        self.file_row = QLineEdit(cue.audio_file or "")
        self.file_row.setPlaceholderText("audio/...  (relative to play folder)")
        self.file_row.setToolTip(
            "Path to the audio file, relative to the play folder "
            "(e.g. audio/thunder.wav). Use Browse/Import to copy a file in.")
        browse = QDialogButtonBox()
        browse_btn = browse.addButton("Browse/Import…", QDialogButtonBox.ActionRole)
        browse_btn.setToolTip("Choose an audio file from anywhere; it is copied "
                              "into the play's audio folder automatically.")
        browse_btn.clicked.connect(self._browse_audio)
        file_layout = QVBoxLayout()
        file_layout.addWidget(self.file_row)
        file_layout.addWidget(browse)
        self.file_label = QLabel("Audio File")
        form.addRow(self.file_label, file_layout)

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setRange(0.0, 400.0)
        self.volume_spin.setSingleStep(5.0)
        self.volume_spin.setSuffix(" %")
        self.volume_spin.setValue(cue.volume * 100.0)
        self.volume_spin.setToolTip(
            "Playback level as a percentage, before its assigned Bus Output "
            "Level. 100% = unity gain, 50% = half, 200% = double (may clip).")
        form.addRow("Volume", self.volume_spin)

        self.fade_in_spin = QDoubleSpinBox()
        self.fade_in_spin.setDecimals(6)
        self.fade_in_spin.setRange(0.0, max(86400.0, cue.fade_in))
        self.fade_in_spin.setSuffix(" s")
        self.fade_in_spin.setValue(cue.fade_in)
        self.fade_in_spin.setToolTip(
            "Seconds to ramp from silence up to the cue volume when playback "
            "starts. 0 = start instantly at full level.")
        form.addRow("Fade-In", self.fade_in_spin)

        self.fade_out_spin = QDoubleSpinBox()
        self.fade_out_spin.setDecimals(6)
        self.fade_out_spin.setRange(0.0, max(86400.0, cue.fade_out))
        self.fade_out_spin.setSuffix(" s")
        self.fade_out_spin.setValue(cue.fade_out)
        self.fade_out_spin.setToolTip(
            "Default seconds used by this sound's FADE OUT control. "
            "0 = stop instantly.")
        form.addRow("Fade-Out", self.fade_out_spin)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.setChecked(cue.loop)
        self.loop_check.setToolTip(
            "On: repeat the segment continuously until stopped or faded. "
            "Must use Next Cue Action 'Arm Next Now' (looping never completes).")
        form.addRow("Loop", self.loop_check)

        self.advance_combo = QComboBox()
        for mode in AdvanceMode:
            self.advance_combo.addItem(mode.label, mode)
        self.advance_combo.setCurrentIndex(self.advance_combo.findData(cue.advance_mode))
        self.advance_combo.setToolTip(
            "Arm Next at End: arm the next cue when this action finishes. "
            "GO on End: arm the next cue now, then execute it when this action finishes. "
            "Arm Next Now: arm the next cue immediately without automatic GO. "
            "Fade finishes after its fade; Stop finishes immediately.")
        form.addRow("Next Cue Action", self.advance_combo)

        self.behavior_combo = QComboBox()
        self.behavior_combo.addItem("Add Sound to Playing Stack", OnGoBehavior.ADD_TO_STACK)
        self.behavior_combo.addItem("Stop Previous and Add", OnGoBehavior.STOP_PREVIOUS)
        self.behavior_combo.addItem("Stop All and Add", OnGoBehavior.STOP_ALL)
        self.behavior_combo.setCurrentIndex(
            list(OnGoBehavior).index(cue.on_go_behavior))
        self.behavior_combo.setToolTip(
            "What happens to already-playing sounds when GO fires this cue: "
            "leave them all, stop only the most recent, or stop everything.")
        form.addRow("On GO Audio Behavior", self.behavior_combo)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setDecimals(6)
        self.start_spin.setRange(0.0, 86400.0)
        self.start_spin.setSuffix(" s")
        self.start_spin.setSpecialValueText("(start of file)")
        self.start_spin.setValue(cue.start_position or 0.0)
        self.start_spin.setToolTip(
            "Optional point in the file to start playing from (seconds). "
            "Leave at '(start of file)' to play from the beginning.")
        form.addRow("Start Position", self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setDecimals(6)
        self.end_spin.setRange(0.0, 86400.0)
        self.end_spin.setSuffix(" s")
        self.end_spin.setSpecialValueText("(end of file)")
        self.end_spin.setValue(cue.end_position or 0.0)
        self.end_spin.setToolTip(
            "Optional point in the file to stop playing (seconds). "
            "Leave at '(end of file)' to play to the end.")
        form.addRow("End Position", self.end_spin)

        form.addRow(QLabel("ACTION TARGET - used by STOP / FADE"))
        # --- STOP / FADE target ---
        self.target_combo = QComboBox()
        self.target_combo.addItem("(none)", None)
        play_cues = [c for c in cue_set.cues if c.is_play_sound() and c is not cue]
        sel = 0
        for i, c in enumerate(play_cues, start=1):
            self.target_combo.addItem(f"{c.identifier}  {c.name}", c.internal_id)
            if cue.target_internal_id == c.internal_id:
                sel = i
        self.target_combo.setCurrentIndex(sel)
        self.target_combo.setToolTip(
            "The PLAY cue whose active sound this STOP/FADE acts on. The link "
            "survives renumbering and reordering (internal stable reference).")
        self.target_label = QLabel("Target PLAY cue")
        form.addRow(self.target_label, self.target_combo)

        self.fade_dur_spin = QDoubleSpinBox()
        self.fade_dur_spin.setDecimals(6)
        self.fade_dur_spin.setRange(0.0, max(86400.0, cue.fade_duration))
        self.fade_dur_spin.setSuffix(" s")
        self.fade_dur_spin.setValue(cue.fade_duration)
        self.fade_dur_spin.setToolTip(
            "Seconds for this FADE cue to bring the target sound to silence. "
            "0 = stop immediately.")
        self.fade_dur_label = QLabel("Fade Duration")
        form.addRow(self.fade_dur_label, self.fade_dur_spin)

        form.addRow(QLabel("OUTPUT ROUTING"))
        self.bus_checks = []
        buses = QVBoxLayout()
        for bus in cue_set.profile.buses:
            check = QCheckBox(f"{bus.name} ({bus.shape})")
            check.setChecked(bus.id in cue.bus_ids)
            self.bus_checks.append((bus.id, check))
            buses.addWidget(check)
        form.addRow("Output buses (one or more)", buses)
        content = QWidget()
        content.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        from .clip_editor import ClipEditor
        self.clip_editor = ClipEditor(self)
        self.clip_editor.setMaximumHeight(260)
        root.addWidget(self.clip_editor)
        root.addWidget(scroll, 1)

        self.error_lbl = QLabel("")
        self.error_lbl.setProperty("tone", "error")
        root.addWidget(self.error_lbl)

        self._import_job = None
        self._import_cancelled = False
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._timing_baseline = {key: spin.value() for key, spin in self._timing_spins().items()}
        self.clip_editor.edited.connect(self._graph_edited)
        for spin in (self.start_spin, self.end_spin, self.fade_in_spin, self.fade_out_spin, self.fade_dur_spin):
            spin.setDecimals(6)
            spin.setSingleStep(.1)
            spin.valueChanged.connect(self._sync_graph_values)
        self.file_row.textChanged.connect(self._refresh_graph)
        self.target_combo.currentIndexChanged.connect(self._refresh_graph)
        self.action_combo.currentIndexChanged.connect(self._refresh_graph)
        self.loop_check.toggled.connect(self._refresh_graph)
        self._refresh_graph()
        self._update_enabled()

    def _timing_spins(self):
        return dict(start_position=self.start_spin, end_position=self.end_spin,
                    fade_in=self.fade_in_spin, fade_out=self.fade_out_spin,
                    fade_duration=self.fade_dur_spin)

    def _graph_values(self):
        result = {}
        for key, spin in self._timing_spins().items():
            if spin.value() == self._timing_baseline[key]:
                result[key] = getattr(self.cue, key)
            else:
                result[key] = (spin.value() or None) if key in ('start_position','end_position') else spin.value()
        return result

    def _refresh_graph(self, *_):
        draft = replace(self.cue, action=self.action_combo.currentData(),
                        audio_file=self.file_row.text().strip() or None,
                        target_internal_id=self.target_combo.currentData(),
                        loop=self.loop_check.isChecked(), **self._graph_values())
        if hasattr(self.cue, '_preview_waveform'):
            draft._preview_waveform = self.cue._preview_waveform
        self.clip_editor.set_cue(draft, self.cue_set, self.play_folder)

    def _sync_graph_values(self, *_):
        self.clip_editor.set_values(self._graph_values())

    def _graph_edited(self, values):
        for key, spin in (('start_position',self.start_spin), ('end_position',self.end_spin),
                          ('fade_in',self.fade_in_spin), ('fade_out',self.fade_out_spin), ('fade_duration',self.fade_dur_spin)):
            blocked = spin.blockSignals(True)
            spin.setValue(values.get(key) or 0)
            spin.blockSignals(blocked)
        self._sync_graph_values()

    # -- enable/disable fields by action type ------------------------------
    def _update_enabled(self):
        action = self.action_combo.currentData()
        is_play = action is ActionType.PLAY
        is_stopfade = action in (ActionType.STOP, ActionType.FADE)

        for w in (self.file_row, self.volume_spin, self.fade_in_spin,
                  self.fade_out_spin, self.loop_check,
                  self.behavior_combo, self.start_spin, self.end_spin):
            w.setEnabled(is_play)
        self.advance_combo.setEnabled(is_play or is_stopfade)
        self.file_label.setEnabled(is_play)
        for _, check in self.bus_checks:
            check.setEnabled(is_play)

        self.target_combo.setEnabled(is_stopfade)
        self.target_label.setEnabled(is_stopfade)
        self.fade_dur_spin.setEnabled(action is ActionType.FADE)
        self.fade_dur_label.setEnabled(action is ActionType.FADE)

    def _browse_audio(self):
        if self.play_folder is None:
            QMessageBox.information(self, "No Play Folder",
                                    "Save the play first so audio can be imported.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Audio File", "",
            "Audio Files (*.wav *.mp3 *.flac *.aac *.m4a *.ogg);;All Files (*)")
        if not path:
            return
        if self._import_job is not None:
            self.error_lbl.setText("An audio check is already running.")
            return
        from ..audio.safe_decode import inspect_audio
        self._import_job = FileTask(lambda: (inspect_audio(path, full=True, analyze_peaks=True), path))
        self._import_job.signals.done.connect(self._audio_checked)
        self.error_lbl.setText("Checking audio before import...")
        QThreadPool.globalInstance().start(self._import_job)

    @Slot(object, str)
    def _audio_checked(self, result, error):
        self._import_job = None
        if self._import_cancelled:
            return
        if error:
            self.error_lbl.setText("Audio import rejected: " + error[:220] + " See Diagnostics / Logs.")
            return
        try:
            metadata, path = result
            rel = self.play_folder.import_audio(Path(path), prevalidated=True)
            self.file_row.setText(str(rel).replace("\\", "/"))
            from .import_warnings import show_import_warnings
            candidate = replace(self.cue, volume=self.volume_spin.value() / 100,
                                bus_ids=[bus_id for bus_id, check in self.bus_checks if check.isChecked()])
            warning = show_import_warnings(self, metadata, candidate, self.cue_set.profile)
            self.error_lbl.setText("Imported - level warning; see warning dialog." if warning else "")
        except Exception as exc:
            self.error_lbl.setText("Audio import rejected: " + str(exc)[:220])

    def done(self, result):
        self._import_cancelled = True
        super().done(result)

    def _on_accept(self):
        if self._import_job is not None:
            self.error_lbl.setText("Wait for the audio import check, or Cancel.")
            return
        identifier = self.ident_edit.text().strip()
        if not validate_identifier(identifier):
            self.error_lbl.setText(
                "Identifier must follow the script-page convention (e.g. 12.0, 47.21).")
            return
        existing = self.cue_set.by_identifier(identifier, exclude=self.cue)
        if existing is not None:
            self.error_lbl.setText(f"Identifier '{identifier}' is already in use as '{existing.identifier}'.")
            return

        action = self.action_combo.currentData()
        cue = replace(self.cue)
        cue.identifier = identifier
        cue.name = self.name_edit.text().strip()
        cue.action = action
        cue.notes = self.notes_edit.text().strip()
        if action in (ActionType.PLAY, ActionType.STOP, ActionType.FADE):
            cue.advance_mode = self.advance_combo.currentData()

        if action is ActionType.PLAY:
            cue.audio_file = self.file_row.text().strip() or None
            cue.volume = self.volume_spin.value() / 100.0  # shown as percent
            cue.fade_in = self._graph_values()["fade_in"]
            cue.fade_out = self._graph_values()["fade_out"]
            cue.loop = self.loop_check.isChecked()
            cue.advance_mode = self.advance_combo.currentData()
            cue.on_go_behavior = self.behavior_combo.currentData()
            cue.start_position = self._graph_values()["start_position"]
            cue.end_position = self._graph_values()["end_position"]
            if cue.start_position is not None and cue.end_position is not None \
                    and cue.start_position >= cue.end_position:
                self.error_lbl.setText("Start Position must be before End Position.")
                return
            if cue.loop and cue.advance_mode is AdvanceMode.ON_COMPLETE:
                self.error_lbl.setText(
                    "Loop requires Arm Next Now; it cannot finish naturally.")
                return
            if self.clip_editor.data and not cue.segment_valid(self.clip_editor.data.duration):
                self.error_lbl.setText("Start / End must be within the source recording.")
                return
            cue.target_internal_id = None
        else:
            cue.audio_file = None
            cue.target_internal_id = (
                self.target_combo.currentData() if action in (ActionType.STOP, ActionType.FADE)
                else None)
            cue.fade_duration = (
                self._graph_values()["fade_duration"] if action is ActionType.FADE else 0.0)
            if action in (ActionType.STOP, ActionType.FADE) and not cue.target_internal_id:
                self.error_lbl.setText("Choose a target PLAY cue.")
                return

        if action is ActionType.PLAY:
            cue.bus_ids = [id for id, check in self.bus_checks if check.isChecked()]
            if not cue.bus_ids:
                self.error_lbl.setText("Choose at least one output bus.")
                return
        for f in fields(cue):
            setattr(self.cue, f.name, getattr(cue, f.name))
        self.accept()
