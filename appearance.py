"""User appearance: colour overrides per mode, background image, typography and shapes.

The settings are a plain dict (saved in .studio-settings.json and exportable as a theme file):
colour overrides are stored separately for the dark and the light mode, so each keeps its look.
"""
import json
from collections import OrderedDict

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

COLOR_KEYS = [
    ('bg', 'Fundo da janela'), ('panel', 'Painéis'), ('field', 'Campos e listas'), ('border', 'Bordas'),
    ('text', 'Texto'), ('muted', 'Texto secundário'), ('strong', 'Títulos'), ('accent', 'Cor de destaque'),
    ('selected', 'Item selecionado'), ('hover', 'Ao passar o mouse'), ('canvas', 'Área ao redor do desenho'),
    ('ok', 'Confirmação'), ('danger', 'Alerta'),
]
FITS = [('Preencher (cortar as sobras)', 'cover'), ('Ajustar (imagem inteira)', 'contain'), ('Esticar', 'stretch'),
        ('Lado a lado', 'tile'), ('Centralizar', 'center')]
FILE_FILTER = 'Tema do Studio (*.studiotheme *.json)'

DEFAULTS = {
    'preset': 'Padrão',
    'colors': {'Escuro': {}, 'Claro': {}},
    'background': '',
    'background_fit': 'cover',
    'background_opacity': .6,
    'background_blur': 0,
    'panel_opacity': .88,
    'background_canvas': True,
    'canvas_opacity': .7,
    'font_family': '',
    'font_size': 12,
    'radius': 8,
    'border_width': 1,
}

_DARK_BASE = {'text': '#d5d7dd', 'muted': '#868a95', 'strong': '#f2f3f5'}
PRESETS = {
    'Padrão': {'Escuro': {}, 'Claro': {}},
    'Oceano': {
        'Escuro': dict(bg='#0b1220', panel='#121b2b', field='#18243a', border='#22314a', hover='#1c2a42',
                       canvas='#080e19', accent='#3b8eea', selected='#1b3150'),
        'Claro': dict(bg='#d5dde8', panel='#f2f6fb', border='#cdd7e3', hover='#e6edf6', canvas='#bfcad8',
                      accent='#2a72c9', selected='#d6e6f8')},
    'Ametista': {
        'Escuro': dict(bg='#120f18', panel='#1c1724', field='#251e30', border='#30273d', hover='#2a2236',
                       canvas='#0d0a12', accent='#9b6cf0', selected='#33264d'),
        'Claro': dict(bg='#dfdae8', panel='#f6f3fa', border='#d9d1e6', hover='#ece6f5', canvas='#cac2d8',
                      accent='#7a4fd6', selected='#e6dcfa')},
    'Âmbar': {
        'Escuro': dict(bg='#14110c', panel='#1f1a13', field='#28221a', border='#352d21', hover='#2d261c',
                       canvas='#0f0c08', accent='#e0a030', selected='#3d3018', strong='#fbf3e4'),
        'Claro': dict(bg='#e4ddd0', panel='#faf6ee', border='#e0d6c4', hover='#f1eadc', canvas='#d0c6b4',
                      accent='#c27c0e', selected='#f6e6c4')},
    'Rosa': {
        'Escuro': dict(bg='#140f12', panel='#1f171b', field='#291e24', border='#35262e', hover='#2c2026',
                       canvas='#0f0a0d', accent='#e8608f', selected='#432232'),
        'Claro': dict(bg='#e8dade', panel='#fbf4f6', border='#e6d3d9', hover='#f3e6ea', canvas='#d6c4ca',
                      accent='#d1406f', selected='#f9dbe5')},
    'Floresta': {
        'Escuro': dict(bg='#0e130e', panel='#171e16', field='#1f281e', border='#293427', hover='#222c21',
                       canvas='#0a0e0a', accent='#5fb35a', selected='#22351f'),
        'Claro': dict(bg='#d9e0d6', panel='#f4f8f2', border='#d0dacb', hover='#e8efe5', canvas='#c2ccbe',
                      accent='#3f8f3a', selected='#dbeed8')},
    'Grafite': {
        'Escuro': dict(bg='#151515', panel='#202020', field='#2a2a2a', border='#333333', hover='#2e2e2e',
                       canvas='#101010', accent='#a0a0a0', selected='#3a3a3a', text='#dddddd', muted='#8c8c8c',
                       strong='#ffffff'),
        'Claro': dict(bg='#dcdcdc', panel='#f5f5f5', field='#ffffff', border='#d0d0d0', hover='#ebebeb',
                      canvas='#c8c8c8', accent='#5c5c5c', selected='#dedede')},
    'Clássico (estilo Photoshop)': {
        'Escuro': dict(bg='#262626', panel='#323232', field='#3c3c3c', border='#454545', hover='#404040',
                       canvas='#1e1e1e', accent='#2d8ceb', selected='#2f4a66', text='#d6d6d6', muted='#9a9a9a'),
        'Claro': dict(bg='#d6d6d6', panel='#ececec', field='#ffffff', border='#c4c4c4', hover='#e0e0e0',
                      canvas='#bdbdbd', accent='#1473e6', selected='#d4e5fb')},
    'Alto contraste': {
        'Escuro': dict(bg='#000000', panel='#0b0b0b', field='#141414', border='#5a5a5a', text='#ffffff',
                       muted='#c8c8c8', strong='#ffffff', accent='#ffd400', selected='#3d3500', hover='#1f1f1f',
                       canvas='#000000'),
        'Claro': dict(bg='#ffffff', panel='#ffffff', field='#ffffff', border='#000000', text='#000000',
                      muted='#333333', strong='#000000', accent='#0047ff', selected='#cfdcff', hover='#eeeeee',
                      canvas='#e6e6e6')},
}
PRESET_NAMES = list(PRESETS)


