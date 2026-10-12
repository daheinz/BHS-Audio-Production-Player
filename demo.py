"""Demo launcher: a Clue show with synthesized tones so you can run the UI
without real audio files. Audio is streamed to the output device you pick.

Run with:  python demo.py   (venv active, PYTHONPATH=src)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import numpy as np
from PySide6.QtWidgets import QApplication

from bhs_player.app import build_app, select_output
from bhs_player.cues.model import ActionType, AdvanceMode, Cue, CueSet

SR = 44100


def tone(seconds, freq=440.0, amp=0.5):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def main():
    cs = CueSet(play_name="Clue (Demo)")

    rain = Cue(identifier="12.0", name="Rain (loops)", action=ActionType.PLAY,
               loop=True, advance_mode=AdvanceMode.ON_GO, volume=0.4)
    rain._demo_pcm = tone(2.0, freq=220.0, amp=0.4)

    bell = Cue(identifier="12.1", name="Doorbell", action=ActionType.PLAY, volume=0.9)
    bell._demo_pcm = tone(1.0, freq=880.0, amp=0.9)

    thunder = Cue(identifier="12.2", name="Thunder", action=ActionType.PLAY,
                  advance_mode=AdvanceMode.ON_GO, volume=0.8)
    thunder._demo_pcm = tone(3.0, freq=110.0, amp=0.8)

    for c in (rain, bell, thunder):
        cs.insert(c)

    app, win = build_app(cs)

    # inject synthesized pcm so no audio files are needed for the demo
    real_start = win.audio.start
    win.audio.start = lambda cue: real_start(cue, pcm=getattr(cue, "_demo_pcm", tone(1.0)))

    win.show()
    if select_output(win):
        print("Streaming to:", win.backend.stream.device_name)
    else:
        print("No output device selected; playback will be simulated visually only.")
    print("Press GO / Spacebar to run cues.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
