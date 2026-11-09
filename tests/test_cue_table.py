import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication, QComboBox
from bhs_player.cues.model import Cue, CueSet, ActionType, AdvanceMode, OnGoBehavior
from bhs_player.ui.cue_table import CueTable, HEADERS, FIELDS, FIELD_HELP
from bhs_player.ui.theme import colors


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_inline_fields_and_validation(qapp):
    cue = Cue('12.10')
    table = CueTable(CueSet('Show', [cue]), editable=True)
    assert table.columnCount() == len(HEADERS) == 16
    assert isinstance(table.cellWidget(0, 2), QComboBox)
    table.item(0, 7).setText('65%')
    assert cue.volume == .65
    assert not table.commit(0, 'identifier', 'bad')
    assert cue.identifier == '12.10'
    assert not table.commit(0, 'loop', True)
    assert not cue.loop
    assert table.commit(0, 'advance_mode', AdvanceMode.ON_GO)
    table.item(0, 8).setCheckState(Qt.Checked)
    assert cue.loop
    assert table.commit(0, 'end_position', '10')
    assert not table.commit(0, 'start_position', '11')
    assert cue.start_position is None
    table.close()


def test_target_survives_renumber_and_action_change(qapp):
    play = Cue('1.0')
    stop = Cue('2.0', action=ActionType.STOP)
    cs = CueSet('Show', [play, stop])
    table = CueTable(cs, editable=True)
    table.cellWidget(1, 11).setCurrentIndex(1)
    assert stop.target_internal_id == play.internal_id
    table.commit(0, 'identifier', '12.10')
    assert '12.10' in table.cellWidget(1, 11).currentText()
    assert not table.item(1, 7).flags() & Qt.ItemIsEditable
    table.close()


def test_show_highlights_do_not_mutate_cues(qapp):
    cues = [Cue('1.0'), Cue('2.0')]
    table = CueTable(CueSet('Show', cues))
    table.highlight({cues[0].internal_id}, cues[1].internal_id)
    assert table.item(0, 0).background().color().name() == colors()['playing']
    assert table.item(1, 0).background().color().name() == colors()['armed']
    assert all(c.action is ActionType.PLAY for c in cues)
    assert not table.item(0, 1).flags() & Qt.ItemIsEditable
    table.close()


def test_edit_audio_cell_opens_picker_and_imports(qapp, tmp_path, monkeypatch):
    from bhs_player.storage.store import PlayFolder
    folder = PlayFolder(tmp_path / 'production', 'Show')
    folder.ensure()
    source = tmp_path / 'sound.wav'
    source.write_bytes(b'audio file')
    cue = Cue('1.0')
    table = CueTable(CueSet('Show', [cue]), editable=True, play_folder=folder)
    picked = []
    def picker(*args):
        picked.append(args)
        return str(source), ''
    monkeypatch.setattr('bhs_player.ui.cue_table.QFileDialog.getOpenFileName', picker)
    table.editItem(table.item(0, 3))
    assert len(picked) == 1
    assert cue.audio_file and not os.path.isabs(cue.audio_file)
    assert (folder.folder / cue.audio_file).read_bytes() == b'audio file'
    assert table.item(0, 3).text() == cue.audio_file
    table.close()


def test_audio_picker_full_path_and_cancel(qapp, tmp_path, monkeypatch):
    cue = Cue('1.0')
    table = CueTable(CueSet('Show', [cue]), editable=True)
    source = tmp_path / 'sound.wav'
    monkeypatch.setattr('bhs_player.ui.cue_table.QFileDialog.getOpenFileName', lambda *args: (str(source), ''))
    assert table.browse_audio(0)
    assert cue.audio_file == str(source).replace('\\', '/')
    monkeypatch.setattr('bhs_player.ui.cue_table.QFileDialog.getOpenFileName', lambda *args: ('', ''))
    assert not table.browse_audio(0)
    assert cue.audio_file == str(source).replace('\\', '/')
    table.close()


def test_dropdowns_survive_repeated_edits_and_teardown(qapp):
    cue = Cue('1.0')
    table = CueTable(CueSet('Show', [cue]), editable=True)
    for index in (1, 0, 1, 0):
        old = table.cellWidget(0, 5)
        old.setCurrentIndex(index)
        # A replaced widget must not overwrite the cue during deferred deletion.
        old.setCurrentIndex(-1)
        qapp.processEvents()
        assert cue.advance_mode is (AdvanceMode.ON_GO if index else AdvanceMode.ON_COMPLETE)
        for col in (5, 6, 11):
            assert isinstance(table.cellWidget(0, col), QComboBox)
            assert table.cellWidget(0, col).currentIndex() >= 0 if col != 11 else table.cellWidget(0, col).currentIndex() == -1
    assert cue.on_go_behavior is OnGoBehavior.ADD_TO_STACK
    assert not table.cellWidget(0, 11).isEnabled()
    table.close()


def test_dropdown_defaults_and_nearest_target(qapp):
    first, nearest = Cue('1.0'), Cue('2.0')
    stop = Cue('3.0', action=ActionType.STOP)
    empty = Cue('4.0', advance_mode=None, on_go_behavior=None)
    table = CueTable(CueSet('Show', [first, nearest, stop, empty]), editable=True)
    assert stop.target_internal_id == nearest.internal_id
    assert table.cellWidget(2, 11).currentData() == nearest.internal_id
    assert not table.cellWidget(2, 5).isEnabled()
    assert empty.advance_mode is AdvanceMode.ON_COMPLETE
    assert empty.on_go_behavior is OnGoBehavior.ADD_TO_STACK
    table.cellWidget(3, 2).setCurrentIndex(2)  # Fade
    assert empty.target_internal_id == nearest.internal_id
    assert table.cellWidget(3, 11).isEnabled()
    assert table.cellWidget(3, 11).currentData() == nearest.internal_id
    table.close()


