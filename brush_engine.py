"""Dab-based brush engine: tip stamping, paper grain, wet edges and previews.

A stroke is stamped as coverage into a 16-bit grey buffer. Each dab pulls the coverage
towards its own level (tip value × pressure opacity) at the rate of the flow, like Krita's
"alpha darken": going over the same place in one stroke never darkens past the pressure,
light pressure gives a light line, and the streaks of a bristle tip stay visible instead of
filling in. Before it is composited, `finish_alpha` applies effects that depend on the whole
stroke: watercolour wet edges and the paper grain (tiled in canvas space, so it stays still
while you draw).
"""
import base64
import io
import math
import random
import threading
from collections import OrderedDict
from functools import lru_cache

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QRadialGradient, QTransform

FORMAT = QImage.Format.Format_ARGB32_Premultiplied
COVERAGE = QImage.Format.Format_Grayscale16
INK = QColor('white')  # what dabs paint into a coverage buffer: white = fully covered
GRAIN_SIZE = 512

GRAINS = [('Sem textura', ''), ('Papel', 'paper'), ('Papel áspero', 'rough'), ('Tela de pintura', 'canvas'),
          ('Carvão', 'charcoal'), ('Aquarela', 'watercolor'), ('Papel kraft', 'kraft'),
          ('Papel pastel (colmeia)', 'pastel'), ('Linho', 'linen'), ('Juta', 'burlap'), ('Concreto', 'concrete'),
          ('Madeira', 'wood'), ('Areia', 'sand'), ('Esponja', 'sponge'), ('Ruído fino', 'noise'),
          ('Hachura', 'crosshatch'), ('Retícula (mangá)', 'halftone'), ('Imagem própria', 'custom')]


# ---------------------------------------------------------------- textures

def _periodic_blur(noise, sigma_x, sigma_y=None, angle=0.):
    """Gaussian blur in the frequency domain: the result tiles seamlessly. Two sigmas and an
    angle smear the noise into fibres running in that direction."""
    sigma_y = sigma_x if sigma_y is None else sigma_y
    fy = np.fft.fftfreq(noise.shape[0])[:, None]
    fx = np.fft.fftfreq(noise.shape[1])[None, :]
    cos, sin = math.cos(angle), math.sin(angle)
    u, v = fx * cos + fy * sin, fy * cos - fx * sin
    kernel = np.exp(-2 * math.pi ** 2 * ((u * sigma_x) ** 2 + (v * sigma_y) ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(noise) * kernel))


def _normalize(values):
    low, high = np.percentile(values, 1), np.percentile(values, 99)
    return np.clip((values - low) / max(1e-6, high - low), 0, 1).astype(np.float32)


def _weave(blur_noise, x, y, size, threads, wobble, gap=0.):
    """Plain weave: threads alternate over and under, each a rounded ridge that wavers a little;
    `gap` opens dark holes between the threads, as in coarse burlap."""
    period = size / threads
    shift = blur_noise * wobble
    u, v = x + shift, y - shift
    across_v, across_h = np.sin(math.pi * (u % period) / period), np.sin(math.pi * (v % period) / period)
    over = (np.floor(u / period) + np.floor(v / period)) % 2
    threads = np.where(over > 0, across_v * (.55 + .45 * across_h), across_h * (.55 + .45 * across_v))
    return np.clip((threads - gap) / (1 - gap), 0, 1) if gap else threads


