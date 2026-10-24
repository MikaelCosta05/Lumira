"""Skeleton panel: bone tree, binding layers to bones and pose helpers."""
from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QInputDialog, QLabel,
                             QLineEdit, QMenu, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QWidget,
                             QVBoxLayout)

import rig
from i18n import tr


class SkeletonPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        add = QGridLayout()
        for index, (label, kind) in enumerate([('+ Humano', 'human'), ('+ Braço', 'arm'), ('+ Perna', 'leg'), ('+ Cauda', 'tail')]):
            button = QPushButton(label)
            button.setToolTip('Cria o esqueleto pronto no centro da tela. Também pode escolher o modelo na barra '
                              'de opções e arrastar um retângulo com a Bone Tool.')
            button.clicked.connect(lambda checked=False, k=kind: self.add_template(k))
            add.addWidget(button, 0, index)
        layout.addLayout(add)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Osso', 'Camada'])
        self.tree.setColumnWidth(0, 130)
        self.tree.setMinimumHeight(150)
        self.tree.itemSelectionChanged.connect(self.tree_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        layout.addWidget(self.tree, 1)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.editingFinished.connect(self.rename)
        self.layer = QComboBox()
        self.layer.activated.connect(self.bind_layer)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-3600, 3600)
        self.angle.setDecimals(1)
        self.angle.setSuffix('°')
        self.angle.editingFinished.connect(self.set_angle)
        form.addRow('Nome', self.name)
        form.addRow('Camada', self.layer)
        form.addRow('Ângulo no quadro', self.angle)
        layout.addLayout(form)
        grid = QGridLayout()
        for index, (label, tip, callback) in enumerate([
                ('Criar camadas das partes', 'Uma camada vazia, vinculada, para cada osso sem camada', self.create_layers),
                ('Espelhar pose', 'Troca a pose dos lados esquerdo e direito neste quadro', self.mirror),
                ('Copiar quadro anterior', 'Repete neste quadro a pose do quadro anterior', self.copy_previous),
                ('Zerar pose do quadro', 'Volta todos os ossos à posição de repouso neste quadro', self.reset_all),
                ('Zerar osso', 'Volta o osso selecionado ao repouso neste quadro', self.reset_selected),
                ('Excluir osso', 'Exclui o osso selecionado e os ossos filhos', self.delete_selected)]):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        hint = QLabel('Arraste um osso para girar · ponta da mão/pé move o membro (IK) · Alt + arrastar: IK em qualquer '
                      'osso · Shift + arrastar ou círculo da raiz: mover · Ctrl + arrastar da ponta de um osso cria um osso filho.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)

    @property
    def document(self):
        return self.owner.canvas.document

    def selected(self):
        return rig.find(self.document, self.owner.canvas.selected_bone)

    def refresh(self):
        self.updating = True
        document = self.document
        layers = {layer.id: layer.name for layer in document.layers}
        self.tree.clear()
        items = {}
        pending = list(document.scene['bones'])
        while pending:
            progressed = False
            for bone in list(pending):
                parent = bone.get('parent')
                if parent and parent in items or not parent or not rig.find(document, parent):
                    item = QTreeWidgetItem([tr(bone['name']), layers.get(bone.get('layer'), '—')])
                    item.setData(0, Qt.ItemDataRole.UserRole, bone['id'])
                    (items[parent].addChild(item) if parent in items else self.tree.addTopLevelItem(item))
                    items[bone['id']] = item
                    pending.remove(bone)
                    progressed = True
            if not progressed:
                break
        self.tree.expandAll()
        current = items.get(self.owner.canvas.selected_bone)
        if current:
            self.tree.setCurrentItem(current)
        self.layer.clear()
        self.layer.addItem('Sem camada', '')
        for layer in reversed(document.layers):
            self.layer.addItem(layer.name, layer.id)
        bone = self.selected()
        for widget in (self.name, self.layer, self.angle):
            widget.setEnabled(bone is not None)
        if bone:
            self.name.setText(bone['name'])
            self.layer.setCurrentIndex(max(0, self.layer.findData(bone.get('layer', ''))))
            self.angle.setValue(rig.values(bone, document.current_frame)['angle'])
        else:
            self.name.clear()
        self.updating = False

    def tree_selected(self):
        if self.updating:
            return
        item = self.tree.currentItem()
        if item:
            self.owner.canvas.select_bone(item.data(0, Qt.ItemDataRole.UserRole))

    def tree_menu(self, point):
        item = self.tree.itemAt(point)
        bone = rig.find(self.document, item.data(0, Qt.ItemDataRole.UserRole)) if item else None
        if bone:
            self.owner.canvas.select_bone(bone['id'])
            self.owner.bone_menu(bone, self.tree.viewport().mapToGlobal(point))

    def change(self, callback):
        self.owner.mutate(callback)

    def add_template(self, kind):
        self.owner.animation_workspace()
        if self.owner.canvas.tool != 'bone':
            self.owner.set_tool('bone')
        document = self.document
        rect = rig.fit_rect(document, fraction=.8 if kind == 'human' else .45)
        if kind in ('arm', 'tail'):
            width, height = document.width * .6, document.height * .2
            rect = QRectF(document.width / 2 - width / 2, document.height / 2 - height / 2, width, height)
        created = []
        self.change(lambda d: created.extend(rig.add_template(d, kind, rect)))
        if created:
            self.owner.canvas.select_bone(created[0]['id'])

    def rename(self):
        bone = self.selected()
        name = self.name.text().strip()
        if bone and name and name != bone['name'] and not self.updating:
            ident = bone['id']
            self.change(lambda d: rig.find(d, ident).update(name=name))

    def bind_layer(self):
        bone = self.selected()
        if bone and not self.updating:
            self.owner.bind_bone_layer(bone['id'], self.layer.currentData())

    def set_angle(self):
        bone = self.selected()
        if bone and not self.updating:
            ident, value = bone['id'], self.angle.value()
            self.change(lambda d: rig.set_key(rig.find(d, ident), d.current_frame, angle=value))

    def create_layers(self):
        if not self.document.scene['bones']:
            return
        def apply(document):
            existing = {layer.id for layer in document.layers}
            index = document.active
            for bone in document.scene['bones']:
                if bone.get('layer') in existing:
                    continue
                if len(document.layers) >= 64:
                    raise ValueError('Limite de 64 camadas atingido.')
                layer = document.blank_layer(bone['name'])
                index += 1
                document.layers.insert(index, layer)
                bone['layer'] = layer.id
            document.sync_layers()
        self.change(apply)
        self.owner.statusBar().showMessage('Camadas criadas e vinculadas: desenhe cada parte na camada com o mesmo nome.', 7000)

    def mirror(self):
        self.change(lambda d: rig.mirror_pose(d, d.current_frame))

    def copy_previous(self):
        if self.document.current_frame > 0:
            self.change(lambda d: rig.copy_pose(d, d.current_frame - 1, d.current_frame))

    def reset_all(self):
        self.change(lambda d: rig.reset_pose(d, d.current_frame))

    def reset_selected(self):
        bone = self.selected()
        if bone:
            ident = bone['id']
            self.change(lambda d: rig.reset_pose(d, d.current_frame, [rig.find(d, ident)]))

    def delete_selected(self):
        bone = self.selected()
        if not bone:
            return
        count = 1 + len(rig.descendants(self.document, bone['id']))
        if count > 1 and QMessageBox.question(self, 'Excluir osso', f'Excluir “{bone["name"]}” e {count - 1} osso(s) filho(s)?') \
                != QMessageBox.StandardButton.Yes:
            return
        ident = bone['id']
        self.owner.canvas.select_bone(None)
        self.change(lambda d: rig.delete_bone(d, ident))


def bone_context_menu(owner, bone, position):
    menu = QMenu(owner)
    ident = bone['id']
    def rename():
        text, accepted = QInputDialog.getText(owner, 'Renomear osso', 'Nome:', text=bone['name'])
        if accepted and text.strip():
            owner.mutate(lambda d: rig.find(d, ident).update(name=text.strip()))
    menu.addAction('Renomear…', rename)
    menu.addAction('Vincular à camada ativa', lambda: owner.bind_bone_layer(ident, owner.canvas.document.layers[owner.canvas.document.active].id))
    menu.addAction('Desvincular camada', lambda: owner.bind_bone_layer(ident, ''))
    menu.addSeparator()
    menu.addAction('Zerar pose deste osso', lambda: owner.mutate(lambda d: rig.reset_pose(d, d.current_frame, [rig.find(d, ident)])))
    menu.addAction('Excluir osso e filhos', lambda: owner.mutate(lambda d: rig.delete_bone(d, ident)))
    menu.exec(position if isinstance(position, QPoint) else position.toPoint())
