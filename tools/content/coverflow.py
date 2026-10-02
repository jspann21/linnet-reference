import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps, __version__ as pillow_version

RECORD = 25088


def _validate_legacy(path: Path, database: bytes) -> None:
    with path.open('rb') as reader:
        header = reader.read(512)
        if (len(header) != 512 or header[:4] != b'LCF1' or
                header[16:48] != database[64:96] or struct.unpack_from('<I', header, 48)[0] > 1 or
                struct.unpack_from('<II', header, 8) != (RECORD, 96) or
                zlib.crc32(header[:508]) != struct.unpack_from('<I', header, 508)[0]):
            raise ValueError('Invalid Cover Flow header or library identity')
        count = struct.unpack_from('<I', header, 4)[0]
        if count > 100000 or path.stat().st_size != 512 + count * RECORD:
            raise ValueError('Invalid Cover Flow size')
        groups, groups_at = struct.unpack_from('<I', database, 20)[0], struct.unpack_from('<I', database, 36)[0]
        for _ in range(count):
            record = reader.read(RECORD)
            if len(record) != RECORD:
                raise ValueError('Truncated Cover Flow album record')
            group, tracks = struct.unpack_from('<II', record)
            if (group >= groups or struct.unpack_from('<I', database, groups_at + group * 32)[0] != 2 or
                    tracks != struct.unpack_from('<I', database, groups_at + group * 32 + 16)[0] or
                    record[135] or record[263] or
                    zlib.crc32(record[512:], zlib.crc32(record[:508])) != struct.unpack_from('<I', record, 508)[0]):
                raise ValueError('Invalid Cover Flow album record')


CATALOG = 1024
ART_RECORD = 13312
NATIVE_SIDE = 130
NATIVE_HEIGHT = 174
NATIVE_RECORD = 23552


def _layout(header):
    native = header[:4] == b'LCFN'
    return (NATIVE_SIDE, NATIVE_HEIGHT, NATIVE_RECORD) if native else (96, 128, ART_RECORD)


def _row_major_art(record: bytes | bytearray, side=96, height=128) -> bytearray:
    packed = bytearray(record)
    end = 512 + side * height
    packed[512:end] = Image.frombytes('P', (height, side), packed[512:end]).transpose(
        Image.Transpose.TRANSPOSE).tobytes()
    struct.pack_into('<I', packed, end, zlib.crc32(packed[:end]))
    return packed


def _original_from_rgb(image: Image.Image, side=96) -> Image.Image:
    return ImageOps.fit(image, (side, side), method=Image.Resampling.LANCZOS)


def original_cover(source) -> Image.Image:
    from .music import _cover_normalized
    if isinstance(source, Image.Image):
        opened = nullcontext(source)
    else:
        opened = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
    with opened as image:
        if image.width * image.height > 16_000_000:
            raise ValueError('cover dimensions exceed bound')
        return _original_from_rgb(_cover_normalized(image))


