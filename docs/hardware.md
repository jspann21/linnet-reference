# Hardware support

Linnet has four hardware targets. The tables below describe observed devices,
implemented variant handling, and the limits of physical testing. A matching
model number alone does not qualify every board, panel, or replacement drive.

For installation, use [Media Manager](media-manager.md). For a new board or model,
use the [porting guide](../targets/README.md).

## Tested device configurations

Storage capacities identify the observed configuration; they are not target
capacity limits. Video RAM was probed on the devices. Photo, Classic, and
monochrome RAM sizes come from their target definitions; display specifications
come from the drivers. An inventory reading does not establish playback,
physical controls, power behavior, or recovery qualification.

| Device | Target | Observed storage | RAM | Display |
| --- | --- | --- | --- | --- |
| iPod Photo / Color A1099 | `photo4g-p98` | iFlash, 64 GB; firmware `iFlash85` | 32 MiB | 220 × 176, RGB565; LCD type 1 |
| iPod Video A1136 | `video5g-m25` | Toshiba MK3008GAL, 30 GB; 512-byte sectors | 32 MiB | 320 × 240, RGB565 |
| iPod Video A1136 | `video5g-m25` | iFlash, 125 GB | 32 MiB | 320 × 240, RGB565 |
| iPod Video A1136 | `video5g-m25` | Toshiba MK8010GAH, 80 GB; logical 512 / physical 1024-byte sectors | 64 MiB | 320 × 240, RGB565 |
| iPod classic A1238 | `classic6g-n25` | iFlash, 125 GB | 64 MiB | 320 × 240, RGB565; LCD type 1 |
| iPod classic A1238 | `classic6g-n25` | Toshiba MK1634GAL, 160 GB; logical 512 / physical 4096-byte sectors, 4200 rpm | 64 MiB, walking data/address checks passed | 320 × 240, RGB565; LCD type 2 |
| iPod 4G monochrome A1059 | `ipod4g-q21` | Toshiba MK2006GAL, 20 GB; firmware `BY301A`, 4200 rpm, 512-byte sectors | 32 MiB | 160 × 128, 2-bit grayscale (four levels) |
| iPod 4G monochrome MP102 | `ipod4g-q21` | Toshiba MK2006GAL, 20 GB; 512-byte sectors | 32 MiB | 160 × 128, 2-bit grayscale (four levels) |

## Target capabilities

| Target | Hardware | Feature and installation scope |
| --- | --- | --- |
| [Photo P98](../targets/photo4g-p98/README.md) | PP5020 / ARM7TDMI, WM8975 audio, PCF50605 power | Music, photos, prepared IPVF video, Cover Flow, and games. Native directory installer and A/B OS updates. |
| [Video M25](../targets/video5g-m25/README.md) | PP5022 / ARM7TDMI, WM8758 audio, BCM2722 display/video, PCF50605 power | Music, photos, native H.264/MPEG-4, Cover Flow, and games. Native directory installer and A/B OS updates. |
| [Classic N25](../targets/classic6g-n25/target.toml) | S5L8702 / ARM926EJ-S, CS42L55 audio, PCF50635 power | Music, photos, native MP4, Cover Flow, and games enabled in the manifest. Media Manager installs Boot and OS after guided DFU entry, with device checks and original NOR recovery. |
| [Monochrome Q21](../targets/ipod4g-q21/target.toml) | PP5020 / ARM7TDMI, WM8975 audio, PCF50605 power, HD66753 LCD | Music and the iPod Mono interface; RGB565 framebuffer converted to four gray levels. Photos, video, Cover Flow, and games disabled. Native directory installer and A/B OS updates. |

All four targets provide native Disk Mode and development-build
[Linnet Link](device-link.md). Feature availability follows the target manifest
and selected system configuration. Apple database writes have a separate
[device and volume qualification boundary](apple-stock-music.md).

## Variant handling and physical coverage

**Tested** describes the stated hardware and behavior. **Implemented** means the
driver has a path for it, but physical qualification is still needed. Neither
status certifies every build or the complete release workflow.

