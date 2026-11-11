# Requested GUI modifications

Recorded November 8, 2026. Implementation is organized into three independently verified chunks. Status below is updated as each chunk is completed.

## 1. Drag handles for cue ordering

Status: Implemented and functionally tested (automated).

- Add a narrow handle at the far left of each cue row.
- Drag the handle to reposition the cue in performance order, with a visible insertion indicator.
- Preserve identifiers, settings, stable target references, and selection of the moved cue.
- Mark a completed reorder as a meaningful change and maintain recovery autosave.
- Enable only in Edit Mode; keep Show/Rehearse locked. Retain Move Up/Down for keyboard and precise positioning.

## 2. Highlight cue IDs that are out of numeric order

Status: Implemented and functionally tested (automated); adjacent-reversal rule follows the user example.

- Compare adjacent cue IDs in performance order. Whenever an ID is numerically greater than the next ID, highlight both Cue ID cells, rather than the entire rows.
- Example: `1.0, 1.2, 1.1, 1.3` highlights only `1.2` and `1.1`.
- Combine highlights when several adjacent reversals overlap; clear them when the order is corrected.
- Use the highlight as an advisory; do not automatically sort, renumber, or prevent deliberate nonnumeric performance order.
- Keep text identity unchanged: `12.1` and `12.10` remain distinct identifiers, even when a numeric comparison treats them as equal.
- Numerically equal IDs do not constitute a descending reversal. Keep numeric-order comparison separate from exact text identity.
- Explain the warning with a tooltip/legend and make it readable in both viewing modes without obscuring selection or execution states.

## 3. Remove the redundant Edit Selected Cell button

Status: Implemented; redundant button removed.

- The button's handler calls `editItem()` on the current table item. The table already supports double-click, the edit key (F2), and typing to begin editing; audio cells use the same file-picker delegate.
- Remove the button while preserving these interactions, dropdown controls, and field help.
- Keep the Advanced Cue Editor button; it provides additional functionality.

## 4. Right-click audition from an Audio File cell

Status: Implemented and functionally tested (automated).

- In Edit Mode, right-click an Audio File cell containing a filename and offer a Play / TEST Audio action for that row.
- Use the existing audition path so the preview uses the cue's trim, level, fades, loop, and bus assignment without destructive On GO behavior.
- Show TEST status/progress and provide Stop. Do not alter the armed cue, execution history, or show position.
- Respect output readiness and unsupported-routing restrictions. Report missing/unreadable audio clearly; do not offer playback for an empty cell or non-PLAY action.

## 5. Graphical audio clip, trim, and fade editor

Status: Implemented and functionally tested (automated); dark-mode screens visually reviewed.

- Replace the spreadsheet's Start Position, End Position, Fade Duration, Fade-In, and Fade-Out controls with a graphical editing workflow where appropriate.
- Use the waveform screenshot supplied with the November 8 request as the visual reference: separate stereo channel waveforms, a clearly bounded clip, and a gain/fade envelope with visible control points.
- Show the full source waveform, playable start/end boundaries, excluded sections, and where fade-in/fade-out occur. Support direct manipulation of the applicable boundaries and fade handles.
- Keep timing information understandable and provide precise numeric entry in the Advanced Cue Editor or alongside the graphical controls. Hiding spreadsheet columns must not discard their saved values.
- Ensure the waveform/envelope works in the default dark viewing mode; follow the reference's editing concepts without forcing a bright background.
- Distinguish a PLAY cue's source trim and playback fades from a FADE action cue's target-fade duration. A FADE action has no source clip of its own; design an appropriate target/envelope representation rather than treating that duration as a source trim.
- The screenshot does not by itself authorize arbitrary gain automation, multitrack editing, live panning, or a full audio workstation. Start with existing trim/fade settings.
- Preserve the original audio asset; graphical edits should change cue playback settings.

## Implementation chunks

1. **Editing shortcuts — completed:** removed Edit Selected Cell; right-click an assigned Audio File cell for Play / TEST Audio.
2. **Cue ordering — completed:** Edit-only left-edge drag handles, insertion line, stable-reference reordering, recovery saving, and ID-only adjacent-reversal warnings.
3. **Graphical audio editing — completed:** background-loaded mono/stereo source waveform, trim/fade handles, precise Advanced numeric entry, and a separate FADE-action duration envelope.


## Editing-chunk verification and usage (historical November 8 results)

