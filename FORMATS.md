# Linnet binary contracts

Integer fields are unsigned little endian unless explicitly marked signed. Readers decode bytes explicitly;
C struct padding and host endianness are never part of a wire contract. CRCs use
CRC32/ISO-HDLC (reflected polynomial `0xedb88320`, initial and final xor
`0xffffffff`). CRC detects accidental corruption, not malicious modification.

## Native OS image: `.los` version 1

The file consists of a 128-byte header followed immediately by the payload.
Trailing bytes are rejected. The payload is native ARM code; it is not an iPod
firmware container and cannot be installed as one.

| Offset | Width | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `LOS1` |
| 4 | 2 | Format version, 1 |
| 6 | 2 | Header bytes, 128 |
| 8 | 4 | Numeric target, 98 for `photo4g-p98` |
| 12 | 4 | Native image ABI, 1 |
| 16 | 4 | Profile: 0 release, 1 dev, 2 trace |
| 20 | 4 | Payload bytes |
| 24 | 4 | Payload load address |
| 28 | 4 | Absolute ARM entry address |
| 32 | 4 | CRC32 of payload |
| 36 | 32 | SHA-256 build identity supplied by build driver |
| 68 | 56 | Reserved, must be zero |
| 124 | 4 | CRC32 of header bytes 0 through 123 |

The build identity is provenance, not a second payload checksum or a signature.
The loader validates target, ABI, allowed profile, both CRCs, exact length, and
the complete load range against a caller-supplied safe execution window. Load
and entry must be four-byte aligned. At least four bytes starting at entry must
be inside the payload. The policy window must exclude the loader, retained
mailbox, and any other live allocations. Validate and stage from immutable or
exclusively owned bytes to prevent mutation between validation and execution.

## Boot state: 32 bytes

| Offset | Width | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `LBS1` |
| 4 | 4 | Version, 1 |
| 8 | 4 | Generation, unsigned wrapping counter |
| 12 | 4 | Attempt count, saturating at `UINT32_MAX` |
| 16 | 1 | Confirmed slot: 0, 1, or 255 (none) |
| 17 | 1 | Candidate slot: 0, 1, or 255 (none) |
| 18 | 1 | Candidate attempt pending: 0 or 1 |
| 19 | 9 | Reserved zero |
| 28 | 4 | CRC32 of bytes 0 through 27 |

A candidate cannot equal the confirmed slot. A pending attempt requires a
candidate. Corrupt state is rejected, leaving the output unchanged. Selection
returns 255 when no validated eligible slot exists; that means stay in recovery.
Encoding alone is not transactional persistence. The eventual storage adapter
must publish state atomically using redundant records and a commit protocol,
including wrap-aware generation comparison.

## Retained crash mailbox: 144 bytes

| Offset | Width | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `LRC1` |
| 4 | 2 | Version, 1 |
| 6 | 2 | Record bytes, 144 |
| 8 | 4 | Sequence |
| 12 | 4 | Reason code supplied by exception/panic adapter |
| 16 | 64 | Captured r0 through r15; r15 is PC |
| 80 | 4 | Captured CPSR |
| 84 | 4 | Capture flags supplied by adapter |
| 88 | 32 | Full build identity, matching the `.los` header |
| 120 | 4 | Boot-state generation at handoff, zero when unavailable |
| 124 | 4 | Active service identifier, zero when unavailable |
| 128 | 4 | Last event identifier, zero when unavailable |
| 132 | 8 | Reserved zero |
| 140 | 4 | CRC32 of bytes 0 through 139 |

The codec does not claim to capture registers, preserve RAM across power loss,
or establish cache coherence. The board adapter reserves retained memory outside
startup clearing, writes the record under exclusive ownership, cleans cache and
issues required barriers before reset. Readers reject a torn or corrupt record.
For publication to retained memory, encode into a temporary 144-byte buffer,
invalidate the retained magic, copy bytes 4 through 143, then publish the four
magic bytes last with the board's required ordering. The codec itself performs
ordinary byte writes and is not a volatile-memory publication primitive.
Reason codes and flag meanings must be documented by the producing adapter;
the codec preserves their numeric values. Retrieval must not erase the record
before the host has durably saved it.

Future music database, photo and video formats are deferred until Batch 0 passes
its hardware gate.

## Linnet Link native identity: 96 bytes

HELLO, INFO and STATUS return the same fixed binary snapshot. This is an endpoint
state snapshot; it does not describe the staged upload. VERIFY returns the full
SHA-256 of the uploaded `.los` file separately.

