"""Play library scanning and Pre-Show Status model (Sections 16, 20).

A plays root (e.g. Plays/) contains one folder per production. Opening a play
gives access to its version history and audio assets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..cues.model import CueSet
from ..validate.check import ValidationReport
from .store import CUESET_EXT, PlayFolder


@dataclass
class PlayInfo:
    name: str
    folder: PlayFolder
    version_count: int
    latest_version_name: Optional[str]
    audio_file_count: int


def scan_plays(root: Path) -> list[PlayInfo]:
    """List all productions under the plays root."""
    root = Path(root)
    if not root.exists():
        return []
    out: list[PlayInfo] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        pf = PlayFolder(root, child.name)
        versions = pf.list_versions()
        audio = pf.audio_dir
        audio_count = (
            sum(1 for p in audio.iterdir() if p.is_file())
            if audio.exists() else 0
        )
        out.append(PlayInfo(
            name=child.name,
            folder=pf,
            version_count=len(versions),
            latest_version_name=versions[-1].name if versions else None,
            audio_file_count=audio_count,
        ))
    return out


def create_play(root: Path, name: str) -> PlayFolder:
    """Create a new, empty production folder."""
    pf = PlayFolder(root, name)
    pf.ensure()
    # initial empty version so the play appears in history
    pf.save_version(CueSet(play_name=name))
    return pf


@dataclass
class PreShowStatus:
    """Section 20 pre-show status contents."""
    play_name: str
    version_name: str
    cue_count: int
    verified_audio: int
    device_name: str
    device_connected: bool
    engine_ready: bool
    recovery_state: str  # "clean" / "unsaved edits" / "none"
    report: ValidationReport

    @property
    def show_ready(self) -> bool:
        return (self.report.show_ready
                and self.device_connected
                and self.engine_ready)


def build_pre_show_status(
    cue_set: CueSet,
    version_name: str,
    report: ValidationReport,
    device_name: str,
    device_connected: bool,
    engine_ready: bool,
    recovery_state: str,
) -> PreShowStatus:
    return PreShowStatus(
        play_name=cue_set.play_name,
        version_name=version_name,
        cue_count=len(cue_set.cues),
        verified_audio=report.verified_audio_files,
        device_name=device_name,
        device_connected=device_connected,
        engine_ready=engine_ready,
        recovery_state=recovery_state,
        report=report,
    )