- Full suite: `python -m pytest -p no:cacheprovider` — 235 tests passed.
- Focused tests cover context audition safety, actual Qt drop-event delivery, drag-grip initiation, linked references, recovery saving, numeric reversals, background waveform loading/stale results, mouse trim/fade changes, Cancel, exact timing preservation, and finite/loop fade playback.
- `python tools/render_gui.py` generates the existing review screens plus a FADE-envelope screen; Edit, Advanced, and FADE-envelope images were visually inspected. Review is offscreen Qt rendering, not a native-desktop drag or theatre hardware verification.
- Select a PLAY cue in Edit Mode to see its waveform. Drag Start / End bars and IN / OUT diamonds. The horizontal splitter adjusts space between the table and the clip panel. Exact timing remains available in Advanced Cue Editor.
- Graph edits in the main panel apply on mouse release and update recovery. Advanced Editor changes apply only on OK; Cancel leaves the production unchanged. Escape cancels an in-progress graph drag.
- Finite PLAY clips now apply their OUT fade at the playable end; manual FADE OUT retains that configured default. Loops do not apply end fades on each repetition. FADE action cues retain their separate target duration.
- Waveform extraction reads bounded blocks on a background worker and caches a small peak representation. It currently uses soundfile-supported codecs; when extraction is unavailable, show the error and retain numeric editing. General playback streaming and multichannel routing remain outside these GUI chunks.
- Preview waveforms are explicitly labeled sample data, produce no sound, and are not stored in production files. Real source audio files are never modified by the editor.


## Approved November 9 Show/Rehearse redesign - completed

The approved layout replaces the previous full-width stack and bottom cue table: full-height cue list left, fixed yellow Armed Cue and independently scrollable orange Playing Stack right, and compact status/GO/STOP ALL/master meters along the bottom. Cards grow upward, retain per-instance controls and per-cue bus identity, and no longer include audio meters. Row ARM remains; the redundant bottom ARM CUE button is removed. Selection outlines preserve state colors, and interrupted cues differ from completed.

Keyboard additions: Enter arms the selected cue-table row; Ctrl+Shift+S invokes existing Stop All; Ctrl+F fades an explicitly selected/focused playback card. Space repeat/text/modal protections remain. Up/Down select without arming. Existing playback, intentional On GO interruption choices, completion, routing, saves, and Edit behavior remain intact. No engine or cue-file format change was required.

Current verification: 284 tests pass, including focused interaction, per-instance isolation, state colors, bottom alignment/overflow, and 1500x920 / 1000x700 layout checks. Updated offline renders were inspected. See [Show/Rehearse guide](SHOW-MODE.md) and [Playing Stack guide](PLAYING-STACK.md). Physical theatre verification remains outstanding.


Live playback follow-up completed: each card has a Level slider and Repeat checkbox initialized from cue settings. Adjustments affect only that instance and do not persist into cue files; repeat off finishes the current pass. Current suite: 289 tests pass. See [Show/Rehearse guide](SHOW-MODE.md).


Completion follow-up: GO on End now genuinely arms the next cue during source playback, showing its yellow card and row flag. At natural end it executes that armed cue; manual early GO prevents a duplicate follow. Arm Next at End remains deferred arming. Current suite: 297 passing tests. See [operator guide](SHOW-MODE.md).


Fresh-session state correction: Show/Rehearse entry now stops/disarms and resets all cue execution states to Idle, clearing stale rehearsal colors. Serialization writes Idle and ignores historical runtime states on load without changing the format or modifying original saved versions. Current suite: 300 passing tests, including mode transitions/re-entry and legacy/new-file state handling.


Cue-follow update: Show/Rehearse now scroll on changes of the armed cue (or waiting source if nothing is armed). The table remains at the top through early cues, then centers the current row as advancement continues, clamping at the list bottom. Selection, arming, audio, and horizontal scroll remain unchanged; periodic refresh does not override manual browsing. Pixel scrolling provides smooth row positioning. Regression tests cover both modes, midpoint behavior, actual GO advancement, manual browsing, and end clamping. Current suite: 302 tests.


## Audio Health and troubleshooting logging - implemented

A compact bottom gauge now reports device-library processing load (callback timing fallback), persistent underflow/clipped-block counts, and five-second issue alerts. Over-budget callback measurements are kept distinct from driver-confirmed underflows. Output-loss and unavailable/preview states remain explicit. The panel does not claim buffer fullness or physical audibility.