| Offset | Width | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `LNI1` |
| 4 | 4 | Numeric target, 98 |
| 8 | 4 | Native ABI, 1 |
| 12 | 4 | Profile: release 0, dev 1, trace 2 |
| 16 | 4 | Running image kind: OS 0, Boot 1 |
| 20 | 4 | Healthy milestones bit mask; all five means 31 |
| 24 | 4 | Boot generation |
| 28 | 4 | Capability mask |
| 32 | 32 | Running image build identity |
| 64 | 32 | Running full `.los` SHA-256 from retained handoff |

Capability bits are upload 1, RAM boot 2, deliberate crash 4, reboot OS 8,
reboot Boot 16 and reboot disk 32. Advertise only actions backed by the configured
platform adapter. An externally loaded initial image may have an unknown full
file hash (32 zero bytes); subsequent RAM boot passes the verified upload hash
through retained handoff metadata.

READ_METRICS returns eight little-endian u32 saturating counters: uploads begun,
bytes accepted, successful verifications, failed verifications, chainload
attempts, crash clears, read requests, and reserved zero. The Batch 0 board
integration uses READ_LOG for 24 little-endian diagnostic words: eight LCD words
(phase, failure, elapsed microseconds, pixel pairs, polling budget, control,
configuration, port), followed by eight USB words (TX queue-head token, TX
descriptor token, active pipes, prime, status, completion, origin/failure,
USB generation), followed by eight retained recovery words (return reason,
last phase, phase generation, candidate size, USB stop proof bits, first failure,
elapsed microseconds, current generation). The USB stop proof uses bits 0..3 for
RUN clear, flush, reset completion and endpoint idle, and bit 5 for the bounded
settling interval; bit 4 is reserved and zero. These diagnostics are excluded
from release.
READ_CRASH returns a valid
144-byte record or an empty payload when no valid record exists. CLEAR_CRASH
zeros the retained record.

## Batch 1 platform state: 128 bytes

PLATFORM_STATE (command 64) returns exactly 32 little-endian u32 words. Offsets
are four times the word index. The record is an observation of current runtime
state; it does not establish physical qualification. Counter differences must
account for unsigned wrap. Header magic and boot generation must match before
the host uses any counters.

| Word | Offset | Field |
| --- | --- | --- |
| 0 | 0 | ASCII `LPB1` (`0x3142504c`) |
| 1 | 4 | Boot generation |
| 2 | 8 | Runtime flags and reported backlight percentage |
| 3 | 12 | Selected menu index |
| 4 | 16 | Scene identifier |
| 5 | 20 | Accepted event count |
| 6 | 24 | Processed event count |
| 7 | 28 | Dropped event count |
| 8 | 32 | Maximum event latency, microseconds |
| 9 | 36 | Event queue high-water count |
| 10 | 40 | Deadline queue high-water count |
| 11 | 44 | Scene arena high-water bytes |
| 12 | 48 | Submitted frame count |
| 13 | 52 | Completed frame count |
| 14 | 56 | Maximum display presentation time, microseconds |
| 15 | 60 | COP display queue head |
| 16 | 64 | COP display queue tail |
| 17 | 68 | COP display queue reset count |
| 18 | 72 | Sleep count |
| 19 | 76 | Wake count |
| 20 | 80 | Accumulated idle time, microseconds |
| 21 | 84 | Idle entry count |
| 22 | 88 | Physical buttons in standardized five-bit mask |
| 23 | 92 | Physical hold switch, boolean |
| 24 | 96 | Physical headphone presence, boolean |
| 25 | 100 | Synthetic hold/headphone values |
| 26 | 104 | Last accepted synthetic event sequence |
| 27 | 108 | Shell animation frame |
| 28 | 112 | Configured CPU clock, hertz |
| 29 | 116 | Battery millivolts; consult validity flag |
| 30 | 120 | Power flags |
| 31 | 124 | Maximum IRQ C dispatcher duration, microseconds |

Word 2 uses bit 0 for initialized runtime, bit 1 for sleeping, bit 2 for active
COP display execution and bit 3 for observed physical input packets. Bit 4 means
the physical two-second Play/Pause shutdown deadline is armed. Bits 8..14
contain the reported 0..100 backlight percentage. Word 25 uses bit 0 for synthetic
hold and bit 1 for synthetic headphone presence; these values are separate from
words 23 and 24. Word 30 uses USB present 1, FireWire present 2, charging 4,
battery sample valid 8 and I2C fault 16. Word 31 measures C dispatcher entry to
exit, including any FIQ preemption and excluding assembly register save/restore.
Early candidate receipts used this word for timer deadline lateness; final
qualification pins the corrected image identity.

