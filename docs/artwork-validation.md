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

## Classic home pane follow-up

After the user confirmed smooth home highlight and triangle scrolling on
the 6G, its home artwork was changed to fill the right pane below the
status bar. The square cover is drawn at 216 px and centered in the
160 by 216 px pane, cropping 28 display pixels from each side. This
replaces the reflection area with the continuing cover image.

Classic development and release builds and the Video release build passed
verification. A 6G framebuffer capture confirms that artwork reaches the
bottom of the pane; 32 alternating home wheel events again had zero drops.
The change reuses the existing artwork and framebuffer buffers.
Local evidence is under `out/art-quality/cropped-com11/`.

## Arbitrary song preview follow-up

Performance testing found that Songs could open album 01 while Cover Flow
still selected album 12, leaving a placeholder during disk audio startup.
The preview bridge previously checked only the selected catalog row.
It now checks that row first, then scans the bounded set of published
resident rows for the requested artwork path and CRC. An independent
preview can also publish while an older full-cover read drains.

On the rotating 30GB 5G, the baseline capture still lacked artwork while
audio was OPEN at 1.5 seconds and PRIME at 3 seconds. Full artwork appeared
by the 4.7-second observation. With the repair, the first requested-song
capture already contained its cover during PRIME, with Cover Flow still
on album 12. Four replacement selections also displayed their matching
cover after the new player generation published, with zero audio underruns.
These timings include Link capture and observation overhead.

Astra's review confirmed library identity, exact path/CRC matching,
published catalog tags, validated tiles, and pending-read buffer ownership.
The repair adds no memory or cache slots. Its immediate preview applies
to resident mapped album covers; uncached covers and differing per-track
artwork continue through the full artwork reader. Audio startup admission
and LCD transfer behavior remain as before.

Local receipts and captures are under `out/art-quality/arbitrary-before-correct/`,
`arbitrary-after/`, and `arbitrary-switches-published/`.

The repair was persistently installed and restarted healthy on the rotating
30GB 5G and Classic 6G. Classic's arbitrary Songs selection was checked with
Cover Flow left on its last album: the published song's cover and the filled
home pane were correct. Both devices completed 32 home wheel events with zero
drops; the captured Classic highlight top edge was one continuous color across
all 160 menu pixels. The user had confirmed physical 6G scrolling smoothness
before this follow-up; these additional checks establish framebuffer geometry.

Classic temporarily lost Link after an accepted RAM boot while its screen
still showed Linnet home. A physical restart restored USB enumeration and Link.
The subsequent persistent installation and restart reported healthy; the
transport interruption was not attributed to the artwork repair. Classic
evidence is under `out/art-quality/arbitrary-classic-installed/`.
