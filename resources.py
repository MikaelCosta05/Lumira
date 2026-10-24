"""Portable brush/palette libraries and side-effect-free ABR parsing."""
from functools import lru_cache
import base64
import importlib.metadata
import importlib.util
import io
import json
import re
import sys
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtGui import QColor, QImage
from app_paths import DATA_ROOT


@dataclass
class Brush:
    name: str = 'Redondo sólido'
    size: float = 5.
    hardness: float = 1.
    spacing: float = .12
    angle: float = 0.
    roundness: float = 1.
    scatter: float = 0.
    jitter: float = 0.
    flow: float = 1.
    tip: str = ''
    source: dict = field(default_factory=dict)
    opacity_pressure: float = 0.
    angle_jitter: float = 0.
    grain: str = ''
    grain_strength: float = 0.
    grain_scale: float = 1.
    grain_image: str = ''
    wet_edges: float = 0.
    follow_direction: bool = False
    size_pressure: bool = True
    category: str = 'Meus pincéis'
    depletion: float = 0.
    taper_in: float = 0.  # the stroke starts thin and widens over up to 12 brush widths
    speed_size: float = 0.  # -1..1: fast strokes get thinner (positive) or thicker (negative)
    opacity_jitter: float = 0.
    flow_pressure: float = 0.
    roundness_jitter: float = 0.
    count: int = 1  # dabs placed at each spacing step (each with its own scatter and jitter)
    flip_jitter: bool = False
    grain_invert: bool = False
    grain_contrast: float = 1.

    @property
    def basic(self):
        return (not self.tip and self.hardness >= .999 and self.roundness >= .999 and self.flow >= .999
                and self.count == 1
                and not (self.scatter or self.jitter or self.angle or self.opacity_pressure or self.angle_jitter
                         or self.wet_edges or self.depletion or (self.grain and self.grain_strength)
                         or self.taper_in or self.speed_size or self.opacity_jitter or self.flow_pressure
                         or self.roundness_jitter or self.flip_jitter))

    def mask(self):
        if self.tip:
            return decoded_mask(self.tip)
        return computed_mask(self.hardness, self.roundness)

    def image(self, color):
        mask = np.asarray(self.mask(), dtype='uint8')
        pixels = np.empty((*mask.shape, 4), dtype='uint8')
        pixels[:, :, :3] = [color.red(), color.green(), color.blue()]
        pixels[:, :, 3] = mask
        return QImage(pixels.tobytes(), pixels.shape[1], pixels.shape[0], pixels.shape[1] * 4,
                      QImage.Format.Format_RGBA8888).copy()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        brush = cls(**{key: val for key, val in value.items() if key in cls.__dataclass_fields__})
        brush.size = max(.1, min(500, float(brush.size)))
        brush.spacing = max(.01, min(2., float(brush.spacing)))
        for key in ('hardness', 'roundness', 'jitter', 'flow', 'opacity_pressure', 'grain_strength', 'wet_edges',
                    'depletion', 'taper_in', 'opacity_jitter', 'flow_pressure', 'roundness_jitter'):
            setattr(brush, key, max(0.01 if key == 'roundness' else 0., min(1., float(getattr(brush, key)))))
        brush.scatter = max(0., min(4., float(brush.scatter)))
        brush.angle_jitter = max(0., min(180., float(brush.angle_jitter)))
        brush.speed_size = max(-1., min(1., float(brush.speed_size)))
        brush.count = max(1, min(16, int(round(float(brush.count)))))
        brush.grain_scale = max(.1, min(8., float(brush.grain_scale)))
        brush.grain_contrast = max(.2, min(4., float(brush.grain_contrast)))
        brush.grain = brush.grain if brush.grain in GRAIN_KINDS else ''
        brush.follow_direction, brush.size_pressure = bool(brush.follow_direction), bool(brush.size_pressure)
        brush.flip_jitter, brush.grain_invert = bool(brush.flip_jitter), bool(brush.grain_invert)
        brush.name, brush.category = str(brush.name)[:80] or 'Pincel', str(brush.category)[:40] or 'Meus pincéis'
        if brush.tip:
            image = brush.mask()
            if max(image.size) > 4096 or not image.getbbox():
                raise ValueError('Ponta de pincel inválida ou grande demais.')
        return brush


GRAIN_KINDS = ('', 'paper', 'rough', 'canvas', 'charcoal', 'watercolor', 'kraft', 'pastel', 'linen', 'burlap',
               'concrete', 'wood', 'sand', 'sponge', 'noise', 'crosshatch', 'halftone', 'custom')


@lru_cache(maxsize=32)
def computed_mask(hardness, roundness, size=512):
    """Round tip, supersampled so hard edges stay smooth when enlarged.
    Soft tips fall off like a real airbrush (smoothstep), without a visible ring at the edge."""
    grid = np.linspace(-1, 1, size * 2, dtype=np.float32)
    y, x = np.meshgrid(grid, grid, indexing='ij')
    radius = np.sqrt(x * x + (y / max(.05, roundness)) ** 2)
    alpha = np.clip((1 - radius) / max(.01, 1 - hardness), 0, 1)
    alpha = alpha * alpha * (3 - 2 * alpha)
    alpha = alpha.reshape(size, 2, size, 2).mean(axis=(1, 3))
    return Image.fromarray((alpha * 255).round().astype('uint8'))


@lru_cache(maxsize=64)
def decoded_mask(tip):
    """Tips are decoded once; every stroke start would otherwise unpack the PNG again."""
    return Image.open(io.BytesIO(base64.b64decode(tip))).convert('L')


