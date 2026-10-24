"""Interface language: Brazilian Portuguese (the source language) or English.

Interface texts are written in Portuguese in the code. With English active they
are translated where they reach Qt: text setters (labels, buttons, actions,
tooltips, titles, combo items, tabs, status messages and standard dialogs) are
wrapped, and every window is translated when it is shown, which also covers texts
given to constructors. The Portuguese original is kept on each object, so the
language can be switched while the program runs.
"""
import json
import re
from pathlib import Path

from PyQt6.QtCore import QEvent, QLibraryInfo, QLocale, QObject, QTranslator
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QColorDialog, QComboBox, QDockWidget, QFileDialog,
                             QGroupBox, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                             QStatusBar, QTabWidget, QToolButton, QTreeWidget, QWidget)

LANGUAGES = [('pt_BR', 'Português (Brasil)'), ('en', 'English')]
TABLE_PATH = Path(__file__).resolve().parent / 'translations' / 'en.json'
ITEM_ROLE = 256 + 77

_language = 'pt_BR'
_table = {}
_patterns = []
_installed = False
_qt_translator = None
_filter = None


# ---------------------------------------------------------------- lookup

def _load():
    global _table, _patterns
    if _table:
        return
    try:
        _table = json.loads(TABLE_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        _table = {}
    patterns = []
    for key, value in _table.items():
        if '{}' not in key or len(re.sub(r'[^A-Za-zÀ-ÿ]', '', key.replace('{}', ''))) < 3:
            continue
        pieces = key.split('{}')
        regex = re.compile('^' + '(.*?)'.join(re.escape(p) for p in pieces) + '$', re.S)
        if regex and value.count('{}') == key.count('{}'):
            patterns.append((len(key.replace('{}', '')), regex, value))
    _patterns = [(regex, value) for _, regex, value in sorted(patterns, key=lambda item: -item[0])]


def language():
    return _language


def tr(text):
    """Translated text for the active language (Portuguese passes through unchanged)."""
    if _language == 'pt_BR' or not isinstance(text, str) or not text:
        return text
    return _translate(text, 0)


def _translate(text, depth):
    if text in _table:
        return _table[text]
    stripped = text.strip()
    if stripped and stripped != text and stripped in _table:
        start = text.index(stripped)
        return text[:start] + _table[stripped] + text[start + len(stripped):]
    if depth < 3:
        for regex, template in _patterns:
            match = regex.match(text)
            if match:
                parts = template.split('{}')
                values = [_translate(group, depth + 1) for group in match.groups()]
                return ''.join(part + (values[i] if i < len(values) else '') for i, part in enumerate(parts))
        if '\n' in text:
            return '\n'.join(_translate(line, depth + 1) for line in text.split('\n'))
        for suffix, english in ((' esq.', ' L.'), (' dir.', ' R.')):
            if text.endswith(suffix) and len(text) > len(suffix):
                return _translate(text[:-len(suffix)], depth + 1) + english
        numbered = re.match(r'^(.+?) (\d+)$', text)
        if numbered and numbered.group(1) in _table:
            return f'{_table[numbered.group(1)]} {numbered.group(2)}'
        shortcut = re.match(r'^(.+) \(([^()]*)\)$', text, re.S)
        if shortcut and shortcut.group(1).strip() in _table:
            return f'{_translate(shortcut.group(1), depth + 1)} ({_translate(shortcut.group(2), depth + 1)})'
        for separator in (' · ', ' — ', ': '):
            if separator in text:
                pieces = text.split(separator)
                if any(piece.strip() in _table for piece in pieces):
                    return separator.join(_translate(piece, depth + 1) for piece in pieces)
    return text


# ----------------------------------------------------------- remembering

def _remember(obj, slot, text):
    obj.setProperty('i18n_' + slot, text)


def _original(obj, slot, current):
    value = obj.property('i18n_' + slot)
    return value if isinstance(value, str) else current


def _skip(widget):
    return bool(widget.property('i18n_skip'))


# --------------------------------------------------------------- patches

def _wrap_setter(cls, method, slot):
    original = getattr(cls, method)

    def wrapper(self, text, *args):
        if isinstance(text, str) and not _skip(self):
            _remember(self, slot, text)
            text = tr(text)
        return original(self, text, *args)
    setattr(cls, method, wrapper)


def _wrap_static(cls, method, positions):
    original = getattr(cls, method)

    def wrapper(*args, **kwargs):
        args = list(args)
        for position in positions:
            if position < len(args) and isinstance(args[position], str):
                args[position] = tr(args[position])
        for key in ('caption', 'title', 'label', 'text', 'filter'):
            if isinstance(kwargs.get(key), str):
                kwargs[key] = tr(kwargs[key])
        return original(*args, **kwargs)
    setattr(cls, method, staticmethod(wrapper))


def _wrap_combo():
    add_item, insert_item = QComboBox.addItem, QComboBox.insertItem

    def text_position(args):
        return next((i for i, value in enumerate(args) if isinstance(value, str)), None)

    def add(self, *args):
        args = list(args)
        position = text_position(args)
        original = args[position] if position is not None else None
        if original is not None and not _skip(self):
            args[position] = tr(original)
        add_item(self, *args)
        if original is not None:
            self.setItemData(self.count() - 1, original, ITEM_ROLE)

    def insert(self, index, *args):
        args = list(args)
        position = text_position(args)
        original = args[position] if position is not None else None
        if original is not None and not _skip(self):
            args[position] = tr(original)
        insert_item(self, index, *args)
        if original is not None:
            self.setItemData(min(index, self.count() - 1), original, ITEM_ROLE)

    def add_items(self, texts):
        for text in texts:
            add(self, text)
    QComboBox.addItem, QComboBox.insertItem, QComboBox.addItems = add, insert, add_items


def _wrap_tabs():
    add_tab, insert_tab, set_tab_text = QTabWidget.addTab, QTabWidget.insertTab, QTabWidget.setTabText

    def text_args(args):
        args = list(args)
        position = next(i for i, value in enumerate(args) if isinstance(value, str))
        return args, position, args[position]

    def add(self, *args):
        args, position, original = text_args(args)
        args[position] = tr(original)
        index = add_tab(self, *args)
        self.tabBar().setTabData(index, original)
        return index

    def insert(self, index, *args):
        args, position, original = text_args(args)
        args[position] = tr(original)
        result = insert_tab(self, index, *args)
        self.tabBar().setTabData(result, original)
        return result

    def set_text(self, index, text):
        self.tabBar().setTabData(index, text)
        set_tab_text(self, index, tr(text))
    QTabWidget.addTab, QTabWidget.insertTab, QTabWidget.setTabText = add, insert, set_text


def _wrap_status():
    show = QStatusBar.showMessage

    def wrapper(self, text, *args):
        return show(self, tr(text), *args)
    QStatusBar.showMessage = wrapper


def install():
    """Wrap Qt text setters once (safe to call more than once)."""
    global _installed
    if _installed:
        return
    _installed = True
    for cls, method, slot in [(QLabel, 'setText', 'text'), (QAbstractButton, 'setText', 'text'),
                              (QAction, 'setText', 'text'), (QAction, 'setToolTip', 'tooltip'),
                              (QWidget, 'setToolTip', 'tooltip'), (QWidget, 'setWindowTitle', 'title'),
                              (QGroupBox, 'setTitle', 'title'), (QMenu, 'setTitle', 'title'),
                              (QLineEdit, 'setPlaceholderText', 'placeholder'),
                              (QPlainTextEdit, 'setPlaceholderText', 'placeholder')]:
        _wrap_setter(cls, method, slot)
    _wrap_combo()
    _wrap_tabs()
    _wrap_status()
    for name, positions in [('information', (1, 2)), ('warning', (1, 2)), ('question', (1, 2)), ('critical', (1, 2))]:
        _wrap_static(QMessageBox, name, positions)
    for name in ('getText', 'getInt', 'getDouble', 'getItem', 'getMultiLineText'):
        _wrap_static(QInputDialog, name, (1, 2))
    for name in ('getOpenFileName', 'getOpenFileNames', 'getSaveFileName', 'getExistingDirectory'):
        _wrap_static(QFileDialog, name, (1, 3))
    _wrap_static(QColorDialog, 'getColor', (2,))


# ------------------------------------------------------------------- walk

def translate_widget(widget):
    if _skip(widget) or type(widget).__name__ in ('QTipLabel',):
        return
    if (widget.isWindow() and not isinstance(widget, QMenu)) or isinstance(widget, QDockWidget):
        title = _original(widget, 'title', widget.windowTitle())
        if title:
            widget.setWindowTitle(title)
    tooltip = _original(widget, 'tooltip', widget.toolTip())
    if tooltip:
        widget.setToolTip(tooltip)
    if isinstance(widget, QLabel):
        text = _original(widget, 'text', widget.text())
        if text:
            widget.setText(text)
    elif isinstance(widget, QAbstractButton) and not (isinstance(widget, QToolButton) and widget.defaultAction()):
        text = _original(widget, 'text', widget.text())
        if text:
            widget.setText(text)
    elif isinstance(widget, QGroupBox):
        widget.setTitle(_original(widget, 'title', widget.title()))
    elif isinstance(widget, (QLineEdit, QPlainTextEdit)):
        placeholder = _original(widget, 'placeholder', widget.placeholderText())
        if placeholder:
            widget.setPlaceholderText(placeholder)
    elif isinstance(widget, QComboBox) and not widget.isEditable():
        for index in range(widget.count()):
            original = widget.itemData(index, ITEM_ROLE)
            if not isinstance(original, str):
                original = widget.itemText(index)
                widget.setItemData(index, original, ITEM_ROLE)
            widget.setItemText(index, tr(original))
    elif isinstance(widget, QTabWidget):
        bar = widget.tabBar()
        for index in range(widget.count()):
            original = bar.tabData(index)
            widget.setTabText(index, original if isinstance(original, str) else widget.tabText(index))
    elif isinstance(widget, QTreeWidget):
        header = widget.headerItem()
        stored = widget.property('i18n_headers')
        originals = stored if isinstance(stored, list) else [header.text(i) for i in range(header.columnCount())]
        widget.setProperty('i18n_headers', originals)
        for index, text in enumerate(originals):
            header.setText(index, tr(text))
    elif isinstance(widget, QMenu):
        title = _original(widget, 'title', widget.title())
        if title:
            widget.setTitle(title)


def translate_action(action):
    if action.isSeparator() or action.menu() is not None or action.property('i18n_skip'):
        return  # a submenu's action follows its menu title
    text = _original(action, 'text', action.text())
    if text:
        action.setText(text)
    tooltip = _original(action, 'tooltip', None)
    if tooltip:
        action.setToolTip(tooltip)


def translate_tree(root):
    for widget in [root] + root.findChildren(QWidget):
        translate_widget(widget)
    for action in root.findChildren(QAction):
        translate_action(action)
    if isinstance(root, QMenu):
        for action in root.actions():
            translate_action(action)
    root.setProperty('i18n_language', _language)


class _ShowFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            if isinstance(obj, QMenu) or obj.property('i18n_language') != _language:
                if _language != 'pt_BR' or obj.property('i18n_language') not in (None, 'pt_BR'):
                    translate_tree(obj)
        return False


def set_language(code, app=None):
    """Activate a language and retranslate every open window."""
    global _language, _qt_translator, _filter
    app = app or QApplication.instance()
    install()
    if code not in dict(LANGUAGES):
        code = 'pt_BR'
    changed = code != _language
    _language = code
    if code != 'pt_BR':
        _load()
    if app is not None:
        if _filter is None:
            _filter = _ShowFilter(app)
            app.installEventFilter(_filter)
        if _qt_translator is not None and changed:
            app.removeTranslator(_qt_translator)
            _qt_translator = None
        QLocale.setDefault(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil) if code == 'pt_BR'
                           else QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        if code == 'pt_BR' and _qt_translator is None:
            translator = QTranslator(app)
            if translator.load('qtbase_pt_BR', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
                app.installTranslator(translator)
                _qt_translator = translator
        if changed:
            for window in app.topLevelWidgets():
                translate_tree(window)
    return code
