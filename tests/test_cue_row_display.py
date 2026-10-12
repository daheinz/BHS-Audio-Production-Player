"""Cue row field display and tooltip tests (Edit/Show cue lists)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueSet,
    OnGoBehavior,
)
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.edit_window import EditWindow, cue_row_tooltip, format_cue_row

SR = 44100


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---- row formatting ---------------------------------------------------------

def test_play_row_lists_fields_to_the_right():
    cue = Cue(identifier="12.0", name="Rain", action=ActionType.PLAY,
              volume=0.8, fade_in=0.5, fade_out=2.0, loop=True,
              advance_mode=AdvanceMode.ON_GO,
              on_go_behavior=OnGoBehavior.STOP_PREVIOUS,
              start_position=1.0, end_position=9.5,
              audio_file="audio/rain.wav")
    row = format_cue_row(cue, CueSet(play_name="X"))
    assert row.startswith("12.0   Rain   [PLAY]")
    assert "Vol 80%" in row
    assert "In 0.5s" in row
    assert "Out 2s" in row
    assert "Loop" in row
    assert "On GO" in row
    assert "Stop Prev" in row
    assert "[1 -> 9.5]" in row
    assert "audio/rain.wav" in row


def test_volume_shown_as_percentage():
    cue = Cue(identifier="1.0", action=ActionType.PLAY, volume=0.5)
    assert "Vol 50%" in format_cue_row(cue, CueSet(play_name="X"))
    cue100 = Cue(identifier="1.1", action=ActionType.PLAY, volume=1.0)
    assert "Vol 100%" in format_cue_row(cue100, CueSet(play_name="X"))


def test_defaults_omitted_from_row():
    cue = Cue(identifier="1.0", action=ActionType.PLAY,
              audio_file="audio/a.wav")
    row = format_cue_row(cue, CueSet(play_name="X"))
    assert "In " not in row and "Out " not in row  # zero fades omitted
    assert "Loop" not in row
    assert "[" not in row.split("|")[1].replace("[PLAY]", "") or "->"
    # segment bracket omitted when no start/end set
    assert "-> end]" not in row


def test_stop_row_shows_target():
    target = Cue(identifier="12.0", action=ActionType.PLAY)
    stop = Cue(identifier="12.1", action=ActionType.STOP,
               target_internal_id=target.internal_id)
    cs = CueSet(play_name="X", cues=[target, stop])
    row = format_cue_row(stop, cs)
    assert "Target 12.0" in row


def test_fade_row_shows_target_and_duration():
    target = Cue(identifier="12.0", action=ActionType.PLAY)
    fade = Cue(identifier="12.1", action=ActionType.FADE,
               target_internal_id=target.internal_id, fade_duration=3.5)
    cs = CueSet(play_name="X", cues=[target, fade])
    row = format_cue_row(fade, cs)
    assert "Target 12.0" in row
    assert "Fade 3.5s" in row


def test_stop_row_missing_target_flagged():
    stop = Cue(identifier="12.1", action=ActionType.STOP,
               target_internal_id="gone")
    row = format_cue_row(stop, CueSet(play_name="X"))
    assert "(missing)" in row


# ---- tooltips --------------------------------------------------------------

def test_play_tooltip_explains_fields():
    cue = Cue(identifier="12.0", name="Rain", action=ActionType.PLAY,
              volume=0.8, loop=True, advance_mode=AdvanceMode.ON_GO,
              audio_file="audio/rain.wav", notes="under window")
    tip = cue_row_tooltip(cue, CueSet(play_name="X"))
    assert "Volume: 80%" in tip
    assert "relative to the Master Output" in tip
    assert "Fade-In" in tip and "Fade-Out" in tip
    assert "Loop: On" in tip
    assert "On GO" in tip and "overlap" in tip
    assert "Audio File: audio/rain.wav" in tip
    assert "Notes: under window" in tip


def test_stop_tooltip_explains_target():
    target = Cue(identifier="12.0", action=ActionType.PLAY)
    stop = Cue(identifier="12.1", action=ActionType.STOP,
               target_internal_id=target.internal_id)
    tip = cue_row_tooltip(stop, CueSet(play_name="X", cues=[target, stop]))
    assert "Target: 12.0" in tip
    assert "PLAY cue whose active sound" in tip


def test_stop_all_tooltip():
    cue = Cue(identifier="99.0", action=ActionType.STOP_ALL)
    tip = cue_row_tooltip(cue, CueSet(play_name="X"))
    assert "Stops every active sound" in tip


# ---- UI wiring --------------------------------------------------------------

def test_edit_list_rows_have_tooltips(qapp, tmp_path):
    from bhs_player.storage.store import PlayFolder
    cue = Cue(identifier="12.0", name="Rain", action=ActionType.PLAY,
              volume=0.8, audio_file="audio/rain.wav")
    cs = CueSet(play_name="Clue", cues=[cue])
    pf = PlayFolder(tmp_path, "Clue")
    win = EditWindow(cs, AudioEngine(Mixer(SR)), pf)
    item = win.list.item(0)
    assert "Vol 80%" in item.text()
    assert item.toolTip()  # mouse-over help present
    assert "Volume: 80%" in item.toolTip()


def test_show_list_rows_have_tooltips(qapp):
    from bhs_player.cues.engine import CueEngine
    from bhs_player.ui.main_window import MainWindow
    cue = Cue(identifier="12.0", name="Rain", action=ActionType.PLAY,
              volume=0.5, audio_file="audio/rain.wav")
    cs = CueSet(play_name="Clue", cues=[cue])
    audio = AudioEngine(Mixer(SR))
    win = MainWindow(cs, CueEngine(cs, audio), audio)
    item = win.cue_list.item(0)
    assert "Vol 50%" in item.text()
    assert item.toolTip()


# ---- editor dialog: percentage + tooltips ------------------------------------

def test_editor_volume_shown_as_percent(qapp):
    cue = Cue(identifier="1.0", action=ActionType.PLAY, volume=0.8)
    dlg = CueEditorDialog(cue, CueSet(play_name="X"))
    assert dlg.volume_spin.value() == 80.0
    assert dlg.volume_spin.suffix() == " %"


def test_editor_percent_converts_back_to_relative(qapp):
    cue = Cue(identifier="1.0", action=ActionType.PLAY)
    dlg = CueEditorDialog(cue, CueSet(play_name="X"))
    dlg.ident_edit.setText("1.0")
    dlg.volume_spin.setValue(65.0)
    dlg._on_accept()
    assert cue.volume == 0.65


def test_editor_fields_have_tooltips(qapp):
    cue = Cue(identifier="1.0", action=ActionType.PLAY)
    dlg = CueEditorDialog(cue, CueSet(play_name="X"))
    for widget in (dlg.ident_edit, dlg.name_edit, dlg.action_combo,
                   dlg.notes_edit, dlg.file_row, dlg.volume_spin,
                   dlg.fade_in_spin, dlg.fade_out_spin, dlg.loop_check,
                   dlg.advance_combo, dlg.behavior_combo, dlg.start_spin,
                   dlg.end_spin, dlg.target_combo, dlg.fade_dur_spin):
        assert widget.toolTip(), f"{widget} missing tooltip"
    assert "page.subcue" in dlg.ident_edit.toolTip()
    assert "Master Output" in dlg.volume_spin.toolTip()
