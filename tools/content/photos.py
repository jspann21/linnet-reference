"""Deterministic PIMG compiler and bounded, streaming package validator."""
from __future__ import annotations

from array import array
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import unicodedata
import zlib
from . import SourceError

HEADER, ALBUM, PHOTO, LEVEL, TILE = 512, 32, 64, 24, 8
MAX_FILE, MAX_PHOTOS, MAX_ALBUMS, MAX_TILES = 0x7fffffff, 65535, 4096, 1_000_000
MAX_STRINGS, MAX_LEVELS = 16 * 1024 * 1024, 6
THUMB, EDGE, NO_INDEX = 64, 32, 0xffffffff
DEVICE_PATH = '/.LINNET/PHOTOS/LIBRARY.PIM'
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
_GREEN_LOW = [(v & 28) << 3 for v in range(256)]
_BLUE_LOW = [v >> 3 for v in range(256)]
_RED_HIGH = [v & 248 for v in range(256)]
_GREEN_HIGH = [v >> 5 for v in range(256)]
FAT_PATH = re.compile(r'(?:/[A-Z0-9_]{1,8}(?:\.[A-Z0-9_]{1,3})?)+')
PHOTO_CACHE_BYTES = 512 * 1024 * 1024
PHOTO_CACHE_ENTRY_BYTES = 32 * 1024 * 1024


def _crc(data):
    return zlib.crc32(data) & 0xffffffff


def _record(data):
    return data + struct.pack('<I', _crc(data))


def _title(value):
    value = unicodedata.normalize('NFC', str(value)).strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('photo/album title is empty or contains control characters')
    if len(value.encode('utf-8')) > 191:
        raise ValueError('photo/album title exceeds 191 UTF-8 bytes')
    return value


def _rgb565(image):
    from PIL import Image, ImageChops

    # Pack little-endian bytes through Pillow's C channel operations. Each
    # addition combines disjoint bits, preserving exact truncation without
    # dithering, rescaling or a Python operation for every output pixel.
    red, green, blue = (image if image.mode == 'RGB' else image.convert('RGB')).split()
    low = ImageChops.add(green.point(_GREEN_LOW), blue.point(_BLUE_LOW))
    high = ImageChops.add(red.point(_RED_HIGH), green.point(_GREEN_HIGH))
    return Image.merge('LA', (low, high)).tobytes()


def _fit(width, height, bound_w, bound_h):
    scale = min(1.0, bound_w / width, bound_h / height)
    return max(1, int(width * scale)), max(1, int(height * scale))


def _sizes(width, height, max_dimension, viewport_width, viewport_height):
    largest = _fit(width, height, max_dimension, max_dimension)
    result = [_fit(width, height, viewport_width, viewport_height)]
    while result[-1] != largest:
        previous = result[-1]
        bound = min(2 * max(previous), max(largest))
        following = _fit(width, height, bound, bound)
        if following == previous:
            following = largest
        result.append(following)
        if len(result) > MAX_LEVELS:
            raise ValueError('photo pyramid exceeds six levels')
    return result


