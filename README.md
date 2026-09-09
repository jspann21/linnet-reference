# Linnet

Native open firmware for classic iPods. The initial target is `photo4g-p98`
(iPod Photo A1099). Constrained TSX applications compile ahead of time into native code.

Batch 7 product integration is installed and verified on the development iPod.
Music, prepared photos, video, settings, updates and recovery are implemented;
full release acceptance remains open. The user confirmed basic music playback,
controls and photo loading. Deferred audio, photo and video qualification and
performance work is recorded in [PROJECT_TODO.md](PROJECT_TODO.md).

The native startup watchdog regression is fixed. Three persistent starts,
including Disk Mode entry and safe eject, returned the exact healthy confirmed
OS with no crash. Physical battery/charging checks, full power removal and the
release-only journey remain unqualified. See
[integration evidence](INTEGRATION_IMPLEMENTATION.md). Batch 0 and Batch 1
campaign results below are historical evidence for their recorded builds.

Storage now includes adapter-aware idle, standby and rail-power handling, dynamic
ATA28/ATA48 capacity discovery, and a two-window read cache that reduces repeated
mirrored-FAT reads. The installed iFlash ATA1 has passed a light idle power-off
and cold wake/read check. See [storage compatibility](STORAGE_COMPATIBILITY.md)
for profiles, filesystem limits, evidence and untested hardware.

Batch 1 platform core is hardware-qualified:
the fixed-pool executive, interactive shell, input and power drivers, bounded
clock switching, COP display queue, and development screenshot/input commands.
Development OS, Boot and release builds pass compilation and release exclusion.
The new Boot worker is installed with verified readback. Platform automation
passed on OS `8af5ad4f058c`: 256 navigation events with zero drops, 40 COP frames,
queue reset, three sleep/wake cycles, screenshot checks and idle without redraw.
Maximum event latency was 2.533 ms; maximum C IRQ dispatcher duration was 13 us.
The physical controls, adjusted wheel feel and clean screen are confirmed.
Automatic guarded unmount/reboot also passed on the connected iPod. Receipt: `out/runs/20260906T042149Z-photo4g-p98-8af5ad4f058c-0001/receipt.json`.

Hold **Play/Pause alone for two seconds** to shut down. A short tap controls
music playback, or the slideshow while viewing a photo. Releasing early, pressing another button, or enabling Hold
cancels the shutdown timer. The shutdown build passes compilation and platform
automation. Physical testing confirmed that a short tap leaves it running and
a long press shuts it down and keeps it off with USB connected. Manual power-on
also passed. Evidence: `out/b01-shutdown-qualified.json`.

Native Boot installation passed raw-device readback. Initial hardware checks
exposed LCD and USB completion faults; subsequent repairs enabled native upload,
verification, RAM boot and USB reconnection. Hardware campaign
`20260906T031506Z-photo4g-p98-def6c43d345e-0001` has recorded healthy OS cycles
with matching full-image SHA-256, increasing boot generations and all five
readiness bits. The user reduced the cycle requirement to 20; 22 complete cycle
receipts were saved before stopping the repeated boots. The resumed campaign
`20260906T032437Z-photo4g-p98-def6c43d345e-0001` preserved that evidence and passed
the remaining fault, watchdog and reboot checks. Its final command entered Apple
Disk Mode. Receipts and firmware backups are local under `out/` and excluded from
Git. Qualification applies to the exact image identities in those receipts.

## Manage music, notes, photos and videos

On Windows, double-click **Linnet Media.cmd**, or run `python linnet media`.
Connect the iPod in Disk Mode. The desktop manager detects its identity and scans
the existing **Music**, **Notes**, **Photos** and **Videos** folders. Choose which
folders to update, optionally add files or folders from the computer, then click
**Prepare & update iPod**. Safely eject when it finishes and restart Linnet.

Existing music and native IPVF video are indexed in place; their media is not copied or transcoded. Photos
and other video formats get prepared playback copies. Notes get a prepared read-only catalog
available under Extras > Notes. Originals stay in their folders. Updated firmware
is required for existing music paths, the Notes reader and multiple-video browsing.

The manager needs Python with Tkinter, Pillow, and FFmpeg/FFprobe. It finds media
tools on PATH or through **Locate FFmpeg**. See [the media guide](MEDIA_MANAGER.md)
for format limits, caching, progress, and recovery details.
Existing music uses fast metadata checks by default, with a resumable per-track
cache. Optional Mutagen (`python -m pip install mutagen`) speeds up the first
import. Video subfolders, including Rockbox IPVF sources, are included.

