"""Cue execution engine: GO, Back, ARM CUE, advance modes, On GO behaviors.

Spec references: Sections 2, 3, 4, 5, 7, 10 (Program Prompt Version 0.1).

The engine is UI-free and audio-engine-agnostic: it talks to an
AudioEngineProtocol so tests can drive it headless against a fake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Optional, Protocol

from .model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueExecutionState,
    CueSet,
    OnGoBehavior,
)


class AudioEngineProtocol(Protocol):
    """What the cue engine needs from the audio layer."""

    @property
    def ready(self) -> bool: ...

    def start(self, cue: Cue) -> "SoundInstance": ...
    def stop_instance(self, instance: "SoundInstance") -> None: ...
    def fade_instance(self, instance: "SoundInstance", duration: float) -> None: ...
    def stop_all(self) -> None: ...
    def active_instances(self) -> list["SoundInstance"]: ...
    def instances_of(self, cue_internal_id: str) -> list["SoundInstance"]: ...


@dataclass
class SoundInstance:
    """One active playback of a cue. Multiple may exist for one cue."""

    cue_internal_id: str
    identifier: str
    name: str
    looping: bool
    fading: bool = False
    stopped: bool = False
    completed_naturally: bool = False
    playback_number: int = 0


@dataclass
class GoResult:
    ok: bool
    reason: str = ""
    cue: Optional[Cue] = None


class GoUnavailableError(Exception):
    pass


class CueEngine:
    """Drives show execution against a CueSet.

    State model (Section 2):
    - pointer: index of the Active/Armed Cue (or None when nothing armed)
    - each cue has an execution_state
    - active sound instances live in the audio engine's Playing Stack
    """

    def __init__(self, cue_set: CueSet, audio: AudioEngineProtocol):
        self.cue_set = cue_set
        self.audio = audio
        self.pointer: Optional[int] = 0 if cue_set.cues else None
        self._waiting_on: Optional[str] = None  # source internal_id awaiting completion
        self._waiting_instance = None
        self._pending_auto_go = None
        self._control_epoch = 0
        if self.pointer is not None:
            cue_set.cues[0].execution_state = CueExecutionState.ARMED
        # Unified completion wiring: every audio instance end (natural, early
        # stop, or fade-completed) flows through here (Sections 3, 4).
        if hasattr(audio, "on_instance_ended"):
            audio.on_instance_ended = self._on_instance_ended
        # Preload the initially armed cue (Section 15).
        self._preload_armed()

    @property
    def waiting_cue(self):
        return self.cue_set.by_internal_id(self._waiting_on) if self._waiting_on else None

    def interrupt_output(self, disarm=False):
        """Cancel stale advancement before stopping audio; preserve independent arming."""
        self._cancel_auto_go()
        waiting = self.waiting_cue
        self._waiting_on = None
        self._waiting_instance = None
        if waiting is not None:
            waiting.execution_state = CueExecutionState.INTERRUPTED
            self._disarm_current()
            self.pointer = None
        if disarm:
            self._disarm_current()
            self.pointer = None
        self.audio.stop_all()

    def reset_session(self):
        """Begin a fresh performance/rehearsal; history is not cue configuration."""
        self.interrupt_output(disarm=True)
        for cue in self.cue_set.cues:
            cue.execution_state = CueExecutionState.IDLE

    # ---- state queries -------------------------------------------------

    @property
    def armed_cue(self) -> Optional[Cue]:
        if self.pointer is None:
            return None
        cue = self.cue_set.cues[self.pointer]
        if self._waiting_on is not None:
            waiting = self.waiting_cue
            if waiting is None or waiting.advance_mode is not AdvanceMode.ON_COMPLETE_GO or cue.internal_id == self._waiting_on:
                return None
        return cue

    def go_available(self) -> tuple[bool, str]:
        if not self.audio.ready:
            return False, "Audio output not ready"
        cue = self.armed_cue
        if cue is None:
            if self._waiting_on is not None:
                return False, "Waiting for sound to complete"
            return False, "No cue armed"
        if cue.is_play_sound() and cue.audio_file and getattr(self.audio, 'nonblocking', False):
            self.audio.prepare_async(cue,refresh=False)
            status, error = self.audio.preparation_status(cue)
            if status != "ready":
                return False, error
        return True, ""

    # ---- GO ------------------------------------------------------------

    def go(self) -> GoResult:
        self._cancel_auto_go()
        ok, reason = self.go_available()
        if not ok:
            return GoResult(ok=False, reason=reason)
        cue = self.armed_cue
        assert cue is not None
        logging.getLogger("bhs_player.cues").info(
            "CUE GO id=%s name=%r action=%s file=%r level=%s repeat=%s next=%s on_go=%s buses=%s",
            cue.identifier, cue.name, cue.action.value, cue.audio_file, cue.volume,
            cue.loop, cue.advance_mode.value, cue.on_go_behavior.value, cue.bus_ids)
        # Manual GO can execute an already armed successor before its source
        # finishes. Detach the old completion callback so it cannot GO twice.
        if self._waiting_on is not None:
            self._release_completion_wait()

        if cue.action is ActionType.PLAY:
            return self._go_play(cue)
        return self._go_action(cue)

    def _go_play(self, cue: Cue) -> GoResult:
        if not cue.loop_config_valid():
            return GoResult(ok=False, reason="Loops require Arm Next Now; they cannot complete naturally.", cue=cue)
        # Check readiness before applying destructive On GO behavior (Section 5).
        if not self.audio.ready:
            return GoResult(ok=False, reason="Audio output not ready", cue=cue)

        # Decode/verify the new sound FIRST. A missing or unreadable file must
        # fail here, before any existing audio is stopped (Section 5).
        pcm = None
        sample_rate = None
        if hasattr(self.audio, "decode_cue") and cue.audio_file:
            try:
                pcm, sample_rate = self.audio.decode_cue(cue)
                check_capacity = getattr(self.audio, 'check_start_capacity', None)
                if callable(check_capacity):
                    check_capacity(cue, pcm)
            except Exception as exc:
                return GoResult(ok=False, reason=f"Failed to start: {exc}", cue=cue)

        behavior = cue.on_go_behavior
        if behavior is OnGoBehavior.STOP_PREVIOUS:
            active = self.audio.active_instances()
            if active:
                # most recently triggered active sound is last in the list
                self.audio.stop_instance(active[-1])
        elif behavior is OnGoBehavior.STOP_ALL:
            self.audio.stop_all()

        try:
            if pcm is not None:
                instance = self.audio.start_prepared(cue, pcm, sample_rate)
            else:
                instance = self.audio.start(cue)
        except Exception as exc:  # start failure reported, no silent advance
            return GoResult(ok=False, reason=f"Failed to start: {exc}", cue=cue)
        _ = instance

        if cue.advance_mode in (AdvanceMode.ON_COMPLETE, AdvanceMode.ON_COMPLETE_GO):
            cue.execution_state = CueExecutionState.PLAYING
            self._waiting_instance = instance
            if cue.advance_mode is AdvanceMode.ON_COMPLETE_GO:
                # The successor is genuinely armed and can be fired manually.
                # Natural completion will execute this same armed cue, without
                # advancing the pointer a second time.
                self._advance_pointer()
            # Publish the completion wait only after its successor is armed.
            # If audio already ended, the check below handles that completion.
            self._waiting_on = cue.internal_id
            if instance.completed_naturally:
                self.notify_sound_finished(cue.internal_id, True, instance)
        else:
            cue.execution_state = CueExecutionState.TRIGGERED
            self._advance_pointer()
        return GoResult(ok=True, cue=cue)

    def _go_action(self, cue: Cue) -> GoResult:
        if cue.action is ActionType.STOP_ALL:
            self.audio.stop_all()
            self._finish_action_cue(cue)
            return GoResult(ok=True, cue=cue)

        # STOP and FADE target a PLAY cue by stable internal ID (Section 4)
        target = (
            self.cue_set.by_internal_id(cue.target_internal_id)
            if cue.target_internal_id
            else None
        )
        if target is None or not target.is_play_sound():
            return GoResult(ok=False, reason="Invalid target", cue=cue)

        instances = self.audio.instances_of(target.internal_id)
        if cue.action is ActionType.STOP:
            for inst in instances:
                self.audio.stop_instance(inst)
            self._finish_action_cue(cue)
        elif cue.action is ActionType.FADE:
            if instances:
                # Set the wait before callbacks: zero-length fades end immediately.
                cue.execution_state = CueExecutionState.PLAYING
                self._waiting_on = cue.internal_id
                self._waiting_instance = None
                for inst in instances:
                    self.audio.fade_instance(inst, cue.fade_duration)
                return GoResult(ok=True, cue=cue)
            # valid target not playing: visible no-op, completes immediately
            self._finish_action_cue(cue)
        return GoResult(ok=True, cue=cue)

    # ---- completion notifications (from audio engine / fades) ----------

    def _on_instance_ended(self, instance, natural: bool) -> None:
        """Unified hook: AudioEngine calls this for every instance end.

        - natural end of a PLAY cue -> advance if it was an On Complete wait
        - early stop/fade of an On Complete sound -> release the wait (Section 3)
        - end of a fade target -> finish the waiting FADE cue (Section 4)
        TEST/audition instances are isolated and never affect show state.
        """
        if getattr(instance, "is_test", False):
            return
        self.notify_sound_finished(instance.cue_internal_id, natural, instance)

        # If a FADE action cue is waiting and its target no longer has any
        # active instances, the fade has finished -> complete the FADE cue.
        if self._waiting_on is not None:
            waiting_cue = self.cue_set.by_internal_id(self._waiting_on)
            if waiting_cue is not None and waiting_cue.action is ActionType.FADE:
                if not self.audio.instances_of(waiting_cue.target_internal_id):
                    self.notify_fade_finished(waiting_cue.internal_id)

    def notify_sound_finished(self, cue_internal_id: str, natural: bool, instance=None) -> None:
        """Called when a sound instance ends.

        natural=True: reached its End Position / natural file end.
        natural=False: manually stopped or faded early.
        """
        cue = self.cue_set.by_internal_id(cue_internal_id)
        if cue is None:
            return

        if cue.advance_mode is AdvanceMode.ON_GO:
            # Completion of an On GO sound never moves the pointer again.
            if natural and cue.execution_state is CueExecutionState.TRIGGERED:
                cue.execution_state = CueExecutionState.COMPLETE
            elif not natural and cue.execution_state is CueExecutionState.TRIGGERED:
                cue.execution_state = CueExecutionState.INTERRUPTED
            return

        # Only the playback holding this wait may schedule automatic continuation.
        epoch = self._control_epoch
        if self._waiting_on != cue_internal_id:
            if cue.execution_state is CueExecutionState.TRIGGERED:
                cue.execution_state = CueExecutionState.COMPLETE if natural else CueExecutionState.INTERRUPTED
            return
        if instance is not None and self._waiting_instance is not None and instance is not self._waiting_instance:
            return
        self._waiting_instance = None
        if natural:
            cue.execution_state = CueExecutionState.COMPLETE
            self._waiting_on = None
            if cue.advance_mode is not AdvanceMode.ON_COMPLETE_GO:
                self._advance_pointer()
            if cue.advance_mode is AdvanceMode.ON_COMPLETE_GO and epoch == self._control_epoch and self.armed_cue is not None:
                # Never decode/start the next sound in the real-time audio callback.
                self._pending_auto_go = (self.armed_cue.internal_id, epoch)
        else:
            self._cancel_auto_go()
            # Interrupted: release the wait but leave navigation to the
            # operator. Nothing remains armed until Back or ARM CUE.
            cue.execution_state = CueExecutionState.INTERRUPTED
            self._waiting_on = None
            self._disarm_current()
            self.pointer = None

    def notify_fade_finished(self, cue_internal_id: str) -> None:
        """A FADE action cue's fade completed: action completes, arm next."""
        cue = self.cue_set.by_internal_id(cue_internal_id)
        if cue is None or cue.action is not ActionType.FADE:
            return
        if self._waiting_on != cue_internal_id:
            return
        self._waiting_on = None
        self._finish_action_cue(cue)

    # ---- navigation -----------------------------------------------------

    def back(self) -> bool:
        """Move armed cue to previous in performance order. No audio change.
        At top of list: visible no-op (returns False)."""
        self._cancel_auto_go()
        self._release_completion_wait()
        if not self.cue_set.cues:
            return False
        self._disarm_current()
        if self.pointer is None:
            self.pointer = 0
        elif self.pointer > 0:
            self.pointer -= 1
        else:
            self._arm_at(0)
            return False
        self._arm_at(self.pointer)
        return True

    def arm_cue(self, internal_id: str) -> bool:
        """Explicitly arm any cue, earlier or later (Sections 10, Mouse
        Select and Arm). Re-arming resets execution eligibility; existing
        sound instances of that cue are untouched."""
        idx = self.cue_set.index_of(internal_id)
        if idx is None:
            return False
        self._cancel_auto_go()
        self._release_completion_wait()
        self._disarm_current()
        cue = self.cue_set.cues[idx]
        cue.execution_state = CueExecutionState.ARMED  # explicit re-arm
        self.pointer = idx
        self._waiting_on = None  # explicit navigation cancels pending waits
        self._preload_armed()
        return True

    def stop_all(self) -> None:
        """Emergency STOP ALL (Section 3): stops audio, executes no cue,
        changes no armed cue; if an On Complete wait was interrupted,
        nothing remains armed."""
        self.interrupt_output()

    def _release_completion_wait(self):
        waiting = self.waiting_cue
        if waiting is not None and waiting.is_play_sound() and waiting.execution_state is CueExecutionState.PLAYING:
            waiting.execution_state = CueExecutionState.TRIGGERED
        self._waiting_on = None
        self._waiting_instance = None

    def _cancel_auto_go(self):
        self._control_epoch += 1
        self._pending_auto_go = None

    def process_pending_auto_go(self):
        """Dispatch on the UI/control thread, not inside audio rendering.

        Navigation, stop, loss, or mode exit invalidates the queued request.
        A manual GO consumes it too, so the next cue cannot execute twice.
        """
        pending = self._pending_auto_go
        if pending is None:
            return None
        cue_id, epoch = pending
        if epoch != self._control_epoch or self.armed_cue is None or self.armed_cue.internal_id != cue_id:
            self._pending_auto_go = None
            return None
        available, reason = self.go_available()
        if not available and reason.startswith("Preparing audio"):
            return None
        self._pending_auto_go = None
        return self.go()

    # ---- internals ------------------------------------------------------

    def _finish_action_cue(self, cue: Cue) -> None:
        cue.execution_state = CueExecutionState.COMPLETE
        self._advance_pointer()

    def _advance_pointer(self) -> None:
        """Arm the next cue in performance order; never auto-executes.
        At end of list: nothing armed, never wraps (Section 3)."""
        if self.pointer is None:
            return
        nxt = self.pointer + 1
        if nxt >= len(self.cue_set.cues):
            self.pointer = None
            return
        self.pointer = nxt
        self._arm_at(nxt)

    def _arm_at(self, index: int) -> None:
        cue = self.cue_set.cues[index]
        cue.execution_state = CueExecutionState.ARMED
        self._preload_armed()

    def _preload_armed(self) -> None:
        """Decode/prepare the Armed Cue off the audio path so GO starts with
        minimal latency (Section 15). No-op for engines without preloading."""
        # GUI readiness polling starts preparation on the control thread.
        # Completion can run in the audio callback: never stat files or start
        # decoder jobs here in live nonblocking mode.
        if getattr(self.audio, 'nonblocking', False):
            return
        cue = self.armed_cue
        if cue is not None and cue.is_play_sound() and cue.audio_file:
            prep = getattr(self.audio, "prepare_async", None)
            if callable(prep):
                prep(cue)

    def _disarm_current(self) -> None:
        if self.pointer is not None:
            cue = self.cue_set.cues[self.pointer]
            if cue.execution_state is CueExecutionState.ARMED:
                cue.execution_state = CueExecutionState.IDLE
