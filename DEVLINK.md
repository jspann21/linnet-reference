# Linnet Link Protocol

`device media-info --port COM6` reads command 95 with an empty payload. The
192-byte LMD2 response reports discovered media and power state without waking
the drive. Fields are documented in `STORAGE_COMPATIBILITY.md` and `FORMATS.md`.
Storage data commands allow 45 seconds to cover a bounded 30-second cold wake;
this changes the protocol deadline, not the serial endpoint configuration.

Linnet Link 1.0 is a development-only binary protocol. Host framing, an optional
serial adapter, a bounded native framing codec and command dispatcher establish
the development software contracts. The native PP5020 CDC ACM driver implements endpoint
descriptors, control transfers and bulk DMA. Serial port discovery alone does not establish Linnet Link support.

## Frame layout

All integers are unsigned little endian. Frames have a 20-byte header, zero to
1024 payload bytes, and a four-byte IEEE CRC32 covering header and payload.

| Offset | Bytes | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `LNK1` |
| 4 | 1 | Major version, 1 |
| 5 | 1 | Minor version, 0 |
| 6 | 2 | Flags: request 0, acknowledgement 1, rejected acknowledgement 3 |
| 8 | 2 | Command |
| 10 | 2 | Reserved, must be zero |
| 12 | 4 | Sequence, starts at 1 |
| 16 | 4 | Payload length |
| 20 | variable | Payload |
| 20 + length | 4 | CRC32 |

The receiver rejects unknown versions, reserved fields, illegal flags, zero or
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
| 48 | READ_LOG | Empty / 96-byte Batch 0 completion and recovery diagnostic snapshot |
| 49 | READ_METRICS | Empty / bounded metrics data |
| 50 | READ_CRASH | Empty / bounded crash record |
| 51 | CLEAR_CRASH | Empty / accepted acknowledgement |
| 52 | CRASH | u32 mode, currently zero only / accepted acknowledgement before deliberate fault |
| 64 | PLATFORM_STATE | Empty / 128-byte `LPB1` state record |
| 65 | INJECT_INPUT | Boot generation, count, event triples / generation and accepted count |
| 66 | CAPTURE_SCREEN | Boot generation / 28-byte immutable snapshot descriptor |
| 67 | SCREEN_READ | Capture ID, boot generation, offset, length / capture ID, generation, offset, pixel bytes |
| 68 | PLATFORM_CONTROL | Boot generation, action, argument / same three words on acceptance |
| 69 | UI_STATE | Empty / 64-byte `LUI3` native UI record (Batch 3) |

HELLO, INFO and STATUS return the same 96-byte native identity record:
`LNI1` at offset 0; u32 target ID at 4, boot ABI at 8, profile at 12, image kind
at 16 (OS 0, Boot 1), health flags at 20, boot generation at 24 and capabilities
at 28; raw build ID[32] at 32 and image SHA256[32] at 64. Capability bits are
upload 1, RAM boot 2, deliberate crash 4, OS reboot 8, Boot reboot 16 and disk
reboot 32. Only advertised and locally available actions may be accepted.
VERIFY returns the verified image SHA256[32]. JSON stays on the host.
Command identifiers reserve the intended operation;
an unsupported operation must reject explicitly, never report success. The
implemented storage and installation commands are described below; log
subscription is not implemented.

## Batch 1 platform commands

Commands 64 through 68 are compiled only into Batch 1 and later development/trace OS
images. They use normal frame sequence, CRC and acknowledgement rules. Their
generation field is the running boot generation from `LNI1`, not the USB
connection counter. A mismatching generation is rejected before mutation.
The exact state and screenshot layouts are in [FORMATS.md](FORMATS.md).

INJECT_INPUT contains u32 generation, u32 count, then 1..32 triples of u32
event sequence, u32 kind and **signed i32** value. Event sequences must increase
beyond state word 26; reopening the serial session does not reset that event
sequence. Kinds are wheel steps 1 (-64..64), button mask 2 (0..31), hold 3
(0 or 1), and headphone presence 4 (0 or 1). Button bits are Menu 1, Play 2,
Next 4, Previous 8 and Select 16; zero releases all buttons. These are synthetic
events, not physical observations. Physical switch and headphone readings remain
separate in the state record.

Input shapes are checked before applying the batch. A successful ACK contains
generation and count. If the runtime rejects a later event, the error ACK
contains generation and the accepted prefix count; it does not undo that prefix.
Stop and inspect state, including the last accepted event sequence, before a new
decision. Never replay the batch automatically. Other platform error ACKs contain
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