## Prepare photos

Prepare the folder containing your photos on the computer before publishing:

```powershell
python linnet photos compile --source "C:\Photos\Anna" --output out/anna.pimg
python linnet photos inspect out/anna.pimg
```

Preparation preserves the originals and creates screen-sized images plus zoom
levels up to 640 pixels. Use `--max-dimension 2048` for more zoom detail and a
larger package. Select the actual photo folder to avoid including sibling folders
of samples or fixtures.

## Build

Requires Python 3.11+ and LLVM **18.1.3** (`clang`, `ld.lld`, `llvm-objcopy`,
`llvm-nm`). The versions are checked before compilation. On Windows, the CLI
uses the installed `Ubuntu-24.04` WSL distribution; run it from PowerShell:

```powershell
python linnet doctor
python linnet build --batch 7 --target photo4g-p98 --profile dev --device-serial 000000F7A765 --verify
python linnet build --batch 7 --target photo4g-p98 --profile release --verify
python linnet build --profile trace --device-serial 000000F7A765
python linnet build --profile dev --kind boot --device-serial 000000F7A765
python linnet build --profile dev --probe crash --device-serial 000000F7A765
python linnet build --profile dev --probe hang --device-serial 000000F7A765
python linnet build --batch 1 --profile dev --device-serial 000000F7A765 --verify
python linnet build --batch 1 --profile release --verify
python linnet build --batch 3 --profile dev --device-serial 000000F7A765 --verify
python linnet build --batch 3 --profile release --system themes/midnight/system.toml --verify
```

On Linux use `python3 linnet` with the same arguments. `linnet.cmd` is also
available on Windows. Builds need no package downloads and include no runtime
allocator, VM or operating-system library. Optional serial discovery requires
`python -m pip install pyserial==3.5` in the Python environment running the CLI.

Unique artifacts and JSON build/memory reports appear under
`out/<profile>/photo4g-p98/<kind>/`. Build IDs cover source contents, configuration
and compiler identities. `.los` files contain the validation envelope; `.ipod`
files have an external iPod checksum wrapper around the native payload. Neither
extension establishes that the image is safe to boot. See the prepared-loader
entry prerequisites in [ARCHITECTURE.md](ARCHITECTURE.md).

```powershell
python linnet inspect <path-to-image.los>
python linnet release verify <path-to-release.los> --symbols <matching-symbols-file>
python linnet device info
python linnet device info --port COM7
python linnet device cycle --image <healthy.los> --crash-image <crash.los> --hang-image <hang.los> --release-image <release.los> --release-symbols <release.symbols> --scenario scenarios/b00-recovery.json
python linnet report <run-id>
```

`device info --port` speaks Linnet Link, so it requires an actual Linnet Link
endpoint. `device cycle` uploads images, checks build identities and recovery
generations, exercises crashes and watchdog recovery, and saves receipts under
`out/runs/`. Its final Disk Mode check requires a newly observed storage device.
The serial in these examples is the inspected development iPod; development
builds for another device must use that device's observed identity.

## Native UI and customization

Batch 3 compiles all 17 native components and the Home, Settings, About, Files,
Music, Photos, Videos and Now Playing screens. The optional UI Demo example adds a custom
app and a clipped native canvas callback. Music, photos and video now use the native media services. Files remains disabled
in the default build configuration. Copyable starters are in `sdk/templates/`.
Static rectangles, menu destinations, theme colors, RGB565 assets and the
licensed ASCII font are resolved on the host. The device runs the linked native
renderer with fixed state and virtualized visible rows.

Settings > Themes applies a complete layout immediately. Five additions join
Linnet and Midnight: iPod Photo, Graphite, Aurora, Sunset, and Blueprint.
iPod Photo follows the stock color iPod's full-width menus, silver title bar,
blue selection, five-column photo grid and centered Now Playing layout.
Graphite uses inset cards, Aurora a status rail, Sunset numbered serif lists,
and Blueprint a tiled menu with a bottom status bar. Licensed DejaVu fonts
approximate the Apple typography. All components, decorations and status symbols
use theme colors; actual media retains its source pixels.

Battery fill, charging/external-power symbols, headphone and Hold indicators,
play/pause and the clock use cached service or hardware state. The Clock screen
reads the device RTC; unavailable values are shown explicitly. Simulator status
inputs are samples and do not establish physical device qualification.

