"""Studio Desenho: pintura com foco em traço firme e toque leve."""
import json
import os
import sys
import zipfile
import uuid
from pathlib import Path

from PyQt6.QtCore import QByteArray, QPointF, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QImage, QPainter
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QDialogButtonBox, QFileDialog,
    QComboBox, QFormLayout, QInputDialog, QListWidgetItem, QMainWindow, QMessageBox, QSpinBox,
)

import appearance
import fonts
import themes
import i18n
from canvas import PAINT_TOOLS, TOOL_INFO, TOOLS, Canvas
from document import Document, Layer
from stabilizer import Stabilizer
from themes import PALETTES, stylesheet
from tools_ui import ToolFeatures
from workbench import WorkbenchUI
from features import StudioFeatures
from comics_ui import ComicFeatures
from music_ui import setup_music
from app_paths import DATA_ROOT

ROOT = DATA_ROOT


class MainWindow(ComicFeatures, ToolFeatures, StudioFeatures, WorkbenchUI, QMainWindow):
    def __init__(self, persist=True):
        super().__init__()
        self.persist = persist
        self.settings_path = ROOT / '.studio-settings.json'
        self.recovery_path = ROOT / '.studio-recovery.sdp'
        self.settings = {}
        if persist and self.settings_path.exists():
            try:
                self.settings = json.loads(self.settings_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        self.current_color = QColor('#202127')
        self.brush_size = 5.
        self.brush_opacity = 1.
        self.minimum_size = 0.15
        self.pressure_profile = self.settings.get('pressure', 'Leve')
        if self.pressure_profile not in ('Leve', 'Normal', 'Firme'):
            self.pressure_profile = 'Leve'
        self.pressure_enabled = True
        self.tool_sizes = {'brush': 5., 'pencil': 3., 'pen': 4., 'pixel': 1., 'eraser': 20.}
        self.stabilizer_level = self.settings.get('stabilizer', 'S-4')
        if self.stabilizer_level not in Stabilizer.LEVELS:
            self.stabilizer_level = 'S-4'
        self.theme = self.settings.get('theme', 'Escuro')
        if self.theme not in PALETTES:
            self.theme = 'Escuro'
        fonts.load()
        self.appearance = themes.configure(self.settings.get('appearance', {}))
        fonts.apply(self.appearance['font_family'], self.appearance['font_size'])
        self.background = appearance.Background()
        self.background.load(self.appearance['background'])
        self.language = i18n.set_language(self.settings.get('language', 'pt_BR'))
        self.setObjectName('StudioDesenho')
        self.resize(1440, 900)
        self.setMinimumSize(960, 640)
        self.canvas = Canvas(self)
        self.build_actions()
        self.build_toolbar()
        self.build_docks()
        self.build_statusbar()
        self.canvas.changed.connect(self.refresh_document)
        self.canvas.view_changed.connect(self.refresh_view)
        self.canvas.color_picked.connect(self.set_color)
        self.canvas.message.connect(lambda text: self.statusBar().showMessage(text, 5000))
        self.setup_features()
        self.setup_tools()
        setup_music(self)
        self.build_language_menu()
        self.apply_theme(self.theme)
        self.set_color(self.current_color)
        self.refresh_document()
        if self.settings.get('geometry'):
            try:
                self.restoreGeometry(QByteArray.fromHex(self.settings['geometry'].encode()))
            except (ValueError, TypeError):
                pass
        QTimer.singleShot(0, self.initialize_layout)
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setInterval(60000)
        self.recovery_timer.timeout.connect(self.autosave)
        if persist:
            self.recovery_timer.start()
            if self.recovery_path.exists():
                QTimer.singleShot(100, self.offer_recovery)

    def build_language_menu(self):
        menu = self.view_menu.addMenu('Idioma')
        group = QActionGroup(self)
        self.language_actions = {}
        for code, label in i18n.LANGUAGES:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(code == self.language)
            action.setProperty('i18n_skip', True)
            action.triggered.connect(lambda checked=False, c=code: self.change_language(c))
            group.addAction(action)
            menu.addAction(action)
            self.language_actions[code] = action
        self.language_combo = QComboBox()
        self.language_combo.setProperty('i18n_skip', True)
        self.language_combo.setToolTip('Idioma da interface')
        for code, label in i18n.LANGUAGES:
            self.language_combo.addItem('PT-BR' if code == 'pt_BR' else 'EN', code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        self.language_combo.setObjectName('languageCombo')
        self.language_combo.setFixedWidth(96)
        self.language_combo.currentIndexChanged.connect(lambda: self.change_language(self.language_combo.currentData()))
        self.options_toolbar.addWidget(self.language_combo)

    def change_language(self, code):
        if code == self.language:
            return
        self.language = i18n.set_language(code)
        self.language_actions[self.language].setChecked(True)
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        self.language_combo.blockSignals(False)
        self.set_tool(self.canvas.tool)
        self.refresh_document()
        self.brush_panel.refresh_list()
        self.palette_panel.refresh(self.palette_panel.name())
        self.statusBar().showMessage('Idioma alterado.', 3000)

    def action(self, menu, text, callback, shortcut=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def build_actions(self):
        file_menu = self.menuBar().addMenu('Arquivo')
        self.action(file_menu, 'Novo…', self.new_document, 'Ctrl+N')
        self.action(file_menu, 'Abrir…', self.open_document, 'Ctrl+O')
        file_menu.addSeparator()
        self.action(file_menu, 'Salvar projeto', self.save_document, 'Ctrl+S')
        self.action(file_menu, 'Salvar projeto como…', lambda: self.save_document(True), 'Ctrl+Shift+S')
        self.action(file_menu, 'Exportar…', self.export_png, 'Ctrl+Shift+E')
        file_menu.addSeparator()
        self.action(file_menu, 'Sair', self.close, 'Ctrl+Q')
        self.edit_menu = edit_menu = self.menuBar().addMenu('Editar')
        self.undo_action = self.action(edit_menu, 'Desfazer', self.undo, 'Ctrl+Z')
        self.redo_action = self.action(edit_menu, 'Refazer', self.redo)
        self.redo_action.setShortcuts(['Ctrl+Shift+Z', 'Ctrl+Y'])
        tools = self.menuBar().addMenu('Ferramentas')
        self.tool_actions = {}
        group = QActionGroup(self)
        for index, tool_group in enumerate(TOOLS):
            if index:
                tools.addSeparator()
            for tool, label, _, key, _ in tool_group:
                callback = (lambda checked=False: self.activate_bone()) if tool == 'bone' else \
                    (lambda checked=False, t=tool: self.set_tool(t))
                action = self.action(tools, label, callback, key)
                action.setCheckable(True)
                action.setToolTip(f'{label} ({key})' if key else label)
                group.addAction(action)
                self.tool_actions[tool] = action
        self.tool_actions['brush'].setChecked(True)
        tools.addSeparator()
        self.action(tools, 'Diminuir pincel', lambda: self.size_spin.setValue(self.brush_size / 1.2), '[')
        self.action(tools, 'Aumentar pincel', lambda: self.size_spin.setValue(self.brush_size * 1.2), ']')
        self.canvas_menu = canvas_menu = self.menuBar().addMenu('Tela')
        self.action(canvas_menu, 'Ajustar à janela', self.canvas.fit, 'Ctrl+0')
        self.action(canvas_menu, 'Tamanho real (100%)', lambda: self.canvas.set_zoom(1.), 'Ctrl+1')
        self.action(canvas_menu, 'Girar 15° à esquerda', lambda: self.canvas.set_rotation(self.canvas.rotation - 15))
        self.action(canvas_menu, 'Girar 15° à direita', lambda: self.canvas.set_rotation(self.canvas.rotation + 15))
        self.action(canvas_menu, 'Redefinir rotação', lambda: self.canvas.set_rotation(0.), 'Ctrl+Shift+0')
        layer_menu = self.menuBar().addMenu('Camadas')
        self.action(layer_menu, 'Nova camada', self.add_layer, 'Ctrl+Shift+N')
        self.action(layer_menu, 'Duplicar camada', self.duplicate_layer, 'Ctrl+J')
        self.action(layer_menu, 'Renomear camada…', self.rename_layer)
        self.action(layer_menu, 'Excluir camada', self.remove_layer)
        self.view_menu = self.menuBar().addMenu('Exibir')
        self.action(self.view_menu, 'Alternar claro / escuro', self.toggle_theme)
        self.action(self.view_menu, 'Personalizar aparência…', self.customize_appearance, 'Ctrl+Alt+K')
        self.view_menu.addSeparator()
        self.help_menu = help_menu = self.menuBar().addMenu('Ajuda')
        self.action(help_menu, 'Atalhos e estabilização', self.show_help)

    def build_toolbar(self):
        return WorkbenchUI.build_toolbar(self)

    def initialize_layout(self):
        return WorkbenchUI.initialize_layout(self)

    def dock(self, title, name, scroll=False):
        return WorkbenchUI.dock(self, title, name, scroll)

    def build_docks(self):
        return WorkbenchUI.build_docks(self)

    def build_statusbar(self):
        return WorkbenchUI.build_statusbar(self)

    def apply_theme(self, theme):
        WorkbenchUI.apply_theme(self, theme)
        if hasattr(self, 'brush_panel'):
            self.brush_panel.theme_changed()
        if hasattr(self, 'music_widget'):
            self.music_widget.refresh_icons()
        if hasattr(self, 'comics_panel'):
            self.comics_panel.refresh_icons(theme)

    def toggle_theme(self):
        self.apply_theme('Claro' if self.theme == 'Escuro' else 'Escuro')

    # ------------------------------------------------------------ appearance

    def apply_appearance(self, settings):
        """Restyle the whole interface (colours, background, font, shapes) immediately."""
        self.appearance = themes.configure(settings)
        fonts.apply(self.appearance['font_family'], self.appearance['font_size'])
        if not self.background.load(self.appearance['background']) and self.appearance['background']:
            self.appearance['background'] = ''
        self.apply_theme(self.theme)
        self.update()

    def customize_appearance(self):
        from appearance_ui import AppearanceDialog
        dialog = AppearanceDialog(self)
        if dialog.exec():
            self.save_settings()

    def toggle_guide(self, enabled):
        self.canvas.show_guide = enabled
        self.canvas.update()

    def change_stabilizer(self):
        self.canvas.finish_stroke()
        self.stabilizer_level = self.stab_combo.currentData()
        if hasattr(self, 'stab_description'):
            text = ('Traço direto, acompanhando a mão.' if self.stabilizer_level == '0' else
                    'Traço firme para contornos. O pincel segue a caneta com um pequeno atraso.' if self.stabilizer_level.startswith('S-') else
                    'Suavização progressiva. Aumente o nível para reduzir tremores.')
            self.stab_description.setText(text)

    def set_brush_size(self, value):
        self.brush_size = float(value)
        if hasattr(self, 'size_slider'):
            self.size_slider.blockSignals(True)
            self.size_slider.setValue(min(2000, round(value * 10)))
            self.size_slider.blockSignals(False)
        self.canvas.update()
        self.refresh_brush_design()

    def set_tool(self, tool):
        previous = self.canvas.tool
        if previous in PAINT_TOOLS:
            self.tool_sizes[previous] = self.brush_size
        self.canvas.set_tool(tool)
        self.tool_actions[tool].setChecked(True)
        self.tool_label.setText(TOOL_INFO[tool][2])
        self.refresh_tool_badge()
        if tool in PAINT_TOOLS and tool != previous:
            self.size_spin.setValue(self.tool_sizes.get(tool, self.brush_size))
        self.tool_changed(tool)

    def set_color(self, color, update_wheel=True):
        if not color.isValid():
            return
        color.setAlpha(255)
        self.current_color = color
        self.color_preview.setStyleSheet(f'background: {color.name()}; border: 1px solid #888; border-radius: 4px;')
        self.hex_edit.setText(color.name())
        if update_wheel:
            self.color_wheel.set_color(color)
        self.refresh_color_design()

    def color_from_hex(self):
        color = QColor(self.hex_edit.text())
        self.set_color(color if color.isValid() else self.current_color)

    def choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, 'Escolher cor', QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.set_color(color)

    def recenter(self, point):
        self.canvas.finish_stroke()
        center = QPointF(self.canvas.width() / 2, self.canvas.height() / 2)
        self.canvas.pan += center - self.canvas.transform().map(point)
        self.canvas.update()
        self.refresh_view()

    def refresh_view(self):
        self.zoom_label.setText(f'  {self.canvas.zoom * 100:.0f}%  ·  {self.canvas.rotation:.0f}°  ')
        self.navigator.update()
        self.sync_design_view()

    def refresh_document(self):
        document = self.canvas.document
        name = Path(document.path).name if document.path else document.name
        self.setWindowTitle(f'{name}{" *" if document.modified else ""} — Studio Desenho')
        self.undo_action.setEnabled(bool(document.undo_stack))
        self.redo_action.setEnabled(bool(document.redo_stack))
        self.dimensions_label.setText(f'{document.width} × {document.height} px  ')
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for index in reversed(range(len(document.layers))):
            layer = document.layers[index]
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            self.layer_list.addItem(item)
        self.layer_list.setCurrentRow(len(document.layers) - 1 - document.active)
        self.layer_list.blockSignals(False)
        layer = document.layers[document.active]
        for widget, value in [(self.layer_opacity, round(layer.opacity * 100)),
                              (self.layer_lock, layer.locked), (self.paper_check, document.paper_visible)]:
            widget.blockSignals(True)
            widget.setValue(value) if isinstance(widget, QSpinBox) else widget.setChecked(value)
            widget.blockSignals(False)
        self.navigator.refresh()
        self.refresh_design_document()
        self.canvas.update()
        self.refresh_view()
        self.refresh_features()
        self.refresh_tools()

    def layer_change(self, operation):
        self.canvas.finish_stroke()
        self.canvas.document.checkpoint()
        operation(self.canvas.document)
        self.canvas.document.sync_layers()
        self.canvas.document.changed()
        self.refresh_document()

    def add_layer(self):
        if len(self.canvas.document.layers) >= 64:
            self.statusBar().showMessage('Limite de 64 camadas atingido.', 5000)
            return
        def add(document):
            document.active += 1
            document.layers.insert(document.active, document.blank_layer(i18n.tr(f'Camada {len(document.layers) + 1}')))
        self.layer_change(add)

    def duplicate_layer(self):
        if len(self.canvas.document.layers) >= 64:
            return
        def duplicate(document):
            layer = document.layers[document.active].copy()
            layer.id = uuid.uuid4().hex
            layer.name += ' cópia'
            document.active += 1
            document.layers.insert(document.active, layer)
        self.layer_change(duplicate)

    def remove_layer(self):
        if len(self.canvas.document.layers) == 1:
            self.statusBar().showMessage('Mantenha pelo menos uma camada no projeto.', 4000)
            return
        def remove(document):
            document.layers.pop(document.active)
            document.active = min(document.active, len(document.layers) - 1)
        self.layer_change(remove)

    def move_layer(self, direction):
        document = self.canvas.document
        destination = document.active + direction
        if not 0 <= destination < len(document.layers):
            return
        def move(document):
            document.layers[document.active], document.layers[destination] = document.layers[destination], document.layers[document.active]
            document.active = destination
        self.layer_change(move)

    def rename_layer(self):
        layer = self.canvas.document.layers[self.canvas.document.active]
        text, accepted = QInputDialog.getText(self, 'Renomear camada', 'Nome:', text=layer.name)
        if accepted and text.strip() and text.strip() != layer.name:
            self.layer_change(lambda d: setattr(d.layers[d.active], 'name', text.strip()))

    def select_layer(self, row):
        if row >= 0:
            self.canvas.finish_stroke()
            self.canvas.document.active = self.layer_list.item(row).data(Qt.ItemDataRole.UserRole)
            self.refresh_document()

    def change_layer_visibility(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        visible = item.checkState() == Qt.CheckState.Checked
        self.layer_change(lambda d: setattr(d.layers[index], 'visible', visible))

    def change_layer_opacity(self, value):
        self.layer_change(lambda d: setattr(d.layers[d.active], 'opacity', value / 100))

    def merge_down(self):
        document = self.canvas.document
        index = document.active
        if index == 0:
            self.statusBar().showMessage('Não há camada abaixo para mesclar.', 4000)
            return
        if document.layers[index].is_shadow:
            self.shadow_panel.merge_down()
            return
        def merge(document):
            from document import draw_layer
            upper, lower = document.layers[index], document.layers[index - 1]
            if lower.locked:
                raise ValueError('A camada de baixo está bloqueada.')
            if upper.visible:
                painter = QPainter(lower.image)
                draw_layer(painter, upper)
                painter.end()
            lower.content = lower.content or upper.content
            document.layers.pop(index)
            document.active = index - 1
            document.sync_layers()
        self.mutate(merge)

    def change_layer_lock(self, value):
        self.layer_change(lambda d: setattr(d.layers[d.active], 'locked', value))

    def change_paper(self, value):
        self.layer_change(lambda d: setattr(d, 'paper_visible', value))

    def undo(self):
        self.canvas.finish_stroke()
        if self.canvas.document.undo():
            self.refresh_document()

    def redo(self):
        self.canvas.finish_stroke()
        if self.canvas.document.redo():
            self.refresh_document()

    def maybe_save(self):
        self.canvas.finish_stroke()
        if not self.canvas.document.modified:
            return True
        answer = QMessageBox.question(self, 'Salvar alterações?', 'Salvar as alterações antes de continuar?',
                                       QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_document()
        return answer == QMessageBox.StandardButton.Discard

    def new_document(self):
        return self.new_document_feature()

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Abrir desenho', '',
                                             'Desenhos (*.sdp *.png *.jpg *.jpeg *.webp *.bmp);;Todos os arquivos (*)')
        if not path or not self.maybe_save():
            return
        try:
            if path.lower().endswith('.sdp'):
                document = Document.load(path)
            else:
                image = QImage(path)
                if image.isNull() or image.width() * image.height() > 24_000_000 or max(image.width(), image.height()) > 8192:
                    raise ValueError('Imagem inválida ou grande demais para esta versão.')
                document = Document(image.width(), image.height())
                document.layers = [Layer(Path(path).stem, image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied), content=True)]
            self.canvas.set_document(document)
            self.remove_recovery()
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, 'Não foi possível abrir', str(error))

    def save_document(self, save_as=False):
        self.canvas.finish_stroke()
        path = self.canvas.document.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Salvar projeto com camadas', path or 'Meu desenho.sdp', 'Projeto Studio (*.sdp)')
            if not path:
                return False
            if not path.lower().endswith('.sdp'):
                path += '.sdp'
        try:
            self.canvas.document.save(path)
            self.remove_recovery()
            self.refresh_document()
            self.statusBar().showMessage('Projeto salvo com camadas.', 4000)
            return True
        except OSError as error:
            QMessageBox.warning(self, 'Falha ao salvar', str(error))
            return False

    def export_png(self):
        return self.export_media()

    def autosave(self):
        if self.canvas.document.modified and not self.canvas.drawing:
            try:
                self.canvas.document.save(self.recovery_path, mark_saved=False)
            except OSError:
                self.statusBar().showMessage('Não foi possível gravar a recuperação automática. Salve o projeto.', 5000)

    def remove_recovery(self):
        if self.persist:
            try:
                self.recovery_path.unlink(missing_ok=True)
            except OSError:
                pass

    def offer_recovery(self):
        answer = QMessageBox.question(self, 'Recuperar desenho', 'Foi encontrado um desenho de uma sessão anterior. Deseja recuperá-lo?')
        if answer == QMessageBox.StandardButton.Yes:
            try:
                document = Document.load(self.recovery_path)
                document.path = None
                document.changed()
                self.canvas.set_document(document)
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
                QMessageBox.warning(self, 'Recuperação', 'Não foi possível ler a cópia de recuperação.')
        else:
            self.remove_recovery()

    def show_help(self):
        QMessageBox.information(self, 'Traço e atalhos',
            'ESTABILIZADOR\n0: livre. 1–15: suavização gradual. S-1–S-7: firme para contornos.\n'
            'Experimente S-4; aumente se quiser mais firmeza ou diminua para acompanhar a mão mais de perto.\n'
            'Ao levantar a caneta, o trecho pendente é concluído.\n\n'
            'PRESSÃO\nToque leve responde com pouca força, mantendo variação de espessura.\n'
            'Pressão e estabilização são independentes. O mouse usa espessura constante.\n\n'
            'FERRAMENTAS\nB: pincel · N: lápis · P: caneta · Shift+N: pixel art · E: borracha · G: balde · I: conta-gotas\n'
            'V: mover pixels · M / Shift+M: seleção retangular / elíptica · L: laço · W: varinha mágica\n'
            'U: régua paralela · Shift+U: perspectiva · H: mover tela · R: girar vista\n\n'
            'SELEÇÃO\nShift adiciona · Alt subtrai · Shift+Alt intersecta · Ctrl mantém proporção\n'
            'Ctrl+A: tudo · Ctrl+D: desmarcar · Ctrl+Shift+I: inverter · Delete: limpar · Esc: desmarcar\n'
            'Ctrl+C / Ctrl+X / Ctrl+V: copiar, recortar, colar como camada · Ctrl+] / Ctrl+[: girar 90°\n\n'
            'GUIAS\nCtrl+R: réguas · Ctrl+\': grade · Ctrl+;: ajustar traço às guias\n'
            'Shift + clique com pincel: reta a partir do último traço\n\n'
            'ATALHOS\nCtrl + clique: pegar cor · Espaço + arrastar: mover · Roda: zoom\n'
            '[ / ]: tamanho · Ctrl+0: ajustar · Ctrl+1: 100% · Ctrl+Shift+0: desfazer rotação\n'
            'Ctrl+Z: desfazer · Ctrl+Shift+Z: refazer · Ctrl+S: salvar projeto\n\n'
            'Esta versão tem um estabilizador próprio, inspirado no controle simples do SAI.')

    def closeEvent(self, event):
        self.timeline.stop()
        if not self.maybe_save():
            event.ignore()
            return
        self.music.stop()
        if getattr(self, 'pose_window', None) is not None:
            self.pose_window.close()
        self.recovery_timer.stop()
        self.remove_recovery()
        self.save_settings()
        event.accept()

    def keep_background(self):
        """Copy the chosen background image next to the settings, so moving the original is harmless."""
        path = self.appearance['background']
        own = ROOT / '.studio-background.png'
        if not path or Path(path) == own or self.background.source is None:
            return
        if self.background.source.save(str(own), 'PNG'):
            self.appearance['background'] = self.background.path = str(own)

    def save_settings(self):
        if self.persist:
            self.keep_background()
            try:
                self.settings_path.write_text(json.dumps({
                    'theme': self.theme, 'pressure': self.pressure_profile, 'stabilizer': self.stabilizer_level,
                    'geometry': bytes(self.saveGeometry().toHex()).decode(),
                    'panels': bytes((self.pre_focus_state if self.focus_mode else self.saveState()).toHex()).decode(),
                    'design_version': self.DESIGN_VERSION,
                    'rulers': self.canvas.show_rulers, 'grid': self.canvas.show_grid,
                    'grid_size': self.canvas.grid_size,
                    'music': self.music_action.isChecked(), 'music_any': self.music_any_action.isChecked(),
                    'language': self.language, 'appearance': self.appearance,
                }, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError:
                pass


def run(persist=True, ready=None):
    """Start the studio and return the exit code once every window is closed."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('Studio Desenho')
    window = MainWindow(persist)
    window.show()
    import brush_engine
    brush_engine.warm_up()
    if ready is not None:
        QTimer.singleShot(0, lambda: ready(window))
    return app.exec()


if __name__ == '__main__':
    code = run()
    # Windows are closed and settings saved by now. Skip interpreter finalisation:
    # destroying Qt and OpenGL objects in arbitrary order there crashes the graphics
    # driver, and the operating system frees GPU memory when the process ends.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    os._exit(code)
