"""Output device flow and resampling tests (Sections 6, 15)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from bhs_player.audio.engine import AudioEngine, Mixer, resample_linear
from bhs_player.audio.stream import StreamingAudioBackend
from bhs_player.cues.engine import CueEngine
from bhs_player.cues.model import ActionType, Cue, CueSet
from bhs_player.ui.main_window import MainWindow

SR = 44100


def tone(seconds, amp=0.5, sr=SR):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    mono = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def play(identifier, **kw):
    return Cue(identifier=identifier, action=ActionType.PLAY, **kw)


# ---- resampling ---------------------------------------------------------

def test_resample_same_rate_is_identity():
    pcm = tone(0.1)
    out = resample_linear(pcm, SR, SR)
    assert out is pcm


def test_resample_48k_to_44k1_length_and_shape():
    pcm = tone(1.0, sr=48000)
    out = resample_linear(pcm, 48000, SR)
    assert out.shape[1] == 2
    assert abs(out.shape[0] - SR) <= 2  # ~1 second at target rate


def test_mixed_sample_rates_mix_correctly():
    mixer = Mixer(SR)
    eng = AudioEngine(mixer)
    eng.start(play("1.0"), pcm=tone(0.5, sr=48000), sample_rate=48000)
    eng.start(play("2.0"), pcm=tone(0.5, sr=SR), sample_rate=SR)
    out = mixer.render_block(1024)
    assert out.shape == (1024, 2)
    assert float(np.max(np.abs(out))) > 0.1  # both voices audible


# ---- streaming backend readiness / output loss ---------------------------

class FakeStream:
    """Stands in for OutputStream without touching real hardware."""
    def __init__(self, name="Fake USB Interface"):
        self._name = name
        self._running = True
        self.on_output_lost = None
        self.on_meter = None

    @property
    def running(self):
        return self._running

    @property
    def device_name(self):
        return self._name

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def simulate_loss(self, reason="device unplugged"):
        self._running = False
        if self.on_output_lost:
            self.on_output_lost(reason)


def test_backend_select_device_success_marks_ready(monkeypatch):
    eng = AudioEngine(Mixer(SR), ready=False)
    backend = StreamingAudioBackend(eng)
    monkeypatch.setattr("bhs_player.audio.stream.OutputStream",
                        lambda *a, **k: FakeStream())
    assert backend.select_device(3)
    assert eng.ready
    assert not backend.output_lost


def test_backend_select_device_failure_not_ready(monkeypatch):
    eng = AudioEngine(Mixer(SR), ready=False)
    backend = StreamingAudioBackend(eng)

    class Boom:
        def __init__(self, *a, **k):
            pass
        def start(self):
            raise RuntimeError("no such device")
        def stop(self):
            pass

    monkeypatch.setattr("bhs_player.audio.stream.OutputStream", Boom)
    assert not backend.select_device(99)
    assert not eng.ready
    assert backend.output_lost


def test_output_lost_disables_go(monkeypatch):
    eng_audio = AudioEngine(Mixer(SR), ready=False)
    backend = StreamingAudioBackend(eng_audio)
    stream = FakeStream()
    monkeypatch.setattr("bhs_player.audio.stream.OutputStream",
                        lambda *a, **k: stream)
    backend.select_device(0)
    cs = CueSet(play_name="Clue", cues=[play("1.0")])
    engine = CueEngine(cs, eng_audio)
    assert engine.go_available()[0]
    # device vanishes mid-show
    stream.simulate_loss("USB device removed")
    backend._handle_lost("USB device removed")
    ok, reason = engine.go_available()
    assert not ok
    assert "not ready" in reason


def test_no_silent_switch_on_loss(monkeypatch):
    """After loss, engine must not redirect to another device automatically."""
    eng_audio = AudioEngine(Mixer(SR), ready=False)
    backend = StreamingAudioBackend(eng_audio)
    stream = FakeStream()
    monkeypatch.setattr("bhs_player.audio.stream.OutputStream",
                        lambda *a, **k: stream)
    backend.select_device(0)
    backend._handle_lost("gone")
    assert not eng_audio.ready
    assert backend.output_lost
    # no new stream created automatically
    assert backend.stream is stream


# ---- UI banner ----------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_output_lost_banner_appears(qapp, monkeypatch):
    eng_audio = AudioEngine(Mixer(SR), ready=False)
    backend = StreamingAudioBackend(eng_audio)
    cs = CueSet(play_name="Clue", cues=[play("1.0")])
    engine = CueEngine(cs, eng_audio)
    win = MainWindow(cs, engine, eng_audio, backend)
    backend.output_lost = True
    backend.output_lost_reason = "USB Audio Interface disconnected"
    win._show_output_lost("USB Audio Interface disconnected")
    # isHidden() reflects the widget flag even when the window isn't shown
    assert not win.output_banner.isHidden()
    assert "AUDIO OUTPUT LOST" in win.output_banner.text()
    assert not win.go_btn.isEnabled()


def test_device_label_shows_running_stream(qapp, monkeypatch):
    eng_audio = AudioEngine(Mixer(SR), ready=False)
    backend = StreamingAudioBackend(eng_audio)
    stream = FakeStream("USB Audio Interface")
    monkeypatch.setattr("bhs_player.audio.stream.OutputStream",
                        lambda *a, **k: stream)
    backend.select_device(0)
    cs = CueSet(play_name="Clue", cues=[play("1.0")])
    engine = CueEngine(cs, eng_audio)
    win = MainWindow(cs, engine, eng_audio, backend)
    win._refresh()
    assert "USB Audio Interface" in win.device_lbl.text()
    assert win.output_banner.isHidden()
    assert win.go_btn.isEnabled()
