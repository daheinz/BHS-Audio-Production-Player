"""Audio engine tests (Sections 6, 6A, 9, 15). Offline-rendered, no hardware."""

import numpy as np

from bhs_player.audio.engine import AudioEngine, Mixer, Voice, _to_db
from bhs_player.cues.model import ActionType, Cue

SR = 44100


def tone(seconds, amp=0.5, channels=2, freq=440.0):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    if channels == 1:
        return mono.reshape(-1, 1)
    return np.stack([mono, mono], axis=1)


def silence(seconds, channels=2):
    return np.zeros((int(seconds * SR), channels), dtype=np.float32)


def play_cue(identifier="1.0", **kw):
    return Cue(identifier=identifier, action=ActionType.PLAY, **kw)


def render_seconds(mixer, seconds):
    blocks = int(seconds * SR / 1024) + 1
    out = []
    for _ in range(blocks):
        out.append(mixer.render_block(1024))
    return np.vstack(out)


def test_single_voice_full_level():
    mixer = Mixer(SR)
    cue = play_cue(volume=1.0)
    mixer.add_voice(Voice(cue, tone(0.5, amp=0.5), SR))
    out = render_seconds(mixer, 0.2)
    peak = float(np.max(np.abs(out)))
    assert 0.45 < peak <= 0.51


def test_cue_volume_scales_signal():
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play_cue(volume=0.5), tone(0.5, amp=0.5), SR))
    out = render_seconds(mixer, 0.2)
    peak = float(np.max(np.abs(out)))
    assert 0.22 < peak <= 0.26  # half of 0.5


def test_master_level_scales_final_mix():
    mixer = Mixer(SR)
    mixer.set_master_level(0.5)
    mixer.add_voice(Voice(play_cue(volume=1.0), tone(0.5, amp=0.5), SR))
    out = render_seconds(mixer, 0.2)
    peak = float(np.max(np.abs(out)))
    assert 0.22 < peak <= 0.26


def test_cue_and_master_levels_compound():
    # relative level within the mix, scaled by master (Section 6A)
    mixer = Mixer(SR)
    mixer.set_master_level(0.5)
    mixer.add_voice(Voice(play_cue(volume=0.5), tone(0.5, amp=0.8), SR))
    out = render_seconds(mixer, 0.2)
    peak = float(np.max(np.abs(out)))
    assert 0.17 < peak <= 0.21  # 0.8 * 0.5 * 0.5 = 0.2


def test_two_voices_mix():
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play_cue("1.0"), tone(0.5, amp=0.3), SR))
    mixer.add_voice(Voice(play_cue("2.0"), tone(0.5, amp=0.3), SR))
    out = render_seconds(mixer, 0.2)
    peak = float(np.max(np.abs(out)))
    assert peak > 0.45  # in-phase tones sum toward 0.6


def test_meter_follows_signal_post_master():
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play_cue(volume=1.0), tone(0.5, amp=0.5), SR))
    mixer.render_block(1024)
    loud = mixer.last_meter
    assert loud.left_db > -7.0 and loud.right_db > -7.0  # ~-6 dBFS
    mixer2 = Mixer(SR)
    mixer2.set_master_level(0.1)
    mixer2.add_voice(Voice(play_cue(volume=1.0), tone(0.5, amp=0.5), SR))
    mixer2.render_block(1024)
    quiet = mixer2.last_meter
    assert quiet.left_db < loud.left_db - 15  # 20 dB down


def test_meter_shows_silence_when_no_signal():
    mixer = Mixer(SR)
    mixer.render_block(1024)
    assert mixer.last_meter.left_db == -np.inf
    assert mixer.last_meter.right_db == -np.inf


def test_clipping_indicator_at_full_scale():
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play_cue(volume=2.0), tone(0.5, amp=0.9), SR))
    mixer.render_block(1024)
    assert mixer.last_meter.clipped


def test_fade_in_ramps_up():
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play_cue(volume=1.0, fade_in=0.1), tone(1.0, amp=0.5), SR))
    first = mixer.render_block(1024)
    later_blocks = render_seconds(mixer, 0.2)
    early_peak = float(np.max(np.abs(first)))
    later_peak = float(np.max(np.abs(later_blocks[-1024:])))
    # first block (1024 of 4410 fade samples) ramps gain 0 -> ~0.23,
    # so peak is ~0.11: clearly attenuated vs the 0.5 full-level target
    assert early_peak < 0.2
    assert later_peak > 0.4  # reaches full level after the fade


def test_fade_out_reaches_silence_and_stops():
    cue = play_cue(volume=1.0)
    voice = Voice(cue, tone(1.0, amp=0.5), SR)
    mixer = Mixer(SR)
    mixer.add_voice(voice)
    voice.start_fade_out(0.05)
    render_seconds(mixer, 0.2)
    assert voice.stopped
    mixer.render_block(1024)
    assert mixer.last_meter.left_db == -np.inf


def test_loop_repeats_segment():
    cue = play_cue(loop=True)
    voice = Voice(cue, tone(0.05, amp=0.5), SR)
    mixer = Mixer(SR)
    mixer.add_voice(voice)
    out = render_seconds(mixer, 0.2)  # 4x the segment length
    assert np.max(np.abs(out[6000:8000])) > 0.4  # still sounding later
    assert not voice.completed_naturally


def test_mono_source_plays_both_channels():
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play_cue(), tone(0.2, amp=0.5, channels=1), SR))
    mixer.render_block(1024)
    m = mixer.last_meter
    assert abs(m.left_db - m.right_db) < 0.5


def test_engine_stop_all_clears_instances():
    eng = AudioEngine(Mixer(SR))
    eng.start(play_cue("1.0"), pcm=tone(1.0))
    eng.start(play_cue("2.0"), pcm=tone(1.0))
    assert len(eng.active_instances()) == 2
    eng.stop_all()
    assert eng.active_instances() == []


def test_engine_fade_instance_applies_duration():
    eng = AudioEngine(Mixer(SR))
    inst = eng.start(play_cue("1.0"), pcm=tone(1.0))
    eng.fade_instance(inst, 0.1)
    assert inst.fading
    render_seconds(eng.mixer, 0.3)
    assert eng.active_instances() == []


def test_engine_natural_finish_callback():
    finished = []
    eng = AudioEngine(Mixer(SR))
    eng.on_instance_ended = lambda inst, natural: finished.append((inst, natural))
    eng.start(play_cue("1.0"), pcm=tone(0.05))
    render_seconds(eng.mixer, 0.2)
    assert len(finished) == 1
    assert finished[0][1] is True  # natural completion


def test_to_db_scale():
    assert _to_db(1.0) == 0.0
    assert abs(_to_db(0.5) - (-6.02)) < 0.05
    assert _to_db(0.0) == -np.inf


def test_start_requires_audio():
    eng = AudioEngine(Mixer(SR))
    try:
        eng.start(play_cue("1.0"))  # no file, no pcm
        assert False, "expected ValueError"
    except ValueError:
        pass
