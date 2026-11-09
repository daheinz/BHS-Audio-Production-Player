# BHS Audio Production Player - Current Feature Snapshot

Updated November 9, 2026. Suitable for pasting into another ChatGPT conversation.

Windows/Python/PySide6 theatrical sound cue player. This update focuses on a working GUI and supporting production state; it does not establish live-performance readiness.

## Real-audio practice production

An eight-cue **Audio Prototype** production was built from five copied local Music assets: fanfare, looping train ambience, bell, music excerpt, and train arrival, plus FADE / STOP / STOP ALL actions. It uses one stereo Main bus and persists edits, history, and recovery. `Launch Audio Prototype.cmd` opens its latest saved version with the normal recovery flow. First launch asks for an explicit output-device choice; no sound auto-starts.

Offline real-asset execution passed for the sequence, with no clipping in the tested mix. Physical audibility and device reliability are still unverified. See `Documentation/AUDIO-PROTOTYPE.md` for the walkthrough.

## Implemented GUI and state

- Configurable Dark/Light viewing mode, defaulting to Dark. Applies across editors, Show/Rehearse, tables, dialogs, and file pickers; saved as an application preference independently of productions.

- Production creation with a definitive production-owned audio profile, followed by the profile tester; production/version library and recovery restoration remain available.
- Profile editor for one to six mono/stereo buses, required Main, stable references, names, percentage levels, primary device/channel maps, board-input labels, and optional combined backup mapping/relative levels. No profile switching or remapping workflow.
- Spreadsheet cue editing with inline controls, field help, column-width preferences, audio import, add/remove/reorder, and bus selection beside the action. Double-click/F2 replace the removed Edit Selected Cell button.
- Edit-only left-edge drag grips reorder cues with an insertion line, preserved references/selection, and recovery saving. Both Cue ID cells at each numeric reversal are highlighted; `1.0, 1.2, 1.1, 1.3` flags `1.2` and `1.1`. No automatic sorting or renumbering.
- Right-click an assigned Audio File cell for Play / TEST Audio; output readiness and TEST isolation rules still apply.
- Selected-cue graphical clip panel replaces the five timing spreadsheet columns: mono/stereo source waveform, excluded regions, draggable Start/End and IN/OUT handles, and source-time axis. A splitter adjusts table/panel space; precise numeric editing remains in Advanced Cue Editor.
- FADE actions have a separate target-duration envelope rather than source trim controls. Source files remain unchanged. Graph edits apply on release; Advanced changes require OK; Escape cancels an active graph drag.
- Waveform peaks load in bounded background blocks with a small cache and stale-result protection. Unsupported waveform decoding reports an error while preserving numeric access.
- Advanced Cue Editor shares the same cue data, supports multiple buses, and applies changes only after validation.
- Cue IDs are exact text: 12.1 and 12.10 coexist and survive saving/loading. Performance order stays explicit.
- Referenced-cue deletion is blocked. Review Linked Cues can retarget or explicitly delete linked STOP/FADE cues before removing their original target.
- Shared Show/Rehearse view: full-height cue list on the left (roughly two-thirds), fixed yellow Armed Cue container above a separate bottom-aligned Playing Stack on the right. Resizable divider, scrolling table/stack, and compact bottom readiness, GO / STOP ALL, route controls, and locked bus meters. Edit layout unchanged.
- Compact orange playback cards grow upward from the bottom, newest above oldest, with playback numbers, timing progress bars, per-cue bus/route identity, LOOPING / FADING states, and instance-local STOP/FADE icons. No per-playback meters; master/bus meters remain at bottom right, capped at 144 logical pixels. Selected rows/cards use blue outlines; armed rows/buttons are yellow; interrupted rows differ from completed.
- Show/Rehearse reuse a prepared silent stream across Edit transitions; voices still stop and disarm on exit. Automated callback tests confirm identical output between modes; physical Rehearse audibility requires retesting.
- No global master control in the GUI. Software levels and routing are configured in Edit and locked in Show/Rehearse.
- Leaving Show/Rehearse stops output and disarms; re-entry needs explicit row ARM or Enter, then GO. Entering stops TEST. Selection remains silent and Spacebar suppresses repeats/modal triggering.
- Pre-Audience Audio Test supports manual path selection, Play Again with audible-output confirmation, human Confirmed Audible, Skip / Not Working, Stop Test, and session/configuration confirmation tracking.
- Show entry offers Run Test / Enter Without Testing / Cancel for unconfirmed audibility; invalid/unavailable routes cannot be overridden. Warnings remain visible.
- Quiet validation before Show/Rehearse, plus optional Show Readiness with correction paths.
- Meaningful changes create a new history version on Edit Save, Show entry, and application exit. No-change events create none; Rehearse uses separate recovery autosave. Required-save failure blocks the transition.
- Silent `--gui-preview` with isolated sample data lets operators inspect GUI workflows without audio hardware or production saves.

