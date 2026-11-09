"""Narrow adapter for the existing stereo backend. Unsupported routes never play."""
from dataclasses import asdict
import json
import time
import logging

log = logging.getLogger("bhs_player.routing")
import numpy as np
from PySide6.QtCore import QObject, Signal
from .stream import list_output_devices
from ..cues.model import Cue


class RoutingSession(QObject):
    outputLost = Signal(str)

    def __init__(self, cue_set, audio, backend, engine=None):
        super().__init__()
        self.cue_set, self.audio, self.backend, self.engine = cue_set, audio, backend, engine
        self.preview = False
        self._device_cache = []
        self._device_time = 0
        self.route = "primary"
        self.message = "Output not prepared. Open Profile & Routing."
        self.confirmations = set()
        self.played = set()
        self._signature = self.signature()
        self._test = None
        self.outputLost.connect(self._lost)
        backend.on_output_lost = self.outputLost.emit

    def signature(self):
        return json.dumps(asdict(self.cue_set.profile), sort_keys=True)

    def invalidate(self):
        self.stop_test()
        self.confirmations.clear()
        self.played.clear()
        self._signature = self.signature()
        if self.engine:
            self.engine.interrupt_output()
        else:
            self.audio.stop_all()
        self.backend.stop()
        self.audio.set_ready(False)
        self.message = "Configuration changed. Prepare output and repeat the audio test."

    def sync(self):
        if self.signature() != self._signature:
            self.invalidate()

    def devices(self):
        if time.monotonic() - self._device_time > 2:
            try:
                self._device_cache = list_output_devices()
            except Exception:
                self._device_cache = []
            self._device_time = time.monotonic()
        return self._device_cache

    def device(self, route):
        identity = getattr(self.cue_set.profile, route + "_device")
        return next((d for d in self.devices() if f"{d.name} [{d.host_api}]" == identity), None)

    def unsupported(self, route="primary"):
        if self.preview:
            return "GUI preview: audio output is disabled."
        p = self.cue_set.profile
        if p.errors():
            return "; ".join(p.errors())
        if len(p.buses) != 1 or p.buses[0].shape != "stereo" or p.buses[0].channels != [1, 2]:
            return "Multibus, mono, and custom channel playback are not connected in this GUI pass. Use one stereo Main bus on channels 1, 2 for playback."
        if route == "backup" and (p.backup_shape != "stereo" or p.backup_channels != [1, 2]):
            return "This backend supports only a stereo backup on channels 1, 2."
        dev = self.device(route)
        if dev is None:
            return f"{route.title()} device unavailable. Choose its device in Profile & Routing."
        if max(p.buses[0].channels) > dev.max_output_channels:
            return "Selected device does not have the mapped output channels."
        return ""

    def prepare(self, route="primary"):
        self.sync()
        reason = self.unsupported(route)
        if reason:
            self.message = reason
            log.warning("ROUTE UNAVAILABLE route=%s device=%r reason=%s", route, getattr(self.cue_set.profile, route + '_device'), reason)
            return False
        # Edit/Show/Rehearse share the exact same prepared endpoint. Keep its
        # silent stream alive rather than reopening it for every mode or TEST.
        reusable = (route == self.route and self.audio.ready and self.backend.stream is not None
                    and self.backend.stream.running)
        if not reusable:
            if self.engine:
                self.engine.interrupt_output()
            else:
                self.audio.stop_all()
            self.audio.set_ready(False)
            self.backend.stop()
        if not reusable and not self.backend.select_device(self.device(route).index):
            self.message = self.backend.output_lost_reason or "Output preparation failed."
            return False
        self.route = route
        p = self.cue_set.profile
        level = p.buses[0].level
        if route == "backup":
            level *= p.backup_levels.get(p.buses[0].id, 0)
        # Reuse the legacy scalar internally ONLY for this one-bus adapter.
        self.audio.mixer.set_master_level(level)
        if not reusable:
            log.info("ROUTE PREPARED route=%s device=%r bus_level=%s confirmed=%s", route, getattr(p, route + '_device'), level, sorted(self.confirmations))
        self.message = f"{route.upper()} prepared — {self.device(route).name}"
        return True

    def _lost(self, reason):
        if self.engine:
            self.engine.interrupt_output()
        else:
            self.audio.stop_all()
        self.audio.set_ready(False)
        self.message = f"AUDIO OUTPUT LOST — {getattr(self.cue_set.profile, self.route + '_device')}: {reason}"
        self.confirmations.clear()
        self.played.clear()

    def unconfirmed(self):
        self.sync()
        return [b.name for b in self.cue_set.profile.buses if b.id not in self.confirmations]

    def play_test(self, key):
        route = "backup" if key == "backup" else "primary"
        self.stop_test()
        if not self.prepare(route):
            return False
        sr = self.audio.mixer.sample_rate
        t = np.arange(sr * 2) / sr
        envelope = np.minimum(t / .03, 1) * np.minimum((2 - t) / .03, 1)
        tone = (.08 * np.sin(2 * np.pi * 440 * t) * envelope).astype(np.float32)
        # Left then right allows separate physical stereo-path confirmation.
        pcm = np.zeros((len(t), 2), dtype=np.float32)
        pcm[:sr, 0] = tone[:sr]
        pcm[sr:, 1] = tone[sr:]
        cue = Cue("0.0", name="Audio path test", bus_ids=[self.cue_set.profile.buses[0].id])
        try:
            self._test = self.audio.start(cue, pcm=pcm, sample_rate=sr)
            self._test.is_test = True
            self.played.add(key)
            self.message = "Test signal sent: left, then right. Listen at the board; meters do not confirm audibility."
            return True
        except Exception as exc:
            self.message = f"Test could not start: {exc}"
            return False

    def confirm(self, key):
        self.sync()
        if key not in self.played or not self.audio.ready:
            return False
        self.confirmations.add(key)
        return True

    def stop_test(self):
        if self._test is not None:
            self.audio.stop_instance(self._test)
            self._test = None
