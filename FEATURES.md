# BHS Audio Production Player - Current Feature Snapshot

Updated November 8, 2026. Suitable for pasting into another ChatGPT conversation.

Windows/Python/PySide6 theatrical sound cue player. This update focuses on a working GUI and supporting production state; it does not establish live-performance readiness.

## Implemented GUI and state

- Configurable Dark/Light viewing mode, defaulting to Dark. Applies across editors, Show/Rehearse, tables, dialogs, and file pickers; saved as an application preference independently of productions.

- Production creation with a definitive production-owned audio profile, followed by the profile tester; production/version library and recovery restoration remain available.
- Profile editor for one to six mono/stereo buses, required Main, stable references, names, percentage levels, primary device/channel maps, board-input labels, and optional combined backup mapping/relative levels. No profile switching or remapping workflow.
- Spreadsheet cue editing with inline controls, field help, column-width preferences, audio import, trims, add/remove/reorder, and bus selection beside the action.
- Advanced Cue Editor shares the same cue data, supports multiple buses, and applies changes only after validation.
- Cue IDs are exact text: 12.1 and 12.10 coexist and survive saving/loading. Performance order stays explicit.
- Referenced-cue deletion is blocked. Review Linked Cues can retarget or explicitly delete linked STOP/FADE cues before removing their original target.
- Shared Show/Rehearse view with REHEARSAL indication, armed cue/action/buses/notes, Playing Stack, progress/waveform, per-instance STOP/FADE, GO, ARM CUE, Back, STOP ALL, bus-level displays/meters, output state, and deliberate route controls.
- No global master control in the GUI. Software levels and routing are configured in Edit and locked in Show/Rehearse.
- Leaving Show/Rehearse stops output and disarms; re-entry needs ARM CUE and GO. Entering stops TEST. Selection remains silent and Spacebar suppresses repeats/modal triggering.
- Pre-Audience Audio Test supports manual path selection, Play Again with audible-output confirmation, human Confirmed Audible, Skip / Not Working, Stop Test, and session/configuration confirmation tracking.
- Show entry offers Run Test / Enter Without Testing / Cancel for unconfirmed audibility; invalid/unavailable routes cannot be overridden. Warnings remain visible.
- Quiet validation before Show/Rehearse, plus optional Show Readiness with correction paths.
- Meaningful changes create a new history version on Edit Save, Show entry, and application exit. No-change events create none; Rehearse uses separate recovery autosave. Required-save failure blocks the transition.
- Silent `--gui-preview` with isolated sample data lets operators inspect GUI workflows without audio hardware or production saves.

## Connected audio in this pass

The existing stereo engine supports overlap, cue gain/fades, loops, trims, and monitoring. A narrow adapter connects a single stereo Main bus on hardware outputs 1/2, including its bus level, real output meter, TEST audition, and a low-level left-then-right path test. An optional stereo backup on outputs 1/2 of its selected endpoint uses the same cue data and prepared combination gain.

Deliberate route switches drop sounds and preserve independently armed cues; interrupted waits leave nothing armed. Output-loss handling disables GO and cancels pending advancement. There is no automatic switchback or replay.

## Pending integration / verification

- Multiple buses, mono routes, custom output-channel maps, and general combined backup feeds are configurable but not connected to playback. Those controls report unsupported status; playback/test confirmations are blocked rather than simulated.
- Individual bus meters on combined backup remain unavailable. Intended ASIO/USB mixer compatibility is unverified.
- Large-file bounded streaming and decoder packaging remain future backend work; AAC/M4A currently needs optional PyAV.
- Automated tests and offscreen screen review are not hardware audibility, latency, reliability, or student usability verification.

## Legacy loading

Older cue sets still load. Their former master value is preserved as the Main bus output level; the original field is retained for compatibility. A visible migration note requires reviewing routing and deliberately selecting the primary device. Historical versions are not rewritten.

Approved requirements: DOC-001 v1.1, DOC-002 v0.2, DEC-001 v1.0, ARCH-001 v1.0, TEST-001 v1.0. See `Documentation/GUI-IMPLEMENTATION-STATUS.md` for source links and verification details.