DEFAULT_PALETTES = {
 'Pele': ['#36211f','#603b32','#845040','#a76b51','#c18b68','#d8a580','#ebbc9a','#f5d2b5','#fae4ce','#73484e','#ba7e7d','#e5b9a5'],
 'Metais': ['#151c25','#293747','#48566b','#718397','#9baaba','#d2dce4','#f4f8fa','#3e4142','#757779','#adaaa5','#bcb1a4','#665952'],
 'Ouro': ['#332018','#644522','#92651f','#b98a2f','#d4aa48','#e8c664','#f8e3a0','#fff4d0','#856043','#c58b47','#eebf6f','#fff9e3'],
 'Diamante': ['#162c48','#244e73','#3b80a3','#64a9c4','#99d0db','#c5e9ec','#effbfb','#ffffff','#8f80b9','#b3a9d0','#cedcea','#ddeefb'],
 'Grama': ['#15291c','#254329','#385f32','#4f7a39','#71994a','#96b660','#c1d481','#e0e8b0','#4b5436','#758146','#b09f51','#e6cc80'],
 'Madeira': ['#261b19','#493126','#704a32','#95643f','#b88456','#d6a571','#ecc694','#f5dfb8','#514037','#89664d','#b09170','#d9c2a0'],
 'Sombras': ['#10121d','#1b2033','#29304a','#3d4561','#555e78','#747d96','#242732','#363b42','#4c5659','#695c6f','#856e83','#a58e9c'],
 'Luz': ['#fffdf2','#fff1ce','#ffe6a3','#ffd374','#ffb966','#f69d69','#fff7e8','#e8f3ff','#c8e5ff','#afd4ef','#e8daff','#ffd6e4'],
 'Neutros': ['#101114','#282a2f','#464951','#6e7380','#959daa','#bcc3cc','#e4e7ec','#ffffff','#b9b0a5','#d5c7b5','#e8dbc9','#f6ecdd'],
 'Prata': ['#1a1d22','#30353d','#4a515b','#68707b','#8c949e','#b2b8bf','#d6dadf','#f3f5f7','#5a6170','#7d8597','#a5adbd','#e9edf5'],
 'Cobre e bronze': ['#2a140c','#4d2414','#73381d','#9a5228','#bd6e38','#d68f52','#ebb178','#f8d6a8','#5c3a22','#8a5f36','#b8894e','#e0bb7a'],
 'Fogo': ['#2b0a06','#5c120a','#8f1f0c','#c2340f','#e3561a','#f47e25','#fba63a','#fdcb5a','#ffe68c','#fff6cf','#7a2a3f','#b5476b'],
 'Céu e água': ['#0b1a33','#14315c','#1d4f8a','#2a72b5','#4597d6','#72b8e8','#a6d6f2','#d9eefa','#0f3d3e','#17676a','#2f9c9a','#7fd1c7'],
 'Pedra': ['#1c1b1d','#2f2d31','#45424a','#5e5a63','#79747d','#958f98','#b3adb4','#d2cdd1','#4a463c','#6b6553','#8e8770','#b8b194'],
 'Cabelo': ['#120c0a','#2b1a14','#4a2c1f','#6e4329','#93603a','#b9874f','#d9b073','#f0d9a3','#5a2416','#8e3b1f','#c45a2c','#9a9aa4'],
 'Pôr do sol': ['#1d1631','#3b1f4a','#6a2a5c','#a13a5f','#d5545a','#f07c4f','#f9a65a','#fdd38a','#fff0c2','#2c3466','#51508a','#8d6fa8'],
 'Oceano': ['#03111f','#062a43','#0a4466','#0f5f85','#1c7fa3','#34a0bd','#62c2d3','#9ee0e3','#d4f4f1','#0c3b3a','#1f6b5f','#e8d9b0'],
 'Floresta': ['#0b1610','#14281b','#1f3d27','#2f5634','#466f3f','#63894b','#86a35d','#b1c27a','#d9dca3','#3b2a1e','#62452c','#8d6a43'],
 'Pastel': ['#fbd3d9','#fde1c3','#fff3c4','#d9f2c9','#c8ecf0','#cfdcfb','#e3d3f6','#f6d6ef','#fff8f0','#e8e2da','#b9c6d6','#a7b6a0'],
 'Neon': ['#0b0b16','#ff2a6d','#ff7a18','#fff200','#39ff14','#00f5d4','#05d9e8','#3a86ff','#8338ec','#ff00f5','#d1f7ff','#ffffff'],
 'Terra': ['#21150f','#3d2618','#5c3a22','#7d5233','#9c6b45','#b98a5d','#cfa97e','#e2c9a5','#6f6047','#8f7f5e','#a63d2a','#c7672f'],
 'Game Boy': ['#0f380f','#306230','#8bac0f','#9bbc0f'],
 'Mangá (cinzas)': ['#000000','#1a1a1a','#333333','#4d4d4d','#666666','#808080','#999999','#b3b3b3','#cccccc','#e6e6e6','#f2f2f2','#ffffff'],
 'Retrô 80': ['#1b1035','#2e1a5c','#4f1f84','#7b2cbf','#c03fbf','#ff4f9a','#ff8a5b','#ffc857','#3ec1d3','#1f7ea1','#f8f1ff','#101010'],
 'PICO-8': ['#000000','#1d2b53','#7e2553','#008751','#ab5236','#5f574f','#c2c3c7','#fff1e8','#ff004d','#ffa300','#ffec27','#00e436','#29adff','#83769c','#ff77a8','#ffccaa'],
}


def png_base64(image):
    data = io.BytesIO()
    image.save(data, format='PNG')
    return base64.b64encode(data.getvalue()).decode('ascii')


