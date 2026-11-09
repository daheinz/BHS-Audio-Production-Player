"""Production-owned routing configuration; stable bus and endpoint references."""
from dataclasses import dataclass, field
import math
import uuid


@dataclass
class OutputBus:
    id: str = "main"
    name: str = "Main"
    channels: list[int] = field(default_factory=lambda: [1, 2])
    level: float = 1.0
    board_input: str = ""
    shape: str = "stereo"


@dataclass
class ProductionProfile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Standard stereo"
    buses: list[OutputBus] = field(default_factory=lambda: [OutputBus()])
    primary_device: str | None = None
    backup_device: str | None = None
    backup_channels: list[int] = field(default_factory=lambda: [1, 2])
    backup_board_input: str = ""
    backup_shape: str = "stereo"
    backup_levels: dict[str, float] = field(default_factory=lambda: {"main": 1.0})

    def errors(self, capacity=None):
        errors = []
        if not 1 <= len(self.buses) <= 6:
            errors.append("Define one to six buses.")
        if not any(b.id == "main" for b in self.buses):
            errors.append("The Main destination is required.")
        if len({b.id for b in self.buses}) != len(self.buses):
            errors.append("Bus references must be unique.")
        used = set()
        for b in self.buses:
            count = 1 if b.shape == "mono" else 2
            if b.shape not in ("mono", "stereo") or len(b.channels) != count or len(set(b.channels)) != count:
                errors.append(f"{b.name}: choose one mono channel or two distinct stereo channels.")
            if not b.name.strip() or not math.isfinite(b.level) or not 0 <= b.level <= 4:
                errors.append(f"{b.name or 'Bus'}: enter a name and level from 0 to 400%.")
            if any(c < 1 or (capacity is not None and c > capacity) for c in b.channels):
                errors.append(f"{b.name}: channel mapping exceeds the device capacity.")
            if used.intersection(b.channels):
                errors.append(f"{b.name}: hardware channels overlap another primary bus.")
            used.update(b.channels)
        if self.backup_device:
            count = 1 if self.backup_shape == "mono" else 2
            if len(self.backup_channels) != count or len(set(self.backup_channels)) != count or any(c < 1 for c in self.backup_channels):
                errors.append("Backup: choose a valid mono channel or stereo pair.")
            if set(self.backup_levels) != {b.id for b in self.buses} or any(not math.isfinite(v) or not 0 <= v <= 4 for v in self.backup_levels.values()):
                errors.append("Backup: set a combination level from 0 to 400% for every bus.")
        return errors

    def bus_names(self, ids):
        return ", ".join(next((b.name for b in self.buses if b.id == id), "Missing bus") for id in ids)


def profile_from_dict(data):
    data = dict(data)
    data["buses"] = [OutputBus(**b) for b in data.get("buses", [])]
    return ProductionProfile(**data)
