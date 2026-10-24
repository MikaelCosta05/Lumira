"""Appearance dialog: colour themes per mode, background image, typography and shapes, with live preview."""
import copy

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFontComboBox,
                             QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider,
                             QSpinBox, QTabWidget, QVBoxLayout, QWidget)

import appearance

MODES = [('Escuro', 'Modo escuro'), ('Claro', 'Modo claro')]


class ColorButton(QPushButton):
    """Swatch + hex code; opens the colour picker."""
    picked = pyqtSignal(str)

    def __init__(self, title):
        super().__init__()
        self.title = title
        self.color = '#000000'
        self.setMinimumWidth(118)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.choose)

    def set_color(self, color):
        self.color = QColor(color).name()
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(self.color))
        self.setIcon(QIcon(pixmap))
        self.setText(self.color.upper())

    def choose(self):
        color = QColorDialog.getColor(QColor(self.color), self, self.title)
        if color.isValid() and color.name() != self.color:
            self.set_color(color.name())
            self.picked.emit(self.color)


def slider(low, high, value, suffix=''):
    widget = QSlider(Qt.Orientation.Horizontal)
    widget.setRange(low, high)
    widget.setValue(value)
    label = QLabel()
    label.setMinimumWidth(42)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    update = lambda v: label.setText(f'{v}{suffix}')
    widget.valueChanged.connect(update)
    update(value)
    return widget, label


class AppearanceDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.original = copy.deepcopy(owner.appearance)
        self.original_theme = owner.theme
        self.value = copy.deepcopy(owner.appearance)
        self.mode = owner.theme
        self.loading = False
        self.setWindowTitle('Personalizar aparência')
        self.resize(760, 600)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(90)
        self.preview_timer.timeout.connect(self.preview)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self.colors_page(), 'Cores')
        tabs.addTab(self.background_page(), 'Imagem de fundo')
        tabs.addTab(self.interface_page(), 'Texto e formas')
        layout.addWidget(tabs, 1)
        buttons = QHBoxLayout()
        for text, callback in (('Importar tema…', self.import_theme), ('Exportar tema…', self.export_theme),
                               ('Restaurar padrão', self.restore_defaults)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        cancel = QPushButton('Cancelar')
        cancel.clicked.connect(self.reject)
        done = QPushButton('Aplicar')
        done.setObjectName('primary')
        done.setDefault(True)
        done.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(done)
        layout.addLayout(buttons)
        self.load_controls()

    # ------------------------------------------------------------- colours

    def colors_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        top.addWidget(QLabel('Tema de cores'))
        self.preset = QComboBox()
        self.preset.setIconSize(QSize(36, 18))
        self.preset.setMinimumWidth(240)
        self.preset.currentIndexChanged.connect(self.choose_preset)
        top.addWidget(self.preset)
        top.addStretch()
        self.mode_buttons = QButtonGroup(self)
        for mode, label in MODES:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty('mode', mode)
            self.mode_buttons.addButton(button)
            top.addWidget(button)
        self.mode_buttons.buttonClicked.connect(lambda button: self.set_mode(button.property('mode')))
        layout.addLayout(top)
        hint = QLabel('Cada modo guarda as próprias cores. A prévia mostra o modo que você está editando; '
                      'ao mudar só a cor de destaque, o item selecionado acompanha automaticamente.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.color_buttons, self.reset_buttons = {}, {}
        for index, (key, label) in enumerate(appearance.COLOR_KEYS):
            row, column = index % 7, (index // 7) * 3
            grid.addWidget(QLabel(label), row, column)
            button = ColorButton(label)
            button.picked.connect(lambda color, k=key: self.set_color(k, color))
            grid.addWidget(button, row, column + 1)
            reset = QPushButton('↺')
            reset.setObjectName('quietButton')
            reset.setToolTip('Voltar à cor do tema')
            reset.setFixedWidth(28)
            reset.clicked.connect(lambda checked=False, k=key: self.reset_color(k))
            grid.addWidget(reset, row, column + 2)
            self.color_buttons[key], self.reset_buttons[key] = button, reset
        grid.setColumnStretch(2, 1)
        layout.addWidget(grid_widget)
        layout.addStretch()
        reset_mode = QPushButton('Restaurar as cores deste modo')
        reset_mode.clicked.connect(self.reset_mode)
        row = QHBoxLayout()
        row.addWidget(reset_mode)
        row.addStretch()
        layout.addLayout(row)
        return page

    def fill_presets(self):
        self.preset.blockSignals(True)
        self.preset.clear()
        for name in appearance.PRESET_NAMES:
            colors = appearance.palette(self.mode, {'colors': appearance.preset_colors(name)})
            self.preset.addItem(appearance.swatch_icon(colors), name, name)
        if self.value['preset'] == 'Personalizado':
            colors = appearance.palette(self.mode, self.value)
            self.preset.addItem(appearance.swatch_icon(colors), 'Personalizado', 'Personalizado')
        self.preset.setCurrentIndex(max(0, self.preset.findData(self.value['preset'])))
        self.preset.blockSignals(False)

    def choose_preset(self):
        name = self.preset.currentData()
        if self.loading or name in (None, 'Personalizado'):
            return
        self.value['preset'] = name
        self.value['colors'] = appearance.preset_colors(name)
        self.sync_colors()
        self.schedule()

    def set_mode(self, mode):
        self.mode = mode
        self.owner.apply_theme(mode)
        self.sync_colors()

    def set_color(self, key, color):
        self.value['colors'][self.mode][key] = color
        self.mark_custom()
        self.sync_colors()
        self.schedule()

    def reset_color(self, key):
        self.value['colors'][self.mode].pop(key, None)
        self.mark_custom()
        self.sync_colors()
        self.schedule()

    def reset_mode(self):
        self.value['colors'][self.mode] = {}
        self.mark_custom()
        self.sync_colors()
        self.schedule()

    def mark_custom(self):
        if self.value['colors'] != appearance.preset_colors(self.value['preset']):
            self.value['preset'] = 'Personalizado'

    def sync_colors(self):
        colors = appearance.palette(self.mode, self.value)
        overrides = self.value['colors'][self.mode]
        for key, button in self.color_buttons.items():
            button.set_color(colors[key])
            self.reset_buttons[key].setEnabled(key in overrides)
        for button in self.mode_buttons.buttons():
            button.setChecked(button.property('mode') == self.mode)
        self.fill_presets()

    # ----------------------------------------------------------- background

    def background_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.background_preview = QLabel()
        self.background_preview.setFixedSize(300, 170)
        self.background_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.background_preview)
        side = QVBoxLayout()
        choose = QPushButton('Escolher imagem…')
        choose.clicked.connect(self.choose_background)
        self.remove_background = QPushButton('Remover imagem')
        self.remove_background.clicked.connect(lambda: self.set_value('background', ''))
        self.background_name = QLabel()
        self.background_name.setObjectName('muted')
        self.background_name.setWordWrap(True)
        for widget in (choose, self.remove_background, self.background_name):
            side.addWidget(widget)
        side.addStretch()
        row.addLayout(side, 1)
        layout.addLayout(row)
        grid = QGridLayout()
        self.fit = QComboBox()
        for label, value in appearance.FITS:
            self.fit.addItem(label, value)
        self.fit.currentIndexChanged.connect(lambda: self.set_value('background_fit', self.fit.currentData()))
        grid.addWidget(QLabel('Ajuste'), 0, 0)
        grid.addWidget(self.fit, 0, 1, 1, 2)
        self.sliders = {}
        rows = [('background_opacity', 'Intensidade da imagem', 0, 100, '%', 100),
                ('background_blur', 'Desfoque', 0, 40, ' px', 1),
                ('panel_opacity', 'Opacidade dos painéis', 30, 100, '%', 100),
                ('canvas_opacity', 'Cor sobre a imagem ao redor do desenho', 0, 100, '%', 100)]
        for index, (key, label, low, high, suffix, scale) in enumerate(rows, 1):
            widget, value_label = slider(low, high, round(self.value[key] * scale), suffix)
            widget.valueChanged.connect(lambda v, k=key, s=scale: self.set_value(k, v / s if s != 1 else v))
            grid.addWidget(QLabel(label), index, 0)
            grid.addWidget(widget, index, 1)
            grid.addWidget(value_label, index, 2)
            self.sliders[key] = (widget, scale)
        self.background_canvas = QCheckBox('Mostrar a imagem também ao redor da tela de desenho')
        self.background_canvas.toggled.connect(lambda value: self.set_value('background_canvas', value))
        grid.addWidget(self.background_canvas, len(rows) + 1, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return page

    def choose_background(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Imagem de fundo', '',
                                              'Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.gif)')
        if not path:
            return
        if appearance.Background().load(path):
            self.set_value('background', path)
        else:
            QMessageBox.warning(self, 'Imagem de fundo', 'Não foi possível abrir a imagem.')

    def sync_background(self):
        path = self.value['background']
        self.remove_background.setEnabled(bool(path))
        self.background_name.setText(path.replace('\\', '/').split('/')[-1] if path else 'Nenhuma imagem: a janela usa a cor de fundo.')
        background = self.owner.background if path == self.owner.background.path else appearance.Background()
        if path and background.source is None:
            background.load(path)
        colors = appearance.palette(self.mode, self.value)
        settings = dict(self.value, background_opacity=self.value['background_opacity'] if path else 0)
        pixmap = background.pixmap(self.background_preview.size(), settings, colors['bg']).copy()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        panel = QColor(colors['panel'])
        panel.setAlphaF(self.value['panel_opacity'] if path else 1.)
        painter.setBrush(panel)
        painter.drawRoundedRect(QRectF(8, 8, 36, 154), 6, 6)
        painter.drawRoundedRect(QRectF(212, 8, 80, 154), 6, 6)
        painter.setBrush(QColor('white'))
        painter.drawRect(QRectF(70, 30, 116, 110))
        painter.setBrush(QColor(colors['accent']))
        painter.drawRoundedRect(QRectF(14, 16, 24, 14), 3, 3)
        painter.end()
        self.background_preview.setPixmap(pixmap)

    # ------------------------------------------------------------ interface

    def interface_page(self):
        page = QWidget()
        grid = QGridLayout(page)
        self.default_font = QCheckBox('Usar a fonte padrão do programa (Inter)')
        self.default_font.toggled.connect(self.font_changed)
        self.font = QFontComboBox()
        self.font.currentFontChanged.connect(self.font_changed)
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 16)
        self.font_size.setSuffix(' px')
        self.font_size.valueChanged.connect(lambda v: self.set_value('font_size', v))
        self.radius, radius_label = slider(0, 16, self.value['radius'], ' px')
        self.radius.valueChanged.connect(lambda v: self.set_value('radius', v))
        self.border_width = QSpinBox()
        self.border_width.setRange(0, 3)
        self.border_width.setSuffix(' px')
        self.border_width.valueChanged.connect(lambda v: self.set_value('border_width', v))
        grid.addWidget(self.default_font, 0, 0, 1, 3)
        grid.addWidget(QLabel('Fonte da interface'), 1, 0)
        grid.addWidget(self.font, 1, 1, 1, 2)
        grid.addWidget(QLabel('Tamanho do texto'), 2, 0)
        grid.addWidget(self.font_size, 2, 1)
        grid.addWidget(QLabel('Cantos arredondados'), 3, 0)
        grid.addWidget(self.radius, 3, 1)
        grid.addWidget(radius_label, 3, 2)
        grid.addWidget(QLabel('Espessura das bordas'), 4, 0)
        grid.addWidget(self.border_width, 4, 1)
        self.sample = QLabel('Exemplo: Aa Bb Cc 0123 — Pincel, Camadas, Animação')
        self.sample.setObjectName('title')
        grid.addWidget(self.sample, 5, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(6, 1)
        return page

    def font_changed(self):
        default = self.default_font.isChecked()
        self.font.setEnabled(not default)
        if not self.loading:
            self.set_value('font_family', '' if default else self.font.currentFont().family())

    # -------------------------------------------------------------- state

    def load_controls(self):
        self.loading = True
        self.sync_colors()
        self.fit.setCurrentIndex(max(0, self.fit.findData(self.value['background_fit'])))
        for key, (widget, scale) in self.sliders.items():
            widget.setValue(round(self.value[key] * scale))
        self.background_canvas.setChecked(self.value['background_canvas'])
        self.default_font.setChecked(not self.value['font_family'])
        if self.value['font_family']:
            self.font.setCurrentFont(QFont(self.value['font_family']))
        self.font.setEnabled(bool(self.value['font_family']))
        self.font_size.setValue(self.value['font_size'])
        self.radius.setValue(self.value['radius'])
        self.border_width.setValue(self.value['border_width'])
        self.loading = False
        self.sync_background()

    def set_value(self, key, value):
        if self.loading:
            return
        self.value[key] = value
        if key.startswith('background') or key in ('panel_opacity', 'canvas_opacity'):
            self.sync_background()
        self.schedule()

    def schedule(self):
        if not self.loading:
            self.preview_timer.start()

    def preview(self):
        self.owner.apply_appearance(self.value)
        self.value = copy.deepcopy(self.owner.appearance)

    def restore_defaults(self):
        self.value = appearance.normalize({})
        self.load_controls()
        self.schedule()

    def import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar tema', '', appearance.FILE_FILTER)
        if not path:
            return
        try:
            self.value = appearance.import_theme(path, self.value)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Importar tema', str(error))
            return
        self.load_controls()
        self.schedule()

    def export_theme(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar tema', 'meu-tema.studiotheme', appearance.FILE_FILTER)
        if path:
            try:
                appearance.export_theme(path, self.value)
            except OSError as error:
                QMessageBox.warning(self, 'Exportar tema', str(error))

    def accept(self):
        self.preview_timer.stop()
        self.owner.apply_appearance(self.value)
        if self.owner.theme != self.original_theme:
            self.owner.apply_theme(self.original_theme)
        super().accept()

    def reject(self):
        self.preview_timer.stop()
        self.owner.apply_appearance(self.original)
        if self.owner.theme != self.original_theme:
            self.owner.apply_theme(self.original_theme)
        super().reject()

