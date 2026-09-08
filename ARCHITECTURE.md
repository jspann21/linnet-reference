# Linnet foundation

The implementation is scoped to Batch 0 in the original implementation plan.
The product and source names follow `LINNET_PROJECT_STRUCTURE_AND_IDENTIFIERS.md`.
Hardware qualification remains a separate gate from compiling portable code.

## Boot contracts

`boot/include/linnet_boot.h` and `boot/src/linnet_boot.c` provide a freestanding,
allocation-free C implementation of image validation, boot selection, candidate
rollback, healthy promotion, and crash/state binary codecs. They require only
the standard integer and size type headers. They contain no peripheral addresses,
USB protocol, storage driver, or OS-specific host calls. Every loop is bounded
by fixed field sizes or the validated image length. Callers enforce transport
capacity and hardware deadlines.

The portable A/B selection contract is:

1. Decode a trusted, atomically published boot-state record. If it is unavailable
   or corrupt, enter recovery; do not infer a confirmed image from untrusted bytes.
2. Call `ln_boot_after_reset`. A pending candidate is discarded because it did not
   publish a healthy marker. Persist the changed state before proceeding.
3. Validate each available image with `ln_image_validate`, using the board's safe
   RAM window, target, ABI and allowed profile mask.
4. Call `ln_boot_select` with the mask of successfully validated slots. A valid
   candidate takes precedence, then the valid confirmed image, otherwise recovery.
5. Call `ln_boot_begin_attempt`, persist its state atomically, then transfer control.
   Abort the transfer if persistence fails. The confirmed slot is never overwritten
   when installing a candidate.
6. The running candidate calls `ln_boot_mark_healthy` only after memory/cache,
   core services, storage resolution (mounted or safely unavailable), first UI
   frame and known audio idle state are all established. Persist promotion before
   treating the update as committed.

An unconfirmed candidate resets back to the earlier confirmed slot. A reset after
durable healthy promotion retains the new confirmed image. Development crash
recovery can independently force the loader on a retained crash record; that
hardware reset/reconnect policy is not implemented by the portable selection
codec. Confirmed-image failure is not silently treated as a new candidate failure.

`FORMATS.md` specifies the byte contracts. `ln_crash_encode` prepares a bounded
CRC-protected record; actual exception capture, retained-memory placement, memory
barriers, watchdog reset and host retrieval belong to their board/transport
adapters. Persistent A/B publication remains unimplemented. The development
recovery path described below uses retained RAM and an intact Boot snapshot.

The development backend in `boot/src/loader.c` connects the command dispatcher to
a caller-supplied fixed staging window, LOS validation, SHA-256, identity/status,
metrics and retained crash retrieval. A contiguous upload invalidates earlier
verification before writing. UPLOAD_END and VERIFY check the complete file
digest and container. The chainload callback revalidates staging after transport
quiescence, then passes payload, absolute load/entry addresses, build identity,
full file digest and next generation to the platform recovery adapter. Staging
must remain exclusively owned throughout validation and transfer.

The board integration serves a bounded 96-byte diagnostic snapshot through
READ_LOG: eight LCD words, eight USB completion words and eight retained
recovery words. It includes the last recovery phase, USB stop proof and first
failure so a host can distinguish an accepted command from a completed handoff.
The exact word layout is in `FORMATS.md`; diagnostics are excluded from release.

`boot/src/sha256.c` is a streaming, allocation-free native SHA-256 implementation.
It does not authenticate images. Boot-state CRC and SHA-256 integrity must not
be presented as signature verification. The release source manifest excludes
the developer backend and its transport dependencies.

## P98 native recovery contract

The initial caller initializes SDRAM and enters the flat image in ARM state at
zero or its native `0x10000000` alias. Startup commits/discards each entering
core's cache with a finite poll budget, disables cache, and remaps SDRAM at zero
through an IRAM stub. It admits a sleeping inherited COP or a live Linnet COP
monitor handshake. It never wakes a previous firmware's unknown continuation.
This is a RAM bootstrap contract, not SDRAM cold initialization or a flash loader.

The development address map reserves low 8 MiB for executable images, 8 MiB at
`0x01000000` for staging, 1 MiB at `0x01e00000` for a pristine Boot snapshot,
4 KiB at `0x01ffe000` for recovery control and 4 KiB at `0x01fff000` for crash
records. Shared recovery control uses the uncached native alias. IRAM
`0x40000000` holds the finite copy/remap trampoline; `0x40001000` holds the COP
monitor when owned. USB exclusively owns IRAM `0x4000c000..0x4000ce00`.

