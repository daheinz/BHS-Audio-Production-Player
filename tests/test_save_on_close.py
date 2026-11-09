import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import Cue, CueSet, CueExecutionState
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.edit_window import EditWindow
from bhs_player.ui.main_window import MainWindow


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def setup_window(tmp_path):
    cs = CueSet('Show', [Cue('1.0', name='Original')])
    folder = PlayFolder(tmp_path, 'Show')
    folder.save_version(cs)
    audio = AudioEngine(Mixer())
    return EditWindow(cs, audio, folder), cs, folder, audio


def answer(monkeypatch, choice):
    seen = []
    def question(*args):
        seen.append(args)
        return choice
    monkeypatch.setattr(QMessageBox, 'question', question)
    return seen


def close_event(window):
    event = QCloseEvent()
    window.closeEvent(event)
    return event.isAccepted()


def test_clean_close_and_playback_changes_do_not_prompt(qapp, tmp_path, monkeypatch):
    win, cs, folder, _ = setup_window(tmp_path)
    cs.cues[0].execution_state = CueExecutionState.PLAYING
    seen = answer(monkeypatch, QMessageBox.Cancel)
    assert close_event(win)
    assert seen == []
    assert len(folder.list_versions()) == 1


def test_close_save_creates_version_and_clears_unsaved_state(qapp, tmp_path, monkeypatch):
    win, cs, folder, _ = setup_window(tmp_path)
    win.list.commit(0, 'name', 'New Name')
    assert folder.has_recovery()
    seen = answer(monkeypatch, QMessageBox.Save)
    assert close_event(win)
    assert len(seen) == 0
    assert len(folder.list_versions()) == 2
    assert folder.load_latest().cues[0].name == 'New Name'
    assert not folder.has_recovery()
    assert not win.save_state.has_changes
    assert close_event(win)
    assert len(seen) == 0


def test_exit_automatically_saves_profile_changes(qapp, tmp_path, monkeypatch):
    win, cs, folder, _ = setup_window(tmp_path)
    cs.profile.buses[0].level = .65
    win._mark_edited()
    seen = answer(monkeypatch, QMessageBox.Cancel)
    assert close_event(win)
    assert seen == []
    assert not folder.has_recovery()
    assert len(folder.list_versions()) == 2
    assert folder.load_latest().profile.buses[0].level == .65


def test_failed_save_prevents_close(qapp, tmp_path, monkeypatch):
    win, cs, folder, _ = setup_window(tmp_path)
    win.list.commit(0, 'notes', 'Unsaved')
    answer(monkeypatch, QMessageBox.Save)
    def fail(*args):
        raise OSError('Disk full')
    monkeypatch.setattr(folder, 'save_version', fail)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    assert not close_event(win)
    assert win.save_state.has_changes
    assert folder.has_recovery()
    assert 'Disk full' in warnings[0][2]


def test_show_save_updates_shared_baseline(qapp, tmp_path, monkeypatch):
    edit, cs, folder, audio = setup_window(tmp_path)
    edit.list.commit(0, 'notes', 'Edited')
    show = MainWindow(cs, CueEngine(cs, audio), audio, play_folder=folder,
                      save_state=edit.save_state, confirm_close=False)
    assert not hasattr(show, "master_slider")
    seen = answer(monkeypatch, QMessageBox.Cancel)
    assert close_event(show)  # Returning to Edit does not exit the app.
    assert seen == []
    assert edit.save_state.has_changes
    assert show._save_version()
    assert not edit.save_state.has_changes
    assert close_event(edit)
    assert seen == []
    assert folder.load_latest().cues[0].notes == "Edited"


def test_reverted_edit_does_not_prompt(qapp, tmp_path, monkeypatch):
    win, cs, folder, _ = setup_window(tmp_path)
    win.list.commit(0, 'name', 'Changed')
    win.list.commit(0, 'name', 'Original')
    seen = answer(monkeypatch, QMessageBox.Cancel)
    assert close_event(win)
    assert seen == []


def test_close_commits_open_inline_editor(qapp, tmp_path, monkeypatch):
    win, cs, folder, _ = setup_window(tmp_path)
    win.show()
    win.list.setCurrentCell(0, 1)
    win.list.editItem(win.list.item(0, 1))
    qapp.processEvents()
    editor = win.list.findChild(QLineEdit)
    assert editor is not None
    editor.setText('Pending Edit')
    editor.setFocus()
    answer(monkeypatch, QMessageBox.Save)
    assert win.close()
    assert folder.load_latest().cues[0].name == 'Pending Edit'
