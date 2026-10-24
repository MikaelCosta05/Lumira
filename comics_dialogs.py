"""Dialogs for comic pages: panels, balloons, action lines, tones, numbers, covers and chapters."""
import random
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox)

import comics
from comic_art import BALLOONS, LINE_KINDS, TONES, action_lines, balloon, lettering_family, screentone
from comic_layouts import STYLES, label_point, scaled_shapes, shape_bounds, shapes_from_rects, stylized_layout
from comics import COMIC_FORMATS, LAYOUTS, POSITIONS, cover_document, panel_rects


class ColorButton(QPushButton):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.setFixedSize(46, 22)
        self.clicked.connect(self.choose)
        self.refresh()

    def choose(self):
        color = QColorDialog.getColor(self.color, self, 'Escolher cor')
        if color.isValid():
            self.color = color
            self.refresh()

    def refresh(self):
        self.setStyleSheet(f'background:{self.color.name()};border:1px solid #888;border-radius:3px;')
        self.setToolTip(self.color.name())


def spin(lo, hi, value, suffix=' px'):
    widget = QSpinBox()
    widget.setRange(lo, hi)
    widget.setValue(int(value))
    widget.setSuffix(suffix)
    return widget


def buttons(dialog, ok_text, accept=None):
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    box.accepted.connect(accept or dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class PagePreview(QLabel):
    def __init__(self, size=QSize(220, 300)):
        super().__init__()
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:#3a3d43;border-radius:4px;')

    def show_image(self, image):
        pixmap = QPixmap.fromImage(image).scaled(self.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(pixmap)


class PanelDialog(QDialog):
    """Panels from fixed grid templates or from stylized, randomly varied layouts."""

    def __init__(self, owner, document):
        super().__init__(owner)
        self.document = document
        self.rects, self.shapes, self.style_used = [], [], 'grid'
        self.seed = random.random()
        self.setWindowTitle('Gerar quadros da página')
        comic = document.scene.get('comic', {})
        margin, gutter, border = comics.spacing(document)
        layout = QHBoxLayout(self)
        form = QFormLayout()
        self.style_combo = QComboBox()
        self.style_combo.addItem('Grade · modelos fixos', 'grid')
        for label, key in STYLES:
            self.style_combo.addItem(label, key)
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(comic.get('panel_style', 'grid'))))
        self.variation = QPushButton('Outra variação')
        self.variation.setToolTip('Sorteia outra disposição no mesmo estilo')
        self.variation.clicked.connect(self.reroll)
        style_row = QHBoxLayout()
        style_row.addWidget(self.style_combo, 1)
        style_row.addWidget(self.variation)
        self.count = spin(0, 12, 0, '')
        self.count.setSpecialValueText('Automático')
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(list(LAYOUTS) + ['Personalizado (linhas × colunas)'])
        self.layout_combo.setCurrentText('Clássico · 6 quadros')
        self.rows, self.columns = spin(1, 12, 3, ''), spin(1, 12, 2, '')
        self.margin = spin(0, 4000, margin)
        self.gutter_x = spin(0, 2000, gutter)
        self.gutter_y = spin(0, 2000, round(gutter * 1.15))
        self.border = spin(0, 200, border)
        self.radius = spin(0, 400, 0)
        self.border_color = ColorButton('#111111')
        self.fill = QCheckBox('Preencher sarjetas (cobre a arte fora dos quadros)')
        self.fill.setChecked(True)
        self.gutter_color = ColorButton('#ffffff')
        self.direction_combo = QComboBox()
        self.direction_combo.addItem('Ocidental · esquerda → direita', 'ltr')
        self.direction_combo.addItem('Mangá · direita → esquerda', 'rtl')
        self.direction_combo.setCurrentIndex(max(0, self.direction_combo.findData(comic.get('direction', 'ltr'))))
        self.replace = QCheckBox('Substituir quadros gerados antes')
        self.replace.setChecked(bool(comic.get('panel_layer')))
        grid = QHBoxLayout()
        grid.addWidget(self.rows)
        grid.addWidget(QLabel('×'))
        grid.addWidget(self.columns)
        colors = QHBoxLayout()
        colors.addWidget(QLabel('Borda'))
        colors.addWidget(self.border_color)
        colors.addWidget(QLabel('Sarjeta'))
        colors.addWidget(self.gutter_color)
        colors.addStretch()
        for label, widget in [('Estilo', style_row), ('Quantidade de quadros', self.count),
                              ('Modelo de quadros', self.layout_combo), ('Linhas × colunas', grid),
                              ('Margem da página', self.margin), ('Espaço entre quadros', self.gutter_x),
                              ('Espaço vertical (grade)', self.gutter_y), ('Espessura da borda', self.border),
                              ('Cantos arredondados (grade)', self.radius), ('Cores', colors),
                              ('Leitura', self.direction_combo)]:
            form.addRow(label, widget)
        form.addRow(self.fill)
        form.addRow(self.replace)
        note = QLabel('Os quadros vão para a camada “Quadros”, bloqueada e no topo. Desenhe nas camadas abaixo; '
                      'a ferramenta Selecionar quadro limita a pintura a um quadro.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Gerar quadros', self.validate))
        layout.addLayout(form, 1)
        self.preview = PagePreview()
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.refresh)
        for widget in (self.rows, self.columns, self.margin, self.gutter_x, self.gutter_y, self.border, self.radius,
                       self.count):
            widget.valueChanged.connect(self.timer.start)
        for widget in (self.layout_combo, self.direction_combo, self.style_combo):
            widget.currentIndexChanged.connect(self.timer.start)
        self.fill.toggled.connect(self.timer.start)
        for button in (self.border_color, self.gutter_color):
            button.clicked.connect(self.timer.start)
        self.refresh()

    def direction(self):
        return self.direction_combo.currentData()

    def is_grid(self):
        return self.style_combo.currentData() == 'grid'

    def reroll(self):
        self.seed = random.random()
        self.refresh()

    def spec(self):
        name = self.layout_combo.currentText()
        custom = name not in LAYOUTS
        return [(1, [1] * self.columns.value())] * self.rows.value() if custom else LAYOUTS[name]

    def sync_controls(self):
        grid = self.is_grid()
        custom = self.layout_combo.currentText() not in LAYOUTS
        for widget, enabled in ((self.layout_combo, grid), (self.rows, grid and custom), (self.columns, grid and custom),
                                (self.gutter_y, grid), (self.radius, grid), (self.count, not grid),
                                (self.variation, not grid)):
            widget.setEnabled(enabled)

    def compute(self):
        """Panel shapes at full page size (cheap: only geometry)."""
        width, height = self.document.width, self.document.height
        if self.is_grid():
            rects = panel_rects(width, height, self.spec(), self.margin.value(), self.gutter_x.value(),
                                self.gutter_y.value(), self.direction() == 'rtl')
            return 'grid', shapes_from_rects(rects, self.radius.value())
        return stylized_layout(width, height, self.style_combo.currentData(), self.seed, self.margin.value(),
                               self.gutter_x.value(), self.direction() == 'rtl', self.count.value())

    def render(self, scale=1., shapes=None):
        shapes = scaled_shapes(shapes if shapes is not None else self.shapes, scale)
        width, height = max(1, round(self.document.width * scale)), max(1, round(self.document.height * scale))
        return comics.render_shapes(width, height, shapes, self.border.value() * scale, self.border_color.color,
                                    self.gutter_color.color if self.fill.isChecked() else None)

    def refresh(self):
        self.sync_controls()
        scale = min(204 / self.document.width, 284 / self.document.height)
        try:
            self.style_used, self.shapes = self.compute()
        except ValueError as error:
            self.preview.setWordWrap(True)
            self.preview.setText(str(error))
            return
        panels = self.render(scale)
        image = QImage(panels.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#f4f1ea'))
        painter = QPainter(image)
        painter.drawImage(0, 0, panels)
        painter.setPen(QColor(40, 110, 200))
        for number, item in enumerate(self.shapes, 1):
            painter.drawText(label_point(item, scale) + QPointF(1, 10), str(number))
        painter.end()
        self.preview.show_image(image)

    def validate(self):
        try:
            self.style_used, self.shapes = self.compute()
        except ValueError as error:
            QMessageBox.warning(self, 'Quadros', str(error))
            return
        self.rects = [shape_bounds(item) for item in self.shapes]
        self.accept()


class PageNumberDialog(QDialog):
    def __init__(self, owner, document, batch=False):
        super().__init__(owner)
        self.batch = batch
        self.paths = []
        comic = document.scene.get('comic', {})
        saved = comic.get('number_style', {})
        height = document.height
        inset = document.guides.get('bleed', 0) + document.guides.get('safe', 0)
        self.setWindowTitle('Numerar páginas em lote' if batch else 'Numerar página')
        form = QFormLayout(self)
        if batch:
            self.files = QListWidget()
            self.files.setMinimumHeight(130)
            choose = QPushButton('Escolher projetos .sdp…')
            choose.clicked.connect(self.choose_files)
            form.addRow(self.files)
            form.addRow(choose)
        self.number = spin(-9999, 99999, comic.get('page', 1), '')
        self.step = spin(1, 10, 1, '')
        self.prefix = QLineEdit(saved.get('prefix', ''))
        self.prefix.setPlaceholderText('ex.: “Pág. ” ou vazio')
        self.position = QComboBox()
        for label, value in POSITIONS:
            self.position.addItem(label, value)
        self.position.setCurrentIndex(max(0, self.position.findData(saved.get('position', 'outer'))))
        self.size = spin(6, 1000, saved.get('size', max(10, round(height * .016))))
        self.margin = spin(0, 4000, saved.get('margin', inset + max(8, round(height * .02))))
        self.color = ColorButton(saved.get('color', '#202020'))
        self.bold = QCheckBox('Negrito')
        self.bold.setChecked(saved.get('bold', True))
        self.rtl = QCheckBox('Leitura oriental (mangá): páginas ímpares à esquerda')
        self.rtl.setChecked(saved.get('rtl', comic.get('direction') == 'rtl'))
        form.addRow('Primeiro número' if batch else 'Número da página', self.number)
        if batch:
            form.addRow('Incremento', self.step)
        for label, widget in [('Prefixo', self.prefix), ('Posição', self.position), ('Tamanho do texto', self.size),
                              ('Distância da borda', self.margin), ('Cor', self.color)]:
            form.addRow(label, widget)
        form.addRow(self.bold)
        form.addRow(self.rtl)
        note = QLabel('Os arquivos são numerados em ordem natural de nome (página 2 antes de página 10). '
                      'A numeração fica na camada “Número da página”.' if batch else
                      '“Lado externo” alterna: ímpares à direita e pares à esquerda (invertido no mangá).')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Numerar', self.validate))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Páginas do quadrinho', '', 'Projeto Lumira (*.sdp)')
        if paths:
            from comics import natural_key
            self.paths = sorted(paths, key=natural_key)
            self.files.clear()
            for offset, path in enumerate(self.paths):
                self.files.addItem(f'{self.number.value() + offset * self.step.value()}  ·  {Path(path).name}')

    def style(self):
        return {'prefix': self.prefix.text(), 'position': self.position.currentData(), 'size': self.size.value(),
                'margin': self.margin.value(), 'color': self.color.color.name(), 'bold': self.bold.isChecked(),
                'rtl': self.rtl.isChecked()}

    def validate(self):
        if self.batch and not self.paths:
            QMessageBox.information(self, 'Numerar páginas', 'Escolha os projetos que serão numerados.')
            return
        self.accept()


class CoverDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWindowTitle('Criar capa de quadrinho')
        layout = QHBoxLayout(self)
        form = QFormLayout()
        self.format = QComboBox()
        for name, width, height, dpi, bleed, safe in COMIC_FORMATS:
            self.format.addItem(f'{name} · {width}×{height}', (width, height, dpi, bleed, safe))
        self.title = QLineEdit('Minha história')
        self.subtitle = QLineEdit('')
        self.subtitle.setPlaceholderText('Subtítulo ou chamada')
        self.issue = QLineEdit('1')
        self.author = QLineEdit('')
        self.author.setPlaceholderText('Roteiro e arte')
        self.publisher = QLineEdit('')
        self.publisher.setPlaceholderText('Editora / selo')
        self.info = QLineEdit('')
        self.info.setPlaceholderText('ex.: Outubro 2026 · R$ 19,90')
        self.position = QComboBox()
        self.position.addItem('Título no topo', 'top')
        self.position.addItem('Título embaixo', 'bottom')
        self.top, self.bottom = ColorButton('#1d3557'), ColorButton('#e63946')
        self.title_color, self.outline = ColorButton('#ffd23f'), ColorButton('#111111')
        self.barcode = QCheckBox('Reservar espaço para código de barras')
        self.barcode.setChecked(True)
        self.bleed, self.safe = spin(0, 500, 38), spin(0, 500, 75)
        colors = QHBoxLayout()
        for label, button in [('Topo', self.top), ('Base', self.bottom), ('Título', self.title_color), ('Contorno', self.outline)]:
            colors.addWidget(QLabel(label))
            colors.addWidget(button)
        for label, widget in [('Formato', self.format), ('Título', self.title), ('Subtítulo', self.subtitle),
                              ('Número da edição', self.issue), ('Autor(es)', self.author), ('Editora', self.publisher),
                              ('Data / preço', self.info), ('Posição do título', self.position), ('Cores', colors),
                              ('Sangria', self.bleed), ('Margem de segurança', self.safe)]:
            form.addRow(label, widget)
        form.addRow(self.barcode)
        note = QLabel('Cada elemento fica numa camada separada; pinte a ilustração em “Arte da capa”.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Criar capa'))
        layout.addLayout(form, 1)
        self.preview = PagePreview(QSize(230, 330))
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(180)
        self.timer.timeout.connect(self.refresh)
        for widget in (self.title, self.subtitle, self.issue, self.author, self.publisher, self.info):
            widget.textChanged.connect(self.timer.start)
        for widget in (self.format, self.position):
            widget.currentIndexChanged.connect(self.timer.start)
        for widget in (self.bleed, self.safe):
            widget.valueChanged.connect(self.timer.start)
        for button in (self.top, self.bottom, self.title_color, self.outline):
            button.clicked.connect(self.timer.start)
        self.barcode.toggled.connect(self.timer.start)
        self.format.currentIndexChanged.connect(self.format_changed)
        self.refresh()

    def format_changed(self):
        _, _, _, bleed, safe = self.format.currentData()
        self.bleed.setValue(bleed)
        self.safe.setValue(safe)

    def options(self, scale=1.):
        width, height, dpi, _, _ = self.format.currentData()
        return {'width': max(8, round(width * scale)), 'height': max(8, round(height * scale)), 'dpi': dpi,
                'title': self.title.text().strip(), 'subtitle': self.subtitle.text(), 'issue': self.issue.text(),
                'author': self.author.text(), 'publisher': self.publisher.text(), 'info': self.info.text(),
                'title_position': self.position.currentData(), 'top': self.top.color.name(),
                'bottom': self.bottom.color.name(), 'title_color': self.title_color.color.name(),
                'outline': self.outline.color.name(), 'barcode': self.barcode.isChecked(),
                'bleed': round(self.bleed.value() * scale), 'safe': round(self.safe.value() * scale)}

    def refresh(self):
        width, height, *_ = self.format.currentData()
        scale = min(214 / width, 314 / height)
        document = cover_document(self.options(scale))
        image = document.composite(paper=True, subtitles=False)
        painter = QPainter(image)
        bleed, safe = round(self.bleed.value() * scale), round(self.safe.value() * scale)
        if bleed:
            painter.setPen(QPen(QColor(230, 70, 70), 1, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(image.rect()).adjusted(bleed, bleed, -bleed - 1, -bleed - 1))
        painter.end()
        self.preview.show_image(image)

    def build(self):
        return cover_document(self.options())


class PrintGuidesDialog(QDialog):
    def __init__(self, owner, guides):
        super().__init__(owner)
        self.setWindowTitle('Sangria e área segura')
        form = QFormLayout(self)
        self.bleed, self.safe = spin(0, 2000, guides.get('bleed', 0)), spin(0, 2000, guides.get('safe', 0))
        form.addRow('Sangria (corte)', self.bleed)
        form.addRow('Margem de segurança', self.safe)
        note = QLabel('Vermelho: linha de corte. Azul: mantenha textos e balões dentro. As guias não são exportadas. '
                      'A 300 dpi, 3 mm ≈ 35 px.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Aplicar'))

    def values(self):
        return {'bleed': self.bleed.value(), 'safe': self.safe.value()}


