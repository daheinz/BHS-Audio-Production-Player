"""Small Qt worker for bounded file checks; results return through QObject slots."""
from PySide6.QtCore import QObject, QRunnable, Signal


class Result(QObject):
    done = Signal(object, str)


class FileTask(QRunnable):
    def __init__(self, work):
        super().__init__()
        self.work = work
        self.signals = Result()

    def run(self):
        try:
            result, error = self.work(), ""
        except Exception as exc:
            result, error = None, str(exc)
        try:
            self.signals.done.emit(result, error)
        except RuntimeError:
            pass  # Closing the application cancels delivery, not file safety checks.
