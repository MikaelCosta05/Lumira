"""Minimal glTF 2.0 (.glb) reader for posable, rigged models.

Reads meshes (positions, normals, UVs, vertex colours, joints and weights),
the node hierarchy, skins, base-colour materials (metal/rough and the
spec/gloss extension) and animations, which become ready-made poses.
"""
import base64
import io
import json
import math
import struct
from pathlib import Path

import numpy as np

COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
NORMALIZE = {np.int8: 127., np.uint8: 255., np.int16: 32767., np.uint16: 65535.}


# ------------------------------------------------------------------ maths

def quaternion_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def matrix_quaternion(m):
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, .25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, .25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, .25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return q / (np.linalg.norm(q) or 1)


def compose(translation, rotation, scale):
    matrix = np.eye(4)
    matrix[:3, :3] = quaternion_matrix(rotation) * np.asarray(scale)[None, :]
    matrix[:3, 3] = translation
    return matrix


def decompose(matrix):
    translation = matrix[:3, 3].copy()
    scale = np.linalg.norm(matrix[:3, :3], axis=0)
    rotation = matrix_quaternion(matrix[:3, :3] / np.where(scale == 0, 1, scale)[None, :])
    return translation, rotation, scale


def slerp(a, b, t):
    a, b = np.asarray(a, float), np.asarray(b, float)
    dot = float(a @ b)
    if dot < 0:
        b, dot = -b, -dot
    if dot > .9995:
        result = a + (b - a) * t
    else:
        theta = math.acos(dot)
        result = (math.sin((1 - t) * theta) * a + math.sin(t * theta) * b) / math.sin(theta)
    return result / (np.linalg.norm(result) or 1)


# ------------------------------------------------------------------ model

class Node:
    __slots__ = ('index', 'name', 'parent', 'children', 'translation', 'rotation', 'scale', 'mesh', 'skin')

    def __init__(self, index, value):
        self.index, self.name = index, value.get('name') or f'Nó {index}'
        self.parent, self.children = None, list(value.get('children', []))
        if 'matrix' in value:
            self.translation, self.rotation, self.scale = decompose(np.array(value['matrix'], float).reshape(4, 4).T)
        else:
            self.translation = np.array(value.get('translation', [0, 0, 0]), float)
            self.rotation = np.array(value.get('rotation', [0, 0, 0, 1]), float)
            self.scale = np.array(value.get('scale', [1, 1, 1]), float)
        self.mesh, self.skin = value.get('mesh'), value.get('skin')


class Primitive:
    def __init__(self, positions, normals, uvs, colors, joints, weights, indices, material, node, skin):
        self.positions, self.normals, self.uvs, self.colors = positions, normals, uvs, colors
        self.joints, self.weights, self.indices = joints, weights, indices
        self.material, self.node, self.skin = material, node, skin


