"""Colour palettes and the application stylesheet (dark, flat, card-like panels).

`BASE_PALETTES` are the built-in looks; `PALETTES` holds the effective colours after the user's
appearance settings (see appearance.py) and is updated in place by `configure()`.
"""
import re
from pathlib import Path
from app_paths import DATA_ROOT

BASE_PALETTES = {
    'Escuro': dict(bg='#101114', panel='#1b1c21', field='#23252b', border='#2b2d34', text='#d5d7dd',
                   muted='#868a95', accent='#1aa38c', selected='#1f3a36', canvas='#0c0d10', hover='#262830',
                   strong='#f2f3f5', ok='#35c88a', danger='#e35d5d'),
    'Claro': dict(bg='#d9dce1', panel='#f4f5f7', field='#ffffff', border='#d3d7dd', text='#23262d',
                  muted='#6a707b', accent='#0f8f7b', selected='#d3eee9', canvas='#c3c7ce', hover='#e9ecf0',
                  strong='#0d0f12', ok='#1f9e68', danger='#c94141'),
}
PALETTES = {name: dict(colors) for name, colors in BASE_PALETTES.items()}
APPEARANCE = None


def configure(settings):
    """Apply appearance settings to the palettes; returns the normalized settings."""
    import appearance
    global APPEARANCE
    APPEARANCE = appearance.normalize(settings)
    for name in BASE_PALETTES:
        colors = appearance.palette(name, APPEARANCE)
        PALETTES[name].clear()
        PALETTES[name].update(colors)
    return APPEARANCE

ASSETS = Path(__file__).resolve().parent / 'assets'
GENERATED = DATA_ROOT / '.studio-cache' / 'theme-icons'


def _svg(name, content):
    """Small theme-coloured SVGs for indicators (written once per theme)."""
    GENERATED.mkdir(parents=True, exist_ok=True)
    path = GENERATED / name
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        path.write_text(content, encoding='utf-8')
    return path.as_posix()


