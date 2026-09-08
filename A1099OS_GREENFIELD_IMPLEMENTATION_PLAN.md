# A1099OS Greenfield Implementation Plan

Implementation status: Batch 7 integration is installed; the startup/recovery pass is verified. Full release qualification remains open. The user
authorized deferring remaining Batch 6 video performance, IPVF reuse/standard-format
evaluation, and hardware qualification to PROJECT_TODO.md. Batch 6 is not qualified.
Photo loading speed and
remaining Batch 5 hardware gates are deferred with user authorization. The user authorized
advancing with the remaining Batch 4 qualification and performance work recorded
in [PROJECT_TODO.md](PROJECT_TODO.md). This does not mark the full Batch 4 gate
passed; combined effects, some mixed-codec transitions and the large-library
latency target remain open.

## 1. Mission

Build a new, purpose-built operating system for the iPod Photo A1099 that is:

- Faster and more responsive than any existing firmware on the device.
- Small, deterministic, and power-efficient.
- Easy to build reproducibly with one command.
- Easy to customize through native AOT applications, themes, feature selection, and host-side content tooling.
- A complete media product, not a technology demo: mature music playback, library browsing, playlists, photos, video, settings, storage, power management, USB, recovery, and updates.
- Designed for the A1099 from first principles. Do not preserve another firmware's architecture, APIs, package formats, plugins, themes, database model, or behavioral quirks.

The implementation may use all existing hardware knowledge, measured behavior, algorithms, media expertise, and proven low-level techniques available to the project. Those are inputs to the work, not architectural constraints.

## 2. Non-negotiable design decisions

1. **No JavaScript engine, virtual machine, garbage collector, browser stack, POSIX layer, or general-purpose GUI toolkit in the shipped system.**
2. **System UI and applications are ahead-of-time compiled from a constrained TypeScript/TSX component model to native code.** The device executes native ARM code only.
3. **The kernel is a small event-driven executive, not a conventional threaded OS.** It uses interrupts, deadline queues, bounded service steps, and fixed-priority work.
4. **No general heap after boot.** Use static storage, fixed pools, ring buffers, and resettable per-scene/per-service arenas. Memory ownership must be visible in the linker map and build report.
5. **Audio is the highest-priority workload.** UI, storage scans, image work, USB, and background tasks may never block or starve PCM production.
6. **Expensive content work happens on the host whenever possible.** Metadata indexing, sorting, search indexes, font baking, album-art conversion, photo pyramids, and video conversion are build/sync operations, not interactive device work.
7. **Development support is selected at compile time.** A release image must not contain the developer USB endpoint, protocol parser, upload buffers, trace buffers, synthetic input, screenshot service, developer strings, or chainload code.
8. **No compatibility layers.** New formats and APIs are allowed to be clean, narrow, and target-specific.
9. **Every hardware-facing operation is bounded.** Poll loops require deadlines; queues require capacities; parsers require length checks; persistent writes require transactional publication.
10. **Optimize for measured user-visible latency and battery behavior, not abstraction count or source-code novelty.**

## 3. Target product definition

### Music

The first complete release must provide:

- MP3, AAC-LC/M4A, ALAC, FLAC, Vorbis, WAV, and AIFF playback.
- A uniform native codec ABI with build-time selection and an optional fixed codec arena for nonresident codecs.
- Gapless playback, accurate seek, pause/resume, next/previous, fast track changes, shuffle, repeat, queue editing, playlists, bookmarks, and playback resume.
- ReplayGain, fixed-point equalizer, balance, volume, channel modes, and optional crossfeed when performance permits.
- Album, artist, track, genre, composer, year, playlist, recently played, favorites, and folder views.
- Fast prefix search and deterministic sorting.
- Embedded or sidecar album art, host-prepared thumbnails, and a responsive Now Playing screen.
- Corrupt-file rejection and bounded recovery without taking down the player.

### Photos

The first complete release must provide:

- Albums and folders.
- Thumbnail grids and lists.
- Full-screen display, orientation correction, zoom, pan, next/previous, slideshow, and resume position.
- A host-generated tiled RGB565 photo format for immediate viewing.
- JPEG fallback for files not preprocessed by the host.
- Bounded caches that can be dropped instantly when audio or video needs memory.

### Video

The first complete release must provide:

- A host-transcoded 220x176 video format designed for the PP5020 and LCD path.
- Audio-master synchronization, pause/resume, seek, progress, resume, and clean exit to the UI.
- Required 24/25/30 fps profiles with zero audio gaps and no sustained late frames on qualified media.
- A qualified 60 fps profile for content that satisfies the measured storage and presentation budget.
- Host-side scaling, frame-rate conversion, color conversion, audio resampling, subtitle burn-in, and record packing.

### System

The first complete release must provide:

- Home, Music, Photos, Videos, Files, Now Playing, Settings, About, and recovery/update flows.
- Click-wheel navigation, hold switch behavior, backlight control, battery state, charging state, sleep, wake, shutdown, and safe storage flush.
- FAT32 media access, robust iFlash/ATA behavior, USB storage/sync behavior, safe eject, and deterministic reconnect.
- Transactional settings and user-state persistence.
- Validated image updates with rollback.
- Themes and system configuration that can be changed without editing low-level firmware code.