Boot snapshots its stored image before peripheral initialization, validates the
snapshot with CRC32 and retains it while a candidate replaces low memory.
An external CPU bootstrap of a development Boot image at the native SDRAM alias
invalidates the earlier anchor before remapping; the relocation delta must be
exactly `0x10000000`. A low-address RAM Boot candidate cannot replace a valid
anchor, and COP entry never invalidates it. The two-core file-bootstrap path
requires the preceding loader to have disabled caches; concurrent enabled-cache
handoff by both cores has not been established.
Chainload validates staging ranges and alignment, stops transport and all four
PP DMA channels, cancels LCD transfers, and disables cache before a finite IRAM
copy enters the candidate. A fault records the 144-byte CRC-protected crash
mailbox with magic published last, then restores Boot through that same copy
path. Partial-register flag bit 0 means only PC and CPSR are captured; other
registers are zero. Returning to Boot advances the retained boot generation.

Timer2 fires FIQ every 100 ms; an unrefreshed 500 ms progress deadline invokes
panic and Boot restoration even if the CPU is busy in an ordinary infinite
loop. The normal executive enables FIQ after initialization. Hashing refreshes
progress after bounded 4096-byte slices; image replacement masks interrupts
only for the finite final copy. A COP entering Linnet installs a separate IRAM
monitor, requests FIQ at 750 ms and asserts system reset at 1500 ms if CPU
progress remains absent. An inherited parked COP is left parked and is not
advertised as an active monitor. A CPU with FIQ masked cannot be recovered by
Timer2 alone. COP reset goes to ROM; return from that reset to resident Boot
has not been established and must not be claimed.

Recovery reboot restores Boot. Normal reboot requires the still-intact staged
image to have been marked healthy, and validates its retained CRC before entry;
overwriting that staging image makes normal reboot unavailable. Disk reboot
writes Apple's known PP5020 disk-mode marker at `0x40017f00` and resets the
system. Automatic return from Apple disk mode requires a separately proven host
or boot path; requesting disk mode alone is not evidence of a completed cycle.

LCD output initializes the old P98 Photo panel, bridge and PWM backlight using
bounded waits. The audio idle operation stops DMA, holds I2S in reset and sends
WM8975 reset, DAC mute and power-down commands through bounded I2C transfers.
PP5020 reports bus completion; the WM8975 write protocol provides no register
readback. GPIO/panel variants beyond the old P98 target are not supported.

Hardware facts were checked read-only against the sibling source trees:

- `../ipod/firmware/export/pp5020.h`: CPU ID, interrupt mask, timer, COP control,
  LCD bridge addresses and bits.
- `../ipod/firmware/target/arm/ipod/lcd-color_nano.c`: old Photo panel window
  commands, rotated addressing and LCD block submission register protocol.
- `../ipod/firmware/target/arm/pp/crt0-pp-bl.S`: CPU ID `0x55`, COP sleep bit.
- `../ipod/firmware/target/arm/pp/crt0-pp502x-bl-usb.S`: cache commit/discard
  operation bits and IRAM remap sequencing.
- `../ipod/firmware/target/arm/pp/timer-pp.c` and `pcm-pp.c`: Timer2 reload,
  interrupt acknowledgement and FIQ routing through interrupt priority bits.
- `../ipod/firmware/target/arm/pp/system-pp502x.c` and `../ipod/bootloader/ipod.c`:
  system reset bit and PP5020 Apple disk-mode marker.
- `../ipod/firmware/target/arm/ipod/backlight-4g_color.c`: GPIO/PWM backlight.
- `../pocketjs-ipodphoto/hosts/ipod-photo/src/audio.c` and `audio_dma.c`: P98
  WM8975 address and mute/power-down registers, bounded bus and DMA stop facts.
- `../pocketjs-ipodphoto/hosts/ipod-photo/boot/crt0.S`: observed loader low-memory
  SDRAM alias contract and bounded cache transition concerns.
- `../pocketjs-ipodphoto/hosts/ipod-photo/tools/pack_ipod.py`: external legacy
  transport wrapper: big-endian checksum `(3 + sum(payload)) mod 2^32`, ASCII
  `ipco`, then flat image. This wrapper does not make a payload boot compatible.

