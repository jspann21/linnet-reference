"""Device menu preferences shared by the screen editor and firmware."""
import os
from pathlib import Path
import struct
import tomllib
import uuid
import zlib
from tools.content import media_manager as media
from tools.studio.targets import target_spec
from tools.content.compiler import resolve_features
from tools.content.layouts import feature_enabled
from tools.content.publish import _plain, _volume_guard
from tools.studio.menu_definition import SCREENS, DEFAULTS, REQUIRED, ITEMS

HINTS = {'Artists': 'Performers credited on individual tracks.', 'Album Artists': 'Main artist credited for each album; useful for compilations.', 'Composers': 'Writers of the music; useful for classical collections.'}


def item_availability(name, identity=None):
    root = Path(__file__).resolve().parents[2]
    target = (identity or {}).get('target_id')
    config = root / 'targets' / target / 'system.toml' if target else root / 'config' / 'system.toml'
    if not config.is_file():
        config = root / 'config' / 'system.toml'
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    target = target or settings['system']['target']
    configured = resolve_features(settings)
    spec = target_spec(target)
    features = resolve_features(settings, spec)
    apps = set(settings.get('ui', {}).get('apps', []))
    game_app = spec['capabilities'].get('games', False) and 'linnet.system.games' in apps
    available, unavailable = [], []
    for i, item in enumerate(ITEMS[name]):
        feature = item.feature
        if feature == 'legacy_extras':
            continue
        if feature == 'demo_or_games' and game_app:
            available.append(i)
            continue
        if item.target and item.target != '@sync' and item.target not in apps:
            continue
        if feature == 'demo_or_games':
            feature = 'demo'
        if feature and not feature_enabled(configured, feature):
            continue
        if feature and not feature_enabled(features, feature):
            unavailable.append(i)
        else:
            available.append(i)
    return available, unavailable


def available_items(name, identity=None):
    return item_availability(name, identity)[0]


def locked_items(name, identity=None):
    """Items firmware restores automatically in addition to navigation anchors."""
    locked = set(REQUIRED.get(name, ()))
    if name == 'Settings' and 10 in available_items(name, identity):
        locked.add(10)
    return locked


def defaults(identity=None):
    result = {}
    for name, rows in DEFAULTS.items():
        rows = list(rows)
        if name == 'Home' and identity and target_spec(identity['target_id'])['capabilities'].get('games', False):
            rows.append(7)
        available = available_items(name, identity) if identity is not None else rows
        result[name] = [i for i in rows if i in available]
    return result


def encode(state):
    data = bytearray(b'MENU' + struct.pack('<I', 1))
    for name, labels in SCREENS.items():
        rows = state[name]
        if (not isinstance(rows, (list, tuple)) or not rows or any(type(i) is not int or i not in range(len(labels)) for i in rows) or len(set(rows)) != len(rows)
                or not REQUIRED.get(name, set()).issubset(rows)):
            raise ValueError(f'{name}: select at least one item and keep required navigation.')
        data.extend(bytes([len(rows), *rows]) + bytes(16 - len(rows)))
    return bytes(data) + struct.pack('<I', zlib.crc32(data))


def decode(data, identity=None):
    if len(data) != 80 or data[:8] != b'MENU' + struct.pack('<I', 1) or zlib.crc32(data[:76]) != struct.unpack_from('<I', data, 76)[0]:
        raise ValueError('Screen settings are damaged or from an unsupported version. Reset defaults to replace them.')
    state = {name: list(data[9 + g * 17:9 + g * 17 + data[8 + g * 17]]) for g, name in enumerate(SCREENS)}
    encode(state)
    home = state['Home']
    state['Home'] = [item for i in home for item in
                     ([j for j in (3, 9) if j not in home] if i == 8 else [i])]
    settings = state['Settings']
    if 0 in settings and 10 not in settings:
        settings.insert(settings.index(0) + 1, 10)
    if identity is not None and 10 not in available_items('Settings', identity):
        settings[:] = [item for item in settings if item != 10]
    return state


def read(identity):
    identity = media.refresh(identity)
    root = Path(identity['root'])
    path = root / '.LINNET' / 'MENUS.BIN'
    _plain(path, root)
    if not path.exists():
        return defaults(identity)
    with path.open('rb') as reader:
        return decode(reader.read(81), identity)


def save(identity, state):
    data = encode(state)
    identity = media.refresh(identity)
    root = Path(identity['root'])
    path = root / '.LINNET' / 'MENUS.BIN'
    _plain(path, root)
    if not path.parent.is_dir():
        raise ValueError('Install Linnet on this iPod first.')
    temporary = path.with_name('MENU-' + uuid.uuid4().hex[:8] + '.TMP')
    _plain(temporary, root)
    temporary_owned = False
    try:
        with temporary.open('xb') as stream:
            temporary_owned = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _volume_guard(identity)
        _plain(path, root)
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise IOError('Screen settings could not be verified on the iPod.')
    finally:
        if temporary_owned and temporary.exists():
            _volume_guard(identity)
            _plain(temporary, root)
            temporary.unlink()
    return state
