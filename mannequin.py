"""Posable 3D mannequin rendered in software with numpy.

The figure is built from oriented ellipsoids attached to a joint hierarchy, like
a wooden artist's mannequin. Rays are intersected analytically, so there is no
OpenGL dependency. Shading produces a darkness map that the shadow styles of
`shading.py` turn into soft, hard, cel, hatching, halftone or comic shadows.
"""
import math

import numpy as np
from PyQt6.QtGui import QPainter

import shading

# ------------------------------------------------------------------ maths


def rotation(x, y, z):
    """Pose rotation in degrees: R = Rz · Rx · Ry (twist innermost)."""
    x, y, z = np.radians([x, y, z])
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ rx @ ry


def euler(matrix):
    x = math.asin(max(-1., min(1., matrix[2, 1])))
    y = math.atan2(-matrix[2, 0], matrix[2, 2])
    z = math.atan2(-matrix[0, 1], matrix[1, 1])
    return [math.degrees(x), math.degrees(y), math.degrees(z)]


def axis_angle(axis, degrees):
    axis = np.asarray(axis, float)
    axis = axis / (np.linalg.norm(axis) or 1)
    angle = math.radians(degrees)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * k @ k


def mirror(values):
    x, y, z = values
    return [x, -y, -z]


def mirror_names(pose):
    """Pose seen in a mirror: left and right joints swap and rotations flip."""
    result = {}
    for name, value in pose.items():
        if name.endswith(('_e', '_d')):
            name = name[:-1] + ('d' if name.endswith('_e') else 'e')
        result[name] = mirror(value)
    return result


# --------------------------------------------------------------- skeleton

class Joint:
    def __init__(self, name, label, parent, offset, shapes, rest=(0., 0., 0.)):
        self.name, self.label, self.parent = name, label, parent
        self.offset = np.array(offset, float)
        self.shapes = [(np.array(c, float), np.array(r, float)) for c, r in shapes]
        self.rest = list(rest)


PROPORTIONS = {
    'Adulto': dict(head=1, shoulders=1, hips=1, arm=1, leg=1, torso=1, thick=1),
    'Heroico': dict(head=.93, shoulders=1.22, hips=.95, arm=1.05, leg=1.1, torso=1.06, thick=1.18),
    'Feminino': dict(head=.97, shoulders=.88, hips=1.12, arm=.96, leg=1.03, torso=.95, thick=.88),
    'Infantil': dict(head=1.18, shoulders=.8, hips=.85, arm=.7, leg=.64, torso=.74, thick=.76),
    'Chibi': dict(head=1.9, shoulders=.78, hips=.88, arm=.5, leg=.45, torso=.6, thick=.95),
}

SIDES = (('e', 1, ' esq.'), ('d', -1, ' dir.'))
FINGERS = [('indicador', 'Indicador', 3.2, (4.2, 2.6, 2.0), .95), ('medio', 'Médio', 1.1, (4.6, 2.9, 2.1), .97),
           ('anelar', 'Anelar', -1.0, (4.3, 2.7, 2.0), .92), ('minimo', 'Mínimo', -3.0, (3.4, 2.1, 1.8), .82)]


