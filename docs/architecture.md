# Architecture

Linnet is freestanding native firmware for the PP502x iPod family: Photo
A1099 (`photo4g-p98`, 220 x 176 color), 4G MP102 (`ipod4g-q21`,
160 x 128 monochrome), and Video A1136 30 GB (`video5g-m25`, 320 x 240 color). Host tools prepare media and compile static
TSX layouts; the device uses fixed memory pools and cooperative service work.
There is no runtime JavaScript VM or general-purpose allocator.

## Source map

| Path | Responsibility |
| --- | --- |
| `boot/` | Image validation, slot selection, recovery and loader |
| `kernel/` | Executive, deadlines and service integration |
| `hal/api/` | Portable hardware interfaces used by kernel, services and UI |
| `hal/<family>/`, `hal/codecs/` | Shared SoC implementations, selected audio codecs, startup and linker contracts |
| `targets/` | Target manifests, board wiring, display adapters, policies, native screens and themes |
| `services/` | Storage, media, settings and other native services |
| `apps/`, `ui/`, `themes/` | Applications, renderer and static layouts |
| `config/`, `sdk/` | Build configuration and app/theme authoring |
| `tools/` | CLI, compiler, media preparation, device link and simulator |
| `scenarios/` | Existing device verification scenarios |
| `third_party/` | Codec dependencies, licenses and provenance |
| `docs/` | Architecture, formats, workflows and project notes |

Use a manifest target ID such as `photo4g-p98` or `ipod4g-q21`, `dev`, `trace`
or `release` for build profiles, and `boot` or `os` for image kind. Application/theme identifiers and
configuration keys are defined by their manifests and compiler validation.
RetailOS detection and installation metadata are also target-owned. See
[adding a target](../targets/README.md); compatible new models do not require
installer code changes.

## Boot and updates

Boot validates target, memory bounds and image integrity before entry.
Persistent updates write the inactive slot and publish transactional state;
a candidate becomes confirmed only after memory, core services, storage
resolution, first UI frame and audio-idle readiness. An unconfirmed candidate
falls back to the earlier confirmed slot. Corrupt state enters recovery.
CRC and SHA-256 provide integrity checks, not signature authentication.

P98 entry requires SDRAM initialized by the preceding loader. Cache ownership,
CPU/COP handoff, IRAM reservations and DMA quiescence are part of the hardware
contract: consult `boot/`, the platform linker scripts and `hal/` before changing
startup. A `.los` validation envelope or `.ipod` checksum wrapper alone does
not establish boot compatibility.

Development Boot retains a recovery snapshot and crash record. Timer2 and the
owned COP monitor enforce progress deadlines. A parked inherited COP is not an
active monitor; a COP reset reaches ROM and does not guarantee resident recovery.
RAM replacement requires a verified staging image and stopped transport/DMA.
Release builds exclude the developer transport, injection and screenshot paths;
verify release exclusions with the build tooling.

Native Boot installation uses a device-specific plan and firmware backup,
stages a replacement, checks readback, and publishes the directory last.
Restore uses the original directory sector. Preserve plans, predecessor files
and backups together; see [local artifacts](local-artifacts.md).

Every native Linnet installation preserves a bootable copy of the device's
original Apple firmware. Normal power-on starts Linnet. Holding `MENU`
continuously during the early boot window requests Apple software. Boot verifies
the preserved payload's target, length, SHA-256, and configuration CRC before
handoff; missing or invalid fallback data never replaces the normal Linnet path.

## Runtime and media

The Classic N25 panel resets the controller before configuration and programs
Memory Access Control to `0x00` after the 60 ms Sleep Out delay. The OS retains
a quiesced Boot panel when the persistent handoff CRC and destination build
match and the display controller is ready. This avoids a reset/clear flash
between identical startup frames. RAM entry or an invalid handoff performs full
panel initialization. Normal initialization clears to the startup background;
color bars are reserved for the explicit monitor display diagnostic. Boot and
the OS both present the Linnet OS bird-and-iPod artwork. The OS keeps it visible
while storage resolves the saved theme, before publishing the first home frame
and its normal health readiness. N25 Boot uses size-focused compilation to keep
the artwork and dual-boot code within the existing NOR archive boundary.

The executive schedules bounded work with audio, input and watchdog deadlines.
Storage operations retain buffer ownership until completion or drained cancellation.
FAT validation and write barriers remain active across media workloads. See
[storage compatibility](storage.md) for supported layouts and power policy.

Audio uses native decoders, a PCM ring and DMA. Effects and next-track preparation
share the service budget with media reads. Photos use host-prepared RGB565 tiles,
paged metadata and fixed caches; baseline JPEG fallback is bounded. New photo
work is admitted according to available audio reserve.

Video uses native IPVF, including LZ4/temporal reconstruction and
IMA ADPCM audio. Presentation uses the audio clock. IPVF displays its validated
first frame before scanning the seek index; audio waits for complete index
verification and a 1.5-second decoded video cushion (bounded by the slot limit).
Seeks retain the same cushion. The controls view keeps native video resolution
and caches opaque control bands between data changes. Obsolete display frames
are discarded; low audio reserve reduces display work while decoding every
frame dependency and keeping presentation tied to the audio clock. Device timing
and underrun counters measure playback across media; framebuffer captures
cannot establish physical A/V quality.

The UI compiler emits native C and simulator scenes from constrained TSX.
Legacy layouts use a 220 x 176 reference space scaled to the target LCD.
Targets can own a complete native screen and theme set; M25 uses 320 x 240
coordinates and unscaled fonts. Runtime buffers and prepared media use
target-native dimensions. The desktop
simulator executes the native renderer; its output checks layout and pixels;
use device measurements for hardware timing. See the [SDK](../sdk/README.md).

Binary layouts live in [formats.md](formats.md), [photo-format.md](photo-format.md),
[video-format.md](video-format.md) and [the music format](music-format.md).
Commands and wire contracts live in [device-link.md](device-link.md).