def mask_from_image(image):
    rgba = image.convert('RGBA')
    alpha = rgba.getchannel('A')
    if alpha.getextrema() == (255, 255):
        alpha = Image.fromarray(255 - np.asarray(rgba.convert('L'), dtype='uint8'))
    box = alpha.getbbox()
    if not box:
        raise ValueError('A ponta não contém pixels visíveis.')
    alpha = alpha.crop(box)
    alpha.thumbnail((1024, 1024))
    return png_base64(alpha)


def _abr_module():
    # Importing this package's __init__ would install a Krita plugin. Load ONLY
    # its independent stdlib parser; no Krita directories are touched.
    name = '_studio_abr_parser'
    if name not in sys.modules:
        source = importlib.metadata.distribution('abr-brush-importer').locate_file('abr_brush_importer/abr_parser.py')
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _tip_mask(tip):
    if not (0 < tip.width <= 8192 and 0 < tip.height <= 8192 and tip.image_data):
        return None
    mode = {1: 'L', 3: 'RGB', 4: 'RGBA'}.get(tip.channels)
    if not mode:
        return None
    mask = Image.frombytes(mode, (tip.width, tip.height), tip.image_data)
    mask = mask if mode == 'L' else mask.getchannel('A') if mode == 'RGBA' else mask.convert('L')
    if not mask.getbbox():
        return None
    mask.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    return mask


def _number(descriptor, key, default=None):
    value = descriptor.get(key) if isinstance(descriptor, dict) else None
    if isinstance(value, dict):
        value = value.get('value')
    return float(value) if isinstance(value, (int, float)) else default


def _uuid_like(name):
    return bool(re.fullmatch(r'\$?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', name or ''))


def abr_presets(parser):
    """Brush presets from the 'desc' block of an ABR v6+ (names, sizes, dynamics)."""
    position = parser._data.find(b'8BIMdesc')
    if position < 0:
        return []
    try:
        parser._seek(position + 16)  # tag, type, length, descriptor version
        descriptor = parser._parse_descriptor()
    except Exception:  # a damaged descriptor only loses the presets, not the tips
        return []
    presets = descriptor.get('Brsh', [])
    return [p for p in presets if isinstance(p, dict)] if isinstance(presets, list) else []


def load_abr(path):
    """Photoshop brushes: each preset keeps its name, tip, size, spacing and pen dynamics."""
    module = _abr_module()
    parser = module.ABRParser(filepath=str(path))
    tips = parser.parse()
    by_id = {tip.name.lstrip('$'): tip for tip in tips if tip.name}
    patterns = {}
    for pattern in getattr(parser, 'patterns', []):
        image = _tip_mask(pattern)
        if image is not None:
            for key in (pattern.name, pattern.pattern_id):
                if key:
                    patterns[key] = png_base64(image)
    stem = ' '.join(Path(path).stem.replace('_', ' ').split()[:4])[:32]
    brushes = []
    for preset in abr_presets(parser):
        shape = preset.get('Brsh', {}) if isinstance(preset.get('Brsh'), dict) else {}
        name = str(preset.get('Nm  ') or shape.get('Nm  ') or f'{stem} {len(brushes) + 1}')
        name = f'{stem} {name}' if name.strip().isdigit() else name
        sampled = shape.get('sampledData')
        tip = by_id.get(str(sampled).lstrip('$')) if sampled else None
        mask = _tip_mask(tip) if tip else None
        if sampled and mask is None:
            continue

        def control(key):
            value = preset.get(key)
            return value.get('bVTy', 0) if isinstance(value, dict) else 0

        def jitter(key):
            return (_number(preset.get(key, {}), 'jitter', 0.) or 0.) / 100

        brush = Brush(name, size=max(1., min(500., _number(shape, 'Dmtr', 30.))),
                      hardness=(_number(shape, 'Hrdn', 100.) / 100) if not sampled else 1.,
                      spacing=max(.01, min(2., _number(shape, 'Spcn', 25.) / 100)),
                      angle=_number(shape, 'Angl', 0.), roundness=max(.05, _number(shape, 'Rndn', 100.) / 100),
                      tip=png_base64(mask) if mask is not None else '', category=f'Photoshop · {stem}',
                      source={'abr': Path(path).name, 'preset': name})
        if preset.get('useTipDynamics', True):
            brush.size_pressure = control('szVr') == 2
            brush.jitter = min(1., jitter('szVr'))
            brush.angle_jitter = min(180., jitter('angleDynamics') * 360)
            brush.follow_direction = control('angleDynamics') == 6
            brush.roundness_jitter = min(1., jitter('roundnessDynamics'))
            brush.flip_jitter = bool(shape.get('flipX') or shape.get('flipY'))
        else:
            brush.size_pressure = False
        if preset.get('useScatter'):
            brush.scatter = min(4., jitter('scatterDynamics'))
            brush.count = max(1, min(16, int(_number(preset, 'Cnt ', 1.) or 1)))
        if preset.get('usePaintDynamics'):
            # Photoshop builds flow up to the opacity; here the tone follows the opacity level, so
            # either pressure control sets it (flow pressure also slows the build-up).
            if control('opVr') == 2 or control('prVr') == 2:
                minimum = max(_number(preset.get('opVr', {}), 'Mnm ', 0.) or 0., _number(preset.get('prVr', {}), 'Mnm ', 0.) or 0.)
                brush.opacity_pressure = max(.2, 1 - minimum / 100)
            if control('prVr') == 2:
                brush.flow_pressure = max(.2, 1 - (_number(preset.get('prVr', {}), 'Mnm ', 0.) or 0.) / 100) * .5
            brush.opacity_jitter = min(1., jitter('opVr'))
        if preset.get('Wtdg'):
            brush.wet_edges = .55
        if preset.get('Nose'):
            brush.grain, brush.grain_strength = 'paper', .35
        texture = preset.get('Txtr') if isinstance(preset.get('Txtr'), dict) else {}
        if preset.get('useTexture') and texture:
            image = patterns.get(texture.get('Nm  ')) or patterns.get(texture.get('Idnt'))
            if image:
                brush.grain, brush.grain_image = 'custom', image
                brush.grain_strength = min(1., (_number(preset, 'textureDepth', 70.) or 70.) / 100)
                brush.grain_scale = max(.1, min(8., (_number(preset, 'textureScale', 100.) or 100.) / 100))
                brush.grain_invert = bool(preset.get('InvT'))
                contrast = _number(preset, 'textureContrast', 0.) or 0.  # Photoshop: -50 … 100
                brush.grain_contrast = max(.2, min(4., 1 + contrast / 50))
        brushes.append(brush)
    if not brushes:
        for index, tip in enumerate(tips):
            mask = _tip_mask(tip)
            if mask is None:
                continue
            name = tip.name if tip.name and not _uuid_like(tip.name) else f'{stem} {index + 1}'
            brushes.append(Brush(name, min(500, tip.diameter or 30), 1., max(.01, tip.spacing / 100),
                                 tip=png_base64(mask), category=f'Photoshop · {stem}', source={'abr': Path(path).name}))
    if not brushes:
        raise ValueError('Nenhuma ponta compatível encontrada neste ABR.')
    return brushes


