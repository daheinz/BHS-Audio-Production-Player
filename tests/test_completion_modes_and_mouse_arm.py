"""Explicit completion actions and exclusive row arming; no physical output."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QMessageBox
from bhs_player.cues.model import Cue, CueSet, AdvanceMode, ActionType, CueExecutionState
from bhs_player.cues.engine import CueEngine
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.storage.store import serialize_cue_set, deserialize_cue_set
from bhs_player.ui.cue_table import CueTable, FIELDS
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.main_window import MainWindow
from bhs_player.ui.cue_arm import CueArmHeader
from bhs_player.ui.cue_drag import CueDragHeader
from tests.fakes import FakeAudioEngine


def setup(mode=AdvanceMode.ON_COMPLETE_GO):
    cues=[Cue('1.0',advance_mode=mode),Cue('2.0'),Cue('3.0')]
    audio=FakeAudioEngine()
    engine=CueEngine(CueSet('Test',cues),audio)
    return engine,audio,cues


def finish(engine,audio,cue,natural=True):
    instance=audio.instances_of(cue.internal_id)[-1]
    audio.finish(instance,natural)
    engine.notify_sound_finished(cue.internal_id,natural,instance)


def test_existing_arm_only_and_new_auto_modes_roundtrip():
    cs=CueSet('Test',[Cue('1.0'),Cue('2.0',advance_mode=AdvanceMode.ON_COMPLETE_GO)])
    loaded=deserialize_cue_set(serialize_cue_set(cs))
    assert loaded.cues[0].advance_mode is AdvanceMode.ON_COMPLETE
    assert loaded.cues[0].advance_mode.value=='on_complete'
    assert loaded.cues[1].advance_mode is AdvanceMode.ON_COMPLETE_GO


def test_arm_only_does_not_auto_execute():
    engine,audio,cues=setup(AdvanceMode.ON_COMPLETE)
    engine.go()
    finish(engine,audio,cues[0])
    assert engine.armed_cue is cues[1]
    assert engine.process_pending_auto_go() is None
    assert audio.started_cues==[cues[0].internal_id]


def test_auto_waits_for_natural_end_and_dispatches_exactly_once():
    engine,audio,cues=setup()
    engine.go()
    assert engine.armed_cue is cues[1]
    assert engine.process_pending_auto_go() is None
    finish(engine,audio,cues[0])
    assert audio.started_cues==[cues[0].internal_id]
    assert engine.process_pending_auto_go().ok
    assert engine.process_pending_auto_go() is None
    assert audio.started_cues==[cues[0].internal_id,cues[1].internal_id]
    assert engine.waiting_cue is cues[1]


@pytest.mark.parametrize('operation',['stop','back','arm','loss','exit'])
@pytest.mark.parametrize('queued',[False,True])
def test_navigation_and_interruptions_cancel_auto(operation,queued):
    engine,audio,cues=setup()
    engine.go()
    if queued:
        finish(engine,audio,cues[0])
    if operation=='stop':
        engine.stop_all()
    elif operation=='back':
        engine.back()
    elif operation=='arm':
        engine.arm_cue(cues[2].internal_id)
    else:
        engine.interrupt_output(disarm=operation=='exit')
        if operation=='loss':
            audio.set_ready(False)
    engine.process_pending_auto_go()
    assert audio.started_cues==[cues[0].internal_id]


def test_manual_go_consumes_queued_auto_request():
    engine,audio,cues=setup()
    engine.go()
    finish(engine,audio,cues[0])
    assert engine.go().ok
    assert engine.process_pending_auto_go() is None
    assert len(audio.started_cues)==2


def test_early_stop_or_fade_never_automatically_executes_next():
    engine,audio,cues=setup()
    engine.go()
    finish(engine,audio,cues[0],natural=False)
    assert engine.armed_cue is None
    assert engine.process_pending_auto_go() is None
    assert cues[0].execution_state is CueExecutionState.INTERRUPTED


def test_auto_failure_remains_armed_and_not_successfully_triggered():
    engine,audio,cues=setup()
    engine.go()
    finish(engine,audio,cues[0])
    audio.fail_next_start=True
    result=engine.process_pending_auto_go()
    assert not result.ok
    assert engine.armed_cue is cues[1]
    assert cues[1].execution_state is CueExecutionState.ARMED
    assert audio.started_cues==[cues[0].internal_id]


def test_unavailable_output_blocks_queued_auto_without_later_replay():
    engine,audio,cues=setup()
    engine.go()
    finish(engine,audio,cues[0])
    audio.set_ready(False)
    assert not engine.process_pending_auto_go().ok
    audio.set_ready(True)
    assert engine.process_pending_auto_go() is None
    assert len(audio.started_cues)==1


def test_old_playback_of_same_cue_cannot_trigger_new_wait():
    engine,audio,cues=setup()
    engine.go()
    old=audio.instances_of(cues[0].internal_id)[0]
    engine.arm_cue(cues[0].internal_id)
    engine.go()
    current=audio.instances_of(cues[0].internal_id)[-1]
    audio.finish(old)
    engine._on_instance_ended(old,True)
    assert engine.waiting_cue is cues[0]
    assert engine.process_pending_auto_go() is None
    audio.finish(current)
    engine._on_instance_ended(current,True)
    assert engine.process_pending_auto_go().ok
    assert audio.started_cues[-1]==cues[1].internal_id


def test_auto_can_execute_action_but_does_not_chain_beyond_it():
    engine,audio,cues=setup()
    cues[1].action=ActionType.STOP_ALL
    engine.go()
    finish(engine,audio,cues[0])
    assert engine.process_pending_auto_go().ok
    assert cues[1].execution_state is CueExecutionState.COMPLETE
    assert engine.armed_cue is cues[2]
    assert engine.process_pending_auto_go() is None


def test_auto_end_of_list_never_wraps():
    engine,audio,cues=setup()
    engine.arm_cue(cues[-1].internal_id)
    cues[-1].advance_mode=AdvanceMode.ON_COMPLETE_GO
    engine.go()
    finish(engine,audio,cues[-1])
    assert engine.armed_cue is None
    assert engine.process_pending_auto_go() is None
    assert len(audio.started_cues)==1


@pytest.mark.parametrize('mode',[AdvanceMode.ON_COMPLETE,AdvanceMode.ON_COMPLETE_GO])
def test_both_completion_modes_reject_loop(mode):
    cue=Cue('1.0',loop=True,advance_mode=mode)
    assert not cue.loop_config_valid()
    engine=CueEngine(CueSet('Test',[cue]),FakeAudioEngine())
    assert not engine.go().ok


def test_real_completion_does_not_start_next_inside_audio_thread(qapp):
    cues=[Cue('1.0',advance_mode=AdvanceMode.ON_COMPLETE_GO),Cue('2.0')]
    audio=AudioEngine(Mixer())
    started=[]
    original=audio.start
    def start(cue):
        started.append(threading.current_thread().name)
        return original(cue,pcm=np.ones((100,2),dtype=np.float32)*.1)
    audio.start=start
    engine=CueEngine(CueSet('Test',cues),audio)
    engine.go()
    thread=threading.Thread(target=lambda:audio.mixer.render_block(1024),name='audio-render-test')
    thread.start()
    thread.join()
    assert len(started)==1
    assert engine.process_pending_auto_go().ok
    assert started==['MainThread','MainThread']


def test_new_modes_available_and_synchronized_in_both_editors(qapp):
    cs=CueSet('Test',[Cue('1.0')])
    table=CueTable(cs,editable=True)
    combo=table.cellWidget(0,FIELDS.index('advance_mode'))
    assert [combo.itemText(i) for i in range(combo.count())]==['Arm Next at End','GO on End','Arm Next Now']
    combo.setCurrentIndex(combo.findData(AdvanceMode.ON_COMPLETE_GO))
    dlg=CueEditorDialog(cs.cues[0],cs)
    assert dlg.advance_combo.currentText()=='GO on End'


def test_row_mouse_arming_is_exclusive_silent_and_banner_is_above_stack(qtbot):
    cues=[Cue('1.0','First'),Cue('2.0','Second'),Cue('3.0','Third')]
    cs=CueSet('Test',cues)
    audio=AudioEngine(Mixer())
    engine=CueEngine(cs,audio)
    win=MainWindow(cs,engine,audio,confirm_close=False)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitUntil(lambda:win.isVisible())
    header=win.cue_list.verticalHeader()
    assert isinstance(header,CueArmHeader)
    for row in (1,1,2):
        pos=QPoint(30,win.cue_list.rowViewportPosition(row)+win.cue_list.rowHeight(row)//2)
        qtbot.mouseClick(header.viewport(),Qt.LeftButton,pos=pos)
        assert engine.armed_cue is cues[row]
        assert audio.active_instances()==[]
        assert sum(c.execution_state is CueExecutionState.ARMED for c in cues)==1
        assert cues[row].name in win.armed_lbl.text()
    assert win.armed_lbl.parentWidget() is win.armed_card
    assert isinstance(CueTable(cs,editable=True).verticalHeader(),CueDragHeader)


def test_ui_auto_banner_and_dispatch_respect_modal_context(qtbot):
    cues=[Cue('1.0','First',advance_mode=AdvanceMode.ON_COMPLETE_GO),Cue('2.0','Next')]
    cs=CueSet('Test',cues)
    audio=AudioEngine(Mixer())
    original=audio.start
    audio.start=lambda cue:original(cue,pcm=np.ones((100,2),dtype=np.float32)*.1)
    engine=CueEngine(cs,audio)
    win=MainWindow(cs,engine,audio,confirm_close=False)
    qtbot.addWidget(win)
    win._timer.stop()
    win._go()
    assert 'AUTO GO' in win.armed_detail.text()
    audio.mixer.render_block(1024)
    box=QMessageBox(win)
    box.setModal(True)
    box.show()
    win._refresh()
    assert audio.active_instances()==[]
    box.close()
    win._refresh()
    assert len(audio.active_instances())==1
    assert audio.active_instances()[0].cue_internal_id==cues[1].internal_id
    assert 'Automatic GO' in win.status_lbl.text()


def test_auto_successor_is_preloaded_while_source_plays():
    first=Cue('1.0',audio_file='first.wav',advance_mode=AdvanceMode.ON_COMPLETE_GO)
    following=Cue('2.0',audio_file='next.wav')
    audio=FakeAudioEngine()
    prepared=[]
    audio.prepare_async=lambda cue:prepared.append(cue.internal_id)
    engine=CueEngine(CueSet('Test',[first,following]),audio)
    assert engine.go().ok
    assert following.internal_id in prepared
    assert audio.started_cues==[first.internal_id]


def test_successive_auto_cues_chain_until_arm_only_mode():
    engine,audio,cues=setup()
    cues[1].advance_mode=AdvanceMode.ON_COMPLETE_GO
    engine.go()
    for cue in cues[:2]:
        finish(engine,audio,cue)
        assert engine.process_pending_auto_go().ok
    assert audio.started_cues==[c.internal_id for c in cues]
    finish(engine,audio,cues[-1])
    assert engine.process_pending_auto_go() is None
    assert engine.armed_cue is None


def test_clicking_arm_on_pending_successor_cancels_auto_without_playing(qtbot):
    cues=[Cue('1.0',advance_mode=AdvanceMode.ON_COMPLETE_GO),Cue('2.0')]
    audio=AudioEngine(Mixer())
    original=audio.start
    audio.start=lambda cue:original(cue,pcm=np.ones((100,2),dtype=np.float32)*.1)
    engine=CueEngine(CueSet('Test',cues),audio)
    win=MainWindow(engine.cue_set,engine,audio,confirm_close=False)
    qtbot.addWidget(win)
    win._timer.stop()
    win._go()
    audio.mixer.render_block(1024)
    win.cue_list.verticalHeader()._request(1)
    assert engine.process_pending_auto_go() is None
    assert audio.active_instances()==[]
    assert engine.armed_cue is cues[1]


@pytest.mark.parametrize('mode,armed_during_play', [
    (AdvanceMode.ON_GO, True),
    (AdvanceMode.ON_COMPLETE, False),
    (AdvanceMode.ON_COMPLETE_GO, True),
])
def test_each_next_cue_action_has_explicit_arming_time(mode, armed_during_play):
    engine,audio,cues=setup(mode)
    engine.go()
    assert (engine.armed_cue is cues[1]) is armed_during_play
    if armed_during_play:
        assert cues[1].execution_state is CueExecutionState.ARMED
    finish(engine,audio,cues[0])
    assert engine.armed_cue is cues[1]
    result=engine.process_pending_auto_go()
    assert (result is not None) is (mode is AdvanceMode.ON_COMPLETE_GO)


def test_manual_go_before_source_end_executes_armed_cue_only_once():
    engine,audio,cues=setup()
    engine.go()
    assert engine.armed_cue is cues[1]
    assert engine.go_available()[0]
    assert engine.go().cue is cues[1]
    finish(engine,audio,cues[0])
    assert engine.process_pending_auto_go() is None
    assert engine.waiting_cue is cues[1]
    assert audio.started_cues == [cues[0].internal_id,cues[1].internal_id]
    assert cues[0].execution_state is CueExecutionState.COMPLETE


@pytest.mark.parametrize('rehearsal', [False, True])
def test_go_on_end_displays_next_as_armed_then_starts_it(qtbot,rehearsal):
    cues=[Cue('7.0','Thunder',advance_mode=AdvanceMode.ON_COMPLETE_GO),
          Cue('8.0','Doorbell',advance_mode=AdvanceMode.ON_GO), Cue('9.0','Next')]
    audio=AudioEngine(Mixer())
    start=audio.start
    audio.start=lambda cue:start(cue,pcm=np.ones((100,2),dtype=np.float32)*.1)
    engine=CueEngine(CueSet('Test',cues),audio)
    win=MainWindow(engine.cue_set,engine,audio,rehearsal=rehearsal,confirm_close=False)
    qtbot.addWidget(win)
    win._timer.stop()
    win.show()
    qtbot.waitExposed(win)
    qtbot.mouseClick(win.go_btn,Qt.LeftButton)
    assert 'ARMED: 8.0' in win.armed_lbl.text()
    assert 'AUTO GO on end of 7.0' in win.armed_detail.text()
    assert win.go_btn.isEnabled()
    header=win.cue_list.verticalHeader()
    assert header.model().headerData(1,Qt.Vertical)=='ARMED'
    image=header.viewport().grab().toImage()
    assert image.pixelColor(8,header.sectionViewportPosition(1)+10).name()=='#f1db8b'
    audio.mixer.render_block(101)
    assert engine.armed_cue is cues[1]  # execution is deferred off audio callback
    win._refresh()
    assert audio.active_instances()[0].cue_internal_id==cues[1].internal_id
    assert engine.armed_cue is cues[2]
    assert header.model().headerData(2,Qt.Vertical)=='ARMED'
    win._refresh()
    assert len(audio.active_instances())==1
    win.close()
