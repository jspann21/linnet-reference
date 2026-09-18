# Linnet Link Protocol

Linnet Link provides diagnostics, synthetic input, screenshots, firmware updates,
and bounded storage access over USB in development/trace builds. Release builds
exclude Link. Run examples from the repository root with `pyserial==3.5` installed;
replace angle-bracket placeholders with observed device values.

## Contents

- [Everyday USB operations](#everyday-usb-operations)
- [Disk Mode and refresh sessions](#disk-mode-and-refresh-sessions)
- [Platform commands](#platform-commands)
- [Native UI inspection](#native-ui-inspection)
- [Media diagnostics](#media-diagnostics)
- [Storage commands](#storage-commands)
- [Native Boot maintenance commands](#native-boot-maintenance-commands)
- [Upload and uncertainty](#upload-and-uncertainty)
- [Frame layout](#frame-layout)
- [Commands](#commands)
- [Host integration and release exclusion](#host-integration-and-release-exclusion)

## Everyday USB operations

Discover the iPod with `python linnet device info`, then handshake its listed
Linnet USB port with `python linnet device info --port <port>`. Do not probe an
unrelated USB serial adapter. Rediscover after every mode change; COM numbers
can change.

Prefix these commands with `python linnet device`:

| Operation | Command | Behavior |
| --- | --- | --- |
| Install OS | `install --port <port> --image <os.los>` | Requires stopped media and prepared storage; does not reboot. |
| Temporary OS | `boot --port <port> --image <os.los>` | Starts a RAM image; does not install it. |
| Normal reboot | `reboot --port <port> --mode persistent` | Boots installed firmware; OS automatically stops media, saves state, and drains storage. No separate stop/preparation needed. |
| RAM reboot | `reboot --port <port> --mode os` | Restarts the retained RAM candidate, not the installed image. |
| Recovery Boot | `reboot --port <port> --mode boot` | Enters recovery Boot when available. |
| Apple Disk Mode | `reboot --port <port> --mode disk` | Switches to mass storage; prepare the return path below first. |

Automatic OS save/stop applies to `persistent`; the other reboot modes use
low-level recovery paths. On-device Sync also saves/stops before Disk Mode.
Recovery Boot still requires idle/prepared storage for persistent reboot.
An ACK confirms acceptance: reconnect and verify the expected healthy build.
Persistent reboot can reset generation to 1; release OS has no Link endpoint.

If OS installation rejects `UPDATE_BEGIN`, inspect state. Recovery Boot can
install: enter `--mode boot`, rediscover/handshake, install, then reboot with
`--mode persistent` and verify the build identity.

Use `tools.link.session.Session` for logs, input, screenshots, and supported
storage reads/writes. Storage commands accept fixed files, not arbitrary paths
or raw addresses. Use Disk Mode for general media/library file changes.

## Disk Mode and refresh sessions

**Prepare the return from Disk Mode before entering it.** Apple Disk Mode exposes
mass storage, not the Linnet COM endpoint. Automatic return uses the host's
verified Boot-directory refresh followed by eject:

```powershell
python linnet device refresh-session prepare --plan <installed-plan.json> --plan-sha256 <sha256> --hours 8 > out/refresh-session-prepared.json
python linnet device refresh-session start --prepared out/refresh-session-prepared.json --allow-uac
python linnet device refresh-session status
# After disk-mode file work, while the identified volume is still mounted:
python linnet device eject --disk-number <number> --expected-serial <disk-serial> --reboot --plan <installed-plan.json> --plan-sha256 <sha256>
```

Use the exact currently installed Boot plan and a live matching refresh session
(or an already elevated process). Validate these prerequisites first. Archived
plans may have absolute dependencies or older formats; restore and validate them
according to [local artifacts](local-artifacts.md), without changing pinned
hashes. Plain eject and `--wait-link` do not request a restart. Plain eject can
leave the device in Disk Mode with Windows reporting **No Media**, preventing
this mounted-volume refresh path until the device is reconnected/restarted.
Always rediscover Link and confirm the expected healthy build after restarting.

`tools/link/refresh_session.py` keeps a protected source snapshot and elevated
process for 1â€“24 hours after one UAC launch. It permits status, the reviewed
identical 512-byte directory refresh, and stop; no arbitrary files or code.
Each refresh rechecks device/firmware guards and saves a receipt. Duplicate IDs
reuse the receipt; an unacknowledged write revokes further writes.

Eject and sync callers reuse a matching session or elevated token. Unattended
calls default to no UAC prompt and fail if neither is available. A new Boot plan
needs a new session. Sessions survive CLI calls but end on stop, expiry, logoff,
or restart; they are not auto-starting services. Stop with:

```powershell
python linnet device refresh-session stop
```

Ordinary Link installation/package preparation needs no UAC elevation. Raw Windows
directory refresh uses the session/elevation above; sync checks it before Disk Mode.

## Platform commands

Commands 64â€“68 require a development/trace OS and the current `LNID` boot
generation, not the USB connection counter. A mismatch rejects the mutation.
State and screenshot layouts are in [formats.md](formats.md).

INJECT_INPUT contains u32 generation, u32 count, then 1..32 triples of u32
event sequence, u32 kind and **signed i32** value. Event sequences must increase
beyond state word 26; reopening the serial session does not reset that event
sequence. Kinds are wheel steps 1 (-64..64), button mask 2 (0..31), hold 3
(0 or 1), and headphone presence 4 (0 or 1). Button bits are Menu 1, Play 2,
Next 4, Previous 8 and Select 16; zero releases all buttons. These are synthetic
events, not physical observations. Physical switch and headphone readings remain
separate in the state record.
Use these `kernel/shell.h` masks, not `hal/api/input.h`: Play is 2; 8 is Previous.
For a short Play press on an open Session `s` with current boot `generation`:

```python
n = s.platform_state()[26]
s.platform_input(generation, [(n + 1, 2, 2), (n + 2, 2, 0)])  # Press, release.
```

Input ACKs return generation/count and mean queued acceptance. A later event
rejection returns the accepted prefix count without undoing those events; inspect
state and sequence before another action. Other platform errors return
generation/zero. Wait for processed input and completed display frames before
asserting a visible result; never automatically replay input.

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

USB/HELLO readiness does not imply library or saved-song readiness. Poll
`python linnet device library-state --port <port>` for phase 3, error 0, then
wait for the expected Now Playing metadata/artwork. Use a bounded timeout,
not a fixed sleep. `player-state` phase 3 is priming, 4 playing, 5 paused, and
0 idle. A restored song stays idle until UI Play; `player-resume` only unpauses
an open player. Do not repeat Play while priming: it can toggle playback off.

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

Run the platform campaign against the intended image:

```powershell
python linnet device platform-cycle --port <port> --image <os.los> --scenario scenarios/platform.json
```

It records identity/generation, navigation/input latency, hold suppression,
framebuffer CRCs, COP queue/reset, backlight, sleep/wake, and idle redraw checks.
Receipts and captures share the run directory. `automated_passed` covers those
checks; physical controls and LCD appearance still require device observation.

## Native UI inspection

`python linnet device ui-state --port <port>` decodes read-only command 69 into
named fields alongside HELLO identity. The native-UI OS returns 16 little-endian
words; images without native UI reject it.

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

Scene indices refer to the matching generated `scenes.json`, not persistent app
IDs. Boot, scene, arena, and USB generations are independent.

Command 94 supplies two passive display diagnostics (16 u32 words each):

| Subcommand | Header | Fields after header |
| --- | --- | --- |
| 7 | `DSYN` | reserved; synchronized frames; pulse timeouts; last/max wait us; waiting; frame pending; submitted/completed frames; LCD failures; copied pixel pairs; max presentation/transfer us; last transfer us; snapshot tick |
| 8 | `BLIT` | reserved; helper bytes; live pixel/live command/expected command hooks; first mismatch offset (`0xffffffff` = exact); expected/live mismatch words; pixel mismatch count (`0xffffffff` = inactive/direct); queue head/tail; LCD failures; three reserved words |

Run BLIT while navigation is idle: its full-frame comparison is diagnostic work.
DSYN reports presentation timing, not proof of tear-free physical output.
The column helper requires the matching preserved Boot worker.

The simulator uses the same generated scenes/renderer. JSON events have `kind`,
`value`, optional `repeat` and `capture`; kinds 1â€“4 match Link input, 0 renders.
Limits: 100,000 expanded events and 512 captures. See the [SDK](../sdk/README.md)
for compilation and simulation. Framebuffer agreement does not prove LCD quality
or physical wheel behavior.

## Media diagnostics

Run CLI diagnostics as `python linnet device <command> --port <port>`.
Layouts are decoded in `tools/link/music.py`; other headers/lengths are rejected.

| Command | Wire ID / response | Use |
| --- | --- | --- |
| `media-info` | 95 / 192-byte `MEDI` | Media/power state without waking the drive; fields in [storage](storage.md) and [formats](formats.md). |
| `player-timing-state` | 120 / 124-byte `TIME` | Clock/decoder identity and cumulative MP3 decode, synthesis, PCM counters. |
| `photos-state` | 121 / 128-byte `PHOT` | Photo state/timing; views: albums 0, grid 1, viewer 2. Finalize running CRC with XOR `0xffffffff` before comparison. |
| `video-state` | 122 / 128-byte `VIDS` | Playback, storage, audio, and timing state. |
| `video-startup-timing` | 122, page 8 / 128-byte `VMEA` | Milestone times measured from video open; zero means not yet reached. |

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
Cuts reset without the normal flush barrier and are used only by the explicit
crash-consistency campaign. Ambiguous commands require reconnect and inspection;
none are automatically replayed.
A rejection payload such as `0100000000000000` means generation 1/value 0;
it does not identify which admission check failed. Inspect state before assigning
a cause. The rejected Python session is poisoned: close it and reconnect.

Resize starts a remount after publication; wait for prepared state and the
expected capacity before further file operations.

| CLI campaign (`python linnet device ...`) | Scope |
| --- | --- |
| `storage-cycle` | `scenarios/storage.json`: scratch writes/readback hashes, random reads, settings restoration, five faults, WORK creation/growth preserving old data and zeroing extensions. |
| `update-cycle` | Healthy and deliberate-crash OS images: candidate confirmation, rollback, and four publication cuts for settings/candidate activation. |
| `storage-sync-cycle` | Explicit disk number and SHA-pinned Boot plan: verify OS, enter Disk Mode, write/fsync/read back a new deterministic 1 MiB `LINNET/HOSTSYNC.BIN`, refresh/eject, verify exact healthy OS. Refuses existing evidence files; checks elevation/session before Disk Mode. |

Campaign receipts go under `out/runs`. Sync can validate transient Boot against
the installed plan before the expected OS returns. Injected software faults do
not certify electrical fault handling.

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

The fixed package pins target 98, storage serial `JQ5081G3SAY`, USB serial
`000000F7A765`, capacity, and reviewed partition geometry. The host re-derives it
from the hash-pinned plan; it requires the original firmware and a zeroed candidate
region. A different full firmware hash rejects before writing.

Apply validates the package/Boot LOS, obtains exclusive storage ownership, checks
MBR/OSOS/full-image hashes, then writes, flushes, and verifies the candidate before
doing the same for the directory. Device timeout is 600 seconds; host timeout is
650 seconds. The single-sector native directory lacks persistent A/B metadata's
dual-record guarantee. Never replay an uncertain candidate/directory write.

```powershell
python linnet device native-install --package out/native-boot.lnb --package-sha256 <reviewed-package-sha256> --port COM6
python linnet device native-status --port COM6
```

Receipts are saved under `out/runs`. A successful apply still requires a separate
restart and identity observation.

## Upload and uncertainty

Upload limits are 16 MiB in the generic host API and 8 MiB including LOS header
on physical P98/campaigns. One staging region accepts contiguous offsets only.
The host pipelines at most four 1020-byte chunks (4080 bytes); each ACK returns
the next offset. Completion checks CRC32/SHA256; VERIFY also validates the
container/target before BOOT_RAM. Hashes identify content, not authenticate it.

Missing, corrupt, out-of-order, or wrong-command ACKs poison the session and raise
`AmbiguousCommand`. A rejected batch is also uncertain: other commands may have
executed. Close, rediscover by USB serial, reconnect, and inspect identity/state.
Never automatically replay a reboot, crash clear, input, or write after an
uncertain result. Offset-based upload resume is not implemented. Ordinary cycles
must not overwrite the developer loader.

Upload discovery allows 180 seconds for USB, then waits for matching healthy
HELLO/STATUS. Cold Boot can disappear during handoff; Home can precede USB.
Repeat only read-only discovery/state checks. Storage transactions allow 45 seconds
for a bounded 30-second cold wake; keep serial settings fixed.

## Frame layout

Frame fields are unsigned little-endian; signed payload fields are marked below.
Frames have a 20-byte header, 0–1024 payload bytes, and a four-byte IEEE CRC32
covering header and payload.

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

Reject nonzero reserved fields, illegal flags, zero/repeated sequences, oversized
payloads, and bad CRCs. Sequences increase per connection; wrap requires reconnect.
ACKs echo command/sequence. Framing errors invalidate the session; never scan
untrusted payloads for magic. The parser owns a 1048-byte buffer, processes at
most one frame per completion, and lends payload pointers only until the next
input byte. Reset it on connection establishment and reject ACK-flagged requests
before dispatch. Reconnection does not authorize replay.

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
| 64 | PLATFORM_STATE | Empty / 128-byte `PLAT` state record |
| 65 | INJECT_INPUT | Boot generation, count, event triples / generation and accepted count |
| 66 | CAPTURE_SCREEN | Boot generation / 28-byte immutable snapshot descriptor |
| 67 | SCREEN_READ | Capture ID, boot generation, offset, length / capture ID, generation, offset, pixel bytes |
| 68 | PLATFORM_CONTROL | Boot generation, action, argument / same three words on acceptance |
| 69 | UI_STATE | Empty / 64-byte `UIST` native UI record |

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

## Host integration and release exclusion

`tools.link.session.Session` exposes identity, upload/verify, `boot_ram`,
`reboot`, `reboot_persistent`, `crash_get`, platform input/capture, and storage
operations. Its transport provides deadline-bound `read`, `write`, and `close`.
`SerialTransport.discover()` lists USB metadata without probing arbitrary ports;
`reconnect(serial_number)` uses a fresh inventory and rejects duplicate identities.

Windows timeout setters reconfigure CDC state: keep serial settings fixed and
poll bytes against a monotonic deadline. Opening establishes a fresh DTR sequence;
closing after boot/reboot/crash waits up to one second to avoid canceling the
deferred action before ACK retirement.

Firmware integration requirements:

- `hal/link/dispatch.h` defines contiguous-upload validation and backend contracts.
  Backends enforce staging bounds; read callbacks respect output capacity.
  Missing callbacks reject operations; `can_action` checks transition support.
- RAM boot, recovery reboots, and crash wait for the exact transmitted ACK via
  `ln_link_dispatch_ack_sent`. Persistent reboot uses the storage ACK hook, then
  OS runtime cleanup. ACK acceptance does not prove the transition completed.
- PP5020 CDC reserves uncached IRAM `0x4000c000..0x4000ce00` for queues and DMA.
  Require cache-disabled entry and a linker reservation. Handle partial I/O,
  call `ln_usb_poll`, and confirm `ln_usb_flush` before declaring ACK retirement.
- Bus reset, reconfiguration, DTR edges, and disconnect change USB generation and
  invalidate the parser/session. MMIO waits are bounded; transfer faults disconnect.
- Lab VID/PID is `1209:504a`, not an assigned production identity. USB serial comes
  from the physical device. The descriptor requests 100 mA; the driver does not
  enable high-current charging.
- Before replacing DMA-visible memory, require successful `ln_usb_stop`, controller
  reset completion, and idle endpoint registers. Boot keeps USB blocks powered;
  power-gate readback or a void disconnect does not prove DMA is idle. Cache a
  successful stop until USB initialization; never infer success by retry.

Release manifests exclude Link dispatch/adapters, screenshots, synthetic input,
staging, developer crash services, and chainload code. The release verifier checks
symbols and protocol magic. Host tools are not packaged into device images.
