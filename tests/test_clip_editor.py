import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import asdict
from pathlib import Path
import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, QPoint
from bhs_player.ui.clip_editor import read_waveform, WaveformLoader, ClipPlot, ClipEditor, WaveformData
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.edit_window import EditWindow
from bhs_player.ui.cue_table import FIELDS
from bhs_player.audio.engine import AudioEngine, Mixer, Voice
from bhs_player.cues.model import Cue, CueSet, ActionType
from bhs_player.storage.store import PlayFolder, serialize_cue_set, deserialize_cue_set


def wave_file(tmp_path, seconds=2, stereo=True):
    path = tmp_path / 'source.wav'
    time = np.arange(int(8000*seconds))/8000
    samples = .5*np.sin(2*np.pi*220*time)
    pcm = np.stack([samples, .6*samples],axis=1) if stereo else samples
    sf.write(str(path), pcm, 8000)
    return path


def test_waveform_reads_source_channels_and_bounded_peak_count(tmp_path):
    for stereo in (True, False):
        path = wave_file(tmp_path, seconds=5, stereo=stereo)
        original = path.read_bytes()
        data = read_waveform(path, buckets=100)
        assert data.duration == 5
        assert data.minimum.shape == (100, 2 if stereo else 1)
        assert data.maximum[:,0].max() > .49
        assert data.minimum[:,0].min() < -.49
        assert path.read_bytes() == original


def test_loader_ignores_old_selection_result(qapp):
    loader = WaveformLoader()
    data = WaveformData(1,np.zeros((3,1)),np.ones((3,1)))
    received = []
    loader.loaded.connect(lambda *args: received.append(args))
    loader.token = 2
    loader._receive(1, data, '')
    assert received == []
    loader._receive(2, data, '')
    assert received == [(data,'')]


def test_async_waveform_and_missing_file_do_not_modify_cue(qtbot, tmp_path):
    path = wave_file(tmp_path)
    cue = Cue('1.0', audio_file=str(path), start_position=.2, end_position=1.8)
    before = asdict(cue)
    editor = ClipEditor()
    qtbot.addWidget(editor)
    editor.set_cue(cue, CueSet('Test',[cue]))
    qtbot.waitUntil(lambda: editor.data is not None, timeout=5000)
    assert editor.data.duration == 2
    assert asdict(cue) == before
    missing = Cue('2.0', audio_file=str(tmp_path/'missing.wav'))
    editor.set_cue(missing, CueSet('Test',[missing]))
    assert editor.data is None
    assert 'unavailable' in editor.plot.message.lower()
    assert not editor.plot.isEnabled()


def drag(qtbot, plot, name, time):
    point = plot.handles()[name].toPoint()
    target = QPoint(round(plot.time_x(time)),point.y())
    qtbot.mousePress(plot, Qt.LeftButton, pos=point)
    qtbot.mouseMove(plot, target)
    qtbot.mouseRelease(plot, Qt.LeftButton, pos=target)


def test_drag_trim_and_fades_emit_only_at_release_and_stay_bounded(qtbot):
    plot = ClipPlot()
    qtbot.addWidget(plot)
    plot.resize(800,220)
    data = WaveformData(10,np.zeros((30,2)),np.ones((30,2))*.5)
    plot.configure(dict(start_position=1,end_position=9,fade_in=1,fade_out=1),data)
    plot.show()
    changes=[]
    plot.edited.connect(changes.append)
    drag(qtbot,plot,'start_position',2)
    assert abs(changes[-1]['start_position']-2) < .03
    drag(qtbot,plot,'end_position',8)
    assert abs(changes[-1]['end_position']-8) < .03
    drag(qtbot,plot,'fade_in',3)
    assert abs(changes[-1]['fade_in']-1) < .05
    drag(qtbot,plot,'fade_out',6)
    assert abs(changes[-1]['fade_out']-2) < .05
    assert len(changes) == 4
    drag(qtbot,plot,'start_position',10)
    assert plot.values['start_position'] < plot.values['end_position']


def test_escape_cancels_uncommitted_graph_drag(qtbot):
    plot=ClipPlot()
    qtbot.addWidget(plot)
    plot.resize(700,200)
    plot.configure(dict(start_position=1,end_position=9,fade_in=1,fade_out=1), WaveformData(10,np.zeros((3,1)),np.ones((3,1))))
    plot.show()
    before=dict(plot.values)
    changes=[]
    plot.edited.connect(changes.append)
    point=plot.handles()['start_position'].toPoint()
    qtbot.mousePress(plot,Qt.LeftButton,pos=point)
    qtbot.mouseMove(plot,QPoint(round(plot.time_x(3)),point.y()))
    qtbot.keyClick(plot,Qt.Key_Escape)
    qtbot.mouseRelease(plot,Qt.LeftButton,pos=point)
    assert plot.values == before
    assert changes == []


