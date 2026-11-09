"""Exclusive mouse arming in performance views; never executes a cue."""
from PySide6.QtGui import QColor, QPen
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionButton, QTableWidgetItem


class CueArmHeader(QHeaderView):
    def __init__(self, table):
        super().__init__(Qt.Vertical, table)
        self.table = table
        self._section_states = {}
        self.setFixedWidth(64)
        self.setDefaultSectionSize(42)
        self.setSectionResizeMode(QHeaderView.Fixed)
        self.setSectionsClickable(True)
        self.setAccessibleName("Arm cue buttons")
        self.setToolTip("Click ARM to choose the single cue GO will execute. Arming never plays audio; clicking another row replaces the armed cue.")
        self.sectionClicked.connect(self._request)

    def _request(self, row):
        if 0 <= row < len(self.table.cue_set.cues):
            self.table.setCurrentRow(row)
            self.table.cueArmRequested.emit(self.table.cue_set.cues[row].internal_id)

    def sync_states(self):
        """Publish state changes to Qt's header model, not just custom paint.

        Native header caches and accessibility clients need headerDataChanged
        notifications when automatic advancement moves the armed row.
        """
        states = {}
        for row, cue in enumerate(self.table.cue_set.cues):
            armed = cue.internal_id == self.table._next_id
            active = cue.internal_id in self.table._active_ids
            state = (cue.internal_id, armed, active, cue.execution_state.value)
            states[row] = state
            text = 'ARMED' if armed else 'ARM'
            item = self.table.verticalHeaderItem(row)
            if self._section_states.get(row) != state or item is None or item.text() != text:
                if item is None:
                    self.table.setVerticalHeaderItem(row, QTableWidgetItem(text))
                else:
                    item.setText(text)
                self.updateSection(row)
        self._section_states = states
        self.viewport().update()

    def paintSection(self, painter, rect, logicalIndex):
        if not 0 <= logicalIndex < len(self.table.cue_set.cues):
            return
        cue = self.table.cue_set.cues[logicalIndex]
        armed = cue.internal_id == getattr(self.table, '_next_id', None)
        option = QStyleOptionButton()
        option.initFrom(self)
        option.rect = rect.adjusted(3, 4, -3, -4)
        option.text = 'ARMED' if armed else 'ARM'
        option.state |= QStyle.State_Enabled
        if armed:
            option.state |= QStyle.State_On | QStyle.State_Sunken
        active = cue.internal_id in self.table._active_ids
        state = cue.execution_state.value
        background, foreground = ('#f1db8b', '#292411') if armed else (('#875024', '#fff4e8') if active else (('#503641', '#e3cad2') if state == 'interrupted' else (('#30343b', '#b8bec7') if state == 'complete' else ('#272e38', '#d2d8e1'))))
        painter.save()
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor('#dfc465' if armed else '#677180'), 1))
        painter.drawRoundedRect(option.rect, 4, 4)
        painter.setPen(QColor(foreground))
        painter.drawText(option.rect, Qt.AlignCenter, option.text)
        painter.restore()
