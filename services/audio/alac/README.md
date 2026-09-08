# Native ALAC and bounded M4A demux

`ln_alac_init/open_step/decode/seek` decode M4A ALAC integer16 mono/stereo to
interleaved signed16 stereo. Mono is duplicated. Rates8–96kHz are parsed; hardware
clock support is separately gated by the player. One ALAC frame is decoded per
step, then caller-sized PCM blocks drain without re-decoding. There is no heap.
State is approximately69KiB; the core coefficient arrays are static, so native
decode calls must be serialized. Compile the imported core with `-fwrapv` for its
intentional signed predictor arithmetic.

`ln_m4a_init/open_step/read_packet/seek` expose the same container reader for
AAC-LC access units. The demux parses bounded ESDS/ASC metadata and exposes raw
access units; it does not decode AAC. Codec IDs17/18 match PODB. The consumer must
finish the returned packet buffer before the next read. Shared state includes
the ALAC PCM arrays even when used for AAC.

Limits are one audio track; nonfragmented M4A; nesting8;4096 atoms;1million packets
and chunks;256 sample-to-chunk runs;128 timing runs;256 packets per chunk;4096
ALAC frames per packet;32768 ALAC packet bytes;8191 AAC packet bytes;64 ASC bytes.
Packet table entries are read on demand. Individual asynchronous reads are at
most16384 bytes. `stsz`, `stsc`, `stco`/`co64`, `stts`, self-contained `dref`, and
version0 audio sample entries are required. Sample/chunk/frame totals and every
packet's range within one `mdat` are checked. Exact media hashes remain the
library/player's responsibility.

Unsupported inputs fail explicitly: ALAC24/32, more than two channels, separate
low-byte planes, unsupported predictor modes, fragmented/encrypted/external
media, multiple tracks,64-bit version1 media headers, and complex edits. AAC ASC
must indicate LC with a standard rate index and mono/stereo channel configuration.
The demux accepts one nonnegative rate1 edit. Its end must match remaining STTS
time within one movie tick; larger intentional end edits are rejected. AAC
consumers discard `lead_trim` and honor `current_packet_frames` to remove the
last packet's padding. STTS sample timing is preserved rather than rounded to
the coarser movie clock.

Seek uses timing and chunk runs, reads the target chunk's size prefix, and
discards only the target frame prefix. Seek refuses while an asynchronous read
owns the buffer. Cancellation is owned by the outer storage adapter: cancel and
drain that read before resetting this decoder. A completed first half of a large
packet can be abandoned safely before a seek because no second read is admitted.

Host validation performed using temporary inline programs, with no retained test
harness or fixture files:

- FFmpeg-encoded ALAC mono/stereo matched source PCM byte for byte across18001
  frames, including sine, silence, and deterministic random samples at8,44.1,48,
  and96kHz; exact seek to frame5371 matched the remaining12630 frames.
- Delayed exact-read callbacks verified identical pending arguments. Random
  stereo exercised large uncompressed packets and split storage reads.
- ASan/UBSan completed these reference checks and2000 bounded malformed packets.
- AAC M4A's19 access units matched FFprobe packet SHA-256 values. ASC, lead trim,
  sample count, and per-packet STTS durations were observed independently.
- Every ALAC core/service ARM object linked together without garbage collection
  or unresolved symbols, using freestanding ARM7 and strict warning flags.

These are host checks. Real-time hardware throughput, DMA interaction, and
subjective audio qualification require the integrated player campaign.
