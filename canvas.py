import math
import time

import numpy as np
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PyQt6.QtWidgets import QWidget

import brush_engine
import display
import drawing_tools
from i18n import tr
import guides
import selection as sel
from document import Document
import rig
from animation import layer_transform
from brush_engine import StampStroke
from resources import Brush
from stabilizer import Stabilizer, pressure_response
from themes import PALETTES

PAINT_TOOLS = ('brush', 'pencil', 'pen', 'pixel', 'eraser', 'smudge', 'blur')
EFFECT_TOOLS = ('smudge', 'blur')
BRUSH_TOOLS = ('brush', 'pencil', 'pen')
ERASER_TIP = Brush('Borracha', hardness=1., spacing=.05)
SELECT_TOOLS = ('select_rect', 'select_ellipse', 'lasso', 'wand')
GUIDE_TOOLS = ('perspective', 'ruler')
DRAG_TOOLS = ('shape', 'gradient', 'balloon')

# (tool, menu label, short badge, shortcut, icon), grouped as in the toolbar.
TOOLS = [
    [('move', 'Mover pixels', 'Mover', 'V', 'cursor-move'),
     ('select_rect', 'Seleção retangular', 'Retângulo', 'M', 'selection'),
     ('select_ellipse', 'Seleção elíptica', 'Elipse', 'Shift+M', 'selection-ellipse'),
     ('lasso', 'Laço (seleção livre)', 'Laço', 'L', 'lasso'),
     ('wand', 'Varinha mágica', 'Varinha', 'W', 'auto-fix'),
     ('panel', 'Selecionar quadro (clique no quadro)', 'Selecionar quadro', 'Shift+W', 'view-quilt-outline')],
    [('brush', 'Pincel', 'Pincel', 'B', 'brush'),
     ('pencil', 'Lápis', 'Lápis', 'N', 'pencil'),
     ('pen', 'Caneta', 'Caneta', 'P', 'fountain-pen-tip'),
     ('pixel', 'Lápis pixel art', 'Pixel', 'Shift+N', 'grid'),
     ('eraser', 'Borracha', 'Borracha', 'E', 'eraser'),
     ('smudge', 'Esfumar (arrasta a tinta)', 'Esfumar', 'Shift+E', 'water-outline'),
     ('blur', 'Desfocar', 'Desfocar', '', 'blur'),
     ('fill', 'Balde de tinta', 'Balde', 'G', 'format-color-fill'),
     ('gradient', 'Degradê', 'Degradê', 'Shift+G', 'gradient-horizontal'),
     ('shape', 'Formas (linha, retângulo, elipse, polígono…)', 'Formas', 'O', 'shape-outline'),
     ('text', 'Texto', 'Texto', 'T', 'format-text'),
     ('balloon', 'Balão (clique no balão e arraste até quem fala)', 'Balão', 'Shift+T', 'chat-outline'),
     ('picker', 'Conta-gotas', 'Conta-gotas', 'I', 'eyedropper')],
    [('ruler', 'Régua paralela', 'Régua', 'U', 'ruler'),
     ('perspective', 'Guias de perspectiva', 'Perspectiva', 'Shift+U', 'perspective-more'),
     ('symmetry', 'Simetria (posicionar o eixo)', 'Simetria', 'Shift+S', 'mirror'),
     ('reference', 'Imagem de referência (mover)', 'Referência', '', 'image-outline')],
    [('hand', 'Mover tela', 'Mover tela', 'H', 'hand-back-left-outline'),
     ('rotate', 'Girar vista', 'Girar vista', 'R', 'rotate-orbit')],
    [('bone', 'Bone Tool · esqueleto', 'Ossos', 'K', 'bone')],
]
TOOL_INFO = {tool[0]: tool for group in TOOLS for tool in group}
# Buttons of the tool column; tools in the same slot share a button with a flyout menu.
TOOL_SLOTS = [['move'], ['select_rect', 'select_ellipse', 'lasso', 'panel'], ['wand'], None,
              ['brush', 'pencil', 'pen', 'pixel'], ['eraser'], ['smudge', 'blur'], ['fill', 'gradient'],
              ['shape'], ['text', 'balloon'], ['picker'], None,
              ['ruler', 'perspective', 'symmetry', 'reference'], None, ['hand', 'rotate'], ['bone']]


def line_pixels(x0, y0, x1, y1):
    """Bresenham line between pixel cells, used by the pixel-art pencil."""
    x0, y0, x1, y1 = math.floor(x0), math.floor(y0), math.floor(x1), math.floor(y1)
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        double = 2 * error
        if double >= dy:
            error += dy
            x0 += sx
        if double <= dx:
            error += dx
            y0 += sy