# ------------------------------------------------------------------ tips

def _field(size=128):
    grid = np.linspace(-1, 1, size, dtype=np.float32)
    return np.meshgrid(grid, grid, indexing='ij')


def _smooth_noise(rng, shape, sigma):
    from scipy import ndimage
    return ndimage.gaussian_filter(rng.standard_normal(shape), sigma)


TIP_SIZE = 512
TIP_CACHE_PATH = DATA_ROOT / '.studio-cache' / 'tips.json'
_tip_cache = None
_tip_cache_dirty = False


def _tip_cache_version():
    """Changes whenever this file changes, so edited tip recipes are generated again."""
    source = sys.executable if getattr(sys, 'frozen', False) else __file__
    stat = Path(source).stat()
    return f'{TIP_SIZE}-{stat.st_size}-{stat.st_mtime_ns}'


def _cached_tips():
    global _tip_cache
    if _tip_cache is None:
        try:
            value = json.loads(TIP_CACHE_PATH.read_text(encoding='utf-8'))
            _tip_cache = value['tips'] if value.get('version') == _tip_cache_version() else {}
        except (OSError, ValueError, KeyError, TypeError):
            _tip_cache = {}
    return _tip_cache


def save_tip_cache():
    """Generated tips are kept on disk: startup then skips the numeric work (and loading SciPy)."""
    global _tip_cache_dirty
    if not _tip_cache_dirty:
        return
    try:
        TIP_CACHE_PATH.parent.mkdir(exist_ok=True)
        temporary = TIP_CACHE_PATH.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': _tip_cache_version(), 'tips': _cached_tips()}), encoding='utf-8')
        temporary.replace(TIP_CACHE_PATH)
        _tip_cache_dirty = False
    except OSError:
        pass


@lru_cache(maxsize=None)
def generated_tip(kind, seed=7):
    global _tip_cache_dirty
    cache = _cached_tips()
    key = f'{kind}:{seed}'
    if key not in cache:
        cache[key] = _generate_tip(kind, seed)
        _tip_cache_dirty = True
    return cache[key]