def build_skeleton(proportion='Adulto'):
    p = PROPORTIONS.get(proportion, PROPORTIONS['Adulto'])
    head, shoulders, hips, arm, leg, torso, thick = (p[k] for k in ('head', 'shoulders', 'hips', 'arm', 'leg', 'torso', 'thick'))
    hand = (arm + thick) / 2
    joints = []

    def add(*args, **kwargs):
        joints.append(Joint(*args, **kwargs))

    add('quadril', 'Quadril', None, (0, 9.7 + 84 * leg, 0), [((0, 1, 0), (15 * hips, 10 * torso, 10.5 * thick))])
    add('abdomen', 'Abdômen', 'quadril', (0, 7 * torso, 0),
        [((0, 6 * torso, 0), (12.5 * (shoulders + hips) / 2, 10 * torso, 8.5 * thick))])
    add('peito', 'Peito', 'abdomen', (0, 13 * torso, 0), [((0, 10 * torso, .5), (16 * shoulders, 14 * torso, 9.5 * thick))])
    add('pescoco', 'Pescoço', 'peito', (0, 22 * torso, 0), [((0, 3.5, 0), (4.6 * thick, 6, 4.6 * thick))])
    add('cabeca', 'Cabeça', 'pescoco', (0, 7, 0), [
        ((0, 9.5 * head, .5 * head), (8.6 * head, 10.5 * head, 9.6 * head)),
        ((0, 4.2 * head, 4.2 * head), (6.2 * head, 4.5 * head, 5.2 * head)),
        ((0, 7.6 * head, 9.6 * head), (1.3 * head, 2.2 * head, 1.6 * head)),
        ((0, 11 * head, 8.1 * head), (6 * head, 1.3 * head, 1.8 * head)),
        ((8.6 * head, 8.4 * head, -.5 * head), (1.2 * head, 2.6 * head, 1.9 * head)),
        ((-8.6 * head, 8.4 * head, -.5 * head), (1.2 * head, 2.6 * head, 1.9 * head))])
    for side, s, label in SIDES:
        add(f'ombro_{side}', 'Ombro' + label, 'peito', (3 * s, 18 * torso, 0),
            [((6 * shoulders * s, 0, 0), (6 * shoulders, 2.4 * thick, 2.4 * thick)),
             ((12 * shoulders * s, -1, 0), (5.2 * thick, 5.2 * thick, 5.2 * thick))])
        add(f'braco_{side}', 'Braço' + label, f'ombro_{side}', (12 * shoulders * s, -1.5, 0),
            [((0, -14 * arm, 0), (4.8 * thick, 14.5 * arm, 4.8 * thick))])
        add(f'antebraco_{side}', 'Antebraço' + label, f'braco_{side}', (0, -28 * arm, 0),
            [((0, 0, 0), (4 * thick, 4 * thick, 4 * thick)), ((0, -12.5 * arm, 0), (4 * thick, 13 * arm, 3.8 * thick))])
        add(f'mao_{side}', 'Mão' + label, f'antebraco_{side}', (0, -25 * arm, 0),
            [((0, 0, 0), (2.6 * hand, 2.6 * hand, 2.6 * hand)), ((0, -5.2 * hand, .3 * hand), (1.9 * hand, 5.6 * hand, 4.4 * hand))])
        for key, finger, z, lengths, radius in FINGERS:
            parent, offset = f'mao_{side}', (0, -10.6 * hand, z * hand)
            for index, length in enumerate(lengths):
                name = f'{key}{index + 1}_{side}'
                add(name, f'{finger} {index + 1}{label}', parent, offset,
                    [((0, -length / 2 * hand, 0), (radius * hand, (length / 2 + .45) * hand, radius * hand))])
                parent, offset = name, (0, -length * hand, 0)
        parent, offset = f'mao_{side}', (-.9 * s * hand, -3.2 * hand, 3.1 * hand)
        for index, length in enumerate((3.6, 3.0, 2.4)):
            name = f'polegar{index + 1}_{side}'
            rest = mirror([-26., 0., -12.]) if s < 0 else [-26., 0., -12.]
            add(name, f'Polegar {index + 1}{label}', parent, offset,
                [((0, -length / 2 * hand, 0), (1.15 * hand, (length / 2 + .5) * hand, 1.15 * hand))],
                rest=rest if index == 0 else (0, 0, 0))
            parent, offset = name, (0, -length * hand, 0)
        add(f'coxa_{side}', 'Coxa' + label, 'quadril', (8.5 * hips * s, -3, 0),
            [((0, -21 * leg, 0), (7.2 * thick, 22.5 * leg, 7.4 * thick))])
        add(f'canela_{side}', 'Canela' + label, f'coxa_{side}', (0, -43 * leg, 0),
            [((0, 0, 0), (5.4 * thick, 5.4 * thick, 5.4 * thick)), ((0, -20 * leg, -.5), (5 * thick, 21 * leg, 5.4 * thick))])
        add(f'pe_{side}', 'Pé' + label, f'canela_{side}', (0, -41 * leg, 0),
            [((0, 0, 0), (3.8 * thick, 3.8 * thick, 3.8 * thick)), ((0, -3.5, 4.5), (4.4 * thick, 3.2, 10.5))])
    return joints


