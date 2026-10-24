"""Shadow styles shared by shadow layers and the 3D mannequin.

Everything works on a "darkness" map: 0 is fully lit, 1 is the deepest shadow.
A style turns darkness into ink coverage (hatching lines, halftone dots, flat
bands...) or, for the colour-aware style, into a shaded version of the art below.
"""
from collections import OrderedDict

import numpy as np
from PyQt6.QtGui import QColor, QImage, QPainter

STYLES = [('Suave (degradê)', 'soft'), ('Dura (recorte)', 'hard'), ('Cel / anime (2 tons)', 'cel'),
          ('Hachura', 'hatch'), ('Hachura cruzada', 'crosshatch'), ('Retícula (pontos)', 'halftone'),
          ('Action comic', 'comic'), ('Conforme as cores do desenho', 'colored')]
STYLE_NAMES = {value: label for label, value in STYLES}
INK_STYLES = ('hatch', 'crosshatch', 'halftone', 'comic')

DEFAULT_SHADOW = {'style': 'soft', 'color': '#4b3f72', 'blend': 'multiply', 'spacing': 7., 'angle': 45., 'strength': 1.}

FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def settings_for(style, base=None):
    """Sensible defaults when switching style: ink styles use black, normal blending."""
    value = dict(DEFAULT_SHADOW, **(base or {}))
    value['style'] = style
    if style in INK_STYLES:
        value.update(color='#151515', blend='normal')
    elif style == 'colored':
        value['blend'] = 'normal'
    elif (base or {}).get('style') in INK_STYLES + ('colored',) or not base:
        value.update(color=DEFAULT_SHADOW['color'], blend='multiply')
    return value


def bgra(image):
    image = image.convertToFormat(FORMAT)
    data = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), dtype=np.uint8)
    return data.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width()]


def darkness_map(image):
    """Painted alpha is the shadow amount; darker paint makes a deeper shadow."""
    pixels = bgra(image).astype(np.float32) / 255
    alpha = pixels[..., 3]
    safe = np.maximum(alpha, 1e-6)[..., None]
    rgb = np.clip(pixels[..., :3] / safe, 0, 1)
    lightness = rgb[..., 2] * .299 + rgb[..., 1] * .587 + rgb[..., 0] * .114
    return alpha * (1 - .75 * lightness)


def smoothstep(value, low, high):
    t = np.clip((value - low) / (high - low), 0, 1)
    return t * t * (3 - 2 * t)


def _coords(shape, angle):
    height, width = shape
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    radians = np.radians(angle)
    return x * np.cos(radians) + y * np.sin(radians), -x * np.sin(radians) + y * np.cos(radians)


def _lines(u, spacing, half_width):
    distance = np.abs((u / spacing) % 1 - .5) * spacing
    return np.clip(half_width - distance + .5, 0, 1)


def _dots(u, v, spacing, darkness):
    fu = (u / spacing) % 1 - .5
    fv = (v / spacing) % 1 - .5
    distance = np.sqrt(fu * fu + fv * fv) * spacing
    radius = np.sqrt(np.clip(darkness, 0, 1)) * spacing * .72
    return np.clip(radius - distance + .5, 0, 1) * (darkness > .02)


def coverage(darkness, style, spacing=7., angle=45.):
    """Ink coverage (0–1) of a monochrome style for a darkness map."""
    spacing = max(2., float(spacing))
    d = np.clip(darkness, 0, 1).astype(np.float32)
    if style == 'soft' or style == 'colored':
        return d
    if style == 'hard':
        return smoothstep(d, .42, .5)
    if style == 'cel':
        return .55 * smoothstep(d, .2, .26) + .45 * smoothstep(d, .62, .68)
    u, v = _coords(d.shape, angle)
    if style == 'hatch':
        return _lines(u, spacing, d * spacing * .48) * (d > .03)
    if style == 'crosshatch':
        width = max(.6, spacing * .14)
        result = _lines(u, spacing, width) * smoothstep(d, .08, .16)
        result = np.maximum(result, _lines(v, spacing, width) * smoothstep(d, .38, .46))
        diagonal, _ = _coords(d.shape, angle + 45)
        result = np.maximum(result, _lines(diagonal, spacing * .7, width) * smoothstep(d, .68, .76))
        return result
    if style == 'halftone':
        return _dots(u, v, spacing, d)
    if style == 'comic':
        return np.maximum(smoothstep(d, .6, .66), _dots(u, v, spacing, np.clip(d * 1.25 - .1, 0, 1)) * (d < .66))
    raise ValueError(f'Estilo de sombra desconhecido: {style}')


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    high, low = rgb.max(axis=-1), rgb.min(axis=-1)
    delta = high - low
    safe = np.where(delta == 0, 1, delta)
    hue = np.where(high == r, ((g - b) / safe) % 6, np.where(high == g, (b - r) / safe + 2, (r - g) / safe + 4)) / 6
    hue = np.where(delta == 0, 0, hue)
    saturation = np.where(high == 0, 0, delta / np.where(high == 0, 1, high))
    return hue, saturation, high


