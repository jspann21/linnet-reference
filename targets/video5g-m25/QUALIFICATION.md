# M25 qualification

Scope: A1136 MA146, 30 GB, 32 MiB RAM. These are recorded checks on that hardware,
not a claim that every later build or storage variant has passed them.

Link observes firmware state, counters, and framebuffers. Physical sound,
controls, LCD appearance, and electrical measurements require separate observation.

## Exercised behavior

| Area | Evidence |
| --- | --- |
| Startup and updates | Native Boot, RAM and persistent OS entry, candidate confirmation, deliberate-crash rollback, and publication fault boundaries |
| Display and input | CRC-checked 320 × 240 captures, completed presentations, synthetic wheel/button checks, and physical control confirmation |
| Audio | Stereo headphone output; PCM, MP3, FLAC, ALAC, AAC/M4A, and Vorbis samples; sample-rate and seek checks |
| Video | H.264 Baseline and MPEG-4 Simple Profile playback, pause/resume, keyframe seeking, EOF, and display restoration |
| Photos | Fit, zoom, rotation, and slideshow |
| Storage | Verified host roundtrip, random reads, bounded file growth, settings restoration, and existing injected faults |
| Power scheduling | Timed sleep/wake, backlight response, and idle redraw checks |
| Host builds | Target build, memory, simulator, and release-exclusion checks |

Video presentation and screen readability were physically observed. Headphone
output, wheel/buttons, Hold, and headphone sensing were also confirmed.
These results are sample coverage, not exhaustive codec or physical acceptance.

## Remaining qualification

Earlier Windows USB descriptor loss during **Apple Disk Mode** was reported with
a cable that has since been replaced. The user reports no recurrence; three
additional native Disk Mode roundtrips returned to the same healthy OS. Direct
Apple-mode cold/manual entry comparison and recovery injection were not
performed.

Charging current/source transitions, dock output, release-image operation, and
long-duration or large-library workloads remain open. The complete actionable
list is the [roadmap](../../docs/roadmap.md); the native video boundary is in
[NATIVE_VIDEO.md](NATIVE_VIDEO.md).

Keep exact build identities, media inventories, device identifiers, images,
and recovery receipts in [local artifacts](../../docs/local-artifacts.md).