Control ACKs confirm acceptance. Poll state for asynchronous completion. In
particular, a COP queue reset advances its reset counter and requests a redraw;
wait for submitted and completed frame counters to match before testing sleep
or idle behavior. CPU rendering fallback does not qualify COP queue behavior.

CAPTURE_SCREEN freezes a 220 by 176 RGB565 frame in a fixed 77,440-byte
development-only buffer. SCREEN_READ accepts 1..1008 bytes within that buffer.
Every chunk echoes the capture ID, boot generation and offset. The frozen bytes
remain unchanged during animation until another capture replaces them or the
image restarts. A stale capture ID, changed boot generation or out-of-range read
is rejected. The host verifies the full raw framebuffer CRC before saving a PNG
preview; capture proves framebuffer contents, not physical LCD appearance.

Run the production platform campaign against the intended `.los` image:

```powershell
python linnet device platform-cycle --port COM6 --image <batch1-os.los> --scenario scenarios/b01-platform.json
```

The port is selected explicitly and reconnects use its physical serial identity.
The campaign records exact image/hash/generation, synthetic navigation and button
transitions, input latency, hold suppression, framebuffer CRCs, COP activity and
queue wrap/reset, three backlight transitions, three sleep/wake cycles, and idle
time without redraws. Receipts, raw screenshots and PNG previews share one run
directory. No ambiguous mutation is retried.

`automated_passed` covers those measured automated checks only. Physical buttons,
wheel, hold switch, headphone detection, visible backlight, sleep/wake and screen
artifacts remain a separate pending checklist. The campaign leaves
`physical_passed` and `hardware_qualified` false; automation alone does not pass
the Batch 1 hardware gate.

## Batch 3 native UI inspection

For panel timing, command 94 with u32 subcommand 7 returns sixteen u32 words:
`DSY1`, version 1, synchronized frames, pulse timeouts, last wait us, maximum
wait us, waiting flag, frame-pending flag, submitted frames, completed frames,
LCD failures, pixel pairs written, maximum presentation us (including the
sync wait), last transfer us, maximum transfer us, and snapshot tick.
This is a passive development-only snapshot. P98 GPIO A0 was measured with
an active-low pulse of approximately 579 us every 16,575 us. Presentation arms
its interrupt only for a pending frame and falls back after 25 ms without a
pulse. Screen captures still cannot establish physical tear-free scanout.

Command 94 subcommand 8 returns sixteen u32 words: `BLT1`, version 1,
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
read-only and uses the normal frame sequence and CRC rules. An older image
without native UI state rejects it. The reply has these word indices:

