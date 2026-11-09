"""Edit-only row-grip drag source; the cue model owns the resulting order."""
from PySide6.QtCore import Qt, QMimeData, QPoint
from PySide6.QtGui import QDrag, QPainter, QColor, QPixmap
from PySide6.QtWidgets import QHeaderView, QApplication
from .theme import colors

MIME_TYPE = "application/x-bhs-cue-order"


class CueDragHeader(QHeaderView):
    def __init__(self, table):
        super().__init__(Qt.Vertical, table)
        self.table = table
        self.origin = None
        self.cue_id = None
        self.setFixedWidth(28)
        self.setDefaultSectionSize(42)
        self.setSectionResizeMode(QHeaderView.Fixed)
        self.setToolTip("Drag this handle to move the cue. Cue IDs and linked actions stay unchanged.")
        self.setCursor(Qt.OpenHandCursor)

    def paintSection(self, painter, rect, logicalIndex):
        c = colors()
        painter.save()
        painter.fillRect(rect, QColor(c['button']))
        painter.setPen(QColor(c['muted']))
        for x in (rect.center().x()-3, rect.center().x()+3):
            for y in (-6, 0, 6):
                painter.drawEllipse(QPoint(x, rect.center().y()+y), 1, 1)
        painter.restore()

    def mousePressEvent(self, event):
        row = self.logicalIndexAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and 0 <= row < len(self.table.cue_set.cues):
            self.origin = event.position().toPoint()
            self.cue_id = self.table.cue_set.cues[row].internal_id
            self.table.setFocus()
            self.table.setCurrentCell(row, 0)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.origin is None or not event.buttons() & Qt.LeftButton:
            return
        if (event.position().toPoint()-self.origin).manhattanLength() < QApplication.startDragDistance():
            return
        cue = self.table.cue_set.by_internal_id(self.cue_id)
        if cue is None:
            return
        drag = QDrag(self)
        data = QMimeData()
        data.setData(MIME_TYPE, (self.table._drag_token + ":" + cue.internal_id).encode())
        drag.setMimeData(data)
        pixmap = QPixmap(230, 34)
        pixmap.fill(QColor(colors()['button']))
        painter = QPainter(pixmap)
        painter.setPen(QColor(colors()['text']))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, f"Move cue {cue.identifier}")
        painter.end()
        drag.setPixmap(pixmap)
        self.origin = None
        drag.exec(Qt.MoveAction)
        self.table._drop_line.hide()

    def mouseReleaseEvent(self, event):
        self.origin = None
        self.cue_id = None
        super().mouseReleaseEvent(event)
