"""Read existing iTunes media without modifying Apple's databases or originals."""
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import struct
import uuid

from .publish import _bounded, _plain


def _u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _record(data, offset, end, tag):
    if offset + 12 > end or data[offset:offset + 4] != tag:
        raise ValueError('Invalid iTunes media record')
    header, total = struct.unpack_from('<II', data, offset + 4)
    if header < 12 or total < header or offset + total > end:
        raise ValueError('Invalid iTunes media record bounds')
    return offset + header, offset + total


def _list(data, magic, list_tag):
    start, end = _record(data, 0, len(data), magic)
    while start < end:
        body, following = _record(data, start, end, b'mhsd')
        if body - start < 16:
            raise ValueError('Truncated iTunes section')
        if _u32(data, start + 12) == 1:
            if body + 12 > following or data[body:body + 4] != list_tag:
                raise ValueError('Invalid iTunes media list')
            header, count = struct.unpack_from('<II', data, body + 4)
            if header < 12 or body + header > following or count > 100000:
                raise ValueError('Invalid iTunes media count')
            return body + header, following, count
        start = following
    return 0, 0, 0


def _path(root, value):
    parts = value.replace(':', '/').strip('/').split('/')
    if not parts or any(not p or p in ('.', '..') or '\\' in p for p in parts):
        raise ValueError('Unsafe iTunes media path')
    path = root.joinpath(*parts)
    _plain(path, root)
    if not path.resolve().is_relative_to(root):
        raise ValueError('iTunes media path escaped the iPod')
    return path


def tracks(root):
    root = Path(root).resolve()
    path = root / 'iPod_Control/iTunes/iTunesDB'
    _plain(path, root)
    if not path.is_file():
        return {}
    info = path.stat()
    return _tracks(str(root), info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=4)
def _tracks(root_name, size, mtime, ctime):
    root = Path(root_name)
    data = _bounded(root / 'iPod_Control/iTunes/iTunesDB', 128 * 1024 * 1024)
    at, end, count = _list(data, b'mhbd', b'mhlt')
    result = {}
    fields = {1: 'title', 2: 'path', 3: 'album', 4: 'artist', 5: 'genre',
              12: 'composer', 22: 'album_artist'}
    for _ in range(count):
        child, following = _record(data, at, end, b'mhit')
        if child - at < 120:
            raise ValueError('Truncated iTunes track')
        row = dict(duration=_u32(data, at + 40) / 1000, track=_u32(data, at + 44),
                   disc=_u32(data, at + 92), dbid=struct.unpack_from('<Q', data, at + 112)[0],
                   compilation=bool(data[at + 30]),
                   media_type=_u32(data, at + 208) if child - at >= 212 else 1)
        while child < following:
            body, next_child = _record(data, child, following, b'mhod')
            kind = _u32(data, child + 12)
            if kind in fields:
                if body + 16 > next_child:
                    raise ValueError('Truncated iTunes track text')
                length = _u32(data, body + 4)
                if length > next_child - body - 16:
                    raise ValueError('Invalid iTunes track text length')
                row[fields[kind]] = data[body + 16:body + 16 + length].decode('utf-16-le').rstrip('\0')
            child = next_child
        if row.get('path'):
            path = _path(root, row.pop('path'))
            row['path'] = str(path)
            result[str(path.resolve()).casefold()] = row
        at = following
    return result


def _image_string(data, at, end):
    if at + 36 > end:
        raise ValueError('Truncated iTunes image text')
    length = _u32(data, at + 24)
    if length > end - at - 36:
        raise ValueError('Invalid iTunes image text length')
    return data[at + 36:at + 36 + length].decode('utf-16-le' if data[at + 28] == 2 else 'utf-8').rstrip('\0')


def images(root, *, artwork=False):
    root = Path(root).resolve()
    folder = root / ('iPod_Control/Artwork' if artwork else 'Photos')
    database = folder / ('ArtworkDB' if artwork else 'Photo Database')
    _plain(database, root)
    if not database.is_file():
        return []
    data = _bounded(database, 64 * 1024 * 1024)
    at, end, count = _list(data, b'mhfd', b'mhli')
    formats = {1009: (42, 30), 1015: (130, 88), 1024: (320, 240), 1036: (50, 41),
               1017: (56, 56), 1016: (140, 140), 1028: (100, 100), 1029: (200, 200)}
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'Linnet/Media/retail'
    cache = base / hashlib.sha256(str(root).encode() + data).hexdigest()
    result = []
    for _ in range(count):
        child, following = _record(data, at, end, b'mhii')
        if child - at < 28:
            raise ValueError('Truncated iTunes image')
        key = _u32(data, at + 16)
        dbid = struct.unpack_from('<Q', data, at + 20)[0]
        title, candidates = f'Photo {key}', []
        while child < following:
            body, next_child = _record(data, child, following, b'mhod')
            kind = struct.unpack_from('<H', data, child + 12)[0]
            if kind == 1:
                title = _image_string(data, child, next_child) or title
            elif kind == 2:
                name_at, thumb_end = _record(data, body, next_child, b'mhni')
                if name_at - body < 36:
                    raise ValueError('Truncated iTunes thumbnail')
                format_id, offset, length = struct.unpack_from('<III', data, body + 16)
                if format_id in formats:
                    _, name_end = _record(data, name_at, thumb_end, b'mhod')
                    name = _image_string(data, name_at, name_end)
                    path = _path(folder, name)
                    width, height = formats[format_id]
                    vertical, horizontal, image_h, image_w = struct.unpack_from('<4H', data, body + 28)
                    candidates.append((width * height, path, offset, length, width, height,
                                       horizontal, vertical, image_w, image_h))
            child = next_child
        if candidates:
            _, path, offset, length, width, height, x, y, iw, ih = max(candidates, key=lambda c: c[0])
            info = path.stat()
            if length < width * height * 2 or offset + length > info.st_size:
                raise ValueError('iTunes thumbnail extends beyond its file')
            stamp = f'{key}-{info.st_size}-{info.st_mtime_ns}'
            preview = cache / (stamp + '.png')
            if not preview.is_file():
                from PIL import Image
                with path.open('rb') as reader:
                    reader.seek(offset)
                    pixels = reader.read(width * height * 2)
                image = Image.frombytes('RGB', (width, height), pixels, 'raw', 'BGR;16')
                if 0 < iw <= width and 0 < ih <= height and x < iw and y < ih:
                    image = image.crop((x, y, iw, ih))
                cache.mkdir(parents=True, exist_ok=True)
                temporary = preview.with_name(uuid.uuid4().hex + '.tmp')
                try:
                    image.save(temporary, format='PNG')
                    os.replace(temporary, preview)
                finally:
                    temporary.unlink(missing_ok=True)
            result.append(dict(key=key, dbid=dbid, title=title, preview=str(preview),
                               source=str(database), bytes=length, mtime_ns=info.st_mtime_ns,
                               relative=f'Photos/@iTunes/{key}.png'))
        at = following
    return result


def metadata(root):
    from .album_art import cached
    covers = {row['dbid']: row['preview'] for row in images(root, artwork=True)}
    return {path: dict(row, artwork=covers.get(row['dbid']) or cached(row)) for path, row in tracks(root).items()}
