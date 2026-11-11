# Audio decoding and import safeguards

These safeguards address the hang observed when Clue 26 attempted cue 36, `36 benny hill.mp3`. Windows reported Application Hang; the last application log recorded its GO attempt. The exact native decoder fault was not available, but that same file had already emitted repeated MP3 decoder errors during import checks.

## Playback behavior

The normal GUI never falls back to synchronous decoding on GO. Arming starts preparation through UI/control-thread polling. While audio is preparing, GO is disabled with a visible explanation. If preparation fails, the cue stays armed and blocked with an error referring to Diagnostics / Logs. Existing sounds are not stopped by a failed preparation, including cues configured to stop previous/all audio when successfully started.

GO on End retains its automatic request while a successor prepares and executes it once it is ready. A preparation error cancels that automatic execution and reports the failure; the player does not silently skip the cue. Manual navigation, stops, output loss, and leaving the mode still cancel pending automatic execution. TEST audition also prepares asynchronously; Stop TEST cancels a pending start.

Show/Rehearse entry and explicit Show Readiness metadata checks run in background jobs. File import checks and waveform extraction do as well. Readiness verifies file metadata and segment settings; it is not a complete corruption scan of every existing asset. Full scanning happens before new imports; existing files are protected when prepared for playback or waveform reading.

## Decoder isolation and limits

Native audio libraries run in disposable helper processes, not inside the GUI or audio callback. The supervisor terminates the worker on timeout or native error output and detects unexpected exits. Captured native stderr and rejection reasons are logged. Workers are hidden on Windows. Windows Job Objects enforce a 512 MiB per-worker process memory limit and terminate the worker if the parent player exits. At most two decoder processes run concurrently.

- Metadata probe timeout: 5 seconds.
- Full validation, waveform, or playback decode timeout: 20 seconds after obtaining a decoder slot.
- Waiting for an occupied decoder slot is separately bounded by that operation's timeout.
- Decoded PCM limit: 128 MiB per clip. Resampling is included in the playback estimate.
- Prepared PCM cache budget: 256 MiB, evicting old entries.
- Active playback PCM budget: 256 MiB, accounted per playback instance. Capacity is checked before intentional On GO stop operations.

These are conservative prototype limits, not a statement that every oversized recording is corrupt. Use a shorter export or a shorter saved playback segment for material that exceeds the playback budget. Full-file import checks require the entire asset to fit the import limit; trim/re-export a long recording before importing it. General large-file streaming is still future work.

WAV/FLAC/MP3/OGG use libsndfile inside the worker; optional AAC/M4A decoding via PyAV/FFmpeg is isolated there too. Decoding uses bounded blocks and rejects empty, truncated, unsupported-channel, non-finite, or oversized results. A decoder warning/error on stderr is treated conservatively as suspect even if the decoder would otherwise return samples.

Native-error/timeout/abnormal-exit failures are quarantined in memory by path, size, and modification time for the current application process, avoiding repeated attempts against the same suspect file. Preparation failures are also cached. Replacing/re-exporting the file changes its fingerprint and allows preparation again. This is a runtime guard; it does not rename, delete, or modify the original file or saved cue reference.

## Imports

Both the inline audio picker and Advanced Cue Editor check the source asynchronously before accepting it. Programmatic `PlayFolder.import_audio` calls run the same validation. A rejected file is not copied and an existing cue's filename/trim remains unchanged. Accepted copies are staged, checked for source changes/content mismatch, then placed in the production audio folder. Import collisions retain existing no-overwrite/content-deduplication behavior.

The UI displays checking/rejection status. Save and mode entry wait for pending table import checks; closing cancels their pending assignment. Canceling an Advanced import prevents a late result from copying an asset. Existing productions are not rewritten to remove problematic references.

## Troubleshooting a blocked cue

Open **Diagnostics / Logs**, then Refresh or Copy report. Look for **AUDIO SAFETY REJECT** and **AUDIO PREPARE FAILED**, which include the file, operation, and failure reason. Native error text, timeout, unexpected process exit, and memory-budget rejection are distinguished. Replace suspect audio with a clean export, preferably WAV, and re-arm it. Do not assume increasing output buffering will repair a malformed source file.

