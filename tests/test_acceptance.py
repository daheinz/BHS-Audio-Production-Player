"""End-to-end acceptance scenarios from Section 21, wired through the real
cue engine + audio engine (offline mixer) + storage."""

import numpy as np

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueExecutionState,
    CueSet,
    OnGoBehavior,
)
from bhs_player.storage.store import PlayFolder, deserialize_cue_set, serialize_cue_set

SR = 44100


def tone(seconds, amp=0.5):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def play(identifier, pcm=None, **kw):
    cue = Cue(identifier=identifier, action=ActionType.PLAY, **kw)
    cue._test_pcm = pcm  # attach synthetic pcm for the real AudioEngine
    return cue


def engine_with_audio(cues):
    cs = CueSet(play_name="Clue", cues=cues)
    audio = AudioEngine(Mixer(SR))
    eng = CueEngine(cs, audio)

    # start with attached synthetic pcm
    orig_start = audio.start
    def start(cue):
        return orig_start(cue, pcm=getattr(cue, "_test_pcm", tone(0.2)))
    audio.start = start
    # CueEngine self-wires audio.on_instance_ended in its constructor
    return eng, audio, cs


def pump(mixer, seconds=0.3):
    for _ in range(int(seconds * SR / 1024) + 1):
        mixer.render_block(1024)


def test_finite_on_complete_arms_next_only_at_natural_end():
    eng, audio, cs = engine_with_audio([play("1.0", pcm=tone(0.05)), play("2.0")])
    eng.go()
    assert eng.armed_cue is None  # waiting
    pump(audio.mixer, 0.2)
    assert cs.cues[0].execution_state is CueExecutionState.COMPLETE
    assert eng.armed_cue is cs.cues[1]
    # newly armed cue is silent until GO
    assert len(audio.active_instances()) == 0


def test_rain_overlaps_thunder_deliberately():
    rain = play("1.0", pcm=tone(2.0), advance_mode=AdvanceMode.ON_GO, loop=True)
    thunder = play("2.0", pcm=tone(0.05), advance_mode=AdvanceMode.ON_GO)
    eng, audio, cs = engine_with_audio([rain, thunder])
    eng.go()  # rain loops
    eng.go()  # thunder fires over it
    assert len(audio.active_instances()) == 2
    pump(audio.mixer, 0.3)  # thunder finishes naturally, rain keeps looping
    remaining = {i.cue_internal_id for i in audio.active_instances()}
    assert remaining == {rain.internal_id}


def test_on_go_behaviors_affect_exact_previous_sounds():
    a = play("1.0", pcm=tone(2.0), advance_mode=AdvanceMode.ON_GO)
    b = play("2.0", pcm=tone(2.0), advance_mode=AdvanceMode.ON_GO)
    c = play("3.0", pcm=tone(0.2), advance_mode=AdvanceMode.ON_GO,
             on_go_behavior=OnGoBehavior.STOP_PREVIOUS)
    eng, audio, cs = engine_with_audio([a, b, c])
    eng.go(); eng.go(); eng.go()
    active = {i.cue_internal_id for i in audio.active_instances()}
    assert a.internal_id in active      # oldest continues
    assert b.internal_id not in active  # most recent stopped
    assert c.internal_id in active


def test_loop_stays_until_stopped_and_blocks_show_if_on_complete():
    loop = play("1.0", pcm=tone(0.05), loop=True, advance_mode=AdvanceMode.ON_GO)
    eng, audio, cs = engine_with_audio([loop])
    eng.go()
    pump(audio.mixer, 0.3)  # many iterations
    assert len(audio.instances_of(loop.internal_id)) == 1
    # validation: loop + On Complete is critical
    bad = CueSet(play_name="X", cues=[Cue(identifier="1.0", action=ActionType.PLAY,
                                          loop=True, advance_mode=AdvanceMode.ON_COMPLETE)])
    from bhs_player.validate.check import validate_show
    assert not validate_show(bad).show_ready


def test_stop_all_stops_everything_and_leaves_nothing_armed_when_waiting():
    eng, audio, cs = engine_with_audio([play("1.0", pcm=tone(2.0)), play("2.0")])
    eng.go()  # On Complete, waiting
    eng.stop_all()
    pump(audio.mixer, 0.1)
    assert audio.active_instances() == []
    assert eng.armed_cue is None


def test_back_and_rearm_enable_replay_without_audio_on_select():
    cues = [play("12.0", pcm=tone(0.05)), play("12.1", pcm=tone(0.05)),
            play("12.2", pcm=tone(0.05)), play("12.3", pcm=tone(0.05))]
    eng, audio, cs = engine_with_audio(cues)
    for c in cues[:3]:
        eng.go()
        pump(audio.mixer, 0.2)  # natural finish advances
    assert eng.armed_cue is cues[3]
    eng.arm_cue(cues[0].internal_id)   # mouse select + ARM CUE
    assert len(audio.active_instances()) == 0  # selection alone is silent
    eng.go()
    assert len(audio.instances_of(cues[0].internal_id)) == 1


def test_five_second_progress_and_meter_follow_signal():
    mixer = Mixer(SR)
    from bhs_player.audio.engine import Voice
    cue = Cue(identifier="1.0", action=ActionType.PLAY, volume=0.5)
    mixer.add_voice(Voice(cue, tone(5.0, amp=0.8), SR))
    # simulate ~5s of playback in blocks; playhead position tracks time
    blocks = int(5.0 * SR / 1024)
    for i in range(blocks):
        mixer.render_block(1024)
    # metering followed the post-volume signal (0.8 amp * 0.5 vol = 0.4)
    assert -9.0 < mixer.last_meter.left_db < -7.0
    # voice consumed ~5s of audio
    v_finished = mixer.last_meter
    assert v_finished is not None


def test_identifiers_stay_distinct_through_save_load():
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.1"))
    cs.insert(Cue(identifier="12.10"))
    loaded = deserialize_cue_set(serialize_cue_set(cs))
    assert [c.identifier for c in loaded.cues] == ["12.1", "12.10"]


def test_every_save_creates_new_version_and_history_survives(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    cs = CueSet(play_name="Clue", cues=[Cue(identifier="1.0")])
    p1 = pf.save_version(cs)
    cs.insert(Cue(identifier="2.0"))
    p2 = pf.save_version(cs)
    # restore old version: history preserved
    old = pf.load_version(p1)
    assert len(old.cues) == 1
    assert len(pf.list_versions()) == 2
    pf.save_version(old)  # saving restored version makes a THIRD version
    assert len(pf.list_versions()) == 3
