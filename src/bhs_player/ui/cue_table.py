"""Shared spreadsheet cue view for editing and show operation."""
from dataclasses import replace
from pathlib import Path
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHeaderView, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem,
)

from ..cues.model import ActionType, AdvanceMode, OnGoBehavior, validate_identifier
from ..audio.engine import audio_file_duration
from .settings import application_settings
from .theme import colors, viewing_mode

FIELDS = ('identifier', 'name', 'action', 'audio_file', 'notes', 'advance_mode',
          'on_go_behavior', 'volume', 'loop', 'start_position', 'end_position',
          'target_internal_id', 'fade_duration', 'fade_in', 'fade_out', 'bus_ids')
HEADERS = ('Cue ID', 'Cue Name', 'Action', 'Audio File', 'Notes', 'Advance Mode',
           'On Go', 'Volume\nPercent', 'Loop', 'Start\nPosition', 'End\nPosition',
           'Target\nPlay Cue', 'Fade\nDuration', 'Fade-In', 'Fade-Out', 'Output Bus')
OPTIONS = {
    'action': [('Play', ActionType.PLAY), ('Stop', ActionType.STOP),
               ('Fade', ActionType.FADE), ('Stop All', ActionType.STOP_ALL)],
    'advance_mode': [('On Complete', AdvanceMode.ON_COMPLETE), ('On Go / Trigger', AdvanceMode.ON_GO)],
    'on_go_behavior': [('Add to Play Stack', OnGoBehavior.ADD_TO_STACK),
                       ('Stop Prev. and Add', OnGoBehavior.STOP_PREVIOUS),
                       ('Stop All and Add', OnGoBehavior.STOP_ALL)],
}
FIELD_HELP = {
    'bus_ids': 'Choose one output bus here. Use Advanced Cue Editor for multiple buses.',
    'identifier': 'Script-page cue ID, stored as text: page.subcue (e.g. 12.10). IDs are exact text: 12.1 and 12.10 are distinct.',
    'name': 'Human-readable cue name displayed in the cue table and the armed cue display.',
    'action': 'Play starts a sound; Stop stops the target; Fade fades the target to silence; Stop All stops every sound.',
    'audio_file': 'Sound file path. Edit this cell to choose a file. Files are imported into the play folder when available.',
    'notes': 'Operator notes, such as the line or stage movement that triggers this cue.',
    'advance_mode': 'On Complete arms the next cue when this sound finishes. On Go / Trigger arms it immediately for overlap. Loops require On Go / Trigger.',
    'on_go_behavior': 'Add to Play Stack keeps existing sounds playing. Stop Prev. and Add stops the most recent sound. Stop All and Add stops all existing sounds.',
    'volume': 'Playback volume as a percentage before the assigned bus output level. 100% is unity; 50% is half; 200% is double and may clip.',
    'loop': 'Repeat the sound segment until stopped or faded. Loop requires Advance Mode On Go / Trigger.',
    'start_position': 'Position in seconds at which playback begins. 0 means the start of the sound. Must be before End Position.',
    'end_position': 'Position in seconds at which playback ends. Choosing a sound fills in its full length; reduce this value to trim it. 0 means file end.',
    'target_internal_id': 'PLAY cue whose active sound this Stop or Fade affects. Defaults to the nearest preceding Play cue. The link survives renumbering and reordering.',
    'fade_duration': 'Seconds for this Fade cue to bring the target sound to silence. 0 stops it immediately.',
    'fade_in': 'Seconds to ramp from silence to the cue volume when the sound starts. 0 starts at full level.',
    'fade_out': 'Default fade duration in seconds used by this sound’s FADE OUT playback control. 0 stops it immediately.',
}


class AudioFileDelegate(QStyledItemDelegate):
    """Use the same picker for double-click, F2, and Edit Selected Cell."""

    def createEditor(self, parent, option, index):
        self.parent().browse_audio(index.row())
        return None