| Word | Meaning |
| --- | --- |
| 0 | ASCII `LUI3` |
| 1 | Version, 1 |
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
python linnet build --batch 3 --profile dev --device-serial 000000F7A765 --verify
python linnet device ui-state --port COM6
python linnet ui compile --system themes/midnight/system.toml --output out/ui-midnight
python linnet simulator --system themes/midnight/system.toml --tape out/ui-tape.json --output out/simulator-midnight
```

The compiler lowers constrained TSX to static native component data, resources
and explicitly declared native canvas callbacks. The simulator runs those same
generated scenes and the native renderer; its JSON tape uses event objects with
`kind`, `value`, optional `repeat` and optional `capture`. Kinds 1..4 match the
input meanings above; kind 0 renders without input. The tape has at most 100,000
expanded events and 512 requested captures. See the [README example](README.md#native-ui-and-customization)
and [SDK grammar](sdk/README.md).

Commands 65..68 provide synthetic input, immutable screen capture and bounded
platform controls for device comparison. UI_STATE adds paint and arena counters
for detecting unnecessary redraws and scene lifecycle changes. Capture CRCs
describe the framebuffer; simulator agreement cannot establish physical LCD
quality or wheel feel. Open qualification work is tracked in PROJECT_TODO.md.

## Upload and uncertainty

The generic host upload API allows images up to 16 MiB. The physical P98
staging region and campaign accept at most 8 MiB including the LOS header.
The upload owns one staging region and
accepts contiguous offsets only. Each chunk receives an explicit next-offset
acknowledgement; the host pipelines up to four chunks before collecting their
acknowledgements. A streaming window therefore covers up to 4080 bytes without
waiting between individual writes. Upload completion checks full-image CRC32
and SHA256. These hashes detect corruption and identify content; they are not
signatures or authentication. VERIFY must additionally validate the image
container and compatibility before BOOT_RAM is allowed.

No transaction is automatically retried. Missing, corrupt, out-of-order or
wrong-command acknowledgements poison the host session and raise
`AmbiguousCommand`. A rejected multi-command window is also uncertain because
other queued commands may have executed. Close the session, rediscover by stable
USB serial identity, reconnect, and inspect identity/state before a new decision.
Never replay BOOT_RAM, a reboot, crash clearing, or an upload mutation merely
because its acknowledgement was lost. Offset-based resume is deferred until
the device exposes a verified image identity plus committed offset. Ordinary
cycles must never overwrite the developer loader.

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
see the root README for implemented commands and qualification limitations.

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

On Windows, automatic eject/restart requires the exact installed Boot plan and
its SHA-256, plus the observed disk identity. See `python linnet device eject --help`
for arguments and elevation options. Plain eject may leave Apple Disk Mode active;
`--wait-link` alone does not request reboot. Never replay an ambiguous mutation.

## Batch 2 storage commands

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

STORAGE_STATE words: `LSB2`, phase, error, available-file bitmask, prepared,
capacity low/high, ready, quarantined, pending, completed, submitted, retries,
failed, canceled, coalesced, cache hits, read-ahead sectors, maximum block step
microseconds, partition LBA, partition sectors, clusters, operation generation,
WORK file capacity. Phase 6 is mounted; 9 is failure. Prepared additionally requires exact
file capacities, writable volume and disjoint allocation proof.

UPDATE_STATUS words: `LUP2`, available, ready, record generation, boot-state
generation, confirmed slot, candidate slot, attempt pending, attempts, slot 0
length, slot 1 length, upload active, upload slot, upload offset, poisoned, error.
Slot 255 means absent. Completion is never inferred from an acceptance ACK alone.

Fault modes are timeout before issue, short completion after transfer, reset
before issue, stale completion rejection, and flush error. These deliberately
exercise software error paths; they do not certify electrical fault handling.
Publication stages cut execution before writing the inactive record, after its
write callback, after the explicit flush, and after readback. The FAT write
callback itself flushes, so stage 2 already follows a durable file write.
Cuts reset without the normal flush barrier and are used only by the explicit
crash-consistency campaign. Ambiguous commands require reconnect and inspection;
none are automatically replayed.

`device storage-cycle` uses `scenarios/b02-storage.json` for deterministic
scratch writes, full readback hashes, random reads, settings restoration and
fault recovery, plus `WORK.BIN` creation/growth with preserved old contents and
zeroed extensions. Resize returns after publication and starts a remount; callers
wait for prepared state and the expected capacity before new file operations.
`device update-cycle` takes a healthy OS and a deliberate crash
OS for candidate confirmation, rollback and four publication cuts each for
settings and candidate activation. Each saves
receipts under `out/runs`; hardware qualification remains false until the full
Batch 2 gate, including host mount/sync/eject, is reviewed.

`device storage-sync-cycle` requires an explicit physical disk number and the
SHA-pinned installed Boot plan. It verifies the running OS, enters Apple Disk
Mode, writes/fsyncs/readbacks a new deterministic 1 MiB `LINNET/HOSTSYNC.BIN`,
then uses the guarded directory refresh/eject mechanism and verifies the exact
healthy OS returns. Existing evidence files are refused. For Batch 2 auto-boot,
the eject helper can explicitly expect a validated OS identity while also
checking any transient Boot against its installed plan.


## Native Boot maintenance commands

These commands are available in the development Batch 2 OS. They consume a
fixed LNB2 package, never a caller-selected raw-sector operation. Mutations begin
with the current boot generation and use the normal sequence/CRC rules.

| ID | Command | Request / successful reply |
|---|---|---|
| 100 | NATIVE_BEGIN | Generation, total bytes 68096, package SHA-256 (32 bytes) / generation, zero |
| 101 | NATIVE_CHUNK | Generation, contiguous offset, 1..1008 package bytes / generation, end offset |
| 102 | NATIVE_APPLY | Generation / generation, zero after complete durable verification |
| 103 | NATIVE_STATUS | Empty / 16 little-endian u32 words |

Status words 0..7 contain `LNB2`, phase, error, received package offset, writes
bitmask, disk bytes read, elapsed microseconds, and block request generation.
Words 8..15 contain the 32-byte observed SHA-256 in byte order. The block request
generation is independent of the boot generation. Phase 10 means complete;
phase 11 means failure. Writes bit 0 records that candidate writing was attempted;
bit 1 records that directory writing was attempted. These bits alone do not prove
durability. The host requires phase 10, error zero, writes mask 3, the complete
package offset and the exact expected final firmware hash before reporting success.

The fixed package pins target 98, ABI 1, storage serial `JQ5081G3SAY`, USB serial
`000000F7A765`, capacity and reviewed partition geometry. The host first re-derives
the package from the hash-pinned plan and all predecessor artifacts. Its exact
before-state assumes every pinned predecessor payload is installed, the latest
predecessor directory is active, and the new candidate region is zero. A different
full firmware hash is rejected before writing.

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
python linnet device native-install --package out/native-boot.lnb --package-sha256 <reviewed-package-sha256> --port COM6
python linnet device native-status --port COM6
```