MODELS = {
    'Corpo inteiro': {'root': 'quadril', 'floor': True},
    'Cabeça e busto': {'root': 'peito', 'only': ('peito', 'pescoco', 'cabeca', 'ombro_', 'braco_'), 'floor': False,
                       'focus': ('cabeca', 'pescoco'), 'view': (20., 5.)},
    'Mão direita': {'root': 'mao_d', 'floor': False, 'rest': (0., 0., 180.), 'view': (70., 10.)},
    'Mão esquerda': {'root': 'mao_e', 'floor': False, 'rest': (0., 0., 180.), 'view': (-70., 10.)},
}


def model_joints(model, proportion):
    spec = MODELS[model]
    joints = build_skeleton(proportion)
    by_name = {j.name: j for j in joints}
    keep, pending = [], [spec['root']]
    while pending:
        name = pending.pop(0)
        joint = by_name[name]
        if 'only' in spec and not name.startswith(spec['only']):
            continue
        keep.append(joint)
        pending += [j.name for j in joints if j.parent == name]
    root = keep[0]
    root.parent = None
    if root.name != 'quadril':
        root.offset = np.zeros(3)
    root.rest = list(spec.get('rest', root.rest))
    return keep


# ------------------------------------------------------------------ poses

def _both(**values):
    pose = {}
    for name, value in values.items():
        pose[f'{name}_e'] = list(value)
        pose[f'{name}_d'] = mirror(value)
    return pose


def _hand(curls, spread=None, thumb=(0, 0, 0)):
    """Finger curl per phalanx (positive closes toward the palm) for both hands."""
    pose = {}
    for key, *_ in FINGERS:
        for index, amount in enumerate(curls.get(key, (0, 0, 0))):
            value = [spread.get(key, 0) if spread and index == 0 else 0, 0, -amount]
            pose.update(_both(**{f'{key}{index + 1}': value}))
    for index, value in enumerate(thumb if isinstance(thumb[0], (list, tuple)) else (thumb, (0, 0, 0), (0, 0, 0))):
        pose.update(_both(**{f'polegar{index + 1}': value}))
    return pose


def _with(base, other, prefixes):
    """`base` hand pose with the fingers named by `prefixes` taken from `other`."""
    return {**base, **{k: v for k, v in other.items() if k.startswith(prefixes)}}


RELAXED_HAND = _hand({'indicador': (12, 18, 10), 'medio': (16, 22, 12), 'anelar': (20, 26, 14), 'minimo': (24, 28, 16)},
                     thumb=((0, 0, -8), (0, 0, -10), (0, 0, -8)))
FIST = _hand({k: (85, 100, 70) for k, *_ in FINGERS}, thumb=((-20, 0, -45), (0, 0, -40), (0, 0, -35)))

HAND_POSES = {
    'Mão aberta': _hand({}, {'indicador': -7, 'anelar': 5, 'minimo': 11}, thumb=((0, 0, 12), (0, 0, 0), (0, 0, 0))),
    'Mão relaxada': RELAXED_HAND,
    'Punho fechado': FIST,
    'Apontando': _with(FIST, _hand({}), ('indicador',)),
    'Paz e amor (V)': _with(FIST, _hand({}, {'indicador': -9, 'medio': 6}), ('indicador', 'medio')),
    'Joinha': _with(FIST, _hand({}, thumb=((0, 0, 25), (0, 0, 0), (0, 0, 0))), ('polegar',)),
    'Pinça / segurando': _hand({'indicador': (40, 45, 30), 'medio': (35, 40, 25), 'anelar': (35, 40, 25), 'minimo': (35, 40, 25)},
                               thumb=((-10, 0, -30), (0, 0, -20), (0, 0, -15))),
    'Garra': _hand({k: (40, 60, 50) for k, *_ in FINGERS}, {'indicador': -8, 'anelar': 6, 'minimo': 12},
                   thumb=((0, 0, -20), (0, 0, -30), (0, 0, -30))),
}


