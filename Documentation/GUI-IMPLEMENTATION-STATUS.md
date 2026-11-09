# GUI-first implementation status

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

## Verification

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
- Audio decoding/validation and device preparation can still block the GUI on slow files/devices. Real-time threading, timing, stale callbacks under stress, and full source-format behavior need subsequent work.
- The existing waveform/progress display was retained; portable waveform-cache completeness has not been verified.
- No realistic technical rehearsal, board audibility test, intended-mixer test, or student usability session has been performed. This prototype is not labeled performance verified.

## Launch

- `Launch GUI Preview.cmd`: silent sample GUI for review.
- `Launch Player.cmd`: normal production workflow.
- Installed environment: `python -m bhs_player.app --gui-preview` or `python -m bhs_player.app`.

Install dependencies first with `pip install -e ".[dev]"` if needed. Launchers run from the repository so relative production folders resolve consistently.
