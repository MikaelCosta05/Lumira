"""Raster cels, animation metadata, bounded history and portable projects."""
import copy
import json
import os
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter

from guides import default_guides
from i18n import tr


M = QPainter.CompositionMode
BLEND_MODES = [('Normal', 'normal', M.CompositionMode_SourceOver), ('Multiplicar', 'multiply', M.CompositionMode_Multiply),
               ('Tela', 'screen', M.CompositionMode_Screen), ('Sobrepor', 'overlay', M.CompositionMode_Overlay),
               ('Escurecer', 'darken', M.CompositionMode_Darken), ('Clarear', 'lighten', M.CompositionMode_Lighten),
               ('Subexposição de cor', 'dodge', M.CompositionMode_ColorDodge),
               ('Superexposição de cor', 'burn', M.CompositionMode_ColorBurn),
               ('Luz forte', 'hard_light', M.CompositionMode_HardLight), ('Luz suave', 'soft_light', M.CompositionMode_SoftLight),
               ('Diferença', 'difference', M.CompositionMode_Difference), ('Exclusão', 'exclusion', M.CompositionMode_Exclusion),
               ('Adição (subexposição linear)', 'add', M.CompositionMode_Plus)]
BLEND_KEYS = {key for _, key, _ in BLEND_MODES}
BLEND_NAMES = {key: label for label, key, _ in BLEND_MODES}
BLEND_COMPOSITION = {key: mode for _, key, mode in BLEND_MODES}
WORKERS = max(1, min(8, (os.cpu_count() or 2)))


_BLANK_PNG = {}


def _is_blank(image):
    import numpy as np
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    return not np.frombuffer(bits, np.uint8).any()


def encode_png(image):
    """PNG bytes of a layer. Fully transparent layers of one size share the same (cached) bytes."""
    size = (image.width(), image.height(), image.format())
    blank = size in _BLANK_PNG or image.format() == QImage.Format.Format_ARGB32_Premultiplied
    if blank and _is_blank(image):
        if size not in _BLANK_PNG:
            _BLANK_PNG[size] = _encode(image)
        return _BLANK_PNG[size]
    return _encode(image)


