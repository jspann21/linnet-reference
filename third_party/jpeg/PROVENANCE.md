# JPEG IDCT provenance

The baseline 8 × 8 inverse DCT comes from Rockbox Photo:

- Source: `apps/plugins/imageviewer/jpeg/jpeg_decoder.c`
- Commit: `a0e9e0c700a51d685c704fa59a28dc859e6ee338`
- Source SHA-256: `4dd6a9734d5b897fdca7da04db20896c5b027a277d8e101a26b56eb0b8ebcbe8`
- License: [GPL-2.0-or-later](COPYING), with upstream notices retained.

Upstream credits Jörg Hohensohn, Alexander Spyridakis, Thomas G. Lane, and
Guido Vollbeding. Linnet retains transform ordering and constants, uses bounded
signed 64-bit intermediates, and replaces negative signed shifts with
multiplication.

The bounded incremental marker/entropy driver in
[services/photos/jpeg.c](../../services/photos/jpeg.c) is Linnet code.
The upstream synchronous file parser was not imported. Prepared photos remain
the normal display path; see [PIMG](../../docs/photo-format.md).

Host reference and emulator comparisons do not establish physical playback
speed or LCD quality.
