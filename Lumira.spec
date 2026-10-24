# Build a single Windows executable with its Python runtime and all assets.
from pathlib import Path
from importlib.metadata import distribution
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'assets'), 'assets'), (str(root / 'translations'), 'translations')]
binaries = []
hiddenimports = []

# Native modules and namespace imports loaded by graphics and Windows media APIs.
for package in ('winrt', 'glcontext', 'imageio_ffmpeg'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

# resources.py deliberately loads this parser as a file, without importing the
# package initializer (which would attempt to install a Krita plugin).
parser = distribution('abr-brush-importer').locate_file('abr_brush_importer/abr_parser.py')
datas += [(str(parser), 'abr_brush_importer')]
datas += copy_metadata('abr-brush-importer')

a = Analysis(
    [str(root / 'standalone.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['PyQt5', 'PySide2', 'PySide6', 'tkinter', 'pytest', 'IPython'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='Lumira',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon='NONE',
)
