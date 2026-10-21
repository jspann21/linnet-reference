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
         ("Sudoku", "Solve 9 by 9 puzzles at four difficulty levels."),
         ("Brick", "Break six handcrafted walls with precise paddle play."),
         ("Music Quiz", "Name songs from your own music library."),
         ("Vortex", "Orbit the core and clear luminous enemy waves."),
         ("Minesweeper", "Clear safe tiles across three difficulty levels."),
         ("Falling Blocks", "Build clean lines with seven classic pieces."),
         ("Reversi", "Outflank a thoughtful computer opponent."),
         ("Snake", "Turn, boost, and grow through a polished grid."),
         ("Word Search", "Find hidden words across three curated boards."),
         ("Scrub", "Pin one echo, then scrub time to align all three."),
         ("Dial Heist", "Find the tumblers before the patrol clock runs out."),
         ("Mixtape", "Place loops on a rotating eight-beat map."),
         ("Signal", "Tune the dial and hold each broadcast to decode it."),
         ("Clockwork City", "Rotate street rings to open the courier route."),
         ("Pocket Pinball", "Tilt the table and kick the ball through targets."))


def encode(selected):
    if not isinstance(selected, (set, list, tuple)) or any(type(i) is not int or not 0 <= i < len(GAMES) for i in selected):
        raise ValueError("Select known games only.")
    mask = sum(1 << i for i in set(selected))
    header = b'GAME' + bytes((4, mask & 255, (mask >> 8) & 255, (mask >> 16) & 255))
    return header + struct.pack('<I', zlib.crc32(header))


def decode(data, identity=None):
    if (len(data) != 12 or data[:4] != b'GAME' or data[4] != 4
            or data[7] & ~((1 << max(0, len(GAMES) - 16)) - 1)
            or struct.unpack_from('<I', data, 8)[0] != zlib.crc32(data[:8])):
        raise ValueError("Game selection is damaged. Save a new selection to replace it.")
    mask = data[5] | (data[6] << 8) | (data[7] << 16)
    selected = {i for i in range(len(GAMES)) if mask & (1 << i)}
    return selected


def available(identity):
    return target_spec(identity['target_id'])['capabilities'].get('games', False)


def supported(identity):
    spec = target_spec(identity['target_id'])
    count = len(GAMES)
    return set(range(count)) if spec['capabilities'].get('games', False) else set()


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
    selected = set(range(len(GAMES)))
    if path.exists():
        with path.open('rb') as reader:
            selected = decode(reader.read(13), identity)
    return selected & supported(identity)


def save(identity, selected):
    if set(selected) - supported(identity):
        raise ValueError("This game is unavailable on this iPod.")
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
