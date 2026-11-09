"""Render isolated GUI preview screens without accessing an audio device."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase, QFont
from bhs_player.app import ProductionController, preview_production
from bhs_player.ui.theme import ViewingMode
from bhs_player.ui.profile_dialog import ProfileDialog
from bhs_player.ui.cue_editor_dialog import CueEditorDialog
from bhs_player.ui.audio_test_dialog import AudioTestDialog
from bhs_player.ui.linked_cues_dialog import LinkedCuesDialog
import bhs_player.ui.cue_table as tables

out = Path("output/gui-review")
out.mkdir(parents=True, exist_ok=True)
tables.application_settings = lambda: QSettings(str(out / "preview-settings.ini"), QSettings.IniFormat)
app = QApplication([])
for font in ("segoeui.ttf", "segoeuib.ttf"):
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font)
app.setFont(QFont("Segoe UI", 10))
app.setStyle("Fusion")
app.viewing_mode = ViewingMode(app, QSettings(str(out / "preview-settings.ini"), QSettings.IniFormat))
app.viewing_mode.apply("light" if "--light" in sys.argv else "dark", persist=False)
controller = ProductionController(preview_production(), preview=True)
controller.edit.list.setCurrentRow(0)

def capture(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / (name + ".png")))
    widget.hide()

capture(controller.edit, "edit")
capture(ProfileDialog(controller.cue_set), "profile")
capture(CueEditorDialog(controller.cue_set.cues[0], controller.cue_set), "advanced")
capture(AudioTestDialog(controller.routing), "audio-test")
capture(LinkedCuesDialog(controller.cue_set, controller.cue_set.cues[0], lambda: None), "linked-cues")
controller.enter_show(rehearsal=True)
capture(controller.show_window, "rehearse")
controller.show_window.close()
print("Rendered Edit, Profile, Advanced, Audio Test, Linked Cues, and Rehearse to", out)
