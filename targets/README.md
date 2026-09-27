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
| `classic6g-n25` | iPod Classic A1238, S5L8702, 320 × 240 color | Native Boot, OS, Link, Disk Mode and H.264 VGA playback verified; MPEG-4 performance qualification in progress |

All targets expose their installation status through the same Media Manager. `build_enabled = false` explicitly marks an incomplete port and requires a `bringup_blocker`; it cannot enable installation. A1238 uses the independent S5L8702 HAL and target-owned NOR maintenance path.
Run `python linnet target-report --target <target-id>` for a read-only report of
conventional source choices and `SOURCES` entries, theme origins, decoder choices,
capabilities, memory reservations, and missing prerequisites. It also reports
the blocker and expected source paths for a disabled port.

## Qualification record

This table records the supported build and installation scope. A successful
build or simulator run establishes only host-side behavior. Physical checks
require the stated hardware and the matching private receipts described in
[local artifacts](../docs/local-artifacts.md).

| Target | Local build and simulator scope | Physical scope and recovery | Open qualification and evidence |
| --- | --- | --- | --- |
| [Photo P98](photo4g-p98/README.md) | Release OS and Boot, dev OS, 220 × 176 UI | A1099/P98, 32 MiB RAM; directory Boot and guarded A/B OS updates are enabled for matching device identities | Primary development target. Keep device observations and recovery receipts with the exact specimen; the [device procedure](../docs/device-link.md) describes Link and Disk Mode. |
| [Video M25](video5g-m25/README.md) | Release OS and Boot, dev OS, 320 × 240 UI | Verified 30 GB MA146/M25, 32 MiB RAM; persistent Boot/OS and rollback exercised | [Qualification results](video5g-m25/QUALIFICATION.md) distinguish Link observations from physical controls and sound. USB reliability, charging/dock measurements, release-image operation, and larger workloads remain open; other A1136 variants are unqualified. |
| [monochrome Q21](ipod4g-q21/target.toml) | Release OS/Boot and 160 × 128 UI with a compatible local content selection | MP102/Q21 identity, 32 MiB RAM; directory Boot and guarded A/B updates are enabled by the manifest | No source-controlled physical qualification record. Confirm display, controls, storage variant, recovery, and audio on the exact device before claiming physical support. |
| [Classic N25](classic6g-n25/target.toml) | Release OS/Boot and 320 × 240 UI | A1238/N25, 64 MiB RAM; Native Boot, OS, Link, Disk Mode and H.264 VGA playback have been exercised on the qualified specimen. NOR bootstrap and recovery require its device-specific workflow; automatic installer is disabled. | MPEG-4 performance qualification remains open. [Apple stock-music scope](../docs/apple-stock-music.md) is specimen-bound; detailed device receipts belong in local artifacts. |

The manifests list accepted USB and sector-size variants for discovery; that
list does not extend physical qualification to every storage configuration.

`presentation_profile = "color320"` shares native screens, themes and layout generation from `ui/profiles/color320/` between A1136 and A1238. A target `screens/` directory replaces the profile's complete screen set; target-local themes are added after profile themes and replace matching theme IDs. Display dimensions must match. The Classic owns its Cobalt and Ember themes under its target directory. `sdram_address` supports nonzero physical RAM bases; it defaults to zero for PortalPlayer targets.

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
  s5l8702/              Classic CPU, ATA, USB and H.264 hardware
  arm926/               ARM926 cache, MMU and pixel conversion
  codecs/               selected audio codecs
targets/
  <target-id>/
    target.toml         complete target description
    hardware.h          board policy constants and ROM restart address
    device.c            board wiring (board.c is the supported fallback)
    power.c             optional board power hooks (otherwise hal/<family>/power.c)
    lcd.c               LCD controller driver
    lcd.h               optional private LCD declarations
    display.c           target display adapter
    screens/<app-id>/screen.tsx  optional complete native screen set
    themes/<theme>/      optional target-native themes
    presentation.toml   optional clock font and reference-layout adjustments
    system.toml         optional target-specific default content
    native_update.c     optional audited firmware maintenance implementation
    SOURCES             optional root-relative paths for additional native files
