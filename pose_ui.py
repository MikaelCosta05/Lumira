"""Pose studio: posable 3D figures (mannequin or rigged glTF models) with light and shadow styles."""
import math
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                             QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

import mannequin
import model3d
import shading
from i18n import tr
from themes import PALETTES

OPEN_FILE = 'open'


class Viewport(QWidget):
    changed = pyqtSignal()
    selected = pyqtSignal()

    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.setMinimumSize(360, 420)
        self.setMouseTracking(True)
        self.image = None
        self.ids = None
        self.selected_joint = None
        self.drag = None
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(140)
        self.idle.timeout.connect(lambda: self.render_now(1.))
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def sizeHint(self):
        return QSize(580, 700)

    @property
    def figure(self):
        return self.studio.figure

    @property
    def camera(self):
        return self.studio.camera

    def request(self, fast=True):
        if fast:
            self.render_now(.5)
        self.idle.start()

    def render_now(self, scale):
        width, height = max(40, int(self.width() * scale)), max(40, int(self.height() * scale))
        settings = self.studio.settings()
        supersample = 2 if scale >= 1 and self.figure.kind == 'gltf' else 1
        try:
            result = self.figure.render(self.camera, width, height, light=settings['light'], supersample=supersample,
                                        cast_shadows=settings['cast'], floor=settings['floor'],
                                        line_width=settings['line_width'] * scale * supersample,
                                        outline=settings['outline'], textures=settings['use_albedo'])
        except Exception as error:  # GPU/driver problems must not close the studio
            self.studio.status(f'Não foi possível desenhar o modelo: {error}')
            return
        rgb, alpha = mannequin.compose(result, settings)
        self.image = shading.to_image(rgb, alpha)
        self.ids = result['ids']
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.request()

    def project(self, point):
        projected = self.camera.project(point, self.width(), self.height())
        return QPointF(*projected) if projected else None

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = PALETTES[self.studio.owner.theme]
        painter.fillRect(self.rect(), QColor(self.studio.background))
        if self.image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(self.rect()), self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(colors['accent'])
        if self.studio.show_bones.isChecked():
            for key, start, end in self.figure.bone_segments():
                a, b = self.project(start), self.project(end)
                if a and b:
                    painter.setPen(QPen(accent if key == self.selected_joint else QColor(255, 255, 255, 170), 2))
                    painter.drawLine(a, b)
                    painter.setBrush(QColor(20, 22, 28, 200))
                    painter.drawEllipse(a, 2.5, 2.5)
        if self.selected_joint is not None:
            point = self.project(self.figure.joint_position(self.selected_joint))
            if point:
                painter.setPen(QPen(accent, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(point, 7, 7)
                label = tr(self.figure.label(self.selected_joint))
                box = QRectF(point.x() + 11, point.y() - 20, painter.fontMetrics().horizontalAdvance(label) + 12, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(20, 22, 28, 210))
                painter.drawRoundedRect(box, 5, 5)
                painter.setPen(QColor('white'))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        azimuth, elevation = self.studio.settings()['light']
        center, radius = QPointF(self.width() - 38, 38), 26
        painter.setPen(QPen(QColor(colors['muted']), 1))
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(center, radius, radius)
        sun = center + QPointF(math.sin(math.radians(azimuth)), -math.sin(math.radians(elevation))) * radius * .85
        painter.setBrush(QColor('#ffd34d'))
        painter.setPen(QPen(QColor('#8a6a10'), 1))
        painter.drawEllipse(sun, 5, 5)
        painter.setPen(QColor(colors['muted']))
        painter.drawText(QRectF(10, self.height() - 24, self.width() - 20, 18), Qt.AlignmentFlag.AlignLeft,
                         tr('Arraste a parte: girar · Shift: girar em profundidade · fundo: orbitar · '
                            'botão direito: mover · roda: zoom · Ctrl: luz'))

    def joint_at(self, position):
        if self.ids is None:
            return None
        height, width = self.ids.shape
        x = int(position.x() / max(1, self.width()) * width)
        y = int(position.y() / max(1, self.height()) * height)
        if 0 <= x < width and 0 <= y < height and self.ids[y, x] >= 0:
            return self.figure.joint_at_id(int(self.ids[y, x]))
        return None

    def mousePressEvent(self, event):
        position = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            self.drag = ('pan', position)
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.drag = ('light', position)
        else:
            joint = self.joint_at(position)
            if joint is not None:
                self.selected_joint = joint
                self.selected.emit()
                pivot = self.project(self.figure.joint_position(joint))
                self.drag = ('joint', position, pivot or position)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                if not self.figure.rigged and self.ids is not None:
                    self.studio.status('Este modelo não tem esqueleto: dá para iluminar e enquadrar, mas não para posar.')
                self.drag = ('orbit', position)
        self.update()

    def mouseMoveEvent(self, event):
        position = event.position()
        if not self.drag:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.joint_at(position) is not None else Qt.CursorShape.OpenHandCursor)
            return
        kind, previous = self.drag[0], self.drag[1]
        delta = position - previous
        _, forward, right, up = self.camera.basis()
        if kind == 'orbit':
            self.camera.yaw -= delta.x() * .4
            self.camera.pitch = max(-85., min(85., self.camera.pitch + delta.y() * .4))
        elif kind == 'pan':
            scale = self.camera.distance * math.tan(math.radians(self.camera.fov) / 2) * 2 / max(1, self.height())
            self.camera.target = self.camera.target + (-delta.x() * right + delta.y() * up) * scale
        elif kind == 'light':
            self.studio.move_light(delta.x() * .5, -delta.y() * .5)
        elif kind == 'joint':
            pivot = self.drag[2]
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                axis = up * delta.x() + right * delta.y()
                if np.linalg.norm(axis) > 0:
                    self.figure.rotate_joint(self.selected_joint, mannequin.axis_angle(axis, math.hypot(delta.x(), delta.y()) * .6))
            else:
                before = math.atan2(previous.y() - pivot.y(), previous.x() - pivot.x())
                after = math.atan2(position.y() - pivot.y(), position.x() - pivot.x())
                turn = (after - before + math.pi) % (2 * math.pi) - math.pi
                self.figure.rotate_joint(self.selected_joint, mannequin.axis_angle(forward, math.degrees(turn)))
            self.changed.emit()
            self.drag = (kind, position, pivot)
            self.request()
            return
        self.drag = (kind, position) + tuple(self.drag[2:])
        self.request()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.request(fast=False)

    def wheelEvent(self, event):
        self.camera.distance = max(1e-3, self.camera.distance * .88 ** (event.angleDelta().y() / 120))
        self.request()


class PoseStudio(QDialog):
    AXES = [('Dobrar (X)', 0), ('Girar (Y)', 1), ('Inclinar (Z)', 2)]

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Window)
        self.owner = owner
        self.setWindowTitle('Manequim 3D · poses, luz e sombra')
        self.resize(1180, 780)
        self.figure = mannequin.Figure()
        self.camera = mannequin.Camera()
        self.camera.fit(self.figure, view=True)
        self.background = '#ece8e1'
        self.model_color, self.shadow_color, self.line_color = '#d8c3a5', '#4b3f72', '#2a2420'
        self.updating = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        column = QVBoxLayout()
        self.viewport = Viewport(self)
        self.viewport.changed.connect(self.refresh_joint)
        self.viewport.selected.connect(self.refresh_joint)
        column.addWidget(self.viewport, 1)
        self.message = QLabel('')
        self.message.setObjectName('muted')
        column.addWidget(self.message)
        layout.addLayout(column, 1)
        panel = QWidget()
        panel.setObjectName('posePanel')
        side = QVBoxLayout(panel)
        side.setContentsMargins(8, 4, 8, 8)
        side.addWidget(self.model_group())
        side.addWidget(self.pose_group())
        side.addWidget(self.joint_group())
        side.addWidget(self.light_group())
        side.addWidget(self.style_group())
        self.separate = QCheckBox('Sombra numa camada de sombra (estilo editável)')
        self.separate.setChecked(True)
        side.addWidget(self.separate)
        insert = QPushButton('Inserir na tela')
        insert.setObjectName('primary')
        insert.setMinimumHeight(34)
        insert.clicked.connect(self.insert)
        side.addWidget(insert)
        side.addStretch()
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFixedWidth(350)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(panel)
        layout.addWidget(area)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.refresh_model_controls()
        self.refresh_presets()
        self.refresh_joint()

    def status(self, text):
        self.message.setText(text)

    # ---------------------------------------------------------- panels

    def model_group(self):
        group = QGroupBox('Modelo')
        form = QFormLayout(group)
        self.model = QComboBox()
        for name in mannequin.MODELS:
            self.model.addItem(f'Manequim · {name}', ('builtin', name))
        library = model3d.library_models()
        if library:
            self.model.insertSeparator(self.model.count())
            for name, path in library:
                self.model.addItem(name, ('file', path))
        self.model.insertSeparator(self.model.count())
        self.model.addItem('Abrir arquivo .glb…', (OPEN_FILE, None))
        self.model.activated.connect(lambda index: self.change_model(True))
        self.proportion = QComboBox()
        self.proportion.addItems(list(mannequin.PROPORTIONS))
        self.proportion.currentTextChanged.connect(lambda: self.change_model(False))
        form.addRow('Modelo', self.model)
        form.addRow('Proporção', self.proportion)
        views = QGridLayout()
        for index, (label, yaw, pitch) in enumerate([('Frente', 0, 5), ('3/4', 35, 10), ('Lado', 90, 5),
                                                     ('Costas', 180, 5), ('Cima', 30, 60), ('Baixo', 20, -35)]):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, y=yaw, p=pitch: self.set_view(y, p))
            views.addWidget(button, index // 3, index % 3)
        form.addRow(views)
        return group

    def pose_group(self):
        group = QGroupBox('Pose')
        grid = QGridLayout(group)
        self.preset = QComboBox()
        self.preset.currentIndexChanged.connect(self.preset_selected)
        apply = QPushButton('Aplicar')
        apply.clicked.connect(self.apply_preset)
        grid.addWidget(self.preset, 0, 0, 1, 2)
        grid.addWidget(apply, 0, 2)
        self.time_label = QLabel('Momento da animação')
        self.time_label.setObjectName('muted')
        self.time = QSlider(Qt.Orientation.Horizontal)
        self.time.setRange(0, 100)
        self.time.valueChanged.connect(self.apply_preset)
        grid.addWidget(self.time_label, 1, 0)
        grid.addWidget(self.time, 1, 1, 1, 2)
        self.pose_buttons = {}
        for index, (key, label, callback) in enumerate([('save', 'Salvar pose…', self.save_pose),
                                                        ('delete', 'Excluir pose', self.delete_pose),
                                                        ('mirror', 'Espelhar', self.mirror), ('reset_part', 'Zerar parte', self.reset_joint),
                                                        ('reset', 'Zerar tudo', self.reset_all), ('frame', 'Enquadrar', self.frame)]):
            button = QPushButton(label)
            button.clicked.connect(callback)
            grid.addWidget(button, 2 + index // 3, index % 3)
            self.pose_buttons[key] = button
        return group

    def joint_group(self):
        group = QGroupBox('Parte selecionada')
        form = QFormLayout(group)
        self.joint_label = QLabel('Clique numa parte do modelo')
        self.joint_label.setWordWrap(True)
        form.addRow(self.joint_label)
        self.axis_sliders = []
        for label, axis in self.AXES:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-180, 180)
            slider.valueChanged.connect(lambda value, a=axis: self.set_axis(a, value))
            form.addRow(label, slider)
            self.axis_sliders.append(slider)
        self.show_bones = QCheckBox('Mostrar ossos')
        self.show_bones.setChecked(True)
        self.show_bones.toggled.connect(self.viewport.update)
        form.addRow(self.show_bones)
        return group

    def light_group(self):
        group = QGroupBox('Luz')
        form = QFormLayout(group)
        self.azimuth, self.elevation = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
        self.azimuth.setRange(-180, 180)
        self.azimuth.setValue(-40)
        self.elevation.setRange(-80, 89)
        self.elevation.setValue(35)
        self.cast = QCheckBox('Sombra projetada')
        self.cast.setChecked(True)
        self.floor = QCheckBox('Sombra no chão')
        self.floor.setChecked(True)
        for widget in (self.azimuth, self.elevation):
            widget.valueChanged.connect(lambda: self.viewport.request())
        for widget in (self.cast, self.floor):
            widget.toggled.connect(lambda: self.viewport.request(False))
        form.addRow('Direção', self.azimuth)
        form.addRow('Altura', self.elevation)
        presets = QGridLayout()
        for index, (label, azimuth, elevation) in enumerate([('Frontal', 0, 20), ('Lateral', -80, 15), ('De cima', -20, 75),
                                                             ('3/4 alta', -40, 35), ('Contraluz', 160, 25), ('De baixo', 10, -45)]):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, a=azimuth, e=elevation: self.set_light(a, e))
            presets.addWidget(button, index // 3, index % 3)
        form.addRow(presets)
        form.addRow(self.cast)
        form.addRow(self.floor)
        return group

    def style_group(self):
        group = QGroupBox('Sombra e traço')
        form = QFormLayout(group)
        self.colors = QComboBox()
        self.colors.addItem('Texturas do modelo', 'texture')
        self.colors.addItem('Cor única', 'flat')
        self.colors.currentIndexChanged.connect(lambda: self.viewport.request(False))
        self.style = QComboBox()
        for label, value in shading.STYLES:
            self.style.addItem(label, value)
        self.style.setCurrentIndex(self.style.findData('cel'))
        self.style.currentIndexChanged.connect(self.style_changed)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(2, 40)
        self.spacing.setValue(5)
        self.spacing.setSuffix(' px')
        self.angle = QSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setValue(45)
        self.angle.setSuffix('°')
        self.strength = QSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setValue(100)
        self.strength.setSuffix('%')
        self.outline = QComboBox()
        for label, value in [('Contorno das partes', 'parts'), ('Só a silhueta', 'silhouette'), ('Sem contorno', 'none')]:
            self.outline.addItem(label, value)
        self.line_width = QDoubleSpinBox()
        self.line_width.setRange(.5, 8)
        self.line_width.setValue(1.5)
        self.line_width.setSuffix(' px')
        colors = QHBoxLayout()
        self.color_buttons = {}
        for key, label in [('model_color', 'Modelo'), ('shadow_color', 'Sombra'), ('line_color', 'Traço'), ('background', 'Fundo')]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, k=key: self.choose_color(k))
            colors.addWidget(button)
            self.color_buttons[key] = button
        for widget in (self.spacing, self.line_width):
            widget.valueChanged.connect(lambda: self.viewport.request(False))
        for widget in (self.angle, self.strength):
            widget.valueChanged.connect(lambda: self.viewport.request(False))
        self.outline.currentIndexChanged.connect(lambda: self.viewport.request(False))
        self.colors_label = QLabel('Cores')
        form.addRow(self.colors_label, self.colors)
        form.addRow('Estilo', self.style)
        form.addRow('Espaçamento', self.spacing)
        form.addRow('Ângulo', self.angle)
        form.addRow('Intensidade', self.strength)
        form.addRow('Contorno', self.outline)
        form.addRow('Espessura', self.line_width)
        form.addRow(colors)
        self.refresh_colors()
        return group

    # -------------------------------------------------------- settings

    def shadow_settings(self):
        style = self.style.currentData()
        color = self.shadow_color if style not in shading.INK_STYLES else self.line_color
        return {'style': style, 'color': color, 'blend': 'normal' if style in shading.INK_STYLES else 'multiply',
                'spacing': self.spacing.value(), 'angle': float(self.angle.value()), 'strength': self.strength.value() / 100}

    def settings(self):
        textured = self.figure.kind == 'gltf' and self.colors.currentData() == 'texture'
        return {'light': (self.azimuth.value(), self.elevation.value()), 'cast': self.cast.isChecked(),
                'floor': self.floor.isChecked() and self.figure.floor_default,
                'outline': self.outline.currentData(), 'line_width': self.line_width.value(),
                'model_color': self.model_color, 'line_color': self.line_color, 'shadow': self.shadow_settings(),
                'use_albedo': textured}

    def refresh_colors(self):
        for key, button in self.color_buttons.items():
            color = QColor(getattr(self, key))
            text = '#111' if color.lightness() > 140 else '#fff'
            button.setStyleSheet(f'background:{color.name()};color:{text};border:1px solid #888;border-radius:5px;padding:4px;')

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(getattr(self, key)), self, 'Escolher cor')
        if color.isValid():
            setattr(self, key, color.name())
            self.refresh_colors()
            self.viewport.request(False)

    def style_changed(self):
        ink = self.style.currentData() in shading.INK_STYLES
        self.spacing.setEnabled(ink)
        self.angle.setEnabled(ink)
        self.viewport.request(False)

    def set_light(self, azimuth, elevation):
        self.azimuth.setValue(azimuth)
        self.elevation.setValue(elevation)

    def move_light(self, delta_azimuth, delta_elevation):
        azimuth = (self.azimuth.value() + delta_azimuth + 180) % 360 - 180
        self.set_light(round(azimuth), round(max(-80, min(89, self.elevation.value() + delta_elevation))))

    def set_view(self, yaw, pitch):
        side = -1 if getattr(self.figure, 'model', '') == 'Mão esquerda' else 1
        self.camera.yaw, self.camera.pitch = yaw * side, pitch
        self.viewport.request(False)

    def frame(self):
        self.camera.fit(self.figure)
        self.viewport.request(False)

    # ------------------------------------------------------------ model

    def change_model(self, reframe=True):
        kind, value = self.model.currentData() or ('builtin', 'Corpo inteiro')
        previous = self.figure
        if kind == OPEN_FILE:
            path, _ = QFileDialog.getOpenFileName(self, 'Abrir modelo 3D', str(model3d.MODEL_FOLDER), 'glTF binário (*.glb)')
            if not path:
                self.select_current_model()
                return
            self.model.insertItem(self.model.count() - 2, Path(path).stem, ('file', path))
            self.model.setCurrentIndex(self.model.count() - 3)
            kind, value = 'file', path
        if kind == 'builtin':
            if previous.kind == 'mannequin':
                self.figure.rebuild(value, self.proportion.currentText())
            else:
                self.figure = mannequin.Figure(value, self.proportion.currentText())
            self.status('')
        elif previous.kind != 'gltf' or previous.path != value:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.figure = model3d.RigFigure(value)
            except Exception as error:  # broken files, missing OpenGL…
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, 'Modelo 3D', f'Não foi possível abrir o modelo:\n{error}')
                self.figure = previous
                self.select_current_model()
                return
            QApplication.restoreOverrideCursor()
            triangles = f'{self.figure.model.triangles:,}'.replace(',', '.')
            if self.figure.rigged:
                self.status(f'{self.figure.model_name}: {triangles} triângulos · {len(self.figure.deform)} ossos.')
            else:
                self.status(f'{self.figure.model_name}: {triangles} triângulos · sem esqueleto (só luz e sombra).')
        if reframe:
            self.viewport.selected_joint = None
            self.camera.fit(self.figure, view=True)
        self.refresh_model_controls()
        self.refresh_presets()
        self.refresh_joint()
        self.viewport.request(False)

    def select_current_model(self):
        current = ('builtin', getattr(self.figure, 'model', None)) if self.figure.kind == 'mannequin' else ('file', self.figure.path)
        for index in range(self.model.count()):
            if self.model.itemData(index) == current:
                self.model.setCurrentIndex(index)
                return

    def refresh_model_controls(self):
        mannequin_figure = self.figure.kind == 'mannequin'
        self.proportion.setEnabled(mannequin_figure)
        self.colors.setVisible(not mannequin_figure)
        self.colors_label.setVisible(not mannequin_figure)
        self.pose_buttons['mirror'].setEnabled(self.figure.can_mirror)
        self.show_bones.setVisible(not mannequin_figure)
        self.floor.setEnabled(self.figure.floor_default)

    def model_key(self):
        return self.figure.model_name.split()[0] if self.figure.kind == 'mannequin' else Path(self.figure.path).name

    def refresh_presets(self):
        self.preset.blockSignals(True)
        self.preset.clear()
        for name in self.figure.presets():
            self.preset.addItem(name, ('preset', name))
        key = self.model_key()
        for name, item in sorted(self.owner.library.poses.items()):
            stored, kind = item.get('model', ''), item.get('kind', 'mannequin')
            if kind != self.figure.kind:
                continue
            if (stored.split()[0] if stored else '') == key if kind == 'mannequin' else stored == key:
                self.preset.addItem(f'★ {name}', ('custom', name))
        self.preset.blockSignals(False)
        self.preset_selected()

    def preset_selected(self):
        kind, name = self.preset.currentData() or (None, '')
        animated = kind == 'preset' and str(name).startswith('Animação:')
        self.time.setVisible(animated)
        self.time_label.setVisible(animated)

    def apply_preset(self):
        kind, name = self.preset.currentData() or (None, None)
        if kind == 'preset':
            self.figure.apply_preset(name, self.time.value() / 100)
        elif kind == 'custom':
            item = self.owner.library.poses[name]
            pose = item['pose']
            if self.figure.kind == 'mannequin' and item.get('model') != self.figure.model:
                pose = mannequin.mirror_names(pose)
            self.figure.load_pose(pose)
        self.refresh_joint()
        self.viewport.request()

    def save_pose(self):
        name, accepted = QInputDialog.getText(self, 'Salvar pose', 'Nome da pose:')
        if accepted and name.strip():
            model = self.figure.model_name if self.figure.kind == 'mannequin' else self.model_key()
            self.owner.library.poses[name.strip()] = {'model': model, 'kind': self.figure.kind,
                                                      'pose': self.figure.serialize_pose()}
            self.owner.library.save()
            self.refresh_presets()
            self.preset.setCurrentIndex(self.preset.findText(f'★ {name.strip()}'))

    def delete_pose(self):
        kind, name = self.preset.currentData() or (None, None)
        if kind != 'custom':
            QMessageBox.information(self, 'Poses', 'As poses prontas não podem ser excluídas; escolha uma pose salva (★).')
            return
        self.owner.library.poses.pop(name, None)
        self.owner.library.save()
        self.refresh_presets()

    def mirror(self):
        if self.figure.can_mirror:
            self.figure.mirrored()
            self.refresh_joint()
            self.viewport.request(False)

    def reset_joint(self):
        if self.viewport.selected_joint is not None:
            self.figure.reset_joint(self.viewport.selected_joint)
            self.refresh_joint()
            self.viewport.request(False)

    def reset_all(self):
        self.figure.pose = {}
        self.refresh_joint()
        self.viewport.request(False)

    def refresh_joint(self):
        key = self.viewport.selected_joint
        self.updating = True
        valid = key is not None
        self.joint_label.setText(tr(self.figure.label(key)) if valid else 'Clique numa parte do modelo para selecioná-la')
        values = self.figure.rotation_values(key) if valid else [0, 0, 0]
        for slider, value in zip(self.axis_sliders, values):
            slider.setEnabled(valid)
            slider.setValue(round(value))
        self.updating = False

    def set_axis(self, axis, value):
        key = self.viewport.selected_joint
        if self.updating or key is None:
            return
        self.figure.set_rotation_value(key, axis, float(value))
        self.viewport.request()

    # ---------------------------------------------------------- insert

    def insert(self):
        document = self.owner.canvas.document
        aspect = self.viewport.width() / max(1, self.viewport.height())
        width = document.width * .9
        height = width / aspect
        if height > document.height * .9:
            height = document.height * .9
            width = height * aspect
        scale = min(1., math.sqrt(4_000_000 / max(1., width * height)))
        width, height = max(8, int(width * scale)), max(8, int(height * scale))
        supersample = 2 if width * height <= 1_200_000 else 1
        settings = self.settings()
        line = settings['line_width'] * width / max(1, self.viewport.width())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.figure.render(self.camera, width, height, light=settings['light'], supersample=supersample,
                                        cast_shadows=settings['cast'], floor=settings['floor'], line_width=line,
                                        outline=settings['outline'], textures=settings['use_albedo'])
        finally:
            QApplication.restoreOverrideCursor()
        if self.separate.isChecked():
            plain = dict(settings, shadow=dict(settings['shadow'], strength=0.))
            rgb, alpha = mannequin.compose(dict(result, floor=np.zeros_like(result['floor'])), plain)
            base = shading.to_image(rgb, alpha)
            mask = shading.to_image(np.zeros(result['alpha'].shape + (3,), np.float32), mannequin.shadow_mask(result))
        else:
            base, mask = shading.to_image(*mannequin.compose(result, settings)), None
        origin = QPointF((document.width - width) / 2, (document.height - height) / 2)
        shadow = settings['shadow']
        if len(document.layers) + (2 if mask is not None else 1) > 64:
            QMessageBox.warning(self, 'Manequim 3D', 'Limite de 64 camadas atingido.')
            return
        name = self.figure.model_name

        def add(document):
            layer = document.blank_layer(f'Modelo 3D · {name}'[:60])
            painter = QPainter(layer.image)
            painter.drawImage(origin, base)
            painter.end()
            layer.content = True
            document.active += 1
            document.layers.insert(document.active, layer)
            if mask is not None:
                shadow_layer = document.shadow_layer('Sombra do modelo 3D', shadow['style'])
                shadow_layer.shadow.update(shadow)
                painter = QPainter(shadow_layer.image)
                painter.drawImage(origin, mask)
                painter.end()
                shadow_layer.content = True
                document.active += 1
                document.layers.insert(document.active, shadow_layer)
        self.owner.layer_change(add)
        self.owner.statusBar().showMessage('Modelo inserido. A sombra está numa camada de sombra: troque o estilo no painel Camadas.'
                                           if mask is not None else 'Modelo inserido como camada.', 8000)
