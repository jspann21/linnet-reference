"""Host-prepared Files directory pages and native-size previews.

The device reads one 4 KiB page, validates its records, and opens the selected
short name relative to its live parent handle. It never sorts or recursively
indexes the disk. Original files are not renamed or rewritten.
"""
from collections import deque
from pathlib import Path
import hashlib
import json
import os
import stat
import struct
import time
import unicodedata
import uuid
import zlib
from types import SimpleNamespace

from .publish import _plain, _hash

RECORD = 256
MAX_RECORDS = 1_000_000
MAX_FILE = 512 + MAX_RECORDS * RECORD
PACK_BYTES = 4 * 1024 * 1024
IMAGES = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.heic', '.avif'}
TEXT = {'.txt', '.text', '.md', '.rst', '.log', '.ini', '.cfg', '.toml', '.yaml', '.yml',
        '.json', '.xml', '.csv', '.nfo', '.c', '.h', '.py', '.js', '.ts', '.tsx', '.css', '.html', '.htm'}


def _short_name(path):
    if os.name == 'nt':
        from .music import _actual_short_component
        return _actual_short_component(_windows_path(path)).upper()
    return path.name.upper()


def _windows_path(path):
    name = os.path.abspath(path)
    if name.startswith('\\\\?\\'):
        return name
    return '\\\\?\\UNC\\' + name[2:] if name.startswith('\\\\') else '\\\\?\\' + name


