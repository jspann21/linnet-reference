import hashlib
import io
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

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


def original_cover(source) -> Image.Image:
    from PIL import ImageCms
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    with Image.open(source) as image:
        if image.width * image.height > 16_000_000:
            raise ValueError('cover dimensions exceed bound')
        profile = image.info.get('icc_profile')
        if image.getexif().get(274, 1) != 1:
            image = ImageOps.exif_transpose(image)
        if profile:
            try:
                image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                                 ImageCms.createProfile('sRGB'), outputMode='RGB')
            except (OSError, ValueError, ImageCms.PyCMSError):
                image = image.convert('RGB')
        return ImageOps.fit(image if image.mode == 'RGB' else image.convert('RGB'), (96, 96), method=Image.Resampling.LANCZOS)


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
        if (len(header) != 1024 or header[:4] != b'LCF2' or header[16:48] != database[64:96] or
                struct.unpack_from('<II', header, 8) != (ART_RECORD, 96) or
                struct.unpack_from('<I', header, 48)[0] != CATALOG or
                struct.unpack_from('<II', header, 56) != (24, 32) or
                zlib.crc32(header[512:]) != struct.unpack_from('<I', header, 64)[0] or
                zlib.crc32(header[:508]) != struct.unpack_from('<I', header, 508)[0]):
            raise ValueError('Invalid Cover Flow header or library identity')
        count, arts = struct.unpack_from('<I', header, 4)[0], struct.unpack_from('<I', header, 52)[0]
        if count > 100000 or arts > count or path.stat().st_size != 1024 + count * CATALOG + arts * ART_RECORD:
            raise ValueError('Invalid Cover Flow size')
        groups, groups_at = struct.unpack_from('<I', database, 20)[0], struct.unpack_from('<I', database, 36)[0]
        expected = [i for i in range(groups) if struct.unpack_from('<I', database, groups_at + i * 32)[0] == 2]
        if len(expected) != count:
            raise ValueError('Incomplete Cover Flow album catalog')
        for group in expected:
            record = reader.read(CATALOG)
            if (len(record) != CATALOG or struct.unpack_from('<II', record) != (group, struct.unpack_from('<I', database, groups_at + group * 32 + 16)[0]) or
                    struct.unpack_from('<I', record, 248)[0] >= arts or record[127] or record[247] or
                    zlib.crc32(record[256:], zlib.crc32(record[:252])) != struct.unpack_from('<I', record, 252)[0]):
                raise ValueError('Invalid Cover Flow catalog record')
        for _ in range(arts):
            record = reader.read(ART_RECORD)
            if len(record) != ART_RECORD or zlib.crc32(record[:12800]) != struct.unpack_from('<I', record, 12800)[0]:
                raise ValueError('Invalid Cover Flow artwork')


def prepare(database: bytes, root: Path, output: Path, *, originals: dict[int, Image.Image] | None = None) -> None:
    from .music import validate_database, TRACK
    from .publish import _bounded
    validate_database(database)
    width = TRACK
    _, _, _, groups, _, _, tracks_at, groups_at, members_at, _, pool, _, _, art_at = struct.unpack_from('<14I', database, 8)

    def text(offset):
        start = pool + offset
        return database[start:database.index(0, start)].decode('utf-8')

    palette = Image.new('P', (1, 1))
    colors = [(r * 255 // 7, g * 255 // 7, b * 255 // 3) for r in range(8) for g in range(8) for b in range(4)]
    palette.putpalette([v for color in colors for v in color])
    source_ids, image_ids, artwork, previews, catalog = {}, {}, [], [], []
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
            cover = Image.new('RGB', (96, 96), '#23374f')
            if originals is not None and art in originals:
                cover = originals[art]
            elif art != 0xffffffff:
                path = text(struct.unpack_from('<I', database, art_at + art * 32 + 8)[0])
                raw = _bounded(root / path.removeprefix('/.LINNET/'), 8192)
                pixels = struct.unpack('<4096H', raw)
                cover = Image.new('RGB', (64, 64))
                cover.putdata([((p >> 11) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31) for p in pixels])
                cover = cover.resize((96, 96), Image.Resampling.LANCZOS)
            else:
                draw = ImageDraw.Draw(cover)
                draw.ellipse((24, 24, 72, 72), outline='#819fbc', width=2)
                draw.ellipse((44, 44, 52, 52), fill='#819fbc')
            cover = cover.filter(ImageFilter.UnsharpMask(radius=.55, percent=35, threshold=3))
            accent = cover.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
            mean = sum(accent) / 3
            accent = tuple(max(0, min(255, round(mean + (c - mean) * 1.4))) for c in accent)
            tile = Image.new('RGB', (96, 128))
            tile.paste(cover)
            reflection = ImageOps.flip(cover).crop((0, 0, 96, 30))
            for y in range(30):
                row = reflection.crop((0, y, 96, y + 1))
                row = Image.blend(Image.new('RGB', row.size), row, .48 * (1 - y / 30) ** 2 * (1 + .8 * y / 30))
                row.putdata([tuple(min(255, round(c + accent[channel] * .18 *
                             (1 - ((x - 47.5) / 48) ** 2) ** 2 * (1 - y / 30) ** 2))
                             for channel, c in enumerate(pixel))
                             for x, pixel in enumerate(row.getdata())])
                tile.paste(row, (0, 98 + y))
            digest = hashlib.sha256(tile.tobytes()).digest()
            if digest not in image_ids:
                image_ids[digest] = len(artwork)
                indexed, rgb565 = _indexed_tile(tile)
                packed = bytearray(ART_RECORD)
                struct.pack_into('<256H', packed, 0, *rgb565)
                packed[512:12800] = indexed.transpose(Image.Transpose.TRANSPOSE).tobytes()
                struct.pack_into('<I', packed, 12800, zlib.crc32(packed[:12800]))
                artwork.append(packed)
                preview = tile.resize((24, 32), Image.Resampling.LANCZOS).quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
                previews.append(preview.transpose(Image.Transpose.TRANSPOSE).tobytes())
            source_ids[art] = image_ids[digest]
        art_id = source_ids[art]
        record = bytearray(CATALOG)
        struct.pack_into('<II', record, 0, group, count)
        for offset, value in ((8, text(name)), (128, artist)):
            encoded = value.encode('utf-8')[:119].decode('utf-8', 'ignore').encode('utf-8')
            record[offset:offset + len(encoded)] = encoded
        struct.pack_into('<I', record, 248, art_id)
        record[256:] = previews[art_id]
        struct.pack_into('<I', record, 252, zlib.crc32(record[256:], zlib.crc32(record[:252])))
        catalog.append(record)
    header = bytearray(1024)
    struct.pack_into('<4sIII', header, 0, b'LCF2', len(catalog), ART_RECORD, 96)
    header[16:48] = database[64:96]
    struct.pack_into('<IIII', header, 48, CATALOG, len(artwork), 24, 32)
    struct.pack_into('<256H', header, 512, *[(r >> 3) << 11 | (g >> 2) << 5 | (b >> 3) for r, g, b in colors])
    struct.pack_into('<I', header, 64, zlib.crc32(header[512:]))
    struct.pack_into('<I', header, 508, zlib.crc32(header[:508]))
    temporary = output.with_suffix('.TMP')
    with temporary.open('wb') as writer:
        writer.write(header)
        for record in catalog:
            writer.write(record)
        for record in artwork:
            writer.write(record)
    validate(temporary, database)
    temporary.replace(output)