## Connected audio in this pass

The existing stereo engine supports overlap, cue gain/fades, loops, trims, and monitoring. Finite PLAY clips now apply their configured fade-out at the playable end; loops reserve OUT for manual fading and do not fade each repetition. A narrow adapter connects a single stereo Main bus on hardware outputs 1/2, including its bus level, real output meter, TEST audition, and a low-level left-then-right path test. An optional stereo backup on outputs 1/2 of its selected endpoint uses the same cue data and prepared combination gain.

Deliberate route switches drop sounds and preserve independently armed cues; interrupted waits leave nothing armed. Output-loss handling disables GO and cancels pending advancement. There is no automatic switchback or replay.

## Pending integration / verification

- Multiple buses, mono routes, custom output-channel maps, and general combined backup feeds are configurable but not connected to playback. Those controls report unsupported status; playback/test confirmations are blocked rather than simulated.
- Individual bus meters on combined backup remain unavailable. Intended ASIO/USB mixer compatibility is unverified.
- Large-file bounded streaming and decoder packaging remain future backend work; AAC/M4A currently needs optional PyAV.
- Current full suite: 333 tests passed. Automated tests and offscreen screen review are not hardware audibility, latency, reliability, or student usability verification.

## Legacy loading

Older cue sets still load. Their former master value is preserved as the Main bus output level; the original field is retained for compatibility. A visible migration note requires reviewing routing and deliberately selecting the primary device. Historical versions are not rewritten.

Approved requirements: DOC-001 v1.1, DOC-002 v0.2, DEC-001 v1.0, ARCH-001 v1.0, TEST-001 v1.0. See `Documentation/GUI-IMPLEMENTATION-STATUS.md` for source links and verification details.


## Arming and completion choices

Show and Rehearse have an **ARM** button at the far left of every cue row. Clicking it silently arms that cue; only one cue is armed at a time. Clicking another replaces it. Clicking the armed row again keeps it armed and cancels any queued automatic GO. The yellow Armed Cue card at the upper right identifies what GO will execute, independently of the selected row and playing cards.

- **Arm Next at End**: natural completion arms the next cue and waits for GO. Existing saved On Complete cues retain this behavior.
- **GO on End**: arms the next cue immediately, then automatically executes that armed cue at natural completion. Each PLAY cue must opt in separately to continue a chain.
- **Arm Next Now**: advances when triggered, allowing overlapping sounds.

Stops, navigation, manual arming, output interruption, and mode exit cancel automatic continuation. Loops require Arm Next Now. STOP/FADE/STOP ALL actions retain their existing advancement behavior. Automatic GO runs on a subsequent UI update, pauses while a modal dialog is open, and is not sample-accurate audio sequencing.


## Show keyboard controls

Space = GO (only when enabled); Ctrl+Shift+S = existing immediate STOP ALL; Up/Down in the cue table = selection only; Enter = arm selected row; Ctrl+F = fade the explicitly selected/focused playback card. Typing/modal contexts are protected and held Space does not repeat GO. The redundant bottom ARM CUE button is removed. Existing On GO interruption settings, completion behavior, routing, file compatibility, and stop-all semantics are preserved. See `Documentation/SHOW-MODE.md`.


