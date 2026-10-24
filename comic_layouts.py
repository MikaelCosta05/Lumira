"""Stylized comic page layouts: slanted cuts, bleeds, impact and dream borders, inset panels.

A page is split into tiers (top to bottom) and each tier into panels. Every cut is a straight
line, possibly slanted, and both sides are clipped half a gutter away from it, so gutters keep
the same width even on diagonals. Panels are convex polygons kept in reading order; a shape is
a dict ``{'points': [[x, y], ...], 'style': 'straight'|'round'|'wavy'|'jagged', 'inset': bool,
'bleed': bool}`` (JSON friendly, saved in the project).
"""
import math
import random

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainterPath, QPolygonF

STYLES = [
    ('Aleatório (surpreenda-me)', 'random'),
    ('Ação · cortes diagonais', 'action'),
    ('Mangá dinâmico', 'manga'),
    ('Cinematográfico (faixas largas)', 'cinema'),
    ('Impacto (quadro explosivo)', 'impact'),
    ('Clássico limpo', 'classic'),
    ('Suave (cantos arredondados)', 'soft'),
    ('Flashback / sonho (bordas onduladas)', 'dream'),
    ('Destaque com inserções', 'inset'),
    ('Splash com inserções', 'splash'),
]
STYLE_NAMES = {key: label for label, key in STYLES}

# tiers / panels per tier ranges, slants (fraction of the page width / tier height), extras.
PROFILES = {
    'classic': dict(tiers=(3, 3), cols=(1, 3), weights=(.85, 1.2), slant=0., cell_slant=0., bleed=0.),
    'action': dict(tiers=(3, 4), cols=(1, 3), weights=(.7, 1.5), slant=.09, cell_slant=.22, bleed=.45),
    'manga': dict(tiers=(3, 4), cols=(1, 3), weights=(.55, 1.8), slant=.05, cell_slant=.3, bleed=.55),
    'cinema': dict(tiers=(3, 5), cols=(1, 2), weights=(.8, 1.25), slant=0., cell_slant=0., bleed=.75, single=.7),
    'impact': dict(tiers=(3, 3), cols=(1, 3), weights=(.7, 1.3), slant=.05, cell_slant=.15, bleed=.2, impact=True),
    'soft': dict(tiers=(2, 4), cols=(1, 3), weights=(.8, 1.3), slant=0., cell_slant=0., bleed=0., shape='round'),
    'dream': dict(tiers=(2, 3), cols=(1, 2), weights=(.8, 1.3), slant=0., cell_slant=.08, bleed=0., shape='wavy'),
    'inset': dict(tiers=(2, 3), cols=(1, 2), weights=(.7, 1.2), slant=.03, cell_slant=.1, bleed=.3, insets=(1, 2),
                  feature=True),
}


# ------------------------------------------------------------------ geometry

def clip(points, nx, ny, limit):
    """Part of a convex polygon where nx*x + ny*y >= limit (Sutherland–Hodgman, one plane)."""
    result = []
    count = len(points)
    for index in range(count):
        p, q = points[index], points[(index + 1) % count]
        fp, fq = nx * p[0] + ny * p[1] - limit, nx * q[0] + ny * q[1] - limit
        if fp >= 0:
            result.append(p)
        if (fp >= 0) != (fq >= 0):
            t = fp / (fp - fq)
            result.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return result