def _merge(*parts):
    pose = {}
    for part in parts:
        pose.update(part)
    return pose


BODY_POSES = {
    'Em pé (relaxado)': _merge(_both(braco=(0, 0, 8), antebraco=(-10, 0, 0)), RELAXED_HAND),
    'T-pose': _both(braco=(0, 0, 88)),
    'A-pose': _merge(_both(braco=(0, 0, 42), antebraco=(-5, 0, 0)), RELAXED_HAND),
    'Andando': _merge(RELAXED_HAND, {
        'coxa_e': [-25, 0, 2], 'canela_e': [10, 0, 0], 'pe_e': [-8, 0, 0],
        'coxa_d': [15, 0, -2], 'canela_d': [25, 0, 0], 'pe_d': [12, 0, 0],
        'braco_e': [18, 0, 7], 'antebraco_e': [-12, 0, 0], 'braco_d': [-20, 0, -7], 'antebraco_d': [-28, 0, 0],
        'quadril': [0, -5, 0], 'peito': [0, 8, 0], 'cabeca': [0, -3, 0]}),
    'Correndo': _merge(FIST, {
        'coxa_e': [-62, 0, 3], 'canela_e': [75, 0, 0], 'pe_e': [-10, 0, 0],
        'coxa_d': [28, 0, -3], 'canela_d': [95, 0, 0], 'pe_d': [25, 0, 0],
        'braco_e': [45, 0, 10], 'antebraco_e': [-85, 0, 0], 'braco_d': [-60, 0, -10], 'antebraco_d': [-95, 0, 0],
        'abdomen': [10, 0, 0], 'peito': [6, 10, 0], 'quadril': [0, -8, 0], 'cabeca': [-10, -5, 0]}),
    'Sentado': _merge(RELAXED_HAND, _both(coxa=(-88, 0, 5), canela=(88, 0, 0), braco=(-18, 0, 10), antebraco=(-55, 0, 0))),
    'Acenando': _merge(RELAXED_HAND, _both(braco=(0, 0, 8), antebraco=(-10, 0, 0)),
                       {k: v for k, v in HAND_POSES['Mão aberta'].items() if k.endswith('_d')},
                       {'braco_d': [0, 0, -82], 'antebraco_d': [0, 0, -95], 'mao_d': [0, 0, -5], 'cabeca': [0, -10, 5],
                        'peito': [0, 0, 4]}),
    'Pulando': _merge(HAND_POSES['Mão aberta'], _both(braco=(0, 0, 150), antebraco=(0, 0, 12), coxa=(-40, 0, 10),
                                                      canela=(75, 0, 0), pe=(35, 0, 0)), {'abdomen': [-8, 0, 0], 'cabeca': [-12, 0, 0]}),
    'Guarda de luta': _merge(FIST, {
        'coxa_e': [-18, 0, 6], 'canela_e': [20, 0, 0], 'coxa_d': [12, 0, -10], 'canela_d': [22, 0, 0],
        'quadril': [0, 25, 0], 'abdomen': [8, 0, 0], 'peito': [0, -20, 0], 'cabeca': [12, -5, 0],
        'braco_e': [-55, 0, 22], 'antebraco_e': [-120, 0, 0], 'braco_d': [-35, 0, -28], 'antebraco_d': [-135, 0, 0]}),
    'Pensativo': _merge(RELAXED_HAND, _both(braco=(0, 0, 8), antebraco=(-12, 0, 0)), {
        'braco_d': [-40, 0, -12], 'antebraco_d': [-145, 0, 0], 'mao_d': [-20, 0, 0], 'cabeca': [10, -10, -8],
        'abdomen': [6, 0, 0]}),
    'Apontando': _merge(RELAXED_HAND, _both(braco=(0, 0, 8), antebraco=(-10, 0, 0)),
                        {k: v for k, v in HAND_POSES['Apontando'].items() if k.endswith('_d')},
                        {'braco_d': [-85, 0, -8], 'antebraco_d': [-5, 0, 0], 'peito': [0, -10, 0], 'cabeca': [0, -12, 0]}),
}

