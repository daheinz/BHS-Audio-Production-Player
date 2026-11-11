# Playing Stack and master meters

Updated November 9, 2026.

## Reading the stack

Show and Rehearse display one card for every active playback, in a separate right-hand container below the fixed Armed Cue container. Cards align at the bottom, with the oldest sound at the bottom and each newer sound above it. Overflow scrolls independently. The stack can contain several sounds at once. Replaying the same cue creates another card; the playback number distinguishes the instances.

Each card contains:

- Cue ID, name, and PLAYING / FADING / LOOPING status.
- A compact progress bar showing playback position. This is a timing display, not a loudness meter.
- Elapsed/remaining time, or current-loop position and total elapsed time.
- That cue's bus names and the current primary/backup route indication.
- Square STOP and descending-line FADE OUT icons affecting only that instance, with tooltips "Stop this playback and run Next Cue Action" and "Fade out this playback". Click the card and use Ctrl+F to fade that explicitly selected/focused instance.

Finished or stopped cards disappear. The yellow Armed Cue above the stack is the instruction GO will execute next; it can differ from all the sounds currently playing. Arming or selecting a cue does not start it.

In the Audio Prototype, run 2.0 (looping engine), then 2.1 (bell), then 3.0 (music). After the bell ends, music is the top card and the engine is underneath. Cue 4.0 is armed separately. GO on 4.0 fades the music card away while the engine keeps running.

## Meter size and meaning

All graphical signal-level meters have a maximum/fixed width of 144 logical pixels, approximately 1.5 inches at standard UI scaling. They no longer stretch across the window. The orange playback cards use separate, compact position bars; they contain no audio level meters.

Master/bus meters at the bottom right show the mixed post-bus-level signal for the supported primary stereo path. These do not confirm speaker audibility. The output label now includes the selected endpoint and driver/API identity.

## Rehearse / Show stream handling

Both modes use the same engine and prepared output endpoint. Previously, returning to Edit closed the stream, so the next mode reopened it. The stream is now kept open, pumping silence after all voices and pending advancement have been stopped and disarmed. Re-entry still requires a row ARM click or Enter on the selected cue, followed by GO. This removes repeated device startup between modes.

Changing profile configuration, deliberately switching routes, device failure, or exiting the application still stops/replaces the stream as appropriate. No output is silently redirected, and interrupted audio never restarts automatically.

Automated callback tests verify identical nonzero sample buffers across Rehearse → Show → Rehearse, silence after each mode exit, and one stream open for that sequence. They do not confirm physical audibility. The reported Rehearse-only silence needs an audible retest after restarting the application; its physical cause was not conclusively reproduced.

## Visual example

`python tools/render_gui.py` now writes `output/gui-review/playing-stack.png`. It shows two offline mixer instances and a separate armed FADE cue. The image is labeled as offline; no output device is opened and no audibility is fabricated.


## Layout and keyboard reference

The full-height cue list occupies the left two-thirds. The bottom strip holds status and compact GO / STOP ALL controls; it has no ARM CUE button. Space executes an enabled GO; Ctrl+Shift+S invokes the existing immediate Stop All. Stop All preserves existing handling of an independently armed cue, so do not assume it always disarms. Up/Down select table rows without arming; Enter arms them. See [Show/Rehearse guide](SHOW-MODE.md) for state colors, shortcut protection, completion choices, and readiness limitations.

The renderer also writes `output/gui-review/playing-stack-small.png` at 1000 by 700 to inspect resizing. The current full suite has 386 passing tests.


## Live playback level and repeat

Each playing card has a **Level** slider (0-400%, before the locked bus level) and a working **Repeat** checkbox. They start with that cue's volume and loop values. Adjustments affect only that active instance, including when the same cue is playing more than once; saved cue settings stay unchanged and a later playback starts with the cue defaults again. 0% mutes without stopping; 100% is unity.

Repeat loops the configured trimmed segment. Turning it off finishes the current pass, including the configured end fade; it does not stop immediately. Manual STOP/FADE still ends the instance, even with Repeat checked. For Arm Next at End / GO on End cues, repeating delays natural completion and continuation until Repeat is turned off. These controls do not change cue order, routing, or bus levels.


GO on End arms its successor when the source starts, so the yellow card and ARMED row flag identify the actual cue that will run at the source's natural end. Manual GO can start that cue early and cancels the old end trigger, preventing double execution. Selecting a table row changes neither arming nor the trigger; explicit ARM/Back navigation cancels automatic follow. Interrupting the waiting source cancels its automatic continuation and disarms its dependent successor. At the end of the list there is no successor and no wraparound.


Playback state colors are session-only. Entering Show or Rehearse starts with neutral rows and no cue armed; previous rehearsal results are cleared. Saved/recovery files retain cue settings but do not restore previous Completed, Interrupted, Playing, or Armed states. Existing files load without conversion.


The Armed Cue uses the same rounded card shape, compact title, padding, and spacing as playing cards, with its state color retained in yellow. Cue details and notes sit inside the card. Both Armed Cue and Playing Stack containers have stronger two-pixel borders and bold headings.


## Following the current cue

In Show and Rehearse, the cue list follows the armed cue as execution advances (or the waiting source when no successor is armed). Early cues leave the list at the top. Once the current cue reaches the visible midpoint, further advancement scrolls to keep it centered, until the bottom of the list prevents further centering. Selection and horizontal scroll remain unchanged. Follow occurs when the current cue changes, so manual browsing between cue changes is not overridden by periodic refresh.


