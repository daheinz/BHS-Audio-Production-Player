"""DOC-002 v0.2 GUI/state acceptance. Output streams are fakes; no hardware claims."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from bhs_player.profiles import ProductionProfile, OutputBus
from bhs_player.cues.model import Cue, CueSet, AdvanceMode, ActionType
from bhs_player.cues.engine import CueEngine
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.audio.stream import StreamingAudioBackend, OutputDevice
from bhs_player.audio.routing import RoutingSession
from bhs_player.storage.store import serialize_cue_set, deserialize_cue_set, PlayFolder
from bhs_player.ui.cue_table import CueTable, FIELDS
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.profile_dialog import ProfileDialog
from bhs_player.ui.audio_test_dialog import AudioTestDialog
from bhs_player.ui.linked_cues_dialog import LinkedCuesDialog
from bhs_player.ui.main_window import MainWindow
from bhs_player.app import ProductionController, preview_production


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Stream:
    def __init__(self, *args, **kwargs):
        self.running = False
        self.device_name = "Controlled test stream"
        self.on_output_lost = None
    def start(self):
        self.running = True
    def stop(self):
        self.running = False


@pytest.fixture
def session(qapp, monkeypatch):
    devs = [OutputDevice(4, "Primary", "Test", 2, 44100), OutputDevice(8, "Backup", "Test", 2, 44100)]
    monkeypatch.setattr("bhs_player.audio.routing.list_output_devices", lambda: devs)
    monkeypatch.setattr("bhs_player.audio.stream.OutputStream", Stream)
    cs = CueSet("Test", [Cue("1.0"), Cue("1.10")])
    cs.profile.primary_device = "Primary [Test]"
    cs.profile.backup_device = "Backup [Test]"
    audio = AudioEngine(Mixer(), ready=False)
    engine = CueEngine(cs, audio)
    return RoutingSession(cs, audio, StreamingAudioBackend(audio), engine)


def test_profile_roundtrip_keeps_stable_multi_bus_references():
    cs = preview_production()
    loaded = deserialize_cue_set(serialize_cue_set(cs))
    assert loaded.profile == cs.profile
    assert loaded.cues[2].bus_ids == ["main", "effects"]
    assert [c.identifier for c in loaded.cues][1:3] == ["12.1", "12.10"]


def test_legacy_migration_preserves_gain_without_guessing_device():
    legacy = {"play_name": "Legacy", "master_level": .62, "cues": []}
    loaded = deserialize_cue_set(json.dumps(legacy))
    assert loaded.master_level == .62
    assert loaded.profile.buses[0].level == .62
    assert loaded.profile.primary_device is None
    assert "Legacy master preserved" in loaded.migration_notes[0]


@pytest.mark.parametrize("kind", ["no_main", "seven", "capacity", "overlap", "nan"])
def test_invalid_profile_detected(kind):
    p = ProductionProfile()
    if kind == "no_main":
        p.buses[0].id = "other"
    elif kind == "seven":
        p.buses += [OutputBus(id=str(i), channels=[i*2+3, i*2+4]) for i in range(6)]
    elif kind == "capacity":
        p.buses[0].channels = [2, 3]
    elif kind == "overlap":
        p.buses.append(OutputBus(id="other"))
    else:
        p.buses[0].level = float("nan")
    assert p.errors(capacity=2)


def test_profile_edit_cancel_and_removal_protection(qapp, monkeypatch):
    monkeypatch.setattr("bhs_player.ui.profile_dialog.list_output_devices", lambda: [])
    cs = preview_production()
    dlg = ProfileDialog(cs)
    dlg.table.item(0, 0).setText("Renamed Main")
    dlg.table.setCurrentCell(0, 0)
    dlg.remove_bus()
    assert dlg.table.rowCount() == 2
    dlg.table.setCurrentCell(1, 0)
    dlg.remove_bus()
    assert "assigned" in dlg.error.text()
    dlg.reject()
    assert cs.profile.buses[0].name == "Main"


def test_advanced_and_table_share_data_and_invalid_edits_are_atomic(qapp):
    cs = preview_production()
    cue = cs.cues[1]
    dlg = CueEditorDialog(cue, cs)
    dlg.name_edit.setText("Edited")
    for _, check in dlg.bus_checks:
        check.setChecked(True)
    dlg._on_accept()
    assert cue.bus_ids == ["main", "effects"]
    table = CueTable(cs, editable=True)
    assert "Main, Effects" in table.cellWidget(1, FIELDS.index("bus_ids")).currentText()
    assert table.commit(1, "name", "From table")
    next_editor = CueEditorDialog(cue, cs)
    assert next_editor.name_edit.text() == "From table"
    before = deepcopy(cue)
    next_editor.name_edit.setText("Do not apply")
    next_editor.start_spin.setValue(10)
    next_editor.end_spin.setValue(2)
    next_editor._on_accept()
    assert cue == before


def test_unavailable_multibus_never_opens_stream_or_confirms(session, monkeypatch):
    session.cue_set.profile.buses.append(OutputBus(id="other", channels=[3, 4]))
    opened = []
    monkeypatch.setattr(session.backend, "select_device", lambda _: opened.append(True))
    assert not session.play_test("main")
    assert not session.confirm("main")
    assert opened == []
    assert not session.audio.ready


def test_stereo_tester_requires_human_confirmation_and_resets_on_changes(session):
    pointer = session.engine.pointer
    states = [c.execution_state for c in session.cue_set.cues]
    assert not session.confirm("main")
    assert session.play_test("main")
    assert session.unconfirmed() == ["Main"]
    assert session.confirm("main")
    assert session.unconfirmed() == []
    assert "backup" not in session.confirmations
    assert session.engine.pointer == pointer
    assert [c.execution_state for c in session.cue_set.cues] == states
    assert all(getattr(i, "is_test", False) for i in session.audio.active_instances())
    session.cue_set.profile.buses[0].level = .5
    assert session.unconfirmed() == ["Main"]
    assert not session.audio.ready
    assert not session.confirm("main")


def test_tester_repeat_skip_stop_and_explicit_step(session, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    dlg = AudioTestDialog(session)
    dlg.play_again()
    assert dlg.path.currentData() == "main"
    first = session._test
    dlg.play_again()
    assert session._test is not first
    assert first.stopped
    dlg.confirm_audible()
    assert dlg.path.currentData() == "backup"
    assert "main" in session.confirmations
    dlg.skip_path()
    assert "backup" not in session.confirmations
    dlg.reject()
    assert not session.audio.active_instances()


def test_deliberate_switch_drops_sounds_preserves_independent_armed_cue(session):
    assert session.prepare()
    first, second = session.cue_set.cues
    first.advance_mode = AdvanceMode.ON_GO
    inst = session.audio.start(first, pcm=np.ones((500, 2), dtype=np.float32)*.1)
    session.engine.arm_cue(second.internal_id)
    assert session.prepare("backup")
    assert inst.stopped
    assert not session.audio.active_instances()
    assert session.engine.armed_cue is second
    assert session.route == "backup"
    assert session.prepare("primary")
    assert session.engine.armed_cue is second
    assert not session.audio.active_instances()


def test_output_loss_cancels_wait_and_old_completion_cannot_advance(session):
    assert session.prepare()
    cue = session.cue_set.cues[0]
    session.engine._waiting_on = cue.internal_id
    session.backend._handle_lost("device removed")
    QApplication.processEvents()
    assert not session.audio.ready
    assert session.engine.armed_cue is None
    assert session.engine.waiting_cue is None
    session.engine.notify_sound_finished(cue.internal_id, True)
    assert session.engine.armed_cue is None
    assert "AUDIO OUTPUT LOST" in session.message


def test_mode_exit_stops_and_disarms_reentry(session):
    assert session.prepare()
    win = MainWindow(session.cue_set, session.engine, session.audio, session.backend,
                     routing=session, rehearsal=True, confirm_close=False)
    inst = session.audio.start(session.cue_set.cues[0], pcm=np.ones((500, 2), dtype=np.float32)*.1)
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()
    assert inst.stopped
    assert session.engine.armed_cue is None
    assert session.backend.stream.running
    assert session.audio.ready  # prepared device pumps silence; no cue remains armed
    assert not np.any(session.audio.mixer.render_block(128))
    assert not hasattr(win, "master_slider")


def test_link_reconciliation_requires_explicit_retarget_or_confirmed_delete(qapp, monkeypatch):
    target, replacement = Cue("1.0"), Cue("2.0")
    stop = Cue("3.0", action=ActionType.STOP, target_internal_id=target.internal_id)
    cs = CueSet("Test", [target, replacement, stop])
    changes = []
    dlg = LinkedCuesDialog(cs, target, lambda: changes.append(True))
    dlg.retarget()
    assert stop.target_internal_id == replacement.internal_id
    assert cs.by_internal_id(target.internal_id) is target
    assert changes == [True]
    stop.target_internal_id = target.internal_id
    dlg.refresh()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Cancel)
    dlg.delete()
    assert stop in cs.cues
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    dlg.delete()
    assert stop not in cs.cues


def test_controller_show_saves_changes_rehearse_does_not(qapp, tmp_path, monkeypatch):
    cs = CueSet("Test", [Cue("1.0", action=ActionType.STOP_ALL)])
    folder = PlayFolder(tmp_path, "Test")
    folder.save_version(cs)
    c = ProductionController(cs, folder)
    monkeypatch.setattr(c.routing, "prepare", lambda route: c.audio.set_ready(True) or True)
    monkeypatch.setattr(c.routing, "unconfirmed", lambda: [])
    c.edit.list.commit(0, "notes", "Changed")
    c.enter_show(rehearsal=True)
    assert c.show_window.rehearsal
    assert len(folder.list_versions()) == 1
    c.show_window.close()
    assert c.engine.armed_cue is None
    c.enter_show()
    assert not c.show_window.rehearsal
    assert len(folder.list_versions()) == 2
    assert not c.edit.save_state.has_changes
    c.show_window.close()
    c.enter_show()
    assert len(folder.list_versions()) == 2
    c.show_window.close()


def test_failed_show_save_blocks_transition_and_retains_dirty(qapp, tmp_path, monkeypatch):
    cs = CueSet("Test", [Cue("1.0", action=ActionType.STOP_ALL)])
    folder = PlayFolder(tmp_path, "Test")
    folder.save_version(cs)
    c = ProductionController(cs, folder)
    monkeypatch.setattr(c.routing, "prepare", lambda route: c.audio.set_ready(True) or True)
    monkeypatch.setattr(c.routing, "unconfirmed", lambda: [])
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    c.edit.list.commit(0, "name", "Changed")
    def fail(*a):
        raise OSError("disk full")
    monkeypatch.setattr(folder, "save_version", fail)
    c.enter_show()
    assert c.show_window is None
    assert c.edit.save_state.has_changes
    assert "disk full" in c.edit.status_lbl.text()


def test_preview_is_silent_and_normal_trigger_protection_remains(qapp):
    c = ProductionController(preview_production(), preview=True)
    c.enter_show(rehearsal=True)
    win = c.show_window
    win.cue_list.setCurrentRow(1)
    win._arm_selected()
    win._go()
    assert not c.audio.active_instances()
    assert not win.go_btn.isEnabled()
    assert not c.routing.play_test("main")
    win.close()


def test_held_space_triggers_once_and_modal_blocks_go(session, monkeypatch):
    session.prepare()
    session.engine.arm_cue(session.cue_set.cues[0].internal_id)
    win = MainWindow(session.cue_set, session.engine, session.audio, confirm_close=False)
    calls = []
    monkeypatch.setattr(win, "_go", lambda: calls.append(True))
    press = lambda repeat=False: QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ", repeat)
    win.keyPressEvent(press())
    win.keyPressEvent(press(True))
    win.keyPressEvent(press())
    assert calls == [True]
    win.keyReleaseEvent(QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier))
    win.keyPressEvent(press())
    assert calls == [True, True]
    win.keyReleaseEvent(QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier))
    box = QMessageBox(win)
    box.setModal(True)
    box.show()
    QApplication.processEvents()
    win.keyPressEvent(press())
    assert calls == [True, True]
    box.close()
    win.close()


def test_zero_fade_completes_action_without_executing_next(session):
    target = session.cue_set.cues[0]
    fade = Cue("2.0", action=ActionType.FADE, target_internal_id=target.internal_id, fade_duration=0)
    next_cue = Cue("3.0", action=ActionType.STOP_ALL)
    session.cue_set.cues += [fade, next_cue]
    session.prepare()
    session.audio.start(target, pcm=np.ones((500, 2), dtype=np.float32)*.1)
    session.engine.arm_cue(fade.internal_id)
    assert session.engine.go().ok
    assert session.engine.armed_cue is next_cue
    assert not session.audio.active_instances()
    assert next_cue.execution_state.value == "armed"


def test_emergency_stop_cancels_pending_fade_without_advancing(session):
    target = session.cue_set.cues[0]
    fade = Cue("2.0", action=ActionType.FADE, target_internal_id=target.internal_id, fade_duration=3)
    session.cue_set.cues += [fade, Cue("3.0")]
    session.prepare()
    session.audio.start(target, pcm=np.ones((500, 2), dtype=np.float32)*.1)
    session.engine.arm_cue(fade.internal_id)
    assert session.engine.go().ok
    session.engine.stop_all()
    assert session.engine.armed_cue is None
    assert session.engine.waiting_cue is None