HEAD_POSES = {
    'De frente': {},
    'Olhando para cima': {'cabeca': [-25, 0, 0], 'pescoco': [-10, 0, 0]},
    'Olhando para baixo': {'cabeca': [25, 0, 0], 'pescoco': [10, 0, 0]},
    'Virado (3/4)': {'cabeca': [0, -35, 0], 'pescoco': [0, -10, 0]},
    'Inclinado': {'cabeca': [5, -10, 18]},
}


def presets_for(model):
    if model.startswith('Mão'):
        return HAND_POSES
    if model == 'Cabeça e busto':
        return HEAD_POSES
    return BODY_POSES


# ----------------------------------------------------------------- figure

class Figure:
    kind = 'mannequin'
    can_mirror = True
    rigged = True

    def __init__(self, model='Corpo inteiro', proportion='Adulto'):
        self.model, self.proportion = model, proportion
        self.joints = model_joints(model, proportion)
        self.by_name = {j.name: j for j in self.joints}
        self.pose = {}
        self.apply_preset(next(iter(presets_for(model))))

    def rebuild(self, model, proportion):
        """Change model or proportions; the pose is kept when the model stays the same."""
        pose, same = self.pose, model == self.model
        self.model, self.proportion = model, proportion
        self.joints = model_joints(model, proportion)
        self.by_name = {j.name: j for j in self.joints}
        if same:
            self.apply_pose(pose)
        else:
            self.apply_preset(next(iter(presets_for(model))))

    @property
    def model_name(self):
        return self.model

    @property
    def floor_default(self):
        return MODELS[self.model]['floor']

    @property
    def default_view(self):
        return MODELS[self.model].get('view', (25., 8.))

    def presets(self):
        return list(presets_for(self.model))

    def apply_preset(self, name, fraction=0.):
        self.pose = {k: list(v) for k, v in presets_for(self.model).get(name, {}).items() if k in self.by_name}

    def serialize_pose(self):
        return {k: [round(float(v), 2) for v in value] for k, value in self.pose.items()}

    def load_pose(self, data):
        self.apply_pose(data)

    def joint_at_id(self, identifier):
        return self.joints[int(identifier)].name if 0 <= int(identifier) < len(self.joints) else None

    def label(self, key):
        return self.by_name[key].label

    def rotation_values(self, key):
        return list(self.pose.get(key, [0., 0., 0.]))

    def set_rotation_value(self, key, axis, value):
        values = self.rotation_values(key)
        values[axis] = float(value)
        self.pose[key] = values

    def reset_joint(self, key):
        self.pose.pop(key, None)

    def bone_segments(self):
        return []

    def render(self, camera, width, height, light=(-40., 35.), supersample=1, cast_shadows=True, floor=None,
               line_width=1., outline='parts', textures=True):
        return render(self, camera, width, height, light, supersample, cast_shadows, floor, line_width, outline)

    def apply_pose(self, pose):
        self.pose = {k: list(v) for k, v in pose.items() if k in self.by_name}

    def mirrored(self):
        """Swap left and right sides of the pose."""
        self.apply_pose(mirror_names(self.pose))

    def local(self, joint):
        return rotation(*joint.rest) @ rotation(*self.pose.get(joint.name, (0, 0, 0)))

    def world(self):
        result = {}
        for joint in self.joints:
            if joint.parent is None:
                result[joint.name] = (self.local(joint), joint.offset.copy())
            else:
                parent_rotation, parent_position = result[joint.parent]
                result[joint.name] = (parent_rotation @ self.local(joint), parent_position + parent_rotation @ joint.offset)
        return result

    def primitives(self):
        world = self.world()
        centers, matrices, owners, bounds = [], [], [], []
        for index, joint in enumerate(self.joints):
            rotation_matrix, position = world[joint.name]
            for center, radii in joint.shapes:
                centers.append(position + rotation_matrix @ center)
                matrices.append(rotation_matrix @ np.diag(1 / radii))
                owners.append(index)
                bounds.append(radii.max())
        return (np.array(centers, np.float32), np.array(matrices, np.float32),
                np.array(owners, np.int32), np.array(bounds, np.float32))

    def joint_position(self, name):
        return self.world()[name][1]

    def rotate_joint(self, name, drag):
        """Apply a world-space rotation to a joint, stored as its local pose."""
        joint = self.by_name[name]
        world = self.world()
        parent = world[joint.parent][0] if joint.parent else np.eye(3)
        frame = parent @ rotation(*joint.rest)
        local = frame.T @ drag @ frame @ rotation(*self.pose.get(name, (0, 0, 0)))
        self.pose[name] = euler(local)

    def bounds(self, focus=False):
        centers, matrices, owners, radii = self.primitives()
        names = MODELS[self.model].get('focus') if focus else None
        if names:
            keep = np.isin(owners, [i for i, j in enumerate(self.joints) if j.name in names])
            centers, radii = centers[keep], radii[keep]
        low = (centers - radii[:, None]).min(axis=0)
        high = (centers + radii[:, None]).max(axis=0)
        return (low + high) / 2, float(np.linalg.norm(high - low) / 2) * (1.6 if names else 1)


