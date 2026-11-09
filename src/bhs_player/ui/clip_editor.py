"""Non-destructive waveform/trim/fade editor with bounded background peak extraction."""
from dataclasses import dataclass
from collections import OrderedDict
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from ..cues.model import ActionType
from .theme import colors, viewing_mode


@dataclass
class WaveformData:
    duration: float
    minimum: np.ndarray
    maximum: np.ndarray


def read_waveform(path, buckets=1600):
    from ..audio.safe_decode import waveform_audio
    duration, (minimum, maximum) = waveform_audio(path, buckets)
    return WaveformData(duration, minimum, maximum)


class _Result(QObject):
    finished = Signal(int, object, str)


class _LoadWaveform(QRunnable):
    def __init__(self, token, path):
        super().__init__()
        self.token, self.path = token, path
        self.signals = _Result()

    def run(self):
        try:
            data, error = read_waveform(self.path), ''
        except Exception as exc:
            data, error = None, str(exc)
        try:
            self.signals.finished.emit(self.token, data, error)
        except RuntimeError:
            pass  # Receiver/application was destroyed while a bounded check finished.


class WaveformLoader(QObject):
    loaded = Signal(object, str)
    cache = OrderedDict()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = 0
        self.tasks = {}
        self.keys = {}

    def request(self, path):
        self.token += 1
        token = self.token
        try:
            path = Path(path)
            stat = path.stat()
            key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        except OSError as exc:
            self.loaded.emit(None, str(exc))
            return
        if key in self.cache:
            self.cache.move_to_end(key)
            self.loaded.emit(self.cache[key], '')
            return
        task = _LoadWaveform(token, path)
        self.tasks[token], self.keys[token] = task, key
        task.signals.finished.connect(self._receive)
        QThreadPool.globalInstance().start(task)

    @Slot(int, object, str)
    def _receive(self, token, data, error):
        key = self.keys.pop(token, None)
        self.tasks.pop(token, None)
        if data is not None:
            self.cache[key] = data
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
        if token == self.token:
            self.loaded.emit(data, error)

    def cancel(self):
        self.token += 1


