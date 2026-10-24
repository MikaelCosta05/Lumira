import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import struct
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication

import comics
from animation import TRANSITIONS, render_scene, shake_offset
from document import Document
from main import MainWindow
from resources import ResourceLibrary, parse_aco, parse_ase, parse_palette


class ToolTests(unittest.TestCase):
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

    def stroke(self, points, pressure=1.):
        self.canvas.begin_stroke(self.position(*points[0]), pressure, 100)
        for n, point in enumerate(points[1:], 1):
            self.canvas.move_stroke(self.position(*point), pressure, 100 + n * .02)
        self.canvas.finish_stroke(self.position(*points[-1]), pressure, 100 + len(points) * .02)

    def press_drag_release(self, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
        self.canvas.press(self.position(*start), 1., modifiers)
        self.canvas.drag(self.position(*end), 1., modifiers)
        self.canvas.release(self.position(*end))

    def alpha(self, x, y, image=None):
        return (image or self.canvas.image).pixelColor(x, y).alpha()

    def draw_box_outline(self):
        image = self.canvas.image
        painter = QPainter(image)
        painter.setPen(QColor('black'))
        painter.drawRect(40, 40, 60, 60)
        painter.end()

    # -------------------------------------------------------------- drawing

    def test_pencil_pen_and_pixel_tools_paint(self):
        for tool, y in (('pencil', 40), ('pen', 80), ('pixel', 120)):
            self.window.set_tool(tool)
            self.stroke([(20, y), (60, y), (100, y)])
            self.assertTrue(any(self.alpha(x, y) for x in range(40, 80)), tool)
        values = {self.alpha(x, 120) for x in range(0, 200)}
        self.assertTrue(values <= {0, 255}, 'pixel art must not be antialiased')

    def test_each_paint_tool_remembers_its_size(self):
        self.window.size_spin.setValue(12)
        self.window.set_tool('pencil')
        self.assertEqual(self.window.brush_size, 3)
        self.window.set_tool('brush')
        self.assertEqual(self.window.brush_size, 12)

    def test_tools_use_their_own_brush_presets(self):
        self.assertEqual(self.window.brush_for('pencil').name, 'Lápis HB')
        self.assertFalse(self.window.brush_for('pencil').basic)
        self.assertEqual(self.window.brush_for('pen').name, 'Caneta nanquim')

    def test_shift_click_draws_straight_line_from_previous_stroke(self):
        self.window.size_spin.setValue(4)
        self.stroke([(20, 100)])
        self.canvas.press(self.position(160, 100), 1., Qt.KeyboardModifier.ShiftModifier)
        self.canvas.release(self.position(160, 100))
        self.assertTrue(all(self.alpha(x, 100) for x in range(30, 150, 10)))

    # ------------------------------------------------------------ selection

    def test_rectangle_selection_limits_painting(self):
        self.window.set_tool('select_rect')
        self.press_drag_release((50, 50), (100, 150))
        self.assertIsNotNone(self.canvas.selection)
        self.window.set_tool('brush')
        self.window.size_spin.setValue(10)
        self.stroke([(20, 100), (80, 100), (180, 100)])
        self.assertGreater(self.alpha(75, 100), 0)
        self.assertEqual(self.alpha(30, 100), 0)
        self.assertEqual(self.alpha(150, 100), 0)

    def test_real_mouse_drag_creates_selection(self):
        from PyQt6.QtTest import QTest
        self.window.set_tool('select_rect')
        start, end = self.position(40, 40).toPoint(), self.position(120, 90).toPoint()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.canvas, end)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
        values = self.canvas.selection_values
        self.assertIsNotNone(values)
        self.assertTrue(values[60, 80])
        self.assertFalse(values[150, 150])
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.canvas.selection)

    def test_click_without_drag_deselects_and_modes_combine(self):
        self.window.set_tool('select_rect')
        self.press_drag_release((10, 10), (60, 60))
        self.press_drag_release((100, 100), (150, 150), Qt.KeyboardModifier.ShiftModifier)
        values = self.canvas.selection_values
        self.assertTrue(values[30, 30] and values[120, 120])
        self.press_drag_release((20, 20), (40, 40), Qt.KeyboardModifier.AltModifier)
        self.assertFalse(self.canvas.selection_values[30, 30])
        self.press_drag_release((5, 5), (5, 5))
        self.assertIsNone(self.canvas.selection)

    def test_ellipse_and_lasso_selections(self):
        self.window.set_tool('select_ellipse')
        self.press_drag_release((40, 40), (160, 160))
        values = self.canvas.selection_values
        self.assertTrue(values[100, 100])
        self.assertFalse(values[42, 42])
        self.window.set_tool('lasso')
        self.canvas.press(self.position(20, 20), 1., Qt.KeyboardModifier.NoModifier)
        for point in [(180, 20), (180, 180), (100, 100)]:
            self.canvas.drag(self.position(*point), 1., Qt.KeyboardModifier.NoModifier)
        self.canvas.release(self.position(100, 100))
        self.assertTrue(self.canvas.selection_values[30, 150])
        self.assertFalse(self.canvas.selection_values[150, 30])

    def test_magic_wand_and_fill_bucket_respect_lines(self):
        self.draw_box_outline()
        self.window.set_tool('wand')
        self.window.tool_options.update(sample_all=False)
        self.canvas.press(self.position(70, 70), 1., Qt.KeyboardModifier.NoModifier)
        values = self.canvas.selection_values
        self.assertTrue(values[70, 70])
        self.assertFalse(values[10, 10])
        self.canvas.set_selection(None)
        self.window.set_tool('fill')
        self.window.set_color(QColor('#d03030'))
        self.canvas.press(self.position(70, 70), 1., Qt.KeyboardModifier.NoModifier)
        self.assertEqual(self.canvas.image.pixelColor(70, 70).red(), 0xd0)
        self.assertEqual(self.alpha(10, 10), 0)
        self.window.undo()
        self.assertEqual(self.alpha(70, 70), 0)

    def test_move_tool_moves_selected_pixels_and_undo_restores(self):
        self.window.size_spin.setValue(10)
        self.stroke([(50, 50)])
        self.canvas.select_rect(QRect(30, 30, 40, 40))
        self.window.set_tool('move')
        self.press_drag_release((50, 50), (110, 90))
        self.assertEqual(self.alpha(50, 50), 0)
        self.assertGreater(self.alpha(110, 90), 0)
        self.assertTrue(self.canvas.selection_values[90, 110])
        self.window.undo()
        self.assertGreater(self.alpha(50, 50), 0)

    def test_rotate_and_flip_selection(self):
        image = self.canvas.image
        painter = QPainter(image)
        painter.fillRect(20, 90, 60, 20, QColor('black'))
        painter.end()
        self.canvas.transform_content(90.)
        self.assertGreater(self.alpha(100, 40), 0)
        self.assertEqual(self.alpha(30, 100), 0)
        self.canvas.transform_content(0., True, False)
        self.assertGreater(self.alpha(100, 40), 0)

    def test_copy_paste_creates_layer_at_original_position(self):
        self.window.size_spin.setValue(10)
        self.stroke([(150, 150)])
        self.canvas.select_rect(QRect(130, 130, 40, 40))
        self.assertTrue(self.window.copy_selection())
        self.window.paste_layer()
        document = self.canvas.document
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(document.layers[1].name, 'Colado')
        self.assertGreater(self.alpha(150, 150, document.layers[1].image), 0)

    def test_clear_and_fill_selection(self):
        self.canvas.select_rect(QRect(0, 0, 100, 200))
        self.canvas.fill_selection(QColor('blue'))
        self.assertEqual(self.alpha(50, 50), 255)
        self.assertEqual(self.alpha(150, 50), 0)
        self.canvas.invert_selection()
        self.canvas.select_rect(QRect(0, 0, 50, 50))
        self.canvas.clear_pixels()
        self.assertEqual(self.alpha(25, 25), 0)
        self.assertEqual(self.alpha(75, 75), 255)

    # --------------------------------------------------------------- guides

    def test_perspective_snapping_keeps_strokes_on_vanishing_lines(self):
        self.canvas.document.guides.update(points=[[100., 100.]], snap=True)
        self.window.size_spin.setValue(3)
        self.stroke([(20, 20), (40, 42), (60, 58), (80, 81)])
        self.assertGreater(self.alpha(60, 60), 0)
        self.assertEqual(self.alpha(60, 45), 0)

    def test_parallel_ruler_snaps_strokes(self):
        self.window.set_tool('ruler')
        self.press_drag_release((10, 10), (190, 10))
        self.assertIsNotNone(self.canvas.document.guides['ruler'])
        self.window.set_snap(True)
        self.window.set_tool('brush')
        self.window.size_spin.setValue(3)
        self.stroke([(30, 100), (80, 104), (140, 97), (170, 103)])
        self.assertTrue(all(self.alpha(x, 100) for x in range(40, 160, 10)))
        self.assertEqual(self.alpha(140, 108), 0)

    def test_perspective_tool_adds_moves_and_removes_points(self):
        self.window.set_tool('perspective')
        self.press_drag_release((50, 50), (60, 70))
        self.assertEqual(self.canvas.document.guides['points'], [[60., 70.]])
        self.canvas.press_guide(self.position(60, 70), remove=True)
        self.assertEqual(self.canvas.document.guides['points'], [])

    def test_guides_are_saved_but_not_rendered(self):
        document = self.canvas.document
        document.guides.update(points=[[10., 20.], [300., 20.]], ruler=[0., 0., 50., 50.], bleed=8, safe=12)
        blank = document.composite()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'guias.sdp'
            document.save(path)
            restored = Document.load(path)
        self.assertEqual(restored.guides['points'], [[10., 20.], [300., 20.]])
        self.assertEqual(restored.guides['bleed'], 8)
        self.assertEqual(restored.composite(), blank)
        self.window.toggle_rulers(True)
        self.window.toggle_grid(True)
        self.canvas.grab()

    # --------------------------------------------------------------- comics

    def test_panel_layouts_follow_reading_order(self):
        rects = comics.panel_rects(1000, 1500, comics.LAYOUTS['2 × 2'], 50, 20, 20)
        self.assertEqual(len(rects), 4)
        self.assertLess(rects[0].x(), rects[1].x())
        manga = comics.panel_rects(1000, 1500, comics.LAYOUTS['2 × 2'], 50, 20, 20, rtl=True)
        self.assertGreater(manga[0].x(), manga[1].x())
        with self.assertRaises(ValueError):
            comics.panel_rects(100, 100, comics.LAYOUTS['9 quadros'], 49, 10, 10)

    def test_generated_panels_layer_and_page_number(self):
        document = Document(600, 900)
        rects = comics.panel_rects(600, 900, comics.LAYOUTS['Clássico · 6 quadros'], 30, 10, 12)
        image = comics.render_panels(600, 900, rects, 3, QColor('black'), QColor('white'))
        self.assertEqual(image.pixelColor(5, 5), QColor('white'))
        self.assertEqual(image.pixelColor(int(rects[0].center().x()), int(rects[0].center().y())).alpha(), 0)
        comics.apply_page_number(document, 7, {'size': 30, 'margin': 20, 'position': 'outer'})
        comics.apply_page_number(document, 8, {'size': 30, 'margin': 20, 'position': 'outer'})
        self.assertEqual([layer.name for layer in document.layers].count(comics.NUMBER_LAYER), 1)
        number = document.layers[-1].image
        left = any(number.pixelColor(x, y).alpha() for x in range(0, 100) for y in range(850, 900))
        self.assertTrue(left, 'even pages put the outer number on the left')

    def test_batch_numbering_uses_natural_order(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name in ('pagina 10.sdp', 'pagina 2.sdp', 'pagina 1.sdp'):
                path = Path(folder) / name
                Document(120, 160).save(path)
                paths.append(str(path))
            done = comics.batch_number(paths, 1, {'size': 12, 'margin': 4})
            self.assertEqual([(Path(p).name, n) for p, n in done],
                             [('pagina 1.sdp', 1), ('pagina 2.sdp', 2), ('pagina 10.sdp', 3)])
            self.assertEqual(Document.load(Path(folder) / 'pagina 10.sdp').scene['comic']['page'], 3)

    def test_cover_has_editable_layers_and_print_guides(self):
        document = comics.cover_document({'width': 400, 'height': 600, 'title': 'Teste', 'issue': '3',
                                          'author': 'Autor', 'bleed': 10, 'safe': 20})
        self.assertEqual([layer.name for layer in document.layers],
                         ['Fundo', 'Arte da capa', 'Título', 'Informações', 'Código de barras'])
        self.assertEqual(document.active, 1)
        self.assertEqual(document.guides['bleed'], 10)
        self.assertTrue(any(document.layers[2].image.pixelColor(x, 100).alpha() for x in range(400)))

    def test_generate_panels_through_window(self):
        import comics_dialogs
        original = comics_dialogs.PanelDialog.exec
        comics_dialogs.PanelDialog.exec = lambda dialog: dialog.validate() or dialog.result()
        try:
            self.window.generate_panels()
        finally:
            comics_dialogs.PanelDialog.exec = original
        document = self.canvas.document
        self.assertEqual(document.layers[-1].name, 'Quadros')
        self.assertTrue(document.layers[-1].locked)
        self.assertEqual(len(document.scene['comic']['panels']), 6)
        self.assertEqual(document.active, 0)
        self.window.undo()
        self.assertEqual(len(document.layers), 1)

    # ------------------------------------------------------------ resources

    def test_palette_formats(self):
        aco = struct.pack('>HH', 1, 2) + struct.pack('>5H', 0, 65535, 0, 0, 0) + struct.pack('>5H', 8, 10000, 0, 0, 0)
        self.assertEqual(parse_aco(aco), ['#ff0000', '#ffffff'])
        name = 'A'.encode('utf-16-be') + b'\0\0'
        body = struct.pack('>H', 2) + name + b'RGB ' + struct.pack('>3f', 0, 1, 0) + struct.pack('>H', 0)
        ase = b'ASEF' + struct.pack('>HHI', 1, 0, 1) + struct.pack('>HI', 1, len(body)) + body
        self.assertEqual(parse_ase(ase), ['#00ff00'])
        with tempfile.TemporaryDirectory() as folder:
            gpl = Path(folder) / 'x.gpl'
            gpl.write_text('GIMP Palette\nName: Minha\n#\n255 0 0 Red\n0 0 255\tBlue\n', encoding='utf-8')
            self.assertEqual(parse_palette(gpl), ('Minha', ['#ff0000', '#0000ff']))
            hexfile = Path(folder) / 'y.hex'
            hexfile.write_text('ff00ff\n00ff00\n', encoding='utf-8')
            self.assertEqual(parse_palette(hexfile)[1], ['#ff00ff', '#00ff00'])

    def test_library_defaults_and_deleted_palettes_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lib.json'
            library = ResourceLibrary(path)
            for name in ('Pele', 'Metais', 'Ouro', 'Diamante', 'Grama', 'Madeira', 'Sombras', 'Luz'):
                self.assertIn(name, library.palettes)
            library.delete_palette('Ouro')
            library.palettes['Minha'] = ['#123456']
            library.save()
            reloaded = ResourceLibrary(path)
            self.assertNotIn('Ouro', reloaded.palettes)
            self.assertIn('Minha', reloaded.palettes)
            with self.assertRaises(ValueError):
                reloaded.delete_brush(0)

    # ------------------------------------------------------------ animation

    def test_new_transitions_render_and_shake_is_deterministic(self):
        document = Document(64, 48)
        document.animation_enabled = True
        document.add_frame()
        for _, kind in TRANSITIONS:
            document.scene['transitions'] = [{'from': 1, 'to': 1, 'type': kind}]
            self.assertFalse(render_scene(document, 1.5).isNull(), kind)
        self.assertEqual(shake_offset(3.2, 5), shake_offset(3.9, 5))
        self.assertEqual(shake_offset(3, 0), (0., 0.))


if __name__ == '__main__':
    unittest.main()
