"""Guarded selection of firmware games on capable targets."""
from pathlib import Path
import struct
import zlib

from . import media_manager as media
from .publish import _plain
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
    from .game_install import inventory
    snapshot=inventory(Path(identity['root']),identity['target_id'])
    if snapshot['valid']:
        return {r['legacy'] for r in snapshot['rows'] if r['legacy']!=0xffffffff}
    selected = set(range(len(GAMES)))
    if path.exists():
        with path.open('rb') as reader:
            selected = decode(reader.read(13), identity)
    return selected & supported(identity)


def prepared(target, directory=None):
    from tools.studio.game_build import library
    from tools.studio.targets import ROOT
    candidates=[Path(directory)] if directory is not None else [ROOT/'resources/games'/target,ROOT/'out/game-packages'/target]
    for path in candidates:
        if (path/'library.json').is_file():return library(path,target)
    raise ValueError('Prepared game packages are missing. Install the matching Media Manager release or build the game library from source.')


def custom(identity):
    identity=media.refresh(identity)
    from .game_install import inventory
    return [r for r in inventory(identity['root'],identity['target_id'])['rows'] if r['legacy']==0xffffffff]


def choices(identity):
    identity=media.refresh(identity)
    from .game_install import inventory
    snapshot=inventory(identity['root'],identity['target_id'])
    return dict(selected={r['legacy'] for r in snapshot['rows'] if r['legacy']!=0xffffffff} if snapshot['valid'] else read(identity),
                custom=[r for r in snapshot['rows'] if r['legacy']==0xffffffff])


def save(identity, selected, library=None, recover=False):
    encode(selected)  # Preserve strict legacy selection validation during migration.
    if set(selected) - supported(identity):
        raise ValueError("This game is unavailable on this iPod.")
    identity = media.refresh(identity)
    from . import game_install,game_package
    if recover:game_install.recover_catalogues(identity)
    root,_=_path(identity)
    available=prepared(identity['target_id'],library) if selected else {}
    if any('linnet.'+game_package.LEGACY_IDS[i] not in available for i in selected):
        raise ValueError('The prepared library is missing a selected built-in game')
    packages=[available['linnet.'+game_package.LEGACY_IDS[i]] for i in sorted(set(selected))]
    # Changing built-in choices must preserve independently installed games.
    snapshot=game_install.inventory(root,identity['target_id'])
    packages.extend(root/'.LINNET/GAMES'/r['filename'] for r in snapshot['rows'] if r['legacy']==0xffffffff)
    game_install.install(identity,packages,expected=snapshot['tokens'])
    return set(selected)


def import_package(identity, path):
    identity=media.refresh(identity)
    from . import game_install,game_package
    candidate=Path(path)
    if candidate.stat().st_size>256+game_package.SLOT_BYTES:raise ValueError('Game package is too large')
    info=game_package.inspect(candidate.read_bytes(),identity['target_id'])
    snapshot=game_install.inventory(identity['root'],identity['target_id']);rows=snapshot['rows']
    paths=[Path(identity['root'])/'.LINNET/GAMES'/r['filename'] for r in rows if r['id']!=info['id']]
    return game_install.install(identity,[*paths,candidate],expected=snapshot['tokens'])


def remove_package(identity, game_id):
    identity=media.refresh(identity)
    from . import game_install
    snapshot=game_install.inventory(identity['root'],identity['target_id']);rows=snapshot['rows']
    paths=[Path(identity['root'])/'.LINNET/GAMES'/r['filename'] for r in rows if r['id']!=game_id]
    return game_install.install(identity,paths,expected=snapshot['tokens'])
