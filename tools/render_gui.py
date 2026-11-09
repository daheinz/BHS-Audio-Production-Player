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
controller.edit.list.setCurrentRow(1)

def capture(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / (name + ".png")))
    widget.hide()

capture(controller.edit, "edit")
capture(ProfileDialog(controller.cue_set), "profile")
capture(CueEditorDialog(controller.cue_set.cues[1], controller.cue_set), "advanced")
controller.edit.list.setCurrentRow(3)
capture(controller.edit, "fade-envelope")
controller.edit.list.setCurrentRow(1)
capture(AudioTestDialog(controller.routing), "audio-test")
capture(LinkedCuesDialog(controller.cue_set, controller.cue_set.cues[0], lambda: None), "linked-cues")
controller.enter_show(rehearsal=True)
capture(controller.show_window, "rehearse")
controller.show_window.close()
print("Rendered Edit, Profile, Advanced, FADE envelope, Audio Test, Linked Cues, and Rehearse to", out)


# Explicit offline layout example: real mixer instances, no output backend.
import numpy as np
from PySide6.QtWidgets import QLabel
from bhs_player.cues.model import Cue, CueSet, ActionType, AdvanceMode
from bhs_player.cues.engine import CueEngine
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.ui.main_window import MainWindow
engine_cue = Cue("2.0", "Steam engine ambience", loop=True, advance_mode=AdvanceMode.ON_GO)
music_cue = Cue("3.0", "Music underneath", advance_mode=AdvanceMode.ON_GO)
fade_cue = Cue("4.0", "Fade music", action=ActionType.FADE, target_internal_id=music_cue.internal_id, fade_duration=3)
stack_set = CueSet("Playing Stack example", [engine_cue, music_cue, fade_cue])
stack_audio = AudioEngine(Mixer(), ready=False)
stack_engine = CueEngine(stack_set, stack_audio)
sample_time = np.arange(44100*8)/44100
sample_pcm = (.12*np.sin(2*np.pi*220*sample_time)).astype(np.float32)
stereo = np.stack([sample_pcm, sample_pcm], axis=1)
stack_audio.start(engine_cue, pcm=stereo)
stack_audio.start(music_cue, pcm=stereo)
stack_audio.mixer.render_block(4096)
stack_engine.arm_cue(fade_cue.internal_id)
stack_win = MainWindow(stack_set, stack_engine, stack_audio, confirm_close=False)
stack_win.centralWidget().layout().insertWidget(0, QLabel("OFFLINE LAYOUT EXAMPLE — NO AUDIO DEVICE IS OPEN"))
stack_win.cue_list.setCurrentRow(1)  # selection is independent of armed FADE
capture(stack_win, "playing-stack")
stack_win.resize(1000, 700)
capture(stack_win, "playing-stack-small")
stack_win.close()
print("Rendered playing-stack.png with two explicitly offline playback cards.")


# Regression example: GO on End keeps its successor genuinely armed.
auto_source = Cue("7.0", "Thunder", advance_mode=AdvanceMode.ON_COMPLETE_GO)
auto_next = Cue("8.0", "Doorbell", advance_mode=AdvanceMode.ON_GO)
auto_set = CueSet("GO on End example", [auto_source, auto_next])
auto_audio = AudioEngine(Mixer())
auto_start = auto_audio.start
auto_audio.start = lambda cue: auto_start(cue, pcm=stereo)
auto_engine = CueEngine(auto_set, auto_audio)
auto_engine.go()
auto_audio.mixer.render_block(4096)
auto_audio.set_ready(False)  # No output endpoint; controls remain disabled in image.
auto_win = MainWindow(auto_set, auto_engine, auto_audio, rehearsal=True, confirm_close=False)
auto_win.centralWidget().layout().insertWidget(0, QLabel("OFFLINE LAYOUT EXAMPLE - NO AUDIO DEVICE IS OPEN"))
capture(auto_win, "go-on-end-armed")
auto_win.close()


# Explicit simulated health states; no stream or output device is created.
from dataclasses import replace
from types import SimpleNamespace
from bhs_player.audio.health import HealthSnapshot
from bhs_player.ui.audio_health import AudioHealthPanel, DiagnosticsDialog
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
import time
health_example = QWidget()
health_layout = QVBoxLayout(health_example)
health_layout.addWidget(QLabel("SIMULATED AUDIO HEALTH EXAMPLES - NO OUTPUT DEVICE"))
health_row = QHBoxLayout()
normal = HealthSnapshot(True, .2, .3, 0, 0, 0, 100, 0, 0, 0, 44100, 1024, .1)
for state in (normal, replace(normal, load=.8), replace(normal, underflows=2, last_underflow=time.monotonic())):
    fake_backend = SimpleNamespace(poll_diagnostics=lambda s=state: s,
                                   output_lost=False, output_lost_reason="")
    health_row.addWidget(AudioHealthPanel(backend=fake_backend))
health_layout.addLayout(health_row)
capture(health_example, "audio-health-example")
import tempfile
from bhs_player import diagnostics
with tempfile.TemporaryDirectory() as logs:
    diagnostics.configure_logging(logs)
    diagnostics.LOGGER.warning("OFFLINE RENDER EXAMPLE: troubleshooting log viewer")
    diagnostics.shutdown_logging()
    capture(DiagnosticsDialog(), "diagnostics-logs")
    diagnostics.shutdown_logging()
