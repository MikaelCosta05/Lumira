"""Shadow layer properties: style, colour, blending and conversion."""
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

import shading
from document import draw_layer


def composite_below(document, index, paper=True):
    """Visible layers under `index` (current frame), as the shadow sees them."""
    image = QImage(document.width, document.height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('white') if paper and document.paper_visible else QColor(0, 0, 0, 0))
    painter = QPainter(image)
    for layer in document.layers[:index]:
        if layer.visible and not layer.is_shadow:
            draw_layer(painter, layer)
    painter.end()
    return image


class ShadowLayerPanel(QFrame):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.updating = False
        self.setObjectName('shadowPanel')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        top = QHBoxLayout()
        title = QLabel('Sombra:')
        title.setObjectName('muted')
        top.addWidget(title)
        self.more = QToolButton()
        self.more.setObjectName('quietButton')
        self.more.setCheckable(True)
        self.more.setText('Ajustes')
        self.more.setToolTip('Cor, mistura, espaçamento, ângulo, intensidade e conversão')
        self.more.toggled.connect(lambda value: self.details.setVisible(value))
        self.details = QWidget()
        grid = QGridLayout(self.details)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.style = QComboBox()
        for label, value in shading.STYLES:
            self.style.addItem(label, value)
        self.style.setToolTip('Pinte aqui com qualquer ferramenta: tudo vira sombra no estilo escolhido. '
                              'Traços mais escuros e opacos geram sombra mais forte.')
        self.style.currentIndexChanged.connect(self.change_style)
        self.color = QPushButton()
        self.color.setFixedHeight(22)
        self.color.setToolTip('Cor da sombra')
        self.color.clicked.connect(self.choose_color)
        self.blend = QComboBox()
        self.blend.addItem('Multiplicar', 'multiply')
        self.blend.addItem('Normal', 'normal')
        self.blend.setToolTip('Mistura com o desenho de baixo')
        self.blend.currentIndexChanged.connect(lambda: self.change(blend=self.blend.currentData()))
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(2, 80)
        self.spacing.setSuffix(' px')
        self.spacing.setDecimals(1)
        self.spacing.setToolTip('Espaçamento das linhas ou pontos')
        self.spacing.editingFinished.connect(lambda: self.change(spacing=self.spacing.value()))
        self.angle = QSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setSuffix('°')
        self.angle.setToolTip('Ângulo da hachura ou da retícula')
        self.angle.editingFinished.connect(lambda: self.change(angle=float(self.angle.value())))
        self.strength = QSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setSuffix('%')
        self.strength.setToolTip('Intensidade da sombra')
        self.strength.editingFinished.connect(lambda: self.change(strength=self.strength.value() / 100))
        convert = QPushButton('Em pixels')
        convert.setToolTip('Converte a sombra estilizada numa camada comum, com a mesma aparência')
        convert.clicked.connect(self.convert)
        merge = QPushButton('Mesclar abaixo')
        merge.setToolTip('Aplica a sombra na camada de baixo, só onde ela tem desenho, e remove esta camada')
        merge.clicked.connect(self.merge_down)
        top.addWidget(self.style, 1)
        top.addWidget(self.more)
        layout.addLayout(top)
        grid.addWidget(self.color, 1, 0)
        grid.addWidget(self.blend, 1, 1, 1, 2)
        grid.addWidget(self.spacing, 2, 0)
        grid.addWidget(self.angle, 2, 1)
        grid.addWidget(self.strength, 2, 2)
        grid.addWidget(convert, 3, 0)
        grid.addWidget(merge, 3, 1, 1, 2)
        layout.addWidget(self.details)
        self.details.hide()

    def layer(self):
        document = self.owner.canvas.document
        return document.layers[document.active]

    def refresh(self):
        layer = self.layer()
        self.setVisible(layer.is_shadow)
        if not layer.is_shadow:
            return
        self.updating = True
        settings = dict(shading.DEFAULT_SHADOW, **layer.shadow)
        self.style.setCurrentIndex(max(0, self.style.findData(settings['style'])))
        self.color.setStyleSheet(f"background:{settings['color']};border:1px solid #888;border-radius:3px;")
        self.color.setToolTip(settings['color'])
        self.blend.setCurrentIndex(max(0, self.blend.findData(settings['blend'])))
        self.spacing.setValue(settings['spacing'])
        self.angle.setValue(round(settings['angle']))
        self.strength.setValue(round(settings['strength'] * 100))
        ink = settings['style'] in shading.INK_STYLES
        self.spacing.setEnabled(ink)
        self.angle.setEnabled(ink)
        colored = settings['style'] == 'colored'
        self.color.setEnabled(not colored)
        self.blend.setEnabled(not colored)
        self.updating = False

    def change(self, **values):
        if self.updating or not self.layer().is_shadow:
            return
        if all(self.layer().shadow.get(key) == value for key, value in values.items()):
            return
        self.owner.layer_change(lambda d: d.layers[d.active].shadow.update(values))

    def change_style(self):
        if self.updating:
            return
        style = self.style.currentData()
        settings = shading.settings_for(style, self.layer().shadow)
        self.owner.layer_change(lambda d: setattr(d.layers[d.active], 'shadow', dict(settings)))

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.layer().shadow.get('color', shading.DEFAULT_SHADOW['color'])), self, 'Cor da sombra')
        if color.isValid():
            self.change(color=color.name())

    def convert(self):
        def apply(document):
            layer = document.layers[document.active]
            settings = dict(shading.DEFAULT_SHADOW, **layer.shadow)
            layer.image = shading.bake(layer.image, settings, composite_below(document, document.active))
            layer.kind, layer.shadow = 'raster', {}
            layer.name += ' (pixels)'
            document.sync_layers()
        self.owner.mutate(apply)

    def merge_down(self):
        document = self.owner.canvas.document
        if document.active == 0:
            self.owner.statusBar().showMessage('Não há camada abaixo para mesclar.', 4000)
            return
        def apply(document):
            index = document.active
            layer, target = document.layers[index], document.layers[index - 1]
            if target.locked:
                raise ValueError('A camada de baixo está bloqueada.')
            settings = dict(shading.DEFAULT_SHADOW, **layer.shadow)
            baked = shading.bake(layer.image, settings, composite_below(document, index))
            painter = QPainter(baked)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.drawImage(0, 0, target.image)
            painter.end()
            painter = QPainter(target.image)
            painter.setOpacity(layer.opacity)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            painter.drawImage(0, 0, baked)
            painter.end()
            document.layers.pop(index)
            document.active = index - 1
            document.sync_layers()
        self.owner.mutate(apply)
