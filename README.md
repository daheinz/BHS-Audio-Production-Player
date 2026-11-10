# BHS Audio Production Player

A Windows theatrical sound cue player that behaves like a sound equivalent of a theatrical lighting console.

Current requirements: [DOC-002 Detailed Requirements v0.2](https://docs.google.com/document/d/1jKmJ7jITTiOwQJUxdYhEs1Uw3dVdIp8jP3T4pAz1Lwk/edit), with the approved November 3 decisions. Historical prompts and the earlier feature snapshot are in `Obsolete/`.

This is a GUI-first prototype. See [FEATURES.md](FEATURES.md) and [GUI implementation status](Documentation/GUI-IMPLEMENTATION-STATUS.md) for wired behavior and remaining audio work.

## Try the GUI

Double-click **Launch GUI Preview.cmd** for an isolated sample production. You can edit cues, inspect routing and the advanced editor, review linked cues, and open Show/Rehearse layouts. The preview produces no audio and saves no production files.

Double-click **Launch Player.cmd** for normal production creation/opening. Select a profile, inspect the audio tester, then prepare cues. Show entry validates and blocks unsupported audio routes; the preview lets you review those screens without hardware.

From an installed development environment:

```powershell
python -m bhs_player.app --gui-preview
python -m bhs_player.app
```

## Saved prototype with real audio

Run **Launch Audio Prototype.cmd** to open the saved eight-cue practice production built from local Music files. On first launch, choose a stereo primary output in Profile and Routing, then run the audio test and enter Rehearse. Unlike GUI Preview, edits and saves persist.

See [Real-audio prototype walkthrough](Documentation/AUDIO-PROTOTYPE.md) for the cue sequence, asset locations, and verification results. `python tools/build_audio_prototype.py` creates it when the named local sources are available; rerunning keeps existing edits intact.

## Stack

- Python 3.11+
- PySide6 (Qt Widgets) — UI
- sounddevice (PortAudio) — output, mixing, metering
- soundfile (libsndfile) — decoding; AAC/M4A fallback needs optional PyAV
- pytest — test suite

## Layout

```
src/bhs_player/
    cues/       # cue model, identifiers, state machine, execution
    audio/      # existing stereo engine, guarded routing adapter, metering
    storage/    # play folders, versioned cue sets, recovery autosave
    validate/   # load-time sanity check / Validate Show
    ui/         # PySide6: Show Mode, Edit Mode, Playing Stack
tests/          # unit + integration tests (Section 21 acceptance scenarios)
plays/          # play folders (one per production)
```

## Develop

```
pip install -e .[dev]
pytest
```

The cue table uses field-specific hover help on column headers and cells.
Cue IDs are exact text: `12.1` and `12.10` are distinct. Their original spelling is retained for display and storage.
Resized column widths are saved in
`BHS Audio Production Player/settings.ini` in the Windows user configuration
directory. These preferences are separate from saved production versions.
Choosing an audio file fills End Position with its full duration in seconds;
you can reduce it to trim playback. Existing saved trims are preserved.


## GUI verification

```powershell
python -m pytest -p no:cacheprovider
python tools/render_gui.py
```

The renderer writes silent sample screenshots under `output/gui-review/`. It uses offscreen Qt rendering and Windows Segoe UI fonts; it does not test real audio hardware.

## Viewing mode

The application defaults to **Dark** for theatre use. Choose **Dark** or **Light** from the Viewing mode selector on the production picker, Edit screen, or Show/Rehearse screen. Changes apply immediately to all screens and are remembered in application settings, separately from production files. File pickers use the application theme as well.


## Cue editing shortcuts and clip envelopes

- Drag the small grip at the far left of an Edit row to reorder cues. The insertion line shows the destination. Amber outlines on Cue IDs identify both sides of a numeric reversal; order is advisory and never automatically changed.
- Double-click a cell or use F2 to edit. Right-click an assigned Audio File cell and choose **Play / TEST Audio** to audition that row; use **Stop TEST** to stop it.
- Select a PLAY cue for its waveform panel. Drag **Start**, **End**, **IN**, and **OUT** handles; use the splitter above the panel to resize the work area. The five former timing columns are hidden; exact values remain in **Advanced Cue Editor**.
- A FADE action displays its own **Duration** envelope for the target sound. It does not trim a source file.
- Main-panel graph edits apply at mouse release and are recovery-saved. Advanced Editor edits require OK. Escape cancels a graph drag. Original audio files remain unchanged.
- Finite clips fade out at their playable end; looping clips do not fade on every repeat. Sample waveforms in GUI Preview are labeled **SAMPLE WAVEFORM / NO AUDIO**.


## Show and Rehearse layout

The full-height cue list occupies the left two-thirds of the main area. Separate Armed Cue and bottom-aligned Playing Stack containers occupy the right third. Yellow identifies armed cues; orange identifies active playback; a blue outline identifies selection independently. Resize the divider and scroll the table for additional fields.

Compact GO / STOP ALL controls and readiness status sit along the bottom, with the existing locked stereo output meters at the bottom right. Playback cards use timing progress bars, bus identity, and instance-specific STOP/FADE icons; they have no audio meters. See the [Show/Rehearse guide](Documentation/SHOW-MODE.md) and [Playing Stack guide](Documentation/PLAYING-STACK.md).

Space executes GO, Ctrl+Shift+S stops all, Up/Down select table rows, and Enter arms the selected row. Click a playback card and press Ctrl+F to fade that instance. Text-entry fields and modal dialogs are protected; held Space does not repeatedly trigger cues. There is no bottom ARM CUE button.

Show and Rehearse reuse the prepared output stream between modes. Returning to Edit stops every sound and disarms; a silent stream remains open until configuration changes or application exit.

## Arming and completion choices

Show and Rehearse have an **ARM** button at the far left of every cue row. Clicking it silently arms that cue; only one cue is armed at a time. Clicking another replaces it. Clicking the armed row again keeps it armed and cancels any queued automatic GO. The yellow Armed Cue card at the upper right identifies what GO will execute; the separate Playing Stack is below it. Enter also arms the selected table row.

- **Arm Next at End**: natural completion arms the next cue and waits for GO. Existing saved On Complete cues retain this behavior.
- **GO on End**: arms the next cue immediately, then automatically executes that armed cue at natural completion. Each PLAY cue must opt in separately to continue a chain.
- **Arm Next Now**: advances when triggered, allowing overlapping sounds.

STOP ALL, interrupting fades, navigation, manual arming, output interruption, and mode exit cancel automatic continuation. The Playing card Stop instead runs its normal Next Cue Action. Loops require Arm Next Now. STOP and FADE use their selected Next Cue Action; the STOP ALL action retains its existing advancement behavior. Automatic GO runs on a subsequent UI update, pauses while a modal dialog is open, and is not sample-accurate audio sequencing.


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


## Preparation performance and recent plays

Validated metadata and decoded playback data now persist locally across launches. Import checks retain playback-ready data; unchanged and identical audio can reuse it after RAM eviction or reopening the app. The next cue preloads ahead, RAM entries use LRU access, and UI refresh avoids repeated file-identity reads. GO still waits for uncached preparation and all decoder safeguards remain enabled.

Edit now includes **Recheck Audio** for an explicit full rescan. Open Play sorts by last successful open, independently of saving; canceled/failed opens do not affect order. The bounded 512 MiB disk cache is under LocalAppData/BHS Audio Production Player/audio-cache, outside the synced project folder. See [Performance and recent-play guide](Documentation/PLAYBACK-PERFORMANCE.md).

Audio import now shows advisory source-peak/headroom and cue/bus level warnings without playing the file. Edit displays Audio Health beside TEST, with live measurements and Diagnostics / Logs access.


Stop and Fade cues now expose **Next Cue Action** in the Edit table and Advanced Cue Editor, and the Armed Cue summary shows the saved choice. **Arm Next Now** arms the successor immediately; **Arm Next at End** waits for the action to finish and then arms it; **GO on End** arms it immediately and automatically executes it after completion. Stop completes immediately. Fade waits for every playback it targeted to end; new playbacks started later are not part of that fade. A silent target or zero-duration Fade completes immediately. Manual GO/arming/navigation cancels the old automatic continuation; STOP ALL and output interruption still cancel it. Existing files keep their stored choice (normally Arm Next at End), with no format change.
