# Adding an iPod target

Linnet calls one hardware model a **target**. A target owns identity, memory,
display, media, discovery and installation data in one manifest. Native sources
follow fixed paths, so adding a model does not require another build table.

## Current targets

| Target | Hardware and display | Status |
| --- | --- | --- |
| `photo4g-p98` | iPod Photo A1099, PP5020, 220 × 176 color | Primary development target |
| `video5g-m25` | iPod Video A1136 30 GB, PP5022 family, 320 × 240 color | Native Boot and development OS verified over USB Link |
| `ipod4g-q21` | iPod 4G MP102, PP5020, 160 × 128 monochrome | Photos, video and theme selection disabled by the manifest |

All targets expose their installation profile through the same Media Manager. M25 is in hardware bringup; see its target README for verification status.

## Repository contract

The portable firmware interfaces live in `hal/api/`. Kernel, service and UI
code include only these headers. Each `hal/<family>/` directory implements the shared SoC interfaces and startup.
`hal_family` selects that implementation independently of the actual `soc`.
Board wiring, display adapters, quirks and native presentation live in
`targets/<target-id>/`. Codec drivers live in `hal/codecs/` and are selected by
`audio_codec`; they never assume the board that happens to use them.

```text
hal/
  api/                  portable firmware interfaces
  pp502x/               common PP5020/PP5022 CPU, ATA, USB and input
  pp5022/               PP5022-only PHY sequence
  codecs/               selected audio codecs
targets/
  <target-id>/
    target.toml         complete target description
    hardware.h          board policy constants and ROM restart address
    device.c            board wiring and power hooks
    lcd.c               LCD controller driver
    lcd.h               optional private LCD declarations
    display.c           target display adapter
    screens/<app-id>/screen.tsx  optional complete native screen set
    themes/<theme>/      optional target-native themes
    presentation.toml   optional clock font and reference-layout adjustments
    system.toml         optional target-specific default content
    native_update.c     optional audited firmware maintenance implementation
```

When `display.c` is absent, the build uses `hal/<family>/display.c`. The loader also
resolves `startup.S`, `memory.ld` and `platform.c` by convention. Manifests do
not contain source-file lists.

The build derives the C target macro from the target ID and generates
`linnet_target.h`. That header carries target identity, display and media sizes,
storage limits, memory bounds and capabilities into native code. The manifest's
CPU, architecture and endianness select the compiler target and flags; the
linker script consumes its SDRAM and mailbox contract.

## Add a model

Create `targets/<target-id>/target.toml` and the conventional native files. Use
[Photo P98](photo4g-p98/target.toml) or
[monochrome Q21](ipod4g-q21/target.toml) as a complete field reference. Use a
lowercase, hyphenated ID matching the directory name and choose a unique
`image_target` integer. `LINNET_TARGET_<ID>` is generated automatically.

| Fields | Purpose |
| --- | --- |
| `id`, `name`, `aliases`, `image_target` | CLI identity, display name, aliases and image compatibility number |
| `board_id`, `model_alias`, `soc`, `cpu`, `architecture`, `endianness` | Hardware identity and build selection |
| `sdram_bytes`, `os_capacity_bytes`, `entry_address`, `load_address` | Native memory and image contract |
| `stage_address`, `stage_bytes`, `recovery_snapshot_address`, `recovery_snapshot_bytes`, `mailbox_address`, `mailbox_bytes` | Update, recovery and retained-memory regions |
| `storage_max_read_sectors` | Largest bounded storage read used by media code |
| `lcd_width`, `lcd_height`, `lcd_format` | Physical display geometry and pixel format |
| `media_photo_width`, `media_photo_height` | Native prepared-photo viewport |
| `media_video_width`, `media_video_height`, `media_video_fps`, `media_video_color` | Native prepared-video profile |
| `capabilities` | Per-target feature restrictions; explicit `false` disables a feature |
| `cop_display` | Whether to include the SoC's COP display worker |
| `[ui]` | Optional allowed themes and required default theme |

The loader rejects unknown fields, invalid dimensions, media geometry outside
the display, a video frame larger than the storage read window, missing native
sources, duplicate IDs and malformed profiles. These checks establish a coherent
build description; they do not prove hardware behavior.

Existing targets may use the shared 220 × 176 reference screens. A target with
a `screens/` directory must provide every selected app at its actual LCD size,
with `native` theme layouts. Missing screens fail compilation; there is no silent
reference-screen fallback. M25 uses 29 native 320 × 240 screens and three local
themes. Native font pixels are retained. Legacy layout adjustments belong in
`presentation.toml`, not target-name branches in the compiler.

`[resources]` declares title-cache placement and cover-flow catalog capacity.
The loader checks these against recovery capture and mailbox reservations, and
the linker checks the final SRAM/SDRAM bounds. Board policy in `hardware.h`
selects bounded clock settling, ATA write/flush behavior, ROM restart markers
and documented storage quirks. Services consume capabilities and policy rather
than naming a board.

The Photo COP LCD worker and blitter belong to the Photo target. Its legacy
firmware maintenance writer is also target-local and retains its exact reviewed
unit checks. Targets without an audited native writer reject those commands;
ordinary A/B OS updates are shared. Never copy a specimen serial into another
target or weaken those checks to make an unsupported writer run.
New resolutions up to 1024 per side and 131,072 pixels are accepted, subject to
memory and media read bounds. Inspect every new resolution in the simulator and
on hardware for text fit and visual quality.

For another PP5020 iPod, reuse `hal/pp502x/` and add the target's LCD and device
files. Add a target `display.c` if its scanout arrangement differs from the SoC
default. For another SoC, implement the headers in `hal/api/` under a new
`hal/<soc>/` directory; portable kernel, service and UI includes stay unchanged.

## Discovery and installation

Populate `[retail]` with observed USB VID/PID and exact board or model strings
from `iPod_Control/Device/SysInfo` and USB enumeration. Keep serial numbers,
hardware GUIDs and firmware backups local. Regulatory labels and volume names
are not sufficient detection keys.

Start `[installer]` with `enabled = false`. All installer fields remain required
so the profile is reviewable before enabling it. Only the `ipod-directory` boot
layout can currently be enabled. Verify the wrapper, firmware directory, memory
and disk bounds on the actual device before changing `enabled` to true. See
[local artifacts](../docs/local-artifacts.md) and the
[Media Manager guide](../docs/media-manager.md) for the operational workflow.

## Validate a port

Run these commands from the repository root, replacing the placeholders with
the new target and its observed USB serial:

```console
python -c "from tools.studio.targets import TARGETS; print('\n'.join(TARGETS))"
python linnet doctor
python linnet ui compile --system out/new-model-system.toml --output out/ui-new-model
python linnet simulator --system out/new-model-system.toml --output out/simulator-new-model
python linnet build --target NEW_TARGET --profile release --kind os --verify
python linnet build --target NEW_TARGET --profile dev --kind boot --device-serial YOUR_SERIAL --verify
python linnet build --target NEW_TARGET --profile dev --kind os --device-serial YOUR_SERIAL --verify
```

For the content commands, copy `config/system.toml` to
`out/new-model-system.toml` and set `[system] target` to the new ID. Pass the same
file to an OS build with `--system` when its app or theme selection differs from
the repository default.

Build and simulator results cannot establish hardware compatibility. On the
physical model, exercise startup, display, controls, audio, storage, power,
recovery, update and installer restoration through the existing `scenarios/`
and device workflows. Document the exact hardware and storage combination,
checks performed and known limitations when contributing the target.
