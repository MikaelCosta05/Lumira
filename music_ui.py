"""Status-bar music controls (Spotify) that appear while something is playing."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QWidget

from design_widgets import icon
from media_control import MediaController
from themes import PALETTES

SPOTIFY_GREEN = '#1db954'


class MusicWidget(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.state = {'available': False}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(3)
        self.logo = QLabel()
        self.logo.setFixedSize(16, 16)
        layout.addWidget(self.logo)
        self.track = QLabel()
        self.track.setObjectName('muted')
        self.track.setMaximumWidth(260)
        layout.addWidget(self.track)
        self.buttons = {}
        for name, tip in (('previous', 'Faixa anterior'), ('toggle', 'Tocar / pausar'), ('next', 'Próxima faixa')):
            button = QToolButton()
            button.setObjectName('quietButton')
            button.setFixedSize(22, 22)
            button.setIconSize(QSize(15, 15))
            button.setToolTip(tip)
            button.clicked.connect(lambda checked=False, n=name: self.owner.music.command(n))
            layout.addWidget(button)
            self.buttons[name] = button
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(70)
        self.volume.setToolTip('Volume do Spotify (mixer do Windows)')
        self.volume.valueChanged.connect(self.volume_changed)
        layout.addWidget(self.volume)
        self.hide()
        self.refresh_icons()

    def refresh_icons(self):
        colors = PALETTES[self.owner.theme]
        spotify = self.state.get('spotify', True)
        self.logo.setPixmap(icon('spotify' if spotify else 'music-note', SPOTIFY_GREEN if spotify else colors['accent']).pixmap(16, 16))
        names = {'previous': 'skip-previous', 'toggle': 'pause' if self.state.get('playing') else 'play', 'next': 'skip-next'}
        for key, button in self.buttons.items():
            button.setIcon(icon(names[key], colors['text']))

    def update_state(self, state):
        self.state = state
        if not state.get('available'):
            self.hide()
            return
        title, artist = state.get('title', ''), state.get('artist', '')
        text = f'{artist} — {title}' if artist and title else title or artist or state.get('app', 'Música')
        self.track.setText(self.track.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 250))
        self.track.setToolTip(f"{state.get('app', '')}: {text}" + (f"\n{state['album']}" if state.get('album') else ''))
        self.buttons['next'].setEnabled(state.get('can_next', True))
        self.buttons['previous'].setEnabled(state.get('can_previous', True))
        volume = state.get('volume')
        self.volume.setVisible(volume is not None)
        if volume is not None and not self.volume.isSliderDown():
            self.volume.blockSignals(True)
            self.volume.setValue(round(volume * 100))
            self.volume.blockSignals(False)
        self.refresh_icons()
        self.show()

    def volume_changed(self, value):
        self.owner.music.command('volume', value / 100)

    def wheelEvent(self, event):
        if self.volume.isVisible():
            self.volume.setValue(self.volume.value() + (5 if event.angleDelta().y() > 0 else -5))


def setup_music(owner):
    owner.music = MediaController(owner, any_player=bool(owner.settings.get('music_any', False)))
    owner.music_widget = MusicWidget(owner)
    owner.statusBar().insertPermanentWidget(0, owner.music_widget)
    owner.music.state_changed.connect(owner.music_widget.update_state)
    menu = next(a.menu() for a in owner.menuBar().actions() if a.text() == 'Exibir')
    menu.addSeparator()
    owner.music_action = owner.action(menu, 'Controle do Spotify na barra de status', lambda value: toggle_music(owner, value))
    owner.music_action.setCheckable(True)
    owner.music_any_action = owner.action(menu, 'Aceitar outros players (navegador, YouTube…)', lambda value: toggle_any(owner, value))
    owner.music_any_action.setCheckable(True)
    owner.music_any_action.setChecked(owner.music.any_player)
    enabled = bool(owner.settings.get('music', True)) and owner.persist
    owner.music_action.setChecked(enabled)
    if enabled:
        owner.music.start()


def toggle_music(owner, value):
    if value:
        owner.music.start()
    else:
        owner.music.stop()
        owner.music_widget.hide()


def toggle_any(owner, value):
    owner.music.any_player = bool(value)