# ----------------------------------------------------------------- camera

class Camera:
    def __init__(self, yaw=25., pitch=8., distance=300., target=(0, 90, 0), fov=30.):
        self.yaw, self.pitch, self.distance, self.fov = yaw, pitch, distance, fov
        self.target = np.array(target, float)

    def fit(self, figure, view=False):
        if view:
            self.yaw, self.pitch = figure.default_view
        center, radius = figure.bounds(focus=True)
        self.target = center
        self.distance = radius / math.sin(math.radians(self.fov) / 2) * 1.08

    def basis(self):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        offset = np.array([math.cos(pitch) * math.sin(yaw), math.sin(pitch), math.cos(pitch) * math.cos(yaw)])
        position = self.target + offset * self.distance
        forward = -offset
        right = np.cross(forward, [0, 1, 0])
        right /= np.linalg.norm(right) or 1
        up = np.cross(right, forward)
        return position, forward, right, up

    def project(self, point, width, height):
        position, forward, right, up = self.basis()
        relative = np.asarray(point) - position
        depth = relative @ forward
        if depth <= 1e-6:
            return None
        tangent = math.tan(math.radians(self.fov) / 2)
        u = relative @ right / depth / (tangent * width / height)
        v = relative @ up / depth / tangent
        return (u + 1) / 2 * width, (1 - v) / 2 * height

    def light(self, azimuth, elevation):
        """Direction toward the light, relative to the view (0° = from the camera)."""
        _, forward, right, up = self.basis()
        a, e = math.radians(azimuth), math.radians(elevation)
        direction = math.cos(e) * math.sin(a) * right + math.sin(e) * up - math.cos(e) * math.cos(a) * forward
        return direction / np.linalg.norm(direction)


# --------------------------------------------------------------- renderer

def _downsample(array, factor):
    if factor == 1:
        return array.astype(np.float32)
    height, width = array.shape[0] // factor, array.shape[1] // factor
    return array[:height * factor, :width * factor].reshape(height, factor, width, factor).mean(axis=(1, 3)).astype(np.float32)


