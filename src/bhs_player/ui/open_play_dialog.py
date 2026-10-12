"""Open Play dialog: pick a production and a cue-set version (Sections 16, 17).

Shows the play library, the selected play's full dated version history, and
offers to restore a recovery copy if one is newer than the last save.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..cues.model import CueSet
from ..storage.plays import PlayInfo, scan_plays
from ..storage.store import PlayFolder


class OpenPlayDialog(QDialog):
    """Returns a loaded CueSet plus its PlayFolder via result."""

    def __init__(self, plays_root: Path, parent=None):
        super().__init__(parent)
        self.plays_root = Path(plays_root)
        self.setWindowTitle("Open Play")
        self.setModal(True)
        self.resize(640, 380)

        self.result_cue_set: Optional[CueSet] = None
        self.result_play_folder: Optional[PlayFolder] = None
        self.result_version_name: str = ""

        root = QHBoxLayout(self)

        # left: play library
        left = QVBoxLayout()
        left.addWidget(QLabel("Plays"))
        self.plays_list = QListWidget()
        self.plays_list.currentRowChanged.connect(self._on_play_changed)
        left.addWidget(self.plays_list, 1)
        new_btn = QPushButton("New Play…")
        new_btn.clicked.connect(self._new_play)
        left.addWidget(new_btn)
        root.addLayout(left, 1)

        # right: version history
        right = QVBoxLayout()
        right.addWidget(QLabel("Version History (newest last)"))
        self.versions_list = QListWidget()
        right.addWidget(self.versions_list, 1)
        self.recovery_lbl = QLabel("")
        self.recovery_lbl.setStyleSheet("color: #e0b050;")
        right.addWidget(self.recovery_lbl)
        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._open)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        root.addLayout(right, 1)

        self._plays: list[PlayInfo] = []
        self._reload()

    def _reload(self):
        self._plays = scan_plays(self.plays_root)
        self.plays_list.clear()
        for p in self._plays:
            item = QListWidgetItem(
                f"{p.name}   ({p.version_count} versions, {p.audio_file_count} audio)")
            self.plays_list.addItem(item)
        if self._plays:
            self.plays_list.setCurrentRow(0)

    def _current_play(self) -> Optional[PlayInfo]:
        row = self.plays_list.currentRow()
        return self._plays[row] if 0 <= row < len(self._plays) else None

    def _on_play_changed(self, _row: int):
        self.versions_list.clear()
        self.recovery_lbl.setText("")
        play = self._current_play()
        if not play:
            return
        for v in play.folder.list_versions():
            item = QListWidgetItem(v.name)
            item.setData(32, v)
            self.versions_list.addItem(item)
        if self.versions_list.count():
            self.versions_list.setCurrentRow(self.versions_list.count() - 1)
        if play.folder.recovery_newer_than_saved():
            self.recovery_lbl.setText("Unsaved recovery data is newer than the last save.")

    def _new_play(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Play", "Play name:")
        if ok and name.strip():
            from ..storage.plays import create_play
            create_play(self.plays_root, name.strip())
            self._reload()

    def _open(self):
        play = self._current_play()
        if not play:
            self.reject()
            return
        pf = play.folder

        # offer recovery restore if newer unsaved data exists (Section 17)
        if pf.recovery_newer_than_saved():
            choice = QMessageBox.question(
                self, "Recovery Available",
                "Newer unsaved recovery data exists for this play.\n\n"
                "Yes = Restore recovery copy\nNo = Open last saved version",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if choice == QMessageBox.Cancel:
                return
            if choice == QMessageBox.Yes:
                self.result_cue_set = pf.load_recovery()
                self.result_play_folder = pf
                self.result_version_name = "(recovery)"
                self.accept()
                return

        item = self.versions_list.currentItem()
        if item is None:
            self.reject()
            return
        path = item.data(32)
        try:
            self.result_cue_set = pf.load_version(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", f"Could not load version:\n{exc}")
            return
        self.result_play_folder = pf
        self.result_version_name = path.name
        self.accept()