def side_of(points, a, b, gap, positive):
    """Clip to one side of the line a→b, `gap` away from it (positive = the normal's side)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.
    nx, ny = dy / length, -dx / length
    if not positive:
        nx, ny = -nx, -ny
    return clip(points, nx, ny, nx * a[0] + ny * a[1] + gap)


def area(points):
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(points, points[1:] + points[:1]))) / 2


def bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def centroid(points):
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def rect_points(rect):
    return [(rect.left(), rect.top()), (rect.right(), rect.top()), (rect.right(), rect.bottom()), (rect.left(), rect.bottom())]


def shape(points, style='straight', inset=False, bleed=False):
    return {'points': [[round(x, 2), round(y, 2)] for x, y in points], 'style': style, 'inset': inset, 'bleed': bleed}


def shapes_from_rects(rects, radius=0.):
    return [shape(rect_points(rect), 'round' if radius > 0 else 'straight') | ({'radius': radius} if radius else {})
            for rect in rects]


def shape_bounds(item):
    return bounds([tuple(p) for p in item['points']])


def scaled_shapes(shapes, scale):
    """Copies of shapes at another size (previews)."""
    result = []
    for item in shapes:
        copy = dict(item, points=[[p[0] * scale, p[1] * scale] for p in item['points']])
        if 'radius' in copy:
            copy['radius'] = copy['radius'] * scale
        result.append(copy)
    return result


# ------------------------------------------------------------------ layout

def _weights(rng, count, low, high):
    return [rng.uniform(low, high) for _ in range(count)]


def _split_counts(rng, total, tiers):
    """Distribute `total` panels over tiers (1 to 4 each)."""
    counts = [1] * tiers
    for _ in range(total - tiers):
        options = [i for i, c in enumerate(counts) if c < 4]
        if not options:
            break
        counts[rng.choice(options)] += 1
    return counts


def stylized_layout(width, height, style='random', seed=None, margin=60, gutter=24, rtl=False, count=0, page_margin=0):
    """Panel shapes for a stylized page. `page_margin` is where bleeding panels stop (0 = page edge)."""
    rng = random.Random(seed)
    if style == 'random':
        style = rng.choice([key for _, key in STYLES if key != 'random'])
    for attempt in range(12):
        try:
            if style == 'splash':
                shapes = _splash(rng, width, height, margin, gutter, rtl, page_margin)
            else:
                shapes = _tiers(rng, PROFILES[style], width, height, margin, gutter, rtl, count, page_margin)
            if shapes:
                return style, shapes
        except ValueError:
            pass
        rng = random.Random(rng.random())
    raise ValueError('Não foi possível montar a página com essa margem e espaçamento.')


def _tiers(rng, profile, width, height, margin, gutter, rtl, count, page_margin):
    inner = QRectF(margin, margin, width - 2 * margin, height - 2 * margin)
    if inner.width() < 40 or inner.height() < 40:
        raise ValueError('A margem é maior que a página.')
    landscape = width > height * 1.3
    if count:
        tiers = max(1, min(count, round(math.sqrt(count * inner.height() / inner.width() * 1.1)), 5))
        if landscape:
            tiers = 1 if count <= 4 else 2
        columns = _split_counts(rng, count, tiers)
    else:
        tiers = 1 if landscape else rng.randint(*profile['tiers'])
        columns = []
        for _ in range(tiers):
            if landscape:
                columns.append(rng.randint(3, 4))
            elif rng.random() < profile.get('single', 0):
                columns.append(1)
            else:
                columns.append(rng.randint(*profile['cols']))
        if all(c == 1 for c in columns) and tiers < 3 and not landscape:
            columns[rng.randrange(tiers)] = 2
    weights = _weights(rng, tiers, *profile['weights'])
    if profile.get('feature') and tiers > 1:
        feature = rng.randrange(tiers)
        weights[feature] *= 1.9
        columns[feature] = 1
    total = sum(weights)
    available = inner.height()
    # Horizontal cuts: (left y, right y). Slant is limited so neighbouring cuts never cross.
    cuts, y = [], inner.top()
    heights = [available * w / total for w in weights]
    for index in range(tiers - 1):
        y += heights[index]
        room = min(heights[index], heights[index + 1]) * .55
        delta = max(-room, min(room, profile['slant'] * inner.width() * rng.uniform(-1, 1)))
        cuts.append(((inner.left() - 1, y - delta / 2), (inner.right() + 1, y + delta / 2)))
    page = rect_points(inner)
    shapes = []
    for tier in range(tiers):
        region = page
        if tier > 0:  # below the previous cut (horizontal cuts' normals point up)
            a, b = cuts[tier - 1]
            region = side_of(region, a, b, gutter / 2, False)
        if tier < tiers - 1:
            a, b = cuts[tier]
            region = side_of(region, a, b, gutter / 2, True)
        if len(region) < 3:
            raise ValueError('degenerate tier')
        box = bounds(region)
        widths = _weights(rng, columns[tier], .65, 1.5)
        x = box.left()
        vertical = []
        tier_height = box.height()
        for index in range(columns[tier] - 1):
            x += box.width() * widths[index] / sum(widths)
            neighbour = box.width() * min(widths[index], widths[index + 1]) / sum(widths)
            delta = max(-neighbour * .5, min(neighbour * .5, profile['cell_slant'] * tier_height * rng.uniform(-1, 1)))
            vertical.append(((x - delta / 2, box.top() - 1), (x + delta / 2, box.bottom() + 1)))
        row = []
        for column in range(columns[tier]):
            cell = region
            if column > 0:  # right of the previous cut (vertical cuts' normals point right)
                a, b = vertical[column - 1]
                cell = side_of(cell, a, b, gutter / 2, True)
            if column < columns[tier] - 1:
                a, b = vertical[column]
                cell = side_of(cell, a, b, gutter / 2, False)
            if len(cell) < 3 or area(cell) < inner.width() * inner.height() * .012:
                raise ValueError('panel too small')
            cell_box = bounds(cell)
            if cell_box.width() < gutter * 2 or cell_box.height() < gutter * 2:
                raise ValueError('panel too thin')
            row.append(shape(cell, profile.get('shape', 'straight')))
        shapes += row[::-1] if rtl else row
    _bleeds(rng, shapes, profile.get('bleed', 0), inner, width, height, page_margin)
    if profile.get('impact'):
        middle = [s for s in shapes if not s['bleed']] or shapes
        target = max(middle, key=lambda s: area([tuple(p) for p in s['points']]))
        target['style'] = 'jagged'
    if profile.get('insets'):
        _insets(rng, shapes, rng.randint(*profile['insets']), gutter, rtl)
    return shapes


def _bleeds(rng, shapes, chance, inner, width, height, page_margin):
    """Some panels touching the page border are extended past it (they bleed off the page)."""
    if chance <= 0:
        return
    edges = {'left': (0, inner.left(), page_margin), 'right': (0, inner.right(), width - page_margin),
             'top': (1, inner.top(), page_margin), 'bottom': (1, inner.bottom(), height - page_margin)}
    for item in shapes:
        if rng.random() > chance:
            continue
        touching = [name for name, (axis, value, _) in edges.items()
                    if sum(abs(p[axis] - value) < .6 for p in item['points']) >= 2]
        if not touching:
            continue
        for name in rng.sample(touching, k=min(len(touching), rng.randint(1, 2))):
            axis, value, target = edges[name]
            points = item['points']
            moved = []
            for index, point in enumerate(points):
                if abs(point[axis] - value) >= .6:
                    moved.append(point)
                    continue
                # Slide the corner along its other edge (a cut line), so gutters stay parallel.
                neighbours = [points[index - 1], points[(index + 1) % len(points)]]
                anchor = next((n for n in neighbours if abs(n[axis] - value) >= .6), None)
                if anchor is None or abs(point[axis] - anchor[axis]) < 1e-6:
                    moved.append([target, point[1]] if axis == 0 else [point[0], target])
                    continue
                t = (target - anchor[axis]) / (point[axis] - anchor[axis])
                moved.append([round(anchor[0] + (point[0] - anchor[0]) * t, 2),
                              round(anchor[1] + (point[1] - anchor[1]) * t, 2)])
            item['points'] = moved
            item['bleed'] = True


def _inset_rect(rng, parent, gutter, fraction):
    box = shape_bounds(parent)
    w, h = box.width() * fraction * rng.uniform(.9, 1.15), box.height() * fraction * rng.uniform(.85, 1.2)
    path = panel_path(parent)
    corners = [(box.left() + gutter * 1.5, box.top() + gutter * 1.5), (box.right() - w - gutter * 1.5, box.top() + gutter * 1.5),
               (box.left() + gutter * 1.5, box.bottom() - h - gutter * 1.5), (box.right() - w - gutter * 1.5, box.bottom() - h - gutter * 1.5)]
    rng.shuffle(corners)
    for x, y in corners:
        rect = QRectF(x, y, w, h)
        if all(path.contains(QPointF(px, py)) for px, py in rect_points(rect.adjusted(-gutter, -gutter, gutter, gutter))):
            return rect
    return None


def _insets(rng, shapes, count, gutter, rtl):
    parents = sorted(shapes, key=lambda s: -area([tuple(p) for p in s['points']]))[:count]
    for parent in parents:
        rect = _inset_rect(rng, parent, gutter, .34)
        if rect is not None:
            shapes.insert(shapes.index(parent) + 1, shape(rect_points(rect), 'straight', inset=True))


def _splash(rng, width, height, margin, gutter, rtl, page_margin):
    """One full-bleed splash panel with a strip of small inset panels."""
    main = shape(rect_points(QRectF(page_margin, page_margin, width - 2 * page_margin, height - 2 * page_margin)),
                 bleed=True)
    shapes = [main]
    count = rng.randint(2, 3)
    strip_bottom = rng.random() < .6
    inset_w = (width - 2 * margin - gutter * (count - 1)) / count
    inset_h = min(inset_w * rng.uniform(.6, .8), height * .2)
    y = height - margin - inset_h if strip_bottom else margin
    row = []
    for index in range(count):
        x = margin + index * (inset_w + gutter)
        row.append(shape(rect_points(QRectF(x, y, inset_w, inset_h)), 'straight', inset=True))
    shapes += row[::-1] if rtl else row
    return shapes


# ------------------------------------------------------------------ drawing

def _inward(points):
    cx, cy = centroid(points)

    def normal(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy) or 1.
        nx, ny = -dy / length, dx / length
        mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        if (cx - mx) * nx + (cy - my) * ny < 0:
            nx, ny = -nx, -ny
        return nx, ny
    return normal


def panel_path(item, scale=1.):
    """QPainterPath of a panel shape (optionally scaled, for previews)."""
    points = [(p[0] * scale, p[1] * scale) for p in item['points']]
    path = QPainterPath()
    if len(points) < 3:
        return path
    style = item.get('style', 'straight')
    box = bounds(points)
    short = min(box.width(), box.height())
    if style == 'round':
        radius = item.get('radius', 0) * scale or short * .08
        count = len(points)
        for index in range(count):
            prev, point, nxt = points[index - 1], points[index], points[(index + 1) % count]
            r_in = min(radius, math.dist(prev, point) / 2) / (math.dist(prev, point) or 1)
            r_out = min(radius, math.dist(point, nxt) / 2) / (math.dist(point, nxt) or 1)
            start = QPointF(point[0] + (prev[0] - point[0]) * r_in, point[1] + (prev[1] - point[1]) * r_in)
            end = QPointF(point[0] + (nxt[0] - point[0]) * r_out, point[1] + (nxt[1] - point[1]) * r_out)
            if index == 0:
                path.moveTo(start)
            else:
                path.lineTo(start)
            path.quadTo(QPointF(*point), end)
        path.closeSubpath()
        return path
    if style in ('wavy', 'jagged'):
        normal = _inward(points)
        amplitude = short * (.025 if style == 'wavy' else .045)
        step = max(8 * scale, short * (.09 if style == 'wavy' else .06))
        path.moveTo(QPointF(*points[0]))
        for p, q in zip(points, points[1:] + points[:1]):
            nx, ny = normal(p, q)
            length = math.dist(p, q)
            pieces = max(2, round(length / step))
            for k in range(pieces):
                a = (p[0] + (q[0] - p[0]) * k / pieces, p[1] + (q[1] - p[1]) * k / pieces)
                b = (p[0] + (q[0] - p[0]) * (k + 1) / pieces, p[1] + (q[1] - p[1]) * (k + 1) / pieces)
                mid = ((a[0] + b[0]) / 2 + nx * amplitude, (a[1] + b[1]) / 2 + ny * amplitude)
                if style == 'wavy':
                    path.quadTo(QPointF(*mid), QPointF(*b))
                else:
                    path.lineTo(QPointF(*mid))
                    path.lineTo(QPointF(*b))
        path.closeSubpath()
        return path
    path.addPolygon(QPolygonF([QPointF(*p) for p in points]))
    path.closeSubpath()
    return path


def label_point(item, scale=1.):
    """Where the panel number goes: near the top-left (reading start) corner, inside the panel."""
    points = [(p[0] * scale, p[1] * scale) for p in item['points']]
    corner = min(points, key=lambda p: p[0] + p[1])
    cx, cy = centroid(points)
    return QPointF(corner[0] + (cx - corner[0]) * .12, corner[1] + (cy - corner[1]) * .12)
