# Edit dashboard and cue duration

Edit uses three compact panels at the bottom of the window:

- **System Status:** actual engine Ready/Idle/Playing/Error state, selected output, shared Audio Health load/dropout/clipping measurements, readiness/import/save messages, and Diagnostics / Logs.
- **Cue Controls:** grouped cue management, adjacent TEST/Stop TEST, validation, audio import, Advanced Editor, and live TEST progress/meters. Existing command callbacks remain in EditWindow.
- **Project & Navigation:** Save Version, REHEARSE, and prominent green ENTER SHOW MODE. The existing readiness progress/countdown and disabled waiting controls are inside this panel.

The duplicate top Logs and Show Readiness controls were removed; Diagnostics / Logs and Validate Show remain in the dashboard. Profile and Routing, Pre-Audience Audio Test, and Recheck Audio remain above the cue list. Disabled controls are visibly unavailable; Move Up/Down respect list boundaries, testing/import require an appropriate selection, and Stop TEST can cancel preparation or active audition.

The dashboard uses three columns at normal desktop widths, reorganizes to two rows in narrower windows, and stacks at very narrow widths. Layout minimum sizes preserve readable controls instead of overlapping them. At narrow widths the window may require more height. The Edit waveform can shrink vertically to preserve visible cue rows; its editing behavior is unchanged. Preview renders include `output/gui-review/edit.png`, `edit-small.png`, and `mode-entry-waiting.png`.

After successful Rehearsal/Show entry, Edit is disabled and hidden. Returning to Edit or closing the performance window restores it. Readiness failures and canceled entry keep Edit visible.

## Duration in Edit, Rehearsal, and Show

A read-only **Duration** column appears immediately after Cue Name in the shared cue list:

| Cue | Display |
| --- | --- |
| Play | Edited End minus Start, to three decimal places in seconds |
| Looping Play | One edited pass, marked `/ loop`; total playback remains open ended |
| Fade | Configured fade duration |
| Stop / Stop All | Immediate |
| No assigned sound | Unassigned |
| Missing metadata | Checking..., then the duration or Unavailable |

Fade-in/out are envelopes inside a Play segment, so they do not add to or subtract from its displayed duration. If End is unspecified, a background task reuses source metadata or performs a bounded metadata probe; it never blocks table creation. Read-only display does not write a duration into cue files. Trim changes update the displayed value through the existing rebuild path. Duration widths are configurable like other columns, with separate Edit/performance preferences.

This update changes layout and derived display only. Audio playback, cue execution, routing, fades, stacking, and cue-set formats retain their behavior.

Verification: the full 386-test suite passes, including eight new dashboard/duration/lifecycle cases. Application source compilation succeeds. Offscreen layouts were reviewed at 1920 x 1080, 1500 x 860, and a narrow window; minimum dimensions prevent controls from overlapping. The final waveform-size/heading refinements also pass the eight focused checks. These are UI/offline checks, not hardware audio verification.
