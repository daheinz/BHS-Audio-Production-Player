"""Playback mode parity, silent transitions, compact meters, and stack instances."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QWidget, QHBoxLayout
from bhs_player.app import ProductionController
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue,CueSet,AdvanceMode
from bhs_player.audio.engine import AudioEngine,Mixer
from bhs_player.audio.stream import OutputDevice
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.main_window import MainWindow
from bhs_player.ui.widgets import LevelMeter


class CallbackStream:
    opened=[]
    def __init__(self, **kwargs):
        self.callback=kwargs['callback']
        self.running=False
        self.opened.append(self)
    def start(self):
        self.running=True
    def stop(self):
        self.running=False
    def close(self):
        self.running=False
    def pump(self,count=1024):
        block=np.zeros((count,2),dtype=np.float32)
        self.callback(block,count,None,None)
        return block


def test_show_rehearse_reentry_use_identical_output_and_no_stream_reopen(qapp,qtbot,tmp_path,monkeypatch):
    CallbackStream.opened=[]
    dev=OutputDevice(0,'Test speakers','Test',2,44100)
    monkeypatch.setattr('bhs_player.audio.routing.list_output_devices',lambda:[dev])
    monkeypatch.setattr('bhs_player.audio.stream.sd.OutputStream',CallbackStream)
    folder=PlayFolder(tmp_path,'Modes')
    folder.ensure()
    pcm=(.2*np.sin(2*np.pi*440*np.arange(44100)/44100)).astype(np.float32)
    sf.write(str(folder.audio_dir/'tone.wav'),np.stack([pcm,pcm],axis=1),44100)
    cs=CueSet('Modes',[Cue('1.0',audio_file='audio/tone.wav')])
    cs.profile.primary_device='Test speakers [Test]'
    folder.save_version(cs)
    c=ProductionController(cs,folder)
    monkeypatch.setattr(c.routing,'unconfirmed',lambda:[])  # Controlled test adapter; no human test results are recorded.
    outputs=[]
    for rehearsal in (True,False,True):
        c.enter_show(rehearsal=rehearsal)
        qtbot.waitUntil(lambda:c.show_window is not None,timeout=10000)
        assert c.show_window is not None
        assert c.show_window.rehearsal is rehearsal
        c.show_window.cue_list.setCurrentRow(0)
        c.show_window._arm_selected()
        qtbot.waitUntil(lambda:c.engine.go_available()[0],timeout=10000)
        c.show_window._go()
        stream=CallbackStream.opened[0]
        output=stream.pump()
        assert np.max(np.abs(output))>.1
        outputs.append(output)
        c.show_window.close()
        assert c.engine.armed_cue is None
        assert c.audio.active_instances()==[]
        assert not np.any(stream.pump())
    assert len(CallbackStream.opened)==1
    np.testing.assert_array_equal(outputs[0],outputs[1])
    np.testing.assert_array_equal(outputs[1],outputs[2])
    c.backend.stop()
    assert not CallbackStream.opened[0].running


def test_level_meter_does_not_stretch_beyond_144_logical_pixels(qapp):
    host=QWidget()
    layout=QHBoxLayout(host)
    meter=LevelMeter()
    layout.addWidget(meter,1)
    host.resize(1200,100)
    host.show()
    qapp.processEvents()
    assert meter.width()<=144
    assert meter.maximumWidth()==144
    host.hide()


def test_batch_stack_newest_on_top_replay_separate_and_stop_is_local(qapp):
    cue=Cue('1.0','Loop',loop=True,advance_mode=AdvanceMode.ON_GO)
    audio=AudioEngine(Mixer())
    cs=CueSet('Stack',[cue])
    engine=CueEngine(cs,audio)
    pcm=np.ones((44100,2),dtype=np.float32)*.1
    first=audio.start(cue,pcm=pcm)
    second=audio.start(cue,pcm=pcm)
    win=MainWindow(cs,engine,audio,confirm_close=False)
    assert win.stack_area.count()==2
    newest=win.stack_area.itemAt(0).widget()
    oldest=win.stack_area.itemAt(1).widget()
    assert newest.instance is second
    assert oldest.instance is first
    assert 'playback #2' in newest.title.text()
    assert '2 sounds' in win.stack_heading.text()
    win.show()
    qapp.processEvents()
    assert oldest.geometry().bottom() <= win.stack_scroll.viewport().height()
    newest._fade()
    win._refresh()
    # The configured zero-duration fade stops only this instance.
    assert first in audio.active_instances()
    assert second not in audio.active_instances()
    assert win.stack_area.count()==1
    oldest._stop()
    win._refresh()
    assert not win.stack_empty.isHidden()
    win.close()


def test_loop_fade_status_exposes_both_states(qapp):
    cue=Cue('1.0','Loop',loop=True,fade_out=1)
    audio=AudioEngine(Mixer())
    cs=CueSet('Stack',[cue])
    engine=CueEngine(cs,audio)
    inst=audio.start(cue,pcm=np.ones((44100,2),dtype=np.float32)*.1)
    win=MainWindow(cs,engine,audio,confirm_close=False)
    entry=win.stack_area.itemAt(0).widget()
    entry._fade()
    entry.refresh()
    assert 'FADING' in entry.title.text()
    assert 'LOOPING' in entry.title.text()
    win.close()
