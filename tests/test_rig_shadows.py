import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

import mannequin
import rig
import shading
from document import Document
from main import MainWindow


def distance(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


class RigTests(unittest.TestCase):
    def setUp(self):
        self.document = Document(800, 800)
        self.document.animation_enabled = True
        self.bones = rig.add_template(self.document, 'human', QRectF(200, 50, 400, 700))
        self.by_name = {b['name']: b for b in self.bones}

    def test_human_template_has_named_parts_and_hierarchy(self):
        for name in ('Quadril', 'Tronco', 'Cabeça', 'Ombro esq.', 'Braço esq.', 'Antebraço esq.', 'Mão esq.',
                     'Coxa dir.', 'Canela dir.', 'Pé dir.'):
            self.assertIn(name, self.by_name)
        self.assertEqual(self.by_name['Mão esq.']['parent'], self.by_name['Antebraço esq.']['id'])
        self.assertEqual(self.by_name['Coxa dir.']['parent'], self.by_name['Quadril']['id'])
        top = min(rig.world_points(self.document, b, 0)[1].y() for b in self.bones)
        bottom = max(rig.world_points(self.document, b, 0)[1].y() for b in self.bones)
        self.assertAlmostEqual(bottom - top, 700, delta=30)

    def test_rotating_parent_carries_children(self):
        arm, hand = self.by_name['Braço esq.'], self.by_name['Mão esq.']
        joint = rig.world_points(self.document, arm, 0)[0]
        tip = rig.world_points(self.document, arm, 0)[1]
        before = rig.world_points(self.document, hand, 0)[1]
        target = joint + QPointF(tip.y() - joint.y(), -(tip.x() - joint.x()))
        rig.rotate_towards(self.document, arm, 0, tip, target)
        self.assertAlmostEqual(rig.values(arm, 0)['angle'] % 360, 270, delta=1)
        self.assertGreater(distance(before, rig.world_points(self.document, hand, 0)[1]), 50)
        self.assertAlmostEqual(distance(joint, rig.world_points(self.document, arm, 0)[0]), 0, delta=.01)

    def test_ik_moves_hand_to_target_and_keeps_shoulder(self):
        hand = self.by_name['Mão esq.']
        shoulder = rig.world_points(self.document, self.by_name['Braço esq.'], 0)[0]
        target = shoulder + QPointF(120, -60)
        rig.solve_ik(self.document, hand, 0, target, include_self=False)
        self.assertLess(distance(rig.world_points(self.document, hand, 0)[1], target), 3)
        self.assertAlmostEqual(distance(shoulder, rig.world_points(self.document, self.by_name['Braço esq.'], 0)[0]), 0, delta=.01)
        self.assertEqual(rig.values(self.by_name['Ombro esq.'], 0)['angle'], 0)

    def test_root_translation_moves_whole_skeleton(self):
        head = self.by_name['Cabeça']
        before = rig.world_points(self.document, head, 0)[1]
        rig.translate(self.document, self.by_name['Quadril'], 0, QPointF(30, -10))
        after = rig.world_points(self.document, head, 0)[1]
        self.assertAlmostEqual(after.x() - before.x(), 30, delta=.01)
        self.assertAlmostEqual(after.y() - before.y(), -10, delta=.01)

    def test_rest_editing_moves_attached_children_without_keys(self):
        forearm, hand = self.by_name['Antebraço esq.'], self.by_name['Mão esq.']
        tip = rig.world_points(self.document, forearm, 0)[1]
        rig.edit_rest_tip(self.document, forearm, 0, tip + QPointF(0, 40))
        self.assertAlmostEqual(distance(rig.world_points(self.document, hand, 0)[0], tip + QPointF(0, 40)), 0, delta=.01)
        self.assertFalse(forearm['keys'])

    def test_mirror_pose_swaps_sides(self):
        rig.set_key(self.by_name['Braço esq.'], 0, angle=30.)
        rig.mirror_pose(self.document, 0)
        self.assertAlmostEqual(rig.values(self.by_name['Braço dir.'], 0)['angle'], -30)
        self.assertAlmostEqual(rig.values(self.by_name['Braço esq.'], 0)['angle'], 0)

    def test_delete_bone_removes_children(self):
        rig.delete_bone(self.document, self.by_name['Braço esq.']['id'])
        names = {b['name'] for b in self.document.scene['bones']}
        self.assertNotIn('Mão esq.', names)
        self.assertIn('Ombro esq.', names)

    def test_bound_layer_follows_bone(self):
        layer = self.document.layers[0]
        painter = QPainter(layer.image)
        hand = self.by_name['Mão esq.']
        start, end = rig.world_points(self.document, hand, 0)
        painter.fillRect(QRectF(end.x() - 3, end.y() - 3, 6, 6), QColor('black'))
        painter.end()
        hand['layer'] = layer.id
        rig.set_key(hand, 0, angle=90.)
        moved = self.document.composite(paper=False)
        self.assertEqual(moved.pixelColor(int(end.x()), int(end.y())).alpha(), 0)


class CanvasRigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.canvas.set_document(Document(600, 600))
        self.window.activate_bone()

    def tearDown(self):
        self.canvas.finish_interaction()
        self.canvas.document.saved_revision = self.canvas.document.revision
        self.window.close()
        self.app.processEvents()

    def at(self, point):
        return self.canvas.transform().map(point)

    def drag(self, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
        self.canvas.press(self.at(start), 1., modifiers)
        self.canvas.drag(self.at(end), 1., modifiers)
        self.canvas.release(self.at(end))

    def test_drag_creates_chain_and_rotation_is_undoable(self):
        self.drag(QPointF(100, 300), QPointF(250, 300))
        self.drag(QPointF(250, 300), QPointF(400, 300), Qt.KeyboardModifier.ControlModifier)
        first, second = self.canvas.document.scene['bones']
        self.assertEqual(second['parent'], first['id'])
        self.drag(QPointF(240, 300), QPointF(100, 450))
        self.assertNotEqual(rig.values(first, 0)['angle'], 0)
        self.window.undo()
        self.assertEqual(rig.values(self.canvas.document.scene['bones'][0], 0)['angle'], 0)

    def test_template_from_panel_and_auto_ik_on_hand(self):
        self.window.skeleton_panel.add_template('human')
        document = self.canvas.document
        hand = next(b for b in document.scene['bones'] if b['name'] == 'Mão esq.')
        tip = rig.world_points(document, hand, 0)[1]
        target = tip + QPointF(40, -120)
        self.drag(tip, target)
        hand = next(b for b in document.scene['bones'] if b['name'] == 'Mão esq.')
        self.assertLess(distance(rig.world_points(document, hand, 0)[1], target), 4)
        self.window.skeleton_panel.create_layers()
        names = [layer.name for layer in document.layers]
        self.assertIn('Antebraço esq.', names)
        self.assertTrue(all(b['layer'] for b in document.scene['bones']))


class ShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_style_gives_bounded_coverage(self):
        darkness = np.tile(np.linspace(0, 1, 120, dtype=np.float32), (60, 1))
        for _, style in shading.STYLES:
            amount = shading.coverage(darkness, style)
            self.assertEqual(amount.shape, darkness.shape)
            self.assertGreaterEqual(amount.min(), 0)
            self.assertLessEqual(amount.max(), 1)
            self.assertLess(amount[:, :5].mean(), .2, style)
            self.assertGreater(amount[:, -10:].mean(), .3, style)

    def shadow_document(self, style):
        document = Document(80, 60)
        base = document.layers[0]
        base.image.fill(QColor('#d06040'))
        base.content = True
        layer = document.shadow_layer('Sombras', style)
        painter = QPainter(layer.image)
        painter.fillRect(0, 0, 40, 60, QColor('black'))
        painter.end()
        document.layers.append(layer)
        return document, layer

    def test_shadow_layer_styles_change_render_not_mask(self):
        renders = {}
        for _, style in shading.STYLES:
            document, layer = self.shadow_document(style)
            mask = QImage(layer.image)
            image = document.composite()
            renders[style] = image
            self.assertEqual(layer.image, mask)
            self.assertEqual(image.pixelColor(70, 30), QColor('#d06040'))
            changed = sum(image.pixelColor(x, y) != QColor('#d06040') for x in range(0, 40, 2) for y in range(0, 60, 2))
            self.assertGreater(changed, 100, style)
        colored = renders['colored'].pixelColor(20, 30)
        self.assertGreater(colored.red(), colored.green())
        self.assertNotEqual(renders['hatch'], renders['halftone'])

    def test_shadow_layer_round_trip_and_bake_matches(self):
        document, layer = self.shadow_document('hatch')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sombra.sdp'
            document.save(path)
            restored = Document.load(path)
        self.assertTrue(restored.layers[1].is_shadow)
        self.assertEqual(restored.layers[1].shadow['style'], 'hatch')
        for style in ('soft', 'hatch', 'colored'):
            document, layer = self.shadow_document(style)
            expected = document.composite()
            from shadow_ui import composite_below
            layer.image = shading.bake(layer.image, dict(shading.DEFAULT_SHADOW, **layer.shadow), composite_below(document, 1))
            layer.kind = 'raster'
            baked = document.composite()
            difference = max(abs(expected.pixelColor(x, 30).red() - baked.pixelColor(x, 30).red()) for x in range(0, 80, 3))
            self.assertLessEqual(difference, 3, style)

    def test_window_shadow_panel_converts_and_merges(self):
        window = MainWindow(persist=False)
        window.show()
        try:
            canvas = window.canvas
            canvas.set_document(Document(120, 120))
            canvas.document.layers[0].image.fill(QColor('#80c0ff'))
            window.add_shadow_layer('hard')
            document = canvas.document
            self.assertTrue(document.layers[document.active].is_shadow)
            self.assertTrue(window.shadow_panel.isVisibleTo(window))
            canvas.fill_selection(QColor('black'))
            window.shadow_panel.style.setCurrentIndex(window.shadow_panel.style.findData('halftone'))
            self.assertEqual(document.layers[document.active].shadow['style'], 'halftone')
            before = document.composite()
            window.shadow_panel.merge_down()
            self.assertEqual(len(document.layers), 1)
            self.assertEqual(document.composite(), before)
            window.undo()
            self.assertEqual(len(document.layers), 2)
            document.saved_revision = document.revision
        finally:
            window.close()


class MannequinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_euler_round_trip(self):
        for values in ([10, 20, 30], [-45, 80, -120], [0, -170, 15]):
            np.testing.assert_allclose(mannequin.rotation(*mannequin.euler(mannequin.rotation(*values))),
                                       mannequin.rotation(*values), atol=1e-9)

    def test_models_render_and_presets_apply(self):
        for model in mannequin.MODELS:
            figure = mannequin.Figure(model)
            for name in mannequin.presets_for(model):
                figure.apply_preset(name)
            camera = mannequin.Camera()
            camera.fit(figure, view=True)
            result = mannequin.render(figure, camera, 80, 100)
            self.assertGreater(result['alpha'].sum(), 300, model)
            self.assertTrue((result['ids'] >= 0).any())
            rgb, alpha = mannequin.compose(result, {'shadow': shading.settings_for('hatch')})
            self.assertEqual(rgb.shape, (100, 80, 3))

    def test_rotate_joint_moves_hand_and_floor_shadow_exists(self):
        figure = mannequin.Figure('Corpo inteiro')
        figure.apply_preset('T-pose')
        hand = figure.joint_position('mao_e')
        figure.rotate_joint('braco_e', mannequin.axis_angle([0, 0, 1], -80))
        self.assertLess(figure.joint_position('mao_e')[1], hand[1] - 30)
        camera = mannequin.Camera(yaw=0, pitch=20)
        camera.fit(figure)
        result = mannequin.render(figure, camera, 120, 160, light=(-60, 40))
        self.assertGreater(result['floor'].sum(), 5)
        self.assertGreater(result['darkness'][result['alpha'] > .5].max(), .5)

    def test_mirror_swaps_sides(self):
        figure = mannequin.Figure()
        figure.apply_preset('Acenando')
        right = figure.joint_position('mao_d')
        figure.mirrored()
        left = figure.joint_position('mao_e')
        self.assertAlmostEqual(left[0], -right[0], delta=.01)
        self.assertAlmostEqual(left[1], right[1], delta=.01)

    def test_studio_inserts_base_and_shadow_layers(self):
        window = MainWindow(persist=False)
        window.show()
        try:
            window.canvas.set_document(Document(300, 400))
            window.pose_studio()
            studio = window.pose_window
            studio.style.setCurrentIndex(studio.style.findData('comic'))
            studio.insert()
            layers = window.canvas.document.layers
            self.assertEqual(len(layers), 3)
            self.assertFalse(layers[1].is_shadow)
            self.assertTrue(layers[2].is_shadow)
            self.assertEqual(layers[2].shadow['style'], 'comic')
            self.assertGreater(layers[1].image.pixelColor(150, 200).alpha(), 0)
            studio.close()
            window.canvas.document.saved_revision = window.canvas.document.revision
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