def _number(value, default, low, high, kind=float):
    try:
        return max(low, min(high, kind(value)))
    except (TypeError, ValueError):
        return default


def _colors(value):
    """Only known keys with valid colours survive (also for imported theme files)."""
    names = {key for key, _ in COLOR_KEYS}
    result = {}
    for mode in ('Escuro', 'Claro'):
        overrides = value.get(mode) if isinstance(value, dict) else None
        result[mode] = {key: QColor(color).name() for key, color in (overrides or {}).items()
                        if key in names and isinstance(color, str) and QColor(color).isValid()}
    return result


def normalize(value):
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULTS)
    preset = value.get('preset')
    result['preset'] = preset if preset in PRESETS or preset == 'Personalizado' else 'Padrão'
    result['colors'] = _colors(value.get('colors', {}))
    result['background'] = value.get('background') if isinstance(value.get('background'), str) else ''
    fits = [fit for _, fit in FITS]
    result['background_fit'] = value.get('background_fit') if value.get('background_fit') in fits else 'cover'
    result['background_opacity'] = _number(value.get('background_opacity'), DEFAULTS['background_opacity'], 0., 1.)
    result['background_blur'] = _number(value.get('background_blur'), 0, 0, 40, int)
    result['panel_opacity'] = _number(value.get('panel_opacity'), DEFAULTS['panel_opacity'], .3, 1.)
    result['background_canvas'] = bool(value.get('background_canvas', DEFAULTS['background_canvas']))
    result['canvas_opacity'] = _number(value.get('canvas_opacity'), DEFAULTS['canvas_opacity'], 0., 1.)
    result['font_family'] = value.get('font_family') if isinstance(value.get('font_family'), str) else ''
    result['font_size'] = _number(value.get('font_size'), 12, 10, 16, int)
    result['radius'] = _number(value.get('radius'), 8, 0, 16, int)
    result['border_width'] = _number(value.get('border_width'), 1, 0, 3, int)
    return result


def preset_colors(name):
    preset = PRESETS.get(name, PRESETS['Padrão'])
    return {'Escuro': dict(preset['Escuro']), 'Claro': dict(preset['Claro'])}


def mix(a, b, amount):
    """Colour between `a` (amount 0) and `b` (amount 1)."""
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * amount), round(a.green() + (b.green() - a.green()) * amount),
                  round(a.blue() + (b.blue() - a.blue()) * amount)).name()


def palette(mode, settings):
    """Effective colours of a mode: the built-in palette with the user's overrides.

    Changing only the accent also tints the selection, so one pick restyles the interface.
    """
    from themes import BASE_PALETTES
    colors = dict(BASE_PALETTES[mode])
    overrides = settings['colors'].get(mode, {})
    colors.update(overrides)
    if 'accent' in overrides and 'selected' not in overrides:
        colors['selected'] = mix(colors['panel'], colors['accent'], .3 if mode == 'Escuro' else .2)
    return colors


