"""Audio engine: simultaneous playback, mixing, fades, master level, metering.

Spec references: Sections 6, 6A, 9, 15 (Program Prompt Version 0.1).

Design:
- A Mixer owns active Voice objects and produces float32 stereo blocks.
- Each Voice plays decoded float32 PCM, applies cue volume, fade-in/out
  envelopes, start/end segment positions, and looping.
- AudioEngine resolves play-relative audio references against base_path
  (the play folder) and preloads the Armed Cue on a background thread so GO
  starts with minimal latency (Section 15).
- The Mixer applies the Master Output Level to the combined mix and taps
  per-channel peak levels for metering (post-master). Each Voice also taps
  its own post-fade peaks for per-instance meters (Section 8).
- Completion reporting is unified: every instance end (natural, stopped, or
  faded) fires on_instance_ended(instance, natural) so the cue engine can
  release waits and finish FADE cues (Sections 3, 4).
- A null backend renders blocks offline so tests run headless; the real
  backend streams the same mixer through sounddevice/PortAudio.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

try:
    import soundfile as sf
except Exception:  # pragma: no cover - soundfile optional at import time
    sf = None

from ..cues.model import Cue

SAMPLE_RATE = 44100
BLOCK = 1024


@dataclass
class MeterReading:
    """Per-channel peak in dBFS for one rendered block."""
    left_db: float = -np.inf
    right_db: float = -np.inf
    clipped: bool = False


class Voice:
    """One active playback instance of a cue's configured segment."""

    def __init__(self, cue: Cue, pcm: np.ndarray, sample_rate: int,
                 target_rate: Optional[int] = None):
        """pcm: float32 (frames, channels). Resampled to target_rate so every
        voice mixes at one output rate (Section 6)."""
        if target_rate and target_rate != sample_rate and pcm.shape[0] > 1:
            pcm = resample_linear(pcm, sample_rate, target_rate)
            sample_rate = target_rate
        self.cue = cue
        self.pcm = pcm
        self.sample_rate = sample_rate
        self.channels = pcm.shape[1]
        self.pos = 0
        self.frames = pcm.shape[0]
        self.looping = cue.loop
        self.fading = False
        self.stopped = False
        self.completed_naturally = False
        self.total_played_frames = 0  # cumulative, for loop elapsed time
        # per-instance meter peaks, post cue-volume/fades (Section 8)
        self.last_peak_l = 0.0
        self.last_peak_r = 0.0
        self._fade_remaining = 0
        self._fade_total = 0
        # Fade-out start level captures ONLY the fade-in envelope factor, not
        # the cue volume; volume is applied separately in render (fixes the
        # double-multiplied fade gain).
        self._fade_from_env = 1.0
        self._gain = float(cue.volume)
        self.fade_out_duration = float(cue.fade_out)  # snapshot at start
        self._fade_in_remaining = int(cue.fade_in * sample_rate) if cue.fade_in > 0 else 0
        self._fade_in_total = self._fade_in_remaining

    # -- control ---------------------------------------------------------
    def start_fade_out(self, duration: float) -> None:
        frames = int(duration * self.sample_rate)
        if frames <= 0:
            self.stopped = True  # zero duration = immediate stop (Section 5)
            return
        self.fading = True
        self._fade_total = frames
        self._fade_remaining = frames
        self._fade_from_env = self._fade_in_factor()

    def stop(self) -> None:
        self.stopped = True

    # -- render ----------------------------------------------------------
    def _fade_in_factor(self) -> float:
        """0..1 ramp factor from fade-in only (excludes cue volume)."""
        if self._fade_in_total and self._fade_in_remaining > 0:
            done = self._fade_in_total - self._fade_in_remaining
            return done / self._fade_in_total
        return 1.0

    def render(self, nframes: int) -> np.ndarray:
        """Return float32 (nframes, channels) with gain/fades applied."""
        out = np.zeros((nframes, self.channels), dtype=np.float32)
        if self.stopped:
            self.last_peak_l = self.last_peak_r = 0.0
            return out
        written = 0
        while written < nframes and not self.stopped:
            chunk = min(nframes - written, self.frames - self.pos)
            if chunk <= 0:
                if self.looping:
                    self.pos = 0
                    continue
                self.completed_naturally = True
                self.stopped = True
                break
            seg = self.pcm[self.pos:self.pos + chunk] * self._gain
            # fade-in ramp
            if self._fade_in_remaining > 0 and self._fade_in_total:
                idx = np.arange(chunk, dtype=np.float32)
                start_done = self._fade_in_total - self._fade_in_remaining
                fi = np.clip((start_done + idx) / self._fade_in_total, 0.0, 1.0)
                seg = seg * fi[:, None]
                self._fade_in_remaining = max(0, self._fade_in_remaining - chunk)
            # fade-out ramp (from the envelope level when the fade began)
            if self.fading and self._fade_total:
                idx = np.arange(chunk, dtype=np.float32)
                rem = np.clip(self._fade_remaining - idx, 0.0, None)
                fo = self._fade_from_env * (rem / self._fade_total)
                seg = seg * fo[:, None]
                self._fade_remaining -= chunk
                if self._fade_remaining <= 0:
                    self.stopped = True
            out[written:written + chunk] = seg
            self.pos += chunk
            self.total_played_frames += chunk
            written += chunk
            if self.stopped:
                break
        self._tap_peaks(out)
        return out

    def _tap_peaks(self, block: np.ndarray) -> None:
        if block.shape[0] == 0:
            self.last_peak_l = self.last_peak_r = 0.0
            return
        self.last_peak_l = float(np.max(np.abs(block[:, 0])))
        if block.shape[1] > 1:
            self.last_peak_r = float(np.max(np.abs(block[:, 1])))
        else:
            self.last_peak_r = self.last_peak_l

    @property
    def active(self) -> bool:
        return not self.stopped

    # -- progress for UI (Section 9) --------------------------------------
    @property
    def duration_seconds(self) -> float:
        return self.frames / float(self.sample_rate) if self.sample_rate else 0.0

    @property
    def position_seconds(self) -> float:
        """Position within the current iteration (for loops)."""
        return self.pos / float(self.sample_rate) if self.sample_rate else 0.0

    @property
    def total_elapsed_seconds(self) -> float:
        """Cumulative playback time, including across loop iterations."""
        return self.total_played_frames / float(self.sample_rate) if self.sample_rate else 0.0

    @property
    def progress_fraction(self) -> float:
        if self.frames <= 0:
            return 0.0
        return min(1.0, self.pos / float(self.frames))

    @property
    def remaining_seconds(self) -> Optional[float]:
        """None for looping sounds (no finite remaining for the whole)."""
        if self.looping:
            return None
        return max(0.0, self.duration_seconds - self.position_seconds)


