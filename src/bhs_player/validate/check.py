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

from ..cues.model import ActionType, CueSet, validate_identifier

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
    """Duration in seconds, using libsndfile with a PyAV fallback for AAC/M4A."""
    try:
        info = sf.info(str(path))
        if info.frames <= 0 or info.samplerate <= 0:
            raise ValueError("no determinable duration")
        return info.frames / info.samplerate
    except Exception:
        # AAC and other FFmpeg-only formats
        from ..audio.engine import _load_segment_av
        from ..cues.model import Cue
        pcm, sr = _load_segment_av(str(path), Cue(identifier="0.0"))
        if sr <= 0 or pcm.shape[0] == 0:
            raise ValueError("no determinable duration")
        return pcm.shape[0] / sr


def validate_show(
    cue_set: CueSet,
    play_folder: Optional[Path] = None,
    output_device_available: bool = True,
) -> ValidationReport:
    """Run the full Section-19 check list."""
    report = ValidationReport()

    # identifier validity and uniqueness
    seen: set[str] = set()
    for cue in cue_set.cues:
        if not validate_identifier(cue.identifier):
            report.add(Severity.CRITICAL, cue.identifier,
                       f"Identifier '{cue.identifier}' does not follow the "
                       "script-page convention (page.number).",
                       "Rename to e.g. 12.0 or 47.21.")
        if cue.identifier in seen:
            report.add(Severity.CRITICAL, cue.identifier,
                       f"Duplicate cue identifier '{cue.identifier}'.",
                       "Identifiers must be unique within a cue set.")
        seen.add(cue.identifier)

    # duplicate internal IDs (stable target references depend on them)
    seen_iids: set[str] = set()
    for cue in cue_set.cues:
        if cue.internal_id in seen_iids:
            report.add(Severity.CRITICAL, cue.identifier,
                       "Duplicate internal cue ID.",
                       "Reload the cue set; internal IDs must be unique.")
        seen_iids.add(cue.internal_id)

    verified: set[str] = set()
    for cue in cue_set.cues:
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
                           "Loop On combined with Advance Mode On Complete is "
                           "invalid: the sound never naturally completes.",
                           "Use On GO / Trigger for looping ambience.")

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

    report.verified_audio_files = len(verified)

    if not output_device_available:
        report.add(Severity.CRITICAL, None,
                   "Selected audio output device is unavailable.",
                   "Select a replacement output device and re-prepare.")

    return report
