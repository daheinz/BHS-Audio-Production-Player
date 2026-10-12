"""Fake audio engine for headless tests (no real audio output)."""

from __future__ import annotations

from bhs_player.cues.engine import SoundInstance
from bhs_player.cues.model import Cue


class FakeAudioEngine:
    def __init__(self, ready: bool = True):
        self._ready = ready
        self.instances: list[SoundInstance] = []
        self.fail_next_start: bool = False
        self.started_cues: list[str] = []
        self.stopped_instances: list[SoundInstance] = []
        self.faded: list[tuple[SoundInstance, float]] = []
        self.stop_all_calls: int = 0

    @property
    def ready(self) -> bool:
        return self._ready

    def set_ready(self, ready: bool) -> None:
        self._ready = ready

    def start(self, cue: Cue) -> SoundInstance:
        if self.fail_next_start:
            self.fail_next_start = False
            raise RuntimeError("simulated start failure")
        inst = SoundInstance(
            cue_internal_id=cue.internal_id,
            identifier=cue.identifier,
            name=cue.name,
            looping=cue.loop,
        )
        self.instances.append(inst)
        self.started_cues.append(cue.internal_id)
        return inst

    def stop_instance(self, instance: SoundInstance) -> None:
        instance.stopped = True
        if instance in self.instances:
            self.instances.remove(instance)
        self.stopped_instances.append(instance)

    def fade_instance(self, instance: SoundInstance, duration: float) -> None:
        instance.fading = True
        self.faded.append((instance, duration))
        if duration == 0.0:
            self.stop_instance(instance)

    def stop_all(self) -> None:
        self.stop_all_calls += 1
        for inst in list(self.instances):
            self.stop_instance(inst)

    def active_instances(self) -> list[SoundInstance]:
        return list(self.instances)

    def instances_of(self, cue_internal_id: str) -> list[SoundInstance]:
        return [i for i in self.instances if i.cue_internal_id == cue_internal_id]

    # test helper: simulate a sound reaching its end
    def finish(self, instance: SoundInstance, natural: bool = True) -> None:
        if natural:
            instance.completed_naturally = True
        else:
            instance.stopped = True
        if instance in self.instances:
            self.instances.remove(instance)
