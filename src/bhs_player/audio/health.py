"""Lightweight audio callback measurements. No logging, Qt, or disk I/O."""
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class HealthSnapshot:
    running: bool
    load: float
    peak_load: float
    underflows: int
    overruns: int
    clipped_blocks: int
    callbacks: int
    last_underflow: float
    last_overrun: float
    last_clip: float
    sample_rate: int
    blocksize: int
    latency: float | None

    def status(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.running:
            return "Not running", "neutral"
        if not self.callbacks:
            return "Waiting for audio", "neutral"
        if self.underflows and now-self.last_underflow < 5:
            return "DROPOUT", "error"
        if self.clipped_blocks and now-self.last_clip < 5:
            return "CLIPPING", "error"
        if self.load >= .7 or (self.overruns and now-self.last_overrun < 5):
            return "HIGH LOAD", "warning"
        return "Normal", "success"


class AudioHealth:
    def __init__(self):
        self.load = self.peak_load = 0.0
        self.underflows = self.overruns = self.clipped_blocks = self.callbacks = 0
        self.last_underflow = self.last_overrun = self.last_clip = 0.0

    def record(self, elapsed, frames, sample_rate, underflow=False, clipped=False):
        now = time.monotonic()
        load = elapsed / (frames/sample_rate) if frames and sample_rate else 0.0
        self.load = load if not self.callbacks else .9*self.load + .1*load
        self.peak_load = max(self.peak_load, load)
        self.callbacks += 1
        if underflow:
            self.underflows += 1
            self.last_underflow = now
        if load >= 1:
            self.overruns += 1
            self.last_overrun = now
        if clipped:
            self.clipped_blocks += 1
            self.last_clip = now
