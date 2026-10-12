"""Regression tests for the Version 0.1 compliance review findings.

Each test names the finding and the spec section it verifies.
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication

from bhs_player.audio.engine import AudioEngine, Mixer, Voice
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueExecutionState,
    CueSet,
    OnGoBehavior,
)
from bhs_player.storage.store import PlayFolder
from bhs_player.validate.check import Severity, validate_show

SR = 44100


def tone(seconds, amp=0.5, freq=440.0):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def write_wav(path: Path, seconds=0.5, freq=440.0):
    sf.write(str(path), tone(seconds, freq=freq), SR)


def play(identifier, **kw):
    return Cue(identifier=identifier, action=ActionType.PLAY, **kw)


# Finding 1: play-relative audio resolution (§§5, 16) ------------------------

def test_show_playback_resolves_play_relative_reference(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    write_wav(pf.audio_dir / "boing2.wav", seconds=0.1)
    audio = AudioEngine(Mixer(SR), base_path=pf.folder)
    cue = play("12.0", audio_file="audio/boing2.wav")
    inst = audio.start(cue)  # must not raise, must find the play-folder file
    assert inst is not None
    assert audio.active_instances()


def test_show_go_with_play_relative_reference(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    write_wav(pf.audio_dir / "bell.wav", seconds=0.05)
    cs = CueSet(play_name="Clue", cues=[
        play("12.0", audio_file="audio/bell.wav")])
    audio = AudioEngine(Mixer(SR), base_path=pf.folder)
    eng = CueEngine(cs, audio)
    result = eng.go()
    assert result.ok, result.reason
    assert len(audio.active_instances()) == 1


# Finding 2: FADE cues finish advancing (§4) ----------------------------------

def test_fade_cue_advances_after_fade_completes(tmp_path):
    target = play("1.0", advance_mode=AdvanceMode.ON_GO)
    fade = Cue(identifier="2.0", action=ActionType.FADE,
               target_internal_id=target.internal_id, fade_duration=0.02)
    cs = CueSet(play_name="Clue", cues=[target, fade, play("3.0")])
    audio = AudioEngine(Mixer(SR))
    eng = CueEngine(cs, audio)
    eng.audio.start(target, pcm=tone(1.0))
    eng.pointer = 1
    eng.cue_set.cues[1].execution_state = CueExecutionState.ARMED
    eng.go()  # FADE starts
    assert eng.armed_cue is None
    # let the fade play out through the mixer
    for _ in range(int(0.1 * SR / 1024) + 1):
        audio.mixer.render_block(1024)
    assert fade.execution_state is CueExecutionState.COMPLETE
    assert eng.armed_cue is cs.cues[2]


# Finding 3: individual STOP releases On Complete wait (§§3, 8) ----------------

def test_individual_stop_releases_on_complete_wait(tmp_path):
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=1.0)
    cue = play("1.0", audio_file="audio/a.wav")  # On Complete
    cs = CueSet(play_name="Clue", cues=[cue, play("2.0", audio_file="audio/a.wav")])
    audio = AudioEngine(Mixer(SR), base_path=tmp_path)
    eng = CueEngine(cs, audio)
    result = eng.go()
    assert result.ok, result.reason
    inst = audio.active_instances()[0]
    audio.stop_instance(inst)  # individual STOP from the stack
    assert cue.execution_state is CueExecutionState.INTERRUPTED
    assert eng.armed_cue is None  # nothing armed; operator takes control
    eng.arm_cue(cs.cues[1].internal_id)
    assert eng.armed_cue is cs.cues[1]


# Finding 4: destructive GO verifies new sound first (§5) ----------------------

def test_failed_go_preserves_existing_audio(tmp_path):
    cs = CueSet(play_name="Clue", cues=[
        play("1.0", advance_mode=AdvanceMode.ON_GO, audio_file="audio/a.wav"),
        play("2.0", audio_file="audio/missing.wav",
             on_go_behavior=OnGoBehavior.STOP_ALL),
    ])
    audio = AudioEngine(Mixer(SR), base_path=tmp_path)
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=1.0)
    eng = CueEngine(cs, audio)
    eng.go()  # 1.0 playing
    assert len(audio.active_instances()) == 1
    result = eng.go()  # 2.0 file missing — must NOT silence 1.0
    assert not result.ok
    assert len(audio.active_instances()) == 1  # still playing


# Finding 5: validation rejects invalid segments (§§19-20) ---------------------

def test_validation_rejects_segment_beyond_file(tmp_path):
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=0.5)
    cs = CueSet(play_name="Clue", cues=[
        play("12.0", audio_file="audio/a.wav", start_position=30.0)])
    report = validate_show(cs, play_folder=tmp_path)
    assert not report.show_ready
    assert any("outside the file duration" in i.message for i in report.critical)


def test_validation_rejects_escaping_reference(tmp_path):
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=0.5)
    cs = CueSet(play_name="Clue", cues=[
        play("12.0", audio_file="../outside.wav")])
    report = validate_show(cs, play_folder=tmp_path)
    assert any("escapes the play folder" in i.message for i in report.critical)


def test_validation_rejects_duplicate_internal_ids(tmp_path):
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=0.5)
    a = play("12.0", audio_file="audio/a.wav")
    b = play("12.1", audio_file="audio/a.wav")
    b.internal_id = a.internal_id  # corrupt duplicate
    cs = CueSet(play_name="Clue", cues=[a, b])
    report = validate_show(cs, play_folder=tmp_path)
    assert any("Duplicate internal cue ID" in i.message for i in report.critical)


def test_validation_warns_compressed_loop(tmp_path):
    (tmp_path / "audio").mkdir()
    # fake mp3 file: write wav bytes with mp3 extension is decodable? No -
    # write real wav bytes but name .mp3; libsndfile sniffs by content.
    write_wav(tmp_path / "audio" / "rain.mp3", seconds=0.2)
    cs = CueSet(play_name="Clue", cues=[
        play("12.0", audio_file="audio/rain.mp3", loop=True,
             advance_mode=AdvanceMode.ON_GO)])
    report = validate_show(cs, play_folder=tmp_path)
    assert any("compressed format" in i.message for i in report.warnings)


# Finding 6: armed cue is preloaded (§15) --------------------------------------

def test_armed_cue_preloaded_on_init(tmp_path):
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=0.2)
    cs = CueSet(play_name="Clue", cues=[play("1.0", audio_file="audio/a.wav")])
    audio = AudioEngine(Mixer(SR), base_path=tmp_path)
    CueEngine(cs, audio)  # constructor preloads armed cue
    for _ in range(50):
        with audio._prep_lock:
            if audio._prepared:
                return
        time.sleep(0.01)
    with audio._prep_lock:
        assert audio._prepared  # preload completed


# Finding 9: per-instance meters receive signal (§§8-9) ------------------------

def test_voice_taps_post_fade_peaks():
    v = Voice(play("1.0", volume=0.5), tone(0.5, amp=0.8), SR)
    block = v.render(1024)
    assert v.last_peak_l > 0.2
    assert v.last_peak_l == pytest.approx(0.8 * 0.5, abs=0.05)
    # silence after stop
    v.stop()
    v.render(1024)
    assert v.last_peak_l == 0.0


# Finding 11: fade-out gain not doubled; zero fade = immediate (§5) ------------

def test_fade_starts_from_current_level_not_half():
    v = Voice(play("1.0", volume=0.5), tone(1.0, amp=0.8), SR)
    v.render(1024)  # settle at full cue volume
    v.start_fade_out(1.0)  # 1 second fade
    block = v.render(128)
    peak = float(np.max(np.abs(block)))
    # should start near 0.4 (0.8 * 0.5), NOT 0.2 (volume applied twice)
    assert peak == pytest.approx(0.4, abs=0.03)


def test_zero_fade_duration_stops_immediately():
    audio = AudioEngine(Mixer(SR))
    inst = audio.start(play("1.0"), pcm=tone(1.0))
    audio.fade_instance(inst, 0.0)
    assert audio.active_instances() == []
    assert inst.stopped


# Finding 12: import dedup uses content, not size (§16) -------------------------

def test_import_same_size_different_content_not_deduped(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    existing = pf.audio_dir / "fx.wav"
    existing.write_bytes(b"AAAA" * 100)
    src = tmp_path / "fx.wav"
    src.write_bytes(b"BBBB" * 100)  # same size, different content
    rel = pf.import_audio(src)
    assert rel != Path("audio") / "fx.wav"
    assert existing.read_bytes() == b"AAAA" * 100


def test_import_identical_content_deduped(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    src = tmp_path / "fx.wav"
    src.write_bytes(b"SAME" * 100)
    rel1 = pf.import_audio(src)
    rel2 = pf.import_audio(src)
    assert rel1 == rel2


# Finding 13: recovery failures visible (§18) ----------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_recovery_failure_is_shown(qapp, tmp_path, monkeypatch):
    from bhs_player.ui.edit_window import EditWindow
    cs = CueSet(play_name="Clue", cues=[Cue(identifier="1.0")])
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    audio = AudioEngine(Mixer(SR))
    win = EditWindow(cs, audio, pf)

    def boom(_cs):
        raise OSError("disk full")
    monkeypatch.setattr(pf, "save_recovery", boom)
    win._mark_edited()
    assert "Recovery autosave failed" in win.status_lbl.text()


# Master level persisted per play (§6A) ----------------------------------------

def test_master_level_round_trips_in_cue_set():
    from bhs_player.storage.store import deserialize_cue_set, serialize_cue_set
    cs = CueSet(play_name="Clue", master_level=0.65)
    cs.insert(Cue(identifier="1.0"))
    loaded = deserialize_cue_set(serialize_cue_set(cs))
    assert loaded.master_level == 0.65


# TEST isolation: audition end must not advance show (§13) ----------------------

def test_test_instance_end_does_not_advance_show(tmp_path):
    (tmp_path / "audio").mkdir()
    write_wav(tmp_path / "audio" / "a.wav", seconds=0.02)
    cs = CueSet(play_name="Clue", cues=[
        play("1.0", audio_file="audio/a.wav"), play("2.0", audio_file="audio/a.wav")])
    audio = AudioEngine(Mixer(SR), base_path=tmp_path)
    eng = CueEngine(cs, audio)
    # audition cue 2 via path (marked is_test)
    inst = audio.start_from_path(str(tmp_path / "audio" / "a.wav"), cs.cues[1])
    assert inst.is_test
    for _ in range(10):
        audio.mixer.render_block(1024)
    # show untouched: first cue still armed, second still idle
    assert eng.armed_cue is cs.cues[0]
    assert cs.cues[1].execution_state is CueExecutionState.IDLE


# Output loss clears voices and never resumes (§15) ------------------------------

def test_output_loss_clears_mixer_voices():
    from bhs_player.audio.stream import OutputStream
    mixer = Mixer(SR)
    mixer.add_voice(Voice(play("1.0"), tone(1.0), SR))
    stream = OutputStream(mixer)
    reasons = []
    stream.on_output_lost = reasons.append
    stream._signal_lost("device removed")
    assert mixer.voices == []
    assert reasons == ["device removed"]
    assert not stream.running