Diagnostics / Logs is available in Edit and Show/Rehearse. Its nonmodal viewer shows current device/health/playback context and a bounded log tail, with Refresh, Copy report, and Open Logs Folder. UTC logs are kept under project logs/, rotated at 2 MiB with four backups and ignored by Git. Startup/runtime, production/mode, device/route, cue GO/failure, live playback controls, preparation errors, output loss, and aggregated health issues are recorded. Audio callbacks update measurements only; control-thread polling queues events for listener-thread file writes. Existing buffering, latency, routing, and cue-file format remain unchanged.

Current suite: 313 passing tests, including eleven diagnostics cases covering real offline PCM, callback/control-thread separation, counters/status, rotation/threaded writes, logging failure, local report/folder actions, and nonmodal playback preservation. Updated small/large layouts and explicitly simulated health examples were rendered and inspected. Physical hardware verification remains outstanding. See [Audio diagnostics guide](AUDIO-DIAGNOSTICS.md).


Decoder/import safeguard follow-up: completed isolated and bounded decoder work, nonblocking GUI preparation/readiness/TEST, strict asynchronous import checks, transactional copy/reference behavior, cached suspect-file rejection, and logged failure details. Existing productions are preserved; failed cues remain visibly blocked. Current suite: 332 tests, including nineteen dedicated safety cases. See [Audio safety guide](AUDIO-SAFETY.md).


Decoder allocation fix: numerical-library worker pools are restricted to one thread so their baseline committed memory does not consume the safety budget. Real cues 1, 7, and 34 pass offline decoding; the suspect cue remains blocked. Safety limits stay enabled. See [Audio safety guide](AUDIO-SAFETY.md).


## Completed: Open Play list ordered by last opened

Status: Implemented. Successful version, recovery, and named-launch opens update application recency; failed/canceled opens do not.

- Sort productions in the Open Play list by when they were last successfully opened, most recently opened first.
- Track last-opened time separately from save/version timestamps.
- Use a stable fallback order for productions that have not been opened before.


## Completed: Reuse audio validation across launches and mode entry

Status: Implemented, including persistent results and an explicit Recheck Audio action.

Current behavior: import validation and metadata results persist locally by file identity. Unchanged assets reuse those results across launches; missing/changed or uncached legacy assets are checked as needed. Mode entry retains lightweight cue/output readiness checks.

- Persist successful import validation and audio metadata so unchanged assets do not need decoder-based rechecking on every launch or Show/Rehearse entry.
- Use quick file existence/change checks to identify missing, replaced, or modified assets; revalidate only new or changed files (and previously unvalidated legacy assets).
- Keep non-file readiness checks for cue settings, trim bounds, routing/device availability, and required output configuration.
- Keep playback preparation and decoder timeout/memory protections; preparing audio for playback is separate from validating an import.
- Retain an explicit manual Recheck Audio action for troubleshooting.
- Make progress/status text distinguish validation, readiness checks, and playback preparation.


## Completed: Faster arming and playback preparation

- Reuse decoded PCM from a bounded persistent local cache after RAM eviction or application restart.
- Preserve playback-ready PCM during import validation, including reuse after copying into a production.
- Share cached PCM for identical source content under different filenames; verify changed content via file identity before reuse.
- Warm the next audio cue while the armed cue is ready/preparing, prioritizing the armed cue.
- Use RAM LRU access and throttle repeated UI file-identity reads to approximately once per second; GO and completed decoder jobs still check current identity.
- Keep the 256 MiB RAM cache, 128 MiB per-clip limit, active-data budget, timeout, isolation, and corrupt-file protections. The local decoded disk cache is bounded at 512 MiB.
- Explicit Recheck Audio bypasses validation results and refreshes preparation state. First-time uncached legacy playback or an evicted disk entry may still require decoding.

See [Playback performance and recent plays](PLAYBACK-PERFORMANCE.md). Current full suite: 386 tests, including thirteen new cache/recency checks.


### Small MP3 end-length discrepancies

A clean MP3 decoder EOF up to 0.25 seconds before the reported end is accepted at the physical file end and logged as `AUDIO LENGTH ADJUSTMENT`. Playback uses the samples actually decoded. Reported duration remains available for compatibility with existing saved trim endpoints. Explicit earlier trim endpoints, empty audio, larger shortfalls, native decoder warnings, timeouts, and memory limits retain their protections. This fixes cue 41 being armed but blocked from GO after cue 39; restart the application to clear previously cached preparation failures.

Verification: all 386 tests pass. Real cue 39 to cue 41 automatic continuation also passes with offline rendering (no hardware output).


