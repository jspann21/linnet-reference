# Linnet Link Protocol

`device media-info --port COMx` reads command 95 with an empty payload. Replace
`COMx` with the currently discovered port for the intended device. The
192-byte MEDI response reports discovered media and power state without waking
the drive. Fields are documented in `storage.md` and `formats.md`.
Storage data commands allow 45 seconds to cover a bounded 30-second cold wake;
this changes the protocol deadline, not the serial endpoint configuration.

Linnet Link is a development-only binary protocol. Host framing, an optional
serial adapter, a bounded native framing codec and command dispatcher establish
the development software contracts. The native PP5020 CDC ACM driver implements endpoint
descriptors, control transfers and bulk DMA. Serial port discovery alone does not establish Linnet Link support.

## Device ownership and connection

Coordinate with other active work before opening a serial port, entering Disk
Mode, ejecting, rebooting, installing firmware, or writing device files.
Discover connected devices and select the intended Linnet endpoint by its
observed USB serial and target. Never hard-code or reuse a USB serial, COM port,
disk number, storage serial, or target identity from another device or session.
A COM number is only a current Windows assignment; do not probe unrelated ports.

Install `pyserial==3.5`. `python linnet device info` lists serial metadata without
opening or probing candidate ports. After selecting the intended endpoint,
`python linnet device info --port COMx` performs HELLO and STATUS. Before every
mutation, match the observed USB serial, target, profile, image kind, build ID,
image SHA-256, boot generation, health, and advertised capabilities to the
intended operation. Never infer device identity from a COM or disk number.

Linnet Link exists in development and trace firmware; release images exclude it.
USB reset, reconnect, reconfiguration, and DTR changes create a new session. A
boot generation is device runtime state and is distinct from the USB connection
generation. A missing, corrupt, mismatched, rejected multi-command, or
out-of-order acknowledgement poisons the session. Close it, rediscover by USB
serial, reconnect, and inspect identity and state. Never automatically replay a
mutation.

## Entering and leaving Apple Disk Mode

Read this before sending command 34 or updating files through Apple's Disk
Mode. A complete interactive round trip on Windows is:

```powershell
python linnet device reboot --mode disk --port COMx
# Perform the intended filesystem work while the iPod is mounted.
python linnet device eject --reboot --disk-number N --expected-serial STORAGE_SERIAL --allow-uac
```

Replace `COMx` and `N` with the currently observed Linnet port and Windows disk
number for the intended device. Discover and validate its USB serial, target,
storage serial, port, and disk identity for every session; never reuse another
device's values. The first command asks the running Linnet image to start Apple
Disk Mode. The second command resolves the current installation record from the
mounted iPod, validates the disk and installed Boot state, rewrites the exact
same guarded firmware-directory sector, ejects storage, and verifies that Linnet
Link returns. An explicit `--plan` and `--plan-sha256` are low-level overrides,
not the normal workflow. Do not look in archived `out/` directories or old
worktrees for a plan.

Do not use plain `device eject`, `device eject --wait-link`, Windows Shell eject,
or the Media Manager's storage-only eject to finish a Linnet-initiated Disk Mode
session. They only remove storage. They do not request a firmware restart and
can leave Apple Disk Mode running while Windows reports **No Media** and Linnet
has no COM endpoint. `--wait-link` only observes; it never changes that state.

If `device eject --reboot` fails its preflight, keep the volume mounted and fix
the current installation metadata or elevation/session setup. Never substitute
a plain eject. If storage has already been ejected and the iPod has no Linnet
endpoint, no host software command can reach either firmware; use a physical
Menu+Select restart.

