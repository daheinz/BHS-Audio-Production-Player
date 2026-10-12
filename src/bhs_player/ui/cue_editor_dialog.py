"""Cue editor dialog: edit all properties of a single cue (Sections 5, 11).

Identifier is validated as script-page TEXT. STOP/FADE cues pick a target
PLAY cue. Audio file can be chosen from the play folder or imported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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
        self.setWindowTitle(f"Edit Cue {cue.identifier or '(new)'}")
        self.setModal(True)
        self.resize(520, 560)

        root = QVBoxLayout(self)
        form = QFormLayout()

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
            "Playback level as a percentage, relative to the Master Output "
            "Level. 100% = unity gain, 50% = half, 200% = double (may clip).")
        form.addRow("Volume", self.volume_spin)

        self.fade_in_spin = QDoubleSpinBox()
        self.fade_in_spin.setRange(0.0, 60.0)
        self.fade_in_spin.setSuffix(" s")
        self.fade_in_spin.setValue(cue.fade_in)
        self.fade_in_spin.setToolTip(
            "Seconds to ramp from silence up to the cue volume when playback "
            "starts. 0 = start instantly at full level.")
        form.addRow("Fade-In", self.fade_in_spin)

        self.fade_out_spin = QDoubleSpinBox()
        self.fade_out_spin.setRange(0.0, 60.0)
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
            "Must use Advance Mode 'On GO / Trigger' (looping never completes).")
        form.addRow("Loop", self.loop_check)

        self.advance_combo = QComboBox()
        self.advance_combo.addItem("On Complete", AdvanceMode.ON_COMPLETE)
        self.advance_combo.addItem("On GO / Trigger", AdvanceMode.ON_GO)
        self.advance_combo.setCurrentIndex(
            0 if cue.advance_mode is AdvanceMode.ON_COMPLETE else 1)
        self.advance_combo.setToolTip(
            "On Complete: hold the pointer until the sound finishes, then arm "
            "the next cue. On GO / Trigger: arm the next cue immediately so "
            "sounds can overlap; the sound keeps playing independently.")
        form.addRow("Advance Mode", self.advance_combo)

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
        self.start_spin.setRange(0.0, 86400.0)
        self.start_spin.setSuffix(" s")
        self.start_spin.setSpecialValueText("(start of file)")
        self.start_spin.setValue(cue.start_position or 0.0)
        self.start_spin.setToolTip(
            "Optional point in the file to start playing from (seconds). "
            "Leave at '(start of file)' to play from the beginning.")
        form.addRow("Start Position", self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, 86400.0)
        self.end_spin.setSuffix(" s")
        self.end_spin.setSpecialValueText("(end of file)")
        self.end_spin.setValue(cue.end_position or 0.0)
        self.end_spin.setToolTip(
            "Optional point in the file to stop playing (seconds). "
            "Leave at '(end of file)' to play to the end.")
        form.addRow("End Position", self.end_spin)

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
        self.fade_dur_spin.setRange(0.0, 300.0)
        self.fade_dur_spin.setSuffix(" s")
        self.fade_dur_spin.setValue(cue.fade_duration)
        self.fade_dur_spin.setToolTip(
            "Seconds for this FADE cue to bring the target sound to silence. "
            "0 = stop immediately.")
        self.fade_dur_label = QLabel("Fade Duration")
        form.addRow(self.fade_dur_label, self.fade_dur_spin)

        root.addLayout(form)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #e07070;")
        root.addWidget(self.error_lbl)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_enabled()

    # -- enable/disable fields by action type ------------------------------
    def _update_enabled(self):
        action = self.action_combo.currentData()
        is_play = action is ActionType.PLAY
        is_stopfade = action in (ActionType.STOP, ActionType.FADE)

        for w in (self.file_row, self.volume_spin, self.fade_in_spin,
                  self.fade_out_spin, self.loop_check, self.advance_combo,
                  self.behavior_combo, self.start_spin, self.end_spin):
            w.setEnabled(is_play)
        self.file_label.setEnabled(is_play)

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
        try:
            rel = self.play_folder.import_audio(Path(path))
            self.file_row.setText(str(rel).replace("\\", "/"))
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))

    def _on_accept(self):
        identifier = self.ident_edit.text().strip()
        if not validate_identifier(identifier):
            self.error_lbl.setText(
                "Identifier must follow the script-page convention (e.g. 12.0, 47.21).")
            return
        existing = self.cue_set.by_identifier(identifier)
        if existing is not None and existing is not self.cue:
            self.error_lbl.setText(f"Identifier '{identifier}' is already in use.")
            return

        action = self.action_combo.currentData()
        cue = self.cue
        cue.identifier = identifier
        cue.name = self.name_edit.text().strip()
        cue.action = action
        cue.notes = self.notes_edit.text().strip()

        if action is ActionType.PLAY:
            cue.audio_file = self.file_row.text().strip() or None
            cue.volume = self.volume_spin.value() / 100.0  # shown as percent
            cue.fade_in = self.fade_in_spin.value()
            cue.fade_out = self.fade_out_spin.value()
            cue.loop = self.loop_check.isChecked()
            cue.advance_mode = self.advance_combo.currentData()
            cue.on_go_behavior = self.behavior_combo.currentData()
            sp = self.start_spin.value()
            ep = self.end_spin.value()
            cue.start_position = sp if sp > 0 else None
            cue.end_position = ep if ep > 0 else None
            if cue.start_position is not None and cue.end_position is not None \
                    and cue.start_position >= cue.end_position:
                self.error_lbl.setText("Start Position must be before End Position.")
                return
            if cue.loop and cue.advance_mode is AdvanceMode.ON_COMPLETE:
                self.error_lbl.setText(
                    "Loop On cannot use Advance Mode On Complete (Section 7).")
                return
            cue.target_internal_id = None
        else:
            cue.audio_file = None
            cue.target_internal_id = (
                self.target_combo.currentData() if action in (ActionType.STOP, ActionType.FADE)
                else None)
            cue.fade_duration = (
                self.fade_dur_spin.value() if action is ActionType.FADE else 0.0)
            if action in (ActionType.STOP, ActionType.FADE) and not cue.target_internal_id:
                self.error_lbl.setText("Choose a target PLAY cue.")
                return

        self.accept()
