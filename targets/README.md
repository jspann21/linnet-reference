# Adding an iPod target

Linnet calls one hardware model a **target**. A target owns identity, memory,
display, media, discovery and installation data in one manifest. Native sources
follow fixed paths, so adding a model does not require another build table.

## Current targets

| Target | Hardware and display | Status |
| --- | --- | --- |
| `photo4g-p98` | iPod Photo A1099, PP5020, 220 × 176 color | Primary development target |
| `ipod4g-q21` | iPod 4G MP102, PP5020, 160 × 128 monochrome | Photos, video and theme selection disabled by the manifest |

Both targets support installation through the Media Manager.

## Repository contract

The portable firmware interfaces live in `hal/api/`. Kernel, service and UI
code include only these headers. Each `hal/<soc>/` directory implements those
interfaces and contains the SoC startup and linker files. Board-specific LCD and
device hooks live in `targets/<target-id>/`.

```text
hal/
  api/                  portable firmware interfaces
  <soc>/                SoC implementation, startup and linker script
targets/
  <target-id>/
    target.toml         complete target description
    device.c            board hooks
    lcd.c               LCD controller driver
    lcd.h               optional private LCD declarations
    display.c           optional target display adapter
```

When `display.c` is absent, the build uses `hal/<soc>/display.c`. The loader also
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

TSX screens use a fixed 220 × 176 authoring coordinate space. The compiler
scales that reference layout and theme metrics to the target LCD in either
direction. Prepared photos and videos use their own target-native dimensions.
New resolutions up to 1024 per side and 131,072 pixels are accepted, subject to
memory and media read bounds. Inspect every new resolution in the simulator and
on hardware for text fit and visual quality.

For another PP5020 iPod, reuse `hal/pp5020/` and add the target's LCD and device
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
recovery, update, and installer restoration with the relevant Linnet Link
commands and device workflows. Document the exact hardware and storage combination,
checks performed and known limitations when contributing the target.
