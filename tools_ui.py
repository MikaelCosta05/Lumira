"""Menus and tool options for selections, transforms, drawing guides and comics."""
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QImage, QPainter
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QSlider,
                             QInputDialog, QLabel, QMessageBox, QPushButton, QSpinBox, QWidget)

import selection as sel
from canvas import BRUSH_TOOLS, GUIDE_TOOLS, SELECT_TOOLS
from rig import TEMPLATE_CHOICES
from shading import STYLES
from shadow_ui import ShadowLayerPanel
import drawing_tools
import guides
from text_ui import TextDialog
from i18n import tr


class ToolFeatures:
    # ------------------------------------------------------------- brushes

    def brush_tool(self):
        tool = self.canvas.tool
        return tool if tool in BRUSH_TOOLS else 'brush'

    @property
    def selected_brush(self):
        return self.brush_for(self.brush_tool())

    @selected_brush.setter
    def selected_brush(self, brush):
        self.tool_brushes[self.brush_tool()] = brush

    def brush_for(self, tool):
        brush = self.tool_brushes.get(tool)
        return brush if brush is not None else self.library.preset(tool)

    # --------------------------------------------------------------- setup

    def setup_tools(self):
        self.tool_options = {'tolerance': 32, 'contiguous': True, 'sample_all': True, 'expand': 1,
                             'antialias': True, 'selection_mode': 'replace',
                             'rig_template': 'free', 'rig_mode': 'pose', 'auto_ik': True,
                             'shape_kind': 'rect', 'shape_fill': 'stroke', 'gradient_kind': 'linear',
                             'gradient_colors': 'colors'}
        self.text_settings = {}
        self.internal_clip = None
        self.build_tool_options()
        self.build_shadow_ui()
        self.build_edit_menu()
        self.build_selection_menu()
        self.build_guides_menu()
        self.setup_comics()
        view = self.canvas_menu
        view.addSeparator()
        self.flip_action = self.action(view, 'Espelhar vista (conferir proporções)', self.toggle_flip_view, 'Ctrl+Alt+F')
        self.flip_action.setCheckable(True)
        self.grayscale_action = self.action(view, 'Ver em tons de cinza (conferir valores)', self.toggle_grayscale, 'Ctrl+Alt+Y')
        self.grayscale_action.setCheckable(True)
        bar = self.menuBar()
        bar.removeAction(self.help_menu.menuAction())
        bar.addAction(self.help_menu.menuAction())
        self.canvas.show_rulers = bool(self.settings.get('rulers', False))
        self.canvas.show_grid = bool(self.settings.get('grid', False))
        self.canvas.grid_size = max(2, min(2048, int(self.settings.get('grid_size', 64))))
        self.rulers_action.setChecked(self.canvas.show_rulers)
        self.grid_action.setChecked(self.canvas.show_grid)
        self.canvas.selection_changed.connect(self.refresh_selection_actions)
        self.refresh_selection_actions()
        self.tool_changed(self.canvas.tool)

    def option_group(self, *widgets):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)
        for widget in widgets:
            if isinstance(widget, QComboBox):
                # Long item labels must not push the right side of the bar (workspace, theme, language) away.
                widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                widget.setMinimumContentsLength(12)
                widget.setMaximumWidth(210)
                widget.view().setMinimumWidth(widget.view().sizeHintForColumn(0) + 24)
            layout.addWidget(widget)
        return self.options_toolbar.insertWidget(self.options_stretch_action, container)

    def option_check(self, text, key, tooltip):
        check = QCheckBox(text)
        check.setChecked(self.tool_options[key])
        check.setToolTip(tooltip)
        check.toggled.connect(lambda value: self.tool_options.__setitem__(key, value))
        return check

    def option_combo(self, key, choices):
        combo = QComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(self.tool_options[key])))
        combo.currentIndexChanged.connect(lambda: self.tool_options.__setitem__(key, combo.currentData()))
        return combo

    # ------------------------------------------------------ symmetry / reference

    def set_symmetry(self, **values):
        symmetry = self.canvas.document.guides.setdefault('symmetry', {'mode': 'none', 'x': None, 'y': None, 'count': 6})
        symmetry.update(values)
        self.canvas.guides_edited()

    def sync_symmetry_controls(self):
        symmetry = self.canvas.document.guides.get('symmetry') or {}
        for widget, value in ((self.symmetry_mode, None), (self.symmetry_count, None)):
            widget.blockSignals(True)
        self.symmetry_mode.setCurrentIndex(max(0, self.symmetry_mode.findData(symmetry.get('mode', 'none'))))
        self.symmetry_count.setValue(int(symmetry.get('count', 6)))
        for widget in (self.symmetry_mode, self.symmetry_count):
            widget.blockSignals(False)

    def load_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Imagem de referência', '',
                                              'Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.gif)')
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, 'Referência', 'Não foi possível abrir a imagem.')
            return
        self.canvas.load_reference(image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
        self.reference_opacity.blockSignals(True)
        self.reference_opacity.setValue(50)
        self.reference_opacity.blockSignals(False)
        self.reference_action.setChecked(True)
        if self.canvas.tool != 'reference':
            self.set_tool('reference')

    def set_reference(self, **values):
        if self.canvas.reference:
            self.canvas.reference.update(values)
            self.canvas.update()

    def remove_reference(self):
        self.canvas.reference = None
        self.reference_action.setChecked(False)
        self.canvas.update()

    def toggle_reference(self, value):
        if self.canvas.reference is None:
            if value:
                self.load_reference()
            self.reference_action.setChecked(self.canvas.reference is not None)
            return
        self.set_reference(visible=bool(value))

    # ---------------------------------------------------------------- text

    def place_text(self, point):
        layer_ok = self.canvas.document.layers[self.canvas.document.active]
        dialog = TextDialog(self, self.text_settings)
        if not dialog.exec() or not dialog.text.toPlainText().strip():
            return
        self.text_settings = dialog.settings()
        document = self.canvas.document
        image = dialog.render(QSize(document.width, document.height), point)
        name = dialog.text.toPlainText().strip().splitlines()[0][:28]
        if dialog.new_layer.isChecked() or layer_ok.locked:
            def add(document):
                layer = document.blank_layer(f'T · {name}')
                painter = QPainter(layer.image)
                painter.drawImage(0, 0, image)
                painter.end()
                layer.content = True
                document.active += 1
                document.layers.insert(document.active, layer)
            self.layer_change(add)
        else:
            def paint(document):
                layer = document.layers[document.active]
                painter = QPainter(layer.image)
                if layer.alpha_lock:
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                painter.drawImage(0, 0, image)
                painter.end()
                layer.content = True
            self.mutate(paint)

    def option_spin(self, key, lo, hi, suffix, tooltip, width=54):
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(self.tool_options[key])
        spin.setSuffix(suffix)
        spin.setToolTip(tooltip)
        self.numeric(spin, width)
        spin.valueChanged.connect(lambda value: self.tool_options.__setitem__(key, value))
        return spin

    def build_tool_options(self):
        mode = QComboBox()
        for label, value in [('Substituir', 'replace'), ('Adicionar', 'add'), ('Subtrair', 'subtract'), ('Interseção', 'intersect')]:
            mode.addItem(label, value)
        mode.setToolTip('Também por teclado: Shift adiciona · Alt subtrai · Shift+Alt intersecta')
        mode.currentIndexChanged.connect(lambda: self.tool_options.__setitem__('selection_mode', mode.currentData()))
        hint = QLabel('Ctrl: proporção fixa')
        self.option_groups = {
            'selection': self.option_group(QLabel('Seleção'), mode, self.option_check(
                'Suavizar borda', 'antialias', 'Borda suave para elipse e laço'), hint),
            'sample': self.option_group(QLabel('Tolerância'), self.option_spin(
                'tolerance', 0, 255, '', 'Diferença máxima de cor aceita (0–255)'),
                self.option_check('Contígua', 'contiguous', 'Apenas áreas conectadas ao clique'),
                self.option_check('Todas as camadas', 'sample_all', 'Analisa a imagem visível em vez da camada ativa')),
            'expand': self.option_group(QLabel('Expandir'), self.option_spin(
                'expand', 0, 20, ' px', 'Avança o preenchimento sob a borda do traço para evitar falhas')),
        }
        self.snap_check = QCheckBox('Ajustar traço às guias')
        self.snap_check.setToolTip('Prende os traços às linhas de perspectiva e à régua (Ctrl+;)')
        self.snap_check.toggled.connect(self.set_snap)
        clear = QPushButton('Limpar guia')
        clear.clicked.connect(self.clear_current_guide)
        self.option_groups['guides'] = self.option_group(self.snap_check, clear, QLabel('Clique direito remove um ponto'))
        template = QComboBox()
        for label, value in TEMPLATE_CHOICES:
            template.addItem(label, value)
        template.setToolTip('Com um modelo escolhido, arraste um retângulo na tela para criar o esqueleto pronto')
        template.currentIndexChanged.connect(lambda: self.tool_options.__setitem__('rig_template', template.currentData()))
        rig_mode = QComboBox()
        rig_mode.addItem('Posar (keyframe)', 'pose')
        rig_mode.addItem('Ajustar esqueleto', 'edit')
        rig_mode.setToolTip('Posar grava a pose no quadro atual. Ajustar move e estica os ossos sem animar.')
        rig_mode.currentIndexChanged.connect(lambda: self.tool_options.__setitem__('rig_mode', rig_mode.currentData()))
        self.option_groups['shape'] = self.option_group(
            QLabel('Forma'), self.option_combo('shape_kind', drawing_tools.SHAPES),
            self.option_combo('shape_fill', drawing_tools.SHAPE_FILLS),
            QLabel('Shift: proporção · Alt: a partir do centro'))
        self.option_groups['gradient'] = self.option_group(
            QLabel('Degradê'), self.option_combo('gradient_kind', drawing_tools.GRADIENTS),
            self.option_combo('gradient_colors', drawing_tools.GRADIENT_COLORS), QLabel('Arraste para definir a direção'))
        self.symmetry_mode = QComboBox()
        for label, value in guides.SYMMETRY_MODES:
            self.symmetry_mode.addItem(label, value)
        self.symmetry_mode.currentIndexChanged.connect(lambda: self.set_symmetry(mode=self.symmetry_mode.currentData()))
        self.symmetry_count = QSpinBox()
        self.symmetry_count.setRange(2, 32)
        self.symmetry_count.setToolTip('Quantidade de cópias da simetria radial')
        self.numeric(self.symmetry_count, 44)
        self.symmetry_count.valueChanged.connect(lambda value: self.set_symmetry(count=value))
        center = QPushButton('Centralizar eixo')
        center.clicked.connect(lambda: self.set_symmetry(x=None, y=None))
        self.option_groups['symmetry'] = self.option_group(QLabel('Simetria'), self.symmetry_mode, QLabel('Cópias'),
                                                           self.symmetry_count, center, QLabel('Clique na tela para posicionar o eixo'))
        load = QPushButton('Carregar…')
        load.clicked.connect(self.load_reference)
        self.reference_opacity = QSlider(Qt.Orientation.Horizontal)
        self.reference_opacity.setRange(5, 100)
        self.reference_opacity.setFixedWidth(90)
        self.reference_opacity.setToolTip('Opacidade da referência')
        self.reference_opacity.valueChanged.connect(lambda value: self.set_reference(opacity=value / 100))
        self.reference_behind = QCheckBox('Atrás do desenho')
        self.reference_behind.toggled.connect(lambda value: self.set_reference(behind=value))
        remove = QPushButton('Remover')
        remove.clicked.connect(self.remove_reference)
        self.option_groups['reference'] = self.option_group(QLabel('Referência'), load, self.reference_opacity,
                                                            self.reference_behind, remove,
                                                            QLabel('Arraste para mover · roda para escala'))
        self.option_groups['effect'] = self.option_group(QLabel('A opacidade define a intensidade do efeito'))
        self.option_groups['bone'] = self.option_group(QLabel('Criar'), template, QLabel('Modo'), rig_mode, self.option_check(
            'IK em mãos e pés', 'auto_ik', 'Arrastar a ponta da mão ou do pé dobra o braço ou a perna inteira'))

    def tool_changed(self, tool):
        visible = {'selection': tool in SELECT_TOOLS, 'sample': tool in ('wand', 'fill'),
                   'expand': tool == 'fill', 'guides': tool in GUIDE_TOOLS, 'bone': tool == 'bone',
                   'shape': tool == 'shape', 'gradient': tool == 'gradient', 'symmetry': tool == 'symmetry',
                   'reference': tool == 'reference', 'effect': tool in ('smudge', 'blur'),
                   'balloon': tool == 'balloon', 'comic_panel': tool == 'panel'}
        for key, action in self.option_groups.items():
            action.setVisible(visible[key])
        if tool in BRUSH_TOOLS and hasattr(self, 'brush_panel'):
            self.brush_panel.refresh_list()
        hints = {'perspective': 'Clique para criar até 3 pontos de fuga; arraste para mover; botão direito remove.',
                 'ruler': 'Arraste para posicionar a régua. Com o ajuste ligado, os traços seguem paralelos a ela.',
                 'move': 'Arraste para mover a seleção ou a camada inteira. Shift trava o eixo.',
                 'rotate': 'Arraste para girar a vista. Shift gira em passos de 15°.',
                 'fill': 'Clique para preencher. Ctrl + clique pega a cor.',
                 'wand': 'Clique numa área para selecioná-la. Shift adiciona, Alt subtrai.',
                 'pixel': 'Pixel art: pixels nítidos, sem suavização. Shift + clique traça uma reta.',
                 'bone': 'Arraste um osso para girar · ponta da mão/pé: IK · Alt: IK · Shift ou raiz: mover · Ctrl + ponta: osso filho · botão direito: opções.'}
        hints.update({
            'shape': 'Arraste para desenhar a forma. Polígono: clique nos pontos e dê duplo clique (ou Enter) para fechar.',
            'gradient': 'Arraste para aplicar o degradê na camada (ou na seleção).',
            'text': 'Clique onde o texto deve começar.',
            'balloon': 'Clique onde fica o balão e arraste até quem fala para apontar o rabicho.',
            'panel': 'Clique num quadro para selecioná-lo (Shift soma, Alt subtrai).',
            'smudge': 'Arraste para esfumar a tinta da camada ativa.',
            'blur': 'Arraste para desfocar a camada ativa.',
            'symmetry': 'Clique ou arraste para posicionar o centro da simetria; escolha o modo na barra de opções.',
            'reference': 'Arraste para mover a imagem de referência; use a roda para mudar a escala.'})
        if tool in hints:
            self.statusBar().showMessage(hints[tool], 6000)
        if tool == 'symmetry':
            self.sync_symmetry_controls()
        if tool == 'reference' and self.canvas.reference is None:
            QTimer.singleShot(0, self.load_reference)

    def refresh_tools(self):
        if not hasattr(self, 'snap_check'):
            return
        self.shadow_panel.refresh()
        self.snap_check.blockSignals(True)
        self.snap_check.setChecked(bool(self.canvas.document.guides.get('snap')))
        self.snap_check.blockSignals(False)
        self.snap_action.blockSignals(True)
        self.snap_action.setChecked(bool(self.canvas.document.guides.get('snap')))
        self.snap_action.blockSignals(False)
        self.perspective_visible_action.blockSignals(True)
        self.perspective_visible_action.setChecked(self.canvas.document.guides.get('perspective_visible', True))
        self.perspective_visible_action.blockSignals(False)

    # -------------------------------------------------------- shadow layers

    def build_shadow_ui(self):
        self.shadow_panel = ShadowLayerPanel(self)
        layout = self.layers_dock.widget().layout()
        layout.insertWidget(layout.indexOf(self.layer_list) + 1, self.shadow_panel)
        row = layout.itemAt(layout.count() - 1).layout()
        row.insertWidget(2, self.icon_button('theme-light-dark', 'Nova camada de sombra', lambda: self.add_shadow_layer()))
        layers = next(a.menu() for a in self.menuBar().actions() if a.text() == 'Camadas')
        layers.addSeparator()
        self.action(layers, 'Nova camada de sombra', lambda: self.add_shadow_layer(), 'Ctrl+Shift+H')
        styles = layers.addMenu('Nova camada de sombra com estilo')
        for label, value in STYLES:
            self.action(styles, label, lambda checked=False, v=value: self.add_shadow_layer(v))

    def add_shadow_layer(self, style='soft'):
        if len(self.canvas.document.layers) >= 64:
            self.statusBar().showMessage('Limite de 64 camadas atingido.', 5000)
            return
        def add(document):
            count = sum(layer.is_shadow for layer in document.layers) + 1
            document.active += 1
            document.layers.insert(document.active, document.shadow_layer(tr(f'Sombras {count}'), style))
        self.layer_change(add)
        if self.canvas.tool not in ('brush', 'pencil', 'pen', 'eraser', 'fill', 'select_rect', 'select_ellipse', 'lasso', 'wand'):
            self.set_tool('brush')
        self.statusBar().showMessage('Camada de sombra criada: pinte as áreas de sombra e troque o estilo no painel Camadas.', 7000)

    # ---------------------------------------------------------- edit menu

    def build_edit_menu(self):
        edit = self.edit_menu
        edit.addSeparator()
        self.action(edit, 'Recortar', self.cut_selection, 'Ctrl+X')
        self.action(edit, 'Copiar', self.copy_selection, 'Ctrl+C')
        self.action(edit, 'Colar como nova camada', self.paste_layer, 'Ctrl+V')
        edit.addSeparator()
        self.action(edit, 'Preencher com a cor principal', lambda: self.canvas.fill_selection(QColor(self.current_color)), 'Alt+Backspace')
        self.action(edit, 'Limpar pixels', lambda: self.canvas.clear_pixels(), 'Delete')
        transform = edit.addMenu('Girar e espelhar')
        for label, args, shortcut in [('Girar 90° horário', (90.,), 'Ctrl+]'), ('Girar 90° anti-horário', (-90.,), 'Ctrl+['),
                                      ('Girar 180°', (180.,), None), ('Espelhar na horizontal', (0., True, False), None),
                                      ('Espelhar na vertical', (0., False, True), None)]:
            self.action(transform, label, lambda checked=False, a=args: self.canvas.transform_content(*a), shortcut)
        transform.addSeparator()
        self.action(transform, 'Girar livremente…', self.free_rotate)
        hint = QAction('Com seleção ativa, gira só a seleção', self)
        hint.setEnabled(False)
        transform.addAction(hint)

    def free_rotate(self):
        angle, accepted = QInputDialog.getDouble(self, 'Girar livremente', 'Ângulo (graus, positivo = horário):', 15., -360., 360., 1)
        if accepted and angle:
            self.canvas.transform_content(angle)

    def copy_selection(self):
        self.canvas.finish_stroke()
        image, origin = self.canvas.selected_image()
        if image is None:
            self.statusBar().showMessage('Nada para copiar nesta camada.', 4000)
            return False
        QApplication.clipboard().setImage(image)
        self.internal_clip = (image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied), origin)
        self.statusBar().showMessage(f'Copiado: {image.width()} × {image.height()} px', 4000)
        return True

    def cut_selection(self):
        if self.canvas.editable_layer() is not None and self.copy_selection():
            self.canvas.clear_pixels()

    def paste_layer(self):
        self.canvas.finish_stroke()
        image = QApplication.clipboard().image()
        if image.isNull():
            self.statusBar().showMessage('A área de transferência não contém imagem.', 4000)
            return
        if len(self.canvas.document.layers) >= 64:
            self.statusBar().showMessage('Limite de 64 camadas atingido.', 5000)
            return
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        document = self.canvas.document
        if self.internal_clip and self.internal_clip[0] == image:
            origin = self.internal_clip[1]
        else:
            origin = QPoint((document.width - image.width()) // 2, (document.height - image.height()) // 2)

        def paste(document):
            layer = document.blank_layer('Colado')
            painter = QPainter(layer.image)
            painter.drawImage(origin, image)
            painter.end()
            layer.content = True
            document.active += 1
            document.layers.insert(document.active, layer)
        self.layer_change(paste)
        area = QRect(origin, image.size()).intersected(QRect(0, 0, document.width, document.height))
        if not area.isEmpty():
            self.canvas.select_rect(area)
        self.statusBar().showMessage('Colado em nova camada. Use Mover (V) para posicionar.', 5000)

    # ----------------------------------------------------- selection menu

    def build_selection_menu(self):
        menu = self.menuBar().addMenu('Seleção')
        self.action(menu, 'Selecionar tudo', self.canvas.select_all, 'Ctrl+A')
        self.deselect_action = self.action(menu, 'Desmarcar', lambda: self.canvas.set_selection(None), 'Ctrl+D')
        self.action(menu, 'Inverter seleção', self.canvas.invert_selection, 'Ctrl+Shift+I')
        self.action(menu, 'Selecionar conteúdo da camada', self.select_layer_content)
        menu.addSeparator()
        self.selection_actions = [self.deselect_action]
        for label, operation in [('Expandir…', 'grow'), ('Contrair…', 'shrink'), ('Suavizar borda…', 'feather')]:
            self.selection_actions.append(self.action(menu, label, lambda checked=False, o=operation: self.modify_selection(o)))
        menu.addSeparator()
        for tool in ('select_rect', 'select_ellipse', 'lasso', 'wand'):
            menu.addAction(self.tool_actions[tool])

    def refresh_selection_actions(self):
        active = self.canvas.selection is not None
        for action in self.selection_actions:
            action.setEnabled(active)

    def select_layer_content(self):
        values = sel.alpha(self.canvas.layer_in_document_space())
        if not values.any():
            self.statusBar().showMessage('A camada ativa está vazia.', 4000)
        self.canvas.set_selection(values)

    def modify_selection(self, operation):
        values = self.canvas.selection_values
        if values is None:
            return
        label = {'grow': 'Expandir em (px)', 'shrink': 'Contrair em (px)', 'feather': 'Raio da suavização (px)'}[operation]
        amount, accepted = QInputDialog.getInt(self, 'Modificar seleção', label, 4, 1, 200)
        if not accepted:
            return
        from scipy import ndimage
        inside = values >= 128
        structure = ndimage.generate_binary_structure(2, 2)
        if operation == 'grow':
            result = ndimage.binary_dilation(inside, structure, iterations=amount).astype(np.uint8) * 255
        elif operation == 'shrink':
            result = ndimage.binary_erosion(inside, structure, iterations=amount).astype(np.uint8) * 255
        else:
            result = np.clip(ndimage.gaussian_filter(values.astype(np.float32), amount / 2), 0, 255).astype(np.uint8)
        self.canvas.set_selection(result)

    # -------------------------------------------------------- guides menu

    def build_guides_menu(self):
        menu = self.menuBar().addMenu('Guias')
        self.rulers_action = self.action(menu, 'Réguas nas bordas', self.toggle_rulers, 'Ctrl+R')
        self.rulers_action.setCheckable(True)
        self.grid_action = self.action(menu, 'Grade', self.toggle_grid, "Ctrl+'")
        self.grid_action.setCheckable(True)
        self.action(menu, 'Tamanho da grade…', self.choose_grid_size)
        self.grid_iso_action = self.action(menu, 'Grade isométrica', self.toggle_grid_kind)
        self.grid_iso_action.setCheckable(True)
        composition = menu.addMenu('Composição')
        group = QActionGroup(self)
        self.composition_actions = {}
        for label, value in guides.COMPOSITIONS:
            action = self.action(composition, label, lambda checked=False, v=value: self.set_composition(v))
            action.setCheckable(True)
            action.setChecked(value == 'none')
            group.addAction(action)
            self.composition_actions[value] = action
        symmetry = menu.addMenu('Simetria')
        group = QActionGroup(self)
        for label, value in guides.SYMMETRY_MODES:
            action = self.action(symmetry, label, lambda checked=False, v=value: self.set_symmetry(mode=v))
            action.setCheckable(True)
            group.addAction(action)
        symmetry.addSeparator()
        self.action(symmetry, 'Centralizar eixo', lambda: self.set_symmetry(x=None, y=None))
        symmetry.addAction(self.tool_actions['symmetry'])
        reference = menu.addMenu('Imagem de referência')
        self.action(reference, 'Carregar imagem…', self.load_reference)
        self.reference_action = self.action(reference, 'Mostrar referência', self.toggle_reference)
        self.reference_action.setCheckable(True)
        self.action(reference, 'Remover referência', self.remove_reference)
        reference.addAction(self.tool_actions['reference'])
        menu.addSeparator()
        perspective = menu.addMenu('Perspectiva')
        for label, count in [('1 ponto de fuga', 1), ('2 pontos de fuga', 2), ('3 pontos de fuga', 3)]:
            self.action(perspective, label, lambda checked=False, n=count: self.perspective_preset(n))
        perspective.addSeparator()
        self.perspective_visible_action = self.action(perspective, 'Mostrar linhas de perspectiva', self.toggle_perspective)
        self.perspective_visible_action.setCheckable(True)
        self.action(perspective, 'Densidade das linhas…', self.perspective_density)
        self.action(perspective, 'Remover pontos de fuga', lambda: self.edit_guides(points=[]))
        perspective.addSeparator()
        perspective.addAction(self.tool_actions['perspective'])
        menu.addAction(self.tool_actions['ruler'])
        self.action(menu, 'Remover régua', lambda: self.edit_guides(ruler=None))
        menu.addSeparator()
        self.snap_action = self.action(menu, 'Ajustar traço às guias', lambda checked: self.set_snap(checked), 'Ctrl+;')
        self.snap_action.setCheckable(True)
        menu.addSeparator()
        self.action(menu, 'Sangria e área segura…', self.print_guides)

    def edit_guides(self, **values):
        self.canvas.document.guides.update(values)
        self.canvas.guides_edited()

    def set_snap(self, value):
        guides = self.canvas.document.guides
        if value and not guides['points'] and not guides.get('ruler'):
            self.statusBar().showMessage('Crie pontos de fuga (Shift+U) ou uma régua (U) para usar o ajuste.', 6000)
        self.edit_guides(snap=bool(value))

    def clear_current_guide(self):
        self.edit_guides(**({'points': []} if self.canvas.tool == 'perspective' else {'ruler': None}))

    def toggle_rulers(self, value):
        self.canvas.show_rulers = bool(value)
        self.canvas.update()

    def toggle_grid_kind(self, value):
        self.canvas.grid_kind = 'iso' if value else 'square'
        self.canvas.show_grid = True
        self.grid_action.setChecked(True)
        self.canvas.update()

    def set_composition(self, value):
        self.canvas.composition = value
        self.canvas.update()

    def toggle_flip_view(self, value):
        self.canvas.flip_view = bool(value)
        self.canvas.update()
        self.canvas.view_changed.emit()

    def toggle_grayscale(self, value):
        self.canvas.grayscale_view = bool(value)
        self.canvas.update()

    def toggle_grid(self, value):
        self.canvas.show_grid = bool(value)
        self.canvas.update()

    def choose_grid_size(self):
        size, accepted = QInputDialog.getInt(self, 'Grade', 'Tamanho de cada célula (px):', self.canvas.grid_size, 2, 2048)
        if accepted:
            self.canvas.grid_size = size
            self.canvas.show_grid = True
            self.grid_action.setChecked(True)
            self.canvas.update()

    def toggle_perspective(self, value):
        self.edit_guides(perspective_visible=bool(value))

    def perspective_density(self):
        guides = self.canvas.document.guides
        rays, accepted = QInputDialog.getInt(self, 'Perspectiva', 'Linhas por ponto de fuga:', guides.get('rays', 28), 4, 120)
        if accepted:
            self.edit_guides(rays=rays)

    def perspective_preset(self, count):
        width, height = self.canvas.document.width, self.canvas.document.height
        presets = {1: [[width / 2, height * .45]],
                   2: [[-width * .6, height * .45], [width * 1.6, height * .45]],
                   3: [[-width * .6, height * .35], [width * 1.6, height * .35], [width / 2, height * 2.4]]}
        self.edit_guides(points=presets[count], perspective_visible=True)
        self.set_tool('perspective')
        if count > 1:
            self.canvas.set_zoom(min(self.canvas.zoom, (self.canvas.width() - 40) / (width * 3.4)))
