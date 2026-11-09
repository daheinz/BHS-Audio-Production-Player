import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import asdict
from PySide6.QtCore import Qt, QMimeData, QPointF, QPoint, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMouseEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from bhs_player.cues.model import Cue, CueSet, ActionType
from bhs_player.ui.cue_table import CueTable
from bhs_player.ui.cue_drag import MIME_TYPE, CueDragHeader
from bhs_player.ui.theme import colors
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.storage.store import PlayFolder, serialize_cue_set, deserialize_cue_set
from bhs_player.ui.edit_window import EditWindow


def test_adjacent_reversals_highlight_only_both_id_cells(qapp):
    cs = CueSet('Order', [Cue(i) for i in ['1.0', '1.2', '1.1', '1.3']])
    table = CueTable(cs, editable=True)
    assert table.out_of_order_ids() == {cs.cues[1].internal_id, cs.cues[2].internal_id}
    for row in range(4):
        assert ('Out of numeric order' in table.item(row, 0).toolTip()) == (row in (1, 2))
        assert table.item(row, 1).background().color().name() == colors()['idle']
    assert table.commit(1, 'identifier', '1.01')
    assert not table.out_of_order_ids()
    assert 'Out of numeric order' not in table.item(2, 0).toolTip()


def test_numeric_comparison_not_text_sort_and_equal_values_not_flagged(qapp):
    cs = CueSet('Order', [Cue(i) for i in ['2.0', '10.0', '12.1', '12.10', 'invalid']])
    table = CueTable(cs, editable=True)
    assert not table.out_of_order_ids()
    cs.cues = [Cue(i) for i in ['3.0', '2.0', '1.0']]
    table.rebuild()
    assert len(table.out_of_order_ids()) == 3


def test_move_preserves_identity_targets_settings_selection_and_noop(qapp):
    first, second = Cue('1.0', volume=.4), Cue('2.0')
    linked = Cue('3.0', action=ActionType.FADE, target_internal_id=first.internal_id)
    cs = CueSet('Order', [first, second, linked])
    before = {c.internal_id: asdict(c) for c in cs.cues}
    table = CueTable(cs, editable=True)
    before = {c.internal_id: asdict(c) for c in cs.cues}
    changes = []
    table.cueChanged.connect(lambda: changes.append(True))
    assert table.move_cue_to_boundary(first.internal_id, 3)
    assert cs.cues == [second, linked, first]
    assert table.currentRow() == 2
    assert not table.move_cue_to_boundary(first.internal_id, 3)
    assert table.move_cue_to_boundary(first.internal_id, 0)
    assert {c.internal_id: asdict(c) for c in cs.cues} == before
    assert changes == [True, True]
    restored = deserialize_cue_set(serialize_cue_set(cs))
    assert restored.cues[2].target_internal_id == first.internal_id
    show = CueTable(cs)
    assert show.verticalHeader().isHidden()
    assert not show.move_cue_to_boundary(first.internal_id, 3)


def test_drop_event_uses_stable_id_and_rejects_other_table(qapp):
    cs = CueSet('Order', [Cue('1.0'), Cue('2.0'), Cue('3.0')])
    first = cs.cues[0]
    table = CueTable(cs, editable=True)
    table.resize(600, 300)
    table.show()
    qapp.processEvents()
    mime = QMimeData()
    mime.setData(MIME_TYPE, (table._drag_token+':'+first.internal_id).encode())
    position = QPoint(10, table.rowViewportPosition(2)+table.rowHeight(2)-2)
    enter = QDragEnterEvent(position, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(table.viewport(), enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(position), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(table.viewport(), drop)
    assert drop.isAccepted()
    assert cs.cues[-1] is first
    assert table.currentRow() == 2
    other = CueTable(cs, editable=True)
    assert other._dragged_cue(drop) is None
    table.hide()


def test_drag_reorder_marks_recovery_and_dirty(qapp, tmp_path):
    cs = CueSet('Order', [Cue('1.0'), Cue('2.0')])
    folder = PlayFolder(tmp_path, 'Order')
    folder.save_version(cs)
    win = EditWindow(cs, AudioEngine(Mixer()), folder)
    assert not win.save_state.has_changes
    assert win.list.move_cue_to_boundary(cs.cues[0].internal_id, 2)
    assert win.save_state.has_changes
    assert folder.has_recovery()
    assert [c.identifier for c in folder.load_recovery().cues] == ['2.0', '1.0']


def test_handle_starts_drag_with_stable_cue_id(qapp, monkeypatch):
    cs = CueSet('Order', [Cue('1.0'), Cue('2.0')])
    table = CueTable(cs, editable=True)
    table.resize(600,300)
    table.show()
    qapp.processEvents()
    records=[]
    class Drag:
        def __init__(self, source):
            records.append(self)
            self.source=source
        def setMimeData(self, data):
            self.data=data
        def setPixmap(self, pixmap):
            pass
        def exec(self, action):
            return action
    monkeypatch.setattr('bhs_player.ui.cue_drag.QDrag', Drag)
    header=table.verticalHeader()
    start=QPointF(12,table.rowViewportPosition(0)+20)
    press=QMouseEvent(QEvent.MouseButtonPress,start,start,Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
    header.mousePressEvent(press)
    end=start+QPointF(0,30)
    move=QMouseEvent(QEvent.MouseMove,end,end,Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
    header.mouseMoveEvent(move)
    assert len(records) == 1
    assert bytes(records[0].data.data(MIME_TYPE)).decode().endswith(':'+cs.cues[0].internal_id)
    table.hide()
