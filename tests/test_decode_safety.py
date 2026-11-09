"""Killable decoder boundaries and transactional, asynchronous import/GO safety."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import subprocess
import json
import threading
import time
import numpy as np
import soundfile as sf
import pytest
from PySide6.QtCore import QTimer
from bhs_player.audio import safe_decode
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue, CueSet, AdvanceMode, OnGoBehavior
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.cue_table import CueTable


def wave(tmp_path):
    path = tmp_path/"source.wav"
    sf.write(str(path),np.ones((8000,2),dtype=np.float32)*.2,8000,subtype="FLOAT")
    return path


def fake_child(monkeypatch, tmp_path, script):
    child = tmp_path/"child.py"
    child.write_text(script,encoding="utf-8")
    original = subprocess.Popen
    processes = []
    def launch(args, **kwargs):
        # Other tests can still have waveform/preload workers finishing. Inject
        # failures only for this test's source, never their unrelated requests.
        try:
            request = json.loads(Path(args[2]).read_text(encoding="utf-8"))
            targeted = Path(request["path"]).parent == tmp_path.resolve()
        except (IndexError, KeyError, ValueError, OSError):
            targeted = False
        if not targeted:
            return original(args, **kwargs)
        process = original([args[0],str(child),args[2]],**kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(safe_decode.subprocess,"Popen",launch)
    return processes


def test_real_isolated_decode_trim_resample_and_waveform(tmp_path,monkeypatch):
    path=wave(tmp_path)
    info=safe_decode.inspect_audio(path,full=True)
    assert info["duration"]==1
    cue=Cue("1.0",start_position=.25,end_position=.75)
    pcm,rate=safe_decode.decode_audio(path,cue,16000)
    assert rate==16000 and pcm.shape==(8000,2)
    np.testing.assert_allclose(pcm,.2,atol=1e-6)
    duration,(low,high)=safe_decode.waveform_audio(path,100)
    assert duration==1 and high.shape==(100,2)
    np.testing.assert_allclose(high,.2)
    short=tmp_path/"one-sample.wav"
    sf.write(str(short),np.array([.1],dtype=np.float32),192000,subtype="FLOAT")
    tiny,rate=safe_decode.decode_audio(short,Cue("1.1"),44100)
    assert tiny.shape==(1,1)
    with pytest.raises(ValueError,match="nonempty"):
        AudioEngine(Mixer()).start(Cue("1.2",loop=True),pcm=np.zeros((0,2),dtype=np.float32))
    def forbidden(*args,**kwargs):
        raise AssertionError("GUI assignment attempted a fresh native decode")
    monkeypatch.setattr(safe_decode,"_execute",forbidden)
    folder=PlayFolder(tmp_path/"plays","Validated")
    relative=folder.import_audio(path,prevalidated=True)
    assert safe_decode.inspect_audio(folder.folder/relative)["duration"]==1


def test_decoder_timeout_is_killed_and_quarantined(tmp_path,monkeypatch):
    path=wave(tmp_path)
    processes=fake_child(monkeypatch,tmp_path,"import time; time.sleep(30)")
    started=time.monotonic()
    with pytest.raises(RuntimeError,match="timed out"):
        safe_decode._run(path,"validate",timeout=.2)
    assert time.monotonic()-started<3
    assert processes[0].poll() is not None
    with pytest.raises(RuntimeError,match="Suspect audio blocked"):
        safe_decode.inspect_audio(path,full=True)
    assert len(processes)==1


def test_native_decoder_error_is_rejected_even_if_python_would_not_raise(tmp_path,monkeypatch):
    path=wave(tmp_path)
    processes=fake_child(monkeypatch,tmp_path,"import sys,time; sys.stderr.write('malformed MPEG frame\\n'); sys.stderr.flush(); time.sleep(30)")
    with pytest.raises(RuntimeError,match="Decoder reported errors"):
        safe_decode.inspect_audio(path,full=True)
    assert processes[0].poll() is not None


def test_native_crash_exit_is_caught_in_parent(tmp_path,monkeypatch):
    path=wave(tmp_path)
    fake_child(monkeypatch,tmp_path,"import os; os._exit(9)")
    with pytest.raises(RuntimeError,match="exited unexpectedly"):
        safe_decode.inspect_audio(path,full=True)


def test_decoded_data_limit_rejects_before_large_allocation(tmp_path,monkeypatch):
    path=wave(tmp_path)
    monkeypatch.setattr(safe_decode,"DECODE_LIMIT",128)
    with pytest.raises(RuntimeError,match="safety limit"):
        safe_decode.inspect_audio(path,full=True)


def test_corrupt_import_is_rejected_before_copy_and_reference_change(tmp_path,qapp):
    path=tmp_path/"broken.mp3";path.write_bytes(b"not audio")
    folder=PlayFolder(tmp_path/"plays","Safety")
    cue=Cue("1.0",audio_file="audio/original.wav",end_position=2)
    table=CueTable(CueSet("Safety",[cue]),editable=True,play_folder=folder,defer_audio=True)
    errors=[];table.editRejected.connect(errors.append)
    assert not table.commit(0,"audio_file",str(path))
    assert cue.audio_file=="audio/original.wav" and cue.end_position==2
    assert not (folder.audio_dir/path.name).exists()
    assert errors
    with pytest.raises(RuntimeError):
        folder.import_audio(path)
    table.close()


def test_async_import_keeps_ui_responsive_and_rejection_keeps_old_cue(tmp_path,qtbot,monkeypatch):
    path=wave(tmp_path)
    cue=Cue("1.0",audio_file="audio/original.wav")
    table=CueTable(CueSet("Safety",[cue]),editable=True,defer_audio=True)
    qtbot.addWidget(table)
    gate=threading.Event()
    def check(*args,**kwargs):
        gate.wait(2)
        raise RuntimeError("suspect decoder errors")
    monkeypatch.setattr(safe_decode,"inspect_audio",check)
    monkeypatch.setattr("bhs_player.ui.cue_table.QFileDialog.getOpenFileName",lambda *a:(str(path),""))
    errors=[];table.editRejected.connect(errors.append)
    started=time.monotonic();assert table.browse_audio(0)
    assert time.monotonic()-started<.2
    ticks=[];QTimer.singleShot(20,lambda:ticks.append(True))
    qtbot.waitUntil(lambda:bool(ticks))
    assert cue.audio_file=="audio/original.wav"
    gate.set();qtbot.waitUntil(lambda:bool(errors))
    assert cue.audio_file=="audio/original.wav"
    assert "suspect" in errors[0]


def test_preparing_and_failed_cue_never_blocks_ui_or_stops_other_audio(tmp_path,qtbot,monkeypatch):
    path=wave(tmp_path)
    cue=Cue("1.0",audio_file=str(path),on_go_behavior=OnGoBehavior.STOP_ALL)
    audio=AudioEngine(Mixer(),nonblocking=True)
    old=audio.start(Cue("0.0"),pcm=np.ones((44100,2),dtype=np.float32)*.1)
    gate=threading.Event();calls=[]
    def decode(*args):
        calls.append(True);gate.wait(2);raise RuntimeError("decoder rejected")
    monkeypatch.setattr("bhs_player.audio.engine.load_segment_mono_or_stereo",decode)
    engine=CueEngine(CueSet("Safety",[cue]),audio)
    started=time.monotonic()
    assert not engine.go().ok
    assert time.monotonic()-started<.2
    for _ in range(5):engine.go_available()
    assert len(calls)==1
    gate.set()
    qtbot.waitUntil(lambda:audio.preparation_status(cue)[0]=="failed")
    assert "Audio blocked" in engine.go_available()[1]
    assert old in audio.active_instances()
    assert not engine.go().ok
    assert len(calls)==1


def test_auto_go_waits_for_preparation_then_executes_once(tmp_path,qtbot,monkeypatch):
    path=wave(tmp_path)
    source=Cue("1.0",advance_mode=AdvanceMode.ON_COMPLETE_GO)
    target=Cue("2.0",audio_file=str(path),advance_mode=AdvanceMode.ON_GO)
    audio=AudioEngine(Mixer(),nonblocking=True)
    start=audio.start
    audio.start=lambda cue,pcm=None,sample_rate=44100:start(cue,pcm=pcm if pcm is not None else np.ones((100,2),dtype=np.float32)*.1,sample_rate=sample_rate)
    gate=threading.Event()
    def decode(*args):
        gate.wait(2);return np.ones((100,2),dtype=np.float32)*.1,44100
    monkeypatch.setattr("bhs_player.audio.engine.load_segment_mono_or_stereo",decode)
    engine=CueEngine(CueSet("Safety",[source,target]),audio)
    assert engine.go().ok
    audio.mixer.render_block(101)
    assert engine.armed_cue is target
    assert engine.process_pending_auto_go() is None
    gate.set();qtbot.waitUntil(lambda:audio.preparation_status(target)[0]=="ready")
    assert engine.process_pending_auto_go().ok
    assert engine.process_pending_auto_go() is None
    assert len(audio.active_instances())==1


def test_replacing_file_invalidates_failed_preparation(tmp_path,qtbot,monkeypatch):
    path=wave(tmp_path);cue=Cue("1.0",audio_file=str(path))
    audio=AudioEngine(Mixer(),nonblocking=True)
    def fail(*args):raise RuntimeError("old bad file")
    monkeypatch.setattr("bhs_player.audio.engine.load_segment_mono_or_stereo",fail)
    audio.prepare_async(cue)
    qtbot.waitUntil(lambda:audio.preparation_status(cue)[0]=="failed")
    sf.write(str(path),np.zeros((1000,2)),8000)
    monkeypatch.setattr("bhs_player.audio.engine.load_segment_mono_or_stereo",lambda *args:(np.zeros((1000,2),dtype=np.float32),44100))
    audio.prepare_async(cue)
    qtbot.waitUntil(lambda:audio.preparation_status(cue)[0]=="ready")



def test_capacity_failure_is_detected_before_stop_previous(tmp_path,monkeypatch):
    path=wave(tmp_path)
    monkeypatch.setattr(safe_decode,"DECODE_LIMIT",2000)
    audio=AudioEngine(Mixer())
    first=audio.start(Cue("0.0"),pcm=np.ones((200,2),dtype=np.float32)*.1)
    second=audio.start(Cue("0.1"),pcm=np.ones((200,2),dtype=np.float32)*.1)
    cue=Cue("1.0",audio_file=str(path),on_go_behavior=OnGoBehavior.STOP_PREVIOUS)
    monkeypatch.setattr(audio,"prepare_async",lambda cue:None)
    monkeypatch.setattr(audio,"decode_cue",lambda cue:(np.ones((400,2),dtype=np.float32),44100))
    engine=CueEngine(CueSet("Capacity",[cue]),audio)
    result=engine.go()
    assert not result.ok and "safety budget" in result.reason
    assert audio.active_instances()==[first,second]


def test_prepared_cache_evicts_old_data_within_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(safe_decode,"DECODE_LIMIT",2048)
    monkeypatch.setattr("bhs_player.audio.engine.load_segment_mono_or_stereo",lambda *args:(np.zeros((180,2),dtype=np.float32),44100))
    audio=AudioEngine(Mixer())
    for i in range(3):
        path=tmp_path/f"{i}.wav";sf.write(str(path),[0.0]*100,44100)
        cue=Cue(str(i)+".0",audio_file=str(path))
        audio._prepare_sync(cue,audio._prep_key(cue))
    assert len(audio._prepared)==2
    assert sum(p.pcm.nbytes for p in audio._prepared.values())<=4096


def test_import_source_change_does_not_leave_a_partial_asset(tmp_path,monkeypatch):
    path=wave(tmp_path)
    def check(*args,**kwargs):
        sf.write(str(path),np.zeros((100,2)),8000)
        return {"duration":.0125}
    monkeypatch.setattr(safe_decode,"inspect_audio",check)
    folder=PlayFolder(tmp_path/"plays","Atomic")
    with pytest.raises(ValueError,match="changed during import"):
        folder.import_audio(path)
    assert not list(folder.audio_dir.iterdir())


def test_stop_test_cancels_pending_audition(tmp_path,qtbot,monkeypatch):
    from types import SimpleNamespace
    from bhs_player.ui.edit_window import EditWindow
    path=wave(tmp_path)
    cue=Cue("1.0",audio_file=str(path))
    audio=AudioEngine(Mixer(),nonblocking=True)
    win=EditWindow(CueSet("Audition",[cue]),audio)
    qtbot.addWidget(win)
    win.routing=SimpleNamespace(prepare=lambda route:True,message="",audio=audio,backend=SimpleNamespace(stop=lambda:None))
    calls=[]
    def prepare(*args):
        calls.append(True)
        raise RuntimeError("Preparing audio - GO will be available when ready.")
    monkeypatch.setattr(audio,"start_from_path",prepare)
    win._audition(cue.internal_id)
    assert "Preparing TEST" in win.test_lbl.text()
    win._stop_audition()
    qtbot.wait(100)
    assert len(calls)==1 and not audio.active_instances()
    win.routing=None


def test_advanced_import_rejection_preserves_existing_file(tmp_path,qtbot,monkeypatch):
    from bhs_player.ui.cue_editor_dialog import CueEditorDialog
    path=tmp_path/"bad.wav";path.write_bytes(b"broken")
    cue=Cue("1.0",audio_file="audio/original.wav")
    folder=PlayFolder(tmp_path/"plays","Advanced")
    dlg=CueEditorDialog(cue,CueSet("Advanced",[cue]),play_folder=folder)
    qtbot.addWidget(dlg)
    monkeypatch.setattr("bhs_player.ui.cue_editor_dialog.QFileDialog.getOpenFileName",lambda *a:(str(path),""))
    dlg._browse_audio()
    qtbot.waitUntil(lambda: "rejected" in dlg.error_lbl.text(),timeout=10000)
    assert dlg.file_row.text()=="audio/original.wav"
    assert cue.audio_file=="audio/original.wav"
    assert not (folder.audio_dir/path.name).exists()


def test_mode_entry_audio_checks_do_not_block_gui(tmp_path,qtbot,monkeypatch):
    from bhs_player.app import ProductionController
    from bhs_player.validate.check import ValidationReport
    path=wave(tmp_path)
    controller=ProductionController(CueSet("Entry",[Cue("1.0",audio_file=str(path))]))
    qtbot.addWidget(controller.edit)
    monkeypatch.setattr(controller.routing,"prepare",lambda route:controller.audio.set_ready(True) or True)
    gate=threading.Event()
    def check(*args,**kwargs):
        gate.wait(2);return ValidationReport()
    monkeypatch.setattr("bhs_player.app.validate_show",check)
    started=time.monotonic();controller.enter_show(rehearsal=True)
    assert time.monotonic()-started<.2 and controller.show_window is None
    ticks=[];QTimer.singleShot(20,lambda:ticks.append(True))
    qtbot.waitUntil(lambda:bool(ticks))
    gate.set();qtbot.waitUntil(lambda:controller.show_window is not None,timeout=5000)
    qtbot.addWidget(controller.show_window)
    controller.show_window.close()



def test_pending_import_blocks_mode_entry_and_save_without_changing_cue(tmp_path,qtbot):
    from bhs_player.app import ProductionController
    cue=Cue("1.0")
    controller=ProductionController(CueSet("Pending",[cue]))
    qtbot.addWidget(controller.edit)
    controller.edit.list._audio_imports[cue.internal_id]=("pending",None)
    controller.enter_show()
    assert controller.show_window is None
    assert "Wait for the audio import" in controller.edit.status_lbl.text()
    assert not controller.edit._save()
    controller.edit.list.cancel_imports()


def test_cancelling_advanced_import_prevents_late_asset_copy(tmp_path,qtbot,monkeypatch):
    from bhs_player.ui.cue_editor_dialog import CueEditorDialog
    path=wave(tmp_path)
    cue=Cue("1.0")
    folder=PlayFolder(tmp_path/"plays","Cancel")
    dlg=CueEditorDialog(cue,CueSet("Cancel",[cue]),play_folder=folder)
    qtbot.addWidget(dlg)
    gate=threading.Event()
    def check(*args,**kwargs):
        gate.wait(2);return {"duration":1}
    monkeypatch.setattr(safe_decode,"inspect_audio",check)
    monkeypatch.setattr("bhs_player.ui.cue_editor_dialog.QFileDialog.getOpenFileName",lambda *a:(str(path),""))
    dlg._browse_audio()
    dlg.reject()
    gate.set();qtbot.waitUntil(lambda:dlg._import_job is None)
    assert cue.audio_file is None
    assert not folder.audio_dir.exists()



def test_live_completion_never_fingerprints_audio_on_callback_thread(tmp_path,monkeypatch):
    path=wave(tmp_path)
    source=Cue("1.0")
    next_cue=Cue("2.0",audio_file=str(path))
    audio=AudioEngine(Mixer(),nonblocking=True)
    start=audio.start
    audio.start=lambda cue:start(cue,pcm=np.ones((100,2),dtype=np.float32)*.1)
    engine=CueEngine(CueSet("Callback",[source,next_cue]),audio)
    assert engine.go().ok
    def forbidden(*args):
        raise AssertionError("Filesystem preparation ran on the audio callback")
    monkeypatch.setattr(safe_decode,"fingerprint",forbidden)
    errors=[]
    def render():
        try:audio.mixer.render_block(101)
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=render,name="audio-callback")
    thread.start();thread.join()
    assert not errors
    assert engine.armed_cue is next_cue
    assert not audio._prepare_jobs



def test_decoder_overrides_large_parent_thread_pools_and_decodes_normal_clip(tmp_path,monkeypatch):
    # A 64-thread NumPy pool can commit ~500 MiB before decoding, falsely
    # exhausting a 512 MiB worker job even for ordinary stereo cues.
    monkeypatch.setenv("OPENBLAS_NUM_THREADS","64")
    monkeypatch.setenv("OMP_NUM_THREADS","64")
    path=tmp_path/"normal-stereo.wav"
    sf.write(str(path),np.full((44100*30,2),.1,dtype=np.float32),44100,subtype="FLOAT")
    original=subprocess.Popen
    seen=[]
    def launch(args,**kwargs):
        seen.append(kwargs["env"])
        return original(args,**kwargs)
    monkeypatch.setattr(safe_decode.subprocess,"Popen",launch)
    pcm,sr=safe_decode.decode_audio(path,Cue("7.0"),44100)
    assert pcm.shape==(44100*30,2) and sr==44100
    np.testing.assert_allclose(pcm,.1)
    assert seen and all(environment["OPENBLAS_NUM_THREADS"]=="1" and environment["OMP_NUM_THREADS"]=="1" for environment in seen)
    assert os.environ["OPENBLAS_NUM_THREADS"]=="64"  # Parent environment is untouched.