Select apps and the default theme in `config/system.toml`. All discovered theme
layouts and fonts compile into the firmware; selection needs no rebuild.
The Midnight example demonstrates a complete configuration override:

```powershell
python linnet ui compile --output out/ui
python linnet ui compile --system themes/midnight/system.toml --output out/ui-midnight
python linnet build --batch 3 --profile dev --device-serial 000000F7A765 --system themes/midnight/system.toml --verify
python linnet simulator --system themes/midnight/system.toml --output out/simulator-midnight
python linnet device ui-state --port COM6
```

The compiler emits native C, matching scene JSON, hashed content manifests, and
host `.lapp` / `.ltheme` packages. Unsupported TSX expressions and out-of-bounds
layouts are rejected. Normal compilation uses the Python standard library;
explicit replacement-font baking uses Pillow. See the [SDK guide](sdk/README.md)
for the accepted grammar, manifests, font baking and native callback contract.

The simulator compiles and executes the same C renderer and generated content
on the desktop. It saves raw RGB565 frames, PNG previews, CRC/SHA records,
paint counters and an `index.html` gallery. A JSON input tape supplies wheel,
button and switch events; kind 0 requests a render without input. For example,
after compiling content into `out/`:

```powershell
@'
[
  {"kind": 1, "value": 1},
  {"kind": 2, "value": 16},
  {"kind": 2, "value": 0},
  {"kind": 1, "value": 64, "repeat": 100, "capture": false},
  {"kind": 0, "value": 0, "repeat": 1000}
]
'@ | Set-Content -Encoding ascii out/ui-tape.json
python linnet simulator --tape out/ui-tape.json --output out/simulator-tape
```

Kinds 1..4 are wheel steps, button mask, hold and headphones. Button bits are
Menu 1, Play 2, Next 4, Previous 8 and Select 16; zero releases buttons. The tape
is limited to 100,000 expanded events and 512 requested captures. Simulator
results are a native pixel oracle, not hardware qualification. The Batch 3
device campaign and physical typography, focus, wheel and LCD inspection remain
in progress; the Batch 2 qualification limitations below still apply.

The inspected iPod originally booted PocketJS directly from its native OSOS
firmware entry. Its current directory points to Linnet Boot, with the original
PocketJS payload preserved. Replacing `.rockbox/rockbox.ipod` does not change
that native directory entry.
`tools/studio/native_bootstrap.py` prepares an exact, device-specific redirect
from a verified firmware backup and matching Linnet Boot build. Its explicit
apply and restore operations verify device identity and preserve the original
OSOS payload. Upgrade plans pin a predecessor plan and stage a replacement in
a separate unused region before publishing its directory sector. Restore writes
the original directory sector and leaves staged payloads in place. Preparing a
plan does not write to the device. This bootstrap is not a general installer or
the planned transactional update system.

The supplied implementation plan defines the sequential batch gates; the
identifier specification defines canonical names. Binary and wire contracts live
in [FORMATS.md](FORMATS.md) and [DEVLINK.md](DEVLINK.md). Hardware qualification
requires 20 healthy cycles under the user's revised gate, plus crash/recovery
and reboot receipts from the physical device.

On Windows, automatic unmount and restart uses the exact installed Boot plan:

```powershell
python linnet device eject --reboot --disk-number 4 --plan out/native-bootstrap-b01-01/plan.json --plan-sha256 34190d6ce8fd4f7c35cb470933e8b0674137c1b042e1b6f0f2c83322981f300a
```

The command validates the plan and device and requires an already elevated
Windows process. It refreshes one identical 512-byte boot-directory sector with
full firmware guards and readback, then ejects and verifies the returning Boot
identity. The CLI never requests a UAC prompt; an unelevated invocation fails
before refresh. No firmware bytes
change. A failed refresh never proceeds to eject; ambiguous operations are not
replayed. Receipts remain under `out/disk-restart-*.json`.

Plain `device eject --disk-number 4` only ejects. Apple Disk Mode may stay active
after ordinary eject; `--wait-link` alone does not request a reboot. To enter
Disk Mode from Linnet, use `python linnet device reboot --mode disk --port COM6`.
Boot and reboot commands confirm matching HELLO and STATUS identities before
sending the mutation. Disk/USB identity defaults name the inspected development
iPod; automatic restart additionally requires its exact pinned installation plan.

## Batch 2 reconnect checklist