@lru_cache(maxsize=32)
def grain_texture(kind, size=GRAIN_SIZE):
    """Tileable paper height in 0–1 (1 = paper top that catches pigment)."""
    rng = np.random.default_rng(_SEEDS.get(kind, 7))
    noise = lambda: rng.standard_normal((size, size))
    blur = lambda *args: _normalize(_periodic_blur(noise(), *args))
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    if kind == 'paper':
        # Drawing paper: fine tooth, gentle undulation and a few pressed-in fibres.
        fibres = sum(blur(9, .7, angle) for angle in rng.uniform(0, math.pi, 4)) / 4
        value = .55 * blur(.8) + .25 * blur(2.6) + .2 * _normalize(fibres)
    elif kind == 'rough':
        # Cold-pressed pastel paper: rounded bumps with fine tooth on top.
        value = (.4 * blur(1.1) + .6 * blur(4.5)) ** 1.5
    elif kind == 'canvas':
        value = .6 * _weave(_periodic_blur(noise(), 10), x, y, size, 64, 14) + .25 * blur(1.) + .15 * blur(5)
    elif kind == 'charcoal':
        # Laid charcoal paper: horizontal laid lines, streaky fibres and fine tooth.
        laid = .5 + .5 * np.sin(y * 2 * math.pi * 48 / size + _periodic_blur(noise(), 8) * 4)
        value = (.3 * laid + .4 * blur(7, .6) + .3 * blur(1.)) ** 1.3
    elif kind == 'watercolor':
        # Cold-pressed watercolour paper: broad soft hills, medium bumps and fine felt.
        value = .5 * blur(12) + .3 * blur(3) + .2 * blur(.8)
    elif kind == 'kraft':
        # Kraft paper: long unbleached fibres in every direction over a blotchy pulp.
        fibres = sum(blur(18, .8, angle) for angle in rng.uniform(0, math.pi, 7)) / 7
        value = .45 * _normalize(fibres) + .3 * blur(1.4) + .25 * blur(16)
    elif kind == 'pastel':
        # Honeycomb pastel paper (Mi-Teintes style): a network of rounded ridges around pits.
        ridges = 1 - np.abs(blur(3.2) * 2 - 1)
        value = .7 * ridges ** 1.6 + .3 * blur(.9)
    elif kind == 'linen':
        # Fine linen: a dense, irregular weave with slubs (thicker stretches of thread).
        slubs = blur(14, 2) * .5 + .5
        value = .65 * _weave(_periodic_blur(noise(), 6), x, y, size, 128, 10) * slubs + .35 * blur(.8)
    elif kind == 'burlap':
        # Burlap (jute): a coarse weave with open holes and hairy threads.
        value = .75 * _weave(_periodic_blur(noise(), 14), x, y, size, 24, 24, gap=.25) + .25 * blur(1.2, 4)
    elif kind == 'concrete':
        # Concrete / plaster: stains, sand, and sharp little air holes.
        pits = np.clip((blur(1.4) - .82) / .1, 0, 1)
        value = (.35 * blur(10) + .25 * blur(3) + .4 * blur(.7)) * (1 - .8 * pits)
    elif kind == 'wood':
        # Wood grain: rings bent by knots, crossed by fine pores along the fibre.
        bend = _periodic_blur(noise(), 40) * 260 + _periodic_blur(noise(), 9) * 18
        rings = .5 + .5 * np.sin(2 * math.pi * 24 * y / size + bend)
        value = .55 * rings ** 2 + .3 * blur(20, .7) + .15 * blur(.8)
    elif kind == 'sand':
        # Sand / gritty ground: tightly packed rounded grains.
        value = blur(1.1) ** 2 * .75 + .25 * blur(5)
    elif kind == 'sponge':
        # Natural sponge print: blobs with holes of every size.
        value = np.clip((.6 * blur(5) + .4 * blur(1.8) - .38) / .3, 0, 1)
    elif kind == 'noise':
        # Fine digital grain, even at every scale.
        value = blur(.55)
    elif kind == 'crosshatch':
        # Pen hatching in two directions; light pressure leaves single lines, more fills the cross.
        lines = 32
        first = .5 + .5 * np.cos(2 * math.pi * lines * (x + y) / size)
        second = .5 + .5 * np.cos(2 * math.pi * lines * (x - y) / size)
        value = .55 * first ** 3 + .35 * second ** 3 + .1 * blur(1.)
    elif kind == 'halftone':
        # Manga screentone at 45°: dots grow with pressure, the way printed tones do.
        lines = 40
        value = (np.cos(2 * math.pi * lines * (x + y) / size) + np.cos(2 * math.pi * lines * (x - y) / size)) / 4 + .5
        return value.astype(np.float32)
    else:
        return np.ones((size, size), np.float32)
    return _normalize(value)


