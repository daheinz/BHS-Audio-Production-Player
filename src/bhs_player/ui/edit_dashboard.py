"""Compact Edit dashboard; commands and state remain owned by EditWindow."""
from PySide6.QtWidgets import (QWidget, QGroupBox, QGridLayout, QVBoxLayout,
                              QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle)
from .audio_health import AudioHealthPanel
from .mode_entry import ModeEntryProgress


class EditDashboard(QWidget):
    def __init__(self, edit):
        super().__init__(edit)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.panels = [QGroupBox(title) for title in
                       ("System Status", "Cue Controls", "Project && Navigation")]
        for panel in self.panels:
            panel.setStyleSheet("QGroupBox { border: 1px solid #526475; border-radius: 5px; "
                                "margin-top: 9px; padding-top: 9px; } "
                                "QGroupBox::title { color: #78b8e8; left: 8px; }")
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        status = QVBoxLayout(self.panels[0])
        status.setSpacing(2)
        status.setContentsMargins(7, 7, 7, 7)
        edit.engine_state = QLabel()
        edit.engine_state.setStyleSheet("font-weight: bold")
        edit.device_label = QLabel()
        edit.device_label.setWordWrap(True)
        edit.device_label.setMaximumHeight(36)
        edit.status_lbl = QLabel("")
        edit.status_lbl.setWordWrap(True)
        edit.status_lbl.setMaximumHeight(48)
        edit.routing_notice.setMaximumHeight(34)
        edit.audio_health = AudioHealthPanel(edit, getattr(edit.routing, "backend", None),
                                           preview=bool(getattr(edit.routing, "preview", False)))
        edit.audio_health.title.hide()
        edit.audio_health.logs_button.setMinimumHeight(26)
        edit.audio_health.setMinimumHeight(82)
        edit.audio_health.setMaximumWidth(16777215)
        for widget in (edit.engine_state, edit.device_label, edit.audio_health,
                       edit.routing_notice, edit.status_lbl):
            status.addWidget(widget)
        controls = QGridLayout(self.panels[1])
        controls.setContentsMargins(7, 7, 7, 7)
        controls.setHorizontalSpacing(5)
        controls.setVerticalSpacing(5)

        def button(text, callback, tip, icon=None):
            widget = QPushButton(text)
            widget.setToolTip(tip)
            widget.setMinimumHeight(29)
            widget.setStyleSheet("padding: 4px 7px")
            if icon is not None:
                widget.setIcon(edit.style().standardIcon(icon))
            widget.clicked.connect(callback)
            return widget

        controls.addWidget(QLabel("Manage"), 0, 0)
        edit.add_btn = button("Add Cue", edit._add_cue, "Add a cue using the existing cue editor")
        edit.del_btn = button("Remove", edit._remove_cue, "Remove the selected cue")
        edit.up_btn = button("Move Up", lambda: edit._move(-1), "Move the selected cue up one row")
        edit.down_btn = button("Move Down", lambda: edit._move(1), "Move the selected cue down one row")
        for col, widget in enumerate((edit.add_btn, edit.del_btn, edit.up_btn, edit.down_btn), 1):
            controls.addWidget(widget, 0, col)
        controls.addWidget(QLabel("Test"), 1, 0)
        edit.test_btn = button("TEST Selected Cue", edit._audition,
                               "Test the selected audio cue without advancing the show", QStyle.SP_MediaPlay)
        edit.test_btn.setStyleSheet("QPushButton { padding: 4px 7px; background: #1468ac; color: white; } "
                                    "QPushButton:disabled { background: #344253; color: #8995a5; }")
        edit.stop_test_btn = button("Stop TEST", edit._stop_audition,
                                    "Stop or cancel preparation of the test playback", QStyle.SP_MediaStop)
        controls.addWidget(edit.test_btn, 1, 1, 1, 2)
        controls.addWidget(edit.stop_test_btn, 1, 3, 1, 2)
        controls.addWidget(QLabel("Tools"), 2, 0)
        edit.validate_btn = button("Validate Show", edit._validate_show, "Check cue and output readiness")
        edit.import_btn = button("Browse / Import Audio", edit._browse_audio,
                                  "Assign audio to the selected Play cue", QStyle.SP_DialogOpenButton)
        edit.advanced_btn = button("Advanced Editor...", edit._advanced,
                                    "Edit all settings for the selected cue")
        controls.addWidget(edit.validate_btn, 2, 1)
        controls.addWidget(edit.import_btn, 2, 2, 1, 2)
        controls.addWidget(edit.advanced_btn, 2, 4)
        edit.test_lbl = QLabel("")
        edit.test_lbl.setWordWrap(True)
        edit.test_lbl.hide()
        controls.addWidget(edit.test_lbl, 3, 0, 1, 5)
        from .widgets import ProgressBar, LevelMeter
        meters = QHBoxLayout()
        edit.test_progress, edit.test_meter = ProgressBar(), LevelMeter()
        edit.test_progress.hide()
        edit.test_meter.hide()
        meters.addWidget(edit.test_progress, 2)
        meters.addWidget(edit.test_meter, 1)
        controls.addLayout(meters, 4, 0, 1, 5)
        project = QVBoxLayout(self.panels[2])
        project.setContentsMargins(7, 7, 7, 7)
        secondary = QHBoxLayout()
        edit.save_btn = button("Save Version", edit._save, "Save a new production version", QStyle.SP_DialogSaveButton)
        edit.rehearse_btn = button("REHEARSE", lambda: edit._enter_show(True), "Enter Rehearsal with the current cues")
        secondary.addWidget(edit.save_btn)
        secondary.addWidget(edit.rehearse_btn)
        project.addLayout(secondary)
        edit.entry_progress = ModeEntryProgress(edit)
        project.addWidget(edit.entry_progress)
        edit.show_btn = button("ENTER SHOW MODE", edit._enter_show,
                                "Check readiness and enter Show Mode", QStyle.SP_MediaPlay)
        edit.show_btn.setStyleSheet("font-weight: bold; padding: 9px 12px; background: #2e7d32; color: white")
        project.addWidget(edit.show_btn)
        project.addStretch(1)
        self._layout_mode = None
        self.reflow(1500)

    def resizeEvent(self, event):
        self.reflow(event.size().width())
        super().resizeEvent(event)

    def reflow(self, width):
        mode = 3 if width >= 1300 else 2 if width >= 800 else 1
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        # Reset rows when moving between the one- and two-row dashboards.
        for row in range(3):
            self.grid.setRowStretch(row, 0)
            self.grid.setRowMinimumHeight(row, 0)
        for panel in self.panels:
            self.grid.removeWidget(panel)
        for col in range(3):
            self.grid.setColumnStretch(col, 0)
        if mode == 3:
            for col, panel in enumerate(self.panels):
                self.grid.addWidget(panel, 0, col)
            for col, stretch in enumerate((3, 6, 3)):
                self.grid.setColumnStretch(col, stretch)
        elif mode == 2:
            self.grid.addWidget(self.panels[0], 0, 0)
            self.grid.addWidget(self.panels[2], 0, 1)
            self.grid.addWidget(self.panels[1], 1, 0, 1, 2)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 1)
        else:
            for row, panel in enumerate((self.panels[0], self.panels[2], self.panels[1])):
                self.grid.addWidget(panel, row, 0)
            self.grid.setColumnStretch(0, 1)
