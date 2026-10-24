import copy
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMenu, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from animation import CAMERA_DEFAULTS, interpolate, play_order
from themes import PALETTES


def upsert(track, key):
    track[:] = [value for value in track if value['frame'] != key['frame']]
    track.append(key)
    track.sort(key=lambda k: k['frame'])


class KeyframeDialog(QDialog):
    def __init__(self, owner, kind):
        super().__init__(owner)
        self.owner, self.kind = owner, kind
        document = owner.canvas.document
        frame = document.current_frame
        layer = document.layers[document.active]
        self.setWindowTitle('Keyframe de câmera' if kind == 'camera' else 'Movimento / parallax da camada')
        defaults = dict(CAMERA_DEFAULTS) if kind == 'camera' else {
            'x': 0., 'y': 0., 'angle': 0., 'scale': 1., 'opacity': 1., 'parallax': 1.}
        track = document.scene['camera'] if kind == 'camera' else document.scene['layers'].get(layer.id, [])
        value = interpolate(track, frame, defaults)
        self.layer_id = layer.id
        self.fields = {}
        form = QFormLayout(self)
        form.addRow(QLabel(f'Quadro {frame+1}'+(' · '+layer.name if kind != 'camera' else '')))
        for key, label, lo, hi in [('x','X (px)',-16000,16000), ('y','Y (px)',-16000,16000),
            ('angle','Rotação (°)',-3600,3600), ('zoom','Zoom',.1,8), ('scale','Escala',.01,8),
            ('opacity','Opacidade',0,1), ('parallax','Profundidade parallax',0,4),
            ('shake','Tremor da câmera (px)',0,500)]:
            if key not in defaults:
                continue
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setDecimals(2)
            spin.setValue(value[key])
            form.addRow(label, spin)
            self.fields[key] = spin
        self.easing = QComboBox()
        self.easing.addItems(['Linear', 'Suave'])
        form.addRow('Interpolação', self.easing)
        if kind != 'camera':
            label = QLabel('Parallax: 0 fixa a camada; 1 acompanha a câmera. Valores menores criam fundos mais distantes.')
            label.setWordWrap(True)
            form.addRow(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self):
        document = self.owner.canvas.document
        key = {'frame': document.current_frame, 'easing': 'ease' if self.easing.currentIndex() else 'linear'}
        key.update({name: spin.value() for name, spin in self.fields.items()})
        track = document.scene['camera'] if self.kind == 'camera' else document.scene['layers'].setdefault(self.layer_id, [])
        upsert(track, key)


class TagDialog(QDialog):
    def __init__(self, owner, tag=None):
        super().__init__(owner)
        self.setWindowTitle('Propriedades da tag')
        from PyQt6.QtWidgets import QLineEdit
        self.tag = copy.deepcopy(tag or {'name':'Loop', 'from':0, 'to':len(owner.canvas.document.frames)-1,
                                         'direction':'forward', 'repeat':0, 'color':'#c86d65'})
        form = QFormLayout(self)
        self.name = QLineEdit(self.tag['name'])
        self.start, self.end, self.repeat = QSpinBox(), QSpinBox(), QSpinBox()
        for widget, key in [(self.start, 'from'), (self.end, 'to')]:
            widget.setRange(1, len(owner.canvas.document.frames))
            widget.setValue(self.tag[key]+1)
        self.repeat.setRange(0, 999)
        self.repeat.setSpecialValueText('∞')
        self.repeat.setValue(self.tag['repeat'])
        self.direction = QComboBox()
        for text, value in [('Para frente','forward'), ('Reversa','reverse'), ('Ida e volta','pingpong')]:
            self.direction.addItem(text, value)
        self.direction.setCurrentIndex(self.direction.findData(self.tag['direction']))
        self.color = QPushButton('Escolher cor')
        self.color.clicked.connect(self.pick_color)
        for label, widget in [('Nome',self.name),('Do quadro',self.start),('Até o quadro',self.end),
            ('Direção',self.direction),('Repetições',self.repeat),('Cor',self.color)]:
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.tag['color']), self)
        if color.isValid():
            self.tag['color'] = color.name()

    def result_tag(self):
        self.tag.update(name=self.name.text() or 'Loop', **{'from':min(self.start.value(),self.end.value())-1,
            'to':max(self.start.value(),self.end.value())-1}, direction=self.direction.currentData(), repeat=self.repeat.value())
        return self.tag