## 4. System architecture

```text
Host workstation
  ├─ a1099 CLI / reproducible build driver
  ├─ TSX AOT compiler
  ├─ asset and font compiler
  ├─ music database compiler
  ├─ photo compiler
  ├─ video converter
  ├─ simulator and scenario runner
  └─ USB device controller
             │
             │ development build only
             ▼
Developer loader / DevLink
  ├─ image staging and validation
  ├─ RAM chainload
  ├─ A/B slot installation
  ├─ reboot modes
  ├─ logs, metrics, screenshots, crash retrieval
  └─ scripted test control
             │
             ▼
A1099OS
  ├─ startup, vectors, clocks, cache, memory
  ├─ event-driven executive
  ├─ hardware abstraction layer
  ├─ storage and FAT32
  ├─ audio pipeline and codecs
  ├─ library/database service
  ├─ image service
  ├─ video service
  ├─ power and settings services
  ├─ native AOT UI runtime
  └─ generated system applications
```

### 4.1 Boot and recovery

Use two distinct layers:

- **Stage 0 loader:** very small, rarely changed, independently recoverable. It validates and boots the selected OS image, records boot attempts, recognizes a healthy-boot marker, and rolls back a candidate that fails before becoming healthy.
- **Main OS image:** the frequently updated system. Normal development cycles chainload this image into RAM and do not overwrite Stage 0.

The developer loader is a separate build of Stage 0. It exposes DevLink and remains the recovery anchor during development. The release loader contains only validation, selection, rollback, and boot logic.

A candidate image must mark itself healthy only after:

1. Memory and cache initialization complete.
2. Core services initialize.
3. Storage is either mounted or safely declared unavailable.
4. The first UI frame is presented.
5. Audio hardware can enter a known idle state.

A reset before that marker counts as a failed boot and causes rollback.

### 4.2 Event-driven executive

Use a tickless, run-to-completion event loop with fixed priorities:

1. Audio DMA/FIQ refill and audio-clock work.
2. Storage completion and decoder production.
3. Power-critical events and watchdog service.
4. Input events and UI state changes.
5. LCD damage submission.
6. Background indexing, thumbnails, and maintenance.
7. Development transport in dev builds only.

Interrupt handlers do the minimum work needed to capture state, acknowledge hardware, and enqueue a bounded event. Normal service work runs outside IRQ/FIQ context.

Do not create general threads. Each service owns its state and exposes bounded `poll`, `on_event`, or `run_slice` functions. Inter-service communication uses fixed-capacity single-producer/single-consumer queues or immutable snapshots. Avoid general mutexes and shared ownership.

### 4.3 CPU and COP ownership

Treat the two execution units asymmetrically.

**CPU owns:**

- Filesystem and storage policy.
- Audio decoding and DSP scheduling.
- Application state and library queries.
- Power policy and update logic.
- USB control in development builds.

**COP owns:**

- LCD presentation queue.
- RGB565 blits and simple compositing.
- Video frame presentation.
- Optional bounded image scaling or spectrum work when video is inactive.

Communication uses fixed uncached mailboxes and SPSC rings. Never share a heap or arbitrary object graph between CPU and COP. Cache maintenance is explicit at every ownership transfer.

### 4.4 Memory model

Create a build-generated memory plan with named regions:

- Vector/startup and IRQ/FIQ code.
- IRAM hot code and hot data.
- Main text and read-only data.
- Core static state.
- Audio compressed-data ring.
- PCM ring and DMA buffers.
- Storage DMA/aligned buffers.
- Framebuffer and LCD transfer buffers.
- COP queues and video slots.
- Scene arena.
- Codec arena, if enabled.
- Image cache.
- Developer staging/trace areas in dev builds only.
- Crash mailbox in retained/no-init memory.

After boot, general allocation is forbidden. A scene switch resets the scene arena in one operation. Opening a codec resets the codec arena. Image/video caches are explicit and evictable. The linker and build tool must fail when any fixed budget is exceeded.

### 4.5 Native AOT UI

Author system applications in a constrained TypeScript/TSX component model and compile them to native C/ARM objects.

The device runtime contains only:

- Native state structs.
- Dirty-bit dependency masks.
- Generated event handlers.
- Generated paint/update functions.
- A compact fixed component ABI.

There is no runtime parser, dynamic dependency tracker, virtual DOM, CSS engine, or JavaScript execution.

Required native components:

- `Screen`, `View`, `Text`, `Icon`, `Image`.
- `VirtualList`, `Menu`, `Grid`, `Scrollbar`.
- `ProgressBar`, `StatusBar`, `Dialog`, `Toast`.
- `AlbumArt`, `PhotoSurface`, `VideoSurface`.
- `CanvasSurface` for specialized native draw callbacks.

Static geometry is resolved at build time. Dynamic layout is limited to bounded text measurement, virtualized lists, and explicitly supported conditional regions. Styles compile to numeric theme tokens. Only changed rectangles are painted and transferred to the LCD.

### 4.6 Customization model

Use three clean inputs:

- `system.toml`: included apps, codecs, features, defaults, memory budgets, and product identity.
- Native AOT app directories: TSX source, manifest, assets, and declared capabilities.
- Theme packages: colors, metrics, fonts, icons, and approved screen-level tokens.