Only hardware facts informed this implementation; no upstream firmware APIs,
runtime architecture or source routines are imported.

## Native installation and current hardware evidence

The inspected device originally selected PocketJS directly through the Apple
format-3 OSOS directory. The bootstrap planner validates the original complete
firmware backup and chooses an all-zero staging region after every referenced
image. A devOffset is relative to one sector into the firmware partition.
Installation writes and verifies candidate bytes before replacing the one
512-byte directory sector; the original PocketJS payload remains intact.

Upgrade planning pins the SHA-256 of the preceding plan and independently
validates its artifacts and directory derivation. Each replacement uses a new
region after all pinned predecessor stages, so publication never overwrites
the currently referenced loader. Raw-device guards accept only the original,
exact predecessor or exact candidate directory and staged bytes. Every other
byte in the firmware partition must match the verified original backup.
Restore reinstates the original directory and retains the staged images.
This device-specific bootstrap is separate from future persistent A/B updates.

Native Boot installation and directory readback have passed on the inspected
P98 device. Early LCD and USB completion faults were repaired, including the
transport stop needed before RAM handoff. The active hardware receipt
`out/runs/20260906T031506Z-photo4g-p98-def6c43d345e-0001/receipt.json` records
healthy native OS RAM boots with the expected build identity, complete LOS
SHA-256, advancing generation and readiness mask 31. That mask reports completed
initialization milestones; it does not establish visual quality or performance
budgets. The user revised the requirement to 20 healthy cycles; 22 were recorded
before stopping the repeated boots. Resumed receipt
`out/runs/20260906T032437Z-photo4g-p98-def6c43d345e-0001/receipt.json` preserves
that source evidence and passes crash recovery before and after the healthy
marker, FIQ watchdog recovery, OS/Boot/Disk Mode reboot and release exclusion.
Batch 0 is qualified under the revised 20-cycle requirement for the exact
recorded builds. COP reset escalation with FIQ masked was not separately tested.

## Batch 1 platform candidate

The executive owns 64 fixed event slots shared by five service queues and 16
replaceable deadlines. Scene allocation uses a bounded arena with generation
checks. The shell renders menu damage into a CPU-owned RGB565 buffer; presentation
copies into a separate immutable scanout buffer before publishing up to eight
jobs to the resident COP worker. A versioned nonce handshake establishes worker
capability. CPU fallback is explicit and cannot satisfy COP qualification.

The resident worker and its stack occupy IRAM `0x40001000..0x40002fff`;
its mailbox occupies SDRAM `0x01ffd000..0x01ffdfff`. Clock changes park an
acknowledged worker and execute a bounded IRAM transaction at `0x4000d000`.
Cache maintenance has a reserved IRAM stack at `0x4000e000..0x4000efff`.
Cache remains disabled by default. SDRAM checks validate owned memory through
both aliases while preserving inherited geometry. Clock readback establishes
configuration, not an independent frequency measurement.

Input interrupts feed wheel, buttons, hold and headphone state. Idle uses a
one-shot timer and the next service deadline, bounded by the watchdog lease.
Power sampling uses bounded PMU transfers. Sleep retains CPU state and turns
off the backlight; it is not PMU deep standby. Charging current changes require
the caller's negotiated USB budget. The shutdown API requires callers to
quiesce peripherals before PMU standby.

Batch 1 Boot `5817b0695d94dac7c342eaafdfb10cdbcf487a48ed716f48f53182b15fe29438`
has passed installation readback under `out/native-bootstrap-b01-01/`.
The original PocketJS payload and all five predecessor stages remain verified.
Compilation and local bounded-memory checks pass. Hardware automation passed on
OS `815b69a9df3f7c0e98e7be66ad653a4a92bf5005177fcadd2a2262c66cddb9d1` in
`out/runs/20260906T040313Z-photo4g-p98-815b69a9df3f-0001/receipt.json`:
256 balanced navigation events, zero drops, 1,193 us maximum event latency,
14 us maximum C IRQ dispatcher duration, 40 COP animation frames, ring reset,
three sleep/wake cycles and matching initial/final screenshot CRC `fa479671`.
Idle residency increased 496,684 us during a 500 ms observation with no redraw
or event processing. The event pool high-water mark was 16 of 64, deadline
high-water mark 1 of 16, and scene arena high-water mark 32 of 2,048 bytes.
Full-frame presentation reached 108,705 us; smaller animation damage completed
the campaign. These timings do not establish later product frame-rate gates.