def _encode(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise OSError('Falha ao salvar uma camada.')
    return bytes(data)


_BLANK_DECODED = {}


def decode_png(data):
    """Image of a stored layer. Empty layers (very common in comic pages) are decoded once per size."""
    key = hash(data) if len(data) < 400_000 else None
    if key in _BLANK_DECODED and _BLANK_DECODED[key][0] == data:
        return QImage(_BLANK_DECODED[key][1])
    # QImageReader releases the GIL while decoding (QImage.fromData does not), so layers load in parallel.
    array = QByteArray(data)
    buffer = QBuffer(array)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    image = QImageReader(buffer, b'PNG').read()
    if image.isNull():
        return image
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if key is not None and _is_blank(image):
        _BLANK_DECODED[key] = (data, image)
    return image


def parallel(function, items):
    """Qt releases the GIL while encoding/decoding images, so layers are processed side by side."""
    items = list(items)
    if len(items) < 2:
        return [function(item) for item in items]
    with ThreadPoolExecutor(min(WORKERS, len(items))) as pool:
        return list(pool.map(function, items))


def draw_layer(painter, layer, opacity=1., origin=None, source=None):
    """Draw a raster layer with its blend mode and opacity."""
    painter.setOpacity(layer.opacity * opacity)
    painter.setCompositionMode(BLEND_COMPOSITION.get(layer.blend, M.CompositionMode_SourceOver))
    if source is None:
        painter.drawImage(0, 0, layer.image)
    else:
        painter.drawImage(origin, layer.image, source)
    painter.setCompositionMode(M.CompositionMode_SourceOver)


@dataclass
class Layer:
    name: str
    image: QImage
    visible: bool = True
    opacity: float = 1.
    locked: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    content: bool = False
    kind: str = 'raster'
    shadow: dict = field(default_factory=dict)
    blend: str = 'normal'
    alpha_lock: bool = False

    @property
    def is_shadow(self):
        return self.kind == 'shadow'

    def copy(self):
        return Layer(self.name, QImage(self.image), self.visible, self.opacity, self.locked, self.id, self.content,
                     self.kind, dict(self.shadow), self.blend, self.alpha_lock)


@dataclass
class Frame:
    layers: list
    duration: int = 100

    def copy(self):
        return Frame([layer.copy() for layer in self.layers], self.duration)


class Document:
    def __init__(self, width=1920, height=1080):
        self.width, self.height = width, height
        self.frames = [Frame([self.blank_layer(tr('Camada 1'))])]
        self.current_frame = self.active = 0
        self.paper_visible = True
        self.animation_enabled = False
        self.onion_skin = True
        self.onion_before, self.onion_after, self.onion_opacity = 1, 1, .28
        self.name = 'Sem título'
        self.dpi = 72
        self.scene = {'camera': [], 'layers': {}, 'bones': [], 'transitions': [],
                      'tags': [], 'audio': [], 'subtitles': [], 'comic': {}}
        # Drawing aids are view metadata: saved with the project, outside undo.
        self.guides = default_guides()
        self.assets = {}
        self.undo_stack, self.redo_stack = [], []
        self.preview_layer = None  # shadow layer being painted: shown as a quick tint
        self.revision = self.saved_revision = self.counter = 0
        self.path = None
        # PNG data of layer images as last saved/loaded (by QImage.cacheKey): unchanged layers
        # are written again without being compressed again.
        self.png_cache = {}

    @property
    def layers(self):
        return self.frames[self.current_frame].layers

    @layers.setter
    def layers(self, value):
        self.frames[self.current_frame].layers = value

    @property
    def modified(self):
        return self.revision != self.saved_revision

    @property
    def total_ms(self):
        return sum(frame.duration for frame in self.frames)

    def frame_start(self, index):
        return sum(f.duration for f in self.frames[:index]) / 1000

    def frame_at(self, seconds):
        ms = max(0, seconds * 1000)
        for index, frame in enumerate(self.frames):
            if ms < frame.duration:
                return index, ms / frame.duration
            ms -= frame.duration
        return len(self.frames) - 1, 0.

    def blank_layer(self, name):
        image = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        if image.isNull():
            raise ValueError('Não foi possível criar a tela nesse tamanho.')
        image.fill(0)
        return Layer(name, image)

    def shadow_layer(self, name='Sombras', style='soft'):
        from shading import settings_for
        layer = self.blank_layer(name)
        layer.kind, layer.shadow = 'shadow', settings_for(style)
        return layer

    @property
    def has_shadow_layers(self):
        return any(layer.is_shadow and layer.visible for layer in self.layers)

    @property
    def needs_composite(self):
        """Shadow layers and blend modes are rendered on a flattened image, not straight to the view."""
        return any(layer.visible and (layer.is_shadow or layer.blend != 'normal') for layer in self.layers)

    def snapshot(self):
        return ([f.copy() for f in self.frames], self.current_frame, self.active,
                self.paper_visible, self.animation_enabled, copy.deepcopy(self.scene),
                dict(self.assets), self.revision)

    def checkpoint(self):
        self.undo_stack.append(self.snapshot())
        limit = max(1, min(24, 64 * 1024 * 1024 //
                    (self.width * self.height * 4 * len(self.layers) * len(self.frames))))
        del self.undo_stack[:-limit]
        self.redo_stack.clear()

    def changed(self):
        self.counter += 1
        self.revision = self.counter

    def restore(self, value):
        frames, self.current_frame, self.active, self.paper_visible, self.animation_enabled, scene, assets, self.revision = value
        self.frames = [f.copy() for f in frames]
        self.scene, self.assets = copy.deepcopy(scene), dict(assets)

    def clone(self):
        result = Document(self.width, self.height)
        result.restore(self.snapshot())
        result.dpi, result.name, result.onion_skin = self.dpi, self.name, self.onion_skin
        result.onion_before, result.onion_after, result.onion_opacity = self.onion_before, self.onion_after, self.onion_opacity
        result.guides = copy.deepcopy(self.guides)
        return result

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.restore(self.undo_stack.pop())
            return True
        return False

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.restore(self.redo_stack.pop())
            return True
        return False

    def sync_layers(self):
        """Layer structure is shared; each frame keeps its own raster cels."""
        template = self.layers
        for frame in self.frames:
            if frame is self.frames[self.current_frame]:
                continue
            images = {layer.id: layer for layer in frame.layers}
            rebuilt = []
            for layer in template:
                new = layer.copy()
                if layer.id in images:
                    new.image, new.content = QImage(images[layer.id].image), images[layer.id].content
                else:
                    new.image, new.content = self.blank_layer(layer.name).image, False
                rebuilt.append(new)
            frame.layers = rebuilt

    def shift_keys(self, index, delta):
        tracks = [self.scene['camera']] + list(self.scene['layers'].values())
        tracks += [bone.get('keys', []) for bone in self.scene['bones']]
        for track in tracks:
            if delta < 0:
                track[:] = [k for k in track if k['frame'] != index]
            for key in track:
                if key['frame'] >= index:
                    key['frame'] += delta
        for tag in self.scene['tags']:
            tag['from'] = max(0, min(len(self.frames) - 1, tag['from'] + (delta if tag['from'] >= index else 0)))
            tag['to'] = max(tag['from'], min(len(self.frames) - 1, tag['to'] + (delta if tag['to'] >= index else 0)))

    def remap_frames(self, order):
        """Reorder frames: `order[new] = old`. Keyframes and tags follow their frames."""
        new_index = {old: new for new, old in enumerate(order)}
        self.frames = [self.frames[old] for old in order]
        tracks = [self.scene['camera']] + list(self.scene['layers'].values())
        tracks += [bone.get('keys', []) for bone in self.scene['bones']]
        for track in tracks:
            for key in track:
                key['frame'] = new_index.get(key['frame'], key['frame'])
            track.sort(key=lambda k: k['frame'])
        for tag in self.scene['tags']:
            ends = sorted((new_index.get(tag['from'], tag['from']), new_index.get(tag['to'], tag['to'])))
            tag['from'], tag['to'] = ends
        self.current_frame = new_index.get(self.current_frame, self.current_frame)

    def move_frame(self, source, target):
        """Move one frame so that it ends up at index `target`."""
        count = len(self.frames)
        source, target = max(0, min(count - 1, source)), max(0, min(count - 1, target))
        if source == target:
            return
        order = list(range(count))
        order.insert(target, order.pop(source))
        self.remap_frames(order)
        self.current_frame = target

    def reverse_frames(self, start, end):
        start, end = sorted((max(0, start), min(len(self.frames) - 1, end)))
        order = list(range(len(self.frames)))
        order[start:end + 1] = order[start:end + 1][::-1]
        self.remap_frames(order)

    def duplicate_frames(self, start, end):
        """Copy frames start..end right after the range."""
        start, end = sorted((max(0, start), min(len(self.frames) - 1, end)))
        if len(self.frames) + end - start + 1 > 600:
            raise ValueError('Limite de 600 quadros por projeto.')
        copies = [self.frames[i].copy() for i in range(start, end + 1)]
        self.shift_keys(end + 1, len(copies))
        self.frames[end + 1:end + 1] = copies
        self.current_frame = end + 1

    def delete_frames(self, start, end):
        start, end = sorted((max(0, start), min(len(self.frames) - 1, end)))
        if end - start + 1 >= len(self.frames):
            raise ValueError('O projeto precisa de pelo menos um quadro.')
        for _ in range(end - start + 1):
            self.frames.pop(start)
            self.shift_keys(start, -1)
        self.current_frame = min(start, len(self.frames) - 1)

    def set_fps(self, fps):
        duration = max(1, round(1000 / max(1, fps)))
        for frame in self.frames:
            frame.duration = duration

    def add_frame(self, empty=False):
        if len(self.frames) >= 600:
            raise ValueError('Limite de 600 quadros por projeto.')
        index = self.current_frame + 1
        frame = self.frames[self.current_frame].copy()
        if empty:
            for layer in frame.layers:
                layer.image = self.blank_layer(layer.name).image
                layer.content = False
        self.frames.insert(index, frame)
        self.shift_keys(index, 1)
        self.current_frame = index

    def delete_frame(self):
        if len(self.frames) > 1:
            index = self.current_frame
            self.frames.pop(index)
            self.shift_keys(index, -1)
            self.current_frame = min(index, len(self.frames) - 1)

    def composite(self, paper=None, frame_index=None, subtitles=True):
        from animation import render_scene
        frame_index = self.current_frame if frame_index is None else frame_index
        return render_scene(self, frame_index, self.paper_visible if paper is None else paper,
                            subtitles=subtitles, effects=self.animation_enabled)

    def save(self, path, mark_saved=True):
        path = Path(path)
        metadata = {'version': 2, 'width': self.width, 'height': self.height,
            'active': self.active, 'paper': self.paper_visible, 'frames': [],
            'current_frame': self.current_frame, 'animation': self.animation_enabled,
            'onion': self.onion_skin, 'onion_range': [self.onion_before, self.onion_after, self.onion_opacity],
            'scene': self.scene, 'name': self.name, 'dpi': self.dpi,
            'assets': list(self.assets), 'guides': self.guides}
        fd, temporary = tempfile.mkstemp(prefix='.studio-', suffix='.tmp', dir=path.parent)
        os.close(fd)
        try:
            images = {layer.image.cacheKey(): layer.image for frame in self.frames for layer in frame.layers}
            missing = [key for key in images if key not in self.png_cache]
            encoded = dict(zip(missing, parallel(encode_png, [images[key] for key in missing])))
            self.png_cache = {key: self.png_cache.get(key) or encoded[key] for key in images}
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for frame_index, frame in enumerate(self.frames):
                    infos = []
                    for index, layer in enumerate(frame.layers):
                        filename = f'frames/{frame_index}/{index}.png'
                        # PNG is already compressed: storing it as is saves time and costs no space.
                        archive.writestr(filename, self.png_cache[layer.image.cacheKey()],
                                         compress_type=zipfile.ZIP_STORED)
                        infos.append({'name': layer.name, 'visible': layer.visible,
                            'opacity': layer.opacity, 'locked': layer.locked, 'file': filename,
                            'id': layer.id, 'content': layer.content, 'kind': layer.kind, 'shadow': layer.shadow,
                            'blend': layer.blend, 'alpha_lock': layer.alpha_lock})
                    metadata['frames'].append({'duration': frame.duration, 'layers': infos})
                for name, data in self.assets.items():
                    archive.writestr(f'audio/{name}.wav', data)
                archive.writestr('document.json', json.dumps(metadata, ensure_ascii=False))
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if mark_saved:
            self.path = str(path)
            self.saved_revision = self.revision

    @classmethod
    def load(cls, path):
        with zipfile.ZipFile(path) as archive:
            value = json.loads(archive.read('document.json'))
            width, height = value['width'], value['height']
            if value.get('version') not in (1, 2) or not (1 <= width <= 8192 and 1 <= height <= 8192) or width * height > 24_000_000:
                raise ValueError('Projeto incompatível ou com dimensões inválidas.')
            document = cls(width, height)
            frame_infos = value.get('frames', [{'duration': 100, 'layers': value.get('layers', [])}])
            if not 1 <= len(frame_infos) <= 600:
                raise ValueError('Quantidade de quadros inválida.')
            document.frames = []
            for frame_info in frame_infos:
                if not 1 <= len(frame_info['layers']) <= 64:
                    raise ValueError('Quantidade de camadas inválida.')
            files = list(dict.fromkeys(info['file'] for frame_info in frame_infos for info in frame_info['layers']))
            raw = {name: archive.read(name) for name in files}
            decoded = dict(zip(files, parallel(decode_png, [raw[name] for name in files])))
            for frame_info in frame_infos:
                layers = []
                for info in frame_info['layers']:
                    image = decoded[info['file']]
                    if image.isNull() or image.width() != width or image.height() != height:
                        raise ValueError('Camada inválida no projeto.')
                    document.png_cache[image.cacheKey()] = raw[info['file']]
                    layers.append(Layer(info['name'], image,
                        bool(info['visible']), max(0., min(1., float(info['opacity']))), bool(info.get('locked', False)),
                        info.get('id', uuid.uuid4().hex), bool(info.get('content', True)),
                        'shadow' if info.get('kind') == 'shadow' else 'raster',
                        dict(info.get('shadow') or {}) if isinstance(info.get('shadow'), dict) else {},
                        info.get('blend') if info.get('blend') in BLEND_KEYS else 'normal', bool(info.get('alpha_lock', False))))
                document.frames.append(Frame(layers, max(1, min(600000, int(frame_info['duration'])))))
            document.active = max(0, min(len(document.frames[0].layers) - 1, int(value['active'])))
            document.current_frame = max(0, min(len(document.frames)-1, value.get('current_frame', 0)))
            document.paper_visible = bool(value['paper'])
            document.animation_enabled = bool(value.get('animation', False))
            document.onion_skin = bool(value.get('onion', True))
            before, after, opacity = (value.get('onion_range') or [1, 1, .28])[:3]
            document.onion_before, document.onion_after = max(0, min(5, int(before))), max(0, min(5, int(after)))
            document.onion_opacity = max(.05, min(1., float(opacity)))
            document.scene.update(value.get('scene', {}))
            guides = value.get('guides', {})
            if isinstance(guides, dict):
                document.guides.update({k: v for k, v in guides.items() if k in document.guides})
                if not isinstance(document.guides.get('symmetry'), dict):
                    document.guides['symmetry'] = {'mode': 'none', 'x': None, 'y': None, 'count': 6}
                points = document.guides['points']
                document.guides['points'] = [[float(x), float(y)] for x, y in points[:3]] if isinstance(points, list) else []
            document.name, document.dpi = value.get('name', 'Sem título'), value.get('dpi', 72)
            document.assets = {name: archive.read(f'audio/{name}.wav') for name in value.get('assets', [])}
            document.path = str(path)
            return document
