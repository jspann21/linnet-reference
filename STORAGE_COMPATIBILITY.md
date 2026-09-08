# Storage compatibility

The P98 ATA driver discovers capacity from IDENTIFY data. It does not assume the
installed card is 64 GB. Addresses and capacity use 64-bit values; LBA28 and
LBA48 commands are selected with checked bounds. Invalid or changed geometry is
rejected before data access. The filesystem currently requires an MBR FAT32
volume with 512-byte logical sectors. 512e media is reported correctly; native
4K logical sectors, GPT and exFAT are rejected rather than reinterpreted. These
filesystem limits are separate from the ATA addressing limit.

| Media | Identification and policy | Physical evidence |
| --- | --- | --- |
| iFlash ATA1 currently installed | Exact model `iFlash-Platform iPod Adapters`; firmware `iFlash85`; solid-state profile. Five seconds idle, successful flush, two-second delay, then rail off. ATA standby is not sent when unsupported. | 125,042,688 sectors; idle rail-off and one cold wake/read passed, approximately 0.59 seconds. |
| Mechanical ATA drive | Reported rotation rate selects rotating media. Ten seconds idle; flush then supported standby. Known rotating media with PM can power off after two seconds. | Original spinning drive is not connected; behavior is implemented but not physically qualified. |
| Other identified SSD/CF media | Reported nonrotating media and separate PM capabilities determine policy. Supported standby is used; rail removal requires a proven safe completion. | Not physically qualified. |
| Unidentified adapters or legacy drives without a rotation-rate field | Preserve unknown classification. Use advertised PM standby; retain rail power when a safe rail policy is not established. | No claim of universal adapter compatibility. |

The exact iFlash profile is independent of card capacity and serial number. A
CFA claim alone does not identify iFlash. The installed adapter's malformed LBA
capability flag is accepted only after a successful LBA-0 READ VERIFY command.
Unknown models are never assigned iFlash power behavior merely because their
capacity resembles an SD card.

Cold wake restores the P98 rail and pins, waits 250 ms before controller access,
resets, and re-identifies the device. Capacity and model/serial/firmware identity
must remain consistent. Requests allow up to 30 seconds for wake; host data
commands allow 45 seconds. Idle operations are serialized with the block queue,
disabled during filesystem transactions, and backed off after failures. Failed
flush/write barriers prevent further writes until explicit recovery. APM is set
to the lowest level without autonomous standby when advertised; an optional APM
ABRT is recorded, while transfer-mode errors remain failures.

ATA metadata does not establish a drive's actual current draw. Linnet uses the
board's existing storage supply and a conservative settling delay; it does not
raise USB charging current based on an adapter name or card capacity. Physical
spin-up current and timing on the original drive still need measurement when
that drive is available. PIO remains enabled for reads and writes; no unqualified
DMA policy is inferred from SSD identification.

`python linnet device media-info --port COM6` reports identity, capacity, sector
sizes, capabilities, profile quirks, rail/standby state, wake and power-off counts,
and idle failures without waking storage. The block cache retains two read
windows so corresponding mirrored FAT sectors remain resident. Writes, reset,
rail-off and partition-window changes invalidate both windows; full chain and
cross-link validation remains enabled.

Source basis: the user's local `rockbox-ipod-photo` fork at `a0e9e0c700`,
especially `firmware/drivers/ata.c`, `firmware/export/ata.h`, and
`firmware/target/arm/ipod/power-ipod.c`. Relevant fork commits include
`1ea65d99ab`, `0fb032dd28`, `b3a55fffb2`, `a9beba8662`, `004c09eeec`,
`6701604789`, `0aab6395f8`, and `cfe93e9b0c`. Linnet uses its own asynchronous
implementation of these behaviors.

Validation is intentionally light per the user's instruction. Evidence:
`out/b02-iflash-light-wake.json`, `out/b02-media-mounted.json`, and the development,
Boot and release build reports. No stress, repeated power-cycle, or destructive
fault campaign was run. Native Boot installation plans remain explicitly pinned
to the inspected physical disk and backup; they are not reusable generic images
for another drive or partition layout.

Boot `3dfc7bd0a7b1` and OS `1767aa1f5e02` are installed. The persistent OS
confirmed its slot, reached health 31 and then powered the iFlash rail off after
idle. The helper's original 60-second reconnect wait expired before completion;
subsequent read-only inspection verified startup, and the host deadline is now
180 seconds. Startup is still slow despite the reduction in physical reads.
Installation evidence: `out/b02-storage-compatibility-complete.json`.

The Batch 3 OS `3ac3673f2188` supersedes that OS and includes the final queued
durability-barrier correction: after an issued durability operation fails,
already queued write/flush/standby operations are rejected until explicit
drained recovery clears the barrier. Strict builds and focused local dispatch
checks passed. Persistent slot A, health 31 and zero storage errors are verified
in `out/b03-persistent-verified.json`. Boot remains `3dfc7bd0a7b1`; no native Boot
write or additional drive-fault campaign was needed for the UI update.
