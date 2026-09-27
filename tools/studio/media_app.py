"""Compatibility launcher for the native Media Manager."""
import os


def launch():
    if os.name != "nt":
        raise RuntimeError("The desktop media manager currently supports Windows Disk Mode.")
    try:
        from .media_desktop import launch as launch_desktop
    except ModuleNotFoundError as error:
        missing = error.name or ''
        if missing in ('PySide6', 'shiboken6') or missing.startswith(('PySide6.', 'shiboken6.')):
            raise RuntimeError('Install the Media Manager with: python -m pip install -r tools/studio/requirements.txt') from error
        raise
    launch_desktop()
