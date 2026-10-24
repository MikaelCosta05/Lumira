"""Integration checks executed inside the packaged application."""
import json
import os
import sys
import traceback
from pathlib import Path


def run_check(report_path):
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    window = None
    try:
        # Checks must never alter the user's normal settings or brush library.
        if not os.environ.get('STUDIO_DESENHO_DATA_DIR'):
            raise RuntimeError('Set STUDIO_DESENHO_DATA_DIR to an isolated test directory.')
        from app_paths import DATA_ROOT, RESOURCE_ROOT
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QColor, QFontDatabase
        from main import MainWindow
        import fonts
        import gltf
        import i18n
        import media
        import media_control
        import model3d
        import resources
        import sounddevice
        import qtawesome
        import render3d
        from document import Document
        from scipy import ndimage
        from pycaw.pycaw import AudioUtilities

        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        settings = DATA_ROOT / '.studio-settings.json'
        previous = settings.exists()
        window = MainWindow(persist=True)
        window.show()
        app.processEvents()
        if previous and window.canvas.grid_size != 37:
            raise RuntimeError('Settings did not survive a restart.')
        if previous and 'Standalone check' not in window.library.palettes:
            raise RuntimeError('Library did not survive a restart.')
        report['reopened'] = previous
        report['checks'].append('interface and persistent settings/library')

        if 'Inter' not in QFontDatabase.families() or qtawesome.icon('fa6s.pen').isNull():
            raise RuntimeError('Bundled fonts/icons failed to load.')
        if not i18n.TABLE_PATH.is_file():
            raise RuntimeError('Translations are missing.')
        report['checks'].append('Inter fonts, QtAwesome icons and translations')

        if len(window.library.brushes) < 20:
            raise RuntimeError('Brushes failed to load.')
        # Third-party .abr files and 3D models are not in the repository; check them only when present.
        abr = next((RESOURCE_ROOT / 'assets' / 'Brushes').glob('*.abr'), None)
        if abr:
            brushes = resources.load_abr(abr)
            if not brushes:
                raise RuntimeError('ABR brushes failed to load.')
            report['abr_brushes'] = len(brushes)
        report['checks'].append('built-in brushes, SciPy and dynamic ABR parser')

        models = model3d.library_models()
        if models:
            model = gltf.load(models[0][1], 256)
            if model.triangles <= 0:
                raise RuntimeError('Bundled 3D models failed to load.')
        report['models'] = len(models)
        report['opengl_available'] = render3d.available()
        report['checks'].append('3D model loading and graphics backend import')

        document = Document(64, 48)
        document.layers[0].image.fill(QColor('#2f91c7'))
        project = DATA_ROOT / 'check.sdp'
        document.save(project)
        loaded = Document.load(project)
        if loaded.layers[0].image.pixelColor(0, 0).name() != '#2f91c7':
            raise RuntimeError('Project round trip failed.')
        if not loaded.layers[0].image.save(str(DATA_ROOT / 'check.png')):
            raise RuntimeError('PNG export failed.')
        media.ffmpeg(['-y', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:d=0.1',
                      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(DATA_ROOT / 'check.mp4')])
        report['checks'].append('SDP save/reload, PNG and MP4 export with bundled FFmpeg')

        media_control._load_winrt()
        report['portaudio'] = sounddevice.get_portaudio_version()[1]
        report['checks'].append('WinRT, pycaw and bundled PortAudio')
        window.canvas.grid_size = 37
        window.library.palettes['Standalone check'] = ['#2f91c7']
        window.library.save()
        window.grab().save(str(Path(report_path).with_suffix('.png')))
        window.close()
        app.processEvents()
        report['data_root'] = str(DATA_ROOT)
        report['resource_root'] = str(RESOURCE_ROOT)
        report['python_paths'] = sys.path
        report['ok'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        if window is not None:
            window.close()
    Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if report['ok'] else 1
