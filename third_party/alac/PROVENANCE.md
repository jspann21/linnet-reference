# ALAC decoder provenance

Imported from local ipod/lib/rbcodec/codecs/libalac at commit `a0e9e0c700a51d685c704fa59a28dc859e6ee338`. Original MIT notice is retained in alac.c and LICENSE.

Original SHA-256:

- `alac.c`: `e33facf8b5015f283c1f8548cdc233bd216f0c9c122a45e195f8dcb4c80611cd`
- `decomp.h`: `f28f873a30433966b32c3c62e22cab2d55d517d99b1051404c1cd522ba223b75`
- `README.rockbox`: `ca809ccd5e135f1c1427893f9bc6e6bd4cf96a8e71b1e6a17370c595f86ddffc`

Linnet changes: freestanding declarations; exact-length bounded bit reader; explicit frame/sample/predictor/Rice bounds; rejection of unsupported prediction and low-byte planes; mono/stereo16-bit output restriction. Decoder retains static coefficient scratch and requires serialized calls. M4A demux is new Linnet code.

The common four-tap adaptive predictor now keeps its coefficient and sample
window in locals and unrolls its four bounded adaptation steps. Signed16
coefficient wrapping and residual stopping conditions retain the upstream
semantics. The existing 220,500-frame ALAC sample remains identical to both the
previous decoder and FFmpeg; 288 predictor boundary cases compare coefficients
and PCM. ARM emulation of the first32,768 frames also matches exactly, reducing
data accesses from1,448,704 to990,800 and instructions from3,866,768 to3,801,600.
This is an emulator comparison, not a hardware throughput claim. Reports are
`out/b04-alac-predictor-host.json` and `out/b04-alac-predictor-arm.json`.
The bounded bit reader, CLZ implementation, other predictor sizes, and compiler
optimization level are unchanged.