class Canvas(QWidget):
    changed = pyqtSignal()
    view_changed = pyqtSignal()
    color_picked = pyqtSignal(QColor)
    message = pyqtSignal(str)
    selection_changed = pyqtSignal()
    bone_selected = pyqtSignal()

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.document = Document()
        self.zoom = 1.
        self.rotation = 0.
        self.pan = QPointF()
        self.theme = 'Escuro'
        self.tool = 'brush'
        self.engine = Stabilizer()
        self.drawing = False
        self.tablet_down = False
        self.panning = False
        self.space_down = False
        self.cursor_inside = False
        self.cursor_pos = QPointF()
        self.last_pressure = 1.
        self.show_guide = True
        self.show_rulers = False
        self.show_grid = False
        self.show_panel_numbers = True
        self.grid_size = 64
        self.rig_drag = None
        self.view = display.ReducedView()
        self.scene_view = display.SceneView()
        self.gray_view = display.SceneView(paper=True, post=display.grayscale)
        self.cursor_rect = QRect()
        self.stroke_revision = None
        self.pending_patches = []
        self.stroke_effects = False
        self.effect = None
        self.shape_drag = None
        self.symmetry_drag = False
        self.reference = None
        self.reference_drag = None
        self.flip_view = False
        self.grayscale_view = False
        self.composition = 'none'
        self.grid_kind = 'square'
        self.selected_bone = None
        self.hover_bone = None
        self.selection = None
        self.selection_values = None
        self.selection_path = None
        self.selection_drag = None
        self.move_state = None
        self.guide_drag = None
        self.rotating = None
        self.constraint = None
        self.stroke_mask = None
        self.last_doc_point = None
        self.last_stroke_end = None
        self.setMinimumSize(320, 240)
        # The view paints every pixel itself: Qt need not draw what lies beneath it first.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self.tick)
        self.checker = QPixmap(16, 16)
        self.checker.fill(QColor('#efefef'))
        painter = QPainter(self.checker)
        painter.fillRect(0, 0, 8, 8, QColor('#d5d5d5'))
        painter.fillRect(8, 8, 8, 8, QColor('#d5d5d5'))
        painter.end()

    @property
    def image(self):
        return self.document.layers[self.document.active].image

    def option(self, key, default):
        return getattr(self.parent_app, 'tool_options', {}).get(key, default)

    def transform(self):
        transform = QTransform()
        transform.translate(self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y())
        transform.rotate(self.rotation)
        transform.scale(-self.zoom if self.flip_view else self.zoom, self.zoom)
        transform.translate(-self.document.width / 2, -self.document.height / 2)
        return transform

    def to_document(self, position):
        return self.transform().inverted()[0].map(position)

    def document_rect(self):
        return QRectF(0, 0, self.document.width, self.document.height)

    def fit(self):
        self.zoom = max(0.02, min((self.width() - 80) / self.document.width,
                                  (self.height() - 80) / self.document.height, 1.))
        self.pan = QPointF()
        self.update()
        self.view_changed.emit()

    def set_zoom(self, zoom, anchor=None):
        self.finish_stroke()
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        point = self.to_document(anchor)
        self.zoom = max(0.02, min(16., zoom))
        self.pan += anchor - self.transform().map(point)
        self.update()
        self.view_changed.emit()

    def set_rotation(self, angle):
        self.finish_stroke()
        self.rotation = (angle + 180) % 360 - 180
        self.update()
        self.view_changed.emit()

    def set_document(self, document):
        self.finish_interaction()
        self.document = document
        self.last_stroke_end = None
        self.selected_bone = self.hover_bone = None
        self.set_selection(None)
        self.fit()
        self.changed.emit()

    def set_tool(self, tool):
        self.finish_interaction()
        self.tool = tool
        self.update_cursor()
        self.update()

    def update_cursor(self):
        if self.space_down or self.tool == 'hand':
            cursor = Qt.CursorShape.OpenHandCursor
        elif self.tool == 'move':
            cursor = Qt.CursorShape.SizeAllCursor
        elif self.tool == 'rotate':
            cursor = Qt.CursorShape.SizeHorCursor
        elif self.tool in GUIDE_TOOLS:
            cursor = Qt.CursorShape.PointingHandCursor
        else:
            cursor = Qt.CursorShape.CrossCursor
        self.setCursor(cursor)

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event):
        if self.drawing and self.pending_patches:
            self.flush_stroke()
        painter = QPainter(self)
        colors = PALETTES[self.theme]
        self.paint_surround(painter, colors, event.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        transform = self.transform()
        painter.setTransform(transform)
        rectangle = self.document_rect()
        painter.fillRect(rectangle.adjusted(-5, -5, 5, 5), QColor(0, 0, 0, 35))
        if self.document.paper_visible:
            painter.fillRect(rectangle, Qt.GlobalColor.white)
        else:
            painter.fillRect(rectangle, QBrush(self.checker))
        if self.reference and self.reference['visible'] and self.reference['behind']:
            self.paint_reference(painter)
        scale = self.zoom * self.devicePixelRatioF()
        self.paint_scale, self.paint_rect = scale, event.rect()
        level = display.level_for(scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, display.smooth_for(scale))
        if self.document.animation_enabled:
            if self.document.onion_skin and not self.parent_app.timeline.playing:
                self.paint_onion(painter, level)
            painter.setOpacity(1.)
            self.draw_level(painter, self.scene_view.image(self.document, level), level)
        elif self.document.needs_composite:
            self.draw_level(painter, self.scene_view.image(self.document, level), level)
        elif level:
            image = self.view.layers(self.document, level)
            painter.drawImage(QRectF(0, 0, image.width() << level, image.height() << level), image)
        else:
            for layer in self.document.layers:
                if layer.visible:
                    painter.setOpacity(layer.opacity)
                    self.draw_level(painter, layer.image, 0)
        painter.setOpacity(1.)
        if self.grayscale_view:
            self.draw_level(painter, self.gray_view.image(self.document, level), level)
        if self.reference and self.reference['visible'] and not self.reference['behind']:
            self.paint_reference(painter)
        painter.resetTransform()
        accent = QColor(colors['accent'])
        guides.draw_composition(painter, transform, self.composition, rectangle)
        aids = self.document.guides
        if self.show_grid:
            guides.draw_grid(painter, transform, self.zoom, self.grid_size, rectangle, self.grid_kind)
        comic = self.document.scene.get('comic', {})
        panels = (comic.get('shapes') or comic.get('panels')) if self.show_panel_numbers else None
        guides.draw_print_guides(painter, transform, aids, rectangle, panels)
        guides.draw_perspective(painter, transform, aids, rectangle, self.tool == 'perspective')
        guides.draw_ruler(painter, transform, aids, rectangle, self.tool == 'ruler')
        guides.draw_symmetry(painter, transform, aids.get('symmetry'), rectangle, self.tool == 'symmetry')
        self.paint_selection(painter, transform)
        self.paint_tool_preview(painter, transform, accent)
        if self.tool == 'bone':
            self.paint_bones(painter, transform, accent)
        if self.cursor_inside and self.tool in PAINT_TOOLS and not self.space_down:
            self.paint_brush_cursor(painter, transform, accent)
        if self.show_rulers:
            guides.draw_edge_rulers(painter, self, colors)

    def paint_surround(self, painter, colors, area):
        """Area around the document: plain colour, or the window's background image seen through it."""
        window = self.window()
        look = getattr(window, 'appearance', None)
        pixmap = window.background_pixmap() if look and look['background_canvas'] else None
        if pixmap is None:
            painter.fillRect(area, QColor(colors['canvas']))
            return
        offset = self.mapTo(window, QPoint(0, 0))
        painter.drawPixmap(area, pixmap, area.translated(offset))
        tint = QColor(colors['canvas'])
        tint.setAlphaF(look['canvas_opacity'])
        painter.fillRect(area, tint)

    def paint_onion(self, painter, level=0):
        """Neighbouring frames tinted red (before) and blue (after), fading with distance."""
        document = self.document
        cache = getattr(self, 'onion_cache', {})
        fresh = {}
        steps = [(-k, QColor(225, 85, 85)) for k in range(document.onion_before, 0, -1)]
        steps += [(k, QColor(70, 140, 235)) for k in range(document.onion_after, 0, -1)]
        for offset, color in steps:
            index = document.current_frame + offset
            if not 0 <= index < len(document.frames):
                continue
            key = (id(document), index, level, color.name(), document.revision,
                   tuple(l.image.cacheKey() for l in document.frames[index].layers),
                   tuple((l.visible, l.opacity) for l in document.frames[index].layers))
            image = cache.get(key)
            if image is None:
                image = document.composite(paper=False, frame_index=index, subtitles=False)
                tint = QPainter(image)
                tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                tint.fillRect(image.rect(), color)
                tint.end()
                if level:
                    image = display.reduce(image, 1 << level)
            fresh[key] = image
            painter.setOpacity(document.onion_opacity * (1 - (abs(offset) - 1) / (max(document.onion_before, document.onion_after) + 1)))
            self.draw_level(painter, image, level)
        painter.setOpacity(1.)
        self.onion_cache = fresh

    def draw_level(self, painter, image, level):
        """Draw an image that is already reduced by 2**level at document size.

        Enlarged views use "sharp bilinear": each pixel becomes an even square joined to its
        neighbours by a one-pixel blend, instead of being smeared over several screen pixels
        (bilinear) or drawn as blocks of uneven size (nearest at a non-integer zoom)."""
        if level:
            painter.drawImage(QRectF(0, 0, image.width() << level, image.height() << level), image)
            return
        scale = getattr(self, 'paint_scale', 1.)
        factor = int(scale + .01)
        if factor < 2 or abs(scale - factor) < .01:
            painter.drawImage(0, 0, image)
            return
        visible = painter.transform().inverted()[0].mapRect(QRectF(self.paint_rect)).toAlignedRect()
        region = visible.adjusted(-1, -1, 1, 1).intersected(image.rect())
        if region.isEmpty():
            return
        enlarged = image.copy(region).scaled(region.width() * factor, region.height() * factor,
                                             Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(region), enlarged)
        painter.restore()

    def mark_dirty(self, rect):
        """Document-space area changed in place (by a stroke): cached views refresh only there."""
        rect = rect.adjusted(-2, -2, 2, 2)
        self.view.mark(rect)
        self.scene_view.mark(rect)
        self.gray_view.mark(rect)

    def cursor_area(self):
        """Widget area covered by the brush cursor (and the stabilizer guide line while drawing)."""
        raw = self.cursor_pos
        area = QRectF(raw.x() - 8, raw.y() - 8, 16, 16)
        if self.tool in PAINT_TOOLS:
            tip = raw
            if self.drawing:
                tip = self.transform().map(self.stroke_transform.map(QPointF(self.engine.last.x, self.engine.last.y)))
            size = self.parent_app.brush_size * self.zoom
            radius = max(2., size * (.75 if self.tool == 'pixel' else .5)) + 4
            area = area.united(QRectF(tip.x() - radius, tip.y() - radius, radius * 2, radius * 2))
        return area.toAlignedRect()

    def update_cursor_area(self):
        """Repaint only where the cursor was and is, instead of the whole view."""
        if self.show_rulers or self.tool not in PAINT_TOOLS:
            self.update()
            return
        area = self.cursor_area()
        self.update(area.united(self.cursor_rect) if not self.cursor_rect.isNull() else area)
        self.cursor_rect = area

    def paint_reference(self, painter):
        reference = self.reference
        painter.save()
        painter.setOpacity(reference['opacity'])
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(reference['position'])
        painter.scale(reference['scale'], reference['scale'])
        painter.drawImage(0, 0, reference['image'])
        painter.restore()

    def load_reference(self, image):
        scale = min(1., self.document.width * .6 / max(1, image.width()), self.document.height * .6 / max(1, image.height()))
        self.reference = {'image': image, 'position': QPointF(self.document.width * .05, self.document.height * .05),
                          'scale': scale, 'opacity': .5, 'visible': True, 'behind': False}
        self.update()

    def paint_tool_preview(self, painter, view, accent):
        drag = self.shape_drag
        if not drag:
            return
        painter.save()
        painter.setTransform(view)
        if drag['tool'] == 'balloon':
            painter.setPen(QPen(accent, 0, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(255, 255, 255, 120))
            radius = min(self.document.width, self.document.height) * .06
            painter.drawEllipse(drag['start'], radius * 1.5, radius)
            painter.drawLine(drag['start'], drag['current'])
            painter.restore()
            return
        if drag['tool'] == 'gradient':
            painter.setPen(QPen(QColor(255, 255, 255, 220), 0))
            painter.drawLine(drag['start'], drag['current'])
            painter.setPen(QPen(accent, 0, Qt.PenStyle.DashLine))
            painter.drawLine(drag['start'], drag['current'])
            painter.restore()
            painter.save()
            for point in (drag['start'], drag['current']):
                painter.setBrush(QColor('white'))
                painter.setPen(QPen(accent, 2))
                painter.drawEllipse(view.map(point), 5, 5)
        else:
            path = self.current_shape_path()
            color = QColor(self.parent_app.current_color)
            color.setAlpha(200)
            painter.setPen(QPen(color, max(.5, self.parent_app.brush_size), Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            fill = self.option('shape_fill', 'stroke')
            if fill != 'stroke' and drag.get('kind') not in ('line', 'arrow'):
                fill_color = QColor(self.parent_app.secondary_color if fill == 'both' else self.parent_app.current_color)
                fill_color.setAlpha(150)
                painter.setBrush(fill_color)
            painter.drawPath(path)
            for point in drag.get('points', []):
                painter.setPen(QPen(accent, 0))
                painter.drawEllipse(point, 3 / self.zoom, 3 / self.zoom)
        painter.restore()

    def current_shape_path(self, drag=None):
        drag = drag or self.shape_drag
        return drawing_tools.shape_path(drag['kind'], drag['start'], drag['current'], drag.get('constrain', False),
                                        drag.get('center', False), drag.get('points'))

    def commit_shape(self):
        drag, self.shape_drag = self.shape_drag, None
        layer = self.editable_layer()
        if not drag or layer is None:
            self.update()
            return
        view = self.transform()
        if drag['tool'] == 'gradient' or drag['kind'] != 'polygon':
            if (view.map(drag['current']) - view.map(drag['start'])).manhattanLength() < 4:
                self.update()
                return
        to_layer = self.active_transform().inverted()[0]
        mask = self.to_layer_space(self.selection) if self.selection is not None else None
        self.document.checkpoint()
        app = self.parent_app
        if drag['tool'] == 'gradient':
            transparent = QColor(app.current_color)
            transparent.setAlpha(0)
            end_color = app.secondary_color if self.option('gradient_colors', 'colors') == 'colors' else transparent
            drawing_tools.paint_gradient(layer.image, to_layer.map(drag['start']), to_layer.map(drag['current']),
                                         self.option('gradient_kind', 'linear'), app.current_color, end_color,
                                         app.brush_opacity, layer.alpha_lock, mask)
        else:
            path = to_layer.map(self.current_shape_path(drag))
            drawing_tools.paint_shape(layer.image, path, drag['kind'], app.brush_size, QColor(app.current_color),
                                      self.option('shape_fill', 'stroke'), QColor(app.secondary_color),
                                      app.brush_opacity, layer.alpha_lock, mask)
        self.commit_edit(layer)

    def paint_brush_cursor(self, painter, transform, accent):
        raw = self.cursor_pos
        tip = transform.map(self.stroke_transform.map(QPointF(self.engine.last.x, self.engine.last.y))) if self.drawing else raw
        if self.drawing and self.show_guide and self.engine.delay and (tip - raw).manhattanLength() > 2:
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DashLine))
            painter.drawLine(tip, raw)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(raw, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.tool == 'pixel':
            size = max(1, round(self.parent_app.brush_size))
            point = self.to_document(tip)
            cell = QRectF(math.floor(point.x()) - size // 2, math.floor(point.y()) - size // 2, size, size)
            polygon = transform.map(QPolygonF(cell))
            painter.setPen(QPen(QColor(0, 0, 0, 190), 2.5))
            painter.drawPolygon(polygon)
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
            painter.drawPolygon(polygon)
            return
        radius = max(2., self.parent_app.brush_size * self.zoom / 2)
        painter.setPen(QPen(QColor(0, 0, 0, 190), 2.5))
        painter.drawEllipse(tip, radius, radius)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        painter.drawEllipse(tip, radius, radius)

    def paint_selection(self, painter, view):
        paths = []
        if self.selection is not None:
            path = self.selection_path
            if path is None:
                path = QPainterPath()
                path.addRect(QRectF(sel.bounds(self.selection_values)))
            if self.move_state and self.move_state.get('doc_offset') is not None:
                offset = self.move_state['doc_offset']
                path = QTransform.fromTranslate(offset.x(), offset.y()).map(path)
            paths.append(path)
        preview = self.selection_preview()
        if preview is not None:
            paths.append(preview)
        if not paths:
            return
        painter.save()
        painter.setTransform(view)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        dashed = QPen(QColor(0, 0, 0, 235), 0)
        dashed.setDashPattern([4, 4])
        for path in paths:
            painter.setPen(QPen(QColor(255, 255, 255, 235), 0))
            painter.drawPath(path)
            painter.setPen(dashed)
            painter.drawPath(path)
        painter.restore()

    # ---------------------------------------------------------------- strokes

    def begin_stroke(self, position, pressure=1., timestamp=None):
        layer = self.document.layers[self.document.active]
        start = self.to_document(position)
        if not self.document_rect().contains(start):
            return False
        if layer.locked or not layer.visible:
            self.message.emit('Selecione uma camada visível e desbloqueada para desenhar.')
            return False
        aids = self.document.guides
        directions = guides.snap_directions(aids, start) if aids.get('snap') else []
        self.constraint = guides.StrokeConstraint(start, directions, 6 / self.zoom) if directions else None
        point = self.stroke_point(position)
        self.document.checkpoint()
        self.drawing = True
        self.stroke_revision = self.document.revision
        self.stroke_layer = self.document.active
        self.stroke_tool = self.tool
        self.stroke_size = self.parent_app.brush_size
        self.stroke_color = QColor(self.parent_app.current_color)
        self.stroke_transform = layer_transform(self.document,layer,self.document.current_frame)[0]
        brush = self.parent_app.brush_for(self.tool) if self.tool in BRUSH_TOOLS and hasattr(self.parent_app, 'brush_for') else None
        self.stroke_brush = brush
        # Every stroke is stamped (the eraser with a hard round tip), so edges are antialiased alike.
        self.stamp_renderer = StampStroke(brush or ERASER_TIP)
        self.stroke_opacity = self.parent_app.brush_opacity
        self.stroke_profile = self.parent_app.pressure_profile
        self.stroke_minimum = self.parent_app.minimum_size
        self.stroke_pressure_enabled = self.parent_app.pressure_enabled and (brush is None or brush.size_pressure)
        self.stroke_mask = self.to_layer_space(self.selection) if self.selection is not None else None
        self.stroke_effects = brush_engine.has_effects(brush) and self.tool != 'eraser'
        self.pending_patches = []
        self.document.preview_layer = layer.id if layer.is_shadow else None
        self.base_image = QImage(layer.image)
        # Coverage only (16-bit grey); the colour is applied when patches are composed.
        self.stroke_image = brush_engine.coverage_buffer(self.document.width, self.document.height)
        self.engine.set_level(self.parent_app.stabilizer_level)
        self.last_pressure = max(0., min(1., pressure))
        self.cursor_pos = position
        samples = self.engine.start(point.x(), point.y(), self.last_pressure, timestamp if timestamp is not None else time.perf_counter())
        self.previous = samples[0]
        self.lanes = self.make_lanes(brush, samples[0])
        self.effect = (drawing_tools.EffectStroke(layer.image, self.tool, max(.05, self.stroke_opacity), self.stroke_mask)
                       if self.tool in EFFECT_TOOLS else None)
        self.render_samples(samples)
        self.timer.start()
        return True

    def move_stroke(self, position, pressure=1., timestamp=None):
        self.cursor_pos = position
        if self.drawing:
            point = self.stroke_point(position)
            if pressure > 0:
                self.last_pressure = min(1., pressure)
            self.render_samples(self.engine.add(point.x(), point.y(), self.last_pressure,
                                                timestamp if timestamp is not None else time.perf_counter()))
        self.update_cursor_area()

    def finish_stroke(self, position=None, pressure=None, timestamp=None):
        if not self.drawing:
            return
        self.timer.stop()
        point = self.stroke_point(position) if position is not None else QPointF(self.engine.raw.x, self.engine.raw.y)
        final_pressure = self.last_pressure if pressure is None or pressure <= 0 else pressure
        self.render_samples(self.engine.finish(point.x(), point.y(), final_pressure,
                                               timestamp if timestamp is not None else time.perf_counter()))
        self.finish_lanes()
        self.flush_stroke()
        self.drawing = False
        self.base_image = None
        self.stroke_image = None
        self.stroke_mask = None
        self.constraint = None
        self.effect = None
        self.document.preview_layer = None
        self.last_stroke_end = self.last_doc_point
        self.document.layers[self.stroke_layer].content = True
        self.document.changed()
        for view in (self.scene_view, self.gray_view):
            view.adopt(self.document, self.stroke_revision)
        # Neighbouring frames are untouched by a stroke: keep their onion images.
        self.onion_cache = {key[:4] + (self.document.revision,) + key[5:] if key[4] == self.stroke_revision else key: image
                            for key, image in getattr(self, 'onion_cache', {}).items()}
        self.changed.emit()
        self.update()

    def tick(self):
        if self.drawing:
            self.render_samples(self.engine.advance(time.perf_counter()))
            self.update_cursor_area()

    def sample_size(self, sample):
        response = pressure_response(sample.pressure, self.stroke_profile, self.stroke_minimum) if self.stroke_pressure_enabled else 1.
        return max(0.1, self.stroke_size * response)

    def render_samples(self, samples):
        if not samples:
            return
        if self.effect is not None:
            region = self.effect.stroke(samples, self.sample_size)
            self.previous = samples[-1]
            if not region.isNull():
                self.mark_dirty(self.stroke_transform.mapRect(QRectF(region)).toAlignedRect())
                self.update((self.stroke_transform * self.transform()).mapRect(QRectF(region)).toAlignedRect().adjusted(-3, -3, 3, 3))
            return
        painter = QPainter(self.stroke_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dirty = QRectF()
        for lane in self.lanes:
            mapped = samples if lane['transform'] is None else [self.map_sample(s, lane['transform']) for s in samples]
            box = self.draw_lane(painter, lane, mapped, brush_engine.INK)
            if not box.isNull():
                dirty = box if dirty.isNull() else dirty.united(box)
        self.previous = samples[-1]
        painter.end()
        self.queue_dirty(dirty)

    def finish_lanes(self):
        """Stamped lanes that never moved far enough to show a direction still leave their dab."""
        if self.effect is not None or self.stroke_image is None:
            return
        painter = QPainter(self.stroke_image)
        dirty = QRectF()
        for lane in self.lanes:
            box = lane['stamp'].finish(painter, self.sample_size)
            if not box.isNull():
                dirty = box if dirty.isNull() else dirty.united(box)
        painter.end()
        self.queue_dirty(dirty)

    def queue_dirty(self, dirty):
        region = dirty.toAlignedRect().intersected(self.stroke_image.rect())
        if region.isEmpty():
            return
        if self.stroke_effects:
            pad = brush_engine.wet_radius(self.stroke_brush, self.stroke_size)
            region = region.adjusted(-pad, -pad, pad, pad).intersected(self.stroke_image.rect())
        # Dabs land in the stroke buffer right away; turning the buffer into layer pixels (texture,
        # wet edges, opacity, selection) happens once per repaint for everything touched since.
        self.queue_patch(region)
        self.update((self.stroke_transform * self.transform()).mapRect(QRectF(region)).toAlignedRect().adjusted(-3, -3, 3, 3))

    def queue_patch(self, region):
        """Add a layer-space area to the pending patches, merging overlapping ones."""
        pending = self.pending_patches
        merged = True
        while merged:
            merged = False
            for index, other in enumerate(pending):
                if other.intersects(region.adjusted(-8, -8, 8, 8)):
                    region = region.united(pending.pop(index))
                    merged = True
                    break
        pending.append(region)

    def flush_stroke(self):
        """Compose pending stroke patches into the layer (called before painting and at stroke end)."""
        patches, self.pending_patches = self.pending_patches, []
        for region in patches:
            self.compose_patch(region)

    def compose_patch(self, region):
        effects = self.stroke_effects
        color = self.stroke_color if self.stroke_tool != 'eraser' else QColor('black')
        if effects:
            pad = brush_engine.wet_radius(self.stroke_brush, self.stroke_size)
            # Wet edges look at neighbouring coverage: compute with extra context and
            # write only the inner part, so patch borders never read as stroke edges.
            context = region.adjusted(-pad, -pad, pad, pad).intersected(self.stroke_image.rect())
        # Rebuild only the affected patch from the pre-stroke image. Opacity is
        # applied once per stroke, avoiding dark seams at overlapping samples.
        target = self.document.layers[self.stroke_layer].image
        painter = QPainter(target)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(region, self.base_image, region)
        alpha_lock = self.document.layers[self.stroke_layer].alpha_lock
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut if self.stroke_tool == 'eraser'
                                   else QPainter.CompositionMode.CompositionMode_SourceAtop if alpha_lock
                                   else QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setOpacity(self.stroke_opacity)
        if effects:
            # Grain and wet edges depend on the whole stroke, so they are applied to the
            # accumulated coverage of this patch rather than to each dab.
            alpha = brush_engine.alpha_of(self.stroke_image.copy(context))
            alpha = brush_engine.finish_alpha(alpha, context.x(), context.y(), self.stroke_brush, self.stroke_size)
            left, top = region.x() - context.x(), region.y() - context.y()
            alpha = alpha[top:top + region.height(), left:left + region.width()]
            patch = brush_engine.solid(color, np.ascontiguousarray(alpha))
        else:
            patch = brush_engine.colorize(color, self.stroke_image, region)
        if self.stroke_mask is not None:
            clip = QPainter(patch)
            clip.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            clip.drawImage(0, 0, self.stroke_mask, region.x(), region.y(), region.width(), region.height())
            clip.end()
        painter.drawImage(region.topLeft(), patch)
        painter.end()
        self.mark_dirty(self.stroke_transform.mapRect(QRectF(region)).toAlignedRect())

    def make_lanes(self, brush, first):
        """One drawing lane per symmetry copy, each with its own dab state."""
        lanes = []
        symmetry = self.document.guides.get('symmetry') or {}
        to_document = self.stroke_transform
        to_layer = to_document.inverted()[0]
        for index, transform in enumerate(guides.symmetry_transforms(symmetry, self.document.width, self.document.height)):
            mapping = None if index == 0 else to_document * transform * to_layer
            start = first if mapping is None else self.map_sample(first, mapping)
            stamp = StampStroke(self.stamp_renderer.brush)
            lanes.append({'transform': mapping, 'previous': start, 'stamp': stamp if index else self.stamp_renderer})
        return lanes

    @staticmethod
    def map_sample(sample, transform):
        point = transform.map(QPointF(sample.x, sample.y))
        return type(sample)(point.x(), point.y(), sample.pressure, sample.time)

    def draw_lane(self, painter, lane, samples, color):
        if self.stroke_tool == 'pixel':
            return self.render_pixels(painter, samples, color, lane)
        box = lane['stamp'].draw(painter, lane['previous'], samples, self.sample_size)
        lane['previous'] = samples[-1]
        return box

    def render_pixels(self, painter, samples, color, lane):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        size = max(1, round(self.stroke_size))
        half = size // 2
        dirty = QRect()
        for sample in samples:
            previous = lane['previous']
            for x, y in line_pixels(previous.x, previous.y, sample.x, sample.y):
                cell = QRect(x - half, y - half, size, size)
                painter.fillRect(cell, color)
                dirty = cell if dirty.isNull() else dirty.united(cell)
            lane['previous'] = sample
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        return QRectF(dirty.adjusted(-1, -1, 1, 1)) if not dirty.isNull() else QRectF()

    def stroke_point(self, position):
        point = self.to_document(position)
        if self.constraint is not None:
            point = self.constraint.apply(point)
        self.last_doc_point = point
        layer = self.document.layers[self.document.active]
        return layer_transform(self.document,layer,self.document.current_frame)[0].inverted()[0].map(point)

    # ------------------------------------------------------- layer-space maps

    def active_transform(self):
        layer = self.document.layers[self.document.active]
        return layer_transform(self.document, layer, self.document.current_frame)[0]

    def to_layer_space(self, mask):
        transform = self.active_transform()
        if transform.isIdentity():
            return mask
        return sel.transformed(mask, transform.inverted()[0], self.document.width, self.document.height)

    def layer_in_document_space(self):
        transform = self.active_transform()
        if transform.isIdentity():
            return self.image
        return sel.transformed(self.image, transform, self.document.width, self.document.height)

    def editable_layer(self):
        layer = self.document.layers[self.document.active]
        if layer.locked or not layer.visible:
            self.message.emit('Selecione uma camada visível e desbloqueada.')
            return None
        return layer

    # -------------------------------------------------------------- selection

    def set_selection(self, values, path=None):
        if values is None or not values.any():
            self.selection = self.selection_values = self.selection_path = None
        else:
            self.selection_values = values
            self.selection = sel.mask_from_alpha(values)
            self.selection_path = path if path is not None else sel.outline(values)
        self.selection_changed.emit()
        self.update()

    def selection_mode(self, modifiers):
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if shift and alt:
            return 'intersect'
        if shift:
            return 'add'
        if alt:
            return 'subtract'
        return self.option('selection_mode', 'replace')

    def apply_selection(self, values, mode, path=None):
        combined = sel.combine(self.selection_values, values, mode)
        self.set_selection(combined, path if mode == 'replace' or self.selection_values is None else None)

    def selection_preview(self, drag=None):
        drag = drag or self.selection_drag
        if not drag:
            return None
        path = QPainterPath()
        if drag['tool'] == 'lasso':
            if len(drag['points']) > 1:
                path.addPolygon(QPolygonF(drag['points']))
                path.closeSubpath()
            return path
        rect = QRectF(drag['start'], drag['current']).normalized()
        if drag.get('square'):
            side = max(rect.width(), rect.height())
            sx = 1 if drag['current'].x() >= drag['start'].x() else -1
            sy = 1 if drag['current'].y() >= drag['start'].y() else -1
            rect = QRectF(drag['start'], drag['start'] + QPointF(side * sx, side * sy)).normalized()
        if drag['tool'] == 'select_ellipse':
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        return path

    def commit_selection_drag(self):
        drag, self.selection_drag = self.selection_drag, None
        path = None
        if drag:
            moved = (self.transform().map(drag['current']) - self.transform().map(drag['start'])).manhattanLength()
            path = self.selection_preview(drag) if moved > 2 else None
        if path is None or path.isEmpty():
            if drag and drag['mode'] == 'replace':
                self.set_selection(None)
            self.update()
            return
        if drag['tool'] == 'select_rect' and not drag.get('square'):
            rect = path.boundingRect()
            path = QPainterPath()
            path.addRect(QRectF(QPointF(round(rect.left()), round(rect.top())), QPointF(round(rect.right()), round(rect.bottom()))))
        antialias = self.option('antialias', True) and drag['tool'] != 'select_rect'
        values = sel.alpha(sel.path_mask(path, self.document.width, self.document.height, antialias))
        self.apply_selection(values, drag['mode'], path.intersected(self.full_path()))

    def full_path(self):
        path = QPainterPath()
        path.addRect(self.document_rect())
        return path

    def wand_region(self, point):
        x, y = math.floor(point.x()), math.floor(point.y())
        if not (0 <= x < self.document.width and 0 <= y < self.document.height):
            return None
        source = (self.document.composite(paper=False, subtitles=False) if self.option('sample_all', True)
                  else self.layer_in_document_space())
        return sel.similar_region(source, x, y, self.option('tolerance', 32), self.option('contiguous', True))

    def wand_at(self, position, mode):
        region = self.wand_region(self.to_document(position))
        if region is None:
            if mode == 'replace':
                self.set_selection(None)
            return
        self.apply_selection(region.astype(np.uint8) * 255, mode)

    def select_all(self):
        self.set_selection(np.full((self.document.height, self.document.width), 255, np.uint8), self.full_path())

    def invert_selection(self):
        if self.selection_values is None:
            self.select_all()
        else:
            self.set_selection(255 - self.selection_values)

    def select_rect(self, rect):
        path = QPainterPath()
        path.addRect(QRectF(rect))
        values = sel.alpha(sel.path_mask(path, self.document.width, self.document.height, False))
        self.set_selection(values, path)

    # ------------------------------------------------------------ pixel edits

    def fill_at(self, position):
        layer = self.editable_layer()
        if layer is None:
            return
        region = self.wand_region(self.to_document(position))
        if region is None:
            return
        values = sel.grow(region, self.option('expand', 1)).astype(np.uint8) * 255
        if self.selection_values is not None:
            values = np.minimum(values, self.selection_values)
        if not values.any():
            return
        self.paint_mask(layer, self.to_layer_space(sel.mask_from_alpha(values)), QColor(self.parent_app.current_color),
                        self.parent_app.brush_opacity)

    def paint_mask(self, layer, mask, color, opacity=1.):
        self.document.checkpoint()
        painter = QPainter(layer.image)
        painter.setOpacity(opacity)
        if layer.alpha_lock:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        painter.drawImage(0, 0, sel.colored(mask, color))
        painter.end()
        self.commit_edit(layer)

    def commit_edit(self, layer):
        layer.content = True
        self.document.changed()
        self.changed.emit()
        self.update()

    def fill_selection(self, color):
        layer = self.editable_layer()
        if layer is not None:
            mask = self.selection if self.selection is not None else sel.mask_from_alpha(
                np.full((self.document.height, self.document.width), 255, np.uint8))
            self.paint_mask(layer, self.to_layer_space(mask), color)

    def clear_pixels(self):
        layer = self.editable_layer()
        if layer is None:
            return
        self.document.checkpoint()
        if self.selection is None:
            layer.image.fill(0)
        else:
            layer.image = sel.remove_mask(layer.image, self.to_layer_space(self.selection))
        self.commit_edit(layer)

    def selected_image(self):
        """Copy of the selected pixels of the active layer (document space) and its origin."""
        image = self.layer_in_document_space()
        if self.selection is not None:
            image = sel.clip_to_mask(image, self.selection)
            rect = sel.bounds(self.selection_values)
        else:
            rect = sel.bounds(sel.alpha(image))
        if rect.isEmpty():
            return None, QPoint()
        return image.copy(rect), rect.topLeft()

    def transform_content(self, angle=0., flip_h=False, flip_v=False):
        layer = self.editable_layer()
        if layer is None:
            return
        self.finish_stroke()
        if self.selection is not None:
            center = QRectF(sel.bounds(self.selection_values)).center()
            mask = self.to_layer_space(self.selection)
            floating, hole = sel.clip_to_mask(layer.image, mask), sel.remove_mask(layer.image, mask)
        else:
            center = self.document_rect().center()
            floating, hole = QImage(layer.image), QImage(layer.image.size(), layer.image.format())
            hole.fill(0)
        transform = QTransform()
        transform.translate(center.x(), center.y())
        transform.rotate(angle)
        transform.scale(-1 if flip_h else 1, -1 if flip_v else 1)
        transform.translate(-center.x(), -center.y())
        self.document.checkpoint()
        painter = QPainter(hole)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, abs(angle) % 90 > 1e-6)
        painter.setTransform(transform)
        painter.drawImage(0, 0, floating)
        painter.end()
        layer.image = hole
        if self.selection is not None:
            moved = sel.transformed(self.selection, transform, self.document.width, self.document.height)
            path = transform.map(self.selection_path) if self.selection_path is not None else None
            self.set_selection(sel.alpha(moved), path)
        self.commit_edit(layer)

    # ------------------------------------------------------------- move tool

    def begin_move(self, position):
        layer = self.editable_layer()
        if layer is None:
            return
        self.document.checkpoint()
        if self.selection is not None:
            mask = self.to_layer_space(self.selection)
            floating, hole = sel.clip_to_mask(layer.image, mask), sel.remove_mask(layer.image, mask)
        else:
            floating, hole = QImage(layer.image), QImage(layer.image.size(), layer.image.format())
            hole.fill(0)
        inverse = self.active_transform().inverted()[0]
        self.move_state = {'layer': layer, 'floating': floating, 'hole': hole, 'inverse': inverse,
                           'start': self.to_document(position), 'offset': QPoint(), 'doc_offset': QPointF()}

    def update_move(self, position, modifiers):
        state = self.move_state
        delta = self.to_document(position) - state['start']
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            delta = QPointF(delta.x(), 0) if abs(delta.x()) >= abs(delta.y()) else QPointF(0, delta.y())
        delta = QPointF(round(delta.x()), round(delta.y()))
        state['doc_offset'] = delta
        local = state['inverse'].map(state['start'] + delta) - state['inverse'].map(state['start'])
        offset = QPoint(round(local.x()), round(local.y()))
        if offset == state['offset'] and state.get('drawn'):
            return
        state['offset'], state['drawn'] = offset, True
        image = QImage(state['hole'])
        painter = QPainter(image)
        painter.drawImage(offset, state['floating'])
        painter.end()
        state['layer'].image = image
        self.update()

    def finish_move(self):
        state, self.move_state = self.move_state, None
        if not state:
            return
        if not state.get('drawn'):
            self.document.undo_stack.pop()
            self.update()
            return
        offset = state['doc_offset']
        if self.selection is not None and not offset.isNull():
            shift = QTransform.fromTranslate(offset.x(), offset.y())
            moved = sel.transformed(self.selection, shift, self.document.width, self.document.height)
            path = shift.map(self.selection_path) if self.selection_path is not None else None
            self.set_selection(sel.alpha(moved), path)
        self.commit_edit(state['layer'])

    # ------------------------------------------------------------ guide tools

    def guide_handles(self):
        view = self.transform()
        aids = self.document.guides
        handles = [('point', index, view.map(QPointF(x, y))) for index, (x, y) in enumerate(aids['points'])]
        if aids.get('ruler'):
            x1, y1, x2, y2 = aids['ruler']
            handles += [('ruler', 0, view.map(QPointF(x1, y1))), ('ruler', 1, view.map(QPointF(x2, y2)))]
        return handles

    def handle_at(self, position, kind):
        best = None
        for handle_kind, index, point in self.guide_handles():
            distance = math.hypot(point.x() - position.x(), point.y() - position.y())
            if handle_kind == kind and distance <= 12 and (best is None or distance < best[1]):
                best = (index, distance)
        return None if best is None else best[0]

    def press_guide(self, position, remove=False):
        aids = self.document.guides
        point = self.to_document(position)
        if self.tool == 'perspective':
            index = self.handle_at(position, 'point')
            if remove:
                if index is not None:
                    aids['points'].pop(index)
                    self.guides_edited()
                return
            if index is None:
                if len(aids['points']) >= 3:
                    index = min(range(3), key=lambda i: math.hypot(aids['points'][i][0] - point.x(), aids['points'][i][1] - point.y()))
                else:
                    aids['points'].append([point.x(), point.y()])
                    index = len(aids['points']) - 1
            aids['perspective_visible'] = True
            self.guide_drag = ('point', index)
        else:
            index = self.handle_at(position, 'ruler')
            if remove:
                aids['ruler'] = None
                self.guides_edited()
                return
            if index is None:
                aids['ruler'] = [point.x(), point.y(), point.x(), point.y()]
                index = 1
            self.guide_drag = ('ruler', index)
        self.drag_guide(position)

    def drag_guide(self, position, modifiers=Qt.KeyboardModifier.NoModifier):
        kind, index = self.guide_drag
        point = self.to_document(position)
        aids = self.document.guides
        if kind == 'point':
            aids['points'][index] = [point.x(), point.y()]
        else:
            ruler = aids['ruler']
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                ox, oy = ruler[2 - 2 * index], ruler[3 - 2 * index]
                angle = round(math.atan2(point.y() - oy, point.x() - ox) / (math.pi / 12)) * math.pi / 12
                length = math.hypot(point.x() - ox, point.y() - oy)
                point = QPointF(ox + math.cos(angle) * length, oy + math.sin(angle) * length)
            ruler[2 * index:2 * index + 2] = [point.x(), point.y()]
        self.update()

    def finish_guide(self):
        if self.guide_drag:
            ruler = self.document.guides.get('ruler')
            if ruler and math.hypot(ruler[2] - ruler[0], ruler[3] - ruler[1]) < 2:
                self.document.guides['ruler'] = None
            self.guide_drag = None
            self.guides_edited()

    def guides_edited(self):
        self.document.changed()
        self.changed.emit()
        self.update()

    # --------------------------------------------------------- interactions

    def press(self, position, pressure, modifiers):
        tool = self.tool
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        if tool == 'balloon':
            point = self.to_document(position)
            self.shape_drag = {'tool': 'balloon', 'kind': None, 'start': point, 'current': point, 'points': []}
            self.update()
        elif tool == 'panel':
            self.parent_app.select_panel_at(self.to_document(position), self.selection_mode(modifiers))
        elif tool in DRAG_TOOLS:
            point = self.to_document(position)
            kind = self.option('shape_kind', 'line') if tool == 'shape' else None
            if kind == 'polygon' and self.shape_drag:
                self.shape_drag['points'].append(point)
                self.shape_drag['current'] = point
            else:
                self.shape_drag = {'tool': tool, 'kind': kind, 'start': point, 'current': point,
                                   'points': [point] if kind == 'polygon' else []}
            self.update()
        elif tool == 'text':
            self.parent_app.place_text(self.to_document(position))
        elif tool == 'symmetry':
            self.symmetry_drag = True
            self.drag_symmetry(position)
        elif tool == 'reference':
            if self.reference:
                self.reference_drag = (self.to_document(position), QPointF(self.reference['position']))
            else:
                self.message.emit('Carregue uma imagem de referência em Guias → Imagem de referência.')
        elif tool == 'bone':
            self.press_bone(position, modifiers)
        elif tool == 'rotate':
            center = QPointF(self.width() / 2, self.height() / 2) + self.pan
            self.rotating = (math.atan2(position.y() - center.y(), position.x() - center.x()), self.rotation, center)
        elif tool == 'picker' or (ctrl and tool in PAINT_TOOLS + ('fill',)):
            self.pick_color(position)
        elif tool in PAINT_TOOLS:
            if modifiers & Qt.KeyboardModifier.ShiftModifier and self.last_stroke_end is not None:
                if self.begin_stroke(self.transform().map(self.last_stroke_end), pressure):
                    self.finish_stroke(position, pressure)
                return
            self.begin_stroke(position, pressure)
        elif tool == 'fill':
            self.fill_at(position)
        elif tool == 'wand':
            self.wand_at(position, self.selection_mode(modifiers))
        elif tool in SELECT_TOOLS:
            point = self.to_document(position)
            self.selection_drag = {'tool': tool, 'start': point, 'current': point, 'points': [point],
                                   'mode': self.selection_mode(modifiers), 'square': ctrl}
        elif tool == 'move':
            self.begin_move(position)
        elif tool in GUIDE_TOOLS:
            self.press_guide(position)

    def drag_symmetry(self, position):
        point = self.to_document(position)
        symmetry = self.document.guides.setdefault('symmetry', {'mode': 'none', 'count': 6})
        symmetry['x'], symmetry['y'] = point.x(), point.y()
        if symmetry.get('mode', 'none') == 'none':
            symmetry['mode'] = 'vertical'
        self.update()

    def drag(self, position, pressure, modifiers):
        if self.shape_drag:
            self.shape_drag['current'] = self.to_document(position)
            self.shape_drag['constrain'] = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            self.shape_drag['center'] = bool(modifiers & Qt.KeyboardModifier.AltModifier)
            self.update()
        elif self.symmetry_drag:
            self.drag_symmetry(position)
        elif self.reference_drag:
            start, origin = self.reference_drag
            self.reference['position'] = origin + self.to_document(position) - start
            self.update()
        elif self.rig_drag:
            self.drag_bone(position)
        elif self.drawing:
            self.move_stroke(position, pressure)
        elif self.selection_drag:
            point = self.to_document(position)
            self.selection_drag['current'] = point
            self.selection_drag['square'] = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            if self.selection_drag['tool'] == 'lasso':
                last = self.selection_drag['points'][-1]
                if (point - last).manhattanLength() * self.zoom >= 2:
                    self.selection_drag['points'].append(point)
        elif self.move_state:
            self.update_move(position, modifiers)
        elif self.rotating:
            angle, origin, center = self.rotating
            current = math.atan2(position.y() - center.y(), position.x() - center.x())
            value = origin + math.degrees(current - angle)
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                value = round(value / 15) * 15
            self.set_rotation(value)
        elif self.guide_drag:
            self.drag_guide(position, modifiers)

    def release(self, position, pressure=None):
        if self.shape_drag and self.shape_drag['tool'] == 'balloon':
            drag, self.shape_drag = self.shape_drag, None
            end = self.to_document(position)
            moved = (self.transform().map(end) - self.transform().map(drag['start'])).manhattanLength() > 12
            self.update()
            self.parent_app.place_balloon(drag['start'], end if moved else None)
        if self.shape_drag and not (self.shape_drag['tool'] == 'shape' and self.shape_drag['kind'] == 'polygon'):
            self.shape_drag['current'] = self.to_document(position)
            self.commit_shape()
        if self.symmetry_drag:
            self.symmetry_drag = False
            self.guides_edited()
        self.reference_drag = None
        if self.rig_drag:
            self.release_bone(position)
        if self.selection_drag:
            self.selection_drag['current'] = self.to_document(position)
            self.commit_selection_drag()
        self.finish_move()
        self.finish_guide()
        self.rotating = None
        self.finish_stroke(position, pressure)

    def finish_interaction(self):
        self.finish_stroke()
        self.selection_drag = None
        self.finish_move()
        self.finish_guide()
        if self.rig_drag:
            self.release_bone(None)
        self.rotating = None

    # --------------------------------------------------------------- skeleton

    def select_bone(self, ident):
        if ident != self.selected_bone:
            self.selected_bone = ident
            self.bone_selected.emit()
        self.update()

    def press_bone(self, position, modifiers):
        document, frame = self.document, self.document.current_frame
        point = self.to_document(position)
        hit = rig.hit_test(document, frame, self.transform(), position)
        if hit and modifiers & Qt.KeyboardModifier.ControlModifier and self.option('rig_template', 'free') == 'free':
            hit = None  # Ctrl + drag from a tip creates a child bone
        if hit:
            bone, part = hit
            self.select_bone(bone['id'])
            if self.option('rig_mode', 'pose') == 'edit':
                mode = 'rest_tip' if part == 'tip' else 'rest_move'
            elif modifiers & Qt.KeyboardModifier.ShiftModifier or (part == 'start' and not bone.get('parent')):
                mode = 'translate'
            elif modifiers & Qt.KeyboardModifier.AltModifier and bone.get('parent'):
                mode = 'ik_self'
            elif part == 'tip' and rig.is_limb_end(bone) and self.option('auto_ik', True) and bone.get('parent'):
                mode = 'ik_limb'
            else:
                mode = 'rotate'
            tip = rig.world_points(document, bone, frame)[1]
            document.checkpoint()
            self.rig_drag = {'mode': mode, 'bone': bone, 'last': point, 'offset': tip - point, 'moved': False}
            return
        template = self.option('rig_template', 'free')
        parent, start = None, point
        if template == 'free':
            parent, tip = rig.nearest_tip(document, frame, self.transform(), position)
            start = tip if parent else point
        self.rig_drag = {'mode': 'create' if template == 'free' else 'template', 'start': start,
                         'current': point, 'parent': parent['id'] if parent else '', 'template': template}

    def drag_bone(self, position):
        drag = self.rig_drag
        document, frame = self.document, self.document.current_frame
        point = self.to_document(position)
        mode, bone = drag['mode'], drag.get('bone')
        if mode in ('create', 'template'):
            drag['current'] = point
        elif mode == 'rotate':
            rig.rotate_towards(document, bone, frame, drag['last'], point)
        elif mode == 'translate':
            rig.translate(document, bone, frame, point - drag['last'])
        elif mode in ('ik_self', 'ik_limb'):
            rig.solve_ik(document, bone, frame, point + drag['offset'], include_self=mode == 'ik_self')
        elif mode == 'rest_tip':
            rig.edit_rest_tip(document, bone, frame, point)
        elif mode == 'rest_move':
            rig.edit_rest_move(document, bone, frame, point - drag['last'])
        drag['last'] = point
        drag['moved'] = True
        self.update()

    def release_bone(self, position):
        drag, self.rig_drag = self.rig_drag, None
        document, frame = self.document, self.document.current_frame
        if position is not None and drag['mode'] in ('create', 'template'):
            drag['current'] = self.to_document(position)
        if drag['mode'] == 'create':
            view = self.transform()
            if (view.map(drag['current']) - view.map(drag['start'])).manhattanLength() < 5 or position is None:
                self.update()
                return
            document.checkpoint()
            bone = rig.create_bone(document, drag['start'], drag['current'], frame, drag['parent'])
            self.select_bone(bone['id'])
        elif drag['mode'] == 'template':
            if position is None:
                return
            view = self.transform()
            rect = QRectF(drag['start'], drag['current']).normalized()
            if view.mapRect(rect).width() < 12 and view.mapRect(rect).height() < 12:
                rect = rig.fit_rect(document, drag['start'])
            document.checkpoint()
            created = rig.add_template(document, drag['template'], rect)
            self.select_bone(created[0]['id'])
            self.message.emit(f'{len(created)} ossos criados. Arraste um osso para girar; Alt + arrastar usa IK; '
                              'use o painel Esqueleto para criar camadas das partes.')
        elif not drag['moved']:
            document.undo_stack.pop()
            self.update()
            return
        document.changed()
        self.changed.emit()
        self.update()

    def paint_bones(self, painter, view, accent):
        document, frame = self.document, self.document.current_frame
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        labels = []
        for bone in document.scene['bones']:
            start, end = (view.map(p) for p in rig.world_points(document, bone, frame))
            length = math.hypot(end.x() - start.x(), end.y() - start.y())
            selected, hovered = bone['id'] == self.selected_bone, bone['id'] == self.hover_bone
            fill = QColor(accent) if selected else QColor(255, 255, 255, 215 if hovered else 150)
            if not bone.get('layer') and not selected:
                fill.setAlpha(90)
            painter.setPen(QPen(QColor(18, 20, 26, 230), 1.4))
            painter.setBrush(fill)
            if length > 1:
                ux, uy = (end.x() - start.x()) / length, (end.y() - start.y()) / length
                width = min(9., max(2.5, length * .11))
                middle = QPointF(start.x() + (end.x() - start.x()) * .18, start.y() + (end.y() - start.y()) * .18)
                painter.drawPolygon(QPolygonF([start, middle + QPointF(-uy, ux) * width, end, middle - QPointF(-uy, ux) * width]))
            painter.drawEllipse(start, 6 if not bone.get('parent') else 3.5, 6 if not bone.get('parent') else 3.5)
            painter.setBrush(QColor('white'))
            painter.drawEllipse(end, 3, 3)
            if selected or hovered:
                labels.append((tr(bone['name']), (start + end) / 2))
        for name, point in labels:
            box = QRectF(point.x() + 8, point.y() - 9, painter.fontMetrics().horizontalAdvance(name) + 10, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(20, 22, 28, 210))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor('white'))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, name)
        drag = self.rig_drag
        if drag and drag['mode'] == 'create':
            painter.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            painter.drawLine(view.map(drag['start']), view.map(drag['current']))
        elif drag and drag['mode'] == 'template':
            painter.setPen(QPen(accent, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(view.map(QPolygonF(QRectF(drag['start'], drag['current']).normalized())))
        painter.restore()

    def preview_image(self, width, height):
        """Small composite (for the navigator) taken from the cached view."""
        document = self.document
        scale = min(width / document.width, height / document.height, 1.)
        image = self.scene_view.image(document, display.level_for(scale))
        return image.scaled(max(1, round(document.width * scale)), max(1, round(document.height * scale)),
                            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def pick_color(self, position):
        point = self.to_document(position)
        image = self.document.composite()
        x, y = int(math.floor(point.x())), int(math.floor(point.y()))
        if image.rect().contains(x, y):
            color = image.pixelColor(x, y)
            if color.alpha():
                color.setAlpha(255)
                self.color_picked.emit(color)

    def start_pan(self, position):
        self.finish_stroke()
        self.panning = True
        self.pan_origin = position
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mousePressEvent(self, event):
        self.setFocus()
        if self.tablet_down:
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and (self.space_down or self.tool == 'hand')):
            self.start_pan(event.position())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.press(event.position(), 1., event.modifiers())
        elif event.button() == Qt.MouseButton.RightButton and self.tool in GUIDE_TOOLS:
            self.press_guide(event.position(), remove=True)
        elif event.button() == Qt.MouseButton.RightButton and self.tool == 'bone':
            hit = rig.hit_test(self.document, self.document.current_frame, self.transform(), event.position())
            if hit:
                self.select_bone(hit[0]['id'])
                self.parent_app.bone_menu(hit[0], event.globalPosition().toPoint())
        event.accept()

    def mouseMoveEvent(self, event):
        self.cursor_pos = event.position()
        if self.tablet_down:
            event.accept()
            return
        if self.panning:
            self.pan += event.position() - self.pan_origin
            self.pan_origin = event.position()
            self.view_changed.emit()
        elif (self.drawing or self.selection_drag or self.move_state or self.rotating or self.guide_drag or self.rig_drag
              or self.shape_drag or self.symmetry_drag or self.reference_drag):
            self.drag(event.position(), 1., event.modifiers())
        elif self.tool == 'bone':
            hit = rig.hit_test(self.document, self.document.current_frame, self.transform(), event.position())
            self.hover_bone = hit[0]['id'] if hit else None
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.CrossCursor)
        if self.drawing or not (self.panning or self.selection_drag or self.move_state or self.rotating
                                or self.guide_drag or self.rig_drag or self.shape_drag or self.symmetry_drag
                                or self.reference_drag or self.tool == 'bone'):
            self.update_cursor_area()
        else:
            self.update()

    def mouseReleaseEvent(self, event):
        if self.tablet_down:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.release(event.position())
        if self.panning:
            self.panning = False
            self.update_cursor()
        event.accept()

    def tabletEvent(self, event):
        self.cursor_inside = True
        self.cursor_pos = event.position()
        if event.type() == QEvent.Type.TabletPress:
            self.setFocus()
            if self.tool == 'hand' or self.space_down:
                self.panning = True
                self.pan_origin = event.position()
            else:
                self.press(event.position(), event.pressure(), event.modifiers())
            self.tablet_down = True
        elif event.type() == QEvent.Type.TabletMove:
            if self.panning:
                self.pan += event.position() - self.pan_origin
                self.pan_origin = event.position()
                self.view_changed.emit()
            elif self.tablet_down:
                self.drag(event.position(), event.pressure(), event.modifiers())
        elif event.type() == QEvent.Type.TabletRelease:
            if not self.panning:
                self.release(event.position(), event.pressure())
            self.tablet_down = self.panning = False
            self.update_cursor()
        # Accept tablet events so Qt does not draw a duplicate mouse stroke.
        event.accept()
        if self.drawing or event.type() == QEvent.Type.TabletMove and not (self.panning or self.tablet_down):
            self.update_cursor_area()
        else:
            self.update()

    def mouseDoubleClickEvent(self, event):
        if self.shape_drag and self.shape_drag['kind'] == 'polygon':
            self.commit_shape()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if self.tool == 'reference' and self.reference and delta:
            self.reference['scale'] = max(.02, min(20., self.reference['scale'] * 1.1 ** (delta / 120)))
            self.update()
            event.accept()
            return
        if delta:
            self.set_zoom(self.zoom * 1.15 ** (delta / 120), event.position())
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space_down = True
            self.update_cursor()
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.document.animation_enabled:
            self.parent_app.timeline.toggle_play()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and self.shape_drag:
            self.shape_drag = None
            self.update()
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.shape_drag:
            self.commit_shape()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            if self.selection_drag:
                self.selection_drag = None
                self.update()
            else:
                self.set_selection(None)
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_down = False
            self.update_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.finish_interaction()
        self.space_down = self.panning = self.tablet_down = False
        self.update_cursor()
        super().focusOutEvent(event)

    def enterEvent(self, event):
        self.cursor_inside = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.cursor_inside = False
        self.update()
        super().leaveEvent(event)
