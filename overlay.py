import sys
import ctypes
import keyboard
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout,
    QPushButton, QSlider, QFileDialog, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt, QPoint, QObject, pyqtSignal
from PyQt5.QtGui import QPixmap

# Constantes da API do Windows
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

WDA_EXCLUDEFROMCAPTURE = 0x00000011
WDA_NONE = 0x00000000

user32 = ctypes.windll.user32
GetWindowLong = getattr(user32, 'GetWindowLongPtrW', user32.GetWindowLongW)
SetWindowLong = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)


class HotkeySignals(QObject):
    """Comunicação segura entre as threads de atalhos e a interface gráfica."""
    toggle_visible = pyqtSignal()
    toggle_ghost = pyqtSignal()
    opacity_up = pyqtSignal()
    opacity_down = pyqtSignal()


class OverlayWindow(QWidget):
    """Janela flutuante que exibe a imagem sobreposta."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.label_image = QLabel(self)
        self.label_image.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label_image)

        self.original_pixmap = None
        self.scale_factor = 1.0
        self.drag_position = QPoint()
        self.is_dragging = False
        self.click_through = False

    def showEvent(self, event):
        super().showEvent(event)
        self.set_capture_protection(True)
        self.set_click_through(self.click_through)

    def set_capture_protection(self, enable: bool):
        """Invisível para gravadores (OBS, Discord, etc.)."""
        hwnd = int(self.winId())
        affinity = WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE
        return user32.SetWindowDisplayAffinity(hwnd, affinity) != 0

    def set_click_through(self, enable: bool):
        """Ativa/Desativa o repasse de cliques para as janelas de trás."""
        self.click_through = enable
        hwnd = int(self.winId())
        
        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        if enable:
            SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        else:
            SetWindowLong(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)

    def set_image(self, file_path: str):
        self.original_pixmap = QPixmap(file_path)
        self.update_image_display()

    def set_scale(self, scale: float):
        self.scale_factor = scale
        self.update_image_display()

    def update_image_display(self):
        if not self.original_pixmap or self.original_pixmap.isNull():
            return
        w = int(self.original_pixmap.width() * self.scale_factor)
        h = int(self.original_pixmap.height() * self.scale_factor)
        scaled = self.original_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label_image.setPixmap(scaled)
        self.resize(w, h)

    def mousePressEvent(self, event):
        if not self.click_through and event.button() == Qt.LeftButton:
            self.is_dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.click_through and self.is_dragging and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False


class ControlPanel(QWidget):
    """Painel de controle com atalhos globais de teclado."""
    def __init__(self, overlay: OverlayWindow):
        super().__init__()
        self.overlay = overlay

        self.setWindowTitle("Controle do Overlay")
        self.setFixedSize(400, 520)

        self._setup_ui()
        self._setup_hotkeys()

    def showEvent(self, event):
        super().showEvent(event)
        hwnd = int(self.winId())
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 1. Carregar Imagem
        btn_load = QPushButton("📁 Escolher Imagem (PNG / JPG)")
        btn_load.clicked.connect(self._select_image)
        layout.addWidget(btn_load)

        # 2. Atalhos Globais
        grp_keys = QGroupBox("⌨️ Teclas de Atalho Globais (Funcionam no Jogo)")
        vbox_keys = QVBoxLayout()
        vbox_keys.addWidget(QLabel("• <b>F6:</b> Mostrar / Ocultar Imagem"))
        vbox_keys.addWidget(QLabel("• <b>F7:</b> Ligar / Desligar Modo Fantasma"))
        vbox_keys.addWidget(QLabel("• <b>F8:</b> Diminuir Opacidade (-10%)"))
        vbox_keys.addWidget(QLabel("• <b>F9:</b> Aumentar Opacidade (+10%)"))
        grp_keys.setLayout(vbox_keys)
        layout.addWidget(grp_keys)

        # 3. Opacidade
        grp_opacity = QGroupBox("Opacidade")
        vbox_op = QVBoxLayout()
        self.lbl_opacity = QLabel("Opacidade: 80%")
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setValue(80)
        self.slider_opacity.valueChanged.connect(self._change_opacity)
        vbox_op.addWidget(self.lbl_opacity)
        vbox_op.addWidget(self.slider_opacity)
        grp_opacity.setLayout(vbox_op)
        layout.addWidget(grp_opacity)

        # 4. Tamanho / Escala
        grp_size = QGroupBox("Tamanho / Escala")
        vbox_sz = QVBoxLayout()
        self.lbl_size = QLabel("Escala: 100%")
        self.slider_size = QSlider(Qt.Horizontal)
        self.slider_size.setRange(10, 300)
        self.slider_size.setValue(100)
        self.slider_size.valueChanged.connect(self._change_size)
        vbox_sz.addWidget(self.lbl_size)
        vbox_sz.addWidget(self.slider_size)
        grp_size.setLayout(vbox_sz)
        layout.addWidget(grp_size)

        # 5. Checkboxes
        self.chk_click_through = QCheckBox("👻 Modo Fantasma [F7] (Cliques atravessam)")
        self.chk_click_through.setStyleSheet("font-weight: bold; color: #0078d7;")
        self.chk_click_through.toggled.connect(self._toggle_click_through)
        layout.addWidget(self.chk_click_through)

        self.chk_protection = QCheckBox("🛡️ Invisível para Gravadores (OBS / Discord / Print)")
        self.chk_protection.setChecked(True)
        self.chk_protection.toggled.connect(self._toggle_protection)
        layout.addWidget(self.chk_protection)

        layout.addStretch()

    def _setup_hotkeys(self):
        """Registra os atalhos globais no sistema operacional."""
        self.signals = HotkeySignals()
        self.signals.toggle_visible.connect(self.action_toggle_visible)
        self.signals.toggle_ghost.connect(self.action_toggle_ghost)
        self.signals.opacity_up.connect(self.action_opacity_up)
        self.signals.opacity_down.connect(self.action_opacity_down)

        try:
            keyboard.add_hotkey('f6', self.signals.toggle_visible.emit)
            keyboard.add_hotkey('f7', self.signals.toggle_ghost.emit)
            keyboard.add_hotkey('f8', self.signals.opacity_down.emit)
            keyboard.add_hotkey('f9', self.signals.opacity_up.emit)
        except Exception as e:
            print(f"Erro ao registrar atalhos: {e}")

    # Ações disparadas pelos atalhos
    def action_toggle_visible(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            if self.overlay.original_pixmap:
                self.overlay.show()

    def action_toggle_ghost(self):
        novo_estado = not self.chk_click_through.isChecked()
        self.chk_click_through.setChecked(novo_estado)

    def action_opacity_up(self):
        val = min(100, self.slider_opacity.value() + 10)
        self.slider_opacity.setValue(val)

    def action_opacity_down(self):
        val = max(10, self.slider_opacity.value() - 10)
        self.slider_opacity.setValue(val)

    def _select_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecione uma imagem", "", "Imagens (*.png *.jpg *.jpeg *.bmp *.webp *.gif)"
        )
        if path:
            self.overlay.set_image(path)
            self._change_opacity(self.slider_opacity.value())
            self.overlay.show()

    def _change_opacity(self, value):
        self.lbl_opacity.setText(f"Opacidade: {value}%")
        self.overlay.setWindowOpacity(value / 100.0)

    def _change_size(self, value):
        self.lbl_size.setText(f"Escala: {value}%")
        self.overlay.set_scale(value / 100.0)

    def _toggle_protection(self, enabled):
        self.overlay.set_capture_protection(enabled)

    def _toggle_click_through(self, enabled):
        self.overlay.set_click_through(enabled)

    def closeEvent(self, event):
        keyboard.unhook_all()  # Libera os atalhos ao fechar
        self.overlay.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    overlay = OverlayWindow()
    panel = ControlPanel(overlay)
    panel.show()

    sys.exit(app.exec_())