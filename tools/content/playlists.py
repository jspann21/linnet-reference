import os
from pathlib import Path
import struct
import zlib

from . import media_manager as manager
from .music import MAX_DATABASE, TRACK, validate_database
from .publish import _exclusive, _plain, _volume_guard, provision_collections

SIZE, SLOTS, CAPACITY = 147456, 16, 1024
RESUME = 80 + 6 * CAPACITY + 44
LISTS, ENTRY = 512 + 4 + RESUME, 40 + 8 * CAPACITY
RECENT = LISTS + SLOTS * ENTRY


def decode(data):
    if len(data) != SIZE:
        raise ValueError('Unexpected playlist bank size')
    raw = bytearray(data)
    magic, version, generation, checksum = struct.unpack_from('<4sIII', raw)
    struct.pack_into('<I', raw, 12, 0)
    if magic != b'LLST' or version != 1 or not generation or zlib.crc32(raw) != checksum:
        raise ValueError('Invalid playlist bank checksum or version')
    if struct.unpack_from('<I', raw, 512)[0] > RESUME or struct.unpack_from('<I', raw, RECENT)[0] > 256:
        raise ValueError('Invalid playlist playback state')
    lists = []
    for slot in range(SLOTS):
        at = LISTS + slot * ENTRY
        count = struct.unpack_from('<I', raw, at + 32)[0]
        if raw[at + 31] or count > CAPACITY or (not raw[at] and count):
            raise ValueError('Invalid playlist entry')
        lists.append(dict(name=bytes(raw[at:at + 32]).split(b'\0', 1)[0].decode('utf-8'),
                          ids=list(struct.unpack_from(f'<{count}Q', raw, at + 40))))
    return generation, lists


def banks(root):
    paths = [root / '.LINNET' / f'LISTS{i}.BIN' for i in range(2)]
    snapshots, valid = [], []
    for index, path in enumerate(paths):
        _plain(path, root)
        if not path.exists():
            snapshots.append(None)
            continue
        if path.stat().st_size != SIZE:
            raise ValueError('Unexpected playlist bank size; preserving it')
        data = path.read_bytes()
        snapshots.append(data)
        try:
            generation, lists = decode(data)
            valid.append((generation, index, lists))
        except ValueError:
            pass
    if not valid:
        if any(data is not None for data in snapshots):
            raise ValueError('No valid playlist bank; preserving iPod state')
        return snapshots, None, [dict(name='', ids=[]) for _ in range(SLOTS)]
    if len(valid) == 2 and valid[0][0] == valid[1][0] and snapshots[0] != snapshots[1]:
        raise ValueError('Playlist banks disagree at the same generation')
    _, active, lists = max(valid, key=lambda item: item[0])
    return snapshots, active, lists


def read(identity):
    identity = manager.refresh(identity)
    root = Path(identity['root'])
    snapshots, _, lists = banks(root)
    path = root / '.LINNET' / 'LIBRARY.PDB'
    _plain(path, root)
    tracks = {}
    if path.exists():
        if path.stat().st_size > MAX_DATABASE:
            raise ValueError('Music library is too large')
        data = path.read_bytes()
        validate_database(data)
        width = TRACK
        fields = struct.unpack_from('<14I', data, 8)
        for index in range(fields[2]):
            at = fields[6] + index * width
            strings = []
            for offset in struct.unpack_from('<3I', data, at + 52):
                start = fields[10] + offset
                strings.append(data[start:data.index(b'\0', start)].decode('utf-8'))
            tracks[struct.unpack_from('<Q', data, at)[0]] = ' · '.join(filter(None, strings))
    return dict(identity=identity, snapshots=snapshots, lists=lists, tracks=tracks)


def save(state):
    identity = manager.refresh(state['identity'])
    root = Path(identity['root'])
    with _exclusive(identity):
        snapshots, active, _ = banks(root)
        if snapshots != state['snapshots']:
            raise ValueError('Playlists changed on the iPod. Reopen Playlists before saving.')
        if len(state['lists']) != SLOTS:
            raise ValueError('The iPod supports 16 playlists')
        if active is None:
            data = bytearray(SIZE)
            struct.pack_into('<4sIII', data, 0, b'LLST', 1, 1, 0)
        else:
            data = bytearray(snapshots[active])
        generation = struct.unpack_from('<I', data, 8)[0]
        if generation == 0xffffffff:
            raise ValueError('Playlist generation limit reached')
        for slot, playlist in enumerate(state['lists']):
            name, ids = playlist['name'].encode('utf-8'), playlist['ids']
            if len(name) > 31 or b'\0' in name or len(ids) > CAPACITY or (not name and ids):
                raise ValueError('Use names of 1–31 UTF-8 bytes and at most 1024 tracks per playlist')
            at = LISTS + slot * ENTRY
            data[at:at + ENTRY] = bytes(ENTRY)
            data[at:at + len(name)] = name
            struct.pack_into('<I', data, at + 32, len(ids))
            struct.pack_into(f'<{len(ids)}Q', data, at + 40, *ids)
        struct.pack_into('<II', data, 8, generation + 1, 0)
        struct.pack_into('<I', data, 12, zlib.crc32(data))
        decode(data)
        guard = lambda: _volume_guard(identity)
        directory = root / '.LINNET'
        _plain(directory, root)
        guard()
        directory.mkdir(exist_ok=True)
        provision_collections(directory, guard)
        target = directory / f'LISTS{1 - active if active is not None else 1}.BIN'
        guard()
        with target.open('r+b') as writer:
            writer.seek(512)
            writer.write(data[512:])
            writer.flush()
            os.fsync(writer.fileno())
            guard()
            writer.seek(0)
            writer.write(data[:512])
            writer.flush()
            os.fsync(writer.fileno())
        guard()
        if target.read_bytes() != data:
            raise OSError('Playlist save readback failed; reopen Playlists before retrying')