Receipts are saved under `out/runs`. A successful apply still requires a separate
restart and identity observation. Hardware qualification of this new path is
pending; the current apply has no completed result recorded here.

No UAC elevation is used by native-install, persistent OS installation, package
preparation, or ordinary file provisioning with sufficient filesystem permissions.
The host raw-directory refresh is different: CLI eject/reboot defaults and sync callers
pass `allow_prompt=False`. They reuse an already elevated token with a hidden
child process or reject the operation without prompting. The sync campaign
checks this prerequisite before entering Disk Mode. Plain Shell eject remains
available without elevation and only confirms storage removal; it does not
promise a firmware restart.

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
The sync campaign also checks for a matching live session before entering Disk
Mode. OS/package installation through Linnet Link already needs no elevation;
this session covers the remaining Windows Disk Mode restart operation. A new
Boot plan needs a new bound session. Stop explicitly with:

```powershell
python linnet device refresh-session stop
```

The process survives the launcher and individual CLI commands. It ends at the
chosen expiry, explicit stop, or Windows logoff/restart; it is not an automatically
starting Windows service.

## Batch 5 photo diagnostic

Development command 121 (`PHOTOS_STATE`) is read-only and returns 20 little-endian
32-bit words (80 bytes). The magic is `PHT5`, version 1. Fields in order:
magic, version, phase, error, active, ready, pending, view, file size, metadata
verification offset, data offset, running CRC, expected metadata CRC, verified
photos, verified levels, verified tiles, current photo index, visible tiles,
revision, navigation. The running CRC is unfinalized (XOR with `0xffffffff`
before comparing). View values are albums 0, grid 1, viewer 2. Phase values
follow `services/photos/photos.c`; idle is 3. The command is excluded from release
firmware. Use `python linnet device photos-state --port COM6`.

Read-only development command122 (`VIDEO_STATE`) returns128 bytes, magicVIT6,
version2 (the host also reads version1/96 bytes). Fields: magic,version,phase,error,active,pending,paused,next_frame,
frame_count,front_frame,read_ops,read_bytes,prepared,presented,late_frames,
max_late_samples,max_prepare_us,queued_frames,max_queued_frames,audio_underruns,
audio_silence_frames,audio_fault,submitted_samples,revision,max_io_us,
max_record_read_us,max_record_crc_us,max_payload_crc_us,max_decode_us,
max_frame_crc_us,max_step_us,min_audio_queued. `video-state` is
available through the device CLI. Release firmware excludes this Link command.

`VIDEO_STATE` with u32 page 8 returns a 128-byte `VST1` record. Its first
eight u32 words are magic, version 1, open timestamp, first accepted display
presentation latency, index-verification latency, first audio-start latency,
frames ready at audio start, and dropped display frames. Latencies are
microseconds from video open; zero means the milestone has not occurred.
Remaining words are zero.
`python linnet device video-startup-timing --port COM6` or
`Session.video_startup_timing()` reads this passive snapshot. A presentation
acknowledges display submission, not the physical panel's scanout completion.
IPVF decode work is reported in `max_decode_us`, including LZ4 and reconstruction;
`max_payload_crc_us` applies to PVID's separate payload CRC phase.

Development interrupted-startup records reuse the144-byte crash mailbox with
reason`0xB0070001` and flags`2`. They are startup diagnostics, not CPU exception
register captures. Words0..3 of the register array hold trace phase, image bytes,
status and elapsed microseconds; `last_event` holds the last startup marker.
The host decoder exposes these separately as `startup_trace`. Existing valid
crash records take precedence over this fallback diagnostic.


PHT5 version 2 returns 128 bytes. First 20 words retain v1 order (version=2).
Added words: frame_valid, frame_complete, slide_armed, slide_at_us, now_us,
view_started_us, frame_ready_us, io_started_us, max_open_us, max_read_us,
render_us, jpeg_us. Host accepts exact v1/v2 length/version pairs. Added
storage and timing calls are development only. Open/read maxima measure from
accepted submission return through completed poll, including scheduling waits;
submission-call work and epoch-canceled work are omitted. Render/JPEG accumulate
step intervals for the selected image, reset by begin_view. They exclude
scheduling waits, but are not isolated CPU counters. Frame_ready records latest
software render publication, not LCD completion; use platform frame completion
separately. Timestamps wrap at 32 bits; use unsigned bounded differences.
IO start is meaningful only while pending. Frame_complete is PIMG-specific;
JPEG completion is shown by frame_valid.
