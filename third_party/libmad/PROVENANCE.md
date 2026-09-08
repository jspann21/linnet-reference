# Linnet libmad integration

Imported from the user's working Rockbox iPod Photo tree at commit
`a0e9e0c700a51d685c704fa59a28dc859e6ee338`, directory
`lib/rbcodec/codecs/libmad`, repository
<https://github.com/jspann21/rockbox-ipod-photo>. That directory was clean at
import. `provenance.json` records SHA-256 for original and imported files.

The decoder is GPL version 2 or later; original copyright and license notices
are retained in every imported file. `COPYING` contains GPL version 2. This is
linked native decoder code, not an external runtime codec service. Distribution
must account for the GPL-covered combined work and corresponding source.

Changes dated 2026-09-06:

- Private `codeclib.h` supplies bounded memory operations, byte-order conversion,
  and bounded integer division. It does not include Rockbox's global codec API.
- `config.h` selects ARMv4 `FPM_ARM` on ARM-state targets and portable
  `FPM_64BIT` on hosts, single-core caller
  storage, no IRAM sections, and no debug abort dependency. No floating-point
  decoder path or heap allocator is present.
- `mad.h` and `fixed.h` use freestanding `stdint.h` and the private config.
- `global.h` uses the config's arithmetic choice; `layer3.c` uses the private
  memory shim instead of unavailable libc headers.
- Variable division in `frame.c` and Layer II degrouping in `layer12.c` uses
  the bounded private divider, avoiding ARM EABI division runtime dependencies.

Build the seven core C files `bit`, `frame`, `huffman`, `layer12`, `layer3`,
`stream`, and `synth` with `-fno-builtin -fwrapv`, plus Linnet's facade at
`services/audio/mp3/mp3.c`. ARM builds additionally require `imdct_l_arm.S`
and `synth_full_arm.S` and use `-O2`. Include the repository root and this
directory. No host codec process, Rockbox scheduler, allocator, or global codec
object is required. The facade exposes only Layer III. The Layer I/II core
objects remain linked because upstream dispatch references them.

The caller owns approximately 38 KiB of decoder state. ARM7 `-Os` compilation
reports a 7,584-byte Layer III stack frame plus nested calls: provide at least
16 KiB of available decode stack. Input is at most 8 KiB plus guard bytes; each
read is at most 4 KiB. Each facade call does at most one frame decode or one
read. MPEG frames may still take meaningful CPU time; hardware real-time budget
qualification is required before claiming uninterrupted playback.

Local validation fully linked every ARM object without section GC, with zero
undefined symbols. Host streaming comparisons against FFmpeg covered generated
MPEG1/2/2.5 at 44.1, 22.05, 48 and 8 kHz, mono and stereo, with identical output
frame counts and maximum signed-16-bit sample difference 4. Input callbacks
alternated pending/completion to verify request ownership. These checks do not
constitute malformed-file fuzzing, hardware qualification, or a codec corpus.

The facade reads bounded Xing/Info fields and recognized LAME/Lavc/Lavf delay
extensions. It follows Rockbox's `codecs/mpa.c` Layer III synthesis latency:
skip encoder delay plus 529 leading samples and encoder padding minus 529
trailing samples. It exposes a known exact output count only when the optional
frame count and trim fields are present and plausible; unsupported extensions
leave `gapless=false`. Tag CRC authentication is not claimed. Four additional
seekable-memory FFmpeg vectors with Xing/LAME headers produced exactly the
original PCM frame counts with peak signed-16-bit sample differences at most 4.

The facade seeks to exact trimmed samples by restarting and incrementally
decoding/discarding at most one frame per call. This is linear in the seek
distance; an indexed fast seek path remains pending. It does not implement
joins between tracks, sample-rate conversion, or media hash verification. It counts recoverable frame
errors; clean EOF does not establish source integrity. Player scheduling is
still responsible for feeding adjacent trimmed tracks without a buffer gap.

ARM optimization dated 2026-09-06: the two GPL2+ ARM assembly files come
from the same verified Rockbox commit. Their external Rockbox `ldmpc` macro
is expanded to `ldmia sp!, {..., pc}` for Linnet's ARM-state-only callers.
Inline SMLAL outputs use early-clobber constraints to prevent input/output
register overlap on ARM7. The upstream ARM path retains 64-bit accumulated
products and rounds fixed-point scaling; its synthesis DCT deliberately uses
the upstream one-bit precision speed optimization. Host FPM_64BIT output is
therefore a reference with potentially different last bits, not a byte-exact
ARM oracle. All seven C objects, both assembly objects and the facade link
strictly for ARM7TDMI at -O2 without section garbage collection or undefined
symbols. Actual ARM PCM and real-time performance require hardware validation;
no emulator measurement is claimed.

The private copy/set/move primitives now use aligned may-alias 32-bit words
with byte prefixes/tails and a byte fallback for mismatched alignment. Move
retains correct forward/backward overlap behavior. These are the same bounded
primitives qualified for AAC across 34,304 alignment/tail/overlap cases.
The full existing Five O'Clock 500 MP3 decodes to identical host PCM before
and after the change (9,627,264 frames). ARM emulation of its first 36,864
frames also remains bit-identical; instructions fell from 8,314,775 to
7,742,523 (6.9%). This subset is an instruction comparison, not a hardware
cycle or whole-track performance claim. Reports:
`out/b04-mp3-memory-host.json`, `out/b04-mp3-memory-arm.json`.