def _generate_tip(kind, seed):
    """Procedural tips (512 px, so big brushes stay crisp). Directional tips (bristle, flat, rake, hair)
    vary along the tip's vertical axis, so with "follow direction" the streaks run along the stroke."""
    rng = np.random.default_rng(seed)
    k = TIP_SIZE / 128
    y, x = _field(TIP_SIZE)
    radius = np.sqrt(x * x + y * y)
    angle = np.arctan2(y, x)

    def noise(sigma):
        return _smooth_noise(rng, radius.shape, np.asarray(sigma) * k)

    def bristles(count, half_width, gap=.1, low=.45, length=(.7, 1.), thickness=(.5, 1.3)):
        """Individual hairs across the tip (y), each with its own paint load, thickness and
        length along the stroke (x): mid-stroke they leave streaks, at the ends a frayed edge."""
        result = np.zeros_like(radius)
        rows = np.linspace(-1, 1, TIP_SIZE)
        clump = np.interp(np.linspace(0, 1, count), np.linspace(0, 1, 7), rng.uniform(.65, 1, 7))
        for n, center in enumerate(np.sort(rng.uniform(-.96, .96, count))):
            if rng.uniform() < gap:
                continue
            half = rng.uniform(*thickness) / count
            band = np.flatnonzero(np.abs(rows - center) < half + 2 / TIP_SIZE)
            if not band.size:
                continue
            across = np.clip(1 - np.abs(rows[band] - center) / half, 0, 1)[:, None] ** .7
            reach = half_width * rng.uniform(*length) * np.sqrt(max(0., 1 - center * center * .55))
            along = np.clip((reach - np.abs(x[band] - rng.uniform(-.06, .06))) / .07, 0, 1)
            load = rng.uniform(low, 1) * clump[n]
            result[band] = np.maximum(result[band], across * along * load)
        # Paint sits unevenly on the hairs, but each hair stays continuous along the stroke.
        return result * np.clip(.9 + noise((.8, 8)) * 4, .6, 1)

    def dots(count, low, high, spread=.8):
        result = np.zeros_like(radius)
        for _ in range(count):
            cx, cy = rng.uniform(-spread, spread, 2)
            r = rng.uniform(low, high)
            result = np.maximum(result, np.clip((r - np.sqrt((x - cx) ** 2 + (y - cy) ** 2)) / .02, 0, 1))
        return result

    if kind == 'pencil':
        # Graphite point: a soft-edged core made of fine particles, denser in the middle.
        particles = np.clip(.5 + noise(.35) * 9, 0, 1)
        core = np.clip((1 - radius) / .45, 0, 1) ** .8
        alpha = core * (.45 + .55 * particles) * np.clip((.97 - radius) / .05, 0, 1)
    elif kind == 'bristle':
        alpha = bristles(36, .5, gap=.05, low=.65, thickness=(1.7, 2.8))
    elif kind == 'dry':
        alpha = bristles(30, .45, gap=.25, low=.5, length=(.45, 1.), thickness=(1.2, 2.2))
    elif kind == 'flat':
        alpha = bristles(44, .26, gap=.03, low=.7, length=(.85, 1.), thickness=(1.8, 2.8))
        alpha *= np.clip((1 - np.abs(y)) / .05, 0, 1)
    elif kind == 'rake':
        teeth = np.clip(1 - np.abs(((y + 1) * 3.5) % 1 - .5) / .2, 0, 1) ** .6
        alpha = bristles(40, .24, gap=.04, low=.75, length=(.8, 1.), thickness=(1., 1.8)) * teeth
    elif kind == 'hair':
        alpha = bristles(18, .2, gap=.08, low=.5, length=(.75, 1.), thickness=(.5, .9))
    elif kind == 'chalk':
        edge = .78 + .12 * np.sin(angle * 7 + 1.3) + noise(6) * .3
        alpha = np.clip((edge - radius) / .1, 0, 1) * np.clip(.5 + noise(1.2) * 4, 0, 1)
    elif kind == 'charcoal':
        streaks = np.clip(.55 + noise((.6, 9)) * 7, 0, 1)
        body = np.clip((1 - np.sqrt((x / .9) ** 2 + (y / .45) ** 2)) / .2, 0, 1)
        alpha = body * streaks
    elif kind == 'watercolor':
        edge = .8 + .1 * np.sin(angle * 5) + noise(8) * 2.5
        # A wash has a defined, irregular edge (where the wet edge pools) and an uneven body.
        alpha = np.clip((edge - radius) / .1, 0, 1) * np.clip(.8 + noise(5) * 3, .45, 1)
    elif kind == 'splatter':
        alpha = dots(26, .03, .14) * (radius < 1)
    elif kind == 'spray':
        from scipy import ndimage
        density = np.clip(1 - radius, 0, 1) ** 1.5
        specks = (rng.uniform(0, 1, radius.shape) < density * .22) * rng.uniform(.4, 1, radius.shape)
        alpha = ndimage.gaussian_filter(specks.astype(np.float32), .5 * k)
        alpha = alpha / max(1e-6, alpha.max())
    elif kind == 'stipple':
        alpha = dots(14, .04, .09, .75) * (radius < 1)
    elif kind == 'sponge':
        holes = noise(2.2)
        holes = (holes - holes.min()) / max(1e-6, np.ptp(holes))
        edge = .85 + noise(10) * 2
        alpha = np.clip((edge - radius) / .12, 0, 1) * np.clip((holes - .42) / .12, 0, 1)
    elif kind == 'cloud':
        blobs = np.zeros_like(radius)
        for _ in range(9):
            cx, cy = rng.uniform(-.45, .45), rng.uniform(-.3, .25)
            r = rng.uniform(.25, .45)
            blobs = np.maximum(blobs, np.clip((r - np.sqrt((x - cx) ** 2 + (y - cy) ** 2)) / .25, 0, 1))
        alpha = blobs * np.clip(.7 + noise(4) * 4, .35, 1) * np.clip((1 - radius) / .2, 0, 1)
    elif kind == 'leaf':
        width = .42 * np.sqrt(np.clip(1 - y * y, 0, 1)) * (1 - .25 * y)
        alpha = np.clip((width - np.abs(x)) / .05, 0, 1) * (np.abs(y) < .98)
        alpha = alpha * (1 - .45 * np.clip(1 - np.abs(x) / .025, 0, 1) * (y > -.9))
    elif kind == 'grass':
        alpha = np.zeros_like(radius)
        for _ in range(7):
            base, height = rng.uniform(-.6, .6), rng.uniform(.9, 1.8)
            lean = rng.uniform(-.35, .35)
            t = np.clip((1 - y) / height, 0, 1)
            center = base + lean * t * t
            half = .07 * (1 - t)
            blade = np.clip((half - np.abs(x - center)) / .025, 0, 1) * (t < 1)
            alpha = np.maximum(alpha, blade)
    elif kind == 'sparkle':
        vertical = np.clip(1 - np.abs(x) / (.05 * (1 - np.abs(y)) + .004), 0, 1) * (np.abs(y) < 1)
        horizontal = np.clip(1 - np.abs(y) / (.05 * (1 - np.abs(x)) + .004), 0, 1) * (np.abs(x) < 1)
        diagonal = np.clip(1 - np.abs(np.abs(x) - np.abs(y)) / (.035 * np.clip(1 - radius / .55, 0, 1) + .002), 0, 1)
        diagonal = diagonal * (radius < .55)
        alpha = np.maximum(np.maximum(np.maximum(vertical, horizontal), diagonal * .8),
                           np.clip((.16 - radius) / .12, 0, 1))
    else:
        raise ValueError(kind)
    return png_base64(Image.fromarray((np.clip(alpha, 0, 1) * 255).astype('uint8')))


TIP_KINDS = [('Redonda (dureza)', ''), ('Lápis', 'pencil'), ('Cerdas', 'bristle'), ('Cerdas secas', 'dry'),
             ('Pincel chato', 'flat'), ('Ancinho', 'rake'), ('Fios de cabelo', 'hair'), ('Giz', 'chalk'),
             ('Carvão', 'charcoal'), ('Aquarela', 'watercolor'), ('Respingos', 'splatter'), ('Spray', 'spray'),
             ('Pontilhado', 'stipple'), ('Esponja', 'sponge'), ('Nuvem', 'cloud'), ('Folha', 'leaf'),
             ('Grama', 'grass'), ('Brilho', 'sparkle')]


