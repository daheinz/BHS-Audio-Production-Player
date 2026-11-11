"""Shared spreadsheet cue view for editing and show operation."""
from dataclasses import replace
from pathlib import Path
import math
import uuid
from decimal import Decimal

from PySide6.QtCore import Qt, Signal, Slot, QThreadPool
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHeaderView, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QMenu, QFrame, QStyle, QStyleOptionViewItem,
)

from ..cues.model import ActionType, AdvanceMode, OnGoBehavior, validate_identifier
from ..audio.engine import audio_file_duration
from .settings import application_settings
from .theme import colors, viewing_mode
from .cue_drag import CueDragHeader, MIME_TYPE
from .cue_arm import CueArmHeader
from .background import FileTask

FIELDS = ('identifier', 'name', 'action', 'audio_file', 'notes', 'advance_mode',
          'on_go_behavior', 'volume', 'loop', 'start_position', 'end_position',
          'target_internal_id', 'fade_duration', 'fade_in', 'fade_out', 'bus_ids', 'duration')
HEADERS = ('Cue ID', 'Cue Name', 'Action', 'Audio File', 'Notes', 'Next Cue Action',
           'On Go', 'Volume\nPercent', 'Loop', 'Start\nPosition', 'End\nPosition',
           'Target\nPlay Cue', 'Fade\nDuration', 'Fade-In', 'Fade-Out', 'Output Bus', 'Duration')
ORDER_WARNING_ROLE = int(Qt.UserRole) + 8

OPTIONS = {
    'action': [('Play', ActionType.PLAY), ('Stop', ActionType.STOP),
               ('Fade', ActionType.FADE), ('Stop All', ActionType.STOP_ALL)],
    'advance_mode': [(mode.label, mode) for mode in AdvanceMode],
    'on_go_behavior': [('Add to Play Stack', OnGoBehavior.ADD_TO_STACK),
                       ('Stop Prev. and Add', OnGoBehavior.STOP_PREVIOUS),
                       ('Stop All and Add', OnGoBehavior.STOP_ALL)],
}
FIELD_HELP = {
    'duration': 'Edited playable duration: End minus Start. Fades do not add time. Loops show one pass; Fade actions show their duration; Stop actions are immediate. Read-only.',
    'bus_ids': 'Choose one output bus here. Use Advanced Cue Editor for multiple buses.',
    'identifier': 'Script-page cue ID, stored as text: page.subcue (e.g. 12.10). IDs are exact text: 12.1 and 12.10 are distinct.',
    'name': 'Human-readable cue name displayed in the cue table and the armed cue display.',
    'action': 'Play starts a sound; Stop stops the target; Fade fades the target to silence; Stop All stops every sound.',
    'audio_file': 'Sound file path. Edit this cell to choose a file. Files are imported into the play folder when available.',
    'notes': 'Operator notes, such as the line or stage movement that triggers this cue.',
    'advance_mode': 'Arm Next at End arms the next cue when this action finishes. GO on End arms it now and executes it when this action finishes. Arm Next Now arms it immediately without automatic GO. For Fade, completion waits for the fade; Stop completes immediately. Loops require Arm Next Now.',
    'on_go_behavior': 'Add to Play Stack keeps existing sounds playing. Stop Prev. and Add stops the most recent sound. Stop All and Add stops all existing sounds.',
    'volume': 'Playback volume as a percentage before the assigned bus output level. 100% is unity; 50% is half; 200% is double and may clip.',
    'loop': 'Repeat the sound segment until stopped or faded. Loop requires Next Cue Action Arm Next Now.',
    'start_position': 'Position in seconds at which playback begins. 0 means the start of the sound. Must be before End Position.',
    'end_position': 'Position in seconds at which playback ends. Choosing a sound fills in its full length; reduce this value to trim it. 0 means file end.',
    'target_internal_id': 'PLAY cue whose active sound this Stop or Fade affects. Defaults to the nearest preceding Play cue. The link survives renumbering and reordering.',
    'fade_duration': 'Seconds for this Fade cue to bring the target sound to silence. 0 stops it immediately.',
    'fade_in': 'Seconds to ramp from silence to the cue volume when the sound starts. 0 starts at full level.',
    'fade_out': 'Default fade duration in seconds used by this sound’s FADE OUT playback control. 0 stops it immediately.',
}


class CueIdentifierDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(ORDER_WARNING_ROLE):
            # Keep the warning visible even when Qt paints row selection over its fill.
            painter.save()
            painter.setPen(QPen(QColor(colors()['warning']), 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


class AudioFileDelegate(QStyledItemDelegate):
    """Use the same picker for double-click and F2."""

    def createEditor(self, parent, option, index):
        self.parent().browse_audio(index.row())
        return None


class PerformanceCueDelegate(QStyledItemDelegate):
    """Selection outlines preserve the independent cue-state fill and contrast."""
    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.State_Selected)
        display = QStyleOptionViewItem(option)
        display.state &= ~QStyle.State_Selected
        super().paint(painter, display, index)
        if selected:
            painter.save()
            painter.setPen(QPen(QColor('#73aeff'), 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


class CueTable(QTableWidget):
    currentRowChanged = Signal(int)
    cueChanged = Signal()
    editRejected = Signal(str)
    audioTestRequested = Signal(str)
    cueArmRequested = Signal(str)
    audioImportStatus = Signal(str)

    def __init__(self, cue_set, editable=False, play_folder=None, parent=None, settings=None, armable=False, defer_audio=False):
        super().__init__(0, len(FIELDS), parent)
        self.cue_set, self.editable, self.play_folder = cue_set, editable, play_folder
        self.armable = armable
        self._rebuilding = False
        self.settings = settings if settings is not None else application_settings()
        self._audio_imports = {}
        self._duration_sources = {}
        self._duration_jobs = {}
        self.defer_audio = defer_audio
        if editable:
            self._initialize_defaults()
        self.setItemDelegateForColumn(FIELDS.index('identifier'), CueIdentifierDelegate(self))
        self.setItemDelegateForColumn(FIELDS.index('audio_file'), AudioFileDelegate(self))
        self.setHorizontalHeaderLabels(HEADERS)
        for col, field in enumerate(FIELDS):
            self.horizontalHeaderItem(col).setToolTip(FIELD_HELP[field])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSortingEnabled(False)
        self.setEditTriggers((QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                              QAbstractItemView.AnyKeyPressed) if editable else QAbstractItemView.NoEditTriggers)
        self._drag_token = uuid.uuid4().hex
        self._drop_line = QFrame(self.viewport())
        self._drop_line.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._drop_line.hide()
        if editable:
            self.setVerticalHeader(CueDragHeader(self))
            self.setDragDropMode(QAbstractItemView.DropOnly)
            self.setDefaultDropAction(Qt.MoveAction)
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)
            self.setAutoScroll(True)
        elif armable:
            delegate = PerformanceCueDelegate(self)
            self.setItemDelegate(delegate)
            self.setItemDelegateForColumn(FIELDS.index('identifier'), delegate)
            self.setItemDelegateForColumn(FIELDS.index('audio_file'), delegate)
            self.setVerticalHeader(CueArmHeader(self))
            self.verticalHeader().show()
        else:
            self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(42)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate((70, 170, 95, 230, 300, 150, 170, 85, 55, 95, 95, 150, 95, 85, 85)):
            self.setColumnWidth(col, width)
        self.setColumnWidth(FIELDS.index("bus_ids"), 160)
        self.setColumnWidth(FIELDS.index("duration"), 105)
        self.horizontalHeader().moveSection(FIELDS.index("duration"), 2)
        self.horizontalHeader().moveSection(self.horizontalHeader().visualIndex(FIELDS.index("bus_ids")), 4)
        for field in ('start_position', 'end_position', 'fade_duration', 'fade_in', 'fade_out'):
            self.setColumnHidden(FIELDS.index(field), True)
        if armable:
            self.horizontalHeaderItem(FIELDS.index('identifier')).setText('Cue')
            self.horizontalHeaderItem(FIELDS.index('bus_ids')).setText('Bus')
            self.horizontalHeaderItem(FIELDS.index('advance_mode')).setText('Next Cue\nAction')
            self.setColumnHidden(FIELDS.index('audio_file'), True)
            compact = {'identifier':54, 'name':170, 'action':65, 'bus_ids':60,
                       'notes':120, 'advance_mode':110, 'on_go_behavior':125,
                       'volume':62, 'loop':42, 'target_internal_id':72}
            for field, width in compact.items():
                self.setColumnWidth(FIELDS.index(field), width)
        self._restore_widths()
        self.horizontalHeader().sectionResized.connect(self._save_width)
        self._active_ids, self._next_id = set(), None
        viewing_mode().changed.connect(self._apply_theme)
        self._apply_theme()
        self.currentCellChanged.connect(lambda row, col, oldrow, oldcol: self.currentRowChanged.emit(row))
        self.itemChanged.connect(self._item_changed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._audio_context_menu)
        self.rebuild()

    def out_of_order_ids(self):
        flagged = set()
        for left, right in zip(self.cue_set.cues, self.cue_set.cues[1:]):
            if validate_identifier(left.identifier) and validate_identifier(right.identifier) and Decimal(left.identifier) > Decimal(right.identifier):
                flagged.update((left.internal_id, right.internal_id))
        return flagged

    def move_cue_to_boundary(self, cue_id, boundary):
        if not self.editable or not 0 <= boundary <= len(self.cue_set.cues):
            return False
        old = self.cue_set.index_of(cue_id)
        if old is None:
            return False
        destination = boundary - (1 if boundary > old else 0)
        if destination == old:
            return False
        self.cue_set.move(cue_id, destination)
        self.rebuild()
        self.setCurrentCell(destination, 0)
        self.scrollToItem(self.item(destination, 0))
        self.cueChanged.emit()
        return True

    def _dragged_cue(self, event):
        if not self.editable or not event.mimeData().hasFormat(MIME_TYPE):
            return None
        raw = bytes(event.mimeData().data(MIME_TYPE)).decode('utf-8', errors='replace')
        token, _, cue_id = raw.partition(':')
        return cue_id if token == self._drag_token and self.cue_set.by_internal_id(cue_id) else None

    def _drop_boundary(self, position):
        row = self.rowAt(position.y())
        if row < 0:
            return len(self.cue_set.cues) if position.y() >= 0 else 0
        rect = self.visualRect(self.model().index(row, 0))
        return row + (1 if position.y() > rect.center().y() else 0)

    def dragEnterEvent(self, event):
        if self._dragged_cue(event):
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._dragged_cue(event):
            event.ignore()
            return
        position = event.position().toPoint()
        bar = self.verticalScrollBar()
        if position.y() < 24:
            bar.setValue(bar.value()-bar.singleStep())
        elif position.y() > self.viewport().height()-24:
            bar.setValue(bar.value()+bar.singleStep())
        boundary = self._drop_boundary(position)
        y = self.rowViewportPosition(boundary) if boundary < self.rowCount() else (self.rowViewportPosition(self.rowCount()-1)+self.rowHeight(self.rowCount()-1) if self.rowCount() else 0)
        self._drop_line.setStyleSheet(f"background: {colors()['warning']};")
        self._drop_line.setGeometry(0, max(0, y-1), self.viewport().width(), 3)
        self._drop_line.show()
        self._drop_line.raise_()
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self._drop_line.hide()
        event.accept()

    def dropEvent(self, event):
        self._drop_line.hide()
        cue_id = self._dragged_cue(event)
        if cue_id:
            self.move_cue_to_boundary(cue_id, self._drop_boundary(event.position().toPoint()))
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def audio_menu_for(self, row, column):
        if not self.editable or column != FIELDS.index('audio_file') or not 0 <= row < len(self.cue_set.cues):
            return None
        cue = self.cue_set.cues[row]
        if not cue.is_play_sound() or not cue.audio_file:
            return None
        menu = QMenu(self)
        play = menu.addAction("Play / TEST Audio")
        play.triggered.connect(lambda: self.audioTestRequested.emit(cue.internal_id))
        return menu

    def _audio_context_menu(self, position):
        index = self.indexAt(position)
        menu = self.audio_menu_for(index.row(), index.column())
        if menu is not None:
            menu.exec(self.viewport().mapToGlobal(position))
            menu.deleteLater()

    def count(self):
        return self.rowCount()

    def item(self, row, column=0):
        return super().item(row, column)

    def setCurrentRow(self, row):
        self.setCurrentCell(row, 0)

    def _width_key(self, field):
        namespace = 'performance_widths_v1' if self.armable else 'widths'
        return f'cue_table/{namespace}/{field}'

    def _restore_widths(self):
        header = self.horizontalHeader()
        blocked = header.blockSignals(True)
        for col, field in enumerate(FIELDS):
            try:
                width = int(self.settings.value(self._width_key(field), self.columnWidth(col)))
            except (TypeError, ValueError):
                continue
            if 32 <= width <= 4000:
                self.setColumnWidth(col, width)
        header.blockSignals(blocked)

    def _save_width(self, col, old_width, width):
        self.settings.setValue(self._width_key(FIELDS[col]), width)
        self.settings.sync()

    def _duration_text(self, cue):
        if cue.action in (ActionType.STOP, ActionType.STOP_ALL):
            return "Immediate"
        if cue.action is ActionType.FADE:
            return f"{cue.fade_duration:.3f}s"
        end = cue.end_position
        if end is None:
            preview = getattr(cue, "_preview_waveform", None)
            if preview is not None:
                end = preview.duration
            elif not cue.audio_file:
                return "Unassigned"
            else:
                path = Path(cue.audio_file)
                if self.play_folder and not path.is_absolute():
                    path = self.play_folder.folder / path
                key = str(path.absolute())
                if key not in self._duration_sources:
                    self._request_duration(key)
                    return "Checking..."
                end = self._duration_sources[key]
                if end is None:
                    return "Unavailable"
        duration = end - (cue.start_position or 0)
        if duration <= 0:
            return "Invalid trim"
        return f"{duration:.3f}s" + (" / loop" if cue.loop else "")

    def _request_duration(self, path):
        if path in self._duration_jobs:
            return
        from ..audio.safe_decode import inspect_audio
        def check():
            try:
                return path, inspect_audio(path)["duration"]
            except Exception:
                return path, None
        task = FileTask(check)
        self._duration_jobs[path] = task
        task.signals.done.connect(self._duration_checked)
        QThreadPool.globalInstance().start(task)

    @Slot(object, str)
    def _duration_checked(self, result, error):
        if error or result is None:
            return
        path, duration = result
        self._duration_jobs.pop(path, None)
        self._duration_sources[path] = duration
        blocked = self.blockSignals(True)
        for row, cue in enumerate(self.cue_set.cues):
            item = self.item(row, FIELDS.index("duration"))
            if item is not None:
                text = self._duration_text(cue)
                item.setText(text)
                item.setToolTip("Duration: " + text + "\n" + FIELD_HELP["duration"])
        self.blockSignals(blocked)

    def _sound_duration(self, audio_file):
        path = Path(audio_file)
        if self.play_folder is not None and not path.is_absolute():
            path = self.play_folder.folder / path
        duration = audio_file_duration(str(path))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Sound has no positive duration.')
        return duration

    def applicable(self, cue, field):
        if field in ('identifier', 'name', 'action', 'notes', 'duration'):
            return True
        if field == 'advance_mode':
            return cue.action in (ActionType.PLAY, ActionType.STOP, ActionType.FADE)
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
            if not self.defer_audio and cue.is_play_sound() and cue.audio_file and cue.end_position is None:
                try:
                    duration = self._sound_duration(cue.audio_file)
                    if (cue.start_position or 0) < duration:
                        cue.end_position = duration
                except Exception:
                    # Missing or unreadable saved references remain visible;
                    # Validate Show reports them without blocking the editor.
                    pass

    @property
    def has_pending_imports(self):
        return bool(self._audio_imports)

    def cancel_imports(self):
        self._audio_imports.clear()  # Late worker results cannot change closed productions.

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
        if not path:
            return False
        cue_id = cue.internal_id
        token = uuid.uuid4().hex
        old_file = cue.audio_file
        from ..audio.safe_decode import inspect_audio
        task = FileTask(lambda: (inspect_audio(path, full=True, analyze_peaks=True), cue_id, token, path, old_file))
        self._audio_imports[cue_id] = (token, task)
        task.signals.done.connect(self._audio_checked)
        self.audioImportStatus.emit("Checking audio before import: " + Path(path).name)
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(object, str)
    def _audio_checked(self, result, error):
        if error:
            for cue_id, (_, task) in list(self._audio_imports.items()):
                if task.signals is self.sender():
                    self._audio_imports.pop(cue_id, None)
                    self.editRejected.emit("Audio import rejected: " + error[:220] + " See Diagnostics / Logs.")
                    break
            return
        metadata, cue_id, token, path, old_file = result
        current = self._audio_imports.get(cue_id)
        if not current or current[0] != token:
            return
        self._audio_imports.pop(cue_id, None)
        cue = self.cue_set.by_internal_id(cue_id)
        row = self.cue_set.index_of(cue_id)
        if cue is None or row is None or cue.audio_file != old_file:
            return
        if self.commit(row, 'audio_file', path, prevalidated=True):
            from .import_warnings import show_import_warnings
            warning = show_import_warnings(self, metadata, cue, self.cue_set.profile)
            self.audioImportStatus.emit(("Audio imported - WARNING: " + warning) if warning
                                        else "Audio checked and imported: " + Path(path).name)

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
                value = self._duration_text(cue) if field == "duration" else getattr(cue, field)
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
                if self.editable and enabled and not choices and field not in ('loop', 'duration'):
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

    def commit(self, row, field, value, prevalidated=False):
        if self._rebuilding or not self.editable or field == "duration":
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
                    from ..audio.safe_decode import inspect_audio, validated_audio
                    if prevalidated:
                        validated_audio(value)
                    else:
                        inspect_audio(value, full=True)
                    if self.play_folder is not None:
                        value = str(self.play_folder.import_audio(Path(value), prevalidated=prevalidated)).replace('\\', '/')
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
                    raise ValueError('Loop requires Arm Next Now. Change Next Cue Action first.')
                if candidate.end_position is not None and (candidate.start_position or 0) >= candidate.end_position:
                    raise ValueError('Start Position must be before End Position (0 end = file end).')
            setattr(cue, field, value)
            if field == 'action':
                cue.target_internal_id = candidate.target_internal_id
            if field == 'audio_file':
                cue.start_position = candidate.start_position
                cue.end_position = candidate.end_position
        except (ValueError, OSError, RuntimeError) as exc:
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
            color = c['stop_previous'] if cue.advance_mode is AdvanceMode.ON_COMPLETE_GO else c['on_complete'] if cue.advance_mode is AdvanceMode.ON_COMPLETE else c['on_go']
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
        flagged = self.out_of_order_ids() if self.editable else set()
        for row, cue in enumerate(self.cue_set.cues):
            active, armed = cue.internal_id in active_ids, cue.internal_id == next_id
            key = 'playing' if active else 'armed' if armed else 'completed' if cue.execution_state.value in ('complete', 'interrupted') else 'idle'
            state_background, state_text = c[key], c['text']
            if self.armable:
                if active:
                    state_background, state_text = '#875024', '#fff4e8'
                elif armed:
                    state_background, state_text = '#f1db8b', '#292411'
                elif cue.execution_state.value == 'interrupted':
                    state_background = '#503641'
            for col, field in enumerate(FIELDS):
                item = self.item(row, col)
                if item is not None:
                    item.setBackground(QColor(state_background if self.applicable(cue, field) else c['inactive']))
                    item.setForeground(QColor(state_text if self.applicable(cue, field) else c['muted']))
                    if field == 'identifier':
                        warning = cue.internal_id in flagged
                        item.setData(ORDER_WARNING_ROLE, warning)
                        if warning:
                            item.setBackground(QColor(c['stop_previous']))
                            item.setForeground(QColor(c['warning']))
                        font = item.font()
                        font.setBold(warning)
                        item.setFont(font)
                        item.setToolTip(f"Cue ID: {cue.identifier}\n{FIELD_HELP[field]}" + ("\nOut of numeric order with an adjacent cue. Order is advisory; drag a handle to rearrange." if warning else ""))
        self.blockSignals(blocked)
        header = self.verticalHeader()
        if isinstance(header, CueArmHeader):
            header.sync_states()
        else:
            header.viewport().update()