def render(figure, camera, width, height, light=(-40., 35.), supersample=1, cast_shadows=True,
           floor=None, line_width=1., outline='parts'):
    """Geometry pass. Returns coverage, darkness, floor shadow, outline and pick ids."""
    ss = max(1, int(supersample))
    w, h = max(1, int(width)) * ss, max(1, int(height)) * ss
    position, forward, right, up = (v.astype(np.float32) for v in camera.basis())
    tangent = math.tan(math.radians(camera.fov) / 2)
    xs = (((np.arange(w) + .5) / w) * 2 - 1).astype(np.float32) * tangent * w / h
    ys = (1 - ((np.arange(h) + .5) / h) * 2).astype(np.float32) * tangent
    rays = forward + xs[None, :, None] * right + ys[:, None, None] * up
    rays /= np.linalg.norm(rays, axis=2, keepdims=True)
    centers, matrices, owners, radii = figure.primitives()
    depth = np.full((h, w), np.inf, np.float32)
    hit = np.full((h, w), -1, np.int32)
    for index in range(len(centers)):
        relative = centers[index] - position
        distance = float(relative @ forward)
        if distance > radii[index] * 1.05:
            u, v = relative @ right / distance, relative @ up / distance
            spread = radii[index] / math.sqrt(max(distance ** 2 - radii[index] ** 2, 1e-6)) * 1.15
            x0 = int(((u - spread) / (tangent * w / h) + 1) / 2 * w) - 2
            x1 = int(((u + spread) / (tangent * w / h) + 1) / 2 * w) + 3
            y0 = int((1 - (v + spread) / tangent) / 2 * h) - 2
            y1 = int((1 - (v - spread) / tangent) / 2 * h) + 3
            x0, x1, y0, y1 = max(0, x0), min(w, x1), max(0, y0), min(h, y1)
            if x0 >= x1 or y0 >= y1:
                continue
        else:
            x0, x1, y0, y1 = 0, w, 0, h
        local_rays = rays[y0:y1, x0:x1] @ matrices[index]
        origin = (position - centers[index]) @ matrices[index]
        a = np.einsum('ijk,ijk->ij', local_rays, local_rays)
        b = local_rays @ origin
        c = float(origin @ origin) - 1
        discriminant = b * b - a * c
        t = (-b - np.sqrt(np.maximum(discriminant, 0))) / a
        closer = (discriminant > 0) & (t > 0) & (t < depth[y0:y1, x0:x1])
        depth[y0:y1, x0:x1][closer] = t[closer]
        hit[y0:y1, x0:x1][closer] = index
    body = hit >= 0
    normals = np.zeros((h, w, 3), np.float32)
    for index in np.unique(hit[body]):
        mask = hit == index
        local = (position - centers[index]) @ matrices[index] + depth[mask][:, None] * (rays[mask] @ matrices[index])
        normal = local @ matrices[index].T
        normals[mask] = normal / np.linalg.norm(normal, axis=1, keepdims=True)
    light_direction = camera.light(*light).astype(np.float32)
    lambert = np.clip(normals @ light_direction, 0, 1)
    points = position + depth[body][:, None] * rays[body]
    lit = np.ones(len(points), np.float32)
    floor_shadow = np.zeros((h, w), np.float32)
    floor_mask = np.zeros((h, w), bool)
    floor = MODELS[figure.model]['floor'] if floor is None else floor
    if floor:
        center, size = figure.bounds()
        with np.errstate(divide='ignore', invalid='ignore'):
            t_floor = -position[1] / rays[..., 1]
        floor_points = position + np.nan_to_num(t_floor, posinf=0, neginf=0)[..., None] * rays
        reach = np.hypot(floor_points[..., 0] - center[0], floor_points[..., 2] - center[2])
        floor_mask = (t_floor > 0) & (t_floor < depth) & (reach < size * 2.2) & np.isfinite(t_floor)
    if cast_shadows:
        samples = [points + normals[body] * .2]
        if floor_mask.any():
            samples.append(floor_points[floor_mask] + np.array([0, .1, 0], np.float32))
        results = []
        for sample in samples:
            blocked = np.zeros(len(sample), bool)
            for index in range(len(centers)):
                local = (sample - centers[index]) @ matrices[index]
                direction = light_direction @ matrices[index]
                a = float(direction @ direction)
                b = local @ direction
                c = np.einsum('ij,ij->i', local, local) - 1
                blocked |= (b * b - a * c > 0) & (c > 0) & (b < 0)
            results.append(blocked)
        lit = (~results[0]).astype(np.float32)
        if len(results) > 1:
            fade = np.clip(1 - reach[floor_mask] / (size * 2.2), 0, 1) ** .5
            floor_shadow[floor_mask] = results[1] * fade
    darkness = np.zeros((h, w), np.float32)
    darkness[body] = 1 - lambert[body] * lit
    joint_ids = np.where(body, owners[np.maximum(hit, 0)], -1)
    edges = np.zeros((h, w), bool)
    if outline != 'none':
        ids = joint_ids if outline == 'parts' else body.astype(np.int32)
        horizontal, vertical = ids[:, 1:] != ids[:, :-1], ids[1:, :] != ids[:-1, :]
        edges[:, 1:] |= horizontal
        edges[:, :-1] |= horizontal
        edges[1:, :] |= vertical
        edges[:-1, :] |= vertical
        extra = int(round(line_width * ss)) - 2
        if extra > 0:
            from scipy import ndimage
            edges = ndimage.binary_dilation(edges, iterations=extra)
    coverage = _downsample(body, ss)
    weighted = _downsample(darkness * body, ss)
    return {
        'alpha': coverage,
        'darkness': np.where(coverage > 0, weighted / np.maximum(coverage, 1e-6), 0).astype(np.float32),
        'floor': _downsample(floor_shadow, ss),
        'outline': _downsample(edges, ss),
        'ids': joint_ids[ss // 2::ss, ss // 2::ss][:int(height), :int(width)],
    }


def compose(result, settings):
    """Final colours: model tone, styled shadow, floor shadow and outline. Returns (rgb, alpha)."""
    alpha, darkness = result['alpha'], result['darkness']
    base_color = np.array([v / 255 for v in bytes.fromhex(settings.get('model_color', '#d8c3a5')[1:])], np.float32)
    if settings.get('use_albedo') and 'albedo' in result:
        base = result['albedo']
    else:
        base = np.empty(alpha.shape + (3,), np.float32)
        base[...] = base_color
    style = dict(shading.DEFAULT_SHADOW, **settings.get('shadow', {}))
    shadow_rgb, amount = shading.stylize(darkness, style, base)
    if shading.composition(style) == QPainter.CompositionMode.CompositionMode_Multiply:
        shadow_rgb = base * shadow_rgb
    rgb = base * (1 - amount[..., None]) + shadow_rgb * amount[..., None]
    floor_rgb, floor_amount = shading.stylize(result['floor'], style, np.full(alpha.shape + (3,), .82, np.float32))
    if style['style'] == 'colored':
        floor_rgb = np.full(alpha.shape + (3,), .4, np.float32)
    floor_alpha = floor_amount * (1 - alpha) * .85
    out_alpha = alpha + floor_alpha
    rgb = (rgb * alpha[..., None] + floor_rgb * floor_alpha[..., None]) / np.maximum(out_alpha, 1e-6)[..., None]
    line = result['outline'][..., None] * settings.get('line_opacity', 1.)
    line_color = np.array([v / 255 for v in bytes.fromhex(settings.get('line_color', '#2a2420')[1:])], np.float32)
    rgb = rgb * (1 - line) + line_color * line
    return rgb, np.maximum(out_alpha, line[..., 0])


def shadow_mask(result):
    """Darkness as painted alpha for a shadow layer (body shading plus floor shadow)."""
    return np.clip(result['darkness'] * result['alpha'] + result['floor'] * (1 - result['alpha']) * .85, 0, 1)
