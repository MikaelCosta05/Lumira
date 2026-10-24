"""Keyframe evaluation, rigid 2D rigs, camera/parallax and transitions."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QTransform


def interpolate(keys, frame, defaults):
    if not keys:
        return dict(defaults)
    keys = sorted(keys, key=lambda k: k['frame'])
    left = right = keys[0]
    for key in keys:
        if key['frame'] <= frame:
            left = key
        if key['frame'] >= frame:
            right = key
            break
    else:
        right = keys[-1]
    span = right['frame'] - left['frame']
    amount = max(0., min(1., (frame - left['frame']) / span)) if span else 0.
    if left.get('easing') == 'ease':
        amount = amount * amount * (3 - 2 * amount)
    return {key: left.get(key, value) + (right.get(key, value) - left.get(key, value)) * amount
            for key, value in defaults.items()}


def bone_transform(document, bone, frame, visited=None):
    visited = set() if visited is None else visited
    if bone['id'] in visited:
        return QTransform()
    visited.add(bone['id'])
    value = interpolate(bone.get('keys', []), frame, {'angle': 0., 'x': 0., 'y': 0.})
    own = QTransform()
    own.translate(bone['x'] + value['x'], bone['y'] + value['y'])
    own.rotate(value['angle'])
    own.translate(-bone['x'], -bone['y'])
    parent = next((b for b in document.scene['bones'] if b['id'] == bone.get('parent')), None)
    return own * bone_transform(document, parent, frame, visited) if parent else own


def layer_transform(document, layer, frame):
    if not document.animation_enabled:
        return QTransform(), 1.
    value = interpolate(document.scene['layers'].get(layer.id, []), frame,
                        {'x': 0., 'y': 0., 'angle': 0., 'scale': 1., 'opacity': 1., 'parallax': 1.})
    transform = QTransform()
    transform.translate(document.width / 2 + value['x'], document.height / 2 + value['y'])
    transform.rotate(value['angle'])
    transform.scale(max(.01, value['scale']), max(.01, value['scale']))
    transform.translate(-document.width / 2, -document.height / 2)
    bone = next((b for b in document.scene['bones'] if b.get('layer') == layer.id), None)
    if bone:
        transform *= bone_transform(document, bone, frame)
    camera = interpolate(document.scene['camera'], frame, CAMERA_DEFAULTS)
    shake_x, shake_y = shake_offset(frame, camera['shake'])
    view = QTransform()
    view.translate(document.width / 2, document.height / 2)
    view.rotate(-camera['angle'])
    view.scale(max(.1, camera['zoom']), max(.1, camera['zoom']))
    view.translate(-document.width / 2 - (camera['x'] + shake_x) * value['parallax'],
                   -document.height / 2 - (camera['y'] + shake_y) * value['parallax'])
    return transform * view, max(0., min(1., value['opacity']))


CAMERA_DEFAULTS = {'x': 0., 'y': 0., 'zoom': 1., 'angle': 0., 'shake': 0.}

TRANSITIONS = [('Fade in (do preto)', 'fade_in'), ('Fade out (para o preto)', 'fade_out'),
               ('Dissolver', 'crossfade'), ('Revelar horizontal', 'wipe'), ('Revelar vertical', 'wipe_vertical'),
               ('Deslizar (empurrar)', 'slide'), ('Íris (círculo)', 'iris'), ('Zoom de saída', 'zoom'),
               ('Clarão branco', 'flash')]


def shake_offset(frame, amount):
    """Deterministic per-frame jitter, so previews and exports match."""
    if amount <= 0:
        return 0., 0.
    step = math.floor(frame)
    def noise(seed):
        value = math.sin(step * 12.9898 + seed * 78.233) * 43758.5453
        return (value - math.floor(value)) * 2 - 1
    return noise(1) * amount, noise(2) * amount


def raw_frame(document, frame, paper, target=None, clip=None):
    """Flattened layers of a frame. With `target` and `clip`, only that area of `target` is redrawn."""
    from document import draw_layer
    if target is None:
        image = QImage(document.width, document.height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('white') if paper else 0)
    else:
        image = target
    painter = QPainter(image)
    if clip is not None:
        painter.setClipRect(clip)
        if target is not None:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(clip, QColor('white') if paper else QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    stack = [paper]
    for layer in document.frames[max(0, min(len(document.frames)-1, int(frame)))].layers:
        if layer.visible:
            transform, opacity = layer_transform(document, layer, frame)
            if layer.is_shadow:
                draw_shadow_layer(painter, image, document, layer, transform, layer.opacity * opacity, tuple(stack))
            else:
                painter.setTransform(transform)
                draw_layer(painter, layer, opacity)
            stack.append((layer.image.cacheKey(), layer.opacity * opacity, layer.blend, transform.m11(), transform.m12(),
                          transform.m21(), transform.m22(), transform.dx(), transform.dy()))
    painter.end()
    return image


def draw_shadow_layer(painter, target, document, layer, transform, opacity, below_key):
    """Paint a shadow layer's styled overlay; its raster is only a mask."""
    import shading
    from selection import transformed
    mask = layer.image if transform.isIdentity() else transformed(layer.image, transform, document.width, document.height)
    settings = dict(shading.DEFAULT_SHADOW, **layer.shadow)
    preview = document.preview_layer == layer.id
    # The image below is copied only when the styled overlay is not cached yet.
    below = (lambda: target.copy()) if settings['style'] == 'colored' and not preview else None
    overlay = shading.render_layer(mask, settings, below, below_key, preview)
    painter.save()
    painter.resetTransform()
    painter.setOpacity(opacity)
    painter.setCompositionMode(shading.composition(settings) if not preview else QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.drawImage(0, 0, overlay)
    painter.restore()


def active_transitions(document, frame):
    return [t for t in document.scene['transitions'] if t['from'] <= frame < t['to'] + 1]


def render_scene(document, frame, paper=True, subtitles=True, effects=True, target=None, clip=None):
    """Final frame. With `target` and `clip` only that area is redrawn (used by the view cache)."""
    image = raw_frame(document, frame, paper, target, clip)
    painter = QPainter(image)
    if clip is not None:
        painter.setClipRect(clip)
    if effects:
        for transition in document.scene['transitions']:
            start, end = transition['from'], transition['to']
            if start <= frame < end + 1:
                fraction = min(1., (frame - start) / max(1, end - start))
                kind = transition['type']
                if kind in ('fade_in', 'fade_out'):
                    painter.setOpacity(1 - fraction if kind == 'fade_in' else fraction)
                    painter.fillRect(image.rect(), Qt.GlobalColor.black)
                elif kind == 'crossfade':
                    previous = raw_frame(document, max(0, start - 1), paper)
                    painter.setOpacity(1 - fraction)
                    painter.drawImage(0, 0, previous)
                elif kind in ('wipe', 'wipe_vertical'):
                    previous = raw_frame(document, max(0, start - 1), paper)
                    painter.setOpacity(1.)
                    painter.save()
                    if kind == 'wipe':
                        painter.setClipRect(QRectF(image.width() * fraction, 0, image.width() * (1 - fraction), image.height()))
                    else:
                        painter.setClipRect(QRectF(0, image.height() * fraction, image.width(), image.height() * (1 - fraction)))
                    painter.drawImage(0, 0, previous)
                    painter.restore()
                elif kind == 'slide':
                    previous = raw_frame(document, max(0, start - 1), paper)
                    current = QImage(image)
                    painter.save()
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.fillRect(image.rect(), QColor('white') if paper else QColor(0, 0, 0, 0))
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                    painter.drawImage(QPointF(-image.width() * fraction, 0), previous)
                    painter.drawImage(QPointF(image.width() * (1 - fraction), 0), current)
                    painter.restore()
                elif kind == 'iris':
                    previous = raw_frame(document, max(0, start - 1), paper)
                    radius = math.hypot(image.width(), image.height()) / 2 * fraction
                    outside = QPainterPath()
                    outside.addRect(QRectF(image.rect()))
                    circle = QPainterPath()
                    circle.addEllipse(QRectF(image.rect()).center(), radius, radius)
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setClipPath(outside.subtracted(circle))
                    painter.drawImage(0, 0, previous)
                    painter.restore()
                elif kind == 'zoom':
                    previous = raw_frame(document, max(0, start - 1), paper)
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    painter.setOpacity(1 - fraction)
                    scale = 1 + fraction * .6
                    painter.translate(image.width() / 2, image.height() / 2)
                    painter.scale(scale, scale)
                    painter.translate(-image.width() / 2, -image.height() / 2)
                    painter.drawImage(0, 0, previous)
                    painter.restore()
                elif kind == 'flash':
                    painter.setOpacity(1 - fraction)
                    painter.fillRect(image.rect(), Qt.GlobalColor.white)
        painter.setOpacity(1.)
    if subtitles and effects:
        index = min(len(document.frames) - 1, int(frame))
        time = document.frame_start(index) + (frame - index) * document.frames[index].duration / 1000
        cues = [cue['text'] for cue in document.scene['subtitles'] if cue['start'] <= time < cue['end']]
        if cues:
            text = '\n'.join(cues)
            font = QFont('Segoe UI')
            font.setPixelSize(max(12, min(48, round(document.height * .04))))
            painter.setFont(font)
            margin = max(4, document.width * .06)
            width = document.width - 2 * margin
            metrics = QFontMetricsF(font)
            bounds = metrics.boundingRect(QRectF(0, 0, width - 12, document.height), Qt.TextFlag.TextWordWrap, text)
            rect = QRectF(margin, document.height - bounds.height() - margin / 2 - 12, width, bounds.height() + 12)
            painter.fillRect(rect, QColor(0, 0, 0, 180))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(rect.adjusted(6, 6, -6, -6), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    painter.end()
    return image


def play_order(document, tag=None):
    start, end, direction = (tag['from'], tag['to'], tag['direction']) if tag else (0, len(document.frames)-1, 'forward')
    order = list(range(start, end + 1))
    if direction == 'reverse':
        return order[::-1]
    if direction == 'pingpong' and len(order) > 1:
        return order + order[-2:0:-1]
    return order
