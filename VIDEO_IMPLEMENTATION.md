# Linnet video implementation

## September 7 spatial playback (bounded device runs; throughput gate open)

The optional PVID version2 repacker reuses IPVF's independent raw LZ4 block
approach while preserving PVID's little-endian RGB565 frames, exact48kHz PCM,
and mandatory header/index/record/payload/decoded-frame CRCs. Version1 files
remain readable and normal compilation still emits version1. Version2 adds
independent type4 frames; older readers reject its header safely. Direct IPVF
container support would additionally require its IMA audio, rational sample
clock, byte order, index and integrity contracts, so it is not enabled here.

`tools.content.video.repack_spatial(source, output)` validates a canonical v1
file and atomically writes v2, replacing a record only when LZ4 saves complete
sectors. The native decoder expands directly into the existing building slot,
with at most2048 bytes of copy/length work per slice and the existing500us
cooperative batch. It allocates no additional frame or compressed-record buffer.
Pending I/O cancellation and held display-frame ownership remain unchanged.
Compressed payload lengths can place PCM at odd byte offsets. Those records use
explicit byte reads into an aligned256-byte stack slice before HAL submission;
partial or zero acceptance preserves the source bytes for retry. Aligned PCM
retains the existing direct submission path. This adds no resident BSS.

The prepared12-second sample at `out/b07-video-spatial/clip.pvid` is12,223,488
bytes versus19,265,024 bytes, with maximum record51,200 versus85,504 bytes.
All288 RGB565 frames and PCM intervals match the source;265 compressed blocks
also pass the independent IPVF reference decoder. See `repack.json` and
`host-validation.json` in the same directory. These are storage-size and host
correctness results; they do not establish sustained device throughput.

The unchanged v2 sample was subsequently published and read back successfully
(`out/b07-video-v2-published.json`). On c714, the valid bounded normal run
presented51 frames with47 audio underruns; no-LCD presented56 with32 underruns
(`out/b07-video-v2-baseline-device.json`). Both remain failed throughput gates.
The maintained-span LZ4 change removes per-copy software division without extra
state or a larger decode budget. On8b9, warm normal playback presented57 frames
with53 underruns and269,312 inserted silence frames, versus51/47/281,600 on c714.
The normal decode maximum fell from95,966 to42,515 microseconds. Underrun count
increased while inserted silence fell by0.256 seconds; playback still fails the
sustained gate. Both used80MHz and the unchanged v2 package, but the firmware
also includes other changes (`out/b07-video-span-device.json` and
`out/b07-video-span-analysis.json`). These are bounded results, not an isolated
whole-system speedup or a passing A/V qualification.

Development command123 (`VIDEO_MEASUREMENT`) accepts exactly two u32 words:
current recovery generation and mode0(disarm),1(normal presentation), or2(no
video presentation). Admission requires inactive, drained video. It arms only
the next ordinary video open, forces frame0, preserves saved resume, and stops
through normal cancellation/draining after8seconds of playback or8seconds of
preparation. Seeking is rejected during the measurement. Mode2 advances due
frames using the same consumed-PCM clock but offers no video asset and causes
no frame-by-frame UI revision. VIT6/version2 `presented`/lateness then describe logical
frame acceptance, not actual LCD completion. Normal shell redraws may still
occur. Release firmware excludes this command and service mode.

Use `Session.video_measurement(generation, mode)` and ordinary Videos entry to
compare the identical package from frame0 in mode1 then mode2. Capture VIT6/version2 and
audio state before/through/after each bounded run; compare read bytes/operations,
record-read time, decode/CRC stages, prepared frames and audio gaps. First compare
the existing v1 package, then the v2 candidate with the same procedure. The
integration task owns all firmware builds, publication and physical tests.
Keep the three render buffers until measured throughput justifies a separate
bounded audio/read cushion within the resident-memory limit.

Batch 6 is implemented for initial qualification, not hardware-qualified.
`PVID_FORMAT.md` defines the bounded container. Studio converts an existing video
with ffmpeg to 220x176 RGB565 and exact 48 kHz stereo PCM slices. Raw, repeat,
tile delta and RLE records are selected by a declared cost model. Default costs
are estimates; they do not qualify a frame-rate profile on an iPod.

```
python linnet video compile --source clip.mp4 --output out/video/clip.pvid --fps 24 --max-frames 240
python linnet video inspect out/video/clip.pvid
```

Publication uses `video publish` with package, disk number, disk serial, volume
serial and optional expected drive. It preserves and verifies the previous file,
then replaces `/LINNET/VIDEOS/CURRENT.PVD`. The initial UI opens this one prepared
video. Publication is unelevated; safe eject/restart uses the existing bound helper.

The native engine retains three frame buffers and one bounded record workspace.
CRC checks and frame preparation run in slices. Record validation hashes the
actual 32-byte header and at most 511 padding bytes, then combines those with
the independently observed payload CRC using exact IEEE CRC32 concatenation.
The payload is scanned once in at most 4096-byte slices. Both the complete
record CRC and declared payload CRC must pass before decode can modify any
record or frame bytes; decoded-frame CRC remains mandatory before PCM or frame
publication. Declared CRC fields are never substituted for observed bytes.
`tools/content/video_crc_tables.py` regenerates the checked-in immutable
`services/video/crc_shift_table.h`: 17 byte-shift powers occupy 2176 bytes in
ordinary read-only storage, with no runtime initialization or extra IRAM table.
One additional 32-bit video state field retains the header/padding contribution.
The existing 500-microsecond batch limit and cancellation checks remain intact;
individual bounded slices can exceed that soft batch limit. Record-CRC timing
now measures header/padding preparation; payload-CRC timing includes the final
composition and both checksum comparisons. Compare the combined stages across
builds rather than interpreting either stage alone as the whole validation cost.
Delta records always refer to the
previous decoded frame. Offered frames remain stable until the runtime accepts a
COP display snapshot. Consumed PCM samples schedule frames; display acceptance
is counted separately from decoding. No frame-rate guarantees are inferred from
successful compilation or host conversion.

