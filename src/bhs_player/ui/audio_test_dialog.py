"""Repeatable human audibility checks; no simulated test successes."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QDialogButtonBox)


class AudioTestDialog(QDialog):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Pre-Audience Audio Test")
        self.resize(680, 430)
        root = QVBoxLayout(self)
        title = QLabel("Check the sound at the board")
        title.setStyleSheet("font-size: 22px; font-weight: bold")
        root.addWidget(title)
        warning = QLabel("Test sound reaches the mixing board and speakers. Coordinate with the board operator. A moving meter does not prove the speakers are audible.")
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.path = QComboBox()
        p = session.cue_set.profile
        for b in p.buses:
            self.path.addItem(f"PRIMARY · {b.name} · {b.shape} · board: {b.board_input or 'not labeled'}", b.id)
        self.path.addItem(f"BACKUP · combined {p.backup_shape} · board: {p.backup_board_input or 'not labeled'}", "backup")
        root.addWidget(self.path)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.meter = QLabel("Meter unavailable until the selected output is prepared.")
        root.addWidget(self.meter)
        root.addStretch()
        row = QHBoxLayout()
        self.play = QPushButton("Play Again")
        self.confirm = QPushButton("Confirmed Audible — Next")
        self.skip = QPushButton("Skip / Not Working — Next")
        self.play.clicked.connect(self.play_again)
        self.confirm.clicked.connect(self.confirm_audible)
        self.skip.clicked.connect(self.skip_path)
        for b in (self.play, self.confirm, self.skip):
            row.addWidget(b)
        root.addLayout(row)
        stop = QPushButton("STOP TEST")
        stop.setStyleSheet("background: #b42318; color: white; padding: 14px; font-weight: bold")
        stop.clicked.connect(session.stop_test)
        root.addWidget(stop)
        done = QDialogButtonBox(QDialogButtonBox.Close)
        done.rejected.connect(self.reject)
        root.addWidget(done)
        self.path.currentIndexChanged.connect(self.path_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_meter)
        self.timer.start(100)
        self.path_changed()

    def path_changed(self):
        self.session.stop_test()
        key = self.path.currentData()
        route = "backup" if key == "backup" else "primary"
        reason = self.session.unsupported(route)
        self.play.setEnabled(not reason)
        self.confirm.setEnabled(key in self.session.played and not reason)
        state = "Confirmed audible this session." if key in self.session.confirmations else "Not confirmed. Play the signal, then listen at the board."
        self.status.setText(reason or state)

    def play_again(self):
        if QMessageBox.question(self, "Play Test Sound?", "Send a quiet left-then-right test tone to the board now?", QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        ok = self.session.play_test(self.path.currentData())
        self.status.setText(self.session.message)
        self.confirm.setEnabled(ok)

    def next_path(self):
        self.session.stop_test()
        if self.path.currentIndex() + 1 < self.path.count():
            self.path.setCurrentIndex(self.path.currentIndex() + 1)
        else:
            self.path_changed()
            self.status.setText("Test review complete. You can select any path to repeat. Unconfirmed primary: " + (", ".join(self.session.unconfirmed()) or "none") + ". Backup: " + ("confirmed" if "backup" in self.session.confirmations else "not confirmed"))

    def confirm_audible(self):
        if self.session.confirm(self.path.currentData()):
            self.next_path()

    def skip_path(self):
        self.session.confirmations.discard(self.path.currentData())
        self.next_path()

    def refresh_meter(self):
        if self.session.audio.ready and self.session.backend.stream and self.session.backend.stream.running:
            m = self.session.audio.mixer.last_meter
            self.meter.setText(f"Actual output · L {m.left_db:.1f} dBFS   R {m.right_db:.1f} dBFS")
        else:
            self.meter.setText("Meter unavailable — output not prepared.")

    def done(self, result):
        self.session.stop_test()
        self.timer.stop()
        super().done(result)