Initialization repairs normalize dormant COP state only after a versioned
pause handshake. Screenshot CRC uses a local lookup table while freezing pixels,
avoiding a full bitwise checksum pass that triggered the watchdog. Development
RX reprimes before executive idle; buffered RX prevents sleeping. An upload
from the running OS and subsequent RAM boot passed after this correction.
Software Disk Mode entry passed. Ordinary Apple Disk Mode eject does not
guarantee CPU restart. The automatic restart path refreshes the exact installed
512-byte boot-directory sector after validating the pinned plan, device identity
and complete firmware. It verifies the sector and complete firmware again before
ejecting, then requires reconnection of the exact Boot build from the plan.
The first hardware refresh/eject run passed with zero changed bytes:
`out/b01-directory-refresh-01.json` and `out/b01-refreshed-eject-01.json`.
This is a guarded media write, not a generic USB reset or firmware installation.

Release `d72d015b812633d2559e8e97625a03d07fad743bbced8320cb2dc3d0f55e32e7`
passes release exclusion with a 19,268-byte payload. Physical controls and
screen verification were still pending for that earlier candidate; the final
qualified build is recorded below.



The integrated `device eject --reboot` command passed in
`out/b01-auto-eject-native.json`, with guarded refresh receipt
`out/disk-restart-eb81d3c9215c45e6aca3c699eb240a3f.json`. Native Windows elevation
replaced a nested PowerShell launcher that stalled before device access. The
returning Boot matched the installed plan and firmware bytes remained identical.
CLI startup uses bounded read-only HELLO probing before identity confirmation;
mutation commands are never replayed on an uncertain acknowledgement.

The user confirmed Select/Menu, Hold, headphone transitions and a clean screen
on the platform shell. Hardware observations are retained in
`out/b01-physical-input-observation.json` and
`out/b01-physical-input-observation-2.json`. They reported excessive wheel
sensitivity. Physical wheel movement now accumulates eight of the 96 sensor
positions per menu step; synthetic navigation remains expressed in whole steps.
Left/right now switch the visible section inside detail pages. A short Play/Pause press has no media playback behavior in Batch 1; the
subsequent shutdown addition is described below.

The adjusted OS is
`8af5ad4f058c8e827d04a6e7830f6526a5daaf7b32658df257f7339b291c490c`.
Its complete automated campaign passed in
`out/runs/20260906T042149Z-photo4g-p98-8af5ad4f058c-0001/receipt.json`:
zero drops, maximum event latency 2,533 us, C IRQ duration 13 us, and full-frame
presentation 107,389 us. Its release counterpart
`1484a150ec871e6d50b7530a9c2ad22aff18892cd67a90ec846a44fa70133426`
passes exclusion at 19,392 bytes. The user confirmed the adjusted wheel and
section navigation: "much better! all works!" A subsequent read verified the
exact running build, healthy state, physical input packets and zero dropped
events. Batch 1 is hardware-qualified. The final receipt preserves the original
automated receipt byte-for-byte as `receipt-automated.json` and records the
physical observations with their source build identities. Sleep/wake and
brightness transitions were qualified by automation, not separately observed
manual power tests.


## Long-press shutdown

Physical Play/Pause held alone for two seconds starts terminal shutdown. The
executive includes this deadline in its next wake time; release, another held
button, or the physical Hold switch cancels it. Synthetic button injection does
not arm a terminal power action. A separate tracking flag makes timer wrap and
zero timestamps unambiguous.

Shutdown pauses COP presentation, stops audio/DMA and development USB, disables
the CPU and COP watchdog lease, masks interrupts, and turns off the backlight.
The PCF50605 standby request retains EXTONWAK. CHGWAK is enabled only when no
external power is present, avoiding immediate restart with USB attached.
A failed prerequisite or PMU write records panic reason 33. A successful bus
write without actual power-down within 200 ms also takes that failure path.
Release panic rearms and unmasks its reset FIQ so recovery does not require COP.

