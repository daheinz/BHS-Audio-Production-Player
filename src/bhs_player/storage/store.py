"""Play folders, versioned cue-set saves (never overwrite), recovery autosave.

Spec references: Sections 16, 17, 18 (Program Prompt Version 0.1).

Play folder layout:
    Plays/Clue/
        Clue - 10-6-2026 23-48-35.cueset      (permanent versions, never overwritten)
        Clue - 10-6-2026 23-49-02.cueset
        audio/doorbell.wav
        .recovery/Clue.recovery.cueset        (autosave; separate from history)

Cue sets serialize to JSON. Identifiers stay TEXT. Internal IDs are stored so
STOP/FADE target references survive save/load. Performance order is the list
order in the file.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueExecutionState,
    CueSet,
    OnGoBehavior,
)

CUESET_EXT = ".cueset"
RECOVERY_DIR = ".recovery"


def _file_hash(path: Path) -> str:
    """SHA-256 of file contents; used to detect truly identical assets."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- serialization -------------------------------------------------------

def _cue_to_dict(cue: Cue) -> dict:
    d = asdict(cue)
    d["action"] = cue.action.value
    d["advance_mode"] = cue.advance_mode.value
    d["on_go_behavior"] = cue.on_go_behavior.value
    d["execution_state"] = cue.execution_state.value
    return d


def _cue_from_dict(d: dict) -> Cue:
    d = dict(d)
    d["action"] = ActionType(d["action"])
    d["advance_mode"] = AdvanceMode(d["advance_mode"])
    d["on_go_behavior"] = OnGoBehavior(d["on_go_behavior"])
    d["execution_state"] = CueExecutionState(d.get("execution_state", "idle"))
    return Cue(**d)


def serialize_cue_set(cue_set: CueSet) -> str:
    payload = {
        "play_name": cue_set.play_name,
        "format_version": 1,
        "master_level": cue_set.master_level,
        "cues": [_cue_to_dict(c) for c in cue_set.performance_order()],
    }
    return json.dumps(payload, indent=2)


def deserialize_cue_set(text: str) -> CueSet:
    payload = json.loads(text)
    cs = CueSet(play_name=payload["play_name"],
                master_level=payload.get("master_level", 1.0))
    for cd in payload["cues"]:
        cs.insert(_cue_from_dict(cd))
    return cs


# ---- play folder ---------------------------------------------------------

def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


class PlayFolder:
    """One production's folder on disk."""

    def __init__(self, root: Path, play_name: str):
        self.root = Path(root)
        self.play_name = play_name
        self.folder = self.root / _safe_name(play_name)
        self.audio_dir = self.folder / "audio"
        self.recovery_dir = self.folder / RECOVERY_DIR

    def ensure(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.recovery_dir.mkdir(parents=True, exist_ok=True)

    def _version_filename(self, when: datetime) -> str:
        stamp = when.strftime("%m-%d-%Y %H-%M-%S")
        return f"{_safe_name(self.play_name)} - {stamp}{CUESET_EXT}"

    # -- permanent versioned saves (NEVER overwrite) ---------------------
    def save_version(self, cue_set: CueSet, when: Optional[datetime] = None) -> Path:
        """Write a new historical version. Guarantees a unique filename even
        for multiple saves within the same second (Section 16)."""
        self.ensure()
        when = when or datetime.now()
        base = self._version_filename(when)
        path = self.folder / base
        n = 1
        while path.exists():
            stem = base[: -len(CUESET_EXT)]
            path = self.folder / f"{stem} ({n}){CUESET_EXT}"
            n += 1
        self._atomic_write(path, serialize_cue_set(cue_set))
        # A permanent save captures current edits, so any prior recovery copy
        # no longer represents unsaved work.
        self.clear_recovery()
        return path

    def list_versions(self) -> list[Path]:
        if not self.folder.exists():
            return []
        files = sorted(
            self.folder.glob(f"*.{CUESET_EXT.lstrip('.')}"),
            key=lambda p: p.stat().st_mtime,
        )
        return [p for p in files if p.name.endswith(CUESET_EXT)]

    def latest_version(self) -> Optional[Path]:
        versions = self.list_versions()
        return versions[-1] if versions else None

    def load_version(self, path: Path) -> CueSet:
        return deserialize_cue_set(Path(path).read_text(encoding="utf-8"))

    def load_latest(self) -> Optional[CueSet]:
        latest = self.latest_version()
        return self.load_version(latest) if latest else None

    # -- recovery autosave (separate from permanent history) -------------
    def _recovery_path(self) -> Path:
        return self.recovery_dir / f"{_safe_name(self.play_name)}.recovery{CUESET_EXT}"

    def save_recovery(self, cue_set: CueSet) -> Path:
        self.ensure()
        path = self._recovery_path()
        self._atomic_write(path, serialize_cue_set(cue_set))
        return path

    def has_recovery(self) -> bool:
        return self._recovery_path().exists()

    def recovery_newer_than_saved(self) -> bool:
        """True if recovery data exists representing work not in a permanent
        save. Because save_version() clears the recovery copy, any recovery
        file present was written after the last permanent save, so a same-tick
        timestamp still counts as newer."""
        if not self.has_recovery():
            return False
        latest = self.latest_version()
        if latest is None:
            return True
        return self._recovery_path().stat().st_mtime >= latest.stat().st_mtime

    def load_recovery(self) -> CueSet:
        return self.load_version(self._recovery_path())

    def clear_recovery(self) -> None:
        p = self._recovery_path()
        if p.exists():
            p.unlink()

    # -- audio import ------------------------------------------------------
    def import_audio(self, source: Path) -> Path:
        """Copy an external audio file into the play's audio folder and return
        the play-relative reference (Section 16). Collisions never overwrite.
        Identical content (not just same size) is deduplicated via hash."""
        self.ensure()
        source = Path(source)
        dest = self.audio_dir / source.name
        if dest.exists():
            if _file_hash(dest) == _file_hash(source):
                return Path("audio") / dest.name  # truly identical, reuse
            n = 1
            while dest.exists():
                dest = self.audio_dir / f"{source.stem} ({n}){source.suffix}"
                if dest.exists() and _file_hash(dest) == _file_hash(source):
                    return Path("audio") / dest.name
                n += 1
        import shutil
        shutil.copy2(source, dest)
        return Path("audio") / dest.name

    # -- device preference (per play, Section 15) ---------------------------
    def _device_pref_path(self) -> Path:
        return self.folder / "output_device.txt"

    def save_device_identity(self, identity: str) -> None:
        """Persist the stable device identity (name [api]) for this play."""
        self.ensure()
        self._atomic_write(self._device_pref_path(), identity)

    def load_device_identity(self) -> Optional[str]:
        p = self._device_pref_path()
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip() or None
            except Exception:
                return None
        return None

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """Write safely so interruption never leaves a truncated file in place
        of a valid version (Section 16)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
