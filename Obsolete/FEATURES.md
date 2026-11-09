# BHS Audio Production Player — Feature Snapshot

Updated: November 2, 2026

Use this document to bring a ChatGPT conversation up to date on the project. It summarizes features present in the current source code, including uncommitted changes; it is not a claim that all features have passed live performance testing.

## Purpose and platform

A Windows desktop sound cue player for theatrical productions. The operator builds a production's cue list, then deliberately triggers sound and control cues during a performance. Reliability, clear show state, and protection against accidental playback are priorities.

Built with Python 3.11+, PySide6, NumPy, sounddevice/PortAudio, and soundfile. Tests use pytest and pytest-qt.

## Production and cue editing

- Create productions, open their saved versions, and choose older versions from history.
- Edit cues in a spreadsheet-style table with field-specific hover help and dropdowns.
- Add cues after the selected row, remove cues with confirmation, and move cues up or down.
- Cue fields include identifier, name, notes, action, audio file, volume, fades, loop, advance mode, On GO behavior, start/end positions, target cue, and target fade duration.
- Browse/import audio into the production folder; handle filename collisions and reuse identical assets.
- Selecting a new audio file fills End Position from its duration; the operator can shorten the playable segment.
- Warn before deleting a cue referenced by STOP or FADE cues.
- Remember table column widths across Edit and Show modes and application sessions.

## Cue identity and ordering

- Display identifiers use script-page notation, such as `12.0` or `47.21`.
- Preserve the entered spelling, but compare identifiers as exact decimal values for uniqueness: `12.1` and `12.10` are duplicates in the current implementation.
- Performance order is explicit and independent of identifier sorting.
- Stable internal IDs keep STOP/FADE targets connected when cues are renamed or reordered.

## Show operation

- Separate Selected, Armed, and Playing concepts: selecting or arming a cue never starts playback.
- GO or Spacebar executes the armed cue. Keyboard auto-repeat is suppressed, and Spacebar in a text field is protected.
- PLAY starts a sound; STOP and FADE act on a target PLAY cue's active instances; STOP ALL stops all sounds.
- **On Complete:** wait for natural completion, then arm the next cue. Another GO is required to play it.
- **On GO / Trigger:** arm the next cue immediately while the current sound continues, allowing deliberate overlap.
- Each PLAY cue can add to existing audio, stop the most recent active sound, or stop all sounds before starting.
- Back and ARM CUE support deliberate navigation and replay without automatically stopping existing sounds.
- Interrupting an On Complete sound releases its wait and requires deliberate navigation; it does not silently advance.
- Show Mode locks normal cue editing. Closing Show Mode returns to Edit Mode while performance audio can continue.
- Save Version is available in both modes.

## Audio and monitoring

- Simultaneous sounds with independent volume, fade-in, fade-out, looping, and start/end trims.
- Mixed sample rates and mono/stereo audio are handled by the audio engine.
- Background preparation of armed audio reduces work needed when GO is pressed.
- Playing Stack shows active instances with cue identity, playback status, progress/waveform, elapsed time, remaining time where applicable, stereo meters, STOP, and FADE OUT.
- Loop displays distinguish iteration progress from total elapsed playback time.
- Master level controls the combined output, including TEST audio, and is saved with the production.
- TEST Selected Cue auditions audio with progress and metering without advancing the show or changing arming.
- Deliberate output-device selection, visible output-loss status, and GO blocking when output is unavailable. Output loss does not silently redirect or automatically replay sounds.

## Saving, recovery, and checks

- Each production has a folder containing JSON-based `.cueset` versions and imported audio with relative references.
- Every permanent save creates a new historical version; existing versions are retained.
- Recovery autosave follows meaningful edits and stays separate from permanent history.
- Opening a production can offer recovery restoration. Closing with unsaved changes offers Save, Discard, or Cancel.
- Validate Show checks identifiers, internal IDs, audio references/readability/duration, segment bounds, targets, negative levels/fades, invalid loop/advance combinations, and output availability.
- Pre-Show Status summarizes validation, audio verification, device/engine status, and recovery state; critical validation errors block entry.

## Current qualifications and scope

- WAV is the preferred performance format. Other formats depend on decoder support; AAC/M4A fallback requires optional PyAV, which is not currently declared in project dependencies.
- Audio preparation currently loads decoded segments into memory; bounded streaming for large files is not implemented.
- Hardware reliability, timing, and full specification compliance still require verification; source presence alone does not establish show readiness.
- MIDI control, automatic-follow playback, WAIT cues, and editable waveforms are outside the current scope.
- `Program Prompt Version 0.1.txt` is the canonical requirements document, but it has a known conflict with current decimal identifier uniqueness. Treat this snapshot as a description of current implementation, not a replacement requirements specification.
