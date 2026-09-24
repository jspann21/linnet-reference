"""Plan metadata-only FAT alias changes; this script never writes the iPod."""
import collections
import hashlib
import json
from pathlib import Path


SOURCE = Path('out/apple-link-probe/fat-directory-inventory.json')
data = json.loads(SOURCE.read_text(encoding='utf-8'))
items = data['items']
by_path = {entry['path']: entry for entry in items}
siblings = collections.defaultdict(list)
for entry in items:
    siblings[entry['path'].rpartition('/')[0]].append(entry)

alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
codes = [a + b for a in alphabet for b in alphabet]
changes = {}
for parent, entries in sorted(siblings.items()):
    reserved = {value.casefold() for entry in entries for value in (entry['name'], entry['short'])}
    for entry in sorted(entries, key=lambda x: x['path'].casefold()):
        if not entry['directory'] or not entry['lfn'] or len(entry['short']) <= 2:
            continue
        code = next((code for code in codes if code.casefold() not in reserved), None)
        if code is None:
            raise ValueError(f'No free two-character alias in {parent}')
        reserved.add(code.casefold())
        changes[entry['path']] = code

def alias_bytes(value):
    stem, dot, ext = value.partition('.')
    if not (1 <= len(stem) <= 8 and len(ext) <= 3 and value == value.upper()):
        raise ValueError(f'Unsafe alias {value}')
    return (stem.ljust(8) + ext.ljust(3)).encode('ascii')


def checksum(alias):
    result = 0
    for byte in alias:
        result = ((((result & 1) << 7) | (result >> 1)) + byte) & 255
    return result


def final_short_path(path):
    parts = path.split('/')
    return '/'.join(changes.get('/'.join(parts[:index]), by_path['/'.join(parts[:index])]['short'])
                    for index in range(1, len(parts) + 1))


for parent, entries in sorted(siblings.items()):
    needed = [entry for entry in entries if not entry['directory'] and len(final_short_path(entry['path'])) > 23]
    if not needed:
        continue
    reserved = {value.casefold() for entry in entries for value in (entry['name'], entry['short'])}
    reserved.update(value.casefold() for path, value in changes.items()
                    if path.rpartition('/')[0] == parent)
    for entry in sorted(needed, key=lambda x: x['path'].casefold()):
        if not entry['lfn']:
            raise ValueError(f'Overlong unchangeable file alias: {entry["path"]}')
        parent_length = len(final_short_path(parent)) if parent else 0
        max_base = 23 - parent_length - (1 if parent else 0) - len('.MP3')
        values = [value + '.MP3' for value in alphabet]
        values += [value + '.MP3' for value in codes]
        code = next((value for value in values if len(value.partition('.')[0]) <= max_base
                     and value.casefold() not in reserved), None)
        if code is None:
            raise ValueError(f'No compact file alias in {parent}')
        reserved.add(code.casefold())
        changes[entry['path']] = code

overlong = [(entry['path'], final_short_path(entry['path'])) for entry in items
            if not entry['directory'] and len(final_short_path(entry['path'])) > 23]
if overlong:
    raise ValueError(f'Paths still exceed the 23-character Apple budget: {overlong[:3]}')

for parent, entries in siblings.items():
    names = [entry['name'].casefold() for entry in entries]
    aliases = [changes.get(entry['path'], entry['short']).casefold() for entry in entries]
    if len(set(names)) != len(names) or len(set(aliases)) != len(aliases):
        raise ValueError(f'Alias collision inside {parent}')
    for entry in entries:
        proposed = changes.get(entry['path'])
        if proposed and proposed.casefold() in names:
            raise ValueError(f'Alias conflicts with a long name in {parent}: {proposed}')

with open(r'\\.\F:', 'rb', buffering=0) as disk:
    before = {}
    after = {}
    def sector(index):
        if index not in before:
            disk.seek(index * 4096)
            raw = disk.read(4096)
            if len(raw) != 4096:
                raise ValueError(f'Failed to read sector {index}')
            before[index] = raw
            after[index] = bytearray(raw)
        return after[index]

    for path, proposed in changes.items():
        entry = by_path[path]
        previous = bytes.fromhex(entry['alias_hex'])
        replacement = alias_bytes(proposed)
        if previous == replacement:
            raise ValueError(f'No-op alias change: {path}')
        position = entry['position']
        start = position % 4096
        page = sector(position // 4096)
        if page[start:start + 32] != bytes.fromhex(entry['raw_hex']):
            raise ValueError(f'Directory entry changed during planning: {path}')
        page[start:start + 11] = replacement
        old_check = checksum(previous)
        new_check = checksum(replacement)
        if not entry['lfn_positions']:
            raise ValueError(f'Cannot preserve visible name without LFN: {path}')
        for lfn_position in entry['lfn_positions']:
            offset = lfn_position % 4096
            lfn = sector(lfn_position // 4096)
            if lfn[offset + 11] != 15 or lfn[offset + 13] != old_check:
                raise ValueError(f'LFN changed during planning: {path}')
            lfn[offset + 13] = new_check

sectors = sorted(before)
result = dict(device_serial='000A2700155D9C10', volume_serial=data['summary']['serial'],
              boot_sha256=data['summary']['boot_sha256'],
              sector_bytes=4096, changes=len(changes), sector_count=len(sectors),
              max_short_path=max(len(final_short_path(entry['path'])) for entry in items
                                 if not entry['directory']),
              sectors=[dict(index=index, before_sha256=hashlib.sha256(before[index]).hexdigest(),
                            after_sha256=hashlib.sha256(after[index]).hexdigest()) for index in sectors],
              aliases=[dict(path=path, old=by_path[path]['short'], new=changes[path])
                       for path in sorted(changes, key=str.casefold)])

# Parse the proposed on-disk directory sectors as a second complete VFAT tree.
# Long names, clusters and sizes must survive byte-for-byte; only short aliases
# may differ. This runs before any device write and catches malformed LFN groups.
from fat_alias_plan import FatVolume, inventory
volume = FatVolume()
volume.overrides = {index: bytes(after[index]) for index in sectors}
overlaid_summary, overlaid_items = inventory(volume)
if len(overlaid_items) != len(items):
    raise ValueError('Proposed aliases changed the number of directory entries')
for proposed in overlaid_items:
    original = by_path.get(proposed['path'])
    if original is None or any(proposed[field] != original[field]
                               for field in ('name', 'cluster', 'size', 'directory')):
        raise ValueError(f'Proposed aliases changed a visible path or data link: {proposed["path"]}')
    if proposed['short'] != changes.get(proposed['path'], original['short']):
        raise ValueError(f'Proposed alias did not round-trip: {proposed["path"]}')
if overlaid_summary['files'] != data['summary']['files']:
    raise ValueError('Proposed aliases changed the music file count')

output = Path('out/apple-link-probe/alias-plan.json')
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
Path('out/apple-link-probe/alias-before.bin').write_bytes(b''.join(before[index] for index in sectors))
Path('out/apple-link-probe/alias-after.bin').write_bytes(b''.join(after[index] for index in sectors))
print(json.dumps({key: value for key, value in result.items() if key not in ('sectors', 'aliases')}, indent=2))
