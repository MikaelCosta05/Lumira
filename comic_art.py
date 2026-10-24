"""Comic lettering and effects: speech balloons, sound effects, action lines and screentones.

Everything renders to a transparent page-sized image (a new layer), optionally limited to an
area mask (a selection or a panel) whose alpha is the coverage.
"""
import math
import random
import zlib

import numpy as np
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
                         QPolygonF, QTransform)

FORMAT = QImage.Format.Format_ARGB32_Premultiplied

BALLOONS = [('Fala', 'speech'), ('Pensamento', 'thought'), ('Grito', 'shout'), ('Sussurro', 'whisper'),
            ('Narração (caixa)', 'caption'), ('Rádio / eletrônico', 'radio'), ('Onomatopeia (SFX)', 'sfx')]
LINE_KINDS = [('Foco / concentração', 'focus'), ('Velocidade', 'speed'), ('Explosão', 'burst')]
TONES = [('Pontos (retícula)', 'dots'), ('Degradê de pontos', 'gradient'), ('Linhas', 'lines'),
         ('Hachura cruzada', 'cross'), ('Granulado', 'noise')]


def lettering_family(kind='speech'):
    """A comic-looking font that exists on this machine."""
    families = set(QFontDatabase.families())
    wanted = ['Impact', 'Arial Black', 'Bahnschrift'] if kind == 'sfx' else \
        ['Comic Neue', 'Comic Sans MS', 'Segoe Print', 'Inter', 'Segoe UI']
    return next((family for family in wanted if family in families), QFont().family())


def blank(width, height):
    image = QImage(width, height, FORMAT)
    image.fill(0)
    return image


def limit_to(image, mask):
    """Keep only what lies inside `mask` (alpha = coverage)."""
    if mask is not None:
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        painter.end()
    return image


# ----------------------------------------------------------------- balloons

def text_box(text, font, center, aspect=2.4):
    """Wrapped text block centred on `center`, wider than tall like comic lettering (`aspect` ≈ width:height)."""
    metrics = QFontMetricsF(font)
    advance = metrics.horizontalAdvance(text.replace('\n', ' '))
    line = metrics.lineSpacing()
    longest = max((metrics.horizontalAdvance(part) for part in text.split()), default=line)
    width = max(longest + 2, min(advance + 2, math.sqrt(advance * line * aspect)))
    flags = int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap)
    rect = metrics.boundingRect(QRectF(0, 0, width, 100000), flags, text)
    return QRectF(center.x() - rect.width() / 2, center.y() - rect.height() / 2, rect.width(), rect.height()), flags


def _ellipse_point(center, rx, ry, angle):
    return QPointF(center.x() + rx * math.cos(angle), center.y() + ry * math.sin(angle))


def _tail(center, rx, ry, tip, spread=.3, curve=.18):
    """Curved wedge from inside the ellipse towards `tip`."""
    angle = math.atan2((tip.y() - center.y()) / max(ry, 1e-6), (tip.x() - center.x()) / max(rx, 1e-6))
    a = _ellipse_point(center, rx * .85, ry * .85, angle - spread)
    b = _ellipse_point(center, rx * .85, ry * .85, angle + spread)
    bend = QPointF(-(tip.y() - center.y()), tip.x() - center.x()) * curve
    path = QPainterPath(a)
    path.quadTo((a + tip) / 2 + bend * .5, tip)
    path.quadTo((b + tip) / 2 + bend * .2, b)
    path.closeSubpath()
    return path


def balloon_path(kind, center, rx, ry, tip=None, seed=0):
    """Outline of a balloon (with its tail when `tip` is outside it)."""
    rng = random.Random(seed)
    path = QPainterPath()
    outside = tip is not None and ((tip.x() - center.x()) / rx) ** 2 + ((tip.y() - center.y()) / ry) ** 2 > 1.2
    if kind in ('speech', 'whisper'):
        path.addEllipse(center, rx, ry)
        if outside:
            path = path.united(_tail(center, rx, ry, tip))
    elif kind == 'thought':
        bumps = max(9, round(2 * math.pi * math.sqrt((rx * rx + ry * ry) / 2) / (min(rx, ry) * .55)))
        path.addEllipse(center, rx * .92, ry * .92)
        for k in range(bumps):
            angle = 2 * math.pi * k / bumps
            radius = min(rx, ry) * rng.uniform(.3, .4)
            path = path.united(_circle(_ellipse_point(center, rx * .92, ry * .92, angle), radius))
        if outside:
            for step, size in ((.45, .2), (.72, .13), (.92, .08)):
                edge = _ellipse_point(center, rx, ry, math.atan2((tip.y() - center.y()) / ry, (tip.x() - center.x()) / rx))
                point = edge + (tip - edge) * step
                path.addEllipse(point, min(rx, ry) * size, min(rx, ry) * size)
    elif kind in ('shout', 'radio'):
        spikes = 22 if kind == 'shout' else 44
        polygon = QPolygonF()
        for k in range(spikes * 2):
            angle = math.pi * k / spikes
            if kind == 'shout':
                scale = 1.28 * rng.uniform(.92, 1.12) if k % 2 == 0 else .98
            else:
                scale = 1.1 if k % 2 == 0 else 1.
            polygon.append(_ellipse_point(center, rx * scale, ry * scale, angle))
        path.addPolygon(polygon)
        path.closeSubpath()
        if outside:
            tail = _tail(center, rx, ry, tip, .22 if kind == 'shout' else .3, curve=0 if kind == 'shout' else .1)
            path = path.united(tail)
    return path


