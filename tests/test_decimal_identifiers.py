import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.model import Cue, CueSet, ActionType, identifier_key
from bhs_player.storage.store import serialize_cue_set, deserialize_cue_set
from bhs_player.ui.cue_table import CueTable
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.edit_window import EditWindow
from bhs_player.validate.check import validate_show


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('existing,entered', [
    ('12.1', '12.10'), ('12.10', '12.1'), ('12.1', '12.100'),
    ('12.0', '12.00'), ('12.1', '012.10'),
    ('12.1234567890123456789012345678901', '12.12345678901234567890123456789010'),
])
def test_decimal_spellings_are_distinct_text_ids(qapp, existing, entered):
    target, edited = Cue(existing), Cue('13.0')
    table = CueTable(CueSet('Show', [target, edited]), editable=True)
    errors = []
    changes = []
    table.editRejected.connect(errors.append)
    table.cueChanged.connect(lambda: changes.append(True))
    edited_id = edited.internal_id
    assert table.commit(1, 'identifier', entered)
    assert edited.identifier == entered
    assert edited.internal_id == edited_id
    assert table.item(1, 0).text() == entered
    assert errors == []
    assert changes == [True]
    table.close()


def test_exact_comparison_keeps_nearby_cue_numbers_distinct():
    a = '12.1234567890123456789012345678901'
    b = '12.1234567890123456789012345678902'
    assert identifier_key(a) != identifier_key(b)
    cs = CueSet('Show')
    cs.insert(Cue(a))
    cs.insert(Cue(b))
    assert cs.identifiers_unique()
    with pytest.raises(ValueError, match='already in use'):
        cs.insert(Cue(a))
    assert len(cs.cues) == 2


def test_same_cue_can_change_decimal_spelling(qapp):
    cue = Cue('12.1')
    table = CueTable(CueSet('Show', [cue]), editable=True)
    assert table.commit(0, 'identifier', '12.10')
    assert cue.identifier == '12.10'
    table.close()


def test_dialog_accepts_distinct_text_id(qapp):
    cue = Cue('13.0')
    cs = CueSet('Show', [Cue('12.1'), cue])
    dlg = CueEditorDialog(cue, cs)
    dlg.ident_edit.setText('12.10')
    dlg._on_accept()
    assert dlg.error_lbl.text() == ''
    assert cue.identifier == '12.10'
    assert dlg.result() == 1


def test_text_ids_roundtrip_and_exact_duplicates_can_be_repaired(qapp):
    cs = CueSet('Show', [Cue('12.1', action=ActionType.STOP_ALL),
                          Cue('12.10', action=ActionType.STOP_ALL)])
    loaded = deserialize_cue_set(serialize_cue_set(cs))
    assert validate_show(loaded).show_ready
    assert [c.identifier for c in loaded.cues] == ['12.1', '12.10']
    table = CueTable(loaded, editable=True)
    assert not table.commit(0, 'identifier', '12.10')
    assert table.commit(1, 'identifier', '12.11')
    table.close()


def test_automatic_number_preserves_text_identity(qapp, monkeypatch):
    cs = CueSet('Show', [Cue('12.2'), Cue('12.19')])
    win = EditWindow(cs, AudioEngine(Mixer()))
    monkeypatch.setattr(win.list, 'editItem', lambda *args: None)
    win._add_cue()
    # 12.20 and 12.2 are distinct text identifiers.
    assert cs.cues[-1].identifier == '12.20'
    assert cs.identifiers_unique()
