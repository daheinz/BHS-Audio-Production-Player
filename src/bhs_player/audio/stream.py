"""Real-time audio output via sounddevice/PortAudio (Section 15).

Wraps the Mixer in an OutputStream. Provides device enumeration/selection,
output-loss detection (never silently redirects), and master metering.

The engine never auto-switches devices: if the selected device disappears,
ready flips False and the operator must deliberately select a replacement.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

from .engine import BLOCK, SAMPLE_RATE, MeterReading, Mixer, _to_db


@dataclass
class OutputDevice:
    index: int
    name: str
    host_api: str
    max_output_channels: int
    default_samplerate: float


def list_output_devices() -> list[OutputDevice]:
    """Enumerate available Windows output devices (Section 15)."""
    if sd is None:
        return []
    devices = []
    apis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            api_name = apis[d["hostapi"]]["name"]
            devices.append(OutputDevice(
                index=i,
                name=d["name"],
                host_api=api_name,
                max_output_channels=d["max_output_channels"],
                default_samplerate=d["default_samplerate"],
            ))
    return devices


def default_output_device() -> Optional[OutputDevice]:
    devs = list_output_devices()
    return devs[0] if devs else None


class OutputStream:
    """Streams the Mixer's output to a selected device.

    on_output_lost is invoked (from the audio callback thread) if the stream
    hits a device error; the app must surface AUDIO OUTPUT LOST and disable GO.
    """

    def __init__(self, mixer: Mixer, device_index: Optional[int] = None,
                 sample_rate: int = SAMPLE_RATE, blocksize: int = BLOCK):
        self.mixer = mixer
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self._stream: Optional["sd.OutputStream"] = None
        self._running = False
        self._lost = threading.Event()
        self.last_meter = MeterReading()
        self.on_output_lost: Optional[Callable[[str], None]] = None
        self.on_meter: Optional[Callable[[MeterReading], None]] = None

    @property
    def running(self) -> bool:
        return self._running and not self._lost.is_set()

    @property
    def device_name(self) -> str:
        if sd is None or self.device_index is None:
            return "(none)"
        try:
            return sd.query_devices(self.device_index)["name"]
        except Exception:
            return "(unknown)"

    def start(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice not available")
        if self._running:
            return
        self._lost.clear()
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            device=self.device_index,
            channels=2,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _callback(self, outdata, frames, time_info, status) -> None:
        # PortAudio status flags catch device removal even when no exception
        # is raised (e.g. priming/underflow errors on a vanished device).
        if status and getattr(status, "output_underflow", False) is False:
            status_text = str(status)
            if any(k in status_text.lower() for k in ("error", "abort", "overflow")):
                self._signal_lost(f"device status: {status_text}")
                outdata[:] = 0
                return
        try:
            block = self.mixer.render_block(frames)
            if block.shape[0] != frames:
                padded = np.zeros((frames, 2), dtype=np.float32)
                padded[: block.shape[0]] = block
                block = padded
            outdata[:] = block
            self.last_meter = self.mixer.last_meter
            if self.on_meter:
                self.on_meter(self.mixer.last_meter)
        except Exception as exc:  # device vanished mid-stream etc.
            outdata[:] = 0
            self._signal_lost(str(exc) or "audio output lost")

    def _signal_lost(self, reason: str) -> None:
        if not self._lost.is_set():
            self._lost.set()
            self._running = False
            # Existing voices must NOT resume when a replacement output starts
            # (Section 15): clear them. Missed cues are not auto-replayed.
            try:
                self.mixer.clear_all()
            except Exception:
                pass
            if self.on_output_lost:
                self.on_output_lost(reason)


class StreamingAudioBackend:
    """Glue between AudioEngine and a real OutputStream. Owns device choice
    and readiness (Section 15).

    Device identity is stable: remembered by name + host API, not list index,
    so a reordered Windows device list doesn't silently pick the wrong output.
    """

    def __init__(self, engine):
        self.engine = engine
        self.stream: Optional[OutputStream] = None
        self.output_lost: bool = False
        self.output_lost_reason: str = ""
        self.on_output_lost: Optional[Callable[[str], None]] = None
        self.selected_identity: Optional[str] = None  # stable "name [api]"

    def select_device(self, device_index: Optional[int]) -> bool:
        """Deliberately select and prepare a device. Returns True on success.
        Never auto-switches; a failed selection leaves the engine not ready."""
        self.stop()
        self.output_lost = False
        self.output_lost_reason = ""
        try:
            self.stream = OutputStream(self.engine.mixer, device_index=device_index)
            self.stream.on_output_lost = self._handle_lost
            self.stream.start()
            self.engine.set_ready(True)
            self.selected_identity = self._identity_of(device_index)
            return True
        except Exception as exc:
            self.engine.set_ready(False)
            self.stream = None
            self.output_lost = True
            self.output_lost_reason = str(exc)
            return False

    @staticmethod
    def _identity_of(device_index: Optional[int]) -> Optional[str]:
        if sd is None or device_index is None:
            return None
        try:
            d = sd.query_devices(device_index)
            api = sd.query_hostapis(d["hostapi"])["name"]
            return f"{d['name']} [{api}]"
        except Exception:
            return None

    def find_device_by_identity(self, identity: str) -> Optional[int]:
        """Resolve a remembered stable identity to a current device index."""
        for dev in list_output_devices():
            if self._identity_of(dev.index) == identity:
                return dev.index
        return None

    def _handle_lost(self, reason: str) -> None:
        self.output_lost = True
        self.output_lost_reason = reason
        self.engine.set_ready(False)
        # Voices were already cleared in the stream's loss handler; make sure
        # the engine's instance registry is emptied too so nothing "resumes".
        try:
            self.engine._instances.clear()
        except Exception:
            pass
        if self.on_output_lost:
            self.on_output_lost(reason)

    def stop(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream = None