class Mixer:
    """Mixes active voices to stereo and applies the Master Output Level."""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.voices: list[Voice] = []
        self.master_level: float = 1.0
        self.last_meter = MeterReading()
        self._lock = threading.Lock()
        self.on_voice_finished: Optional[Callable[[Voice], None]] = None

    def set_master_level(self, level: float) -> None:
        self.master_level = max(0.0, float(level))

    def add_voice(self, voice: Voice) -> None:
        with self._lock:
            self.voices.append(voice)

    def stop_all(self) -> None:
        with self._lock:
            for v in self.voices:
                v.stop()

    def clear_all(self) -> None:
        """Stop AND drop every voice immediately (used on output loss so
        nothing can resume on reconnection, Section 15)."""
        with self._lock:
            for v in self.voices:
                v.stop()
            self.voices.clear()

    def _to_stereo(self, block: np.ndarray) -> np.ndarray:
        if block.shape[1] == 2:
            return block
        return np.repeat(block, 2, axis=1)

    def render_block(self, nframes: int = BLOCK) -> np.ndarray:
        mix = np.zeros((nframes, 2), dtype=np.float32)
        finished: list[Voice] = []
        with self._lock:
            for v in self.voices:
                if not v.active:
                    finished.append(v)
                    continue
                mix += self._to_stereo(v.render(nframes))
                # a voice that finished during this render notifies promptly,
                # not one block late
                if not v.active and v not in finished:
                    finished.append(v)
            for v in finished:
                if v in self.voices:
                    self.voices.remove(v)
        mix *= self.master_level
        peak_l = float(np.max(np.abs(mix[:, 0]))) if nframes else 0.0
        peak_r = float(np.max(np.abs(mix[:, 1]))) if nframes else 0.0
        self.last_meter = MeterReading(
            left_db=_to_db(peak_l), right_db=_to_db(peak_r),
            clipped=(peak_l >= 1.0 or peak_r >= 1.0),
        )
        for v in finished:
            if self.on_voice_finished:
                self.on_voice_finished(v)
        return mix