def _directory_entries(folder):
    """Keep the short alias and metadata Windows already returns per entry."""
    if os.name != 'nt':
        with os.scandir(folder) as iterator:
            for entry in iterator:
                if entry.is_symlink():
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                    yield entry.name, stat.S_ISDIR(info.st_mode), info, None
        return
    import ctypes
    from ctypes import wintypes
    from .music import _FindData, _find_kernel
    next_file = _find_kernel.FindNextFileW
    next_file.argtypes = (wintypes.HANDLE, ctypes.POINTER(_FindData))
    next_file.restype = wintypes.BOOL
    data = _FindData()
    handle = _find_kernel.FindFirstFileW(_windows_path(folder / '*'), ctypes.byref(data))
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 2:  # Empty directory.
            return
        raise ctypes.WinError(error)
    try:
        while True:
            if data.name not in ('.', '..') and not data.attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                stamp = (data.write.dwHighDateTime << 32) | data.write.dwLowDateTime
                info = SimpleNamespace(st_size=(data.size_high << 32) | data.size_low,
                                       st_mtime_ns=(stamp - 116444736000000000) * 100)
                yield data.name, bool(data.attributes & 16), info, data.alternate or data.name
            if not next_file(handle, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error != 18:  # ERROR_NO_MORE_FILES
                    raise ctypes.WinError(error)
                break
    finally:
        if not _find_kernel.FindClose(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _label(value, limit):
    # Linnet's fonts are ASCII; normalize on the host once, not each UI frame.
    from .notes import _ascii
    value = _ascii(value)
    return ''.join(c if 32 <= ord(c) < 127 else ' ' for c in value).encode('ascii')[:limit]


def _alias(value):
    value = value.upper()
    parts = value.split('.')
    if (len(parts) > 2 or not 1 <= len(parts[0]) <= 8 or
            (len(parts) == 2 and not 1 <= len(parts[1]) <= 3) or
            any(ord(c) < 33 or ord(c) > 126 or c in '/\\:*?"<>|+,;=[]' for c in value)):
        return b''
    return value.encode('ascii')


def _preview(source, cache, width, height, columns, recipe, checkpoint, info, root):
    suffix = source.suffix.lower()
    if suffix not in IMAGES | TEXT or (suffix in IMAGES and not width):
        return None
    # Cache-key work uses file metadata; unchanged images/text are not decoded
    # again during each preparation. Output hashes still guard publication.
    key = hashlib.sha256(f'files-v2:{source}:{info.st_size}:{info.st_mtime_ns}:{width}:{height}:{columns}:{recipe[2]}'.encode()).hexdigest()
    output = cache / (key + ('.FIM' if suffix in IMAGES else '.TXT'))
    if not output.exists():
        checkpoint()
        # Enumeration rejects links; recheck the complete path immediately
        # before reading source bytes. Cache hits only read the local cache.
        _plain(source, root)
        if suffix in IMAGES:
            from PIL import Image, ImageOps
            from .photos import _rgb565
            with Image.open(source) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
                canvas = Image.new('RGB', (width, height))
                canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
                payload = _rgb565(canvas)
            header = bytearray(512)
            struct.pack_into('<4s4I', header, 0, b'FIMG', 1, width, height, zlib.crc32(payload))
            struct.pack_into('<I', header, 508, zlib.crc32(header[:508]))
            data = header + payload
        else:
            if info.st_size > 16 * 1024 * 1024:
                return None  # Native bounded byte/text paging remains available.
            raw = source.read_bytes()
            encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
            try:
                text = raw.decode(encoding)
            except UnicodeError:
                text = raw.decode('cp1252', errors='replace')
            if '\0' in text:
                return None
            from .notes import _ascii, _display_lines
            text = _ascii(text)
            # One record per visual line; whole pages start on line boundaries.
            data = bytearray()
            for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
                checkpoint()
                clean = ''.join(c if 32 <= ord(c) < 127 else ' ' for c in line.expandtabs(4))
                for wrapped in _display_lines(clean, recipe[0], recipe[1], columns):
                    if len(data) + columns > 4 * 1024 * 1024:
                        return None
                    data.extend(wrapped.encode('ascii').ljust(columns, b' '))
        after = source.stat()
        if after.st_size != info.st_size or after.st_mtime_ns != info.st_mtime_ns:
            raise ValueError(f'File changed while preparing its preview: {source}')
        temporary = output.with_suffix(output.suffix + '.tmp')
        with temporary.open('wb') as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, output)
    digest = _hash(output)
    relative = f'.LINNET/FILES/PREVIEW/{digest[:2].upper()}/{digest[2:10].upper()}{output.suffix}'
    return dict(source=str(output), path=relative, bytes=output.stat().st_size,
                sha256=digest, kind=1 if suffix in IMAGES else 2)


def _prepared_videos(root, warnings):
    """Resolve the existing host conversions once, including AVI/MKV sources."""
    from .video_catalog import read_file
    catalog = root / '.LINNET' / 'VIDEOS' / 'INDEX.VID'
    if not catalog.exists():
        return {}
    result = {}
    try:
        _plain(catalog, root)
        _, entries = read_file(catalog)
        for key, path, _ in entries:
            if len(path.encode('ascii')) >= 76:
                continue
            prepared = root / path.lstrip('/')
            _plain(prepared, root)
            if prepared.is_file():
                result[key] = dict(path=path, bytes=prepared.stat().st_size, kind=3)
    except (OSError, ValueError) as error:
        warnings.append(dict(path='.LINNET/VIDEOS/INDEX.VID', message=str(error)))
    return result


def _pack_previews(previews, cache, checkpoint):
    """Reuse sealed packs; adding one preview never rewrites existing packs."""
    cache = Path(cache) / 'packs'
    cache.mkdir(parents=True, exist_ok=True)
    manifest = cache / 'layout.json'
    packs, locations, layout = [], {}, []

    def add_pack(digest, size, members):
        path = f'.LINNET/FILES/PACKS/{digest[:8].upper()}/{digest[8:16].upper()}.FPK'
        packs.append(dict(source=str(cache / (digest + '.FPK')), path=path, bytes=size, sha256=digest))
        layout.append(dict(sha256=digest, members=members))
        for key, offset, length in members:
            locations[key] = (path, offset)

    try:
        previous = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = []
    # This is only a host cache hint. Verify both the pack and each requested
    # slice before trusting offsets, and rebuild any missing/corrupt cache data.
    for item in previous if isinstance(previous, list) else []:
        checkpoint()
        if not isinstance(item, dict):
            continue
        digest, members = item.get('sha256'), item.get('members')
        if (not isinstance(digest, str) or len(digest) != 64 or
                any(c not in '0123456789abcdef' for c in digest) or not isinstance(members, list)):
            continue
        wanted = [m for m in members if isinstance(m, list) and len(m) == 3 and
                  isinstance(m[0], str) and m[0] in previews and m[0] not in locations and
                  type(m[1]) is int and type(m[2]) is int and m[1] >= 0 and not m[1] % 512 and
                  m[2] == previews[m[0]]['bytes'] and m[2] >= 0]
        if not wanted:
            continue
        try:
            with (cache / (digest + '.FPK')).open('rb') as reader:
                data = reader.read(PACK_BYTES + 1)
        except OSError:
            continue
        if len(data) > PACK_BYTES or hashlib.sha256(data).hexdigest() != digest:
            continue
        valid = [m for m in wanted if m[1] <= len(data) and m[2] <= len(data) - m[1] and
                 hashlib.sha256(data[m[1]:m[1]+m[2]]).hexdigest() == m[0]]
        if valid:
            add_pack(digest, len(data), valid)

    missing = sorted((key, item) for key, item in previews.items() if key not in locations)
    for bucket in '0123456789abcdef':
        payload, members = bytearray(), []

        def finish():
            if not members:
                return
            checkpoint()
            digest = hashlib.sha256(payload).hexdigest()
            output = cache / (digest + '.FPK')
            try:
                valid = _hash(output, len(payload)) == digest
            except (OSError, ValueError):
                valid = False
            if not valid:
                temporary = output.with_suffix('.tmp')
                with temporary.open('wb') as writer:
                    writer.write(payload)
                    writer.flush()
                    os.fsync(writer.fileno())
                os.replace(temporary, output)
            add_pack(digest, len(payload), list(members))
            payload.clear()
            members.clear()

        for key, item in missing:
            if key[0] != bucket:
                continue
            checkpoint()
            size = item['bytes']
            if not 0 <= size <= PACK_BYTES:
                raise ValueError('Files preview exceeds pack limit')
            padded = (size + 511) & ~511
            if len(payload) + padded > PACK_BYTES:
                finish()
            with Path(item['source']).open('rb') as reader:
                data = reader.read(size + 1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != key:
                raise ValueError('Files preview changed while packing')
            members.append((key, len(payload), size))
            payload.extend(data)
            payload.extend(bytes(padded - size))
        finish()
    temporary = manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps(layout, separators=(',', ':')), encoding='utf-8')
    os.replace(temporary, manifest)
    return packs, locations


def compile_files(root, package, cache, *, width=0, height=0, text_columns=24, target='photo4g-p98', checkpoint=lambda: None,
                  progress=lambda message: None, short_name=_short_name):
    if text_columns not in (20, 24):
        raise ValueError('Files text width must match a native layout')
    root, package, cache = Path(root).resolve(), Path(package).resolve(), Path(cache).resolve()
    if package.is_relative_to(root) or cache.is_relative_to(root):
        raise ValueError('Files index and preview cache must be staged on the computer')
    cache.mkdir(parents=True, exist_ok=True)
    from .music import EXTENSIONS
    from .notes import _display_recipe
    recipe = _display_recipe(target, 'linnet.system.files')
    records = [bytearray(RECORD)]
    records[0][32:37] = b'Files'
    records[0][160:164] = b'ROOT'
    struct.pack_into('<I', records[0], 0, 16)
    folders = deque([(root, 0)])
    previews, warnings, preview_rows = {}, [], []
    videos = _prepared_videos(root, warnings)
    while folders:
        folder, parent = folders.popleft()
        checkpoint()
        # Generated cache/backup contents remain accessible in Live folder;
        # indexing the index itself would grow a new snapshot on every run.
        if folder == root / '.LINNET' / 'FILES':
            struct.pack_into('<I', records[parent], 24, 2)
            continue
        _plain(folder, root)
        entries = []
        try:
            for entry in _directory_entries(folder):
                checkpoint()
                entries.append(entry)
        except PermissionError as error:
            warnings.append(dict(path=folder.relative_to(root).as_posix(), message=str(error)))
            struct.pack_into('<I', records[parent], 24, 2)
            continue
        entries.sort(key=lambda e: (not e[1], unicodedata.normalize('NFKC', e[0]).casefold(), e[0]))
        if len(records) + len(entries) > MAX_RECORDS:
            raise ValueError('Files index exceeds one million entries; use Live folder')
        struct.pack_into('<II', records[parent], 8, len(records), len(entries))
        for name, directory, info, alternate in entries:
            checkpoint()
            source = folder / name
            row = bytearray(RECORD)
            struct.pack_into('<II', row, 0, 16 if directory else 0, 0 if directory else info.st_size)
            native = 1 if source.suffix.lower() in EXTENSIONS else 2 if source.suffix.lower() in {'.mp4', '.m4v', '.mov', '.ipvf'} else 3 if source.suffix.lower() in {'.jpg', '.jpeg'} else 0
            struct.pack_into('<I', row, 28, native)
            label = _label(name, 127)
            row[32:32+len(label)] = label
            try:
                alias = _alias(alternate if alternate is not None and short_name is _short_name else short_name(source))
            except PermissionError:
                alias = b''
            # An unrepresentable short alias is shown, then resolved through
            # the live folder reader instead of pointing at another file.
            row[160:160+len(alias)] = alias
            if not alias:
                row[160:165] = b'LIVE!'
                struct.pack_into('<I', row, 24, 1)
            if directory:
                folders.append((source, len(records)))
            else:
                key = hashlib.sha256(source.relative_to(root).as_posix().encode('utf-8')).digest()
                preview = videos.get(key)
                if not preview and source.suffix.lower() in IMAGES | TEXT and not source.is_relative_to(root / '.LINNET'):
                    try:
                        preview = _preview(source, cache, width, height, text_columns, recipe, checkpoint, info, root)
                    except (OSError, ValueError) as error:
                        warnings.append(dict(path=source.relative_to(root).as_posix(), message=str(error)))
                if preview:
                    if preview['kind'] != 3:
                        previews[preview['sha256']] = preview
                        preview_rows.append((row, preview['sha256']))
                    struct.pack_into('<II', row, 16, preview['kind'], preview['bytes'])
                    path = ('/' + preview['path'].lstrip('/')).encode('ascii')
                    assert len(path) < 76
                    row[176:176+len(path)] = path
            records.append(row)
        progress(f'Indexing Files: {len(records)-1:,} entries')
    progress('Packing Files previews')
    packs, locations = _pack_previews(previews, cache, checkpoint)
    for row, key in preview_rows:
        path, offset = locations[key]
        struct.pack_into('<H', row, 174, offset // 512)
        row[176:252] = bytes(76)
        encoded = ('/' + path).encode('ascii')
        assert len(encoded) < 76
        row[176:176+len(encoded)] = encoded
    header = bytearray(512)
    struct.pack_into('<4s3I', header, 0, b'FILS', 2, len(records), RECORD)
    struct.pack_into('<I', header, 508, zlib.crc32(header[:508]))
    package.parent.mkdir(parents=True, exist_ok=True)
    with package.open('wb') as writer:
        writer.write(header)
        for row in records:
            struct.pack_into('<I', row, 252, zlib.crc32(row[:252]))
            writer.write(row)
        writer.flush()
        os.fsync(writer.fileno())
    return dict(bytes=package.stat().st_size, sha256=_hash(package), entries=len(records)-1,
                previews=packs, preview_count=len(previews), warnings=warnings)


def publish_files(package, candidate, *, disk_number, expected_disk_serial,
                  expected_volume_serial, expected_drive=None):
    from .publish import (inspect_target, _exclusive, _volume_guard, _copy_verified,
                          _publish_library, _same_target, _write_receipt)
    package = Path(package).resolve(strict=True)
    if package.stat().st_size != candidate['bytes'] or _hash(package) != candidate['sha256']:
        raise ValueError('Files package changed before publication')
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root'])
    if package.drive.casefold() == root.drive.casefold():
        raise ValueError('Files package must be staged on a different volume from the iPod')
    with _exclusive(identity):
        started_at = time.time()
        guard = lambda: _volume_guard(identity)
        active = root / '.LINNET' / 'FILES' / 'INDEX.FIL'
        guard()
        _plain(active, root)
        previous_hint = None
        if active.is_file():
            info = active.stat()
            if info.st_size == candidate['bytes'] and candidate['bytes'] <= MAX_FILE:
                digest = _hash(active, info.st_size)
                info = active.stat()
                previous_hint = dict(bytes=info.st_size, sha256=digest,
                                     stamp=(info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino))
        unchanged = previous_hint is not None and previous_hint['sha256'] == candidate['sha256']
        guard()
        needed = 0 if unchanged else candidate['bytes'] * 2 + 1024 * 1024
        missing_preview = False
        added = 0
        for item in candidate['previews']:
            destination = root / item['path']
            _plain(destination, root)
            if not destination.exists():
                missing_preview = True
                needed += item['bytes'] + 65536
        if unchanged and missing_preview:
            needed += 1024 * 1024
        if needed > identity['free_bytes']:
            raise ValueError('Not enough space for Files previews and index; previous index retained')
        for item in candidate['previews']:
            guard()
            destination = root / item['path']
            _plain(destination, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _plain(destination, root)
            added += _copy_verified(Path(item['source']), destination, item, root, guard)
        if unchanged:
            guard()
            _plain(package, Path(package.anchor))
            if _hash(package, candidate['bytes']) != candidate['sha256']:
                raise ValueError('Files package changed before reuse')
            _same_target(identity, inspect_target(disk_number, expected_disk_serial,
                                                   expected_volume_serial, expected_drive))
            guard()
            _plain(active, root)
            if _hash(active, candidate['bytes']) != candidate['sha256']:
                raise RuntimeError('Active Files index changed during publication')
            guard()
            receipt_path = package.parent / ('publish-files-' + uuid.uuid4().hex + '.json')
            receipt = dict(operation='publish-files', passed=True, phase='reused',
                           identity=identity, candidate_sha256=candidate['sha256'],
                           candidate_bytes=candidate['bytes'], package=str(active),
                           receipt=str(receipt_path), reused_index=True,
                           previews_added=added, entries=candidate['entries'],
                           previews=candidate.get('preview_count', len(candidate['previews'])),
                           preview_files=len(candidate['previews']), started_at=started_at,
                           finished_at=time.time(), elevation=False,
                           durability='Existing index and preview objects verified by complete hashes; index not rewritten')
            _write_receipt(receipt_path, receipt)
            return receipt
        return _publish_library(package, candidate, identity, root, disk_number,
            expected_disk_serial, expected_volume_serial, expected_drive,
            kind='files', label='Files index', filename='INDEX.FIL', max_file=MAX_FILE,
            previous_hint=previous_hint,
            summary=dict(entries=candidate['entries'], previews=candidate.get('preview_count', len(candidate['previews'])),
                         preview_files=len(candidate['previews'])))
