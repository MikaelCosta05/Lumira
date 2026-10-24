import struct

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget)

from comics import COMIC_FORMATS
from resources import write_palette


class NewDocumentDialog(QDialog):
    # name, width, height, dpi, bleed, safe
    PRESETS = {
        'Ilustração': [('Full HD', 1920, 1080, 72, 0, 0), ('4K / UHD', 3840, 2160, 72, 0, 0),
                       ('A4 · 300 dpi', 2480, 3508, 300, 0, 0), ('A3 · 300 dpi', 3508, 4961, 300, 0, 0),
                       ('Ilustração quadrada', 2048, 2048, 300, 0, 0), ('Papel de parede celular', 1170, 2532, 72, 0, 0)],
        'Pixel art e sprites': [('Pixel art · 16', 16, 16, 72, 0, 0), ('Pixel art · 32', 32, 32, 72, 0, 0),
                                ('Sprite · 64', 64, 64, 72, 0, 0), ('Sprite · 128', 128, 128, 72, 0, 0),
                                ('Sprite · 256', 256, 256, 72, 0, 0), ('Tela retrô · 320 × 180', 320, 180, 72, 0, 0),
                                ('Tela GBA · 240 × 160', 240, 160, 72, 0, 0), ('Tileset · 256 × 256', 256, 256, 72, 0, 0)],
        'Animação e vídeo': [('Vídeo · 720p', 1280, 720, 72, 0, 0), ('Vídeo · Full HD', 1920, 1080, 72, 0, 0),
                             ('Vertical / Reels', 1080, 1920, 72, 0, 0), ('Quadrado', 1080, 1080, 72, 0, 0),
                             ('Vídeo · 4K', 3840, 2160, 72, 0, 0), ('Storyboard · 1280 × 540', 1280, 540, 72, 0, 0)],
        'Quadrinhos': [(name, w, h, dpi, bleed, safe) for name, w, h, dpi, bleed, safe in COMIC_FORMATS],
    }

    def __init__(self, parent, category=None):
        super().__init__(parent)
        self.setWindowTitle('Criar novo arquivo')
        self.resize(760, 500)
        layout = QHBoxLayout(self)
        self.tabs = QTabWidget()
        for name, presets in self.PRESETS.items():
            page = QWidget()
            grid = QGridLayout(page)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop)
            for index, preset in enumerate(presets):
                button = QPushButton(f'{preset[0]}\n{preset[1]} × {preset[2]} px')
                button.setMinimumSize(150, 58)
                button.clicked.connect(lambda checked=False, c=name, p=preset: self.select(c, p))
                grid.addWidget(button, index // 2, index % 2)
            self.tabs.addTab(page, name)
        layout.addWidget(self.tabs, 1)
        form = QFormLayout()
        self.name = QLineEdit('Sem título')
        self.width, self.height, self.dpi, self.fps = QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox()
        self.bleed, self.safe = QSpinBox(), QSpinBox()
        for widget, maximum, value in [(self.width, 8192, 1920), (self.height, 8192, 1080), (self.dpi, 1200, 72),
                                       (self.fps, 120, 12), (self.bleed, 2000, 0), (self.safe, 2000, 0)]:
            widget.setRange(0 if widget in (self.bleed, self.safe) else 1, maximum)
            widget.setValue(value)
        self.paper = QCheckBox('Papel branco')
        self.paper.setChecked(True)
        self.animation = QCheckBox('Criar como animação')
        self.panels = QCheckBox('Gerar quadros de quadrinho em seguida')
        form.addRow('Nome', self.name)
        form.addRow('Largura (px)', self.width)
        form.addRow('Altura (px)', self.height)
        swap = QPushButton('Trocar orientação')
        swap.clicked.connect(self.swap)
        form.addRow(swap)
        form.addRow('Resolução (dpi)', self.dpi)
        form.addRow(self.paper)
        form.addRow(self.animation)
        form.addRow('Quadros / segundo', self.fps)
        form.addRow('Sangria (px)', self.bleed)
        form.addRow('Área segura (px)', self.safe)
        form.addRow(self.panels)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Criar arquivo')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        layout.addLayout(form)
        if category in self.PRESETS:
            self.tabs.setCurrentIndex(list(self.PRESETS).index(category))
            self.select(category, self.PRESETS[category][0])

    def select(self, category, preset):
        name, width, height, dpi, bleed, safe = preset
        self.width.setValue(width)
        self.height.setValue(height)
        self.dpi.setValue(dpi)
        self.bleed.setValue(bleed)
        self.safe.setValue(safe)
        self.paper.setChecked(category != 'Pixel art e sprites')
        self.animation.setChecked(category == 'Animação e vídeo')
        self.panels.setChecked(category == 'Quadrinhos' and 'Webtoon' not in name)
        if self.name.text() in ('Sem título', '') or self.name.text().startswith('Página'):
            self.name.setText('Página 1' if category == 'Quadrinhos' else 'Sem título')

    def swap(self):
        width = self.width.value()
        self.width.setValue(self.height.value())
        self.height.setValue(width)

    def validate(self):
        if self.width.value() * self.height.value() > 24_000_000:
            QMessageBox.warning(self, 'Dimensões', 'Use até 24 milhões de pixels nesta versão.')
            return
        self.accept()


class PalettePanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self.refresh_colors)
        layout.addWidget(self.combo)
        self.grid = QGridLayout()
        self.grid.setSpacing(4)
        layout.addLayout(self.grid)
        row = QHBoxLayout()
        row.setSpacing(2)
        for name, tip, callback in [('palette-swatch-outline', 'Criar paleta', self.create),
                                    ('plus', 'Adicionar a cor principal à paleta', self.add_color),
                                    ('eyedropper-plus', 'Escolher cor para adicionar…', self.pick_color),
                                    ('tray-arrow-down', 'Importar paleta (.json, .gpl, .hex, .txt, .aco, .ase)', self.import_),
                                    ('tray-arrow-up', 'Exportar paleta (.json, .gpl, .hex)', self.export_),
                                    ('delete-outline', 'Excluir paleta', self.delete)]:
            row.addWidget(self.owner.icon_button(name, tip, callback))
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel('Clique: usar cor · Botão direito: remover')
        hint.setObjectName('muted')
        layout.addWidget(hint)
        layout.addStretch()
        self.refresh()

    def refresh(self, selected=None):
        self.combo.blockSignals(True)
        self.combo.clear()
        for name in self.owner.library.palettes:
            self.combo.addItem(name, name)
        if selected:
            self.combo.setCurrentIndex(max(0, self.combo.findData(selected)))
        self.combo.blockSignals(False)
        self.refresh_colors()

    def refresh_colors(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        colors = self.owner.library.palettes.get(self.name(), [])
        for index, color in enumerate(colors):
            button = QPushButton()
            button.setFixedSize(28, 22)
            button.setToolTip(color)
            button.setStyleSheet(f'background:{color};border:1px solid #777;border-radius:3px;padding:0;')
            button.clicked.connect(lambda checked=False, c=color: self.owner.set_color(QColor(c)))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda point, i=index, b=button: self.color_menu(i, b, point))
            self.grid.addWidget(button, index // 7, index % 7)

    def name(self):
        return self.combo.currentData() or ''

    def palette(self):
        return self.owner.library.palettes.get(self.name())

    def color_menu(self, index, button, point):
        menu = QMenu(self)
        menu.addAction('Usar como cor principal', lambda: self.owner.set_color(QColor(self.palette()[index])))
        menu.addAction('Substituir pela cor principal', lambda: self.replace_color(index))
        menu.addAction('Remover da paleta', lambda: self.remove_color(index))
        menu.exec(button.mapToGlobal(point))

    def changed(self, selected=None):
        self.owner.library.save()
        self.refresh(selected or self.name())

    def replace_color(self, index):
        self.palette()[index] = self.owner.current_color.name()
        self.changed()

    def remove_color(self, index):
        colors = self.palette()
        if len(colors) <= 1:
            QMessageBox.information(self, 'Paleta', 'A paleta precisa de pelo menos uma cor. Exclua a paleta inteira se preferir.')
            return
        colors.pop(index)
        self.changed()

    def create(self):
        name, ok = QInputDialog.getText(self, 'Criar paleta', 'Nome:')
        if ok and name.strip():
            name = self.owner.library.unique_palette_name(name)
            self.owner.library.palettes[name] = [self.owner.current_color.name()]
            self.changed(name)

    def add_color(self):
        colors = self.palette()
        if colors is not None and len(colors) < 256:
            colors.append(self.owner.current_color.name())
            self.changed()

    def pick_color(self):
        color = QColorDialog.getColor(self.owner.current_color, self, 'Adicionar cor')
        colors = self.palette()
        if color.isValid() and colors is not None and len(colors) < 256:
            colors.append(color.name())
            self.changed()

    def import_(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar paleta', '',
            'Paletas (*.json *.gpl *.hex *.txt *.aco *.ase);;Photoshop (*.aco *.ase);;GIMP / Krita / Aseprite (*.gpl)')
        if path:
            try:
                self.changed(self.owner.library.import_palette(path))
            except (OSError, ValueError, KeyError, struct.error) as error:
                QMessageBox.warning(self, 'Importar paleta', str(error) or 'Arquivo de paleta inválido.')

    def export_(self):
        name = self.name()
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar paleta', name + '.gpl',
                                              'GIMP / Krita / Aseprite (*.gpl);;Paleta JSON (*.json);;Lospec HEX (*.hex)')
        if path:
            try:
                write_palette(path, name, self.palette())
            except OSError as error:
                QMessageBox.warning(self, 'Exportar paleta', str(error))

    def delete(self):
        name = self.name()
        if len(self.owner.library.palettes) <= 1:
            return
        answer = QMessageBox.question(self, 'Excluir paleta', f'Excluir a paleta “{name}”?')
        if answer == QMessageBox.StandardButton.Yes:
            self.owner.library.delete_palette(name)
            self.refresh()