def test_fade_action_has_duration_handle_not_source_trim(qtbot):
    target = Cue('1.0')
    cue = Cue('2.0',action=ActionType.FADE,target_internal_id=target.internal_id,fade_duration=3)
    editor=ClipEditor()
    qtbot.addWidget(editor)
    editor.resize(700,240)
    editor.set_cue(cue,CueSet('Test',[target,cue]))
    editor.show()
    assert editor.plot.action_mode
    assert set(editor.plot.handles()) == {'fade_duration'}
    changes=[]
    editor.edited.connect(changes.append)
    drag(qtbot,editor.plot,'fade_duration',5)
    assert abs(changes[-1]['fade_duration']-5) < .03
    assert cue.fade_duration == 3  # owner chooses when to commit


def test_advanced_graph_and_numeric_fields_sync_and_cancel_is_atomic(qtbot,tmp_path):
    path=wave_file(tmp_path)
    cue=Cue('1.0',audio_file=str(path),end_position=2)
    before=asdict(cue)
    dlg=CueEditorDialog(cue,CueSet('Test',[cue]))
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.clip_editor.data is not None,timeout=5000)
    dlg.clip_editor._edited(dict(start_position=.25,end_position=1.75,fade_in=.2,fade_out=.3,fade_duration=0))
    assert dlg.start_spin.value() == .25
    assert dlg.fade_out_spin.value() == .3
    dlg.fade_in_spin.setValue(.4)
    assert dlg.clip_editor.plot.values['fade_in'] == .4
    assert asdict(cue) == before
    dlg.reject()
    assert asdict(cue) == before


def test_panel_graph_edit_persists_settings_recovery_and_preserves_source(qtbot,tmp_path):
    folder=PlayFolder(tmp_path,'Test')
    folder.ensure()
    path=wave_file(folder.audio_dir)
    original=path.read_bytes()
    cue=Cue('1.0',audio_file='audio/source.wav',end_position=2)
    cs=CueSet('Test',[cue])
    folder.save_version(cs)
    win=EditWindow(cs,AudioEngine(Mixer()),folder)
    qtbot.addWidget(win)
    win.list.setCurrentRow(0)
    qtbot.waitUntil(lambda: win.clip_editor.data is not None,timeout=5000)
    win.clip_editor._edited(dict(start_position=.2,end_position=1.7,fade_in=.1,fade_out=.4,fade_duration=0))
    assert cue.start_position == .2
    assert cue.fade_out == .4
    assert win.save_state.has_changes
    assert folder.load_recovery().cues[0].end_position == 1.7
    assert path.read_bytes() == original
    assert all(win.list.isColumnHidden(FIELDS.index(key)) for key in ('start_position','end_position','fade_in','fade_out','fade_duration'))
    assert win._save()
    assert folder.load_latest().cues[0].fade_out == .4


def test_finite_end_fade_and_manual_fade_match_without_gain_jump():
    cue=Cue('1.0',fade_out=.5)
    voice=Voice(cue,np.ones((1000,2),dtype=np.float32),1000)
    first=voice.render(750)
    assert first[100,0] == 1
    assert abs(first[-1,0]-.502) < .005
    voice.start_fade_out(.2)
    tail=voice.render(200)
    assert abs(tail[0,0]-.5) < .005
    assert tail[-1,0] < .01
    assert not voice.active


def test_loop_does_not_apply_out_envelope_on_each_repeat():
    cue=Cue('1.0',fade_out=.5,loop=True)
    voice=Voice(cue,np.ones((1000,2),dtype=np.float32),1000)
    output=voice.render(1500)
    assert np.all(output == 1)


def test_advanced_unrelated_edit_preserves_existing_exact_timing(qapp):
    cue=Cue('1.0',start_position=.123456789,end_position=20.987654321,fade_in=.123456789,fade_out=75.123456789)
    dlg=CueEditorDialog(cue,CueSet('Test',[cue]))
    dlg.name_edit.setText('Renamed')
    dlg._on_accept()
    assert dlg.result() == 1
    assert cue.start_position == .123456789
    assert cue.end_position == 20.987654321
    assert cue.fade_in == .123456789
    assert cue.fade_out == 75.123456789


def test_file_switch_ignores_preview_waveform_and_loads_actual_source(qtbot,tmp_path):
    path=wave_file(tmp_path)
    cue=Cue('1.0',audio_file=str(path))
    cue._preview_waveform=WaveformData(100,np.zeros((3,1)),np.ones((3,1)))
    editor=ClipEditor()
    qtbot.addWidget(editor)
    editor.set_cue(cue,CueSet('Test',[cue]))
    qtbot.waitUntil(lambda: editor.data is not None,timeout=5000)
    assert editor.data.duration == 2
    assert 'SAMPLE' not in editor.title.text()