For an unattended workflow, prepare and start the matching finite refresh session
before `device reboot --mode disk`. Treat a missing session or failed readiness
check as a reason not to enter Disk Mode. The session procedure is documented
under [Finite refresh sessions](#finite-refresh-sessions).

## Frame layout

All integers are unsigned little endian. Frames have a 20-byte header, zero to
1024 payload bytes, and a four-byte IEEE CRC32 covering header and payload.

| Offset | Bytes | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `LINK` |
| 4 | 2 | Reserved, must be zero |
| 6 | 2 | Flags: request 0, acknowledgement 1, rejected acknowledgement 3 |
| 8 | 2 | Command |
| 10 | 2 | Reserved, must be zero |
| 12 | 4 | Sequence, starts at 1 |
| 16 | 4 | Payload length |
| 20 | variable | Payload |
| 20 + length | 4 | CRC32 |

The receiver rejects nonzero reserved fields, illegal flags, zero or
repeated sequences, oversized payloads and incorrect CRCs. Sequence increases
monotonically per connection; wrap requires a new connection. Acknowledgements
echo the command and sequence. Framing corruption invalidates the session; there
is no scanning for magic inside untrusted payload. The native parser has a fixed
1048-byte buffer and processes at most one frame per completion. Frame payload
pointers borrow that buffer until the next input byte. Connection owners must
reset the parser on connection establishment and discard requests with ACK flags
before dispatching mutation. A new session does not authorize replaying old work.

## Commands

| ID | Command | Request / successful response |
| --- | --- | --- |
| 1 | HELLO | Empty / endpoint identity |
| 2 | INFO | Empty / target and build identity |
| 3 | STATUS | Empty / boot generation and state |
| 16 | UPLOAD_BEGIN | u32 length, u32 image CRC32, SHA256[32] / u32 zero |
| 17 | UPLOAD_CHUNK | u32 offset, 1..1020 bytes / u32 next accepted offset |
| 18 | UPLOAD_END | Empty / u32 complete length |
| 19 | VERIFY | Empty / verified image identity |
| 20 | BOOT_RAM | Empty / explicit accepted acknowledgement before transition |
| 32 | REBOOT_NORMAL | Empty / accepted acknowledgement |
| 33 | REBOOT_RECOVERY | Empty / accepted acknowledgement |
| 34 | REBOOT_DISK | Empty / accepted acknowledgement |
| 48 | READ_LOG | Empty / 96-byte completion and recovery diagnostic snapshot |
| 49 | READ_METRICS | Empty / bounded metrics data |
| 50 | READ_CRASH | Empty / bounded crash record |
| 51 | CLEAR_CRASH | Empty / accepted acknowledgement |
| 52 | CRASH | u32 mode, currently zero only / accepted acknowledgement before deliberate fault |
| 53 | STARTUP_TIMING | Empty / 64-byte retained startup timing record |
| 54 | BOOT_TIMELINE | Empty / 192-byte Boot and OS timeline record |
| 64 | PLATFORM_STATE | Empty / 128-byte `PLAT` state record |
| 65 | INJECT_INPUT | Boot generation, count, event triples / generation and accepted count |
| 66 | CAPTURE_SCREEN | Boot generation / 28-byte immutable snapshot descriptor |
| 67 | SCREEN_READ | Capture ID, boot generation, offset, length / capture ID, generation, offset, pixel bytes |
| 68 | PLATFORM_CONTROL | Boot generation, action, argument / same three words on acceptance |
| 69 | UI_STATE | Empty / 64-byte `UIST` native UI record |
| 70 | INPUT_STATE | Empty / 64-byte `INP1` low-level input diagnostic record |
| 80 | STORAGE_STATE | Empty / 96-byte `STOR` record |
| 81 | SCRATCH_READ | Offset and length / offset and bytes |
| 82 | SCRATCH_WRITE | Generation, offset and bytes / generation and end offset |
| 83 | SETTINGS_GET | Empty / generation and settings bytes |
| 84 | SETTINGS_PUT | Generation and settings bytes / generation and length |
| 85 | UPDATE_BEGIN | Generation, image length and SHA-256 / generation and zero |
| 86 | UPDATE_CHUNK | Generation, offset and bytes / generation and end offset |
| 87 | UPDATE_FINISH | Generation / generation and zero after durable verification |
| 88 | UPDATE_STATUS | Empty / 64-byte `USTA` record |
| 89 | STORAGE_FAULT | Generation and mode / generation and mode |
| 91 | STORAGE_RECOVER | Generation / generation and zero |
| 92 | REBOOT_PERSISTENT | Generation / accepted acknowledgement before transition |
| 93 | PUBLICATION_FAULT | Generation and stage / generation and stage |
| 94 | ATA_DIAGNOSTICS | Empty or diagnostic subcommand / fixed diagnostic record |
| 95 | MEDIA_INFO | Empty / 192-byte `MEDI` record |
| 96 | FILE_RESIZE | Generation, create/grow action and size / generation and size |
| 97 | WORK_READ | Offset and length / offset and bytes |
| 98 | WORK_WRITE | Generation, offset and bytes / generation and end offset |
| 100 | NATIVE_BEGIN | Generation, package length and SHA-256 / generation and zero |
| 101 | NATIVE_CHUNK | Generation, offset and bytes / generation and end offset |
| 102 | NATIVE_APPLY | Generation / generation and zero after complete verification |
| 103 | NATIVE_STATUS | Empty / 64-byte `LNPK` status |
| 112 | AUDIO_STATE | Empty / 80-byte `AUDS` record |
| 113 | AUDIO_CONFIG | Generation and sample rate / generation and rate |
| 114 | AUDIO_PCM | Generation, expected frame offset and stereo PCM / generation and next frame offset |
| 115 | AUDIO_CONTROL | Generation, action and argument / generation and action |
| 116 | PLAYER_STATE | Empty / 64-byte `PLYR` record |
| 117 | PLAYER_OPEN | Generation and NUL-terminated absolute ASCII path / generation and zero |
| 118 | PLAYER_CONTROL | Generation, action and optional seek position / generation and action |
| 119 | LIBRARY_STATE | Empty / 64-byte `LIBS` record and library SHA-256 |
| 120 | PLAYER_TIMING_STATE | Empty / 124-byte `TIME` record |
| 121 | PHOTOS_STATE | Empty / 128-byte `PHOT` record |
| 122 | VIDEO_STATE | Empty or development metadata page / 128-byte `VIDS` or metadata record |
| 123 | VIDEO_MEASUREMENT | Generation and mode / generation and mode |

HELLO, INFO and STATUS return the same 96-byte native identity record:
`LNID` at offset 0; u32 target ID at 4, reserved zero at 8, profile at 12, image kind
at 16 (OS 0, Boot 1), health flags at 20, boot generation at 24 and capabilities
at 28; raw build ID[32] at 32 and image SHA256[32] at 64. Capability bits are
upload 1, RAM boot 2, deliberate crash 4, OS reboot 8, Boot reboot 16 and disk
reboot 32. Only advertised and locally available actions may be accepted.
VERIFY returns the verified image SHA256[32]. JSON stays on the host.
Command identifiers reserve the intended operation;
an unsupported operation must reject explicitly, never report success. The
implemented storage and installation commands are described below; log
subscription is not implemented.

Reserved command gaps are unsupported and must be rejected. New commands must
be added to the protocol enum, native dispatcher, host validation, release
exclusion, and this document. Do not send experimental numeric commands to
physical hardware.

## Host CLI reference

Use the CLI when it exposes an operation. It performs identity checks, bounded
timeouts, reply validation, and reconnect handling that raw requests do not.
Commands emit JSON on stdout. Operations that need durable evidence keep a
bounded receipt below `out/runs/`.

Passive commands are:

- `device info` to list ports without probing, or `device info --port COMx` to
  read HELLO and STATUS for the selected endpoint.
- `device media-info --port COMx` for media geometry, identity, capabilities,
  quirks, power state, timeouts, power cycles, and spin-up state without waking
  the drive.
- `device ui-state --port COMx` for scene, selection, lifecycle, paint, dirty,
  pending action, arena, generation, and scene-count state.
- `device startup-timing --port COMx`, `device boot-timeline --port COMx`, and
  `device video-startup-timing --port COMx` for their retained timing records.
- `device storage-info --port COMx` for storage plus persistent-update state,
  and `device native-status --port COMx` for native-package progress and result.
- `device audio-state|player-state|player-timing-state|library-state|photos-state|video-state
  --port COMx` for the corresponding runtime telemetry.

Controlled mutation commands are:

- `device boot --mode ram --image IMAGE.los --port COMx` to upload, CRC/SHA
  verify, validate, and chainload once without persistent installation.
- `device reboot --mode os|boot|disk|persistent --port COMx` to request an OS,
  recovery Boot, Apple Disk Mode, or prepared persistent restart. An ACK means
  accepted for deferred execution; observe the next identity to prove completion.
- `device install --image IMAGE.los --port COMx` to publish a persistent A/B OS
  candidate, and `device native-install --package PACKAGE.lnb --package-sha256
  SHA256 --port COMx` to apply one fixed device-bound native Boot package.
- `device storage-recover --port COMx` to start an asynchronous remount; poll
  `storage-info`. `device storage-fault --mode 1..5 --port COMx` deliberately
  injects timeout-before-issue, short completion, reset-before-issue, stale
  completion, or flush failure.
- `device player-open --path /ABSOLUTE/ASCII/PATH --port COMx`, followed by
  `player-pause`, `player-resume`, `player-stop`, or
  `player-seek --sample POSITION`. Read `player-state` after acceptance.
- `device eject --reboot --disk-number N --expected-serial STORAGE_SERIAL
  --allow-uac` for the interactive Apple Disk Mode exit. Always pass the
  currently observed storage serial rather than relying on a default.
  `refresh-session prepare|start|status|stop` provides a finite plan-bound
  elevated helper for unattended exits; `refresh-session install` is the
  separately authorized reviewed-Boot installation operation.

Mount-based `device detect-retail`, `bootstrap`, `bootstrap-status`, `restore`,
and content publication commands are not Linnet Link operations.

`tools.link.session.Session` additionally exposes direct helpers for identity,
upload/verify/boot, crash read, platform state/input/control/capture, media and
storage state, storage performance and timing, ATA capabilities, scratch,
settings, WORK, persistent publication, native maintenance, publication faults,
and video measurement. Use these only when no CLI command covers the task,
and preserve the same identity, generation, timeout, evidence, and ambiguity
rules.

## Logs, crashes, and low-level diagnostics

`READ_LOG` returns the bounded 96-byte completion and recovery diagnostic
snapshot. It is a snapshot, not a stream; log subscription is not implemented.
`READ_METRICS` returns the bounded 32-byte native metrics record.

`READ_CRASH` returns the retained 144-byte CRC-protected `CRSH` mailbox with its
sequence, reason, r0..r15, CPSR, flags, build identity, boot generation, service,
and event. `CLEAR_CRASH` clears it. `CRASH` accepts only mode zero and
deliberately faults after the acceptance ACK retires. Clearing or triggering a
crash has no standalone CLI command and must never be retried after an uncertain
acknowledgement.

`STARTUP_TIMING` records candidate validation, copy, entry, BSS, IRAM and C-entry
timestamps. `BOOT_TIMELINE` records native Boot and OS milestones, intervals,
image I/O/hash counters, inherited clock/cache state, and Boot clock-transition
diagnostics. The CLI validates their size, magic, generation, masks, counters,
and only reports intervals whose endpoints exist.

`INPUT_STATE` returns sixteen words beginning with `INP1`: input poll, ready-read,
packet and invalid-packet counters; last controller status, packet, and wheel
position; and the relevant controller registers. It has no standalone CLI
wrapper.

`ATA_DIAGNOSTICS` is a passive diagnostic multiplexer. Empty payload returns the
base 24-word ATA record. Development subcommands are:

| Subcommand | Record or purpose |
| ---: | --- |
| 1 | `SIOP`: block/ATA command, sector, wall-time, service-time, poll, queue, retry, failure and timeout performance |
| 2 | `POLL`: storage poll, progress, FAT and runtime callback inclusive timing |
| 3 | `ACAP`: cached IDENTIFY capability words plus passive controller and clock registers |
| 4 | `RNDR`: dirty render and publication timing |
| 5 | `SCHD`: scheduler opportunity, wait, overdue, completion-age and cancellation telemetry |
| 6 | ATA clock diagnostics |
| 7 | `DSYN`: display synchronization and presentation timing |
| 8 | `BLIT`: resident display-worker, packed scanout and queue consistency |
| 9 | Target LCD register and panel snapshot, where implemented |
| 10 | Target runtime idle-clock diagnostics, where implemented |
| 11 | Cover Flow diagnostics, where compiled |

`Session` has validated helpers for subcommands 1 through 5. The remaining
subcommands are low-level and can reject based on target, image kind, profile,
or compiled features.

## Platform commands

Commands 64 through 68 are available in development and trace OS images. They
use normal frame sequence, CRC and acknowledgement rules. Their
generation field is the running boot generation from `LNID`, not the USB
connection counter. A mismatching generation is rejected before mutation.
The exact state and screenshot layouts are in [formats.md](formats.md).

`PLATFORM_STATE` returns 32 words beginning with `PLAT`: generation; readiness,
sleep, COP, input and backlight flags; selection and scene; accepted, processed
and dropped events; maximum event latency and queue high-water marks; arena and
frame counters; maximum LCD presentation time; COP queue and reset state;
sleep/wake and idle counters; physical buttons, hold and headphones; synthetic
flags and last injected sequence; animation; clock; battery; charge flags; and
maximum IRQ time.

INJECT_INPUT contains u32 generation, u32 count, then 1..32 triples of u32
event sequence, u32 kind and **signed i32** value. Event sequences must increase
beyond state word 26; reopening the serial session does not reset that event
sequence. Kinds are wheel steps 1 (-64..64), button mask 2 (0..31), hold 3
(0 or 1), and headphone presence 4 (0 or 1). Button bits are Menu 1, Play 2,
Next 4, Previous 8 and Select 16; zero releases all buttons. These are synthetic
events, not physical observations. Physical switch and headphone readings remain
separate in the state record.

Input shapes are checked before applying the request. A successful ACK contains
generation and count. If the runtime rejects a later event, the error ACK
contains generation and the accepted prefix count; it does not undo that prefix.
Stop and inspect state, including the last accepted event sequence, before a new
decision. Never replay the request automatically. Other platform error ACKs contain
generation and zero. An input ACK means queued acceptance; observe processed
counters and display completion before asserting a visible result.

PLATFORM_CONTROL actions are:

| Action | Operation | Argument |
| --- | --- | --- |
| 1 | Sleep with scheduled wake | 50..1000 milliseconds; rejected while sleeping or display busy |
| 2 | Wake | 0 |
| 3 | Backlight level | 0..100 percent; zero disables it |
| 4 | Reset COP display queue | 0; requests a full redraw |
| 5 | Start animation | 1..120 frames; rejected while an animation is active |
| 6 | Clear synthetic switch overrides | 0; restores physical hold/headphone state |
| 7 | Reset shell | 0; requires no queued events, animation or sleep |
| 8 | Target display diagnostic | Target-specific argument; rejected when the target does not implement it |

Control ACKs confirm acceptance. Poll state for asynchronous completion. In
particular, a COP queue reset advances its reset counter and requests a redraw;
wait for submitted and completed frame counters to match before testing sleep
or idle behavior. CPU rendering fallback does not exercise the COP queue.

CAPTURE_SCREEN freezes the target-native RGB565 frame in a development-only
buffer sized from the target display. Its descriptor reports width, height and
byte length. SCREEN_READ accepts 1..1008 bytes within that buffer.
Every chunk echoes the capture ID, boot generation and offset. The frozen bytes
remain unchanged during animation until another capture replaces them or the
image restarts. A stale capture ID, changed boot generation or out-of-range read
is rejected. The host verifies the full raw framebuffer CRC before saving a PNG
preview; capture proves framebuffer contents, not physical LCD appearance.

`Session.capture_screen()` reads the descriptor and chunks, verifies the complete
framebuffer CRC, and returns the RGB565 bytes and dimensions. Save or convert a
capture only when the current task needs it. Physical LCD appearance, buttons,
wheel, switches, headphones, visible backlight, and wake behavior are observations
made on the device rather than claims derived from the captured framebuffer.

## Native UI inspection

For panel timing, command 94 with u32 subcommand 7 returns sixteen u32 words:
`DSYN`, reserved zero, synchronized frames, pulse timeouts, last wait us, maximum
wait us, waiting flag, frame-pending flag, submitted frames, completed frames,
LCD failures, pixel pairs written, maximum presentation us (including the
sync wait), last transfer us, maximum transfer us, and snapshot tick.
This is a passive development-only snapshot. P98 GPIO A0 was measured with
an active-low pulse of approximately 579 us every 16,575 us. Presentation arms
its interrupt only for a pending frame and falls back after 25 ms without a
pulse. Screen captures still cannot establish physical tear-free scanout.

Command 94 subcommand 8 returns sixteen u32 words: `BLIT`, reserved zero,
helper byte count, live pixel hook, live command hook, expected command hook,
first resident mismatch offset (`0xffffffff` when exact), expected and live
words at that mismatch, column-buffer pixel mismatch count (`0xffffffff`
when inactive or in a direct transaction), queue head, queue tail, LCD failures,
and three reserved zeros. This passive development-only check compares the
complete packed scanout with the logical draw buffer. Run it while navigation
is idle; its full-frame comparison is diagnostic work, not a render-path cost.
The column helper is installed only into the exact preserved Boot worker.
It uses panel register 0x18 mode 0 and ascending native column coordinates,
as observed in the local RetailOS image, with right-to-left logical columns.


Command 69, UI_STATE, takes an empty payload and returns 16 little-endian u32
words in development/trace OS images built with the native UI. The command is
read-only and uses the normal frame sequence and CRC rules. An image without
native UI state rejects it. The reply has these word indices:

| Word | Meaning |
| --- | --- |
| 0 | ASCII `UIST` |
| 1 | Reserved, zero |
| 2 | Current scene index |
| 3 | Selected item index |
| 4 | Scene lifecycle epoch |
| 5 | Scene transition count |
| 6 | Native paint count |
| 7 | Accumulated painted pixels |
| 8 | Visible items from the most recent paint |
| 9 | Pending dirty bits |
| 10 | Pending native action; UINT32_MAX means none |
| 11 | Scene arena bytes used |
| 12 | Scene arena high-water bytes |
| 13 | Scene arena generation |
| 14 | Current boot generation |
| 15 | Compiled scene count |

Scene indices refer to the ordered scenes in the matching generated
`scenes.json`; they are not persistent app identifiers. Boot generation is
independent of scene epoch, arena generation and USB connection generation.
The CLI verifies the size and magic and prints named fields alongside the
HELLO identity:

```powershell
python linnet build --profile dev --device-serial DEVICE_USB_SERIAL --verify
python linnet device ui-state --port COMx
python linnet ui compile --system themes/midnight/system.toml --output out/ui-midnight
python linnet simulator --system themes/midnight/system.toml --tape out/ui-tape.json --output out/simulator-midnight
```

The compiler lowers constrained TSX to static native component data, resources
and explicitly declared native canvas callbacks. The simulator runs those same
generated scenes and the native renderer; its JSON tape uses event objects with
`kind`, `value`, optional `repeat` and optional `capture`. Kinds 1..4 match the
input meanings above; kind 0 renders without input. The tape has at most 100,000
expanded events and 512 requested captures. See the [README example](../README.md#native-ui-and-customization)
and [SDK grammar](../sdk/README.md).

Commands 65..68 provide synthetic input, immutable screen capture and bounded
platform controls for device comparison. UI_STATE adds paint and arena counters
for detecting unnecessary redraws and scene lifecycle changes. Capture CRCs
describe the framebuffer; simulator agreement cannot establish physical LCD
quality or wheel feel.

## Upload and uncertainty

The generic host upload API allows images up to 16 MiB. The physical P98
staging region accepts at most 8 MiB including the LOS header.
The upload owns one staging region and
accepts contiguous offsets only. Each chunk receives an explicit next-offset
acknowledgement; the host pipelines up to four chunks before collecting their
acknowledgements. A streaming window therefore covers up to 4080 bytes without
waiting between individual writes. Upload completion checks full-image CRC32
and SHA256. These hashes detect corruption and identify content; they are not
signatures or authentication. VERIFY must additionally validate the image
container and target constraints before BOOT_RAM is allowed.

No transaction is automatically retried. Missing, corrupt, out-of-order or
wrong-command acknowledgements poison the host session and raise
`AmbiguousCommand`. A rejected multi-command window is also uncertain because
other queued commands may have executed. Close the session, rediscover by stable
USB serial identity, reconnect, and inspect identity/state before a new decision.
Never replay BOOT_RAM, a reboot, crash clearing, or an upload mutation merely
because its acknowledgement was lost. Offset-based resume is deferred until
the device exposes a verified image identity plus committed offset. Ordinary
operations must never overwrite the developer loader.

## Host integration and release exclusion

`hal/link/dispatch.h` defines the native backend contract. The dispatcher tracks
contiguous uploads, incrementally checks full image CRC32, and requires backend
SHA256/container verification at upload completion and VERIFY. Backend callbacks
own staging memory and must enforce the board memory plan; no address is supplied
by the wire. The read callback receives its output capacity and must respect it.
Missing callbacks reject operations. Reboots and RAM boots remain deferred until
the transport reports their exact acknowledgement sequence fully transmitted via
`ln_link_dispatch_ack_sent`; only then does it quiesce and invoke the action.
The acceptance ACK does not assert the later boot succeeded. Failure to quiesce
consumes the action without automatic retry. Connection loss discards the
dispatcher, including pending actions, and the next connection inspects state.
The required `can_action` callback rejects unsupported boot/reboot/crash modes
before accepting a transition. CRASH follows the same deferred ACK rule.

The PP5020 CDC implementation owns the fixed uncached IRAM window
`0x4000c000..0x4000ce00`: queue heads, transfer descriptors and control/bulk DMA
buffers. It requires cache-disabled entry and a linker reservation of that
window. Its single-transfer bulk buffers apply USB backpressure without dropping
bytes. The owner must call `ln_usb_poll`, handle partial `read`/`write` results,
and wait for `ln_usb_flush` success before reporting an action ACK transmitted.
Bus reset, reconfiguration, CDC DTR edges and disconnect change `ln_usb_generation`; any change
invalidates the previous parser/session. All MMIO waits have timer and iteration
bounds, and transfer faults disconnect the controller. The development descriptor
uses the existing lab identity `1209:504a`, which is not an assigned production
VID/PID. The USB serial is provisioned from the physical device identity and has
no fabricated default. Charging-current control belongs to platform integration;
the descriptor requests 100 mA and this driver never enables high-current charging.
Recovery must require `ln_usb_stop()` success before overwriting a DMA-visible
destination. It verifies controller reset completion and idle endpoint registers.
The boot-loader path keeps the USB blocks powered, as the PP5020 reference path
does; power-gate readback is not a DMA ownership condition. A successful stop is
cached until USB initialization; a failed stop cannot become success merely from
a repeated call. The void disconnect wrapper alone does not authorize a RAM
image overwrite.

`tools.link.session.Session` exposes `hello`, `info`, `status`, `upload`,
`verify`, `boot_ram`, `reboot`, and `crash_get`, using an injected transport with
deadline-bound `read`, `write`, and `close`. `SerialTransport.discover()` lists
USB metadata without probing or writing to arbitrary serial devices.
`SerialTransport.reconnect(serial_number)` searches a fresh port inventory and
rejects duplicate identities; it never assumes a fixed COM number. Physical
serial access requires optional `pyserial==3.5`. The CLI is `linnet device`;
see the root README for implemented commands.

On Windows, serial timeout setters reconfigure CDC control state. The host
therefore keeps serial settings fixed during a session and polls available bytes
against a monotonic deadline. Opening establishes a fresh DTR sequence with a
bounded settling interval. Closing after boot, reboot, or crash keeps the handle
open for up to one second so a DTR edge cannot cancel the deferred transition
while the device retires its acceptance ACK. No command is automatically replayed.

The `release` source manifest excludes all of `hal/link/`, the developer
dispatcher, platform protocol adapter, screenshot snapshot, synthetic injection
entry points, staging buffers, crash developer services and chainload code. The
release verifier checks linked symbols and protocol magic. Host tools do not
run on the device and are never packaged into the release image.

On Windows, automatic eject/restart validates the exact current installed Boot
state and observed disk identity. The normal interactive command resolves that
installation record automatically; see `python linnet device eject --help` for
the low-level explicit-plan and elevation options. Never replay an ambiguous
mutation.

## Storage commands

All integers are little-endian u32. State-changing requests start with the
current boot generation. Ordinary successful mutation replies contain generation
and an end offset/value (zero when unspecified). File paths and raw sectors are
never chosen by the wire. Commands are excluded from release builds.

| ID | Command | Request / successful response |
| --- | --- | --- |
| 80 | STORAGE_STATE | Empty / 24 words described below |
| 81 | SCRATCH_READ | Offset, length 1..1008 / offset, bytes |
| 82 | SCRATCH_WRITE | Generation, offset, 1..1008 bytes / generation, end offset |
| 83 | SETTINGS_GET | Empty / generation, 0..480 bytes |
| 84 | SETTINGS_PUT | Generation, 0..480 bytes / generation, length |
| 85 | UPDATE_BEGIN | Generation, actual LOS length, SHA256 / generation, zero |
| 86 | UPDATE_CHUNK | Generation, contiguous offset, 1..1008 bytes / generation, end |
| 87 | UPDATE_FINISH | Generation / generation, zero after durable verification |
| 88 | UPDATE_STATUS | Empty / 16 words described below |
| 89 | STORAGE_FAULT | Generation, mode 1..5 / generation, mode |
| 91 | STORAGE_RECOVER | Generation / generation, zero; remount progresses asynchronously |
| 92 | REBOOT_PERSISTENT | Generation / generation, zero; reset only after ACK retirement |
| 93 | PUBLICATION_FAULT | Generation, stage 1..4 / generation, stage |
| 96 | FILE_RESIZE | Generation, action (1 create, 2 grow), size 1..1 MiB / generation, size |
| 97 | WORK_READ | Offset, length 1..1008 / offset, bytes |
| 98 | WORK_WRITE | Generation, offset, 1..1008 bytes / generation, end offset |

STORAGE_STATE words: `STOR`, phase, error, available-file bitmask, prepared,
capacity low/high, ready, quarantined, pending, completed, submitted, retries,
failed, canceled, coalesced, cache hits, read-ahead sectors, maximum block step
microseconds, partition LBA, partition sectors, clusters, operation generation,
WORK file capacity. Phase 6 is mounted; 9 is failure. Prepared additionally requires exact
file capacities, writable volume and disjoint allocation proof.

UPDATE_STATUS words: `USTA`, available, ready, record generation, boot-state
generation, confirmed slot, candidate slot, attempt pending, attempts, slot 0
length, slot 1 length, upload active, upload slot, upload offset, poisoned, error.
Slot 255 means absent. Completion is never inferred from an acceptance ACK alone.

Fault modes are timeout before issue, short completion after transfer, reset
before issue, stale completion rejection, and flush error. These deliberately
exercise software error paths; they do not certify electrical fault handling.
Publication stages cut execution before writing the inactive record, after its
write callback, after the explicit flush, and after readback. The FAT write
callback itself flushes, so stage 2 already follows a durable file write.
Cuts reset without the normal flush barrier and are used only when explicitly
testing crash consistency. Ambiguous commands require reconnect and inspection;
none are automatically replayed.


## Native Boot maintenance commands

These commands are available in the development OS. They consume a
fixed LNPK package, never a caller-selected raw-sector operation. Mutations begin
with the current boot generation and use the normal sequence/CRC rules.

| ID | Command | Request / successful reply |
|---|---|---|
| 100 | NATIVE_BEGIN | Generation, total bytes 68096, package SHA-256 (32 bytes) / generation, zero |
| 101 | NATIVE_CHUNK | Generation, contiguous offset, 1..1008 package bytes / generation, end offset |
| 102 | NATIVE_APPLY | Generation / generation, zero after complete durable verification |
| 103 | NATIVE_STATUS | Empty / 16 little-endian u32 words |

Status words 0..7 contain `LNPK`, phase, error, received package offset, writes
bitmask, disk bytes read, elapsed microseconds, and block request generation.
Words 8..15 contain the 32-byte observed SHA-256 in byte order. The block request
generation is independent of the boot generation. Phase 10 means complete;
phase 11 means failure. Writes bit 0 records that candidate writing was attempted;
bit 1 records that directory writing was attempted. These bits alone do not prove
durability. The host requires phase 10, error zero, writes mask 3, the complete
package offset and the exact expected final firmware hash before reporting success.

Each fixed package pins the target, storage serial, USB serial, capacity, and
reviewed partition geometry from its hash-pinned plan. Never reuse a package for
another device. Its exact before-state assumes the original firmware is installed
and the new candidate region is zero. A different full firmware hash is rejected
before writing.

Apply validates the package and reconstructed Boot LOS, acquires exclusive storage
maintenance ownership after quiescing FAT activity, and checks MBR, original OSOS
and full firmware hashes. It writes the candidate once, flushes and verifies it
and the full staged firmware. Only then does it write the directory once, flush
and verify the directory and final full firmware hash. The device's total apply
budget is 600 seconds; the host allows 650 seconds for the transaction and reply.
Serial timeouts remain fixed during the session. Candidate and directory writes
are not retried after ambiguous outcomes; status inspection is a separate action.
The native directory is a single sector, so its interrupted publication does not
have the dual-record guarantee of the persistent A/B metadata.

```powershell
python linnet device native-install --package out/native-boot.lnb --package-sha256 <reviewed-package-sha256> --port COMx
python linnet device native-status --port COMx
```

Receipts are saved under `out/runs`. A successful apply still requires a separate
restart and identity observation.

No UAC elevation is used by native-install, persistent OS installation, package
preparation, or ordinary file provisioning with sufficient filesystem permissions.
The host raw-directory refresh is different: unattended callers pass
`allow_prompt=False`. They reuse a matching live refresh session or an already
elevated process, and must establish that prerequisite before entering Disk Mode.
Plain Shell eject remains available without elevation and only confirms storage
removal; it does not promise a firmware restart.

Upload startup discovery now allows up to 180 seconds for the USB endpoint,
then waits for matching healthy HELLO/STATUS before sending upload bytes.
Cold Boot may disappear while handing off to the saved OS; a responsive Home
screen can precede its serial endpoint. These waits repeat only discovery and
read-only identity/status requests. An uncertain upload is never replayed.


## Finite refresh sessions

`tools/link/refresh_session.py` provides a separate, fixed-operation Python
session. One ordinary Windows UAC launch creates a protected source snapshot
and retains the elevated process for the selected 1–24 hour lifetime. This
session supports only status, the already-reviewed identical 512-byte directory
refresh, and stop. It accepts no file paths, firmware payloads, shell commands,
or executable code from clients. Each refresh rechecks the exact iPod and full
firmware guards, closes its raw handle, and returns the existing strict receipt.
Duplicate request IDs reuse a receipt; an unacknowledged write revokes further
writes.

Prepare and inspect the local snapshot, then start it with normal consent:

```powershell
python linnet device refresh-session prepare --plan <installed-plan.json> --plan-sha256 <plan-sha256> --hours 24 > out/refresh-session-prepared.json
python linnet device refresh-session start --prepared out/refresh-session-prepared.json --allow-uac
python linnet device refresh-session status
```

Subsequent `device eject --reboot` commands automatically reuse the matching
live session. Omit `--allow-uac` for unattended use: if the session is unavailable
and the calling process is not elevated, the command fails without a prompt.
Any unattended Disk Mode workflow must check for a matching live session before
entering Disk Mode. OS/package installation through Linnet Link already needs no elevation;
this session covers the remaining Windows Disk Mode restart operation. A new
Boot plan needs a new bound session. Stop explicitly with:

```powershell
python linnet device refresh-session stop
```

The process survives the launcher and individual CLI commands. It ends at the
chosen expiry, explicit stop, or Windows logoff/restart; it is not an automatically
starting Windows service.

## Audio and player commands

`AUDIO_STATE` is passive. Its `AUDS` record reports sample rate, queued and free
frames, consumed and submitted frames, interrupts, underruns, inserted silence,
fault, playing/paused/initialized state, last and maximum IRQ time, volume in
tenths of a decibel, FIFO-empty interrupts, and maximum completion interval and
lateness.

The raw audio mutation commands have no public CLI wrapper. `AUDIO_CONFIG`
initializes the requested sample rate. `AUDIO_PCM` submits sequential stereo
16-bit PCM frames and requires the exact current submitted-frame offset.
`AUDIO_CONTROL` actions are start 1, pause 2, stop 3, volume 4, and finish 5.
These commands are generation-bound and reject incompatible storage, player, or
video ownership. Use them only through a purpose-built, receipt-producing host
operation.

`PLAYER_STATE` returns phase, error, generation, sample rate, decode/render and
underrun counters, total frames, pending transition, gapless join counters, and
current position. `PLAYER_OPEN` accepts a generation plus an absolute NUL-
terminated ASCII path of at most 255 bytes. `PLAYER_CONTROL` actions are pause
1, resume 2, stop 3, and seek 4; seek adds an unsigned 64-bit sample position.
The corresponding CLI commands perform a fresh STATUS identity check before
sending a mutation and poison the session on any acknowledgement mismatch.

`LIBRARY_STATE` reports library phase, signed error, tracks, groups, verified
bytes, revision, and SHA-256. `PLAYER_TIMING_STATE` reports cumulative decoder,
DSP, runtime, music, storage, Link and MP3 frame/synthesis/PCM timing plus clock,
cache, idle, and decoder identity. Timing counters are observations, not proof
of audible correctness.

## Media diagnostics

Development command 121 (`PHOTOS_STATE`) is read-only and returns 32
little-endian words. Its `PHOT` header is followed by the complete current photo
state and timing snapshot documented by `tools/link/music.py`. The running CRC
is unfinalized and must be XORed with `0xffffffff` before comparison. View values
are albums 0, grid 1, viewer 2. Release firmware excludes this command.

Development command 122 (`VIDEO_STATE`) returns exactly 128 bytes with a `VIDS`
header and the complete current playback, storage, audio and timing snapshot.
Development metadata pages 0 through 8 are also available. Passing page 8
returns exactly 128 bytes with a `VMEA` header for startup
milestones. Latencies are measured from video open; zero means the milestone has
not occurred. `python linnet device video-startup-timing --port COMx` reads the
passive snapshot.

Development command 123 (`VIDEO_MEASUREMENT`) accepts the current generation
and mode 0 cancel, 1 display, or 2 no display. It requires inactive, drained
video; does not open media; preserves resume state; and stops after eight seconds
of playback or preparation. `Session.video_measurement()` validates its reply;
there is no standalone CLI command.

Player timing uses the fixed 124-byte `TIME` record. It includes clock and
decoder identity plus cumulative MP3 decode, synthesis and PCM conversion
counters. These records are exact current layouts: any other header or length is
rejected.