First-party apps are statically linked and dead-stripped. Add loadable trusted AOT modules only after the static system is stable and measured; do not design the first release around a plugin loader.

## 5. Media and storage design

### 5.1 Music database

Define a compact host-generated `PODB` format containing:

- Fixed-size core records.
- One string pool.
- Precomputed sort orders.
- Artist-to-album, album-to-track, genre, composer, year, playlist, and folder indexes.
- Prefix-search tables.
- Direct media paths and cached cluster/extents where safe.
- Album-art references.
- Gapless, duration, replay-gain, and seek-table metadata.

The database is immutable during normal playback. Ratings, favorites, play counts, bookmarks, queue state, and resume positions go to a small append-only journal. The host compacts the journal during sync; the device may compact only when externally powered and idle.

An on-device scanner is a fallback for files copied without the host tool. It runs incrementally at the lowest priority and publishes a new database transactionally. Interactive browsing must never wait for a full scan.

### 5.2 Audio pipeline

Use the following pipeline:

```text
async storage reads
    → compressed-data ring
    → native decoder
    → fixed-point DSP
    → PCM ring
    → DMA buffers
    → audio codec
```

Rules:

- DMA consumption is the authoritative audio clock.
- Decoder, DSP, and storage work are scheduled by low-water deadlines.
- UI time and wall time never drive audio presentation.
- Track transitions pre-open the next file, pre-read metadata, and prefill decoder state.
- Seek cancels stale I/O by generation number rather than waiting for it to drain.
- Corrupt data returns a bounded error to the player and advances or stops according to policy.
- Audio buffers are never borrowed for UI work.

### 5.3 Photo format

Define `PIMG` as a host-generated package with:

- Correct orientation already applied.
- RGB565 thumbnails.
- Multiple pre-scaled levels.
- Fixed tiles for zoom/pan.
- Optional bounded per-tile compression selected by a host-side cost model.
- A compact index for direct tile reads.

The device chooses the nearest level and fetches only visible tiles. JPEG decoding is fallback behavior, not the normal browsing path.

### 5.4 Video format

Define `PVID` as a sector-friendly container with:

- File header and seek index.
- Keyframe boundaries.
- One bounded record per displayed frame.
- The exact PCM slice associated with that frame or time interval.
- Record types chosen by the host: raw RGB565, repeat previous frame, tile-copy/delta, or simple bounded RLE where it is faster than reading raw data.
- CRCs for headers and optional record groups.

Use triple buffering. CPU reads and prepares the next record while COP presents the current frame. Consumed PCM samples determine presentation time. The host converter rejects encodes whose measured worst-case decode/read budget does not fit the chosen frame rate.

### 5.5 Storage service

The storage service owns:

- ATA/iFlash initialization and transfer modes.
- Aligned DMA/PIO policy.
- Request ordering and coalescing.
- Read-ahead.
- Cluster-chain and extent caches.
- Flush, standby, wake, retry, and quarantine policy.
- FAT32 mount and validation.
- Transactional publication of settings, journals, databases, and images.

Use one storage owner and an asynchronous request queue. Callers receive completion events tagged with generation IDs. Do not let application code issue raw sector operations.

## 6. Development mode with zero release overhead

### 6.1 Build profiles

Provide exactly three build profiles:

| Profile | Purpose | Included development features |
|---|---|---|
| `release` | Normal installed system | None |
| `dev` | Routine hardware development | DevLink, RAM chainload, structured logs, crash retrieval, counters, screenshots, synthetic input |
| `trace` | Difficult timing or corruption faults | Everything in `dev` plus event trace, guard regions, heavy assertions, optional memory dumps |

This is a compile-time selection, not a settings toggle. Use separate source manifests, feature definitions, USB descriptors, linker sections, and memory plans.

The release build must fail verification if it contains any of the following:

- Developer USB interface descriptors.
- DevLink protocol magic or command tables.
- `devlink_*`, `trace_*`, `inject_*`, `screenshot_*`, or chainload symbols.
- Developer staging, trace, or screenshot buffers.
- Structured log dictionaries or debug strings not explicitly approved for release faults.
- Developer-only retained memory sections.

Generate a release-vs-dev map report proving the removal.

### 6.2 DevLink protocol

Implement a transport-independent binary protocol over the working USB COM transport. Keep JSON on the host side only.

Required commands:

- `HELLO`, `INFO`, `STATUS`.
- `IMAGE_BEGIN`, streaming `IMAGE_DATA`, `IMAGE_END`.
- `RAM_BOOT` and `INSTALL_SLOT`.
- `REBOOT_NORMAL`, `REBOOT_RECOVERY`, `REBOOT_DISK`.
- `READ_LOG`, `SUBSCRIBE_LOG`, `READ_METRICS`.
- `READ_CRASH`, `CLEAR_CRASH`.
- `CAPTURE_SCREEN`.
- `INJECT_INPUT`, `CLEAR_INPUT`.
- `RUN_SCENARIO`, `SCENARIO_STATUS`, `ABORT_SCENARIO`.
- `PUSH_FILE`, `PULL_FILE`, `DELETE_FILE` within a dedicated development namespace.
- `MARK`, allowing the host and device trace to share named boundaries.

