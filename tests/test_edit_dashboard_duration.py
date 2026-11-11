"""Dashboard commands, responsive layout, derived duration, and window lifecycle."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
import soundfile as sf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from bhs_player.app import ProductionController,preview_production
from bhs_player.ui.cue_table import CueTable,FIELDS
from bhs_player.cues.model import Cue,CueSet,ActionType,AdvanceMode
from bhs_player.storage.store import serialize_cue_set


@pytest.mark.parametrize("editable,armable",[(True,False),(False,True),(False,False)])
def test_derived_duration_is_visible_readonly_and_does_not_change_storage(editable,armable,qtbot):
    cues=[Cue("1.0",start_position=2,end_position=12,fade_out=3),
          Cue("2.0",end_position=4,loop=True,advance_mode=AdvanceMode.ON_GO),
          Cue("3.0",action=ActionType.FADE,fade_duration=5),
          Cue("4.0",action=ActionType.STOP),Cue("5.0")]
    cues[2].target_internal_id=cues[0].internal_id
    cues[3].target_internal_id=cues[0].internal_id
    cs=CueSet("Duration",cues)
    before=serialize_cue_set(cs)
    table=CueTable(cs,editable=editable,armable=armable,defer_audio=True)
    qtbot.addWidget(table)
    col=FIELDS.index("duration")
    assert not table.isColumnHidden(col)
    assert [table.item(r,col).text() for r in range(5)]==["10.000s","4.000s / loop","5.000s","Immediate","Unassigned"]
    assert not table.item(0,col).flags() & Qt.ItemIsEditable
    assert not table.commit(0,"duration",123)
    assert serialize_cue_set(cs)==before
    cues[0].end_position=9
    table.rebuild()
    assert table.item(0,col).text()=="7.000s"


def test_untrimmed_duration_loads_asynchronously(tmp_path,qtbot,monkeypatch):
    from bhs_player.audio import safe_decode
    path=tmp_path/"duration.wav"
    sf.write(str(path),np.zeros((8000,2),dtype=np.float32),8000)
    def delayed(*a,**k):
        time.sleep(.15)
        return {"duration":1.0}
    monkeypatch.setattr(safe_decode,"inspect_audio",delayed)
    cue=Cue("1.0",audio_file=str(path),start_position=.25)
    started=time.monotonic()
    table=CueTable(CueSet("Async",[cue]),editable=True,defer_audio=True)
    qtbot.addWidget(table)
    assert time.monotonic()-started<.15
    col=FIELDS.index("duration")
    assert table.item(0,col).text()=="Checking..."
    qtbot.waitUntil(lambda:table.item(0,col).text()=="0.750s")
    assert cue.end_position is None


@pytest.mark.parametrize("rehearsal",[True,False])
def test_edit_hides_for_performance_and_returns_on_close(qtbot,rehearsal):
    controller=ProductionController(preview_production(),preview=True)
    qtbot.addWidget(controller.edit)
    controller.edit.show()
    controller.enter_show(rehearsal)
    qtbot.addWidget(controller.show_window)
    assert controller.edit.isHidden()
    assert controller.show_window.isVisible()
    assert not controller.show_window.cue_table.isColumnHidden(FIELDS.index("duration"))
    controller.show_window.close()
    assert controller.edit.isVisible() and controller.edit.isEnabled()


@pytest.mark.parametrize("width",[1500,1000])
def test_dashboard_reflows_and_has_no_duplicate_commands(qtbot,width):
    controller=ProductionController(preview_production(),preview=True)
    win=controller.edit
    qtbot.addWidget(win)
    win.resize(width,850)
    win.show()
    qtbot.wait(60)
    panels=win.dashboard.panels
    assert [p.title().replace("&&","&") for p in panels]==["System Status","Cue Controls","Project & Navigation"]
    for i,panel in enumerate(panels):
        assert panel.geometry().right()<=win.dashboard.width()
        for other in panels[i+1:]:
            assert not panel.geometry().intersects(other.geometry())
    assert len([b for b in win.findChildren(QPushButton) if b.text()=="Diagnostics / Logs"])==1
    assert len([b for b in win.findChildren(QPushButton) if b.text()=="Validate Show"])==1
    win.list.setCurrentRow(0)
    win._update_buttons()
    assert not win.up_btn.isEnabled()
    assert not win.stop_test_btn.isEnabled()
    win.list.setCurrentRow(win.list.rowCount()-1)
    win._update_buttons()
    assert not win.down_btn.isEnabled()
    assert win.show_btn.isVisible()
