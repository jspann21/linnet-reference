# Native artwork validation

Hardware checks on 2 October 2026 cover the native artwork changes in
`d9c5f5f` and the malformed-catalog repair in `23e4a63`.
The host prepares 160 px playback covers, exact 112/126 px Now Playing
renditions, and 130 px indexed Cover Flow tiles. The 5G home menu retains
its full width; Classic uses its existing 160 px home cover pane.

## Hardware results

| Device | Library used | Unique Cover Flow tiles | Warm navigation |
| --- | --- | ---: | --- |
| Flash 5G, 30GB board, serial ending 1596FB5F | 426 tracks, 70 albums | 50 | 12 resident hits; zero misses |
| Rotating 80GB 5G, serial ending 15E30DA1 | 2,222 tracks, 1,254 albums | 603 | 12 resident hits; zero misses |
| Rotating 30GB 5G, serial ending 14C20FE4 | 12 temporary PCM WAV albums | 12 | 11 resident hits; final move clamped at the last album |
| Flash Classic 6G, serial ending 155D9C10 | 394 tracks, 53 albums | 40 | 12 resident hits; zero misses |

Warm navigation performed no artwork reads. The 30GB disk had no prepared
library before testing. Its temporary tracks, covers, and indexes were
hash-checked and removed after the run, then its original persistent OS
was safely restarted and reported healthy.

First-frame captures show artwork in Now Playing on 5G and Classic when
the selected album has a cover. Classic's home Now Playing selection also
shows the full prepared cover. A coverless album correctly leaves the art
area empty. All four devices accepted 32 alternating home wheel events
with zero dropped events. These checks verify input processing and display
completion; framebuffer captures cannot establish physical LCD smoothness.

The native tiles contain 83% more square-image pixels than the previous
96 px tiles. In the captured Cover Flow runs, mean render CPU time was
25.24 ms versus 23.46 ms on the flash 5G, and 13.79 ms versus 12.38 ms on
Classic. The final installed 80GB 5G run averaged 24.11 ms versus its
23.62 ms baseline. Higher artwork resolution therefore has a measured CPU cost.
The input harness can observe an animation between submitted frames, so
its wheel timings are not a reliable animation latency benchmark.

## Source fidelity

Astra independently compared all 59 distinct original embedded covers in
the flash 5G host cache. The reference was the full-resolution source,
normalized for EXIF orientation and ICC color, square-cropped and resized
with Lanczos. Both production recipes included their JPEG draft decoding,
RGB565 quantization, and the old device's exact sampling coordinates.
Every cover improved at every primary display size.

| Display rendition | Old pooled PSNR | New pooled PSNR |
| --- | ---: | ---: |
| Now Playing, 112 px | 21.40 dB | 42.39 dB |
| Classic Now Playing, 126 px | 21.12 dB | 42.40 dB |
| Classic home, 160 px | 22.89 dB | 42.42 dB |
| Cover Flow center card, 130 px | 24.16 dB | 34.92 dB |

These values describe RGB pixel error against that reference in
gamma-encoded sRGB. They do not quantify perceived improvement on the LCD.
The Cover Flow metric covers the square image and excludes the reflection.
The reproducible method and anonymous per-cover values are retained locally
in `out/art-quality/quality-metrics.json`.

## Memory and verification

Astra reviewed both commits and the common 32 MiB 5G allocation. Native
tiles use six decoded slots, an independent owned preview, and a packed
cache of 619 unique covers on 5G (1,157 on Classic). The 603-cover 80GB
library fits the common allocation without using that board's extra RAM.
The final 5G development build has 72,640 bytes of resident headroom
under its 8,167,424-byte resident limit. This is a static linker budget,
not a measurement of runtime stack high-water.

Video and Classic development and release builds passed image verification.
Photo and monochrome 4G release builds also passed. Host package checks
validated mapped catalog identities and CRCs; truncated headers reject
with ValueError. Prepared libraries passed publication readback. LCD
transfer code and AAC decoding were outside this change.

Per-device JSON receipts, timing summaries, and framebuffer PNGs are local
ignored artifacts under `out/art-quality/`. The tested matching firmware
was installed on the flash 5G, 80GB 5G, and Classic with user authorization;
persistent restart checks verify the installed image identity and health.