def _to_db(peak: float) -> float:
    if peak <= 1e-7:
        return -np.inf
    return float(20.0 * np.log10(peak))


def resample_linear(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample float32 (frames, channels) via linear interpolation.

    Adequate for cue playback; keeps every voice at one output rate so
    mixed sample-rate files coexist correctly (Section 6).
    """
    if src_rate == dst_rate or pcm.shape[0] == 0:
        return pcm
    n_src = pcm.shape[0]
    n_dst = max(1, int(round(n_src * dst_rate / src_rate)))
    src_idx = np.linspace(0.0, n_src - 1, num=n_dst)
    base = np.floor(src_idx).astype(np.int64)
    frac = (src_idx - base).astype(np.float32)[:, None]
    nxt = np.minimum(base + 1, n_src - 1)
    out = pcm[base] * (1.0 - frac) + pcm[nxt] * frac
    return out.astype(np.float32)


def load_segment_mono_or_stereo(path: str, cue: Cue) -> tuple[np.ndarray, int]:
    """Decode the cue's configured segment to float32 PCM. Returns
    (pcm, sample_rate). Raises on missing/unreadable files or bad segments.

    WAV/FLAC/MP3/OGG decode via libsndfile; AAC/M4A (unsupported by
    libsndfile) fall back to PyAV/FFmpeg (Section 6).
    """
    if sf is None:  # pragma: no cover
        raise RuntimeError("soundfile not available")
    try:
        info = sf.info(path)
        sr = info.samplerate
        total_frames = info.frames
        reader = lambda s, n: sf.read(path, start=s, frames=n, dtype="float32",
                                      always_2d=True)  # noqa: E731
    except Exception:
        return _load_segment_av(path, cue)
    start = int((cue.start_position or 0.0) * sr)
    end = int(cue.end_position * sr) if cue.end_position is not None else total_frames
    if start >= total_frames:
        raise ValueError(
            f"Start position {start / sr:.2f}s is beyond the file duration "
            f"{total_frames / sr:.2f}s")
    end = min(end, total_frames)
    if end <= start:
        raise ValueError("Empty segment: Start must be before End")
    data, sr = reader(start, end - start)
    return data, sr


def _load_segment_av(path: str, cue: Cue) -> tuple[np.ndarray, int]:
    """AAC/M4A decode via PyAV. Decodes the file, then slices the segment."""
    try:
        import av
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"Cannot decode '{path}': libsndfile rejected it and "
                           "PyAV is not installed") from exc
    container = av.open(path)
    try:
        stream = next(s for s in container.streams if s.type == "audio")
        sr = stream.codec_context.sample_rate or SAMPLE_RATE
        chunks = []
        for frame in container.decode(stream):
            arr = frame.to_ndarray()  # (channels, samples) or (samples,)
            if arr.ndim == 1:
                arr = arr[None, :]
            chunks.append(arr.T.astype(np.float32))
        if not chunks:
            raise RuntimeError(f"no audio frames decoded from '{path}'")
        pcm = np.vstack(chunks)
        # normalize integer formats to float range if needed
        if np.abs(pcm).max() > 2.0:
            pcm = pcm / 32768.0
    finally:
        container.close()
    start = int((cue.start_position or 0.0) * sr)
    end = int(cue.end_position * sr) if cue.end_position is not None else pcm.shape[0]
    if start >= pcm.shape[0]:
        raise ValueError(
            f"Start position {start / sr:.2f}s is beyond the file duration "
            f"{pcm.shape[0] / sr:.2f}s")
    end = min(end, pcm.shape[0])
    if end <= start:
        raise ValueError("Empty segment: Start must be before End")
    return pcm[start:end].copy(), sr


@dataclass
class _Prepared:
    pcm: np.ndarray
    sample_rate: int
    key: tuple


class AudioEngine:
    """Concrete engine used by CueEngine.

    - base_path: play folder; play-relative cue.audio_file references resolve
      against it (Sections 5, 16). If unset, references resolve as given.
    - The Armed Cue is decoded/resampled on a background thread (prepare) so
      GO starts immediately (Section 15).
    - on_instance_ended(instance, natural) fires for EVERY instance end, so
      the cue engine can release On Complete waits on early stops and finish
      FADE cues when their fades complete (Sections 3, 4).
    """

    def __init__(self, mixer: Optional[Mixer] = None, ready: bool = True,
                 base_path: Optional[Path] = None):
        self.mixer = mixer or Mixer()
        self._ready = ready
        self.base_path = Path(base_path) if base_path else None
        self._instances: dict[int, tuple[Voice, object]] = {}
        self._counter = 0
        self._prepared: dict[tuple, _Prepared] = {}
        self._prepare_errors: dict[tuple, str] = {}
        self._prep_lock = threading.Lock()
        self.on_instance_ended: Optional[Callable[[object, bool], None]] = None
        self.mixer.on_voice_finished = self._voice_finished

    @property
    def ready(self) -> bool:
        return self._ready

    def set_ready(self, ready: bool) -> None:
        self._ready = ready

    # -- path resolution ---------------------------------------------------
    def resolve_audio_path(self, audio_file: str) -> Path:
        p = Path(audio_file)
        if not p.is_absolute() and self.base_path is not None:
            p = self.base_path / p
        return p

    # -- preparation / preload ---------------------------------------------
    def _prep_key(self, cue: Cue) -> tuple:
        return (cue.internal_id, cue.audio_file, cue.start_position,
                cue.end_position, cue.volume, cue.fade_in, cue.loop)

    def prepare_async(self, cue: Cue) -> None:
        """Decode+resample the cue off the calling thread (Section 15)."""
        if cue.audio_file is None:
            return
        key = self._prep_key(cue)
        with self._prep_lock:
            if key in self._prepared:
                return
        t = threading.Thread(target=self._prepare_sync, args=(cue, key),
                             daemon=True)
        t.start()

    def _prepare_sync(self, cue: Cue, key: tuple) -> None:
        try:
            pcm, sr = load_segment_mono_or_stereo(
                str(self.resolve_audio_path(cue.audio_file)), cue)
            if sr != self.mixer.sample_rate and pcm.shape[0] > 1:
                pcm = resample_linear(pcm, sr, self.mixer.sample_rate)
                sr = self.mixer.sample_rate
            with self._prep_lock:
                self._prepared[key] = _Prepared(pcm, sr, key)
                self._prepare_errors.pop(key, None)
        except Exception as exc:
            with self._prep_lock:
                self._prepare_errors[key] = str(exc)

    def prepare_blocking(self, cue: Cue) -> None:
        """Prepare now (used by GO when the preload has not finished)."""
        key = self._prep_key(cue)
        with self._prep_lock:
            done = key in self._prepared
        if not done:
            self._prepare_sync(cue, key)
        with self._prep_lock:
            err = self._prepare_errors.get(key)
        if err:
            raise RuntimeError(err)

    # -- playback ------------------------------------------------------------
    def start(self, cue: Cue, pcm: Optional[np.ndarray] = None,
              sample_rate: int = SAMPLE_RATE):
        """Start a cue. The caller should decode/verify (via decode_cue)
        BEFORE applying destructive behavior; see CueEngine._go_play."""
        from ..cues.engine import SoundInstance
        if pcm is None:
            if not cue.audio_file:
                raise ValueError("cue has no audio file and no pcm supplied")
            pcm, sample_rate = self.decode_cue(cue)
            voice = Voice(cue, pcm, sample_rate)  # already at mixer rate
        else:
            voice = Voice(cue, pcm, sample_rate, target_rate=self.mixer.sample_rate)
        self.mixer.add_voice(voice)
        inst = SoundInstance(
            cue_internal_id=cue.internal_id,
            identifier=cue.identifier,
            name=cue.name,
            looping=cue.loop,
        )
        self._instances[self._counter] = (voice, inst)
        self._counter += 1
        return inst

    def decode_cue(self, cue: Cue) -> tuple[np.ndarray, int]:
        """Decode+resample a cue to mixer rate, using the prepared cache.
        Raises on failure. Call before applying destructive behavior."""
        key = self._prep_key(cue)
        with self._prep_lock:
            prepared = self._prepared.get(key)
        if prepared is None:
            self.prepare_blocking(cue)
            with self._prep_lock:
                prepared = self._prepared.get(key)
        if prepared is None:
            raise RuntimeError(self._prepare_errors.get(key, "preparation failed"))
        return prepared.pcm, prepared.sample_rate

    def start_prepared(self, cue: Cue, pcm: np.ndarray, sample_rate: int):
        """Start an already-decoded cue (no decode on the GO path)."""
        return self.start(cue, pcm=pcm, sample_rate=sample_rate)

    def start_from_path(self, path: str, cue: Cue):
        """Audition/TEST playback straight from a file path (Section 13).

        Isolated from the show: it does not touch the Armed Cue, completion
        states, or pointer, and its end does not drive show advancement.
        """
        pcm, sr = load_segment_mono_or_stereo(path, cue)
        inst = self.start(cue, pcm=pcm, sample_rate=sr)
        inst.is_test = True
        return inst

    def _find(self, instance) -> Optional[Voice]:
        for voice, inst in self._instances.values():
            if inst is instance:
                return voice
        return None

    def voice_for(self, instance) -> Optional[Voice]:
        """Public accessor for the UI (per-instance progress/meters)."""
        return self._find(instance)

    def stop_instance(self, instance) -> None:
        v = self._find(instance)
        if v:
            v.stop()
            instance.stopped = True
            self._drop(instance)
            self._emit_ended(instance, natural=False)

    def fade_instance(self, instance, duration: float) -> None:
        v = self._find(instance)
        if v:
            if duration <= 0:
                # zero duration = immediate stop (Section 5)
                self.stop_instance(instance)
                return
            v.start_fade_out(duration)
            instance.fading = True

    def stop_all(self) -> None:
        ended = [inst for voice, inst in list(self._instances.values())]
        self.mixer.stop_all()
        for inst in ended:
            inst.stopped = True
        self._instances.clear()
        for inst in ended:
            self._emit_ended(inst, natural=False)

    def active_instances(self):
        return [inst for voice, inst in self._instances.values() if voice.active]

    def instances_of(self, cue_internal_id: str):
        return [inst for voice, inst in self._instances.values()
                if inst.cue_internal_id == cue_internal_id and voice.active]

    def _drop(self, instance) -> None:
        for k, (v, inst) in list(self._instances.items()):
            if inst is instance:
                del self._instances[k]

    def _emit_ended(self, instance, natural: bool) -> None:
        if self.on_instance_ended:
            self.on_instance_ended(instance, natural)

    def _voice_finished(self, voice: Voice) -> None:
        for k, (v, inst) in list(self._instances.items()):
            if v is voice:
                inst.completed_naturally = voice.completed_naturally
                del self._instances[k]
                # fires for natural end AND fade-completed stops
                self._emit_ended(inst, natural=voice.completed_naturally)
                return