The real `36 benny hill.mp3` was rejected by the import decoded-size check in approximately 0.5 seconds in an offline check. Its existing Clue 26 reference and all originals were left unchanged. It still needs a clean replacement; the safeguards do not repair audio data.

## Verification

The full suite has 386 passing tests. Twenty focused safety cases cover isolated decode/resampling/waveforms, killed timeouts, native error output, unexpected exits, memory/cache limits, transactional import rejection/source changes, responsive UI, duplicate preparation suppression, queued automatic GO, safe Stop Previous failure, file replacement, pending/canceled import handling, canceled TEST, asynchronous mode entry, and absence of file preparation in the live audio callback. Existing placeholder-byte import fixtures now use real WAV assets. Physical audibility and device reliability remain separate verification.


Implementation reference: Windows isolation uses [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), including the documented process-memory and kill-on-job-close flags.


## Decoder memory-overhead correction

An ordinary cue (`7 thunder.mp3`, about 13 MiB of decoded audio) exposed a false rejection: the default NumPy/OpenBLAS thread pool committed about 500 MiB before audio decoding, leaving too little room under the 512 MiB worker limit. Decoder subprocesses now explicitly use one numerical-library thread (OpenBLAS/OMP/MKL/BLIS/NumExpr), without changing the player process's environment. Timeout, job-memory, PCM, and cache limits remain enforced.

Offline checks now decode the real Clue 26 cues 1, 7, and 34 successfully, while cue 36 remains blocked by the decoded-data safety limit. The regression suite includes a 30-second stereo decode with a deliberately large parent thread-pool environment. Fully relaunch the application after this update to load the fix and clear prior cached preparation failures.


## Preparation/cache update

The player now retains successful validation, metadata, and playback-ready PCM in a bounded local cache across launches. Import checks prepare reusable PCM; identical audio under different names can share it. One upcoming cue preloads ahead, RAM reuse is LRU, and repetitive UI file-identity polling is throttled. GO still checks current identity and retains all safety protections. Uncached legacy/changed clips or disk-evicted entries can still need initial decoding.

Use **Recheck Audio** in Edit for an explicit full scan. Open Play is now ordered by last successful open, not last save. Diagnostics logs record decoded-cache hits and preparation elapsed time. See [Performance and recent plays](PLAYBACK-PERFORMANCE.md) for cache location/limits, first-use behavior, and measured offline timings.


### Small MP3 end-length discrepancies

A clean MP3 decoder EOF up to 0.25 seconds before the reported end is accepted at the physical file end and logged as `AUDIO LENGTH ADJUSTMENT`. Playback uses the samples actually decoded. Reported duration remains available for compatibility with existing saved trim endpoints. Explicit earlier trim endpoints, empty audio, larger shortfalls, native decoder warnings, timeouts, and memory limits retain their protections. This fixes cue 41 being armed but blocked from GO after cue 39; restart the application to clear previously cached preparation failures.


Import silently measures the decoded whole-source sample peak and counts samples near full scale. Inline Browse / Import and the Advanced Cue Editor show a nonblocking level warning after successful import for full-scale peaks (possible source clipping), little headroom (within 1 dB of full scale), or peaks that could exceed full scale with the current cue and selected bus levels. These are advisory, not import failures. Source peaks alone cannot prove distortion; whole-source estimates may overstate trimmed/faded playback peaks and cannot predict operator-timed overlapping sounds. Peak results persist with validation by file identity; older cached proofs acquire peak analysis on the next import without discarding the decoded cache.

Edit now includes the shared Audio Health panel beside TEST progress/meters, including Diagnostics / Logs. It shows Idle without active playback, live load/clipping/dropout measurements during TEST, and output loss even when idle. The existing top logs button remains available.

The Playing card square Stop button now completes that playback immediately as a normal ending: Arm Next at End arms the successor; GO on End queues automatic GO on the already armed cue; Arm Next Now keeps its current armed cue. STOP ALL, internal Stop Previous/Stop All behavior, output loss, and configured interrupting fades retain their cancellation semantics.
