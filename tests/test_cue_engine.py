"""Cue execution engine tests (Sections 2, 3, 4, 7, 10)."""

from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueExecutionState,
    CueSet,
    OnGoBehavior,
)
from tests.fakes import FakeAudioEngine


def make_engine(cues, ready=True):
    cs = CueSet(play_name="Clue", cues=cues)
    audio = FakeAudioEngine(ready=ready)
    return CueEngine(cs, audio), audio, cs


def play(identifier, **kw):
    return Cue(identifier=identifier, action=ActionType.PLAY, **kw)


# ---- basic GO / On Complete flow --------------------------------------

def test_first_cue_is_armed_at_start():
    eng, _, cs = make_engine([play("1.0"), play("2.0")])
    assert cs.cues[0].execution_state is CueExecutionState.ARMED
    assert eng.armed_cue is cs.cues[0]


def test_go_triggers_armed_on_complete_and_waits():
    eng, audio, cs = make_engine([play("1.0"), play("2.0")])
    result = eng.go()
    assert result.ok
    assert cs.cues[0].execution_state is CueExecutionState.PLAYING
    assert len(audio.active_instances()) == 1
    # pointer held: next cue not armed while sound plays
    assert eng.armed_cue is None
    ok, reason = eng.go_available()
    assert not ok


def test_on_complete_natural_end_advances_and_arms_next():
    eng, audio, cs = make_engine([play("1.0"), play("2.0")])
    eng.go()
    inst = audio.active_instances()[0]
    audio.finish(inst, natural=True)
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=True)
    assert cs.cues[0].execution_state is CueExecutionState.COMPLETE
    assert cs.cues[1].execution_state is CueExecutionState.ARMED
    # next cue must NOT auto-play
    assert len(audio.active_instances()) == 0
    assert audio.started_cues == [cs.cues[0].internal_id]


def test_second_go_required_for_newly_armed_cue():
    eng, audio, cs = make_engine([play("1.0"), play("2.0")])
    eng.go()
    audio.finish(audio.active_instances()[0], natural=True)
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=True)
    result = eng.go()
    assert result.ok
    assert audio.started_cues == [cs.cues[0].internal_id, cs.cues[1].internal_id]


def test_end_of_list_no_wrap():
    eng, audio, cs = make_engine([play("1.0")])
    eng.go()
    audio.finish(audio.active_instances()[0], natural=True)
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=True)
    assert eng.armed_cue is None
    result = eng.go()
    assert not result.ok
    assert result.reason


def test_go_unavailable_when_audio_not_ready():
    eng, audio, cs = make_engine([play("1.0")], ready=False)
    result = eng.go()
    assert not result.ok
    assert not audio.active_instances()
    assert cs.cues[0].execution_state is CueExecutionState.ARMED


def test_failed_start_does_not_advance():
    eng, audio, cs = make_engine([play("1.0"), play("2.0")])
    audio.fail_next_start = True
    result = eng.go()
    assert not result.ok
    assert "Failed to start" in result.reason
    assert cs.cues[0].execution_state is CueExecutionState.ARMED
    assert eng.armed_cue is cs.cues[0]


# ---- On GO / Trigger mode ----------------------------------------------

def test_on_go_trigger_advances_immediately_and_sound_continues():
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        play("2.0"),
    ])
    eng.go()
    assert cs.cues[0].execution_state is CueExecutionState.TRIGGERED
    assert cs.cues[1].execution_state is CueExecutionState.ARMED
    # sound 1 still playing while cue 2 armed — deliberate overlap
    assert len(audio.active_instances()) == 1
    eng.go()
    assert len(audio.active_instances()) == 2


def test_on_go_completion_does_not_move_pointer_again():
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        play("2.0"),
        play("3.0"),
    ])
    eng.go()  # fires 1.0, arms 2.0
    audio.finish(audio.active_instances()[0], natural=True)
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=True)
    assert cs.cues[0].execution_state is CueExecutionState.COMPLETE
    assert eng.armed_cue is cs.cues[1]  # pointer unchanged


# ---- On GO audio behaviors ---------------------------------------------