Development and release compilation, release exclusion and the platform
regression campaign pass for development OS `20415bc07091`. Physical testing
confirmed short-tap cancellation, sustained power-off with USB attached, and
manual power-on. Evidence is recorded in `out/b01-shutdown-qualified.json`, with
the regression receipt at
`out/runs/20260906T043246Z-photo4g-p98-20415bc07091-0001/receipt.json`.
Shutdown does not yet flush a storage service because
Batch 2 storage is not implemented; that service must join this sequence when
introduced.

## Batch 2 storage and persistent boot

The storage owner discovers the physical ATA capacity, validates the MBR and its
non-overlapping partitions, and selects exactly one FAT32 partition. Subsequent
block requests and read-ahead are confined to that partition. PP5020 uses PIO0
with at most eight 512-byte sectors per command; DMA remains disabled pending
hardware qualification. An eight-entry queue snapshots writes, coalesces adjacent
requests of one generation, caches read-ahead, and delivers tagged completions.
Read errors may retry once. Writes and flush failures propagate without replay;
uncertain durability prevents a successful shutdown barrier. Quiesce drains the
queue, flushes and enters standby. System PMU shutdown then removes power.

FAT32 operations advance through bounded polling steps. BPB geometry, sector
bounds, FAT mirrors, path depth and 8.3 components are validated. Full chain
checks detect loops and truncated files. Before writes, all provisioned files
and traversed directory chains must have distinct terminal clusters: two valid
singly linked chains that intersect necessarily share a terminal cluster.
This proves those files and directories do not share allocation. Fixed caches
avoid repeated full scans. Dirty or inconsistent volumes deny writes.

Create and grow use detached allocation. New sectors are zeroed; growth copies
the old contents into a replacement chain. Data and FAT mirrors are flushed
before publishing the directory entry; the old chain is reclaimed only after
that publication is flushed. FSInfo hints become unknown and the volume is
marked dirty during mutation. Failures invalidate handles and write proofs;
interrupted allocation can leak clusters and needs host filesystem repair.
The allocator supports existing parent directories and 8.3 names, without
directory expansion, shrinking or long-name creation. `WORK.BIN` is the optional
eighth file used by the device create/grow campaign, bounded to 1 MiB.

The runtime facade owns seven preallocated files under `/LINNET`: `OS0.LOS` and
`OS1.LOS` are 8 MiB each; `BOOT0.BIN`, `BOOT1.BIN`, `STATE0.BIN`, and `STATE1.BIN`
are 512 bytes each; `SCRATCH.BIN` is 4 MiB. Host preparation writes a verified
file set with boot metadata last. Initial provisioning refuses existing files,
checks the exact physical USB disk serial and FAT32 volume, and never changes
the native firmware partition. The Batch 2 native Boot update remains a separate
guarded installation using the established backup/plan mechanism.

State publication writes the inactive record, flushes, reads it back, and only
then advances the in-memory generation. CRCs and monotonically increasing
generations select the last complete record. A failed publication poisons that
store until reopen. Equal generations with different contents are rejected.
Persistent installation first withdraws the inactive candidate, streams its LOS
bytes, flushes, re-reads and validates SHA-256 plus the complete LOS policy, then
publishes candidate metadata. Boot validates images again and durably records
an attempt before executing the selected slot. An unconfirmed attempt rolls
back on the next Boot entry. All five readiness bits and the exact running image
identity are required to confirm a candidate.

A CRC-protected 80-byte handoff at `0x01fff100` communicates the selected slot,
build and SHA to the OS; linker assertions separate it from retained crash data.
Boot clears the marker before selection. Recovered development Boot remains
available after rollback; an explicit persistent restart performs a cold boot.
Release uses a separate bounded IRAM copy routine and has no Linnet Link or
development recovery transport. Its staging window is explicitly reserved.

During file operations the facade advances block work, services the shell at
bounded intervals, and progresses USB DMA without recursively accepting another
command. Shutdown and Disk Mode actions wait until this owner returns. Lower
I/O deadlines, a total-operation deadline and a stalled-clock escape bound waits.
Physical System → Select enters Apple's standard Disk Mode after storage
quiescence in both profiles. Apple firmware provides mass storage; Linnet never
mounts FAT concurrently with the host. Release contains no developer USB stack.

Offline builds and source checks are distinct from the Batch 2 hardware gate.
PIO timing, flush durability, reconnect behavior, power transitions and actual
candidate rollback must pass the connected campaigns before qualification.
