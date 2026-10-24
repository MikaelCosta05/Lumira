import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QFontDatabase, QInputDevice, QPointingDevice, QTabletEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from document import Document
from main import MainWindow


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        if not QFontDatabase.families():
            for name in ('segoeui.ttf', 'segoeuib.ttf'):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.canvas.set_document(Document(256, 256))

    def tearDown(self):
        self.canvas.finish_stroke()
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

    def test_canvas_is_visible_and_fractional_brush_size_survives(self):
        self.assertGreater(self.canvas.width(), 100)
        self.assertGreater(self.canvas.height(), 100)
        self.window.size_spin.setValue(2.3)
        self.assertEqual(self.window.brush_size, 2.3)
        self.assertEqual(self.window.size_slider.value(), 23)

    def test_real_mouse_click_draws_dot(self):
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=self.position(100, 100).toPoint())
        self.assertGreater(self.canvas.image.pixelColor(100, 100).alpha(), 0)

    def test_complete_stroke_undo_redo(self):
        self.stroke([(20, 100), (40, 100), (80, 100), (120, 100)])
        after = self.canvas.image.copy()
        self.assertGreater(after.pixelColor(120, 100).alpha(), 0)
        self.window.undo()
        self.assertEqual(self.canvas.image.pixelColor(120, 100).alpha(), 0)
        self.window.redo()
        self.assertEqual(self.canvas.image, after)

    def test_eraser_removes_alpha_instead_of_painting_white(self):
        self.window.size_spin.setValue(25)
        self.stroke([(100, 100)])
        self.window.set_tool('eraser')
        self.stroke([(100, 100)])
        self.assertEqual(self.canvas.image.pixelColor(100, 100).alpha(), 0)

    def test_opacity_does_not_build_up_at_sample_overlaps(self):
        self.window.opacity_spin.setValue(30)
        self.window.size_spin.setValue(20)
        self.stroke([(30, 100), (60, 100), (90, 100), (120, 100)])
        alpha = [self.canvas.image.pixelColor(x, 100).alpha() for x in (30, 50, 70, 100, 120)]
        self.assertLessEqual(max(alpha) - min(alpha), 1)
        self.assertTrue(all(75 <= a <= 77 for a in alpha))

    def test_pressure_changes_width_without_changing_stabilization(self):
        self.window.size_spin.setValue(40)
        self.stroke([(40, 80)], pressure=.1)
        self.stroke([(120, 80)], pressure=.9)
        light = sum(self.canvas.image.pixelColor(40, y).alpha() > 100 for y in range(256))
        heavy = sum(self.canvas.image.pixelColor(120, y).alpha() > 100 for y in range(256))
        self.assertGreater(light, 8)
        self.assertGreater(heavy, light + 12)
        self.assertEqual(self.window.stabilizer_level, 'S-4')

    def test_tablet_events_use_pressure_and_do_not_duplicate_mouse_strokes(self):
        device = QPointingDevice('Test Pen', 42, QInputDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Pen,
            QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 3)
        def send(kind, x, pressure, buttons):
            position = self.position(x, 100)
            event = QTabletEvent(kind, device, position, position, pressure,
                0., 0., 0., 0., 0., Qt.KeyboardModifier.NoModifier,
                Qt.MouseButton.LeftButton, buttons)
            self.app.sendEvent(self.canvas, event)
            self.assertTrue(event.isAccepted())
        send(QEvent.Type.TabletPress, 40, .1, Qt.MouseButton.LeftButton)
        self.assertTrue(self.canvas.tablet_down)
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=self.position(40, 100).toPoint())
        self.assertTrue(self.canvas.drawing)
        self.assertEqual(len(self.canvas.document.undo_stack), 1)
        send(QEvent.Type.TabletMove, 80, .8, Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.last_pressure, .8)
        send(QEvent.Type.TabletRelease, 100, 0., Qt.MouseButton.NoButton)
        self.assertFalse(self.canvas.tablet_down)
        self.assertFalse(self.canvas.drawing)
        self.assertGreater(self.canvas.image.pixelColor(100, 100).alpha(), 0)

    def test_locked_layer_rejects_stroke_and_layer_edits_undo(self):
        self.window.add_layer()
        self.window.layer_lock.setChecked(True)
        self.assertFalse(self.canvas.begin_stroke(self.position(100, 100), 1., 100))
        self.window.undo()
        self.assertFalse(self.canvas.document.layers[1].locked)
        self.window.undo()
        self.assertEqual(len(self.canvas.document.layers), 1)

    def test_project_round_trip_preserves_layers_and_transparency(self):
        self.stroke([(30, 40), (70, 80)])
        self.window.add_layer()
        self.window.set_color(QColor('#b64455'))
        self.stroke([(100, 120)])
        self.window.layer_opacity.setValue(65)
        self.window.paper_check.setChecked(False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sdp'
            self.canvas.document.save(path)
            restored = Document.load(path)
            self.assertEqual(len(restored.layers), 2)
            self.assertEqual(restored.composite(), self.canvas.document.composite())
            self.assertEqual(restored.layers[1].opacity, .65)
            self.assertFalse(restored.paper_visible)
            self.assertFalse(restored.modified)

    def test_zoom_keeps_anchor_and_themes_preserve_document(self):
        self.stroke([(100, 100)])
        original = self.canvas.image.copy()
        anchor = QPointF(240, 160)
        before = self.canvas.to_document(anchor)
        self.canvas.set_zoom(self.canvas.zoom * 2, anchor)
        after = self.canvas.to_document(anchor)
        self.assertAlmostEqual(before.x(), after.x())
        self.assertAlmostEqual(before.y(), after.y())
        self.window.toggle_theme()
        self.assertEqual(self.window.theme, 'Claro')
        self.assertEqual(self.canvas.image, original)

    def test_visual_refresh_does_not_change_document_or_history(self):
        self.window.refresh_document()
        self.window.toggle_theme()
        self.window.refresh_document()
        self.assertFalse(self.canvas.document.modified)
        self.assertEqual(len(self.canvas.document.undo_stack), 0)

    def test_layer_eye_toggles_visibility(self):
        self.app.processEvents()
        rect = self.window.layer_list.visualItemRect(self.window.layer_list.item(0))
        QTest.mouseClick(self.window.layer_list.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(rect.x() + 15, rect.y() + 27))
        self.assertFalse(self.canvas.document.layers[0].visible)
        self.window.undo()
        self.assertTrue(self.canvas.document.layers[0].visible)

    def test_focus_workspace_restores_panels_without_changing_artwork(self):
        self.stroke([(100, 100)])
        image = self.canvas.image.copy()
        original_width = self.canvas.width()
        self.window.workspace_combo.setCurrentIndex(1)
        self.app.processEvents()
        self.assertGreater(self.canvas.width(), original_width)
        self.assertTrue(self.window.layers_dock.isHidden())
        self.window.workspace_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertFalse(self.window.layers_dock.isHidden())
        self.assertEqual(self.canvas.image, image)


if __name__ == '__main__':
    unittest.main()