class _PhotoCache:
    """Bounded, disposable cache of one image's immutable RGB565 payload."""
    def __init__(self, directory, recipe):
        self.directory = Path(directory).resolve()
        self.recipe = recipe
        self.entries = {}
        self.bytes = 0
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob('*.bin'):
            if not re.fullmatch(r'[0-9a-f]{64}', path.stem):
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            self.entries[path] = (info.st_size, info.st_mtime_ns)
            self.bytes += info.st_size

    def key(self, path, name, title, fallback, checkpoint):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checkpoint()
                digest.update(chunk)
        identity = [str(path.resolve()), name, title, fallback,
                    digest.hexdigest(), self.recipe]
        return hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()

    def get(self, key, checkpoint):
        path = self.directory / (key + '.bin')
        try:
            if not path.is_file() or path.stat().st_size > PHOTO_CACHE_ENTRY_BYTES:
                return None
            with path.open('rb') as stream:
                length = int.from_bytes(stream.read(4), 'little')
                if not 0 < length <= 1024 * 1024:
                    return None
                metadata = json.loads(stream.read(length))
                payload = stream.read(PHOTO_CACHE_ENTRY_BYTES + 1)
            if (not isinstance(metadata, dict) or metadata.get('key') != key or
                    len(payload) > PHOTO_CACHE_ENTRY_BYTES or
                    len(payload) != metadata.get('bytes') or
                    hashlib.sha256(payload).hexdigest() != metadata.get('sha256')):
                return None
            if not _cached_photo_valid(metadata, payload, checkpoint):
                return None
            try:
                os.utime(path, None)
                self.entries[path] = (path.stat().st_size, path.stat().st_mtime_ns)
            except OSError:
                pass
            return metadata, payload[:THUMB*THUMB*2], payload[THUMB*THUMB*2:]
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            return None

    def put(self, key, metadata, thumb, tile_bytes):
        payload = thumb + tile_bytes
        metadata = dict(metadata, key=key, bytes=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest())
        header = json.dumps(metadata, separators=(',', ':')).encode()
        if len(header) + len(payload) + 4 > PHOTO_CACHE_ENTRY_BYTES:
            return
        path = self.directory / (key + '.bin')
        temporary = None
        try:
            fd, name = tempfile.mkstemp(prefix=key + '.', suffix='.tmp', dir=self.directory)
            temporary = Path(name)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(len(header).to_bytes(4, 'little'))
                stream.write(header)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            info = path.stat()
            previous = self.entries.get(path, (0, 0))[0]
            self.entries[path] = (info.st_size, info.st_mtime_ns)
            self.bytes += info.st_size - previous
            self._trim()
        except OSError:
            pass  # A host cache failure must not fail an otherwise valid PIMG.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _trim(self):
        if self.bytes <= PHOTO_CACHE_BYTES:
            return
        for path, (size, _) in sorted(self.entries.items(), key=lambda item: item[1][1]):
            try:
                path.unlink()
            except OSError:
                continue
            self.bytes -= size
            del self.entries[path]
            if self.bytes <= PHOTO_CACHE_BYTES:
                break


def _cached_photo_valid(meta, payload, checkpoint):
    if (type(meta.get('width')) is not int or type(meta.get('height')) is not int or
            not 1 <= meta['width'] <= 16384 or not 1 <= meta['height'] <= 16384 or
            type(meta.get('fallback_bytes')) is not int or type(meta.get('fallback_crc')) is not int or
            type(meta.get('orientation')) is not int or
            not isinstance(meta.get('levels'), list) or not 1 <= len(meta['levels']) <= MAX_LEVELS or
            not isinstance(meta.get('tile_crcs'), list)):
        return False
    counts = 0
    for level in meta['levels']:
        if (not isinstance(level, list) or len(level) != 5 or
                any(type(value) is not int or value < 1 for value in level)):
            return False
        width, height, tx, ty, count = level
        if tx != (width + EDGE - 1)//EDGE or ty != (height + EDGE - 1)//EDGE or count != tx*ty:
            return False
        counts += count
    if (counts != len(meta['tile_crcs']) or len(payload) != THUMB*THUMB*2 + counts*EDGE*EDGE*2 or
            _crc(payload[:THUMB*THUMB*2]) != meta.get('thumb_crc')):
        return False
    for index, expected in enumerate(meta['tile_crcs']):
        if index % 256 == 0:
            checkpoint()
        if type(expected) is not int or _crc(payload[THUMB*THUMB*2 + index*2048:
                                                   THUMB*THUMB*2 + (index+1)*2048]) != expected:
            return False
    return True


