"""Visual composition of the studio. Drawing algorithms live in canvas.py."""
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTabBar, QTabWidget,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from canvas import TOOL_INFO, TOOL_SLOTS
from design_widgets import (BrushPreview, ColorChips, ColorSelector, ColorWheel, DockHeader, LayerDelegate, LogoMark,
                            SizePreset, ToolSlot, icon)
from document import BLEND_MODES, BLEND_NAMES
from i18n import tr
from shading import STYLE_NAMES
from stabilizer import Stabilizer
from themes import PALETTES, stylesheet
from widgets import Navigator
from window_chrome import apply_titlebar


class ColorPicker(QStackedWidget):
    """Colour wheel (default) or square selector, sharing one colour."""
    color_changed = pyqtSignal(QColor)

    def __init__(self):
        super().__init__()
        self.wheel, self.square = ColorWheel(), ColorSelector()
        for widget in (self.wheel, self.square):
            self.addWidget(widget)
            widget.color_changed.connect(self.forward)
        self.setMinimumHeight(132)

    def forward(self, color):
        other = self.square if self.sender() is self.wheel else self.wheel
        other.set_color(color)
        self.color_changed.emit(color)

    def set_color(self, color):
        self.wheel.set_color(color)
        self.square.set_color(color)

    def toggle(self):
        self.setCurrentIndex(1 - self.currentIndex())
        self.setMinimumHeight(132 if self.currentIndex() == 0 else 104)


