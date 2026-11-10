# Show and Rehearse operator guide

Updated November 9, 2026. This guide describes the approved Show Mode redesign, which also applies to Rehearse. Edit Mode retains its existing layout.

## Screen layout

The main work area uses roughly two-thirds width for the full-height cue list and one-third for two separate containers. Drag the divider to adjust those widths. The cue table scrolls horizontally for additional fields and vertically for additional cues. Cue IDs and names lead the table; ARM controls remain at the left edge during horizontal scrolling.

The ARMED CUE container stays at the upper right. An armed cue has a compact light-yellow card with its ID, name, action, bus assignments where relevant, and operator notes. **GO on End** keeps the successor genuinely armed in the yellow card and table flag while the source plays; the detail names the source whose end will trigger GO. **Arm Next at End** leaves no cue armed until completion. The neutral **No cue armed** message appears only when there is no armed cue.

The separate Playing Stack fills the remaining right-hand space. Cards align at the bottom: oldest at the bottom, newest above it. Overflow scrolls without moving the armed container. Finished/stopped instances disappear. Every active instance has its own card, including repeated executions of the same cue.

The compact bottom strip contains system/readiness warnings and route controls on the left, green GO and red STOP ALL together, and locked output meters on the right. Meter groups retain the production's bus definitions and scroll horizontally when necessary. There is no bottom ARM CUE or Ready for GO button.

## Selection, arming, and state colors

Clicking a table row selects it; selection alone never changes the armed cue. Click the row's **ARM** control, or select the row and press Enter, to arm it silently. Only one cue can be armed. Clicking another ARM replaces it. Clicking the already armed row keeps it armed and cancels a queued automatic GO.

- Available: neutral dark/muted blue.
- Armed: light yellow with dark text, including the ARMED row control.
- Playing: orange with light text.
- Completed: muted gray.
- Interrupted: muted warning/plum, distinct from completed.
- Selected: blue outline independent of the state fill.

A cue may have multiple playing instances while also being armed again. The row fill shows active playback; its ARM/ARMED control still identifies whether it is armed. The right-hand armed card remains yellow.

## Playback cards

Each orange card shows the cue ID/name, playback number, PLAYING/FADING/LOOPING state, position/duration/remaining time where applicable, a compact position bar, and that cue's bus names plus the current primary/backup route indication. Different cue bus assignments remain distinct. The display does not add routing capabilities to the backend.

The square icon stops only that playback immediately and runs its normal Next Cue Action. The descending-line icon fades only that playback using its configured fade-out duration; zero stops immediately. Hover tooltips are **Stop this playback** and **Fade out this playback**. The armed card has neither control.

There are no per-playback audio level meters. Position bars indicate time, not signal level. Master/bus stereo meters are at the bottom right, with L/R dBFS readings and locked-level labels. Graphical meters remain 144 logical pixels wide (approximately 1.5 inches at standard scaling). Unsupported/combined-backup meter paths report unavailable rather than fabricated levels. Meters do not confirm sound at the speakers.

## Keyboard and bottom controls

| Control | Action |
| --- | --- |
| Space / GO | Execute the armed cue through the existing GO function |
| Ctrl+Shift+S / STOP ALL | Existing immediate Stop All, without a confirmation dialog |
| Up / Down in cue table | Select previous/next row; never arm automatically |
| Enter in cue table | Arm the selected row without playing it |
| Ctrl+F on a selected playback card | Fade only that instance; click the card first and keep keyboard focus within it |
| Back | Existing backward cue-navigation behavior, including explicit arming |

GO is disabled when no cue is armed, output is unavailable, or GUI Preview disables playback. Space does nothing in those cases. Held/repeated Space presses cannot run a sequence of cues. Show shortcuts do not intercept text-entry fields, editable combo boxes/spin boxes, or modal dialogs. Tab and other standard navigation remain available. Ctrl+F does not guess a playback from the selected cue-table row.

GO can execute while other sounds are playing. **Add to Play Stack** preserves overlap; existing **Stop Previous and Add** and **Stop All and Add** settings intentionally retain their interruption behavior. STOP ALL also retains existing semantics: it cancels pending continuation and interrupts a waiting cue; an independently armed cue may remain armed. It does not change routing or saved cue settings.

## Completion and readiness

**Arm Next at End** arms the next cue after natural completion and waits for GO. **GO on End** arms the next cue immediately and automatically executes that same armed cue when the source finishes naturally, on a subsequent UI update. Each source PLAY cue must opt in to continue a chain. **Arm Next Now** advances immediately when triggered. STOP ALL, configured interrupting fades, manual navigation/arming, output interruption, and mode exit cancel queued automatic continuation. A Playing card Stop completes normally and honors Next Cue Action. Loops require Arm Next Now. Existing cue files load with the same stored action choices; GO on End now arms its successor during playback. No cue-set format change is required.

Readiness, device, board confirmation, and backup warnings remain visible at the bottom left. Unconfirmed outputs are not labeled confirmed. Deliberate route switching retains its existing confirmation and interruption behavior. Leaving Show/Rehearse stops all voices and disarms; the prepared stream can remain open pumping silence between modes.

## Verification

Run `python -m pytest -p no:cacheprovider` and `python tools/render_gui.py`. The current suite has 360 passing tests. Offline renders include `output/gui-review/playing-stack.png` (1500 by 920) and `playing-stack-small.png` (1000 by 700), plus Rehearse and unchanged Edit screens. These are silent/offscreen checks, not physical audibility or performance-reliability verification.


The **Next Cue Action** column (formerly Advance Mode) uses **Arm Next Now**, **Arm Next at End**, and **GO on End**. Stored values remain compatible. GO on End now visibly arms its successor during playback, then executes that armed cue at completion.


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


Mode entry now visibly disables both mode buttons during readiness checks. A progress panel directly above them identifies the current cue, completed/total cue count, and an approximate seconds-remaining countdown. The estimate starts at 0.25 seconds per cue (minimum one second), then adapts to observed progress; slow checks explicitly say they are taking longer. It is an estimate, not a fixed unlock delay. The requested mode opens automatically after successful checks and any required confirmation/save. Errors or edits during checking restore the controls for retry.


Each Playing card also has a **2s fade-and-complete** icon beside Stop and the configured Fade control. It fades only that playback over two seconds (or ends at its earlier natural end), including repeating playback, then reports normal completion. The saved Next Cue Action applies: GO on End automatically starts the armed cue; Arm Next at End arms the successor; Arm Next Now keeps its already armed cue. Saved level, repeat and fade settings are unchanged. Repeated presses cannot extend this fade. The card Stop button completes normally immediately and honors Next Cue Action; STOP ALL cancels automatic continuation. The existing configured fade remains an interrupted ending.


Stop and Fade cues now expose **Next Cue Action** in the Edit table and Advanced Cue Editor, and the Armed Cue summary shows the saved choice. **Arm Next Now** arms the successor immediately; **Arm Next at End** waits for the action to finish and then arms it; **GO on End** arms it immediately and automatically executes it after completion. Stop completes immediately. Fade waits for every playback it targeted to end; new playbacks started later are not part of that fade. A silent target or zero-duration Fade completes immediately. Manual GO/arming/navigation cancels the old automatic continuation; STOP ALL and output interruption still cancel it. Existing files keep their stored choice (normally Arm Next at End), with no format change.
