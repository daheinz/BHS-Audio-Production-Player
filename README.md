# BHS Audio Production Player

A Windows theatrical sound cue player that behaves like a sound equivalent of a theatrical lighting console.

Current requirements: [DOC-002 Detailed Requirements v0.2](https://docs.google.com/document/d/1jKmJ7jITTiOwQJUxdYhEs1Uw3dVdIp8jP3T4pAz1Lwk/edit), with the approved November 3 decisions. Historical prompts and the earlier feature snapshot are in `Obsolete/`.

This is a GUI-first prototype. See [FEATURES.md](FEATURES.md) and [GUI implementation status](Documentation/GUI-IMPLEMENTATION-STATUS.md) for wired behavior and remaining audio work.

## Try the GUI

Double-click **Launch GUI Preview.cmd** for an isolated sample production. You can edit cues, inspect routing and the advanced editor, review linked cues, and open Show/Rehearse layouts. The preview produces no audio and saves no production files.

Double-click **Launch Player.cmd** for normal production creation/opening. Select a profile, inspect the audio tester, then prepare cues. Show entry validates and blocks unsupported audio routes; the preview lets you review those screens without hardware.

From an installed development environment:

```powershell
python -m bhs_player.app --gui-preview
python -m bhs_player.app
```

## Stack

- Python 3.11+
- PySide6 (Qt Widgets) — UI
- sounddevice (PortAudio) — output, mixing, metering
- soundfile (libsndfile) — decoding; AAC/M4A fallback needs optional PyAV
- pytest — test suite

## Layout

```
src/bhs_player/
    cues/       # cue model, identifiers, state machine, execution
    audio/      # existing stereo engine, guarded routing adapter, metering
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

The cue table uses field-specific hover help on column headers and cells.
Cue IDs are exact text: `12.1` and `12.10` are distinct. Their original spelling is retained for display and storage.
Resized column widths are shared between Edit and Show modes and saved in
`BHS Audio Production Player/settings.ini` in the Windows user configuration
directory. These preferences are separate from saved production versions.
Choosing an audio file fills End Position with its full duration in seconds;
you can reduce it to trim playback. Existing saved trims are preserved.


## GUI verification

```powershell
python -m pytest -p no:cacheprovider
python tools/render_gui.py
```

The renderer writes six silent sample screenshots under `output/gui-review/`. It uses offscreen Qt rendering and Windows Segoe UI fonts; it does not test real audio hardware.

## Viewing mode

The application defaults to **Dark** for theatre use. Choose **Dark** or **Light** from the Viewing mode selector on the production picker, Edit screen, or Show/Rehearse screen. Changes apply immediately to all screens and are remembered in application settings, separately from production files. File pickers use the application theme as well.
