"""Drawing aids: perspective vanishing points, parallel ruler, grid, edge rulers
and comic print guides. Everything here is an overlay; nothing is exported."""
import math

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPen

VP_COLORS = ['#e5735f', '#5fa8e5', '#79c777']


def default_guides():
    return {'points': [], 'perspective_visible': True, 'rays': 28, 'ruler': None,
            'snap': False, 'bleed': 0, 'safe': 0,
            'symmetry': {'mode': 'none', 'x': None, 'y': None, 'count': 6}}


SYMMETRY_MODES = [('Sem simetria', 'none'), ('Espelho vertical (esquerda ↔ direita)', 'vertical'),
                  ('Espelho horizontal (cima ↔ baixo)', 'horizontal'), ('Quatro quadrantes', 'both'),
                  ('Radial (caleidoscópio)', 'radial'), ('Radial espelhado (mandala)', 'mandala')]


def symmetry_center(settings, width, height):
    x, y = settings.get('x'), settings.get('y')
    return QPointF(width / 2 if x is None else x, height / 2 if y is None else y)


def symmetry_transforms(settings, width, height):
    """Document-space copies of a stroke for the active symmetry (identity first)."""
    from PyQt6.QtGui import QTransform
    mode = (settings or {}).get('mode', 'none')
    center = symmetry_center(settings or {}, width, height)

    def around(apply):
        transform = QTransform()
        transform.translate(center.x(), center.y())
        apply(transform)
        transform.translate(-center.x(), -center.y())
        return transform
    result = [QTransform()]
    if mode in ('vertical', 'both'):
        result.append(around(lambda t: t.scale(-1, 1)))
    if mode in ('horizontal', 'both'):
        result.append(around(lambda t: t.scale(1, -1)))
    if mode == 'both':
        result.append(around(lambda t: t.scale(-1, -1)))
    if mode in ('radial', 'mandala'):
        count = max(2, min(32, int(settings.get('count', 6))))
        for k in range(1, count):
            result.append(around(lambda t, k=k: t.rotate(360 * k / count)))
        if mode == 'mandala':
            def mirrored(transform, angle):
                transform.rotate(angle)
                transform.scale(-1, 1)
            for k in range(count):
                result.append(around(lambda t, k=k: mirrored(t, 360 * k / count)))
    return result


