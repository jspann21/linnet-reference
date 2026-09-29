# FLAC decoder provenance

`decoder.c`, `decoder.h`, and `COPYING` originate from
[Rockbox Photo](https://github.com/jspann21/rockbox-ipod-photo), revision
`a0e9e0c700`, at `lib/rbcodec/codecs/libffmpegFLAC/`.
Original notices and [LGPL-2.0-or-later terms](COPYING) remain intact.

Linnet adds freestanding declarations, fixed LPC storage, predictor and bitstream
bounds, explicit output scaling, and error propagation. Private bitreader/Rice
helpers replace the global codec dependencies. The separate Shorten decoder is
not part of this FLAC integration.

The [native wrapper](../../services/audio/flac/flac.c) owns fixed buffers,
metadata, asynchronous reads, PCM16 conversion, and header/frame CRC checks.
It accepts mono/stereo, 8–24-bit samples, blocks up to 4,608 samples, and bounded
compressed frames. Larger blocks, additional channels, Ogg FLAC, and ID3-prefixed
FLAC reject explicitly. STREAMINFO MD5 verification is not implemented.

Seeking uses retained native SEEKTABLE points, or restart at zero; it does not
scan storage to invent an index. Discard work is bounded to a decoded frame per
call. The build uses wrapping predictor arithmetic; see
[build.py](../../tools/studio/build.py) for current integration flags.
