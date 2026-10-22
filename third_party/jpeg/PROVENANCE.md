# JPEG IDCT provenance

The baseline 8 × 8 inverse DCT comes from [Rockbox](https://github.com/Rockbox/rockbox):

- Source: `apps/plugins/imageviewer/jpeg/jpeg_decoder.c`
- Commit: `99c18f336c730f533d3b7d2d8951f5dc4a6da802`
- Source SHA-256 (CRLF checkout line endings): `4dd6a9734d5b897fdca7da04db20896c5b027a277d8e101a26b56eb0b8ebcbe8`
- License: [GPL-2.0-or-later](COPYING), with upstream notices retained.

Upstream credits Jörg Hohensohn, Alexander Spyridakis, Thomas G. Lane, and
Guido Vollbeding. Linnet retains transform ordering and constants, uses bounded
signed 64-bit intermediates, and replaces negative signed shifts with
multiplication.

The integration implements Linnet's [IDCT interface](../../services/photos/idct.h)
with immutable coefficient and 16-bit quantization inputs. The entropy driver
passes its validated table directly, avoiding a 256-byte stack copy per block;
the transform ordering, constants and rounding are unchanged.

The bounded incremental marker/entropy driver in
[services/photos/jpeg.c](../../services/photos/jpeg.c) is Linnet code.
The upstream synchronous file parser was not imported. Prepared photos remain
the normal display path; see [LPIC](../../docs/photo-format.md).

Host reference and emulator comparisons do not establish physical playback
speed or LCD quality.
