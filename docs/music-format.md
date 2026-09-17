# PODB

`tools/content/music.py` compiles an immutable library with at most 100,000 tracks
and 128 MiB of database bytes. All integers are little endian. Offsets and sizes
are checked with subtraction before reads; no file bytes are cast to C structs.
Tables are contiguous in the order below, with no padding or trailing bytes.
The file is `/.LINNET/LIBRARY.PDB`; media and artwork have FAT-compatible 8.3 names.
The compiler packs group names in browse order, followed by track titles, search
keys and remaining deduplicated strings. All references use rewritten pool
offsets; record IDs, ordering and format remain unchanged. Existing databases
remain readable and acquire this layout on the next Media Manager music update.

## Header: 128 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | char[4] | `PODB` |
| 4 | u16 | Format identifier, fixed at 2 |
| 6 | u16 | Header bytes 128 |
| 8 | u32 | Exact file size, at most 134217728 |
| 12 | u32 | Flags, zero |
| 16 | u32 | Track count, at most 100000 |
| 20 | u32 | Group count |
| 24 | u32 | Member count |
| 28 | u32 | Search count: tracks plus artist/album groups |
| 32 | u32 | Track table offset, exactly 128 |
| 36 | u32 | Group table offset |
| 40 | u32 | Member table offset |
| 44 | u32 | Search table offset |
| 48 | u32 | String pool offset |
| 52 | u32 | String pool bytes, at least 1 |
| 56 | u32 | Artwork count |
| 60 | u32 | Artwork table offset |
| 64 | byte[32] | SHA-256 of all bytes after the header |
| 96 | byte[28] | Reserved zero |
| 124 | u32 | CRC32/ISO-HDLC of header bytes 0 through 123 |

Track/group/member/search/artwork/string sections occupy respectively
`128*ntracks`, `32*ngroups`, `4*nmembers`, `8*nsearch`, `32*nart`, and
`string_bytes`. Verify every section equation, header CRC, and payload SHA before
publishing a library as verified. Header-only validation must be described as
such. SHA is corruption detection, not authentication. A bounded asynchronous
device reader can stream the hash and retain only active records and strings.

## Track record: 128 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u64 | Stable track ID |
| 8 | u64 | Exact staged media file bytes |
| 16 | u64 | Audio data offset within media file |
| 24 | u64 | Audio data bytes |
| 32 | u64 | Exact PCM frames; zero means unknown for compressed media |
| 40 | u32 | Sample rate, 1 through 384000 |
| 44 | u16 | Channels, 1 through 8 |
| 46 | u16 | Bits per sample; may be zero for compressed media |
| 48 | u32 | Codec ID |
| 52 | u32 | Title string offset |
| 56 | u32 | Artist string offset |
| 60 | u32 | Album string offset |
| 64 | u32 | Direct media path string offset |
| 68 | u32 | Genre string offset |
| 72 | u32 | Composer string offset |
| 76 | u32 | Year; zero means unknown |
| 80 | u32 | Track number; zero means unknown |
| 84 | u32 | Disc number; zero means unknown |
| 88 | u32 | Artwork table index, or `0xffffffff` |
| 92 | i32 | Track ReplayGain dB in Q16.16; `INT32_MIN` means unknown |
| 96 | byte[32] | SHA-256 of complete media; all zero for metadata-only existing references |

Codec IDs are 1 integer PCM little endian, 2 integer PCM big endian, 3 IEEE float
little endian, 4 IEEE float big endian, 16 MP3, 17 AAC, 18 ALAC, 19 FLAC,
20 Vorbis, 21 Opus, 22 WavPack. IDs express source encoding, not native decoder
availability. Integer PCM widths are 8, 16, 24, or 32; float widths are 32.
WAV 8-bit integer samples are unsigned; AIFF 8-bit samples are signed. Consumers
must inspect the media container when the byte-order codec ID is insufficient
to determine sample signedness. Interleaving is channel-major within each frame.
PCM `data_bytes == frames * channels * bytes_per_sample` is mandatory.
Compressed records cover the complete container (`offset=0`, `bytes=file_bytes`)
and do not claim exact frame counts or an immediately decodable payload offset.

Track IDs are the first eight SHA-256 bytes of UTF-8 `track:` plus the exact
source-relative POSIX path, decoded as little-endian u64. Metadata edits preserve
IDs; moving a source changes its ID. The compiler rejects ID and short-name
collisions. The staged name is uppercase low-32-bit ID hex plus an extension of
at most three characters, e.g. `/.LINNET/MUSIC/7A31B298.WAV`. AIFF/AIFC use `AIF`,
FLAC uses `FLC`, Opus uses `OPS`. Original relative paths are retained only in
the host manifest. In-place imports instead reference the existing file using its
actual FAT 8.3 alias, resolved on the mounted volume. Paths are absolute, at most
255 characters and 16 components; each component is an uppercase FAT short name.
The host manifest marks these entries `storage: "existing"`. Default fast imports
use `integrity: "metadata"`, a zero digest, and recorded `bytes`/`mtime_ns`;
publication checks file size and modification time without reading full audio.
Explicit full verification uses `integrity: "sha256"` and complete file hashes.
Entries without an integrity shortcut receive full SHA-256 verification.
No audio is copied for either existing-reference mode. Compressed entries
store host-decoded sample counts, cached between imports, so duration is available
even without a native duration header. Native decoder frame counts take precedence
during playback. Older databases may contain `frames=0` (unknown).
Staged media bytes are unchanged, and originals are never
modified. The device must reject unsafe paths and size/range mismatches before
starting playback, and verify content hashes before claiming media integrity.

