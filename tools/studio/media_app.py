"""Compatibility launcher for the native Media Manager."""
import os


def launch():
    if os.name != "nt":
        raise RuntimeError("The desktop media manager currently supports Windows Disk Mode.")
    try:
        from .media_desktop import launch as launch_desktop
    except ImportError as error:
        raise RuntimeError('The Media Manager requires PySide6. Install it with: python -m pip install -r tools/studio/requirements.txt') from error
    launch_desktop()