_SEEDS = {'paper': 11, 'rough': 23, 'canvas': 37, 'charcoal': 41, 'watercolor': 53, 'kraft': 59, 'pastel': 61,
          'linen': 67, 'burlap': 71, 'concrete': 73, 'wood': 79, 'sand': 83, 'sponge': 89, 'noise': 97,
          'crosshatch': 101, 'halftone': 103}


@lru_cache(maxsize=8)
def _custom_grain(encoded):
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert('L')
    image.thumbnail((512, 512))
    return _normalize(np.asarray(image, np.float32))


def texture_for(brush):
    if brush.grain == 'custom':
        return _custom_grain(brush.grain_image) if brush.grain_image else None
    return grain_texture(brush.grain) if brush.grain else None


def grain_patch(texture, x, y, width, height, scale=1.):
    """The texture under a canvas area, sampled bilinearly so scaled grain stays smooth."""
    scale = max(.1, float(scale))
    rows, cols = texture.shape
    v = np.arange(y, y + height) / scale
    u = np.arange(x, x + width) / scale
    if scale == 1.:
        return texture[np.ix_(v.astype(np.int64) % rows, u.astype(np.int64) % cols)]
    v0, u0 = np.floor(v), np.floor(u)
    fv = (v - v0).astype(np.float32)[:, None]
    fu = (u - u0).astype(np.float32)[None, :]
    r0, c0 = v0.astype(np.int64) % rows, u0.astype(np.int64) % cols
    r1, c1 = (r0 + 1) % rows, (c0 + 1) % cols
    top = texture[np.ix_(r0, c0)] * (1 - fu) + texture[np.ix_(r0, c1)] * fu
    bottom = texture[np.ix_(r1, c0)] * (1 - fu) + texture[np.ix_(r1, c1)] * fu
    return top * (1 - fv) + bottom * fv


def deposit(alpha, tooth, strength):
    """Pigment catches the paper's peaks first; more coverage (pressure) reaches into the valleys.
    Strength is how deep the valleys are: strong grain leaves the deepest ones bare even when
    pressing hard, as chalk and crayon do."""
    valley = (1 - tooth) * (strength * 1.3)
    return alpha * np.clip((alpha * .95 - valley) / .22 + 1, 0, 1)


def wet_radius(brush, size):
    return 0 if brush is None or brush.wet_edges <= 0 else int(math.ceil(max(1.5, min(14., size * .12)) * 3))


def finish_alpha(alpha, x, y, brush, size):
    """Stroke-level effects on coverage (0–1) of a patch whose top-left is (x, y)."""
    if brush is None:
        return alpha
    if brush.wet_edges > 0:
        from scipy import ndimage
        sigma = max(1.5, min(14., size * .12))
        blurred = ndimage.gaussian_filter(alpha, sigma, mode='constant')
        edge = np.clip(alpha - blurred, 0, 1)
        alpha = np.clip(alpha * (1 - .45 * brush.wet_edges) + edge * 2.4 * brush.wet_edges, 0, 1)
    texture = texture_for(brush)
    if texture is not None and brush.grain_strength > 0:
        tooth = grain_patch(texture, x, y, alpha.shape[1], alpha.shape[0], brush.grain_scale)
        if brush.grain_invert:
            tooth = 1 - tooth
        if brush.grain_contrast != 1:
            tooth = np.clip((tooth - .5) * brush.grain_contrast + .5, 0, 1)
        alpha = deposit(alpha, tooth, brush.grain_strength)
    return alpha.astype(np.float32, copy=False)


def has_effects(brush):
    return brush is not None and (brush.wet_edges > 0 or (brush.grain and brush.grain_strength > 0))


