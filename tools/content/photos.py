"""Deterministic PIMG compiler and bounded, streaming package validator."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import unicodedata
import zlib

HEADER, ALBUM, PHOTO, LEVEL, TILE = 512, 32, 64, 24, 8
MAX_FILE, MAX_PHOTOS, MAX_ALBUMS, MAX_TILES = 0x7fffffff, 65535, 4096, 1_000_000
MAX_STRINGS, MAX_LEVELS = 16 * 1024 * 1024, 6
THUMB, EDGE, NO_INDEX = 64, 32, 0xffffffff
DEVICE_PATH = '/.LINNET/PHOTOS/LIBRARY.PIM'
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
FAT_PATH = re.compile(r'(?:/[A-Z0-9_]{1,8}(?:\.[A-Z0-9_]{1,3})?)+')


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
    red, green, blue = image.convert('RGB').split()
    low = ImageChops.add(green.point(lambda v: (v & 28) << 3),
                         blue.point(lambda v: v >> 3))
    high = ImageChops.add(red.point(lambda v: v & 248),
                          green.point(lambda v: v >> 5))
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


def compile_photos(source, output, *, max_dimension=640, viewport_width=220,
                   viewport_height=156, fallback_paths=None, excluded=None):
    """Prepare a folder into one .pimg; optional mapping names existing JPEG copies.

    The default keeps zoom detail without a desktop-sized tile pyramid.
    fallback_paths maps source-relative filenames to their already-provisioned
    absolute FAT8.3 device paths. The compiler never copies or modifies originals.
    """
    from PIL import Image, ImageOps
    source, output = Path(source).resolve(), Path(output).resolve()
    minimum = max(viewport_width, viewport_height)
    if (not source.is_dir() or type(viewport_width) is not int or
            type(viewport_height) is not int or not 1 <= viewport_width <= 1024 or
            not 1 <= viewport_height <= 1024 or viewport_width*viewport_height > 131072 or
            not minimum <= max_dimension <= 2048):
        raise ValueError('invalid photo source, viewport, or maximum dimension')
    if output.suffix.lower() not in ('.pimg', '.pim'):
        raise ValueError('photo output must have .pimg or .pim extension')
    excluded = {Path(value).as_posix().casefold() for value in (excluded or ())}
    paths = []
    for path in source.rglob('*'):
        relative = path.relative_to(source).as_posix().casefold()
        if path.is_file() and path.suffix.lower() in EXTENSIONS and relative not in excluded:
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError('photo source links may not escape or alias the source tree')
            paths.append(path)
            if len(paths) > MAX_PHOTOS:
                raise ValueError('photo count exceeds 65535')
    if not paths:
        raise ValueError('source contains no supported still images')
    paths.sort(key=lambda p: (p.relative_to(source).as_posix().casefold(),
                             p.relative_to(source).as_posix()))
    fallback_paths = dict(fallback_paths or {})
    known = {p.relative_to(source).as_posix() for p in paths}
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

    photos, levels, tile_crcs = [], [], []
    with tempfile.TemporaryFile() as thumbs, tempfile.TemporaryFile() as tiles:
        for index, path in enumerate(paths):
            title = string(_title(path.stem))
            fallback = fallback_paths.get(path.relative_to(source).as_posix(), '')
            fallback_bytes = fallback_crc = orientation = 0
            if fallback and (not FAT_PATH.fullmatch(fallback) or len(fallback) > 127 or
                             not fallback.endswith(('.JPG', '.JPEG'))):
                raise ValueError('fallback path must be an absolute uppercase FAT8.3 JPEG path')
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
                        if orientation not in range(1, 9):
                            raise ValueError('invalid EXIF fallback orientation')
                        fallback_crc = _crc(path.read_bytes())
                    oriented = ImageOps.exif_transpose(original)
                    if 'A' not in oriented.getbands() and 'transparency' not in oriented.info:
                        image = oriented.convert('RGB')
                    else:
                        rgba = oriented.convert('RGBA')
                        image = Image.new('RGB', rgba.size, (0, 0, 0))
                        image.paste(rgba, mask=rgba.getchannel('A'))
            except (OSError, ValueError, SyntaxError) as error:
                raise ValueError(f'Could not prepare photo {path}: {error}') from error
            width, height = image.size
            thumb = Image.new('RGB', (THUMB, THUMB), (0, 0, 0))
            tw, th = _fit(width, height, THUMB, THUMB)
            thumb.paste(image.resize((tw, th), Image.Resampling.LANCZOS, reducing_gap=3.0), ((THUMB-tw)//2, (THUMB-th)//2))
            raw_thumb = _rgb565(thumb)
            thumbs.write(raw_thumb)
            first_level = len(levels)
            for lw, lh in _sizes(width, height, max_dimension, viewport_width, viewport_height):
                tx, ty = (lw+EDGE-1)//EDGE, (lh+EDGE-1)//EDGE
                first_tile, count = len(tile_crcs), tx * ty
                if first_tile + count > MAX_TILES or ((len(paths)*8192)+(first_tile+count)*2048) > MAX_FILE:
                    raise ValueError('photo tile payload exceeds package limits')
                padded = Image.new('RGB', (tx*EDGE, ty*EDGE), (0, 0, 0))
                padded.paste(image.resize((lw, lh), Image.Resampling.LANCZOS, reducing_gap=3.0))
                raw = _rgb565(padded)
                stride = tx * EDGE * 2
                for y in range(ty):
                    for x in range(tx):
                        start = y * EDGE * stride + x * EDGE * 2
                        tile = b''.join(raw[start + row*stride:start + row*stride + EDGE*2] for row in range(EDGE))
                        tiles.write(tile)
                        tile_crcs.append(_crc(tile))
                levels.append((index, lw, lh, tx, ty, first_tile, count))
            photos.append((0, *title, *string(fallback), width, height, first_level,
                           len(levels)-first_level, 0, _crc(raw_thumb), fallback_bytes,
                           fallback_crc, orientation, 0))
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
                    shutil.copyfileobj(spool, result, 1024*1024)
                result.flush()
                os.fsync(result.fileno())
            report = inspect(temporary)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    report.update(output=str(output), source=str(source), device_path=DEVICE_PATH,
                  orientation_applied=True, originals_modified=False)
    return report


def inspect(path, *, verify_payloads=True):
    """Validate every record and metadata range; optionally read all tile payloads."""
    path = Path(path)
    size = path.stat().st_size
    if not HEADER <= size <= MAX_FILE:
        raise ValueError('invalid PIMG file size')
    with path.open('rb') as stream:
        def read(offset, count):
            if offset < 0 or count < 0 or offset > size or count > size-offset:
                raise ValueError('PIMG read outside package bounds')
            stream.seek(offset)
            data = stream.read(count)
            if len(data) != count:
                raise ValueError('truncated PIMG')
            return data
        header = read(0, HEADER)
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
            crc = zlib.crc32(read(offset, min(1024*1024, do-offset)), crc)
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
            for ordinal, (offset, crc) in enumerate(struct.iter_unpack('<II', records)):
                if offset != base+ordinal*2048:
                    raise ValueError('noncanonical PIMG tile payload offset')
                if verify_payloads and _crc(payload[ordinal*2048:(ordinal+1)*2048]) != crc:
                    raise ValueError('PIMG tile CRC mismatch')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(format='PIMG', passed=True, photos=pc, albums=ac,
                levels=lc, tiles=tc, bytes=size, sha256=digest,
                album_titles=album_titles, payloads_verified=bool(verify_payloads))
