import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import unittest
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

import gltf
import i18n
import mannequin
from document import Document
from main import MainWindow

MODELS = Path(__file__).resolve().parents[1] / 'assets' / '3D'
STICKMAN = MODELS / 'stickman.glb'
LOW_POLY = MODELS / 'low_poly_base_mesh-530_tri.glb'


def gl_available():
    try:
        import render3d
        return render3d.available()
    except ImportError:
        return False


class GltfTests(unittest.TestCase):
    @unittest.skipUnless(STICKMAN.exists(), 'modelo de exemplo ausente')
    def test_reads_skin_animations_and_samples_pose(self):
        model = gltf.load(STICKMAN, 256)
        self.assertTrue(model.rigged)
        self.assertGreater(model.triangles, 1000)
        self.assertTrue(model.animations)
        animation = model.animations[0]
        pose = gltf.sample_animation(model, animation, animation['duration'] / 2)
        self.assertTrue(pose)
        moved = model.world(pose)
        rest = model.world()
        self.assertTrue(any(not np.allclose(moved[i], rest[i]) for i in pose))

    def test_quaternion_round_trip(self):
        for q in ([0, 0, 0, 1], [.2, .3, .1, .92], [-.5, .5, .5, .5]):
            q = np.array(q, float) / np.linalg.norm(q)
            back = gltf.matrix_quaternion(gltf.quaternion_matrix(q))
            self.assertTrue(np.allclose(back, q, atol=1e-6) or np.allclose(back, -q, atol=1e-6))

    def test_rejects_non_glb(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.glb'
            path.write_bytes(b'nope')
            with self.assertRaises(ValueError):
                gltf.load(path)


@unittest.skipUnless(LOW_POLY.exists() and STICKMAN.exists() and gl_available(), 'OpenGL ou modelos indisponíveis')
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rig_figure_renders_and_poses(self):
        import model3d
        figure = model3d.RigFigure(LOW_POLY)
        camera = mannequin.Camera()
        camera.fit(figure, view=True)
        before = figure.render(camera, 120, 160)
        self.assertGreater(before['alpha'].sum(), 200)
        ids = {figure.joint_at_id(i) for i in np.unique(before['ids']) if i >= 0} - {None}
        self.assertTrue(ids)
        joint = next(iter(ids))
        figure.rotate_joint(joint, mannequin.axis_angle([0, 0, 1], 60))
        after = figure.render(camera, 120, 160)
        self.assertGreater(np.abs(after['alpha'] - before['alpha']).sum(), 10)
        values = figure.rotation_values(joint)
        figure.set_rotation_value(joint, 0, values[0] + 10)
        self.assertAlmostEqual(figure.rotation_values(joint)[0], values[0] + 10, delta=.5)
        saved = figure.serialize_pose()
        figure.pose = {}
        figure.load_pose(saved)
        self.assertAlmostEqual(figure.rotation_values(joint)[0], values[0] + 10, delta=.5)

    def test_animation_preset_and_studio_insert(self):
        window = MainWindow(persist=False)
        window.show()
        try:
            window.canvas.set_document(Document(320, 400))
            window.pose_studio()
            studio = window.pose_window
            index = next(i for i in range(studio.model.count()) if studio.model.itemData(i) == ('file', str(STICKMAN)))
            studio.model.setCurrentIndex(index)
            studio.change_model(True)
            self.assertEqual(studio.figure.kind, 'gltf')
            animated = next(i for i in range(studio.preset.count()) if str(studio.preset.itemData(i)[1]).startswith('Animação'))
            studio.preset.setCurrentIndex(animated)
            self.assertFalse(studio.time.isHidden())
            studio.time.setValue(50)
            self.assertTrue(studio.figure.pose)
            studio.insert()
            layers = window.canvas.document.layers
            self.assertEqual(len(layers), 3)
            self.assertTrue(layers[2].is_shadow)
            self.assertGreater(layers[1].image.pixelColor(160, 200).alpha() + sum(
                layers[1].image.pixelColor(x, 200).alpha() for x in range(100, 220, 5)), 0)
            studio.close()
            window.canvas.document.saved_revision = window.canvas.document.revision
        finally:
            window.close()


class LayerAndDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.canvas.set_document(Document(100, 80))

    def tearDown(self):
        self.canvas.finish_interaction()
        self.canvas.document.saved_revision = self.canvas.document.revision
        self.window.close()
        self.app.processEvents()

    def test_multiply_blend_and_merge_down(self):
        document = self.canvas.document
        document.layers[0].image.fill(QColor(200, 200, 200))
        self.window.add_layer()
        document.layers[1].image.fill(QColor(128, 128, 255))
        self.window.layer_blend.setCurrentIndex(self.window.layer_blend.findData('multiply'))
        self.assertEqual(document.layers[1].blend, 'multiply')
        expected = document.composite().pixelColor(50, 40)
        self.assertLess(expected.red(), 128)
        self.window.merge_down()
        self.assertEqual(len(document.layers), 1)
        self.assertEqual(document.composite().pixelColor(50, 40), expected)
        self.window.undo()
        self.assertEqual(len(document.layers), 2)

    def test_alpha_lock_keeps_transparent_pixels(self):
        image = self.canvas.image
        painter = QPainter(image)
        painter.fillRect(0, 0, 50, 80, QColor('black'))
        painter.end()
        self.window.layer_alpha_lock.setChecked(True)
        self.window.set_color(QColor('red'))
        self.window.size_spin.setValue(20)
        at = lambda x, y: self.canvas.transform().map(QPointF(x, y))
        self.canvas.begin_stroke(at(10, 40), 1., 100)
        self.canvas.move_stroke(at(90, 40), 1., 100.1)
        self.canvas.finish_stroke(at(90, 40), 1., 100.2)
        self.assertEqual(self.canvas.image.pixelColor(30, 40).red(), 255)
        self.assertEqual(self.canvas.image.pixelColor(80, 40).alpha(), 0)

    def test_tool_slots_follow_group_choice(self):
        slot = next(s for s in self.window.tool_slots if self.window.tool_actions['pencil'] in s.group)
        self.window.set_tool('pencil')
        self.assertIs(slot.defaultAction(), self.window.tool_actions['pencil'])
        self.assertTrue(slot.menu() is not None)

    def test_color_wheel_round_trip(self):
        wheel = self.window.color_wheel.wheel
        wheel.resize(200, 200)
        color = QColor.fromHsvF(.6, .7, .8)
        wheel.set_color(color)
        saturation, value = wheel.sv_for(wheel.point_for(.7, .8))
        self.assertAlmostEqual(saturation, .7, delta=.02)
        self.assertAlmostEqual(value, .8, delta=.02)

    def test_language_switch_translates_and_restores(self):
        try:
            self.window.change_language('en')
            menus = [action.text() for action in self.window.menuBar().actions()]
            self.assertIn('File', menus)
            self.assertIn('Layers', menus)
            self.assertEqual(self.window.layer_blend.itemText(1), 'Multiply')
            self.assertEqual(i18n.tr('Nova camada'), 'New layer')
            self.assertEqual(i18n.tr('Camada 7'), 'Layer 7')
            self.assertEqual(i18n.tr('Pincel (B)'), 'Brush (B)')
            label = QLabel('Opacidade')
            self.window.layout().addWidget(label) if False else None
            label.setText('Nova camada')
            self.assertEqual(label.text(), 'New layer')
            combo = QComboBox()
            combo.addItem('Multiplicar', 'multiply')
            self.assertEqual(combo.itemText(0), 'Multiply')
            self.assertEqual(combo.itemData(0), 'multiply')
            self.window.add_layer()
            self.assertEqual(self.canvas.document.layers[-1].name, 'Layer 2')
        finally:
            self.window.change_language('pt_BR')
        menus = [action.text() for action in self.window.menuBar().actions()]
        self.assertIn('Arquivo', menus)
        self.assertEqual(self.window.layer_blend.itemText(1), 'Multiplicar')
        self.assertEqual(i18n.tr('Nova camada'), 'Nova camada')

    def test_translation_table_keeps_placeholders(self):
        import json
        table = json.loads(i18n.TABLE_PATH.read_text(encoding='utf-8'))
        self.assertGreater(len(table), 800)
        for key, value in table.items():
            self.assertEqual(key.count('{}'), value.count('{}'), key)


if __name__ == '__main__':
    unittest.main()
