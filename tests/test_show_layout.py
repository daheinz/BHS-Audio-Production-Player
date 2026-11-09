"""Approved Show/Rehearse restructuring: real Qt interactions, no hardware."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit, QPushButton
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue, CueSet, AdvanceMode, CueExecutionState
from bhs_player.profiles import OutputBus
from bhs_player.ui.main_window import MainWindow
from bhs_player.ui.widgets import LevelMeter


@pytest.fixture
def show(qtbot):
    cues = [Cue(str(i)+".0", "Cue "+str(i), advance_mode=AdvanceMode.ON_GO) for i in range(1, 7)]
    cs = CueSet("Layout", cues)
    cs.profile.buses.append(OutputBus(id="fx", name="Effects"))
    audio = AudioEngine(Mixer())
    start = audio.start
    audio.start = lambda cue: start(cue, pcm=np.ones((44100, 2), dtype=np.float32)*.1)
    engine = CueEngine(cs, audio)
    win = MainWindow(cs, engine, audio, confirm_close=False)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


@pytest.mark.parametrize("size", [(1500, 920), (1000, 700)])
def test_three_regions_resize_and_no_redundant_arm(show, qtbot, size):
    show.resize(*size)
    qtbot.wait(20)
    table = show.cue_list
    right = show.main_splitter.widget(1)
    assert 0.58 < show.main_splitter.sizes()[0]/sum(show.main_splitter.sizes()) < .73
    assert table.height() > show.height()*.5
    assert show.bottom_panel.height() <= show.height()*.26
    assert show.armed_panel.geometry().bottom() < show.playing_panel.geometry().top()
    assert show.go_btn.parentWidget() is show.bottom_panel
    assert show.meter_scroll.x() > show.stop_all_btn.x()
    from bhs_player.ui.cue_table import FIELDS
    assert table.isColumnHidden(FIELDS.index('audio_file'))
    assert table.horizontalHeaderItem(FIELDS.index('identifier')).text() == 'Cue'
    assert table.horizontalHeaderItem(FIELDS.index('bus_ids')).text() == 'Bus'
    if size[0] <= 1000:
        assert table.horizontalScrollBar().maximum() > 0
    assert right.width() > 240
    assert not any(b.text() == "ARM CUE" for b in show.findChildren(QPushButton))


def test_stack_is_bottom_aligned_and_scrollable_without_moving_armed(show, qtbot):
    show._go()
    qtbot.wait(20)
    entry = next(iter(show._stack_entries.values()))
    assert not entry.findChildren(LevelMeter)
    assert entry.geometry().bottom() >= show.stack_scroll.viewport().height()-5
    assert entry.height() < 130
    assert entry.stop_btn.toolTip() == "Stop this playback"
    assert entry.fade_btn.toolTip() == "Fade out this playback"
    armed_top = show.armed_panel.geometry().top()
    for _ in range(5):
        show._go()
    show.resize(1000, 700)
    qtbot.wait(20)
    assert show.stack_scroll.verticalScrollBar().maximum() > 0
    assert show.armed_panel.geometry().top() == armed_top
    assert show.stack_area.itemAt(0).widget().instance.identifier == "6.0"
    assert show.stack_area.itemAt(5).widget().instance.identifier == "1.0"


def test_selection_enter_and_space_work_from_table_without_repeat(show, qtbot):
    original = show.engine.armed_cue
    show.cue_list.setCurrentRow(0)
    show.cue_list.setFocus()
    qtbot.keyClick(show.cue_list, Qt.Key_Down)
    assert show.cue_list.currentRow() == 1
    assert show.engine.armed_cue is original
    qtbot.keyClick(show.cue_list, Qt.Key_Return)
    assert show.engine.armed_cue.identifier == "2.0"
    qtbot.keyPress(show.cue_list, Qt.Key_Space)
    assert len(show.audio.active_instances()) == 1
    repeat = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ", True)
    show.keyPressEvent(repeat)
    assert len(show.audio.active_instances()) == 1
    qtbot.keyRelease(show.cue_list, Qt.Key_Space)
    qtbot.keyClick(show.cue_list, Qt.Key_Space)
    assert len(show.audio.active_instances()) == 2


def test_no_armed_space_is_silent_and_stop_all_shortcut_cleans_up(show, qtbot):
    show._go()
    show.cue_list.setFocus()
    qtbot.keyClick(show.cue_list, Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
    assert show.audio.active_instances() == []
    assert show.engine.armed_cue.identifier == "2.0"  # existing independently armed cue survives STOP ALL
    show.engine.interrupt_output(disarm=True)
    show._refresh()
    assert not show.go_btn.isEnabled()
    qtbot.keyClick(show.cue_list, Qt.Key_Space)
    assert show.audio.active_instances() == []
    assert show.armed_lbl.text() == "No cue armed"


def test_text_entry_blocks_show_shortcuts(show, qtbot):
    show._go()
    field = QLineEdit(show)
    field.show()
    field.setFocus()
    qtbot.keyClick(field, Qt.Key_Space)
    qtbot.keyClick(field, Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
    qtbot.keyClick(field, Qt.Key_Return)
    qtbot.keyClick(field, Qt.Key_F, Qt.ControlModifier)
    assert field.text() == " "
    assert len(show.audio.active_instances()) == 1
    assert show.engine.armed_cue.identifier == "2.0"


def test_selected_playback_fade_shortcut_and_buttons_are_instance_local(show, qtbot):
    show._go()
    show._go()
    qtbot.wait(30)
    newest = show.stack_area.itemAt(0).widget()
    oldest = show.stack_area.itemAt(1).widget()
    show.cue_list.setFocus()
    qtbot.keyClick(show.cue_list, Qt.Key_F, Qt.ControlModifier)
    assert len(show.audio.active_instances()) == 2
    qtbot.mouseClick(newest, Qt.LeftButton)
    assert show._selected_playback is newest
    assert newest.hasFocus()
    qtbot.keyClick(newest, Qt.Key_F, Qt.ControlModifier)
    assert newest.instance not in show.audio.active_instances()
    assert oldest.instance in show.audio.active_instances()
    qtbot.mouseClick(oldest.stop_btn, Qt.LeftButton)
    assert show.audio.active_instances() == []


def test_per_cue_bus_identity_and_performance_state_colors(show, qtbot):
    show.cue_set.cues[0].bus_ids = ["fx"]
    show._go()
    entry = show.stack_area.itemAt(0).widget()
    assert "Effects" in entry.destination.text()
    assert "Main" not in entry.destination.text()
    assert show.cue_list.item(0, 0).background().color().name() == "#875024"
    assert show.cue_list.item(1, 0).background().color().name() == "#f1db8b"
    assert show.cue_list.item(1, 0).foreground().color().name() == "#292411"
    show.cue_set.cues[2].execution_state = CueExecutionState.COMPLETE
    show.cue_set.cues[3].execution_state = CueExecutionState.INTERRUPTED
    show._refresh()
    assert show.cue_list.item(2, 0).background() != show.cue_list.item(3, 0).background()


@pytest.mark.parametrize("rehearsal", [False, True])
def test_auto_arm_now_updates_native_header_and_painted_flags(qtbot, rehearsal):
    cues = [Cue(str(i)+".0", "Cue "+str(i), advance_mode=AdvanceMode.ON_GO) for i in range(1, 4)]
    cs = CueSet("Flags", cues)
    audio = AudioEngine(Mixer())
    start = audio.start
    audio.start = lambda cue: start(cue, pcm=np.ones((44100, 2), dtype=np.float32)*.1)
    engine = CueEngine(cs, audio)
    win = MainWindow(cs, engine, audio, rehearsal=rehearsal, confirm_close=False)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    header = win.cue_list.verticalHeader()
    for armed_row in range(3):
        qtbot.wait(10)
        image = header.viewport().grab().toImage()
        for row in range(3):
            assert header.model().headerData(row, Qt.Vertical) == ("ARMED" if row == armed_row else "ARM")
            fill = image.pixelColor(8, header.sectionViewportPosition(row)+10).name()
            assert fill == ("#f1db8b" if row == armed_row else "#875024" if row < armed_row else "#272e38")
        # Exercise the same mouse GO path used in Show and Rehearse.
        qtbot.mouseClick(win.go_btn, Qt.LeftButton)
    assert engine.armed_cue is None
    assert all(header.model().headerData(row, Qt.Vertical) == "ARM" for row in range(3))
    win.close()


@pytest.mark.parametrize("rehearsal", [False, True])
def test_controller_mode_entry_resets_previous_playback_colors(qtbot, rehearsal):
    from bhs_player.app import ProductionController
    states = [CueExecutionState.INTERRUPTED, CueExecutionState.COMPLETE,
              CueExecutionState.PLAYING, CueExecutionState.TRIGGERED]
    cs = CueSet("Session", [Cue(str(i)+".0") for i in range(1, 5)])
    controller = ProductionController(cs, preview=True)
    qtbot.addWidget(controller.edit)
    for cue, state in zip(cs.cues, states):
        cue.execution_state = state
    controller.enter_show(rehearsal=rehearsal)
    win = controller.show_window
    qtbot.addWidget(win)
    assert all(c.execution_state is CueExecutionState.IDLE for c in cs.cues)
    assert controller.engine.armed_cue is None
    assert not win.go_btn.isEnabled()
    assert win.cue_list.item(0, 0).background() == win.cue_list.item(1, 0).background()
    win.close()
    # Re-enter after another rehearsal result: every new session is neutral.
    cs.cues[2].execution_state = CueExecutionState.INTERRUPTED
    controller.enter_show(rehearsal=not rehearsal)
    qtbot.addWidget(controller.show_window)
    assert all(c.execution_state is CueExecutionState.IDLE for c in cs.cues)
    controller.show_window.close()


def test_runtime_states_are_not_restored_from_old_or_new_files():
    import json
    from bhs_player.storage.store import serialize_cue_set, deserialize_cue_set
    cue = Cue("9.0", execution_state=CueExecutionState.INTERRUPTED)
    cs = CueSet("History", [cue])
    saved = serialize_cue_set(cs)
    assert json.loads(saved)["cues"][0]["execution_state"] == "idle"
    assert cue.execution_state is CueExecutionState.INTERRUPTED  # saving does not alter current display
    legacy = json.loads(saved)
    for state in CueExecutionState:
        legacy["cues"][0]["execution_state"] = state.value
        assert deserialize_cue_set(json.dumps(legacy)).cues[0].execution_state is CueExecutionState.IDLE


@pytest.mark.parametrize("rehearsal", [False, True])
def test_cue_follow_starts_at_middle_centers_and_clamps_without_selecting(qtbot, rehearsal):
    cs = CueSet("Follow", [Cue(str(i)+".0", "Cue "+str(i), advance_mode=AdvanceMode.ON_GO) for i in range(1, 41)])
    audio = AudioEngine(Mixer())
    start = audio.start
    audio.start = lambda cue: start(cue, pcm=np.ones((44100, 2), dtype=np.float32)*.1)
    engine = CueEngine(cs, audio)
    win = MainWindow(cs, engine, audio, rehearsal=rehearsal, confirm_close=False)
    qtbot.addWidget(win)
    win.resize(1000, 700)
    win.show()
    qtbot.waitExposed(win)
    win._timer.stop()
    table = win.cue_list
    table.setCurrentRow(0)
    table.horizontalScrollBar().setValue(100)
    horizontal = table.horizontalScrollBar().value()
    bar = table.verticalScrollBar()
    height = table.viewport().height()
    # Early rows remain at the top; reaching the middle begins following.
    engine.arm_cue(cs.cues[1].internal_id)
    win._refresh()
    assert bar.value() == 0
    for row in (8, 14, 24):
        engine.arm_cue(cs.cues[row].internal_id)
        win._refresh()
        qtbot.wait(10)
        rect = table.visualItemRect(table.item(row, 0))
        assert abs(rect.center().y() - table.viewport().height()//2) <= table.rowHeight(row)
        assert table.currentRow() == 0
        assert table.horizontalScrollBar().value() == horizontal
        assert engine.armed_cue is cs.cues[row]
    # Browsing is not snapped back by the normal refresh timer.
    bar.setValue(0)
    win._refresh()
    assert bar.value() == 0
    # A real GO advances the armed cue and resumes following.
    win._go()
    assert engine.armed_cue is cs.cues[25]
    assert bar.value() > 0
    engine.arm_cue(cs.cues[-1].internal_id)
    win._refresh()
    assert bar.value() == bar.maximum()
    assert table.visualItemRect(table.item(39, 0)).bottom() <= table.viewport().height()
    win.close()
