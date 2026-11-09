"""Reconcile linked action cues before deleting their target."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QListWidget, QComboBox,
    QPushButton, QMessageBox, QDialogButtonBox)


class LinkedCuesDialog(QDialog):
    def __init__(self, cue_set, target, changed, parent=None):
        super().__init__(parent)
        self.cue_set, self.target, self.changed = cue_set, target, changed
        self.setWindowTitle("Review Linked Cues")
        self.resize(570, 360)
        root = QVBoxLayout(self)
        self.intro = QLabel(f"Cue {target.identifier} cannot be deleted while these action cues target it. Choose a replacement or delete each linked cue.")
        self.intro.setWordWrap(True)
        root.addWidget(self.intro)
        self.list = QListWidget()
        root.addWidget(self.list)
        self.replacement = QComboBox()
        for cue in cue_set.cues:
            if cue.is_play_sound() and cue is not target:
                self.replacement.addItem(f"{cue.identifier} — {cue.name}", cue.internal_id)
        root.addWidget(self.replacement)
        retarget = QPushButton("Use Replacement for Selected Linked Cue")
        retarget.setEnabled(self.replacement.count() > 0)
        retarget.clicked.connect(self.retarget)
        root.addWidget(retarget)
        delete = QPushButton("Delete Selected Linked Cue…")
        delete.clicked.connect(self.delete)
        root.addWidget(delete)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        root.addWidget(close)
        self.refresh()

    def refresh(self):
        self.links = [c for c in self.cue_set.cues if c.target_internal_id == self.target.internal_id]
        self.list.clear()
        self.list.addItems([f"{c.identifier} — {c.name} ({c.action.value})" for c in self.links])
        if self.links:
            self.list.setCurrentRow(0)
        else:
            self.intro.setText("All links resolved. Close this window, then remove the original cue when ready.")

    def retarget(self):
        row = self.list.currentRow()
        if row >= 0 and self.replacement.currentData():
            self.links[row].target_internal_id = self.replacement.currentData()
            self.changed()
            self.refresh()

    def delete(self):
        row = self.list.currentRow()
        if row >= 0 and QMessageBox.question(self, "Delete Linked Cue?", f"Delete cue {self.links[row].identifier}?", QMessageBox.Yes | QMessageBox.Cancel) == QMessageBox.Yes:
            self.cue_set.remove(self.links[row].internal_id)
            self.changed()
            self.refresh()