def hsv_to_rgb(hue, saturation, value):
    i = np.floor(hue * 6).astype(np.int32) % 6
    f = hue * 6 - np.floor(hue * 6)
    p, q, t = value * (1 - saturation), value * (1 - f * saturation), value * (1 - (1 - f) * saturation)
    choices = [np.stack(c, -1) for c in ((value, t, p), (q, value, p), (p, value, t), (p, q, value), (t, p, value), (value, p, q))]
    return np.select([i[..., None] == n for n in range(6)], choices)


def shade_colors(rgb):
    """Painterly shadow of each colour: darker, a bit more saturated, hue pulled toward violet."""
    hue, saturation, value = rgb_to_hsv(rgb)
    target = .72
    difference = (target - hue + .5) % 1 - .5
    grey = saturation < .06
    hue = np.where(grey, target, (hue + difference * .12) % 1)
    saturation = np.where(grey, .12, np.clip(saturation + (1 - saturation) * .2, 0, 1))
    return hsv_to_rgb(hue, saturation, value * .6)


def to_image(rgb, alpha):
    """Float RGB (h, w, 3) and alpha (h, w) in 0–1 to a premultiplied QImage."""
    height, width = alpha.shape
    data = np.empty((height, width, 4), dtype=np.uint8)
    premultiplied = np.clip(rgb, 0, 1) * alpha[..., None]
    data[..., 0] = np.round(premultiplied[..., 2] * 255)
    data[..., 1] = np.round(premultiplied[..., 1] * 255)
    data[..., 2] = np.round(premultiplied[..., 0] * 255)
    data[..., 3] = np.round(np.clip(alpha, 0, 1) * 255)
    buffer = data.tobytes()
    return QImage(buffer, width, height, width * 4, FORMAT).copy()


def below_rgb(image):
    pixels = bgra(image).astype(np.float32) / 255
    alpha = pixels[..., 3:4]
    rgb = pixels[..., 2::-1] / np.maximum(alpha, 1e-6)
    return np.clip(rgb * alpha + (1 - alpha), 0, 1)


def stylize(darkness, settings, below=None):
    """RGBA shadow overlay (float rgb, alpha) for a darkness map."""
    style = settings.get('style', 'soft')
    strength = float(settings.get('strength', 1.))
    amount = coverage(darkness, style, settings.get('spacing', 7.), settings.get('angle', 45.)) * strength
    if style == 'colored':
        base = below if below is not None else np.ones(darkness.shape + (3,), np.float32)
        return shade_colors(base), amount
    color = QColor(settings.get('color', DEFAULT_SHADOW['color']))
    rgb = np.empty(darkness.shape + (3,), np.float32)
    rgb[...] = (color.redF(), color.greenF(), color.blueF())
    return rgb, amount


def composition(settings):
    if settings.get('style') == 'colored' or settings.get('blend') == 'normal':
        return QPainter.CompositionMode.CompositionMode_SourceOver
    return QPainter.CompositionMode.CompositionMode_Multiply


def bake(mask, settings, below):
    """Ordinary (normal-blend) pixels that look exactly like the shadow over `below`."""
    under = below_rgb(below)
    rgb, alpha = stylize(darkness_map(mask), settings, under)
    if composition(settings) == QPainter.CompositionMode.CompositionMode_Multiply:
        rgb = under * rgb
    return to_image(rgb, alpha)


_cache = OrderedDict()


def render_layer(mask, settings, below=None, below_key=None, preview=False):
    """Styled overlay for a shadow layer's painted mask. Cached by content."""
    if preview:
        tint = QImage(mask.size(), FORMAT)
        tint.fill(QColor(settings.get('color', DEFAULT_SHADOW['color'])))
        painter = QPainter(tint)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.setOpacity(.55)
        painter.drawImage(0, 0, mask)
        painter.end()
        return tint
    needs_below = settings.get('style') == 'colored'
    key = (mask.cacheKey(), tuple(sorted(settings.items())), below_key if needs_below else None)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if callable(below):
        below = below()
    rgb, alpha = stylize(darkness_map(mask), settings, below_rgb(below) if needs_below and below is not None else None)
    image = to_image(rgb, alpha)
    _cache[key] = image
    while len(_cache) > 8:
        _cache.popitem(last=False)
    return image
