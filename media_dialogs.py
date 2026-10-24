import copy
import threading
import uuid
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from media import (RATE, Recorder, audio_array, export_document, import_audio, mix_audio,
                   parse_srt, split_clip, subtitles_srt, ExportCancelled)
from themes import PALETTES


class Waveform(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.samples = None
        self.setFixedHeight(86)

    def paintEvent(self, event):
        painter = QPainter(self)
        c = PALETTES[self.owner.theme]
        painter.fillRect(self.rect(), QColor(c['field']))
        painter.setPen(QPen(QColor(c['accent']), 1))
        center = self.height() / 2
        painter.drawLine(0, round(center), self.width(), round(center))
        if self.samples is not None and len(self.samples):
            samples = self.samples.mean(axis=1)
            for x in range(self.width()):
                a, b = x * len(samples) // self.width(), (x + 1) * len(samples) // self.width()
                peak = float(np.max(np.abs(samples[a:max(a+1,b)])))
                painter.drawLine(x, round(center-peak*center*.9), x, round(center+peak*center*.9))


class AudioEditor(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.clips = copy.deepcopy(owner.canvas.document.scene['audio'])
        self.assets = dict(owner.canvas.document.assets)
        self.recorder = Recorder()
        self.recording = False
        self.updating = False
        self.setWindowTitle('Áudio e dublagem')
        self.resize(760, 500)
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.refresh_fields)
        left.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton('Importar áudio…')
        add.clicked.connect(self.import_)
        remove = QPushButton('Excluir')
        remove.clicked.connect(self.remove)
        row.addWidget(add)
        row.addWidget(remove)
        left.addLayout(row)
        self.record_button = QPushButton('Gravar dublagem…')
        self.record_button.clicked.connect(self.record)
        left.addWidget(self.record_button)
        layout.addLayout(left, 1)
        form = QFormLayout()
        self.waveform = Waveform(owner)
        form.addRow(self.waveform)
        self.fields = {}
        for key, label, lo, hi in [('start','Início na timeline (s)',0,86400), ('trim_start','Cortar início (s)',0,86400),
            ('trim_end','Fim no arquivo (s)',.001,86400), ('gain_db','Volume (dB)',-60,24),
            ('noise','Redução de ruído (dB)',0,30), ('fade_in','Fade in (s)',0,60), ('fade_out','Fade out (s)',0,60)]:
            spin = QDoubleSpinBox()
            spin.setDecimals(3 if key in ('start','trim_start','trim_end') else 1)
            spin.setRange(lo, hi)
            spin.valueChanged.connect(self.commit_fields)
            self.fields[key] = spin
            form.addRow(label, spin)
        self.muted = QCheckBox('Silenciar faixa')
        self.muted.toggled.connect(self.commit_fields)
        form.addRow(self.muted)
        row = QHBoxLayout()
        split = QPushButton('Dividir no cursor')
        split.clicked.connect(self.split)
        preview = QPushButton('Ouvir / parar')
        preview.clicked.connect(self.preview)
        row.addWidget(split)
        row.addWidget(preview)
        form.addRow(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Aplicar áudio')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        layout.addLayout(form, 2)
        self.refresh_list()

    def refresh_list(self):
        row = self.list.currentRow()
        self.list.clear()
        self.list.addItems([clip['name'] for clip in self.clips])
        self.list.setCurrentRow(max(0,min(row,len(self.clips)-1)))
        self.refresh_fields()

    def refresh_fields(self):
        self.updating = True
        row = self.list.currentRow()
        clip = self.clips[row] if 0 <= row < len(self.clips) else {}
        for key, spin in self.fields.items():
            spin.setEnabled(bool(clip))
            spin.setValue(clip.get(key, .001 if key=='trim_end' else 0))
        self.muted.setChecked(clip.get('muted', False))
        self.waveform.samples = audio_array(self.assets[clip['asset']]) if clip else None
        self.waveform.update()
        self.updating = False

    def commit_fields(self):
        row = self.list.currentRow()
        if not self.updating and 0 <= row < len(self.clips):
            self.clips[row].update({key: spin.value() for key, spin in self.fields.items()})
            self.clips[row]['muted'] = self.muted.isChecked()

    def add_data(self, name, data, duration, start=None):
        asset = uuid.uuid4().hex
        self.assets[asset] = data
        self.clips.append({'name':name, 'asset':asset, 'start':self.owner.cursor_seconds() if start is None else start,
            'trim_start':0., 'trim_end':duration, 'gain_db':0., 'noise':0., 'fade_in':0., 'fade_out':0., 'muted':False})
        self.refresh_list()
        self.list.setCurrentRow(len(self.clips)-1)

    def import_(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar áudio', '', 'Áudio (*.wav *.mp3 *.ogg *.flac *.m4a *.aac);;Todos (*)')
        if path:
            try:
                data, duration = import_audio(path)
                self.add_data(Path(path).name, data, duration)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Áudio', str(error))

    def remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.clips):
            self.clips.pop(row)
            self.refresh_list()

    def split(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.clips):
            try:
                first, second = split_clip(self.clips[row], self.owner.cursor_seconds())
                self.clips[row:row+1] = [first, second]
                self.refresh_list()
            except ValueError as error:
                QMessageBox.information(self, 'Dividir áudio', str(error))

    def working_document(self):
        document = self.owner.canvas.document.clone()
        document.scene['audio'], document.assets = self.clips, self.assets
        self.owner.extend_to_media(document)
        return document

    def preview(self):
        try:
            import sounddevice as sd
            if sd.get_stream().active:
                sd.stop()
                return
        except Exception:
            pass
        try:
            import sounddevice as sd
            sd.play(mix_audio(self.working_document()), RATE)
        except Exception as error:
            QMessageBox.warning(self, 'Reprodução', str(error))

    def record(self):
        if self.recording:
            try:
                data, duration = self.recorder.stop()
                self.recording = False
                self.owner.timeline.stop()
                self.record_button.setText('Gravar dublagem…')
                self.add_data('Dublagem', data, duration, self.record_start)
            except ValueError as error:
                self.recording = False
                self.record_button.setText('Gravar dublagem…')
                QMessageBox.warning(self, 'Gravação', str(error))
            return
        try:
            import sounddevice as sd
            devices = [(i, device['name']) for i,device in enumerate(sd.query_devices()) if device['max_input_channels']]
            if not devices:
                raise ValueError('Nenhum microfone disponível.')
            label, accepted = QInputDialog.getItem(self, 'Microfone', 'Dispositivo de entrada:', [name for i,name in devices], editable=False)
            if not accepted:
                return
            device = devices[[name for i,name in devices].index(label)][0]
            self.record_start = self.owner.cursor_seconds()
            self.recorder.start(device)
            self.recording = True
            self.record_button.setText('● Parar gravação')
            if not self.owner.timeline.playing:
                self.owner.timeline.toggle_play()
        except Exception as error:
            QMessageBox.warning(self, 'Microfone', str(error))

    def validate(self):
        if self.recording:
            self.record()
        if any(c['trim_end']<=c['trim_start'] for c in self.clips):
            QMessageBox.warning(self, 'Recorte', 'O fim do trecho deve ficar depois do início.')
            return
        self.owner.timeline.stop()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self.accept()

    def reject(self):
        if self.recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recording = False
        self.owner.timeline.stop()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        super().reject()


class SubtitleEditor(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('Legendas e sincronização')
        self.resize(780, 430)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Início (s)', 'Fim (s)', 'Texto'])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for text, callback in [('+ Legenda',self.add), ('Excluir',self.remove), ('Início no cursor',lambda:self.sync(0)),
                               ('Fim no cursor',lambda:self.sync(1)), ('Importar SRT',self.import_), ('Exportar SRT',self.export_)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Deslocar todas (s)'))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-86400, 86400)
        self.offset.setDecimals(3)
        row.addWidget(self.offset)
        shift = QPushButton('Aplicar deslocamento')
        shift.clicked.connect(self.shift)
        row.addWidget(shift)
        row.addStretch()
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for cue in owner.canvas.document.scene['subtitles']:
            self.add_cue(cue)

    def add_cue(self, cue):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, key in enumerate(['start','end','text']):
            self.table.setItem(row,col,QTableWidgetItem(str(cue[key])))
        self.table.setCurrentCell(row,2)

    def add(self):
        start = self.owner.cursor_seconds()
        self.add_cue({'start':start, 'end':start+1, 'text':'Nova legenda'})

    def remove(self):
        if self.table.currentRow()>=0:
            self.table.removeRow(self.table.currentRow())

    def sync(self, column):
        row = self.table.currentRow()
        if row>=0:
            self.table.item(row,column).setText(f'{self.owner.cursor_seconds():.3f}')

    def cues(self):
        result = []
        for row in range(self.table.rowCount()):
            start, end = [float(self.table.item(row,col).text()) for col in (0,1)]
            if start<0 or end<=start:
                raise ValueError('Cada legenda deve ter início positivo e fim depois do início.')
            result.append({'start':start, 'end':end, 'text':self.table.item(row,2).text()})
        return result

    def shift(self):
        for row in range(self.table.rowCount()):
            for col in (0,1):
                self.table.item(row,col).setText(str(max(0,float(self.table.item(row,col).text())+self.offset.value())))

    def import_(self):
        path,_ = QFileDialog.getOpenFileName(self,'Importar legendas','','Legendas SRT (*.srt)')
        if path:
            try:
                cues = parse_srt(Path(path).read_text(encoding='utf-8-sig'))
                self.table.setRowCount(0)
                for cue in cues:
                    self.add_cue(cue)
            except (OSError,ValueError) as error:
                QMessageBox.warning(self,'SRT',str(error))

    def export_(self):
        path,_ = QFileDialog.getSaveFileName(self,'Exportar legendas','Legendas.srt','Legendas SRT (*.srt)')
        if path:
            try:
                Path(path).write_text(subtitles_srt(self.cues()),encoding='utf-8')
            except (OSError,ValueError) as error:
                QMessageBox.warning(self,'SRT',str(error))

    def validate(self):
        try:
            self.cues()
            self.accept()
        except ValueError as error:
            QMessageBox.warning(self,'Legendas',str(error))


class ExportWorker(QThread):
    progress = pyqtSignal(int)

    def __init__(self, document, destination, options, parent):
        super().__init__(parent)
        self.document, self.destination, self.options = document, destination, options
        self.cancel = threading.Event()
        self.error = None

    def run(self):
        try:
            export_document(self.document,self.destination,progress=self.progress.emit,cancel=self.cancel,**self.options)
        except Exception as error:
            self.error = error


class ExportDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.worker = None
        self.setWindowTitle('Exportar desenho / animação')
        self.resize(490, 290)
        form = QFormLayout(self)
        self.format = QComboBox()
        for text, value in [('PNG · quadro atual','png'),('JPEG · quadro atual','jpg'),
            ('WebP · imagem / animação','webp'),('MP4 · vídeo com áudio','mp4'),
            ('GIF · animação','gif'),('Spritesheet PNG + JSON','spritesheet')]:
            self.format.addItem(text,value)
        self.fps,self.quality,self.columns = QSpinBox(),QSpinBox(),QSpinBox()
        for spin,lo,hi,value in [(self.fps,1,120,24),(self.quality,1,100,90),(self.columns,0,600,0)]:
            spin.setRange(lo,hi)
            spin.setValue(value)
        self.columns.setSpecialValueText('Automático')
        self.subtitles = QCheckBox('Incluir legendas na imagem / vídeo')
        self.subtitles.setChecked(True)
        self.srt = QCheckBox('Exportar também arquivo SRT')
        self.progress = QProgressBar()
        self.progress.setValue(0)
        form.addRow('Formato',self.format)
        form.addRow('FPS do MP4',self.fps)
        form.addRow('Qualidade',self.quality)
        form.addRow('Colunas do spritesheet',self.columns)
        form.addRow(self.subtitles)
        form.addRow(self.srt)
        form.addRow(self.progress)
        self.state = QLabel('GIF e WebP preservam a duração individual dos quadros.')
        self.state.setWordWrap(True)
        form.addRow(self.state)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.start_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.start_button.setText('Exportar…')
        buttons.accepted.connect(self.start)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def start(self):
        format = self.format.currentData()
        suffix = 'png' if format=='spritesheet' else format
        path,_ = QFileDialog.getSaveFileName(self,'Destino da exportação',f'Desenho.{suffix}',f'Arquivo (*.{suffix})')
        if not path:
            return
        if not path.lower().endswith('.'+suffix):
            path += '.'+suffix
        self.owner.canvas.finish_stroke()
        self.owner.timeline.stop()
        self.start_button.setEnabled(False)
        self.state.setText('Exportando…')
        self.destination = path
        self.worker = ExportWorker(self.owner.canvas.document.clone(),path,{
            'format':format,'fps':self.fps.value(),'quality':self.quality.value(),
            'columns':self.columns.value(),'subtitles':self.subtitles.isChecked()},self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.finished_export)
        self.worker.start()

    def finished_export(self):
        self.start_button.setEnabled(True)
        if self.worker.error:
            self.state.setText('Cancelado.' if isinstance(self.worker.error,ExportCancelled) else str(self.worker.error))
            return
        if self.srt.isChecked():
            try:
                Path(self.destination).with_suffix('.srt').write_text(subtitles_srt(self.worker.document.scene['subtitles']),encoding='utf-8')
            except OSError as error:
                self.state.setText('Mídia exportada; falha no SRT: '+str(error))
                return
        self.owner.statusBar().showMessage('Exportado: '+self.destination,8000)
        self.accept()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.state.setText('Cancelando…')
            return
        super().reject()

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