class EffectPreview(QLabel):
    """Page thumbnail with an effect drawn over it."""

    def __init__(self, owner, size=QSize(260, 300)):
        super().__init__()
        self.owner = owner
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:#3a3d43;border-radius:4px;')
        document = owner.canvas.document
        self.scale = min((size.width() - 12) / document.width, (size.height() - 12) / document.height)
        self.page = owner.canvas.preview_image(round(document.width * self.scale), round(document.height * self.scale))
        page = QImage(self.page.size(), QImage.Format.Format_ARGB32_Premultiplied)
        page.fill(QColor('white'))
        painter = QPainter(page)
        painter.drawImage(0, 0, self.page)
        painter.end()
        self.page = page

    def show(self, overlay):
        image = QImage(self.page)
        painter = QPainter(image)
        painter.drawImage(0, 0, overlay)
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


def scaled_mask(mask, size):
    if mask is None:
        return None
    return mask.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


class BalloonDialog(QDialog):
    """Text, kind and look of a speech balloon (or sound effect), with a live preview."""

    def __init__(self, owner, document, center, tip, kind='speech', settings=None):
        super().__init__(owner)
        self.document, self.center, self.tip = document, center, tip
        settings = dict(settings or {})
        self.setWindowTitle('Balão e letreiramento')
        short = min(document.width, document.height)
        layout = QHBoxLayout(self)
        form = QFormLayout()
        self.text = QPlainTextEdit(settings.get('text', ''))
        self.text.setPlaceholderText('Fala, pensamento, narração ou onomatopeia')
        self.text.setMaximumHeight(90)
        self.kind = QComboBox()
        for label, value in BALLOONS:
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.font = QFontComboBox()
        self.size = spin(6, 1000, settings.get('size', max(12, round(short * .02))))
        self.bold = QCheckBox('Negrito')
        self.bold.setChecked(settings.get('bold', True))
        self.fill, self.outline = ColorButton(settings.get('fill', '#ffffff')), ColorButton(settings.get('outline', '#111111'))
        self.text_color = ColorButton(settings.get('text_color', '#111111'))
        self.line = spin(0, 100, settings.get('line', max(2, round(short * .0028))))
        self.angle = spin(-60, 60, settings.get('angle', -8), '°')
        self.new_layer = QCheckBox('Cada balão na própria camada (fácil de mover)')
        self.new_layer.setChecked(settings.get('new_layer', True))
        colors = QHBoxLayout()
        for label, button in (('Fundo', self.fill), ('Contorno', self.outline), ('Texto', self.text_color)):
            colors.addWidget(QLabel(label))
            colors.addWidget(button)
        colors.addStretch()
        for label, widget in (('Texto', self.text), ('Tipo', self.kind), ('Fonte', self.font), ('Tamanho', self.size),
                              ('Cores', colors), ('Contorno', self.line), ('Inclinação (onomatopeia)', self.angle)):
            form.addRow(label, widget)
        form.addRow(self.bold)
        form.addRow(self.new_layer)
        hint = QLabel('Dica: com a ferramenta Balão, clique onde fica o balão e arraste até quem fala para apontar o rabicho.')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        form.addRow(hint)
        form.addRow(buttons(self, 'Inserir balão'))
        layout.addLayout(form, 1)
        self.preview = QLabel()
        self.preview.setFixedSize(300, 240)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('background:#f4f1ea;border-radius:4px;')
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        self.apply_kind_defaults(kind, initial=True, family=settings.get('family'))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)
        self.text.textChanged.connect(self.timer.start)
        self.kind.currentIndexChanged.connect(lambda: (self.apply_kind_defaults(self.kind.currentData()), self.timer.start()))
        for widget in (self.size, self.line, self.angle):
            widget.valueChanged.connect(self.timer.start)
        self.font.currentFontChanged.connect(self.timer.start)
        self.bold.toggled.connect(self.timer.start)
        for button in (self.fill, self.outline, self.text_color):
            button.clicked.connect(self.timer.start)
        self.refresh()

    def apply_kind_defaults(self, kind, initial=False, family=None):
        """Sound effects and captions start with their usual look."""
        self.font.setCurrentFont(QFont(family or lettering_family(kind)))
        self.angle.setEnabled(kind == 'sfx')
        if initial:
            return
        short = min(self.document.width, self.document.height)
        fill, size = {'sfx': ('#ffd23f', max(24, round(short * .06))),
                      'caption': ('#fff6c9', max(12, round(short * .018)))}.get(kind, ('#ffffff', max(12, round(short * .02))))
        self.fill.color = QColor(fill)
        self.fill.refresh()
        self.size.setValue(size)

    def qfont(self, scale=1.):
        font = QFont(self.font.currentFont())
        font.setPixelSize(max(4, round(self.size.value() * scale)))
        font.setBold(self.bold.isChecked())
        return font

    def render(self):
        text = self.text.toPlainText().strip() or ('BOOM!' if self.kind.currentData() == 'sfx' else '...')
        return balloon(self.document.width, self.document.height, self.center, self.tip, text,
                       self.kind.currentData(), self.qfont(), self.fill.color.name(), self.outline.color.name(),
                       self.text_color.color.name(), self.line.value(), self.angle.value())

    def refresh(self):
        image, bounds = self.render()
        crop = bounds.adjusted(-20, -20, 20, 20).toAlignedRect().intersected(image.rect())
        if crop.isEmpty():
            return
        part = image.copy(crop)
        self.preview.setPixmap(QPixmap.fromImage(part).scaled(self.preview.size() - QSize(16, 16),
                               Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def settings(self):
        return {'size': self.size.value(), 'bold': self.bold.isChecked(), 'fill': self.fill.color.name(),
                'outline': self.outline.color.name(), 'text_color': self.text_color.color.name(),
                'line': self.line.value(), 'angle': self.angle.value(), 'new_layer': self.new_layer.isChecked(),
                'family': self.font.currentFont().family(), 'kind': self.kind.currentData()}


class ActionLinesDialog(QDialog):
    """Focus, speed or burst lines inside a panel or selection."""

    def __init__(self, owner, document, area, mask):
        super().__init__(owner)
        self.document, self.area, self.mask = document, area, mask
        self.seed = random.randrange(1 << 30)
        self.setWindowTitle('Linhas de ação')
        short = min(area.width(), area.height())
        layout = QHBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        for label, value in LINE_KINDS:
            self.kind.addItem(label, value)
        self.count = spin(8, 600, 140, '')
        self.clear = spin(0, 95, 38, '%')
        self.thickness = spin(1, 400, max(2, round(short * .012)))
        self.angle = spin(-180, 180, 0, '°')
        self.jitter = spin(0, 100, 60, '%')
        self.center_x, self.center_y = spin(0, 100, 50, '%'), spin(0, 100, 50, '%')
        self.color = ColorButton('#111111')
        vary = QPushButton('Variar')
        vary.clicked.connect(self.reroll)
        center = QHBoxLayout()
        center.addWidget(self.center_x)
        center.addWidget(self.center_y)
        for label, widget in (('Tipo', self.kind), ('Quantidade', self.count), ('Área livre no centro', self.clear),
                              ('Espessura', self.thickness), ('Ângulo (velocidade)', self.angle),
                              ('Irregularidade', self.jitter), ('Centro (x, y)', center), ('Cor', self.color)):
            form.addRow(label, widget)
        form.addRow(vary)
        note = QLabel('As linhas vão para uma camada nova, limitadas ao quadro ou à seleção.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Aplicar linhas'))
        layout.addLayout(form, 1)
        self.preview = EffectPreview(owner)
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.refresh)
        for widget in (self.count, self.clear, self.thickness, self.angle, self.jitter, self.center_x, self.center_y):
            widget.valueChanged.connect(self.timer.start)
        self.kind.currentIndexChanged.connect(self.timer.start)
        self.color.clicked.connect(self.timer.start)
        self.refresh()

    def reroll(self):
        self.seed = random.randrange(1 << 30)
        self.refresh()

    def render(self, scale=1.):
        width, height = max(1, round(self.document.width * scale)), max(1, round(self.document.height * scale))
        area = QRectF(self.area.x() * scale, self.area.y() * scale, self.area.width() * scale, self.area.height() * scale)
        center = QPointF(area.left() + area.width() * self.center_x.value() / 100,
                         area.top() + area.height() * self.center_y.value() / 100)
        mask = self.mask if scale == 1 else scaled_mask(self.mask, QSize(width, height))
        return action_lines(width, height, area, self.kind.currentData(), center, self.count.value(),
                            self.clear.value() / 100, self.thickness.value() * scale, self.color.color.name(),
                            self.angle.value(), self.jitter.value() / 100, self.seed, mask)

    def refresh(self):
        self.preview.show(self.render(self.preview.scale))