def _indexed_tile(tile: Image.Image) -> tuple[Image.Image, list[int]]:
    palette = tile.quantize(colors=256, method=Image.Quantize.MEDIANCUT, kmeans=3)
    rgb = palette.getpalette()
    rgb += [0] * (768 - len(rgb))
    colors = [((rgb[i] * 31 + 127) // 255) << 11 |
              ((rgb[i+1] * 63 + 127) // 255) << 5 |
              ((rgb[i+2] * 31 + 127) // 255) for i in range(0, 768, 3)]
    # Diffuse against the actual LCD colors, including RGB565 rounding error.
    palette.putpalette([c for p in colors for c in
                        (((p >> 11) * 255 + 15) // 31,
                         (((p >> 5) & 63) * 255 + 31) // 63,
                         ((p & 31) * 255 + 15) // 31)])
    return tile.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG), colors


def validate(path: Path, database: bytes) -> None:
    with path.open('rb') as reader:
        header = reader.read(1024)
        if header[:4] == b'LCF1':
            return _validate_legacy(path, database)
        side, height, art_record = _layout(header)
        mapped = header[:4] == b'LCFN' and struct.unpack_from('<I', header, 68)[0] == 1
        end = 512 + side * height
        if (len(header) != 1024 or header[:4] not in (b'LCF2', b'LCFR', b'LCFN') or header[16:48] != database[64:96] or
                struct.unpack_from('<II', header, 8) != (art_record, side) or
                struct.unpack_from('<I', header, 48)[0] != CATALOG or
                struct.unpack_from('<II', header, 56) != (24, 32) or
                (header[:4] == b'LCFN' and struct.unpack_from('<I', header, 68)[0] not in (0, 1)) or
                zlib.crc32(header[512:]) != struct.unpack_from('<I', header, 64)[0] or
                zlib.crc32(header[:508]) != struct.unpack_from('<I', header, 508)[0]):
            raise ValueError('Invalid Cover Flow header or library identity')
        count, arts = struct.unpack_from('<I', header, 4)[0], struct.unpack_from('<I', header, 52)[0]
        if count > 100000 or arts > count or path.stat().st_size != 1024 + count * CATALOG + arts * art_record:
            raise ValueError('Invalid Cover Flow size')
        groups, groups_at = struct.unpack_from('<I', database, 20)[0], struct.unpack_from('<I', database, 36)[0]
        expected = [i for i in range(groups) if struct.unpack_from('<I', database, groups_at + i * 32)[0] == 2]
        if len(expected) != count:
            raise ValueError('Incomplete Cover Flow album catalog')
        for group in expected:
            record = reader.read(CATALOG)
            if (len(record) != CATALOG or struct.unpack_from('<II', record) != (group, struct.unpack_from('<I', database, groups_at + group * 32 + 16)[0]) or
                    struct.unpack_from('<I', record, 248)[0] >= arts or record[127] or record[239 if mapped else 247] or
                    zlib.crc32(record[256:], zlib.crc32(record[:252])) != struct.unpack_from('<I', record, 252)[0]):
                raise ValueError('Invalid Cover Flow catalog record')
        for _ in range(arts):
            record = reader.read(art_record)
            if len(record) != art_record or zlib.crc32(record[:end]) != struct.unpack_from('<I', record, end)[0]:
                raise ValueError('Invalid Cover Flow artwork')


def remove_tracks(source: Path, before: bytes, after: bytes, output: Path) -> None:
    """Remap the album catalog after deletion, reusing prepared artwork bytes."""
    from .music import validate_database
    validate_database(before)
    validate_database(after)
    validate(source, before)

    def albums(database):
        count, start = struct.unpack_from('<I', database, 20)[0], struct.unpack_from('<I', database, 36)[0]
        return {struct.unpack_from('<Q', database, start + i * 32 + 24)[0]:
                (i, struct.unpack_from('<I', database, start + i * 32 + 16)[0])
                for i in range(count) if struct.unpack_from('<I', database, start + i * 32)[0] == 2}

    old, new = albums(before), albums(after)
    if not new.keys() <= old.keys():
        raise ValueError('Cover Flow deletion introduced new albums')
    mapping = {old[key][0]: value for key, value in new.items()}
    created = False
    try:
        with source.open('rb') as reader, output.open('xb') as writer:
            created = True
            legacy = reader.read(4) == b'LCF1'
            reader.seek(0)
            header = bytearray(reader.read(512 if legacy else 1024))
            _, _, art_record = _layout(header)
            count = struct.unpack_from('<I', header, 4)[0]
            records, art_ids = [], {}
            for _ in range(count):
                row = bytearray(reader.read(RECORD if legacy else CATALOG))
                group = struct.unpack_from('<I', row)[0]
                if group not in mapping:
                    continue
                struct.pack_into('<II', row, 0, *mapping[group])
                if not legacy:
                    art = struct.unpack_from('<I', row, 248)[0]
                    art_ids.setdefault(art, len(art_ids))
                    struct.pack_into('<I', row, 248, art_ids[art])
                crc_at = 508 if legacy else 252
                struct.pack_into('<I', row, crc_at,
                                 zlib.crc32(row[crc_at + 4:], zlib.crc32(row[:crc_at])))
                records.append(row)
            records.sort(key=lambda row: struct.unpack_from('<I', row)[0])
            header[16:48] = after[64:96]
            struct.pack_into('<I', header, 4, len(records))
            if not legacy:
                struct.pack_into('<I', header, 52, len(art_ids))
            struct.pack_into('<I', header, 508, zlib.crc32(header[:508]))
            writer.write(header)
            for row in records:
                writer.write(row)
            for art in art_ids:
                reader.seek(1024 + count * CATALOG + art * art_record)
                writer.write(reader.read(art_record))
        validate(output, after)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise


def prepare(database: bytes, root: Path, output: Path, *, originals: dict[int, Image.Image] | None = None,
            cache=None, bypass_cache: bool = False, row_major: bool = False) -> None:
    from .music import validate_database, TRACK
    from .publish import _bounded
    validate_database(database)
    side, height, art_record = (NATIVE_SIDE, NATIVE_HEIGHT, NATIVE_RECORD) if row_major else (96, 128, ART_RECORD)
    width = TRACK
    _, _, _, groups, _, _, tracks_at, groups_at, members_at, _, pool, _, _, art_at = struct.unpack_from('<14I', database, 8)

    def text(offset):
        start = pool + offset
        return database[start:database.index(0, start)].decode('utf-8')

    palette = Image.new('P', (1, 1))
    colors = [(r * 255 // 7, g * 255 // 7, b * 255 // 3) for r in range(8) for g in range(8) for b in range(4)]
    palette.putpalette([v for color in colors for v in color])
    reflection_shape = [(1 - ((x - (side - 1) / 2) / (side / 2)) ** 2) ** 2 for x in range(side)]
    source_ids, image_ids, artwork, previews, catalog = {}, {}, [], [], []
    catalog_rows, pending, workers = [], [], None

    def finish_tile():
        art_id, key, future = pending.pop(0)
        packed, preview = future.result()
        artwork[art_id], previews[art_id] = packed, preview
        if cache is not None:
            cache.coverflow_put(key, bytes(packed) + preview)

    try:
        for group in range(groups):
            kind, name, parent, first, count = struct.unpack_from('<5I', database, groups_at + group * 32)
            if kind != 2:
                continue
            artist = text(struct.unpack_from('<I', database, groups_at + parent * 32 + 4)[0])
            # Prefer a member with a cover when the first track has no artwork.
            art = 0xffffffff
            for member in range(first, first + count):
                track = struct.unpack_from('<I', database, members_at + member * 4)[0]
                art = struct.unpack_from('<I', database, tracks_at + track * width + 88)[0]
                if art != 0xffffffff:
                    break
            if art not in source_ids:
                cover = Image.new('RGB', (side, side), '#23374f')
                if originals is not None and art in originals:
                    cover = originals[art]
                elif art != 0xffffffff:
                    path_offset, source_side, _, _, art_bytes = struct.unpack_from('<IHHII', database, art_at + art * 32 + 8)
                    path = text(path_offset)
                    raw = _bounded(root / path.lstrip('/'), art_bytes)
                    pixels = struct.unpack(f'<{source_side * source_side}H', raw[:source_side * source_side * 2])
                    cover = Image.new('RGB', (source_side, source_side))
                    cover.putdata([((p >> 11) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31) for p in pixels])
                    cover = cover.resize((side, side), Image.Resampling.LANCZOS)
                else:
                    draw = ImageDraw.Draw(cover)
                    draw.ellipse((side//4, side//4, side*3//4, side*3//4), outline='#819fbc', width=2)
                    draw.ellipse((side*11//24, side*11//24, side*13//24, side*13//24), fill='#819fbc')
                # Include the recipe and Pillow version; never reuse art by timestamp.
                key = hashlib.sha256(b'LCF-tile-2\0' + struct.pack('<II', side, height) + pillow_version.encode() + b'\0' +
                                     cover.mode.encode() + struct.pack('<II', *cover.size) + cover.tobytes()).digest()
                saved = cache.coverflow_get(key, art_record + 768) if cache is not None and not bypass_cache else None
                if key in image_ids:
                    source_ids[art] = image_ids[key]
                elif saved is not None:
                    source_ids[art] = image_ids[key] = len(artwork)
                    artwork.append(saved[:art_record])
                    previews.append(saved[art_record:])
                else:
                    source_ids[art] = image_ids[key] = len(artwork)
                    artwork.append(None)
                    previews.append(None)
                    if workers is None:
                        workers = ThreadPoolExecutor(max_workers=4)
                    pending.append((source_ids[art], key,
                                    workers.submit(_prepare_tile, cover, palette.copy(), reflection_shape, height, art_record)))
                    if len(pending) >= 4:
                        finish_tile()
            art_id = source_ids[art]
            catalog_rows.append((group, count, name, artist, art_id, art))
        while pending:
            finish_tile()
    finally:
        if workers is not None:
            workers.shutdown(wait=True, cancel_futures=True)
    for group, count, name, artist, art_id, source_art in catalog_rows:
        record = bytearray(CATALOG)
        struct.pack_into('<II', record, 0, group, count)
        for offset, value in ((8, text(name)), (128, artist)):
            maximum = 111 if row_major and offset == 128 else 119
            encoded = value.encode('utf-8')[:maximum].decode('utf-8', 'ignore').encode('utf-8')
            record[offset:offset + len(encoded)] = encoded
        if row_major and source_art != 0xffffffff:
            source = art_at + source_art * 32
            struct.pack_into('<II', record, 240, struct.unpack_from('<I', database, source)[0],
                             struct.unpack_from('<I', database, source + 24)[0])
        struct.pack_into('<I', record, 248, art_id)
        record[256:] = previews[art_id]
        struct.pack_into('<I', record, 252, zlib.crc32(record[256:], zlib.crc32(record[:252])))
        catalog.append(record)
    header = bytearray(1024)
    struct.pack_into('<4sIII', header, 0, b'LCFN' if row_major else b'LCF2', len(catalog), art_record, side)
    header[16:48] = database[64:96]
    struct.pack_into('<IIII', header, 48, CATALOG, len(artwork), 24, 32)
    if row_major:
        struct.pack_into('<I', header, 68, 1)
    struct.pack_into('<256H', header, 512, *[(r >> 3) << 11 | (g >> 2) << 5 | (b >> 3) for r, g, b in colors])
    struct.pack_into('<I', header, 64, zlib.crc32(header[512:]))
    struct.pack_into('<I', header, 508, zlib.crc32(header[:508]))
    temporary = output.with_suffix('.TMP')
    with temporary.open('wb') as writer:
        writer.write(header)
        for record in catalog:
            writer.write(record)
        for record in artwork:
            writer.write(_row_major_art(record, side, height) if row_major else record)
    validate(temporary, database)
    temporary.replace(output)


def _prepare_tile(cover, palette, reflection_shape, height=128, art_record=ART_RECORD):
    side = cover.width
    cover = cover.filter(ImageFilter.UnsharpMask(radius=.55, percent=35, threshold=3))
    accent = cover.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    mean = sum(accent) / 3
    accent = tuple(max(0, min(255, round(mean + (c - mean) * 1.4))) for c in accent)
    tile = Image.new('RGB', (side, height))
    tile.paste(cover)
    gap = max(2, round(side / 48))
    reflection_height = height - side - gap
    reflection = ImageOps.flip(cover).crop((0, 0, side, reflection_height))
    reflection_accent = [c * .18 for c in accent]
    for y in range(reflection_height):
        fade = (1 - y / reflection_height) ** 2
        row = reflection.crop((0, y, side, y + 1))
        row = Image.blend(Image.new('RGB', row.size), row, .48 * fade * (1 + .8 * y / reflection_height))
        row.putdata([tuple(min(255, round(c + reflection_accent[channel] * reflection_shape[x] * fade))
                     for channel, c in enumerate(pixel))
                     for x, pixel in enumerate(row.getdata())])
        tile.paste(row, (0, side + gap + y))
    indexed, rgb565 = _indexed_tile(tile)
    packed = bytearray(art_record)
    struct.pack_into('<256H', packed, 0, *rgb565)
    end = 512 + side * height
    packed[512:end] = indexed.transpose(Image.Transpose.TRANSPOSE).tobytes()
    struct.pack_into('<I', packed, end, zlib.crc32(packed[:end]))
    preview = tile.resize((24, 32), Image.Resampling.LANCZOS).quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
    return packed, preview.transpose(Image.Transpose.TRANSPOSE).tobytes()