class WorkbenchUI:
    DESIGN_VERSION = 4

    def icon_button(self, name, tooltip, callback, parent=None):
        button = QToolButton(parent)
        button.setObjectName('quietButton')
        button.setFixedSize(26, 26)
        button.setIconSize(QSize(17, 17))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        self.design_icons.append((button, name))
        return button

    def numeric(self, widget, width=65):
        widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        widget.setFixedWidth(width)
        widget.setFixedHeight(24)
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        return widget

    # --------------------------------------------------------------- top

    def build_toolbar(self):
        self.design_icons = []
        self.dock_headers = []
        self.focus_mode = False
        self.secondary_color = QColor('#ffffff')
        self.logo = LogoMark(self)
        self.logo.setParent(self.menuBar())
        self.logo.move(4, 2)
        toolbar = QToolBar('Opções da ferramenta', self)
        toolbar.setObjectName('optionsToolbar')
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.options_toolbar = toolbar
        self.tool_icon = QLabel()
        self.tool_icon.setFixedSize(20, 20)
        toolbar.addWidget(self.tool_icon)
        self.tool_label = QLabel('Pincel')
        self.tool_label.setObjectName('toolBadge')
        self.tool_label.setMinimumWidth(70)
        toolbar.addWidget(self.tool_label)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel('Tamanho'))
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(.1, 500)
        self.size_spin.setDecimals(1)
        self.size_spin.setValue(self.brush_size)
        self.size_spin.setSuffix(' px')
        self.numeric(self.size_spin, 72)
        self.size_spin.valueChanged.connect(self.set_brush_size)
        toolbar.addWidget(self.size_spin)
        toolbar.addWidget(QLabel('Opacidade'))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(1, 100)
        self.opacity_spin.setValue(100)
        self.opacity_spin.setSuffix('%')
        self.numeric(self.opacity_spin, 56)
        self.opacity_spin.valueChanged.connect(lambda v: setattr(self, 'brush_opacity', v / 100))
        toolbar.addWidget(self.opacity_spin)
        toolbar.addWidget(QLabel('Estabilizador'))
        self.stab_combo = QComboBox()
        self.stab_combo.setObjectName('stabilizerControl')
        self.stab_combo.setFixedWidth(86)
        for level in Stabilizer.LEVELS:
            self.stab_combo.addItem('0 · Livre' if level == '0' else level, level)
        self.stab_combo.setCurrentIndex(self.stab_combo.findData(self.stabilizer_level))
        self.stab_combo.setToolTip('0: livre · 1–15: suave · S-1–S-7: firme para contornos')
        self.stab_combo.currentIndexChanged.connect(self.change_stabilizer)
        toolbar.addWidget(self.stab_combo)
        stretch = QWidget()
        stretch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.options_stretch_action = toolbar.addWidget(stretch)
        self.workspace_combo = QComboBox()
        self.workspace_combo.setFixedWidth(120)
        self.workspace_combo.addItems(['Pintura', 'Foco na tela'])
        self.workspace_combo.setToolTip('Organização da área de trabalho')
        self.workspace_combo.currentIndexChanged.connect(self.change_workspace)
        toolbar.addWidget(self.workspace_combo)
        self.theme_button = self.icon_button('weather-night', 'Alternar tema claro / escuro', self.toggle_theme)
        toolbar.addWidget(self.theme_button)
        self.appearance_button = self.icon_button('palette-outline', 'Personalizar aparência (cores, fundo, fonte)',
                                                  self.customize_appearance)
        toolbar.addWidget(self.appearance_button)
        self.brand_label = QLabel('')
        self.tools_toolbar = QToolBar('Ferramentas', self)
        self.tools_toolbar.setObjectName('toolsToolbar')
        self.tools_toolbar.setMovable(False)
        self.tools_toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.tools_toolbar)
        self.tool_slots = []
        for group in TOOL_SLOTS:
            if group is None:
                self.tools_toolbar.addSeparator()
                continue
            slot = ToolSlot(self, [self.tool_actions[tool] for tool in group])
            slot.toolbar_action = self.tools_toolbar.addWidget(slot)
            slot.sync()
            self.tool_slots.append(slot)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.tools_toolbar.addWidget(spacer)
        self.color_chips = ColorChips(self)
        self.tools_toolbar.addWidget(self.color_chips)
        self.foreground_chip = self.color_chips
        frame = QWidget()
        frame.setObjectName('documentFrame')
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 6)
        view = QWidget()
        view.setObjectName('documentView')
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.document_bar = QFrame()
        self.document_bar.setObjectName('documentBar')
        self.document_bar.setFixedHeight(34)
        row = QHBoxLayout(self.document_bar)
        row.setContentsMargins(4, 0, 10, 0)
        row.setSpacing(4)
        self.document_title = QLabel('Sem título')
        self.document_title.setObjectName('documentTab')
        row.addWidget(self.document_title)
        self.close_tab = QToolButton()
        self.close_tab.setObjectName('tabClose')
        self.close_tab.setFixedSize(20, 20)
        self.close_tab.setToolTip('Fechar documento')
        self.close_tab.clicked.connect(self.close_document)
        row.addWidget(self.close_tab)
        row.addStretch()
        self.document_info = QLabel('RGBA / 8 bits')
        self.document_info.setObjectName('muted')
        row.addWidget(self.document_info)
        layout.addWidget(self.document_bar)
        layout.addWidget(self.canvas, 1)
        outer.addWidget(view)
        self.setCentralWidget(frame)
        self.view_menu.addSeparator()
        self.action(self.view_menu, 'Restaurar área de trabalho', self.reset_workspace)
        self.action(self.view_menu, 'Foco na tela', self.toggle_focus, 'F11')

    def close_document(self):
        if self.maybe_save():
            from document import Document
            self.timeline.stop()
            self.canvas.set_document(Document())
            self.remove_recovery()

    def choose_secondary_color(self):
        from PyQt6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(self.secondary_color, self, 'Cor secundária', QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.secondary_color = color
            self.color_chips.update()

    # ------------------------------------------------------------- docks

    def dock(self, title, name, scroll=False):
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setMinimumWidth(262)
        panel = QWidget()
        panel.setObjectName('panel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(7)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setWidget(panel)
            dock.setWidget(area)
        else:
            dock.setWidget(panel)
        header = DockHeader(self, dock, title)
        dock.setTitleBarWidget(header)
        self.dock_headers.append(header)
        dock.visibilityChanged.connect(lambda visible: self.sync_dock_titles())
        dock.topLevelChanged.connect(lambda floating: self.sync_dock_titles())
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.view_menu.addAction(dock.toggleViewAction())
        return dock, layout

    def build_docks(self):
        self.color_dock, layout = self.dock('Cor', 'colorDockV4')
        self.color_wheel = ColorPicker()
        self.color_wheel.color_changed.connect(lambda c: self.set_color(c, update_wheel=False))
        layout.addWidget(self.color_wheel, 1)
        row = QHBoxLayout()
        row.setSpacing(7)
        self.color_preview = QPushButton()
        self.color_preview.setFixedSize(24, 24)
        self.color_preview.setToolTip('Abrir seletor de cores')
        self.color_preview.clicked.connect(self.choose_color)
        row.addWidget(self.color_preview)
        row.addWidget(self.icon_button('triangle-outline', 'Alternar roda / quadrado de cor', self.color_wheel.toggle))
        row.addStretch()
        hex_label = QLabel('Hex:')
        hex_label.setObjectName('muted')
        row.addWidget(hex_label)
        self.hex_edit = QLineEdit()
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setFixedWidth(82)
        self.hex_edit.editingFinished.connect(self.color_from_hex)
        row.addWidget(self.hex_edit)
        layout.addLayout(row)
        self.swatch_buttons = []
        row = QHBoxLayout()
        row.setSpacing(5)
        for value in ['#202127', '#ffffff', '#d17764', '#e6b46a', '#84a591', '#749ebd', '#a48cbd', '#d7b4ad']:
            button = QPushButton()
            button.setFixedSize(22, 18)
            button.setProperty('swatch', True)
            button.setToolTip(value)
            button.setStyleSheet(f'background: {value}; border: 1px solid #555; border-radius: 4px;')
            button.clicked.connect(lambda checked=False, c=value: self.set_color(QColor(c)))
            self.swatch_buttons.append(button)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.nav_dock, layout = self.dock('Navegador', 'navigatorDockV4')
        self.navigator = Navigator(self.canvas)
        self.navigator.setMinimumHeight(114)
        self.navigator.recenter.connect(self.recenter)
        layout.addWidget(self.navigator, 1)
        fit = QPushButton('Ajustar à janela')
        fit.clicked.connect(self.canvas.fit)
        layout.addWidget(fit)
        self.build_brush_dock()
        self.build_layers_dock()
        self.build_panel_strip()
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self.arrange_docks()
        self.change_stabilizer()

    def build_brush_dock(self):
        self.brush_dock, layout = self.dock('Pincel', 'brushDockV4')
        layout.setContentsMargins(4, 0, 4, 4)
        self.brush_tabs = QTabWidget()
        self.brush_tabs.setObjectName('inspectorTabs')
        layout.addWidget(self.brush_tabs)
        page = QWidget()
        page.setObjectName('panel')
        body = QVBoxLayout(page)
        body.setContentsMargins(10, 8, 10, 8)
        body.setSpacing(7)
        self.brush_preview = BrushPreview(self)
        body.addWidget(self.brush_preview)
        row = QHBoxLayout()
        row.addWidget(QLabel('Tamanho'))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 2000)
        self.size_slider.setValue(50)
        self.size_slider.valueChanged.connect(lambda v: self.size_spin.setValue(v / 10))
        row.addWidget(self.size_slider, 1)
        self.brush_size_readout = QLabel('5,0 px')
        self.brush_size_readout.setObjectName('muted')
        self.brush_size_readout.setFixedWidth(50)
        row.addWidget(self.brush_size_readout)
        body.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(5)
        self.size_presets = []
        for size in [2.3, 5, 10, 20, 50]:
            button = SizePreset(self, size)
            self.size_presets.append(button)
            row.addWidget(button)
        row.addStretch()
        body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Caneta'))
        self.pressure_combo = QComboBox()
        for label, profile in [('Toque leve', 'Leve'), ('Equilibrada', 'Normal'), ('Pressão firme', 'Firme')]:
            self.pressure_combo.addItem(label, profile)
        self.pressure_combo.setCurrentIndex(self.pressure_combo.findData(self.pressure_profile))
        self.pressure_combo.setToolTip('Ajusta a sensibilidade da pressão, independentemente da estabilização.')
        self.pressure_combo.currentIndexChanged.connect(self.change_pressure_design)
        row.addWidget(self.pressure_combo, 1)
        body.addLayout(row)
        self.pressure_check = QCheckBox('Pressão controla o tamanho')
        self.pressure_check.setChecked(True)
        self.pressure_check.toggled.connect(self.change_pressure_enabled_design)
        body.addWidget(self.pressure_check)
        row = QHBoxLayout()
        row.addWidget(QLabel('Espessura mínima'))
        row.addStretch()
        self.minimum_spin = QSpinBox()
        self.minimum_spin.setRange(0, 80)
        self.minimum_spin.setValue(15)
        self.minimum_spin.setSuffix('%')
        self.numeric(self.minimum_spin, 60)
        self.minimum_spin.valueChanged.connect(self.change_minimum_design)
        row.addWidget(self.minimum_spin)
        body.addLayout(row)
        body.addStretch()
        self.brush_tabs.addTab(self.scrolled(page), 'Ajustes')
        page = QWidget()
        page.setObjectName('panel')
        body = QVBoxLayout(page)
        body.setContentsMargins(10, 8, 10, 8)
        body.setSpacing(8)
        row = QHBoxLayout()
        for label, level in [('Livre', '0'), ('Suave', '10'), ('Firme', 'S-4')]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=level: self.stab_combo.setCurrentIndex(self.stab_combo.findData(value)))
            row.addWidget(button)
        body.addLayout(row)
        self.stab_description = QLabel()
        self.stab_description.setObjectName('muted')
        self.stab_description.setWordWrap(True)
        body.addWidget(self.stab_description)
        self.guide_check = QCheckBox('Guia do estabilizador')
        self.guide_check.setChecked(True)
        self.guide_check.toggled.connect(self.toggle_guide)
        body.addWidget(self.guide_check)
        hint = QLabel('A ponta do traço é concluída ao soltar a caneta.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        body.addWidget(hint)
        body.addStretch()
        self.brush_tabs.addTab(self.scrolled(page), 'Estabilização')

    def scrolled(self, page):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def build_layers_dock(self):
        self.layers_dock, layout = self.dock('Camadas', 'layersDockV4')
        header = QFrame()
        header.setObjectName('layerHeader')
        rows = QVBoxLayout(header)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        row = QHBoxLayout()
        label = QLabel('Mistura:')
        label.setObjectName('muted')
        row.addWidget(label)
        self.layer_blend = QComboBox()
        for name, key, _ in BLEND_MODES:
            self.layer_blend.addItem(name, key)
        self.layer_blend.currentIndexChanged.connect(self.change_layer_blend)
        row.addWidget(self.layer_blend, 1)
        label = QLabel('Opacidade:')
        label.setObjectName('muted')
        row.addWidget(label)
        self.layer_opacity = QSpinBox()
        self.layer_opacity.setRange(0, 100)
        self.layer_opacity.setSuffix('%')
        self.numeric(self.layer_opacity, 54)
        self.layer_opacity.valueChanged.connect(self.change_layer_opacity)
        row.addWidget(self.layer_opacity)
        rows.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(2)
        label = QLabel('Bloquear:')
        label.setObjectName('muted')
        row.addWidget(label)
        self.layer_alpha_lock = self.icon_button('checkerboard', 'Bloquear pixels transparentes (pinta só onde já há desenho)',
                                                 lambda: None)
        self.layer_alpha_lock.setCheckable(True)
        self.layer_alpha_lock.toggled.connect(self.change_layer_alpha_lock)
        row.addWidget(self.layer_alpha_lock)
        self.layer_lock = self.icon_button('lock-outline', 'Bloquear a camada inteira', lambda: None)
        self.layer_lock.setCheckable(True)
        self.layer_lock.toggled.connect(self.change_layer_lock)
        row.addWidget(self.layer_lock)
        row.addStretch()
        self.paper_check = QCheckBox('Papel branco')
        self.paper_check.setChecked(True)
        self.paper_check.toggled.connect(self.change_paper)
        row.addWidget(self.paper_check)
        rows.addLayout(row)
        layout.addWidget(header)
        self.layer_list = QListWidget()
        self.layer_list.setObjectName('layerList')
        self.layer_list.setMinimumHeight(80)
        self.layer_list.setMouseTracking(True)
        self.layer_list.setItemDelegate(LayerDelegate(self))
        self.layer_list.currentRowChanged.connect(self.select_layer)
        self.layer_list.itemChanged.connect(self.change_layer_visibility)
        self.layer_list.itemDoubleClicked.connect(lambda: self.rename_layer())
        layout.addWidget(self.layer_list, 1)
        row = QHBoxLayout()
        row.setSpacing(1)
        self.layer_count_label = QLabel('1 camada')
        self.layer_count_label.setObjectName('muted')
        row.addWidget(self.layer_count_label)
        row.addStretch()
        for name, tip, callback in [('plus', 'Nova camada', self.add_layer), ('content-duplicate', 'Duplicar camada', self.duplicate_layer),
                                    ('arrow-collapse-down', 'Mesclar com a camada abaixo', self.merge_down),
                                    ('chevron-up', 'Mover camada para cima', lambda: self.move_layer(1)),
                                    ('chevron-down', 'Mover camada para baixo', lambda: self.move_layer(-1)),
                                    ('delete-outline', 'Excluir camada', self.remove_layer)]:
            row.addWidget(self.icon_button(name, tip, callback))
        layout.addLayout(row)

    def build_panel_strip(self):
        """Narrow column of panel shortcuts between the canvas and the panels."""
        self.strip_dock = QDockWidget('Atalhos de painéis', self)
        self.strip_dock.setObjectName('panelStripDockV4')
        self.strip_dock.setTitleBarWidget(QWidget())
        self.strip_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.strip_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.panel_strip = QToolBar('Painéis', self)
        self.panel_strip.setObjectName('panelStrip')
        self.panel_strip.setOrientation(Qt.Orientation.Vertical)
        self.panel_strip.setIconSize(QSize(18, 18))
        self.strip_dock.setWidget(self.panel_strip)
        self.strip_dock.setFixedWidth(42)
        self.strip_actions = []
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.strip_dock)

    def add_strip_button(self, name, tooltip, callback):
        action = QAction(tooltip, self)
        action.setToolTip(tooltip)
        action.triggered.connect(callback)
        self.panel_strip.addAction(action)
        self.strip_actions.append((action, name))
        return action

    def sync_dock_titles(self):
        for header in self.dock_headers:
            header.sync_title()

    def show_panel(self, dock, tab=None):
        dock.show()
        dock.raise_()
        if tab is not None:
            tab()

    def arrange_docks(self):
        main = [self.color_dock, self.nav_dock, self.brush_dock, self.layers_dock]
        for dock in main:
            dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            dock.show()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.strip_dock)
        self.splitDockWidget(self.strip_dock, self.color_dock, Qt.Orientation.Horizontal)
        self.splitDockWidget(self.color_dock, self.brush_dock, Qt.Orientation.Vertical)
        self.splitDockWidget(self.brush_dock, self.layers_dock, Qt.Orientation.Vertical)
        self.tabifyDockWidget(self.color_dock, self.nav_dock)
        self.color_dock.raise_()

    def initialize_layout(self):
        if self.settings.get('design_version') == self.DESIGN_VERSION and self.settings.get('panels'):
            from PyQt6.QtCore import QByteArray
            try:
                self.restoreState(QByteArray.fromHex(self.settings['panels'].encode()))
            except (ValueError, TypeError):
                self.reset_workspace()
        else:
            self.reset_workspace()
        self.polish_tabs()
        self.sync_dock_titles()
        self.canvas.fit()

    def polish_tabs(self):
        for bar in self.findChildren(QTabBar):
            bar.setElideMode(Qt.TextElideMode.ElideNone)
            bar.setExpanding(False)
            bar.setUsesScrollButtons(True)
            bar.setDrawBase(False)

    def reset_workspace(self):
        self.focus_mode = False
        self.workspace_combo.blockSignals(True)
        self.workspace_combo.setCurrentIndex(0)
        self.workspace_combo.blockSignals(False)
        self.arrange_docks()
        self.resizeDocks([self.strip_dock, self.color_dock], [42, 292], Qt.Orientation.Horizontal)
        self.resizeDocks([self.color_dock, self.brush_dock, self.layers_dock], [250, 330, 300], Qt.Orientation.Vertical)
        self.polish_tabs()
        self.sync_dock_titles()

    def toggle_focus(self):
        self.workspace_combo.setCurrentIndex(0 if self.focus_mode else 1)

    def change_workspace(self, index):
        if index == 1 and not self.focus_mode:
            self.canvas.finish_stroke()
            self.pre_focus_state = self.saveState()
            for dock in [self.color_dock, self.nav_dock, self.brush_dock, self.layers_dock, self.strip_dock]:
                dock.hide()
            self.focus_mode = True
        elif index == 0 and self.focus_mode:
            self.restoreState(self.pre_focus_state)
            self.focus_mode = False
            self.polish_tabs()

    # ------------------------------------------------------------ status

    def build_statusbar(self):
        self.statusBar().setSizeGripEnabled(True)
        self.statusBar().setMinimumHeight(24)
        ready = QLabel('●  Pronto')
        ready.setObjectName('readyLabel')
        self.statusBar().addWidget(ready)
        self.shortcuts_label = QLabel('B  Pincel     N  Lápis     P  Caneta     M  Seleção     W  Varinha     G  Balde     Espaço  Mover')
        self.shortcuts_label.setObjectName('muted')
        self.statusBar().addWidget(self.shortcuts_label)
        self.dimensions_label = QLabel()
        self.dimensions_label.setObjectName('muted')
        self.zoom_label = QLabel()
        self.zoom_label.setObjectName('muted')
        self.statusBar().addPermanentWidget(self.dimensions_label)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.zoom_spin = QDoubleSpinBox()
        self.zoom_spin.setRange(2, 1600)
        self.zoom_spin.setDecimals(0)
        self.zoom_spin.setSuffix('%')
        self.numeric(self.zoom_spin, 59)
        self.zoom_spin.valueChanged.connect(lambda value: self.canvas.set_zoom(value / 100))
        self.statusBar().addPermanentWidget(self.zoom_spin)

    # ------------------------------------------------------------- theme

    def apply_theme(self, theme):
        self.theme = self.canvas.theme = theme
        c = PALETTES[theme]
        palette = QPalette()
        for role, key in [(QPalette.ColorRole.Window, 'bg'), (QPalette.ColorRole.WindowText, 'text'),
                          (QPalette.ColorRole.Base, 'field'), (QPalette.ColorRole.AlternateBase, 'panel'),
                          (QPalette.ColorRole.Text, 'text'), (QPalette.ColorRole.Button, 'panel'),
                          (QPalette.ColorRole.ButtonText, 'text'), (QPalette.ColorRole.Highlight, 'accent'),
                          (QPalette.ColorRole.HighlightedText, 'strong'), (QPalette.ColorRole.ToolTipBase, 'panel'),
                          (QPalette.ColorRole.ToolTipText, 'text')]:
            palette.setColor(role, QColor(c[key]))
        self.setPalette(palette)
        self.setStyleSheet(stylesheet(theme))
        self.polish_tabs()
        for tool, action in self.tool_actions.items():
            action.setIcon(icon(TOOL_INFO[tool][4], c['text']))
        for button, name in self.design_icons:
            button.setIcon(icon(name, c['muted']))
        for action, name in getattr(self, 'strip_actions', []):
            action.setIcon(icon(name, c['text']))
        self.close_tab.setIcon(icon('close', c['muted']))
        self.theme_button.setIcon(icon('white-balance-sunny' if theme == 'Escuro' else 'weather-night', c['text']))
        self.appearance_button.setIcon(icon('palette-outline', c['text']))
        self.theme_button.setToolTip('Usar modo claro' if theme == 'Escuro' else 'Usar modo escuro')
        self.setWindowIcon(icon('brush-variant', c['accent']))
        for header in self.dock_headers:
            header.refresh()
        self.refresh_tool_badge()
        self.brush_preview.update()
        self.layer_list.viewport().update()
        self.canvas.update()
        self.navigator.update()
        self.logo.update()
        self.color_chips.update()
        for slot in self.tool_slots:
            slot.update()
        for preset in self.size_presets:
            preset.update()
        apply_titlebar(self, c, theme == 'Escuro')

    def refresh_tool_badge(self):
        tool = self.canvas.tool
        if hasattr(self, 'tool_icon'):
            self.tool_icon.setPixmap(icon(TOOL_INFO[tool][4], PALETTES[self.theme]['accent']).pixmap(18, 18))

    # ---------------------------------------------------------- refresh

    def refresh_design_document(self):
        document = self.canvas.document
        name = Path(document.path).name if document.path else document.name
        marker = ' *' if document.modified else ''
        self.document_title.setText(f'{name} @ {self.canvas.zoom * 100:.0f}% (RGBA / 8){marker}')
        self.document_title.setToolTip(document.path or 'Documento sem título')
        count = len(document.layers)
        self.layer_count_label.setText(f'{count} camada' + ('s' if count != 1 else ''))
        layer = document.layers[document.active]
        self.layer_blend.blockSignals(True)
        self.layer_blend.setCurrentIndex(max(0, self.layer_blend.findData(layer.blend)))
        self.layer_blend.setEnabled(not layer.is_shadow)
        self.layer_blend.blockSignals(False)
        self.layer_alpha_lock.blockSignals(True)
        self.layer_alpha_lock.setChecked(layer.alpha_lock)
        self.layer_alpha_lock.blockSignals(False)
        blocked = self.layer_list.blockSignals(True)
        # Thumbnails are kept by image content: after a stroke only the painted layer is redrawn.
        previous_thumbnails, self.layer_thumbnails = getattr(self, 'layer_thumbnails', {}), {}
        for row in range(self.layer_list.count()):
            item = self.layer_list.item(row)
            layer = document.layers[item.data(Qt.ItemDataRole.UserRole)]
            detail = tr(f"sombra · {STYLE_NAMES.get(layer.shadow.get('style'), '')}" if layer.is_shadow else BLEND_NAMES.get(layer.blend, 'Normal'))
            item.setData(Qt.ItemDataRole.UserRole + 1, {'locked': layer.locked, 'alpha_lock': layer.alpha_lock,
                                                        'opacity': round(layer.opacity * 100), 'detail': detail})
            key = layer.image.cacheKey()
            thumbnail = previous_thumbnails.get(key) or self.layer_thumbnails.get(key)
            if thumbnail is None:
                pixmap = QPixmap(44, 42)
                pixmap.fill(QColor('#ededed'))
                painter = QPainter(pixmap)
                for y in range(0, 42, 6):
                    for x in range(0, 44, 6):
                        if (x // 6 + y // 6) % 2:
                            painter.fillRect(x, y, 6, 6, QColor('#d0d0d0'))
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                image = layer.image.scaled(44, 42, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                painter.drawImage((44 - image.width()) // 2, (42 - image.height()) // 2, image)
                painter.end()
                thumbnail = QIcon(pixmap)
            self.layer_thumbnails[key] = thumbnail
            item.setIcon(thumbnail)
        self.layer_list.blockSignals(blocked)

    def sync_design_view(self):
        self.zoom_spin.blockSignals(True)
        self.zoom_spin.setValue(self.canvas.zoom * 100)
        self.zoom_spin.blockSignals(False)
        document = self.canvas.document
        name = Path(document.path).name if document.path else document.name
        self.document_title.setText(f'{name} @ {self.canvas.zoom * 100:.0f}% (RGBA / 8){" *" if document.modified else ""}')
        self.document_info.setText(f'{document.width} × {document.height} px · {document.dpi} dpi')

    def refresh_brush_design(self):
        if hasattr(self, 'brush_preview'):
            self.brush_preview.update()
            self.brush_size_readout.setText(f'{self.brush_size:.1f} px'.replace('.', ','))
            for preset in self.size_presets:
                preset.update()

    def refresh_color_design(self):
        self.color_chips.update()

    def swap_colors(self):
        old = QColor(self.current_color)
        self.set_color(QColor(self.secondary_color))
        self.secondary_color = old
        self.color_chips.update()

    def change_pressure_design(self):
        self.pressure_profile = self.pressure_combo.currentData()
        self.refresh_brush_design()

    def change_pressure_enabled_design(self, value):
        self.pressure_enabled = value
        self.refresh_brush_design()

    def change_minimum_design(self, value):
        self.minimum_size = value / 100
        self.refresh_brush_design()

    def change_layer_blend(self):
        value = self.layer_blend.currentData()
        self.layer_change(lambda d: setattr(d.layers[d.active], 'blend', value))

    def change_layer_alpha_lock(self, value):
        self.layer_change(lambda d: setattr(d.layers[d.active], 'alpha_lock', bool(value)))

    def background_pixmap(self):
        """Window-sized background (image over the window colour), or None without an image."""
        look = self.appearance
        if not look['background']:
            return None
        return self.background.pixmap(self.size(), look, PALETTES[self.theme]['bg'])

    def paintEvent(self, event):
        pixmap = self.background_pixmap()
        if pixmap is None:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.drawPixmap(event.rect(), pixmap, event.rect())
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'shortcuts_label'):
            self.shortcuts_label.setVisible(self.width() >= 1280)
