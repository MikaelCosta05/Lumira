import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRect
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

import brush_engine
import display
import media_control
import resources
from document import Document
from main import MainWindow

ROOT = Path(__file__).resolve().parents[1]
PENS = ROOT / 'assets' / 'Brushes' / 'nanda_s_real_pen_and_marker_brushes_for_photoshop_by_soenanda_d67j37s.abr'


def alpha(image):
    return brush_engine.alpha_of(image)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.brushes = {b.name: b for b in resources.builtin_brushes()}

    def test_textures_tile_and_are_normalized(self):
        for _, kind in brush_engine.GRAINS:
            if kind in ('', 'custom'):
                continue
            texture = brush_engine.grain_texture(kind)
            self.assertEqual(texture.shape, (brush_engine.GRAIN_SIZE, brush_engine.GRAIN_SIZE))
            self.assertGreater(texture.std(), .1, kind)
            seam = np.abs(texture[:, 0] - texture[:, -1]).mean()
            inner = np.abs(np.diff(texture, axis=1)).mean()
            self.assertLess(seam, inner * 3, kind)

    def test_grain_breaks_up_light_pencil_strokes(self):
        pencil = self.brushes['Lápis HB']
        solid = brush_engine.finish_alpha(np.full((60, 60), 1., np.float32), 0, 0, pencil, 6)
        light = brush_engine.finish_alpha(np.full((60, 60), .4, np.float32), 0, 0, pencil, 6)
        self.assertGreater(solid.mean(), light.mean())
        self.assertGreater((light == 0).mean(), .05)
        self.assertGreater(light.std(), .02)

    def test_wet_edges_darken_the_rim(self):
        watercolor = resources.Brush('Teste', 30, wet_edges=.8)
        disc = np.zeros((80, 80), np.float32)
        y, x = np.mgrid[0:80, 0:80]
        disc[(x - 40) ** 2 + (y - 40) ** 2 < 25 ** 2] = .5
        result = brush_engine.finish_alpha(disc, 0, 0, watercolor, 30)
        self.assertGreater(result[40, 16], result[40, 40])

    def test_every_builtin_previews_with_visible_ink(self):
        self.assertGreaterEqual(len(self.brushes), 20)
        for name in ('Lápis HB', 'Giz pastel', 'Carvão', 'Aquarela', 'Pincel seco', 'Óleo / acrílica', 'Respingos'):
            self.assertIn(name, self.brushes)
        for brush in self.brushes.values():
            image = brush_engine.preview(brush, '#202020', 120, 40, size=10)
            self.assertGreater(alpha(image).sum(), 15, brush.name)

    def test_small_dabs_use_area_averaged_tip(self):
        stroke = brush_engine.StampStroke(self.brushes['Lápis HB'], QColor('black'))
        small = stroke.tip_for(4)
        self.assertLess(small.width(), 10)
        self.assertIs(stroke.tip_for(4), small)
        self.assertIs(stroke.tip_for(stroke.tip.width()), stroke.tip)

    def test_thin_elliptical_tip_draws_continuously(self):
        brush = resources.Brush('Caligrafia', 30, hardness=1., spacing=.2, angle=-55, roundness=.25)
        image = brush_engine.render_stroke(brush, QColor('black'), 30, brush_engine.preview_samples(200, 60), 200, 60,
                                           pressure_enabled=False)
        columns = (alpha(image) > .5).any(axis=0)
        start, end = np.argmax(columns), len(columns) - np.argmax(columns[::-1])
        self.assertTrue(columns[start:end].all())

    def test_pressure_sets_the_tone_instead_of_building_up(self):
        brush = resources.Brush('Tom', 12, hardness=1., spacing=.05, opacity_pressure=1.)
        samples = [brush_engine._Sample(10 + n, 30, .3) for n in range(150)]
        image = brush_engine.render_stroke(brush, QColor('black'), 12, samples, 180, 60, pressure_enabled=False)
        self.assertAlmostEqual(alpha(image).max(), .3, delta=.02)

    def test_bristle_streaks_survive_overlapping_dabs(self):
        brush = self.brushes['Óleo / acrílica']
        samples = [brush_engine._Sample(10 + n * .5, 40, 1.) for n in range(300)]
        image = brush_engine.render_stroke(brush, QColor('black'), 40, samples, 180, 80, pressure_enabled=False)
        profile = alpha(image)[22:58, 60:120].mean(axis=1)
        self.assertGreater(profile.max() - np.sort(profile)[len(profile) // 2], .1)

    def test_directional_first_dab_lies_along_the_stroke(self):
        flat = self.brushes['Pincel chato']
        samples = [brush_engine._Sample(60, 20 + n, 1.) for n in range(80)]
        image = alpha(brush_engine.render_stroke(flat, QColor('black'), 30, samples, 120, 120))
        self.assertGreater(image[20:100, 45:75].max(), .3)
        self.assertLess(image[:14].max(), .05)  # a dab across the start would reach 15 px above it
        tap = alpha(brush_engine.render_stroke(flat, QColor('black'), 30, [brush_engine._Sample(60, 60, 1.)], 120, 120))
        self.assertGreater(tap.max(), .3)

    def test_paint_runs_out_along_the_stroke(self):
        brush = resources.Brush('Seco', 10, hardness=1., spacing=.05, depletion=.5)
        samples = [brush_engine._Sample(5 + n, 20, 1.) for n in range(400)]
        values = alpha(brush_engine.render_stroke(brush, QColor('black'), 10, samples, 420, 40))
        self.assertGreater(values[:, 10:40].max(), .9)
        self.assertLess(values[:, 300:].max(), .1)

    def test_scaled_grain_is_interpolated(self):
        texture = brush_engine.grain_texture('paper')
        patch = brush_engine.grain_patch(texture, 0, 0, 64, 64, 2.5)
        steps = np.abs(np.diff(patch, axis=1))
        self.assertLess(steps.max(), np.abs(np.diff(texture, axis=1)).max())
        self.assertGreater(len(np.unique(patch)), 64 * 64 * .9)

    def test_new_brush_controls_are_clamped_and_round_trip(self):
        brush = resources.Brush.from_dict({'name': 'X', 'count': 40, 'speed_size': -3, 'taper_in': 2,
                                           'grain_contrast': 9, 'flip_jitter': 1, 'grain': 'halftone'})
        self.assertEqual((brush.count, brush.speed_size, brush.taper_in, brush.grain_contrast), (16, -1., 1., 4.))
        self.assertIs(brush.flip_jitter, True)
        self.assertEqual(resources.brushes_from_code(resources.share_code([brush]))[0].grain, 'halftone')
        old = resources.Brush.from_dict({'name': 'Antigo', 'size': 8})  # brushes saved before these controls
        self.assertEqual((old.count, old.taper_in, old.grain_contrast), (1, 0., 1.))

    def test_start_taper_and_count(self):
        line = [brush_engine._Sample(10 + n, 30, 1.) for n in range(200)]
        def ink(**values):
            brush = resources.Brush('T', 20, hardness=1., **{'spacing': .05, **values})
            return alpha(brush_engine.render_stroke(brush, QColor('black'), 20, line, 220, 60, pressure_enabled=False))
        plain, tapered = ink(), ink(taper_in=.5)
        self.assertLess((tapered[:, 12:20] > .5).sum(), (plain[:, 12:20] > .5).sum() * .5)
        self.assertAlmostEqual((tapered[:, 180:200] > .5).sum(), (plain[:, 180:200] > .5).sum(), delta=8)
        single = ink(spacing=1.5, scatter=1.)
        many = ink(spacing=1.5, scatter=1., count=6)
        self.assertGreater((many > .5).sum(), (single > .5).sum() * 2)

    def test_every_preset_texture_tiles_and_inverting_changes_the_grain(self):
        for _, kind in brush_engine.GRAINS:
            if kind in ('', 'custom'):
                continue
            self.assertIn(kind, resources.GRAIN_KINDS)
            texture = brush_engine.grain_texture(kind)
            self.assertGreater(texture.std(), .08, kind)
            self.assertLess(np.abs(texture[:, 0] - texture[:, -1]).mean(), np.abs(np.diff(texture, axis=1)).mean() * 3, kind)
        plain = resources.Brush('G', 20, grain='halftone', grain_strength=.8)
        inverted = resources.Brush('G', 20, grain='halftone', grain_strength=.8, grain_invert=True)
        coverage = np.full((40, 40), .5, np.float32)
        a = brush_engine.finish_alpha(coverage, 0, 0, plain, 20)
        b = brush_engine.finish_alpha(coverage, 0, 0, inverted, 20)
        self.assertLess(np.corrcoef(a.ravel(), b.ravel())[0, 1], 0)

    def test_share_code_round_trip_and_rejects_garbage(self):
        code = resources.share_code([self.brushes['Aquarela'], self.brushes['Carvão']])
        restored = resources.brushes_from_code('  ' + code[:60] + '\n' + code[60:])
        self.assertEqual([b.name for b in restored], ['Aquarela', 'Carvão'])
        self.assertEqual(restored[0].wet_edges, self.brushes['Aquarela'].wet_edges)
        old = resources.OLD_SHARE_PREFIX + code[len(resources.SHARE_PREFIX):]
        self.assertEqual([b.name for b in resources.brushes_from_code(old)], ['Aquarela', 'Carvão'])
        with self.assertRaises(ValueError):
            resources.brushes_from_code('qualquer coisa')
        with self.assertRaises(ValueError):
            resources.brushes_from_code(resources.SHARE_PREFIX + 'AAAA')

    @unittest.skipUnless(PENS.exists(), 'arquivo ABR de exemplo ausente')
    def test_abr_presets_keep_names_spacing_and_dynamics(self):
        brushes = {b.name: b for b in resources.load_abr(PENS)}
        self.assertIn('Real Ballpoint Pen', brushes)
        self.assertIn('Real Fineliner', brushes)
        self.assertFalse(any(resources._uuid_like(name) for name in brushes))
        self.assertAlmostEqual(brushes['Real Ballpoint Pen'].spacing, .5)
        self.assertAlmostEqual(brushes['Real Gel Pen'].spacing, .05)
        self.assertTrue(brushes['Real Fineliner'].size_pressure)
        self.assertGreater(brushes['Real Highlighter'].wet_edges, 0)
        self.assertFalse(brushes['Ink Brush'].tip)
        self.assertAlmostEqual(brushes['Ink Brush'].roundness, .25)
        self.assertTrue(brushes['Real Marker'].tip)

    def test_library_imports_unique_names(self):
        with tempfile.TemporaryDirectory() as folder:
            library = resources.ResourceLibrary(Path(folder) / 'lib.json')
            imported = library.import_code(resources.share_code([self.brushes['Carvão']]))
            self.assertEqual(imported[0].name, 'Carvão (2)')
            path = Path(folder) / 'meus.sbrush'
            library.export_brushes(path, imported)
            again = resources.ResourceLibrary(Path(folder) / 'lib.json').import_brushes(path)
            self.assertEqual(again[0].grain, 'charcoal')


class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_levels_and_smoothing(self):
        self.assertEqual(display.level_for(1.), 0)
        self.assertEqual(display.level_for(.6), 0)
        self.assertEqual(display.level_for(.3), 1)
        self.assertEqual(display.level_for(.1), 3)
        self.assertTrue(display.smooth_for(1.25))
        self.assertFalse(display.smooth_for(2.))
        self.assertFalse(display.smooth_for(6.))

    def test_reduce_averages_area(self):
        image = QImage(4, 2, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setPixelColor(0, 0, QColor(255, 255, 255))
        reduced = display.reduce(image, 2)
        self.assertEqual((reduced.width(), reduced.height()), (2, 1))
        self.assertAlmostEqual(reduced.pixelColor(0, 0).alpha(), 64, delta=1)

    def test_incremental_view_matches_full_rebuild(self):
        document = Document(300, 200)
        view = display.ReducedView()
        view.layers(document, 2)
        painter = QPainter(document.layers[0].image)
        painter.fillRect(37, 41, 30, 22, QColor('red'))
        painter.end()
        view.mark(QRect(37, 41, 30, 22))
        incremental = view.layers(document, 2)
        full = display.reduce(display.flatten(document.layers, QRect(0, 0, 300, 200)), 4)
        self.assertEqual(incremental, full)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.show()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.canvas.set_document(Document(400, 300))

    def tearDown(self):
        self.canvas.finish_interaction()
        self.canvas.document.saved_revision = self.canvas.document.revision
        self.window.close()
        self.app.processEvents()

    def stroke(self, points, pressure=.6):
        position = lambda p: self.canvas.transform().map(QPointF(*p))
        self.canvas.begin_stroke(position(points[0]), pressure, 100)
        for n, point in enumerate(points[1:], 1):
            self.canvas.move_stroke(position(point), pressure, 100 + n * .02)
        self.canvas.finish_stroke(position(points[-1]), pressure, 100 + len(points) * .02)

    def test_textured_brush_on_canvas_and_zoomed_out_view(self):
        panel = self.window.brush_panel
        charcoal = next(b for b in self.window.library.brushes if b.name == 'Carvão')
        panel.refresh_list(select=charcoal)
        panel.use()
        self.assertIs(self.window.selected_brush, charcoal)
        self.stroke([(40 + i * 6, 150) for i in range(50)])
        values = alpha(self.canvas.image)[130:170, 60:300]
        self.assertGreater(values.max(), .5)
        self.assertGreater(((values > 0) & (values < .95)).mean(), .05, 'grain should leave partial coverage')
        self.canvas.set_zoom(.2)
        self.canvas.grab()
        self.stroke([(40, 60), (300, 70)])
        self.canvas.grab()
        self.window.undo()
        self.canvas.grab()

    def test_solid_round_stroke_keeps_an_antialiased_edge(self):
        solid = next(b for b in self.window.library.brushes if b.name == 'Redondo sólido')
        self.window.tool_brushes['brush'] = solid
        self.window.size_spin.setValue(6)
        self.stroke([(40 + i * 3, 60 + i * 1.7) for i in range(100)], pressure=1.)
        values = alpha(self.canvas.image)[80:200, 100:300]
        edge = ((values > .05) & (values < .95)).sum()
        core = (values >= .95).sum()
        # Overlapping antialiased segments used to pile up into a hard, stair-stepped edge.
        self.assertGreater(edge / core, .22)

    def test_brush_editor_offers_tips_textures_and_new_controls(self):
        from brush_ui import BrushEditor
        oil = next(b for b in self.window.library.brushes if b.name == 'Óleo / acrílica')
        editor = BrushEditor(self.window, oil, copy_of=True)
        self.assertEqual(editor.grain_gallery.count(), len(brush_engine.GRAINS))
        self.assertGreaterEqual(editor.tip_gallery.count(), len(resources.TIP_KINDS))
        for key in ('taper_in', 'speed_size', 'count', 'flow_pressure', 'opacity_jitter', 'roundness_jitter', 'grain_contrast'):
            self.assertIn(key, editor.fields)
        editor.grain_gallery.select('wood')
        editor.change_grain()
        editor.fields['count'].setValue(3)
        result = editor.result_brush()
        self.assertEqual((result.grain, result.count), ('wood', 3))
        editor.reset()
        self.assertEqual(editor.result_brush().grain, oil.grain)
        editor.close()

    @unittest.skipUnless(PENS.exists(), 'arquivo ABR de exemplo ausente')
    def test_photoshop_brushes_can_be_dropped_on_the_panel(self):
        from PyQt6.QtCore import QMimeData, QUrl
        panel = self.window.brush_panel
        before = len(self.window.library.brushes)
        self.window.library.path = None  # keep the test from writing the user's library
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(PENS))])
        self.assertEqual([Path(f) for f in panel.brush_files(SimpleNamespace(mimeData=lambda: data))], [PENS])
        panel.import_paths([str(PENS)])
        self.assertGreater(len(self.window.library.brushes), before)
        self.assertEqual(panel.import_button.text(), 'Importar')

    def test_watercolor_on_canvas_has_rim_and_no_patch_seams(self):
        watercolor = next(b for b in self.window.library.brushes if b.name == 'Aquarela')
        self.window.tool_brushes['brush'] = watercolor
        self.window.stab_combo.setCurrentIndex(self.window.stab_combo.findData('0'))
        self.window.size_spin.setValue(40)
        self.stroke([(30 + i * 4, 150) for i in range(85)], pressure=1.)
        values = alpha(self.canvas.image)
        rows = values[:, 80:320].mean(axis=1)
        filled = np.flatnonzero(rows > .02)
        top, bottom = filled[0], filled[-1]
        center = values[(top + bottom) // 2 - 2:(top + bottom) // 2 + 3, 80:320].mean(axis=0)
        rim = max(rows[top + 2:top + 7].mean(), rows[bottom - 6:bottom - 1].mean())
        self.assertGreater(rim, center.mean())
        self.assertLess(center.std() / center.mean(), .35)

    def test_music_widget_shows_only_while_playing(self):
        widget = self.window.music_widget
        widget.update_state({'available': True, 'app': 'Spotify', 'spotify': True, 'title': 'Faixa',
                             'artist': 'Artista', 'playing': True, 'volume': .4})
        self.assertFalse(widget.isHidden())
        self.assertIn('Artista — Faixa', widget.track.text())
        self.assertEqual(widget.volume.value(), 40)
        commands = []
        self.window.music.command = lambda name, value=None: commands.append((name, value))
        widget.buttons['next'].click()
        widget.volume.setValue(70)
        self.assertEqual(commands, [('next', None), ('volume', .7)])
        widget.update_state({'available': False})
        self.assertTrue(widget.isHidden())


class MediaSessionTests(unittest.TestCase):
    def test_spotify_session_is_preferred(self):
        class Session:
            def __init__(self, app):
                self.source_app_user_model_id = app
        chrome, spotify = Session('Chrome'), Session('Spotify.exe')
        self.assertIs(media_control.choose_session([chrome, spotify]), spotify)
        self.assertIsNone(media_control.choose_session([chrome], current=chrome))
        self.assertIs(media_control.choose_session([chrome], any_player=True, current=chrome), chrome)
        self.assertEqual(media_control.player_name('SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify'), 'Spotify')


if __name__ == '__main__':
    unittest.main()
