"""Comics workspace: one-click stylized pages, panel selection, lettering, effects and publishing."""
import random
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QGridLayout, QInputDialog, QLabel, QMessageBox,
                             QProgressDialog, QPushButton, QSpinBox, QVBoxLayout, QWidget)

import comics
import selection as sel
from comic_art import BALLOONS
from comic_layouts import STYLE_NAMES, STYLES
from comics_dialogs import (ActionLinesDialog, BalloonDialog, ChapterDialog, CoverDialog, PageNumberDialog,
                            PanelDialog, PrintGuidesDialog, ToneDialog)
from design_widgets import icon
from document import Layer
from themes import PALETTES


class ComicsPanel(QWidget):
    """Dock content: everything for comic pages at hand."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.buttons = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.section('PÁGINA'))
        self.style = QComboBox()
        for label, key in STYLES:
            self.style.addItem(label, key)
        self.direction = QComboBox()
        self.direction.addItem('Leitura ocidental (→)', 'ltr')
        self.direction.addItem('Leitura de mangá (←)', 'rtl')
        self.count = QSpinBox()
        self.count.setRange(0, 12)
        self.count.setSpecialValueText('Quadros: automático')
        self.count.setPrefix('Quadros: ')
        for widget in (self.style, self.direction, self.count):
            layout.addWidget(widget)
        self.generate = self.button('Gerar página estilizada', 'creation', owner.generate_stylized_page,
                                    'Monta quadros estilizados na página (Ctrl+Alt+G). Clique de novo para outra variação.')
        self.generate.setObjectName('primary')
        self.generate.setMinimumHeight(34)
        layout.addWidget(self.generate)
        hint = QLabel('Cada clique sorteia uma variação nova; Ctrl+Z volta à anterior.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(self.grid([
            ('Quadros personalizados…', 'view-quilt-outline', owner.generate_panels, 'Grade ou estilo com todas as opções'),
            ('Selecionar quadro', 'select-group', lambda: owner.set_tool('panel'), 'Clique num quadro para limitar a pintura'),
        ]))
        layout.addWidget(self.section('LETREIRAMENTO'))
        layout.addLayout(self.grid([
            ('Balão de fala', 'chat-outline', lambda: owner.balloon_tool('speech'), 'Clique e arraste até quem fala'),
            ('Pensamento', 'chat-processing-outline', lambda: owner.balloon_tool('thought'), 'Balão de nuvem'),
            ('Grito', 'flash-outline', lambda: owner.balloon_tool('shout'), 'Balão com espinhos'),
            ('Narração', 'format-quote-close-outline', lambda: owner.balloon_tool('caption'), 'Caixa de narração'),
            ('Onomatopeia', 'star-four-points-outline', lambda: owner.balloon_tool('sfx'), 'BOOM! POW! KRAK!'),
            ('Sussurro', 'message-outline', lambda: owner.balloon_tool('whisper'), 'Balão tracejado'),
        ]))
        layout.addWidget(self.section('EFEITOS'))
        layout.addLayout(self.grid([
            ('Linhas de ação…', 'blur-radial', owner.action_lines, 'Foco, velocidade ou explosão no quadro'),
            ('Retícula…', 'dots-grid', owner.screentone, 'Pontos, degradê, linhas ou granulado'),
        ]))
        layout.addWidget(self.section('PUBLICAÇÃO'))
        layout.addLayout(self.grid([
            ('Numerar página…', 'numeric', owner.number_page, 'Número da página no rodapé ou no topo'),
            ('Numerar em lote…', 'book-multiple-outline', owner.number_pages, 'Vários arquivos de uma vez'),
            ('Gerar capítulo…', 'book-open-page-variant-outline', owner.generate_chapter,
             'Várias páginas prontas, cada uma com quadros diferentes'),
            ('Exportar PDF…', 'file-pdf-box', owner.export_chapter_pdf, 'Junta as páginas num PDF'),
            ('Capa…', 'image-frame', owner.create_cover, 'Modelo de capa com título e informações'),
            ('Sangria…', 'crop', owner.print_guides, 'Guias de corte e área segura'),
        ]))
        layout.addStretch()
        comic = owner.canvas.document.scene.get('comic', {})
        self.direction.setCurrentIndex(max(0, self.direction.findData(comic.get('direction', 'ltr'))))

    def section(self, text):
        label = QLabel(text)
        label.setObjectName('section')
        return label

    def button(self, text, name, callback, tooltip):
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda: callback())
        self.buttons.append((button, name))
        return button

    def grid(self, items):
        grid = QGridLayout()
        grid.setSpacing(5)
        for index, (text, name, callback, tooltip) in enumerate(items):
            grid.addWidget(self.button(text, name, callback, tooltip), index // 2, index % 2)
        return grid

    def refresh_icons(self, theme):
        colors = PALETTES[theme]
        for button, name in self.buttons:
            button.setIcon(icon(name, '#ffffff' if button is self.generate else colors['text']))


class ComicFeatures:
    def setup_comics(self):
        self.balloon_kind = 'speech'
        self.balloon_settings = {}
        self.comics_dock, layout = self.dock('Quadrinhos', 'comicsDockV1', True)
        self.comics_panel = ComicsPanel(self)
        layout.addWidget(self.comics_panel)
        self.comics_dock.hide()
        self.add_strip_button('book-open-page-variant-outline', 'Quadrinhos', self.show_comics_panel)
        self.balloon_combo = QComboBox()
        for label, kind in BALLOONS:
            self.balloon_combo.addItem(label, kind)
        self.balloon_combo.currentIndexChanged.connect(lambda: setattr(self, 'balloon_kind', self.balloon_combo.currentData()))
        self.option_groups['balloon'] = self.option_group(QLabel('Tipo'), self.balloon_combo,
                                                          QLabel('Clique no lugar do balão e arraste até quem fala'))
        self.option_groups['comic_panel'] = self.option_group(
            QLabel('Clique num quadro · Shift soma · Alt subtrai'))
        self.build_comics_menu()

    def show_comics_panel(self):
        if self.comics_dock.isHidden():
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.comics_dock)
            self.tabifyDockWidget(self.layers_dock, self.comics_dock)
            self.comics_dock.show()
        self.comics_panel.refresh_icons(self.theme)
        self.comics_dock.raise_()

    def build_comics_menu(self):
        menu = self.menuBar().addMenu('Quadrinhos')
        self.action(menu, 'Nova página de quadrinho…', lambda: self.new_document_feature('Quadrinhos'))
        self.action(menu, 'Gerar página estilizada', self.generate_stylized_page, 'Ctrl+Alt+G')
        self.action(menu, 'Gerar quadros da página…', self.generate_panels)
        self.action(menu, 'Selecionar quadro pelo número…', self.select_panel)
        menu.addAction(self.tool_actions['panel'])
        self.panel_numbers_action = self.action(menu, 'Mostrar números dos quadros', self.toggle_panel_numbers)
        self.panel_numbers_action.setCheckable(True)
        self.panel_numbers_action.setChecked(True)
        menu.addSeparator()
        lettering = menu.addMenu('Balões e letreiramento')
        for label, kind in BALLOONS:
            self.action(lettering, label, lambda checked=False, k=kind: self.balloon_tool(k))
        self.action(menu, 'Linhas de ação…', self.action_lines)
        self.action(menu, 'Retícula…', self.screentone)
        menu.addSeparator()
        self.action(menu, 'Numerar esta página…', self.number_page)
        self.action(menu, 'Numerar páginas em lote…', self.number_pages)
        self.action(menu, 'Gerar capítulo (várias páginas)…', self.generate_chapter)
        self.action(menu, 'Exportar capítulo em PDF…', self.export_chapter_pdf)
        menu.addSeparator()
        self.action(menu, 'Criar capa…', self.create_cover)
        self.action(menu, 'Sangria e área segura…', self.print_guides)
        menu.addSeparator()
        self.action(menu, 'Painel de quadrinhos', self.show_comics_panel)

    def toggle_panel_numbers(self, value):
        self.canvas.show_panel_numbers = bool(value)
        self.canvas.update()

    # ------------------------------------------------------------- panels

    def generate_stylized_page(self):
        """One click: a new stylized panel layout (another variation on every click)."""
        panel = self.comics_panel
        document = self.canvas.document
        style, direction = panel.style.currentData(), panel.direction.currentData()
        try:
            used, shapes, image = comics.stylized_page(document, style, random.random(), direction, panel.count.value())
        except ValueError as error:
            QMessageBox.warning(self, 'Página estilizada', str(error))
            return
        self.mutate(lambda d: comics.apply_panels(d, shapes, image, direction, used))
        self.statusBar().showMessage(f'Página estilizada · {STYLE_NAMES.get(used, used)} · {len(shapes)} quadros. '
                                     'Clique de novo para outra variação (Ctrl+Z desfaz).', 9000)

    def generate_panels(self):
        dialog = PanelDialog(self, self.canvas.document)
        if not dialog.exec():
            return
        image = dialog.render()
        self.mutate(lambda d: comics.apply_panels(d, dialog.shapes, image, dialog.direction(), dialog.style_used,
                                                  dialog.replace.isChecked()))
        self.statusBar().showMessage(f'{len(dialog.shapes)} quadros criados na camada “Quadros” (bloqueada). '
                                     'Desenhe nas camadas abaixo; use Selecionar quadro para limitar a pintura.', 9000)

    def panel_shapes(self):
        shapes = comics.page_shapes(self.canvas.document)
        if not shapes:
            self.statusBar().showMessage('Gere os quadros da página primeiro (Quadrinhos → Gerar página estilizada).', 6000)
        return shapes

    def select_panel_index(self, index, mode='replace'):
        document = self.canvas.document
        path = comics.panel_selection_path(document, index)
        values = sel.alpha(sel.path_mask(path, document.width, document.height, False))
        self.canvas.apply_selection(values, mode, path)
        self.statusBar().showMessage(f'Quadro {index + 1} selecionado: a pintura fica dentro dele.', 4000)

    def select_panel(self):
        shapes = self.panel_shapes()
        if shapes:
            number, accepted = QInputDialog.getInt(self, 'Selecionar quadro', f'Quadro (1–{len(shapes)}):', 1, 1, len(shapes))
            if accepted:
                self.select_panel_index(number - 1)

    def select_panel_at(self, point, mode='replace'):
        if not self.panel_shapes():
            return
        index = comics.panel_at(self.canvas.document, point)
        if index is None:
            if mode == 'replace':
                self.canvas.set_selection(None)
            self.statusBar().showMessage('Nenhum quadro aqui (clique dentro de um quadro).', 4000)
            return
        self.select_panel_index(index, mode)

    # ---------------------------------------------------- lettering/effects

    def add_art_layer(self, name, image, top=False):
        """New layer with `image`; balloons go on top so they can cross panel borders."""
        if len(self.canvas.document.layers) >= 64:
            QMessageBox.warning(self, 'Camadas', 'Limite de 64 camadas atingido.')
            return

        def add(document):
            index = len(document.layers) if top else document.active + 1
            document.layers.insert(index, Layer(name, image, content=True))
            document.active = index
        self.layer_change(add)

    def balloon_tool(self, kind):
        self.balloon_kind = kind
        self.balloon_combo.blockSignals(True)
        self.balloon_combo.setCurrentIndex(max(0, self.balloon_combo.findData(kind)))
        self.balloon_combo.blockSignals(False)
        self.set_tool('balloon')

    def place_balloon(self, center, tip):
        document = self.canvas.document
        dialog = BalloonDialog(self, document, center, tip, self.balloon_kind, self.balloon_settings)
        if not dialog.exec():
            return
        image, _ = dialog.render()
        self.balloon_settings = dialog.settings()
        self.balloon_kind = self.balloon_settings['kind']
        text = dialog.text.toPlainText().strip().replace('\n', ' ')[:24] or '…'
        kind = dialog.kind.currentData()
        if dialog.new_layer.isChecked():
            self.add_art_layer(f'{"Onomatopeia" if kind == "sfx" else "Balão"} · {text}', image, top=True)
            return
        shared = next((i for i, layer in enumerate(document.layers) if layer.name == 'Balões'), None)
        if shared is None:
            self.add_art_layer('Balões', image, top=True)
            return

        def paint(document):
            from PyQt6.QtGui import QPainter
            painter = QPainter(document.layers[shared].image)
            painter.drawImage(0, 0, image)
            painter.end()
            document.layers[shared].content = True
            document.active = shared
        self.mutate(paint)

    def effect_area(self):
        """Selection (e.g. a panel picked with Selecionar quadro) or the whole page."""
        canvas = self.canvas
        if canvas.selection is not None and canvas.selection_path is not None:
            return canvas.selection_path.boundingRect().intersected(canvas.document_rect()), canvas.selection
        if comics.page_shapes(canvas.document):
            self.statusBar().showMessage('Dica: selecione um quadro (ferramenta Quadro) para aplicar só nele.', 6000)
        return canvas.document_rect(), None

    def action_lines(self):
        area, mask = self.effect_area()
        dialog = ActionLinesDialog(self, self.canvas.document, area, mask)
        if dialog.exec():
            self.add_art_layer('Linhas de ação', dialog.render())

    def screentone(self):
        area, mask = self.effect_area()
        dialog = ToneDialog(self, self.canvas.document, area, mask)
        if dialog.exec():
            self.add_art_layer('Retícula', dialog.render())

    # ---------------------------------------------------------- publishing

    def number_page(self):
        dialog = PageNumberDialog(self, self.canvas.document)
        if dialog.exec():
            self.mutate(lambda d: comics.apply_page_number(d, dialog.number.value(), dialog.style()))

    def number_pages(self):
        dialog = PageNumberDialog(self, self.canvas.document, batch=True)
        if not dialog.exec() or not dialog.paths:
            return
        current = self.canvas.document.path
        involved = current and any(Path(p).resolve() == Path(current).resolve() for p in dialog.paths)
        if involved and not self.maybe_save():
            return
        answer = QMessageBox.question(self, 'Numerar páginas',
            f'Gravar a numeração em {len(dialog.paths)} arquivo(s)? Cada projeto recebe/atualiza a camada '
            '“Número da página”; o restante do desenho não é alterado.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            done = comics.batch_number(dialog.paths, dialog.number.value(), dialog.style(), dialog.step.value())
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, 'Numerar páginas', str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if involved:
            from document import Document
            self.canvas.set_document(Document.load(current))
        summary = '\n'.join(f'{Path(path).name}: {number}' for path, number in done[:30])
        QMessageBox.information(self, 'Numerar páginas', f'{len(done)} página(s) numerada(s).\n\n{summary}')

    def progress(self, title, total):
        dialog = QProgressDialog(title, 'Cancelar', 0, total, self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(300)

        def step(done, count):
            dialog.setValue(done)
            QApplication.processEvents()
            if dialog.wasCanceled():
                raise InterruptedError
        return dialog, step

    def generate_chapter(self):
        dialog = ChapterDialog(self, self.canvas.document)
        if not dialog.exec():
            return
        values = dialog.values()
        progress, step = self.progress('Gerando páginas…', values['pages'])
        try:
            paths = comics.chapter(values['folder'], values['pages'], values['width'], values['height'], values['dpi'],
                                   values['style'], values['direction'], values['start'], values['number_style'],
                                   values['prefix'], values['bleed'], values['safe'], progress=step)
        except InterruptedError:
            self.statusBar().showMessage('Geração interrompida; as páginas já criadas ficaram na pasta.', 6000)
            return
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Gerar capítulo', str(error))
            return
        finally:
            progress.close()
        answer = QMessageBox.question(self, 'Gerar capítulo',
                                      f'{len(paths)} página(s) criada(s) em {values["folder"]}.\n\nAbrir a primeira agora?')
        if answer == QMessageBox.StandardButton.Yes and self.maybe_save():
            from document import Document
            self.canvas.set_document(Document.load(paths[0]))

    def export_chapter_pdf(self):
        start = str(Path(self.canvas.document.path).parent) if self.canvas.document.path else ''
        paths, _ = QFileDialog.getOpenFileNames(self, 'Páginas do capítulo', start, 'Projeto Lumira (*.sdp)')
        if not paths:
            return
        output, _ = QFileDialog.getSaveFileName(self, 'Salvar PDF', str(Path(paths[0]).with_name('capitulo.pdf')),
                                                'PDF (*.pdf)')
        if not output:
            return
        progress, step = self.progress('Exportando PDF…', len(paths))
        try:
            count = comics.export_pdf(paths, output, step)
        except InterruptedError:
            self.statusBar().showMessage('Exportação interrompida.', 6000)
            return
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, 'Exportar PDF', str(error))
            return
        finally:
            progress.close()
        self.statusBar().showMessage(f'PDF com {count} página(s) salvo em {output}.', 8000)

    def create_cover(self):
        dialog = CoverDialog(self)
        if dialog.exec() and self.maybe_save():
            self.timeline.stop()
            self.canvas.set_document(dialog.build())
            self.remove_recovery()
            self.statusBar().showMessage('Capa criada. Pinte em “Arte da capa”; título e informações estão em camadas próprias.', 8000)

    def print_guides(self):
        dialog = PrintGuidesDialog(self, self.canvas.document.guides)
        if dialog.exec():
            self.edit_guides(**dialog.values())