class CueTable(QTableWidget):
    currentRowChanged = Signal(int)
    cueChanged = Signal()
    editRejected = Signal(str)

    def __init__(self, cue_set, editable=False, play_folder=None, parent=None, settings=None):
        super().__init__(0, len(FIELDS), parent)
        self.cue_set, self.editable, self.play_folder = cue_set, editable, play_folder
        self._rebuilding = False
        self.settings = settings if settings is not None else application_settings()
        if editable:
            self._initialize_defaults()
        self.setItemDelegateForColumn(FIELDS.index('audio_file'), AudioFileDelegate(self))
        self.setHorizontalHeaderLabels(HEADERS)
        for col, field in enumerate(FIELDS):
            self.horizontalHeaderItem(col).setToolTip(FIELD_HELP[field])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSortingEnabled(False)
        self.setEditTriggers((QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                              QAbstractItemView.AnyKeyPressed) if editable else QAbstractItemView.NoEditTriggers)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(42)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate((70, 170, 95, 230, 300, 150, 170, 85, 55, 95, 95, 150, 95, 85, 85)):
            self.setColumnWidth(col, width)
        self.setColumnWidth(FIELDS.index("bus_ids"), 160)
        self.horizontalHeader().moveSection(FIELDS.index("bus_ids"), 3)
        self._restore_widths()
        self.horizontalHeader().sectionResized.connect(self._save_width)
        self._active_ids, self._next_id = set(), None
        viewing_mode().changed.connect(self._apply_theme)
        self._apply_theme()
        self.currentCellChanged.connect(lambda row, col, oldrow, oldcol: self.currentRowChanged.emit(row))
        self.itemChanged.connect(self._item_changed)
        self.rebuild()

    def count(self):
        return self.rowCount()

    def item(self, row, column=0):
        return super().item(row, column)

    def setCurrentRow(self, row):
        self.setCurrentCell(row, 0)

    def _restore_widths(self):
        header = self.horizontalHeader()
        blocked = header.blockSignals(True)
        for col, field in enumerate(FIELDS):
            try:
                width = int(self.settings.value(f'cue_table/widths/{field}', self.columnWidth(col)))
            except (TypeError, ValueError):
                continue
            if 32 <= width <= 4000:
                self.setColumnWidth(col, width)
        header.blockSignals(blocked)

    def _save_width(self, col, old_width, width):
        self.settings.setValue(f'cue_table/widths/{FIELDS[col]}', width)
        self.settings.sync()

    def _sound_duration(self, audio_file):
        path = Path(audio_file)
        if self.play_folder is not None and not path.is_absolute():
            path = self.play_folder.folder / path
        duration = audio_file_duration(str(path))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Sound has no positive duration.')
        return duration

    def applicable(self, cue, field):
        if field in ('identifier', 'name', 'action', 'notes'):
            return True
        if field == 'target_internal_id':
            return cue.action in (ActionType.STOP, ActionType.FADE)
        if field == 'fade_duration':
            return cue.action is ActionType.FADE
        return cue.action is ActionType.PLAY

    def options(self, cue, field):
        if field == 'bus_ids':
            return [(b.name, [b.id]) for b in self.cue_set.profile.buses] + ([(self.cue_set.profile.bus_names(cue.bus_ids) + ' (multiple)', cue.bus_ids)] if len(cue.bus_ids) > 1 else [])
        if field == 'target_internal_id':
            choices = [('(none)', None)] + [(f'{c.identifier}  {c.name}', c.internal_id)
                                          for c in self.cue_set.cues if c.is_play_sound() and c is not cue]
            if cue.target_internal_id and not any(data == cue.target_internal_id for _, data in choices):
                choices.append(('(missing target)', cue.target_internal_id))
            return choices
        return OPTIONS[field]

    def _default_target(self, cue):
        row = self.cue_set.cues.index(cue)
        preceding = [c for c in self.cue_set.cues[:row] if c.is_play_sound()]
        if preceding:
            return preceding[-1].internal_id
        return next((c.internal_id for c in self.cue_set.cues if c.is_play_sound() and c is not cue), None)

    def _initialize_defaults(self):
        for cue in self.cue_set.cues:
            for field, choices in OPTIONS.items():
                if getattr(cue, field) not in [data for _, data in choices]:
                    default = AdvanceMode.ON_GO if field == 'advance_mode' and cue.loop else choices[0][1]
                    setattr(cue, field, default)
        for cue in self.cue_set.cues:
            if cue.action in (ActionType.STOP, ActionType.FADE) and cue.target_internal_id is None:
                cue.target_internal_id = self._default_target(cue)
            if cue.is_play_sound() and cue.audio_file and cue.end_position is None:
                try:
                    duration = self._sound_duration(cue.audio_file)
                    if (cue.start_position or 0) < duration:
                        cue.end_position = duration
                except Exception:
                    # Missing or unreadable saved references remain visible;
                    # Validate Show reports them without blocking the editor.
                    pass

    def browse_audio(self, row):
        if not self.editable or not 0 <= row < len(self.cue_set.cues):
            return False
        cue = self.cue_set.cues[row]
        if not cue.is_play_sound():
            return False
        initial = cue.audio_file or ''
        if self.play_folder:
            initial = str(self.play_folder.folder / initial)
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose Audio File', initial,
            'Audio Files (*.wav *.mp3 *.flac *.aac *.m4a *.ogg);;All Files (*)')
        return self.commit(row, 'audio_file', path) if path else False

    def rebuild(self):
        self._restore_widths()
        selected = self.currentRow()
        selected_column = max(0, self.currentColumn())
        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        self._rebuilding = True
        self.blockSignals(True)
        # Old cell widgets are deleted later by Qt. Silence their teardown
        # signals before replacing them so they cannot commit empty values.
        for row in range(self.rowCount()):
            for col in range(self.columnCount()):
                widget = self.cellWidget(row, col)
                if widget is not None:
                    widget.blockSignals(True)
        self.clearContents()
        self.setRowCount(len(self.cue_set.cues))
        for row, cue in enumerate(self.cue_set.cues):
            for col, field in enumerate(FIELDS):
                value = getattr(cue, field)
                enabled = self.applicable(cue, field)
                choices = self.options(cue, field) if field in OPTIONS or field in ('target_internal_id', 'bus_ids') else None
                text = str(value or '')
                if choices:
                    text = next((label for label, data in choices if data == value), '(missing)')
                elif field == 'volume':
                    text = f'{value * 100:g}%'
                elif field in ('start_position', 'end_position', 'fade_duration', 'fade_in', 'fade_out'):
                    text = f'{value or 0:.2f}'
                item = QTableWidgetItem(text if enabled else '')
                label = HEADERS[col].replace('\n', ' ')
                display = ('On' if value else 'Off') if field == 'loop' else text
                context = f'{label}: {display}' if enabled else f'{label}: not used for {cue.action.value} cues'
                item.setToolTip(f'{context}\n{FIELD_HELP[field]}')
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if self.editable and enabled and not choices and field != 'loop':
                    flags |= Qt.ItemIsEditable
                if field == 'loop' and enabled:
                    flags |= Qt.ItemIsUserCheckable if self.editable else Qt.NoItemFlags
                    item.setText('')
                    item.setCheckState(Qt.Checked if value else Qt.Unchecked)
                item.setFlags(flags)
                if not enabled:
                    item.setBackground(QColor(colors()['inactive']))
                self.setItem(row, col, item)
                if choices and self.editable:
                    combo = QComboBox()
                    for label, data in choices:
                        combo.addItem(label, data)
                    combo.setCurrentIndex(max(0, combo.findData(value)))
                    combo.setEnabled(enabled)
                    if not enabled:
                        combo.setCurrentIndex(-1)
                    combo.setToolTip(item.toolTip())
                    self._style_combo(combo, cue, field)
                    combo.currentIndexChanged.connect(lambda _, r=row, f=field, w=combo: self.commit(r, f, w.currentData()))
                    self.setCellWidget(row, col, combo)
        if 0 <= selected < self.rowCount():
            self.setCurrentCell(selected, selected_column)
        self.horizontalScrollBar().setValue(scroll_x)
        self.verticalScrollBar().setValue(scroll_y)
        self.blockSignals(False)
        self._rebuilding = False
        self.highlight(self._active_ids, self._next_id)

    def _item_changed(self, item):
        if not self.editable:
            return
        field = FIELDS[item.column()]
        value = item.checkState() == Qt.Checked if field == 'loop' else item.text()
        self.commit(item.row(), field, value)

    def commit(self, row, field, value):
        if self._rebuilding or not self.editable:
            return False
        cue = self.cue_set.cues[row]
        duration_warning = None
        try:
            if field == 'bus_ids':
                if not value or not set(value) <= {b.id for b in self.cue_set.profile.buses}:
                    raise ValueError('Choose a defined output bus.')
            elif field == 'identifier':
                value = value.strip()
                if not validate_identifier(value):
                    raise ValueError('Cue ID must use page.subcue, such as 12.10.')
                existing = self.cue_set.by_identifier(value, exclude=cue)
                if existing is not None:
                    raise ValueError(f"Cue ID '{value}' is already in use as '{existing.identifier}'.")
            elif field in ('volume', 'start_position', 'end_position', 'fade_duration', 'fade_in', 'fade_out'):
                value = float(str(value).strip().rstrip('%') or 0)
                if not math.isfinite(value) or value < 0 or (field == 'volume' and value > 400):
                    raise ValueError('Enter a nonnegative number (volume: 0–400%).')
                if field == 'volume':
                    value /= 100
                elif field in ('start_position', 'end_position'):
                    value = value or None
            elif field == 'audio_file':
                value = value.strip() or None
                if value and Path(value).is_absolute():
                    if self.play_folder is not None:
                        value = str(self.play_folder.import_audio(Path(value))).replace('\\', '/')
                    else:
                        value = str(Path(value)).replace('\\', '/')
            candidate = replace(cue, **{field: value})
            if field == 'audio_file':
                candidate.end_position = None
                if value:
                    try:
                        candidate.end_position = self._sound_duration(value)
                        if (candidate.start_position or 0) >= candidate.end_position:
                            candidate.start_position = None
                    except Exception as exc:
                        duration_warning = f'Audio file selected, but its length could not be read: {exc}'
            if field == 'action' and candidate.action in (ActionType.STOP, ActionType.FADE) and candidate.target_internal_id is None:
                candidate.target_internal_id = self._default_target(cue)
            if candidate.is_play_sound():
                if not candidate.loop_config_valid():
                    raise ValueError('Loop requires On Go / Trigger. Change Advance Mode first.')
                if candidate.end_position is not None and (candidate.start_position or 0) >= candidate.end_position:
                    raise ValueError('Start Position must be before End Position (0 end = file end).')
            setattr(cue, field, value)
            if field == 'action':
                cue.target_internal_id = candidate.target_internal_id
            if field == 'audio_file':
                cue.start_position = candidate.start_position
                cue.end_position = candidate.end_position
        except (ValueError, OSError) as exc:
            self.editRejected.emit(str(exc))
            self.rebuild()
            return False
        self.rebuild()
        self.cueChanged.emit()
        if duration_warning:
            self.editRejected.emit(duration_warning)
        return True

    def _style_combo(self, combo, cue, field):
        c = colors()
        color = c['button']
        if field == 'advance_mode':
            color = c['on_complete'] if cue.advance_mode is AdvanceMode.ON_COMPLETE else c['on_go']
        elif field == 'on_go_behavior':
            color = c[{OnGoBehavior.ADD_TO_STACK: 'add', OnGoBehavior.STOP_PREVIOUS: 'stop_previous', OnGoBehavior.STOP_ALL: 'stop_all'}[cue.on_go_behavior]]
        if not self.applicable(cue, field):
            color = c['inactive']
        combo.setStyleSheet(f"QComboBox {{ background: {color}; color: {c['text']}; border-radius: 5px; padding: 4px; }}")

    def _apply_theme(self, *_):
        c = colors()
        self.setStyleSheet(f"QTableWidget {{ background: {c['base']}; color: {c['text']}; gridline-color: {c['border']}; }}"
                          f"QTableWidget::item:selected {{ border: 2px solid #6489b7; background: {c['selection']}; color: {c['text']}; }}")
        for row, cue in enumerate(self.cue_set.cues):
            for col, field in enumerate(FIELDS):
                widget = self.cellWidget(row, col)
                if widget:
                    self._style_combo(widget, cue, field)
        self.highlight(self._active_ids, self._next_id)

    def highlight(self, active_ids, next_id=None):
        self._active_ids, self._next_id = set(active_ids), next_id
        c = colors()
        blocked = self.blockSignals(True)
        for row, cue in enumerate(self.cue_set.cues):
            active, armed = cue.internal_id in active_ids, cue.internal_id == next_id
            key = 'playing' if active else 'armed' if armed else 'completed' if cue.execution_state.value in ('complete', 'interrupted') else 'idle'
            for col, field in enumerate(FIELDS):
                item = self.item(row, col)
                if item is not None:
                    item.setBackground(QColor(c[key] if self.applicable(cue, field) else c['inactive']))
                    item.setForeground(QColor(c['text'] if self.applicable(cue, field) else c['muted']))
        self.blockSignals(blocked)
