"""Create a complete libgpod input using the verified Linnet metadata cache."""
import base64
import argparse
import json
from pathlib import Path
import sqlite3


parser = argparse.ArgumentParser()
parser.add_argument('--cache', type=Path, required=True,
                    help='Linnet music-metadata.sqlite3 for the mounted A1238')
parser.add_argument('--cache-source', default='F:\\',
                    help='Source key used by that cache (default: F:\\)')
parser.add_argument('--cache-relative-prefix', default='Music/',
                    help='Relative path prefix in cache rows (default: Music/)')
args = parser.parse_args()
inventory = json.loads(Path('out/apple-link-probe/fat-directory-inventory.json').read_text(encoding='utf-8'))
plan = json.loads(Path('out/apple-link-probe/alias-plan.json').read_text(encoding='utf-8'))
items = inventory['items']
by_path = {entry['path']: entry for entry in items}
changes = {entry['path']: entry['new'] for entry in plan['aliases']}
cache = args.cache
database = sqlite3.connect(f'file:{cache.as_posix()}?mode=ro', uri=True)
cached = {relative.casefold(): (size, mtime, json.loads(value))
          for relative, size, mtime, value in database.execute(
              'SELECT relative,size,mtime,value FROM metadata WHERE source=? AND parser=?', (args.cache_source, 'existing'))}


def short_path(path):
    parts = path.split('/')
    return '/'.join(changes.get('/'.join(parts[:index]),
                                by_path['/'.join(parts[:index])]['short'])
                    for index in range(1, len(parts) + 1))


def text(value, fallback=''):
    if isinstance(value, list):
        value = value[0] if value else ''
    return str(value or fallback).strip().replace('\x00', '')


def number(value):
    first = text(value).split('/')[0]
    return int(first) if first.isdecimal() else 0


rows = []
for entry in sorted((entry for entry in items if not entry['directory']), key=lambda x: x['path'].casefold()):
    key = (args.cache_relative_prefix + entry['path']).casefold()
    record = cached.get(key)
    current = (Path('F:/Music') / entry['path']).stat()
    if (record is None or record[0] != entry['size'] or
            current.st_size != entry['size'] or current.st_mtime_ns != record[1] or
            record[2].get('_source_stamp') != [current.st_dev, current.st_ino, current.st_size,
                                             current.st_mtime_ns, current.st_ctime_ns]):
        raise ValueError(f'Missing or mismatched cached MP3 metadata: {entry["path"]}')
    details = record[2]
    rate, frames = details['rate'], details['frames']
    if rate <= 0 or frames <= 0:
        raise ValueError(f'Invalid audio duration: {entry["path"]}')
    tags = details.get('tags') or {}
    actual = short_path(entry['path']).replace('/', ':')
    if not actual.lower().endswith('.mp3'):
        raise ValueError(f'Expected an MP3 FAT alias: {entry["path"]}')
    # Apple's MP3 kind detector is case-sensitive for the final three letters.
    actual = actual[:-4] + '.mp3'
    ipod_path = ':iPod_Control:Music:..:..:Music:' + actual
    if len(ipod_path) > 55:
        raise ValueError(f'Apple path too long: {entry["path"]}')
    title = text(tags.get('title'), Path(entry['path']).stem)
    artist = text(tags.get('artist'), 'Unknown Artist')
    album = text(tags.get('album'), 'Unknown Album')
    album_artist = text(tags.get('albumartist'), artist)
    row = dict(original=entry['path'], apple_path=ipod_path, bytes=entry['size'],
               duration_ms=round(frames * 1000 / rate),
               bitrate_kbps=round(details['data_bytes'] * 8 * rate / frames / 1000),
               sample_rate=rate, track=number(tags.get('tracknumber') or tags.get('track')),
               disc=number(tags.get('discnumber') or tags.get('disc')),
               title=title, artist=artist, album=album, album_artist=album_artist,
               genre=text(tags.get('genre')))
    rows.append(row)

if len(rows) != inventory['summary']['files']:
    raise ValueError(f'Expected {inventory["summary"]["files"]} MP3s, found {len(rows)}')
output = Path('out/apple-link-probe/full-library-manifest.json')
output.write_text(json.dumps(dict(device_serial=plan['device_serial'], rows=rows),
                             ensure_ascii=False, indent=2), encoding='utf-8')

def encoded(value):
    return base64.b64encode(value.encode('utf-8')).decode('ascii')

fields = ('title', 'artist', 'album', 'album_artist', 'genre')
with Path('out/apple-link-probe/full-library-manifest.tsv').open('w', encoding='ascii', newline='\n') as writer:
    for row in rows:
        values = [row['apple_path'], row['bytes'], row['duration_ms'], row['bitrate_kbps'],
                  row['sample_rate'], row['track'], row['disc']]
        values.extend(encoded(row[field]) for field in fields)
        writer.write('\t'.join(map(str, values)) + '\n')
print(json.dumps(dict(tracks=len(rows), max_apple_path=max(map(lambda x:len(x['apple_path']),rows)),
                      total_bytes=sum(row['bytes'] for row in rows),
                      examples=rows[:2]), ensure_ascii=False, indent=2))
