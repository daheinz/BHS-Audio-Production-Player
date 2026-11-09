"""Exercise the saved practice sequence offline. Never opens an audio device."""
from pathlib import Path
import sys
import json
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bhs_player.cues.engine import CueEngine
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.storage.store import PlayFolder
from bhs_player.sample_production import NAME
from bhs_player.validate.check import validate_show


def verify(folder):
    cs=folder.load_latest()
    if cs is None:
        raise ValueError('Create the Audio Prototype production first.')
    report=validate_show(cs,folder.folder,output_device_available=True)
    if report.critical:
        raise AssertionError('; '.join(i.message for i in report.critical))
    audio=AudioEngine(Mixer(),ready=True,base_path=folder.folder)
    audio.mixer.set_master_level(cs.profile.buses[0].level)
    # All sample sources are decoded/resampled using the real engine before GO checks.
    decoded={}
    for cue in cs.cues:
        if cue.is_play_sound():
            pcm,rate=audio.decode_cue(cue)
            if pcm.size == 0 or not np.isfinite(pcm).all():
                raise AssertionError(f'Invalid decoded data for {cue.identifier}')
            decoded[cue.identifier]=dict(frames=len(pcm),sample_rate=rate,channels=pcm.shape[1])
    engine=CueEngine(cs,audio)
    peak=0.0
    def render(seconds):
        nonlocal peak
        frames=int(seconds*audio.mixer.sample_rate)
        while frames>0:
            count=min(1024,frames)
            out=audio.mixer.render_block(count)
            peak=max(peak,float(np.max(np.abs(out))))
            frames-=count
    def go(identifier):
        if engine.armed_cue is None or engine.armed_cue.identifier != identifier:
            raise AssertionError(f'{identifier} is not armed')
        result=engine.go()
        if not result.ok:
            raise AssertionError(result.reason)
    def active(identifier):
        cue=cs.by_identifier(identifier)
        return audio.instances_of(cue.internal_id)
    try:
        go('1.0')
        assert engine.armed_cue is None
        render(8)
        assert engine.armed_cue.identifier == '2.0'
        assert not audio.active_instances()
        go('2.0')
        render(10)  # Verify a real loop wrap.
        assert active('2.0')
        go('2.1')
        render(2)
        assert active('2.0') and not active('2.1')
        go('3.0')
        render(2)
        assert active('2.0') and active('3.0')
        go('4.0')
        assert engine.armed_cue is None
        render(4)
        assert not active('3.0') and active('2.0')
        assert engine.armed_cue.identifier == '5.0'
        go('5.0')
        assert not audio.active_instances()
        go('6.0')
        render(13)
        assert not audio.active_instances()
        go('7.0')
        assert engine.armed_cue is None
        assert not audio.active_instances()
        assert 0 < peak < 1, f'Unexpected silent or clipped sample mix: {peak}'
        # Emergency STOP ALL preserves an independent armed cue without replay.
        engine.arm_cue(cs.by_identifier('2.0').internal_id)
        go('2.0')
        armed=engine.armed_cue
        engine.stop_all()
        assert engine.armed_cue is armed and not audio.active_instances()
        return dict(cues=len(cs.cues),audio_files=len(decoded),peak=round(peak,4),decoded=decoded,
                    warnings=[i.message for i in report.warnings],hardware_tested=False)
    finally:
        engine.interrupt_output(disarm=True)


if __name__ == '__main__':
    folder=PlayFolder(Path(__file__).resolve().parents[1]/'Plays',NAME)
    print(json.dumps(verify(folder),indent=2))