```

When `display.c` is absent, the build uses `hal/<family>/display.c`. It selects
`device.c` or falls back to `board.c`; it selects target `power.c` or falls back
to `hal/<family>/power.c`. The loader resolves `startup.S`, `memory.ld` and
`platform.c` by convention. Additional native files can be listed in
`hal/<family>/SOURCES` or `targets/<target-id>/SOURCES`, one root-relative path
per line. Manifests do not contain source-file lists.

The build derives the C target macro from the target ID and generates
`linnet_target.h`. That header carries target identity, display and media sizes,
storage limits, memory bounds and capabilities into native code. The manifest's
CPU, architecture and endianness select the compiler target and flags; the
linker script consumes its SDRAM and mailbox contract.

`resolve_target` in `tools/studio/targets.py` returns an immutable view of a
manifest with optional defaults applied. Build, media, and UI code use that
view for effective values while the source manifest remains unchanged. Defaults
include `hal_family = soc`, `audio_codec = "wm8975"`, active and idle clocks of
80 MHz and 0 Hz, software H.264, no MPEG-4 decoder, 16,384 video startup audio
frames, and enabled builds. Capabilities default to enabled except Cover Flow
and games. Add a new optional default there before consuming it elsewhere.

## Native presentation assets

Run generator commands from the repository root. Generated headers are checked
in because Boot and the LCD driver include them directly. Keep the input font
files and their [license](../sdk/assets/FONT-LICENSE.txt) with any regenerated
output.

| Output | Authoritative input and regeneration | Ownership |
| --- | --- | --- |
| [`photo4g-p98/boot_menu_font.h`](photo4g-p98/boot_menu_font.h) | `sdk/assets/font-sans14.json`; `python tools/studio/boot_menu_font.py --output targets/photo4g-p98/boot_menu_font.h` | Generated from licensed DejaVu font data |
| [`photo4g-p98/disk_screen_runs.h`](photo4g-p98/disk_screen_runs.h) | `sdk/assets/font-sans12.json`, `sdk/assets/font-sans14.json`, and the drawing recipe in `tools/studio/disk_screen_asset.py`; `python tools/studio/disk_screen_asset.py --output targets/photo4g-p98/disk_screen_runs.h` | Generated from licensed DejaVu font data and the in-tree Disk Mode design |
| [`photo220/games_graphics.h`](../services/games/presentations/photo220/games_graphics.h), [`color320/games_arcade.h`](../services/games/presentations/color320/games_arcade.h), [`color320/games_solitaire.h`](../services/games/presentations/color320/games_solitaire.h) | Edit these native drawing sources directly; there is no generator or external bitmap input. | In-tree game presentation code |
| [`photo220/solitaire_courts.h`](../services/games/presentations/photo220/solitaire_courts.h), [`color320/solitaire_courts.h`](../services/games/presentations/color320/solitaire_courts.h) | Manually maintained RGB565 palette and samples derived from [Austin Gabriel's Public Domain Playing Cards](https://github.com/AustinGabriel/Public-Domain-and-CC0-Playing-Cards); the headers record the sampling sizes. | External card artwork released under CC0; retain the attribution in both headers |

The build also generates target, build, and UI headers inside each invocation's
`out/<profile>/<target>/<kind>/runs/<invocation>/generated/` directory. Those
files are outputs of the manifest and content compiler, not checked in assets.

## Add a model

Run `python -m tools.studio.target_scaffold <target-id>` to create a disabled
manifest and conventional native file skeletons. The generated values are
placeholders, the source files deliberately fail compilation, and installation
is disabled. Run `python linnet target-report --target <target-id>` to inspect
the bring-up blocker and missing HAL, codec, and system configuration inputs.
Replace each placeholder with measured values and implement the hardware before
enabling a build.

Use [Photo P98](photo4g-p98/target.toml) or
[monochrome Q21](ipod4g-q21/target.toml) as a complete field reference. Use a
lowercase, hyphenated ID matching the directory name. The scaffold reserves an
unused `image_target` integer; review it before qualification.
`LINNET_TARGET_<ID>` is generated automatically.

| Fields | Purpose |
| --- | --- |
| `id`, `name`, `aliases`, `image_target` | CLI identity, display name, aliases and image compatibility number |
| `board_id`, `model_alias`, `soc`, `cpu`, `architecture`, `endianness` | Hardware identity and build selection |
| `sdram_bytes`, `os_capacity_bytes`, `resident_limit_bytes`, `entry_address`, `load_address` | Native memory and image contract |
| `stage_address`, `stage_bytes`, `recovery_snapshot_address`, `recovery_snapshot_bytes`, `mailbox_address`, `mailbox_bytes` | Update, recovery and retained-memory regions |
| `storage_max_read_sectors` | Largest bounded storage read used by media code |
| `lcd_width`, `lcd_height`, `lcd_format` | Physical display geometry and pixel format |
| `media_photo_width`, `media_photo_height` | Native prepared-photo viewport |
| `media_art_side` | Square album artwork size prepared by Media Manager and accepted by firmware |
| `media_video_width`, `media_video_height`, `media_video_fps`, `media_video_color` | Native prepared-video profile |
| `video_catalog_cache` | Video browser cache policy: `paged` or `resident` on video targets |
| `coverflow_cache` | Cover Flow page, artwork cache and catalog placement policy when enabled: `compact` or `expanded` |
| `presentation_policy` | Optional named UI choices: `music_hint_menu_back` for a compact music hint and `battery_theme_monochrome` for a monochrome battery fill. Defaults are `false` and `true` respectively. |
| `video_start_audio_frames` | Native video AAC priming target in PCM frames, from 1024 to 32768; defaults to 16384. The Classic uses 12288, about 0.28 seconds at 44.1 kHz. |
| `boot_size_optimization` | Optional smaller Boot code when constrained by a fixed NOR slot |
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
profile or reference-screen fallback. M25 uses the shared `color320` 320 × 240
screen set and themes. Native font pixels are retained. Legacy layout adjustments belong in
`presentation.toml`, not target-name branches in the compiler.

`[resources]` declares title-cache placement and cover-flow catalog capacity.
The loader checks these against recovery capture and mailbox reservations, and
the linker checks the final SRAM/SDRAM bounds. Runtime scheduling and music features are selected by `runtime_policy`, independently of the board ID. Board policy in `hardware.h`
selects bounded clock settling, ATA write/flush behavior, ROM restart markers
and documented storage quirks. Services consume capabilities and policy rather
than naming a board.

Boot quirks follow the same rule. Optional `hardware.h` policies select a held-key
query before or after input initialization (`LINNET_BOOT_MENU_QUERY_BEFORE_INPUT`
or `LINNET_BOOT_MENU_QUERY_AFTER_INPUT`) and a delayed chooser refresh
(`LINNET_BOOT_MENU_REDRAW_US`). PP502x handoff policies select Timer2 IRQ routing,
the retail I2C divider and a bounded COP acknowledgement. The register operations
and two-core handoff protocol remain in the shared HAL; kernel code uses the
portable input API. Omitted policies are disabled.

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

When a model's archived Apple image has a verified marker, `[retail]` can declare
`firmware_signature = { offset = 32, ascii = "portalplayer" }`. The installer uses
that target-owned format check along with image bounds, SHA-256 and configuration
CRC. On reinstall, an OSOS slot containing Linnet must not replace the preserved
Apple archive; an existing archive must pass the same target-bound checks.

Start `[installer]` with `enabled = false`. The directory installer requires its partition and header fields; other disabled boot layouts do not inherit those fields. Only the `ipod-directory` boot
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
