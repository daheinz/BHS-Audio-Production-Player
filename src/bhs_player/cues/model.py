"""Cue data model.

Spec references: Sections 4, 5, 6, 11 (Program Prompt Version 0.1).

Key invariants:
- Cue identifiers are stored as TEXT and preserved exactly as entered
  (12.10 must never become 12.1).
- Every cue has a stable internal ID that survives identifier edits,
  renumbering, and reordering. STOP/FADE cues reference targets by
  this internal ID, never by display identifier.
- Performance order is an explicit sequence, independent of any sorting
  of identifiers.
"""

from __future__ import annotations

import itertools
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(Enum):
    PLAY = "PLAY"
    STOP = "STOP"
    FADE = "FADE"
    STOP_ALL = "STOP_ALL"


class AdvanceMode(Enum):
    ON_COMPLETE = "on_complete"
    ON_GO = "on_go"


class OnGoBehavior(Enum):
    ADD_TO_STACK = "add_to_stack"
    STOP_PREVIOUS = "stop_previous"
    STOP_ALL = "stop_all"


class CueExecutionState(Enum):
    """Execution state of a cue in the show (Section 2)."""
    IDLE = "idle"            # not yet executed this run
    ARMED = "armed"          # occupies the execution pointer, GO will fire it
    PLAYING = "playing"      # an On Complete PLAY cue holding the pointer
    TRIGGERED = "triggered"  # fired (On GO), sound may still be playing
    COMPLETE = "complete"    # finished naturally
    INTERRUPTED = "interrupted"  # stopped before natural end


# Script-page identifier convention: digits, a dot, digits (Section 11).
# Examples: 12.0, 12.1, 12.10, 47.2, 47.21
_IDENTIFIER_RE = re.compile(r"^\d+\.\d+$")


def validate_identifier(identifier: str) -> bool:
    """True if identifier follows the script-page convention (page.subcue)."""
    return bool(_IDENTIFIER_RE.match(identifier))


_id_counter = itertools.count(1)


def new_internal_id() -> str:
    """Stable internal cue ID. Survives renumbering and reordering."""
    return f"cue-{uuid.uuid4().hex[:12]}"


@dataclass
class Cue:
    """A single cue. Only PLAY cues carry audio settings."""

    identifier: str  # TEXT, preserved exactly (e.g. "12.10")
    name: str = ""
    action: ActionType = ActionType.PLAY
    internal_id: str = field(default_factory=new_internal_id)
    notes: str = ""

    # PLAY SOUND settings (Section 5)
    audio_file: Optional[str] = None  # path relative to play folder
    volume: float = 1.0               # relative level within the mix
    fade_in: float = 0.0              # seconds
    fade_out: float = 0.0             # seconds
    loop: bool = False
    advance_mode: AdvanceMode = AdvanceMode.ON_COMPLETE
    on_go_behavior: OnGoBehavior = OnGoBehavior.ADD_TO_STACK
    start_position: Optional[float] = None  # seconds; None = file start
    end_position: Optional[float] = None    # seconds; None = file end

    # STOP / FADE settings (Section 4): stable internal target reference
    target_internal_id: Optional[str] = None
    fade_duration: float = 0.0  # FADE action's own duration

    # Runtime execution state (not persisted in cue set file semantics,
    # but saved so restores are faithful)
    execution_state: CueExecutionState = CueExecutionState.IDLE

    def is_play_sound(self) -> bool:
        return self.action is ActionType.PLAY

    def segment_valid(self, file_duration: float) -> bool:
        """0 <= Start < End <= file duration (Section 5)."""
        start = self.start_position if self.start_position is not None else 0.0
        end = self.end_position if self.end_position is not None else file_duration
        return 0.0 <= start < end <= file_duration

    def loop_config_valid(self) -> bool:
        """Loop On + On Complete is invalid (Section 7)."""
        return not (self.loop and self.advance_mode is AdvanceMode.ON_COMPLETE)


@dataclass
class CueSet:
    """A full production cue list, in explicit performance order."""

    play_name: str
    cues: list[Cue] = field(default_factory=list)
    master_level: float = 1.0  # remembered per play (Section 6A)

    def performance_order(self) -> list[Cue]:
        """The cue list in performance order (identity order of self.cues)."""
        return list(self.cues)

    def by_internal_id(self, internal_id: str) -> Optional[Cue]:
        for c in self.cues:
            if c.internal_id == internal_id:
                return c
        return None

    def by_identifier(self, identifier: str) -> Optional[Cue]:
        for c in self.cues:
            if c.identifier == identifier:
                return c
        return None

    def identifiers_unique(self) -> bool:
        ids = [c.identifier for c in self.cues]
        return len(ids) == len(set(ids))

    def insert(self, cue: Cue, index: Optional[int] = None) -> None:
        """Insert at an explicit performance position; default appends."""
        if index is None:
            self.cues.append(cue)
        else:
            self.cues.insert(index, cue)

    def remove(self, internal_id: str) -> Optional[Cue]:
        for i, c in enumerate(self.cues):
            if c.internal_id == internal_id:
                return self.cues.pop(i)
        return None

    def move(self, internal_id: str, new_index: int) -> bool:
        """Explicit reorder; never relies on identifier sorting."""
        cue = self.by_internal_id(internal_id)
        if cue is None:
            return False
        self.cues.remove(cue)
        self.cues.insert(max(0, min(new_index, len(self.cues))), cue)
        return True

    def index_of(self, internal_id: str) -> Optional[int]:
        for i, c in enumerate(self.cues):
            if c.internal_id == internal_id:
                return i
        return None

    def next_after(self, internal_id: str) -> Optional[Cue]:
        i = self.index_of(internal_id)
        if i is None or i + 1 >= len(self.cues):
            return None
        return self.cues[i + 1]

    def previous_before(self, internal_id: str) -> Optional[Cue]:
        i = self.index_of(internal_id)
        if i is None or i == 0:
            return None
        return self.cues[i - 1]