def builtin_brushes():
    brushes = _builtin_brushes()
    save_tip_cache()
    return brushes


def _builtin_brushes():
    tip = generated_tip

    def make(category, name, size, **values):
        return Brush(name, size, category=category, **values)

    return [
        make('Básicos', 'Redondo sólido', 5),
        make('Básicos', 'Redondo suave', 40, hardness=.15, spacing=.08),
        make('Básicos', 'Aerógrafo', 80, hardness=0., spacing=.05, flow=.08, opacity_pressure=1.),
        make('Lápis', 'Lápis HB', 4, tip=tip('pencil'), spacing=.08, flow=.75, opacity_pressure=.8, angle_jitter=180,
             grain='paper', grain_strength=.55),
        make('Lápis', 'Lápis 6B macio', 8, tip=tip('pencil', 3), spacing=.07, flow=.9, opacity_pressure=.7,
             angle_jitter=180, grain='paper', grain_strength=.45, grain_scale=1.3),
        make('Lápis', 'Lapiseira 0,5', 2, hardness=.9, spacing=.06, flow=.85, opacity_pressure=.6, grain='paper',
             grain_strength=.3),
        make('Lápis', 'Lápis de cor', 7, tip=tip('pencil', 5), spacing=.07, flow=.7, opacity_pressure=.75,
             angle_jitter=180, grain='rough', grain_strength=.6),
        make('Canetas', 'Caneta nanquim', 4, spacing=.05),
        make('Canetas', 'Caneta pincel', 10, hardness=.95, spacing=.04, roundness=.8, angle=30.),
        make('Canetas', 'Marcador', 20, spacing=.08, angle=35., roundness=.35, flow=.9, opacity_pressure=.2),
        make('Pincéis', 'Pincel de tinta', 24, hardness=.75, spacing=.05, flow=.85, opacity_pressure=.35),
        make('Pincéis', 'Pincel redondo de cerdas', 26, tip=tip('bristle'), spacing=.04, flow=.8, opacity_pressure=.4,
             follow_direction=True, grain='canvas', grain_strength=.25, depletion=.08),
        make('Pincéis', 'Pincel chato', 34, tip=tip('flat'), spacing=.03, flow=.85, opacity_pressure=.35,
             follow_direction=True, size_pressure=False, grain='canvas', grain_strength=.2, depletion=.06),
        make('Pincéis', 'Pincel seco', 32, tip=tip('dry', 9), spacing=.04, flow=.85, jitter=.1, opacity_pressure=.45,
             follow_direction=True, grain='rough', grain_strength=.6, depletion=.15),
        make('Pincéis', 'Óleo / acrílica', 36, tip=tip('bristle', 13), spacing=.03, flow=.95, opacity_pressure=.25,
             follow_direction=True, grain='canvas', grain_strength=.3, depletion=.05),
        make('Aquarela', 'Aquarela', 40, tip=tip('watercolor'), spacing=.05, flow=.35, jitter=.1, opacity_pressure=.5,
             angle_jitter=180, wet_edges=.7, grain='watercolor', grain_strength=.4),
        make('Aquarela', 'Aquarela lavada', 90, hardness=.1, spacing=.05, flow=.18, opacity_pressure=.6,
             wet_edges=.55, grain='watercolor', grain_strength=.3, grain_scale=1.6),
        make('Aquarela', 'Aquarela seca', 30, tip=tip('watercolor', 17), spacing=.05, flow=.5, angle_jitter=180,
             wet_edges=.35, grain='rough', grain_strength=.55),
        make('Secos', 'Giz pastel', 28, tip=tip('chalk'), spacing=.06, flow=.85, angle_jitter=180, opacity_pressure=.5,
             grain='rough', grain_strength=.7, grain_scale=1.3),
        make('Secos', 'Giz de cera', 14, hardness=.9, spacing=.05, flow=.95, opacity_pressure=.4,
             grain='paper', grain_strength=.75, grain_scale=.8),
        make('Secos', 'Carvão', 22, tip=tip('charcoal'), spacing=.05, flow=.8, angle_jitter=25, opacity_pressure=.55,
             grain='charcoal', grain_strength=.65),
        make('Secos', 'Carvão macio (esfuminho)', 40, hardness=.2, spacing=.05, flow=.45, opacity_pressure=.6,
             grain='charcoal', grain_strength=.5, grain_scale=1.5),
        make('Efeitos', 'Textura dispersa', 18, hardness=.65, spacing=.3, scatter=.7, jitter=.4),
        make('Efeitos', 'Respingos', 40, tip=tip('splatter'), spacing=.6, scatter=.8, jitter=.5, angle_jitter=180,
             size_pressure=False),
        make('Básicos', 'Pintura digital', 30, hardness=.85, spacing=.05, flow=.8, opacity_pressure=.7),
        make('Básicos', 'Sombreado suave', 60, hardness=.05, spacing=.06, flow=.12, opacity_pressure=1.,
             size_pressure=False),
        make('Lápis', 'Lápis de esboço 2H', 3, tip=tip('pencil', 11), spacing=.07, flow=.5, opacity_pressure=.9,
             angle_jitter=180, grain='paper', grain_strength=.6),
        make('Canetas', 'Pena G (mangá)', 6, hardness=.98, spacing=.03),
        make('Canetas', 'Caneta técnica', 3, spacing=.04, size_pressure=False),
        make('Canetas', 'Caneta caligráfica', 18, hardness=.97, spacing=.03, angle=45., roundness=.22),
        make('Pincéis', 'Pincel ancinho', 34, tip=tip('rake'), spacing=.03, flow=.85, opacity_pressure=.35,
             follow_direction=True, depletion=.08),
        make('Pincéis', 'Fios de cabelo', 22, tip=tip('hair'), spacing=.03, flow=.75, opacity_pressure=.5,
             follow_direction=True),
        make('Pincéis', 'Mistura suave', 40, tip=tip('bristle', 21), spacing=.04, flow=.25, opacity_pressure=.8,
             follow_direction=True, wet_edges=.15),
        make('Natureza', 'Folhagem', 36, tip=tip('leaf'), spacing=.45, scatter=.9, jitter=.4, angle_jitter=180),
        make('Natureza', 'Grama', 40, tip=tip('grass'), spacing=.22, scatter=.35, jitter=.3, angle_jitter=10,
             size_pressure=False),
        make('Natureza', 'Nuvens', 90, tip=tip('cloud'), spacing=.12, scatter=.3, jitter=.3, flow=.3,
             angle_jitter=180, opacity_pressure=.6),
        make('Natureza', 'Esponja (textura de folhas)', 50, tip=tip('sponge'), spacing=.25, angle_jitter=180,
             flow=.75, jitter=.2),
        make('Efeitos', 'Spray / grafite', 70, tip=tip('spray'), spacing=.08, flow=.5, angle_jitter=180,
             opacity_pressure=.7, size_pressure=False),
        make('Efeitos', 'Pontilhismo', 24, tip=tip('stipple'), spacing=.5, scatter=.6, angle_jitter=180, jitter=.3),
        make('Efeitos', 'Brilhos', 30, tip=tip('sparkle'), spacing=.8, scatter=1.3, jitter=.5, angle_jitter=20,
             size_pressure=False),
        make('Efeitos', 'Estrelas (céu noturno)', 4, hardness=.85, spacing=1.6, scatter=3.5, jitter=.8,
             size_pressure=False),
    ]