class ToneDialog(QDialog):
    """Manga screentone (dots, gradient dots, lines, cross-hatching, grain)."""

    def __init__(self, owner, document, area, mask):
        super().__init__(owner)
        self.document, self.area, self.mask = document, area, mask
        self.setWindowTitle('Retícula')
        layout = QHBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        for label, value in TONES:
            self.kind.addItem(label, value)
        self.spacing = spin(3, 200, max(6, round(min(document.width, document.height) * .006)))
        self.size = spin(5, 100, 50, '%')
        self.angle = spin(-90, 90, 45, '°')
        self.color = ColorButton('#111111')
        self.reverse = QCheckBox('Inverter o degradê (escuro em cima)')
        for label, widget in (('Padrão', self.kind), ('Espaçamento', self.spacing), ('Densidade', self.size),
                              ('Ângulo', self.angle), ('Cor', self.color)):
            form.addRow(label, widget)
        form.addRow(self.reverse)
        note = QLabel('A retícula vai para uma camada nova, limitada ao quadro ou à seleção. '
                      'Para impressão, prefira espaçamento de 6 px ou mais a 300 dpi.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Aplicar retícula'))
        layout.addLayout(form, 1)
        self.preview = EffectPreview(owner)
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.refresh)
        for widget in (self.spacing, self.size, self.angle):
            widget.valueChanged.connect(self.timer.start)
        self.kind.currentIndexChanged.connect(self.timer.start)
        self.reverse.toggled.connect(self.timer.start)
        self.color.clicked.connect(self.timer.start)
        self.refresh()

    def render(self, scale=1.):
        width, height = max(1, round(self.document.width * scale)), max(1, round(self.document.height * scale))
        area = QRectF(self.area.x() * scale, self.area.y() * scale, self.area.width() * scale, self.area.height() * scale)
        mask = self.mask if scale == 1 else scaled_mask(self.mask, QSize(width, height))
        # The preview keeps the pattern readable instead of shrinking it below a pixel.
        spacing = self.spacing.value() * (scale if scale == 1 else max(scale, 3 / self.spacing.value()))
        return screentone(width, height, self.kind.currentData(), spacing, self.size.value() / 100, self.angle.value(),
                          self.color.color.name(), mask, area, reverse=self.reverse.isChecked())

    def refresh(self):
        self.preview.show(self.render(self.preview.scale))


