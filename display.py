"""High-quality view of the document when zoomed out.

QPainter's bilinear filter samples only four pixels, so at 50% or less lines
alias and shimmer. The view keeps area-averaged reductions (1/2, 1/4, …) of the
flattened layers; while painting only the touched area is reduced again.
"""
import math
from collections import OrderedDict

import numpy as np
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QImage, QPainter

from document import draw_layer

FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def level_for(scale):
    """Reduction level whose remaining bilinear step stays between 1/2 and 1."""
    if scale >= 1:
        return 0
    return max(0, min(6, int(math.floor(math.log2(1 / scale) + 1e-9))))


def smooth_for(scale):
    """Bilinear when enlarging, except crisp integer zooms (pixel art) and very close views."""
    if scale < 1:
        return True
    return scale < 4 and not (scale >= 2 and abs(scale - round(scale)) < .01)


def pixels(image):
    """Zero-copy (height, width, 4) view of a 32-bit image; keep `image` alive while using it."""
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    data = np.frombuffer(bits, np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    return data[:, :image.width()]


def from_pixels(data):
    data = np.ascontiguousarray(data, np.uint8)
    height, width = data.shape[:2]
    return QImage(data.data, width, height, width * 4, FORMAT).copy()


def reduce(image, factor):
    """Box-filter downscale by an integer factor (premultiplied, so colours stay correct)."""
    if image.format() != FORMAT:
        image = image.convertToFormat(FORMAT)
    width, height = image.width(), image.height()
    data = pixels(image)
    out_w, out_h = -(-width // factor), -(-height // factor)
    if out_w * factor != width or out_h * factor != height:
        padded = np.zeros((out_h * factor, out_w * factor, 4), np.uint8)
        padded[:height, :width] = data
        data = padded
    # Summing strided slices is several times faster than reshape().sum() and exact.
    accumulator = np.zeros((out_h, out_w, 4), np.uint16 if factor <= 16 else np.uint32)
    for dy in range(factor):
        rows = data[dy::factor]
        for dx in range(factor):
            accumulator += rows[:, dx::factor]
    count = factor * factor
    accumulator += count // 2
    accumulator //= count
    return from_pixels(accumulator.astype(np.uint8))


def grayscale(image):
    """Luminance view of an image (alpha kept), to judge values without colour."""
    source = image.convertToFormat(FORMAT)
    data = pixels(source)
    luma = data[..., 2] * np.float32(.299) + data[..., 1] * np.float32(.587) + data[..., 0] * np.float32(.114)
    result = np.empty(data.shape, np.uint8)
    result[..., 0] = result[..., 1] = result[..., 2] = np.clip(np.round(luma), 0, 255)
    result[..., 3] = data[..., 3]
    return from_pixels(result)


def flatten(layers, rect):
    image = QImage(rect.size(), FORMAT)
    image.fill(0)
    painter = QPainter(image)
    for layer in layers:
        if layer.visible:
            draw_layer(painter, layer, 1., QPoint(0, 0), rect)
    painter.end()
    return image


def _aligned(area, factor, full):
    """`area` grown to whole reduction cells (so reduced patches line up), inside `full`."""
    left, top = area.left() // factor * factor, area.top() // factor * factor
    right = min(full.right() + 1, -(-(area.right() + 1) // factor) * factor)
    bottom = min(full.bottom() + 1, -(-(area.bottom() + 1) // factor) * factor)
    return QRect(left, top, right - left, bottom - top)


def _paste(target, position, patch):
    painter = QPainter(target)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(position, patch)
    painter.end()


class SceneView:
    """Final composite of the current frame (blend modes, shadow layers, camera, transitions,
    subtitles), kept between repaints instead of being rebuilt for every one.

    While painting, only the area touched by the stroke is composed again. Recent frames stay
    in memory (within a budget), so animation playback composes each frame once.
    `post` optionally converts the composite (e.g. to grayscale) and is cached as well.
    """

    BUDGET = 192 * 1024 * 1024

    def __init__(self, paper=False, post=None):
        self.paper, self.post = paper, post
        self.states = OrderedDict()
        self.dirty = QRect()

    def mark(self, rect):
        self.dirty = rect if self.dirty.isNull() else self.dirty.united(rect)

    def clear(self):
        self.states.clear()
        self.dirty = QRect()

    @staticmethod
    def structure(document):
        layers = tuple((layer.id, layer.visible, layer.opacity, layer.blend, layer.kind,
                        repr(sorted(layer.shadow.items())) if layer.is_shadow else None) for layer in document.layers)
        return (id(document), document.revision, document.current_frame, document.animation_enabled,
                document.preview_layer, document.width, document.height, layers)

    @staticmethod
    def partial_ok(document):
        """Areas can be refreshed alone unless something samples pixels from elsewhere."""
        from animation import active_transitions
        if document.animation_enabled and active_transitions(document, document.current_frame):
            return False
        return not any(layer.visible and layer.is_shadow and layer.shadow.get('style') == 'colored'
                       and document.preview_layer != layer.id for layer in document.layers)

    @staticmethod
    def transformed(document):
        if not document.animation_enabled:
            return False
        from animation import layer_transform
        return any(layer.visible and not layer_transform(document, layer, document.current_frame)[0].isIdentity()
                   for layer in document.layers)

    def adopt(self, document, old_revision):
        """A stroke bumped the revision without touching anything but marked pixels: keep the cache."""
        for key in list(self.states):
            if key[0] == id(document) and key[1] == old_revision:
                self.states[(key[0], document.revision) + key[2:]] = self.states.pop(key)

    def image(self, document, level=0):
        from animation import render_scene
        key = self.structure(document)
        stamps = tuple(layer.image.cacheKey() for layer in document.layers)
        full = QRect(0, 0, document.width, document.height)
        state = self.states.get(key)
        if state is None:
            stale = [k for k in self.states if k[0] == key[0] and k[1] != key[1]]
            for old in stale:
                del self.states[old]
            raw = render_scene(document, document.current_frame, self.paper, effects=document.animation_enabled)
            state = self.states[key] = {'raw': raw, 'full': self.post(raw) if self.post else raw,
                                        'stamps': stamps, 'levels': {}}
        elif state['stamps'] != stamps:
            area = self.dirty.intersected(full)
            if area.isEmpty() or not self.partial_ok(document):
                raw = render_scene(document, document.current_frame, self.paper, effects=document.animation_enabled)
                state.update(raw=raw, full=self.post(raw) if self.post else raw, levels={})
            else:
                if self.transformed(document):
                    # Qt's filtered sampling of rotated/scaled layers depends on where each scanline
                    # starts: refresh whole rows so the result matches a full render.
                    area = QRect(0, area.top(), full.width(), area.height())
                render_scene(document, document.current_frame, self.paper, effects=document.animation_enabled,
                             target=state['raw'], clip=area)
                if self.post:
                    _paste(state['full'], area.topLeft(), self.post(state['raw'].copy(area)))
                for factor_level, reduced in state['levels'].items():
                    factor = 1 << factor_level
                    aligned = _aligned(area, factor, full)
                    _paste(reduced, QPoint(aligned.left() // factor, aligned.top() // factor),
                           reduce(state['full'].copy(aligned), factor))
            state['stamps'] = stamps
        self.dirty = QRect()
        self.states.move_to_end(key)
        if level and level not in state['levels']:
            state['levels'][level] = reduce(state['full'], 1 << level)
        self.trim()
        return state['levels'][level] if level else state['full']

    def trim(self):
        def size(state):
            images = {id(image): image for image in [state['raw'], state['full'], *state['levels'].values()]}
            return sum(image.sizeInBytes() for image in images.values())
        total = sum(size(state) for state in self.states.values())
        while total > self.BUDGET and len(self.states) > 1:
            _, state = self.states.popitem(last=False)
            total -= size(state)


class ReducedView:
    def __init__(self):
        self.state = None
        self.dirty = QRect()

    def mark(self, rect):
        """Document-space area changed by a stroke (used for incremental updates)."""
        self.dirty = rect if self.dirty.isNull() else self.dirty.united(rect)

    def layers(self, document, level):
        """Reduced flattening of the current frame's layers, updated incrementally."""
        factor = 1 << level
        structure = (id(document), level, document.width, document.height,
                     tuple((layer.id, layer.visible, layer.opacity, layer.blend) for layer in document.layers))
        stamps = tuple(layer.image.cacheKey() for layer in document.layers)
        state = self.state
        full = QRect(0, 0, document.width, document.height)
        if state is None or state['structure'] != structure:
            state = self.state = {'structure': structure, 'stamps': stamps,
                                  'image': reduce(flatten(document.layers, full), factor)}
        elif state['stamps'] != stamps:
            area = self.dirty.intersected(full)
            if area.isEmpty():
                state['image'] = reduce(flatten(document.layers, full), factor)
            else:
                aligned = _aligned(area, factor, full)
                _paste(state['image'], QPoint(aligned.left() // factor, aligned.top() // factor),
                       reduce(flatten(document.layers, aligned), factor))
            state['stamps'] = stamps
        self.dirty = QRect()
        return state['image']