TOOL_PRESETS = {'brush': 'Redondo sólido', 'pencil': 'Lápis HB', 'pen': 'Caneta nanquim'}

SHARE_PREFIX = 'STUDIO-PINCEL:'


def share_code(brushes):
    """Compact text that can be pasted in a chat or e-mail to share brushes."""
    payload = json.dumps({'version': 1, 'brushes': [b.to_dict() for b in brushes]}, ensure_ascii=False)
    return SHARE_PREFIX + base64.b64encode(zlib.compress(payload.encode('utf-8'), 9)).decode('ascii')


def brushes_from_code(text):
    text = ''.join(text.split())
    if not text.startswith(SHARE_PREFIX):
        raise ValueError('O texto não é um código de pincel do Studio Desenho.')
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(base64.b64decode(text[len(SHARE_PREFIX):]), 64_000_000)
        value = json.loads(raw.decode('utf-8'))
    except (ValueError, zlib.error) as error:
        raise ValueError('Código de pincel corrompido ou incompleto.') from error
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('brushes'), list):
        raise ValueError('Código de pincel incompatível.')
    return [Brush.from_dict(item) for item in value['brushes'][:200]]


def _hex(r, g, b):
    return QColor(max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b)))).name()


def _cmyk(c, m, y, k):
    return _hex(255 * (1 - c) * (1 - k), 255 * (1 - m) * (1 - k), 255 * (1 - y) * (1 - k))


def parse_aco(data):
    """Photoshop color swatches (.aco), versions 1 and 2."""
    import struct
    version, count = struct.unpack_from('>HH', data, 0)
    if version not in (1, 2):
        raise ValueError('Arquivo ACO inválido.')
    offset, colors = 4, []
    for _ in range(count):
        space, w, x, y, z = struct.unpack_from('>HHHHH', data, offset)
        offset += 10
        if version == 2:
            length = struct.unpack_from('>I', data, offset)[0]
            offset += 4 + length * 2
        if space == 0:
            colors.append(_hex(w / 257, x / 257, y / 257))
        elif space == 1:
            colors.append(QColor.fromHsvF(w / 65536, x / 65535, y / 65535).name())
        elif space == 2:
            colors.append(_cmyk(1 - w / 65535, 1 - x / 65535, 1 - y / 65535, 1 - z / 65535))
        elif space == 8:
            colors.append(_hex(*(w / 10000 * 255,) * 3))
    return colors


def parse_ase(data):
    """Adobe Swatch Exchange (.ase)."""
    import struct
    if data[:4] != b'ASEF':
        raise ValueError('Arquivo ASE inválido.')
    count = struct.unpack_from('>I', data, 8)[0]
    offset, colors = 12, []
    for _ in range(count):
        kind, length = struct.unpack_from('>HI', data, offset)
        block = offset + 6
        offset = block + length
        if kind != 1:
            continue
        name_length = struct.unpack_from('>H', data, block)[0]
        position = block + 2 + name_length * 2
        model = data[position:position + 4].decode('ascii', errors='replace')
        position += 4
        if model == 'RGB ':
            colors.append(_hex(*(v * 255 for v in struct.unpack_from('>3f', data, position))))
        elif model == 'CMYK':
            colors.append(_cmyk(*struct.unpack_from('>4f', data, position)))
        elif model == 'Gray':
            colors.append(_hex(*(struct.unpack_from('>f', data, position)[0] * 255,) * 3))
        elif model == 'LAB ':
            lightness, a, b = struct.unpack_from('>3f', data, position)
            colors.append(_lab(lightness * 100, a, b))
    return colors


