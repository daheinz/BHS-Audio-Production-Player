"""Open Play + Pre-Show Status tests (Sections 16, 17, 19, 20)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.audio.stream import StreamingAudioBackend
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import ActionType, AdvanceMode, Cue, CueSet
from bhs_player.storage.plays import build_pre_show_status, create_play, scan_plays
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.pre_show_dialog import PreShowDialog
from bhs_player.validate.check import validate_show

SR = 44100


def write_wav(path: Path, seconds=0.5):
    n = int(seconds * SR)
    sf.write(str(path), np.zeros((n, 2), dtype=np.float32), SR)


# ---- play library scanning ----------------------------------------------

def test_scan_plays_lists_productions(tmp_path):
    create_play(tmp_path, "Clue")
    create_play(tmp_path, "Hamlet")
    plays = scan_plays(tmp_path)
    names = [p.name for p in plays]
    assert names == ["Clue", "Hamlet"]
    assert all(p.version_count >= 1 for p in plays)


def test_scan_empty_root(tmp_path):
    assert scan_plays(tmp_path) == []


def test_create_play_makes_folder_and_initial_version(tmp_path):
    pf = create_play(tmp_path, "Clue")
    assert pf.folder.exists()
    assert pf.audio_dir.exists()
    assert len(pf.list_versions()) == 1
    loaded = pf.load_latest()
    assert loaded.play_name == "Clue"
    assert loaded.cues == []


def test_play_info_reports_audio_count(tmp_path):
    pf = create_play(tmp_path, "Clue")
    (pf.audio_dir / "a.wav").write_bytes(b"x")
    (pf.audio_dir / "b.wav").write_bytes(b"y")
    plays = scan_plays(tmp_path)
    assert plays[0].audio_file_count == 2


# ---- pre-show status model ------------------------------------------------

def make_status(tmp_path, device_ok=True, engine_ok=True, bad_cue=False):
    audio = tmp_path / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    write_wav(audio / "a.wav")
    cs = CueSet(play_name="Clue")
    cue = Cue(identifier="12.0", action=ActionType.PLAY, audio_file="audio/a.wav")
    if bad_cue:
        cue.loop = True
        cue.advance_mode = AdvanceMode.ON_COMPLETE  # invalid combo
    cs.insert(cue)
    report = validate_show(cs, play_folder=tmp_path,
                           output_device_available=device_ok)
    return build_pre_show_status(
        cs, "Clue - v1", report,
        device_name="USB Interface" if device_ok else "(none)",
        device_connected=device_ok,
        engine_ready=engine_ok,
        recovery_state="clean",
    )


def test_show_ready_when_all_good(tmp_path):
    status = make_status(tmp_path)
    assert status.show_ready
    assert status.cue_count == 1
    assert status.verified_audio == 1


def test_not_ready_on_critical_validation(tmp_path):
    status = make_status(tmp_path, bad_cue=True)
    assert not status.show_ready


def test_not_ready_when_device_missing(tmp_path):
    status = make_status(tmp_path, device_ok=False, engine_ok=False)
    assert not status.show_ready


# ---- pre-show dialog ------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_preshow_dialog_blocks_enter_on_critical(qapp, tmp_path):
    status = make_status(tmp_path, bad_cue=True)
    dlg = PreShowDialog(status)
    assert not dlg.enter_btn.isEnabled()


def test_preshow_dialog_allows_enter_when_ready(qapp, tmp_path):
    status = make_status(tmp_path)
    dlg = PreShowDialog(status)
    assert dlg.enter_btn.isEnabled()


def test_preshow_dialog_lists_issues(qapp, tmp_path):
    status = make_status(tmp_path, bad_cue=True)
    dlg = PreShowDialog(status)
    texts = [dlg.issues.item(i).text() for i in range(dlg.issues.count())]
    assert any("never naturally completes" in t for t in texts)
