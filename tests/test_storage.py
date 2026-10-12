"""Storage tests: versioned saves, recovery, audio import (Sections 16-18)."""

import time
from datetime import datetime
from pathlib import Path

from bhs_player.cues.model import ActionType, AdvanceMode, Cue, CueSet
from bhs_player.storage.store import (
    PlayFolder,
    deserialize_cue_set,
    serialize_cue_set,
)


def make_show():
    cs = CueSet(play_name="Clue")
    target = Cue(identifier="12.0", action=ActionType.PLAY,
                 audio_file="audio/doorbell.wav", volume=0.8)
    cs.insert(target)
    cs.insert(Cue(identifier="12.1", action=ActionType.PLAY,
                  audio_file="audio/thunder.wav", loop=True,
                  advance_mode=AdvanceMode.ON_GO))
    cs.insert(Cue(identifier="12.2", action=ActionType.FADE,
                  target_internal_id=target.internal_id, fade_duration=2.5))
    return cs


def test_roundtrip_preserves_everything(tmp_path):
    cs = make_show()
    text = serialize_cue_set(cs)
    loaded = deserialize_cue_set(text)
    assert loaded.play_name == "Clue"
    assert [c.identifier for c in loaded.cues] == ["12.0", "12.1", "12.2"]
    # internal IDs preserved so target references survive
    assert loaded.cues[2].target_internal_id == loaded.cues[0].internal_id
    assert loaded.cues[1].loop is True
    assert loaded.cues[1].advance_mode is AdvanceMode.ON_GO
    assert loaded.cues[0].volume == 0.8


def test_identifier_text_survives_save_load(tmp_path):
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.1"))
    cs.insert(Cue(identifier="12.10"))
    loaded = deserialize_cue_set(serialize_cue_set(cs))
    ids = [c.identifier for c in loaded.cues]
    assert ids == ["12.1", "12.10"]  # distinct, exact


def test_save_never_overwrites_creates_history(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    cs = make_show()
    p1 = pf.save_version(cs, when=datetime(2026, 10, 4, 19, 2, 11))
    cs.insert(Cue(identifier="13.0"))
    p2 = pf.save_version(cs, when=datetime(2026, 10, 5, 21, 17, 44))
    assert p1 != p2
    assert p1.exists() and p2.exists()
    # first version unchanged
    v1 = pf.load_version(p1)
    assert len(v1.cues) == 3
    v2 = pf.load_version(p2)
    assert len(v2.cues) == 4


def test_same_second_saves_get_unique_names(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    cs = make_show()
    when = datetime(2026, 10, 6, 23, 48, 35)
    p1 = pf.save_version(cs, when=when)
    p2 = pf.save_version(cs, when=when)
    assert p1 != p2
    assert p1.exists() and p2.exists()


def test_open_play_gives_latest_and_history(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    pf.save_version(make_show(), when=datetime(2026, 10, 4, 19, 2, 11))
    time.sleep(0.02)
    newer = make_show()
    newer.insert(Cue(identifier="99.0"))
    pf.save_version(newer, when=datetime(2026, 10, 6, 23, 48, 35))
    versions = pf.list_versions()
    assert len(versions) == 2
    latest = pf.load_latest()
    assert len(latest.cues) == 4


def test_recovery_separate_from_history(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    cs = make_show()
    pf.save_version(cs)
    cs.insert(Cue(identifier="77.0"))  # unsaved edit
    pf.save_recovery(cs)
    assert len(pf.list_versions()) == 1  # recovery not in history
    assert pf.has_recovery()
    rec = pf.load_recovery()
    assert len(rec.cues) == 4  # has the unsaved edit
    assert pf.recovery_newer_than_saved()


def test_recovery_not_newer_after_save(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    cs = make_show()
    pf.save_recovery(cs)
    assert pf.recovery_newer_than_saved()  # nothing saved yet
    time.sleep(0.02)
    pf.save_version(cs)
    assert not pf.recovery_newer_than_saved()


def test_import_audio_copies_and_returns_relative_path(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    src = tmp_path / "downloads" / "thunder.wav"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake-audio-data")
    rel = pf.import_audio(src)
    assert rel == Path("audio") / "thunder.wav"
    assert (pf.audio_dir / "thunder.wav").read_bytes() == b"fake-audio-data"


def test_import_audio_collision_never_overwrites(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    src = tmp_path / "thunder.wav"
    src.write_bytes(b"version-one")
    pf.import_audio(src)
    src.write_bytes(b"version-two-different")
    rel2 = pf.import_audio(src)
    assert rel2 != Path("audio") / "thunder.wav"
    assert (pf.audio_dir / "thunder.wav").read_bytes() == b"version-one"


def test_import_audio_dedupes_identical_source(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    src = tmp_path / "rain.wav"
    src.write_bytes(b"same-bytes")
    rel1 = pf.import_audio(src)
    rel2 = pf.import_audio(src)
    assert rel1 == rel2  # no duplicate copy


def test_play_folder_layout(tmp_path):
    pf = PlayFolder(tmp_path, "Clue")
    pf.ensure()
    assert pf.folder.name == "Clue"
    assert pf.audio_dir.name == "audio"
    assert (pf.folder / ".recovery").exists()
