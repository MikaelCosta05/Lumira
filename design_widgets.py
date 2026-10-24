"""Small, code-native UI components for the painting workbench."""
import math
from functools import lru_cache

from PyQt6.QtCore import QEvent, QLineF, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPolygonF)
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QSizePolicy, QStyledItemDelegate, QStyle,
    QToolButton, QWidget,
)

import glyph_icons
from stabilizer import pressure_response
from themes import PALETTES


@lru_cache(maxsize=256)
def icon(name, color):
    return glyph_icons.icon(name, color)


class ColorSelector(QWidget):
    color_changed = pyqtSignal(QColor)

    def __init__(self):
        super().__init__()
        self.hue, self.saturation, self.value = 0., 0., 0.
        self.target = None
        self.setMinimumSize(180, 114)
        self.setMaximumHeight(138)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setToolTip('Quadrado: saturação e luminosidade. Barra: matiz.')

    def rectangles(self):
        return QRectF(2, 2, self.width() - 29, self.height() - 4), QRectF(self.width() - 19, 2, 16, self.height() - 4)

    def set_color(self, color):
        hue, self.saturation, self.value, _ = color.getHsvF()
        if hue >= 0:
            self.hue = hue
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        square, bar = self.rectangles()
        gradient = QLinearGradient(square.topLeft(), square.topRight())
        gradient.setColorAt(0, Qt.GlobalColor.white)
        gradient.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
        painter.fillRect(square, gradient)
        shadow = QLinearGradient(square.topLeft(), square.bottomLeft())
        shadow.setColorAt(0, QColor(0, 0, 0, 0))
        shadow.setColorAt(1, Qt.GlobalColor.black)
        painter.fillRect(square, shadow)
        hue = QLinearGradient(bar.topLeft(), bar.bottomLeft())
        for n in range(7):
            hue.setColorAt(n / 6, QColor.fromHsvF(n / 6, 1, 1))
        painter.fillRect(bar, hue)
        point = QPointF(square.left() + self.saturation * square.width(), square.top() + (1 - self.value) * square.height())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#202127'), 3))
        painter.drawEllipse(point, 4, 4)
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        painter.drawEllipse(point, 4, 4)
        y = bar.top() + self.hue * bar.height()
        painter.setPen(QPen(QColor('#202127'), 3))
        painter.drawRect(QRectF(bar.left() - 1, y - 2, bar.width() + 2, 4))
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.drawRect(QRectF(bar.left() - 1, y - 2, bar.width() + 2, 4))

    def pick(self, point):
        square, bar = self.rectangles()
        if self.target == 'square':
            self.saturation = max(0., min(1., (point.x() - square.x()) / square.width()))
            self.value = max(0., min(1., 1 - (point.y() - square.y()) / square.height()))
        elif self.target == 'hue':
            self.hue = max(0., min(1., (point.y() - bar.y()) / bar.height()))
        self.color_changed.emit(QColor.fromHsvF(self.hue, self.saturation, self.value))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            square, bar = self.rectangles()
            self.target = 'square' if square.contains(event.position()) else 'hue' if bar.adjusted(-3, 0, 3, 0).contains(event.position()) else None
            if self.target:
                self.pick(event.position())

    def mouseMoveEvent(self, event):
        if self.target and event.buttons() & Qt.MouseButton.LeftButton:
            self.pick(event.position())

    def mouseReleaseEvent(self, event):
        self.target = None


