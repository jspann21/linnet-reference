# Architecture

Linnet is freestanding native firmware. Host tools prepare media and compile
static TSX layouts to C. The device uses fixed memory budgets, bounded service
work, and a native renderer; there is no JavaScript runtime.

## Source map

| Path | Responsibility |
| --- | --- |
| `boot/` | Image validation, slot selection, recovery, and handoff |
| `kernel/` | Executive, deadlines, and service integration |
| `hal/api/` | Portable hardware interfaces |
| `hal/<family>/`, `hal/codecs/` | SoC implementations and audio codec drivers |
| `targets/` | Hardware manifests, board wiring, display adapters, and policies |
| `services/` | Storage, playback, settings, games, and other native services |
| `ui/`, `apps/`, `themes/` | Native renderer and authored presentation |
| `tools/` | CLI, build system, media preparation, Link, and simulator |
| `sdk/`, `scenarios/` | Authoring templates and existing verification scenarios |
| `third_party/` | Imported codecs, notices, and provenance |

Targets select their HAL, memory layout, capabilities, and presentation through
manifests. Photo, Video, and monochrome 4G use PP502x; Classic uses S5L8702.
See the [porting guide](../targets/README.md) for source resolution and validation.

## Boot and updates

Boot validates the image's target, bounds, and integrity before entry. CRC and
SHA-256 detect corruption; they do not provide signature authentication.

Persistent OS updates write the inactive slot and publish redundant state.
A candidate is confirmed after memory, services, storage, UI, and audio readiness.
An unsuccessful candidate falls back to the confirmed image; corrupt state
enters recovery. RAM boot is temporary and does not install an image.

Native installation preserves the original Apple firmware for the MENU startup
chooser. The loader checks its target, length, hash, and configuration before
handoff. Boot installation is separate from an A/B OS update and uses its own
backup-bound procedure. Classic's NOR bootstrap differs from the PortalPlayer
directory installer; see the [bootstrap map](bootstrap-tooling.md).

Startup code depends on target-specific RAM initialization, CPU/COP ownership,
reserved memory, and quiescent DMA. An image passing container checks does not
prove those hardware conditions.

Development and trace images include Link and diagnostics. Release builds remove
the developer transport, injection, screenshot, and crash services; the release
verifier checks their exclusion.

## Runtime and media

The executive schedules bounded work around audio, input, and watchdog deadlines.
Storage retains buffer ownership until completion or drained cancellation.
Filesystem validation and write barriers remain active during media work.

| Service | Runtime approach |
| --- | --- |
| Music | Native decoders feed a PCM ring and DMA; metadata and next-track preparation share a bounded work budget. |
| Photos | Host-prepared RGB565 tiles, paged metadata, and fixed caches; bounded JPEG fallback where available. |
| Video | IPVF on Photo, BCM2722 video on M25, and the native MP4 backend on Classic. Preparation and limits follow the target. |
| UI | Immutable compiled scenes, baked fonts, runtime state, and bounded rendering. Target/profile layouts use the appropriate display geometry. |
| Settings | Validated records and redundant publication; rendering does not write storage. |

The simulator executes the same native renderer and compiled UI definitions.
It checks layouts and pixels, not physical timing, audio, USB, or power.

Next: [SDK](../sdk/README.md), [storage](storage.md),
[binary contracts](formats.md), [media formats](music-format.md), and
[Linnet Link](device-link.md).
