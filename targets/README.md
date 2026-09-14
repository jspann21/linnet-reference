# Adding support for an iPod model

Linnet calls a hardware model a **target**. A target ID connects the native build,
image identity, UI compiler, RetailOS detection and installer. Start with the
closest existing target, then verify every hardware assumption on the new model.
Adding a name or alias does not implement a hardware port.

## Existing targets and scope

| Target | Hardware and display | Current status |
| --- | --- | --- |
| `photo4g-p98` | iPod Photo A1099, PP5020, 220 × 176 color | Primary development target. |
| `ipod4g-q21` | iPod 4G MP102, PP5020, 160 × 128 monochrome | Video and theme selection disabled in its manifest. |

Both targets support installation through the Media Manager.

The current build explicitly selects ARM7TDMI and a fixed set of platform services in
[build.py](../tools/studio/build.py). Changing `soc`, `cpu` or `architecture` in a
manifest selects a HAL source folder but does not select a different toolchain or
complete a new HAL. A different SoC needs build and driver work. The UI compiler currently limits logical dimensions to
220 × 176; larger displays also need compiler/layout work.

## 1. Collect the model's hardware facts

Record the board, SoC, memory map, LCD controller and format, input, storage,
audio, charging and boot-entry requirements. For discovery, collect USB VID/PID
and exact board/model strings from `iPod_Control/Device/SysInfo` and Windows USB
enumeration. Keep serial numbers, hardware GUIDs and firmware backups local.

The existing RetailOS discovery path requires Windows, a mounted FAT32 USB iPod
and 512-byte logical sectors. It matches VID/PID plus an exact board name or model
number, and checks the SysInfo hardware GUID against USB enumeration. Regulatory
model labels and friendly volume names are not sufficient detection keys.

## 2. Add the target manifest and native sources

Create `targets/<target-id>/target.toml`, using one of these complete manifests
as a field reference:

- [Photo P98](photo4g-p98/target.toml), for a color display.
- [Monochrome Q21](ipod4g-q21/target.toml), for display conversion and capability restrictions.

Each target directory has one predictable layout:

```text
targets/<target-id>/
  target.toml       identity, display, capabilities, discovery and installation
  device.c          board-specific hooks
  lcd.c             LCD controller driver
  lcd.h             optional private LCD declarations
  display.c         optional display adapter; otherwise hal/<soc>/display.c
```

Shared SoC startup, linker, platform and default display files live in
`hal/<soc>/` as `startup.S`, `memory.ld`, `platform.c` and `display.c`. The target
loader derives these paths from the directory and `soc`; manifests do not repeat
source paths.

Use a lowercase, hyphenated ID matching the directory name. Choose a unique
`image_target` integer and `target_define`; retain established image IDs for
existing models. Update aliases and board/model identity to describe the new
hardware.

| Fields | What to configure |
| --- | --- |
| `id`, `name`, `aliases`, `image_target`, `target_define` | CLI identity, display name, image compatibility number and C selection macro. |
| `board_id`, `soc_id`, `model_alias`, `soc`, `cpu`, `architecture`, `endianness` | Hardware metadata; these do not automatically implement hardware support. |
| `sdram_bytes`, `entry_address`, `load_address`, `mailbox_address`, `mailbox_bytes` | Memory contract; reconcile with startup, linker script and image/boot validation. |
| `lcd_width`, `lcd_height`, `lcd_format`, `ui_width`, `ui_height` | Physical display and logical UI dimensions. |
| `capabilities` | Boolean `photos`, `video`, `files`, `demo`, `themes` restrictions. Explicit `false` disables a feature even if system configuration enables it. |
| `media_video_fps`, `media_video_color` | Media conversion defaults: 4–30 fps and `rgb565` or `gray4`. Required even when video is disabled. |
| `cop_display` | Whether the build includes the existing COP video blit path. |
| `[ui]` | Optional `allowed_themes` and `default_theme` restriction for displays that need a dedicated theme. |

Q21 and P98 share the PP5020 startup and memory layout. Q21 provides its own
display adapter; P98 uses the PP5020 default. Review shared `hal/pp5020/` code for
model assumptions, including input, audio, storage and power. Setting a new C
macro alone does not add those behaviors.

## 3. Configure the UI

