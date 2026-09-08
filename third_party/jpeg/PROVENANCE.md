# JPEG IDCT provenance

Imported the baseline 8x8 inverse DCT from the working local Rockbox Photo checkout:

- Source: `apps/plugins/imageviewer/jpeg/jpeg_decoder.c`
- Commit: `a0e9e0c700a51d685c704fa59a28dc859e6ee338`
- Source SHA-256: `4dd6a9734d5b897fdca7da04db20896c5b027a277d8e101a26b56eb0b8ebcbe8`
- License: GPL-2.0-or-later, upstream notices retained; see COPYING.

The source credits Jörg Hohensohn, Alexander Spyridakis, Thomas G. Lane and Guido Vollbeding. Linnet retains the transform ordering/constants, uses signed64 bounded intermediates instead of short truncation, and replaces negative signed shifts with multiplication. The incremental bounded marker/entropy driver is implemented in services/photos/jpeg.c; the synchronous upstream file parser and decoder were not imported. No upstream tests or fixtures were copied.

Qualification evidence (host/emulation, not physical hardware timing):

- `out/b05-jpeg-reference.json`: eight existing local JPEG corpus files, all eight orientations, native YUV reference within one RGB565 channel unit. Nearest chroma is intentionally different from interpolated reference RGB.
- `out/b05-jpeg-sanitizer.json`: 1,040 existing/mutated/truncated cases, ASan/UBSan clean, output canaries intact and progressive markers explicitly rejected.
- `out/b05-jpeg-arm.json`: actual ARM7 output equals host for all eight files; observed maximum17,277 instructions in an entropy/IDCT step and22,052 initialization instructions. Instruction counts do not establish device wall-clock deadlines.

The fallback supports a single interleaved baseline8-bit grayscale/YCbCr scan with1x1/2x1/1x2/2x2 luma, independent0..3 quantization/DC/AC table selectors, and ordered restart markers. Limits are256KiB compressed bytes,2048 pixels per source dimension,220x176 output,4096 header markers, and no repeated tables. EXIF orientation is supplied by the already-validated photo index. The engine owns sourceCRC verification, timeout, memory sharing, and admission/suspension under audio pressure. Partial output must not be displayed on error.