def test_target_default_fallback_and_missing_reference(qapp):
    stop = Cue('1.0', action=ActionType.STOP)
    play = Cue('2.0')
    missing = Cue('3.0', action=ActionType.FADE, target_internal_id='removed')
    table = CueTable(CueSet('Show', [stop, play, missing]), editable=True)
    assert stop.target_internal_id == play.internal_id
    assert missing.target_internal_id == 'removed'
    assert table.cellWidget(2, 11).currentText() == '(missing target)'
    table.close()


@pytest.mark.parametrize('editable', [False, True])
def test_help_is_specific_to_each_header_cell_and_dropdown(qapp, editable):
    cue = Cue('12.10', name='Rain', notes='After the line', loop=True,
              advance_mode=AdvanceMode.ON_GO)
    table = CueTable(CueSet('Show', [cue]), editable=editable)
    for col, field in enumerate(FIELDS):
        assert table.horizontalHeaderItem(col).toolTip() == FIELD_HELP[field]
        tip = table.item(0, col).toolTip()
        assert FIELD_HELP[field] in tip
        for other in FIELDS:
            if other != field:
                assert FIELD_HELP[other] not in tip
        widget = table.cellWidget(0, col)
        if widget is not None:
            assert widget.toolTip() == tip
    before = table.item(0, 0).toolTip()
    table.highlight({cue.internal_id}, cue.internal_id)
    assert table.item(0, 0).toolTip() == before
    table.close()


def test_widths_saved_to_ini_restored_between_modes_and_rebuilds(qapp, tmp_path):
    path = tmp_path / 'preferences' / 'settings.ini'
    cs = CueSet('Show', [Cue('1.0')])
    edit = CueTable(cs, editable=True, settings=QSettings(str(path), QSettings.IniFormat))
    edit.setColumnWidth(4, 456)
    assert path.exists()
    saved = QSettings(str(path), QSettings.IniFormat)
    assert int(saved.value('cue_table/widths/notes')) == 456
    show = CueTable(cs, settings=saved)
    assert show.columnWidth(4) == 456
    show.setColumnWidth(4, 321)
    edit.rebuild()
    assert edit.columnWidth(4) == 321
    assert cs.cues[0].notes == ''
    edit.close()
    show.close()


def test_invalid_saved_width_uses_default(qapp, tmp_path):
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    settings.setValue('cue_table/widths/notes', 'bad')
    settings.setValue('cue_table/widths/audio_file', -20)
    table = CueTable(CueSet('Show'), settings=settings)
    assert table.columnWidth(4) == 300
    assert table.columnWidth(3) == 230
    table.close()


def write_sound(path, seconds):
    import numpy as np
    import soundfile as sf
    sr = 8000
    sf.write(str(path), np.zeros((int(seconds * sr), 2)), sr)


def test_sound_selection_populates_full_end_and_persists(qapp, tmp_path, monkeypatch):
    from bhs_player.storage.store import PlayFolder
    folder = PlayFolder(tmp_path / 'plays', 'Show')
    folder.ensure()
    sound = tmp_path / 'sound.wav'
    write_sound(sound, 2.375)
    cue = Cue('1.0', start_position=1, end_position=1.5)
    cs = CueSet('Show', [cue])
    table = CueTable(cs, editable=True, play_folder=folder)
    monkeypatch.setattr('bhs_player.ui.cue_table.QFileDialog.getOpenFileName', lambda *args: (str(sound), ''))
    assert table.browse_audio(0)
    assert cue.end_position == 2.375
    assert cue.start_position == 1
    assert table.item(0, 10).text() == '2.38'
    folder.save_version(cs)
    assert folder.load_latest().cues[0].end_position == 2.375
    # A manual trim survives opening the production again.
    table.commit(0, 'end_position', '2')
    folder.save_version(cs)
    loaded = folder.load_latest()
    reopened = CueTable(loaded, editable=True, play_folder=folder)
    assert loaded.cues[0].end_position == 2
    table.close()
    reopened.close()


def test_loaded_sound_fills_unset_end_and_shorter_replacement_resets_start(qapp, tmp_path):
    sound = tmp_path / 'sound.wav'
    write_sound(sound, 2.5)
    cue = Cue('1.0', audio_file=str(sound))
    table = CueTable(CueSet('Show', [cue]), editable=True)
    assert cue.end_position == 2.5
    assert table.commit(0, 'start_position', '2')
    short = tmp_path / 'short.wav'
    write_sound(short, 1)
    assert table.commit(0, 'audio_file', str(short))
    assert cue.end_position == 1
    assert cue.start_position is None
    table.close()


def test_unreadable_sound_reports_length_problem_without_using_previous_end(qapp, tmp_path):
    cue = Cue('1.0', end_position=10)
    table = CueTable(CueSet('Show', [cue]), editable=True)
    errors = []
    table.editRejected.connect(errors.append)
    assert table.commit(0, 'audio_file', str(tmp_path / 'missing.wav'))
    assert cue.end_position is None
    assert 'length could not be read' in errors[-1]
    table.close()
