# Audio Health monitor and troubleshooting logs

The Audio Health panel is in the bottom strip of Show and Rehearse, separate from output level meters. Choose **Diagnostics / Logs** there, or beside Viewing mode in Edit, to inspect local diagnostics without stopping audio.

## Reading the monitor

- **Normal / green:** measured processing load is below the warning threshold, with no recent detected issue. This is not a guarantee of speaker audibility.
- **HIGH LOAD / amber:** processing load is at least 70%, or a measured callback exceeded its audio-time budget within the last five seconds. This indicates reduced headroom, not proof of an audible dropout.
- **DROPOUT / red:** the audio driver reported an output underflow within the last five seconds. Audio was not delivered quickly enough. Playback continues; the app does not stop or silently reroute on an underflow.
- **CLIPPING / red:** the software mix exceeded full scale within the last five seconds. Lower the playing-card levels or configured bus level. This is a signal-level problem, distinct from buffering.
- **OUTPUT LOST:** existing device-loss handling has detected a failure. Existing readiness rules still disable playback.
- **Unavailable / Not running / Waiting for audio:** there are no usable live measurements. GUI Preview is labeled explicitly and never displays simulated health as live.

The percentage is **processing load**, not buffer fullness and not overall Windows CPU utilization. 100% corresponds to the audio processing time budget. The bar caps at 100%; its text can show a higher measured value. The device library's CPU-load measurement is used where available, with measured callback duration as a fallback. Hover for peak callback load, over-budget callbacks, sample rate, requested block size, and reported output latency.

**Dropouts** is the accumulated count of driver-reported output underflows. **Clipped blocks** counts audio callback blocks above full scale, not distinct audible clipping incidents. Counts remain after the five-second warning expires and cover the prepared stream's lifetime, including silent pumping between modes; preparing a new stream resets its counters. Recent incidents remain in the log when counters reset. Over-budget callbacks do not necessarily produce underflow reports, and underflows can happen even when the measured callback load looks low.

Wireless interruptions, board distortion, speaker problems, and other faults downstream of the application may not register. The monitor helps locate a problem; it does not fix dropouts or tune buffering automatically.

## Access and sharing

Click **Diagnostics / Logs** in Edit or Show/Rehearse. The nonmodal viewer provides:

- **Refresh:** current device/health/active-playback context and the latest 128 KiB of the log.
- **Copy report:** copies that context and recent log text to the clipboard for pasting into troubleshooting.
- **Open Logs Folder:** opens the directory in Windows Explorer, where you can copy the log files.
- **Close:** closes only the viewer; playback continues.

Logs are stored in the application's project folder under `logs/`, separate from productions and ignored by Git. In this workspace the active file is:

`G:\My Drive\Programming\BHS Audio Production Player\logs\bhs-player.log`

The active file rotates at 2 MiB, retaining four older files (`bhs-player.log.1` through `.4`), approximately 10 MiB total. Timestamps use UTC and end in `Z`. Logging starts when the application starts and appends across launches. The viewer shows logging initialization/write errors; its access button changes to **Logs (error)** when a problem is recorded. No logs are uploaded automatically.

## What is recorded

Application/runtime versions; production and mode entry; device/route preparation and failures; cue GO settings and success/failure; automatic GO results; manual per-instance level/repeat/stop/fade changes; audio preparation exceptions; output loss; and periodic audio-health context. Health warnings summarize new underflows, over-budget callbacks, and clipped blocks with totals, current/peak load, device identity, and active cue/playback numbers. A status summary is recorded about every ten seconds while stream measurements exist. Some native decoder/driver stderr messages may not be available to Python logging.

Audio callbacks only update lightweight measurements/counters. Control-thread polling aggregates them at most once per second and queues log messages. A listener thread performs regular log writes and rotation; there is no log file I/O in the audio callback. Logging and monitoring do not change the block size, requested latency, routing, or cue-file format.

## Investigating crackling

Note the cue and approximate time of the problem. Look at Audio Health and the master meters, then open Diagnostics / Logs and copy the report.

- Increasing underflows points toward late audio delivery; check load and whether the event coincided with GO, cue decoding, or UI activity.
- Clipped blocks with no underflows points toward an excessive mix level; overlapping cues can clip even when each cue is at 100%.
- A repeatable fault at the same position in one file may be a source recording/decoding problem. The imported `36 benny hill.mp3` was already flagged for decoder errors.
- Clean app measurements with audible interruption suggests checking the device/connection/board path as well.

## Verification

The automated suite covers callback counters without callback logging, unchanged PCM on underflow, separate clipping/load classification, warning hold time, device telemetry availability, loss reporting, deduplicated control-thread issue logs, rotation, listener-thread writes, logging failure, and nonmodal viewer/report/folder access. Full suite: 347 passing tests. Offline renders include `audio-health-example.png` (explicitly simulated states), `diagnostics-logs.png`, and updated Show/Rehearse layouts. Physical device reliability and audibility remain unverified.


## Decoder and import safety

The GUI prepares audio asynchronously in killable, memory-limited Windows decoder workers. GO is disabled while preparing; a failed cue remains armed and blocked with a visible error. GO on End waits for a successful preparation, or reports failure without skipping ahead. Existing audio keeps playing when preparation fails. TEST preparation is also asynchronous and can be canceled.

New imports are fully checked before copying or changing cue references. Native errors, timeouts, abnormal exits, and data/memory budget failures appear in Diagnostics / Logs as AUDIO SAFETY REJECT / AUDIO PREPARE FAILED. Existing assets are not deleted or repaired. The known `36 benny hill.mp3` is blocked under the full-file decoded-data budget and needs a clean replacement. See [Audio safety guide](AUDIO-SAFETY.md) for limits, import behavior, and recovery.


## Preparation/cache update

The player now retains successful validation, metadata, and playback-ready PCM in a bounded local cache across launches. Import checks prepare reusable PCM; identical audio under different names can share it. One upcoming cue preloads ahead, RAM reuse is LRU, and repetitive UI file-identity polling is throttled. GO still checks current identity and retains all safety protections. Uncached legacy/changed clips or disk-evicted entries can still need initial decoding.

Use **Recheck Audio** in Edit for an explicit full scan. Open Play is now ordered by last successful open, not last save. Diagnostics logs record decoded-cache hits and preparation elapsed time. See [Performance and recent plays](PLAYBACK-PERFORMANCE.md) for cache location/limits, first-use behavior, and measured offline timings.
