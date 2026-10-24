import sys
import math
import colorsys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QPushButton, QSlider, QLabel, QComboBox, QFrame, QScrollArea, QToolBar, QMenuBar, QSizePolicy
from PyQt6.QtGui import QPainter, QPen, QColor, QImage, QMouseEvent, QAction, QPixmap, QIcon
from PyQt6.QtCore import Qt, QPointF, QTimer, QRectF

class ColorWheel(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent_app = parent
        self.setFixedSize(160, 160)
        self.image = QImage(160, 160, QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.transparent)
        self.draw_wheel()

    def draw_wheel(self):
        for x in range(160):
            for y in range(160):
                dx = x - 80
                dy = y - 80
                dist = math.sqrt(dx**2 + dy**2)
                if dist <= 80:
                    hue = (math.atan2(dy, dx) + math.pi) / (2 * math.pi)
                    sat = dist / 80.0
                    r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
                    self.image.setPixelColor(x, y, QColor(int(r*255), int(g*255), int(b*255)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self.image)

    def mousePressEvent(self, event):
        self.pick_color(event.position())

    def mouseMoveEvent(self, event):
        self.pick_color(event.position())

    def pick_color(self, pos):
        dx = pos.x() - 80
        dy = pos.y() - 80
        dist = math.sqrt(dx**2 + dy**2)
        if dist <= 80:
            hue = (math.atan2(dy, dx) + math.pi) / (2 * math.pi)
            sat = dist / 80.0
            r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
            self.parent_app.current_color = QColor(int(r*255), int(g*255), int(b*255))
            self.parent_app.color_preview.setStyleSheet(f"background-color: {self.parent_app.current_color.name()}; border: 1px solid #aaa;")

class Canvas(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent_app = parent
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        self.image = QImage(1920, 1080, QImage.Format.Format_RGB32)
        self.image.fill(Qt.GlobalColor.white)
        self.drawing = False
        self.mouse_pos = QPointF()
        self.brush_pos = QPointF()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_brush)
        self.timer.start(10)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(event.rect(), self.image, event.rect())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.mouse_pos = event.position()
            self.brush_pos = event.position()

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton):
            self.mouse_pos = event.position()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = False

    def update_brush(self):
        if not self.drawing:
            return
        stabilizer_level = self.parent_app.get_stabilizer_value()
        factor = 1.0 - (stabilizer_level / 100.0) * 0.95
        new_brush_pos = QPointF(
            self.brush_pos.x() + (self.mouse_pos.x() - self.brush_pos.x()) * factor,
            self.brush_pos.y() + (self.mouse_pos.y() - self.brush_pos.y()) * factor
        )
        if abs(new_brush_pos.x() - self.brush_pos.x()) > 0.1 or abs(new_brush_pos.y() - self.brush_pos.y()) > 0.1:
            painter = QPainter(self.image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            size = self.parent_app.brush_size
            pen = QPen(self.parent_app.current_color, size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(self.brush_pos, new_brush_pos)
            self.brush_pos = new_brush_pos
            self.update()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Paint Tool SAI Clone")
        self.setGeometry(100, 100, 1280, 720)
        self.current_color = QColor(0, 0, 0)
        self.brush_size = 5.0
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QWidget { font-size: 11px; font-family: Segoe UI, sans-serif; }
            QMainWindow { background-color: #f0f0f0; }
            QComboBox, QPushButton { border: 1px solid #aaa; background-color: #fff; padding: 2px; }
            QSlider::groove:horizontal { border: 1px solid #999; height: 4px; background: #eee; }
            QSlider::handle:horizontal { background: #ccc; border: 1px solid #777; width: 8px; margin: -4px 0; }
        """)
        menubar = self.menuBar()
        for menu_name in ["File", "Edit", "Canvas", "Layer", "Selection", "Ruler", "Filter", "View", "Window", "Other"]:
            menubar.addMenu(menu_name)
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)
        self.stab_combo = QComboBox()
        self.stab_combo.addItems(["0", "S-1", "S-2", "S-3", "S-4", "S-5", "S-6", "S-7"])
        self.stab_combo.setCurrentText("S-2")
        toolbar.addWidget(QLabel(" Stabilizer "))
        toolbar.addWidget(self.stab_combo)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        left_panel = QScrollArea()
        left_panel.setFixedWidth(270)
        left_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_panel_widget = QWidget()
        left_layout = QVBoxLayout(left_panel_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(5)
        nav_frame = QFrame()
        nav_frame.setFixedSize(250, 120)
        nav_frame.setStyleSheet("background-color: #ddd; border: 1px solid #aaa;")
        left_layout.addWidget(nav_frame)
        color_layout = QHBoxLayout()
        self.color_wheel = ColorWheel(self)
        color_layout.addWidget(self.color_wheel, alignment=Qt.AlignmentFlag.AlignCenter)
        left_layout.addLayout(color_layout)
        self.color_preview = QFrame()
        self.color_preview.setFixedSize(40, 40)
        self.color_preview.setStyleSheet("background-color: #000000; border: 1px solid #aaa;")
        left_layout.addWidget(self.color_preview, alignment=Qt.AlignmentFlag.AlignCenter)
        layer_effect = QLabel("▼ Layer Effect")
        layer_effect.setStyleSheet("color: #b22222; font-weight: bold;")
        left_layout.addWidget(layer_effect)
        tools_layout = QGridLayout()
        tools_layout.setSpacing(2)
        tools = ["Pencil", "Bucket", "Eraser", "Blur", "Water\nColor", "Oil", "Gouache", "Chalk", "Scratch", "Space", "Bone", "Delicio"]
        for i, tool in enumerate(tools):
            btn = QPushButton(tool)
            btn.setFixedSize(50, 50)
            tools_layout.addWidget(btn, i // 4, i % 4)
        left_layout.addLayout(tools_layout)
        brush_mode = QComboBox()
        brush_mode.addItem("Normal")
        left_layout.addWidget(brush_mode)
        settings_grid = QGridLayout()
        settings_grid.addWidget(QLabel("Brush Size"), 0, 0)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 100)
        self.size_slider.setValue(5)
        self.size_slider.valueChanged.connect(self.update_brush_size)
        settings_grid.addWidget(self.size_slider, 0, 1)
        self.size_label = QLabel("5.0")
        settings_grid.addWidget(self.size_label, 0, 2)
        settings_grid.addWidget(QLabel("Min Size"), 1, 0)
        settings_grid.addWidget(QSlider(Qt.Orientation.Horizontal), 1, 1)
        settings_grid.addWidget(QLabel("0%"), 1, 2)
        settings_grid.addWidget(QLabel("Density"), 2, 0)
        settings_grid.addWidget(QSlider(Qt.Orientation.Horizontal), 2, 1)
        settings_grid.addWidget(QLabel("100"), 2, 2)
        left_layout.addLayout(settings_grid)
        sizes_grid = QGridLayout()
        sizes_grid.setSpacing(2)
        sizes = ["2.3", "2.6", "3", "3.5", "4", "5", "6", "7", "8", "9", "10", "12", "14", "16", "20", "25", "30", "35", "40", "50"]
        for i, s in enumerate(sizes):
            btn = QPushButton(s)
            btn.setFixedSize(35, 35)
            btn.clicked.connect(lambda checked, val=s: self.set_brush_size(float(val)))
            sizes_grid.addWidget(btn, i // 5, i % 5)
        left_layout.addLayout(sizes_grid)
        left_layout.addStretch()
        left_panel.setWidget(left_panel_widget)
        main_layout.addWidget(left_panel)
        self.canvas = Canvas(self)
        canvas_container = QScrollArea()
        canvas_container.setStyleSheet("background-color: #a0a0a0;")
        canvas_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        canvas_container.setWidget(self.canvas)
        main_layout.addWidget(canvas_container)

    def update_brush_size(self, value):
        self.brush_size = float(value)
        self.size_label.setText(str(value))

    def set_brush_size(self, value):
        self.brush_size = value
        self.size_slider.setValue(int(value))
        self.size_label.setText(str(value))

    def get_stabilizer_value(self):
        val = self.stab_combo.currentText()
        if val == "0": return 0
        if val.startswith("S-"):
            return 60 + int(val.split("-")[1]) * 5
        return 50

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())