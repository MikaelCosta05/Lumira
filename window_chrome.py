"""Use native Windows title bars with the same palette as the workbench."""
import ctypes
import sys

from PyQt6.QtWidgets import QApplication


def apply_titlebar(window, colors, dark):
    if sys.platform != 'win32' or QApplication.platformName() != 'windows':
        return
    try:
        function = ctypes.windll.dwmapi.DwmSetWindowAttribute
        function.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        function.restype = ctypes.c_long
        handle = ctypes.c_void_p(int(window.winId()))
        immersive = ctypes.c_int(int(dark))
        function(handle, 20, ctypes.byref(immersive), ctypes.sizeof(immersive))
        for attribute, key in [(35, 'panel'), (36, 'text'), (34, 'border')]:
            rgb = colors[key].lstrip('#')
            value = ctypes.c_uint(int(rgb[0:2], 16) | int(rgb[2:4], 16) << 8 | int(rgb[4:6], 16) << 16)
            function(handle, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass  # Older Windows versions retain the standard native title bar.
