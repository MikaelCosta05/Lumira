"""2D skeletons: ready-made rigs, posing (FK, IK, translation) and rest editing.

Bones keep the original project format: rest pose as start point, length and
angle, plus per-frame keys {'frame', 'angle', 'x', 'y'} relative to the parent.
"""
import math
import uuid

from PyQt6.QtCore import QPointF, QRectF

from animation import bone_transform, interpolate

LEFT, RIGHT = ' esq.', ' dir.'

TEMPLATE_CHOICES = [('Osso livre (arrastar)', 'free'), ('Esqueleto humano', 'human'),
                    ('Braço com mão', 'arm'), ('Perna com pé', 'leg'), ('Cauda / corrente', 'tail')]


def _human():
    bones = [('hip', 'Quadril', None, (0, 0), (0, -.07)),
             ('torso', 'Tronco', 'hip', (0, -.07), (0, -.29)),
             ('neck', 'Pescoço', 'torso', (0, -.29), (0, -.35)),
             ('head', 'Cabeça', 'neck', (0, -.35), (0, -.48))]
    for side, s in ((LEFT, 1), (RIGHT, -1)):
        bones += [(f'shoulder{side}', 'Ombro' + side, 'torso', (0, -.27), (s * .1, -.27)),
                  (f'arm{side}', 'Braço' + side, f'shoulder{side}', (s * .1, -.27), (s * .125, -.11)),
                  (f'forearm{side}', 'Antebraço' + side, f'arm{side}', (s * .125, -.11), (s * .14, .04)),
                  (f'hand{side}', 'Mão' + side, f'forearm{side}', (s * .14, .04), (s * .15, .1)),
                  (f'thigh{side}', 'Coxa' + side, 'hip', (s * .055, 0), (s * .065, .23)),
                  (f'shin{side}', 'Canela' + side, f'thigh{side}', (s * .065, .23), (s * .065, .45)),
                  (f'foot{side}', 'Pé' + side, f'shin{side}', (s * .065, .45), (s * .11, .48))]
    return bones


TEMPLATES = {
    'human': _human,
    'arm': lambda: [('shoulder', 'Ombro', None, (0, 0), (.18, .02)), ('arm', 'Braço', 'shoulder', (.18, .02), (.5, .05)),
                    ('forearm', 'Antebraço', 'arm', (.5, .05), (.8, .06)), ('hand', 'Mão', 'forearm', (.8, .06), (.95, .07))],
    'leg': lambda: [('thigh', 'Coxa', None, (0, 0), (0, .45)), ('shin', 'Canela', 'thigh', (0, .45), (0, .88)),
                    ('foot', 'Pé', 'shin', (0, .88), (.13, .95))],
    'tail': lambda: [(f'tail{n}', f'Cauda {n + 1}', f'tail{n - 1}' if n else None,
                      (sum(.24 * .85 ** k for k in range(n)), 0), (sum(.24 * .85 ** k for k in range(n + 1)), 0))
                     for n in range(6)],
}


# ------------------------------------------------------------------ basics

def find(document, ident):
    return next((b for b in document.scene['bones'] if b['id'] == ident), None)


def children(document, ident):
    return [b for b in document.scene['bones'] if b.get('parent') == ident]


def descendants(document, ident):
    result, pending = [], [ident]
    while pending:
        current = pending.pop()
        for child in children(document, current):
            if child['id'] not in [b['id'] for b in result]:
                result.append(child)
                pending.append(child['id'])
    return result


def rest_end(bone):
    radians = math.radians(bone['base_angle'])
    return QPointF(bone['x'] + math.cos(radians) * bone['length'], bone['y'] + math.sin(radians) * bone['length'])


def world_points(document, bone, frame):
    pose = bone_transform(document, bone, frame)
    return pose.map(QPointF(bone['x'], bone['y'])), pose.map(rest_end(bone))


def make_bone(name, start, end, parent='', layer=''):
    return {'id': uuid.uuid4().hex, 'name': name, 'layer': layer, 'parent': parent or '',
            'x': start.x(), 'y': start.y(), 'length': math.hypot(end.x() - start.x(), end.y() - start.y()),
            'base_angle': math.degrees(math.atan2(end.y() - start.y(), end.x() - start.x())), 'keys': []}