def warm_up():
    """Load SciPy and build the paper textures in the background, so the first textured or
    watercolour stroke does not stall the pen."""
    def work():
        try:
            from scipy import ndimage  # noqa: F401
            for _, kind in GRAINS:
                if kind not in ('', 'custom'):
                    grain_texture(kind)
        except Exception:  # only a head start; the stroke builds what it needs anyway
            pass
    threading.Thread(target=work, name='brush-warm-up', daemon=True).start()


# ---------------------------------------------------------------- coverage

def coverage_buffer(width, height):
    image = QImage(width, height, COVERAGE)
    if image.isNull():
        raise ValueError('Não foi possível criar a tela nesse tamanho.')
    image.fill(QColor('black'))
    return image


def alpha_of(image):
    """Coverage 0–1: the grey value of a coverage buffer, otherwise the alpha channel."""
    raw = image.constBits().asstring(image.sizeInBytes())
    if image.format() == COVERAGE:
        data = np.frombuffer(raw, np.uint16).reshape(image.height(), image.bytesPerLine() // 2)
        return data[:, :image.width()].astype(np.float32) / 65535
    data = np.frombuffer(raw, np.uint8)
    return data.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), 3].astype(np.float32) / 255


def solid(color, alpha):
    """Premultiplied image of one colour with the given coverage."""
    height, width = alpha.shape
    data = np.empty((height, width, 4), np.float32)
    data[..., 0], data[..., 1], data[..., 2] = color.blueF(), color.greenF(), color.redF()
    data[..., :3] *= alpha[..., None]
    data[..., 3] = alpha
    buffer = np.round(data * 255).astype(np.uint8).tobytes()
    return QImage(buffer, width, height, width * 4, FORMAT).copy()


def colorize(color, coverage, region=None):
    """Premultiplied image of `color` whose alpha is the coverage buffer (in `region`)."""
    mask = (coverage.copy(region) if region is not None else coverage).convertToFormat(QImage.Format.Format_Grayscale8)
    mask.reinterpretAsFormat(QImage.Format.Format_Alpha8)
    patch = QImage(mask.size(), FORMAT)
    patch.fill(color)
    painter = QPainter(patch)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return patch


# ---------------------------------------------------------------- tips

def tip_key(brush):
    return brush.tip or ('round', round(brush.hardness, 4), round(brush.roundness, 4))


_tips = {}
_scaled = OrderedDict()
_scaled_bytes = 0
SCALED_BUDGET = 96 << 20


def tip_image(brush):
    """The tip as an opaque grey image (value = coverage), shared by every stroke."""
    key = tip_key(brush)
    image = _tips.get(key)
    if image is None:
        if len(_tips) > 32:
            _tips.clear()
        mask = np.asarray(brush.mask(), np.uint8)
        if brush.tip:
            # Image tips are textures drawn as levels, not as build-up: lift their mid-tones so
            # loaded hairs and grains read as paint (ease-out keeps the empty parts empty).
            mask = (255 - (255 - mask.astype(np.float32)) ** 2 / 255).round().astype(np.uint8)
        pixels = np.empty((*mask.shape, 4), np.uint8)
        pixels[..., :3] = mask[..., None]
        pixels[..., 3] = 255
        image = QImage(pixels.tobytes(), mask.shape[1], mask.shape[0], mask.shape[1] * 4,
                       QImage.Format.Format_RGB32).copy()
        _tips[key] = image
    return image


def scaled_tip(tip, key, width, height):
    """Area-averaged copies of tips, kept across strokes within a memory budget."""
    global _scaled_bytes
    entry = (key, width, height)
    image = _scaled.get(entry)
    if image is not None:
        _scaled.move_to_end(entry)
        return image
    image = tip.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    _scaled[entry] = image
    _scaled_bytes += image.sizeInBytes()
    while _scaled_bytes > SCALED_BUDGET and len(_scaled) > 1:
        _, old = _scaled.popitem(last=False)
        _scaled_bytes -= old.sizeInBytes()
    return image