def _render_photo(path, fallback, max_dimension, viewport_width, viewport_height,
                  checkpoint):
    from PIL import Image, ImageOps

    fallback_bytes = fallback_crc = orientation = 0
    try:
        with Image.open(path) as original:
            width, height = original.size
            source_orientation = original.getexif().get(274, 1)
            if source_orientation not in range(1, 9):
                raise ValueError(f'invalid EXIF orientation: {path.name}')
            if not width or not height or max(width, height) > 16384 or width * height > 32_000_000:
                raise ValueError(f'image dimensions exceed the host decode bound: {path.name}')
            if getattr(original, 'n_frames', 1) != 1:
                raise ValueError(f'animated/multiframe image is unsupported: {path.name}')
            if fallback:
                fallback_bytes = path.stat().st_size
                if (original.format != 'JPEG' or original.mode not in ('RGB', 'L') or
                    original.info.get('progressive') or original.info.get('progression') or
                    fallback_bytes > 262144 or max(width, height) > 2048 or width * height > 4_000_000):
                    raise ValueError('fallback JPEG exceeds baseline format/size bounds')
                orientation = source_orientation
                fallback_crc = _crc(path.read_bytes())
            oriented = ImageOps.exif_transpose(original) if source_orientation != 1 else original
            if 'A' not in oriented.getbands() and 'transparency' not in oriented.info:
                if oriented.mode == 'RGB':
                    oriented.load()
                    image = oriented
                else:
                    image = oriented.convert('RGB')
            else:
                rgba = oriented.convert('RGBA')
                image = Image.new('RGB', rgba.size, (0, 0, 0))
                image.paste(rgba, mask=rgba.getchannel('A'))
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise SourceError(f'Could not prepare photo {path}: {error}', path) from error

    width, height = image.size
    thumb = Image.new('RGB', (THUMB, THUMB), (0, 0, 0))
    tw, th = _fit(width, height, THUMB, THUMB)
    thumb.paste(image.resize((tw, th), Image.Resampling.LANCZOS, reducing_gap=3.0),
                ((THUMB-tw)//2, (THUMB-th)//2))
    raw_thumb = _rgb565(thumb)
    local_levels, local_crcs, tile_bytes = [], [], bytearray()
    for lw, lh in _sizes(width, height, max_dimension, viewport_width, viewport_height):
        checkpoint()
        tx, ty = (lw+EDGE-1)//EDGE, (lh+EDGE-1)//EDGE
        resized = image if image.size == (lw, lh) else image.resize(
            (lw, lh), Image.Resampling.LANCZOS, reducing_gap=3.0)
        if (lw, lh) == (tx*EDGE, ty*EDGE):
            padded = resized
        else:
            padded = Image.new('RGB', (tx*EDGE, ty*EDGE), (0, 0, 0))
            padded.paste(resized)
        raw = _rgb565(padded)
        stride = tx * EDGE * 2
        tile_rows = struct.Struct(f'<{EDGE*2}s' + f'{stride-EDGE*2}x{EDGE*2}s' * (EDGE-1))
        for y in range(ty):
            for x in range(tx):
                start = y * EDGE * stride + x * EDGE * 2
                tile = b''.join(tile_rows.unpack_from(raw, start))
                tile_bytes.extend(tile)
                local_crcs.append(_crc(tile))
        local_levels.append([lw, lh, tx, ty, tx*ty])
    metadata = dict(width=width, height=height, fallback_bytes=fallback_bytes,
                    fallback_crc=fallback_crc, orientation=orientation,
                    thumb_crc=_crc(raw_thumb), levels=local_levels,
                    tile_crcs=local_crcs)
    return metadata, raw_thumb, bytes(tile_bytes)


def compile_photos(source, output, *, max_dimension=640, viewport_width=220,
                   viewport_height=156, fallback_paths=None, excluded=None, additional_sources=None,
                   progress=None, checkpoint=None, cache_dir=None):
    """Prepare a folder into one .pimg; optional mapping names existing JPEG copies.

    The default keeps zoom detail without a desktop-sized tile pyramid.
    fallback_paths maps source-relative filenames to their already-provisioned
    absolute FAT8.3 device paths. The compiler never copies or modifies originals.
    """
    from PIL import __version__ as pillow_version
    check = checkpoint or (lambda: None)
    source, output = Path(source).resolve(), Path(output).resolve()
    if (not source.is_dir() or type(viewport_width) is not int or
            type(viewport_height) is not int or type(max_dimension) is not int or not 1 <= viewport_width <= 1024 or
            not 1 <= viewport_height <= 1024 or viewport_width*viewport_height > 131072 or
            not max(viewport_width, viewport_height) <= max_dimension <= 2048):
        raise ValueError('invalid photo source, viewport, or maximum dimension')
    if output.suffix.lower() not in ('.pimg', '.pim'):
        raise ValueError('photo output must have .pimg or .pim extension')
    cache = None
    if cache_dir is not None:
        cache_root = Path(cache_dir).resolve()
        if cache_root == source or source in cache_root.parents:
            raise ValueError('photo cache must be outside the source folder')
        recipe = hashlib.sha256(json.dumps([
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), pillow_version,
            max_dimension, viewport_width, viewport_height, THUMB, EDGE],
            separators=(',', ':')).encode()).hexdigest()
        try:
            cache = _PhotoCache(cache_root, recipe)
        except OSError:
            pass
    excluded = {Path(value).as_posix().casefold() for value in (excluded or ())}
    paths = []
    for path in source.rglob('*'):
        relative = path.relative_to(source).as_posix().casefold()
        if path.suffix.lower() in EXTENSIONS and relative not in excluded and path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError('photo source links may not escape or alias the source tree')
            paths.append(path)
            if len(paths) > MAX_PHOTOS:
                raise ValueError('photo count exceeds 65535')
    names = {path: path.relative_to(source).as_posix() for path in paths}
    titles = {}
    for name, (preview, title) in (additional_sources or {}).items():
        if name.casefold() not in excluded:
            path = Path(preview)
            paths.append(path)
            names[path], titles[path] = name, title
    if len(paths) > MAX_PHOTOS:
        raise ValueError('photo count exceeds 65535')
    if not paths:
        raise ValueError('source contains no supported still images')
    paths.sort(key=lambda p: (names[p].casefold(), names[p]))
    fallback_paths = dict(fallback_paths or {})
    known = set(names.values())
    if set(fallback_paths) - known:
        raise ValueError('fallback mapping names a photo outside the selected source set')
    strings, string_index = bytearray(b'\0'), {'': (0, 0)}

    def string(value):
        if value not in string_index:
            raw = value.encode('utf-8')
            if len(strings) + len(raw) + 1 > MAX_STRINGS:
                raise ValueError('photo string pool exceeds 16 MiB')
            string_index[value] = (len(strings), len(raw))
            strings.extend(raw + b'\0')
        return string_index[value]

    photos, levels, tile_crcs = [], [], array('I')
    cache_reused = cache_rendered = 0
    with tempfile.TemporaryFile() as thumbs, tempfile.TemporaryFile() as tiles:
        for index, path in enumerate(paths):
            check()
            if progress:
                progress(dict(phase='photos', current=index, total=len(paths), file=str(path)))
            try:
                title = _title(titles.get(path, path.stem))
            except ValueError as error:
                raise SourceError(f'Could not prepare photo {path}: {error}', path) from error
            title_text = title
            title = string(title_text)
            fallback = fallback_paths.get(names[path], '')
            if fallback and (not FAT_PATH.fullmatch(fallback) or len(fallback) > 127 or
                             not fallback.endswith(('.JPG', '.JPEG'))):
                raise ValueError('fallback path must be an absolute uppercase FAT8.3 JPEG path')
            rendered = None
            key = None
            if cache is not None:
                before = path.stat()
                key = cache.key(path, names[path], title_text, fallback, check)
                after_hash = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after_hash.st_size, after_hash.st_mtime_ns):
                    raise SourceError(f'Photo changed while preparing: {path}', path)
                rendered = cache.get(key, check)
            if rendered is None:
                rendered = _render_photo(path, fallback, max_dimension,
                                         viewport_width, viewport_height, check)
                cache_rendered += 1
                if cache is not None:
                    after_render = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after_render.st_size, after_render.st_mtime_ns):
                        raise SourceError(f'Photo changed while preparing: {path}', path)
                    cache.put(key, *rendered)
            else:
                cache_reused += 1
                after_render = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after_render.st_size, after_render.st_mtime_ns):
                    raise SourceError(f'Photo changed while preparing: {path}', path)
            image_meta, raw_thumb, tile_bytes = rendered
            thumbs.write(raw_thumb)
            first_level = len(levels)
            local_offset = 0
            for lw, lh, tx, ty, count in image_meta['levels']:
                first_tile = len(tile_crcs)
                if first_tile + count > MAX_TILES or ((len(paths)*8192)+(first_tile+count)*2048) > MAX_FILE:
                    raise ValueError('photo tile payload exceeds package limits')
                levels.append((index, lw, lh, tx, ty, first_tile, count))
                tile_crcs.extend(image_meta['tile_crcs'][local_offset:local_offset+count])
                local_offset += count
            tiles.write(tile_bytes)
            photos.append((0, *title, *string(fallback), image_meta['width'], image_meta['height'],
                           first_level, len(levels)-first_level, 0, image_meta['thumb_crc'],
                           image_meta['fallback_bytes'], image_meta['fallback_crc'],
                           image_meta['orientation'], 0))
        album_records = [_record(struct.pack('<7I', *string(_title(source.name)),
                                             0, len(photos), NO_INDEX, 0, 0))]
        album_offset = HEADER
        photo_offset = album_offset + len(album_records)*ALBUM
        level_offset = photo_offset + len(photos)*PHOTO
        tile_offset = level_offset + len(levels)*LEVEL
        string_offset = tile_offset + len(tile_crcs)*TILE
        data_offset = (string_offset + len(strings) + 511) & ~511
        tile_base = data_offset + len(photos)*8192
        total = tile_base + len(tile_crcs)*2048
        if total > MAX_FILE:
            raise ValueError('PIMG exceeds the 2 GiB package bound')
        metadata = bytearray(b''.join(album_records))
        for index, photo in enumerate(photos):
            values = list(photo)
            values[9] = data_offset + index*8192
            metadata.extend(_record(struct.pack('<15I', *values)))
        for level in levels:
            metadata.extend(_record(struct.pack('<I4H2I', *level)))
        for index, crc in enumerate(tile_crcs):
            if index % 4096 == 0:
                check()
            metadata.extend(struct.pack('<II', tile_base+index*2048, crc))
        metadata.extend(strings)
        metadata.extend(bytes(data_offset - HEADER - len(metadata)))
        header = bytearray(HEADER)
        struct.pack_into('<4sHH14I4H', header, 0, b'PIMG', 0, HEADER, 0, total,
                         len(album_records), len(photos), len(levels), len(tile_crcs),
                         album_offset, photo_offset, level_offset, tile_offset,
                         string_offset, len(strings), _crc(metadata), data_offset,
                         THUMB, THUMB, EDGE, 1)
        struct.pack_into('<I', header, 508, _crc(header[:508]))
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=output.name+'.', suffix='.tmp', dir=output.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, 'wb') as result:
                result.write(header)
                result.write(metadata)
                for spool in (thumbs, tiles):
                    spool.seek(0)
                    while chunk := spool.read(1024*1024):
                        check()
                        result.write(chunk)
                result.flush()
                os.fsync(result.fileno())
            report = inspect(temporary, checkpoint=checkpoint)
            check()
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    report.update(output=str(output), source=str(source), device_path=DEVICE_PATH,
                  orientation_applied=True, originals_modified=False,
                  cache_reused=cache_reused, cache_rendered=cache_rendered)
    return report


