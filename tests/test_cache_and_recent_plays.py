"""Persist validation/preparation work and record actual successful play opens."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import threading
import numpy as np
import soundfile as sf
import pytest
from PySide6.QtWidgets import QMessageBox
from bhs_player.audio import cache, safe_decode
from bhs_player.audio.engine import AudioEngine, Mixer, _Prepared
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue, CueSet
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.open_play_dialog import OpenPlayDialog


def sound(tmp_path):
    path=tmp_path/"tone.wav"
    sf.write(str(path),np.full((8000,2),.1,dtype=np.float32),8000,subtype="FLOAT")
    return path


def test_validation_survives_memory_cache_loss_and_changed_file_rechecks(tmp_path,monkeypatch):
    path=sound(tmp_path)
    expected=safe_decode.inspect_audio(path,full=True)
    safe_decode._CACHE.clear()
    def forbidden(*args,**kwargs):raise AssertionError("new decoder check")
    monkeypatch.setattr(safe_decode,"_run",forbidden)
    assert safe_decode.inspect_audio(path,full=True)==expected
    assert safe_decode.inspect_audio(path)==expected
    sf.write(str(path),np.zeros((16000,2),dtype=np.float32),8000)
    with pytest.raises(AssertionError,match="new decoder"):
        safe_decode.inspect_audio(path)


def test_pcm_disk_cache_reuses_decode_after_ram_eviction_and_rejects_changes(tmp_path,monkeypatch):
    path=sound(tmp_path);cue=Cue("1.0",audio_file=str(path))
    original,rate=safe_decode.decode_audio(path,cue,44100)
    def forbidden(*args,**kwargs):raise AssertionError("decode repeated")
    monkeypatch.setattr(safe_decode,"_run",forbidden)
    audio=AudioEngine(Mixer(),nonblocking=False)
    cached,sr=audio.decode_cue(cue)
    np.testing.assert_array_equal(cached,original)
    assert sr==rate
    sf.write(str(path),np.zeros((16000,2),dtype=np.float32),8000)
    with pytest.raises(AssertionError,match="decode repeated"):
        safe_decode.decode_audio(path,cue,44100)


def test_corrupt_pcm_cache_falls_back_to_guarded_decode(tmp_path,monkeypatch):
    path=sound(tmp_path);cue=Cue("1.0")
    safe_decode.decode_audio(path,cue,44100)
    for p in cache.ROOT.glob("*.npy"):p.write_bytes(b"corrupt cache")
    calls=[];run=safe_decode._run
    def counted(*args,**kwargs):calls.append(True);return run(*args,**kwargs)
    monkeypatch.setattr(safe_decode,"_run",counted)
    pcm,sr=safe_decode.decode_audio(path,cue,44100)
    assert pcm.shape==(44100,2) and len(calls)==1


def test_disk_cache_budget_evicts_old_data(tmp_path,monkeypatch):
    monkeypatch.setattr(cache,"PCM_BUDGET",1200)
    pcm=np.zeros((50,2),dtype=np.float32)
    for i in range(3):
        cache.store_pcm(i,pcm)
        p=cache._path("pcm",i,".npy")
        os.utime(p,(100+i,100+i))
    assert cache.load_pcm(0,1000) is None
    assert cache.load_pcm(2,1000) is not None
    assert sum(p.stat().st_size for p in cache.ROOT.glob("*.npy"))<=1200


def test_manual_full_recheck_bypasses_both_validation_caches(tmp_path,monkeypatch):
    path=sound(tmp_path)
    safe_decode.inspect_audio(path,full=True)
    calls=[];run=safe_decode._run
    def counted(*args,**kwargs):calls.append(True);return run(*args,**kwargs)
    monkeypatch.setattr(safe_decode,"_run",counted)
    safe_decode.inspect_audio(path,full=True,force=True)
    assert len(calls)==1


def test_file_identity_is_not_repeated_each_ui_refresh(tmp_path,monkeypatch):
    path=sound(tmp_path);cue=Cue("1.0",audio_file=str(path))
    audio=AudioEngine(Mixer(),nonblocking=True)
    calls=[];original=safe_decode.fingerprint
    def counted(path):calls.append(True);return original(path)
    monkeypatch.setattr(safe_decode,"fingerprint",counted)
    key=audio._prep_key(cue,refresh=True)
    audio._prepared[key]=_Prepared(np.zeros((100,2),dtype=np.float32),44100,key)
    engine=CueEngine(CueSet("Polling",[cue]),audio)
    for _ in range(20):assert engine.go_available()[0]
    assert len(calls)==1
    now=__import__('time').monotonic()
    monkeypatch.setattr("bhs_player.audio.engine.time.monotonic",lambda:now+2)
    assert engine.go_available()[0]
    assert len(calls)==2


def test_successful_opens_sort_recent_first_independently_of_saves(tmp_path,qtbot,monkeypatch):
    folders={name:PlayFolder(tmp_path,name) for name in ("Alpha","Beta","Gamma")}
    for name,folder in folders.items():folder.save_version(CueSet(name))
    dialog=OpenPlayDialog(tmp_path);qtbot.addWidget(dialog)
    assert [p.name for p in dialog._plays]==["Alpha","Beta","Gamma"]
    monkeypatch.setattr("bhs_player.ui.open_play_dialog.time.time",lambda:100)
    assert dialog.open_named("Beta")
    second=OpenPlayDialog(tmp_path);qtbot.addWidget(second)
    assert second._plays[0].name=="Beta"
    monkeypatch.setattr("bhs_player.ui.open_play_dialog.time.time",lambda:200)
    assert second.open_named("Alpha")
    folders['Gamma'].save_version(CueSet("Gamma"))
    third=OpenPlayDialog(tmp_path);qtbot.addWidget(third)
    assert [p.name for p in third._plays]==["Alpha","Beta","Gamma"]


def test_failed_and_canceled_opens_do_not_set_recency(tmp_path,qtbot,monkeypatch):
    folder=PlayFolder(tmp_path,"Failed");path=folder.save_version(CueSet("Failed"))
    path.write_text("invalid json")
    monkeypatch.setattr(QMessageBox,"critical",lambda *args:None)
    dialog=OpenPlayDialog(tmp_path);qtbot.addWidget(dialog)
    assert not dialog.open_named("Failed")
    assert dialog._last_opened(folder)==0
    folder.save_version(CueSet("Failed"));folder.save_recovery(CueSet("Failed"))
    monkeypatch.setattr(QMessageBox,"question",lambda *args:QMessageBox.Cancel)
    second=OpenPlayDialog(tmp_path);qtbot.addWidget(second)
    assert not second.open_named("Failed")
    assert second._last_opened(folder)==0


def test_upcoming_cue_preloads_without_preparing_entire_show(qtbot,monkeypatch):
    from bhs_player.ui.main_window import MainWindow
    cues=[Cue(str(i)+".0",audio_file=f"audio/{i}.wav") for i in range(1,4)]
    audio=AudioEngine(Mixer(),nonblocking=True)
    calls=[]
    monkeypatch.setattr(audio,"prepare_async",lambda cue,refresh=False:calls.append(cue.internal_id))
    monkeypatch.setattr(audio,"preparation_status",lambda cue:("ready",""))
    win=MainWindow(CueSet("Ahead",cues),CueEngine(CueSet("Ahead",cues),audio),audio,confirm_close=False)
    qtbot.addWidget(win)
    assert cues[0].internal_id in calls and cues[1].internal_id in calls
    assert cues[2].internal_id not in calls


def test_recheck_audio_control_forces_scan_and_reports_results(tmp_path,qtbot,monkeypatch):
    from bhs_player.ui.edit_window import EditWindow
    path=sound(tmp_path)
    bad=tmp_path/"missing.wav"
    audio=AudioEngine(Mixer(),nonblocking=True)
    win=EditWindow(CueSet("Recheck",[Cue("1.0",audio_file=str(path)),Cue("2.0",audio_file=str(bad))]),audio)
    qtbot.addWidget(win)
    calls=[]
    def inspect(path,full=False,force=False):
        calls.append((full,force))
        if path==bad:raise RuntimeError("missing")
        return {"duration":1}
    monkeypatch.setattr(safe_decode,"inspect_audio",inspect)
    win._recheck_audio()
    qtbot.waitUntil(lambda: win._recheck_job is None)
    assert calls==[(True,True),(True,True)]
    assert "1/2 files passed" in win.status_lbl.text()



def test_cache_write_failure_does_not_block_valid_playback(tmp_path,monkeypatch):
    path=sound(tmp_path)
    blocked=tmp_path/"not-a-folder";blocked.write_text("occupied")
    monkeypatch.setattr(cache,"ROOT",blocked)
    info=safe_decode.inspect_audio(path,full=True)
    assert info["duration"]==1
    pcm,sr=safe_decode.decode_audio(path,Cue("1.0"),44100)
    assert pcm.shape==(44100,2) and sr==44100



def test_import_validation_leaves_copied_asset_ready_without_another_decode(tmp_path,monkeypatch):
    path=sound(tmp_path)
    folder=PlayFolder(tmp_path/"plays","Warm import")
    relative=folder.import_audio(path)
    safe_decode._CACHE.clear()  # Simulate a later application launch.
    def forbidden(*args,**kwargs):raise AssertionError("Repeated native decode after import")
    monkeypatch.setattr(safe_decode,"_run",forbidden)
    cue=Cue("1.0",end_position=1.0)
    pcm,sr=safe_decode.decode_audio(folder.folder/relative,cue,44100)
    assert pcm.shape==(44100,2) and sr==44100


def test_identical_audio_different_names_share_pcm_but_different_content_does_not(tmp_path,monkeypatch):
    import shutil
    first=sound(tmp_path)
    second=tmp_path/"same-audio-another-name.wav";shutil.copy2(first,second)
    expected,sr=safe_decode.decode_audio(first,Cue("1.0"),44100)
    safe_decode.inspect_audio(second)
    def forbidden(*args,**kwargs):raise AssertionError("Native decode needed")
    monkeypatch.setattr(safe_decode,"_run",forbidden)
    cached,sr=safe_decode.decode_audio(second,Cue("2.0"),44100)
    np.testing.assert_array_equal(cached,expected)
    sf.write(str(second),np.full((8000,2),.2,dtype=np.float32),8000,subtype="FLOAT")
    with pytest.raises(AssertionError,match="Native decode needed"):
        safe_decode.decode_audio(second,Cue("2.0"),44100)
