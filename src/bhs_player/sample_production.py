"""Build a real, saved practice production from user-owned local audio copies."""
from pathlib import Path
from types import SimpleNamespace
from .audio.safe_decode import inspect_audio
from .cues.model import Cue, CueSet, ActionType, AdvanceMode
from .storage.store import PlayFolder
from .validate.check import validate_show

NAME = "Audio Prototype"
SOURCES = {
    'fanfare': '524848__mc5__short-brass-fanfare-2.wav',
    'ambience': '558259__samsterbirdies__steam-engine.flac',
    'bell': 'boxing_bell.wav',
    'music': '03 - (I Love You) For Sentimental Reasons - Nat King Cole.mp3',
    'arrival': '204416__nhumphrey__steam-train-coming-into-the-station.wav',
}


def locate_sources(music_folder):
    folder = Path(music_folder)
    result = {}
    for role, name in SOURCES.items():
        preferred = folder / 'Other' / name
        path = preferred if preferred.is_file() else next(folder.rglob(name), None)
        if path is None:
            raise FileNotFoundError(f"Missing sample audio: {name} in {folder}")
        metadata = inspect_audio(path, full=True)
        info = SimpleNamespace(**metadata, samplerate=metadata["sample_rate"])
        if info.duration <= 0 or info.channels not in (1, 2):
            raise ValueError(f"Sample needs readable mono/stereo audio: {name}")
        result[role] = (path, info)
    return result


def build_audio_prototype(music_folder, plays_root, name=NAME):
    """Never rebuild an existing production or replace the user's subsequent edits."""
    folder = PlayFolder(plays_root, name)
    if folder.folder.exists():
        if folder.latest_version() is None:
            raise FileExistsError(f"{folder.folder} already exists without a saved version. Choose a new production name.")
        return folder, False
    sources = locate_sources(music_folder)  # Verify every source before making a production.
    assets = {role: str(folder.import_audio(path)).replace('\\','/') for role,(path,_) in sources.items()}
    duration = {role: info.duration for role,(_,info) in sources.items()}
    cs = CueSet(name)
    cs.profile.name = 'Stereo practice — one Main bus'
    cs.profile.buses[0].level = .5
    cs.profile.buses[0].board_input = 'Selected speakers / headphones, left and right'
    fanfare = Cue('1.0','Opening fanfare',audio_file=assets['fanfare'],volume=.35,
                  end_position=duration['fanfare'],fade_in=.05,fade_out=.5,
                  notes='ARM, then GO. Wait for the fanfare to finish; the next cue only arms.')
    ambience = Cue('2.0','Steam engine ambience — LOOP',audio_file=assets['ambience'],volume=.22,
                   end_position=duration['ambience'],fade_in=.7,fade_out=2,
                   loop=True,advance_mode=AdvanceMode.ON_GO,
                   notes='GO starts a repeating engine bed and immediately arms the bell. It keeps playing until cue 5.0 or STOP ALL.')
    bell = Cue('2.1','Station bell — over the engine',audio_file=assets['bell'],volume=.35,
               end_position=duration['bell'],
               notes='GO adds this mono bell over the looping engine. Wait for the bell to finish before music.')
    music_start = min(12.0, duration['music']*.1)
    music_end = min(music_start+24.0, duration['music'])
    music = Cue('3.0','Music underneath — 24-second excerpt',audio_file=assets['music'],volume=.28,
                start_position=music_start,end_position=music_end,fade_in=1,fade_out=2,
                advance_mode=AdvanceMode.ON_GO,
                notes='GO adds music over the engine. Let it run a few seconds, then GO on cue 4.0 to fade it. Natural end also fades out.')
    fade = Cue('4.0','Fade music — 3 seconds',action=ActionType.FADE,
               target_internal_id=music.internal_id,fade_duration=3,
               notes='GO fades all active instances of cue 3.0. The engine bed continues. Wait until cue 5.0 arms.')
    stop = Cue('5.0','Stop the engine ambience',action=ActionType.STOP,
               target_internal_id=ambience.internal_id,
               notes='GO stops the engine only. This action arms the arriving-train cue without playing it.')
    arrival = Cue('6.0','Train arriving — trimmed effect',audio_file=assets['arrival'],volume=.3,
                  end_position=min(12.0,duration['arrival']),fade_in=.1,fade_out=1.5,
                  notes='GO plays the 48 kHz stereo train recording. The last 1.5 seconds fade to silence.')
    all_stop = Cue('7.0','STOP ALL — end of practice',action=ActionType.STOP_ALL,
                   notes='GO stops any remaining sound. Also try the permanent red STOP ALL button during a loop.')
    cs.cues = [fanfare,ambience,bell,music,fade,stop,arrival,all_stop]
    report = validate_show(cs,folder.folder,output_device_available=True)
    if report.critical:
        raise ValueError('Sample data validation failed: '+ '; '.join(i.message for i in report.critical))
    folder.save_version(cs)
    lines = [f'# {name} — real-audio practice production', '',
             'This is a saved production, not the silent GUI preview. Edits, recovery, and history are real.',
             'The original Music files were copied; they are not modified.', '',
             '## Start', '',
             'Run Launch Audio Prototype.cmd from the repository. On first launch, choose your actual output in Profile and Routing.',
             'One stereo Main bus is configured on outputs 1/2 at 50%. No device is selected by the builder; selection is deliberate.',
             'Run Pre-Audience Audio Test and confirm only after you hear the left/right signal. Then enter REHEARSE.',
             'Select cue 1.0, ARM CUE, then GO. Selection and mode changes never play audio.', '',
             '## Practice cues', '', '| Cue | Name | What to do |', '| --- | --- | --- |']
    lines += [f'| {c.identifier} | {c.name} | {c.notes} |' for c in cs.cues]
    lines += ['', '## Other checks', '',
              '- Right-click an assigned Audio File cell for TEST; Stop TEST stops only the audition.',
              '- Drag clip boundaries/fades, save, close, and relaunch to verify persistence.',
              '- Rehearse stops and disarms when you return to Edit. Re-entry needs ARM CUE and GO.',
              '- Try STOP ALL while the engine loops; replay requires deliberate arming.',
              '- The trimmed MP3 can produce a compressed-timing warning. It is a warning, not a claim of sample-accurate looping.',
              '- No backup is configured. Add a distinct usable endpoint in Profile and Routing if you want to test switching.', '',
              '## Imported sources', '', '| Role | Original file | Format | Duration | Channels / sample rate |',
              '| --- | --- | --- | --- | --- |']
    for role,(path,info) in sources.items():
        lines.append(f'| {role} | {path.name} | {info.format} | {info.duration:.3f}s | {info.channels} / {info.samplerate} Hz |')
    lines += ['', 'Static cue/audio validation succeeded when built. Physical output and audibility are not confirmed until you select and test the device.', '']
    (folder.folder / 'PRACTICE-GUIDE.md').write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    return folder, True
