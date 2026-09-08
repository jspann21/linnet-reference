# Linnet FLAC decoder provenance

`decoder.c`, `decoder.h`, and `COPYING` originate from
`https://github.com/jspann21/rockbox-ipod-photo`, local checkout
`C:/Users/user/Desktop/Projects/ipod`, revision `a0e9e0c700`.
Original path: `lib/rbcodec/codecs/libffmpegFLAC/`.
The retained decoder is LGPL version 2 or later, with original notices intact.
`COPYING` supplies the included LGPL text. Source and modifications remain
available here; binary distribution must meet the license's relinking terms.

Linnet modifications: freestanding `<stdint.h>` include; bounded fixed LPC
coefficient array; predictor/block/bit-depth/rate validation; bounded UTF-8 and
wasted-bit parsing; explicit unsigned output scaling; bitreader error propagation.
Compile the retained decoder with `-fwrapv` for its intentional signed predictor
arithmetic. No assembly implementation is enabled in this initial integration.

`bitstream.h`, `golomb.h`, and `codeclib.h` are minimal Linnet shims. The bounded
reader and Rice parser replace the generic Rockbox bit-cache dependencies.
`shndec.c` is a separate Shorten decoder and is not required for FLAC.

The production wrapper in `services/audio/flac/` owns fixed buffers, metadata,
asynchronous exact reads, PCM16 conversion and both header/frame CRC checks.
It supports mono/stereo, 8–24 bits, blocks up to 4608 samples and compressed
frames up to 65536 bytes. Larger blocks, more channels, Ogg FLAC and ID3-prefixed
FLAC are rejected explicitly. STREAMINFO MD5 verification is not implemented.
The first 64 native SEEKTABLE points are retained. Seeking without an applicable
native point returns false, except restart at sample zero. Discard after a point
advances at most one decoded frame per call. The wrapper never scans the drive
to manufacture an index.

Host validation compared decoded output with FFmpeg for stereo PCM16 at
44.1 kHz, duplicated mono PCM16 at 48 kHz, and stereo PCM24 at 44.1 kHz.
The latter two comparisons ran under AddressSanitizer and UndefinedBehaviorSanitizer.
Native SEEKTABLE parsing and discard seeking matched the reference at sample
positions 0, 100, 4500, 44000 and EOF, with every source read deliberately returning
pending once before completion and asserting identical replay arguments.
Ten thousand bounded malformed frame inputs also passed both sanitizers.
These checks do not constitute iPod performance or listening qualification.
