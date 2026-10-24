"""Separate bundled resources from persistent user files."""
import os
import sys
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent


def data_root():
    override = os.environ.get('LUMIRA_DATA_DIR')
    if override:
        root = Path(override).expanduser().resolve()
    elif getattr(sys, 'frozen', False):
        local_appdata = os.environ.get('LOCALAPPDATA')
        parent = Path(local_appdata) if local_appdata else Path.home() / 'AppData' / 'Local'
        root = parent / 'Lumira'
        # The program used to be called Studio Desenho: keep the data of earlier versions.
        previous = parent / 'Studio Desenho'
        if previous.is_dir() and not root.exists():
            try:
                previous.rename(root)
            except OSError:
                pass
    else:
        return RESOURCE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA_ROOT = data_root()