def assets_for(name):
    c = PALETTES[name]
    key = name.lower()
    switch_off = _svg(f'switch-off-{key}.svg', f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="14">'
                      f'<rect x="0.5" y="0.5" width="23" height="13" rx="6.5" fill="{c["field"]}" stroke="{c["border"]}"/>'
                      f'<circle cx="7" cy="7" r="4" fill="{c["muted"]}"/></svg>')
    switch_on = _svg(f'switch-on-{key}.svg', f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="14">'
                     f'<rect x="0.5" y="0.5" width="23" height="13" rx="6.5" fill="{c["field"]}" stroke="{c["border"]}"/>'
                     f'<circle cx="17" cy="7" r="4" fill="{c["ok"]}"/></svg>')
    arrow = _svg(f'arrow-{key}.svg', f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
                 f'<path d="M3 4.5 L6 7.5 L9 4.5" fill="none" stroke="{c["muted"]}" stroke-width="1.4" '
                 f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    check = _svg(f'check-{key}.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
                 '<path d="M2.5 6.2 L5 8.6 L9.6 3.6" fill="none" stroke="#ffffff" stroke-width="1.6" '
                 'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return switch_off, switch_on, arrow, check


def stylesheet(name):
    import appearance
    import fonts
    c = PALETTES[name]
    look = APPEARANCE or appearance.normalize({})
    family = fonts.FAMILY
    switch_off, switch_on, arrow, check = assets_for(name)
    # With a background image the window areas are see-through and panels become glass.
    pictured = bool(look['background'])
    window = 'transparent' if pictured else c['bg']
    glass = appearance.rgba(c['panel'], look['panel_opacity']) if pictured else c['panel']
    veil = appearance.rgba(c['bg'], .6) if pictured else c['bg']  # keeps menu and status text readable
    return _adjust(f'''
    QWidget {{ color: {c['text']}; font-family: '{family}'; font-size: 12px; }}
    QMainWindow {{ background: {window}; }}
    QDialog {{ background: {c['bg']}; }}
    QMainWindow::separator {{ background: {window}; width: 6px; height: 6px; }}
    QMainWindow::separator:hover {{ background: {c['accent']}; }}

    QMenuBar {{ background: {veil}; padding: 4px 6px 2px 44px; }}
    QMenuBar::item {{ padding: 5px 9px; background: transparent; color: {c['text']}; border-radius: 5px; font-weight: 500; }}
    QMenuBar::item:selected {{ background: {c['hover']}; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c['selected']}; color: {c['strong']}; }}
    QMenu::item:disabled {{ color: {c['muted']}; }}
    QMenu::separator {{ background: {c['border']}; height: 1px; margin: 4px 8px; }}
    QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}

    QToolBar {{ background: {window}; spacing: 4px; border: none; }}
    QToolBar#optionsToolbar {{ background: {glass}; padding: 4px 10px; margin: 0 6px 6px 6px;
                               border-radius: 8px; spacing: 8px; }}
    QToolBar#optionsToolbar QLabel {{ color: {c['muted']}; font-size: 11px; }}
    QToolBar#optionsToolbar QCheckBox {{ color: {c['text']}; font-size: 11px; }}
    QToolBar#optionsToolbar QCheckBox::indicator {{ width: 24px; height: 14px; border: none; background: transparent;
                                                    image: url("{switch_off}"); }}
    QToolBar#optionsToolbar QCheckBox::indicator:checked {{ image: url("{switch_on}"); }}
    QToolBar::separator {{ background: {c['border']}; width: 1px; height: 1px; margin: 4px 6px; }}
    QToolBar#toolsToolbar {{ background: {glass}; padding: 6px 3px; margin: 0 0 6px 6px; border-radius: 8px; spacing: 2px; }}
    QToolBar#toolsToolbar QToolButton {{ background: transparent; border: none; border-radius: 6px;
                                         width: 30px; height: 30px; padding: 2px; }}
    QToolBar#toolsToolbar QToolButton:hover {{ background: {c['hover']}; }}
    QToolBar#toolsToolbar QToolButton:checked {{ background: {c['selected']}; }}
    QToolBar#panelStrip {{ background: {glass}; padding: 6px 3px; margin: 0 0 6px 0; border-radius: 8px; }}
    QToolBar#panelStrip QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 5px; }}
    QToolBar#panelStrip QToolButton:hover {{ background: {c['hover']}; }}
    QToolBar#panelStrip QToolButton:checked {{ background: {c['selected']}; }}

    QToolButton, QPushButton {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 5px;
                               padding: 5px 10px; color: {c['text']}; }}
    QToolButton:hover, QPushButton:hover {{ background: {c['hover']}; border-color: {c['muted']}; }}
    QToolButton:pressed, QPushButton:pressed {{ background: {c['selected']}; }}
    QToolButton:checked, QPushButton:checked {{ background: {c['selected']}; border-color: {c['accent']}; color: {c['strong']}; }}
    QPushButton:default, QPushButton#primary {{ background: {c['accent']}; border-color: {c['accent']}; color: #ffffff; }}
    QPushButton:default:hover, QPushButton#primary:hover {{ background: {c['ok']}; }}
    QToolButton#quietButton {{ border: none; background: transparent; padding: 3px; border-radius: 5px; }}
    QToolButton#quietButton:hover {{ background: {c['hover']}; }}
    QToolButton#quietButton:checked {{ background: {c['selected']}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}

    QLabel#toolBadge {{ color: {c['strong']}; font-weight: 600; }}
    QLabel#brandLabel {{ color: {c['muted']}; font-size: 10px; font-weight: 600; padding-right: 12px; }}
    QFrame#documentBar {{ background: {glass}; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
    QLabel#documentTab {{ color: {c['strong']}; padding: 7px 4px 7px 14px; font-size: 12px; font-weight: 500; }}
    QToolButton#tabClose {{ border: none; background: transparent; padding: 2px; border-radius: 4px; }}
    QToolButton#tabClose:hover {{ background: {c['hover']}; }}
    QWidget#documentView {{ background: {c['canvas']}; border-radius: 8px; }}
    QWidget#documentFrame {{ background: {window}; }}
    QWidget#panel, QTabWidget::pane {{ background: {glass}; }}
    QDockWidget {{ color: {c['text']}; }}
    QDockWidget > QWidget {{ background: {glass}; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; }}
    QWidget#dockHeader {{ background: {glass}; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
    QLabel#dockTitle {{ font-size: 12px; font-weight: 600; color: {c['strong']}; letter-spacing: .2px; }}
    QLabel#section {{ color: {c['muted']}; font-size: 10px; font-weight: 600; letter-spacing: .6px; }}
    QLabel#muted {{ color: {c['muted']}; font-size: 11px; }}

    QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit, QPlainTextEdit {{ background: {c['field']};
        border: 1px solid {c['border']}; border-radius: 5px; padding: 3px 7px; min-height: 17px;
        selection-background-color: {c['accent']}; }}
    QComboBox:hover, QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {c['muted']}; }}
    QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
    QComboBox {{ padding-right: 22px; }}
    QComboBox::drop-down {{ width: 20px; border: none; background: transparent; }}
    QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
    QComboBox#stabilizerControl {{ color: {c['accent']}; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 6px; padding: 3px; selection-background-color: {c['selected']}; outline: none; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

    QSlider::groove:horizontal {{ background: {c['field']}; height: 4px; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {c['strong']}; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
    QSlider::handle:horizontal:hover {{ background: {c['accent']}; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{ color: {c['muted']}; background: transparent; font-size: 12px; font-weight: 500; padding: 7px 10px 6px 10px;
                   border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['strong']}; border-bottom: 2px solid {c['accent']}; }}
    QTabBar::tab:hover {{ color: {c['strong']}; }}

    QListWidget, QTreeWidget, QTableWidget {{ background: {c['field']}; border: 1px solid {c['border']};
        border-radius: 6px; outline: none; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {c['selected']}; color: {c['strong']}; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c['hover']}; }}
    QListWidget#layerList {{ background: transparent; border: none; }}
    QTreeWidget::item {{ padding: 3px 0; }}
    QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none;
                           border-bottom: 1px solid {c['border']}; padding: 4px 6px; }}
    QTableWidget {{ gridline-color: {c['border']}; }}

    QCheckBox, QRadioButton {{ spacing: 7px; font-size: 12px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {c['muted']}; border-radius: 4px; background: {c['field']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{check}"); }}
    QGroupBox {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; margin-top: 18px;
                 padding: 10px 8px 8px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['muted']}; font-weight: 600; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 3px 1px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 1px 3px; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 3px; min-width: 28px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QStatusBar {{ background: {veil}; color: {c['muted']}; }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ padding: 0 8px; font-size: 11px; color: {c['muted']}; }}
    QLabel#readyLabel {{ color: {c['ok']}; }}
    QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 6px;
               padding: 6px 9px; font-size: 11px; }}
    QWidget:disabled {{ color: {c['muted']}; }}
    QWidget#posePanel, QWidget#cardPanel {{ background: {glass}; }}
    QLabel#title {{ font-size: 13px; font-weight: 600; color: {c['strong']}; }}
    QDockWidget#timelineDockV3 > QWidget {{ border-radius: 8px; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 7px; }}
    QComboBox#languageCombo {{ padding-right: 18px; }}
    QFrame#shadowPanel {{ background: {c['field']}; border-radius: 8px; }}
    QFrame#layerHeader {{ background: transparent; }}
    ''', look)


def _adjust(css, look):
    """Scale text sizes, corner radii and border widths of the stylesheet to the user's choices."""
    delta = look['font_size'] - 12
    if delta:
        css = re.sub(r'font-size: (\d+)px', lambda m: f'font-size: {max(8, int(m[1]) + delta)}px', css)
    radius = look['radius']
    if radius != 8:
        lines = []
        for line in css.split('\n'):
            # Slider handles, scrollbars and check indicators keep their own geometry.
            if not any(part in line for part in ('QSlider', 'QScrollBar', 'indicator')):
                line = re.sub(r'(border(?:-[a-z]+)*-radius): (\d+)px',
                              lambda m: f'{m[1]}: {round(int(m[2]) * radius / 8)}px', line)
            lines.append(line)
        css = '\n'.join(lines)
    width = look['border_width']
    if width != 1:
        css = re.sub(r'(border(?:-top|-bottom|-left|-right)?): 1px solid', lambda m: f'{m[1]}: {width}px solid', css)
    return css