The **Next Cue Action** column (formerly Advance Mode) uses **Arm Next Now**, **Arm Next at End**, and **GO on End**. Stored values remain compatible. GO on End now visibly arms its successor during playback, then executes that armed cue at completion.


## Live playback level and repeat

Each playing card has a **Level** slider (0-400%, before the locked bus level) and a working **Repeat** checkbox. They start with that cue's volume and loop values. Adjustments affect only that active instance, including when the same cue is playing more than once; saved cue settings stay unchanged and a later playback starts with the cue defaults again. 0% mutes without stopping; 100% is unity.

Repeat loops the configured trimmed segment. Turning it off finishes the current pass, including the configured end fade; it does not stop immediately. Manual STOP/FADE still ends the instance, even with Repeat checked. For Arm Next at End / GO on End cues, repeating delays natural completion and continuation until Repeat is turned off. These controls do not change cue order, routing, or bus levels.


GO on End arms its successor when the source starts, so the yellow card and ARMED row flag identify the actual cue that will run at the source's natural end. Manual GO can start that cue early and cancels the old end trigger, preventing double execution. Selecting a table row changes neither arming nor the trigger; explicit ARM/Back navigation cancels automatic follow. Interrupting the waiting source cancels its automatic continuation and disarms its dependent successor. At the end of the list there is no successor and no wraparound.


Playback state colors are session-only. Entering Show or Rehearse starts with neutral rows and no cue armed; previous rehearsal results are cleared. Saved/recovery files retain cue settings but do not restore previous Completed, Interrupted, Playing, or Armed states. Existing files load without conversion.


The Armed Cue uses the same rounded card shape, compact title, padding, and spacing as playing cards, with its state color retained in yellow. Cue details and notes sit inside the card. Both Armed Cue and Playing Stack containers have stronger two-pixel borders and bold headings.


## Following the current cue

In Show and Rehearse, the cue list follows the armed cue as execution advances (or the waiting source when no successor is armed). Early cues leave the list at the top. Once the current cue reaches the visible midpoint, further advancement scrolls to keep it centered, until the bottom of the list prevents further centering. Selection and horizontal scroll remain unchanged. Follow occurs when the current cue changes, so manual browsing between cue changes is not overridden by periodic refresh.


## Audio health and logs

Show/Rehearse now have a bottom Audio Health gauge showing processing load, cumulative output underflows (dropouts), and clipped audio blocks. Green is normal, amber indicates reduced processing headroom, and red holds recent dropout/clipping alerts for five seconds. This is not buffer fullness or a guarantee of audibility. Hover for peak load, over-budget callbacks, and stream settings.

Use **Diagnostics / Logs** beside the gauge or in Edit to view recent logs and current context, **Copy report**, or **Open Logs Folder**. Local UTC-timestamped logs live under `logs/bhs-player.log` in the project folder and rotate at 2 MiB with four backups. Counters are updated without log I/O in the audio callback; log writes use a listener thread. See [Audio diagnostics guide](Documentation/AUDIO-DIAGNOSTICS.md).


## Audio safety safeguards

Playback preparation, new-import validation, and waveform extraction use disposable decoder processes with time/data limits; Windows workers also have a memory/lifetime Job Object. The normal GUI keeps GO disabled while preparing instead of decoding on its UI thread. Failures leave the cue armed with an explanation and preserve existing playback. GO on End waits for preparation without firing twice. Suspect new imports are rejected before copying or changing a cue reference.

Use Diagnostics / Logs for AUDIO SAFETY REJECT and AUDIO PREPARE FAILED details. Default limits are 5 seconds for metadata, 20 seconds for decoding, 128 MiB decoded PCM per clip, and 256 MiB each for prepared and active audio. Long but valid recordings may need a shorter export/segment. Existing production files and originals are not rewritten. See [Audio safety guide](Documentation/AUDIO-SAFETY.md).


Show/Rehearse cue columns now use compact widths, hide Audio File, and label the ID and output columns Cue and Bus. Full text remains available on hover and columns can be resized. Their width preferences are shared between Show and Rehearse but kept separately from Edit, whose columns remain unchanged.
