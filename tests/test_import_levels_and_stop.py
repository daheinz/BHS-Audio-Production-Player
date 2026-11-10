"""Silent import peak warnings, Edit telemetry and operator Stop completion."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import Qt
from bhs_player.audio import safe_decode
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue, CueSet, AdvanceMode, CueExecutionState
from bhs_player.ui.main_window import PlayingStackEntry
from bhs_player.ui.import_warnings import peak_warnings


def test_peak_scan_is_silent_persistent_and_distinguishes_level_risk(tmp_path,monkeypatch):
    path=tmp_path/"peaks.wav"
    sf.write(str(path),np.array([[1.1,-1.0],[.2,-.3]],dtype=np.float32),8000,subtype="FLOAT")
    result=safe_decode.inspect_audio(path,full=True,analyze_peaks=True)
    assert result["sample_peak"]==pytest.approx(1.1)
    assert result["full_scale_samples"]==2
    safe_decode._CACHE.clear()
    monkeypatch.setattr(safe_decode,"_run",lambda *a,**k:pytest.fail("Repeated scan"))
    assert safe_decode.inspect_audio(path,full=True,analyze_peaks=True)==result
    cue=Cue("1.0",volume=.5)
    cs=CueSet("Peaks",[cue])
    assert len(peak_warnings(result,cue,cs.profile))==1  # Source warning survives attenuation.
    cue.volume=2
    assert len(peak_warnings({"sample_peak":.8},cue,cs.profile))==1
    assert "little headroom" in peak_warnings({"sample_peak":.95},Cue("2.0"),cs.profile)[0]
    assert not peak_warnings({"sample_peak":.2},Cue("2.0"),cs.profile)


@pytest.mark.parametrize("mode",list(AdvanceMode))
def test_card_stop_runs_next_cue_action(mode,qtbot):
    cue=Cue("1.0",advance_mode=mode)
    target=Cue("2.0")
    cs=CueSet("Stop",[cue,target])
    audio=AudioEngine(Mixer(sample_rate=100))
    start=audio.start
    audio.start=lambda c:start(c,pcm=np.ones((1000,2),dtype=np.float32)*.1,sample_rate=100)
    engine=CueEngine(cs,audio)
    assert engine.go().ok
    instance=audio.active_instances()[0]
    card=PlayingStackEntry(instance,audio.voice_for(instance),audio)
    qtbot.addWidget(card)
    qtbot.mouseClick(card.stop_btn,Qt.LeftButton)
    assert cue.execution_state is CueExecutionState.COMPLETE
    assert engine.armed_cue is target
    assert not audio.active_instances()
    result=engine.process_pending_auto_go()
    assert (result is not None)==(mode is AdvanceMode.ON_COMPLETE_GO)
    if result:assert result.ok


def test_edit_health_follows_test_activity_and_preserves_output_loss(qtbot):
    from bhs_player.ui.edit_window import EditWindow
    from tests.test_audio_diagnostics import stream_with_tone
    audio,instance,stream,backend=stream_with_tone(1.2)
    routing=SimpleNamespace(backend=backend,preview=False,unsupported=lambda:"",audio=audio)
    win=EditWindow(CueSet("Test",[Cue("1.0")]),audio,routing=routing)
    qtbot.addWidget(win)
    out=np.zeros((1024,2),dtype=np.float32)
    stream._callback(out,1024,None,None)
    win._refresh_test()
    assert "CLIPPING" in win.audio_health.gauge.format()
    audio.stop_instance(instance)
    win._refresh_test()
    assert "Idle" in win.audio_health.gauge.format()
    backend.output_lost=True
    backend.output_lost_reason="Disconnected"
    win._refresh_test()
    assert "OUTPUT LOST" in win.audio_health.gauge.format()


def test_import_warns_visibly_without_rejecting_file(tmp_path,qtbot,monkeypatch):
    from bhs_player.ui.cue_table import CueTable
    path=tmp_path/"loud.wav"
    sf.write(str(path),np.full((100,2),1.0,dtype=np.float32),8000,subtype="FLOAT")
    cue=Cue("1.0")
    table=CueTable(CueSet("Import",[cue]),editable=True,defer_audio=True)
    qtbot.addWidget(table)
    monkeypatch.setattr("bhs_player.ui.cue_table.QFileDialog.getOpenFileName",lambda *a:(str(path),""))
    messages=[]
    table.audioImportStatus.connect(messages.append)
    assert table.browse_audio(0)
    qtbot.waitUntil(lambda:not table.has_pending_imports,timeout=5000)
    assert cue.audio_file
    assert "WARNING" in messages[-1]
    assert table._audio_warning_boxes
    for box in list(table._audio_warning_boxes):box.accept()


def test_advanced_import_uses_current_level_and_warns(tmp_path,qtbot,monkeypatch):
    from bhs_player.storage.store import PlayFolder
    from bhs_player.ui.cue_editor_dialog import CueEditorDialog
    path=tmp_path/"gain.wav"
    sf.write(str(path),np.full((100,2),.6,dtype=np.float32),8000,subtype="FLOAT")
    cue=Cue("1.0")
    cs=CueSet("Advanced",[cue])
    folder=PlayFolder(tmp_path/"plays","Advanced")
    dlg=CueEditorDialog(cue,cs,play_folder=folder)
    qtbot.addWidget(dlg)
    dlg.volume_spin.setValue(200)
    monkeypatch.setattr("bhs_player.ui.cue_editor_dialog.QFileDialog.getOpenFileName",lambda *a:(str(path),""))
    dlg._browse_audio()
    qtbot.waitUntil(lambda:dlg._import_job is None,timeout=5000)
    assert "level warning" in dlg.error_lbl.text()
    assert "could exceed full scale" in dlg._audio_warning_boxes[0].text()
    assert dlg.file_row.text()
    for box in list(dlg._audio_warning_boxes):box.accept()
    dlg.reject()
