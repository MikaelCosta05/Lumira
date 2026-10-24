import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

import appearance
import fonts
import main
import themes
from appearance_ui import AppearanceDialog
from main import MainWindow


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(persist=False)
        self.window.resize(1200, 800)
        self.window.show()
        self.app.processEvents()
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.window.canvas.document.saved_revision = self.window.canvas.document.revision
        self.window.close()
        self.app.processEvents()
        themes.configure({})
        fonts.apply('', 12)
        self.folder.cleanup()

    def image_file(self, name='background.png', color='#d53a9d'):
        image = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(color))
        path = str(Path(self.folder.name) / name)
        image.save(path)
        return path

    def test_settings_are_validated(self):
        value = appearance.normalize({'font_size': 99, 'radius': -4, 'panel_opacity': 'x', 'background_fit': 'zoom',
                                      'colors': {'Escuro': {'accent': '#ff0000', 'bg': 'not a colour', 'nope': '#fff'}},
                                      'preset': 'Inexistente'})
        self.assertEqual(value['font_size'], 16)
        self.assertEqual(value['radius'], 0)
        self.assertEqual(value['panel_opacity'], appearance.DEFAULTS['panel_opacity'])
        self.assertEqual(value['background_fit'], 'cover')
        self.assertEqual(value['colors'], {'Escuro': {'accent': '#ff0000'}, 'Claro': {}})
        self.assertEqual(value['preset'], 'Padrão')

    def test_each_mode_keeps_its_own_colours_and_accent_tints_selection(self):
        themes.configure({'colors': {'Escuro': {'accent': '#ff0000'}, 'Claro': {'bg': '#ffeedd'}}})
        dark, light = themes.PALETTES['Escuro'], themes.PALETTES['Claro']
        self.assertEqual(dark['accent'], '#ff0000')
        self.assertNotEqual(dark['selected'], themes.BASE_PALETTES['Escuro']['selected'])
        self.assertEqual(dark['bg'], themes.BASE_PALETTES['Escuro']['bg'])
        self.assertEqual(light['bg'], '#ffeedd')
        self.assertEqual(light['accent'], themes.BASE_PALETTES['Claro']['accent'])
        themes.configure({})
        self.assertEqual(themes.PALETTES, themes.BASE_PALETTES)

    def test_every_preset_restyles_both_modes(self):
        for name in appearance.PRESET_NAMES:
            settings = themes.configure({'preset': name, 'colors': appearance.preset_colors(name)})
            for mode in ('Escuro', 'Claro'):
                css = themes.stylesheet(mode)
                self.assertIn(themes.PALETTES[mode]['accent'], css, (name, mode))
            self.assertEqual(settings['preset'], name)

    def test_stylesheet_follows_text_size_corners_borders_and_background(self):
        themes.configure({'font_size': 14, 'radius': 0, 'border_width': 2})
        css = themes.stylesheet('Escuro')
        self.assertIn('font-size: 14px', css)
        self.assertNotIn('border-radius: 8px', css)
        self.assertIn('border: 2px solid', css)
        handle = next(line for line in css.splitlines() if 'QSlider::handle:horizontal {' in line)
        self.assertIn('border-radius: 6px', handle)  # round handles keep their shape
        themes.configure({'background': self.image_file(), 'panel_opacity': .5})
        css = themes.stylesheet('Escuro')
        self.assertIn('QMainWindow { background: transparent; }', css)
        self.assertIn(appearance.rgba(themes.PALETTES['Escuro']['panel'], .5), css)

    def test_background_image_is_painted_behind_panels_and_canvas(self):
        path = self.image_file()
        self.window.apply_appearance(dict(self.window.appearance, background=path, background_opacity=1.,
                                          background_canvas=True, canvas_opacity=0.))
        pixmap = self.window.background_pixmap()
        self.assertEqual(pixmap.size(), self.window.size())
        self.assertEqual(pixmap.toImage().pixelColor(5, 5).name(), '#d53a9d')
        canvas = self.window.canvas
        corner = canvas.grab().toImage().pixelColor(3, canvas.height() - 3)
        self.assertEqual(corner.name(), '#d53a9d')
        for fit in [value for _, value in appearance.FITS]:
            self.window.apply_appearance(dict(self.window.appearance, background_fit=fit, background_blur=6))
            self.assertIsNotNone(self.window.background_pixmap())
        self.window.apply_appearance(dict(self.window.appearance, background=''))
        self.assertIsNone(self.window.background_pixmap())

    def test_missing_background_file_is_dropped(self):
        self.window.apply_appearance(dict(self.window.appearance, background=str(Path(self.folder.name) / 'gone.png')))
        self.assertEqual(self.window.appearance['background'], '')

    def test_dialog_previews_live_and_cancel_restores_everything(self):
        before = json.dumps(self.window.appearance, sort_keys=True)
        dialog = AppearanceDialog(self.window)
        dialog.preset.setCurrentIndex(dialog.preset.findData('Âmbar'))
        dialog.set_mode('Claro')
        dialog.set_color('accent', '#123456')
        dialog.font_size.setValue(14)
        dialog.preview()
        self.assertEqual(self.window.theme, 'Claro')
        self.assertEqual(themes.PALETTES['Claro']['accent'], '#123456')
        self.assertEqual(self.window.appearance['preset'], 'Personalizado')
        dialog.reject()
        self.assertEqual(json.dumps(self.window.appearance, sort_keys=True), before)
        self.assertEqual(self.window.theme, 'Escuro')
        self.assertEqual(themes.PALETTES['Claro']['accent'], themes.BASE_PALETTES['Claro']['accent'])

    def test_dialog_apply_keeps_choices_and_returns_to_the_users_mode(self):
        dialog = AppearanceDialog(self.window)
        dialog.preset.setCurrentIndex(dialog.preset.findData('Floresta'))
        dialog.set_mode('Claro')
        dialog.radius.setValue(3)
        dialog.accept()
        self.assertEqual(self.window.theme, 'Escuro')
        self.assertEqual(self.window.appearance['preset'], 'Floresta')
        self.assertEqual(self.window.appearance['radius'], 3)
        self.assertEqual(themes.PALETTES['Escuro']['accent'], appearance.PRESETS['Floresta']['Escuro']['accent'])

    def test_theme_files_round_trip_without_machine_paths(self):
        path = Path(self.folder.name) / 'tema.studiotheme'
        settings = appearance.normalize({'preset': 'Rosa', 'colors': appearance.preset_colors('Rosa'),
                                         'font_size': 13, 'background': self.image_file()})
        appearance.export_theme(path, settings)
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertNotIn('background', data)
        loaded = appearance.import_theme(path, appearance.normalize({}))
        self.assertEqual(loaded['colors'], settings['colors'])
        self.assertEqual(loaded['font_size'], 13)
        broken = Path(self.folder.name) / 'broken.json'
        broken.write_text('[1, 2]', encoding='utf-8')
        with self.assertRaises(ValueError):
            appearance.import_theme(broken, settings)

    def test_saved_settings_keep_a_copy_of_the_background(self):
        root = Path(self.folder.name)
        source = self.image_file('original.png', '#336699')
        self.window.apply_appearance(dict(self.window.appearance, background=source, font_size=13))
        self.window.persist = True
        self.window.settings_path = root / 'settings.json'
        with mock.patch.object(main, 'ROOT', root):
            self.window.save_settings()
        self.window.persist = False
        saved = json.loads((root / 'settings.json').read_text(encoding='utf-8'))['appearance']
        self.assertEqual(Path(saved['background']), root / '.studio-background.png')
        self.assertTrue((root / '.studio-background.png').exists())
        self.assertEqual(saved['font_size'], 13)

    def test_interface_font_can_change(self):
        family = fonts.apply('Arial', 14)
        self.assertIn(family, ('Arial', fonts.DEFAULT))
        self.assertEqual(QApplication.instance().font().pixelSize(), 14)
        self.assertEqual(fonts.apply('Fonte que não existe', 12), fonts.DEFAULT)


if __name__ == '__main__':
    unittest.main()