| Variation | Handling and coverage |
| --- | --- |
| Q21 A1059 and MP102 identities | Both use the Q21 target and have physical bring-up evidence. A1059 checks include boot, library, headphone audio, controls/Hold, backlight, USB charging, sleep/wake, and native USB reads/writes. Current release acceptance remains open. |
| M25 32 / 64 MiB boards | A preserving alias probe detects the upper bank; 64 MiB boards gain metadata and clean-read caches. Both sizes tested; the 60 GB configuration remains unqualified. |
| M25 BCM revisions `0x000b0010` / `0x000b0011` | Both tested. Driver admission checks the board and firmware image; other revisions are rejected. The [M25 qualification record](../targets/video5g-m25/QUALIFICATION.md) covers the 30 GB / 32 MiB unit in more detail. |
| P98 LCD types | Type 1 tested. Types 0/2/3 are implemented but unqualified. ROM revision `0x60000` forces type 0 because its straps are unreliable; that revision has no separate physical qualification. COP video blitting is limited to compatible even panel types. |
| N25 LCD types | Types 1 and 2 have physical display evidence. Type 2 was checked on the MK1634GAL 160 GB unit. Types 0/3 need physical qualification. |
| Q21 HD66753 panel | Wake, contrast, scanout, and grayscale conversion tested on A1059 and MP102. Replacement assemblies remain unqualified. |
| Mechanical disks without rotation data | Exact model fallbacks report 4200 rpm. Q21 MK2004GAL/MK2006GAL and M25 MK3008GAL/MK8010GAH have physical checks. Q21 MK4004GAH, P98 factory-disk fallbacks, and M25 MK6008GAH remain unqualified. |
| ATA addressing and sector geometry | LBA28 and LBA48 tested. PP502x physical-sector alignment and partial-sector read/modify/write tested at 512 and 1024 bytes; 2048/4096-byte physical sectors remain unqualified. Native logical sectors must be 512 bytes. |
| Flash adapters | P98 `iFlash85` has tested CFA admission and DMA handling. M25 and N25 flash configurations have media checks; their drivers apply their own admission and transfer policies. Other adapter firmware and cards need separate qualification. |
| Classic PATA and NOR | Native Boot, OS, storage, display, media, and power bring-up have physical evidence. The Toshiba MK3008GAL PATA path has also been exercised. NOR writes admit JEDEC `BF 25 8E` only. |
| USB | Q21, M25, and P98 OS Disk Mode use tested native high-speed paths; P98 Boot and Link retain full speed. Host USB sector geometry is separate from native ATA geometry. |
| Controls and headphone audio | Board-specific wheel, button, Hold, jack, clicker, and codec paths have physical evidence on the tested units. Replacement assemblies and sustained playback need their own checks. |
| Power and charging | USB charging and bounded sleep/wake have been exercised. Negotiated current limits and diagnostics do not measure actual current, battery runtime, or FireWire charging. |

The N25 MK1634GAL unit passed screen, wheel, buttons, Hold, and audible clicker
checks. Its drive powered off after idle and woke for a verified scratch
write/read/restore crossing a 4 KiB boundary, without storage errors. MP3
decoding and PCM playback ran without underruns or digital audio faults, but
only the left headphone output was audible. A right-only PCM tone was silent
with headphones whose right earpiece worked elsewhere. Stereo headphone output
on this unit remains unqualified: the same right-channel failure was reported
in Apple OS, pointing to the device's analog headphone path. Symmetric codec
readback alone does not establish analog output.

## Known limits

- **Classic storage:** CE-ATA is detected and rejected before PATA setup; the
  native CE-ATA transport is missing. The S5L driver has its own exact iFlash
  handling, but does not inherit PP502x physical-sector edge handling.
- **Classic variants:** the A1238 label spans different board populations.
  Alternative LCD, RAM, disk, and NOR combinations need separate qualification.
  Classic MPEG-4 samples have played, but broader playback and physical A/V sync
  acceptance remain open.
- **Accessories:** headset inline buttons and Classic Mikey controls are not
  implemented. Dock audio, recording, TV output, remotes, and FM accessories need
  separate electrical and protocol work; headphone playback does not qualify them.
- **Replacement parts:** batteries, chargers, display panels, wheel assemblies,
  adapters, and larger drives are not qualified by matching a shell label or
  advertised capacity.

See [storage compatibility](storage.md) for addressing, power, and write policies,
and the [roadmap](roadmap.md) for release acceptance and remaining measurements.
Keep unit identifiers, raw diagnostics, build identities, and recovery receipts
in [local artifacts](local-artifacts.md).
