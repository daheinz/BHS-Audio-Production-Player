"""Application entry point.

Run:  python -m bhs_player.app
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .audio.engine import AudioEngine, Mixer
from .audio.stream import StreamingAudioBackend
from .cues.engine import CueEngine
from .cues.model import CueSet
from .storage.plays import build_pre_show_status
from .ui.device_dialog import DeviceDialog
from .ui.edit_window import EditWindow
from .ui.main_window import MainWindow
from .ui.open_play_dialog import OpenPlayDialog
from .ui.pre_show_dialog import PreShowDialog
from .validate.check import validate_show

DEFAULT_PLAYS_ROOT = Path("Plays")


def build_app(cue_set: CueSet, audio: AudioEngine | None = None,
              backend: StreamingAudioBackend | None = None) -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication(sys.argv)
    audio = audio or AudioEngine(Mixer(), ready=False)
    backend = backend or StreamingAudioBackend(audio)
    engine = CueEngine(cue_set, audio)  # self-wires on_instance_ended + preload
    win = MainWindow(cue_set, engine, audio, backend)
    return app, win


def select_output(win: MainWindow) -> bool:
    """Startup device selection (Section 15). Returns True if a device was
    selected and the stream started."""
    dlg = DeviceDialog(win, reason="Select the audio output device for this show.")
    if not dlg.exec() or dlg.selected_device() is None:
        return False
    dev = dlg.selected_device()
    return win.backend.select_device(dev.index) if win.backend else False


def open_play(plays_root: Path, parent=None):
    """Open Play flow. Returns (cue_set, play_folder, version_name) or None."""
    dlg = OpenPlayDialog(plays_root, parent)
    if dlg.exec() and dlg.result_cue_set is not None:
        return dlg.result_cue_set, dlg.result_play_folder, dlg.result_version_name
    return None


def pre_show_gate(win: MainWindow, cue_set: CueSet, play_folder,
                  version_name: str) -> bool:
    """Validate + Pre-Show Status gate (Sections 19, 20)."""
    report = validate_show(
        cue_set,
        play_folder=play_folder.folder if play_folder else None,
        output_device_available=win.audio.ready,
    )
    device_name = (
        win.backend.stream.device_name
        if win.backend and win.backend.stream is not None else "(none)")
    recovery_state = "none"
    if play_folder is not None:
        recovery_state = "unsaved edits" if play_folder.recovery_newer_than_saved() else "clean"
    status = build_pre_show_status(
        cue_set, version_name, report,
        device_name=device_name,
        device_connected=win.audio.ready,
        engine_ready=win.audio.ready,
        recovery_state=recovery_state,
    )
    dlg = PreShowDialog(status, win)
    return bool(dlg.exec())


def main() -> int:
    # QApplication must exist before any QWidget/dialog is constructed.
    app = QApplication.instance() or QApplication(sys.argv)
    opened = open_play(DEFAULT_PLAYS_ROOT)
    if opened is None:
        return 0
    cue_set, play_folder, version_name = opened

    audio = AudioEngine(Mixer(), ready=False,
                        base_path=play_folder.folder if play_folder else None)
    backend = StreamingAudioBackend(audio)
    engine = CueEngine(cue_set, audio)  # self-wires on_instance_ended + preload

    # Edit Mode is the persistent home; Show Mode opens on top and returns here.
    edit_win = EditWindow(cue_set, audio, play_folder)
    edit_win.show()

    show_state: dict = {"win": None}

    def enter_show() -> None:
        # stop any audition playback before performing (Section 13)
        edit_win._stop_audition()
        show_win = MainWindow(cue_set, engine, audio, backend)
        show_state["win"] = show_win
        show_win.show()
        # Only select output when no stream is already running; re-entering
        # Show Mode must not restart the stream (Section 15).
        if not (backend.stream is not None and backend.stream.running):
            select_output(show_win)
            if play_folder is not None and backend.selected_identity:
                play_folder.save_device_identity(backend.selected_identity)
        if not pre_show_gate(show_win, cue_set, play_folder, version_name):
            # Back to Edit: close show window, keep editing
            show_state["win"] = None
            show_win.close()
            return
        # Show Mode boundary (Section 13): lock the Edit window while the
        # show runs; closing the show window returns to Edit Mode.
        edit_win.setEnabled(False)
        show_win.setAttribute(Qt.WA_DeleteOnClose)

        def _on_show_closed(*_args):
            show_state["win"] = None
            edit_win.setEnabled(True)
            edit_win._rebuild()  # reflect any show-time state in the editor

        show_win.destroyed.connect(_on_show_closed)

    edit_win.enter_show = enter_show  # Edit window can call this
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
