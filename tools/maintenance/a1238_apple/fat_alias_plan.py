"""Read-only VFAT directory inventory for the A1238 alias experiment."""
import collections
import hashlib
import json
from pathlib import Path
import struct


DRIVE = r'\\.\F:'
EXPECTED_SERIAL = 0x5FC88A5C


class FatVolume:
    def __init__(self):
        self.io = open(DRIVE, 'rb', buffering=0)
        boot = self.io.read(4096)
        if len(boot) != 4096 or boot[510:512] != b'\x55\xaa':
            raise ValueError('Unexpected FAT boot sector')
        self.sector_size = struct.unpack_from('<H', boot, 11)[0]
        self.sectors_per_cluster = boot[13]
        self.reserved = struct.unpack_from('<H', boot, 14)[0]
        self.fats = boot[16]
        self.fat_sectors = struct.unpack_from('<I', boot, 36)[0]
        self.root_cluster = struct.unpack_from('<I', boot, 44)[0]
        self.serial = struct.unpack_from('<I', boot, 67)[0]
        self.total_sectors = struct.unpack_from('<I', boot, 32)[0]
        self.data_sector = self.reserved + self.fats * self.fat_sectors
        if (self.serial != EXPECTED_SERIAL or
                self.sector_size != 4096 or self.sectors_per_cluster != 4 or
                self.fats != 2 or self.root_cluster != 2 or
                self.fat_sectors != 1777 or self.total_sectors != 7276358):
            raise ValueError('This is not the inventoried A1238 FAT32 geometry')
        self.io.seek(self.reserved * self.sector_size)
        self.fat = self.io.read(self.fat_sectors * self.sector_size)
        if len(self.fat) != self.fat_sectors * self.sector_size:
            raise ValueError('FAT read was short')
        self.boot_hash = hashlib.sha256(boot).hexdigest()
        self.overrides = {}

    def chain(self, cluster):
        seen = set()
        while 2 <= cluster < 0x0ffffff8:
            if cluster in seen or cluster * 4 + 4 > len(self.fat):
                raise ValueError(f'Invalid directory FAT chain at {cluster}')
            seen.add(cluster)
            yield cluster
            cluster = struct.unpack_from('<I', self.fat, cluster * 4)[0] & 0x0fffffff
        if cluster < 0x0ffffff8:
            raise ValueError(f'Invalid FAT end marker {cluster}')

    def directory_bytes(self, cluster):
        for item in self.chain(cluster):
            sector = self.data_sector + (item - 2) * self.sectors_per_cluster
            data = bytearray()
            for index in range(sector, sector + self.sectors_per_cluster):
                if index in self.overrides:
                    data.extend(self.overrides[index])
                else:
                    self.io.seek(index * self.sector_size)
                    data.extend(self.io.read(self.sector_size))
            if len(data) != self.sector_size * self.sectors_per_cluster:
                raise ValueError('Directory read was short')
            for offset in range(0, len(data), 32):
                absolute = sector * self.sector_size + offset
                yield absolute, data[offset:offset + 32]


def checksum(alias):
    result = 0
    for byte in alias:
        result = (((result & 1) << 7) | (result >> 1)) + byte
        result &= 255
    return result


def short_name(alias, flags):
    base = alias[:8].decode('cp437').rstrip()
    ext = alias[8:].decode('cp437').rstrip()
    if flags & 8:
        base = base.lower()
    if flags & 16:
        ext = ext.lower()
    return base + ('.' + ext if ext else '')


def long_name(slots, alias):
    if not slots:
        return None
    expected = list(range(len(slots), 0, -1))
    if [raw[0] & 0x1f for _, raw in slots] != expected or slots[0][1][0] != (len(slots) | 0x40):
        raise ValueError('Malformed VFAT LFN ordinals')
    if any(raw[11] != 15 or raw[12] or raw[13] != checksum(alias) or raw[26:28] != b'\0\0'
           for _, raw in slots):
        raise ValueError('Malformed VFAT LFN checksum or attributes')
    units = []
    for _, raw in reversed(slots):
        fragment = raw[1:11] + raw[14:26] + raw[28:32]
        units.extend(struct.unpack('<13H', fragment))
    if 0 in units:
        units = units[:units.index(0)]
    units = [x for x in units if x != 0xffff]
    return struct.pack('<' + 'H' * len(units), *units).decode('utf-16le')


def entries(volume, cluster):
    pending = []
    for position, raw in volume.directory_bytes(cluster):
        if raw[0] == 0:
            break
        if raw[0] == 0xe5:
            pending = []
            continue
        if raw[11] == 15:
            pending.append((position, raw))
            continue
        alias = raw[:11]
        if raw[11] & 8:
            pending = []
            continue
        displayed = long_name(pending, alias)
        short = short_name(alias, raw[12])
        item = dict(name=displayed or short, short=short, alias_hex=alias.hex(),
                    cluster=(struct.unpack_from('<H', raw, 20)[0] << 16) |
                            struct.unpack_from('<H', raw, 26)[0],
                    size=struct.unpack_from('<I', raw, 28)[0],
                    directory=bool(raw[11] & 16), lfn=bool(pending),
                    position=position, lfn_positions=[pos for pos, _ in pending],
                    raw_hex=raw.hex())
        pending = []
        if short in ('.', '..'):
            continue
        yield item


def walk(volume, cluster, prefix=''):
    for item in entries(volume, cluster):
        path = f'{prefix}/{item["name"]}' if prefix else item['name']
        item['path'] = path
        yield item
        if item['directory']:
            if not item['cluster']:
                raise ValueError(f'Directory with no cluster: {path}')
            yield from walk(volume, item['cluster'], path)


def inventory(volume):
    root_items = list(entries(volume, volume.root_cluster))
    music = [x for x in root_items if x['name'].casefold() == 'music']
    if len(music) != 1 or not music[0]['directory']:
        raise ValueError('Cannot identify /Music')
    items = list(walk(volume, music[0]['cluster']))
    files = [x for x in items if not x['directory']]
    directories = [x for x in items if x['directory']]
    if not files or any(not x['name'].lower().endswith('.mp3') for x in files):
        raise ValueError('Expected a nonempty MP3-only /Music tree')
    by_path = {item['path']: item for item in items}
    if len(by_path) != len(items):
        raise ValueError('Duplicate path in /Music directory tree')
    def short_path_length(path):
        parts = path.split('/')
        return len('/'.join(by_path['/'.join(parts[:index])]['short']
                            for index in range(1, len(parts) + 1)))
    summary = dict(serial=f'{volume.serial:08x}', boot_sha256=volume.boot_hash,
                   music_cluster=music[0]['cluster'], files=len(files), directories=len(directories),
                   lfn_files=sum(x['lfn'] for x in files), lfn_directories=sum(x['lfn'] for x in directories),
                   longest_existing_short_path=max(short_path_length(x['path']) for x in files))
    return summary, items


if __name__ == '__main__':
    volume = FatVolume()
    summary, items = inventory(volume)
    print(json.dumps(summary, indent=2))
    Path('out/apple-link-probe/fat-directory-inventory.json').write_text(
        json.dumps(dict(summary=summary, items=items), ensure_ascii=False, indent=2), encoding='utf-8')