The display ring has eight entries. Head and tail advance as unsigned counters
and index slots modulo eight; a queue reset sets both to zero and increments
word 17. Frame counts continue across that reset. A reset requests a redraw,
so idle checks must wait for frame submission/completion to settle.

## Batch 1 immutable framebuffer snapshot

CAPTURE_SCREEN (66) accepts one u32 boot generation and returns seven u32 words:

| Offset | Field |
| --- | --- |
| 0 | Nonzero capture ID |
| 4 | Boot generation |
| 8 | Width, 220 |
| 12 | Height, 176 |
| 16 | Pixel format, 1 for RGB565 little endian |
| 20 | Total byte count, 77,440 |
| 24 | CRC32 of all 77,440 raw pixel bytes |

Pixels have no header or row padding. Rows run top to bottom and pixels left to
right. Each little-endian u16 contains red in bits 11..15, green in bits 5..10
and blue in bits 0..4. The device copies a complete scanout snapshot into a fixed
development-only buffer before acknowledging its descriptor. The copy remains
immutable until the next accepted capture or image restart; capture ID exhaustion
rejects further captures instead of wrapping.

SCREEN_READ (67) accepts four u32 words: capture ID, boot generation, byte offset
and requested byte count (1..1008). Its response contains capture ID, boot
generation and byte offset, followed by exactly the requested bytes. Reads must
remain entirely within the snapshot. The host validates each echoed tuple and
the final full-image CRC. `.rgb565` artifacts contain those raw bytes; `.png`
artifacts are host-generated previews and do not change the native pixel format.

Generation-protected input and control payloads, accepted-prefix error semantics,
and command usage are defined in [DEVLINK.md](DEVLINK.md). These platform records,
snapshot buffers and mutation entry points are absent from release images.

## Transactional state record (`LTS1`)

Each copy is exactly 512 bytes, little-endian: magic `LTS1` at 0, version 1 at
4, nonzero publication generation at 8, payload length (0..480) at 12, twelve
reserved zero bytes at 16, payload at 28, zero padding through 507, and IEEE
CRC32 of bytes 0..507 at 508. Generation wrap is refused. Read both copies;
choose the valid larger generation. Identical equal-generation copies are
allowed; differing copies at the same generation are corruption. Two all-zero
copies mean uninitialized, not a valid committed record.

## Persistent update metadata (`LUP1`)

The `BOOT0.BIN`/`BOOT1.BIN` LTS1 payload is 184 bytes: `LUP1` at 0, version 1
at 4, the existing 32-byte `LBS1` boot state at 8, slot 0 at 40 and slot 1 at
112. Each 72-byte slot record stores actual LOS length (u32), profile (u32),
32-byte build ID, and 32-byte SHA-256 of the complete unpadded LOS. Empty slot
records are entirely zero. The file's 8 MiB allocation is capacity, not image
length. LOS validation still checks target, ABI, profile, address bounds and
both CRCs. The slot SHA is checked after a complete readback before publication.

The 80-byte retained `LPH2` handoff has magic at 0, slot (u32, 0 or 1) at 4,
build ID at 8, full LOS SHA at 40, reserved zero u32 at 72 and CRC32 over the
first 76 bytes at 76. It lives at `0x01fff100`; the OS consumes it once and
matches its own compiled build identity before publishing healthy state.


## Device-side native Boot package (`LNB2`)

LNB2 version 1 is exactly 68,096 bytes. It is a fixed-purpose development package
for the inspected P98 native firmware layout. All integers below are little-endian;
all SHA-256 values are raw 32-byte digests. The host sidecar `<package>.json` pins
the source plan/hash, package/hash, image identity and expected installed
predecessors. The explicit CLI package hash is checked independently of that file.

