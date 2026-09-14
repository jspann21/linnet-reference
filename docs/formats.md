# Linnet binary contracts

Linnet has one current binary contract and one product release number: `0.1.0`.
Persisted and wire records carry no compatibility or format numbers. Counters
used to order writes or reject stale commands are runtime state only. Reserved
fields must be zero. Readers reject unknown magic, unexpected
lengths, nonzero reserved bytes and invalid checksums.

Integers are unsigned little endian unless marked signed. CRCs use
CRC32/ISO-HDLC with reflected polynomial `0xedb88320` and initial/final XOR
`0xffffffff`.

## Native image (`.los`)

The image is a 128-byte header followed immediately by the ARM payload.

| Offset | Width | Field |
| ---: | ---: | --- |
| 0 | 4 | `LNOS` |
| 4 | 2 | Reserved zero |
| 6 | 2 | Header bytes, 128 |
| 8 | 4 | Numeric target |
| 12 | 4 | Reserved zero |
| 16 | 4 | Profile: release 0, dev 1, trace 2 |
| 20 | 4 | Payload bytes |
| 24 | 4 | Load address |
| 28 | 4 | Absolute ARM entry |
| 32 | 4 | Payload CRC32 |
| 36 | 32 | Build identity |
| 68 | 56 | Reserved zero |
| 124 | 4 | Header CRC32 over bytes 0..123 |

The loader checks target, profile, address bounds, exact length and both CRCs.
The build identity records provenance and is separate from the payload checksum.

## Boot state

The 32-byte `BOOT` record contains reserved zero at offset 4, generation at 8,
attempt count at 12, confirmed and candidate slots at 16 and 17, pending-attempt
flag at 18, zero through 27, and CRC32 at 28. Slots are 0, 1 or 255 for absent.

## Crash mailbox

The 144-byte `CRSH` record contains reserved zero at 4, record size 144 at 6,
sequence at 8, reason at 12, r0..r15 at 16, CPSR at 80, flags at 84, build
identity at 88, boot generation at 120, service and event identifiers at 124 and
128, reserved zero at 132 and CRC32 at 140.

## Native identity

HELLO, INFO and STATUS return the 96-byte `LNID` record: target at 4, reserved
zero at 8, profile at 12, image kind at 16, health flags at 20, boot generation
at 24, capability mask at 28, build identity at 32 and full image SHA-256 at 64.

## Transactional state

Each redundant state copy is exactly 512 bytes. `STAT` is at 0, reserved zero at
4, nonzero publication generation at 8, payload length 0..480 at 12, twelve zero
bytes at 16, payload at 28, zero padding through 507 and CRC32 at 508. The reader
chooses the valid copy with the newer wrapping generation. Equal-generation
copies must be identical. Two all-zero copies mean uninitialized state.

## Persistent update metadata

The 184-byte `UPDT` payload stores reserved zero at 4, the `BOOT` state at 8 and
two 72-byte image slot records at 40 and 112. Each slot contains actual image
length, profile, build identity and complete `.los` SHA-256. An empty slot is all
zero. The 80-byte retained `HAND` record stores the selected slot at 4, build
identity at 8, image SHA-256 at 40, reserved zero at 72 and CRC32 at 76.

The optional 60-byte `RLBK` payload records one failed boot result: reserved zero
at 4, reason at 8, failed and fallback slots at 12 and 16, attempt count and boot
generation at 20 and 24, and failed build identity at 28.

## Native maintenance package

`LNPK` is a fixed-purpose maintenance package. Its header is 512 bytes: reserved
zero at 4, package length at 8, target at 12, reserved zero at 16, reviewed disk
geometry and candidate extents at 20..79, storage and USB identities at 80..111,
all required before/after hashes at 112..463, zero padding through 507 and CRC32
at 508. The body contains the exact MBR, expected directory, replacement
directory, native image header and padded payload. The target manifest supplies
the geometry; the package never authorizes arbitrary sectors.

## Settings and theme

`SETT` is the sole settings envelope. Bytes 4..5 hold music payload length, byte
6 holds the display-timeout choice, byte 7 holds 12-hour clock selection, bytes
8..19 hold photo resume state, bytes 20..27 video resume state, bytes 28..31
battery capacity, music starts at 32 and the final four bytes are CRC32. Total
length is music length plus 36 and may not exceed 480. An empty transactional
payload means defaults have never been changed.

Theme selection is empty for the compiled default or a 9..89-byte `THMS` record.
Offset 4 is reserved zero; offset 8 begins a NUL-terminated stable theme ID.

## Music history

`MUSIC0.BIN` and `MUSIC1.BIN` are equal-size redundant history banks. Each bank
has 1,025 pages of 4,096 bytes. Page zero is a `HIST` superblock with reserved
zero at 4, header size 64, total bytes, 1,024 data pages, 125 records per page,
32 bytes per record and a 16-byte epoch. Data pages use `HPGE`, reserved zero,
page index, publication sequence, count, event revision, occupancy bitmap and
the same epoch. CRC32 is at byte 4092 of every page. Each record stores stable ID,
flags, play count, bookmark frame and resume frame. No alternate bank layout is
accepted.

## Queue and sound state

`MSET` contains queue length at 4, a `QUEU` record at 8, a 32-byte `PROF` sound
record and final CRC32. `QUEU` byte 4 selects explicit storage 0 or virtual-source
storage 1; it is an encoding kind, not a release number. `PROF` carries reserved
zero and fixed length 32 at offset 4. Every embedded record has its own CRC.

## Content

- Music databases use `PODB` with a reserved-zero header field.
- Photo packages use `PIMG` with a reserved-zero header field; see
  [photo-format.md](photo-format.md).
- Video packages use `IPVF`; see [video-format.md](video-format.md).
- DSP profiles use `LDSP` with a reserved-zero header field.
- Notes use `NOTE` with a reserved-zero header field.
- Baked fonts identify themselves as `FONT`.
- Compiled UI, theme, application and content manifests use `LNUI`, `THME`,
  `APPL` and `CNTN`.

Development wire framing and diagnostic record layouts are documented in
[device-link.md](device-link.md).
