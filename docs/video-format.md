# IPVF video format

IPVF is Linnet’s sole video format. Host files use `.ipvf` or `.ipv`;
published files use `/LINNET/VIDEOS/<key>.IPV` and are listed in
`/LINNET/VIDEOS/INDEX.VID`.

The 512-byte header starts with `IPVF` and contains an 80-byte fixed header
plus bounded title, artist and album metadata. It declares target-native
RGB565 big-endian frame dimensions, a rational frame rate, 44.1 kHz stereo
IMA ADPCM audio, the media region, and a seek index. Records are aligned to
512-byte sectors and carry the next record’s sector count.

Video records support raw and LZ4 keyframes, rectangle updates, repeated
frames, temporal XOR, and motion prediction with LZ4 residuals. Audio records
independently encode stereo, mono, or silence. The seek index identifies every
keyframe. IPVF uses Rockbox’s MSB-first CRC32 without a final XOR for its
media identity, index, and temporal compressed payloads.

The streaming host validator checks bounds, reserved bytes, padding, the
record chain, index identity, checksums, and reconstruction of every video
and audio frame. Firmware validates the header and first frame before showing
a preview; playback waits for index verification and buffered media.

## Host commands

```console
python linnet video compile --source movie.mp4 --output out/movie.ipvf --target photo4g-p98
python linnet video inspect out/movie.ipvf
```

Compilation uses the target’s dimensions, frame rate, color profile and maximum
record size. `--fps` overrides the frame rate within 4–30 fps. FFmpeg and FFprobe
are required; `--ffmpeg` and `--ffprobe` select explicit executables.

`tools.content.ipvf_encode.encode_ipvf` converts, validates, and atomically
publishes the local output. `tools.content.ipvf_validate.inspect_file` validates
an existing file. The Media Manager uses these same paths and can index native
IPVF already on an iPod without copying it. Device publication uses
`tools.content.publish_video` and preserves the previous package.