class Model:
    def __init__(self, path, nodes, primitives, skins, materials, images, animations):
        self.path, self.name = str(path), readable_name(path)
        self.nodes, self.primitives, self.skins = nodes, primitives, skins
        self.materials, self.images, self.animations = materials, images, animations
        self.roots = [n.index for n in nodes if n.parent is None]
        self.order = []
        pending = list(self.roots)
        while pending:
            index = pending.pop(0)
            self.order.append(index)
            pending.extend(nodes[index].children)
        self.deform = sorted({skin['joints'][j] for p in primitives if p.skin is not None
                              for j in np.unique(p.joints[p.weights > .01]) for skin in [skins[p.skin]]})
        self.triangles = sum(len(p.indices) // 3 for p in primitives)

    @property
    def rigged(self):
        return bool(self.deform)

    def world(self, pose=None):
        """World matrices of every node, with pose overrides {node: {'r': quat, 't': vec}}."""
        pose = pose or {}
        result = [None] * len(self.nodes)
        for index in self.order:
            node = self.nodes[index]
            override = pose.get(index, {})
            local = compose(override.get('t', node.translation), override.get('r', node.rotation),
                            override.get('s', node.scale))
            result[index] = local if node.parent is None else result[node.parent] @ local
        return result

    def joint_matrices(self, skin_index, world):
        skin = self.skins[skin_index]
        return np.stack([world[j] @ skin['inverse'][k] for k, j in enumerate(skin['joints'])]).astype(np.float32)


def readable_name(path):
    stem = Path(path).stem.replace('_-_', ' · ').replace('_', ' ').replace('  ', ' ')
    return stem[:1].upper() + stem[1:60]


# ---------------------------------------------------------------- reading

def _accessor(document, binary, index):
    accessor = document['accessors'][index]
    dtype = np.dtype(COMPONENTS[accessor['componentType']])
    width, count = WIDTHS[accessor['type']], accessor['count']
    if 'bufferView' in accessor:
        view = document['bufferViews'][accessor['bufferView']]
        offset = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
        stride = view.get('byteStride', 0)
        item = dtype.itemsize * width
        if stride and stride != item:
            raw = np.frombuffer(binary, np.uint8, (count - 1) * stride + item, offset)
            rows = np.lib.stride_tricks.as_strided(raw, (count, item), (stride, 1))
            data = np.ascontiguousarray(rows).view(dtype).reshape(count, width)
        else:
            data = np.frombuffer(binary, dtype, count * width, offset).reshape(count, width)
    else:
        data = np.zeros((count, width), dtype)
    sparse = accessor.get('sparse')
    if sparse:
        data = data.copy()
        indices_view = document['bufferViews'][sparse['indices']['bufferView']]
        values_view = document['bufferViews'][sparse['values']['bufferView']]
        where = np.frombuffer(binary, COMPONENTS[sparse['indices']['componentType']], sparse['count'],
                              indices_view.get('byteOffset', 0) + sparse['indices'].get('byteOffset', 0))
        values = np.frombuffer(binary, dtype, sparse['count'] * width,
                               values_view.get('byteOffset', 0) + sparse['values'].get('byteOffset', 0))
        data[where.astype(np.int64)] = values.reshape(-1, width)
    if accessor.get('normalized') and dtype.type in NORMALIZE:
        data = np.maximum(data.astype(np.float32) / NORMALIZE[dtype.type], -1)
    return data


def _image(document, binary, index, limit):
    from PIL import Image
    image = document['images'][index]
    if 'bufferView' in image:
        view = document['bufferViews'][image['bufferView']]
        raw = binary[view.get('byteOffset', 0):view.get('byteOffset', 0) + view['byteLength']]
    elif image.get('uri', '').startswith('data:'):
        raw = base64.b64decode(image['uri'].split(',', 1)[1])
    else:
        return None
    picture = Image.open(io.BytesIO(raw))
    picture.draft('RGB', (limit, limit))
    picture = picture.convert('RGBA')
    picture.thumbnail((limit, limit))
    return np.asarray(picture, np.uint8)


def _material(value):
    pbr = value.get('pbrMetallicRoughness', {})
    gloss = value.get('extensions', {}).get('KHR_materials_pbrSpecularGlossiness', {})
    factor = gloss.get('diffuseFactor', pbr.get('baseColorFactor', [1, 1, 1, 1]))
    texture = gloss.get('diffuseTexture', pbr.get('baseColorTexture'))
    return {'color': [float(v) for v in factor], 'texture': texture.get('index') if texture else None,
            'texcoord': texture.get('texCoord', 0) if texture else 0, 'double': bool(value.get('doubleSided')),
            'mask': value.get('alphaMode', 'OPAQUE') != 'OPAQUE', 'cutoff': float(value.get('alphaCutoff', .5))}


def _normals(positions, indices):
    normals = np.zeros_like(positions)
    triangles = positions[indices.reshape(-1, 3)]
    face = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    for corner in range(3):
        np.add.at(normals, indices.reshape(-1, 3)[:, corner], face)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def load(path, texture_limit=2048):
    data = Path(path).read_bytes()
    if data[:4] != b'glTF':
        raise ValueError('O arquivo não é um glTF binário (.glb).')
    length = struct.unpack_from('<I', data, 12)[0]
    document = json.loads(data[20:20 + length])
    binary = b''
    position = 20 + length
    while position + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from('<I4s', data, position)
        if chunk_type == b'BIN\x00':
            binary = data[position + 8:position + 8 + chunk_length]
            break
        position += 8 + chunk_length
    if 'KHR_draco_mesh_compression' in document.get('extensionsRequired', []):
        raise ValueError('Malhas com compressão Draco não são suportadas. Exporte sem compressão.')
    nodes = [Node(i, value) for i, value in enumerate(document.get('nodes', []))]
    for node in nodes:
        for child in node.children:
            nodes[child].parent = node.index
    skins = []
    for skin in document.get('skins', []):
        joints = skin['joints']
        inverse = (_accessor(document, binary, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
                   if 'inverseBindMatrices' in skin else np.tile(np.eye(4), (len(joints), 1, 1)))
        skins.append({'joints': joints, 'inverse': inverse.astype(np.float64)})
    textures = document.get('textures', [])
    materials = [_material(m) for m in document.get('materials', [])] or [_material({})]
    image_cache = {}
    for material in materials:
        if material['texture'] is not None and material['texture'] < len(textures):
            source = textures[material['texture']].get('source')
            if source is not None and source not in image_cache:
                try:
                    image_cache[source] = _image(document, binary, source, texture_limit)
                except Exception:  # an unreadable texture falls back to the base colour
                    image_cache[source] = None
            material['image'] = source
        else:
            material['image'] = None
    primitives = []
    for node in nodes:
        if node.mesh is None:
            continue
        for primitive in document['meshes'][node.mesh]['primitives']:
            if primitive.get('mode', 4) != 4:
                continue
            attributes = primitive['attributes']
            positions = _accessor(document, binary, attributes['POSITION']).astype(np.float32)
            indices = (_accessor(document, binary, primitive['indices']).reshape(-1).astype(np.uint32)
                       if 'indices' in primitive else np.arange(len(positions), dtype=np.uint32))
            indices = indices[:len(indices) // 3 * 3]
            normals = (_accessor(document, binary, attributes['NORMAL']).astype(np.float32) if 'NORMAL' in attributes
                       else _normals(positions, indices).astype(np.float32))
            material = primitive.get('material', 0) if document.get('materials') else 0
            texcoord = f"TEXCOORD_{materials[material]['texcoord']}"
            uvs = (_accessor(document, binary, attributes[texcoord]).astype(np.float32) if texcoord in attributes
                   else np.zeros((len(positions), 2), np.float32))
            colors = np.ones((len(positions), 4), np.float32)
            if 'COLOR_0' in attributes:
                color = _accessor(document, binary, attributes['COLOR_0']).astype(np.float32)
                colors[:, :color.shape[1]] = color
            skin = node.skin if node.skin is not None and 'JOINTS_0' in attributes and 'WEIGHTS_0' in attributes else None
            if skin is not None:
                joints = _accessor(document, binary, attributes['JOINTS_0']).astype(np.int32)
                weights = _accessor(document, binary, attributes['WEIGHTS_0']).astype(np.float32)
                weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-6)
            else:
                joints = np.zeros((len(positions), 4), np.int32)
                weights = np.zeros((len(positions), 4), np.float32)
            primitives.append(Primitive(positions, normals, uvs, colors, joints, weights, indices, material, node.index, skin))
    if not primitives:
        raise ValueError('O arquivo não contém malhas de triângulos.')
    animations = []
    for index, animation in enumerate(document.get('animations', [])):
        channels = []
        for channel in animation.get('channels', []):
            target = channel.get('target', {})
            if target.get('path') not in ('translation', 'rotation', 'scale') or 'node' not in target:
                continue
            sampler = animation['samplers'][channel['sampler']]
            times = _accessor(document, binary, sampler['input']).reshape(-1).astype(np.float64)
            values = _accessor(document, binary, sampler['output']).astype(np.float64)
            if sampler.get('interpolation') == 'CUBICSPLINE':
                values = values.reshape(len(times), 3, -1)[:, 1]
            channels.append((target['node'], target['path'], times, values, sampler.get('interpolation', 'LINEAR')))
        if channels:
            duration = max(c[2][-1] for c in channels if len(c[2]))
            animations.append({'name': animation.get('name') or f'Animação {index + 1}', 'channels': channels,
                               'duration': float(duration)})
    return Model(path, nodes, primitives, skins, materials, image_cache, animations)


def sample_animation(model, animation, time):
    """Pose overrides of an animation at `time` seconds."""
    pose = {}
    for node, path, times, values, interpolation in animation['channels']:
        if not len(times):
            continue
        if time <= times[0] or len(times) == 1:
            value = values[0]
        elif time >= times[-1]:
            value = values[-1]
        else:
            k = int(np.searchsorted(times, time) - 1)
            span = times[k + 1] - times[k]
            t = 0. if interpolation == 'STEP' or span <= 0 else (time - times[k]) / span
            value = slerp(values[k], values[k + 1], t) if path == 'rotation' else values[k] + (values[k + 1] - values[k]) * t
        key = {'translation': 't', 'rotation': 'r', 'scale': 's'}[path]
        pose.setdefault(node, {})[key] = np.array(value, float)
    return pose
