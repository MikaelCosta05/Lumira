"""Shape, gradient, smudge/blur and text tools (pure image operations)."""
import math
from functools import lru_cache

import numpy as np
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPolygonF, QRadialGradient)

FORMAT = QImage.Format.Format_ARGB32_Premultiplied

SHAPES = [('Linha', 'line'), ('Retângulo', 'rect'), ('Retângulo arredondado', 'rounded'), ('Elipse', 'ellipse'),
          ('Polígono (clique nos pontos, duplo clique fecha)', 'polygon'), ('Estrela', 'star'), ('Seta', 'arrow')]
SHAPE_FILLS = [('Contorno', 'stroke'), ('Preenchido', 'fill'), ('Contorno + preenchimento (cor secundária)', 'both')]
GRADIENTS = [('Linear', 'linear'), ('Radial', 'radial'), ('Espelhado', 'reflected'), ('Cônico (anel de cor)', 'conical')]
GRADIENT_COLORS = [('Principal → secundária', 'colors'), ('Principal → transparente', 'transparent')]


# ------------------------------------------------------------------ shapes

def shape_path(kind, start, end, constrain=False, from_center=False, points=None):
    """Path of a shape dragged from `start` to `end` (document coordinates)."""
    if kind == 'polygon':
        path = QPainterPath()
        if points and len(points) > 1:
            path.addPolygon(QPolygonF(points + [end]))
        return path
    if kind in ('line', 'arrow'):
        if constrain:
            angle = round(math.atan2(end.y() - start.y(), end.x() - start.x()) / (math.pi / 4)) * math.pi / 4
            length = math.hypot(end.x() - start.x(), end.y() - start.y())
            end = QPointF(start.x() + math.cos(angle) * length, start.y() + math.sin(angle) * length)
        path = QPainterPath(start)
        path.lineTo(end)
        if kind == 'arrow':
            angle = math.atan2(end.y() - start.y(), end.x() - start.x())
            size = max(8., math.hypot(end.x() - start.x(), end.y() - start.y()) * .18)
            for side in (-1, 1):
                path.moveTo(end)
                path.lineTo(end.x() - math.cos(angle + side * .45) * size, end.y() - math.sin(angle + side * .45) * size)
        return path
    dx, dy = end.x() - start.x(), end.y() - start.y()
    if constrain:
        side = max(abs(dx), abs(dy))
        dx, dy = math.copysign(side, dx or 1), math.copysign(side, dy or 1)
    rect = QRectF(start.x() - dx, start.y() - dy, dx * 2, dy * 2) if from_center else QRectF(start, QPointF(start.x() + dx, start.y() + dy))
    rect = rect.normalized()
    path = QPainterPath()
    if kind == 'rect':
        path.addRect(rect)
    elif kind == 'rounded':
        radius = min(rect.width(), rect.height()) * .18
        path.addRoundedRect(rect, radius, radius)
    elif kind == 'ellipse':
        path.addEllipse(rect)
    elif kind == 'star':
        center, outer = rect.center(), min(rect.width(), rect.height()) / 2
        polygon = QPolygonF()
        for k in range(10):
            radius = outer if k % 2 == 0 else outer * .45
            angle = -math.pi / 2 + k * math.pi / 5
            polygon.append(QPointF(center.x() + math.cos(angle) * radius * rect.width() / max(1e-6, 2 * outer),
                                   center.y() + math.sin(angle) * radius * rect.height() / max(1e-6, 2 * outer)))
        path.addPolygon(polygon)
        path.closeSubpath()
    return path