Offline candidates, exact image identities and verification results are indexed
in `out/b02-offline-ready.json`. The initial file set is in `out/b02-package`.
Offline validation does not establish hardware qualification. The device-side
native Boot apply was still under evaluation at that Batch 2 checkpoint. Later
Batch 7 native installation completed (`out/b07-usb-native-installed.json`);
current qualification status is tracked in PROJECT_TODO.md.

1. Reconnect and inspect Linnet Link. RAM-boot the Batch 2 development OS first;
   use `device storage-info --port COM6` to inspect ATA capacity, partition,
   mount state and counters before provisioning.
2. Prepare and review a new native Boot plan against the installed Boot plan
   and preserved firmware backup. Package it as LNB2 and run `device native-install`
   from the Batch 2 development RAM OS using the commands below. This device-side
   path uses Linnet Link and requires no Windows elevation. Enter Disk Mode only
   when ready to provision the FAT32 files.
3. Provision the prepared file set onto the identified FAT32 drive with
   `storage provision --package out/b02-package --mount F:\ --serial JQ5081G3SAY`.
   This initial operation refuses existing Batch 2 files. Safely eject/restart
   and verify the exact persistent OS identity.
4. Run `device storage-cycle --image <dev-os.los> --scenario scenarios/b02-storage.json --port COM6`,
   then `device update-cycle --image <dev-os.los> --crash-image <crash-os.los> --port COM6`.
5. Run `device storage-sync-cycle --image <dev-os.los> --port COM6 --disk-number 4 --plan <installed-plan.json> --plan-sha256 <hash>`.
   This creates and retains `LINNET/HOSTSYNC.BIN` as evidence; it refuses an
   existing file. Finish with physical sleep/wake and long-press shutdown checks.

`device install --image <os.los> --port COM6` publishes an inactive persistent
candidate. `device reboot --mode persistent --port COM6` then performs a cold
restart into Boot's validated slot selection. A RAM boot is still available for
development; it does not itself install an image. Batch 3 implementation and
device checks do not substitute for the unrun Batch 2 stress and fault campaigns.

## Native Boot installation through Linnet Link

```powershell
python -m tools.studio.native_package --plan <reviewed-plan.json> --plan-sha256 <plan-sha256> --output out/native-boot.lnb
python linnet device native-install --package out/native-boot.lnb --package-sha256 <package-sha256> --port COM6
python linnet device native-status --port COM6
```

The host validates the explicit package hash, sidecar provenance, pinned plan,
artifacts and firmware backup before opening the port. The device accepts only
the fixed P98 package for storage serial `JQ5081G3SAY` and USB serial
`000000F7A765`. It checks the MBR and complete firmware before-state, stages and
flushes the replacement Boot, verifies the staged firmware hash, then publishes
and flushes the directory and verifies the final full firmware hash. The
original OSOS payload remains guarded throughout. Success requires a completed
receipt. The first device-side attempt reached its 600-second deadline during
the initial hash check, with zero disk writes; that attempt did not qualify
the device-side path. Later Batch 7 native installation completed and verified
its firmware publication (`out/b07-usb-native-installed.json`).
The installed Batch 2 Boot at that earlier checkpoint used the verified host-side installer with
one approved UAC elevation. No mutation is retried
automatically after an uncertain acknowledgement.

`device native-install` updates the native Boot entry; `device install` publishes
an A/B OS candidate. Both use the device's storage service without host raw-disk
access or UAC prompts. `storage package` creates local files, and `storage provision`
uses normal FAT32 file access where Windows permissions allow it. Plain `device eject`
also needs no elevation, but ordinary Apple Disk Mode ejection does not guarantee
a restart. The existing directory-refresh `eject --reboot` and
`storage-sync-cycle` require an already elevated host process and fail closed
without requesting a prompt. Automatic restart after provisioning remains a
separate hardware observation.

On 2026-09-06 the host installed Boot `d277fb8fe374` and provisioned OS
`f22a18828260`. Safe eject after that Boot publication restarted automatically;
the persistent OS reached health 31 with prepared storage and no errors or
retries. A 512-byte scratch write/read/restore passed. The user requested light
checks only, so stress and fault campaigns were not run. Startup chain validation
took several minutes at that checkpoint. Evidence is indexed in
`out/b02-installation-complete.json`.

Batch 6 video implementation and qualification status: [VIDEO_IMPLEMENTATION.md](VIDEO_IMPLEMENTATION.md).
Photo loading speed and other deferred work: [PROJECT_TODO.md](PROJECT_TODO.md).