Protocol requirements:

- Versioned frame header.
- Monotonic sequence numbers.
- Per-frame CRC and complete-image identity.
- Explicit state-changing acknowledgements.
- No automatic repetition of an ambiguous state-changing command.
- Streaming window with periodic acknowledgements instead of one round trip for every small block.
- Resume from the last verified block when safe.
- Build ID and image hash in every boot report.
- Re-enumeration discovery that does not assume the same COM port number.

### 6.3 Crash and rollback behavior

Reserve a small retained crash mailbox containing:

- Build ID and boot generation.
- Reset/fault reason.
- CPU registers and exception state.
- Active service and last event ID.
- Stack bounds and a bounded stack snapshot.
- Last storage request, audio counters, and DevLink command.
- CRC and version.

On reset, the developer loader exposes this mailbox before booting another image. A crashing RAM-loaded image must return to a known developer image after watchdog reset without cable removal or user input.

### 6.4 Host command surface

Create one top-level CLI:

```sh
./a1099 build --profile dev
./a1099 build --profile release --verify
./a1099 device info
./a1099 device cycle --image out/dev/a1099.ipod --suite batches/b03-ui.json
./a1099 device install --slot candidate --image out/release/a1099.ipod
./a1099 device reboot --mode disk
./a1099 device collect --run <run-id>
./a1099 report <run-id>
```

`device cycle` must:

1. Discover and handshake.
2. Capture pre-update state.
3. Stop/quiesce the running image.
4. Stream and verify the new image.
5. RAM-chainload it.
6. Rediscover the re-enumerated device.
7. Verify image identity and boot health.
8. Run the named scenario suite.
9. Collect logs, metrics, screenshots, and crash state.
10. Write one machine-readable run receipt and return a failing exit code on any failed invariant.

## 7. Large-batch development workflow

Device deployment is a milestone operation, not the inner edit loop.

For every batch:

1. Implement the complete vertical slice locally.
2. Compile frequently and run host-side format/compiler checks as needed.
3. Do not upload partial features merely because they compile.
4. Build one integrated `dev` image with a unique build ID.
5. Run static image, memory-map, and release-exclusion checks.
6. Upload and chainload the whole batch once.
7. Run the complete automated device campaign.
8. Collect one structured receipt containing firmware hash, image identity, suite results, counters, timings, screenshots, and crash information.
9. Diagnose all failures together.
10. Make a grouped refinement sub-batch addressing the evidence.
11. Rebuild and repeat the full campaign only when the sub-batch is internally complete.
12. Advance to the next batch only after the gate passes.

An early device upload is allowed only when progress is blocked by an unknown hardware fact that cannot be answered by source analysis, simulation, or existing measurements.

Do not push one-line probes, cosmetic changes, isolated refactors, or unfinished subsystems to the device.

## 8. Implementation batches

### Batch 0 — Greenfield build, loader, and automated hardware loop

**Goal:** Establish a safe, repeatable, no-unplug development foundation before building product features.

**Deliverables:**

- New repository layout and top-level `a1099` build CLI.
- Pinned toolchain manifest and one-command dev/release builds.
- Startup, vector table, linker script, memory report, panic screen, timer, minimal LCD output, and watchdog.
- Developer Stage 0 loader.
- DevLink framing, image streaming, verification, RAM boot, reconnect, reboot modes, logs, status, and crash mailbox.
- Host `device cycle` command and machine-readable run receipts.
- A deliberately crashing test image and a healthy minimal image.
- Release build path with DevLink completely absent.

**Automated device campaign:**

- At least 20 consecutive healthy RAM-chainload/re-enumeration cycles (revised from 50 by the user on 2026-09-05, America/New_York).
- Inject failures before and after the healthy marker and verify automatic return to the developer loader.
- Verify no ambiguous command is repeated automatically.
- Verify disk-mode, normal, and recovery reboot commands.
- Verify release map/binary contains no developer sections, symbols, protocol identifiers, or buffers.

**Manual check:** None.

**Gate:** A developer can build, upload, boot, test, crash, recover, collect evidence, and repeat without touching the cable or device controls.

**Gate result — passed, 2026-09-05 (America/New_York):** 22 healthy cycles were
recorded before the user reduced the requirement to 20. Receipt
`out/runs/20260906T032437Z-photo4g-p98-def6c43d345e-0001/receipt.json` preserves
the original cycle evidence and confirms crash recovery before/after healthy,
watchdog recovery, OS/Boot/Disk Mode reboot, and release exclusion. Qualified
OS build: `def6c43d345e04505644ca7526251f0c9cd5b4ff31d64c1e554cea20c15750fe`;
LOS SHA-256: `3ba716c82c12e63e41d3fd60fe4241ab5730abf3c99c4a98d4915adf3dbceabe`.
Installed Boot build: `e52e94c647bb0d58ed40d7583e84541bf9f4dceb363f75345914360d4f5c4f49`.
The initial native bootstrap needed button restarts; the qualified campaign's
RAM boots, fault recovery and mode transitions completed through USB control.

### Batch 1 — Complete platform core

**Goal:** Build the deterministic hardware and scheduling substrate used by every feature.

**Deliverables:**

