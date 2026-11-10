# Playback preparation, persistent validation, and recent plays

## What happens when arming

Arming chooses a cue immediately. GO becomes available when its playback data is ready. The player now reuses decoded PCM from RAM or a local disk cache instead of repeatedly starting a decoder for unchanged audio. Import validation also stores playback-ready data, so importing and then arming the same full clip does not require a second decode.

The armed cue is prioritized, with one successor prepared ahead on the control thread. Access updates RAM LRU order. Rehearsal jumps back to a clip evicted from RAM can load the disk copy, and identical recordings with different filenames can share decoded data through their content identity. Live level, Repeat, fades, and other cue execution behavior still apply independently after PCM loading; they are not baked into the cache.

The UI uses memoized file-identity snapshots rather than repeatedly resolving/statting the same file every refresh. Snapshots refresh about once a second. GO and completed preparation jobs perform fresh identity checks, so changed files are not knowingly played from stale RAM entries.

First-time playback of an uncached legacy file, a newly trimmed segment, or an entry evicted from disk may still need native decoding. That work remains isolated and bounded. The optimization does not guarantee instant access to every arbitrarily selected file.

## Validation across launches

Successful import validation and metadata probes persist by resolved path, byte size, modification time, and cache format version. Unchanged files reuse those results after relaunch. Missing or changed files are checked as needed. Normal mode entry retains cue-setting, segment, output availability, and routing checks; its status says **Checking cue and output readiness** rather than suggesting a repeated full import scan.

Choose **Recheck Audio** in Edit to force a full scan, bypassing the stored validation results. This can take time. It runs in the background, reports pass/failure counts, and records issues in Diagnostics / Logs. It stops TEST audition and refreshes prepared state; finish the recheck before entering Show/Rehearse. Decoder safeguards remain enabled.

Legacy assets without persistent results initially receive metadata/readiness checks and guarded preparation. Recheck Audio is available when a full rescan is wanted.

## Cache location and limits

On this Windows computer the cache is under:

`C:\Users\heinz\AppData\Local\BHS Audio Production Player\audio-cache`

It is outside the Google Drive project and separate from production files, source audio, application settings, and troubleshooting logs. Metadata records are bounded to 1,024 files. Decoded disk data uses a 512 MiB budget with oldest-use eviction. The prepared RAM cache remains 256 MiB; per-clip and active-playback limits remain unchanged. Cache files are versioned, written atomically, and treated as disposable. An unreadable/corrupted/unwritable cache falls back to guarded preparation, with write problems logged.

Closing the app and deleting this cache loses only acceleration data; saved cues and audio assets are unaffected. The first subsequent use needs checking/preparation again. No cache data is uploaded by the player.

## Open Play ordering

Open Play sorts productions by the most recent successful open. Opening a saved version, restoring recovery, and opening through a named production launcher all count. Canceling recovery or failing to load does not change recency. Saving a version does not change the last-opened time.

Recency is an application preference in settings.ini, keyed by production-folder identity. Never-opened productions use a stable alphabetical fallback. History begins with successful opens after this update; past opening times are not reconstructed from save timestamps.

## Verification

360 automated tests pass. Thirteen new cases cover persistent validation, changed-file invalidation, PCM reuse after RAM loss, corruption fallback, cache bounds/failure, manual recheck, reduced identity polling, successor preloading, copied/identical asset reuse, and successful/canceled/failed opening order.

Offline checks with the real Clue 26 recordings observed an uncached long MP3 taking several seconds to decode, a RAM-evicted reload around 0.23 seconds, and persisted validation around 13 ms. With content reuse and local storage, cue 43 reused cue 34's audio in about 0.11 seconds and cue 34 reloaded in about 0.08 seconds. These timings are observations on this machine, not latency guarantees or physical audio verification.
