"""Image/video export, audio clips and timed SRT subtitles."""
import io
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import wave
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage

RATE = 48000


def ffmpeg(args, data=None):
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', *args],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace')[-2000:])
    return result.stdout


def qt_image(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA', (image.width(), image.height()), image.constBits().asstring(image.sizeInBytes()),
                           'raw', 'RGBA', image.bytesPerLine()).copy()


def wav_bytes(array):
    data = io.BytesIO()
    with wave.open(data, 'wb') as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes((np.clip(array, -1, 1) * 32767).astype('<i2').tobytes())
    return data.getvalue()


def import_audio(path):
    raw = ffmpeg(['-i', str(path), '-vn', '-ar', str(RATE), '-ac', '2', '-f', 'f32le', 'pipe:1'])
    array = np.frombuffer(raw, dtype='<f4').reshape(-1, 2)
    if not len(array):
        raise ValueError('O arquivo não contém áudio.')
    return wav_bytes(array), len(array) / RATE


@lru_cache(maxsize=12)
def audio_array(data, noise_db=0):
    with wave.open(io.BytesIO(data), 'rb') as source:
        if source.getframerate() != RATE or source.getsampwidth() != 2 or source.getnchannels() != 2:
            raise ValueError('Áudio interno incompatível.')
        array = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').reshape(-1, 2).astype('float32') / 32768
    if noise_db:
        raw = ffmpeg(['-f', 'f32le', '-ar', str(RATE), '-ac', '2', '-i', 'pipe:0',
                      '-af', f'afftdn=nr={max(.01, min(30, noise_db))}', '-f', 'f32le', 'pipe:1'], array.tobytes())
        array = np.frombuffer(raw, dtype='<f4').reshape(-1, 2).copy()
    return array


def mix_audio(document):
    total = max(1, math.ceil(document.total_ms / 1000 * RATE))
    result = np.zeros((total, 2), dtype='float32')
    for clip in document.scene['audio']:
        if clip.get('muted') or clip['asset'] not in document.assets:
            continue
        source = audio_array(document.assets[clip['asset']], clip.get('noise', 0))
        begin = max(0, round(clip.get('trim_start', 0) * RATE))
        end = min(len(source), round(clip.get('trim_end', len(source) / RATE) * RATE))
        samples = source[begin:end].copy()
        if not len(samples):
            continue
        samples *= 10 ** (clip.get('gain_db', 0) / 20)
        for key, reverse in [('fade_in', False), ('fade_out', True)]:
            count = min(len(samples), round(clip.get(key, 0) * RATE))
            if count:
                fade = np.linspace(0, 1, count, dtype='float32')[:, None]
                if reverse:
                    samples[-count:] *= fade[::-1]
                else:
                    samples[:count] *= fade
        offset = max(0, round(clip.get('start', 0) * RATE))
        count = min(len(samples), total - offset)
        if count > 0:
            result[offset:offset + count] += samples[:count]
    return np.clip(result, -1, 1)


def split_clip(clip, seconds):
    length = clip['trim_end'] - clip.get('trim_start', 0)
    delta = seconds - clip.get('start', 0)
    if not 0 < delta < length:
        raise ValueError('Posicione o cursor dentro do trecho de áudio para dividir.')
    first, second = dict(clip), dict(clip)
    first['trim_end'] = clip.get('trim_start', 0) + delta
    first['fade_out'] = 0
    second.update(start=seconds, trim_start=first['trim_end'], fade_in=0)
    return first, second


def srt_time(seconds):
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'


def subtitles_srt(cues):
    return '\n\n'.join(f'{n}\n{srt_time(c["start"])} --> {srt_time(c["end"])}\n{c["text"]}'
                        for n, c in enumerate(sorted(cues, key=lambda c: c['start']), 1)) + '\n'


def parse_srt(text):
    def seconds(value):
        h, m, s, ms = map(int, re.split('[:,.]', value))
        return h * 3600 + m * 60 + s + ms / 1000
    pattern = r'(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
    cues = [{'start': seconds(a), 'end': seconds(b), 'text': text.strip()} for a, b, text in
            re.findall(pattern, text.replace('\r', ''), re.S)]
    if not cues or any(c['end'] <= c['start'] for c in cues):
        raise ValueError('Arquivo SRT inválido.')
    return cues


