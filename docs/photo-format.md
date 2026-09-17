# PIMG photo package

PIMG is Linnet's prepared photo library. Host files use `.pimg`; the initial
device package is `/.LINNET/PHOTOS/LIBRARY.PIM`. All integer fields are unsigned
little-endian. RGB565 pixels are little-endian words: red bits15..11, green10..5,
blue4..0. EXIF orientation is applied before creating prepared pixels.

The package has one paged album/photo catalog, per-photo resolution levels, a
direct tile index, a UTF-8 string pool, then raw thumbnail and tile payloads.
The device does not need to retain the complete catalog or tile index.

## Header — 512 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | char[4] | `PIMG` |
| 4 | u16 | Reserved zero |
| 6 | u16 | Header size512 |
| 8 | u32 | Flags0 |
| 12 | u32 | Exact file bytes |
| 16,20,24,28 | u32 each | Album, photo, level, tile counts |
| 32,36,40,44 | u32 each | Album, photo, level, tile table offsets |
| 48,52 | u32 each | String pool offset and bytes |
| 56 | u32 | Metadata CRC32 |
| 60 | u32 | Payload start, aligned512 |
| 64,66 | u16 each | Thumbnail width64 and height64 |
| 68 | u16 | Tile edge32 |
| 70 | u16 | Pixel format1: raw RGB565 LE |
| 72..507 | bytes | Reserved zero |
| 508 | u32 | CRC32 of bytes0..507 |

Every CRC uses CRC-32/ISO-HDLC, as returned by `zlib.crc32`, with no external
initial/final transformation. The metadata CRC covers bytes512 up to the payload
start, excluding payloads and including zero alignment padding.

Tables are contiguous in the listed order, beginning at byte512. Their record
sizes are32,64,24,8 bytes respectively. The string pool follows the tile table
immediately; zero padding reaches the next512-byte boundary. Counts are bounded
to4096 albums,65535 photos,1..6 levels per photo and1,000,000 tiles. The string
pool is1..16MiB. Exact file size is at most `0x7fffffff` bytes. Arithmetic must
be widened or checked before multiplication/addition.

## Album record — 32 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0,4 | u32 each | Title string offset and byte length |
| 8,12 | u32 each | First photo and photo count |
| 16 | u32 | Parent album index; root uses `0xffffffff` |
| 20..27 | bytes | Reserved zero |
| 28 | u32 | CRC32 of preceding28 bytes |

Album0 is the source root. Every other parent precedes its child. Each album's
photos occupy one contiguous interval. Intervals in album order cover all photos
exactly once; an empty ancestor has a zero-length interval at the running index.

## Photo record — 64 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u32 | Album index |
| 4,8 | u32 each | Title string offset and byte length |
| 12,16 | u32 each | Optional original JPEG device path offset and length |
| 20,24 | u32 each | Oriented original width and height |
| 28,32 | u32 each | First level and level count |
| 36,40 | u32 each | Thumbnail absolute offset and CRC32 |
| 44,48 | u32 each | Optional JPEG file bytes and complete-file CRC32 |
| 52 | u32 | Optional JPEG EXIF orientation1..8 |
| 56 | u32 | Reserved zero |
| 60 | u32 | CRC32 of preceding60 bytes |

Original dimensions are1..16384 with at most32,000,000 pixels. Levels occupy
contiguous intervals in photo order. All thumbnail payloads precede all tiles:
thumbnail `i` starts at `payload_start + i*8192` and contains a64×64 RGB565 image.
The compiler fits the oriented image inside the thumbnail and centers it on black.

Empty JPEG paths use string offset0,length0 and zero fields44..52. A nonempty
path is uppercase ASCII, absolute, composed of FAT8.3 components, ending in `.JPG`.
It is at most127 bytes. The referenced JPEG is1..262144 bytes, baseline mono/RGB,
at most2048×2048 and4,000,000 pixels. Its oriented dimensions match fields20/24.
Before fallback decode, verify exact file length and CRC; apply field52 orientation
to JPEG output. Progressive, CMYK, multiframe or unsupported JPEG data must fail
boundedly. Prepared pixels do not receive this orientation a second time.
The compiler emits fallback references only from an explicit mapping and does not
provision those original files automatically.

## Level record — 24 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u32 | Photo index |
| 4,6 | u16 each | Pixel width and height |
| 8,10 | u16 each | Tile columns and rows |
| 12,16 | u32 each | First tile and tile count |
| 20 | u32 | CRC32 of preceding20 bytes |

Each dimension is1..2048 and no greater than its oriented original. Tile counts
are `ceil(width/32)` by `ceil(height/32)`. Level intervals cover the tile index
exactly once in photo/level order. Dimensions increase monotonically; duplicate
levels are invalid. Level0 fits the target's configured photo viewport and is
bounded to 131,072 pixels. Successive levels approximately double, without
upscaling, until the original or selected maximum long edge (default2048) is
reached. Small originals may have one level.

## Tile record — 8 bytes

Each record contains an absolute u32 payload offset followed by its u32 CRC.
All payloads are exactly2048 bytes:32 rows of32 RGB565 pixels. Tiles are ordered
row-major within each level. Edge padding is black. Tile `i` starts at
`payload_start + photo_count*8192 + i*2048`. The file ends immediately after the
last tile. There are no overlapping, compressed, sparse or indirect payloads.
The reader requests only visible tiles at the selected prepared level.

## Strings and validation

String offsets are relative to the pool. The pool begins with one NUL sentinel.
Lengths exclude the terminating NUL. A nonempty string begins immediately after a
NUL, contains no NUL, and ends with one. Titles are nonempty NFC UTF-8, at most191
bytes, with no ASCII controls; source paths are optional and follow the narrower
rules above. The compiler deduplicates equal strings.

Header and metadata CRCs, fixed bounds, canonical offsets, per-record CRCs,
relationships and strings must validate before catalog use. Each thumbnail/tile
CRC must validate before its pixels enter the cache or display. Corrupt data
must produce an error without changing previously valid displayed pixels.
`tools.content.photos.inspect` verifies all these relationships and, by default,
every payload CRC using bounded reads. Host compilation uses Pillow, Lanczos
prescaling, black compositing for transparency and exact RGB565 quantization.
It writes and verifies a temporary package before replacing its output.

## Publishing

`tools.content.publish_photos.publish_photos(package, disk_number=...,
expected_disk_serial=..., expected_volume_serial=..., expected_drive=...)`
uses ordinary Windows Disk Mode filesystem access. It validates the complete
host package before any device mutation and checks the explicit Apple iPod
disk/partition/volume identity. Optional JPEG references must already exist on
that volume with exact size and CRC; this operation copies no original photos.

The previous `LINNET/PHOTOS/LIBRARY.PIM` is copied and read back under
`LINNET/PHOTOS/BACKUP/<SHA256-prefix>.PIM`. A temporary FAT8.3 package is flushed
and fully read back, references and identities are rechecked, then `LIBRARY.PIM`
is replaced last. The published file receives another flush and complete hash
readback. A host JSON receipt records phases, hashes and backup paths. A named
mutex serializes cooperating photo publishers; the caller must keep the iPod
exclusively in Disk Mode. Publication performs no elevation or reboot. FAT rename
is not a power-loss journal; failures retain evidence without automatic replay.
