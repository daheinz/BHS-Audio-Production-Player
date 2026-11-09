"""Viewing preferences persist independently and update active cue views safely."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import asdict
import pytest
from PySide6.QtCore import QSettings, Qt, QEvent, QCoreApplication
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
from bhs_player.ui.theme import ViewingMode, ViewingModeControl, COLORS
from bhs_player.ui.cue_table import CueTable, FIELDS
from bhs_player.cues.model import Cue, CueSet


@pytest.fixture
def display(tmp_path):
    app = QApplication.instance() or QApplication([])
    # Earlier legacy UI tests leave parentless windows/timers alive. Isolate live theme tests.
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    previous = getattr(app, "viewing_mode", None)
    settings = QSettings(str(tmp_path / "display.ini"), QSettings.IniFormat)
    manager = ViewingMode(app, settings)
    app.viewing_mode = manager
    yield app, manager, settings
    if previous is not None:
        app.viewing_mode = previous
        previous.apply(previous.mode, persist=False)
    else:
        manager.apply("dark", persist=False)


def test_dark_is_default_and_invalid_saved_value_falls_back(display):
    app, manager, settings = display
    assert manager.mode == "dark"
    assert app.palette().color(QPalette.Window).name() == COLORS['dark']['window']
    assert app.testAttribute(Qt.AA_DontUseNativeDialogs)
    settings.setValue("display/viewing_mode", "invalid")
    assert ViewingMode(app, settings).mode == "dark"


def test_selector_switch_is_immediate_persistent_and_synchronized(display):
    app, manager, settings = display
    first, second = ViewingModeControl(), ViewingModeControl()
    first.combo.setCurrentIndex(first.combo.findData("light"))
    assert manager.mode == "light"
    assert second.combo.currentData() == "light"
    reloaded = QSettings(settings.fileName(), QSettings.IniFormat)
    assert ViewingMode(app, reloaded).mode == "light"
    first.combo.setCurrentIndex(first.combo.findData("dark"))
    assert second.combo.currentData() == "dark"
    assert settings.value("display/viewing_mode") == "dark"


def test_switch_retains_selection_highlights_and_production_data(display):
    app, manager, settings = display
    cs = CueSet("Test", [Cue("1.0"), Cue("2.0")])
    table = CueTable(cs, editable=True, settings=settings)
    table.setCurrentCell(1, 1)
    table.highlight({cs.cues[0].internal_id}, cs.cues[1].internal_id)
    before = asdict(cs)
    changes = []
    table.cueChanged.connect(lambda: changes.append(True))
    for mode in ("light", "dark"):
        manager.apply(mode)
        assert table.currentRow() == 1
        assert table.item(0, 0).background().color().name() == COLORS[mode]['playing']
        assert table.item(1, 0).background().color().name() == COLORS[mode]['armed']
        assert COLORS[mode]['on_complete'] in table.cellWidget(0, FIELDS.index('advance_mode')).styleSheet()
        assert asdict(cs) == before
    assert changes == []
    table.close()
