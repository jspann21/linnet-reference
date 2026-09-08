# Startup timing and remaining performance work

The September 7 BTT1 instrumentation is implemented but awaits parent-owned
firmware builds and device measurements. No startup speed improvement is claimed
from instrumentation. Existing nibble CRC, preferred-slot retention and bulk BSS
clearing remain in place. Clock policy and integrity checks are unchanged.

Development command54 (`python linnet device boot-timeline --port PORT`) reads a
192-byte BTT1 record from retained-control bytes256..447. Command53 STT1 remains
64 bytes at192..255; display capability160, READ_LOG96 and metrics32 are unchanged.
Release builds omit instrumentation and transport. Both records report missing
stages as unavailable, use raw microsecond timestamps with modulo32 subtraction,
and add no watchdog renewals. BTT1 counters saturate at UINT32_MAX.

BTT1 follows Boot C entry through recovery setup, development USB initialization,
ATA initialization, FAT mount, fixed-file discovery, extent proof, state-store
opening, image preparation, and handoff. Preparation counters separate time
inside image reads, SHA processing and LOS validation, with completed bytes and
attempted read calls. Read time includes synchronous storage progress work;
LOS validation time includes its existing progress callbacks. These counters
are not pure ATA bus time or pure CRC CPU time. Fallback attempts accumulate.

OS stages cover C entry, recovery validation, runtime clock setup, media init,
input/power/display and completed first frame, monitor/cache setup, USB init,
storage mount/proof, successful persistent confirmation, first development poll,
and first parsed host request. First host request includes host scheduling and
enumeration; it does not independently timestamp USB configuration. The first
frame is the initial shell frame, before later saved settings/library work.

`chainload_to_os_c` includes retained candidate CRC, copy and assembly setup.
Read STT1 alongside it for candidate CRC, copy/entry, BSS and IRAM subdivisions.
`boot_prepare_and_rejection_history` includes durable attempt publication and
optional rejection history; post-prepare time includes handoff creation,
snapshot checking and quiescence. Boot C entry excludes earlier Boot assembly.

Only successful native preparation grants one-shot native provenance. A failed
chainload consumes it. RAM launches reset native timing, and an OS running under
older Boot produces OS-only BTT1. Generation and OS-entry guards reject stale
handoff records. The host reports `native_boot` to distinguish these cases.

## Parent measurement request

1. Run the coherent development/release Boot and OS build checks, including
   release exclusion, then qualify RAM behavior before persistent installation.
2. After one authorized persistent start, capture identity/health/build IDs,
   STT1, BTT1, READ_LOG and host-observed healthy elapsed time in one receipt.
   Require matching generation and `native_boot=true` for native conclusions.
3. Compare Boot file/proof, read/SHA/LOS validation, late handoff, OS runtime and
   host-contact durations. Resolve the dominant measured cost first. Do not
   infer isolated BSS performance from total host elapsed time.

Host syntax and manual decoder smoke evidence is in
`out/b07-boot-timeline-host.json`. No firmware build or device operation was run
by the startup task. Parent owns all firmware builds and device measurements.

## Photo loading audit

First header read can include the full PIMG FAT-chain proof; separate that from
metadata CRC/semantic validation and directory open time. For viewer loading,
measure navigation, level descriptors, final validated tile, frame publication
and LCD completion. Photo revision/title changes and `frame_complete` alone do
not prove completed rendering. Compare cold and cached navigation, then the same
uncached operation with a filled audio ring. Existing photo receipts establish
correctness but do not establish the remaining speed target.

Conditional candidates are metadata parsing in bounded record runs, coalescing
adjacent tile payload requests within existing scratch capacity, and adjusting
render slices from measured frame-publication delay. Existing descriptor
batching, cache/read-ahead and integrity checks must be preserved. No speculative
photo changes are part of this timing patch.


## Stage 2 timing checkpoint (2026-09-07)

SPT1 selector 2 is 16 words: magic, version 1, storage-init epoch, flags,
then media poll calls/us/nested calls/us, progress calls/us/nested calls/us,
all storage-service FAT poll calls/us, and progress runtime callback calls/us.
Counters publish completed inclusive spans and saturate. Media polls exclude
stale owners. Progress and FAT counters cover all storage-service callers.
Nested means reentry of the same function, not the outer runtime invocation.
Total minus nested gives top-level inclusive time for that function only;
progress, FAT, runtime callbacks and media poll overlap and must not be added.

Flags bits 0..11 identify counter saturation, bit 28 an active sampled span,
bit 29 depth/reset anomaly, bit 30 elapsed duration at least 2^31 us, and bit 31
exhausted init epoch. Reject any flagged snapshot. Compare only one uninterrupted
firmware/recovery generation, matching SPT1 and SIO1 epochs, with host/SIO1 time
brackets. Static epochs restart on reboot. No scheduling changes were made.
State is exactly 64 bytes; release removes instrumentation. Native helper checks
with GCC ASan/UBSan and four profile/image syntax checks passed, alongside an
independent review. See out/b07-storage-poll-native-host.json and the video
owner's out/b07-storage-poll-link-host.json. Parent owns firmware size checks
and hardware qualification.

BTT1 version 2 retains the 192-byte layout, using words 46/47 for Boot clock
status and directly observed clock-source register. Status 0 unobserved,
1 skipped, 2 attempting, 3 verified 80 MHz, 4 failed. Verified means the existing
clock transition returned after PLL/source validation. Inherited register words
still describe entry before the attempt. The host accepts strict legacy v1 and
v2; no retained RAM was added. See out/b07-boot-clock-telemetry-host.json.
The clock precondition helper is unchanged; parent native qualification remains
pending for the clock patch and instrumentation.

The isolated FAT/SHA native parent capture reached first frame at 65.531741 s
(previous 86.492944 s) and confirmation at 68.847487 s (previous 93.999130 s).
Boot proof fell to 3.696672 s from 19.107623 s. Source receipt:
out/b07-storage-speed-native-timeline-device.json. This predates the early
Boot clock change and must not be attributed to that change.