def inspect(path, *, verify_payloads=True, checkpoint=None):
    """Validate every record and metadata range; optionally read all tile payloads."""
    check = checkpoint or (lambda: None)
    path = Path(path)
    size = path.stat().st_size
    if not HEADER <= size <= MAX_FILE:
        raise ValueError('invalid PIMG file size')
    hashed = hashlib.sha256() if verify_payloads else None
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        def read(offset, count):
            check()
            if offset < 0 or count < 0 or offset > size or count > size-offset:
                raise ValueError('PIMG read outside package bounds')
            stream.seek(offset)
            data = stream.read(count)
            if len(data) != count:
                raise ValueError('truncated PIMG')
            return data
        header = read(0, HEADER)
        if hashed is not None:
            hashed.update(header)
        if (header[:4] != b'PIMG' or struct.unpack_from('<HH', header, 4) != (0, HEADER) or
            _crc(header[:508]) != struct.unpack_from('<I', header, 508)[0] or any(header[72:508])):
            raise ValueError('invalid PIMG header identity/CRC/reserved bytes')
        flags, total, ac, pc, lc, tc, ao, po, lo, to, so, sb, mc, do = struct.unpack_from('<14I', header, 8)
        if (flags or total != size or not 1 <= ac <= MAX_ALBUMS or not 1 <= pc <= MAX_PHOTOS or
            not pc <= lc <= pc*MAX_LEVELS or not 1 <= tc <= MAX_TILES or not 1 <= sb <= MAX_STRINGS or
            struct.unpack_from('<4H', header, 64) != (THUMB, THUMB, EDGE, 1)):
            raise ValueError('invalid PIMG counts or pixel contract')
        if (ao != HEADER or po != ao+ac*ALBUM or lo != po+pc*PHOTO or to != lo+lc*LEVEL or
            so != to+tc*TILE or do != (so+sb+511)&~511 or size != do+pc*8192+tc*2048):
            raise ValueError('noncanonical PIMG section offsets')
        crc = 0
        for offset in range(HEADER, do, 1024*1024):
            block = read(offset, min(1024*1024, do-offset))
            crc = zlib.crc32(block, crc)
            if hashed is not None:
                hashed.update(block)
        if crc & 0xffffffff != mc or any(read(so+sb, do-so-sb)):
            raise ValueError('PIMG metadata CRC/alignment mismatch')
        pool = read(so, sb)
        if pool[0] != 0 or pool[-1] != 0:
            raise ValueError('PIMG string pool lacks empty sentinel')
        pool.decode('utf-8', errors='strict')
        def text(offset, count, *, source=False):
            if count > (127 if source else 191) or offset >= sb or count >= sb-offset:
                raise ValueError('PIMG string outside pool')
            if pool[offset+count] != 0 or (offset and pool[offset-1] != 0) or b'\0' in pool[offset:offset+count]:
                raise ValueError('PIMG string is not independently NUL delimited')
            value = pool[offset:offset+count].decode('ascii' if source else 'utf-8', errors='strict')
            if source:
                if (not value and offset != 0) or (value and (not FAT_PATH.fullmatch(value) or not value.endswith(('.JPG', '.JPEG')))):
                    raise ValueError('invalid PIMG fallback device path')
            else:
                if _title(value) != value:
                    raise ValueError('noncanonical PIMG title')
            return value
        def records(offset, count, length):
            # Each table retains at most 64 KiB while photo and level records
            # are consumed together, avoiding a seek for every small record.
            batch = 65536 // length
            for first in range(0, count, batch):
                block = read(offset + first*length, min(batch, count-first)*length)
                for start in range(0, len(block), length):
                    data = block[start:start+length]
                    if _crc(data[:-4]) != struct.unpack_from('<I', data, length-4)[0]:
                        raise ValueError('PIMG record CRC mismatch')
                    yield data
        intervals, count, album_titles = [], 0, []
        for index, data in enumerate(records(ao, ac, ALBUM)):
            title, length, first, photos, parent, r0, r1 = struct.unpack('<7I', data[:-4])
            if r0 or r1 or first != count or photos > pc-count or parent != (NO_INDEX if index == 0 else parent) or (index and parent >= index):
                raise ValueError('invalid PIMG album ordering/range')
            intervals.append((first, photos))
            album_titles.append(text(title, length))
            count += photos
        if count != pc:
            raise ValueError('PIMG albums do not cover the photo catalog')
        next_level = next_tile = 0
        level_records = records(lo, lc, LEVEL)
        thumb_crcs = []
        for index, data in enumerate(records(po, pc, PHOTO)):
            p = struct.unpack('<15I', data[:-4])
            album, title, length, source_offset, source_length, width, height, first, count, thumb, thumb_crc, fallback_bytes, fallback_crc, orientation, reserved = p
            if (album >= ac or not intervals[album][0] <= index < sum(intervals[album]) or reserved or
                not 1 <= width <= 16384 or not 1 <= height <= 16384 or width*height > 32_000_000 or
                first != next_level or not 1 <= count <= MAX_LEVELS or count > lc-first or thumb != do+index*8192):
                raise ValueError('invalid PIMG photo record')
            text(title, length)
            fallback = text(source_offset, source_length, source=True)
            if (not fallback and (fallback_bytes or fallback_crc or orientation)) or (fallback and (not 1 <= fallback_bytes <= 262144 or not 1 <= orientation <= 8 or max(width, height) > 2048 or width*height > 4_000_000)):
                raise ValueError('invalid PIMG fallback metadata')
            if verify_payloads:
                thumb_crcs.append(thumb_crc)
            previous = None
            for ordinal in range(count):
                photo, w, h, x, y, first_tile, tiles = struct.unpack('<I4H2I', next(level_records)[:-4])
                if (photo != index or not 1 <= w <= min(width, 2048) or not 1 <= h <= min(height, 2048) or
                    x != (w+31)//32 or y != (h+31)//32 or tiles != x*y or first_tile != next_tile or tiles > tc-first_tile or
                    (ordinal == 0 and w*h > 131072) or
                    (previous and (w < previous[0] or h < previous[1] or (w, h) == previous))):
                    raise ValueError('invalid PIMG level/tile range')
                previous = (w, h)
                next_tile += tiles
            next_level += count
        if next_level != lc or next_tile != tc:
            raise ValueError('PIMG levels do not cover tile index exactly')
        for first in range(0, len(thumb_crcs), 128):
            count = min(128, len(thumb_crcs)-first)
            payload = memoryview(read(do+first*8192, count*8192))
            hashed.update(payload)
            for ordinal in range(count):
                if _crc(payload[ordinal*8192:(ordinal+1)*8192]) != thumb_crcs[first+ordinal]:
                    raise ValueError('PIMG thumbnail CRC mismatch')
        # Group the index and contiguous payloads to avoid two seeks per tile.
        # Keep payload memory bounded to 1 MiB even for maximum-size libraries.
        for first in range(0, tc, 512):
            count = min(512, tc-first)
            records = read(to+first*TILE, count*TILE)
            base = do+pc*8192+first*2048
            payload = memoryview(read(base, count*2048)) if verify_payloads else None
            if hashed is not None:
                hashed.update(payload)
            for ordinal, (offset, crc) in enumerate(struct.iter_unpack('<II', records)):
                if offset != base+ordinal*2048:
                    raise ValueError('noncanonical PIMG tile payload offset')
                if verify_payloads and _crc(payload[ordinal*2048:(ordinal+1)*2048]) != crc:
                    raise ValueError('PIMG tile CRC mismatch')
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('PIMG changed during validation')
    if hashed is not None:
        digest = hashed.hexdigest()
    else:
        with path.open('rb') as stream:
            if checkpoint is None:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            else:
                hashed = hashlib.sha256()
                while chunk := stream.read(1024*1024):
                    check()
                    hashed.update(chunk)
                digest = hashed.hexdigest()
    return dict(format='PIMG', passed=True, photos=pc, albums=ac,
                levels=lc, tiles=tc, bytes=size, sha256=digest,
                album_titles=album_titles, payloads_verified=bool(verify_payloads))
