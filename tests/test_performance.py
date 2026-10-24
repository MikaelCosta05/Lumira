import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import math
import unittest

import numpy as np
from PyQt6.QtCore import QPointF, QRect
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication

import display
from document import Document
from main import MainWindow


def same(a, b):
    a, b = a.convertToFormat(display.FORMAT), b.convertToFormat(display.FORMAT)
    return a.size() == b.size() and np.array_equal(display.pixels(a), display.pixels(b))


def reference_reduce(image, factor):
    data = display.pixels(image)
    height, width = data.shape[:2]
    out_w, out_h = -(-width // factor), -(-height // factor)
    padded = np.zeros((out_h * factor, out_w * factor, 4), np.uint8)
    padded[:height, :width] = data
    summed = padded.reshape(out_h, factor, out_w, factor, 4).sum(axis=(1, 3), dtype=np.uint32)
    return ((summed + factor * factor // 2) // (factor * factor)).astype(np.uint8)


class CachedViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.resize(1200, 800)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        document = Document(400, 300)
        for index in range(3):
            document.layers.append(document.blank_layer(f'L{index}'))
        for index, layer in enumerate(document.layers):
            painter = QPainter(layer.image)
            painter.fillRect(20 + index * 30, 20 + index * 20, 220, 160, QColor(60 * index, 120, 200 - 40 * index, 160))
            painter.end()
            layer.content = True
        document.active = 3
        self.canvas.set_document(document)
        self.app.processEvents()

    def tearDown(self):
        self.canvas.finish_interaction()
        self.canvas.document.saved_revision = self.canvas.document.revision
        self.window.close()
        self.app.processEvents()

    def stroke(self, cx=200, cy=150, size=14):
        self.window.set_tool('brush')
        self.window.size_spin.setValue(size)
        transform = self.canvas.transform()
        points = [(cx + 90 * math.cos(t / 6), cy + 60 * math.sin(t / 4)) for t in range(40)]
        self.canvas.begin_stroke(transform.map(QPointF(*points[0])), .8)
        for n, point in enumerate(points[1:]):
            self.canvas.move_stroke(transform.map(QPointF(*point)), .5 + .4 * math.sin(n))
            if n % 5 == 0:
                self.canvas.repaint()
        self.canvas.finish_stroke(transform.map(QPointF(*points[-1])), .6)
        self.canvas.repaint()

    def assert_view_matches(self, edge_pixels=0):
        """The cached view equals a full render. Rotated/scaled layers may differ only in a few
        isolated pixels on their aliased outer edge (Qt rasterizes those per clip)."""
        document = self.canvas.document
        cached = self.canvas.scene_view.image(document).convertToFormat(display.FORMAT)
        full = document.composite(paper=False).convertToFormat(display.FORMAT)
        differing = np.count_nonzero(np.any(display.pixels(cached) != display.pixels(full), axis=2))
        self.assertLessEqual(differing, edge_pixels)

    def test_blend_modes_refresh_only_touched_area_but_match_full_render(self):
        self.canvas.document.layers[1].blend = 'multiply'
        self.canvas.document.layers[2].blend = 'screen'
        self.canvas.repaint()
        self.stroke()
        self.assert_view_matches()
        self.canvas.document.active = 1
        self.stroke(150, 120, 30)
        self.assert_view_matches()

    def test_animation_with_camera_and_layer_motion_matches_full_render(self):
        self.window.animation_workspace()
        document = self.canvas.document
        document.scene['camera'] = [{'frame': 0, 'x': 13.5, 'y': -7., 'zoom': 1.15, 'angle': 4., 'shake': 0.}]
        document.scene['layers'][document.layers[3].id] = [{'frame': 0, 'x': 17., 'y': 9., 'angle': 11., 'scale': .9,
                                                            'opacity': .8, 'parallax': .6}]
        document.changed()
        self.canvas.repaint()
        self.stroke()
        self.assert_view_matches(edge_pixels=8)
        self.window.new_frame()
        self.canvas.repaint()
        self.stroke(220, 160)
        self.assert_view_matches(edge_pixels=8)
        self.window.undo()
        self.canvas.repaint()
        self.assert_view_matches(edge_pixels=8)

    def test_grayscale_and_reduced_levels_stay_exact(self):
        self.canvas.document.layers[2].blend = 'multiply'
        self.canvas.set_zoom(.3)
        self.window.grayscale_action.trigger()
        self.canvas.repaint()
        level = display.level_for(self.canvas.zoom * self.canvas.devicePixelRatioF())
        self.assertGreater(level, 0)
        self.stroke()
        document = self.canvas.document
        gray = self.canvas.gray_view.image(document)
        self.assertTrue(same(gray, display.grayscale(document.composite(paper=True))))
        reduced = self.canvas.scene_view.image(document, level)
        expected = reference_reduce(document.composite(paper=False).convertToFormat(display.FORMAT), 1 << level)
        self.assertTrue(np.array_equal(display.pixels(reduced), expected))

    def test_playback_frames_are_cached_and_edits_invalidate(self):
        self.window.animation_workspace()
        for _ in range(3):
            self.window.new_frame()
        view = self.canvas.scene_view
        document = self.canvas.document
        for index in range(len(document.frames)):
            document.current_frame = index
            view.image(document)
        self.assertGreaterEqual(len(view.states), len(document.frames))
        document.current_frame = 0
        first = view.image(document)
        self.assertIs(view.image(document), first)
        painter = QPainter(document.layers[0].image)
        painter.fillRect(QRect(0, 0, 50, 50), QColor('red'))
        painter.end()
        document.changed()
        self.assertTrue(same(view.image(document), document.composite(paper=False)))

    def test_reduce_matches_reference_box_filter(self):
        rng = np.random.default_rng(3)
        data = rng.integers(0, 256, (157, 211, 4), dtype=np.uint8)
        data[..., :3] = np.minimum(data[..., :3], data[..., 3:4])
        image = display.from_pixels(data)
        for factor in (2, 3, 4, 8, 32):
            reduced = display.reduce(image, factor)
            self.assertTrue(np.array_equal(display.pixels(reduced), reference_reduce(image, factor)), factor)

    def test_hover_repaints_only_around_the_cursor(self):
        self.window.set_tool('brush')
        self.canvas.cursor_inside = True
        self.canvas.cursor_pos = QPointF(300, 300)
        area = self.canvas.cursor_area()
        radius = self.window.brush_size * self.canvas.zoom / 2
        self.assertTrue(area.contains(QRect(int(300 - radius), int(300 - radius), int(radius * 2), int(radius * 2))))
        self.assertLess(area.width(), self.canvas.width() / 2)

    def test_textured_stroke_is_the_same_however_often_the_view_repaints(self):
        """Stroke patches are composed once per repaint; the result must not depend on the rate."""
        import random
        from types import SimpleNamespace
        from unittest import mock
        import brush_engine
        results = []
        for per_paint in (1, 8):
            self.canvas.set_document(Document(500, 300))
            self.window.set_tool('brush')
            self.window.selected_brush = next(b for b in self.window.library.brushes if b.name == 'Aquarela')
            self.window.size_spin.setValue(50)
            transform = self.canvas.transform()
            points = [(250 + 160 * math.cos(k / 12), 150 + 90 * math.sin(k / 7)) for k in range(60)]
            seeded = SimpleNamespace(Random=lambda: random.Random(99))
            with mock.patch.object(brush_engine, 'random', seeded):
                self.canvas.begin_stroke(transform.map(QPointF(*points[0])), .7, 100)
                for n, point in enumerate(points[1:], 1):
                    self.canvas.move_stroke(transform.map(QPointF(*point)), .5 + .4 * math.sin(n / 5), 100 + n * .01)
                    if n % per_paint == 0:
                        self.canvas.repaint()
                self.canvas.finish_stroke(transform.map(QPointF(*points[-1])), .5, 101)
            image = self.canvas.image.convertToFormat(display.FORMAT)
            results.append(display.pixels(image).astype(int).copy())
            self.canvas.document.saved_revision = self.canvas.document.revision
        self.assertGreater(np.count_nonzero(results[0][..., 3]), 1000)
        self.assertLessEqual(np.abs(results[0] - results[1]).max(), 1)

    def test_navigator_uses_cached_preview(self):
        image = self.canvas.preview_image(200, 120)
        self.assertLessEqual(image.width(), 200)
        self.assertLessEqual(image.height(), 150)
        self.assertGreater(image.pixelColor(image.width() // 3, image.height() // 3).alpha(), 0)


if __name__ == '__main__':
    unittest.main()