- Clock/PLL, cache, SDRAM, IRQ/FIQ, timer, watchdog, and CPU idle.
- LCD initialization, damage rectangles, bounded controller waits, and COP presentation queue.
- Click wheel, buttons, hold switch, headphone detection, backlight, PMU/I2C, battery sampling, charging state, sleep, wake, shutdown.
- Event-driven executive, deadline queue, fixed event pools, service ownership rules, and memory arenas.
- Synthetic input injection and framebuffer capture in dev builds.
- Structured counters for event latency, dropped work, LCD time, IRQ latency, queue high-water marks, and sleep residency.

**Automated device campaign:**

- Synthetic navigation storm with no lost-state or queue overflow.
- Framebuffer CRC/screenshot verification for menus and animations.
- Repeated sleep/wake and backlight transitions.
- COP mailbox wraparound and reset recovery.
- Hold-switch and headphone-state transitions.
- Idle test proving no periodic redraw and no unnecessary fixed-rate polling.

**Manual check:** One physical click-wheel/buttons/hold pass after automation succeeds.

**Gate:** Stable interactive shell foundation, bounded event latency, reliable sleep/wake, and a clean memory/counter report.

**Gate progress — hardware qualified, 2026-09-06:**
Receipt `out/runs/20260906T040313Z-photo4g-p98-815b69a9df3f-0001/receipt.json`
records OS `815b69a9df3f7c0e98e7be66ad653a4a92bf5005177fcadd2a2262c66cddb9d1`,
256 navigation events with zero drops, 1.193 ms maximum event latency, 14 us
maximum C IRQ dispatcher duration, 40 COP animation frames, queue reset,
three sleep/wake cycles and idle without redraw. Initial/final CRCs match.
Development and release builds pass; release exclusion passes. The user confirmed
physical wheel input, Select/Menu, Hold, headphone detection and a clean screen.
Wheel sensitivity was then reduced eightfold and left/right detail navigation
was corrected. The adjusted build `8af5ad4f058c` passed the full campaign in
`out/runs/20260906T042149Z-photo4g-p98-8af5ad4f058c-0001/receipt.json`; maximum
event latency was 2.533 ms with zero drops. The user confirmed the adjusted
wheel and navigation, and a live read verified the exact healthy build and
physical input. The final receipt records hardware qualification; its SHA-256
is `a29d035d39e92f11cba1f48a6719ed5e9ae0fbcdb8ad0826e058cdcf0bdf1b98`.
Automatic guarded eject/reboot passed with exact Boot reconnection in
`out/b01-auto-eject-native.json`.

The subsequent long-press Play/Pause shutdown addition passed development and
release builds, release exclusion and platform regression on OS `20415bc07091`.
The user confirmed short-tap cancellation, power-off that persists with USB
connected, and manual power-on. Evidence: `out/b01-shutdown-qualified.json`.

### Batch 2 — Storage, FAT32, state durability, and persistent updates

**Goal:** Make storage reliable enough that later media work is not debugging on top of uncertain I/O.

**Deliverables:**

- ATA/iFlash bring-up, DMA/PIO policy, deadlines, retries, quarantine, flush, standby, wake, and power-off.
- Asynchronous block queue, aligned buffers, request generations, cancellation, coalescing, and read-ahead.
- Validated FAT32 reader/writer with cluster-chain cache and bounded path handling.
- Transactional settings/journal store with dual headers or dual slots.
- Persistent A/B OS image slots and boot-candidate metadata.
- Safe installer, rollback, update identity reporting, and disk-mode handoff.
- Release USB storage/sync behavior separate from DevLink.

**Automated device campaign:**

- Large deterministic file write/read/readback hash validation.
- Random aligned and unaligned read tests across the volume.
- Injected timeout, short-transfer, reset, stale completion, and flush failure cases.
- Forced reset at every publication stage of settings and candidate image activation.
- Candidate success, candidate crash, rollback, and last-known-good boot.
- USB mount, write, sync, eject, reconnect, and post-USB boot validation.

**Manual check:** One host-visible mount/eject observation if the host OS behavior cannot be fully asserted programmatically.

**Gate:** No corruption, no unsafe activation, deterministic rollback, and storage metrics within the initial budget.

**Offline implementation progress, 2026-09-06:** The iPod is disconnected for
the night. ATA PIO0, the bounded block queue, validated FAT32 access, dual state
records, persistent A/B selection and update publication are implemented for
offline integration. Storage quiescence joins shutdown, sleep and Disk Mode.
Host provisioning and the scratch/fault and persistent-update campaigns are
prepared. Development/release builds and offline checks do not close this gate;
physical disk timing, durability, power transitions, rollback and host sync must
be qualified after reconnection. DMA stays disabled until measured and qualified.

**Installation progress, 2026-09-06:** The corrected CFA/ATA driver mounts the
physical FAT32 volume. Boot `d277fb8fe374` and persistent OS `f22a18828260` are
installed. One approved host elevation performed the guarded native Boot write;
ordinary file provisioning and safe eject followed without another UAC prompt.
The device restarted automatically and reached OS health 31, prepared storage,
and confirmed slot 0 with no pending attempt. A 512-byte scratch write/read/restore
passed with no errors or retries. The user explicitly limited checks to light,
necessary validation; exhaustive, random-read and fault campaigns were not run.
This confirms installation, not the full durability/rollback gate. Startup chain
validation remains slow and requires later performance work. The device-side
native updater timed out during its initial full-partition hash with zero writes;
the host installer was used instead. Evidence: `out/b02-installation-complete.json`.

