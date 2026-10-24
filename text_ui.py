"""Text tool dialog: font, size, style, colour, outline (comic lettering) and alignment."""
from PyQt6.QtCore import QPointF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox,
                             QVBoxLayout)

import drawing_tools

ALIGNMENTS = [('Esquerda', Qt.AlignmentFlag.AlignLeft), ('Centro', Qt.AlignmentFlag.AlignHCenter),
              ('Direita', Qt.AlignmentFlag.AlignRight)]


class TextDialog(QDialog):
    def __init__(self, owner, settings=None):
        super().__init__(owner)
        self.owner = owner
        settings = settings or {}
        self.setWindowTitle('Texto')
        self.resize(560, 470)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(settings.get('text', ''))
        self.text.setPlaceholderText('Digite o texto (Enter cria uma nova linha)')
        self.text.setMinimumHeight(70)
        self.text.setMaximumHeight(110)
        layout.addWidget(self.text)
        form = QFormLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(settings.get('family', 'Inter')))
        self.size = QSpinBox()
        self.size.setRange(4, 1000)
        self.size.setValue(settings.get('size', 48))
        self.size.setSuffix(' px')
        style = QHBoxLayout()
        self.bold, self.italic = QCheckBox('Negrito'), QCheckBox('Itálico')
        self.bold.setChecked(settings.get('bold', False))
        self.italic.setChecked(settings.get('italic', False))
        style.addWidget(self.bold)
        style.addWidget(self.italic)
        style.addStretch()
        self.align = QComboBox()
        for label, value in ALIGNMENTS:
            self.align.addItem(label, value)
        self.color = QColor(owner.current_color)
        self.outline_color = QColor(settings.get('outline_color', '#ffffff'))
        self.color_button, self.outline_button = QPushButton(), QPushButton()
        self.color_button.clicked.connect(lambda: self.choose('color'))
        self.outline_button.clicked.connect(lambda: self.choose('outline_color'))
        colors = QHBoxLayout()
        colors.addWidget(QLabel('Texto'))
        colors.addWidget(self.color_button)
        colors.addSpacing(12)
        self.outline = QCheckBox('Contorno')
        self.outline.setChecked(settings.get('outline', False))
        colors.addWidget(self.outline)
        colors.addWidget(self.outline_button)
        self.outline_width = QDoubleSpinBox()
        self.outline_width.setRange(.5, 60)
        self.outline_width.setValue(settings.get('outline_width', 4))
        self.outline_width.setSuffix(' px')
        colors.addWidget(self.outline_width)
        colors.addStretch()
        self.new_layer = QCheckBox('Criar em uma nova camada')
        self.new_layer.setChecked(settings.get('new_layer', True))
        form.addRow('Fonte', self.font)
        form.addRow('Tamanho', self.size)
        form.addRow('Estilo', style)
        form.addRow('Alinhamento', self.align)
        form.addRow('Cores', colors)
        form.addRow(self.new_layer)
        layout.addLayout(form)
        self.preview = QLabel()
        self.preview.setMinimumHeight(130)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('background:#f4f1ea;border-radius:6px;')
        layout.addWidget(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Inserir texto')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for signal in (self.text.textChanged, self.font.currentFontChanged, self.size.valueChanged, self.bold.toggled,
                       self.italic.toggled, self.align.currentIndexChanged, self.outline.toggled, self.outline_width.valueChanged):
            signal.connect(self.refresh)
        self.refresh()

    def choose(self, key):
        color = QColorDialog.getColor(getattr(self, key), self, 'Escolher cor')
        if color.isValid():
            setattr(self, key, color)
            self.refresh()

    def qfont(self, scale=1.):
        font = QFont(self.font.currentFont())
        font.setPixelSize(max(4, round(self.size.value() * scale)))
        font.setBold(self.bold.isChecked())
        font.setItalic(self.italic.isChecked())
        return font

    def render(self, size, position, scale=1.):
        return drawing_tools.render_text(size, position, self.text.toPlainText(), self.qfont(scale), self.color,
                                         self.outline_color if self.outline.isChecked() else None,
                                         self.outline_width.value() * scale, self.align.currentData())

    def refresh(self):
        for button, color in ((self.color_button, self.color), (self.outline_button, self.outline_color)):
            button.setStyleSheet(f'background:{color.name()};border:1px solid #888;border-radius:5px;min-width:34px;')
        width, height = max(200, self.preview.width() - 16), max(110, self.preview.height() - 12)
        lines = max(1, len(self.text.toPlainText().split('\n')))
        scale = min(1., (height - 16) / (max(1, self.size.value()) * 1.3 * lines))
        image = self.render(QSize(width, height), QPointF(10, 8), scale)
        self.preview.setPixmap(QPixmap.fromImage(image))

    def settings(self):
        return {'text': self.text.toPlainText(), 'family': self.font.currentFont().family(), 'size': self.size.value(),
                'bold': self.bold.isChecked(), 'italic': self.italic.isChecked(), 'outline': self.outline.isChecked(),
                'outline_color': self.outline_color.name(), 'outline_width': self.outline_width.value(),
                'new_layer': self.new_layer.isChecked()}
