"""Audio health gauge and nonmodal access to local troubleshooting logs."""
from dataclasses import asdict
import json
import platform
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QProgressBar, QPushButton, QDialog, QPlainTextEdit,
                              QApplication)
from .. import diagnostics


class DiagnosticsDialog(QDialog):
    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("Audio diagnostics and logs")
        self.resize(850, 560)
        self.setModal(False)
        layout = QVBoxLayout(self)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        self.error_label = QLabel()
        self.error_label.setProperty("tone", "error")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        for label, callback in (("Refresh", self.refresh), ("Copy report", self.copy_report),
                                ("Open Logs Folder", self.open_folder), ("Close", self.close)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        path = diagnostics.configure_logging()
        self.path_label.setText(str(path))
        self.error_label.setText("Logging unavailable: " + diagnostics.logging_error() if diagnostics.logging_error() else "")
        context = {"platform": platform.platform(), "device": None, "health": None}
        if self.backend is not None:
            snapshot = self.backend.poll_diagnostics(force=True)
            context.update(device=self.backend.selected_identity,
                           output_lost=self.backend.output_lost,
                           output_lost_reason=self.backend.output_lost_reason,
                           health=asdict(snapshot) if snapshot else None,
                           active=[{"cue": i.identifier, "playback": i.playback_number}
                                   for i in self.backend.engine.active_instances()])
        self.text.setPlainText("CURRENT DIAGNOSTICS\n" + json.dumps(context, indent=2) +
                               "\n\nRECENT LOG (UTC timestamps)\n" + diagnostics.read_log_tail())

    def copy_report(self):
        self.refresh()
        QApplication.clipboard().setText(self.text.toPlainText())

    def open_folder(self):
        path = diagnostics.configure_logging().parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.error_label.setText("Could not open the log folder. Path: " + str(path))


def show_diagnostics(parent, backend=None):
    dialog = getattr(parent, '_diagnostics_dialog', None)
    if dialog is not None:
        dialog.refresh()
        dialog.raise_()
        dialog.activateWindow()
        return
    dialog = DiagnosticsDialog(parent, backend)
    parent._diagnostics_dialog = dialog
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.destroyed.connect(lambda: setattr(parent, '_diagnostics_dialog', None))
    dialog.show()


class AudioHealthPanel(QWidget):
    def __init__(self, parent=None, backend=None, preview=False):
        super().__init__(parent)
        self.backend, self.preview = backend, preview
        self.setMinimumWidth(175)
        self.setMaximumWidth(230)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(3)
        self.title = QLabel("AUDIO HEALTH")
        self.title.setStyleSheet("font-weight: bold")
        layout.addWidget(self.title)
        self.gauge = QProgressBar()
        self.gauge.setRange(0, 100)
        self.gauge.setFixedHeight(19)
        layout.addWidget(self.gauge)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("font-size: 11px")
        layout.addWidget(self.detail)
        self.logs_button = QPushButton("Diagnostics / Logs")
        self.logs_button.setStyleSheet("padding: 4px 8px")
        self.logs_button.clicked.connect(lambda: show_diagnostics(self.window(), self.backend))
        layout.addWidget(self.logs_button)
        self._tone = None
        self.refresh()

    def refresh(self):
        snapshot = self.backend.poll_diagnostics() if self.backend is not None else None
        if self.preview or snapshot is None:
            status, tone, load = ("Preview / no audio" if self.preview else "Unavailable"), "neutral", 0
            detail = "No live stream measurements"
        else:
            status, tone = snapshot.status()
            if self.backend.output_lost:
                status, tone = "OUTPUT LOST", "error"
            load = max(0, snapshot.load*100)
            detail = f"Dropouts: {snapshot.underflows} | Clipped blocks: {snapshot.clipped_blocks}"
            self.setToolTip(f"Processing load: {load:.1f}% | peak callback: {snapshot.peak_load*100:.1f}%\n"
                            f"Over-budget callbacks: {snapshot.overruns} | callbacks: {snapshot.callbacks}\n"
                            f"Sample rate: {snapshot.sample_rate} | block: {snapshot.blocksize} | latency: {snapshot.latency}\n"
                            "Dropouts count driver-reported output underflows. This is not buffer fullness or speaker verification.")
        if self.backend is not None and self.backend.output_lost and not self.preview:
            status, tone = "OUTPUT LOST", "error"
            detail += " | " + self.backend.output_lost_reason
        self.logs_button.setText("Logs (error)" if diagnostics.logging_error() else "Diagnostics / Logs")
        self.gauge.setValue(min(100, round(load)))
        self.gauge.setFormat(f"{status} | {load:.0f}%")
        self.detail.setText(detail)
        if self._tone != tone:
            color = {"neutral": "#657185", "success": "#2e7d32", "warning": "#9b6a17", "error": "#a92323"}[tone]
            self.gauge.setStyleSheet("QProgressBar { border: 1px solid " + color + "; text-align: center; background: #20242b; color: #f4f6f8; } QProgressBar::chunk { background: " + color + "; }")
            self.title.setProperty("tone", tone)
            self.title.style().unpolish(self.title)
            self.title.style().polish(self.title)
            self._tone = tone
