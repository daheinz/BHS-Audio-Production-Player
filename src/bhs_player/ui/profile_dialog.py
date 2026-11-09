"""Production profile editor. Configuration is saved only after validation."""
from copy import deepcopy
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QFormLayout, QComboBox, QTableWidget, QTableWidgetItem, QPushButton,
    QDialogButtonBox, QGroupBox, QDoubleSpinBox, QScrollArea, QWidget)
from ..profiles import OutputBus
from ..audio.stream import list_output_devices


class ProfileDialog(QDialog):
    def __init__(self, cue_set, parent=None, creation=False):
        super().__init__(parent)
        self.cue_set = cue_set
        self.profile = deepcopy(cue_set.profile)
        self.setWindowTitle("Choose Production Profile" if creation else "Profile and Routing")
        self.resize(1000, 690)
        root = QVBoxLayout(self)
        intro = QLabel("This profile belongs to this production. Configure its routes here; primary and backup use the same cue settings.")
        intro.setWordWrap(True)
        root.addWidget(intro)
        if creation:
            presets = QComboBox()
            presets.addItems(["Standard stereo", "Custom venue / USB mixer"])
            root.addWidget(QLabel("Starting profile"))
            root.addWidget(presets)
            presets.currentTextChanged.connect(lambda name: self.name.setText(name))
        form = QFormLayout()
        self.name = QLineEdit(self.profile.name)
        self.primary = QComboBox()
        self.backup = QComboBox()
        self.primary.addItem("Choose primary device…", None)
        self.backup.addItem("No backup configured", None)
        try:
            self.devices = list_output_devices()
        except Exception:
            self.devices = []
        for combo, identity in ((self.primary, self.profile.primary_device), (self.backup, self.profile.backup_device)):
            for d in self.devices:
                key = f"{d.name} [{d.host_api}]"
                combo.addItem(f"{key} — {d.max_output_channels} outputs", key)
            if identity and combo.findData(identity) < 0:
                combo.addItem(identity + " (unavailable)", identity)
            combo.setCurrentIndex(max(0, combo.findData(identity)))
        form.addRow("Profile name", self.name)
        form.addRow("Primary output", self.primary)
        form.addRow("Optional backup output", self.backup)
        root.addLayout(form)
        root.addWidget(QLabel("Defined buses — Main is required; each bus is its own destination. Levels are percentages."))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Bus name", "Mono / stereo", "Hardware channels", "Output level %", "Expected board input", "Backup mix %"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(4, 190)
        root.addWidget(self.table, 1)
        for bus in self.profile.buses:
            self.add_bus(bus)
        buttons = QHBoxLayout()
        add = QPushButton("Add Bus")
        remove = QPushButton("Remove Selected Bus")
        add.clicked.connect(lambda: self.add_bus())
        remove.clicked.connect(self.remove_bus)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        root.addLayout(buttons)
        backup_form = QFormLayout()
        self.backup_shape = QComboBox()
        self.backup_shape.addItems(["stereo", "mono"])
        self.backup_shape.setCurrentText(self.profile.backup_shape)
        self.backup_channels = QLineEdit(", ".join(map(str, self.profile.backup_channels)))
        self.backup_input = QLineEdit(self.profile.backup_board_input)
        backup_form.addRow("Backup feed shape", self.backup_shape)
        backup_form.addRow("Backup hardware channels", self.backup_channels)
        backup_form.addRow("Expected backup board input", self.backup_input)
        root.addLayout(backup_form)
        note = QLabel("Playback connection in this pass: one stereo Main bus on outputs 1, 2. Other valid configurations can be saved and edited, but playback and tests stay unavailable until routing is connected.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setProperty("tone", "error")
        root.addWidget(self.error)
        done = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        done.accepted.connect(self.save)
        done.rejected.connect(self.reject)
        root.addWidget(done)

    def add_bus(self, bus=None):
        if self.table.rowCount() >= 6:
            self.error.setText("A profile can contain at most six buses.")
            return
        if bus is None:
            bus = OutputBus(id=uuid.uuid4().hex, name="New Bus", channels=[self.table.rowCount()*2+1, self.table.rowCount()*2+2])
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(bus.name)
        name.setData(Qt.UserRole, bus.id)
        if bus.id == "main":
            name.setToolTip("Required Main destination. Its display name may be changed.")
        self.table.setItem(row, 0, name)
        shape = QComboBox()
        shape.addItems(["stereo", "mono"])
        shape.setCurrentText(bus.shape)
        self.table.setCellWidget(row, 1, shape)
        for col, value in ((2, ", ".join(map(str, bus.channels))), (3, f"{bus.level*100:g}"), (4, bus.board_input), (5, f"{self.profile.backup_levels.get(bus.id, 1)*100:g}")):
            self.table.setItem(row, col, QTableWidgetItem(value))

    def remove_bus(self):
        row = self.table.currentRow()
        if row < 0:
            return
        id = self.table.item(row, 0).data(Qt.UserRole)
        if id == "main":
            self.error.setText("Main is required and cannot be removed.")
        elif any(id in c.bus_ids for c in self.cue_set.cues if c.is_play_sound()):
            self.error.setText("This bus is assigned to cues. Change those assignments in the Advanced Cue Editor first.")
        else:
            self.table.removeRow(row)

    def save(self):
        try:
            p = deepcopy(self.profile)
            p.name = self.name.text().strip()
            if not p.name:
                raise ValueError("Enter a profile name.")
            p.primary_device = self.primary.currentData()
            p.backup_device = self.backup.currentData()
            p.buses = []
            p.backup_levels = {}
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                bus = OutputBus(id=item.data(Qt.UserRole), name=item.text().strip(),
                    shape=self.table.cellWidget(row, 1).currentText(),
                    channels=[int(c.strip()) for c in self.table.item(row, 2).text().split(",")],
                    level=float(self.table.item(row, 3).text())/100,
                    board_input=self.table.item(row, 4).text().strip())
                p.buses.append(bus)
                p.backup_levels[bus.id] = float(self.table.item(row, 5).text())/100
            p.backup_shape = self.backup_shape.currentText()
            p.backup_channels = [int(c.strip()) for c in self.backup_channels.text().split(",")]
            p.backup_board_input = self.backup_input.text().strip()
            dev = next((d for d in self.devices if f"{d.name} [{d.host_api}]" == p.primary_device), None)
            errors = p.errors(dev.max_output_channels if dev else None)
            backup_dev = next((d for d in self.devices if f"{d.name} [{d.host_api}]" == p.backup_device), None)
            if backup_dev and max(p.backup_channels) > backup_dev.max_output_channels:
                errors.append("Backup mapping exceeds the backup device capacity.")
            if errors:
                raise ValueError("\n".join(errors))
            self.profile = p
            self.accept()
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
