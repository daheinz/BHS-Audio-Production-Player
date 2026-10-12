"""Validation engine tests (Section 19 checks)."""

from pathlib import Path

import numpy as np
import soundfile as sf

from bhs_player.cues.model import ActionType, AdvanceMode, Cue, CueSet
from bhs_player.validate.check import Severity, validate_show


def write_wav(path: Path, seconds=0.5, sr=44100):
    n = int(seconds * sr)
    data = np.zeros((n, 2), dtype=np.float32)
    sf.write(str(path), data, sr)


def good_show(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir(parents=True)
    write_wav(audio / "a.wav")
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.0", action=ActionType.PLAY,
                  audio_file="audio/a.wav"))
    return cs


def test_clean_show_is_ready(tmp_path):
    cs = good_show(tmp_path)
    report = validate_show(cs, play_folder=tmp_path)
    assert report.show_ready
    assert report.verified_audio_files == 1


def test_missing_audio_is_critical(tmp_path):
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.0", action=ActionType.PLAY,
                  audio_file="audio/nope.wav"))
    report = validate_show(cs, play_folder=tmp_path)
    assert not report.show_ready
    assert any("does not exist" in i.message for i in report.critical)


def test_unassigned_play_cue_is_critical(tmp_path):
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.0", action=ActionType.PLAY))
    report = validate_show(cs, play_folder=tmp_path)
    assert any("no assigned audio" in i.message for i in report.critical)


def test_duplicate_identifiers_critical(tmp_path):
    cs = good_show(tmp_path)
    cs.insert(Cue(identifier="12.0", action=ActionType.PLAY,
                  audio_file="audio/a.wav"))
    report = validate_show(cs, play_folder=tmp_path)
    assert any("Duplicate" in i.message for i in report.critical)


def test_bad_identifier_format_critical(tmp_path):
    cs = good_show(tmp_path)
    cs.insert(Cue(identifier="abc", action=ActionType.PLAY,
                  audio_file="audio/a.wav"))
    report = validate_show(cs, play_folder=tmp_path)
    assert any("script-page" in i.message for i in report.critical)


def test_loop_on_complete_blocks_show(tmp_path):
    cs = good_show(tmp_path)
    cs.insert(Cue(identifier="20.0", action=ActionType.PLAY,
                  audio_file="audio/a.wav", loop=True,
                  advance_mode=AdvanceMode.ON_COMPLETE))
    report = validate_show(cs, play_folder=tmp_path)
    assert not report.show_ready
    assert any("never naturally completes" in i.message for i in report.critical)


def test_loop_on_go_is_fine(tmp_path):
    cs = good_show(tmp_path)
    cs.insert(Cue(identifier="20.0", action=ActionType.PLAY,
                  audio_file="audio/a.wav", loop=True,
                  advance_mode=AdvanceMode.ON_GO))
    report = validate_show(cs, play_folder=tmp_path)
    assert report.show_ready


def test_stop_fade_invalid_target(tmp_path):
    cs = good_show(tmp_path)
    cs.insert(Cue(identifier="30.0", action=ActionType.STOP,
                  target_internal_id="missing"))
    report = validate_show(cs, play_folder=tmp_path)
    assert any("no valid target" in i.message for i in report.critical)


def test_stop_fade_valid_target_ok(tmp_path):
    cs = good_show(tmp_path)
    target = cs.cues[0]
    cs.insert(Cue(identifier="30.0", action=ActionType.FADE,
                  target_internal_id=target.internal_id, fade_duration=2.0))
    report = validate_show(cs, play_folder=tmp_path)
    assert report.show_ready


def test_unavailable_output_is_critical(tmp_path):
    cs = good_show(tmp_path)
    report = validate_show(cs, play_folder=tmp_path, output_device_available=False)
    assert not report.show_ready
    assert any("output device" in i.message for i in report.critical)


def test_unreadable_audio_critical(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir(parents=True)
    (audio / "bad.wav").write_bytes(b"not real audio")
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.0", action=ActionType.PLAY,
                  audio_file="audio/bad.wav"))
    report = validate_show(cs, play_folder=tmp_path)
    assert any("cannot be" in i.message and "opened/decoded" in i.message
               for i in report.critical)