### Batch 3 — Native AOT UI, system shell, content compiler, and customization

Implementation and device automation completed on OS `3ac3673f2188`:
all nine shell/app screens matched the native desktop oracle, large virtual
list/grid endpoints matched, 202 scene transitions kept arena usage at 188
bytes, and injected events had zero drops. Idle/no-change paint and explicit
canvas animation checks passed. The user's first visual check confirmed clean
text/selection and no artifacts, but found slow scrolling. The revised renderer
reduces ordinary measured list steps from about 290 ms to 92–96 ms using stable
pages and selection-region damage; page changes remain about 257 ms. See
`UI_IMPLEMENTATION.md` and `out/b03-hardware-final.json`. Persistent installation
confirmed slot A with health 31 and no pending candidate or storage errors
(`out/b03-persistent-verified.json`). Revised scrolling was accepted by the user as much better; Batch 3 is complete.
Follow-up: consider velocity-based accelerated scrolling for long collections,
while preserving precise slow wheel control.

Storage follow-up completed before Batch 3: Boot `3dfc7bd0a7b1` and OS
`1767aa1f5e02` add iFlash identification, capability-based HDD/SSD standby,
flush-before-rail-off, bounded cold wake/re-identification, dynamic capacity
reporting and two-window read caching. The installed iFlash ATA1 passed one
light idle/cold-wake/read check. Other hardware remains unqualified; see
`STORAGE_COMPATIBILITY.md`. No exhaustive drive campaign was run per user request.

**Goal:** Deliver the complete application model and responsive shell before media-specific complexity.

**Deliverables:**

- `ipod-photo` pixel target in the TSX AOT compiler.
- Native components, static layout lowering, dirty-bit effects, damage-region generation, font baking, icon packing, and image resources.
- Focus/navigation model tuned for the wheel.
- Virtualized lists and grids with no per-row allocation.
- Home, Settings, About, Files, Music, Photos, Videos, and Now Playing shell screens using placeholder services.
- Scene lifecycle and resettable scene arena.
- `system.toml`, app manifests, theme tokens, theme package compiler, and example custom app/theme.
- Desktop simulator/oracle for generated UI and input tapes.
- Initial host content compiler framework and package manifest.

**Automated device campaign:**

- Large virtual list and grid navigation using synthetic wheel input.
- Screenshot/CRC checks for all shell states.
- App switching and arena reset under memory pressure.
- No-change input proving zero paint work.
- Idle screen proving zero redraw except explicit clock/status deadlines.
- Theme and app rebuild proving one-command customization.

**Manual check:** One visual inspection of typography, focus, wheel feel, and LCD artifacts.

**Gate:** Native shell is fluid, deterministic, allocator-free after boot, and customizable without touching platform code.

### Batch 4 — Complete music product

**Goal:** Deliver a mature, daily-usable music player as one integrated vertical slice.

**Deliverables:**

- Audio codec initialization, sample clock, DMA/FIQ path, PCM ring, underrun recovery, volume, mute, and headphone transitions.
- Uniform codec API and common codec set.
- Fixed-point DSP, ReplayGain, EQ, balance, channel modes, and optional crossfeed behind measured feature flags.
- Async compressed-data buffering, prefetch, accurate seek, gapless transition, next-track pre-open, and stale-I/O cancellation.
- Metadata parser fallback and host-generated `PODB` compiler.
- Device database reader, search, browse indexes, playlists, queue, shuffle, repeat, bookmarks, favorites, play counts, and resume journal.
- Album-art conversion and Music/Now Playing UI.
- Corrupt-file handling and bounded codec failure recovery.

**Automated device campaign:**

- Decoder reference vectors compared by PCM hash and sample count.
- Gapless pairs checked for sample-exact transition and zero underruns.
- Repeated seeks, rapid next/previous, pause/resume, volume changes, and headphone transitions.
- Large-library browse/search/queue tests.
- Corrupt and truncated file corpus.
- Storage wake/sleep during playback.
- Long stress playlist with track transitions across all qualified codecs.
- PCM production, DMA consumption, buffer low-water, and deadline-margin reports.

**Manual check:** One headphone test covering silence/noise, left/right channels, volume range, track transition, seek, and subjective audio quality.

**Gate:** Zero underruns in the qualified campaign, correct decoder output, reliable gapless/seek behavior, and a complete music UX.

### Batch 5 — Complete photo product

**Goal:** Deliver immediate, smooth photo browsing without making JPEG decode the normal interaction path.

**Deliverables:**

- `PIMG` compiler, package reader, thumbnail cache, multi-level tile reader, and visible-tile scheduler.
- Album/folder views, thumbnail grid/list, full-screen viewer, zoom, pan, rotate/orientation, next/previous, slideshow, and resume.
- COP RGB565 blit path and bounded image cache.
- JPEG fallback decoder with memory and time limits.
- Corrupt-image handling and cache eviction under audio pressure.

