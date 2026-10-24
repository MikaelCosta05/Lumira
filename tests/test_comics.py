import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication

import comic_art
import comic_layouts
import comics
import comics_dialogs
from document import Document
from main import MainWindow

STYLE_KEYS = [key for _, key in comic_layouts.STYLES if key != 'random']


def segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0., min(1., ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def polygon_distance(first, second):
    """Distance between two non-overlapping convex polygons (vertex to edge, both ways)."""
    best = math.inf
    for polygon, other in ((first, second), (second, first)):
        for point in polygon:
            for a, b in zip(other, other[1:] + other[:1]):
                best = min(best, segment_distance(point, a, b))
    return best


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_style_fits_the_page_with_even_gutters(self):
        width, height, margin, gutter = 2480, 3508, 150, 50
        for style in STYLE_KEYS:
            for seed in range(6):
                used, shapes = comic_layouts.stylized_layout(width, height, style, seed, margin, gutter)
                self.assertEqual(used, style)
                self.assertGreaterEqual(len(shapes), 2 if style == 'splash' else 3, (style, seed))
                main = [[tuple(p) for p in item['points']] for item in shapes if not item.get('inset')]
                for item in shapes:
                    box = comic_layouts.shape_bounds(item)
                    self.assertTrue(QRectF(-.5, -.5, width + 1, height + 1).contains(box), (style, seed, box))
                for i, first in enumerate(main):
                    for second in main[i + 1:]:
                        self.assertGreaterEqual(polygon_distance(first, second), gutter * .98, (style, seed))

    def test_layouts_are_reproducible_and_follow_reading_direction(self):
        _, first = comic_layouts.stylized_layout(2000, 3000, 'action', 42, 100, 40)
        _, again = comic_layouts.stylized_layout(2000, 3000, 'action', 42, 100, 40)
        self.assertEqual(first, again)
        for style in ('classic', 'manga', 'action'):
            _, ltr = comic_layouts.stylized_layout(2000, 3000, style, 9, 100, 40, count=6)
            _, rtl = comic_layouts.stylized_layout(2000, 3000, style, 9, 100, 40, rtl=True, count=6)
            self.assertEqual(len(ltr), 6)
            boxes = [comic_layouts.shape_bounds(item) for item in ltr]
            centres = [box.center() for box in boxes]
            mirrored = [comic_layouts.shape_bounds(item).center() for item in rtl]

            def overlap(a, b):  # panels of one tier share most of their height (cuts may be slanted)
                return min(a.bottom(), b.bottom()) - max(a.top(), b.top()) > min(a.height(), b.height()) * .5
            same_tier = [i for i in range(5) if overlap(boxes[i], boxes[i + 1])]
            self.assertTrue(same_tier, style)
            i = same_tier[0]
            self.assertLess(centres[i].x(), centres[i + 1].x())
            self.assertGreater(mirrored[i].x(), mirrored[i + 1].x())

    def test_styles_have_their_character(self):
        def styles(style, seed=1):
            return [item['style'] for item in comic_layouts.stylized_layout(2000, 3000, style, seed, 100, 40)[1]]
        self.assertIn('jagged', styles('impact'))
        self.assertTrue(all(kind == 'wavy' for kind in styles('dream')))
        self.assertTrue(all(kind == 'round' for kind in styles('soft')))
        splash = comic_layouts.stylized_layout(2000, 3000, 'splash', 3, 100, 40)[1]
        self.assertTrue(splash[0]['bleed'] and all(item['inset'] for item in splash[1:]))
        inset_pages = [comic_layouts.stylized_layout(2000, 3000, 'inset', seed, 100, 40)[1] for seed in range(5)]
        self.assertTrue(any(item['inset'] for page in inset_pages for item in page))
        bleeding = [comic_layouts.stylized_layout(2000, 3000, 'cinema', seed, 100, 40)[1] for seed in range(5)]
        self.assertTrue(any(item['bleed'] for page in bleeding for item in page))
        for kind in ('straight', 'round', 'wavy', 'jagged'):
            item = comic_layouts.shape([(0, 0), (300, 0), (300, 200), (0, 200)], kind)
            path = comic_layouts.panel_path(item)
            self.assertTrue(path.contains(QPointF(150, 100)), kind)
            self.assertFalse(path.contains(QPointF(320, 100)), kind)

    def test_panel_layer_covers_gutters_and_keeps_panels_clear(self):
        _, shapes = comic_layouts.stylized_layout(800, 1200, 'action', 5, 40, 20)
        image = comics.render_shapes(800, 1200, shapes, 3, QColor('black'), QColor('white'))
        self.assertEqual(image.pixelColor(5, 5).alpha(), 255)
        centre = comic_layouts.shape_bounds(shapes[0]).center()
        self.assertEqual(image.pixelColor(int(centre.x()), int(centre.y())).alpha(), 0)

    def test_older_projects_with_rectangles_still_work(self):
        document = Document(600, 900)
        document.scene['comic'] = {'panels': [[20, 20, 560, 400], [20, 440, 560, 440]]}
        shapes = comics.page_shapes(document)
        self.assertEqual(len(shapes), 2)
        self.assertEqual(comics.panel_at(document, QPointF(300, 600)), 1)
        self.assertIsNone(comics.panel_at(document, QPointF(5, 5)))

    def test_inset_is_cut_out_of_its_parent_selection(self):
        document = Document(1000, 1000)
        parent = comic_layouts.shape([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
        inset = comic_layouts.shape([(100, 100), (300, 100), (300, 300), (100, 300)], inset=True)
        document.scene['comic'] = {'shapes': [parent, inset]}
        self.assertEqual(comics.panel_at(document, QPointF(200, 200)), 1)
        path = comics.panel_selection_path(document, 0)
        self.assertFalse(path.contains(QPointF(200, 200)))
        self.assertTrue(path.contains(QPointF(600, 600)))

    def test_balloons_lines_and_tones(self):
        for _, kind in comic_art.BALLOONS:
            image, bounds = comic_art.balloon(800, 600, QPointF(400, 200), QPointF(250, 450), 'Olá, tudo bem?', kind)
            self.assertGreater(image.pixelColor(400, 200).alpha(), 0, kind)
            self.assertTrue(QRectF(0, 0, 800, 600).intersects(bounds), kind)
        image, bounds = comic_art.balloon(800, 600, QPointF(400, 200), QPointF(250, 520), 'Oi', 'speech')
        self.assertGreater(bounds.bottom(), 480)  # the tail reaches towards the speaker
        import selection as sel
        from PyQt6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRect(QRectF(100, 100, 300, 200))
        mask = sel.path_mask(path, 800, 600)
        for kind in ('focus', 'speed', 'burst'):
            lines = comic_art.action_lines(800, 600, QRectF(100, 100, 300, 200), kind, mask=mask, count=200)
            self.assertEqual(lines.pixelColor(500, 500).alpha(), 0, kind)
            self.assertTrue(any(lines.pixelColor(x, 110).alpha() for x in range(100, 400)), kind)
        for _, kind in comic_art.TONES:
            tone = comic_art.screentone(800, 600, kind, 8, .6, 30, '#000000', mask, QRectF(100, 100, 300, 200))
            self.assertEqual(tone.pixelColor(50, 50).alpha(), 0, kind)
            covered = sum(tone.pixelColor(x, y).alpha() > 0 for x in range(120, 380, 3) for y in range(120, 280, 3))
            self.assertGreater(covered, 50, kind)


class ComicWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.resize(1300, 900)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.canvas.set_document(Document(600, 900))
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.canvas.finish_interaction()
        self.canvas.document.saved_revision = self.canvas.document.revision
        self.window.close()
        self.app.processEvents()
        self.folder.cleanup()

    def position(self, point):
        return self.canvas.transform().map(point)

    def test_one_click_stylized_pages_and_undo(self):
        self.window.show_comics_panel()
        panel = self.window.comics_panel
        panel.style.setCurrentIndex(panel.style.findData('action'))
        panel.generate.click()
        document = self.canvas.document
        first = [list(map(tuple, s['points'])) for s in document.scene['comic']['shapes']]
        self.assertEqual(document.layers[-1].name, 'Quadros')
        self.assertTrue(document.layers[-1].locked)
        self.assertEqual(document.scene['comic']['panel_style'], 'action')
        panel.generate.click()
        second = [list(map(tuple, s['points'])) for s in document.scene['comic']['shapes']]
        self.assertNotEqual(first, second)
        self.assertEqual([layer.name for layer in document.layers].count('Quadros'), 1)
        self.window.undo()
        restored = [list(map(tuple, s['points'])) for s in self.canvas.document.scene['comic']['shapes']]
        self.assertEqual(restored, first)

    def test_panel_tool_selects_the_clicked_panel(self):
        panel = self.window.comics_panel
        panel.style.setCurrentIndex(panel.style.findData('manga'))  # several main panels (splash has one)
        self.window.generate_stylized_page()
        shapes = self.canvas.document.scene['comic']['shapes']
        target = next(i for i, s in enumerate(shapes) if not s.get('inset'))
        centre = comic_layouts.shape_bounds(shapes[target]).center()
        inside = comic_layouts.panel_path(shapes[target])
        if not inside.contains(centre):
            centre = QPointF(*comic_layouts.centroid([tuple(p) for p in shapes[target]['points']]))
        self.window.set_tool('panel')
        self.canvas.press(self.position(centre), 1., Qt.KeyboardModifier.NoModifier)
        self.canvas.release(self.position(centre))
        self.assertIsNotNone(self.canvas.selection)
        self.assertGreater(self.canvas.selection.pixelColor(int(centre.x()), int(centre.y())).alpha(), 0)
        # Another panel stays outside (the page corner may belong to a panel that bleeds off the page).
        other = next(i for i, s in enumerate(shapes) if i != target and not s.get('inset'))
        x, y = comic_layouts.centroid([tuple(p) for p in shapes[other]['points']])
        self.assertEqual(self.canvas.selection.pixelColor(int(x), int(y)).alpha(), 0)

    def test_balloon_tool_adds_a_layer_on_top(self):
        self.window.generate_stylized_page()

        def accept(dialog):
            dialog.text.setPlainText('Olha ali!')
            return True
        with mock.patch.object(comics_dialogs.BalloonDialog, 'exec', accept):
            self.window.balloon_tool('speech')
            start, end = QPointF(300, 200), QPointF(200, 420)
            self.canvas.press(self.position(start), 1., Qt.KeyboardModifier.NoModifier)
            self.canvas.drag(self.position(end), 1., Qt.KeyboardModifier.NoModifier)
            self.canvas.release(self.position(end))
        document = self.canvas.document
        top = document.layers[-1]
        self.assertTrue(top.name.startswith('Balão'))
        self.assertGreater(top.image.pixelColor(300, 200).alpha(), 0)
        self.assertGreater(len(document.layers), 2)
        self.window.undo()
        self.assertEqual(self.canvas.document.layers[-1].name, 'Quadros')

    def test_effects_follow_the_selected_panel(self):
        self.window.generate_stylized_page()
        self.window.select_panel_index(0)
        mask = self.canvas.selection
        for method, dialog_class, name in ((self.window.action_lines, comics_dialogs.ActionLinesDialog, 'Linhas de ação'),
                                           (self.window.screentone, comics_dialogs.ToneDialog, 'Retícula')):
            with mock.patch.object(dialog_class, 'exec', lambda dialog: True):
                method()
            layer = self.canvas.document.layers[self.canvas.document.active]
            self.assertEqual(layer.name, name)
            outside = [(x, y) for x in range(0, 600, 7) for y in range(0, 900, 7) if mask.pixelColor(x, y).alpha() == 0]
            self.assertTrue(all(layer.image.pixelColor(x, y).alpha() == 0 for x, y in outside), name)
            self.assertTrue(any(layer.image.pixelColor(x, y).alpha() for x in range(0, 600, 5) for y in range(0, 900, 5)))

    def test_chapter_pages_and_pdf_export(self):
        folder = Path(self.folder.name) / 'cap1'
        paths = comics.chapter(folder, 3, 400, 600, 150, 'random', 'rtl', 5,
                               {'position': 'outer', 'size': 20, 'margin': 20}, seed=11)
        self.assertEqual([Path(p).name for p in paths], ['pagina 05.sdp', 'pagina 06.sdp', 'pagina 07.sdp'])
        layouts = []
        for path in paths:
            document = Document.load(path)
            names = [layer.name for layer in document.layers]
            self.assertEqual(names, ['Rascunho', 'Arte', 'Quadros', comics.NUMBER_LAYER])
            self.assertEqual(document.scene['comic']['direction'], 'rtl')
            layouts.append(document.scene['comic']['shapes'])
        self.assertNotEqual(layouts[0], layouts[1])
        with self.assertRaises(ValueError):
            comics.chapter(folder, 1, 400, 600, start=5)
        output = Path(self.folder.name) / 'cap1.pdf'
        self.assertEqual(comics.export_pdf(list(reversed(paths)), output), 3)
        data = output.read_bytes()
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertEqual(data.count(b'/Type /Page\n') + data.count(b'/Type /Page\r') + data.count(b'/Type /Page '), 3)

    def test_saving_reuses_unchanged_layers(self):
        document = Document(300, 200)
        document.layers.append(document.blank_layer('B'))
        painter = QPainter(document.layers[0].image)
        painter.fillRect(10, 10, 100, 100, QColor('red'))
        painter.end()
        path = Path(self.folder.name) / 'cache.sdp'
        document.save(path)
        loaded = Document.load(path)
        with mock.patch('document.encode_png', side_effect=AssertionError('should not re-encode')):
            loaded.save(path)
        painter = QPainter(loaded.layers[1].image)
        painter.fillRect(0, 0, 20, 20, QColor('blue'))
        painter.end()
        calls = []
        import document as document_module
        original = document_module.encode_png
        with mock.patch('document.encode_png', side_effect=lambda image: calls.append(1) or original(image)):
            loaded.save(path)
        self.assertEqual(len(calls), 1)
        again = Document.load(path)
        self.assertEqual(again.layers[0].image.pixelColor(50, 50).name(), '#ff0000')
        self.assertEqual(again.layers[1].image.pixelColor(5, 5).name(), '#0000ff')
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.getinfo('frames/0/0.png').compress_type, zipfile.ZIP_STORED)


if __name__ == '__main__':
    unittest.main()
