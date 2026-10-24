"""Resource libraries and animation/media workflows for the desktop studio."""
import math
import uuid
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDockWidget, QVBoxLayout, QWidget,
    QFormLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QSpinBox)

from animation import TRANSITIONS
import rig
from animation_ui import KeyframeDialog, TagDialog
from timeline_ui import Timeline
from rig_ui import SkeletonPanel, bone_context_menu
from document import Document
from media_dialogs import AudioEditor, ExportDialog, SubtitleEditor
from brush_ui import BrushPanel
from design_widgets import DockHeader
from resource_dialogs import NewDocumentDialog, PalettePanel
from resources import ResourceLibrary
from workbench import WorkbenchUI
from app_paths import DATA_ROOT


class StudioFeatures:
    def setup_features(self):
        root = DATA_ROOT
        try:
            self.library = ResourceLibrary(root / '.studio-library.json' if self.persist else None)
        except (OSError, ValueError, KeyError):
            self.library = ResourceLibrary()
            self.library.path = root / '.studio-library.json' if self.persist else None
        self.tool_brushes = {tool: self.library.preset(tool) for tool in ('brush', 'pencil', 'pen')}
        self.project_identity = id(self.canvas.document)
        self.refreshing_features = False
        self.workspace_combo.addItem('Animação')
        self.brush_panel = BrushPanel(self)
        page = QWidget()
        page.setObjectName('panel')
        body = QVBoxLayout(page)
        body.setContentsMargins(8,8,8,8)
        body.addWidget(self.brush_panel)
        self.brush_tabs.insertTab(0,page,'Pincéis')
        self.brush_tabs.setCurrentIndex(0)
        self.palette_dock, layout = self.dock('Paletas','paletteDockV3')
        self.palette_panel = PalettePanel(self)
        layout.addWidget(self.palette_panel)
        self.tabifyDockWidget(self.color_dock,self.palette_dock)
        self.color_dock.raise_()
        self.skeleton_dock, layout = self.dock('Esqueleto','skeletonDockV1',True)
        self.skeleton_panel = SkeletonPanel(self)
        layout.addWidget(self.skeleton_panel)
        self.skeleton_dock.hide()
        self.canvas.bone_selected.connect(self.skeleton_panel.refresh)
        self.timeline = Timeline(self)
        self.timeline_dock = QDockWidget('Timeline · Animação', self)
        self.timeline_dock.setObjectName('timelineDockV3')
        self.timeline_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.timeline_dock.setWidget(self.timeline)
        timeline_header = DockHeader(self,self.timeline_dock,'Timeline · animação')
        self.timeline_dock.setTitleBarWidget(timeline_header)
        self.dock_headers.append(timeline_header)
        self.timeline_dock.setMinimumHeight(170)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,self.timeline_dock)
        self.timeline_dock.hide()
        self.view_menu.addAction(self.timeline_dock.toggleViewAction())
        resources = self.menuBar().addMenu('Recursos')
        self.action(resources,'Biblioteca de pincéis…',self.brush_library)
        self.action(resources,'Criar pincel…',lambda:(self.brush_library(),self.brush_panel.create()))
        self.action(resources,'Importar pincéis do Photoshop (.abr)…',
                    lambda:(self.brush_library(),self.brush_panel.import_file(kind='abr')))
        self.action(resources,'Paletas de cores',lambda:self.palette_dock.raise_())
        self.action(resources,'Manequim 3D · poses, luz e sombra…',self.pose_studio,'Ctrl+Shift+M')
        animation = self.menuBar().addMenu('Animação')
        self.action(animation,'Abrir modo animação',self.animation_workspace)
        self.action(animation,'Reproduzir / pausar (Enter na tela ou na timeline)',lambda:self.timeline.toggle_play())
        self.action(animation,'Quadro anterior',lambda:self.timeline.step(-1),',')
        self.action(animation,'Próximo quadro',lambda:self.timeline.step(1),'.')
        self.action(animation,'Inserir intermediário (quadro vazio)',self.insert_inbetween,'Alt+I')
        self.action(animation,'Duplicar quadro',lambda:self.timeline.duplicate_range(),'Alt+D')
        self.action(animation,'Copiar célula',lambda:self.timeline.copy_cel())
        self.action(animation,'Colar célula',lambda:self.timeline.paste_cel())
        self.action(animation,'Definir FPS…',self.choose_fps)
        animation.addSeparator()
        self.action(animation,'Novo quadro',lambda:self.new_frame(),'Alt+N')
        self.action(animation,'Novo quadro vazio',lambda:self.new_frame(True),'Alt+B')
        self.action(animation,'Excluir quadro',self.delete_frame)
        self.action(animation,'Duração do quadro…',self.frame_duration)
        self.action(animation,'Propriedades da tag…',self.edit_tag)
        animation.addSeparator()
        self.bone_action = self.tool_actions['bone']
        animation.addAction(self.bone_action)
        self.bone_action.setVisible(False)
        self.action(animation,'Painel do esqueleto',self.bones)
        self.action(animation,'Keyframe da câmera…',lambda:self.motion_key('camera'))
        self.action(animation,'Keyframe de camada / parallax…',lambda:self.motion_key('layer'))
        self.action(animation,'Adicionar transição…',self.transition)
        animation.addSeparator()
        self.action(animation,'Áudio e dublagem…',self.audio_editor)
        self.action(animation,'Legendas e sincronização…',self.subtitle_editor)
        self.action(animation,'Exportar animação…',self.export_media)
        for name,tip,callback in [('palette-outline','Cor',lambda:self.show_panel(self.color_dock)),
                                  ('palette-swatch-outline','Paletas',lambda:self.show_panel(self.palette_dock)),
                                  ('compass-outline','Navegador',lambda:self.show_panel(self.nav_dock)),
                                  ('brush-variant','Pincéis',self.brush_library),
                                  ('layers-outline','Camadas',lambda:self.show_panel(self.layers_dock)),
                                  ('bone','Esqueleto',self.activate_bone),
                                  ('filmstrip','Timeline · animação',self.animation_workspace),
                                  ('human-handsup','Manequim 3D',self.pose_studio),
                                  ('ruler','Réguas',lambda:self.rulers_action.trigger()),
                                  ('grid','Grade',lambda:self.grid_action.trigger())]:
            self.add_strip_button(name,tip,callback)
        self.polish_tabs()

    def brush_library(self):
        self.brush_dock.show()
        self.brush_dock.raise_()
        self.brush_tabs.setCurrentIndex(0)

    def mutate(self, callback):
        self.canvas.finish_stroke()
        self.timeline.stop()
        document = self.canvas.document
        document.checkpoint()
        try:
            callback(document)
        except (ValueError,OSError) as error:
            document.restore(document.undo_stack.pop())
            QMessageBox.warning(self,'Não foi possível concluir',str(error))
            return
        document.changed()
        self.refresh_document()

    def new_document_feature(self, category=None):
        dialog = NewDocumentDialog(self, category)
        if dialog.exec() != QDialog.DialogCode.Accepted or not self.maybe_save():
            return
        document = Document(dialog.width.value(),dialog.height.value())
        document.name = dialog.name.text().strip() or 'Sem título'
        document.dpi = dialog.dpi.value()
        document.paper_visible = dialog.paper.isChecked()
        document.animation_enabled = dialog.animation.isChecked()
        document.frames[0].duration = round(1000/dialog.fps.value())
        document.guides['bleed'], document.guides['safe'] = dialog.bleed.value(), dialog.safe.value()
        self.timeline.stop()
        self.canvas.set_document(document)
        self.remove_recovery()
        if dialog.panels.isChecked():
            self.generate_panels()

    def export_media(self):
        self.canvas.finish_stroke()
        ExportDialog(self).exec()

    def animation_workspace(self):
        if self.workspace_combo.currentIndex()!=2:
            self.workspace_combo.setCurrentIndex(2)
        else:
            self.change_workspace(2)

    def change_workspace(self,index):
        if not hasattr(self,'timeline'):
            return WorkbenchUI.change_workspace(self,index)
        if index==1:
            self.focus_return = 2 if self.timeline_dock.isVisible() else 0
            WorkbenchUI.change_workspace(self,index)
            self.palette_dock.hide()
            self.timeline_dock.hide()
            return
        if self.focus_mode:
            WorkbenchUI.change_workspace(self,0)
        self.timeline.stop()
        if index==2:
            document = self.canvas.document
            if not document.animation_enabled:
                document.checkpoint()
                document.animation_enabled = True
                document.changed()
            self.timeline_dock.show()
            self.bone_action.setVisible(True)
            self.resizeDocks([self.timeline_dock],[210],Qt.Orientation.Vertical)
            self.timeline.refresh()
        else:
            self.timeline_dock.hide()
            self.skeleton_dock.hide()
            self.bone_action.setVisible(False)
            if self.canvas.tool=='bone':
                self.set_tool('brush')
        self.canvas.update()

    def toggle_focus(self):
        self.workspace_combo.setCurrentIndex(getattr(self,'focus_return',0) if self.focus_mode else 1)

    def reset_workspace(self):
        WorkbenchUI.reset_workspace(self)
        if hasattr(self,'palette_dock'):
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.palette_dock)
            self.tabifyDockWidget(self.color_dock,self.palette_dock)
            self.color_dock.raise_()
            self.timeline_dock.hide()
            self.skeleton_dock.hide()
            self.bone_action.setVisible(False)
            self.polish_tabs()

    def refresh_features(self):
        if self.refreshing_features:
            return
        self.refreshing_features = True
        try:
            document = self.canvas.document
            if id(document)!=self.project_identity:
                self.timeline.stop()
                self.project_identity = id(document)
                self.workspace_combo.setCurrentIndex(2 if document.animation_enabled else 0)
                self.change_workspace(self.workspace_combo.currentIndex())
            self.timeline.refresh()
            if self.skeleton_dock.isVisible():
                self.skeleton_panel.refresh()
        finally:
            self.refreshing_features = False

    def cursor_seconds(self):
        return self.canvas.document.frame_start(self.canvas.document.current_frame)

    def new_frame(self,empty=False):
        self.animation_workspace()
        self.mutate(lambda document:document.add_frame(empty))

    def insert_inbetween(self):
        """Empty frame between the current and the next one; onion skin shows both neighbours."""
        self.animation_workspace()
        document = self.canvas.document
        document.onion_skin = True
        document.onion_before, document.onion_after = max(1, document.onion_before), max(1, document.onion_after)
        self.mutate(lambda d: d.add_frame(True))
        self.statusBar().showMessage('Intermediário inserido: desenhe usando os quadros vizinhos no onion skin.', 6000)

    def choose_fps(self):
        document = self.canvas.document
        current = max(1, round(1000 / max(1, document.frames[document.current_frame].duration)))
        fps, accepted = QInputDialog.getInt(self, 'Quadros por segundo', 'FPS de todos os quadros:', current, 1, 60)
        if accepted:
            self.mutate(lambda d: d.set_fps(fps))

    def delete_frame(self):
        self.mutate(lambda document:document.delete_frame())

    def frame_duration(self):
        self.canvas.finish_stroke()
        document = self.canvas.document
        duration,accepted = QInputDialog.getInt(self,'Propriedades do quadro',
            f'Quadro {document.current_frame+1} · duração em milissegundos:',document.frames[document.current_frame].duration,1,600000)
        if accepted:
            self.mutate(lambda d:setattr(d.frames[d.current_frame],'duration',duration))

    def edit_tag(self):
        index = self.timeline.tags.currentData()
        tag = self.canvas.document.scene['tags'][index] if index is not None and index>=0 else None
        dialog = TagDialog(self,tag)
        if dialog.exec():
            def apply(document):
                if tag is None:
                    document.scene['tags'].append(dialog.result_tag())
                else:
                    document.scene['tags'][index] = dialog.result_tag()
            self.mutate(apply)

    def motion_key(self,kind):
        self.animation_workspace()
        dialog = KeyframeDialog(self,kind)
        if dialog.exec():
            self.mutate(lambda document:dialog.apply())

    def activate_bone(self):
        self.animation_workspace()
        self.set_tool('bone')
        self.show_skeleton_panel()
        self.statusBar().showMessage('Escolha um esqueleto pronto no painel ou arraste para criar um osso. '
                                     'Arraste um osso para posar; a pose vira keyframe do quadro atual.',9000)

    def show_skeleton_panel(self):
        if self.skeleton_dock.isHidden():
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.skeleton_dock)
            self.tabifyDockWidget(self.layers_dock,self.skeleton_dock)
            self.skeleton_dock.show()
            self.polish_tabs()
        self.skeleton_dock.raise_()
        self.skeleton_panel.refresh()

    def bones(self):
        self.activate_bone()

    def bone_menu(self,bone,position):
        bone_context_menu(self,bone,position)

    def bind_bone_layer(self,ident,layer_id):
        def apply(document):
            for other in document.scene['bones']:
                if layer_id and other.get('layer')==layer_id:
                    other['layer'] = ''
            rig.find(document,ident)['layer'] = layer_id
        self.mutate(apply)

    def pose_studio(self):
        from pose_ui import PoseStudio
        if getattr(self,'pose_window',None) is None:
            self.pose_window = PoseStudio(self)
        self.pose_window.show()
        self.pose_window.raise_()
        self.pose_window.activateWindow()

    def transition(self):
        self.animation_workspace()
        document = self.canvas.document
        dialog = QDialog(self)
        dialog.setWindowTitle('Adicionar transição')
        form = QFormLayout(dialog)
        start,end = QSpinBox(),QSpinBox()
        for spin,value in [(start,document.current_frame+1),(end,len(document.frames))]:
            spin.setRange(1,len(document.frames))
            spin.setValue(value)
        kind = QComboBox()
        for label,value in TRANSITIONS:
            kind.addItem(label,value)
        form.addRow('Do quadro',start)
        form.addRow('Até o quadro',end)
        form.addRow('Transição',kind)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.mutate(lambda d:d.scene['transitions'].append({'from':min(start.value(),end.value())-1,
                'to':max(start.value(),end.value())-1,'type':kind.currentData()}))

    def extend_to_media(self,document):
        end = max([0.]+[c['start']+c['trim_end']-c['trim_start'] for c in document.scene['audio']]
                  +[c['end'] for c in document.scene['subtitles']])
        extra = math.ceil(end*1000)-document.total_ms
        if extra>0:
            document.frames[-1].duration += extra

    def audio_editor(self):
        self.animation_workspace()
        self.timeline.stop()
        dialog = AudioEditor(self)
        if dialog.exec():
            def apply(document):
                document.scene['audio'],document.assets = dialog.clips,dialog.assets
                self.extend_to_media(document)
            self.mutate(apply)

    def subtitle_editor(self):
        self.animation_workspace()
        self.timeline.stop()
        dialog = SubtitleEditor(self)
        if dialog.exec():
            def apply(document):
                document.scene['subtitles'] = dialog.cues()
                self.extend_to_media(document)
            self.mutate(apply)
