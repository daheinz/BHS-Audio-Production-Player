# BHS Audio Production Player

A Windows theatrical sound cue player that behaves like a sound equivalent of a theatrical lighting console.

Canonical requirements: [Program Prompt Version 0.1.txt](Program%20Prompt%20Version%200.1.txt)

## Stack

- Python 3.11+
- PySide6 (Qt Widgets) — UI
- sounddevice (PortAudio) — output, mixing, metering
- soundfile (libsndfile) — decode (WAV/FLAC/MP3/AAC)
- pytest — test suite

## Layout

```
src/bhs_player/
    cues/       # cue model, identifiers, state machine, execution
    audio/      # audio engine, mixing, master level, metering
    storage/    # play folders, versioned cue sets, recovery autosave
    validate/   # load-time sanity check / Validate Show
    ui/         # PySide6: Show Mode, Edit Mode, Playing Stack
tests/          # unit + integration tests (Section 21 acceptance scenarios)
plays/          # play folders (one per production)
```

## Develop

```
pip install -e .[dev]
pytest
```
