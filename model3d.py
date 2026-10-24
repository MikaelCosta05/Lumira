"""Posable figure from a rigged glTF file, with the same interface as the mannequin.

Clicking a part selects the bone that most influences it; dragging rotates that
bone. Animations stored in the file become ready-made poses.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np

import gltf
import mannequin
import render3d

ROOT = Path(__file__).resolve().parent
MODEL_FOLDER = ROOT / 'assets' / '3D'
REST = 'Pose de repouso'


def library_models():
    """(display name, path) of the models placed in assets/3D."""
    if not MODEL_FOLDER.exists():
        return []
    return sorted(((gltf.readable_name(path), str(path)) for path in MODEL_FOLDER.glob('*.glb')), key=lambda item: item[0].lower())


@lru_cache(maxsize=3)
def _load(path):
    return gltf.load(path, texture_limit=2048)


def _rotation_part(matrix):
    block = matrix[:3, :3]
    return block / np.maximum(np.linalg.norm(block, axis=0), 1e-12)[None, :]


class RigFigure:
    kind = 'gltf'
    floor_default = True
    default_view = (30., 10.)
    can_mirror = False

    def __init__(self, path):
        self.path = str(path)
        self.model = _load(self.path)
        self.model_name = self.model.name
        self.pose = {}
        self.deform = set(self.model.deform)
        self.gpu = None

    # --------------------------------------------------------------- pose
    @property
    def rigged(self):
        return self.model.rigged

    def presets(self):
        names = [REST]
        for animation in self.model.animations:
            names.append(f"Animação: {animation['name']}")
        return names

    def apply_preset(self, name, fraction=0.):
        if name == REST or not name:
            self.pose = {}
            return
        title = name.split(': ', 1)[-1]
        animation = next((a for a in self.model.animations if a['name'] == title), None)
        if animation:
            sampled = gltf.sample_animation(self.model, animation, animation['duration'] * max(0., min(1., fraction)))
            self.pose = {node: {k: np.asarray(v, float) for k, v in values.items()} for node, values in sampled.items()}

    def serialize_pose(self):
        return {self.model.nodes[i].name: {k: [round(float(x), 6) for x in v] for k, v in values.items()}
                for i, values in self.pose.items()}

    def load_pose(self, data):
        names = {node.name: node.index for node in self.model.nodes}
        self.pose = {names[name]: {k: np.asarray(v, float) for k, v in values.items()}
                     for name, values in data.items() if name in names}

    def world(self):
        return self.model.world(self.pose)

    def joint_at_id(self, identifier):
        return int(identifier) if int(identifier) in self.deform else None

    def label(self, key):
        name = self.model.nodes[key].name
        for prefix in ('mixamorig:', 'mixamorig_', 'DEF-', 'ORG-'):
            name = name.replace(prefix, '')
        return name

    def joint_position(self, key):
        return self.world()[key][:3, 3]

    def local_rotation(self, key):
        node = self.model.nodes[key]
        return gltf.quaternion_matrix(self.pose.get(key, {}).get('r', node.rotation))

    def rotate_joint(self, key, drag):
        node = self.model.nodes[key]
        world = self.world()
        parent = _rotation_part(world[node.parent]) if node.parent is not None else np.eye(3)
        local = parent.T @ drag @ parent @ self.local_rotation(key)
        self.pose.setdefault(key, {})['r'] = gltf.matrix_quaternion(local)

    def rotation_values(self, key):
        rest = gltf.quaternion_matrix(self.model.nodes[key].rotation)
        return mannequin.euler(rest.T @ self.local_rotation(key))

    def set_rotation_value(self, key, axis, value):
        values = self.rotation_values(key)
        values[axis] = value
        rest = gltf.quaternion_matrix(self.model.nodes[key].rotation)
        self.pose.setdefault(key, {})['r'] = gltf.matrix_quaternion(rest @ mannequin.rotation(*values))

    def reset_joint(self, key):
        self.pose.pop(key, None)

    def bone_segments(self):
        world = self.world()
        segments = []
        for key in self.deform:
            node = self.model.nodes[key]
            for child in node.children:
                if child in self.deform:
                    segments.append((key, world[key][:3, 3], world[child][:3, 3]))
        return segments

    # ------------------------------------------------------------- render
    def bounds(self, focus=False):
        low, high = render3d.bounds(self.model, self.world())
        return (low + high) / 2, float(np.linalg.norm(high - low) / 2)

    def render(self, camera, width, height, light=(-40., 35.), supersample=1, cast_shadows=True, floor=None,
               line_width=1., outline='parts', textures=True):
        if self.gpu is None:
            self.gpu = render3d.GPUModel(self.model)
        return render3d.render(self.gpu, self.world(), camera, width, height, camera.light(*light), supersample,
                               cast_shadows, self.floor_default if floor is None else floor, textures, outline, line_width)
