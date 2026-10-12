"""Output device selection dialog (Section 15).

Shown at startup and whenever the operator must deliberately select a
replacement device. Never auto-selects on the operator's behalf except to
pre-highlight the remembered/default device; the operator confirms.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..audio.stream import OutputDevice, list_output_devices


class DeviceDialog(QDialog):
    """Modal device picker. result() -> chosen OutputDevice or None."""

    def __init__(self, parent=None, reason: str = "",
                 preselect_index: Optional[int] = None):
        super().__init__(parent)
        self.setWindowTitle("Select Audio Output Device")
        self.setModal(True)
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        if reason:
            lbl = QLabel(reason)
            lbl.setStyleSheet("color: #e0a0a0; font-weight: bold;")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        layout.addWidget(QLabel("Choose the Windows audio output for this show:"))
        self.list = QListWidget()
        self._devices: list[OutputDevice] = list_output_devices()
        highlight_row = -1
        for i, dev in enumerate(self._devices):
            item = QListWidgetItem(
                f"{dev.name}   [{dev.host_api}]  ({int(dev.default_samplerate)} Hz)")
            item.setData(32, dev)  # Qt.UserRole
            self.list.addItem(item)
            if preselect_index is not None and dev.index == preselect_index:
                highlight_row = i
        if highlight_row < 0 and self._devices:
            highlight_row = 0
        if self._devices:
            self.list.setCurrentRow(highlight_row)
        layout.addWidget(self.list, 1)

        if not self._devices:
            layout.addWidget(QLabel("No output devices found."))

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def selected_device(self) -> Optional[OutputDevice]:
        item = self.list.currentItem()
        return item.data(32) if item else None
