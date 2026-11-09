import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QPushButton
from bhs_player.cues.model import Cue, CueSet, ActionType, OnGoBehavior
from bhs_player.audio.engine import AudioEngine, Mixer
from bhs_player.cues.engine import CueEngine
from bhs_player.storage.store import PlayFolder
from bhs_player.ui.cue_table import CueTable, FIELDS
from bhs_player.ui.edit_window import EditWindow


def test_context_menu_only_for_assigned_audio_in_edit(qapp):
    cs = CueSet("Test", [Cue("1.0", audio_file="sound.wav"), Cue("2.0"), Cue("3.0", action=ActionType.STOP_ALL)])
    table = CueTable(cs, editable=True)
    assert table.audio_menu_for(0, FIELDS.index('audio_file')) is not None
    assert table.audio_menu_for(0, FIELDS.index('name')) is None
    assert table.audio_menu_for(1, FIELDS.index('audio_file')) is None
    assert table.audio_menu_for(2, FIELDS.index('audio_file')) is None
    assert CueTable(cs).audio_menu_for(0, FIELDS.index('audio_file')) is None


def test_right_click_auditions_clicked_row_without_show_side_effects(qapp, tmp_path):
    folder = PlayFolder(tmp_path, 'Test')
    folder.ensure()
    sf.write(str(folder.audio_dir / 'sound.wav'), np.ones((4410, 2), dtype=np.float32)*.1, 44100)
    first, clicked = Cue('1.0'), Cue('2.0', audio_file='audio/sound.wav', on_go_behavior=OnGoBehavior.STOP_ALL)
    cs = CueSet('Test', [first, clicked])
    audio = AudioEngine(Mixer())
    engine = CueEngine(cs, audio)
    win = EditWindow(cs, audio, folder, routing=SimpleNamespace(prepare=lambda route: True, unsupported=lambda: ""))
    win.list.setCurrentRow(0)
    existing = audio.start(first, pcm=np.ones((4410, 2), dtype=np.float32)*.1)
    pointer = engine.pointer
    menu = win.list.audio_menu_for(1, FIELDS.index('audio_file'))
    menu.actions()[0].trigger()
    assert win._test_cue_id == clicked.internal_id
    assert win._test_instance.is_test
    assert existing in audio.active_instances()
    assert engine.pointer == pointer
    assert win.list.currentRow() == 0
    assert not any(b.text() == 'Edit Selected Cell' for b in win.findChildren(QPushButton))
    win._stop_audition()
    assert existing in audio.active_instances()


def test_context_audition_does_not_bypass_unavailable_output(qapp):
    cue=Cue('1.0',audio_file='missing.wav')
    cs=CueSet('Test',[cue])
    audio=AudioEngine(Mixer(),ready=False)
    win=EditWindow(cs,audio,routing=SimpleNamespace(prepare=lambda route: False,unsupported=lambda: 'Unavailable',message='Choose an output'))
    menu=win.list.audio_menu_for(0,FIELDS.index('audio_file'))
    menu.actions()[0].trigger()
    assert win._test_instance is None
    assert audio.active_instances() == []
    assert 'Choose an output' in win.status_lbl.text()