# ---------------------------------------------------------------- stamping

class StampStroke:
    def __init__(self, brush, color=None):
        self.brush = brush
        self.key = tip_key(brush)
        self.tip = tip_image(brush)
        self.random = random.Random()
        self.until_next = 0.
        self.started = False
        self.origin = None
        self.direction = None
        self.widths = 0.  # distance travelled, in brush widths (paint depletion)
        self.load = 1.
        self.length = 0.  # stroke length up to the current segment, in pixels
        self.along = self.last_along = 0.  # where the current dab lies along the stroke
        self.speed = 0.  # smoothed pen speed, pixels per second
        self.tinted = {}
        self.gradients = {}
        self.base = QTransform()
        # Round tips are drawn analytically, so their edge is a clean one-pixel ramp at any size.
        self.analytic = not brush.tip
        # Spacing follows the narrowest side of the tip, so thin elliptical tips stay continuous.
        ratio = self.tip.height() / max(1, self.tip.width())
        self.extent = max(.05, min(1., ratio, brush.roundness if not brush.tip else 1.))
        # Solid continuous round strokes need only enough dabs for a smooth outline.
        self.outline_spacing = (self.analytic and brush.flow >= .999 and brush.spacing <= .25
                                and not (brush.jitter or brush.scatter or brush.depletion))

    def tip_for(self, width, level=1.):
        """Area-averaged copy of the tip near the drawn size (small dabs keep their texture),
        scaled to the dab's coverage level."""
        if width >= self.tip.width() * .8:
            image = self.tip
        else:
            bucket = max(2, int(round(width * 1.25)))
            image = scaled_tip(self.tip, self.key, bucket, max(1, round(bucket * self.tip.height() / self.tip.width())))
        step = round(max(0., min(1., level)) * 255)
        if step >= 255:
            return image
        key = (image.cacheKey(), step)
        tinted = self.tinted.get(key)
        if tinted is None:
            if len(self.tinted) > 64:
                self.tinted.clear()
            tinted = image.copy()
            painter = QPainter(tinted)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            painter.fillRect(tinted.rect(), QColor(step, step, step))
            painter.end()
            self.tinted[key] = tinted
        return tinted

    def round_brush(self, radius, level):
        """Radial gradient for a round dab: the brush's hardness falloff, widened to at least a
        one-pixel ramp so the edge is antialiased exactly. It ends at zero inside the drawn disc,
        so the disc's own (accumulating) edge never shows."""
        radius_step = round(radius * 8) / 8 if radius < 32 else round(radius)
        step = round(max(0., min(1., level)) * 255)
        key = (radius_step, step)
        gradient = self.gradients.get(key)
        if gradient is None:
            if len(self.gradients) > 768:
                self.gradients.clear()
            radius = max(.5, radius_step)
            ramp = .5 / math.sqrt(max(.05, self.brush.roundness))
            soft = max(0., 1 - self.brush.hardness) * radius
            outer = radius + ramp + 1
            inner_edge, outer_edge = radius - soft - ramp, radius + ramp
            gradient = QRadialGradient(QPointF(0, 0), outer)
            def value(t):
                x = max(0., min(1., (outer_edge - t) / (outer_edge - inner_edge)))
                return round(step * x * x * (3 - 2 * x))
            gradient.setColorAt(0, QColor.fromRgb(*(value(0),) * 3))
            for n in range(13):
                t = inner_edge + (outer_edge - inner_edge) * n / 12
                if t > 0:
                    gradient.setColorAt(t / outer, QColor.fromRgb(*(value(t),) * 3))
            gradient.setColorAt(1, QColor('black'))
            gradient = self.gradients[key] = QBrush(gradient)
        return gradient

    def spacing(self, size):
        step = size * self.brush.spacing * self.extent
        if self.outline_spacing:
            # Overlapping discs leave a scalloped edge of depth step²/(8·radius); keep it invisible.
            step = min(max(step, size * .1 * self.extent), math.sqrt(.12 * size * self.extent))
        return max(.2, step)

    def begin(self, painter):
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # The disc's own edge lies where the gradient is already zero: it needs no antialiasing.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(self.brush.flow)
        self.base = painter.transform()

    def draw(self, painter, previous, samples, size_fn):
        dirty = QRectF()
        self.begin(painter)
        for sample in samples:
            if not self.started:
                if self.origin is None:
                    self.origin = previous
                origin = self.origin
                if self.brush.follow_direction:
                    # Wait until the stroke shows where it goes, so the first dab already lies along it.
                    if math.hypot(sample.x - origin.x, sample.y - origin.y) < max(1., size_fn(origin) * .12):
                        continue
                    self.direction = math.degrees(math.atan2(sample.y - origin.y, sample.x - origin.x))
                previous = origin
                size = size_fn(origin)
                dirty = self.stamp(painter, QPointF(origin.x, origin.y), size, origin.pressure)
                self.until_next = self.spacing(size)
                self.started = True
            dx, dy = sample.x - previous.x, sample.y - previous.y
            distance = math.hypot(dx, dy)
            size_start, size_end = size_fn(previous), size_fn(sample)
            elapsed = getattr(sample, 'time', 0.) - getattr(previous, 'time', 0.)
            if elapsed > 0:
                self.speed += (distance / elapsed - self.speed) * min(1., elapsed / .03)
            if distance > .3:
                angle = math.degrees(math.atan2(dy, dx))
                if self.direction is None:
                    self.direction = angle
                else:
                    turn = (angle - self.direction + 180) % 360 - 180
                    # Big brushes turn more slowly, like hairs dragged behind the ferrule.
                    self.direction += turn * min(1., distance / max(4., size_end * .2))
            travelled = 0.
            while distance - travelled >= self.until_next and distance > 0:
                travelled += self.until_next
                ratio = travelled / distance
                size = size_start + (size_end - size_start) * ratio
                pressure = previous.pressure + (sample.pressure - previous.pressure) * ratio
                self.along = self.length + travelled
                self.deplete(self.along - self.last_along, size)
                self.last_along = self.along
                bounds = self.stamp(painter, QPointF(previous.x + dx * ratio, previous.y + dy * ratio), size, pressure)
                dirty = bounds if dirty.isNull() else dirty.united(bounds)
                self.until_next = self.spacing(size)
            self.until_next -= max(0., distance - travelled)
            self.length += distance
            previous = sample
        painter.restore()
        return dirty

    def finish(self, painter, size_fn):
        """A tap, or a stroke too short to show its direction, still leaves one dab."""
        if self.started or self.origin is None:
            return QRectF()
        self.begin(painter)
        dirty = self.stamp(painter, QPointF(self.origin.x, self.origin.y), size_fn(self.origin), self.origin.pressure)
        painter.restore()
        self.started = True
        return dirty

    def deplete(self, step, size):
        """Paint runs out along the stroke: full at first, then fading into dry-brush marks."""
        if self.brush.depletion > 0:
            self.widths += step / max(1., size)
            self.load = math.exp(-(self.widths * self.brush.depletion / 6) ** 2)

    def shape_factor(self, size):
        """Size changes that depend on the stroke itself: start taper and pen speed."""
        brush, factor = self.brush, 1.
        if brush.taper_in:
            grown = min(1., self.along / (brush.taper_in * 12 * max(1., size)))
            factor *= .06 + .94 * math.sqrt(grown)
        if brush.speed_size:
            fast = min(1., self.speed / 1500.)
            factor *= max(.15, 1 - brush.speed_size * fast) if brush.speed_size > 0 else 1 - brush.speed_size * fast
        return factor

    def stamp(self, painter, position, size, pressure=1.):
        brush = self.brush
        pressure = max(0., min(1., pressure))
        size *= self.shape_factor(size)
        if brush.flow_pressure:
            painter.setOpacity(brush.flow * (1 - brush.flow_pressure * (1 - pressure)))
        dirty = QRectF()
        for _ in range(brush.count):
            box = self.dab(painter, position, size, pressure)
            dirty = box if dirty.isNull() else dirty.united(box)
        return dirty

    def dab(self, painter, position, size, pressure):
        brush = self.brush
        size *= 1 - brush.jitter * self.random.random()
        level = (1 - brush.opacity_pressure * (1 - pressure)) * self.load
        if brush.opacity_jitter:
            level *= 1 - brush.opacity_jitter * self.random.random()
        if size < 1:
            # Hairline dabs keep their visual weight through coverage instead of shrinking away.
            level *= max(.1, size)
            size = 1.
        position = position + QPointF(self.random.uniform(-1, 1), self.random.uniform(-1, 1)) * (brush.scatter * size)
        squash = 1 - brush.roundness_jitter * self.random.random() if brush.roundness_jitter else 1.
        height = size * self.tip.height() / self.tip.width() * squash
        angle = brush.angle + self.random.uniform(-1, 1) * brush.angle_jitter
        if brush.follow_direction and self.direction is not None:
            angle += self.direction
        transform = QTransform(self.base)
        transform.translate(position.x(), position.y())
        transform.rotate(angle)
        if brush.flip_jitter:
            transform.scale(self.random.choice((-1, 1)), self.random.choice((-1, 1)))
        if self.analytic:
            transform.scale(1, max(.05, brush.roundness * squash))
            painter.setTransform(transform)
            fill = self.round_brush(size / 2, level)
            outer = fill.gradient().radius()
            painter.setBrush(fill)
            painter.drawEllipse(QPointF(0, 0), outer, outer)
            radius = outer + 2
        else:
            painter.setTransform(transform)
            painter.drawImage(QRectF(-size / 2, -height / 2, size, height), self.tip_for(size, level))
            radius = math.hypot(size, height) / 2 + 2
        return QRectF(position.x() - radius, position.y() - radius, radius * 2, radius * 2)