def _circle(center, radius):
    path = QPainterPath()
    path.addEllipse(center, radius, radius)
    return path


def balloon(width, height, center, tip, text, kind='speech', font=None, fill='#ffffff', outline='#111111',
            text_color='#111111', line_width=4., angle=0.):
    """Page-sized image with one balloon (or sound effect) and the area it covers."""
    font = QFont(font) if font is not None else QFont(lettering_family(kind))
    image = blank(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if kind == 'sfx':
        bounds = _sound_effect(painter, text, font, center, QColor(fill), QColor(outline), line_width, angle)
        painter.end()
        return image, bounds
    box, flags = text_box(text, font, center, 4. if kind == 'caption' else 2.4)
    pad = font.pixelSize() * .45
    if kind == 'caption':
        frame = box.adjusted(-pad * 1.6, -pad, pad * 1.6, pad)
        path = QPainterPath()
        path.addRect(frame)
        shadow = QPainterPath(path)
        shadow.translate(line_width * 1.5, line_width * 1.5)
        painter.fillPath(shadow, QColor(0, 0, 0, 70))
    else:
        rx, ry = box.width() / 2 * 1.42 + pad, box.height() / 2 * 1.42 + pad
        path = balloon_path(kind, center, rx, ry, tip, zlib.crc32(text.encode()))
    painter.fillPath(path, QColor(fill))
    if line_width > 0:
        pen = QPen(QColor(outline), line_width, Qt.PenStyle.DashLine if kind == 'whisper' else Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(path, pen)
    painter.setFont(font)
    painter.setPen(QColor(text_color))
    painter.drawText(box, flags, text)
    painter.end()
    return image, path.boundingRect().adjusted(-line_width, -line_width, line_width, line_width)


def _sound_effect(painter, text, font, center, fill, outline, line_width, angle):
    """Big outlined lettering, rotated, with a drop shadow: BOOM!, POW!, KRAK!"""
    path = QPainterPath()
    lines = text.split('\n')
    metrics = QFontMetricsF(font)
    y = -metrics.lineSpacing() * (len(lines) - 1) / 2 + metrics.ascent() / 2
    for line in lines:
        path.addText(QPointF(-metrics.horizontalAdvance(line) / 2, y), font, line)
        y += metrics.lineSpacing()
    transform = QTransform()
    transform.translate(center.x(), center.y())
    transform.rotate(angle)
    transform.shear(-.12, 0)
    path = transform.map(path)
    width = max(line_width, font.pixelSize() * .1)
    shadow = QPainterPath(path)
    shadow.translate(width * .8, width * .9)
    painter.strokePath(shadow, QPen(QColor(0, 0, 0, 150), width * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
    painter.strokePath(path, QPen(outline, width * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                  Qt.PenJoinStyle.RoundJoin))
    painter.fillPath(path, fill)
    return path.boundingRect().adjusted(-width * 2, -width * 2, width * 3, width * 3)


# ------------------------------------------------------------- action lines

def action_lines(width, height, area, kind='focus', center=None, count=120, clear=.35, thickness=6.,
                 color='#111111', angle=0., jitter=.6, seed=1, mask=None):
    """Focus (radial), speed (parallel) or burst lines inside `area` (a QRectF), clipped by `mask`."""
    rng = random.Random(seed)
    image = blank(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setClipRect(area)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    center = center if center is not None else area.center()
    if kind in ('focus', 'burst'):
        reach = max(math.dist((center.x(), center.y()), (x, y)) for x, y in
                    ((area.left(), area.top()), (area.right(), area.top()), (area.left(), area.bottom()),
                     (area.right(), area.bottom()))) * 1.05
        inner = clear * min(area.width(), area.height()) / 2
        lines = count if kind == 'focus' else max(8, count // 6)
        for k in range(lines):
            theta = 2 * math.pi * (k + rng.uniform(-.5, .5) * jitter) / lines
            start = inner * rng.uniform(1, 1 + 1.2 * jitter) if kind == 'focus' else inner * rng.uniform(.6, 1.)
            spread = (thickness * rng.uniform(.4, 1.6) / reach) if kind == 'focus' else (math.pi / lines * rng.uniform(.35, .7))
            tip = QPointF(center.x() + math.cos(theta) * start, center.y() + math.sin(theta) * start)
            a = QPointF(center.x() + math.cos(theta - spread) * reach, center.y() + math.sin(theta - spread) * reach)
            b = QPointF(center.x() + math.cos(theta + spread) * reach, center.y() + math.sin(theta + spread) * reach)
            painter.drawPolygon(QPolygonF([tip, a, b]))
    else:
        radians = math.radians(angle)
        direction = QPointF(math.cos(radians), math.sin(radians))
        normal = QPointF(-direction.y(), direction.x())
        span = math.hypot(area.width(), area.height())
        for _ in range(count):
            offset = rng.uniform(-span / 2, span / 2)
            if clear and abs(offset) < clear * min(area.width(), area.height()) / 2 and rng.random() < .85:
                continue
            length = span * rng.uniform(.25, .9)
            along = rng.uniform(-span / 2, span / 2 - length)
            base = center + normal * offset + direction * along
            half = thickness * rng.uniform(.3, 1.) / 2
            end = base + direction * length
            middle = (base + end) / 2
            painter.drawPolygon(QPolygonF([base, middle + normal * half, end, middle - normal * half]))
    painter.end()
    return limit_to(image, mask)


# --------------------------------------------------------------- screentone

def screentone(width, height, kind='dots', spacing=12., size=.5, angle=45., color='#111111', mask=None,
               area=None, seed=7, reverse=False):
    """Manga screentone inside `area` (and `mask`). Only the area's pixels are computed."""
    area = (area or QRectF(0, 0, width, height)).toAlignedRect().intersected(QRect(0, 0, width, height))
    image = blank(width, height)
    if area.isEmpty():
        return image
    y, x = np.mgrid[area.top():area.bottom() + 1, area.left():area.right() + 1].astype(np.float32)
    theta = math.radians(angle)
    u = x * math.cos(theta) + y * math.sin(theta)
    v = -x * math.sin(theta) + y * math.cos(theta)
    spacing = max(2., float(spacing))
    if kind in ('dots', 'gradient'):
        cu, cv = (u % spacing) - spacing / 2, (v % spacing) - spacing / 2
        distance = np.sqrt(cu * cu + cv * cv)
        radius = size * spacing * .5 * 1.2
        if kind == 'gradient':
            t = (y - area.top()) / max(1, area.height() - 1)
            radius = radius * ((1 - t) if reverse else t) * 1.1
        coverage = np.clip(radius - distance + .5, 0, 1)
    elif kind in ('lines', 'cross'):
        half = size * spacing / 2
        coverage = np.clip(half - np.abs((v % spacing) - spacing / 2) + .5, 0, 1)
        if kind == 'cross':
            coverage = np.maximum(coverage, np.clip(half - np.abs((u % spacing) - spacing / 2) + .5, 0, 1))
    else:
        rng = np.random.default_rng(seed)
        coverage = (rng.random(x.shape, dtype=np.float32) < size * .55).astype(np.float32)
    if mask is not None:
        alpha = np.frombuffer(mask.constBits().asstring(mask.sizeInBytes()), np.uint8)
        alpha = alpha.reshape(mask.height(), mask.bytesPerLine() // 4, 4)[area.top():area.bottom() + 1,
                                                                         area.left():area.right() + 1, 3]
        coverage = coverage * (alpha.astype(np.float32) / 255)
    tone = QColor(color)
    pixels = np.empty(coverage.shape + (4,), np.uint8)
    for channel, value in ((0, tone.blue()), (1, tone.green()), (2, tone.red()), (3, 255)):
        pixels[..., channel] = np.round(coverage * value).astype(np.uint8)
    patch = QImage(np.ascontiguousarray(pixels).data, pixels.shape[1], pixels.shape[0], pixels.shape[1] * 4, FORMAT).copy()
    painter = QPainter(image)
    painter.drawImage(area.topLeft(), patch)
    painter.end()
    return image
