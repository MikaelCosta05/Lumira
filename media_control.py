"""Spotify (and other players) control through Windows media sessions.

Windows publishes what each player is playing (System Media Transport Controls).
The Spotify desktop app registers there, so the studio can show the track and
skip, go back or pause without any Spotify account setup. Volume is Spotify's
own slider in the Windows volume mixer. Everything runs in a background thread.
"""
import threading

from PyQt6.QtCore import QObject, pyqtSignal

import importlib.util

# The WinRT bindings are only imported by the background thread (they are slow to load).
try:
    AVAILABLE = importlib.util.find_spec('winrt.windows.media.control') is not None
except (ImportError, ValueError):  # not Windows, or the optional packages are missing
    AVAILABLE = False
SessionManager = PlaybackStatus = None


def _load_winrt():
    global SessionManager, PlaybackStatus
    if SessionManager is None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as status)
        SessionManager, PlaybackStatus = manager, status


def is_spotify(app_id):
    return 'spotify' in (app_id or '').lower()


def player_name(app_id):
    app_id = (app_id or '').lower()
    for key, name in (('spotify', 'Spotify'), ('chrome', 'Chrome'), ('msedge', 'Edge'), ('firefox', 'Firefox'),
                      ('zune', 'Media Player'), ('vlc', 'VLC'), ('music', 'Música')):
        if key in app_id:
            return name
    return app_id.split('!')[-1].split('.')[0][:20] or 'Player'


def choose_session(sessions, any_player=False, current=None):
    """Spotify first; optionally fall back to whatever Windows considers current."""
    for session in sessions:
        if is_spotify(session.source_app_user_model_id):
            return session
    return current if any_player else None


def process_volume(app_id, value=None):
    """Read or set the player's volume in the Windows mixer (0–1). Returns None if unknown."""
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        return None
    key = 'spotify' if is_spotify(app_id) else (app_id or '').lower().split('!')[-1].split('.exe')[0]
    result = None
    for session in AudioUtilities.GetAllSessions():
        process = session.Process
        if process is None or not key or key not in process.name().lower():
            continue
        volume = session.SimpleAudioVolume
        if value is not None:
            volume.SetMasterVolume(max(0., min(1., float(value))), None)
        result = volume.GetMasterVolume()
    return result


class MediaController(QObject):
    """Polls the media session in a worker thread; commands are queued to it."""
    state_changed = pyqtSignal(dict)

    def __init__(self, parent=None, interval=1.5, any_player=False):
        super().__init__(parent)
        self.interval, self.any_player = interval, any_player
        self.loop = None
        self.queue = None
        self.thread = None
        self.running = False

    def start(self):
        if not AVAILABLE:
            self.state_changed.emit({'available': False, 'reason': 'Controle de mídia indisponível neste sistema.'})
            return
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self.run, name='media-control', daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.loop and self.queue:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ('stop', None))

    def command(self, name, value=None):
        if self.loop and self.queue and self.running:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, (name, value))

    def run(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except (ImportError, OSError):
            pass
        import asyncio  # loaded in this thread, so startup does not pay for it
        self.loop = asyncio.new_event_loop()
        try:
            self.loop.run_until_complete(self.main())
        except Exception as error:  # keep the studio alive whatever the media stack does
            self.state_changed.emit({'available': False, 'reason': f'Controle de mídia parou: {error}'})
        finally:
            self.loop.close()
            self.loop = None

    async def main(self):
        import asyncio
        _load_winrt()
        self.queue = asyncio.Queue()
        manager = await SessionManager.request_async()
        while self.running:
            session = choose_session(manager.get_sessions(), self.any_player, manager.get_current_session())
            try:
                state = await self.describe(session)
            except Exception as error:  # a player closing mid-query raises COM errors
                state = {'available': False, 'reason': str(error)}
            self.state_changed.emit(state)
            try:
                name, value = await asyncio.wait_for(self.queue.get(), self.interval)
            except asyncio.TimeoutError:
                continue
            if name == 'stop':
                break
            if session is None:
                continue
            try:
                if name == 'next':
                    await session.try_skip_next_async()
                elif name == 'previous':
                    await session.try_skip_previous_async()
                elif name == 'toggle':
                    await session.try_toggle_play_pause_async()
                elif name == 'volume':
                    process_volume(session.source_app_user_model_id, value)
            except Exception:  # the player may refuse a command (ads, closed) — next poll shows the truth
                pass
            await asyncio.sleep(.25)

    async def describe(self, session):
        if session is None:
            return {'available': False, 'reason': 'Nenhuma música tocando no Spotify.'}
        properties = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        app_id = session.source_app_user_model_id
        return {'available': True, 'app': player_name(app_id), 'spotify': is_spotify(app_id),
                'title': properties.title or '', 'artist': properties.artist or '', 'album': properties.album_title or '',
                'playing': info.playback_status == PlaybackStatus.PLAYING,
                'can_next': bool(info.controls.is_next_enabled), 'can_previous': bool(info.controls.is_previous_enabled),
                'volume': process_volume(app_id)}