class ChapterDialog(QDialog):
    """Several numbered pages at once, each with its own stylized layout."""

    def __init__(self, owner, document):
        super().__init__(owner)
        self.setWindowTitle('Gerar capítulo')
        form = QFormLayout(self)
        self.folder = QLineEdit(str(Path(document.path).parent) if document.path else str(Path.home()))
        choose = QPushButton('Escolher…')
        choose.clicked.connect(self.choose_folder)
        folder = QHBoxLayout()
        folder.addWidget(self.folder, 1)
        folder.addWidget(choose)
        self.prefix = QLineEdit('pagina')
        self.pages = spin(1, 200, 8, '')
        self.format = QComboBox()
        self.format.addItem(f'Igual a esta página · {document.width}×{document.height}',
                            (document.width, document.height, document.dpi or 300,
                             document.guides.get('bleed', 0), document.guides.get('safe', 0)))
        for name, width, height, dpi, bleed, safe in COMIC_FORMATS:
            self.format.addItem(f'{name} · {width}×{height}', (width, height, dpi, bleed, safe))
        self.style = QComboBox()
        for label, key in STYLES:
            self.style.addItem(label, key)
        self.direction = QComboBox()
        self.direction.addItem('Ocidental · esquerda → direita', 'ltr')
        self.direction.addItem('Mangá · direita → esquerda', 'rtl')
        self.start = spin(1, 9999, 1, '')
        self.number = QCheckBox('Numerar as páginas')
        self.number.setChecked(True)
        self.position = QComboBox()
        for label, value in POSITIONS:
            self.position.addItem(label, value)
        for label, widget in (('Pasta', folder), ('Nome dos arquivos', self.prefix), ('Páginas', self.pages),
                              ('Formato', self.format), ('Estilo dos quadros', self.style), ('Leitura', self.direction),
                              ('Primeira página', self.start), ('Posição do número', self.position)):
            form.addRow(label, widget)
        form.addRow(self.number)
        note = QLabel('Cada página recebe uma disposição diferente no estilo escolhido, camadas “Arte” e “Rascunho”, '
                      'os quadros e o número. Os arquivos ficam prontos para abrir e desenhar.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        form.addRow(buttons(self, 'Gerar páginas', self.validate))

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Pasta do capítulo', self.folder.text())
        if folder:
            self.folder.setText(folder)

    def values(self):
        width, height, dpi, bleed, safe = self.format.currentData()
        return {'folder': self.folder.text().strip(), 'pages': self.pages.value(), 'width': width, 'height': height,
                'dpi': dpi, 'bleed': bleed, 'safe': safe, 'style': self.style.currentData(),
                'direction': self.direction.currentData(), 'start': self.start.value(),
                'prefix': self.prefix.text().strip() or 'pagina',
                'number_style': {'position': self.position.currentData(), 'size': max(10, round(height * .016)),
                                 'margin': bleed + safe + max(8, round(height * .02)), 'bold': True}
                if self.number.isChecked() else None}

    def validate(self):
        if not self.folder.text().strip():
            QMessageBox.information(self, 'Gerar capítulo', 'Escolha a pasta das páginas.')
            return
        self.accept()
