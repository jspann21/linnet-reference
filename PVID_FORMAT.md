# PVID format

PVID stores prepared full-screen RGB565 video and the exact stereo signed 16-bit
little-endian PCM interval associated with each displayed frame. All integers
are unsigned little-endian unless stated otherwise. CRCs use CRC-32/ISO-HDLC
(`zlib.crc32`). The host extension is `.pvid`; a device file can use the FAT name
`/LINNET/VIDEOS/<key>.PVD`, referenced by `/LINNET/VIDEOS/INDEX.VID`.
Maximum file size is 2,147,483,647 bytes.

## Header — 512 bytes

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | char[4] | `PVID` |
| 4 | u32 | Header size, 512 |
| 8 | u32 | Flags, zero |
| 12 | u32 | Exact file bytes |
| 16, 20 | u32 each | Width 1..220, height 1..176 |
| 24 | u32 | Frames per second: 24, 25, 30, or optional 60 |
| 28 | u32 | PCM sample rate, 48000 |
| 32 | u32 | Frame count, 1..1,000,000 |
| 36 | u32 | Index offset, 512 |
| 40 | u32 | Data offset, `align512(512 + frame_count * 32)` |
| 44 | u32 | Exact largest aligned record size, at most 90112 |
| 48 | u32 | CRC of bytes 512 through data offset, including zero padding |
| 52 | u32 | Keyframe interval, 1..10 times fps |
| 56..507 | bytes | Reserved, zero |
| 508 | u32 | CRC of bytes 0..507 |

RGB565 words use red bits 15..11, green bits 10..5, blue bits 4..0. Images are
row-major. Host conversion preserves aspect ratio and letterboxes to the chosen
dimensions. Runtime may center smaller dimensions on the panel.

## Frame index — 32 bytes per frame

Eight u32 fields: absolute record offset, aligned record bytes, zero-based frame
number, first PCM sample frame, PCM sample frame count, nearest preceding
independent frame number, CRC of the complete aligned record, reserved zero.

Records are contiguous in frame order, starting at the data offset and ending
at exact EOF. Every offset and size is aligned to 512. Sample count is exactly
`48000 / fps`; first sample is exactly `frame_number * sample_count`. Total
samples must fit u32. An independent frame is required at frame zero and each
multiple of the keyframe interval. Additional independent frames are allowed.
Seek starts at the indexed independent frame and reconstructs successive frames
until the target; PCM before the target is discarded.

## Frame record

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | char[4] | `FRAM` |
| 4 | u32 | Frame number |
| 8 | u32 | Type: raw 0, repeat 1, tile delta 2, RLE 3, LZ4 4 |
| 12 | u32 | Video payload bytes |
| 16, 20 | u32 each | First sample and sample count, matching index |
| 24 | u32 | CRC of the complete decoded RGB565 frame |
| 28 | u32 | CRC of video payload followed by PCM; excludes padding |
| 32 | bytes | Video payload, then `sample_count * 4` PCM bytes |
| after PCM | bytes | Zero padding to the next sector |

PCM order is left s16, right s16 for every sample frame. Silent or exhausted
source audio is padded with zero samples; longer audio is clipped to the video
interval. Source audio timestamps are resampled to start at zero. Header,
index, record, payload and decoded-frame CRCs are all mandatory.

- **Raw:** exactly `width * height * 2` pixel bytes. Independent.
- **Repeat:** empty video payload; use the previous complete decoded frame.
- **Tile delta:** u32 changed-tile count, then that many tile records. Tile
  records have u16 tile number, u16 reserved zero, and raw pixel bytes. The grid
  uses 16×16 tiles in row-major order; right/bottom tiles are clipped to image
  dimensions and contain only their valid pixels. Tile numbers are strictly
  increasing and count is 1..total tiles. Copy the previous complete frame then
  replace those tiles. No trailing bytes are allowed.
- **RLE:** repeated u16 run length, u16 pixel pairs. Run lengths are nonzero;
  their sum is exactly width×height. Independent. No trailing bytes are allowed.
- **LZ4:** an independent raw LZ4 block reconstructing exactly
  `width * height * 2` little-endian RGB565 bytes. Independent, so the index's
  nearest preceding independent frame becomes this frame. The payload must be
  nonempty and shorter than the raw frame. There is no frame wrapper, dictionary,
  decoded-size prefix, byte swapping, temporal transform, or audio compression.
  Tokens have literal length in the high nibble and match length minus four in
  the low nibble. A length nibble of 15 is extended by bytes through the first
  value below 255. The match offset is a nonzero little-endian u16 no larger
  than the bytes already decoded; overlapping matches copy forward. The block
  must finish with a nonempty literal sequence, at least five terminal literals
  for output of at least five bytes, and the final match must begin at least
  twelve decoded bytes before the end. Input and output must be consumed exactly.
  Reject truncation, invalid offsets, length overflow, and output overrun.

Readers reject invalid lengths, arithmetic overflow, nonzero reserved or padding
bytes, index ordering errors, sample discontinuities, invalid dependency chains,
out-of-bounds tiles/runs, unsupported record types, or CRC mismatches before
presentation. There is no best-effort playback of a corrupt record.

## Host API and budget model

`tools.content.video.compile_video(source, output, *, fps=24, width=220,
height=176, key_interval=24, cost_model=None, ffmpeg=None, max_frames=None)`
streams ffmpeg video and PCM through bounded frame buffers, spools records and
index locally, validates the complete result, then atomically replaces output.
`inspect(path)` validates all records and reconstructs every frame without
retaining the complete movie. Reports include SHA256 and counts by record type.

`repack_spatial(source, output)` validates a PVID file and compresses it
atomically. It preserves exact decoded frames, PCM, timing, and the
keyframe interval. It tries bounded independent LZ4 compression of each decoded
frame and retains the original record unless LZ4 saves at least one complete
sector. It updates the index's independent-frame references and recomputes
stored-record, payload, index, and header CRCs. Output is fully inspected before
replacement; an invalid source or failed conversion leaves the output intact.
The report includes source/output hashes, decoded-frame and PCM stream hashes,
and bytes saved. This operation does not change the compiler cost model or establish that
its byte reduction satisfies the device audio gate.

The model uses explicit `read_us_per_byte`, `raw_us_per_pixel`,
`copy_us_per_pixel`, `rle_us_per_run`, `delta_us_per_tile`, `fixed_us`, and
`present_us`. Cost includes the aligned record read plus preparation and
presentation. The cheapest eligible encoding is selected; conversion rejects
any selected frame costing more than `1000000 / fps` microseconds. Keyframes
only select raw or RLE. Repeat and delta include prior-frame copy cost.

Default values are estimates, and their report is **unqualified estimate**.
`measured=True` requires every model parameter and a nonempty `measurement_id`
identifying device evidence. Passing this declared model alone does not qualify
the product's zero-gap audio, drift, tearing, storage wake, or sustained playback
gates. Profiles 24/25/30 and optional 60 remain unqualified until their device
campaigns pass. The current container has no embedded performance certificate;
the conversion report retains the model and worst declared frame cost.