def test_stop_previous_behavior_stops_only_most_recent():
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        play("2.0", advance_mode=AdvanceMode.ON_GO),
        play("3.0", advance_mode=AdvanceMode.ON_GO,
             on_go_behavior=OnGoBehavior.STOP_PREVIOUS),
    ])
    eng.go()  # 1.0 playing
    eng.go()  # 2.0 playing
    eng.go()  # 3.0: stops 2.0 only
    active_ids = {i.cue_internal_id for i in audio.active_instances()}
    assert cs.cues[0].internal_id in active_ids  # 1.0 continues
    assert cs.cues[1].internal_id not in active_ids  # 2.0 stopped
    assert cs.cues[2].internal_id in active_ids  # 3.0 playing


def test_stop_all_behavior_clears_stack_then_starts():
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        play("2.0", advance_mode=AdvanceMode.ON_GO),
        play("3.0", on_go_behavior=OnGoBehavior.STOP_ALL),
    ])
    eng.go()
    eng.go()
    eng.go()
    assert audio.stop_all_calls == 1
    active_ids = {i.cue_internal_id for i in audio.active_instances()}
    assert active_ids == {cs.cues[2].internal_id}


def test_add_behavior_stops_nothing():
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        play("2.0", advance_mode=AdvanceMode.ON_GO),
    ])
    eng.go()
    eng.go()
    assert len(audio.active_instances()) == 2
    assert audio.stop_all_calls == 0


# ---- STOP / FADE / STOP ALL cue actions ---------------------------------

def test_stop_cue_stops_all_instances_of_target():
    target = play("1.0", advance_mode=AdvanceMode.ON_GO)
    stop = Cue(identifier="2.0", action=ActionType.STOP,
               target_internal_id=target.internal_id)
    # 1.5 must be ON_GO so the pointer advances to the STOP cue;
    # an On Complete cue would correctly hold the pointer (Section 3).
    eng, audio, cs = make_engine(
        [target, play("1.5", advance_mode=AdvanceMode.ON_GO), stop])
    eng.go()  # target playing
    eng.go()  # 1.5 playing
    assert len(audio.active_instances()) == 2
    eng.go()  # STOP cue
    assert audio.instances_of(target.internal_id) == []
    assert len(audio.instances_of(cs.cues[1].internal_id)) == 1
    # STOP cue completed and armed the next cue
    assert stop.execution_state is CueExecutionState.COMPLETE


def test_fade_cue_waits_for_fade_then_arms_next():
    target = play("1.0", advance_mode=AdvanceMode.ON_GO)
    fade = Cue(identifier="2.0", action=ActionType.FADE,
               target_internal_id=target.internal_id, fade_duration=3.0)
    eng, audio, cs = make_engine([target, fade, play("3.0")])
    eng.go()  # target playing
    eng.go()  # fade starts
    assert fade.execution_state is CueExecutionState.PLAYING
    assert eng.armed_cue is None  # fade still in progress
    assert audio.faded[0][1] == 3.0
    eng.notify_fade_finished(fade.internal_id)
    assert fade.execution_state is CueExecutionState.COMPLETE
    assert eng.armed_cue is cs.cues[2]


def test_fade_valid_target_not_playing_is_noop():
    target = play("1.0")
    fade = Cue(identifier="2.0", action=ActionType.FADE,
               target_internal_id=target.internal_id, fade_duration=2.0)
    eng, audio, cs = make_engine([target, fade, play("3.0")])
    eng.go()  # play 1.0 (On Complete, holds pointer)
    audio.finish(audio.active_instances()[0], natural=True)
    eng.notify_sound_finished(target.internal_id, natural=True)
    # now fade is armed; target no longer playing -> no-op completes
    eng.go()
    assert fade.execution_state is CueExecutionState.COMPLETE
    assert eng.armed_cue is cs.cues[2]


def test_stop_invalid_target_fails_visibly():
    stop = Cue(identifier="1.0", action=ActionType.STOP, target_internal_id="nope")
    eng, audio, cs = make_engine([stop, play("2.0")])
    result = eng.go()
    assert not result.ok
    assert stop.execution_state is CueExecutionState.ARMED