def paint_shape(image, path, kind, width, color, fill_mode='stroke', fill_color=None, opacity=1., alpha_lock=False,
                mask=None):
    """Draw a shape path onto a layer image."""
    shape = QImage(image.size(), FORMAT)
    shape.fill(0)
    painter = QPainter(shape)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    closed = kind not in ('line', 'arrow')
    if closed and fill_mode in ('fill', 'both'):
        painter.fillPath(path, QColor(fill_color if fill_mode == 'both' and fill_color is not None else color))
    if fill_mode in ('stroke', 'both') or not closed:
        painter.strokePath(path, QPen(color, max(.5, width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                      Qt.PenJoinStyle.RoundJoin))
    painter.end()
    _composite(image, shape, opacity, alpha_lock, mask)


def _composite(image, overlay, opacity, alpha_lock, mask):
    if mask is not None:
        clip = QPainter(overlay)
        clip.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        clip.drawImage(0, 0, mask)
        clip.end()
    painter = QPainter(image)
    painter.setOpacity(opacity)
    if alpha_lock:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    painter.drawImage(0, 0, overlay)
    painter.end()


# ---------------------------------------------------------------- gradient

def paint_gradient(image, start, end, kind, color_a, color_b, opacity=1., alpha_lock=False, mask=None):
    color_b = QColor(color_b)
    if kind == 'linear' or kind == 'reflected':
        gradient = QLinearGradient(start, end)
        if kind == 'reflected':
            gradient.setSpread(QLinearGradient.Spread.ReflectSpread)
    elif kind == 'conical':
        from PyQt6.QtGui import QConicalGradient
        gradient = QConicalGradient(start, -math.degrees(math.atan2(end.y() - start.y(), end.x() - start.x())))
    else:
        gradient = QRadialGradient(start, max(1., math.hypot(end.x() - start.x(), end.y() - start.y())))
    gradient.setColorAt(0, QColor(color_a))
    gradient.setColorAt(1, color_b)
    if kind == 'conical':
        gradient.setColorAt(.5, color_b)
        gradient.setColorAt(1, QColor(color_a))
    overlay = QImage(image.size(), FORMAT)
    overlay.fill(0)
    painter = QPainter(overlay)
    painter.fillRect(overlay.rect(), QBrush(gradient))
    painter.end()
    _composite(image, overlay, opacity, alpha_lock, mask)


# ---------------------------------------------------------- smudge / blur

def read_patch(image, rect):
    patch = image.copy(rect).convertToFormat(FORMAT)
    data = np.frombuffer(patch.constBits().asstring(patch.sizeInBytes()), np.uint8)
    return data.reshape(patch.height(), patch.bytesPerLine() // 4, 4)[:, :patch.width()].astype(np.float32) / 255


def write_patch(image, rect, values):
    data = np.ascontiguousarray(np.clip(np.round(values * 255), 0, 255).astype(np.uint8))
    height, width = data.shape[:2]
    buffer = data.tobytes()
    patch = QImage(buffer, width, height, width * 4, FORMAT).copy()
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(rect.topLeft(), patch)
    painter.end()


@lru_cache(maxsize=64)
def dab_mask(diameter, hardness=.4):
    grid = (np.arange(diameter, dtype=np.float32) - (diameter - 1) / 2) / max(1., diameter / 2)
    radius = np.sqrt(grid[None, :] ** 2 + grid[:, None] ** 2)
    return np.clip((1 - radius) / max(.05, 1 - hardness), 0, 1)


class EffectStroke:
    """Smudge (drags paint along the stroke) or blur, applied dab by dab to a layer."""

    def __init__(self, image, mode, strength=.6, mask=None):
        self.image, self.mode, self.strength, self.mask = image, mode, strength, mask
        self.carry = None
        self.until_next = 0.
        self.previous = None

    def stroke(self, samples, size_fn):
        dirty = QRect()
        for sample in samples:
            point = QPointF(sample.x, sample.y)
            if self.previous is None:
                dirty = self.dab(point, size_fn(sample), sample.pressure)
                self.previous = (point, sample)
                continue
            start, previous_sample = self.previous
            distance = math.hypot(point.x() - start.x(), point.y() - start.y())
            spacing = max(1., size_fn(sample) * .18)
            travelled = self.until_next
            while travelled <= distance and distance > 0:
                ratio = travelled / distance
                position = QPointF(start.x() + (point.x() - start.x()) * ratio, start.y() + (point.y() - start.y()) * ratio)
                pressure = previous_sample.pressure + (sample.pressure - previous_sample.pressure) * ratio
                box = self.dab(position, size_fn(sample), pressure)
                dirty = box if dirty.isNull() else dirty.united(box)
                travelled += spacing
            self.until_next = travelled - distance
            self.previous = (point, sample)
        return dirty

    def dab(self, position, size, pressure):
        diameter = max(3, int(round(size)))
        rect = QRect(int(round(position.x() - diameter / 2)), int(round(position.y() - diameter / 2)), diameter, diameter)
        clipped = rect.intersected(self.image.rect())
        if clipped.isEmpty():
            return QRect()
        mask = dab_mask(diameter)[clipped.top() - rect.top():clipped.top() - rect.top() + clipped.height(),
                                  clipped.left() - rect.left():clipped.left() - rect.left() + clipped.width()]
        weight = mask * self.strength * (.35 + .65 * max(0., min(1., pressure)))
        if self.mask is not None:
            weight = weight * read_patch(self.mask, clipped)[..., 3]
        patch = read_patch(self.image, clipped)
        if self.mode == 'blur':
            from scipy import ndimage
            sigma = max(.8, diameter / 7)
            blurred = ndimage.gaussian_filter(patch, (sigma, sigma, 0), mode='nearest')
            result = patch + (blurred - patch) * weight[..., None]
        else:
            if self.carry is None or self.carry.shape != patch.shape:
                self.carry = patch.copy()
                return clipped
            result = patch + (self.carry - patch) * weight[..., None]
            self.carry = self.carry * .78 + result * .22
        write_patch(self.image, clipped, result)
        return clipped


# -------------------------------------------------------------------- text

def render_text(size, position, text, font, color, outline=None, outline_width=0., align=Qt.AlignmentFlag.AlignLeft,
                width=None):
    """Raster text block (with optional outline, for comics lettering) on a transparent image."""
    image = QImage(size, FORMAT)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    metrics = QFontMetricsF(font)
    lines = text.split('\n')
    block_width = width or max((metrics.horizontalAdvance(line) for line in lines), default=0)
    y = position.y() + metrics.ascent()
    for line in lines:
        advance = metrics.horizontalAdvance(line)
        if align & Qt.AlignmentFlag.AlignHCenter:
            x = position.x() + (block_width - advance) / 2
        elif align & Qt.AlignmentFlag.AlignRight:
            x = position.x() + block_width - advance
        else:
            x = position.x()
        path = QPainterPath()
        path.addText(QPointF(x, y), font, line)
        if outline is not None and outline_width > 0:
            painter.strokePath(path, QPen(QColor(outline), outline_width * 2, Qt.PenStyle.SolidLine,
                                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.fillPath(path, QColor(color))
        y += metrics.lineSpacing()
    painter.end()
    return image
