"""Bounded local troubleshooting logs; all file writes use a listener thread."""
from pathlib import Path
import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from queue import Queue
import platform
import sys
import time

LOGGER = logging.getLogger("bhs_player")
LOGGER.addHandler(logging.NullHandler())
_directory = Path(__file__).resolve().parents[2] / "logs"
_listener = None
_handler = None
_file_handler = None
_error = ""



class _FileHandler(RotatingFileHandler):
    def handleError(self, record):
        global _error
        _error = "Log write failed: " + str(sys.exc_info()[1])


class _QueueHandler(QueueHandler):
    def handleError(self, record):
        global _error
        _error = "Log queue full; some diagnostic entries were dropped."


def log_path():
    return _directory / "bhs-player.log"


def logging_error():
    return _error


def configure_logging(directory=None):
    global _directory, _listener, _handler, _file_handler, _error
    if _listener is not None:
        return log_path()
    if directory is not None:
        _directory = Path(directory)
    try:
        _directory.mkdir(parents=True, exist_ok=True)
        _file_handler = _FileHandler(log_path(), maxBytes=2*1024*1024,
                                           backupCount=4, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s",
                                      datefmt="%Y-%m-%dT%H:%M:%SZ")
        formatter.converter = time.gmtime
        _file_handler.setFormatter(formatter)
        queue = Queue(maxsize=2048)
        _handler = _QueueHandler(queue)
        LOGGER.setLevel(logging.INFO)
        LOGGER.addHandler(_handler)
        _listener = QueueListener(queue, _file_handler, respect_handler_level=True)
        _listener.start()
        _error = ""
        LOGGER.info("APPLICATION START python=%s platform=%s", sys.version.split()[0], platform.platform())
        LOGGER.info("RUNTIME numpy=%s sounddevice=%s PySide6=%s",
                    getattr(sys.modules.get('numpy'), '__version__', 'unknown'),
                    getattr(sys.modules.get('sounddevice'), '__version__', 'unknown'),
                    getattr(sys.modules.get('PySide6'), '__version__', 'unknown'))
    except OSError as exc:
        _error = str(exc)
    return log_path()


def shutdown_logging():
    global _listener, _handler, _file_handler
    if _listener is not None:
        LOGGER.info("APPLICATION END")
        _listener.queue.join()
        _listener.stop()
        LOGGER.removeHandler(_handler)
        _file_handler.close()
        _listener = _handler = _file_handler = None


def read_log_tail(limit=128*1024):
    path = log_path()
    if not path.exists():
        return "No log entries yet."
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size-limit))
            return stream.read(limit).decode("utf-8", errors="replace")
    except OSError as exc:
        return "Cannot read log: " + str(exc)