def draw_symmetry(painter, view, settings, rect, active):
    mode = (settings or {}).get('mode', 'none')
    if mode == 'none':
        return
    center = symmetry_center(settings, rect.width(), rect.height())
    reach = math.hypot(rect.width(), rect.height())
    painter.save()
    painter.setTransform(view)
    painter.setClipRect(rect)
    pen = QPen(QColor(26, 163, 140, 210 if active else 140), 0, Qt.PenStyle.DashLine)
    painter.setPen(pen)
    angles = []
    if mode in ('vertical', 'both'):
        angles.append(90)
    if mode in ('horizontal', 'both'):
        angles.append(0)
    if mode in ('radial', 'mandala'):
        count = max(2, min(32, int(settings.get('count', 6))))
        angles += [180 * k / count for k in range(count)] if mode == 'mandala' else []
        for k in range(count):
            angle = math.radians(360 * k / count - 90)
            painter.drawLine(QLineF(center, center + QPointF(math.cos(angle), math.sin(angle)) * reach))
    for angle in angles:
        direction = QPointF(math.cos(math.radians(angle)), math.sin(math.radians(angle))) * reach
        painter.drawLine(QLineF(center - direction, center + direction))
    painter.restore()
    screen = view.map(center)
    painter.save()
    painter.setPen(QPen(QColor('white'), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(screen, 6, 6)
    painter.setPen(QPen(QColor(26, 163, 140), 2))
    painter.drawEllipse(screen, 6, 6)
    painter.restore()


def unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-6 else None


def snap_directions(guides, start):
    """Directions a stroke beginning at `start` may follow (document space)."""
    directions = []
    points = guides['points'] if guides.get('perspective_visible', True) else []
    for x, y in points:
        direction = unit(x - start.x(), y - start.y())
        if direction:
            directions.append(direction)
    if len(points) == 1:
        directions += [(1., 0.), (0., 1.)]
    elif len(points) == 2:
        directions.append((0., 1.))
    if guides.get('ruler'):
        x1, y1, x2, y2 = guides['ruler']
        direction = unit(x2 - x1, y2 - y1)
        if direction:
            directions.append(direction)
    return directions


class StrokeConstraint:
    """Locks a stroke onto the guide direction that best matches its first movement."""

    def __init__(self, start, directions, threshold):
        self.start = QPointF(start)
        self.directions = directions
        self.threshold = threshold
        self.direction = None

    def apply(self, point):
        dx, dy = point.x() - self.start.x(), point.y() - self.start.y()
        if self.direction is None:
            if math.hypot(dx, dy) < self.threshold:
                return QPointF(self.start)
            self.direction = max(self.directions, key=lambda d: abs(d[0] * dx + d[1] * dy))
        ux, uy = self.direction
        amount = ux * dx + uy * dy
        return QPointF(self.start.x() + ux * amount, self.start.y() + uy * amount)


def ray_angles(origin, rect, count):
    corners = [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()]
    if rect.contains(origin):
        return [2 * math.pi * n / count for n in range(count)]
    center = rect.center()
    base = math.atan2(center.y() - origin.y(), center.x() - origin.x())
    relative = []
    for corner in corners:
        angle = math.atan2(corner.y() - origin.y(), corner.x() - origin.x()) - base
        relative.append((angle + math.pi) % (2 * math.pi) - math.pi)
    low, high = min(relative), max(relative)
    pad = (high - low) * .02
    low, high = low - pad, high + pad
    return [base + low + (high - low) * n / max(1, count - 1) for n in range(count)]


def infinite_line(a, b, rect):
    direction = unit(b.x() - a.x(), b.y() - a.y())
    if not direction:
        return None
    reach = math.hypot(rect.width(), rect.height()) * 4 + math.hypot(a.x() - rect.center().x(), a.y() - rect.center().y())
    return QLineF(a.x() - direction[0] * reach, a.y() - direction[1] * reach,
                  a.x() + direction[0] * reach, a.y() + direction[1] * reach)


def draw_perspective(painter, view, guides, rect, active):
    points = [QPointF(x, y) for x, y in guides['points']]
    if not points or not guides.get('perspective_visible', True):
        return
    painter.save()
    painter.setTransform(view)
    painter.setClipRect(rect)
    reach = math.hypot(rect.width(), rect.height()) * 6
    for index, point in enumerate(points):
        color = QColor(VP_COLORS[index % 3])
        color.setAlpha(120 if active else 75)
        painter.setPen(QPen(color, 0))
        distance = math.hypot(point.x() - rect.center().x(), point.y() - rect.center().y())
        for angle in ray_angles(point, rect, guides.get('rays', 28)):
            painter.drawLine(QLineF(point, QPointF(point.x() + math.cos(angle) * (reach + distance),
                                                   point.y() + math.sin(angle) * (reach + distance))))
    horizon = None
    if len(points) >= 2:
        horizon = infinite_line(points[0], points[1], rect)
    elif len(points) == 1:
        horizon = infinite_line(points[0], points[0] + QPointF(1, 0), rect)
    if horizon:
        painter.setPen(QPen(QColor(240, 200, 80, 200), 0, Qt.PenStyle.DashLine))
        painter.drawLine(horizon)
    painter.restore()
    painter.save()
    for index, point in enumerate(points):
        screen = view.map(point)
        painter.setPen(QPen(QColor('white'), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(screen, 7, 7)
        painter.setPen(QPen(QColor(VP_COLORS[index % 3]), 2))
        painter.drawEllipse(screen, 7, 7)
        painter.drawLine(screen - QPointF(11, 0), screen + QPointF(11, 0))
        painter.drawLine(screen - QPointF(0, 11), screen + QPointF(0, 11))
    painter.restore()


def draw_ruler(painter, view, guides, rect, active):
    if not guides.get('ruler'):
        return
    x1, y1, x2, y2 = guides['ruler']
    a, b = QPointF(x1, y1), QPointF(x2, y2)
    painter.save()
    painter.setTransform(view)
    painter.setClipRect(rect.adjusted(-rect.width(), -rect.height(), rect.width(), rect.height()))
    line = infinite_line(a, b, rect)
    if line:
        painter.setPen(QPen(QColor(120, 220, 160, 150 if active else 90), 0, Qt.PenStyle.DashDotLine))
        painter.drawLine(line)
    painter.restore()
    painter.save()
    painter.setPen(QPen(QColor(90, 200, 140), 3))
    painter.drawLine(view.map(a), view.map(b))
    painter.setBrush(QColor('white'))
    painter.setPen(QPen(QColor(40, 130, 90), 1.5))
    for point in (a, b):
        painter.drawEllipse(view.map(point), 5, 5)
    painter.restore()


COMPOSITIONS = [('Sem guia de composição', 'none'), ('Regra dos terços', 'thirds'), ('Proporção áurea', 'golden'),
                ('Diagonais', 'diagonals'), ('Centro e eixos', 'center'), ('Espiral áurea', 'spiral')]


def draw_composition(painter, view, mode, rect):
    """Composition overlays: thirds, golden ratio, diagonals, centre or golden spiral."""
    if mode == 'none':
        return
    painter.save()
    painter.setTransform(view)
    painter.setClipRect(rect)
    painter.setPen(QPen(QColor(240, 196, 70, 190), 0))
    w, h = rect.width(), rect.height()
    if mode in ('thirds', 'golden'):
        ratios = (1 / 3, 2 / 3) if mode == 'thirds' else (.382, .618)
        for r in ratios:
            painter.drawLine(QLineF(w * r, 0, w * r, h))
            painter.drawLine(QLineF(0, h * r, w, h * r))
    elif mode == 'diagonals':
        painter.drawLine(QLineF(0, 0, w, h))
        painter.drawLine(QLineF(w, 0, 0, h))
        side = min(w, h)
        painter.drawLine(QLineF(0, h, side, h - side))
        painter.drawLine(QLineF(w, 0, w - side, side))
    elif mode == 'center':
        painter.drawLine(QLineF(w / 2, 0, w / 2, h))
        painter.drawLine(QLineF(0, h / 2, w, h / 2))
        painter.drawEllipse(QPointF(w / 2, h / 2), min(w, h) * .05, min(w, h) * .05)
    elif mode == 'spiral':
        # Golden spiral: cut a square off the remaining rectangle in turn (left, top, right,
        # bottom) and draw a quarter circle inside each square.
        x, y, width, height = 0., 0., w, h
        for step in range(10):
            side = min(width, height)
            if side < 2:
                break
            corner = step % 4
            if corner == 0:
                square, center, start = QRectF(x, y, side, side), QPointF(x + side, y + side), 90
                x, width = x + side, width - side
            elif corner == 1:
                square, center, start = QRectF(x, y, side, side), QPointF(x, y + side), 0
                y, height = y + side, height - side
            elif corner == 2:
                square, center, start = QRectF(x + width - side, y, side, side), QPointF(x + width - side, y), 270
                width -= side
            else:
                square, center, start = QRectF(x, y + height - side, side, side), QPointF(x + side, y + height - side), 180
                height -= side
            painter.setPen(QPen(QColor(240, 196, 70, 90), 0))
            painter.drawRect(square)
            painter.setPen(QPen(QColor(240, 196, 70, 210), 0))
            painter.drawArc(QRectF(center.x() - side, center.y() - side, side * 2, side * 2), start * 16, 90 * 16)
    painter.restore()


def draw_grid(painter, view, zoom, size, rect, kind='square'):
    if size <= 0 or size * zoom < 5:
        return
    painter.save()
    painter.setTransform(view)
    painter.setPen(QPen(QColor(128, 140, 160, 90), 0))
    if kind == 'iso':
        painter.setClipRect(rect)
        width, height = rect.width(), rect.height()
        slope = math.tan(math.radians(30))
        span = height + width * slope
        offset = -width * slope
        while offset < span:
            painter.drawLine(QLineF(0, offset, width, offset + width * slope))
            painter.drawLine(QLineF(0, offset + width * slope, width, offset))
            offset += size
        x = 0.
        step = size / slope / 2
        while x < width:
            painter.drawLine(QLineF(x, 0, x, height))
            x += step * 2
        painter.restore()
        return
    x = size
    while x < rect.width():
        painter.drawLine(QLineF(x, 0, x, rect.height()))
        x += size
    y = size
    while y < rect.height():
        painter.drawLine(QLineF(0, y, rect.width(), y))
        y += size
    painter.restore()


def draw_print_guides(painter, view, guides, rect, panels):
    bleed, safe = guides.get('bleed', 0), guides.get('safe', 0)
    painter.save()
    painter.setTransform(view)
    if bleed > 0:
        painter.setPen(QPen(QColor(230, 70, 70, 210), 0, Qt.PenStyle.DashLine))
        painter.drawRect(rect.adjusted(bleed, bleed, -bleed, -bleed))
    if safe > 0:
        painter.setPen(QPen(QColor(70, 150, 230, 210), 0, Qt.PenStyle.DashLine))
        inset = bleed + safe
        painter.drawRect(rect.adjusted(inset, inset, -inset, -inset))
    painter.restore()
    if panels:
        painter.save()
        font = QFont('Segoe UI')
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        from comic_layouts import label_point
        for number, panel in enumerate(panels, 1):
            # Shapes (stylized pages) or plain [x, y, w, h] rectangles from older projects.
            anchor = label_point(panel) if isinstance(panel, dict) else QPointF(panel[0], panel[1])
            corner = view.map(anchor) + QPointF(6, 6)
            box = QRectF(corner, corner + QPointF(22, 18))
            painter.fillRect(box, QColor(40, 110, 200, 200))
            painter.setPen(QColor('white'))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(number))
        painter.restore()


def nice_step(zoom):
    for step in (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000):
        if step * zoom >= 60:
            return step
    return 10000


def draw_edge_rulers(painter, canvas, colors, thickness=20):
    """Pixel rulers along the top and left edges of the view."""
    painter.save()
    painter.resetTransform()
    background, text, accent = QColor(colors['panel']), QColor(colors['muted']), QColor(colors['accent'])
    width, height = canvas.width(), canvas.height()
    painter.fillRect(QRectF(0, 0, width, thickness), background)
    painter.fillRect(QRectF(0, 0, thickness, height), background)
    painter.setPen(QPen(QColor(colors['border']), 1))
    painter.drawLine(QLineF(0, thickness, width, thickness))
    painter.drawLine(QLineF(thickness, 0, thickness, height))
    font = QFont('Segoe UI')
    font.setPixelSize(9)
    painter.setFont(font)
    painter.setPen(text)
    rotated = round(canvas.rotation) % 360 != 0
    if rotated:
        painter.drawText(QRectF(thickness + 6, 0, 200, thickness), Qt.AlignmentFlag.AlignVCenter, 'Régua indisponível com a vista girada')
    else:
        view = canvas.transform()
        inverse = view.inverted()[0]
        step = nice_step(canvas.zoom)
        minor = step / 5
        for axis in (0, 1):
            start = inverse.map(QPointF(thickness, thickness))
            end = inverse.map(QPointF(width, height))
            low, high = (start.x(), end.x()) if axis == 0 else (start.y(), end.y())
            value = math.floor(low / minor) * minor
            while value <= high:
                screen = view.map(QPointF(value, value))
                position = screen.x() if axis == 0 else screen.y()
                major = abs(value / step - round(value / step)) < 1e-6
                length = 9 if major else 4
                if axis == 0:
                    painter.drawLine(QLineF(position, thickness - length, position, thickness))
                    if major:
                        painter.drawText(QPointF(position + 3, 10), f'{value:g}')
                else:
                    painter.drawLine(QLineF(thickness - length, position, thickness, position))
                    if major:
                        painter.save()
                        painter.translate(10, position - 3)
                        painter.rotate(-90)
                        painter.drawText(QPointF(0, 0), f'{value:g}')
                        painter.restore()
                value += minor
        if canvas.cursor_inside:
            painter.setPen(QPen(accent, 1))
            cursor = canvas.cursor_pos
            painter.drawLine(QLineF(cursor.x(), 0, cursor.x(), thickness))
            painter.drawLine(QLineF(0, cursor.y(), thickness, cursor.y()))
    painter.fillRect(QRectF(0, 0, thickness, thickness), background)
    painter.restore()
