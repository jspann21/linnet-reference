# Tremor integration

Retained sources originate from `lib/rbcodec/codecs/libtremor/` in
`https://github.com/jspann21/rockbox-ipod-photo`, local revision `a0e9e0c700`.
Original copyright notices remain. `COPYING` contains the Xiph BSD license.
`ffmpeg_stuff.h` carries its own LGPL 2.1-or-later notice; the LGPL text is
available at `../flac/COPYING`. Shared fixed FFT/MDCT sources and their license
notices live in `../aac/lib/`; they must be linked once for both codecs.

The imported packet decoder omits `vorbisfile.c`, Ogg stream allocation,
`oggmalloc.c`, and TLSF. Linnet's facade owns explicit asynchronous page reads,
Ogg CRC and sequence validation, packet assembly and source positions.
Rockbox's global PCM scratch pointers were moved into `vorbis_dsp_state`, so
two contexts may be stepped alternately. Coefficient/codebook work remains
fixed point. Build these sources with `-fwrapv -fno-builtin`; the shared FFT
must use its own AAC include directory, while Tremor uses this directory and
`../aac/lib`. Generic ARM7 C paths are used; do not define `CPU_ARM` here.

Each caller-owned context is below 1 MiB: a 768 KiB allocator pool, a 65307-byte
Ogg page, a 65536-byte packet buffer, and decoder bookkeeping. Pool allocations
are aligned, individually freed and coalesced. Reallocation preserves content.
Temporary allocations replacing `alloca` are reclaimed after each codec call.
Exhaustion unwinds the guarded codec call and resets the pool; it never returns
an unchecked null pointer to Tremor. The ARM guard preserves callee-saved
registers and stack; host builds use setjmp/longjmp for equivalent behavior.
No allocation uses the system heap. Close/restart resets the full owned pool.

Supported initial profile: one unmultiplexed, unchained Ogg Vorbis stream,
mono/stereo, 8–96 kHz, blocks up to 8192 samples. A codebook has at most 256
dimensions, 65536 entries, and 131072 dimension/entry products. Packet/page
limits and the pool budget reject larger configurations explicitly. Comments
are skipped by the retained decoder. Sequential seek restarts and discards PCM
in bounded steps; no fast seek index is implied. A call reads at most 4096 source
bytes, processes one packet, or delivers/discards a caller-bounded PCM segment.

Host qualification used libvorbisfile's floating decoder as the oracle. Stereo
44.1/22.05 kHz and mono 48 kHz produced matching frame counts and at most one
PCM16 LSB difference. Pending read replay, restart and seeks through EOF passed.
Allocator reallocation/coalescing/exhaustion and 256 CRC-valid malformed setup
variants were exercised. AddressSanitizer and UndefinedBehaviorSanitizer ran
with shift checks disabled for retained fixed-point signed-shift idioms and
`-fwrapv` for intentional predictor arithmetic. iPod timing, IRQ latency and
listening qualification remain separate hardware work.

The complete ARM object set plus shared FFT links without garbage collection;
only the existing `__aeabi_memclr8` memory primitive remains external. Weak,
bounded 32-step EABI division helpers supply quotient/remainder registers and
deterministic zero-divisor behavior.
