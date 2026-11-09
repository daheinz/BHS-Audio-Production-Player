"""Application preferences kept separately from production cue sets."""
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths


def application_settings():
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.GenericConfigLocation))
    path = folder / 'BHS Audio Production Player' / 'settings.ini'
    return QSettings(str(path), QSettings.IniFormat)
