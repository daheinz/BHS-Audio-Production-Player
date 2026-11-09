# Requested GUI modifications

Recorded November 8, 2026. These are requested changes for a later implementation pass; none is implemented by this list.

## 1. Drag handles for cue ordering

Status: Requested.

- Add a narrow handle at the far left of each cue row.
- Drag the handle to reposition the cue in performance order, with a visible insertion indicator.
- Preserve identifiers, settings, stable target references, and selection of the moved cue.
- Mark a completed reorder as a meaningful change and maintain recovery autosave.
- Enable only in Edit Mode; keep Show/Rehearse locked. Retain Move Up/Down for keyboard and precise positioning.

## 2. Highlight cue IDs that are out of numeric order

Status: Requested; adjacent-reversal rule clarified by the user.

- Compare adjacent cue IDs in performance order. Whenever an ID is numerically greater than the next ID, highlight both Cue ID cells, rather than the entire rows.
- Example: `1.0, 1.2, 1.1, 1.3` highlights only `1.2` and `1.1`.
- Combine highlights when several adjacent reversals overlap; clear them when the order is corrected.
- Use the highlight as an advisory; do not automatically sort, renumber, or prevent deliberate nonnumeric performance order.
- Keep text identity unchanged: `12.1` and `12.10` remain distinct identifiers, even when a numeric comparison treats them as equal.
- Numerically equal IDs do not constitute a descending reversal. Keep numeric-order comparison separate from exact text identity.
- Explain the warning with a tooltip/legend and make it readable in both viewing modes without obscuring selection or execution states.

## 3. Remove the redundant Edit Selected Cell button

Status: Requested; redundancy confirmed in current source.

- The button's handler calls `editItem()` on the current table item. The table already supports double-click, the edit key (F2), and typing to begin editing; audio cells use the same file-picker delegate.
- Remove the button while preserving these interactions, dropdown controls, and field help.
- Keep the Advanced Cue Editor button; it provides additional functionality.

## 4. Right-click audition from an Audio File cell

Status: Requested.

- In Edit Mode, right-click an Audio File cell containing a filename and offer a Play / TEST Audio action for that row.
- Use the existing audition path so the preview uses the cue's trim, level, fades, loop, and bus assignment without destructive On GO behavior.
- Show TEST status/progress and provide Stop. Do not alter the armed cue, execution history, or show position.
- Respect output readiness and unsupported-routing restrictions. Report missing/unreadable audio clearly; do not offer playback for an empty cell or non-PLAY action.

## 5. Graphical audio clip, trim, and fade editor

Status: Requested design direction; needs a focused GUI design/implementation pass.

- Replace the spreadsheet's Start Position, End Position, Fade Duration, Fade-In, and Fade-Out controls with a graphical editing workflow where appropriate.
- Use the waveform screenshot supplied with the November 8 request as the visual reference: separate stereo channel waveforms, a clearly bounded clip, and a gain/fade envelope with visible control points.
- Show the full source waveform, playable start/end boundaries, excluded sections, and where fade-in/fade-out occur. Support direct manipulation of the applicable boundaries and fade handles.
- Keep timing information understandable and provide precise numeric entry in the Advanced Cue Editor or alongside the graphical controls. Hiding spreadsheet columns must not discard their saved values.
- Ensure the waveform/envelope works in the default dark viewing mode; follow the reference's editing concepts without forcing a bright background.
- Distinguish a PLAY cue's source trim and playback fades from a FADE action cue's target-fade duration. A FADE action has no source clip of its own; design an appropriate target/envelope representation rather than treating that duration as a source trim.
- The screenshot does not by itself authorize arbitrary gain automation, multitrack editing, live panning, or a full audio workstation. Start with existing trim/fade settings.
- Preserve the original audio asset; graphical edits should change cue playback settings.

## Suggested implementation sequence

1. Remove the redundant button and add right-click audition.
2. Add drag-handle ordering and numeric-order warnings.
3. Design and implement the graphical clip editor, including a clear treatment of FADE action duration.
