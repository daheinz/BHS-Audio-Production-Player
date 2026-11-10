"""Stop and Fade actions honor editable, persisted Next Cue Action choices."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import numpy as np
import pytest
from bhs_player.cues.model import Cue,CueSet,ActionType,AdvanceMode,CueExecutionState
from bhs_player.cues.engine import CueEngine
from bhs_player.audio.engine import AudioEngine,Mixer
from bhs_player.storage.store import serialize_cue_set,deserialize_cue_set


def setup(action,mode,duration=.2):
    target=Cue("1.0",advance_mode=AdvanceMode.ON_GO)
    action_cue=Cue("2.0",action=action,target_internal_id=target.internal_id,
                   advance_mode=mode,fade_duration=duration)
    following=Cue("3.0")
    cs=CueSet("Actions",[target,action_cue,following])
    audio=AudioEngine(Mixer(sample_rate=100))
    start=audio.start
    audio.start=lambda cue:start(cue,pcm=np.ones((1000,2),dtype=np.float32)*.1,sample_rate=100)
    engine=CueEngine(cs,audio)
    return engine,audio,cs


@pytest.mark.parametrize("action",[ActionType.STOP,ActionType.FADE])
@pytest.mark.parametrize("mode",list(AdvanceMode))
def test_action_honors_choice_and_waits_for_all_fade_targets(action,mode):
    engine,audio,cs=setup(action,mode)
    target,action_cue,following=cs.cues
    assert engine.go().ok
    audio.start(target)  # Both current instances are targeted.
    assert engine.go().ok
    if action is ActionType.FADE:
        assert (engine.armed_cue is following)==(mode is not AdvanceMode.ON_COMPLETE)
        assert engine.process_pending_auto_go() is None
        audio.mixer.render_block(19)
        assert engine.process_pending_auto_go() is None
        audio.mixer.render_block(1)
    assert action_cue.execution_state is CueExecutionState.COMPLETE
    assert engine.armed_cue is following
    assert not audio.active_instances()
    result=engine.process_pending_auto_go()
    assert (result is not None)==(mode is AdvanceMode.ON_COMPLETE_GO)
    if result:assert result.ok
    assert engine.process_pending_auto_go() is None


@pytest.mark.parametrize("action",[ActionType.STOP,ActionType.FADE])
@pytest.mark.parametrize("mode",list(AdvanceMode))
def test_action_with_silent_target_completes_immediately(action,mode):
    engine,audio,cs=setup(action,mode)
    engine.arm_cue(cs.cues[1].internal_id)
    assert engine.go().ok
    assert engine.armed_cue is cs.cues[2]
    result=engine.process_pending_auto_go()
    assert (result is not None)==(mode is AdvanceMode.ON_COMPLETE_GO)


def test_manual_go_during_auto_fade_cancels_late_automatic_go():
    engine,audio,cs=setup(ActionType.FADE,AdvanceMode.ON_COMPLETE_GO)
    engine.go();engine.go()
    assert engine.go().ok
    audio.mixer.render_block(20)
    assert engine.process_pending_auto_go() is None
    assert cs.cues[1].execution_state is CueExecutionState.COMPLETE
    assert len(audio.active_instances())==1


def test_zero_fade_go_on_end_and_emergency_stop_cancellation():
    engine,audio,cs=setup(ActionType.FADE,AdvanceMode.ON_COMPLETE_GO,duration=0)
    engine.go();engine.go()
    assert engine.armed_cue is cs.cues[2]
    assert engine.process_pending_auto_go().ok
    engine,audio,cs=setup(ActionType.FADE,AdvanceMode.ON_COMPLETE_GO)
    engine.go();engine.go();engine.stop_all()
    audio.mixer.render_block(30)
    assert engine.process_pending_auto_go() is None
    assert cs.cues[1].execution_state is CueExecutionState.INTERRUPTED


@pytest.mark.parametrize("action",[ActionType.STOP,ActionType.FADE])
def test_editors_allow_and_save_action_choice(action,qtbot):
    from bhs_player.ui.cue_table import CueTable,FIELDS
    from bhs_player.ui.cue_editor_dialog import CueEditorDialog
    engine,audio,cs=setup(action,AdvanceMode.ON_COMPLETE)
    cue=cs.cues[1]
    table=CueTable(cs,editable=True)
    qtbot.addWidget(table)
    assert table.applicable(cue,"advance_mode")
    assert table.commit(1,"advance_mode",AdvanceMode.ON_COMPLETE_GO)
    dlg=CueEditorDialog(cue,cs)
    qtbot.addWidget(dlg)
    assert dlg.advance_combo.isEnabled()
    dlg.advance_combo.setCurrentIndex(dlg.advance_combo.findData(AdvanceMode.ON_GO))
    dlg._on_accept()
    assert cue.advance_mode is AdvanceMode.ON_GO
    assert deserialize_cue_set(serialize_cue_set(cs)).cues[1].advance_mode is AdvanceMode.ON_GO


def test_later_playback_of_same_target_does_not_extend_fade_wait():
    engine,audio,cs=setup(ActionType.FADE,AdvanceMode.ON_COMPLETE_GO)
    engine.go();engine.go()
    later=audio.start(cs.cues[0])
    audio.mixer.render_block(20)
    assert audio.voice_for(later).active
    assert cs.cues[1].execution_state is CueExecutionState.COMPLETE
    assert engine.process_pending_auto_go().ok


def test_five_second_fade_starts_immediately_and_logs_target(caplog):
    import logging
    engine,audio,cs=setup(ActionType.FADE,AdvanceMode.ON_COMPLETE,duration=5)
    engine.go()
    instance=audio.active_instances()[0]
    with caplog.at_level(logging.INFO,logger="bhs_player.cues"):
        assert engine.go().ok
    voice=audio.voice_for(instance)
    assert voice.fading and voice._fade_total==500
    audio.mixer.render_block(499)
    assert audio.voice_for(instance).active
    audio.mixer.render_block(1)
    assert not audio.active_instances()
    assert engine.armed_cue is cs.cues[2]
    assert any("target=1.0" in r.message and "duration=5" in r.message
               and "active_playbacks=1" in r.message for r in caplog.records)