def to_rest(document, parent_id, point, frame):
    """Map a world point into the rest space of a bone's parent."""
    parent = find(document, parent_id) if parent_id else None
    return bone_transform(document, parent, frame).inverted()[0].map(point) if parent else QPointF(point)


def create_bone(document, start, end, frame, parent='', layer=None):
    bones = document.scene['bones']
    if layer is None:
        active = document.layers[document.active].id
        layer = '' if any(b.get('layer') == active for b in bones) else active
    bone = make_bone(f'Osso {len(bones) + 1}', to_rest(document, parent, start, frame),
                     to_rest(document, parent, end, frame), parent, layer)
    bones.append(bone)
    return bone


def add_template(document, kind, rect):
    """Create a ready-made rig fitted inside `rect` (document coordinates)."""
    spec = TEMPLATES[kind]()
    xs = [p[0] for item in spec for p in item[3:5]]
    ys = [p[1] for item in spec for p in item[3:5]]
    width, height = max(xs) - min(xs) or 1e-6, max(ys) - min(ys) or 1e-6
    scale = min(rect.width() / width if max(xs) > min(xs) else math.inf, rect.height() / height if max(ys) > min(ys) else math.inf)
    if not math.isfinite(scale):
        scale = rect.height()
    origin = QPointF(rect.center().x() - (min(xs) + width / 2) * scale, rect.center().y() - (min(ys) + height / 2) * scale)
    ids, created = {}, []
    for key, name, parent, start, end in spec:
        bone = make_bone(name, origin + QPointF(*start) * scale, origin + QPointF(*end) * scale, ids.get(parent, ''))
        ids[key] = bone['id']
        created.append(bone)
    document.scene['bones'].extend(created)
    return created


# ----------------------------------------------------------------- posing

def values(bone, frame):
    return interpolate(bone.get('keys', []), frame, {'angle': 0., 'x': 0., 'y': 0.})


def set_key(bone, frame, **changes):
    current = values(bone, frame)
    current.update(changes)
    keys = bone.setdefault('keys', [])
    easing = next((k.get('easing', 'linear') for k in keys if k['frame'] == frame), 'linear')
    keys[:] = [k for k in keys if k['frame'] != frame]
    keys.append({'frame': frame, 'easing': easing, **current})
    keys.sort(key=lambda k: k['frame'])


def wrap(radians):
    return (radians + math.pi) % (2 * math.pi) - math.pi


def angle_of(origin, point):
    return math.atan2(point.y() - origin.y(), point.x() - origin.x())


def rotate_towards(document, bone, frame, previous, point):
    joint = world_points(document, bone, frame)[0]
    delta = wrap(angle_of(joint, point) - angle_of(joint, previous))
    set_key(bone, frame, angle=values(bone, frame)['angle'] + math.degrees(delta))


def translate(document, bone, frame, delta):
    parent = find(document, bone.get('parent'))
    if parent:
        inverse = bone_transform(document, parent, frame).inverted()[0]
        delta = inverse.map(delta) - inverse.map(QPointF())
    current = values(bone, frame)
    set_key(bone, frame, x=current['x'] + delta.x(), y=current['y'] + delta.y())


def is_limb_end(bone):
    return bone['name'].startswith(('Mão', 'Pé'))


def ik_chain(document, bone, include_self):
    """Bones that bend for IK: two links above (and optionally including) the effector."""
    chain = [bone] if include_self else []
    current = bone
    while len(chain) < 2 and current.get('parent'):
        current = find(document, current['parent'])
        if current is None:
            break
        chain.append(current)
    return chain


def solve_ik(document, bone, frame, target, include_self=True, iterations=14):
    """Cyclic coordinate descent: the bone's tip reaches toward `target`.

    With include_self=False (hands and feet) the limb bends and the end keeps its
    angle relative to the forearm or shin."""
    chain = ik_chain(document, bone, include_self)
    for _ in range(iterations):
        for link in chain:
            effector = world_points(document, bone, frame)[1]
            joint = world_points(document, link, frame)[0]
            if math.hypot(effector.x() - joint.x(), effector.y() - joint.y()) < 1e-6:
                continue
            delta = wrap(angle_of(joint, target) - angle_of(joint, effector))
            set_key(link, frame, angle=values(link, frame)['angle'] + math.degrees(delta))
        effector = world_points(document, bone, frame)[1]
        if math.hypot(effector.x() - target.x(), effector.y() - target.y()) < .5:
            break
    return chain


