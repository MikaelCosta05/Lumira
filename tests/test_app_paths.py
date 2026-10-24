"""User data must survive a one-file executable's temporary extraction."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths


class AppPathsTests(unittest.TestCase):
    def test_source_uses_project_folder(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(app_paths.data_root(), app_paths.RESOURCE_ROOT)

    def test_frozen_uses_persistent_local_appdata(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}, clear=True):
                with patch.object(sys, 'frozen', True, create=True):
                    root = app_paths.data_root()
                    self.assertEqual(root, Path(folder) / 'Lumira')
                    self.assertTrue(root.is_dir())

    def test_frozen_keeps_data_from_the_old_name(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'Studio Desenho').mkdir()
            (Path(folder) / 'Studio Desenho' / '.studio-settings.json').write_text('{}')
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}, clear=True):
                with patch.object(sys, 'frozen', True, create=True):
                    root = app_paths.data_root()
                    self.assertTrue((root / '.studio-settings.json').is_file())
                    self.assertFalse((Path(folder) / 'Studio Desenho').exists())

    def test_explicit_directory_supports_isolated_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'LUMIRA_DATA_DIR': str(Path(folder) / 'data')}):
                self.assertTrue(app_paths.data_root().is_dir())

    def test_frozen_brush_cache_does_not_require_source_file(self):
        import resources
        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(resources, '__file__', str(Path(tempfile.gettempdir()) / 'missing-studio-source.py')):
                self.assertTrue(resources._tip_cache_version().startswith(f'{resources.TIP_SIZE}-'))