Mode entry now visibly disables both mode buttons during readiness checks. A progress panel directly above them identifies the current cue, completed/total cue count, and an approximate seconds-remaining countdown. The estimate starts at 0.25 seconds per cue (minimum one second), then adapts to observed progress; slow checks explicitly say they are taking longer. It is an estimate, not a fixed unlock delay. The requested mode opens automatically after successful checks and any required confirmation/save. Errors or edits during checking restore the controls for retry.


Each Playing card also has a **2s fade-and-complete** icon beside Stop and the configured Fade control. It fades only that playback over two seconds (or ends at its earlier natural end), including repeating playback, then reports normal completion. The saved Next Cue Action applies: GO on End automatically starts the armed cue; Arm Next at End arms the successor; Arm Next Now keeps its already armed cue. Saved level, repeat and fade settings are unchanged. Repeated presses cannot extend this fade. The card Stop button completes normally immediately and honors Next Cue Action; STOP ALL cancels automatic continuation. The existing configured fade remains an interrupted ending.


Import silently measures the decoded whole-source sample peak and counts samples near full scale. Inline Browse / Import and the Advanced Cue Editor show a nonblocking level warning after successful import for full-scale peaks (possible source clipping), little headroom (within 1 dB of full scale), or peaks that could exceed full scale with the current cue and selected bus levels. These are advisory, not import failures. Source peaks alone cannot prove distortion; whole-source estimates may overstate trimmed/faded playback peaks and cannot predict operator-timed overlapping sounds. Peak results persist with validation by file identity; older cached proofs acquire peak analysis on the next import without discarding the decoded cache.

Edit now includes the shared Audio Health panel beside TEST progress/meters, including Diagnostics / Logs. It shows Idle without active playback, live load/clipping/dropout measurements during TEST, and output loss even when idle. Diagnostics / Logs is consolidated into the Edit System Status panel.

The Playing card square Stop button now completes that playback immediately as a normal ending: Arm Next at End arms the successor; GO on End queues automatic GO on the already armed cue; Arm Next Now keeps its current armed cue. STOP ALL, internal Stop Previous/Stop All behavior, output loss, and configured interrupting fades retain their cancellation semantics.

Verification: 386 automated tests pass, including silent peak/cache checks, inline and Advanced import warning display, Edit health states/output loss, and card Stop for every Next Cue Action. The Pre-Audience test dialog update also passes 33 related workflow/diagnostics tests. Edit and test dialog layouts were reviewed with offline renders; no hardware playback was used.


Stop and Fade cues now expose **Next Cue Action** in the Edit table and Advanced Cue Editor, and the Armed Cue summary shows the saved choice. **Arm Next Now** arms the successor immediately; **Arm Next at End** waits for the action to finish and then arms it; **GO on End** arms it immediately and automatically executes it after completion. Stop completes immediately. Fade waits for every playback it targeted to end; new playbacks started later are not part of that fade. A silent target or zero-duration Fade completes immediately. Manual GO/arming/navigation cancels the old automatic continuation; STOP ALL and output interruption still cancel it. Existing files keep their stored choice (normally Arm Next at End), with no format change.

Stop/Fade Next Cue Action verification: 196 related engine, editor, UI, storage, and playback checks pass, including 17 new action-specific cases. These cover all three choices, multiple fade targets, silent targets, zero fades, manual override, emergency cancellation, persisted editing, and playbacks started after a fade begins.

Cue 15.1 troubleshooting: the latest Clue 26 rehearsal recovery referenced 17.0 with a 0.5-second fade. A new version corrects its target to 15.0 and duration to 5 seconds, preserving the original recovery in its backups folder. Actual-source offline verification confirms immediate fade initiation on GO, five-second completion, and arming 17.0. Target/duration/count logging and a five-second regression were added; 35 related action/mixer tests pass. Already-open application state requires the same two field edits or reopening the corrected saved version.


Edit now uses a compact **System Status / Cue Controls / Project & Navigation** dashboard. It hides after successful Rehearsal or Show entry and restores on return. All three cue-list views include a read-only **Duration** column showing the edited Play length (one pass for loops), Fade duration, or Immediate for stops. Source metadata loads asynchronously when needed; cue files and playback behavior are unchanged. See [Edit dashboard and cue duration](EDIT-DASHBOARD.md).

Completed approved Edit dashboard / hide-on-performance / shared Duration work. Full suite: 386 passing tests; source compilation and desktop/narrow visual review pass. Eight new checks cover derived read-only duration, asynchronous source lengths, both mode hide/restore paths, responsive panels, unique commands, and selection boundaries.
