"""Live instance controls must affect real PCM and never saved cue settings."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
import numpy as np
from PySide6.QtCore import Qt
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue, CueSet, AdvanceMode
from bhs_player.ui.main_window import MainWindow
from bhs_player.storage.store import serialize_cue_set


def test_level_changes_only_one_instance_and_preserves_fades():
    cue = Cue("1.0", volume=.5)
    audio = AudioEngine(Mixer(sample_rate=100))
    pcm = np.ones((100, 2), dtype=np.float32)
    first = audio.start(cue, pcm=pcm, sample_rate=100)
    second = audio.start(cue, pcm=pcm, sample_rate=100)
    assert audio.set_instance_level(first, .2)
    np.testing.assert_allclose(audio.mixer.render_block(10), .7)
    assert audio.voice_for(second)._gain == .5
    audio.fade_instance(first, .2)
    assert audio.set_instance_level(first, .4)
    block = audio.mixer.render_block(10)
    assert block[0, 0] > block[-1, 0]
    assert audio.voice_for(first).fading
    assert cue.volume == .5


def test_repeat_can_be_enabled_then_disabled_without_restarting():
    cue = Cue("1.0", loop=False)
    audio = AudioEngine(Mixer(sample_rate=100))
    inst = audio.start(cue, pcm=np.ones((10, 2), dtype=np.float32), sample_rate=100)
    assert audio.set_instance_repeat(inst, True)
    np.testing.assert_allclose(audio.mixer.render_block(25), 1)
    assert audio.voice_for(inst).pos == 5
    assert inst.looping
    assert audio.set_instance_repeat(inst, False)
    block = audio.mixer.render_block(10)
    np.testing.assert_allclose(block[:5], 1)
    np.testing.assert_allclose(block[5:], 0)
    assert inst.completed_naturally
    assert not audio.active_instances()
    assert not cue.loop
    assert not audio.set_instance_repeat(inst, True)
    assert not audio.set_instance_level(inst, .5)


def test_repeat_does_not_cancel_manual_fade():
    cue = Cue("1.0", loop=True)
    audio = AudioEngine(Mixer(sample_rate=100))
    inst = audio.start(cue, pcm=np.ones((20, 2), dtype=np.float32), sample_rate=100)
    audio.fade_instance(inst, .1)
    audio.set_instance_repeat(inst, False)
    audio.set_instance_repeat(inst, True)
    audio.mixer.render_block(15)
    assert not audio.active_instances()
    assert not inst.completed_naturally


def test_live_repeat_defers_automatic_go_until_final_completion():
    cue = Cue("1.0", advance_mode=AdvanceMode.ON_COMPLETE_GO)
    cs = CueSet("Test", [cue, Cue("2.0")])
    audio = AudioEngine(Mixer(sample_rate=100))
    start = audio.start
    audio.start = lambda c: start(c, pcm=np.ones((10, 2), dtype=np.float32), sample_rate=100)
    engine = CueEngine(cs, audio)
    engine.go()
    inst = audio.active_instances()[0]
    audio.set_instance_repeat(inst, True)
    audio.mixer.render_block(25)
    assert engine.waiting_cue is cue
    assert engine.process_pending_auto_go() is None
    audio.set_instance_repeat(inst, False)
    audio.mixer.render_block(10)
    assert engine.armed_cue is cs.cues[1]
    assert engine.process_pending_auto_go().ok


def test_card_defaults_live_changes_and_replay_reset_without_saving(qtbot):
    cue = Cue("1.0", "Music", volume=.65, loop=True, advance_mode=AdvanceMode.ON_GO)
    cs = CueSet("Test", [cue])
    audio = AudioEngine(Mixer())
    pcm = np.ones((44100, 2), dtype=np.float32)*.1
    first = audio.start(cue, pcm=pcm)
    second = audio.start(cue, pcm=pcm)
    win = MainWindow(cs, CueEngine(cs, audio), audio, confirm_close=False)
    before = serialize_cue_set(cs)
    qtbot.addWidget(win)
    win.show()
    entry = win._stack_entries[id(second)]
    assert entry.level_slider.value() == 65
    assert entry.repeat_check.isChecked()
    entry.level_slider.setValue(30)
    qtbot.mouseClick(entry.repeat_check, Qt.LeftButton)
    assert audio.voice_for(second)._gain == .3
    assert not audio.voice_for(second).looping
    assert not second.looping
    assert audio.voice_for(first)._gain == .65
    assert audio.voice_for(first).looping
    assert cue.volume == .65 and cue.loop
    replay = audio.start(cue, pcm=pcm)
    win._refresh()
    fresh = win._stack_entries[id(replay)]
    assert fresh.level_slider.value() == 65
    assert fresh.repeat_check.isChecked()
    # No live level/repeat overrides enter a save.
    assert serialize_cue_set(cs) == before
    win.close()


@pytest.mark.parametrize("mode",list(AdvanceMode))
def test_two_second_finish_uses_normal_end_action(mode):
    from bhs_player.cues.model import CueExecutionState
    cue=Cue("1.0",advance_mode=mode)
    target=Cue("2.0")
    audio=AudioEngine(Mixer(sample_rate=100))
    start=audio.start
    audio.start=lambda c:start(c,pcm=np.ones((1000,2),dtype=np.float32),sample_rate=100)
    engine=CueEngine(CueSet("Finish",[cue,target]),audio)
    assert engine.go().ok
    instance=audio.active_instances()[0]
    assert audio.finish_instance(instance)
    assert not audio.finish_instance(instance)  # Repeated clicks cannot extend the fade.
    block=audio.mixer.render_block(199)
    assert block[0,0]>block[-1,0]>0
    assert not instance.completed_naturally
    audio.mixer.render_block(1)
    assert instance.completed_naturally
    assert cue.execution_state is CueExecutionState.COMPLETE
    assert engine.armed_cue is target
    result=engine.process_pending_auto_go()
    if mode is AdvanceMode.ON_COMPLETE_GO:
        assert result.ok
        assert len(audio.active_instances())==1
    else:
        assert result is None
        assert not audio.active_instances()


def test_finish_loop_only_affects_selected_playback_and_stop_cancels_it(qtbot):
    from bhs_player.ui.main_window import PlayingStackEntry
    cue=Cue("1.0",loop=True,advance_mode=AdvanceMode.ON_GO)
    audio=AudioEngine(Mixer(sample_rate=100))
    pcm=np.ones((30,2),dtype=np.float32)*.1
    first=audio.start(cue,pcm=pcm,sample_rate=100)
    other=audio.start(cue,pcm=pcm,sample_rate=100)
    card=PlayingStackEntry(first,audio.voice_for(first),audio)
    qtbot.addWidget(card)
    qtbot.mouseClick(card.finish_btn,Qt.LeftButton)
    assert not card.finish_btn.isEnabled()
    audio.mixer.render_block(200)
    assert first.completed_naturally
    assert audio.voice_for(other).active
    assert cue.loop and cue.fade_out==0
    assert audio.finish_instance(other)
    audio.stop_instance(other)
    audio.mixer.render_block(201)
    assert not other.completed_naturally
    assert not audio.active_instances()
