"""UI tests (pytest-qt, offscreen). Sections 9, 10, 13, 14."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import ActionType, AdvanceMode, Cue, CueExecutionState, CueSet
from bhs_player.ui.main_window import MainWindow

SR = 44100


def tone(seconds, amp=0.5):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_window(qapp, cues):
    cs = CueSet(play_name="Clue", cues=cues)
    audio = AudioEngine(Mixer(SR))
    engine = CueEngine(cs, audio)  # self-wires audio.on_instance_ended
    win = MainWindow(cs, engine, audio)
    return win, engine, audio, cs


def play(identifier, pcm=None, **kw):
    c = Cue(identifier=identifier, action=ActionType.PLAY, **kw)
    c._test_pcm = pcm if pcm is not None else tone(0.2)
    return c


def attach_pcm(audio):
    orig = audio.start
    def start(cue):
        return orig(cue, pcm=getattr(cue, "_test_pcm", tone(0.2)))
    audio.start = start


def test_initial_armed_and_go_enabled(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0"), play("2.0")])
    attach_pcm(audio)
    assert "1.0" in win.armed_lbl.text()
    assert win.go_btn.isEnabled()


def test_go_button_triggers_and_shows_playing(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0"), play("2.0")])
    attach_pcm(audio)
    win._go()
    win._refresh()
    assert cs.cues[0].execution_state is CueExecutionState.PLAYING
    assert win.armed_lbl.text() == "No cue armed"  # Waiting is not an armed cue
    assert "Waiting for 1.0" in win.armed_detail.text()
    assert not win.go_btn.isEnabled()


def test_clicking_cue_does_not_play_it(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0"), play("2.0")])
    attach_pcm(audio)
    win.cue_list.setCurrentRow(1)  # click cue 2.0
    assert len(audio.active_instances()) == 0  # selection is silent
    assert cs.cues[1].execution_state is not CueExecutionState.PLAYING


def test_arm_cue_button_arms_selection(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0"), play("2.0")])
    attach_pcm(audio)
    win.cue_list.setCurrentRow(1)
    win._arm_selected()
    assert engine.armed_cue is cs.cues[1]
    assert "2.0" in win.armed_lbl.text()


def test_stop_all_leaves_nothing_armed(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0"), play("2.0")])
    attach_pcm(audio)
    win._go()
    win._stop_all()
    assert audio.active_instances() == []
    assert engine.armed_cue is None
    assert "ARM button" in win.status_lbl.text()


def test_playing_stack_shows_active_sound(qapp):
    win, engine, audio, cs = make_window(
        qapp, [play("1.0", advance_mode=AdvanceMode.ON_GO, pcm=tone(2.0))])
    attach_pcm(audio)
    win._go()
    win._refresh()
    assert win.stack_area.count() == 1  # one entry for the active sound


def test_show_has_locked_bus_displays_and_no_master(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0")])
    assert not hasattr(win, 'master_slider')
    assert set(win.bus_displays) == {'main'}


def test_back_moves_armed_to_previous(qapp):
    win, engine, audio, cs = make_window(qapp, [play("1.0"), play("2.0")])
    attach_pcm(audio)
    win._go()
    # simulate natural finish to advance
    inst = audio.active_instances()[0]
    v = audio._find(inst)
    v.pos = v.frames  # force to end
    audio.mixer.render_block(1024)
    win._refresh()
    assert engine.armed_cue is cs.cues[1]
    win._back()
    assert engine.armed_cue is cs.cues[0]
