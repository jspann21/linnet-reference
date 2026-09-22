import struct
import zlib


def prepare(database: bytes) -> bytes:
    """Compile exact artist/album relations from the validated PODB membership lists."""
    from .music import validate_database
    validate_database(database)
    groups, start, members = (struct.unpack_from('<I', database, offset)[0] for offset in (20, 36, 40))
    rows = [struct.unpack_from('<6IQ', database, start + i * 32) for i in range(groups)]
    track_albums = {}
    owners = set()
    owned = {}
    for album, row in enumerate(rows):
        if row[0] != 2:
            continue
        owners.add(row[2])
        owned.setdefault(row[2], set()).add(album)
        for (track,) in struct.iter_unpack('<I', database[members + row[3]*4:members + (row[3]+row[4])*4]):
            track_albums.setdefault(track, set()).add(album)
    records, links = [], []
    for artist, row in enumerate(rows):
        if row[0] != 1:
            continue
        albums = set(owned.get(artist, ()))
        for (track,) in struct.iter_unpack('<I', database[members + row[3]*4:members + (row[3]+row[4])*4]):
            albums.update(track_albums.get(track, ()))
        records.append(struct.pack('<III', artist, len(links), len(albums)))
        links.extend(sorted(albums))
    ranges = []
    for kind in range(1, 9):
        indices = [i for i, row in enumerate(rows) if row[0] == kind]
        if indices and indices != list(range(indices[0], indices[0] + len(indices))):
            raise ValueError('Browse groups are not contiguous by kind')
        ranges.extend((indices[0] if indices else 0, len(indices)))
    payload = struct.pack('<16I', *ranges) + b''.join(records) + struct.pack(f'<{len(links)}I', *links) + struct.pack(f'<{len(owners)}I', *sorted(owners))
    header = bytearray(64)
    struct.pack_into('<4s5I', header, 0, b'LBR1', 64 + len(payload), len(records), len(links), len(owners), groups)
    header[24:56] = database[64:96]
    struct.pack_into('<I', header, 56, zlib.crc32(payload))
    struct.pack_into('<I', header, 60, zlib.crc32(header[:60]))
    return bytes(header) + payload