# ----------------------------------------------------------------- preview

class _Sample:
    __slots__ = ('x', 'y', 'pressure')

    def __init__(self, x, y, pressure):
        self.x, self.y, self.pressure = x, y, pressure


def preview_samples(width, height, count=160):
    """An S-shaped stroke with a pressure taper at both ends."""
    samples = []
    for n in range(count):
        t = n / (count - 1)
        x = width * (.08 + .84 * t)
        y = height * (.5 + .28 * math.sin(t * math.pi * 2))
        samples.append(_Sample(x, y, .15 + .85 * math.sin(t * math.pi) ** .7))
    return samples


def render_stroke(brush, color, size, samples, width, height, minimum=.15, pressure_enabled=True):
    """Draw a stroke with the real engine onto a transparent image (used by previews)."""
    scratch = coverage_buffer(width, height)
    painter = QPainter(scratch)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    def size_fn(sample):
        if not (pressure_enabled and brush.size_pressure):
            return size
        return max(.3, size * (minimum + (1 - minimum) * sample.pressure))
    stroke = StampStroke(brush)
    stroke.draw(painter, samples[0], samples, size_fn)
    stroke.finish(painter, size_fn)
    painter.end()
    if has_effects(brush):
        return solid(color, finish_alpha(alpha_of(scratch), 0, 0, brush, size))
    return colorize(color, scratch)


def preview(brush, color, width=160, height=48, size=None, scale=1.):
    """Stroke preview; `scale` renders it for high-density screens (device pixel ratio)."""
    size = size or max(3., min(height * .45, brush.size))
    scale = max(1., float(scale))
    w, h = round(width * scale), round(height * scale)
    image = render_stroke(brush, QColor(color), size * scale, preview_samples(w, h), w, h)
    image.setDevicePixelRatio(scale)
    return image