## Audio Health and troubleshooting

The bottom Audio Health gauge reports processing load, output-underflow dropout counts, and clipped-block counts separately from the master signal meters. Amber warns of reduced headroom; red holds recent dropout/clipping alerts for five seconds. It is not a buffer-fill display. Choose **Diagnostics / Logs** there or in Edit for a nonmodal viewer, **Copy report**, and **Open Logs Folder**. UTC logs in the project `logs/` folder rotate at 2 MiB with four backups; measurements and log writes stay separate from audio processing. See [Audio diagnostics guide](AUDIO-DIAGNOSTICS.md) for meanings, limits, and crackling investigations.


## Decoder and import safety

The GUI prepares audio asynchronously in killable, memory-limited Windows decoder workers. GO is disabled while preparing; a failed cue remains armed and blocked with a visible error. GO on End waits for a successful preparation, or reports failure without skipping ahead. Existing audio keeps playing when preparation fails. TEST preparation is also asynchronous and can be canceled.

New imports are fully checked before copying or changing cue references. Native errors, timeouts, abnormal exits, and data/memory budget failures appear in Diagnostics / Logs as AUDIO SAFETY REJECT / AUDIO PREPARE FAILED. Existing assets are not deleted or repaired. The known `36 benny hill.mp3` is blocked under the full-file decoded-data budget and needs a clean replacement. See [Audio safety guide](AUDIO-SAFETY.md) for limits, import behavior, and recovery.


Show/Rehearse cue columns now use compact widths, hide Audio File, and label the ID and output columns Cue and Bus. Full text remains available on hover and columns can be resized. Their width preferences are shared between Show and Rehearse but kept separately from Edit, whose columns remain unchanged.


## Preparation/cache update

The player now retains successful validation, metadata, and playback-ready PCM in a bounded local cache across launches. Import checks prepare reusable PCM; identical audio under different names can share it. One upcoming cue preloads ahead, RAM reuse is LRU, and repetitive UI file-identity polling is throttled. GO still checks current identity and retains all safety protections. Uncached legacy/changed clips or disk-evicted entries can still need initial decoding.

Use **Recheck Audio** in Edit for an explicit full scan. Open Play is now ordered by last successful open, not last save. Diagnostics logs record decoded-cache hits and preparation elapsed time. See [Performance and recent plays](PLAYBACK-PERFORMANCE.md) for cache location/limits, first-use behavior, and measured offline timings.


Each Playing card also has a **2s fade-and-complete** icon beside Stop and the configured Fade control. It fades only that playback over two seconds (or ends at its earlier natural end), including repeating playback, then reports normal completion. The saved Next Cue Action applies: GO on End automatically starts the armed cue; Arm Next at End arms the successor; Arm Next Now keeps its already armed cue. Saved level, repeat and fade settings are unchanged. Repeated presses cannot extend this fade. The card Stop button completes normally immediately and honors Next Cue Action; STOP ALL cancels automatic continuation. The existing configured fade remains an interrupted ending.


Import silently measures the decoded whole-source sample peak and counts samples near full scale. Inline Browse / Import and the Advanced Cue Editor show a nonblocking level warning after successful import for full-scale peaks (possible source clipping), little headroom (within 1 dB of full scale), or peaks that could exceed full scale with the current cue and selected bus levels. These are advisory, not import failures. Source peaks alone cannot prove distortion; whole-source estimates may overstate trimmed/faded playback peaks and cannot predict operator-timed overlapping sounds. Peak results persist with validation by file identity; older cached proofs acquire peak analysis on the next import without discarding the decoded cache.

Edit now includes the shared Audio Health panel beside TEST progress/meters, including Diagnostics / Logs. It shows Idle without active playback, live load/clipping/dropout measurements during TEST, and output loss even when idle. Diagnostics / Logs is consolidated into the Edit System Status panel.

The Playing card square Stop button now completes that playback immediately as a normal ending: Arm Next at End arms the successor; GO on End queues automatic GO on the already armed cue; Arm Next Now keeps its current armed cue. STOP ALL, internal Stop Previous/Stop All behavior, output loss, and configured interrupting fades retain their cancellation semantics.


Stop and Fade cues now expose **Next Cue Action** in the Edit table and Advanced Cue Editor, and the Armed Cue summary shows the saved choice. **Arm Next Now** arms the successor immediately; **Arm Next at End** waits for the action to finish and then arms it; **GO on End** arms it immediately and automatically executes it after completion. Stop completes immediately. Fade waits for every playback it targeted to end; new playbacks started later are not part of that fade. A silent target or zero-duration Fade completes immediately. Manual GO/arming/navigation cancels the old automatic continuation; STOP ALL and output interruption still cancel it. Existing files keep their stored choice (normally Arm Next at End), with no format change.


Edit now uses a compact **System Status / Cue Controls / Project & Navigation** dashboard. It hides after successful Rehearsal or Show entry and restores on return. All three cue-list views include a read-only **Duration** column showing the edited Play length (one pass for loops), Fade duration, or Immediate for stops. Source metadata loads asynchronously when needed; cue files and playback behavior are unchanged. See [Edit dashboard and cue duration](EDIT-DASHBOARD.md).
