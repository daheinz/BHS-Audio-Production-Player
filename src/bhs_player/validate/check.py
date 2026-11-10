"""Load-time sanity check and Validate Show (Section 19/18).

Every check reports severity, the affected cue identifier, a description, and
corrective context. Critical errors block entering Show Mode; warnings stay
visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from ..cues.model import ActionType, CueSet, identifier_key, validate_identifier

try:
    import soundfile as sf
except Exception:  # pragma: no cover
    sf = None


class Severity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"


@dataclass
class Issue:
    severity: Severity
    cue_identifier: Optional[str]
    message: str
    fix: str = ""


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    verified_audio_files: int = 0

    def add(self, severity, identifier, message, fix=""):
        self.issues.append(Issue(severity, identifier, message, fix))

    @property
    def critical(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.CRITICAL]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def show_ready(self) -> bool:
        return not self.critical


def _probe_duration(path: Path) -> float:
    from ..audio.safe_decode import inspect_audio
    return inspect_audio(path)["duration"]


def validate_show(
    cue_set: CueSet,
    play_folder: Optional[Path] = None,
    output_device_available: bool = True,
    progress=None,
) -> ValidationReport:
    """Run the full Section-19 check list."""
    report = ValidationReport()

    # identifier validity and uniqueness
    seen = {}
    for cue in cue_set.cues:
        if not validate_identifier(cue.identifier):
            report.add(Severity.CRITICAL, cue.identifier,
                       f"Identifier '{cue.identifier}' does not follow the "
                       "script-page convention (page.number).",
                       "Rename to e.g. 12.0 or 47.21.")
        key = identifier_key(cue.identifier)
        if key in seen:
            report.add(Severity.CRITICAL, cue.identifier,
                       f"Duplicate cue identifier '{cue.identifier}' (same number as '{seen[key]}').",
                       "Cue identifiers must be unique as text; 12.1 and 12.10 are distinct.")
        seen[key] = cue.identifier

    # duplicate internal IDs (stable target references depend on them)
    seen_iids: set[str] = set()
    for cue in cue_set.cues:
        if cue.internal_id in seen_iids:
            report.add(Severity.CRITICAL, cue.identifier,
                       "Duplicate internal cue ID.",
                       "Reload the cue set; internal IDs must be unique.")
        seen_iids.add(cue.internal_id)

    verified: set[str] = set()
    for index, cue in enumerate(cue_set.cues):
        if progress:
            progress(index, len(cue_set.cues), f"Checking cue {cue.identifier}")
        if cue.action is ActionType.PLAY:
            # assigned file
            if not cue.audio_file:
                report.add(Severity.CRITICAL, cue.identifier,
                           "PLAY SOUND cue has no assigned audio file.",
                           "Assign an audio file in Edit Mode.")
            else:
                path = (Path(play_folder) / cue.audio_file) if play_folder else Path(cue.audio_file)
                # asset containment: references must stay within the play folder
                if play_folder is not None:
                    try:
                        resolved = path.resolve()
                        root = Path(play_folder).resolve()
                        if root not in resolved.parents and resolved != root:
                            report.add(Severity.CRITICAL, cue.identifier,
                                       f"Audio reference '{cue.audio_file}' escapes the "
                                       "play folder.", "Re-import the file into the play.")
                    except Exception:
                        pass
                if not path.exists():
                    report.add(Severity.CRITICAL, cue.identifier,
                               f"Audio file '{cue.audio_file}' does not exist.",
                               "Re-import or relink the audio file.")
                elif sf is not None:
                    try:
                        file_dur = _probe_duration(path)
                        if str(path) not in verified:
                            verified.add(str(path))
                        # segment bounds against the REAL file duration (§5)
                        if not cue.segment_valid(file_dur):
                            report.add(Severity.CRITICAL, cue.identifier,
                                       f"Segment (start={cue.start_position}, "
                                       f"end={cue.end_position}) is outside the file "
                                       f"duration {file_dur:.2f}s.",
                                       "Fix Start/End Positions in Edit Mode.")
                        # compressed-format timing warning (Section 6)
                        if path.suffix.lower() in (".mp3", ".aac", ".m4a", ".ogg"):
                            if cue.loop or cue.start_position or cue.end_position:
                                report.add(Severity.WARNING, cue.identifier,
                                           f"'{path.suffix}' is a compressed format; "
                                           "loop points and segment boundaries may not be "
                                           "sample-accurate.",
                                           "Convert to WAV for performance use.")
                    except Exception as exc:
                        report.add(Severity.CRITICAL, cue.identifier,
                                   f"Audio file '{cue.audio_file}' cannot be "
                                   f"opened/decoded: {exc}",
                                   "Replace with a readable WAV/FLAC/MP3/AAC file.")
            # volume and fades
            if cue.volume < 0:
                report.add(Severity.CRITICAL, cue.identifier,
                           f"Volume {cue.volume} is negative.",
                           "Set volume within the supported range.")
            if cue.fade_in < 0 or cue.fade_out < 0:
                report.add(Severity.CRITICAL, cue.identifier,
                           "Fade durations must be nonnegative.",
                           "Use 0 for an immediate change.")
            # loop + On Complete is invalid (Section 7)
            if not cue.loop_config_valid():
                report.add(Severity.CRITICAL, cue.identifier,
                           "Loop On combined with Arm Next at End or GO on End is "
                           "invalid: the sound never naturally completes.",
                           "Use Arm Next Now for looping ambience.")

        # STOP / FADE target references
        if cue.action in (ActionType.STOP, ActionType.FADE):
            target = (cue_set.by_internal_id(cue.target_internal_id)
                      if cue.target_internal_id else None)
            if target is None:
                report.add(Severity.CRITICAL, cue.identifier,
                           "STOP/FADE cue has no valid target reference.",
                           "Retarget to a PLAY SOUND cue.")
            elif not target.is_play_sound():
                report.add(Severity.CRITICAL, cue.identifier,
                           "STOP/FADE target is not a PLAY SOUND cue.",
                           "Target a PLAY SOUND cue.")
            if cue.action is ActionType.FADE and cue.fade_duration < 0:
                report.add(Severity.CRITICAL, cue.identifier,
                           "Fade duration must be nonnegative.",
                           "Use 0 for an immediate stop.")

    if progress:
        progress(len(cue_set.cues), len(cue_set.cues), "Checking output and routing")
    report.verified_audio_files = len(verified)

    if not output_device_available:
        report.add(Severity.CRITICAL, None,
                   "Selected audio output device is unavailable.",
                   "Select a replacement output device and re-prepare.")

    for message in cue_set.profile.errors():
        report.add(Severity.CRITICAL, None, message, "Open Profile & Routing in Edit Mode.")
    bus_ids = {bus.id for bus in cue_set.profile.buses}
    for cue in cue_set.cues:
        if cue.is_play_sound() and (not cue.bus_ids or not set(cue.bus_ids) <= bus_ids):
            report.add(Severity.CRITICAL, cue.identifier, "Choose valid output buses in the Advanced Cue Editor.")
    if not cue_set.profile.backup_device:
        report.add(Severity.WARNING, None, "No backup output configured.")
    return report
