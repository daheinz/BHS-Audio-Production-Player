"""Reusable UI widgets: progress/playhead bar and audio level meters.

Progress is driven from actual playback position (Voice), not a display
timer (Section 9). Meters show post-master signal in dBFS.
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..audio.engine import Voice, _to_db


def format_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--.-"
    seconds = max(0.0, seconds)
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:04.1f}"


class ProgressBar(QWidget):
    """Horizontal progress bar with waveform and moving playhead (Sections 8-9)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._voice: Optional[Voice] = None
        self._waveform: Optional[list[float]] = None  # normalized peaks 0..1
        self.setMinimumHeight(36)

    def set_voice(self, voice: Optional[Voice]) -> None:
        self._voice = voice
        if voice is not None and self._waveform is None:
            self._waveform = compute_waveform_peaks(voice.pcm, buckets=200)
        if voice is None:
            self._waveform = None
        self.update()

    def clear(self) -> None:
        self.set_voice(None)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(24, 24, 24))

        # waveform
        if self._waveform:
            mid = h / 2
            amp = h / 2 - 2
            n = len(self._waveform)
            bw = w / n
            p.setPen(QPen(QColor(90, 140, 200)))
            for i, peak in enumerate(self._waveform):
                x = i * bw
                p.drawLine(int(x), int(mid - peak * amp),
                           int(x), int(mid + peak * amp))

        # progress fill
        frac = self._voice.progress_fraction if self._voice else 0.0
        p.fillRect(0, 0, int(w * frac), h, QColor(60, 90, 60, 120))

        # playhead
        if self._voice:
            x = int(w * frac)
            p.setPen(QPen(QColor(255, 220, 80), 2))
            p.drawLine(x, 0, x, h)

        p.setPen(QPen(QColor(70, 70, 70)))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


def compute_waveform_peaks(pcm, buckets: int = 200) -> list[float]:
    """Min/max-style peak envelope for the waveform (Section 8). Cached at
    load; not recomputed during playback."""
    import numpy as np
    if pcm is None or pcm.shape[0] == 0:
        return []
    mono = np.max(np.abs(pcm), axis=1)
    n = mono.shape[0]
    bucket = max(1, n // buckets)
    peaks = [float(np.max(mono[i:i + bucket])) for i in range(0, n, bucket)]
    mx = max(peaks) if peaks else 1.0
    return [p / mx if mx > 0 else 0.0 for p in peaks]


class LevelMeter(QWidget):
    """Stereo level meter with dBFS scale and clip indicator (Sections 8-9)."""

    DB_FLOOR = -60.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._left = -math.inf
        self._right = -math.inf
        self._clipped = False
        self.setMinimumHeight(30)
        self.setMinimumWidth(160)

    def set_levels(self, left_db: float, right_db: float, clipped: bool) -> None:
        self._left, self._right, self._clipped = left_db, right_db, clipped
        self.update()

    def _frac(self, db: float) -> float:
        if db <= self.DB_FLOOR or db == -math.inf:
            return 0.0
        return min(1.0, (db - self.DB_FLOOR) / (0.0 - self.DB_FLOOR))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(20, 20, 20))
        bar_h = (h - 6) // 2
        for row, db in enumerate((self._left, self._right)):
            y = 2 + row * (bar_h + 2)
            frac = self._frac(db)
            bw = int(w * frac)
            color = QColor(60, 180, 75) if db < -12 else (
                QColor(230, 200, 60) if db < -3 else QColor(220, 60, 60))
            p.fillRect(0, y, bw, bar_h, color)
            p.setPen(QPen(QColor(70, 70, 70)))
            p.drawRect(0, y, w - 1, bar_h)
        if self._clipped:
            p.fillRect(w - 8, 0, 8, h, QColor(255, 0, 0))
        p.end()
