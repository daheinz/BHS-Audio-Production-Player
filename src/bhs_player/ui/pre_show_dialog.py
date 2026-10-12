"""Pre-Show Status screen (Section 20).

Shown after loading and validation, before Show Mode. Critical failures block
ENTER SHOW MODE; warnings remain visible.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..storage.plays import PreShowStatus
from ..validate.check import Severity


class PreShowDialog(QDialog):
    """Modal gate before Show Mode. Accepted only when show_ready."""

    def __init__(self, status: PreShowStatus, parent=None):
        super().__init__(parent)
        self.status = status
        self.setWindowTitle("Pre-Show Status")
        self.setModal(True)
        self.resize(560, 480)

        root = QVBoxLayout(self)

        title = QLabel(status.play_name.upper())
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        root.addWidget(title)

        root.addWidget(QLabel(f"Version: {status.version_name}"))
        root.addWidget(QLabel(f"{status.cue_count} cues loaded"))
        root.addWidget(QLabel(f"{status.verified_audio} audio files verified"))

        refs_ok = not any(
            i.severity is Severity.CRITICAL and ("target" in i.message or "identifier" in i.message.lower())
            for i in status.report.issues)
        refs_lbl = QLabel("All cue references valid" if refs_ok else "Cue reference problems found")
        refs_lbl.setStyleSheet(f"color: {'#7fc97f' if refs_ok else '#e07070'};")
        root.addWidget(refs_lbl)

        dev_lbl = QLabel(
            f"{status.device_name} connected" if status.device_connected
            else "No audio output device connected")
        dev_lbl.setStyleSheet(f"color: {'#7fc97f' if status.device_connected else '#e07070'};")
        root.addWidget(dev_lbl)

        eng_lbl = QLabel("Audio engine ready" if status.engine_ready else "Audio engine NOT ready")
        eng_lbl.setStyleSheet(f"color: {'#7fc97f' if status.engine_ready else '#e07070'};")
        root.addWidget(eng_lbl)

        root.addWidget(QLabel(f"Recovery state: {status.recovery_state}"))

        # issues
        root.addWidget(QLabel("Warnings and Errors:"))
        self.issues = QListWidget()
        for issue in status.report.issues:
            cue = f"[{issue.cue_identifier}] " if issue.cue_identifier else ""
            text = f"{issue.severity.value.upper()}: {cue}{issue.message}"
            if issue.fix:
                text += f"  — {issue.fix}"
            item = QListWidgetItem(text)
            item.setForeground(
                Qt.red if issue.severity is Severity.CRITICAL else Qt.yellow)
            self.issues.addItem(item)
        if not status.report.issues:
            self.issues.addItem(QListWidgetItem("No issues."))
        root.addWidget(self.issues, 1)

        ready_lbl = QLabel("SHOW READY" if status.show_ready else "NOT READY - resolve critical issues")
        ready_lbl.setStyleSheet(
            f"font-size: 18px; font-weight: bold; padding: 8px;"
            f"color: {'#7fc97f' if status.show_ready else '#e07070'};")
        ready_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(ready_lbl)

        self.enter_btn = QPushButton("ENTER SHOW MODE")
        self.enter_btn.setEnabled(status.show_ready)
        self.enter_btn.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 14px;")
        self.enter_btn.clicked.connect(self.accept)
        root.addWidget(self.enter_btn)

        cancel_btn = QPushButton("Back to Edit")
        cancel_btn.clicked.connect(self.reject)
        root.addWidget(cancel_btn)