## Group record: 32 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u32 | Kind: 1 artist, 2 album, 3 genre, 4 composer, 5 year, 6 folder, 7 playlist |
| 4 | u32 | Name string offset |
| 8 | u32 | Parent group index: album's artist; otherwise `0xffffffff` |
| 12 | u32 | First member index |
| 16 | u32 | Member count |
| 20 | u32 | Reserved zero |
| 24 | u64 | Stable group ID |

Each member is a u32 track-table index. An album is keyed by album artist and album
name. The compiler uses `album_artist`/`albumartist`, falling back to track artist;
compilation tags (`1`, `true`, `yes`) use Various Artists when the owner would
otherwise be the track artist. An explicit different album artist takes precedence.
Trailing guest credits
introduced by feat., ft. or featuring are removed from album ownership only.
Track artist credits are preserved. Artist groups include tracks they perform
or own as album artist, without repeating a track within a group.
Groups are sorted by kind, Unicode-casefolded name, casefolded parent name,
then the exact key for deterministic ties. Non-playlist members are sorted by
disc, track number, casefolded title, then track index. Playlists preserve supplied
order and repeats. Artist-to-album lookup follows album parent indexes; artist
members are direct tracks. Group IDs hash UTF-8 `group:` followed by the JSON
array `[kind,parent,name]` (no separating whitespace, Unicode unescaped) using the
same first-eight-byte scheme; collisions are rejected. Empty optional genre/composer/year groups are
omitted. Folder names are source-relative POSIX paths (root is `.`).

## Search record: 8 bytes

Each record contains a u32 reference followed by a u32 search-key string offset.
Bit 31 marks a group reference; otherwise the reference is a track index.
For group references the remaining bits are the group index; only artist (1) and album (2)
groups are admitted. Every track and every artist/album group appears exactly
once. The table is sorted by Unicode-casefolded title or group name,
then reference. The stored key is that casefolded name. UTF-8 byte ordering
preserves Unicode scalar ordering. Readers can binary-search a casefolded prefix
without transforming titles or scanning media. Full Unicode query folding is a
host concern unless implemented on-device; an ASCII keyboard can fold A-Z only.
Artist and album results open their existing member lists. Search uses one
cached binary lower bound and 12-row pages; it does not scan tracks or media.
Only the current format is supported. Rebuild incompatible catalogs with the
media manager. Its update signature includes name search so unchanged audio
still receives the current index.


## Artwork record: 32 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u64 | First eight bytes of SHA-256 of RGB565 data, little endian |
| 8 | u32 | Artwork path string offset |
| 12 | u16 | Width, 64 |
| 14 | u16 | Height, 64 |
| 16 | u32 | Encoding 1: little-endian RGB565, top row first |
| 20 | u32 | Bytes, 8192 |
| 24 | u32 | CRC32/ISO-HDLC of RGB565 data |
| 28 | u32 | Reserved zero |

Artwork files are `/.LINNET/ART/XXXXXXXX.RGB`, where the name uses the first four
SHA-256 bytes as hex. The compiler optionally uses Pillow to crop/resize a folder's
`cover.png`, `cover.jpg`, `folder.jpg`, or `Folder.jpg`. It bounds input file size
to 32 MiB and decoded dimensions to 16 million pixels. Missing artwork uses the
sentinel, and name collisions are rejected. Embedded artwork extraction is not
implemented in the current player.

## String pool and publication

String offsets are relative to the pool and must point at a string start, not a
continuation byte. Strings are strict UTF-8, NUL terminated, at most 255 bytes
excluding NUL. Offset zero is the empty string; the pool starts and ends with
NUL. Strings are deduplicated. No variable strings or filesystem paths are read
without bounds.

The compiler validates its complete output before replacing `LIBRARY.PDB` through
a same-directory temporary file. The source directory and output directory must
not overlap. Compilation is local staging; it does not perform transactional
device installation or remove old staged media. The sync layer must validate all
new objects and publish the immutable database only after their durable upload.
Open media and the active library must retain the same generation across a swap.

This first contract implements PCM metadata, optional ffprobe compressed metadata,
track/group/title-search indexes, explicit playlists, track ReplayGain tags, and
folder artwork. Exact compressed gapless trims, seek tables, cached FAT extents,
album ReplayGain/peak, device scanning, and the mutable playback journal are
separate work. This compiler does not transcode audio.
