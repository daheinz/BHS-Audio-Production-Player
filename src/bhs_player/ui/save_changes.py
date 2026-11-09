"""Shared saved baseline and meaningful change tracking for a production."""
from dataclasses import asdict



def editable_snapshot(cue_set):
    data = asdict(cue_set)
    for cue in data['cues']:
        cue.pop('execution_state', None)
    return data


class SaveState:
    def __init__(self, cue_set):
        self.cue_set = cue_set
        self.saved = editable_snapshot(cue_set)
        self.force_unsaved = False

    @property
    def has_changes(self):
        return self.force_unsaved or editable_snapshot(self.cue_set) != self.saved

    def mark_saved(self):
        self.saved = editable_snapshot(self.cue_set)
        self.force_unsaved = False

