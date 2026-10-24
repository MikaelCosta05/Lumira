"""Material Design icons drawn straight from the font bundled with qtawesome.

Importing qtawesome itself costs ~0.1 s at startup (it wraps every Qt enum through qtpy);
the studio only needs one icon font, so icons are painted here with the same metrics
(glyph at 0.875 of the icon height, centred). qtawesome stays as a fallback.
"""
import importlib.util
import json
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication

_font = None  # (family, charmap) once loaded, False if unavailable


def _load():
    global _font
    if _font is None:
        _font = False
        spec = importlib.util.find_spec('qtawesome')
        if spec and spec.submodule_search_locations:
            folder = Path(next(iter(spec.submodule_search_locations))) / 'fonts'
            fonts = sorted(folder.glob('materialdesignicons6-webfont-*.ttf'))
            maps = sorted(folder.glob('materialdesignicons6-webfont-charmap-*.json'))
            if fonts and maps:
                ident = QFontDatabase.addApplicationFont(str(fonts[-1]))
                families = QFontDatabase.applicationFontFamilies(ident) if ident >= 0 else []
                if families:
                    charmap = json.loads(maps[-1].read_text(encoding='utf-8'))
                    _font = (families[0], charmap)
    return _font


class GlyphEngine(QIconEngine):
    def __init__(self, family, char, color):
        super().__init__()
        self.family, self.char, self.color = family, char, QColor(color)

    def paint(self, painter, rect, mode, state):
        painter.save()
        color = self.color
        if mode == QIcon.Mode.Disabled:
            app = QApplication.instance()
            color = (app.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
                     if app else QColor(150, 150, 150))
        font = QFont(self.family)
        font.setPixelSize(max(1, round(.875 * rect.height())))
        painter.setFont(font)
        painter.setPen(color)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self.char)
        painter.restore()

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(QPoint(0, 0), size), mode, state)
        painter.end()
        return pixmap

    def clone(self):
        return GlyphEngine(self.family, self.char, self.color)


def icon(name, color):
    loaded = _load()
    if loaded and name in loaded[1]:
        family, charmap = loaded
        return QIcon(GlyphEngine(family, chr(int(charmap[name], 16)), color))
    import qtawesome as qta
    return qta.icon('mdi6.' + name, color=color, color_active=color, color_selected=color)