def test_stop_all_cue_action():
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        Cue(identifier="2.0", action=ActionType.STOP_ALL),
        play("3.0"),
    ])
    eng.go()
    eng.go()  # STOP ALL cue
    assert audio.stop_all_calls == 1
    assert eng.armed_cue is cs.cues[2]


# ---- Back, ARM CUE, re-arming ------------------------------------------

def test_back_moves_armed_to_previous_without_audio():
    eng, audio, cs = make_engine([play("1.0"), play("2.0"), play("3.0")])
    eng.go()
    audio.finish(audio.active_instances()[0], natural=True)
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=True)
    assert eng.armed_cue is cs.cues[1]
    assert eng.back()
    assert eng.armed_cue is cs.cues[0]
    assert not audio.active_instances()


def test_back_at_top_is_noop():
    eng, _, cs = make_engine([play("1.0")])
    assert not eng.back()
    assert eng.armed_cue is cs.cues[0]


def test_mouse_select_then_arm_previous_cue_replays():
    # Section 10 example: at 12.3, click 12.0, ARM CUE, Spacebar replays
    cues = [play("12.0"), play("12.1"), play("12.2"), play("12.3")]
    eng, audio, cs = make_engine(cues)
    for c in cues[:3]:  # burn through 12.0-12.2
        eng.go()
        audio.finish(audio.active_instances()[0], natural=True)
        eng.notify_sound_finished(c.internal_id, natural=True)
    assert eng.armed_cue is cues[3]
    assert eng.arm_cue(cues[0].internal_id)  # mouse-selected earlier cue
    assert cues[0].execution_state is CueExecutionState.ARMED
    eng.go()
    assert audio.started_cues.count(cues[0].internal_id) == 2


def test_rearm_does_not_disturb_existing_instance():
    cue = play("12.0", advance_mode=AdvanceMode.ON_GO)
    eng, audio, cs = make_engine([cue, play("12.1")])
    eng.go()
    assert len(audio.instances_of(cue.internal_id)) == 1
    eng.arm_cue(cue.internal_id)
    assert len(audio.instances_of(cue.internal_id)) == 1  # untouched
    eng.go()  # explicit replay: second instance
    assert len(audio.instances_of(cue.internal_id)) == 2


def test_interrupted_on_complete_leaves_nothing_armed():
    eng, audio, cs = make_engine([play("1.0"), play("2.0")])
    eng.go()
    inst = audio.active_instances()[0]
    audio.finish(inst, natural=False)  # manually stopped early
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=False)
    assert cs.cues[0].execution_state is CueExecutionState.INTERRUPTED
    assert eng.armed_cue is None
    # operator takes control: arm 2.0 deliberately
    eng.arm_cue(cs.cues[1].internal_id)
    assert eng.armed_cue is cs.cues[1]


def test_emergency_stop_all_leaves_nothing_armed_when_waiting():
    eng, audio, cs = make_engine([play("1.0"), play("2.0")])
    eng.go()
    eng.stop_all()
    assert audio.stop_all_calls == 1
    assert eng.armed_cue is None
    ok, _ = eng.go_available()
    assert not ok


def test_old_completion_cannot_override_operator_navigation():
    # Operator arms a different cue while an On GO sound still plays;
    # its later completion must not move the pointer.
    eng, audio, cs = make_engine([
        play("1.0", advance_mode=AdvanceMode.ON_GO),
        play("2.0"),
        play("3.0"),
    ])
    eng.go()  # 1.0 playing, 2.0 armed
    eng.arm_cue(cs.cues[2].internal_id)  # operator jumps to 3.0
    audio.finish(audio.active_instances()[0], natural=True)
    eng.notify_sound_finished(cs.cues[0].internal_id, natural=True)
    assert eng.armed_cue is cs.cues[2]


# ---- looping ------------------------------------------------------------

def test_looping_sound_stays_active_until_stopped():
    cue = play("1.0", loop=True, advance_mode=AdvanceMode.ON_GO)
    eng, audio, cs = make_engine([cue, play("2.0")])
    eng.go()
    inst = audio.instances_of(cue.internal_id)[0]
    assert inst.looping
    assert eng.armed_cue is cs.cues[1]
    # loop remains until explicit stop
    assert len(audio.active_instances()) == 1
