"""Application-wide viewing preference, independent of production data."""
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel, QComboBox
from .settings import application_settings

COLORS = {
    "dark": dict(window="#14171c", base="#1b2027", text="#d2d8e1", muted="#8893a3",
                 button="#272e38", border="#414c5c", header="#29372f", selection="#30465f",
                 idle="#1b2027", inactive="#20242b", armed="#254331", playing="#514125",
                 completed="#30343b", on_complete="#293f51", on_go="#42334f",
                 add="#294235", stop_previous="#514323", stop_all="#552e32",
                 warning="#e2b66c", error="#ed9292", success="#95cba3", route="#283b51"),
    "light": dict(window="#f3f5f8", base="#ffffff", text="#172238", muted="#657185",
                  button="#ffffff", border="#bdc9d9", header="#b6d7a8", selection="#dbeafe",
                  idle="#ffffff", inactive="#eeeeee", armed="#c5e7d1", playing="#ffe1a1",
                  completed="#e5e7eb", on_complete="#bddff4", on_go="#e4cef2",
                  add="#c5e7d1", stop_previous="#ffe49b", stop_all="#f4b4b4",
                  warning="#805000", error="#a61b1b", success="#216e39", route="#dbeafe"),
}


def stylesheet(mode):
    c = COLORS[mode]
    return f"""
    QWidget {{ background-color: {c['window']}; color: {c['text']}; }}
    QLabel {{ background: transparent; }}
    QPushButton {{ background: {c['button']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 5px; padding: 8px 12px; }}
    QPushButton:hover {{ background: {c['selection']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['inactive']}; }}
    QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QAbstractItemView {{ background: {c['base']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
    QLineEdit, QComboBox, QAbstractSpinBox {{ padding: 5px; }}
    QAbstractItemView::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
    QHeaderView::section, QTableCornerButton::section {{ background: {c['header']}; color: {c['text']}; padding: 6px; border: 1px solid {c['border']}; font-weight: bold; }}
    QScrollBar {{ background: {c['window']}; }}
    QScrollBar::handle {{ background: {c['border']}; border-radius: 3px; min-width: 20px; min-height: 20px; }}
    QToolTip {{ background: {c['button']}; color: {c['text']}; padding: 6px; border: 1px solid {c['border']}; }}
    QLabel[tone="error"] {{ color: {c['error']}; }}
    QLabel[tone="warning"] {{ color: {c['warning']}; }}
    QLabel[tone="success"] {{ color: {c['success']}; }}
    QFrame#armedContainer, QFrame#playingContainer {{ border: 2px solid {c['muted']}; border-radius: 7px; }}
    QLabel#performanceSectionTitle {{ font-size: 14px; font-weight: bold; padding: 2px 0; }}
    QWidget#playingStackCard {{ background: #875024; color: #fff4e8; border: 1px solid #d78c43; border-radius: 5px; }}
    QWidget#playingStackCard QLabel {{ color: #fff4e8; border: none; }}
    QWidget#playingStackCard[selected="true"] {{ border: 2px solid #73aeff; }}
    QWidget#playingStackCard QCheckBox, QWidget#playingStackCard QSlider {{ color: #fff4e8; background: transparent; }}
    QWidget#playingStackCard QSlider::groove:horizontal {{ height: 4px; background: #3b291c; }}
    QWidget#playingStackCard QSlider::sub-page:horizontal {{ background: #f1db8b; }}
    QWidget#playingStackCard QSlider::handle:horizontal {{ width: 12px; margin: -5px 0; background: #fff4e8; border: 1px solid #3b291c; border-radius: 3px; }}
    QWidget#playingStackCard QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid #fff4e8; background: #3b291c; }}
    QWidget#playingStackCard QCheckBox::indicator:checked {{ background: #f1db8b; border: 1px solid #292411; }}
    QWidget#playingStackCard QProgressBar {{ background: #3b291c; border: none; }}
    QWidget#playingStackCard QProgressBar::chunk {{ background: #ffd39a; }}
    QFrame#armedStackCard {{ background: #f1db8b; border: 1px solid #dfc465; border-radius: 5px; }}
    QFrame#armedStackCard QLabel {{ background: transparent; color: #292411; border: none; }}
    QFrame#armedStackCard[cueState="idle"], QFrame#armedStackCard[cueState="waiting"], QFrame#armedStackCard[cueState="automatic"] {{ background: {c['button']}; border-color: {c['border']}; }}
    QFrame#armedStackCard[cueState="idle"] QLabel, QFrame#armedStackCard[cueState="waiting"] QLabel, QFrame#armedStackCard[cueState="automatic"] QLabel {{ color: {c['text']}; }}
    QLabel#routeStatus {{ background: {c['route']}; color: {c['text']}; padding: 8px; font-weight: bold; }}
    """


class ViewingMode(QObject):
    changed = Signal(str)

    def __init__(self, app, settings=None):
        super().__init__(app)
        self.app = app
        # Keep file pickers inside the application theme rather than a bright OS dialog.
        app.setAttribute(Qt.AA_DontUseNativeDialogs, True)
        self.settings = settings if settings is not None else application_settings()
        saved = self.settings.value("display/viewing_mode", "dark")
        self.mode = saved if saved in COLORS else "dark"
        self.apply(self.mode, persist=False)

    def apply(self, mode, persist=True):
        if mode not in COLORS:
            raise ValueError("Viewing mode must be dark or light.")
        self.mode = mode
        c = COLORS[mode]
        palette = QPalette()
        for role, value in ((QPalette.Window, c['window']), (QPalette.WindowText, c['text']),
                            (QPalette.Base, c['base']), (QPalette.AlternateBase, c['inactive']),
                            (QPalette.Text, c['text']), (QPalette.Button, c['button']),
                            (QPalette.ButtonText, c['text']), (QPalette.Highlight, c['selection']),
                            (QPalette.HighlightedText, c['text']), (QPalette.ToolTipBase, c['button']),
                            (QPalette.ToolTipText, c['text']), (QPalette.PlaceholderText, c['muted'])):
            palette.setColor(role, QColor(value))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(c['muted']))
        if self.app.style().objectName().lower() != "fusion":
            self.app.setStyle("Fusion")
        self.app.setPalette(palette)
        self.app.setStyleSheet(stylesheet(mode))
        if persist:
            self.settings.setValue("display/viewing_mode", mode)
            self.settings.sync()
        self.changed.emit(mode)


def viewing_mode():
    app = QApplication.instance()
    if not hasattr(app, "viewing_mode"):
        app.viewing_mode = ViewingMode(app)
    return app.viewing_mode


def colors():
    return COLORS[viewing_mode().mode]


class ViewingModeControl(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        manager = viewing_mode()
        self.setMaximumWidth(240)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Viewing mode"))
        self.combo = QComboBox()
        self.combo.setAccessibleName("Viewing mode")
        self.combo.addItem("Dark", "dark")
        self.combo.addItem("Light", "light")
        self.combo.setCurrentIndex(self.combo.findData(manager.mode))
        self.combo.setToolTip("Application display preference. Saved for future launches; does not change the production.")
        row.addWidget(self.combo)
        self.combo.currentIndexChanged.connect(lambda _: manager.apply(self.combo.currentData()))
        manager.changed.connect(self.sync)

    def sync(self, mode):
        blocked = self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(mode))
        self.combo.blockSignals(blocked)
