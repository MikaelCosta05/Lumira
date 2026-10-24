"""Animation timeline in the spirit of Aseprite: a painted frame grid with transport controls.

Rows are layers (top layer first) plus camera, bone, audio and subtitle tracks.
Click a cell to pick frame and layer, drag on the ruler to scrub, Ctrl + drag a
frame number to move that frame, Shift + click to select a range, double-click a
frame number to change its duration, right-click for every frame operation.
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QAbstractScrollArea, QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu,
                             QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from animation import play_order
from design_widgets import icon
from i18n import tr
from themes import PALETTES

NAME_WIDTH = 176
TAG_HEIGHT = 16
RULER_HEIGHT = 24
ROW_HEIGHT = 24


class TimelineView(QAbstractScrollArea):
    """Painted grid of frames × tracks."""
    frame_clicked = pyqtSignal(int)

    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline
        self.owner = timeline.owner
        self.cell = 30
        self.rows = []
        self.selection = None          # (start, end) frame range
        self.drag = None
        self.hover = None
        self.peaks = {}
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.setMinimumHeight(110)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def doc(self):
        return self.owner.canvas.document

    # -------------------------------------------------------------- layout
    def build_rows(self):
        document = self.doc
        rows = [('layer', index) for index in reversed(range(len(document.layers)))]
        rows.append(('camera', None))
        if document.scene['bones']:
            rows.append(('bones', None))
        rows += [('audio', index) for index in range(len(document.scene['audio']))]
        if document.scene['subtitles']:
            rows.append(('subtitles', None))
        self.rows = rows
        self.update_scrollbars()

    def header_height(self):
        return TAG_HEIGHT + RULER_HEIGHT

    def update_scrollbars(self):
        width = len(self.doc.frames) * self.cell + 40
        height = len(self.rows) * ROW_HEIGHT + 8
        visible_w = max(1, self.viewport().width() - NAME_WIDTH)
        visible_h = max(1, self.viewport().height() - self.header_height())
        self.horizontalScrollBar().setRange(0, max(0, width - visible_w))
        self.horizontalScrollBar().setPageStep(visible_w)
        self.verticalScrollBar().setRange(0, max(0, height - visible_h))
        self.verticalScrollBar().setPageStep(visible_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_scrollbars()

    def frame_x(self, index):
        return NAME_WIDTH + index * self.cell - self.horizontalScrollBar().value()

    def row_y(self, row):
        return self.header_height() + row * ROW_HEIGHT - self.verticalScrollBar().value()

    def frame_at(self, x):
        index = int((x - NAME_WIDTH + self.horizontalScrollBar().value()) // self.cell)
        return max(0, min(len(self.doc.frames) - 1, index))

    def row_at(self, y):
        row = int((y - self.header_height() + self.verticalScrollBar().value()) // ROW_HEIGHT)
        return row if 0 <= row < len(self.rows) else None

    def time_x(self, seconds):
        document = self.doc
        ms = seconds * 1000
        for index, frame in enumerate(document.frames):
            if ms < frame.duration:
                return self.frame_x(index) + ms / frame.duration * self.cell
            ms -= frame.duration
        return self.frame_x(len(document.frames))

    def ensure_visible(self, index):
        x = index * self.cell
        bar = self.horizontalScrollBar()
        visible = self.viewport().width() - NAME_WIDTH
        if x < bar.value():
            bar.setValue(x)
        elif x + self.cell > bar.value() + visible:
            bar.setValue(x + self.cell - visible)

    # ------------------------------------------------------------ painting
    def paintEvent(self, event):
        document = self.doc
        c = PALETTES[self.owner.theme]
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.viewport().width(), self.viewport().height()
        painter.fillRect(self.viewport().rect(), QColor(c['panel']))
        current = document.current_frame
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        first = max(0, self.frame_at(NAME_WIDTH))
        last = min(len(document.frames) - 1, self.frame_at(width) + 1)
        # grid background, onion range and selection
        grid_top = self.header_height()
        painter.save()
        painter.setClipRect(QRectF(NAME_WIDTH, 0, width - NAME_WIDTH, height))
        if document.onion_skin:
            for offset, color in [(-k, c['danger']) for k in range(1, document.onion_before + 1)] + \
                                 [(k, c['accent']) for k in range(1, document.onion_after + 1)]:
                index = current + offset
                if 0 <= index < len(document.frames):
                    tint = QColor(color)
                    tint.setAlpha(26)
                    painter.fillRect(QRectF(self.frame_x(index), TAG_HEIGHT, self.cell, height), tint)
        if self.selection:
            start, end = sorted(self.selection)
            tint = QColor(c['accent'])
            tint.setAlpha(40)
            painter.fillRect(QRectF(self.frame_x(start), TAG_HEIGHT, (end - start + 1) * self.cell, height), tint)
        column = QColor(c['selected'])
        painter.fillRect(QRectF(self.frame_x(current), TAG_HEIGHT, self.cell, height), column)
        painter.setPen(QPen(QColor(c['border']), 1))
        for index in range(first, last + 2):
            x = self.frame_x(index)
            painter.drawLine(QPointF(x, grid_top), QPointF(x, height))
        for row in range(len(self.rows) + 1):
            y = self.row_y(row)
            if y >= grid_top:
                painter.drawLine(QPointF(NAME_WIDTH, y), QPointF(width, y))
        # tags band
        for tag in document.scene['tags']:
            x0, x1 = self.frame_x(tag['from']), self.frame_x(tag['to'] + 1)
            rect = QRectF(x0 + 2, 2, x1 - x0 - 4, TAG_HEIGHT - 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tag.get('color', c['accent'])))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor('white'))
            painter.drawText(rect.adjusted(5, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(tag['name'], Qt.TextElideMode.ElideRight, int(rect.width()) - 8))
        # ruler
        step = 1 if self.cell >= 22 else 5 if self.cell >= 10 else 10
        for index in range(first, last + 1):
            x = self.frame_x(index)
            rect = QRectF(x, TAG_HEIGHT, self.cell, RULER_HEIGHT)
            if index == current:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c['accent']))
                painter.drawRoundedRect(rect.adjusted(2, 3, -2, -3), 5, 5)
            if index == current or (index + 1) % step == 0 or index == 0:
                painter.setPen(QColor('#ffffff' if index == current else c['muted']))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(index + 1))
            if document.frames[index].duration != document.frames[0].duration and self.cell >= 22:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c['ok']))
                painter.drawEllipse(QPointF(x + self.cell - 5, TAG_HEIGHT + 5), 2, 2)
        painter.restore()
        # cells
        painter.save()
        painter.setClipRect(QRectF(NAME_WIDTH, grid_top, width - NAME_WIDTH, height - grid_top))
        for row, (kind, value) in enumerate(self.rows):
            y = self.row_y(row)
            if y + ROW_HEIGHT < grid_top or y > height:
                continue
            middle = y + ROW_HEIGHT / 2
            if kind == 'layer':
                layer_index = value
                active = layer_index == document.active
                for index in range(first, last + 1):
                    layers = document.frames[index].layers
                    if layer_index >= len(layers):
                        continue
                    cx = self.frame_x(index) + self.cell / 2
                    if active and index == current:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor(c['accent']))
                        painter.drawRoundedRect(QRectF(self.frame_x(index) + 2, y + 2, self.cell - 4, ROW_HEIGHT - 4), 5, 5)
                    filled = layers[layer_index].content
                    color = QColor('#ffffff' if active and index == current else c['text'] if filled else c['muted'])
                    painter.setPen(QPen(color, 1.4))
                    painter.setBrush(color if filled else Qt.BrushStyle.NoBrush)
                    radius = min(5., self.cell / 5)
                    painter.drawEllipse(QPointF(cx, middle), radius, radius)
                    if not document.layers[layer_index].visible:
                        painter.setPen(QPen(QColor(c['muted']), 1))
                        painter.drawLine(QPointF(cx - radius - 2, middle + radius + 2), QPointF(cx + radius + 2, middle - radius - 2))
            elif kind in ('camera', 'bones'):
                keys = document.scene['camera'] if kind == 'camera' else [k for b in document.scene['bones'] for k in b.get('keys', [])]
                frames = {k['frame'] for k in keys}
                for index in frames:
                    if first <= index <= last:
                        cx = self.frame_x(index) + self.cell / 2
                        diamond = QPainterPath()
                        size = min(5.5, self.cell / 4.5)
                        diamond.moveTo(cx, middle - size)
                        diamond.lineTo(cx + size, middle)
                        diamond.lineTo(cx, middle + size)
                        diamond.lineTo(cx - size, middle)
                        diamond.closeSubpath()
                        painter.fillPath(diamond, QColor('#e8b64c' if kind == 'camera' else '#9b8cf0'))
            elif kind == 'audio':
                clip = document.scene['audio'][value]
                x0 = self.time_x(clip['start'])
                x1 = self.time_x(clip['start'] + clip['trim_end'] - clip.get('trim_start', 0))
                rect = QRectF(x0, y + 3, max(2., x1 - x0), ROW_HEIGHT - 6)
                tint = QColor(c['accent'])
                tint.setAlpha(70 if not clip.get('muted') else 25)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tint)
                painter.drawRoundedRect(rect, 4, 4)
                peaks = self.clip_peaks(clip)
                if peaks is not None and rect.width() > 4:
                    painter.setPen(QPen(QColor(c['accent']), 1))
                    count = len(peaks)
                    for px in range(int(rect.width())):
                        peak = peaks[min(count - 1, int(px / rect.width() * count))]
                        h = peak * (rect.height() / 2 - 1)
                        painter.drawLine(QPointF(rect.x() + px, rect.center().y() - h), QPointF(rect.x() + px, rect.center().y() + h))
            elif kind == 'subtitles':
                for cue in document.scene['subtitles']:
                    x0, x1 = self.time_x(cue['start']), self.time_x(cue['end'])
                    rect = QRectF(x0, y + 4, max(2., x1 - x0), ROW_HEIGHT - 8)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(c['hover']))
                    painter.drawRoundedRect(rect, 4, 4)
                    painter.setPen(QColor(c['text']))
                    painter.drawText(rect.adjusted(4, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter,
                                     metrics.elidedText(cue['text'], Qt.TextElideMode.ElideRight, int(rect.width()) - 6))
        if self.drag and self.drag[0] == 'move' and self.drag[2] is not None:
            x = self.frame_x(self.drag[2] + (1 if self.drag[2] > self.drag[1] else 0))
            painter.setPen(QPen(QColor(c['ok']), 3))
            painter.drawLine(QPointF(x, TAG_HEIGHT), QPointF(x, height))
        painter.restore()
        # playhead line
        x = self.frame_x(current) + self.cell / 2
        if x >= NAME_WIDTH:
            painter.setPen(QPen(QColor(c['accent']), 1.2))
            painter.drawLine(QPointF(x, grid_top), QPointF(x, height))
        # names column
        painter.fillRect(QRectF(0, 0, NAME_WIDTH, height), QColor(c['panel']))
        painter.setPen(QPen(QColor(c['border']), 1))
        painter.drawLine(QPointF(NAME_WIDTH - .5, 0), QPointF(NAME_WIDTH - .5, height))
        painter.setPen(QColor(c['muted']))
        painter.drawText(QRectF(10, TAG_HEIGHT, NAME_WIDTH - 20, RULER_HEIGHT), Qt.AlignmentFlag.AlignVCenter,
                         f"{tr('Quadro')} {current + 1}/{len(document.frames)} · {document.frames[current].duration} ms")
        painter.save()
        painter.setClipRect(QRectF(0, grid_top, NAME_WIDTH, height - grid_top))
        for row, (kind, value) in enumerate(self.rows):
            y = self.row_y(row)
            rect = QRectF(0, y, NAME_WIDTH, ROW_HEIGHT)
            if kind == 'layer':
                layer = document.layers[value]
                if value == document.active:
                    painter.fillRect(rect.adjusted(4, 2, -4, -2), QColor(c['selected']))
                icon('eye-outline' if layer.visible else 'eye-off-outline', c['text'] if layer.visible else c['muted']).paint(
                    painter, 8, int(y) + 4, 16, 16)
                icon('lock-outline' if layer.locked else 'lock-open-variant-outline', c['muted'] if layer.locked else c['border']).paint(
                    painter, 28, int(y) + 5, 14, 14)
                name = layer.name + (' ◐' if layer.is_shadow else '')
                painter.setPen(QColor(c['strong'] if value == document.active else c['text']))
                painter.drawText(rect.adjusted(48, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter,
                                 metrics.elidedText(name, Qt.TextElideMode.ElideRight, NAME_WIDTH - 56))
            else:
                names = {'camera': ('video-outline', tr('Câmera')), 'bones': ('bone', tr('Ossos')),
                         'subtitles': ('subtitles-outline', tr('Legendas'))}
                if kind == 'audio':
                    glyph, label = 'music-note', document.scene['audio'][value]['name']
                else:
                    glyph, label = names[kind]
                icon(glyph, c['muted']).paint(painter, 10, int(y) + 4, 16, 16)
                painter.setPen(QColor(c['muted']))
                painter.drawText(rect.adjusted(34, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter,
                                 metrics.elidedText(label, Qt.TextElideMode.ElideRight, NAME_WIDTH - 42))
        painter.restore()

    def clip_peaks(self, clip):
        key = (clip['asset'], clip.get('trim_start', 0), clip['trim_end'])
        if key not in self.peaks:
            data = self.doc.assets.get(clip['asset'])
            if data is None:
                return None
            try:
                from media import RATE, audio_array
                samples = np.abs(audio_array(data)).mean(axis=1)
                start, end = int(clip.get('trim_start', 0) * RATE), int(clip['trim_end'] * RATE)
                part = samples[start:max(start + 1, end)]
                buckets = np.array_split(part, min(400, max(1, len(part))))
                peaks = np.array([b.max() if len(b) else 0 for b in buckets])
                self.peaks[key] = peaks / max(1e-6, peaks.max())
            except Exception:  # unreadable audio just shows a plain bar
                self.peaks[key] = None
        return self.peaks[key]

    # --------------------------------------------------------- interaction
    def mousePressEvent(self, event):
        position = event.position()
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self.context_menu(position)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if position.x() < NAME_WIDTH:
            row = self.row_at(position.y())
            if row is not None and self.rows[row][0] == 'layer':
                index = self.rows[row][1]
                if position.x() < 26:
                    self.owner.layer_change(lambda d: setattr(d.layers[index], 'visible', not d.layers[index].visible))
                elif position.x() < 46:
                    self.owner.layer_change(lambda d: setattr(d.layers[index], 'locked', not d.layers[index].locked))
                else:
                    self.timeline.select(self.doc.current_frame, layer=index)
            return
        frame = self.frame_at(position.x())
        if position.y() < self.header_height():
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.drag = ('move', frame, None)
            elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                anchor = self.selection[0] if self.selection else self.doc.current_frame
                self.selection = (anchor, frame)
                self.viewport().update()
                return
            else:
                self.selection = None
                self.drag = ('scrub', frame)
                self.timeline.select(frame)
            return
        row = self.row_at(position.y())
        layer = self.rows[row][1] if row is not None and self.rows[row][0] == 'layer' else None
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            anchor = self.selection[0] if self.selection else self.doc.current_frame
            self.selection = (anchor, frame)
            self.viewport().update()
            return
        self.selection = None
        self.drag = ('scrub', frame)
        self.timeline.select(frame, layer=layer)

    def mouseMoveEvent(self, event):
        position = event.position()
        frame = self.frame_at(position.x())
        if self.drag and self.drag[0] == 'scrub' and frame != self.doc.current_frame:
            self.timeline.select(frame)
        elif self.drag and self.drag[0] == 'move':
            self.drag = ('move', self.drag[1], frame)
            self.viewport().update()
        if position.x() >= NAME_WIDTH and position.y() < self.header_height():
            duration = self.doc.frames[frame].duration
            self.setToolTip(f"{tr('Quadro')} {frame + 1} · {duration} ms\n"
                            + tr('Arraste: navegar · Ctrl + arrastar: mover quadro · Shift + clique: selecionar trecho · '
                                 'duplo clique: duração'))
        else:
            self.setToolTip('')

    def mouseReleaseEvent(self, event):
        drag, self.drag = self.drag, None
        if drag and drag[0] == 'move' and drag[2] is not None and drag[2] != drag[1]:
            source, target = drag[1], drag[2]
            self.owner.mutate(lambda d: d.move_frame(source, target))
        self.viewport().update()

    def mouseDoubleClickEvent(self, event):
        position = event.position()
        if position.x() < NAME_WIDTH:
            row = self.row_at(position.y())
            if row is not None and self.rows[row][0] == 'layer':
                self.owner.rename_layer()
        elif position.y() < self.header_height():
            self.owner.frame_duration()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.timeline.set_zoom(self.cell + (4 if delta > 0 else -4))
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta)
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.timeline.toggle_play()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Comma):
            self.timeline.step(-1)
        elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Period):
            self.timeline.step(1)
        elif event.key() == Qt.Key.Key_Delete:
            self.timeline.delete_range()
        else:
            super().keyPressEvent(event)

    def selected_range(self):
        if self.selection:
            return tuple(sorted(self.selection))
        return self.doc.current_frame, self.doc.current_frame

    def context_menu(self, position):
        frame = self.frame_at(position.x())
        if not self.selection or not (min(self.selection) <= frame <= max(self.selection)):
            self.selection = None
            if position.x() >= NAME_WIDTH:
                self.timeline.select(frame)
        self.timeline.frame_menu().exec(self.viewport().mapToGlobal(position.toPoint()))


class Timeline(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.playing = False
        self.tag = None
        self.order, self.position, self.repeats = [0], 0, 0
        self.clipboard = None
        self.play_timer = QTimer(self)
        self.play_timer.setSingleShot(True)
        self.play_timer.timeout.connect(self.advance)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.buttons = {}
        for key, glyph, tip, callback in [
                ('first', 'skip-previous', 'Primeiro quadro', lambda: self.select(0)),
                ('previous', 'chevron-left', 'Quadro anterior (,)', lambda: self.step(-1)),
                ('play', 'play', 'Reproduzir / pausar (Enter)', self.toggle_play),
                ('next', 'chevron-right', 'Próximo quadro (.)', lambda: self.step(1)),
                ('last', 'skip-next', 'Último quadro', lambda: self.select(len(self.doc.frames) - 1))]:
            button = owner.icon_button(glyph, tip, callback)
            bar.addWidget(button)
            self.buttons[key] = button
        self.loop = owner.icon_button('repeat', 'Repetir em loop', lambda: None)
        self.loop.setCheckable(True)
        self.loop.setChecked(True)
        bar.addWidget(self.loop)
        bar.addSpacing(8)
        self.tags = QComboBox()
        self.tags.setMinimumWidth(130)
        self.tags.setToolTip('Trecho reproduzido')
        bar.addWidget(self.tags)
        label = QLabel('FPS')
        label.setObjectName('muted')
        bar.addWidget(label)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setToolTip('Quadros por segundo (define a duração de todos os quadros)')
        owner.numeric(self.fps, 42)
        self.fps.editingFinished.connect(self.change_fps)
        bar.addWidget(self.fps)
        bar.addSpacing(8)
        self.onion = QCheckBox('Onion skin')
        self.onion.toggled.connect(self.toggle_onion)
        bar.addWidget(self.onion)
        self.onion_before, self.onion_after = QSpinBox(), QSpinBox()
        for spin, tip in ((self.onion_before, 'Quadros anteriores visíveis'), (self.onion_after, 'Quadros seguintes visíveis')):
            spin.setRange(0, 5)
            spin.setToolTip(tip)
            owner.numeric(spin, 30)
            spin.valueChanged.connect(self.change_onion)
        bar.addWidget(self.onion_before)
        bar.addWidget(self.onion_after)
        self.onion_opacity = QSlider(Qt.Orientation.Horizontal)
        self.onion_opacity.setRange(5, 80)
        self.onion_opacity.setFixedWidth(70)
        self.onion_opacity.setToolTip('Opacidade do onion skin')
        self.onion_opacity.valueChanged.connect(self.change_onion)
        bar.addWidget(self.onion_opacity)
        bar.addStretch()
        self.time_label = QLabel()
        self.time_label.setObjectName('muted')
        bar.addWidget(self.time_label)
        bar.addSpacing(6)
        for glyph, tip, callback in [
                ('plus-box-outline', 'Novo quadro (cópia) · Alt+N', lambda: owner.new_frame()),
                ('checkbox-blank-outline', 'Novo quadro vazio · Alt+B', lambda: owner.new_frame(True)),
                ('content-duplicate', 'Duplicar quadros selecionados', self.duplicate_range),
                ('delete-outline', 'Excluir quadros selecionados', self.delete_range),
                ('timer-outline', 'Duração do quadro', owner.frame_duration),
                ('tag-outline', 'Criar / editar tag', owner.edit_tag),
                ('key-outline', 'Keyframe da camada / parallax', lambda: owner.motion_key('layer')),
                ('video-outline', 'Keyframe da câmera', lambda: owner.motion_key('camera'))]:
            bar.addWidget(owner.icon_button(glyph, tip, callback))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(12, 64)
        self.zoom.setValue(30)
        self.zoom.setFixedWidth(70)
        self.zoom.setToolTip('Largura dos quadros (Ctrl + roda)')
        self.zoom.valueChanged.connect(self.set_zoom)
        bar.addWidget(self.zoom)
        layout.addLayout(bar)
        self.view = TimelineView(self)
        layout.addWidget(self.view, 1)

    @property
    def doc(self):
        return self.owner.canvas.document

    # ------------------------------------------------------------- refresh
    def refresh(self):
        document = self.doc
        selected = self.tags.currentData()
        self.tags.blockSignals(True)
        self.tags.clear()
        self.tags.addItem('Todos os quadros', -1)
        self.tags.addItem('Trecho selecionado', -2)
        for index, tag in enumerate(document.scene['tags']):
            self.tags.addItem(tag['name'], index)
        self.tags.setCurrentIndex(max(0, self.tags.findData(selected)))
        self.tags.blockSignals(False)
        for widget, value in ((self.onion, document.onion_skin), (self.onion_before, document.onion_before),
                              (self.onion_after, document.onion_after), (self.onion_opacity, round(document.onion_opacity * 100)),
                              (self.fps, max(1, min(60, round(1000 / max(1, document.frames[document.current_frame].duration)))))):
            widget.blockSignals(True)
            widget.setChecked(value) if isinstance(widget, QCheckBox) else widget.setValue(value)
            widget.blockSignals(False)
        self.view.build_rows()
        self.view.ensure_visible(document.current_frame)
        self.view.viewport().update()
        self.time_label.setText(f'{document.frame_start(document.current_frame):.2f}s / {document.total_ms / 1000:.2f}s')
        self.buttons['play'].setIcon(icon('pause' if self.playing else 'play', PALETTES[self.owner.theme]['muted']))

    def set_zoom(self, value):
        value = max(12, min(64, int(value)))
        self.view.cell = value
        self.zoom.blockSignals(True)
        self.zoom.setValue(value)
        self.zoom.blockSignals(False)
        self.view.update_scrollbars()
        self.view.viewport().update()

    # --------------------------------------------------------------- frames
    def select(self, index, layer=None):
        self.owner.canvas.finish_stroke()
        document = self.doc
        document.current_frame = max(0, min(len(document.frames) - 1, index))
        if layer is not None:
            document.active = layer
        self.owner.refresh_document()

    def step(self, delta):
        self.stop()
        self.select((self.doc.current_frame + delta) % len(self.doc.frames))

    def change_fps(self):
        fps = self.fps.value()
        self.owner.mutate(lambda d: d.set_fps(fps))

    def toggle_onion(self, value):
        self.doc.onion_skin = value
        self.owner.canvas.update()
        self.view.viewport().update()

    def change_onion(self):
        document = self.doc
        document.onion_before, document.onion_after = self.onion_before.value(), self.onion_after.value()
        document.onion_opacity = self.onion_opacity.value() / 100
        self.owner.canvas.update()
        self.view.viewport().update()

    def duplicate_range(self):
        start, end = self.view.selected_range()
        self.owner.mutate(lambda d: d.duplicate_frames(start, end))
        self.view.selection = None

    def delete_range(self):
        start, end = self.view.selected_range()
        self.owner.mutate(lambda d: d.delete_frames(start, end))
        self.view.selection = None

    def reverse_range(self):
        start, end = self.view.selected_range()
        if end > start:
            self.owner.mutate(lambda d: d.reverse_frames(start, end))

    def move_current(self, delta):
        index = self.doc.current_frame
        self.owner.mutate(lambda d: d.move_frame(index, index + delta))

    def copy_cel(self):
        document = self.doc
        layer = document.layers[document.active]
        from PyQt6.QtGui import QImage
        self.clipboard = (QImage(layer.image), layer.content)
        self.owner.statusBar().showMessage('Célula copiada.', 3000)

    def paste_cel(self):
        if not self.clipboard:
            return
        image, content = self.clipboard
        from PyQt6.QtGui import QImage

        def paste(document):
            layer = document.layers[document.active]
            if layer.locked:
                raise ValueError('A camada está bloqueada.')
            layer.image, layer.content = QImage(image), content
        self.owner.mutate(paste)

    def clear_cel(self):
        def clear(document):
            layer = document.layers[document.active]
            if layer.locked:
                raise ValueError('A camada está bloqueada.')
            layer.image.fill(0)
            layer.content = False
        self.owner.mutate(clear)

    def stretch(self, factor):
        index = self.doc.current_frame
        self.owner.mutate(lambda d: setattr(d.frames[index], 'duration', max(1, round(d.frames[index].duration * factor))))

    def tag_selection(self):
        start, end = self.view.selected_range()
        name, accepted = QInputDialog.getText(self, 'Nova tag', 'Nome da tag:', text=f'Tag {len(self.doc.scene["tags"]) + 1}')
        if accepted and name.strip():
            colors = ['#c86d65', '#5f9fd8', '#6bbf7a', '#d8a84f', '#a77fd6', '#d07aa8']
            color = colors[len(self.doc.scene['tags']) % len(colors)]
            self.owner.mutate(lambda d: d.scene['tags'].append({'name': name.strip(), 'from': start, 'to': end,
                                                                'direction': 'forward', 'repeat': 0, 'color': color}))

    def frame_menu(self):
        menu = QMenu(self)
        start, end = self.view.selected_range()
        span = end - start + 1
        label = f"{tr('Quadros')} {start + 1}–{end + 1}" if span > 1 else f"{tr('Quadro')} {start + 1}"
        title = menu.addAction(label)
        title.setEnabled(False)
        menu.addAction('Novo quadro (cópia)', lambda: self.owner.new_frame())
        menu.addAction('Novo quadro vazio', lambda: self.owner.new_frame(True))
        menu.addAction('Duplicar quadros', self.duplicate_range)
        menu.addAction('Inverter ordem dos quadros', self.reverse_range).setEnabled(span > 1)
        menu.addAction('Excluir quadros', self.delete_range)
        menu.addSeparator()
        menu.addAction('Mover quadro para a esquerda', lambda: self.move_current(-1)).setEnabled(self.doc.current_frame > 0)
        menu.addAction('Mover quadro para a direita', lambda: self.move_current(1)).setEnabled(self.doc.current_frame < len(self.doc.frames) - 1)
        menu.addAction('Duração do quadro…', self.owner.frame_duration)
        menu.addAction('Dobrar duração', lambda: self.stretch(2))
        menu.addAction('Metade da duração', lambda: self.stretch(.5))
        menu.addSeparator()
        menu.addAction('Copiar célula', self.copy_cel)
        paste = menu.addAction('Colar célula', self.paste_cel)
        paste.setEnabled(self.clipboard is not None)
        menu.addAction('Limpar célula', self.clear_cel)
        menu.addSeparator()
        menu.addAction('Criar tag com a seleção…', self.tag_selection)
        menu.addAction('Editar tag…', self.owner.edit_tag)
        menu.addAction('Keyframe da câmera…', lambda: self.owner.motion_key('camera'))
        menu.addAction('Keyframe da camada / parallax…', lambda: self.owner.motion_key('layer'))
        return menu

    # ------------------------------------------------------------- playback
    def toggle_play(self):
        if self.playing:
            self.stop()
            return
        self.owner.canvas.finish_stroke()
        data = self.tags.currentData()
        if data == -2 and self.view.selection:
            start, end = sorted(self.view.selection)
            self.tag = {'from': start, 'to': end, 'direction': 'forward', 'repeat': 0}
        else:
            self.tag = self.doc.scene['tags'][data] if data is not None and data >= 0 else None
        self.order = play_order(self.doc, self.tag)
        self.position = self.order.index(self.doc.current_frame) if self.doc.current_frame in self.order else 0
        self.repeats = 0
        self.playing = True
        self.start_audio()
        self.select(self.order[self.position])
        self.play_timer.start(self.doc.frames[self.doc.current_frame].duration)

    def start_audio(self):
        if not self.doc.scene['audio'] or (self.tag and self.tag.get('direction') != 'forward'):
            return
        try:
            import sounddevice as sd
            from media import RATE, mix_audio
            offset = round(self.doc.frame_start(self.order[self.position]) * RATE)
            sd.play(mix_audio(self.doc)[offset:], RATE)
        except Exception as error:  # no audio device: playback continues silently
            self.owner.statusBar().showMessage(tr('Áudio de prévia indisponível: ') + str(error), 6000)

    def advance(self):
        if not self.playing:
            return
        self.position += 1
        if self.position >= len(self.order):
            self.position = 0
            self.repeats += 1
            limit = self.tag.get('repeat', 0) if self.tag else 0
            if not self.loop.isChecked() or (limit and self.repeats >= limit):
                self.stop()
                return
            self.start_audio()
        self.select(self.order[self.position])
        self.play_timer.start(self.doc.frames[self.doc.current_frame].duration)

    def stop(self):
        self.play_timer.stop()
        if self.playing:
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:  # audio backend missing
                pass
        self.playing = False
        if hasattr(self, 'buttons'):
            self.buttons['play'].setIcon(icon('play', PALETTES[self.owner.theme]['muted']))