| Header offset | Size | Field |
|---:|---:|---|
| 0 | 4 | Magic `LNB2` |
| 4 | 4 | Version 1 |
| 8 | 4 | Total package bytes 68096 |
| 12 | 4 | Target 98 |
| 16 | 4 | Boot ABI 1 |
| 20 | 4 | Firmware partition bytes 41094144 |
| 24 | 8 | Firmware absolute byte offset 32256 |
| 32 | 8 | Reviewed candidate absolute byte offset |
| 40 | 4 | Candidate extent bytes 65536 |
| 44 | 4 | Actual Boot payload bytes, 32..65536 |
| 48 | 8 | Directory absolute byte offset 49152 |
| 56 | 8 | Original OSOS absolute byte offset 21003776 |
| 64 | 4 | Original OSOS bytes 1549256 |
| 68 | 4 | Profile: 1 development, 2 trace |
| 72 | 8 | Device capacity bytes 64021856256 |
| 80 | 16 | Storage serial ASCII, zero-padded: `JQ5081G3SAY` |
| 96 | 16 | USB serial ASCII, zero-padded: `000000F7A765` |
| 112 | 32 | Exact full firmware before SHA-256 |
| 144 | 32 | Full firmware SHA-256 after candidate staging |
| 176 | 32 | Full firmware SHA-256 after directory publication |
| 208 | 32 | Preserved original OSOS SHA-256 |
| 240 | 32 | Embedded MBR SHA-256 |
| 272 | 32 | Full padded candidate extent SHA-256 |
| 304 | 32 | Expected old directory SHA-256 |
| 336 | 32 | New directory SHA-256 |
| 368 | 32 | Reconstructed complete Boot LOS SHA-256 |
| 400 | 32 | Boot build ID |
| 432 | 32 | Package body SHA-256: bytes 512..68095 |
| 464 | 44 | Reserved, all zero |
| 508 | 4 | IEEE CRC32 over header bytes 0..507 |

| Package offset | Size | Body component |
|---:|---:|---|
| 512 | 512 | Exact MBR |
| 1024 | 512 | Expected active directory before installation |
| 1536 | 512 | Reviewed replacement directory |
| 2048 | 128 | Boot LOS header |
| 2176 | 384 | Zero padding |
| 2560 | 65536 | Raw Boot payload followed by zero padding |

The candidate extent has no extra wrapper. Reconstruct LOS as the 128-byte header
followed by exactly the payload length at header offset 44, excluding candidate
padding. Its full SHA, LOS CRCs, target, ABI, profile, zero load/entry addresses
and build ID must all agree. The native directory additionally carries the Apple
additive payload checksum and points only to the reviewed candidate extent.

Before-state construction starts from the verified original firmware backup,
inserts each pinned predecessor candidate, and substitutes the newest predecessor's
directory; without a predecessor it retains the original directory. The new
candidate region must still be zero. Staged and final hashes are obtained by
replacing only the candidate extent and then the directory sector. This exact
state assumption is checked against the device before any write. The package
never authorizes rewriting the MBR, original OSOS payload or whole partition.
# LDS1 display and shared settings

The durable settings payload can wrap its existing music record in `LDS1`.
All integers are little-endian u32: magic at offset 0, embedded payload length
at 4, and backlight timeout seconds at 8. The opaque music payload starts at
12, followed by IEEE CRC32 over the header and payload. Exact total length is
embedded length plus 16 bytes. Accepted timeouts are 0 (Never), 5, 10, 15, 30,
60 and 120 seconds. The default is 30 seconds. The largest current music record
is 444 bytes, so the wrapped record occupies 460 of the available 480 bytes.

Legacy unwrapped music records still restore with the default display timeout.
Display changes retain the existing embedded record, and music writes retain
the current display preference. Corrupt wrappers and legacy records too large
to wrap are preserved rather than replaced. Preference loading and saving wait
for safe storage admission while playback is paused or stopped.

# LMD2 media report

Development Link command 95 returns 192 bytes. Little-endian u32 fields at
offsets 0 and 4 are magic `LMD2` and version 1; offset 8 is sector count (u64).
Offsets 16..60 contain media kind, RPM, logical/physical sector bytes,
capabilities, quirks, power state, idle/wake microseconds, power-off count,
wake count, and idle failure count. Media kinds are 0 unknown, 1 rotating,
2 solid state. Power states are 0 rail off, 1 active, 2 standby, 3 transition.
Capability bits 0..4 are LBA48, flush, PM, APM, enabled write cache. Quirk bits
0..3 are missing-LBA CFA probe, optional APM rejected, CFA claim, exact iFlash
platform model. ASCII model (40), serial (20), firmware (8) occupy offsets 64,
104, 124; trailing bytes through 191 are reserved zero. This report is read-only
and samples no ATA registers while the rail is off.
# PIMG photos and LDS2 settings

