"""Brush panel (library with stroke previews) and brush editor with live preview."""
import copy
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                             QTabWidget, QToolButton, QVBoxLayout, QWidget)

import brush_engine
from i18n import tr
from media import qt_image
from resources import TIP_KINDS, Brush, computed_mask, generated_tip, load_abr, mask_from_image, png_base64
from themes import PALETTES

ALL = 'Todas as categorias'


class BrushPanel(QWidget):
    """Grid of brushes with real stroke previews; the choice applies to the active drawing tool."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.icons = {}
        self.pending = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self.refresh_list)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buscar…')
        self.search.textChanged.connect(self.refresh_list)
        row.addWidget(self.category, 3)
        row.addWidget(self.search, 2)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setIconSize(QSize(120, 28))
        self.list.setMinimumHeight(64)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(1)
        self.list.itemClicked.connect(self.use)
        self.list.itemDoubleClicked.connect(lambda item: self.edit())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.tool_label = QLabel()
        self.tool_label.setObjectName('muted')
        row.addWidget(self.tool_label, 1)
        for name, tip, callback in [('plus', 'Criar pincel', self.create), ('pencil-outline', 'Editar / copiar pincel', self.edit),
                                    ('tray-arrow-down', 'Importar pincéis (.abr do Photoshop, .sbrush ou código)', self.import_menu),
                                    ('share-variant-outline', 'Exportar ou compartilhar pincéis selecionados', self.share_menu),
                                    ('delete-outline', 'Excluir pincel', self.delete)]:
            button = owner.icon_button(name, tip, callback)
            row.addWidget(button)
            if name == 'tray-arrow-down':
                # Labelled, so importing Photoshop brushes is easy to find.
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                button.setText('Importar')
                button.setMinimumSize(26, 26)
                button.setMaximumSize(200, 26)
                self.import_button = button
            elif name == 'share-variant-outline':
                self.share_button = button
        layout.addLayout(row)
        # Brush files (.abr, .sbrush) can also be dropped on the panel.
        self.setAcceptDrops(True)
        self.timer = QTimer(self)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self.render_next)
        self.refresh()

    @property
    def library(self):
        return self.owner.library

    # ------------------------------------------------------------- listing

    def refresh(self, select=None):
        categories = []
        for brush in self.library.brushes:
            if brush.category not in categories:
                categories.append(brush.category)
        current = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(ALL, ALL)
        for name in categories:
            self.category.addItem(name, name)
        self.category.setCurrentIndex(max(0, self.category.findData(current if current in categories else ALL)))
        self.category.blockSignals(False)
        self.refresh_list(select=select)

    def refresh_list(self, *args, select=None):
        selected = select or self.owner.selected_brush
        text = self.search.text().strip().lower()
        category = self.category.currentData() or ALL
        self.list.clear()
        self.pending = []
        for index, brush in enumerate(self.library.brushes):
            if category != ALL and brush.category != category:
                continue
            if text and text not in brush.name.lower():
                continue
            item = QListWidgetItem(tr(brush.name) if index < self.library.builtin_count else brush.name)
            item.setSizeHint(QSize(0, 36))
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(f'{brush.name}\n{brush.category} · {brush.size:g} px'
                            + ('\nPadrão (edite para criar uma cópia)' if index < self.library.builtin_count else ''))
            icon = self.icons.get(self.icon_key(brush))
            if icon:
                item.setIcon(icon)
            else:
                self.pending.append((item, brush))
            self.list.addItem(item)
            if brush is selected:
                self.list.setCurrentItem(item)
        tool = {'pencil': 'Lápis', 'pen': 'Caneta'}.get(self.owner.brush_tool(), 'Pincel')
        self.tool_label.setText(f'Ferramenta: {tool}')
        if self.pending:
            self.timer.start()

    def icon_key(self, brush):
        return id(brush), self.owner.theme

    def render_next(self):
        if not self.pending:
            self.timer.stop()
            return
        item, brush = self.pending.pop(0)
        color = PALETTES[self.owner.theme]['text']
        try:
            image = brush_engine.preview(brush, color, 120, 28, size=max(3., min(12., brush.size)),
                                         scale=self.devicePixelRatioF())
        except Exception:  # a broken custom tip must not break the list
            image = QImage(120, 28, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
        icon = QIcon(QPixmap.fromImage(image))
        self.icons[self.icon_key(brush)] = icon
        try:
            item.setIcon(icon)
        except RuntimeError:
            pass  # the list was rebuilt meanwhile

    def theme_changed(self):
        self.icons.clear()
        self.refresh_list()

    def selected_brushes(self):
        rows = [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        return [self.library.brushes[row] for row in rows]

    def current(self):
        item = self.list.currentItem()
        return self.library.brushes[item.data(Qt.ItemDataRole.UserRole)] if item else None

    # ------------------------------------------------------------- actions

    def use(self, item=None):
        brush = self.current()
        if brush is None:
            return
        if self.owner.canvas.tool not in ('brush', 'pencil', 'pen'):
            self.owner.set_tool('brush')
        self.owner.selected_brush = brush
        self.owner.size_spin.setValue(brush.size)
        self.owner.statusBar().showMessage(f'Pincel: {brush.name}', 3000)
        self.owner.refresh_brush_design()

    def create(self):
        base = copy.deepcopy(self.current() or self.library.brushes[0])
        base.name, base.category = 'Meu pincel', 'Meus pincéis'
        dialog = BrushEditor(self.owner, base)
        if dialog.exec():
            brush = dialog.result_brush()
            self.library.add_brushes([brush])
            self.refresh(select=brush)
            self.use()

    def edit(self):
        brush = self.current()
        if brush is None:
            return
        index = self.library.brushes.index(brush)
        builtin = index < self.library.builtin_count
        dialog = BrushEditor(self.owner, brush, copy_of=builtin)
        if not dialog.exec():
            return
        result = dialog.result_brush()
        if builtin:
            self.library.add_brushes([result])
        else:
            self.library.brushes[index] = result
            for tool, used in list(self.owner.tool_brushes.items()):
                if used is brush:
                    self.owner.tool_brushes[tool] = result
            self.library.save()
        self.icons.pop(self.icon_key(brush), None)
        self.refresh(select=result)
        self.use()

    def delete(self):
        brushes = self.selected_brushes()
        if not brushes:
            return
        if any(self.library.brushes.index(b) < self.library.builtin_count for b in brushes):
            QMessageBox.information(self, 'Pincéis', 'Os pincéis padrão não podem ser excluídos; edite para criar uma cópia.')
            return
        names = ', '.join(b.name for b in brushes[:5]) + ('…' if len(brushes) > 5 else '')
        if QMessageBox.question(self, 'Excluir pincéis', f'Excluir {len(brushes)} pincel(is)? {names}') != QMessageBox.StandardButton.Yes:
            return
        for brush in brushes:
            self.library.brushes.remove(brush)
            for tool, used in list(self.owner.tool_brushes.items()):
                if used is brush:
                    self.owner.tool_brushes[tool] = self.library.preset(tool)
        self.library.save()
        self.refresh()

    def context_menu(self, point):
        menu = QMenu(self)
        menu.addAction('Usar', self.use)
        menu.addAction('Editar / copiar…', self.edit)
        menu.addAction('Duplicar', self.duplicate)
        menu.addAction('Mover para categoria…', self.move_category)
        menu.addSeparator()
        menu.addAction('Exportar arquivo .sbrush…', self.export_file)
        menu.addAction('Copiar código de compartilhamento', self.copy_code)
        menu.addSeparator()
        menu.addAction('Excluir', self.delete)
        menu.exec(self.list.viewport().mapToGlobal(point))

    def duplicate(self):
        brush = self.current()
        if brush:
            clone = copy.deepcopy(brush)
            clone.category = 'Meus pincéis'
            self.library.add_brushes([clone])
            self.refresh(select=clone)

    def move_category(self):
        brushes = self.selected_brushes()
        if not brushes:
            return
        name, accepted = QInputDialog.getText(self, 'Categoria', 'Nome da categoria:', text=brushes[0].category)
        if accepted and name.strip():
            builtin = [b for b in brushes if self.library.brushes.index(b) < self.library.builtin_count]
            for brush in brushes:
                if brush not in builtin:
                    brush.category = name.strip()[:40]
            self.library.save()
            self.refresh()

    def import_menu(self):
        menu = QMenu(self)
        menu.addAction('Pincéis do Photoshop (.abr)…', lambda: self.import_file(kind='abr'))
        menu.addAction('Pincéis do Studio (.sbrush)…', lambda: self.import_file(kind='sbrush'))
        menu.addAction('Colar código de compartilhamento…', self.import_code)
        menu.addSeparator()
        menu.addAction('Dica: arraste arquivos .abr ou .sbrush para este painel').setEnabled(False)
        menu.exec(self.import_button.mapToGlobal(self.import_button.rect().bottomLeft()))

    @staticmethod
    def brush_files(event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        return [u.toLocalFile() for u in urls if u.toLocalFile().lower().endswith(('.abr', '.sbrush'))]

    def dragEnterEvent(self, event):
        if self.brush_files(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = self.brush_files(event)
        if paths:
            event.acceptProposedAction()
            self.import_paths(paths)

    def share_menu(self):
        menu = QMenu(self)
        menu.addAction('Exportar selecionados em arquivo .sbrush…', self.export_file)
        menu.addAction('Copiar código de compartilhamento', self.copy_code)
        menu.exec(self.share_button.mapToGlobal(self.share_button.rect().bottomLeft()))

    def import_file(self, kind=None):
        filters = {'abr': 'Pincéis do Photoshop (*.abr)', 'sbrush': 'Pincéis do Studio (*.sbrush)'}
        filter_text = filters.get(kind) or 'Pincéis (*.abr *.sbrush);;Photoshop (*.abr);;Studio (*.sbrush)'
        paths, _ = QFileDialog.getOpenFileNames(self, 'Importar pincéis', '', filter_text)
        self.import_paths(paths)

    def import_paths(self, paths):
        imported = []
        for path in paths:
            try:
                imported += self.library.import_brushes(path)
            except Exception as error:  # parser errors come in many types; report and continue
                QMessageBox.warning(self, 'Importar pincéis', f'{Path(path).name}: {error}')
        if imported:
            self.refresh(select=imported[0])
            self.category.setCurrentIndex(max(0, self.category.findData(imported[0].category)))
            self.owner.statusBar().showMessage(f'{len(imported)} pincel(is) importado(s).', 6000)

    def import_code(self):
        dialog = CodeDialog(self, 'Importar pincéis por código', 'Cole aqui o código recebido:',
                            QApplication.clipboard().text() if brush_text(QApplication.clipboard().text()) else '')
        if dialog.exec():
            try:
                imported = self.library.import_code(dialog.text())
            except ValueError as error:
                QMessageBox.warning(self, 'Importar pincéis', str(error))
                return
            self.refresh(select=imported[0])
            self.owner.statusBar().showMessage(f'{len(imported)} pincel(is) importado(s).', 6000)

    def export_file(self):
        brushes = self.selected_brushes() or ([self.current()] if self.current() else [])
        if not brushes:
            return
        name = brushes[0].name if len(brushes) == 1 else 'Meus pincéis'
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar pincéis', f'{name}.sbrush', 'Pincéis Studio (*.sbrush)')
        if path:
            if not path.lower().endswith('.sbrush'):
                path += '.sbrush'
            self.library.export_brushes(path, brushes)
            self.owner.statusBar().showMessage(f'{len(brushes)} pincel(is) exportado(s) para {Path(path).name}.', 6000)

    def copy_code(self):
        from resources import share_code
        brushes = self.selected_brushes() or ([self.current()] if self.current() else [])
        if not brushes:
            return
        code = share_code(brushes)
        QApplication.clipboard().setText(code)
        CodeDialog(self, 'Compartilhar pincéis', f'Código copiado ({len(brushes)} pincel(is)). Envie para quem quiser: '
                   'a pessoa usa Importar → Colar código.', code, read_only=True).exec()


def brush_text(text):
    from resources import SHARE_PREFIX
    return text.strip().startswith(SHARE_PREFIX)


class CodeDialog(QDialog):
    def __init__(self, parent, title, message, text='', read_only=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 300)
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.editor = QPlainTextEdit(text)
        self.editor.setReadOnly(read_only)
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | (QDialogButtonBox.StandardButton.NoButton
                                   if read_only else QDialogButtonBox.StandardButton.Cancel))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self):
        return self.editor.toPlainText()


class StrokePreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 120)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:#f7f3ea;border:1px solid #888;border-radius:4px;')

    def show_brush(self, brush, color, size):
        # Rendered at the screen's pixel density, so the preview shows the brush's real detail.
        scale = max(1., self.devicePixelRatioF())
        width = round(max(200, self.width() - 12) * scale)
        height = round(max(80, self.height() - 12) * scale)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#f7f3ea'))
        painter = QPainter(image)
        stroke = brush_engine.render_stroke(brush, color, size * scale, brush_engine.preview_samples(width, height),
                                            width, height)
        painter.drawImage(0, 0, stroke)
        painter.end()
        image.setDevicePixelRatio(scale)
        self.setPixmap(QPixmap.fromImage(image))


def _thumbnail(gray, size=52):
    """Grey 0–1 array (ink coverage) as a small icon: dark ink on light paper."""
    values = (247 - np.clip(gray, 0, 1) * 215).astype('uint8')
    image = Image.fromarray(values).resize((size, size), Image.Resampling.LANCZOS).convert('RGB')
    picture = QImage(image.tobytes(), size, size, size * 3, QImage.Format.Format_RGB888).copy()
    return QIcon(QPixmap.fromImage(picture))


def tip_icon(mask):
    """Icon of a tip mask (PIL greyscale), keeping its proportions."""
    mask = mask.copy()
    mask.thumbnail((52, 52), Image.Resampling.LANCZOS)
    canvas = Image.new('L', (52, 52), 0)
    canvas.paste(mask, ((52 - mask.width) // 2, (52 - mask.height) // 2))
    return _thumbnail(np.asarray(canvas, np.float32) / 255)


def grain_icon(kind):
    """How the paper texture takes ink: a light wash over a patch of it."""
    if kind in ('', 'custom'):
        return _thumbnail(np.full((52, 52), .55 if not kind else 0., np.float32))
    tooth = brush_engine.grain_texture(kind)[:160, :160]
    return _thumbnail(brush_engine.deposit(np.full(tooth.shape, .55, np.float32), tooth, .85))


class Gallery(QListWidget):
    """Grid of thumbnails to pick a tip or a paper texture."""

    def __init__(self, rows=2):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(52, 52))
        self.setGridSize(QSize(82, 86))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setMinimumHeight(86 * rows + 8)

    def add(self, label, value, icon):
        item = QListWidgetItem(icon, label)
        item.setData(Qt.ItemDataRole.UserRole, value)
        item.setToolTip(label)
        self.addItem(item)
        return item

    def select(self, value):
        self.blockSignals(True)
        self.clearSelection()
        for row in range(self.count()):
            if self.item(row).data(Qt.ItemDataRole.UserRole) == value:
                self.setCurrentRow(row)
                break
        self.blockSignals(False)

    def value(self):
        item = self.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class AbrTipDialog(QDialog):
    """Pick one tip from a Photoshop brush file (.abr) for the brush being edited."""

    def __init__(self, parent, brushes):
        super().__init__(parent)
        self.setWindowTitle('Pontas do Photoshop')
        self.resize(560, 420)
        self.brushes = [b for b in brushes if b.tip]
        layout = QVBoxLayout(self)
        label = QLabel('Escolha a ponta (a forma da marca) que o pincel vai usar:')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.gallery = Gallery(3)
        for index, brush in enumerate(self.brushes):
            self.gallery.add(brush.name, index, tip_icon(brush.mask()))
        self.gallery.setCurrentRow(0)
        self.gallery.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.gallery, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self):
        index = self.gallery.value()
        return self.brushes[index] if index is not None else None


class BrushEditor(QDialog):
    """Create or edit a brush: tip, shape dynamics, paint and texture, with a live stroke preview."""

    SLIDERS = {
        'size': ('Tamanho padrão', 1, 500, 1, ' px'),
        'hardness': ('Dureza', 0, 100, 100, '%'),
        'spacing': ('Espaçamento', 1, 200, 100, '%'),
        'flow': ('Fluxo', 1, 100, 100, '%'),
        'angle': ('Ângulo', -180, 180, 1, '°'),
        'roundness': ('Proporção da ponta', 5, 100, 100, '%'),
        'opacity_pressure': ('Pressão → opacidade', 0, 100, 100, '%'),
        'flow_pressure': ('Pressão → fluxo', 0, 100, 100, '%'),
        'opacity_jitter': ('Variação de opacidade', 0, 100, 100, '%'),
        'jitter': ('Variação de tamanho', 0, 100, 100, '%'),
        'roundness_jitter': ('Variação de proporção', 0, 100, 100, '%'),
        'angle_jitter': ('Variação de ângulo', 0, 180, 1, '°'),
        'scatter': ('Dispersão', 0, 400, 100, '%'),
        'count': ('Quantidade por passo', 1, 16, 1, ''),
        'taper_in': ('Afinar o início', 0, 100, 100, '%'),
        'speed_size': ('Velocidade → tamanho', -100, 100, 100, '%'),
        'grain_strength': ('Força da textura', 0, 100, 100, '%'),
        'grain_scale': ('Escala da textura', 10, 800, 100, '%'),
        'grain_contrast': ('Contraste da textura', 20, 400, 100, '%'),
        'wet_edges': ('Bordas úmidas (aquarela)', 0, 100, 100, '%'),
        'depletion': ('Esgotamento da tinta', 0, 100, 100, '%'),
    }
    TIPS = {
        'hardness': 'Borda nítida (100%) ou esfumada (0%). Vale para a ponta redonda.',
        'spacing': 'Distância entre as marcas da ponta, em % do tamanho. Pouco espaço = traço contínuo.',
        'flow': 'Quanta tinta cada marca deposita; abaixo de 100% o traço vai acumulando aos poucos.',
        'roundness': 'Achata a ponta redonda numa elipse (caligrafia, marcador).',
        'opacity_pressure': 'Quanto a pressão define o tom: com pouca pressão o traço sai mais claro.',
        'flow_pressure': 'Quanto a pressão reduz a tinta de cada marca (acúmulo mais lento com pouca pressão).',
        'opacity_jitter': 'Cada marca sai um pouco mais clara, ao acaso.',
        'jitter': 'Cada marca sai um pouco menor, ao acaso.',
        'roundness_jitter': 'Cada marca sai achatada ao acaso (folhas, respingos, cerdas).',
        'angle_jitter': 'Gira cada marca ao acaso até este ângulo.',
        'scatter': 'Espalha as marcas para os lados do traço, em % do tamanho.',
        'count': 'Quantas marcas são carimbadas a cada passo (use com dispersão).',
        'taper_in': 'O traço começa fino e engrossa no início, como um pincel pousando no papel.',
        'speed_size': 'Positivo: traço rápido fica mais fino (nanquim). Negativo: fica mais grosso.',
        'grain_strength': 'Quanto a textura aparece: o pigmento pega primeiro nos relevos.',
        'grain_scale': 'Tamanho do grão do papel.',
        'grain_contrast': 'Relevos mais marcados (acima de 100%) ou mais suaves.',
        'wet_edges': 'Acumula pigmento no contorno, como aquarela.',
        'depletion': 'A tinta acaba ao longo do traço, que termina seco e falhado.',
    }
    CHECKS = {
        'size_pressure': 'Pressão da caneta controla o tamanho',
        'follow_direction': 'Ponta acompanha a direção do traço (cerdas, caligrafia)',
        'flip_jitter': 'Espelhar a ponta ao acaso (mais variedade)',
        'grain_invert': 'Inverter a textura (pigmento nos vales)',
    }

    def __init__(self, owner, brush, copy_of=False):
        super().__init__(owner)
        self.owner = owner
        self.brush = copy.deepcopy(brush)
        if copy_of:
            self.brush.name += ' (cópia)'
            self.brush.category = 'Meus pincéis'
        self.initial = copy.deepcopy(self.brush)
        self.setWindowTitle('Editor de pincel')
        self.resize(1000, 660)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.update_preview)
        layout = QHBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 3)
        self.fields, self.checks = {}, {}
        tabs.addTab(self.page(self.tip_rows()), 'Ponta')
        tabs.addTab(self.page(self.shape_rows()), 'Forma')
        tabs.addTab(self.page(self.paint_rows()), 'Tinta')
        tabs.addTab(self.page(self.texture_rows()), 'Textura')
        side = QVBoxLayout()
        self.preview = StrokePreview()
        side.addWidget(self.preview)
        self.preview_size = QSlider(Qt.Orientation.Horizontal)
        self.preview_size.setRange(2, 120)
        self.preview_size.setValue(int(max(4, min(60, self.brush.size))))
        self.preview_size.valueChanged.connect(self.timer.start)
        row = QHBoxLayout()
        row.addWidget(QLabel('Tamanho da prévia'))
        row.addWidget(self.preview_size)
        side.addLayout(row)
        self.tip_view = QLabel()
        self.tip_view.setFixedSize(96, 96)
        self.tip_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tip_view.setStyleSheet('background:#f7f3ea;border:1px solid #888;border-radius:4px;')
        row = QHBoxLayout()
        row.addWidget(self.tip_view)
        row.addWidget(self.hint('A prévia usa o mesmo motor da tela, com variação de pressão do início ao fim '
                                'do traço. Passe o mouse sobre um controle para ver o que ele faz.'), 1)
        side.addLayout(row)
        side.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.Reset)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Salvar pincel')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText('Desfazer alterações')
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self.reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        side.addWidget(buttons)
        layout.addLayout(side, 2)
        self.sync_galleries()
        self.update_preview()

    # ------------------------------------------------------------ widgets

    def page(self, rows):
        widget = QWidget()
        widget.setObjectName('panel')  # themed like the main window's panels
        form = QFormLayout(widget)
        for label, field in rows:
            form.addRow(label, field) if label else form.addRow(field)
        area = QScrollArea()
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        return area

    def slider(self, key):
        label, low, high, factor, suffix = self.SLIDERS[key]
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(1 if key == 'size' else 0)
        spin.setSuffix(suffix)
        spin.setValue(getattr(self.brush, key) * factor)
        spin.setToolTip(self.TIPS.get(key, ''))
        spin.valueChanged.connect(lambda value: (setattr(self.brush, key, value / factor), self.timer.start()))
        self.fields[key] = spin
        return label, spin

    def check(self, key):
        box = QCheckBox(self.CHECKS[key])
        box.setChecked(getattr(self.brush, key))
        box.toggled.connect(lambda value: (setattr(self.brush, key, value), self.timer.start()))
        self.checks[key] = box
        return None, box

    @staticmethod
    def hint(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName('muted')
        return label

    @staticmethod
    def buttons_row(*buttons):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for text, callback in buttons:
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        return holder

    # --------------------------------------------------------------- tabs

    def tip_rows(self):
        self.name = QLineEdit(self.brush.name)
        self.category = QLineEdit(self.brush.category)
        self.model = QComboBox()
        self.model.addItem('— manter as configurações atuais —', None)
        for index, brush in enumerate(self.owner.library.brushes):
            self.model.addItem(f'{brush.category} · {brush.name}', index)
        self.model.setToolTip('Copia ponta, dinâmica e textura de outro pincel, mantendo o nome.')
        self.model.activated.connect(self.start_from_model)
        self.tip_gallery = Gallery(3)
        self.known_tips = {}
        for label, kind in TIP_KINDS:
            mask = computed_mask(.85, 1.) if not kind else Brush(tip=generated_tip(kind)).mask()
            self.tip_gallery.add(label, kind, tip_icon(mask))
            if kind:
                self.known_tips[generated_tip(kind)] = kind
        self.custom_tip_item = self.tip_gallery.add('Personalizada', 'custom', QIcon())
        self.tip_gallery.itemClicked.connect(self.change_tip)
        tips = self.buttons_row(('Imagem…', self.load_tip), ('Camada atual', self.layer_tip),
                                ('Do Photoshop (.abr)…', self.abr_tip))
        rows = [('Nome', self.name), ('Categoria', self.category), ('Partir de', self.model),
                ('Ponta', self.tip_gallery), (None, tips)]
        return rows + [self.slider(key) for key in ('size', 'hardness', 'roundness', 'angle', 'spacing', 'flow')]

    def shape_rows(self):
        return [self.check('size_pressure'), self.slider('taper_in'), self.slider('speed_size'), self.slider('jitter'),
                self.slider('roundness_jitter'), self.slider('angle_jitter'), self.check('follow_direction'),
                self.check('flip_jitter'), self.slider('scatter'), self.slider('count'),
                (None, self.hint('Dispersão e quantidade espalham várias marcas a cada passo: folhagem, '
                                 'respingos, estrelas.'))]

    def paint_rows(self):
        return [self.slider('opacity_pressure'), self.slider('flow_pressure'), self.slider('opacity_jitter'),
                self.slider('depletion'), self.slider('wet_edges'),
                (None, self.hint('A tinta acaba ao longo do traço e ele termina seco e falhado, como um pincel '
                                 'real. Bordas úmidas acumulam pigmento no contorno, como aquarela.'))]

    def texture_rows(self):
        self.grain_gallery = Gallery(3)
        for label, kind in brush_engine.GRAINS:
            self.grain_gallery.add(label, kind, grain_icon(kind))
        self.grain_gallery.itemClicked.connect(self.change_grain)
        hint = self.hint('A textura fica presa ao papel: o pigmento pega primeiro nos relevos e, com mais '
                         'pressão, entra nos vales. A retícula cresce com a pressão, como um tom de mangá.')
        return [('Textura do papel', self.grain_gallery), self.slider('grain_strength'), self.slider('grain_scale'),
                self.slider('grain_contrast'), self.check('grain_invert'), (None, hint)]

    # ------------------------------------------------------------ actions

    def apply_values(self):
        """Show the current brush in every control (after undoing changes or picking a model)."""
        for key, spin in self.fields.items():
            spin.blockSignals(True)
            spin.setValue(getattr(self.brush, key) * self.SLIDERS[key][3])
            spin.blockSignals(False)
        for key, box in self.checks.items():
            box.blockSignals(True)
            box.setChecked(getattr(self.brush, key))
            box.blockSignals(False)
        self.sync_galleries()
        self.timer.start()

    def sync_galleries(self):
        kind = '' if not self.brush.tip else self.known_tips.get(self.brush.tip, 'custom')
        if kind == 'custom':
            self.custom_tip_item.setIcon(tip_icon(self.brush.mask()))
        self.custom_tip_item.setHidden(kind != 'custom')
        self.tip_gallery.select(kind)
        self.grain_gallery.select(self.brush.grain)

    def reset(self):
        self.brush = copy.deepcopy(self.initial)
        self.name.setText(self.brush.name)
        self.category.setText(self.brush.category)
        self.apply_values()

    def start_from_model(self):
        index = self.model.currentData()
        if index is None:
            return
        name, category = self.brush.name, self.brush.category
        self.brush = copy.deepcopy(self.owner.library.brushes[index])
        self.brush.name, self.brush.category, self.brush.source = name, category, {}
        self.apply_values()

    def change_tip(self, item=None):
        kind = self.tip_gallery.value()
        if kind == 'custom':
            if not self.brush.tip:
                self.load_tip()
        else:
            self.brush.tip = generated_tip(kind) if kind else ''
        self.sync_galleries()
        self.timer.start()

    def change_grain(self, item=None):
        kind = self.grain_gallery.value()
        if kind == 'custom':
            path, _ = QFileDialog.getOpenFileName(self, 'Textura do papel', '', 'Imagens (*.png *.jpg *.jpeg *.webp *.bmp)')
            if not path:
                self.sync_galleries()
                return
            try:
                image = Image.open(path).convert('L')
                image.thumbnail((512, 512))
                self.brush.grain_image = png_base64(image)
            except OSError as error:
                QMessageBox.warning(self, 'Textura', str(error))
                self.sync_galleries()
                return
        self.brush.grain = kind
        if kind and self.brush.grain_strength == 0:
            self.fields['grain_strength'].setValue(50)
        self.timer.start()

    def set_tip(self, tip):
        self.brush.tip = tip
        self.sync_galleries()
        self.timer.start()

    def load_tip(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Ponta do pincel', '', 'Imagens (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            try:
                self.set_tip(mask_from_image(Image.open(path)))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Ponta', str(error))
        self.sync_galleries()

    def layer_tip(self):
        try:
            self.set_tip(mask_from_image(qt_image(self.owner.canvas.image)))
        except ValueError as error:
            QMessageBox.warning(self, 'Ponta', str(error))

    def abr_tip(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Pontas do Photoshop', '', 'Pincéis do Photoshop (*.abr)')
        if path:
            self.pick_abr_tip(path)

    def pick_abr_tip(self, path):
        try:
            brushes = load_abr(path)
        except Exception as error:  # parser errors come in many types; report them
            QMessageBox.warning(self, 'Pontas do Photoshop', f'{Path(path).name}: {error}')
            return
        if not any(b.tip for b in brushes):
            QMessageBox.information(self, 'Pontas do Photoshop', 'Este arquivo só tem pontas redondas, sem imagem.')
            return
        dialog = AbrTipDialog(self, brushes)
        if dialog.exec() and dialog.chosen() is not None:
            chosen = dialog.chosen()
            self.fields['spacing'].setValue(chosen.spacing * 100)
            self.set_tip(chosen.tip)

    def update_preview(self):
        try:
            brush = Brush.from_dict(self.brush.to_dict())
        except ValueError:
            return
        color = QColor(self.owner.current_color)
        self.preview.show_brush(brush, color, self.preview_size.value())
        scale = max(1., self.tip_view.devicePixelRatioF())
        tip = brush.image(QColor('#202127')).scaled(round(88 * scale), round(88 * scale), Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation)
        tip.setDevicePixelRatio(scale)
        self.tip_view.setPixmap(QPixmap.fromImage(tip))

    def result_brush(self):
        self.brush.name = self.name.text().strip() or 'Meu pincel'
        self.brush.category = self.category.text().strip() or 'Meus pincéis'
        return Brush.from_dict(self.brush.to_dict())