class Recorder:
    def __init__(self):
        self.stream = None
        self.chunks = []

    def start(self, device=None):
        import sounddevice as sd
        self.chunks = []
        def callback(data, frames, clock, status):
            self.chunks.append(data.copy())
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype='float32', device=device, callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if not self.chunks:
            raise ValueError('Nenhum áudio foi capturado.')
        mono = np.concatenate(self.chunks)
        array = np.repeat(mono, 2, axis=1)
        self.chunks = []
        return wav_bytes(array), len(array) / RATE


class ExportCancelled(Exception):
    pass


def export_document(document, destination, format, fps=24, columns=0, quality=90,
                    subtitles=True, progress=None, cancel=None):
    path = Path(destination)
    format = format.lower()
    def report(done, total):
        if cancel is not None and cancel.is_set():
            raise ExportCancelled()
        if progress:
            progress(round(done * 100 / max(1, total)))
    def render(frame):
        return qt_image(document.composite(frame_index=frame, subtitles=subtitles))
    with tempfile.TemporaryDirectory(prefix='.studio-export-', dir=path.parent) as folder:
        staged = Path(folder) / ('output.' + ('png' if format == 'spritesheet' else format))
        if format in ('png', 'jpg', 'jpeg') or (format == 'webp' and not document.animation_enabled):
            image = render(document.current_frame)
            if format in ('jpg', 'jpeg'):
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.getchannel('A'))
                image = background
            image.save(staged, format='JPEG' if format in ('jpg', 'jpeg') else format.upper(), quality=quality,
                       dpi=(document.dpi, document.dpi))
        elif format in ('gif', 'webp'):
            images = []
            for index in range(len(document.frames)):
                report(index, len(document.frames))
                images.append(render(index))
            durations = [f.duration for f in document.frames]
            if format == 'gif':
                converted = []
                for image in images:
                    alpha = image.getchannel('A')
                    indexed = image.convert('RGB').quantize(colors=255)
                    indexed.paste(255, mask=alpha.point(lambda p: 255 if p < 128 else 0))
                    indexed.info['transparency'] = 255
                    converted.append(indexed)
                images = converted
            images[0].save(staged, format=format.upper(), save_all=True, append_images=images[1:],
                           duration=durations, loop=0, disposal=2, quality=quality)
        elif format == 'spritesheet':
            count = len(document.frames)
            columns = max(1, min(count, columns or math.ceil(math.sqrt(count))))
            rows = math.ceil(count / columns)
            if document.width * columns * document.height * rows > 100_000_000:
                raise ValueError('Spritesheet grande demais. Reduza a tela ou o número de quadros.')
            image = Image.new('RGBA', (document.width * columns, document.height * rows))
            metadata = {'image': path.name, 'frames': [], 'tags': document.scene['tags']}
            for index, frame in enumerate(document.frames):
                report(index, count)
                x, y = index % columns * document.width, index // columns * document.height
                image.paste(render(index), (x, y))
                metadata['frames'].append({'x': x, 'y': y, 'w': document.width, 'h': document.height, 'duration': frame.duration})
            image.save(staged, format='PNG')
            Path(folder, 'output.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        elif format == 'mp4':
            frames = max(1, math.ceil(document.total_ms / 1000 * fps))
            audio_path = Path(folder) / 'mix.wav'
            if document.scene['audio']:
                audio_path.write_bytes(wav_bytes(mix_audio(document)))
            command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{document.width}x{document.height}',
                '-r', str(fps), '-i', 'pipe:0']
            if audio_path.exists():
                command += ['-i', str(audio_path), '-c:a', 'aac', '-b:a', '192k']
            command += ['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-crf', str(round(35 - quality * .2)), '-movflags', '+faststart', str(staged)]
            with open(Path(folder) / 'ffmpeg.log', 'wb+') as log:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log, stdout=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                try:
                    for n in range(frames):
                        report(n, frames)
                        index, fraction = document.frame_at(n / fps)
                        image = render(index + fraction)
                        background = Image.new('RGB', image.size, 'white')
                        background.paste(image, mask=image.getchannel('A'))
                        process.stdin.write(background.tobytes())
                    process.stdin.close()
                    if process.wait(timeout=120):
                        log.seek(0)
                        raise ValueError(log.read().decode('utf-8', errors='replace')[-2000:])
                except BaseException:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
                    raise
        else:
            raise ValueError('Formato de exportação desconhecido.')
        report(1, 1)
        os.replace(staged, path)
        if format == 'spritesheet':
            os.replace(Path(folder) / 'output.json', path.with_suffix('.json'))
