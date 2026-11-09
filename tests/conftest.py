import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def isolated_application_settings(tmp_path, monkeypatch):
    """UI tests must not read or overwrite the user's column preferences."""
    path = tmp_path / 'settings.ini'
    monkeypatch.setattr('bhs_player.ui.cue_table.application_settings',
                        lambda: QSettings(str(path), QSettings.IniFormat))


@pytest.fixture(autouse=True)
def isolated_audio_cache(tmp_path, monkeypatch):
    monkeypatch.setattr('bhs_player.audio.cache.ROOT',tmp_path/'decoder-cache')
    monkeypatch.setattr('bhs_player.ui.open_play_dialog.application_settings',
                        lambda: QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat))