def reset_pose(document, frame, bones=None):
    for bone in bones or document.scene['bones']:
        set_key(bone, frame, angle=0., x=0., y=0.)


def mirror_pose(document, frame):
    """Swap left/right poses of bones named '… esq.' / '… dir.', mirroring angles."""
    bones = document.scene['bones']
    snapshot = {b['id']: values(b, frame) for b in bones}
    by_name = {b['name']: b for b in bones}
    for bone in bones:
        name = bone['name']
        if name.endswith(LEFT):
            other = by_name.get(name[:-len(LEFT)] + RIGHT)
        elif name.endswith(RIGHT):
            other = by_name.get(name[:-len(RIGHT)] + LEFT)
        else:
            value = snapshot[bone['id']]
            set_key(bone, frame, angle=-value['angle'], x=-value['x'], y=value['y'])
            continue
        if other:
            value = snapshot[other['id']]
            set_key(bone, frame, angle=-value['angle'], x=-value['x'], y=value['y'])


def copy_pose(document, source_frame, frame):
    for bone in document.scene['bones']:
        set_key(bone, frame, **values(bone, source_frame))


# ------------------------------------------------------------ rest editing

def shift_subtree(document, bone, delta):
    for item in [bone] + descendants(document, bone['id']):
        item['x'] += delta.x()
        item['y'] += delta.y()


def edit_rest_tip(document, bone, frame, point):
    """Move a bone's tip in its rest pose; attached children follow."""
    inverse = bone_transform(document, bone, frame).inverted()[0]
    tip = inverse.map(point)
    old = rest_end(bone)
    bone['length'] = max(1., math.hypot(tip.x() - bone['x'], tip.y() - bone['y']))
    bone['base_angle'] = math.degrees(math.atan2(tip.y() - bone['y'], tip.x() - bone['x']))
    new = rest_end(bone)
    for child in children(document, bone['id']):
        if math.hypot(child['x'] - old.x(), child['y'] - old.y()) < 1.5:
            shift_subtree(document, child, new - old)


def edit_rest_move(document, bone, frame, delta):
    """Move a bone (and its children) in the rest pose without keying."""
    inverse = bone_transform(document, bone, frame).inverted()[0]
    shift_subtree(document, bone, inverse.map(delta) - inverse.map(QPointF()))


def delete_bone(document, ident):
    doomed = {ident} | {b['id'] for b in descendants(document, ident)}
    document.scene['bones'][:] = [b for b in document.scene['bones'] if b['id'] not in doomed]


# --------------------------------------------------------------- picking

def hit_test(document, frame, view, position, radius=9.):
    """Nearest bone under the cursor: (bone, 'tip' | 'start' | 'body') or None."""
    best = None
    for bone in document.scene['bones']:
        start, end = (view.map(p) for p in world_points(document, bone, frame))
        candidates = [('tip', math.hypot(end.x() - position.x(), end.y() - position.y()), 0)]
        if not bone.get('parent'):
            candidates.append(('start', math.hypot(start.x() - position.x(), start.y() - position.y()), 1))
        dx, dy = end.x() - start.x(), end.y() - start.y()
        span = dx * dx + dy * dy
        if span > 1e-6:
            t = max(0., min(1., ((position.x() - start.x()) * dx + (position.y() - start.y()) * dy) / span))
            closest = QPointF(start.x() + dx * t, start.y() + dy * t)
            candidates.append(('body', math.hypot(closest.x() - position.x(), closest.y() - position.y()), 2))
        for part, distance, priority in candidates:
            if distance <= radius and (best is None or (priority, distance) < (best[2], best[3])):
                best = (bone, part, priority, distance)
    return (best[0], best[1]) if best else None


def nearest_tip(document, frame, view, position, radius=12.):
    best = None
    for bone in document.scene['bones']:
        end = world_points(document, bone, frame)[1]
        screen = view.map(end)
        distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
        if distance <= radius and (best is None or distance < best[1]):
            best = (bone, distance, end)
    return (best[0], best[2]) if best else (None, None)


def fit_rect(document, point=None, fraction=.8):
    height = document.height * fraction
    center = point or QPointF(document.width / 2, document.height / 2)
    return QRectF(center.x() - height / 4, center.y() - height / 2, height / 2, height)
