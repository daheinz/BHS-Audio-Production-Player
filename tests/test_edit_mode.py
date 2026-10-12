"""Edit Mode tests (Sections 12, 13)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.model import ActionType, AdvanceMode, Cue, CueSet
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.edit_window import EditWindow
from PySide6.QtWidgets import QMessageBox

SR = 44100


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_setup(tmp_path, cues=None):
    cs = CueSet(play_name="Clue", cues=cues or [])
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    audio = AudioEngine(Mixer(SR))
    win = EditWindow(cs, audio, pf)
    return win, cs, pf, audio


def write_wav(path: Path, seconds=0.2):
    n = int(seconds * SR)
    sf.write(str(path), np.zeros((n, 2), dtype=np.float32), SR)


# ---- cue list / ordering ---------------------------------------------------

def test_list_shows_cues_in_performance_order(qapp, tmp_path):
    cues = [Cue(identifier="47.2"), Cue(identifier="12.1"), Cue(identifier="12.10")]
    win, cs, pf, _ = make_setup(tmp_path, cues)
    texts = [win.list.item(i).text() for i in range(win.list.count())]
    assert texts[0].startswith("47.2")
    assert texts[1].startswith("12.1")
    assert texts[2].startswith("12.10")


def test_move_reorders_and_keeps_identifiers(qapp, tmp_path):
    cues = [Cue(identifier="1.0"), Cue(identifier="2.0"), Cue(identifier="3.0")]
    win, cs, pf, _ = make_setup(tmp_path, cues)
    win.list.setCurrentRow(2)
    win._move(-1)
    order = [c.identifier for c in cs.performance_order()]
    assert order == ["1.0", "3.0", "2.0"]


def test_next_identifier_suggestion(qapp, tmp_path):
    cues = [Cue(identifier="12.0"), Cue(identifier="12.1")]
    win, cs, pf, _ = make_setup(tmp_path, cues)
    assert win._next_identifier() == "12.2"
    empty, _, _, _ = make_setup(tmp_path / "e", [])
    assert empty._next_identifier() == "1.0"


# ---- cue editor validation -------------------------------------------------

def test_editor_rejects_bad_identifier(qapp, tmp_path):
    cs = CueSet(play_name="Clue")
    cue = Cue(identifier="1.0")
    dlg = CueEditorDialog(cue, cs, None)
    dlg.ident_edit.setText("not-a-cue-id")
    dlg._on_accept()
    assert dlg.result() == 0  # not accepted
    assert "script-page" in dlg.error_lbl.text()


def test_editor_rejects_duplicate_identifier(qapp, tmp_path):
    cs = CueSet(play_name="Clue", cues=[Cue(identifier="12.0")])
    cue = Cue(identifier="12.1")
    dlg = CueEditorDialog(cue, cs, None)
    dlg.ident_edit.setText("12.0")
    dlg._on_accept()
    assert "already in use" in dlg.error_lbl.text()


def test_editor_blocks_loop_with_on_complete(qapp, tmp_path):
    cs = CueSet(play_name="Clue")
    cue = Cue(identifier="1.0", action=ActionType.PLAY)
    dlg = CueEditorDialog(cue, cs, None)
    dlg.ident_edit.setText("1.0")
    dlg.loop_check.setChecked(True)
    dlg.advance_combo.setCurrentIndex(0)  # On Complete
    dlg._on_accept()
    assert "cannot use Advance Mode On Complete" in dlg.error_lbl.text()


def test_editor_applies_play_fields(qapp, tmp_path):
    cs = CueSet(play_name="Clue")
    cue = Cue(identifier="1.0", action=ActionType.PLAY)
    dlg = CueEditorDialog(cue, cs, None)
    dlg.ident_edit.setText("12.5")
    dlg.name_edit.setText("Thunder")
    dlg.file_row.setText("audio/thunder.wav")
    dlg.volume_spin.setValue(70.0)  # percent: 70% -> 0.7 relative
    dlg.loop_check.setChecked(True)
    dlg.advance_combo.setCurrentIndex(1)  # On GO
    dlg._on_accept()
    assert dlg.result() == 1
    assert cue.identifier == "12.5"
    assert cue.name == "Thunder"
    assert cue.audio_file == "audio/thunder.wav"
    assert cue.volume == 0.7
    assert cue.loop is True
    assert cue.advance_mode is AdvanceMode.ON_GO


def test_editor_requires_target_for_stop(qapp, tmp_path):
    target = Cue(identifier="1.0", action=ActionType.PLAY)
    cs = CueSet(play_name="Clue", cues=[target])
    stop = Cue(identifier="2.0", action=ActionType.STOP)
    dlg = CueEditorDialog(stop, cs, None)
    dlg.action_combo.setCurrentIndex(list(ActionType).index(ActionType.STOP))
    dlg.target_combo.setCurrentIndex(0)  # (none)
    dlg._on_accept()
    assert "Choose a target" in dlg.error_lbl.text()


# ---- audition / TEST --------------------------------------------------------

def test_audition_plays_without_touching_show_state(qapp, tmp_path):
    cue = Cue(identifier="12.0", action=ActionType.PLAY, audio_file="audio/a.wav")
    win, cs, pf, audio = make_setup(tmp_path, [cue])
    # audio must live in the play folder's audio dir (audio_file is relative)
    write_wav(pf.audio_dir / "a.wav")
    win.list.setCurrentRow(0)
    win._audition()
    assert win._test_instance is not None
    assert "TEST playing" in win.test_lbl.text()
    # show state untouched: cue not playing/triggered in show terms
    assert cue.execution_state.value == "idle"
    win._stop_audition()
    assert win._test_instance is None


def test_audition_requires_play_cue(qapp, tmp_path):
    cue = Cue(identifier="1.0", action=ActionType.STOP_ALL)
    win, cs, pf, audio = make_setup(tmp_path, [cue])
    win.list.setCurrentRow(0)
    win._audition()
    assert win._test_instance is None
    assert "Select a PLAY cue" in win.status_lbl.text()


# ---- save -------------------------------------------------------------------

def test_save_creates_new_version(qapp, tmp_path):
    win, cs, pf, audio = make_setup(tmp_path, [Cue(identifier="1.0")])
    win._save()
    assert len(pf.list_versions()) == 1
    cs.insert(Cue(identifier="2.0"))
    win._save()
    assert len(pf.list_versions()) == 2  # never overwrite


def test_edit_marks_recovery_autosave(qapp, tmp_path):
    win, cs, pf, audio = make_setup(tmp_path, [Cue(identifier="1.0")])
    win.list.setCurrentRow(0)
    win._move(0)  # no-op move still marks edited via _mark_edited? force:
    win._mark_edited()
    assert pf.has_recovery()
    assert "Unsaved changes" in win.status_lbl.text()


def test_remove_cue_warns_about_dependents(qapp, tmp_path, monkeypatch):
    target = Cue(identifier="1.0", action=ActionType.PLAY)
    stop = Cue(identifier="2.0", action=ActionType.STOP,
               target_internal_id=target.internal_id)
    win, cs, pf, audio = make_setup(tmp_path, [target, stop])
    win.list.setCurrentRow(0)
    # auto-answer No so nothing is deleted; we just want the warning text
    seen = {}
    def fake_question(parent, title, msg):
        seen["msg"] = msg
        return QMessageBox.No
    monkeypatch.setattr("bhs_player.ui.edit_window.QMessageBox.question", fake_question)
    win._remove_cue()
    assert "target of" in seen["msg"]
    assert "2.0" in seen["msg"]
    assert len(cs.cues) == 2  # nothing removed
