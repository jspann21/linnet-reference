# Linnet Link

Linnet Link provides USB diagnostics, input, screenshots, RAM boot, and persistent
OS updates in **development and trace builds**. Release builds exclude it.
General library transfers use Disk Mode.

Run commands from the source environment described in the
[README](../README.md#develop-on-windows). Replace `PORT`, `DEVICE_SERIAL`,
and file paths with observed values; never use a remembered port or disk number
after a mode change.

## Everyday USB operations

Discover with `python linnet device info`, then handshake the listed Linnet port:

```console
python linnet device info --port PORT
```

Prefix the following commands with `python linnet device`:

| Operation | Command | Result |
| --- | --- | --- |
| Temporary image | `boot --port PORT --image path/to/os.los` | Runs in RAM; does not replace the installed image. |
| Persistent update | `install --port PORT --image path/to/os.los` | Publishes an A/B candidate; requires stopped media and prepared storage. Does not reboot. |
| Boot installed OS | `reboot --port PORT --mode persistent` | OS saves state, stops media, drains storage, and reboots. |
| Restart RAM image | `reboot --port PORT --mode os` | Restarts the retained RAM candidate. |
| Recovery Boot | `reboot --port PORT --mode boot` | Enters recovery when available. |
| Native Disk Mode | `reboot --port PORT --mode disk` | Enters USB mass storage; rejected while storage is busy. On-device Sync saves and stops first. |

An acknowledgement means accepted, not completed. Rediscover and verify the
expected image and health after a transition. A release image will not expose Link.
Recovery Boot also needs prepared, idle storage before persistent reboot.

## Disk Mode and refresh sessions

Native Disk Mode is available on the four current targets. Link is unavailable
while the disk is mounted. Use Media Manager for normal eject, or identify the
mounted iPod explicitly:

```console
python linnet device detect-retail --mount X:/
python linnet device eject --disk-number DISK_NUMBER --expected-serial STORAGE_SERIAL --wait-link --link-serial LINK_SERIAL
```

The placeholders must come from the current discovery. Storage and Link serials
can have different representations. Native eject flushes and returns to Linnet.

Older installations using **Apple Disk Mode** may require a plan-bound directory
refresh before eject. Prepare that return path before switching modes:

```console
python linnet device refresh-session prepare --plan path/to/installed-plan.json --plan-sha256 PLAN_SHA256 --hours 8 > out/refresh-session.json
python linnet device refresh-session start --prepared out/refresh-session.json --allow-uac
python linnet device refresh-session status
python linnet device eject --disk-number DISK_NUMBER --expected-serial STORAGE_SERIAL --reboot --plan path/to/installed-plan.json --plan-sha256 PLAN_SHA256
python linnet device refresh-session stop
```

The finite elevated helper accepts only its reviewed operations. A new plan needs
a new session. Plain eject on these older installations may leave the device in
Disk Mode with **No Media** reported by Windows. Retain the matching backup,
plan, and receipts; see [local artifacts](local-artifacts.md).

## Diagnostics, input, and screenshots

| CLI command, followed by `--port PORT` | Use |
| --- | --- |
| `ui-state` | Scene, selection, lifecycle, and paint state |
| `library-state`, `player-state` | Library readiness and playback state |
| `player-timing-state` | Decoder and PCM timing |
| `photos-state`, `video-state` | Media state and counters |
| `startup-timing`, `video-startup-timing` | Startup milestones |
| `media-info` | Storage identity, power, and error state without waking the drive |

[Session](../tools/link/session.py) provides input, capture, logs, and bounded
storage APIs. Mutations use the current boot generation. Input events have their
own increasing sequence; reopening a connection does not reset it.

For a short Play press on an already-open session `s`, using its current
`generation`:

```python
n = s.platform_state()[26]
s.platform_input(generation, [(n + 1, 2, 2), (n + 2, 2, 0)])
```

Link button masks come from [kernel/shell.h](../kernel/shell.h): Menu 1, Play 2,
Next 4, Previous 8, Select 16; zero releases buttons. These are synthetic events.
Wait for processed input and completed display frames before checking a result.

`capture_screen(generation)` returns the frozen native framebuffer after
transfer and CRC checks. It proves framebuffer contents, not the physical LCD.
HELLO readiness also does not imply library readiness: wait for library phase 3,
error 0. Do not repeat Play while the player is priming.

## Updates and uncertain results

Storage APIs operate on fixed files, not arbitrary paths or sectors. Uploads are
bounded and contiguous; the host verifies image identity and target compatibility.
Hashes provide integrity checks, not signature authentication.

A missing, corrupt, or mismatched acknowledgement poisons the session and may
raise `AmbiguousCommand`. Close it, rediscover, and inspect state before deciding
what to do. Never automatically replay input, reboot, crash-clear, or a write.
Offset-based upload resume is not implemented.

Legacy native Boot maintenance accepts a fixed reviewed package on explicitly
admitted hardware. It is separate from ordinary A/B OS updates; use the
[bootstrap map](bootstrap-tooling.md) and matching recovery artifacts.

## Existing device checks

- `platform-cycle`: input, framebuffer, presentation, sleep, and wake checks.
- `storage-cycle`: readback, settings, bounded file growth, and injected faults.
- `update-cycle`: candidate confirmation, rollback, and publication cuts.
- `storage-sync-cycle`: guarded Disk Mode roundtrip and return to the expected OS.

Use each command's `--help` for required images, scenarios, and identities.
Receipts go under `out/runs`. Injected software faults do not qualify electrical
failures; physical controls, sound, current, and panel quality need observation.

## Protocol reference

Frames contain a 20-byte little-endian `LINK` header, at most 1,024 payload bytes,
and a four-byte CRC32 over header and payload. Reserved fields must be zero.
Acknowledgements echo the request command and sequence. Boot, USB, input, scene,
and storage generations have different purposes and are not interchangeable.

Use the implementation for exact command IDs and record offsets:

| Contract | Source |
| --- | --- |
| Framing and upload | [Host protocol](../tools/link/protocol.py), [firmware link](../hal/link/link.h), [dispatcher](../hal/link/dispatch.h) |
| Device identity | [Host identity](../tools/link/identity.py), [binary formats](formats.md) |
| Input and capture | [Platform Link](../kernel/platform_link.h), [Session](../tools/link/session.py) |
| Storage and updates | [Storage Link](../kernel/storage_link.h), [storage owner](../services/storage/storage.c) |
| Media records | [Host decoders](../tools/link/music.py) |

Release verification checks that developer transport, injection, capture, and
related services are excluded. Keep ACK retirement, DMA quiescence, bounded
waits, and buffer ownership intact when changing firmware transport code.

## Windows loses the iPod during Disk Mode

**Device Descriptor Request Failed / Code 43** means the endpoint is not normally
enumerated. Stop I/O, retain the receipt, and distinguish completed writes from
uncertain ones. Do not replay a write or bypass its guard to make eject succeed.

Reconnect/reset the affected iPod, then rediscover its identity. The finite
refresh helper also supports reviewed tracing and device restart actions; inspect
`refresh-session --help`. Do not reset a shared USB hub.

Earlier M25 Apple Disk Mode descriptor losses were reported with a cable that
has since been replaced, with no reported recurrence. If the fault returns,
retain the receipt and reopen qualification; see [M25 qualification](../targets/video5g-m25/QUALIFICATION.md).