class ClipPlot(QWidget):
    """Drag trim bars or fade diamonds. Emit once at release, never during paint."""
    edited = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.setMinimumWidth(340)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.data = None
        self.values = {}
        self.action_mode = False
        self.message = "Select a PLAY or FADE cue to edit its clip or envelope."
        self.horizon = 10.0
        self.dragging = None
        self.playhead = None
        viewing_mode().changed.connect(self.update)
        self.setToolTip("Drag Start / End bars to trim. Drag IN / OUT diamonds to set fades. Numeric precision is available in Advanced Cue Editor. Source audio is never modified.")

    def area(self):
        return QRectF(44, 56, max(1, self.width()-64), max(40, self.height()-86))

    def time_x(self, time):
        area = self.area()
        return area.left() + min(self.horizon, max(0, time))/self.horizon * area.width()

    def x_time(self, x):
        area = self.area()
        return min(self.horizon, max(0, (x-area.left())/area.width()*self.horizon))

    def configure(self, values, data=None, action_mode=False, message=''):
        self.values = dict(values)
        self.data = data
        self.action_mode = action_mode
        self.message = message
        self.horizon = max(1.0, values.get('fade_duration', 0)*1.25, 10.0) if action_mode else data.duration if data else 1.0
        self.setEnabled(action_mode or data is not None)
        self.update()

    def boundaries(self):
        return self.values.get('start_position') or 0.0, self.values.get('end_position') or self.horizon

    def handles(self):
        area = self.area()
        if self.action_mode:
            return {'fade_duration': QPointF(self.time_x(self.values.get('fade_duration', 0)), area.bottom())}
        if self.data is None:
            return {}
        start, end = self.boundaries()
        return {
            'start_position': QPointF(self.time_x(start), area.top()-18),
            'end_position': QPointF(self.time_x(end), area.top()-18),
            'fade_in': QPointF(self.time_x(min(end, start+self.values.get('fade_in', 0))), area.top()+3),
            'fade_out': QPointF(self.time_x(max(start, end-self.values.get('fade_out', 0))), area.top()+3),
        }

    def _hit_handle(self, position):
        hits = [(abs(position.x()-point.x())+abs(position.y()-point.y()), name) for name, point in self.handles().items()]
        if not hits:
            return None
        distance, name = min(hits)
        if distance <= 18:
            return name
        if not self.action_mode and self.area().top() <= position.y() <= self.area().bottom():
            start, end = self.boundaries()
            if abs(position.x()-self.time_x(start)) <= 7:
                return 'start_position'
            if abs(position.x()-self.time_x(end)) <= 7:
                return 'end_position'
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.dragging = self._hit_handle(event.position())
            self._before_drag = dict(self.values)
            if self.dragging:
                self.setFocus()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.dragging:
            self.setCursor(Qt.SizeHorCursor if self._hit_handle(event.position()) else Qt.ArrowCursor)
            return
        time = self.x_time(event.position().x())
        name = self.dragging
        if name == 'fade_duration':
            self.values[name] = round(time, 3)
        else:
            start, end = self.boundaries()
            epsilon = min(.001, self.horizon/1000)
            if name == 'start_position':
                self.values[name] = round(min(max(0, time), end-epsilon), 6) or None
            elif name == 'end_position':
                self.values[name] = round(min(self.horizon, max(start+epsilon, time)), 6)
            elif name == 'fade_in':
                self.values[name] = round(min(end-start, max(0, time-start)), 3)
            elif name == 'fade_out':
                self.values[name] = round(min(end-start, max(0, end-time)), 3)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging and event.button() == Qt.LeftButton:
            self.mouseMoveEvent(event)
            self.dragging = None
            if self.values != self._before_drag:
                self.edited.emit(dict(self.values))
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.dragging:
            self.values = self._before_drag
            self.dragging = None
            self.update()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(c['base']))
        area = self.area()
        p.setPen(QColor(c['text']))
        if self.message and not self.action_mode and self.data is None:
            p.drawText(self.rect().adjusted(16, 8, -16, -8), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        p.drawText(12, 14, "FADE target envelope — drag Duration; no source trim" if self.action_mode else "Source waveform — drag Start / End bars and IN / OUT diamonds")
        p.setPen(QPen(QColor(c['border']), 1))
        for tick in range(6):
            x = self.time_x(tick*self.horizon/5)
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            p.setPen(QColor(c['muted']))
            p.drawText(QRectF(x-30, area.bottom()+5, 60, 20), Qt.AlignCenter, f"{tick*self.horizon/5:.2f}s")
            p.setPen(QPen(QColor(c['border']), 1))
        if self.action_mode:
            stop_x = self.time_x(self.values.get('fade_duration', 0))
            p.setPen(QPen(QColor(c['warning']), 2))
            p.drawPolyline(QPolygonF([QPointF(area.left(), area.top()), QPointF(stop_x, area.bottom()), QPointF(area.right(), area.bottom())]))
        elif self.data is not None:
            count, channels = self.data.maximum.shape
            scale = max(float(np.max(np.abs(self.data.minimum))), float(np.max(np.abs(self.data.maximum))), 1e-5)
            for ch in range(channels):
                top = area.top()+area.height()*ch/channels
                height = area.height()/channels
                mid = top+height/2
                p.setPen(QColor(c['muted']))
                p.drawText(6, int(mid), 'M' if channels == 1 else ('L' if ch == 0 else 'R'))
                p.fillRect(QRectF(area.left(), top, area.width(), height-2), QColor(c['add']))
                points = [QPointF(area.left()+i/max(1,count-1)*area.width(), mid-float(v)/scale*(height/2-5)) for i,v in enumerate(self.data.maximum[:,ch])]
                points += [QPointF(area.left()+i/max(1,count-1)*area.width(), mid-float(self.data.minimum[i,ch])/scale*(height/2-5)) for i in range(count-1,-1,-1)]
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c['success']))
                p.drawPolygon(QPolygonF(points))
            start, end = self.boundaries()
            shade = QColor(c['window'])
            shade.setAlpha(210)
            p.fillRect(QRectF(area.left(), area.top(), self.time_x(start)-area.left(), area.height()), shade)
            p.fillRect(QRectF(self.time_x(end), area.top(), max(0,area.right()-self.time_x(end)), area.height()), shade)
            fi, fo = self.values.get('fade_in',0), self.values.get('fade_out',0)
            envelope = []
            for time in np.linspace(start, end, 200):
                gain_in = min(1, max(0,(time-start)/fi)) if fi else 1
                gain_out = min(1, max(0,(end-time)/fo)) if fo and not getattr(self, 'looping', False) else 1
                envelope.append(QPointF(self.time_x(time), area.bottom()-(gain_in*gain_out)*(area.height()-3)))
            p.setPen(QPen(QColor(c['warning']), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(envelope))
            for time in (start, end):
                p.setPen(QPen(QColor(c['warning']), 2))
                p.drawLine(QPointF(self.time_x(time), area.top()), QPointF(self.time_x(time), area.bottom()))
            if self.playhead is not None:
                p.setPen(QPen(QColor(c['text']), 1))
                p.drawLine(QPointF(self.time_x(self.playhead), area.top()), QPointF(self.time_x(self.playhead), area.bottom()))
        for name, point in self.handles().items():
            p.setPen(QPen(QColor(c['warning']), 1))
            p.setBrush(QColor(c['base']))
            p.drawPolygon(QPolygonF([point+QPointF(-5,0),point+QPointF(0,-5),point+QPointF(5,0),point+QPointF(0,5)]))
            label = {'start_position':'Start','end_position':'End','fade_in':'IN','fade_out':'OUT','fade_duration':'Duration'}[name]
            p.drawText(QRectF(point.x()-30, point.y()-19, 60, 14), Qt.AlignCenter, label)


class ClipEditor(QWidget):
    """Selected-cue editor; changes are proposals applied atomically by its owner."""
    edited = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        self.title = QLabel("Audio clip")
        self.title.setWordWrap(True)
        root.addWidget(self.title)
        self.plot = ClipPlot()
        root.addWidget(self.plot)
        self.summary = QLabel("Exact timing controls are available in Advanced Cue Editor.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.loader = WaveformLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.plot.edited.connect(self._edited)
        self.cue = None
        self.data = None
        self.values = {}
        self.path = None
        self.error = ''

    def set_cue(self, cue, cue_set, play_folder=None):
        self.loader.cancel()
        self.cue, self.data, self.path, self.error = cue, None, None, ''
        self.plot.looping = bool(cue and cue.loop)
        self.plot.playhead = None
        self.values = {key: getattr(cue,key) for key in ('start_position','end_position','fade_in','fade_out','fade_duration')} if cue else {}
        if cue is None:
            self.title.setText('Audio clip — select a cue')
            self.plot.configure({}, message='Select a PLAY or FADE cue. Double-click cells or use Advanced Cue Editor for precise settings.')
        elif cue.action is ActionType.FADE:
            target = cue_set.by_internal_id(cue.target_internal_id)
            self.title.setText(f"FADE {cue.identifier} → {target.identifier + ' ' + target.name if target else '(choose a target in Advanced Cue Editor)'}")
            self.plot.configure(self.values, action_mode=True)
        elif cue.is_play_sound():
            self.title.setText(f"Audio clip · {cue.identifier} · {cue.name}")
            sample = getattr(cue, '_preview_waveform', None)
            if sample is not None and not cue.audio_file:
                self.title.setText(self.title.text()+' · SAMPLE WAVEFORM / NO AUDIO')
                self._loaded(sample, '')
            elif cue.audio_file:
                self.path = Path(cue.audio_file)
                if play_folder is not None and not self.path.is_absolute():
                    self.path = play_folder.folder / self.path
                self.plot.configure(self.values, message='Loading source waveform…')
                self.loader.request(self.path)
            else:
                self.plot.configure(self.values, message='Choose an audio file to see its waveform. Use Browse / Import Audio or double-click the Audio File cell.')
        else:
            self.title.setText(f"{cue.action.value} {cue.identifier} · no audio clip")
            self.plot.configure(self.values, message='This action has no source audio or clip envelope.')
        self._summary()

    @Slot(object, str)
    def _loaded(self, data, error):
        self.data, self.error = data, error
        self.plot.configure(self.values, data=data, message=('Waveform unavailable: '+error+'\nUse Advanced Cue Editor for numeric timing.') if error else '')
        self._summary()

    def set_values(self, values):
        self.values.update(values)
        self.plot.configure(self.values, self.data, action_mode=bool(self.cue and self.cue.action is ActionType.FADE), message=('Waveform unavailable: '+self.error) if self.error else self.plot.message)
        self._summary()

    def _edited(self, values):
        self.values = dict(values)
        self._summary()
        self.edited.emit(values)

    def _summary(self):
        if self.cue is None:
            self.summary.setText('Drag cue-row handles to reorder. Amber Cue IDs mark numeric reversals.')
        elif self.cue.action is ActionType.FADE:
            self.summary.setText(f"Target fade: {self.values.get('fade_duration',0):.3f}s to silence, then stop. This is an action duration, not a source-file trim.")
        elif self.cue.is_play_sound():
            start = self.values.get('start_position') or 0
            end = self.values.get('end_position')
            end = f"{end:.3f}s" if end else f"{self.data.duration:.3f}s" if self.data else 'file end'
            loop_note = ' · OUT applies to manual FADE OUT; loops do not fade each repeat.' if self.cue.loop else ' · OUT fades at the playable end and is the manual fade default.'
            self.summary.setText(f"Start {start:.3f}s → End {end} · IN {self.values.get('fade_in',0):.3f}s · OUT {self.values.get('fade_out',0):.3f}s"+loop_note)
        else:
            self.summary.setText('Use Advanced Cue Editor to configure action settings.')
