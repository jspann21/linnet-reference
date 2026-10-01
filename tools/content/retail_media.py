"""Read existing iTunes media without modifying Apple's databases or originals."""
from collections import OrderedDict
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import stat
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


def _path(root, value, *, with_identity=False, parent_checks=None):
    parts = value.replace(':', '/').strip('/').split('/')
    # Apple's tested Classic database route to a shared /Music tree begins at
    # iPod_Control/Music, then steps back to the volume root. Accept that one
    # fixed traversal only; all other parent components remain invalid.
    if parts[:4] == ['iPod_Control', 'Music', '..', '..'] and len(parts) > 5 \
            and parts[4] in ('Music', 'Videos'):
        parts = parts[4:]
    if not parts or any(not p or p in ('.', '..') or '\\' in p for p in parts):
        raise ValueError('Unsafe iTunes media path')
    path = root.joinpath(*parts)
    if parent_checks is None:
        _plain(path, root)
    else:
        # Tracks in one iTunesDB share a small set of directories. Check each
        # directory once for this read-only parse, but still check every leaf
        # and resolve every full path below.
        cursor = root
        for component in (None, *parts[:-1]):
            if component is not None:
                cursor /= component
            if cursor not in parent_checks:
                _plain(cursor, root)
                try:
                    info = cursor.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    parent_checks[cursor] = (info.st_dev, info.st_ino, info.st_ctime_ns)
        try:
            info = path.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(f'reparse/symlink path rejected: {path}')
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('iTunes media path escaped the iPod')
    return (path, resolved) if with_identity else path


def tracks(root):
    root = Path(root).resolve()
    path = root / 'iPod_Control/iTunes/iTunesDB'
    _plain(path, root)
    if not path.is_file():
        return {}
    info = path.stat()
    return _tracks(str(root), info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def available_tracks(root):
    """Apple metadata is optional when its database cannot be read."""
    try:
        return tracks(root)
    except (OSError, ValueError, UnicodeError, struct.error):
        return {}


@lru_cache(maxsize=4)
def _tracks(root_name, size, mtime, ctime):
    root = Path(root_name)
    data = _bounded(root / 'iPod_Control/iTunes/iTunesDB', 128 * 1024 * 1024)
    at, end, count = _list(data, b'mhbd', b'mhlt')
    result = {}
    parent_checks = {}
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
            path, resolved = _path(root, row.pop('path'), with_identity=True,
                                   parent_checks=parent_checks)
            row['path'] = str(path)
            result[str(resolved).casefold()] = row
        at = following
    # A directory replaced during the parse must not leave a cached proof in
    # the returned metadata. This cache never survives the current parse.
    for path, before in parent_checks.items():
        _plain(path, root)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino, info.st_ctime_ns) != before:
            raise ValueError('iTunes media directory changed during scan')
    return result


def _image_string(data, at, end):
    if at + 36 > end:
        raise ValueError('Truncated iTunes image text')
    length = _u32(data, at + 24)
    if length > end - at - 36:
        raise ValueError('Invalid iTunes image text length')
    return data[at + 36:at + 36 + length].decode('utf-16-le' if data[at + 28] == 2 else 'utf-8').rstrip('\0')


def image_count(root):
    """Validate the image list without rendering every thumbnail."""
    root = Path(root).resolve()
    database = root / 'Photos/Photo Database'
    _plain(database, root)
    data = _bounded(database, 64 * 1024 * 1024)
    at, end, count = _list(data, b'mhfd', b'mhli')
    for _ in range(count):
        _, at = _record(data, at, end, b'mhii')
    return count


class _ThumbnailReaders:
    """Keep a few shared thumbnail files open for one cold extraction."""

    def __init__(self):
        self._open = OrderedDict()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for reader in self._open.values():
            reader.close()
        self._open.clear()

    def read(self, path, offset, size):
        reader = self._open.pop(path, None)
        if reader is None:
            reader = path.open('rb')
        self._open[path] = reader
        if len(self._open) > 4:
            _, retired = self._open.popitem(last=False)
            retired.close()
        reader.seek(offset)
        pixels = reader.read(size)
        if len(pixels) != size:
            raise ValueError('Truncated iTunes thumbnail')
        return pixels


