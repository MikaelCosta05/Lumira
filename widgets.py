import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QConicalGradient, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget
from themes import PALETTES


class ColorWheel(QWidget):
    color_changed = pyqtSignal(QColor)

    def __init__(self):
        super().__init__()
        self.setFixedSize(200, 200)
        self.hue, self.saturation, self.value = 0., 0., 0.
        self.drag_target = None
        self.square = QRectF(48, 48, 104, 104)
        self.gradient = None
        self.setToolTip('Anel: matiz. Quadrado: saturação e luminosidade.')
        self.rebuild()

    def rebuild(self):
        image = QImage(104, 104, QImage.Format.Format_RGB32)
        for y in range(104):
            for x in range(104):
                image.setPixelColor(x, y, QColor.fromHsvF(self.hue, x / 103, 1 - y / 103))
        self.gradient = image
        self.update()

    def set_color(self, color):
        hue, sat, value, _ = color.getHsvF()
        if hue >= 0:
            self.hue = hue
        self.saturation, self.value = sat, value
        self.rebuild()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QConicalGradient(QPointF(100, 100), 0)
        for i in range(13):
            gradient.setColorAt(i / 12, QColor.fromHsvF((i / 12) % 1, 1, 1))
        painter.setPen(QPen(gradient, 17))
        painter.drawEllipse(QPointF(100, 100), 87, 87)
        painter.drawImage(self.square, self.gradient)
        angle = self.hue * math.tau
        markers = [QPointF(100 + math.cos(angle) * 87, 100 - math.sin(angle) * 87),
                   QPointF(48 + self.saturation * 104, 48 + (1 - self.value) * 104)]
        for point in markers:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(Qt.GlobalColor.black, 3))
            painter.drawEllipse(point, 4.5, 4.5)
            painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
            painter.drawEllipse(point, 4.5, 4.5)

    def pick(self, position):
        if self.drag_target == 'ring':
            self.hue = math.atan2(100 - position.y(), position.x() - 100) % math.tau / math.tau
            self.rebuild()
        elif self.drag_target == 'square':
            self.saturation = max(0., min(1., (position.x() - 48) / 104))
            self.value = max(0., min(1., 1 - (position.y() - 48) / 104))
        self.color_changed.emit(QColor.fromHsvF(self.hue, self.saturation, self.value))
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        distance = math.hypot(point.x() - 100, point.y() - 100)
        self.drag_target = 'square' if self.square.contains(point) else 'ring' if 74 < distance < 100 else None
        if self.drag_target:
            self.pick(point)

    def mouseMoveEvent(self, event):
        if self.drag_target and event.buttons() & Qt.MouseButton.LeftButton:
            self.pick(event.position())

    def mouseReleaseEvent(self, event):
        self.drag_target = None


class Navigator(QWidget):
    recenter = pyqtSignal(QPointF)

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.thumbnail = None
        self.setMinimumSize(180, 130)
        self.setMaximumHeight(190)
        self.setToolTip('Clique na miniatura para navegar pela tela.')

    def refresh(self):
        """Coalesce refreshes: the thumbnail is rebuilt shortly after edits, off the stroke's path."""
        if not hasattr(self, 'refresh_timer'):
            self.refresh_timer = QTimer(self)
            self.refresh_timer.setSingleShot(True)
            self.refresh_timer.setInterval(120)
            self.refresh_timer.timeout.connect(self.rebuild)
        self.refresh_timer.start()

    def rebuild(self):
        if not self.isVisible():
            self.thumbnail = None
            return
        self.thumbnail = self.canvas.preview_image(400, 240)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.thumbnail is None:
            self.refresh()

    def image_rect(self):
        ratio = min((self.width() - 20) / self.canvas.document.width,
                    (self.height() - 20) / self.canvas.document.height)
        w, h = self.canvas.document.width * ratio, self.canvas.document.height * ratio
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PALETTES[self.canvas.theme]['field']))
        rectangle = self.image_rect()
        painter.fillRect(rectangle, Qt.GlobalColor.white)
        if self.thumbnail is not None:
            painter.drawImage(rectangle, self.thumbnail)
        inverse = self.canvas.transform().inverted()[0]
        viewport = inverse.mapRect(QRectF(self.canvas.rect()))
        scale = rectangle.width() / self.canvas.document.width
        visible = QRectF(rectangle.x() + viewport.x() * scale, rectangle.y() + viewport.y() * scale,
                         viewport.width() * scale, viewport.height() * scale).intersected(rectangle)
        painter.setPen(QPen(QColor('#63b9ff'), 1.5))
        painter.drawRect(visible)

    def mousePressEvent(self, event):
        rectangle = self.image_rect()
        if event.button() == Qt.MouseButton.LeftButton and rectangle.contains(event.position()):
            point = event.position() - rectangle.topLeft()
            scale = self.canvas.document.width / rectangle.width()
            self.recenter.emit(point * scale)
