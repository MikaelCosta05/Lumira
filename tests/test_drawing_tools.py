import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QApplication

import display
import drawing_tools
import guides
import text_ui
from document import Document
from main import MainWindow
from stabilizer import Sample


class DrawingToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.canvas.set_document(Document(200, 200))

    def tearDown(self):
        self.canvas.finish_interaction()
        self.canvas.document.saved_revision = self.canvas.document.revision
        self.window.close()
        self.app.processEvents()

    def position(self, x, y):
        return self.canvas.transform().map(QPointF(x, y))

    def drag(self, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
        self.canvas.press(self.position(*start), 1., modifiers)
        self.canvas.drag(self.position(*end), 1., modifiers)
        self.canvas.release(self.position(*end))

    def stroke(self, points):
        self.canvas.begin_stroke(self.position(*points[0]), 1., 100)
        for n, point in enumerate(points[1:], 1):
            self.canvas.move_stroke(self.position(*point), 1., 100 + n * .02)
        self.canvas.finish_stroke(self.position(*points[-1]), 1., 100 + len(points) * .02)

    def alpha(self, x, y):
        return self.canvas.image.pixelColor(x, y).alpha()

    # ----------------------------------------------------------- shapes

    def test_shape_tool_draws_outline_and_fill(self):
        self.window.set_tool('shape')
        self.window.brush_size = 4
        self.window.tool_options['shape_kind'] = 'rect'
        self.drag((40, 40), (120, 120))
        self.assertGreater(self.alpha(40, 80), 0)
        self.assertEqual(self.alpha(80, 80), 0)
        self.window.undo()
        self.assertEqual(self.alpha(40, 80), 0)
        self.window.tool_options['shape_fill'] = 'fill'
        self.window.tool_options['shape_kind'] = 'ellipse'
        self.drag((40, 40), (120, 120))
        self.assertGreater(self.alpha(80, 80), 0)
        self.assertEqual(self.alpha(42, 42), 0)

    def test_shape_paths(self):
        start, end = QPointF(10, 10), QPointF(50, 30)
        square = drawing_tools.shape_path('rect', start, end, constrain=True).boundingRect()
        self.assertAlmostEqual(square.width(), square.height())
        centered = drawing_tools.shape_path('ellipse', start, end, from_center=True).boundingRect()
        self.assertAlmostEqual(centered.center().x(), 10)
        for kind in ('line', 'rounded', 'star', 'arrow'):
            self.assertFalse(drawing_tools.shape_path(kind, start, end).isEmpty(), kind)
        polygon = drawing_tools.shape_path('polygon', start, end, points=[start, QPointF(40, 10)])
        self.assertFalse(polygon.isEmpty())

    def test_polygon_closes_on_enter(self):
        self.window.set_tool('shape')
        self.window.tool_options['shape_kind'] = 'polygon'
        self.window.tool_options['shape_fill'] = 'fill'
        for point in ((30, 30), (150, 30), (90, 150)):
            self.canvas.press(self.position(*point), 1., Qt.KeyboardModifier.NoModifier)
            self.canvas.release(self.position(*point))
        self.assertEqual(self.alpha(90, 60), 0)
        self.canvas.commit_shape()
        self.assertGreater(self.alpha(90, 60), 0)

    def test_gradient_tool(self):
        self.window.set_tool('gradient')
        self.window.current_color = QColor('#ff0000')
        self.window.secondary_color = QColor('#0000ff')
        self.drag((0, 100), (199, 100))
        left, right = self.canvas.image.pixelColor(2, 50), self.canvas.image.pixelColor(197, 50)
        self.assertGreater(left.red(), left.blue())
        self.assertGreater(right.blue(), right.red())
        self.assertEqual(left.alpha(), 255)

    def test_gradient_respects_selection(self):
        image = QImage(100, 100, drawing_tools.FORMAT)
        image.fill(0)
        mask = QImage(100, 100, drawing_tools.FORMAT)
        mask.fill(0)
        painter = QPainter(mask)
        painter.fillRect(QRect(0, 0, 50, 100), QColor('white'))
        painter.end()
        drawing_tools.paint_gradient(image, QPointF(0, 0), QPointF(100, 0), 'radial', QColor('red'), QColor('blue'),
                                     mask=mask)
        self.assertGreater(image.pixelColor(20, 20).alpha(), 0)
        self.assertEqual(image.pixelColor(80, 20).alpha(), 0)

    # ------------------------------------------------------ smudge / blur

    def test_blur_and_smudge_change_pixels(self):
        image = self.canvas.image
        painter = QPainter(image)
        painter.fillRect(QRect(0, 0, 100, 200), QColor('black'))
        painter.end()
        before = image.pixelColor(100, 100)
        self.window.set_tool('blur')
        self.window.brush_size = 30
        self.stroke([(100, 60), (100, 100), (100, 140)])
        self.assertNotEqual(image.pixelColor(100, 100), before)
        self.window.undo()
        self.assertEqual(self.canvas.image.pixelColor(101, 100).alpha(), 0)
        effect = drawing_tools.EffectStroke(self.canvas.image, 'smudge', 1.)
        samples = [Sample(90 + i * 4, 100, 1., i) for i in range(10)]
        effect.stroke(samples, lambda sample: 20)
        self.assertGreater(self.canvas.image.pixelColor(110, 100).alpha(), 0)

    # ------------------------------------------------------------- text

    def test_text_render_and_tool(self):
        font = QFont('Inter')
        font.setPixelSize(40)
        image = drawing_tools.render_text(QSize(300, 120), QPointF(10, 10), 'Olá\nmundo', font, QColor('black'),
                                          QColor('white'), 3)
        self.assertFalse(image.copy(QRect(0, 0, 300, 120)).isNull())
        alpha = [image.pixelColor(x, y).alpha() for x in range(0, 300, 3) for y in range(0, 120, 3)]
        self.assertGreater(max(alpha), 0)
        layers = len(self.canvas.document.layers)

        def accept(dialog):
            dialog.text.setPlainText('BOOM!')
            dialog.size.setValue(60)
            return True
        with mock.patch.object(text_ui.TextDialog, 'exec', accept):
            self.window.set_tool('text')
            self.canvas.press(self.position(20, 60), 1., Qt.KeyboardModifier.NoModifier)
            self.canvas.release(self.position(20, 60))
        self.assertEqual(len(self.canvas.document.layers), layers + 1)
        layer = self.canvas.document.layers[self.canvas.document.active]
        self.assertIn('BOOM', layer.name)
        self.assertTrue(any(layer.image.pixelColor(x, y).alpha() for x in range(20, 180, 2) for y in range(60, 130, 2)))
        self.window.undo()
        self.assertEqual(len(self.canvas.document.layers), layers)

    # --------------------------------------------------------- symmetry

    def test_symmetry_transforms(self):
        for mode, count in (('none', 1), ('vertical', 2), ('horizontal', 2), ('both', 4), ('radial', 6), ('mandala', 12)):
            transforms = guides.symmetry_transforms({'mode': mode, 'count': 6}, 200, 100)
            self.assertEqual(len(transforms), count, mode)
        vertical = guides.symmetry_transforms({'mode': 'vertical'}, 200, 100)[1]
        self.assertEqual(vertical.map(QPointF(20, 30)), QPointF(180, 30))

    def test_symmetric_stroke_paints_mirror(self):
        self.window.set_tool('symmetry')
        self.drag((100, 100), (100, 100))
        symmetry = self.canvas.document.guides['symmetry']
        self.assertEqual(symmetry['mode'], 'vertical')
        self.window.set_tool('brush')
        self.window.brush_size = 6
        self.stroke([(30, 50), (40, 60), (50, 70)])
        self.assertGreater(self.alpha(40, 60), 0)
        self.assertGreater(self.alpha(160, 60), 0)
        self.window.set_symmetry(mode='none')
        self.assertEqual(self.canvas.document.guides['symmetry']['mode'], 'none')

    # ------------------------------------------------- overlays and views

    def test_reference_image_overlay(self):
        image = QImage(50, 50, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('red'))
        self.canvas.load_reference(image)
        self.window.set_tool('reference')
        start = QPointF(self.canvas.reference['position'])
        self.drag((20, 20), (40, 50))
        self.assertAlmostEqual(self.canvas.reference['position'].x(), start.x() + 20, delta=.5)
        self.window.set_reference(opacity=.3, behind=True)
        self.assertTrue(self.canvas.reference['behind'])
        self.canvas.grab()
        self.assertEqual(self.alpha(30, 30), 0)  # never written into the layer
        self.window.remove_reference()
        self.assertIsNone(self.canvas.reference)

    def test_flip_grayscale_composition_and_iso_grid(self):
        point = QPointF(30, 40)
        normal = self.canvas.transform().map(point)
        self.window.flip_action.trigger()
        flipped = self.canvas.transform().map(point)
        self.assertNotAlmostEqual(normal.x(), flipped.x())
        self.assertAlmostEqual(self.canvas.to_document(flipped).x(), 30, delta=.01)
        self.window.flip_action.trigger()
        image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#ff0000'))
        gray = display.grayscale(image).pixelColor(1, 1)
        self.assertEqual(gray.red(), gray.green())
        self.window.grayscale_action.trigger()
        for value in [v for _, v in guides.COMPOSITIONS]:
            self.window.set_composition(value)
            self.canvas.grab()
        self.window.grid_iso_action.trigger()
        self.assertEqual(self.canvas.grid_kind, 'iso')
        self.canvas.grab()

    # ---------------------------------------------------------- timeline

    def test_frame_operations_keep_keys_and_tags(self):
        document = Document(40, 40)
        for _ in range(4):
            document.add_frame()
        marks = []
        for index, frame in enumerate(document.frames):
            frame.layers[0].name = f'f{index}'
            marks.append(frame)
        document.scene['tags'].append({'name': 'run', 'from': 1, 'to': 2, 'color': '#ff0000'})
        document.move_frame(0, 3)
        self.assertEqual([f.layers[0].name for f in document.frames], ['f1', 'f2', 'f3', 'f0', 'f4'])
        self.assertEqual((document.scene['tags'][0]['from'], document.scene['tags'][0]['to']), (0, 1))
        document.reverse_frames(0, 4)
        self.assertEqual([f.layers[0].name for f in document.frames], ['f4', 'f0', 'f3', 'f2', 'f1'])
        document.duplicate_frames(1, 2)
        self.assertEqual(len(document.frames), 7)
        self.assertEqual(document.current_frame, 3)
        document.delete_frames(0, 2)
        self.assertEqual(len(document.frames), 4)
        with self.assertRaises(ValueError):
            document.delete_frames(0, 3)
        document.set_fps(24)
        self.assertTrue(all(frame.duration == 42 for frame in document.frames))
        document.onion_before, document.onion_after, document.onion_opacity = 3, 2, .5
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'anim.sdp'
            document.save(path)
            loaded = Document.load(path)
        self.assertEqual((loaded.onion_before, loaded.onion_after, loaded.onion_opacity), (3, 2, .5))

    def test_timeline_widget_operations(self):
        timeline = self.window.timeline
        document = self.canvas.document
        for _ in range(2):
            document.add_frame()
        timeline.refresh()
        timeline.select(0)
        self.window.insert_inbetween()
        self.assertEqual(len(self.canvas.document.frames), 4)
        timeline.fps.setValue(12)
        timeline.change_fps()
        self.assertEqual(self.canvas.document.frames[0].duration, 83)
        self.window.undo()
        self.assertEqual(self.canvas.document.frames[0].duration, 100)
        timeline.view.grab()


if __name__ == '__main__':
    unittest.main()
