"""Real saved sample workflow, using generated test assets rather than private Music files."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QMessageBox
from bhs_player import sample_production
from bhs_player.sample_production import build_audio_prototype
from bhs_player.storage.store import PlayFolder
from bhs_player.app import launch_arguments, ProductionController
from bhs_player.ui.open_play_dialog import OpenPlayDialog
from bhs_player.validate.check import validate_show


@pytest.fixture
def source_music(tmp_path,monkeypatch):
    root=tmp_path/'Music'
    other=root/'Other'
    other.mkdir(parents=True)
    sources={role:role+'.wav' for role in sample_production.SOURCES}
    monkeypatch.setattr(sample_production,'SOURCES',sources)
    for role,name in sources.items():
        seconds=40 if role=='music' else 1
        rate=8000
        time=np.arange(int(seconds*rate))/rate
        pcm=(.2*np.sin(2*np.pi*220*time)).astype(np.float32)
        if role!='bell':
            pcm=np.stack([pcm,pcm],axis=1)
        sf.write(str(other/name),pcm,rate)
    return root


def test_builder_creates_real_portable_show_and_leaves_originals_unchanged(source_music,tmp_path):
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source_music.rglob('*.wav')}
    folder,created=build_audio_prototype(source_music,tmp_path/'Plays')
    assert created
    cs=folder.load_latest()
    assert len(cs.cues)==8
    assert cs.profile.primary_device is None
    assert cs.profile.buses[0].level==.5
    assert {b.id for b in cs.profile.buses}=={'main'}
    assert len(list(folder.audio_dir.iterdir()))==5
    for cue in cs.cues:
        if cue.is_play_sound():
            assert not Path(cue.audio_file).is_absolute()
            assert (folder.folder/cue.audio_file).is_file()
    assert cs.by_identifier('4.0').target_internal_id==cs.by_identifier('3.0').internal_id
    assert cs.by_identifier('5.0').target_internal_id==cs.by_identifier('2.0').internal_id
    assert validate_show(cs,folder.folder,True).critical==[]
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source_music.rglob('*.wav')}==before
    assert (folder.folder/'PRACTICE-GUIDE.md').read_text(encoding='utf-8').startswith('# Audio Prototype')


def test_rerun_preserves_user_edits_history_and_recovery(source_music,tmp_path):
    folder,_=build_audio_prototype(source_music,tmp_path/'Plays')
    cs=folder.load_latest()
    cs.cues[0].name='My edits'
    folder.save_version(cs)
    cs.cues[0].notes='Unsaved recovery'
    folder.save_recovery(cs)
    _,created=build_audio_prototype(source_music,tmp_path/'Plays')
    assert not created
    assert len(folder.list_versions())==2
    assert folder.load_latest().cues[0].name=='My edits'
    assert folder.load_recovery().cues[0].notes=='Unsaved recovery'


def test_missing_source_does_not_create_partial_production(source_music,tmp_path):
    (source_music/'Other'/'bell.wav').unlink()
    with pytest.raises(FileNotFoundError):
        build_audio_prototype(source_music,tmp_path/'Plays')
    assert not (tmp_path/'Plays'/'Audio Prototype').exists()


def test_existing_unsaved_folder_is_not_overwritten(source_music,tmp_path):
    folder=PlayFolder(tmp_path/'Plays','Audio Prototype')
    folder.ensure()
    with pytest.raises(FileExistsError):
        build_audio_prototype(source_music,tmp_path/'Plays')
    assert not list(folder.audio_dir.iterdir())


def test_named_launch_opens_latest_and_preserves_normal_recovery_flow(qapp,source_music,tmp_path,monkeypatch):
    folder,_=build_audio_prototype(source_music,tmp_path/'Plays')
    cs=folder.load_latest()
    cs.cues[0].notes='Recovered work'
    folder.save_recovery(cs)
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    dlg=OpenPlayDialog(tmp_path/'Plays')
    assert dlg.open_named('Audio Prototype')
    assert dlg.result_version_name=='(recovery)'
    assert dlg.result_cue_set.cues[0].notes=='Recovered work'
    assert folder.has_recovery()
    assert len(folder.list_versions())==1


def test_named_launch_cancel_and_missing_are_safe(qapp,source_music,tmp_path,monkeypatch):
    folder,_=build_audio_prototype(source_music,tmp_path/'Plays')
    folder.save_recovery(folder.load_latest())
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Cancel)
    assert not OpenPlayDialog(tmp_path/'Plays').open_named('Audio Prototype')
    warnings=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:warnings.append(args))
    assert not OpenPlayDialog(tmp_path/'Plays').open_named('Missing')
    assert warnings


def test_command_line_modes_are_explicit():
    assert launch_arguments([]).production is None
    assert launch_arguments(['--gui-preview']).gui_preview
    assert launch_arguments(['--production','Audio Prototype']).production=='Audio Prototype'
    with pytest.raises(SystemExit):
        launch_arguments(['--gui-preview','--production','Audio Prototype'])


def test_opening_sample_does_not_start_audio(qapp,source_music,tmp_path,monkeypatch):
    folder,_=build_audio_prototype(source_music,tmp_path/'Plays')
    opened=[]
    monkeypatch.setattr('bhs_player.audio.stream.OutputStream',lambda *a,**k:opened.append(True))
    controller=ProductionController(folder.load_latest(),folder)
    assert opened==[]
    assert controller.audio.active_instances()==[]
    assert not controller.audio.ready
    assert controller.engine.armed_cue is None
