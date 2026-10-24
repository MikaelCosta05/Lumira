"""Interface typeface: Inter (bundled, SIL Open Font License) with Segoe UI as fallback."""
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

FOLDER = Path(__file__).resolve().parent / 'assets' / 'fonts'
FAMILY = 'Segoe UI'
DEFAULT = 'Segoe UI'
SIZE = 12
_loaded = False


def load():
    """Register the bundled fonts once and make Inter the application font."""
    global FAMILY, _loaded
    if not _loaded:
        _loaded = True
        for weight in ('Regular', 'Medium', 'SemiBold', 'Bold'):
            path = FOLDER / f'Inter-{weight}.ttf'
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        if 'Inter' in QFontDatabase.families():
            FAMILY = DEFAULT = 'Inter'
    _set_application_font()
    return FAMILY


def apply(family='', size=12):
    """Use another interface font (empty = the bundled default) and base size."""
    global FAMILY, SIZE
    load()
    FAMILY = family if family and family in QFontDatabase.families() else DEFAULT
    SIZE = size
    _set_application_font()
    return FAMILY


def _set_application_font():
    app = QApplication.instance()
    if app is not None:
        font = QFont(FAMILY)
        font.setPixelSize(SIZE)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(font)