Videos: Select opens/resumes the prepared video, Play/Pause pauses, left/right
seek ten seconds, wheel adjusts volume, Select toggles progress/controls, and
Menu exits. Long Play/Pause shutdown still applies. Playback keeps the backlight
awake. Video acquires audio only after music and photo storage ownership drains.
Exit/cancel drains reads and stops audio before returning ownership. A failed
HAL stop keeps video ownership rather than allowing another audio producer.

LDS3 settings keep the existing 32-byte envelope overhead. Header bytes0..3 are
LDS3;4..5 music payload length;6 timeout-choice index;7 zero. Bytes8..19 contain
the photo identity32/index16/flags8/reserved8/pan32,20..27 video identity32/frame32,
then music payload at28 and final CRC32. Old LDS1/LDS2 and unwrapped music records
remain readable. The current maximum music payload444 gives476 bytes total.
Photo flags pack zoom bits0..2, rotation3..4 and view5..6. Video identity is the
validated PVID header CRC. Resume is saved on exit and normal shutdown; EOF resets
the next starting position. Older firmware cannot interpret LDS3.

Read-only development command122 (`VIDEO_STATE`) returns128 bytes, magicVIT6,
version2 (the host also reads version1/96 bytes). Fields: magic,version,phase,error,active,pending,paused,next_frame,
frame_count,front_frame,read_ops,read_bytes,prepared,presented,late_frames,
max_late_samples,max_prepare_us,queued_frames,max_queued_frames,audio_underruns,
audio_silence_frames,audio_fault,submitted_samples,revision,max_io_us,
max_record_read_us,max_record_crc_us,max_payload_crc_us,max_decode_us,
max_frame_crc_us,max_step_us,min_audio_queued. `video-state` is
available through the device CLI. Release firmware excludes this Link command.

Still required: passing 24/25/30fps hardware measurements, optional60fps decision, corrupt
record coverage, A/V drift/lip-sync/tearing checks, seek/pause/exit/resume cycles,
and storage wake/low-memory checks. Additional read/presentation/cache timing
instrumentation and a device-measured cost model remain to be completed. Use only
bounded storage qualification. The earlier persistent-installation blocker was
superseded by successful native installation and post-eject startup receipts
(`out/b07-usb-native-installed.json` and
`out/b07-video-v2-post-eject-inspection.json`). Full power-removal and release
journeys remain separate qualification work.

Validation reports: `out/b06-integrated-dev.json`,
`out/b06-integrated-release.json`, and `out/b06-simulator-command.json`.
Development resident memory is approximately3.94MB, below the4MiB limit.
These reports do not qualify real playback.

The user authorized a clip from the supplied Mr. Brightside video. A12-second
24fps package exercises all four record types; every frame and seek/resume result
passed the native host comparison (`out/b06-video-sample/native-host.json`).
The first hardware runs decoded without content errors but starved audio; the
warm run sustained only about7fps. They are failed qualification, recorded in
`first-device.json` and `warm-device.json`. Performance work targets index-page
caching, bounded word copies, CRC throughput and measured storage admission.

## IPVF comparison and current bottlenecks

The user supplied the earlier work at `../ipod/tools/ipvf`. Its README and
qualification records document spatial LZ4 RGB565 video with adaptive IMA audio,
sector-aligned records, cached reconstruction, three render slots and a separate
audio cushion. The recorded Rockbox music run completed 240 frames at 30 fps
without late frames or audio gaps. A later cached spatial run completed 1,148
frames at 24 fps without late frames, gaps, rebuffers or errors. These are evidence
for those Rockbox builds, not qualification of Linnet. Dense temporal modes and
general 60 fps playback are not justified by the same results.

Reuse direction: start from the spatial compression, buffer ownership and audio
prebuffering techniques rather than expanding the uncompressed PVID design.
Evaluate IPVF interoperability before defining another container revision.
Any integration must use Linnet's bounded native storage/audio/display services;
the Rockbox plugin runtime is not part of this design. Account explicitly for
IPVF's RGB565 byte order, rational cadence, 44.1 kHz IMA audio, 96 KiB maximum
record and key-only index. A standard container alone does not establish that
its decoder and I/O requirements fit this device. No Linnet standard video codec
has yet passed a hardware throughput gate.

The current PVID hardware runs remain failed qualification. Bounded polling and
word copies reduced some preparation costs, but motion record reads still take
hundreds of milliseconds. `out/b06-video-sample/platform-after-memory.json`
records a 124,356 us maximum LCD presentation time. The resident COP display
worker returns through the whole monitor after every two pixels; this cost also
affects compressed content. An optional Batch 6 RAM helper now groups at most 32
FIFO-checked pixel pairs per call. Its installer accepts only the exact preserved
Boot worker, parks it before copying, verifies its payload and single branch
patch, and leaves unknown workers on their existing path. This is a RAM-only
optimization. Bounded hardware measurements are recorded in
`out/b06-video-sample/blit-device.json`; they did not close the video gate and
do not isolate a helper speedup from the other changes in that run.

Local references: `../ipod/tools/ipvf/README.md`,
`../ipod/tools/ipvf/qualification/2026-08-31-hardware-runs.md`, and
`../ipod/tools/ipvf/qualification/2026-09-01-cached-spatial-copy-runs.tsv`.