**Automated device campaign:**

- Large photo-library browsing and synthetic rapid scroll.
- Random zoom/pan/next/previous sequence with screenshot checks.
- Cache-thrash and low-memory scenarios while music continues.
- Corrupt PIMG/JPEG corpus.
- Slideshow timing and sleep/backlight interaction.

**Manual check:** One image-quality and visible-artifact inspection.

**Gate:** Preprocessed images appear immediately, navigation remains responsive, and photo work never disturbs audio.

### Batch 6 — Complete video product

**Goal:** Deliver synchronized full-screen video using a device-native container and bounded presentation pipeline.

**Deliverables:**

- `PVID` specification, host converter, cost model, seek index, and validation tool.
- Raw/repeat/tile-delta/RLE record support selected by the host.
- Triple-buffered storage path, COP presentation, audio PCM ring integration, and sample-count presentation clock.
- Video UI, pause/resume, seek, progress, resume, exit, and error handling.
- Qualified 24/25/30 fps profiles and an optional 60 fps profile.
- Trace counters for read time, prepare time, present time, late frames, audio gaps, queue depth, and cache maintenance.

**Automated device campaign:**

- High-motion, low-motion, repeat-heavy, scene-cut, and seek-heavy clips.
- Exact frame CRCs at selected checkpoints.
- Zero-gap PCM accounting and bounded A/V drift.
- Repeated start/stop/seek/exit cycles.
- Storage wake, low-memory, and corrupted-record cases.
- Simultaneous UI overlay/progress updates without presentation starvation.

**Manual check:** One tearing, motion quality, and lip-sync observation on representative clips.

**Gate:** Required frame-rate profiles complete without audio gaps or sustained late frames, and exit returns the system to a clean audio/UI state.

### Batch 7 — Product integration, power, hardening, and release qualification

**Goal:** Convert the completed vertical slices into a polished, fast, recoverable release.

**Deliverables:**

- Unified navigation, settings, resume, error screens, low-battery behavior, charging behavior, safe shutdown, and USB transitions.
- Complete update/rollback UX.
- Final theme/app templates and build configuration. Copyable static starters and
  Batch 7 instructions are now in `sdk/templates/` and `sdk/README.md`;
  device and release qualification remain separate gates.
- Performance-driven IRAM placement, cache policy, clock scaling, storage power policy, LTO/dead stripping, and asset packing.
- Release fault screen and minimal field diagnostics that do not include DevLink.
- Final release image, loader, content tools, and installer.

**Automated device campaign:**

- Mixed-use scripted journey across music, photos, video, settings, sleep/wake, USB, update, rollback, and low-battery simulations.
- Repeated app transitions and memory-pressure cycles.
- Parser and transaction fault corpus.
- Release-only run proving the same core behavior without development services.
- Map and binary proof that all development code and memory are absent.
- Final boot, input-to-pixel, app-open, library-query, track-start, seek, photo-open, and video counters.
- Direct comparison against the project's measured performance baselines.

**Manual check:** One complete user journey, charging/unplug behavior, physical controls, audio, photos, and video.

**Gate:** Release acceptance criteria pass, no developer overhead remains, and the measured system meets or beats the performance goals below.

## 9. Initial performance goals

Treat these as engineering budgets. Measure from Batch 0 onward and tighten them when hardware data supports it.

- First interactive UI frame from main-image entry: target at or below 1 second.
- Button/wheel event to visible LCD change: within one 60 Hz frame for normal UI updates; p99 below 35 ms.
- Interactive UI work: p99 below 12 ms excluding LCD controller transfer.
- Idle UI: no redraw and no periodic wake unless a visible clock/status deadline requires it.
- Warm screen/app transition: target below 100 ms.
- Indexed library open and common browse queries: target below 100 ms.
- Prefix-search first results: target below 75 ms for the qualified large-library corpus.
- Cached/prepared track start: target below 250 ms; cold start target below 500 ms.
- Gapless transition: zero inserted/dropped PCM samples for qualified pairs.
- Playback campaign: zero PCM underruns.
- Preprocessed photo first visible result: target below 150 ms.
- Required video profiles: zero audio gaps and no sustained late frames.
- Release developer overhead: exactly zero bytes of developer code/data and zero runtime service work because it is not linked.

Do not claim a target is met from simulator results. Device receipts are authoritative.

## 10. Testing policy

Create tests only where they prevent expensive device debugging or protect critical data/timing invariants.

### Required host tests

- AOT compiler lowering, memory planning, and deterministic output.
- DevLink framing, sequence handling, CRC, ambiguous-command behavior, and reconnect logic.
- Image validation, boot selection, healthy marker, and rollback state machine.
- FAT32 and transactional state/database publication.
- `PODB`, `PIMG`, `PVID`, theme, and app-package parsers.
- Codec reference vectors and metadata bounds.
- Host content compiler determinism.

### Required device tests

- One integrated machine-readable scenario suite per batch.
- Targeted fault injection for storage, boot, audio deadlines, queues, and media corruption.
- Minimal physical checks only where software cannot prove the result: wheel feel, analog audio, LCD artifacts, charging, and A/V perception.

### Do not create