def _write_preview(image, preview):
    temporary = preview.with_name(uuid.uuid4().hex + '.tmp')
    try:
        image.save(temporary, format='PNG', compress_level=3)
        os.replace(temporary, preview)
    finally:
        temporary.unlink(missing_ok=True)


def images(root, *, artwork=False, dbids=None, render=True):
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
    # Windows st_dev is the volume serial. It survives a drive-letter change,
    # unlike root, while the database bytes still separate artwork revisions.
    cache_scope = f'volume:{root.stat().st_dev:08x}' if os.name == 'nt' else str(root)
    cache = base / hashlib.sha256(cache_scope.encode() + data).hexdigest()
    result = {}
    paths = {}
    file_info = {}
    pending, queued = deque(), set()
    selected = []
    for order in range(count):
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
                    if name not in paths:
                        paths[name] = _path(folder, name)
                    path = paths[name]
                    width, height = formats[format_id]
                    vertical, horizontal, image_h, image_w = struct.unpack_from('<4H', data, body + 28)
                    candidates.append((width * height, path, offset, length, width, height,
                                       horizontal, vertical, image_w, image_h))
            child = next_child
        if candidates and (dbids is None or dbid in dbids):
            selected.append((order, key, dbid, title,
                             sorted(candidates, key=lambda c: c[0], reverse=True)))
        at = following
    if render and len({row[1] for row in selected}) == len(selected):
        selected.sort(key=lambda row: (str(row[4][0][1]).casefold(), row[4][0][2]))
    with _ThumbnailReaders() as readers, ExitStack() as workers:
        encoder = None
        for order, key, dbid, title, candidates in selected:
            for _, path, offset, length, width, height, x, y, iw, ih in candidates:
                info = file_info.get(path)
                if info is None:
                    try:
                        info = path.stat()
                    except FileNotFoundError:
                        continue
                    file_info[path] = info
                if length < width * height * 2 or offset + length > info.st_size:
                    raise ValueError('iTunes thumbnail extends beyond its file')
                stamp = f'{key}-{info.st_size}-{info.st_mtime_ns}'
                preview = cache / (stamp + '.png')
                if render and preview not in queued and not preview.is_file():
                    from PIL import Image
                    try:
                        pixels = readers.read(path, offset, width * height * 2)
                    except FileNotFoundError:
                        continue
                    image = Image.frombytes('RGB', (width, height), pixels, 'raw', 'BGR;16')
                    if 0 < iw <= width and 0 < ih <= height and x < iw and y < ih:
                        image = image.crop((x, y, iw, ih))
                    cache.mkdir(parents=True, exist_ok=True)
                    if encoder is None:
                        encoder = workers.enter_context(ThreadPoolExecutor(max_workers=4))
                    queued.add(preview)
                    pending.append(encoder.submit(_write_preview, image, preview))
                    if len(pending) >= 4:
                        pending.popleft().result()
                result[order] = dict(key=key, dbid=dbid, title=title, preview=str(preview),
                                     source=str(database), bytes=length, mtime_ns=info.st_mtime_ns,
                                     relative=f'Photos/@iTunes/{key}.png')
                break
        while pending:
            pending.popleft().result()
        for path, before in file_info.items():
            _plain(path, folder)
            after = path.stat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('iTunes thumbnail changed during scan')
    return [result[order] for order in sorted(result)]


def metadata(root):
    from .album_art import _base, cached
    rows = available_tracks(root)
    if not rows:
        return {}
    used_dbids = {row['dbid'] for row in rows.values()}
    try:
        covers = {row['dbid']: row['preview'] for row in images(root, artwork=True, dbids=used_dbids)}
    except (OSError, ValueError, UnicodeError, struct.error):
        covers = {}
    cached_covers = {}
    def artwork(row):
        if row['dbid'] in covers:
            return covers[row['dbid']]
        album = _base(row)
        if album not in cached_covers:
            cached_covers[album] = cached(row)
        return cached_covers[album]
    return {path: dict(row, artwork=artwork(row)) for path, row in rows.items()}