Prepared photo catalogs use the bounded PIMG v1 layout documented in
[PIMG_FORMAT.md](PIMG_FORMAT.md). The device reads `/LINNET/PHOTOS/LIBRARY.PIM`.

LDS2 extends the shared LDS1 preference envelope with 16 opaque photo resume
bytes. Its little-endian layout is: magic `LDS2` at 0, embedded music length at 4,
display timeout seconds at 8, photo resume at 12, music payload at 28, then CRC32
of all preceding bytes. Maximum embedded payload is 448 bytes; the current
largest music record is 444 bytes, making the complete envelope 476 bytes.
LDS1 and unwrapped legacy music records remain readable. Photo identity and
indexes are validated against the catalog before restoring a view. Display and
music writes preserve the photo record; photo changes preserve both other values.

PVID video contract: see `PVID_FORMAT.md`.

LDS3 settings keep the existing 32-byte envelope overhead. Header bytes0..3 are
LDS3;4..5 music payload length;6 timeout-choice index;7 zero. Bytes8..19 contain
the photo identity32/index16/flags8/reserved8/pan32,20..27 video identity32/frame32,
then music payload at28 and final CRC32. Old LDS1/LDS2 and unwrapped music records
remain readable. The current maximum music payload444 gives476 bytes total.
Photo flags pack zoom bits0..2, rotation3..4 and view5..6. Video identity is the
validated PVID header CRC. Resume is saved on exit and normal shutdown; EOF resets
the next starting position. Older firmware cannot interpret LDS3.

LDS4 retains LDS3 fields through offset 27, adds u32 battery capacity at 28,
and starts music at 32. The final CRC gives 36 bytes of envelope overhead;
the maximum 444-byte music record fits the 480-byte store. LDS1/LDS2/LDS3 and
legacy music remain readable; older firmware cannot parse LDS4.

LDS5 retains the LDS4 layout and uses byte 7 for time format (0: 24-hour,
1: 12-hour). Other values are invalid. Older envelopes default to 24-hour.

## Optional rollback history (`LRH1`)

`/LINNET/UPDATE0.BIN` and `UPDATE1.BIN` are optional 512-byte LTS1 records.
They leave LUP1 boot metadata and LDS4 settings unchanged. Empty payload means
no recorded outcome. A nonempty payload is exactly 60 bytes: magic LRH1 at0,
version1 at4, reason at8 (1 reset before candidate confirmation; 2 candidate
validation failed), failed slot0/1 at12, fallback slot0/1/255 at16, attempt count
at20, boot generation at24, and failed build ID32 bytes at28. Integers are u32.

Boot records observed outcomes after required update-state publication, using
normal redundant-record flush/readback publication. History is diagnostic and
never changes selection or authorizes image execution. Missing or corrupt history
is reported unavailable. A power loss between boot metadata and history can leave
the prior outcome; history is not an exhaustive audit log. Physical I/O errors
retain normal storage safety handling. A failed history write remains poisoned
and is not retried during that execution. New updates and successful starts retain
the last recorded outcome. Older firmware ignores these additional files.

## Optional theme selection (`LTH1`)

`/LINNET/THEME0.BIN` and `THEME1.BIN` are optional 512-byte `LTS1` records.
They use the existing generation selection, CRC, inactive-copy write, flush,
and readback protocol. The LDS4 settings envelope and opaque music payload
are unchanged, so earlier firmware can still read those settings on rollback.
The additional files participate in the existing FAT non-overlap write proof.

An empty LTS1 payload selects the configured build default. A populated payload
is 9 through 89 bytes: `LTH1` at byte 0, little-endian version 1 at byte 4, then
an ASCII theme identifier and one terminating NUL at byte 8. An empty identifier
also means the configured default. Nonempty identifiers use the compiler's
lowercase dot-separated grammar, including hyphens within segments, and are at
most 80 bytes. Store identifiers rather than palette indices so reordering the
registry cannot change the user's choice. Unknown valid IDs use the default.

Missing, invalid, or poisoned optional records leave theme changes available
for the current session and do not block shutdown. Valid available records
save only under the existing paused/stopped playback and storage admission.
The Themes footer distinguishes `Saved`, `Saving...`, `Default`, and
`This session`. Rendering and input never read or write disk directly.

`linnet storage theme-provision` adds missing records to an explicitly identified
Disk Mode installation. It checks disk serial, exact size, confirmed build,
existing record validity and unchanged boot metadata before exclusive creation.
Existing records are preserved. It does not install firmware or activate a theme.
