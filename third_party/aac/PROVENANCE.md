# Native AAC-LC integration

Source: the user's working Rockbox Photo repository,
<https://github.com/jspann21/rockbox-ipod-photo>, commit
`a0e9e0c700a51d685c704fa59a28dc859e6ee338`. The imported `libfaad` and shared
codec `lib` directories were clean. `provenance.json` records original and
adapted file SHA-256 values.

FAAD and several Rockbox lookup files are GPL version 2 or later; their original
notices and `faad/COPYING` are preserved. The shared FFT implementation is LGPL
2.1 or later; IMDCT files specify LGPL 2 or later. LGPL 2.1 is provided in
`licenses/LGPL-2.1.txt`. Shared Tremor math helpers have the Xiph BSD license,
provided in `licenses/Tremor-BSD.txt`. See each source's original notice.
This decoder is linked into firmware; GPL combined-work/source distribution
requirements must be accounted for when distributing that firmware.

Adaptations dated 2026-09-06:

- Fixed-point, LC-only configuration with `-fwrapv`. Host builds retain the
  generic integer FFT/MDCT. ARM7 firmware builds use the imported Rockbox
  ARM windowing, FFT butterflies, multiply helpers and inline-assembly IMDCT
  through `-O2 -DCPU_ARM=1 -DARM_ARCH=4`. No additional upstream source files
  are needed; the existing `mdct.c` supplies both implementations.
  No floating-point runtime is linked. SBR/HE-AAC, PS, ER, MAIN, LTP and LD are
  excluded from the supported configuration.
- All mutable decoder singleton buffers and PNS random state moved into
  `ln_faad_workspace`, owned by the caller. A single pointer binds the current
  workspace only for a synchronous decoder call. No binding survives a yield.
  Audio decoding must run on the serialized executor, never concurrently or
  inside an interrupt handler. Immutable lookup tables remain shared.
- The supported LC path has no allocation calls. There is no allocator or
  no-op free substitute. Disabled SBR/ER/debug allocation code is not linked.
- Private freestanding memory operations replace libc/Rockbox codec APIs.
  PNS division uses a bounded 32-iteration divider; aggregate clearing avoids
  missing ARM EABI helpers. Minor Clang warning corrections preserve intent.
- The bit reader uses caller-owned storage for up to 8191 compressed bytes
  plus its required zero guard. Original bitstream bounds checks remain.
- The facade converts fourteen-fractional-bit FAAD output to PCM16 and exposes
  all 1024 samples of the first access unit. Upstream hides that block in its
  sample-count report; Linnet leaves priming/final-duration trimming explicit
  in the container layer.

Compile the sources in `SOURCES` with the repository root, `third_party/aac`,
`third_party/aac/faad` and `third_party/aac/lib` include paths, plus
`-fno-builtin -fwrapv`. Add `services/audio/aac/aac.c` and, for M4A,
`services/audio/aac/m4a.c` with the shared `services/audio/alac/alac.c` demux
and its ALAC core dependency. FFT/MDCT exported symbols must be linked once
if another decoder shares them.

ARM7 context sizes: ADTS/raw facade 110,672 bytes; M4A facade including shared
demux 179,792 bytes; actual typed FAAD workspace 90,736 bytes, within its fixed
98,304-byte reserve. No frame processing expands that memory. The largest
compiled core stack frame is 7,664 bytes in the unused ADIF init entry; use at
least 16 KiB available decode stack including nested callers. Hardware real-time
performance is not established by host validation.

The public APIs live in `services/audio/aac/aac.h` and `m4a.h`. ADTS supports
unprotected, single-block LC frames, mono/stereo. CRC-protected ADTS, PCE,
960-sample frames and ADIF reject explicitly. Raw ASC is bounded to 64 bytes;
raw access units to 8191 bytes. M4A uses the bounded nonfragmented shared demux,
accepts exact STTS packet timing and one supported leading edit, and truncates
only the last packet's padding. Both containers implement exact incremental
restart/decode/discard seeking; large forward seeks take proportional time.
No indexed fast-seek, resampling, media hash verification, or cross-track
scheduling guarantee is implied.

Validation fully linked all core/facade ARM objects without section GC and
found no undefined symbols. Four generated ADTS mono/stereo vectors at 44.1,
22.05, 48 and 8 kHz matched FFmpeg frame counts with peak PCM16 difference 1.
M4A vectors at 44.1 kHz stereo and 22.05 kHz mono produced exactly 18,001 valid
source frames after trimming, with peak difference 1. Five seek points per
container, including start/end, matched linear output byte-for-byte. Callbacks
alternated pending/completion and verified exact read identity. These are
focused host checks, not exhaustive corruption or hardware qualification.

ARM optimization qualification on 2026-09-06 compiled every AAC core/facade
source for ARM7TDMI and linked the complete raw decoder without undefined
symbols. Unicorn executed both generic and optimized ARM binaries on all 542
access units of the existing recovered AAC clip (555,008 untrimmed frames).
The optimized path differs from generic PCM16 by at most one LSB (988 samples),
consistent with the upstream multiply helpers truncating one fixed-point bit.
After the existing 2,112-frame lead and 764-frame tail trim, all 552,132 valid
frames differ from FFmpeg by at most two LSB, matching the previous bound.
This proves the exercised ARM arithmetic and frame counts, not real-time
throughput; device qualification is required. The report is
`out/b04-aac-arm-emulation.json`.

The M4A facade now keeps two bounded 16 KiB read windows for the alternating
sample-table and compressed-media accesses. Every fill stays within the file,
and an outstanding asynchronous fill preserves both caller and source read
identity. Seek resets the windows and retains the original source callback.
On the existing recovered AAC clip this reduced upstream reads from 1,656
to 13 (204,037 bytes fetched), with identical host PCM and exact seek suffixes
at frames 0, 5,371, 552,000 and EOF. Alternating pending/completed callbacks
verified offset, pointer and length stability. See
`out/b04-aac-readcache-host.json`. The cache adds 32 KiB plus bookkeeping to
the M4A context; it is fixed memory, with no allocation or filesystem writes.

A bounded ARM emulator instruction profile of access units 32 through 63
counted 451,849 to 505,545 ARM instructions per 1,024-frame decode (mean
466,000). At 44.1 kHz an 80 MHz CPU has approximately 1,857,596 cycles per AU.
Instruction counts are not cycle estimates: memory, multiply, cache and
scheduler costs still require hardware timing. This evidence plus the repeated
metadata/media reads motivated bounded read-ahead instead of further blind
compiler changes. See `out/b04-aac-instruction-profile.json`.

Freestanding AAC memory operations use aligned may-alias 32-bit words, with
byte prefixes and tails for arbitrary addresses. Copy falls back to bytes
when source and destination alignments differ; move preserves overlap in
both directions. No unaligned ARM word accesses are introduced. A focused
34,304-case host comparison covered alignments, lengths, fill truncation and
overlap. Full 542-AU ARM emulation remains bit-identical to the previous ARM
implementation. Mean instructions per AU (32..63) fell from 466,000 to 341,075,
about 27%, largely by removing byte-at-a-time spectral/window clearing.
See `out/b04-aac-memory-host.json` and `out/b04-aac-memory-arm.json`.
