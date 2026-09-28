"""Guarded selection of firmware games on capable targets."""
import os
from pathlib import Path
import struct
import uuid
import zlib

from . import media_manager as media
from .publish import _plain, _volume_guard
from tools.studio.targets import target_spec

GAMES = (("Comet Run", "Steer through a rising meteor storm."),
         ("Pulse Path", "Remember and repeat an expanding light pattern."),
         ("Solitaire", "Play draw-one Klondike and build four foundations."),
         ("Sudoku", "Solve 9 by 9 puzzles at four difficulty levels."))


def encode(selected):
    if not isinstance(selected, (set, list, tuple)) or any(type(i) is not int or i not in (0, 1, 2, 3) for i in selected):
        raise ValueError("Select known games only.")
    mask = sum(1 << i for i in set(selected))
    header = b'GAME' + bytes((2, mask, 0, 0))
    return header + struct.pack('<I', zlib.crc32(header))


def decode(data):
    if (len(data) != 12 or data[:4] != b'GAME' or data[4] not in (1, 2)
            or data[5] & ~(7 if data[4] == 1 else 15) or data[6:8] != b'\0\0'
            or struct.unpack_from('<I', data, 8)[0] != zlib.crc32(data[:8])):
        raise ValueError("Game selection is damaged. Save a new selection to replace it.")
    selected = {i for i in range(4) if data[5] & (1 << i)}
    if data[4] == 1 and selected == {0, 1, 2}:
        selected.add(3)
    return selected


def available(identity):
    return target_spec(identity['target_id'])['capabilities'].get('games', False)


def _path(identity):
    if not available(identity):
        raise ValueError("Games are unavailable on this iPod.")
    root = Path(identity['root'])
    path = root / '.LINNET' / 'GAMES.BIN'
    _plain(path, root)
    if not path.parent.is_dir():
        raise ValueError("Install Linnet on this iPod first.")
    return root, path


def read(identity):
    identity = media.refresh(identity)
    _, path = _path(identity)
    return decode(path.read_bytes()) if path.exists() else {0, 1, 2, 3}


def save(identity, selected):
    data = encode(selected)
    identity = media.refresh(identity)
    root, path = _path(identity)
    temporary = path.with_name('GAME-' + uuid.uuid4().hex[:8] + '.TMP')
    _plain(temporary, root)
    owned = False
    try:
        with temporary.open('xb') as stream:
            owned = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _volume_guard(identity)
        _plain(path, root)
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise IOError("Game selection could not be verified on the iPod.")
    finally:
        if owned and temporary.exists():
            _volume_guard(identity)
            _plain(temporary, root)
            temporary.unlink()
    return set(selected)
