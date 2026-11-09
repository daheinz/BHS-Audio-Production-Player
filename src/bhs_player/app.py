"""Application entry point. Use --gui-preview for isolated, silent layout review."""
from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from .audio.engine import AudioEngine, Mixer
from .audio.stream import StreamingAudioBackend
from .audio.routing import RoutingSession
from .cues.engine import CueEngine
from .cues.model import CueSet, Cue, ActionType, AdvanceMode
from .ui.device_dialog import DeviceDialog
from .ui.edit_window import EditWindow
from .ui.main_window import MainWindow
from .ui.open_play_dialog import OpenPlayDialog
from .validate.check import validate_show

DEFAULT_PLAYS_ROOT = Path("Plays")

from .ui.theme import stylesheet, viewing_mode

STYLE = stylesheet("dark")



def build_app(cue_set, audio=None, backend=None):
    app = QApplication.instance() or QApplication(sys.argv)
    viewing_mode()
    audio = audio or AudioEngine(Mixer(), ready=False)
    backend = backend or StreamingAudioBackend(audio)
    engine = CueEngine(cue_set, audio)
    return app, MainWindow(cue_set, engine, audio, backend)


def select_output(win):
    dlg = DeviceDialog(win, reason="Select an output deliberately.")
    if not dlg.exec() or dlg.selected_device() is None:
        return False
    return win.backend.select_device(dlg.selected_device().index) if win.backend else False


def open_play(plays_root, parent=None):
    dlg = OpenPlayDialog(plays_root, parent)
    if dlg.exec() and dlg.result_cue_set is not None:
        return dlg.result_cue_set, dlg.result_play_folder, dlg.result_version_name
    return None


def pre_show_gate(win, cue_set, play_folder, version_name):
    report = validate_show(cue_set, play_folder=play_folder.folder if play_folder else None,
                           output_device_available=win.audio.ready)
    if report.critical:
        QMessageBox.warning(win, "Cannot Enter — Review in Edit", "\n".join(f"{i.cue_identifier or 'Production'}: {i.message}" for i in report.critical))
        return False
    return True


class ProductionController:
    """One state owner for editing, Show, Rehearse, and output routing."""
    def __init__(self, cue_set, folder=None, version_name="", preview=False):
        self.cue_set, self.folder, self.version_name, self.preview = cue_set, folder, version_name, preview
        self.audio = AudioEngine(Mixer(), ready=False, base_path=folder.folder if folder else None)
        self.backend = StreamingAudioBackend(self.audio)
        self.engine = CueEngine(cue_set, self.audio)
        self.engine.interrupt_output(disarm=True)
        self.routing = RoutingSession(cue_set, self.audio, self.backend, self.engine)
        self.routing.preview = preview
        self.edit = EditWindow(cue_set, self.audio, folder, routing=self.routing)
        self.edit.save_state.force_unsaved = version_name == "(recovery)"
        self.edit.enter_show = self.enter_show
        self.show_window = None
        if preview:
            self.edit.setWindowTitle("GUI PREVIEW — isolated sample, no audio")
            self.edit.routing_notice.setText("GUI PREVIEW: sample data only. Audio, permanent saving, and show readiness are disabled.")
            self.edit.save_state.mark_saved()
            self.edit._save = lambda: True

    def enter_show(self, rehearsal=False):
        if self.show_window is not None:
            self.show_window.raise_()
            return
        self.edit.list.setFocus()
        self.edit._stop_audition()
        self.routing.stop_test()
        if not self.preview:
            if not self.routing.prepare("primary"):
                QMessageBox.warning(self.edit, "Output Not Ready", self.routing.message)
                return
            report = validate_show(self.cue_set, self.folder.folder if self.folder else None,
                                   output_device_available=self.audio.ready)
            if report.critical:
                QMessageBox.warning(self.edit, "Cannot Enter — Review in Edit", "\n".join(f"{i.cue_identifier or 'Production'}: {i.message}" for i in report.critical))
                return
            if not rehearsal and self.routing.unconfirmed():
                box = QMessageBox(self.edit)
                box.setWindowTitle("Audio Not Confirmed at Board")
                box.setText("Unconfirmed buses: " + ", ".join(self.routing.unconfirmed()) + ". Run the test, or enter with visible warnings.")
                test = box.addButton("Run Test", QMessageBox.ActionRole)
                proceed = box.addButton("Enter Without Testing", QMessageBox.AcceptRole)
                box.addButton(QMessageBox.Cancel)
                box.exec()
                if box.clickedButton() is test:
                    self.edit._audio_test()
                    return
                if box.clickedButton() is not proceed:
                    return
            if not rehearsal and not self.edit._save():
                QMessageBox.warning(self.edit, "Save Required", self.edit.status_lbl.text())
                return
            if rehearsal and self.edit.save_state.has_changes and self.folder:
                try:
                    self.folder.save_recovery(self.cue_set)
                except OSError as exc:
                    QMessageBox.warning(self.edit, "Recovery Save Failed", str(exc))
                    return
        self.engine.interrupt_output(disarm=True)
        version = self.folder.latest_version().name if self.folder and self.folder.latest_version() else self.version_name
        win = MainWindow(self.cue_set, self.engine, self.audio, self.backend,
                         play_folder=self.folder, version_name=version,
                         save_state=self.edit.save_state, confirm_close=False,
                         routing=self.routing, rehearsal=rehearsal, preview=self.preview)
        self.show_window = win
        win.setAttribute(Qt.WA_DeleteOnClose)
        win.returnedToEdit.connect(self.return_to_edit)
        self.edit.setEnabled(False)
        win.show()

    def return_to_edit(self):
        self.show_window = None
        self.edit.setEnabled(True)
        self.edit._rebuild()
        self.edit._refresh_profile()
        self.edit.show()
        self.edit.raise_()


def preview_production():
    from .profiles import OutputBus
    cs = CueSet("Theatre — GUI Preview")
    cs.profile.name = "Sample theatre profile (not connected)"
    cs.profile.buses.append(OutputBus(id="effects", name="Effects", channels=[3, 4], board_input="Board 3 / 4"))
    cs.profile.buses[0].board_input = "Board 1 / 2"
    rain = Cue("12.0", "Rain outside", loop=True, advance_mode=AdvanceMode.ON_GO,
               notes="Stand by as the lights fade. Background continues under dialogue.")
    bell = Cue("12.1", "Doorbell", bus_ids=["effects"])
    thunder = Cue("12.10", "Thunder", bus_ids=["main", "effects"])
    fade = Cue("13.0", "Fade rain", action=ActionType.FADE, target_internal_id=rain.internal_id, fade_duration=3)
    cs.cues = [rain, bell, thunder, fade]
    return cs


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    viewing_mode()
    preview = "--gui-preview" in sys.argv
    created = False
    if preview:
        cs, folder, version = preview_production(), None, "sample only"
    else:
        dlg = OpenPlayDialog(DEFAULT_PLAYS_ROOT)
        if not dlg.exec() or dlg.result_cue_set is None:
            return 0
        cs, folder, version = dlg.result_cue_set, dlg.result_play_folder, dlg.result_version_name
        created = dlg.created_new
    controller = ProductionController(cs, folder, version, preview)
    controller.edit.show()
    if created:
        controller.edit._audio_test()
    app.aboutToQuit.connect(controller.backend.stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