- Unit tests for trivial wrappers, getters, constants, or obvious generated code.
- Broad test scaffolding before a real invariant exists.
- Duplicate simulator suites that do not correlate with device behavior.
- Snapshot tests for cosmetic details that are expected to change frequently during design.

## 11. Documentation policy

Keep only documentation required to build, preserve contracts, or prevent destructive mistakes:

1. Root `README.md`: exact build, device-cycle, release, install, restore, and recovery commands.
2. `ARCHITECTURE.md`: service ownership, event priorities, memory regions, CPU/COP contract, and non-negotiable invariants.
3. `DEVLINK.md`: wire protocol, state-changing command rules, recovery behavior, and host CLI.
4. `FORMATS.md`: canonical binary contracts for OS image metadata, PODB, PIMG, PVID, app manifests, and themes.
5. This implementation plan, updated only at batch gates.

Do not create per-directory READMEs, speculative design documents, duplicate API references, migration guides, compatibility notes, or prose status reports. Device run receipts are generated data, not documentation.

## 12. Repository layout

```text
a1099os/
  boot/                 stage 0, startup, vectors, linker scripts, rollback
  hal/                  PP5020, LCD, wheel, PMU, ATA, USB, audio codec
  kernel/               event loop, deadlines, queues, arenas, watchdog
  services/
    storage/
    state/
    audio/
    library/
    image/
    video/
    power/
    update/
  ui/
    compiler-target/    iPod pixel backend for the TSX AOT compiler
    runtime/            tiny native component ABI
    system/             generated shell and first-party apps
  apps/                 customizable AOT application sources
  themes/               theme sources and compiled assets
  formats/              shared host/device binary definitions
  tools/
    a1099/              top-level CLI
    content/            PODB/PIMG/PVID/font/theme compilers
    device/             DevLink transport and scenario runner
    inspect/            image, map, memory, and release-exclusion checks
  scenarios/            one integrated device suite per implementation batch
  config/               system.toml profiles and memory budgets
  out/                  generated artifacts and run receipts
```

Avoid a generic `common` dumping ground. Every source file must belong to a clear owner and build profile.

## 13. Codex execution rules

- Execute batches in order. Do not begin the next product subsystem before the current gate passes.
- Build a clean architecture directly. Do not preserve or wrap old APIs, packages, databases, themes, plugin systems, event models, or runtime assumptions.
- Existing implementation knowledge may be consulted for hardware facts, algorithms, constants, timing behavior, and failure cases. Translate that knowledge into the new interfaces; do not make the new system structurally dependent on the source it came from.
- Prefer the smallest design that satisfies the current batch and the stated final product. Do not add a generic abstraction for hypothetical future devices.
- Keep hardware MMIO inside `hal/`. Generated apps and services do not access registers directly.
- Keep state ownership explicit. Do not introduce shared mutable global state outside the kernel/HAL contracts.
- Every queue, buffer, string, list, parser, and loop has a fixed bound or deadline.
- Do not allocate after boot except inside explicitly resettable arenas whose maximum size is fixed at link/build time.
- Do not put logging, assertions, upload buffers, screenshots, synthetic input, or trace work behind a runtime `if (dev_mode)`. Exclude it from release at compilation and linking.
- During a batch, compile and inspect locally as often as needed, but do not upload incomplete fragments to the iPod. Upload at integrated batch or refinement-sub-batch boundaries.
- When a hardware run fails, collect the full receipt and diagnose the failure class before changing code. Group related fixes and rerun the complete batch suite.
- Do not write documentation or tests beyond the policies above.
- Do not optimize unmeasured code. Add a counter, capture a device receipt, then optimize the observed bottleneck.
- Preserve a known-good developer loader and never make ordinary `device cycle` replace it.
- A state-changing USB command with an ambiguous acknowledgement is never repeated automatically. Reconnect and inspect identity/state first.
- A batch is complete only when its device gate passes and the run receipt is saved with the exact build hash.

## 14. Definition of done

A1099OS v1 is complete when:

- A clean release image boots reliably and rolls back failed updates.
- The release image contains no developer transport or instrumentation code/data.
- Music, photos, and video meet the product definition and device gates.
- Physical wheel, audio, LCD, charging, sleep/wake, USB, and update behavior are qualified.
- The top-level CLI can reproduce the release and all host content tools from a clean checkout.
- A developer can edit a TSX app or theme, run one build command, and deploy/test it over USB without unplugging or manually rebooting the iPod.
- A full native-image development cycle can upload, chainload, rediscover, test, diagnose, and recover without manual intervention.
- Device measurements demonstrate the required responsiveness, media stability, and power behavior.
- The architecture contains no compatibility code or unused general-purpose subsystem that does not serve the A1099 product.

## 15. First Codex assignment

Begin with **Batch 0 only**.

Create the new repository skeleton, build profiles, minimal startup/LCD image, developer Stage 0 loader, DevLink protocol, host `a1099 device cycle` command, crash mailbox, healthy-boot marker, and release-exclusion verifier. The first hardware milestone is not a media screen. It is a reliable automated loop that can repeatedly RAM-boot a healthy image, deliberately crash another image, return to the developer loader, retrieve the crash record, and continue without cable or button intervention.

Do not begin storage, the full UI compiler target, audio, photos, or video until that loop passes its Batch 0 gate.