def _lab(lightness, a, b):
    y = (lightness + 16) / 116
    x, z = y + a / 500, y - b / 200
    def f(t):
        return t ** 3 if t ** 3 > .008856 else (t - 16 / 116) / 7.787
    x, y, z = .95047 * f(x), f(y), 1.08883 * f(z)
    rgb = [x * 3.2406 + y * -1.5372 + z * -.4986, x * -.9689 + y * 1.8758 + z * .0415, x * .0557 + y * -.2040 + z * 1.0570]
    rgb = [1.055 * v ** (1 / 2.4) - .055 if v > .0031308 else 12.92 * v for v in (max(0., v) for v in rgb)]
    return _hex(*(v * 255 for v in rgb))


def parse_palette(path):
    """Returns (name, colors) from JSON, GIMP/Krita/Aseprite GPL, Lospec HEX, Paint.NET TXT, ACO or ASE."""
    path = Path(path)
    suffix = path.suffix.lower()
    name = path.stem
    if suffix == '.aco':
        colors = parse_aco(path.read_bytes())
    elif suffix == '.ase':
        colors = parse_ase(path.read_bytes())
    else:
        text = path.read_text(encoding='utf-8-sig', errors='replace')
        if suffix == '.json':
            value = json.loads(text)
            name, colors = value.get('name', name), value.get('colors', [])
        elif suffix == '.gpl':
            colors = []
            for line in text.splitlines():
                line = line.strip()
                if line.lower().startswith('name:'):
                    name = line.split(':', 1)[1].strip() or name
                    continue
                parts = line.split()
                if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                    colors.append(_hex(*map(int, parts[:3])))
        else:
            colors = []
            for line in text.splitlines():
                line = line.split(';')[0].strip().lstrip('#')
                if len(line) == 8:
                    line = line[2:]
                if len(line) == 6:
                    colors.append('#' + line.lower())
    colors = [QColor(c).name() for c in colors if QColor(c).isValid()][:256]
    if not colors:
        raise ValueError('Nenhuma cor encontrada nesse arquivo.')
    return name, colors


def write_palette(path, name, colors):
    path = Path(path)
    if path.suffix.lower() == '.gpl':
        rows = [f'{QColor(c).red():3d} {QColor(c).green():3d} {QColor(c).blue():3d}\t{c}' for c in colors]
        path.write_text('GIMP Palette\nName: ' + name + '\nColumns: 8\n#\n' + '\n'.join(rows) + '\n', encoding='utf-8')
    elif path.suffix.lower() == '.hex':
        path.write_text('\n'.join(c.lstrip('#') for c in colors) + '\n', encoding='utf-8')
    else:
        path.write_text(json.dumps({'name': name, 'colors': colors}, ensure_ascii=False), encoding='utf-8')


class ResourceLibrary:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.brushes = builtin_brushes()
        self.builtin_count = len(self.brushes)
        self.palettes = {name: list(colors) for name, colors in DEFAULT_PALETTES.items()}
        self.hidden_palettes = []
        self.poses = {}
        if self.path and self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self.brushes.extend(Brush.from_dict(v) for v in value.get('brushes', []))
            self.hidden_palettes = [n for n in value.get('hidden_palettes', []) if isinstance(n, str)]
            self.poses = {name: item for name, item in value.get('poses', {}).items()
                          if isinstance(item, dict) and isinstance(item.get('pose'), dict)}
            for name in self.hidden_palettes:
                self.palettes.pop(name, None)
            for name, colors in value.get('palettes', {}).items():
                if colors and all(QColor(c).isValid() for c in colors):
                    self.palettes[name] = colors

    def preset(self, tool):
        name = TOOL_PRESETS.get(tool, TOOL_PRESETS['brush'])
        return next((b for b in self.brushes if b.name == name), self.brushes[0])

    def save(self):
        if self.path:
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'brushes': [asdict(b) for b in self.brushes[self.builtin_count:]],
                'palettes': self.palettes, 'hidden_palettes': self.hidden_palettes, 'poses': self.poses},
                ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)

    def unique_palette_name(self, name):
        name, base, number = name.strip() or 'Paleta', name.strip() or 'Paleta', 2
        while name in self.palettes:
            name = f'{base} ({number})'
            number += 1
        return name

    def import_palette(self, path):
        name, colors = parse_palette(path)
        name = self.unique_palette_name(name)
        self.palettes[name] = colors
        self.save()
        return name

    def delete_palette(self, name):
        self.palettes.pop(name, None)
        if name in DEFAULT_PALETTES and name not in self.hidden_palettes:
            self.hidden_palettes.append(name)
        self.save()

    def restore_default_palettes(self):
        self.hidden_palettes = []
        for name, colors in DEFAULT_PALETTES.items():
            self.palettes.setdefault(name, list(colors))
        self.save()

    def delete_brush(self, index):
        if index < self.builtin_count:
            raise ValueError('Os pincéis padrão não podem ser excluídos; crie uma cópia para personalizar.')
        self.brushes.pop(index)
        self.save()

    def import_brushes(self, path):
        if str(path).lower().endswith('.abr'):
            brushes = load_abr(path)
        else:
            value = json.loads(Path(path).read_text(encoding='utf-8'))
            if value.get('version') != 1:
                raise ValueError('Biblioteca de pincéis incompatível.')
            brushes = [Brush.from_dict(item) for item in value['brushes']]
        return self.add_brushes(brushes)

    def import_code(self, text):
        return self.add_brushes(brushes_from_code(text))

    def add_brushes(self, brushes):
        names = {b.name for b in self.brushes}
        for brush in brushes:
            base, number = brush.name, 2
            while brush.name in names:
                brush.name = f'{base} ({number})'
                number += 1
            names.add(brush.name)
        self.brushes.extend(brushes)
        self.save()
        return brushes

    def export_brushes(self, path, brushes):
        Path(path).write_text(json.dumps({'version': 1, 'brushes': [b.to_dict() for b in brushes]}, ensure_ascii=False), encoding='utf-8')
