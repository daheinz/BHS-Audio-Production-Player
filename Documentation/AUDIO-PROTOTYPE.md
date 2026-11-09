# Real-audio prototype walkthrough

Built November 9, 2026 from the user's local Music library. This is a saved, editable production, not the silent GUI preview.

## Launch from VS Code

```powershell
& ".\Launch Audio Prototype.cmd"
```

This directly opens **Audio Prototype**, using its latest saved version and the existing recovery-restore flow. The first launch opens Profile and Routing if no primary endpoint has been selected. Choose the actual stereo speakers/headphones you want, leave Main on channels 1/2, and Save the profile. No audio plays on launch or device selection.

Open **Pre-Audience Audio Test**, choose Play Again, and confirm the audible-output prompt. Confirmed Audible is your listening result; no test is marked successful by the builder. Then close the tester and enter **REHEARSE**.

Click the **ARM** control at the left of cue **1.0**, or select its row and press Enter, then click **GO** or press Space. Each subsequent action needs another GO. Returning to Edit stops playback and disarms; re-entry requires deliberate arming.

## Cue sequence

| Cue | Action | Expected behavior |
| --- | --- | --- |
| 1.0 | Opening fanfare | Finite WAV; waits for natural completion before arming 2.0 |
| 2.0 | Steam engine ambience | FLAC segment loops; immediately arms the bell |
| 2.1 | Station bell | Mono bell overlaps the engine; music arms after the bell ends |
| 3.0 | Music underneath | Trimmed 24-second MP3 excerpt overlaps the engine; immediately arms the music FADE |
| 4.0 | Fade music | Three seconds to silence and stop; engine continues |
| 5.0 | Stop engine | Stops only the looping engine; arrival arms silently |
| 6.0 | Train arriving | 48 kHz source trimmed to 12 seconds, with a 1.5-second end fade |
| 7.0 | STOP ALL | Stops any remaining sound; sequence ends without wrapping |

After cue 3.0, let the music run for a few seconds, then GO on 4.0 before the excerpt finishes. If music has already finished, the FADE is a valid no-op.

You can also right-click an Audio File cell to TEST that row, drag clip handles, reorder cues, and save/reopen your edits. The permanent STOP ALL button is always available in Rehearse/Show.

## Saved data and original audio

The production lives under `Plays/Audio Prototype/`:

- Versioned `.cueset` production files.
- Five imported audio copies in `audio/`, referenced with relative paths.
- `PRACTICE-GUIDE.md` with cue notes and original source filenames.
- Separate recovery data after meaningful edits.

The original `C:/Users/heinz/Music` files remain unchanged. The imported files were verified byte-for-byte against the originals. This production uses conservative cue levels and a 50% Main bus level; actual listening volume still depends on the selected device and external equipment.

The local production/audio folder is excluded from Git. Source code, builder, tests, and this guide can be committed without adding the private audio assets.

## Rebuild / verify tools

```powershell
python tools/build_audio_prototype.py
python tools/check_audio_prototype.py
```

The builder keeps an existing production and its edits/recovery intact. It never rebuilds it implicitly. To create a separate fresh copy, use a new name:

```powershell
python tools/build_audio_prototype.py --name "Audio Prototype 2"
python -m bhs_player.app --production "Audio Prototype 2"
```

An alternate Music directory can be passed with `--music-folder`. The builder currently uses five explicitly named sources from the user's library; it is not a general audio-library classifier.

The check tool exercises the original Audio Prototype sequence offline, without opening an audio device. It is intended for the unmodified practice sequence; customized versions may no longer match its fixed assertions.

## Verification and limits

- Full suite: **243 tests passed**.
- The real saved assets decoded through the existing engine: WAV, FLAC, MP3, mono/stereo, and source rates 11.025/44.1/48 kHz, mixed at 44.1 kHz.
- Offline execution verified natural completion, looping, overlap, music FADE, targeted STOP, sequence-end silence, and emergency STOP ALL. The measured practice-mix peak was about 0.225 full scale, below clipping.
- The actual saved production and its imported source waveform were rendered and visually inspected in dark mode, with no output stream opened.
- Physical audibility, latency, and unplug/backup recovery have not been verified on the user's hardware. Available outputs were enumerated, but none was silently assigned.
- The trimmed MP3 produces a compressed-timing warning; no optional backup is configured. Neither warning is silently treated as a completed audio test.
- General multichannel routing and bounded large-file playback remain future work. The sample uses the supported single stereo Main bus.


## Updated Show/Rehearse screen

The cue table now fills the left two-thirds of the main area. The yellow Armed Cue card is at the upper right; active orange playback cards stack upward from the bottom of their separate container below it. GO / STOP ALL are compact bottom controls, with readiness on the left and master/bus meters on the right. Playback cards have position bars and local stop/fade icons, without per-sound audio meters. Ctrl+Shift+S invokes existing Stop All; click a playback card and use Ctrl+F to fade only it. See [Show/Rehearse guide](SHOW-MODE.md). The saved prototype sequence and audio assets were not changed by this redesign.


While practicing, each playing card now offers a Level slider and Repeat checkbox for temporary, instance-only adjustments. New playback restores the saved cue defaults. Turning Repeat off lets the current pass finish; STOP and FADE remain available. See [live controls](SHOW-MODE.md#live-playback-level-and-repeat).


If you change a practice cue to GO on End, the successor is now armed and visible while that cue plays, then starts automatically at its natural end. Arm Next at End still waits until completion to arm its successor. Saved practice cue settings were not altered.


Each Show/Rehearse entry now starts with neutral cue rows and no cue armed. Completed/interrupted playback colors from a previous session are not restored from saved files; cue settings and audio references remain intact.


The Show/Rehearse cue table follows the current armed cue as you advance: scrolling begins at the visible midpoint and keeps it centered until the list bottom is reached. Short lists may need no scrolling. Manual browsing between cue changes remains available.


## Audio Health and troubleshooting

The bottom Audio Health gauge reports processing load, output-underflow dropout counts, and clipped-block counts separately from the master signal meters. Amber warns of reduced headroom; red holds recent dropout/clipping alerts for five seconds. It is not a buffer-fill display. Choose **Diagnostics / Logs** there or in Edit for a nonmodal viewer, **Copy report**, and **Open Logs Folder**. UTC logs in the project `logs/` folder rotate at 2 MiB with four backups; measurements and log writes stay separate from audio processing. See [Audio diagnostics guide](AUDIO-DIAGNOSTICS.md) for meanings, limits, and crackling investigations.


## Decoder and import safety

The GUI prepares audio asynchronously in killable, memory-limited Windows decoder workers. GO is disabled while preparing; a failed cue remains armed and blocked with a visible error. GO on End waits for a successful preparation, or reports failure without skipping ahead. Existing audio keeps playing when preparation fails. TEST preparation is also asynchronous and can be canceled.

New imports are fully checked before copying or changing cue references. Native errors, timeouts, abnormal exits, and data/memory budget failures appear in Diagnostics / Logs as AUDIO SAFETY REJECT / AUDIO PREPARE FAILED. Existing assets are not deleted or repaired. The known `36 benny hill.mp3` is blocked under the full-file decoded-data budget and needs a clean replacement. See [Audio safety guide](AUDIO-SAFETY.md) for limits, import behavior, and recovery.
