# GUI-first implementation status

Current Show/Rehearse layout and controls: [operator guide](SHOW-MODE.md). The dated sections below retain implementation history; the final approved-redesign section supersedes earlier screen layouts and reports current verification.

November 3, 2026. This handoff distinguishes available GUI, connected behavior, and hardware verification.

## Sources read

- User-supplied `VS-Code-AI-GUI-First-Instructions.md` from the attached local path.
- [DOC-001 Project Overview v1.1](https://docs.google.com/document/d/1D8venfmmV-NhkIw1CnKbuWnKa6Q6GRjKn8yH8unu54c/edit).
- [DOC-002 Detailed Requirements v0.2](https://docs.google.com/document/d/1jKmJ7jITTiOwQJUxdYhEs1Uw3dVdIp8jP3T4pAz1Lwk/edit).
- [DEC-001 Approved Design Decisions v1.0](https://docs.google.com/document/d/1lWPQzc5CXnWRvhFQcMEnW5I-kd59fCheIS_UYlkrpr8/edit).
- [ARCH-001 Audio Routing and Recovery v1.0](https://docs.google.com/document/d/1ybsgY3oYjmi71zm4ZpLS0uGlPGU7pmtIKa33O64iOzo/edit).
- [TEST-001 Pre-Audience Test and Acceptance v1.0](https://docs.google.com/document/d/1wmdcvvSbxhuSjstS7RqLbeqTvIwjd6PStN9411ETxyE/edit).
- Existing source, tests, README, and prior feature snapshot (now under Obsolete).

The five approved documents were fetched through the Google Drive skill/connector and were not edited. ChatGPT project chat history was not available through the connected tools; no unobserved chat decisions were assumed.

## Screens and workflows

| Area | GUI / state | Audio connection |
| --- | --- | --- |
| Production creation | Choose a starting profile, configure defined buses, save definition, open tester before cue preparation | Device enumeration is real; unavailable hardware remains visible |
| Profile and Routing | One to six defined buses; stable required Main; mono/stereo, levels %, channels, board labels, optional backup and combination levels; validation and safe Cancel | Single stereo Main on channels 1/2 only; general routing remains unsupported |
| Spreadsheet / Advanced Editor | Shared cue objects; exact text IDs; multi-bus advanced assignment; apply only after validation; import and trim retained | Existing decoder/engine reused |
| Linked-cue review | Block deletion; list dependencies; explicit retarget or confirmed dependent deletion; Cancel preserves unresolved target | No special backend needed |
| Show / Rehearse | Same view/controller; locked editing/software levels/routing; armed identity/action/buses/notes; per-instance controls; bus displays; output state; visible GO reason | Existing stereo playback; no automatic playback on entry; stop/disarm on exit |
| Audio tester | Repetition, explicit next/skip, prominent Stop, human confirmation, invalidation on profile changes, pre-show warning override | Real left-then-right tone for supported stereo route; disabled for unsupported routes |
| Readiness | Quiet entry checks; optional summary with Profile, Audio Test, and Review Cues correction actions | Invalid/unavailable required output blocks normal entry |
| Output recovery | Deliberate primary/backup controls; interrupted waits canceled; independent arming preserved; no replay/switchback | Connected only for supported stereo endpoints; no verified USB/ASIO claims |
| Saving | Shared dirty baseline; changed-only Save/Show entry/exit; Rehearse recovery only; failures block required transitions | Existing atomic version/recovery storage retained |
| GUI preview | Isolated sample production and Show/Rehearse layout access; no production persistence | Audio and GO disabled; meters are not simulated |

Defined buses remain visible even if unused. Main does not sum other buses. Normal productions with unsupported configurations remain editable but cannot enter performance playback; use the explicit GUI preview to inspect Show/Rehearse without hardware.

## Migration and compatibility

Cue-set format 2 adds the production profile, stable bus assignments, and migration notes. Version-1 cue sets load without rewriting their files. Their master scalar is copied to the new Main bus level and retained in the legacy field. No global master interface remains. The existing mixer's scalar is reused internally only to apply the supported single bus's level (and its backup combination gain).

Legacy output is unresolved until deliberately configured; loading does not guess a device or silently route to Windows default. Historical files stay unchanged. Current saves retain profile definitions and explicit cue order. Cue IDs 12.1 and 12.10 now coexist, as required by v0.2.

Import still avoids overwriting a different asset. Cue history protects settings/references, not externally replaced shared audio contents.

## Initial GUI/state verification (historical)

- Full command: `python -m pytest -p no:cacheprovider`.
- 211 tests passed after the GUI/state implementation, including updated v0.2 expectations and focused profile, migration, editor synchronization, atomic failed edit, tester, route switch/loss, mode exit, linked-cue reconciliation, keyboard/modal safety, save-failure, and preview-silence coverage.
- Output tests use controlled fake streams and offline PCM rendering. They do not send sound to physical hardware.
- `python tools/render_gui.py` renders Edit, Profile, Advanced, Audio Test, Linked Cues, and Rehearse using offscreen Qt and explicit Windows fonts. All six images were inspected; bus visibility, advanced-editor sizing, action-specific fields, and visible mode/GO information were refined.
- Images are generated under `output/gui-review/` and excluded from Git. Offscreen visual review does not establish native desktop interaction or real-device behavior.

## Remaining backend work and known limits

- General multibus rendering, mono/custom channel routes, multichannel device output, ASIO compatibility, and combined multi-bus backup playback are not connected. Saved configuration is not a claim of support.
- Combined-backup per-bus meters are unavailable; the path tester reports actual combined output meter values for its supported stereo signal.
- Primary-device reconnection is advisory through refreshed availability and deliberate switch controls; no automatic route change occurs. Real unplug/reconnect timing needs hardware verification.
- Segments remain decoded into memory; bounded large-file streaming and decoder packaging are deferred. AAC/M4A fallback still needs optional PyAV.
- Device preparation can still block on slow endpoints. Decoder, import, waveform, and file-readiness work now use guarded background operations; general real-time stress, hardware timing, and source-format behavior still need verification.
- Edit source-waveform caching remains bounded; Show/Rehearse now use compact position bars instead of the former playback waveform strips. Portable waveform-cache completeness has not been verified.
- No realistic technical rehearsal, board audibility test, intended-mixer test, or student usability session has been performed. This prototype is not labeled performance verified.

## Launch

- `Launch GUI Preview.cmd`: silent sample GUI for review.
- `Launch Player.cmd`: normal production workflow.
- Installed environment: `python -m bhs_player.app --gui-preview` or `python -m bhs_player.app`.

Install dependencies first with `pip install -e ".[dev]"` if needed. Launchers run from the repository so relative production folders resolve consistently.


## November 8 editing update

The three modification chunks are implemented: editing shortcuts, drag ordering/numeric-ID warnings, and graphical source trim/fade editing. See [Requested modifications and verification](REQUESTED-MODIFICATIONS.md) for the completed checklist and usage. The current full suite has 235 passing tests. The graph uses bounded background peak extraction; finite end fades are connected to existing playback. This does not complete multichannel routing, large-file playback streaming, or physical theatre verification.


## November 9 real-audio prototype

A saved eight-cue **Audio Prototype** was created from five copies of local Music-library assets. A dedicated launcher opens its latest version with recovery handling and asks for output selection when unresolved. Original audio files were verified against their imported copies. The entire practice sequence ran successfully through the real decoder/mixer offline; the actual imported waveform was visually inspected. The current full suite has **243 passing tests**. Physical audibility has not been verified. See [Audio prototype walkthrough](AUDIO-PROTOTYPE.md).


## November 9 compact stack / playback-mode follow-up (earlier layout, superseded below)

Level meters now remain 144 logical pixels wide (about 1.5 inches), with timing/waveform strips separate. Playing Stack cards are compact, counted, newest first even on batch arrival, and have playback numbers for repeated cues. Looping fades expose both states; controls stop/fade only their own instance. The empty stack no longer reserves a large blank region.

Show and Rehearse keep the same prepared endpoint pumping silence across returns to Edit, while stopping all voices and canceling/disarming cue advancement. Configuration changes, route switches, failure, and application exit still replace/stop output. This removes repeated stream startup as a potential contributor to the reported Rehearse-only silence; the physical symptom was not conclusively reproduced. Restart and audible retest remain necessary.

The full suite has **247 passing tests**, including actual output-callback buffer equality across Rehearse → Show → Rehearse (controlled fake endpoint), transition silence, no repeated stream opening, meter width, and stack ordering/control behavior. The offline two-card stack render was visually inspected. See [Playing Stack guide](PLAYING-STACK.md).


## November 9 arming and completion update (earlier layout, superseded below)

The user's revised completion request adds opt-in **On Complete - GO!**, alongside **On Complete - Arm** and **On GO / Trigger**. This supersedes the earlier exclusion of automatic follow for this prototype. Existing stored `on_complete` values still mean Arm; the new automatic mode stores `on_complete_go`. Production cues were not automatically changed.

Show/Rehearse now expose exclusive row ARM buttons and a large armed-cue banner above the Playing Stack. Mouse arming never starts playback. Natural completion queues automatic GO for the UI control thread; stops, navigation, manual arming, mode exit, and output interruption cancel it. Old playback instances cannot complete a newer wait. Modal dialogs postpone dispatch. Automatic successor audio is prepared in advance where possible; timing remains dependent on the UI update and audio preparation.

The full suite has **276 passing tests**, including completion chains, cancellation before/after completion, legacy loading, output failure, actual mixer callback/control-thread separation, mouse clicks, modal deferral, editor choices, and exclusive arming. Offscreen Show/Rehearse renders were visually inspected. Physical theatre audibility and timing remain unverified. See the README arming and completion guide.


The subsequent layout revision moves armed-cue information beneath ARM CUE with smaller text, leaving GO directly above the Playing Stack. The revised offline render was inspected and all 276 tests pass.


## Approved Show/Rehearse redesign - current layout

The user's approved redesign supersedes earlier placement, meter, and ARM CUE descriptions in this historical log. The full-height cue list uses roughly two-thirds of the main width; the right third contains a fixed Armed Cue container and separate bottom-aligned Playing Stack. Compact bottom controls put system/readiness status left, GO / STOP ALL together, and existing locked bus/master meters right. The main area receives the remaining height (at least about 75% in the tested window sizes). The divider, table, stack, and meter strip support resizing/scrolling.

Armed cues/cards/row controls use light yellow; active playback uses orange; selection remains a separate blue outline; interrupted cues have a distinct muted warning fill. Compact playback cards have timing position bars, per-cue bus names/current route, playback numbers, and instance-specific STOP/FADE icons. Per-playback audio meters and the bottom ARM CUE button are removed. Waiting playback is described separately from a neutral No cue armed message.

Keyboard controls are Space for enabled GO, Ctrl+Shift+S for existing Stop All, Up/Down for table selection, Enter for table arming, and Ctrl+F for an explicitly selected playback card retaining focus. Text-entry, modal, and repeat protections remain. Existing On GO interruption settings, independent arming on Stop All, automatic completion cancellation, readiness/confirmation checks, output switching, audio processing, and cue-set format are unchanged. Edit-specific delegates/colors and controls are retained.

All 284 tests pass, including eight new focused cases covering both layout sizes, bottom-aligned stack overflow, per-cue bus identity, state colors, real Qt keyboard delivery, text-entry protection, and local stop/fade behavior. The renderer produces updated Show/Rehearse screens plus a 1000x700 small-window stack example; both sizes were visually inspected. These are offline UI/mixer checks, not physical audibility or live-performance certification.

Documentation pass: README, FEATURES, Audio Prototype walkthrough, Playing Stack guide, requested-modification log, this implementation log, and the new [Show/Rehearse operator guide](SHOW-MODE.md) now describe the current UI. Historical results remain labeled by stage; approved source requirements and obsolete snapshots remain historical references.


Current terminology: **Next Cue Action** replaces the Advance Mode heading. Labels are **Arm Next Now** (stored `on_go`), **Arm Next at End** (`on_complete`), and **GO on End** (`on_complete_go`). Earlier labels in this historical log are superseded; execution behavior and saved files are unchanged.


## Live playback controls

Playing cards now expose per-instance Level (0-400%) and Repeat controls initialized from cue defaults. AudioEngine applies changes to the live voice under the mixer lock, without editing cue data or bus/master levels. Repeat off finishes the current iteration naturally; repeat on delays completion-based continuation. Manual fading/stopping remains effective. Tests verify rendered PCM gain, independent repeated instances, natural completion and automatic-GO timing, fade preservation, cue serialization, and defaults on replay. Current full suite: 289 tests; physical audio validation remains separate.


## Armed row flag refresh

The ARM/ARMED vertical header now owns explicit header items and sends section updates when the armed/playing state changes. This keeps Qt header data and the custom-painted flags synchronized on automatic advancement. Regression checks use actual GO button clicks and inspect both header labels and rendered yellow/orange fills in Show and Rehearse. The original stale-flag symptom was not reproduced offscreen; this change strengthens native header invalidation. Current full suite: 291 tests.


## GO on End correction - current completion semantics

The user's clarification changes GO on End to arm its successor immediately while retaining the source completion wait separately. The armed card and row flag now identify the real successor throughout playback. Natural completion dispatches GO on that already armed cue without advancing twice. Manual GO can execute it early, detaches the old source wait, and prevents a later duplicate trigger. Arm Next at End still arms only after completion; Arm Next Now still arms immediately without automatic GO. Manual navigation, early interruption, output loss, mode exit, repeat, and no-wrap protections remain covered. Earlier No cue armed descriptions for GO on End in this historical log are superseded. No production files or serialized values were changed.

Current suite: 297 tests pass, including six additional mode-timing, early-manual-GO, and Show/Rehearse rendered-header/card tests reproducing the 7.0 -> 8.0 scenario with actual offline mixer completion. Physical audio-device testing remains separate.


Fresh-session state correction: Show/Rehearse entry now stops/disarms and resets all cue execution states to Idle, clearing stale rehearsal colors. Serialization writes Idle and ignores historical runtime states on load without changing the format or modifying original saved versions. Current suite: 300 passing tests, including mode transitions/re-entry and legacy/new-file state handling.


Card presentation follow-up: armed identity, details, and notes now share one rounded yellow card with the same typography, margins, and spacing as playing cards. Both right-hand containers have stronger borders and bold headings; no playback behavior changed.


Cue-follow update: Show/Rehearse now scroll on changes of the armed cue (or waiting source if nothing is armed). The table remains at the top through early cues, then centers the current row as advancement continues, clamping at the list bottom. Selection, arming, audio, and horizontal scroll remain unchanged; periodic refresh does not override manual browsing. Pixel scrolling provides smooth row positioning. Regression tests cover both modes, midpoint behavior, actual GO advancement, manual browsing, and end clamping. Current suite: 302 tests.


## Audio Health and troubleshooting logging - implemented

A compact bottom gauge now reports device-library processing load (callback timing fallback), persistent underflow/clipped-block counts, and five-second issue alerts. Over-budget callback measurements are kept distinct from driver-confirmed underflows. Output-loss and unavailable/preview states remain explicit. The panel does not claim buffer fullness or physical audibility.

Diagnostics / Logs is available in Edit and Show/Rehearse. Its nonmodal viewer shows current device/health/playback context and a bounded log tail, with Refresh, Copy report, and Open Logs Folder. UTC logs are kept under project logs/, rotated at 2 MiB with four backups and ignored by Git. Startup/runtime, production/mode, device/route, cue GO/failure, live playback controls, preparation errors, output loss, and aggregated health issues are recorded. Audio callbacks update measurements only; control-thread polling queues events for listener-thread file writes. Existing buffering, latency, routing, and cue-file format remain unchanged.

Current suite: 313 passing tests, including eleven diagnostics cases covering real offline PCM, callback/control-thread separation, counters/status, rotation/threaded writes, logging failure, local report/folder actions, and nonmodal playback preservation. Updated small/large layouts and explicitly simulated health examples were rendered and inspected. Physical hardware verification remains outstanding. See [Audio diagnostics guide](AUDIO-DIAGNOSTICS.md).


## Decoder/import safeguards after the Clue 26 hang

Windows recorded Application Hang after GO on cue 36 (`36 benny hill.mp3`), with no successful start or Python exception logged. Native decoding is now isolated in disposable hidden processes with timeout/stderr/exit-code supervision, Windows 512 MiB memory and kill-on-parent-exit job limits, bounded PCM/cache/active data, and at most two concurrent decoder workers. Normal GUI GO never synchronously decodes; automatic GO waits for readiness and fails visibly without interrupting other voices or skipping cues. Live completion callbacks do not fingerprint files or launch decoder jobs.

Inline and Advanced imports validate asynchronously and reject suspect data before copying/assignment. Copy staging checks source identity/content stability; pending imports block Save/mode entry and cancellation prevents late assignment/copy. Waveforms and metadata readiness checks are guarded too. Optional PyAV remains inside the child boundary. Existing production files and original assets are unchanged. The real offending asset was rejected by the decoded-size check in about 0.5 seconds.

Current suite: 332 passing tests, including nineteen decoder/import safety cases and updated real-audio import fixtures. Compilation and whitespace checks pass. These protections do not repair the suspect asset or establish physical audibility/performance reliability. See [Audio safety guide](AUDIO-SAFETY.md).


Compact performance-table follow-up: Show/Rehearse hide Audio File, use Cue / Bus headings, narrower ARM controls, and compact default widths for all remaining fields. Performance widths use a separate settings namespace so old editing widths do not override the new layout or change Edit.


Decoder memory-overhead follow-up: reproduced ordinary MP3 preparation failing a 512 KiB allocation because NumPy/OpenBLAS committed roughly 500 MiB for its default worker thread pool. Decoder child environments now constrain numerical-library pools to one thread; the player environment and all safety limits are retained. Real Clue 26 cues 1, 7, and 34 decode offline successfully, and suspect cue 36 is still rejected. Current suite: 333 passing tests, including the new large-parent-thread-pool regression. A full relaunch clears cached failures.


## Persistent preparation/validation and recent-play ordering

Implemented both deferred requests and the preparation optimization. Successful validation/metadata persists by file identity; PCM is retained in a bounded local disk cache and generated during import checking. Identical content can share converted data despite differing filenames. RAM access uses LRU, one successor preloads after the armed cue is prioritized, and source identity polling is throttled while GO and worker completion still recheck identity. Manual Recheck Audio performs a fresh full scan and refreshes prepared state. Quick cue/routing/output readiness checks remain at mode entry. Cold uncached legacy clips still require guarded decoding.

Open Play records last successful version/recovery/named-launch opens in application settings; failures and cancellations leave recency unchanged. Never-opened productions fall back alphabetically and save/version timestamps do not determine order. Cache data is outside the synced workspace under LocalAppData, with 512 MiB decoded disk and 1,024 metadata-entry bounds; production formats and source files remain unchanged.

Current suite: 386 tests pass, including thirteen new cache/recency checks. Offline real-asset timing showed cue 43 content reuse at ~0.11 s and cue 34 reload at ~0.08 s; validation reuse was ~13 ms in another check. See [Performance and recent plays](PLAYBACK-PERFORMANCE.md). Physical audio/performance verification remains outstanding.


Mode entry now visibly disables both mode buttons during readiness checks. A progress panel directly above them identifies the current cue, completed/total cue count, and an approximate seconds-remaining countdown. The estimate starts at 0.25 seconds per cue (minimum one second), then adapts to observed progress; slow checks explicitly say they are taking longer. It is an estimate, not a fixed unlock delay. The requested mode opens automatically after successful checks and any required confirmation/save. Errors or edits during checking restore the controls for retry.


Import silently measures the decoded whole-source sample peak and counts samples near full scale. Inline Browse / Import and the Advanced Cue Editor show a nonblocking level warning after successful import for full-scale peaks (possible source clipping), little headroom (within 1 dB of full scale), or peaks that could exceed full scale with the current cue and selected bus levels. These are advisory, not import failures. Source peaks alone cannot prove distortion; whole-source estimates may overstate trimmed/faded playback peaks and cannot predict operator-timed overlapping sounds. Peak results persist with validation by file identity; older cached proofs acquire peak analysis on the next import without discarding the decoded cache.

Edit now includes the shared Audio Health panel beside TEST progress/meters, including Diagnostics / Logs. It shows Idle without active playback, live load/clipping/dropout measurements during TEST, and output loss even when idle. Diagnostics / Logs is consolidated into the Edit System Status panel.

The Playing card square Stop button now completes that playback immediately as a normal ending: Arm Next at End arms the successor; GO on End queues automatic GO on the already armed cue; Arm Next Now keeps its current armed cue. STOP ALL, internal Stop Previous/Stop All behavior, output loss, and configured interrupting fades retain their cancellation semantics.

The Pre-Audience Audio Test dialog also includes the same live Audio Health panel, so diagnostics remain visible while that dialog is open.


Stop and Fade cues now expose **Next Cue Action** in the Edit table and Advanced Cue Editor, and the Armed Cue summary shows the saved choice. **Arm Next Now** arms the successor immediately; **Arm Next at End** waits for the action to finish and then arms it; **GO on End** arms it immediately and automatically executes it after completion. Stop completes immediately. Fade waits for every playback it targeted to end; new playbacks started later are not part of that fade. A silent target or zero-duration Fade completes immediately. Manual GO/arming/navigation cancels the old automatic continuation; STOP ALL and output interruption still cancel it. Existing files keep their stored choice (normally Arm Next at End), with no format change.


Edit now uses a compact **System Status / Cue Controls / Project & Navigation** dashboard. It hides after successful Rehearsal or Show entry and restores on return. All three cue-list views include a read-only **Duration** column showing the edited Play length (one pass for loops), Fade duration, or Immediate for stops. Source metadata loads asynchronously when needed; cue files and playback behavior are unchanged. See [Edit dashboard and cue duration](EDIT-DASHBOARD.md).