class BrushPreview(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedHeight(38)
        self.setToolTip('Prévia da espessura e da dinâmica do pincel.')

    def paintEvent(self, event):
        c = PALETTES[self.owner.theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c['field']))
        painter.drawRoundedRect(QRectF(self.rect()), 4, 4)
        width = max(2., min(13., self.owner.brush_size * .5))
        previous = None
        for n in range(101):
            t = n / 100
            point = QPointF(14 + t * (self.width() - 28), 19 + math.sin(t * math.tau) * 8)
            pressure = .12 + .88 * math.sin(t * math.pi)
            factor = pressure_response(pressure, self.owner.pressure_profile, self.owner.minimum_size) if self.owner.pressure_enabled else 1.
            painter.setPen(QPen(QColor(c['text']), width * factor, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if previous:
                painter.drawLine(previous, point)
            previous = point


class SizePreset(QToolButton):
    def __init__(self, owner, size):
        super().__init__()
        self.owner, self.brush_size = owner, size
        self.setFixedSize(39, 34)
        self.setToolTip(f'{size:g} px')
        self.clicked.connect(lambda: owner.size_spin.setValue(size))

    def paintEvent(self, event):
        c = PALETTES[self.owner.theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = abs(self.owner.brush_size - self.brush_size) < .05
        painter.setBrush(QColor(c['selected'] if selected else c['hover'] if self.underMouse() else c['field']))
        painter.setPen(QPen(QColor(c['accent'] if selected else c['border']), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 3, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c['text']))
        radius = max(1.2, min(5.5, self.brush_size / 7))
        painter.drawEllipse(QPointF(self.width() / 2, 10), radius, radius)
        painter.setPen(QColor(c['muted']))
        font = QFont(painter.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(QRectF(0, 20, self.width(), 12), Qt.AlignmentFlag.AlignCenter, f'{self.brush_size:g}')


class DockHeader(QWidget):
    def __init__(self, owner, dock, title):
        super().__init__(dock)
        self.owner, self.dock = owner, dock
        self.setObjectName('dockHeader')
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 5, 0)
        self.label = QLabel(title)
        self.label.setObjectName('dockTitle')
        layout.addWidget(self.label)
        layout.addStretch()
        self.button = QToolButton()
        self.button.setObjectName('quietButton')
        self.button.setFixedSize(22, 22)
        self.button.setToolTip('Opções do painel')
        self.button.clicked.connect(self.open_menu)
        layout.addWidget(self.button)
        self.refresh()

    def refresh(self):
        self.button.setIcon(icon('dots-horizontal', PALETTES[self.owner.theme]['muted']))
        self.sync_title()

    def sync_title(self):
        """Tabbed panels already show their name in the tab: keep only the menu button."""
        siblings = [d for d in self.owner.tabifiedDockWidgets(self.dock) if d.toggleViewAction().isChecked()]
        tabbed = bool(siblings) and not self.dock.isFloating()
        self.label.setVisible(not tabbed)
        self.setFixedHeight(18 if tabbed else 28)

    def open_menu(self):
        menu = QMenu(self)
        menu.addAction('Encaixar painel' if self.dock.isFloating() else 'Destacar painel', lambda: self.dock.setFloating(not self.dock.isFloating()))
        menu.addAction('Ocultar painel', self.dock.hide)
        menu.exec(self.button.mapToGlobal(self.button.rect().bottomLeft()))

    def mousePressEvent(self, event):
        event.ignore()  # Forward to QDockWidget for native drag and docking.

    def mouseMoveEvent(self, event):
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dock.setFloating(not self.dock.isFloating())


class LayerDelegate(QStyledItemDelegate):
    ROW = 52

    def __init__(self, owner):
        super().__init__(owner.layer_list)
        self.owner = owner

    def sizeHint(self, option, index):
        return QSize(230, self.ROW)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = PALETTES[self.owner.theme]
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c['selected'] if selected else c['hover']))
            painter.drawRoundedRect(rect, 6, 6)
        visible = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
        eye = icon('eye-outline' if visible else 'eye-off-outline', c['text'] if visible else c['muted'])
        eye.paint(painter, int(rect.x()) + 8, int(rect.center().y()) - 8, 16, 16)
        thumb = QRectF(rect.x() + 32, rect.y() + 5, 44, rect.height() - 10)
        thumbnail = index.data(Qt.ItemDataRole.DecorationRole)
        if thumbnail:
            thumbnail.paint(painter, thumb.toRect())
        painter.setPen(QPen(QColor(c['accent'] if selected else c['border']), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(thumb, 4, 4)
        metadata = index.data(Qt.ItemDataRole.UserRole + 1) or {}
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(c['strong'] if selected else c['text']))
        left = thumb.right() + 10
        available = rect.right() - left - 40
        name = painter.fontMetrics().elidedText(str(index.data(Qt.ItemDataRole.DisplayRole)), Qt.TextElideMode.ElideRight, int(available))
        painter.drawText(QRectF(left, rect.y() + 8, available, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(c['muted']))
        detail = metadata.get('detail', '')
        painter.drawText(QRectF(left, rect.y() + 26, available, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(f'{metadata.get("opacity", 100)}% · {detail}', Qt.TextElideMode.ElideRight, int(available)))
        x = rect.right() - 20
        for key, name in (('locked', 'lock-outline'), ('alpha_lock', 'checkerboard')):
            if metadata.get(key):
                icon(name, c['muted']).paint(painter, int(x), int(rect.center().y()) - 7, 14, 14)
                x -= 18
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton and event.position().x() < option.rect.x() + 30:
            checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
            return model.setData(index, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        return super().editorEvent(event, model, option, index)


class ColorWheel(QWidget):
    """Hue ring with a saturation/value triangle (the classic painter's colour wheel)."""
    color_changed = pyqtSignal(QColor)

    def __init__(self):
        super().__init__()
        self.hue, self.saturation, self.value = 0., 0., 0.
        self.target = None
        self.setMinimumSize(110, 110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setToolTip('Anel: matiz · Triângulo: saturação e luminosidade')

    def set_color(self, color):
        hue, self.saturation, self.value, _ = color.getHsvF()
        if hue >= 0:
            self.hue = hue
        self.update()

    def geometry_values(self):
        side = min(self.width(), self.height()) - 6
        outer = side / 2
        return QPointF(self.width() / 2, self.height() / 2), outer, outer * .8

    def triangle(self):
        """Vertices: pure hue, white, black."""
        center, outer, inner = self.geometry_values()
        radius = inner - 4
        angle = -self.hue * math.tau
        return [center + QPointF(math.cos(angle + k * math.tau / 3), math.sin(angle + k * math.tau / 3)) * radius
                for k in range(3)]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center, outer, inner = self.geometry_values()
        gradient = QConicalGradient(center, 0)
        for n in range(13):
            gradient.setColorAt(n / 12, QColor.fromHsvF((n / 12) % 1., 1, 1))
        ring = QPainterPath()
        ring.addEllipse(center, outer, outer)
        hole = QPainterPath()
        hole.addEllipse(center, inner, inner)
        painter.fillPath(ring.subtracted(hole), QBrush(gradient))
        hue_point, white, black = self.triangle()
        path = QPainterPath()
        path.addPolygon(QPolygonF([hue_point, white, black]))
        path.closeSubpath()
        painter.save()
        painter.setClipPath(path)
        bounds = path.boundingRect()
        painter.fillPath(path, QColor.fromHsvF(self.hue, 1, 1))
        white_gradient = QLinearGradient(QLineF(black, hue_point).pointAt(.5), white)
        white_gradient.setColorAt(0, QColor(255, 255, 255, 0))
        white_gradient.setColorAt(1, QColor(255, 255, 255, 255))
        painter.fillRect(bounds, QBrush(white_gradient))
        black_gradient = QLinearGradient(QLineF(white, hue_point).pointAt(.5), black)
        black_gradient.setColorAt(0, QColor(0, 0, 0, 0))
        black_gradient.setColorAt(1, QColor(0, 0, 0, 255))
        painter.fillRect(bounds, QBrush(black_gradient))
        painter.restore()
        angle = -self.hue * math.tau
        for point in (center + QPointF(math.cos(angle), math.sin(angle)) * (inner + outer) / 2,
                      self.point_for(self.saturation, self.value)):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 3))
            painter.drawEllipse(point, 5, 5)
            painter.setPen(QPen(QColor('white'), 1.6))
            painter.drawEllipse(point, 5, 5)

    def point_for(self, saturation, value):
        hue_point, white, black = self.triangle()
        top = white + (hue_point - white) * saturation
        return black + (top - black) * value

    def sv_for(self, position):
        hue_point, white, black = self.triangle()
        v0, v1, v2 = white - hue_point, black - hue_point, position - hue_point
        d00, d01, d11 = QPointF.dotProduct(v0, v0), QPointF.dotProduct(v0, v1), QPointF.dotProduct(v1, v1)
        d20, d21 = QPointF.dotProduct(v2, v0), QPointF.dotProduct(v2, v1)
        denominator = d00 * d11 - d01 * d01 or 1e-9
        w = (d11 * d20 - d01 * d21) / denominator
        b = (d00 * d21 - d01 * d20) / denominator
        h, w, b = max(0., 1 - w - b), max(0., w), max(0., b)
        total = h + w + b or 1
        h, w = h / total, w / total
        value = max(0., min(1., h + w))
        saturation = 0. if value <= 1e-6 else max(0., min(1., h / value))
        return saturation, value

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        center, outer, inner = self.geometry_values()
        distance = math.hypot(event.position().x() - center.x(), event.position().y() - center.y())
        self.target = 'ring' if inner - 2 <= distance <= outer + 4 else 'triangle' if distance < inner else None
        self.pick(event.position())

    def mouseMoveEvent(self, event):
        if self.target and event.buttons() & Qt.MouseButton.LeftButton:
            self.pick(event.position())

    def mouseReleaseEvent(self, event):
        self.target = None

    def pick(self, position):
        if self.target == 'ring':
            center, _, _ = self.geometry_values()
            self.hue = (-math.atan2(position.y() - center.y(), position.x() - center.x()) / math.tau) % 1.
        elif self.target == 'triangle':
            self.saturation, self.value = self.sv_for(position)
        else:
            return
        self.color_changed.emit(QColor.fromHsvF(self.hue, self.saturation, self.value))
        self.update()


class ToolSlot(QToolButton):
    """Toolbar button for a group of tools: shows the last used one; the others are in a menu
    (right click or press and hold), marked by a small triangle in the corner."""

    def __init__(self, owner, actions):
        super().__init__()
        self.owner, self.group = owner, actions
        self.toolbar_action = None
        self.setDefaultAction(actions[0])
        self.setIconSize(QSize(20, 20))
        if len(actions) > 1:
            menu = QMenu(self)
            for action in actions:
                menu.addAction(action)
            self.setMenu(menu)
            self.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        for action in actions:
            action.toggled.connect(lambda checked, a=action: checked and self.setDefaultAction(a))
            action.changed.connect(self.sync)

    def sync(self):
        visible = any(action.isVisible() for action in self.group)
        if self.toolbar_action is not None and self.toolbar_action.isVisible() != visible:
            self.toolbar_action.setVisible(visible)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.menu():
            self.showMenu()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if len(self.group) > 1:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PALETTES[self.owner.theme]['muted']))
            w, h = self.width(), self.height()
            painter.drawPolygon(QPolygonF([QPointF(w - 3, h - 8), QPointF(w - 3, h - 3), QPointF(w - 8, h - 3)]))


class ColorChips(QWidget):
    """Main and secondary colours as overlapping squares, with a swap button."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedSize(40, 48)
        self.setToolTip('Cor principal e secundária · clique para escolher · seta troca as cores')

    def rects(self):
        return QRectF(4, 4, 21, 21), QRectF(15, 15, 21, 21)

    def paintEvent(self, event):
        c = PALETTES[self.owner.theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        front, back = self.rects()
        for rect, color in ((back, self.owner.secondary_color), (front, self.owner.current_color)):
            painter.setPen(QPen(QColor(c['panel']), 3))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QPen(QColor(c['muted']), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 4, 4)
        icon('swap-horizontal', c['muted']).paint(painter, 1, 32, 13, 13)

    def mousePressEvent(self, event):
        front, back = self.rects()
        position = event.position()
        if position.y() > 30 and position.x() < 15:
            self.owner.swap_colors()
        elif front.contains(position):
            self.owner.choose_color()
        elif back.contains(position):
            self.owner.choose_secondary_color()
        self.update()


class LogoMark(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedSize(36, 30)
        self.setToolTip('Lumira')

    def paintEvent(self, event):
        c = PALETTES[self.owner.theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c['accent']))
        painter.drawRoundedRect(QRectF(8, 4, 22, 22), 6, 6)
        icon('brush-variant', '#ffffff').paint(painter, 11, 7, 16, 16)
