"""Application entry point. Use --gui-preview for isolated, silent layout review."""
from __future__ import annotations
import sys
import argparse
import logging
from .diagnostics import configure_logging, shutdown_logging

log = logging.getLogger("bhs_player.app")
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QObject, Slot, QThreadPool
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
    audio = audio or AudioEngine(Mixer(), ready=False, nonblocking=True)
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


class ProductionController(QObject):
    """One state owner for editing, Show, Rehearse, and output routing."""
    def __init__(self, cue_set, folder=None, version_name="", preview=False):
        super().__init__()
        self._entry_check = None
        self._entry_report = None
        self.cue_set, self.folder, self.version_name, self.preview = cue_set, folder, version_name, preview
        self.audio = AudioEngine(Mixer(), ready=False, base_path=folder.folder if folder else None, nonblocking=True)
        self.backend = StreamingAudioBackend(self.audio)
        self.engine = CueEngine(cue_set, self.audio)
        self.engine.reset_session()
        self.routing = RoutingSession(cue_set, self.audio, self.backend, self.engine)
        self.routing.preview = preview
        self.edit = EditWindow(cue_set, self.audio, folder, routing=self.routing)
        self.edit.save_state.force_unsaved = version_name == "(recovery)"
        self.edit.enter_show = self.enter_show
        self.show_window = None
        self.diagnostics_timer = QTimer(self.edit)
        self.diagnostics_timer.setInterval(1000)
        self.diagnostics_timer.timeout.connect(self.backend.poll_diagnostics)
        self.diagnostics_timer.start()
        log.info("PRODUCTION OPEN name=%r version=%r preview=%s", cue_set.play_name, version_name, preview)
        if preview:
            self.edit.setWindowTitle("GUI PREVIEW — isolated sample, no audio")
            self.edit.routing_notice.setText("GUI PREVIEW: sample data only. Audio, permanent saving, and show readiness are disabled.")
            self.edit.save_state.mark_saved()
            self.edit._save = lambda: True

    def enter_show(self, rehearsal=False):
        if self._entry_check is not None:
            return
        if self.show_window is not None:
            self.show_window.raise_()
            return
        if self.edit.list.has_pending_imports:
            self.edit.status_lbl.setText("Wait for the audio import check to finish before entering a mode.")
            return
        if getattr(self.edit,'_recheck_job',None) is not None:
            self._entry_report=None
            self.edit.status_lbl.setText("Wait for the full audio recheck to finish before entering a mode.")
            return
        self.edit.list.setFocus()
        self.edit._stop_audition()
        self.routing.stop_test()
        if not self.preview:
            if not self.routing.prepare("primary"):
                self._entry_report = None
                QMessageBox.warning(self.edit, "Output Not Ready", self.routing.message)
                return
            if self._entry_report is None and any(c.is_play_sound() and c.audio_file for c in self.cue_set.cues):
                if self._entry_check is None:
                    from copy import deepcopy
                    from .ui.background import FileTask
                    from .ui.save_changes import editable_snapshot
                    snapshot = editable_snapshot(self.cue_set)
                    checked_cues = deepcopy(self.cue_set)
                    folder = self.folder.folder if self.folder else None
                    ready = self.audio.ready
                    task = FileTask(lambda: (validate_show(checked_cues, folder, output_device_available=ready,
                                                          progress=task.signals.progress.emit), snapshot, rehearsal))
                    self._entry_check = task
                    task.signals.progress.connect(self._entry_progress)
                    self.edit.set_entry_busy(True, rehearsal)
                    self._entry_check.signals.done.connect(self._entry_checked)
                    self.edit.status_lbl.setText("Checking cue and output readiness...")
                    QThreadPool.globalInstance().start(self._entry_check)
                return
            report = self._entry_report or validate_show(self.cue_set, self.folder.folder if self.folder else None,
                                                        output_device_available=self.audio.ready)
            self._entry_report = None
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
        self.engine.reset_session()
        log.info("MODE ENTER mode=%s production=%r device=%r", "Rehearse" if rehearsal else "Show", self.cue_set.play_name, self.backend.selected_identity)
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

    @Slot(int, int, str)
    def _entry_progress(self, done, total, detail):
        if self._entry_check is not None:
            self.edit.entry_progress.update_progress(done, total, detail)

    @Slot(object, str)
    def _entry_checked(self, result, error):
        self._entry_check = None
        self.edit.set_entry_busy(False)
        if error:
            self.edit.status_lbl.setText("Audio readiness check failed: " + error)
            return
        report, snapshot, rehearsal = result
        from .ui.save_changes import editable_snapshot
        if editable_snapshot(self.cue_set) != snapshot:
            self.edit.status_lbl.setText("Production changed during checks; enter the mode again.")
            return
        self._entry_report = report
        self.enter_show(rehearsal)

    def return_to_edit(self):
        log.info("MODE ENTER mode=Edit production=%r", self.cue_set.play_name)
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
    # Developer-only display samples: no audio file, no playback, never serialized.
    import numpy as np
    from .ui.clip_editor import WaveformData
    time = np.linspace(0, 12, 700)
    amplitude = .10 + .65*np.exp(-((time-4.5)/2.8)**2) + .12*np.sin(time*5)**2
    peak = np.stack([amplitude, amplitude*(.8+.15*np.sin(time*2))], axis=1).astype(np.float32)
    for cue in (rain, bell, thunder):
        cue._preview_waveform = WaveformData(12.0, -peak, peak)
    bell.start_position, bell.end_position, bell.fade_in, bell.fade_out = .8, 11.0, 1.0, 2.0
    return cs


def launch_arguments(argv=None):
    parser = argparse.ArgumentParser(description="BHS Audio Production Player")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gui-preview", action="store_true", help="Open the silent, unsaved GUI sample")
    mode.add_argument("--production", metavar="NAME", help="Open the latest saved version of this production (with normal recovery handling)")
    return parser.parse_args(argv)


def main(argv=None):
    args = launch_arguments(argv)
    configure_logging()
    original_excepthook = sys.excepthook
    def report_exception(kind, value, trace):
        log.critical("UNHANDLED EXCEPTION", exc_info=(kind, value, trace))
        original_excepthook(kind, value, trace)
    sys.excepthook = report_exception
    app = QApplication.instance() or QApplication(sys.argv)
    viewing_mode()
    preview = args.gui_preview
    created = False
    if preview:
        cs, folder, version = preview_production(), None, "sample only"
    else:
        dlg = OpenPlayDialog(DEFAULT_PLAYS_ROOT)
        opened = dlg.open_named(args.production) if args.production else dlg.exec()
        if not opened or dlg.result_cue_set is None:
            shutdown_logging()
            return 0
        cs, folder, version = dlg.result_cue_set, dlg.result_play_folder, dlg.result_version_name
        created = dlg.created_new
    controller = ProductionController(cs, folder, version, preview)
    controller.edit.show()
    if preview:
        controller.edit.list.setCurrentRow(1)
    if args.production:
        controller.edit.list.setCurrentRow(0)
        if not cs.profile.primary_device:
            controller.edit._profile()
    if created:
        controller.edit._audio_test()
    app.aboutToQuit.connect(controller.backend.stop)
    app.aboutToQuit.connect(shutdown_logging)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