The compiler reads `ui_width`, `ui_height`, `lcd_width`, `lcd_height` and
`lcd_format` directly from `target.toml`. For a monochrome display, use a
`lcd_format` beginning with `gray` and add `[ui]` when the target needs a fixed
theme. Review each theme's `targets` list in `themes/*/theme.toml` so the new
target has a compatible theme. See the [UI compiler reference](../docs/ui-compiler.md)
and [SDK guide](../sdk/README.md).

For content compilation and simulator runs, copy `config/system.toml` to a local
file such as `out/new-model-system.toml`, set `[system] target` to your new ID,
and select a compatible `[ui] theme`. Keep the existing application IDs/order.
Firmware builds accept `--target`; the content-only compiler and simulator
select the target through `--system`.

## 4. Configure discovery and installation

The shared [target loader](../tools/studio/targets.py) discovers
`targets/*/target.toml` automatically. Compatible devices do not need a second
USB/model table in the installer.

Populate `[retail]` with integer `usb_vid`/`usb_pid` and ASCII string lists
`board_names`, `model_numbers`, `regulatory_models`. At least one board name or
model number is required. Use observed values, not a nearby model's identity.

Start `[installer]` with `enabled = false`. All installer fields are required
even when disabled; do not omit the profile. An unimplemented layout may use
`boot_layout = "unsupported"` while disabled. Populate the remaining fields from
verified model-specific evidence:

| Fields | Meaning and loader constraints |
| --- | --- |
| `boot_layout` | Only `ipod-directory` can currently be enabled. Other layouts need implementation. |
| `file_loader` | Relative loader path with at least two components and no `..`, such as `.rockbox/rockbox.ipod`. |
| `wrapper_model`, `wrapper_checksum_seed` | Four printable ASCII characters and an unsigned 32-bit checksum seed for the model's wrapper. |
| `firmware_header_magic`, `firmware_header_field` | Eight hex digits and an unsigned 16-bit header field. |
| `firmware_partition_types`, `media_partition_types` | Nonempty, disjoint lists of unique partition type bytes. |
| `firmware_entry_type` | Four printable ASCII characters for the firmware directory entry. |
| `max_firmware_bytes` | Firmware bound, 512-byte aligned, from 512 bytes through 1 GiB. |

Unknown installer keys are rejected. The loader also rejects missing conventional
source files, duplicate image IDs/aliases and malformed profiles; one invalid manifest
can prevent CLI startup. These checks validate structure, not hardware accuracy.

Enable installation only after verifying the wrapper, directory layout, memory
and disk bounds on the actual model. Generated images must match the detected
target exactly. Keep matching backups, plans and recovery receipts together as
described in [local artifacts](../docs/local-artifacts.md); the operational workflow is
in the [Media Manager guide](../docs/media-manager.md).

## 5. Validate and document the port

Run commands from the repository root. Replace `NEW_TARGET` with the target ID
and `YOUR_SERIAL` with the observed device serial. On Linux use `python3`.

```console
python -c "from tools.studio.targets import TARGETS; print('\n'.join(TARGETS))"
python linnet doctor
python linnet ui compile --system out/new-model-system.toml --output out/ui-new-model
python linnet simulator --system out/new-model-system.toml --output out/simulator-new-model
python linnet build --target NEW_TARGET --profile release --kind os --verify
python linnet build --target NEW_TARGET --profile dev --kind boot --device-serial YOUR_SERIAL --verify
python linnet build --target NEW_TARGET --profile dev --kind os --device-serial YOUR_SERIAL --verify
```

If using a custom system configuration, also pass
`--system out/new-model-system.toml` to the OS builds. `--verify` performs image
checks and, for release images, checks development-symbol exclusions.

Inspect simulator output for clipped text, navigation, theme and disabled-feature
behavior. Then use the [device workflows](../docs/device-link.md) and existing
`scenarios/` to assess physical startup, display, controls, audio, storage, power,
recovery and updates. Exercise installer inspection, interrupted provisioning,
plan identity guards, restart and restoration on the physical target. Build and
simulator results cannot establish these hardware properties.

When contributing the port, update the target table here and in the root README.
State which hardware/storage combination was exercised, checks that passed,
known limitations and any follow-up work. Include the native sources,
manifest and any necessary theme changes together; keep generated
images and device-specific recovery material out of the contribution.
