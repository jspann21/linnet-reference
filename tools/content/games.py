"""Guarded selection of firmware games for the A1136."""
import os
from pathlib import Path
import struct
import uuid
import zlib

from . import media_manager as media
from .publish import _plain, _volume_guard

GAMES = (("Comet Run", "Steer through a rising meteor storm."),
         ("Pulse Path", "Remember and repeat an expanding light pattern."))


def encode(selected):
    if not isinstance(selected, (set, list, tuple)) or any(type(i) is not int or i not in (0, 1) for i in selected):
        raise ValueError("Select known games only.")
    mask = sum(1 << i for i in set(selected))
    header = b'GAME' + bytes((1, mask, 0, 0))
    return header + struct.pack('<I', zlib.crc32(header))


def decode(data):
    if (len(data) != 12 or data[:5] != b'GAME\x01' or data[5] & ~3 or data[6:8] != b'\0\0'
            or struct.unpack_from('<I', data, 8)[0] != zlib.crc32(data[:8])):
        raise ValueError("Game selection is damaged. Save a new selection to replace it.")
    return {i for i in range(2) if data[5] & (1 << i)}


def _path(identity):
    if identity['target_id'] != 'video5g-m25':
        raise ValueError("Games are currently available on the iPod Video A1136.")
    root = Path(identity['root'])
    path = root / '.LINNET' / 'GAMES.BIN'
    _plain(path, root)
    if not path.parent.is_dir():
        raise ValueError("Install Linnet on this iPod first.")
    return root, path


def read(identity):
    identity = media.refresh(identity)
    _, path = _path(identity)
    return decode(path.read_bytes()) if path.exists() else {0, 1}


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