def rgba(color, alpha):
    color = QColor(color)
    return f'rgba({color.red()}, {color.green()}, {color.blue()}, {round(alpha * 255)})'


def export_theme(path, settings):
    """Theme file: everything except the background image path (it is machine-specific)."""
    data = {key: value for key, value in settings.items() if key != 'background'}
    data['format'] = 'studio-desenho-theme'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def import_theme(path, current):
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get('colors', {}), dict):
        raise ValueError('O arquivo não é um tema do Studio Desenho.')
    merged = dict(current)
    merged.update({key: value for key, value in data.items() if key in DEFAULTS and key != 'background'})
    return normalize(merged)


# ------------------------------------------------------------- background

class Background:
    """The window background image: loaded once, blurred and scaled on demand, cached."""

    MAX_SIDE = 2560

    def __init__(self):
        self.path = ''
        self.source = None
        self.blurred = {}
        self.cache = OrderedDict()

    def load(self, path):
        if path == self.path and (self.source is not None or not path):
            return self.source is not None
        self.clear()
        if not path:
            return False
        image = QImage(path)
        if image.isNull():
            return False
        if max(image.width(), image.height()) > self.MAX_SIDE:
            image = image.scaled(self.MAX_SIDE, self.MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        self.source = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.path = path
        return True

    def clear(self):
        self.path, self.source, self.blurred, self.cache = '', None, {}, OrderedDict()

    def image(self, blur):
        if not blur or self.source is None:
            return self.source
        if blur not in self.blurred:
            import display
            from scipy import ndimage
            # Blur a reduced copy (a blurred image has no fine detail to lose), then keep it.
            small = self.source.scaled(max(1, self.source.width() // 2), max(1, self.source.height() // 2),
                                       Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            data = display.pixels(small).astype('float32')
            blurred = ndimage.gaussian_filter(data, (blur / 2, blur / 2, 0), mode='nearest')
            self.blurred = {blur: display.from_pixels(blurred.round().clip(0, 255))}
        return self.blurred[blur]

    def pixmap(self, size, settings, base_color):
        """Window-sized background: base colour with the image drawn over it."""
        key = (size.width(), size.height(), settings['background_fit'], settings['background_opacity'],
               settings['background_blur'], base_color, self.path)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        pixmap = QPixmap(QSize(max(1, size.width()), max(1, size.height())))
        pixmap.fill(QColor(base_color))
        image = self.image(settings['background_blur'])
        if image is not None:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setOpacity(settings['background_opacity'])
            draw_fitted(painter, image, QRectF(0, 0, size.width(), size.height()), settings['background_fit'])
            painter.end()
        self.cache[key] = pixmap
        while len(self.cache) > 3:
            self.cache.popitem(last=False)
        return pixmap


def draw_fitted(painter, image, rect, fit):
    width, height = image.width(), image.height()
    if fit == 'stretch':
        painter.drawImage(rect, image)
    elif fit == 'tile':
        painter.drawTiledPixmap(rect, QPixmap.fromImage(image))
    elif fit == 'center':
        painter.drawImage(QPointF(rect.center().x() - width / 2, rect.center().y() - height / 2), image)
    else:
        scale = (max if fit == 'cover' else min)(rect.width() / width, rect.height() / height)
        w, h = width * scale, height * scale
        painter.drawImage(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h), image)


def swatch_icon(colors, size=18):
    """Small icon showing a preset's accent over its panel colour (for the preset list)."""
    from PyQt6.QtGui import QIcon
    pixmap = QPixmap(size * 2, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colors['panel']))
    painter.drawRoundedRect(QRectF(0, 0, size * 2, size), 4, 4)
    painter.setBrush(QColor(colors['accent']))
    painter.drawEllipse(QRectF(size * .25, size * .2, size * .6, size * .6))
    painter.setBrush(QColor(colors['text']))
    painter.drawRoundedRect(QRectF(size, size * .38, size * .8, size * .24), 2, 2)
    painter.end()
    return QIcon(pixmap)


def effective_preview(settings):
    """Both modes' palettes (for previews in the dialog)."""
    return {mode: palette(mode, settings) for mode in ('Escuro', 'Claro')}
