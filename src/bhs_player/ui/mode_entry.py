"""Visible readiness progress and an explicitly approximate countdown."""
import math
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar


class ModeEntryProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-weight: bold; color: #efce75")
        self.bar = QProgressBar()
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.hide()

    def begin(self, total, rehearsal=False):
        self.total = max(1, total)
        self.done = 0
        self.mode = "Rehearsal" if rehearsal else "Show Mode"
        self.detail = "Starting readiness checks"
        self.started = time.monotonic()
        self.deadline = self.started + max(1, total * 0.25)
        self.bar.setRange(0, self.total)
        self.bar.setValue(0)
        self.show()
        self.refresh()
        self.timer.start()

    def update_progress(self, done, total, detail):
        self.done = done
        self.total = max(1, total)
        self.detail = detail
        elapsed = time.monotonic() - self.started
        if done:
            self.deadline = time.monotonic() + elapsed / done * (total - done)
        self.bar.setRange(0, self.total)
        self.bar.setValue(done)
        self.refresh()

    def refresh(self):
        remaining = math.ceil(self.deadline - time.monotonic())
        estimate = (f"About {remaining}s remaining (estimate)" if remaining > 0
                    else "Taking longer than estimated; still checking")
        self.label.setText(f"Preparing {self.mode} - {self.done}/{self.total} cues checked\n"
                           f"{self.detail} - {estimate}. Opens automatically when ready.")

    def finish(self):
        self.timer.stop()
        self.hide()
