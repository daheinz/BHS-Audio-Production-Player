"""Audio callback telemetry and logs must not change playback or write on audio thread."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import logging
import threading
import numpy as np
import pytest
from PySide6.QtCore import Qt
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.audio.stream import OutputStream, StreamingAudioBackend
from bhs_player.audio.health import AudioHealth, HealthSnapshot
from bhs_player.cues.model import Cue
from bhs_player import diagnostics
from bhs_player.ui.audio_health import AudioHealthPanel, DiagnosticsDialog


def stream_with_tone(amp=.1):
    audio = AudioEngine(Mixer())
    inst = audio.start(Cue("7.0"), pcm=np.ones((44100, 2), dtype=np.float32)*amp)
    stream = OutputStream(audio.mixer)
    stream._running = True
    backend = StreamingAudioBackend(audio)
    backend.stream = stream
    backend.selected_identity = "Controlled test output"
    stream.on_output_lost = backend._handle_lost
    return audio, inst, stream, backend


def test_underflow_is_counted_without_stopping_or_logging_in_callback(caplog):
    audio, inst, stream, backend = stream_with_tone()
    out = np.zeros((1024, 2), dtype=np.float32)
    with caplog.at_level(logging.INFO, logger="bhs_player"):
        stream._callback(out, 1024, None, SimpleNamespace(output_underflow=True))
        assert not caplog.records
        np.testing.assert_allclose(out, .1)
        assert inst in audio.active_instances()
        snapshot = backend.poll_diagnostics(force=True)
        assert snapshot.underflows == 1
        assert snapshot.status()[0] == "DROPOUT"
        health = [r for r in caplog.records if "AUDIO HEALTH" in r.message]
        assert len(health) == 1
        assert "underflows=+1" in health[0].message
        assert "7.0" in health[0].message
        backend.poll_diagnostics(force=True)
        assert len([r for r in caplog.records if "AUDIO HEALTH" in r.message]) == 1


def test_clipping_and_over_budget_are_distinct_from_underflow(monkeypatch):
    audio, inst, stream, backend = stream_with_tone(1.2)
    ticks = iter([1.0, 1.05])
    monkeypatch.setattr("bhs_player.audio.stream.time.perf_counter", lambda: next(ticks))
    out = np.zeros((1024, 2), dtype=np.float32)
    stream._callback(out, 1024, None, None)
    snapshot = stream.health_snapshot()
    assert snapshot.underflows == 0
    assert snapshot.overruns == 1
    assert snapshot.clipped_blocks == 1
    assert snapshot.peak_load > 2
    assert snapshot.status()[0] == "CLIPPING"


def test_warning_hold_expires_but_counters_remain(monkeypatch):
    monkeypatch.setattr("bhs_player.audio.health.time.monotonic", lambda: 100)
    audio, inst, stream, backend = stream_with_tone()
    stream.health.record(.001, 1024, 44100, underflow=True)
    snapshot = stream.health_snapshot()
    assert snapshot.status(now=104)[0] == "DROPOUT"
    assert snapshot.status(now=106)[0] == "Normal"
    assert snapshot.underflows == 1
    assert replace(snapshot, load=.8).status(now=106)[0] == "HIGH LOAD"
    assert replace(snapshot, running=False).status()[0] == "Not running"


def test_portaudio_load_latency_and_unavailable_properties():
    audio, inst, stream, backend = stream_with_tone()
    stream._stream = SimpleNamespace(cpu_load=.82, latency=.1)
    snapshot = stream.health_snapshot()
    assert snapshot.load == .82 and snapshot.latency == .1
    class Gone:
        @property
        def cpu_load(self):
            raise RuntimeError("disconnected")
    stream._stream = Gone()
    assert stream.health_snapshot().load == stream.health.load


def test_output_loss_is_logged_by_control_poll_not_audio_callback(caplog):
    audio, inst, stream, backend = stream_with_tone()
    out = np.ones((1024, 2), dtype=np.float32)
    with caplog.at_level(logging.INFO, logger="bhs_player"):
        stream._callback(out, 1024, None, "device error")
        assert not caplog.records
        assert not np.any(out)
        assert backend.output_lost
        backend.poll_diagnostics(force=True)
        backend.poll_diagnostics(force=True)
        assert len([r for r in caplog.records if "OUTPUT LOST" in r.message]) == 1


@pytest.fixture
def local_logs(tmp_path, monkeypatch):
    diagnostics.shutdown_logging()
    monkeypatch.setattr(diagnostics, "_directory", tmp_path/"logs")
    monkeypatch.setattr(diagnostics, "_error", "")
    yield tmp_path/"logs"
    diagnostics.shutdown_logging()


def test_logs_rotate_and_file_io_is_on_listener_thread(local_logs, monkeypatch):
    writes = []
    original = diagnostics._FileHandler.emit
    def emit(handler, record):
        writes.append(threading.current_thread().name)
        return original(handler, record)
    monkeypatch.setattr(diagnostics._FileHandler, "emit", emit)
    diagnostics.configure_logging(local_logs)
    diagnostics._file_handler.maxBytes = 220
    for i in range(20):
        diagnostics.LOGGER.warning("Troubleshooting record %s %s", i, "x"*80)
    diagnostics.shutdown_logging()
    files = list(local_logs.glob("bhs-player.log*"))
    assert 1 < len(files) <= 5
    assert writes and all(name != threading.current_thread().name for name in writes)
    content = "".join(p.read_text(encoding="utf-8") for p in files)
    assert "Troubleshooting record 19" in content
    assert "Z WARNING" in content


def test_unwritable_log_location_is_reported_not_raised(tmp_path, local_logs):
    blocked = tmp_path/"file"
    blocked.write_text("not a directory")
    diagnostics.configure_logging(blocked)
    assert diagnostics.logging_error()


def test_monitor_shows_real_counts_and_preview_is_neutral(qtbot):
    audio, inst, stream, backend = stream_with_tone()
    stream.health.record(.001, 1024, 44100, underflow=True)
    panel = AudioHealthPanel(backend=backend)
    qtbot.addWidget(panel)
    panel.refresh()
    assert "DROPOUT" in panel.gauge.format()
    assert "Dropouts: 1" in panel.detail.text()
    assert panel._tone == "error"
    preview = AudioHealthPanel(backend=backend, preview=True)
    qtbot.addWidget(preview)
    assert preview._tone == "neutral"
    assert "Preview" in preview.gauge.format()
    empty = AudioHealthPanel()
    qtbot.addWidget(empty)
    assert "Unavailable" in empty.gauge.format()


def test_log_viewer_is_nonmodal_copies_report_and_opens_folder(qtbot, local_logs, monkeypatch):
    opened, copied = [], []
    monkeypatch.setattr("bhs_player.ui.audio_health.QDesktopServices.openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    monkeypatch.setattr("bhs_player.ui.audio_health.QApplication.clipboard", lambda: SimpleNamespace(setText=copied.append))
    audio, inst, stream, backend = stream_with_tone()
    dialog = DiagnosticsDialog(backend=backend)
    qtbot.addWidget(dialog)
    assert not dialog.isModal()
    assert str(local_logs) in dialog.path_label.text()
    dialog.copy_report()
    assert "CURRENT DIAGNOSTICS" in copied[0]
    assert "Controlled test output" in copied[0]
    dialog.open_folder()
    assert [Path(p) for p in opened] == [local_logs]
    assert dialog.text.isReadOnly()



def test_recorded_issue_log_contains_device_cues_and_totals(local_logs):
    diagnostics.configure_logging(local_logs)
    audio, inst, stream, backend = stream_with_tone()
    stream._callback(np.zeros((1024, 2), dtype=np.float32), 1024, None,
                     SimpleNamespace(output_underflow=True))
    backend.poll_diagnostics(force=True)
    diagnostics.shutdown_logging()
    text = diagnostics.read_log_tail()
    assert "underflows=+1 total=1" in text
    assert "Controlled test output" in text
    assert "7.0" in text
    assert "sample_rate=44100" in text


def test_logs_button_opens_nonmodal_without_stopping_audio(qtbot, local_logs):
    from bhs_player.cues.engine import CueEngine
    from bhs_player.cues.model import CueSet
    from bhs_player.ui.main_window import MainWindow
    audio, inst, stream, backend = stream_with_tone()
    cs = CueSet("Logs", [Cue("7.0")])
    win = MainWindow(cs, CueEngine(cs, audio), audio, backend, confirm_close=False)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    qtbot.mouseClick(win.audio_health.logs_button, Qt.LeftButton)
    dialog = win._diagnostics_dialog
    assert dialog.isVisible() and not dialog.isModal()
    assert inst in audio.active_instances()
    dialog.close()
    win.close()
