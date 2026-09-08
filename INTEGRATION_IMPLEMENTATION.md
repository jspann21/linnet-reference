# Linnet product integration

Batch 7 integration is installed and verified; release qualification remains open. Deferred Batch 4–6 gates remain release blockers in
PROJECT_TODO.md; advancement does not imply release acceptance.

The initial hardening pass closes photo/video owners when their scenes are left,
including navigation caused by development controls without a later input event.
Video cancellation is idempotent while pending reads drain. Music retains its
normal background playback behavior.

Shutdown and Sync disable runtime admission before draining services. Storage
progress callbacks continue their existing watchdog and USB progress, but cannot
reenter UI work and reopen media during terminal cleanup.

Retained diagnostic sleep rejects active or pending photo/video work, busy music,
initialized audio and pending settings writes. Storage resume must succeed before
the backlight wakes. This does not implement full media suspend/resume.

The CLI accepts Batch 7 development and release builds. Existing image, memory
and release-exclusion checks apply. Bounded hardware transition receipts are
stored under out/b07-*; no video throughput claim belongs to this batch's
navigation checks.

Battery capacity is a persisted nominal rating under Settings / Battery, with
1200 mAh as this installation's default and 50..10000 mAh in 50 mAh steps.
It does not change chemistry thresholds, negotiated USB charging current, or
the voltage percentage curve. Runtime/charge-duration estimation remains
unqualified until consumption and battery aging are measured. No capacity is
inferred from the ATA adapter or storage size.

The Batch 7 battery guard requires three distinct valid samples no more than
two seconds apart. A sample older than two seconds or an invalid sample revokes
confirmation. At or below 3450 mV it requests shutdown unless the charging pin
and an available charging source agree; USB requires a nonzero negotiated
current. At or below 3300 mV charging does not exempt the battery. These thresholds
come from the project's Photo/Color power work. Shutdown drains media, skips new
optional music/history/display persistence, and retains required storage flush
and quiescence. The existing PMU shutdown path is unchanged. Physical battery
discharge qualification remains open.

LDS4 extends the shared settings envelope to 36 bytes: LDS3 fields through offset
27 retain their layout, capacity is u32 at28, music begins at32 and CRC ends the
record. The maximum music payload444 fits the480-byte store. LDS1/LDS2/LDS3 and
legacy music remain readable; old firmware cannot read LDS4.

Persistent confirmation now waits for all health bits before consuming the
handoff. Store-open failures allow at most three attempts, one second apart.
Proposed boot state becomes live only after successful publication. A failed
publication latches the error and retains poisoned state and the diagnostic
handoff; it is never blindly rewritten. Full cold-boot installation/rollback
qualification remains open.

Boot now carries the signed elapsed-time watchdog comparison and bounded
32-pair FIFO-checked display worker permanently. Development OS builds retain
the existing startup milestones for distinguishing cache, USB and service
initialization failures. Release builds omit these markers.

The finite Windows refresh helper can optionally install the exact reviewed
Boot plan. `refresh-session prepare --install-reviewed-boot` binds that capability
into its approved snapshot; `refresh-session install --disk-number N` supplies
only the device number and request identity. Candidate bytes and paths come from
the protected snapshot. Payload verification precedes directory publication;
uncertain writes revoke further writes. Later refreshes reuse the same session.

`native_bootstrap_v2.py` supports 32 pinned predecessors with the original guards.
The original `native_bootstrap.py` is unchanged. Host dispatch now accepts the original, v2 and v3 hash-identified versions. Snapshot serialization stores each predecessor
once, preserving every old image without exponential artifact duplication.


USB initial enumeration now allows one bounded soft reconnect after five seconds
of cable-present, non-suspended time. A successful configuration permanently
disables this retry. The restart requires proven DMA shutdown, preserves the
serial descriptor and interrupt mask, and renews the watchdog only between
completed initialization stages. Physical recovery remains under qualification.

Settings / Update / Recovery shows a short running build identity, saved slot,
candidate state and storage error. Rendering uses a cached storage snapshot with
no disk I/O. Its Sync action uses the existing drained Disk Mode transition.
Release faults display a reason code, short build identity and recovery controls
through the bounded LCD path, without UI assets, storage or DevLink.

LNB2 maintenance packages retain version 1 compatibility and add version 2 for
sector-aligned candidate extents from64 to128KiB. The upper bound is fixed in the
receiver; actual package length, extent, hashes, original firmware and directory
remain validated before writes. Final partial chunks are sector bounded. This
supports the larger Boot image through the development OS without Windows UAC.
The original and v2 native planners remain unchanged; v3 adds release Boot plans
and fixed-version dispatch, preserving historical plan verification.


The version2 native Boot installation passed on the iFlash device without UAC
(out/b07-usb-native-installed.json): all required firmware digests matched,
original and previous Boot payloads were preserved, and final directory readback
passed. It read124,900,808 bytes sequentially for installation verification.
The first attempt performed zero writes and exposed an idle-power admission bug:
block-window configuration required initialized hardware even though powered-off
media retained verified geometry. Window configuration now accepts that known,
nonfailed geometry; the first request still owns bounded wake/re-identification.

The earlier Windows helper was bound to b07-01 and could not refresh b07-02.
The current finite helper is bound to b07-03, as recorded below. Device-native Boot
updates bypass Windows elevation by performing the guarded maintenance operation
on the iPod; they do not modify or relax the existing elevated helper's scope.


A further development Boot diagnostic preserves an unfinished startup across a
native reset in the existing crash mailbox, without disk I/O. ReasonB0070001
means interrupted startup rather than a CPU exception. Flags2 identifies this
record: register words0..3 contain trace phase, image size, status and elapsed
microseconds; last_event contains the last startup marker. A valid existing
crash record is preserved. This diagnostic was installed and captured the interrupted startup.


The retained hardware report (out/b07-retained-startup-result.json) captured
phase0x40 and COP watchdog marker0xC0 before runtime/cache initialization. The
current OS clears3,394,152 bytes of BSS before its0x42 milestone. Startup now
renews the inherited watchdog only after completed1KiB blocks during BSS clear
and IRAM copying. It also marks0x41 before BSS and0x43 before the IRAM copy.
Three persistent starts now pass with the current OS confirmed in slotB and
no crash record (out/b07-confirmed-second-startup.json and
out/b07-final-cycle-os.json). The slower
inherited clock versus warm80MHz startup is the working timing explanation.


The current development image is cfb8afb3ef70, with a verified release counterpart
in out/b07-startup-progress-release.json. All three persistent starts retained the
confirmed image. Settings CRC and1200mAh capacity passed after startup, and the
new Update / Recovery screen was captured and inspected. Full power removal,
physical low-battery discharge and release media/user-journey acceptance remain
separate open qualifications; earlier media deferrals remain in PROJECT_TODO.md.


The Windows refresh helper was reauthorized for b07-03 for24 hours
(out/b07-current-helper-start.json). The programmatic Disk Mode request and safe
eject/restart passed with zero changed bytes and the exact installed Boot
identity (out/b07-final-eject-restart.json); final OS identity is checked separately.
Subsequent refreshes during this session reuse that approval.


The final automated Disk Mode cycle returned the exact confirmed Batch7 OS,
with no crash and no pending candidate (out/b07-final-cycle-os.json). Across the
two native restarts and Disk Mode exit, persistent attempts advanced once each
(32,33,34). The device remains on Home. Startup latency and full release
qualification remain TODOs; the watchdog startup regression is resolved.

## Continuation audit

Read-only rediscovery on 2026-09-07 confirmed the installed cfb8afb3ef70 OS,
health31, confirmed slotB, attempt34, no pending candidate, poison or crash
(`out/b07-continuation-identity.json`). The current refresh-only helper remains
bound to b07-03. No Boot or OS installation was needed for this audit.

Durable rollback history remains a separate implementation item. LUP1 is exactly
184 bytes and LBS1 reserves zero bytes; the installed Boot rejects extensions.
A new OS must not silently migrate that metadata. Neither a remaining old slot
nor an empty candidate is sufficient evidence that a rollback occurred.

The startup latency audit found repeated full slot validation in
`ln_update_prepare_boot`: both slots, followed by the selected slot again because
they share scratch storage. The current slot sizes imply 1,290,368 bytes of reads
and validation before a 589,428-byte image is selected. No stage timings establish
its share of the observed delay. A future measured Boot optimization should try
the preferred eligible slot first and read the fallback only on failure, retaining
all digest, image-policy and transactional attempt checks.

Copyable static app and theme starters now live under `sdk/templates/`, with
copy, configuration, compile, simulator and firmware build instructions in
`sdk/README.md`. They use the existing static ABI and discovery paths. Template
verification is host evidence; the confirmed device installation remains the
startup-qualified build identified above.

The unchanged default UI content hash matches the installed build:
`9d47973c5078c1ebe30dd6a908fe8f1c8de623fac2e03e8281da9ce5216720c8`
(`out/b07-continuation-ui.json`). The copied starter configuration compiles and
renders through the existing native simulator
(`out/b07-sdk-template-compile.json`, `out/b07-sdk-template-simulator/report.json`).
The copied-template Batch 7 release build also passes verification and development
exclusion (`out/b07-sdk-template-release.json`). Combined verification and source
digests are in `out/b07-sdk-template-result.json`. This artifact was not installed.

## Rollback and startup follow-up under verification

The next coherent Boot/OS batch adds optional LRH1 history sidecars, preserving
LUP1 and LDS4 compatibility. Settings / Update / Recovery displays the last
recorded unconfirmed candidate or failed validation, or an explicit unavailable/
none-recorded state. Rendering remains cached with no storage I/O. Sidecars are
provisioned additively through `device prepare-update-history` in identified Disk
Mode; existing records and installation files are preserved.

Boot now validates the preferred eligible candidate (or confirmed slot) first,
and only reads the confirmed fallback after candidate failure. The successful
image remains in scratch. Full SHA, LOS policy/CRC, and durable attempt checks
remain required. For the previously observed confirmed-only state this removes
700,940 image bytes of redundant reads/hash/CRC work. Hardware timing and the new
persistent rollback journey are being qualified; no speed claim follows yet.

The rollback/startup follow-up passes development and release OS/Boot builds,
including release exclusion. Default and Midnight native simulators pass.
The prepared development OS is f7124a979a4b and Boot14eefb8d8c56; neither is
installed. The guarded host provisioner created only UPDATE0/1.BIN, with flush
and readback, while retaining the confirmed cfb8afb3ef70 metadata.

Deployment stopped at an external prerequisite: the former24-hour helper process
and pipe no longer existed, so the safe-eject command performed no raw refresh
and no eject. A supported helper restart was attempted; Windows returned canceled
consent, error1223. The device remains mounted in Disk Mode. The new exact plan is
`out/native-bootstrap-b07-04/plan.json`; the currently installed Boot is still
b07-03, and its helper scope is required for the next eject. New plan/package and
all build identities are saved in `out/b07-history-checkpoint.json`.

Focused ephemeral native checks also passed: preferred-slot read counts, invalid
candidate fallback, no boot when both eligible images fail, and poisoned
publication returning no boot slot without retry. Cached history labels and
refresh-change detection pass. Receipts: `out/b07-history-selection-validation.json`
and `out/b07-history-ui-validation.json`. No retained test harness was added.

## Completed rollback campaign and next fixes

Boot14eefb8d8c56 native installation passed all firmware hashes, original/prior
preservation, three writes and124,901,832 verification bytes. OSf7124a979a4b
passed RAM UI/settings checks and persistent promotion to slotA. One deliberately
crashing d33fee5d8ecf candidate in slotB returned to Boot, cleared pending and
preserved confirmedA. The exact crash was saved before clearing. A healthyA
restart displayed `Last: B not confirmed`. Disk Mode readback verified the LRH1
record with failed build, failedB/fallbackA, attempt37 and boot generation67.
Receipts: `out/b07-history-native-installed.json`, `out/b07-history-persistent-confirmed.json`,
`out/b07-history-rollback-observed.json`, `out/b07-history-durable-records.json`.
The first new-Boot promotion took129.85 seconds to host-observed confirmation;
this is not a stage-by-stage timing result or release latency qualification.

The campaign found a stale diagnostic, not another crash: after recovery and
explicit mailbox clearing, an orderly restart synthesized B0070001 from the
already-returned candidate's quiesce trace0x14. `ln_recovery_init` now requires
returned=0 before synthesizing an interrupted-startup report. Actual unfinished
chainloads set returned=0; completed recovery sets1. The fix leaves the proven
BSS-progress watchdog repair and retained ABI unchanged. Its deployment and
subsequent media promotion are recorded below.

## Installed media follow-up and bounded qualification

Bootb6fa9efeb198 is installed under native plan b07-05. Device-side installation
completed three writes and124,901,832 verification bytes, matching the expected
final firmware hash and preserving prior payloads
(`out/b07-returned-native-installed.json`). Integrated media OS8495bdea580d
reached confirmed slotB, attempt40, health31, no pending candidate or crash,
valid settings CRC and1200mAh capacity (`out/b07-media-persistent-health.json`).
This supersedes earlier uninstalled/helper-blocked snapshots in this document.

Photo OS550949694b90 passed RAM health and first/next/previous navigation with
stable expected-image screenshots (`out/b07-photo-ram-health.json`,
`out/b07-photo-device.json`). Exact empty-album resume and descriptor caching
pass local checks; persistent empty-album qualification and measured photo speed
remain open. Idle PHOTOS_STATE/revision alone cannot prove rendering completion.

The bounded resumed24fps video observation remained functionally responsive and
exited without crash or pending work, but failed performance:51 frames presented,
17 late frames and50 audio underruns (`out/b07-video-device.json`). Maximum record
read was285,976us; max step38,554us includes startup and is not attributable to
one frame. The roughly18-second observation is not full-clip or24/25/30fps acceptance.
Local decode-progress checks remain recorded separately in
`out/b07-video-decode-progress-host.json`.

The combined Bass/ReplayGain/crossfeed/right10 balance/preamp-1dB audio run also
failed performance. An active-playback sample showed one underrun/1,024 silence
frames; by stop, audio counters reached14 underruns/15,360 silence frames.
Restored prior-track seeking contaminates aggregate decode throughput, so this
does not isolate a steady-state decoder or DSP cost. Defaults were restored
(`out/b07-audio-effects-device.json`). Earlier successful flat playback remains
valid; full-effects and mixed-codec acceptance remain open.

An ephemeral native state-store fault model passed28 cases/261 assertions,
including torn writes, failed acknowledgements/flush/readback, poisoned retry
rejection, reopen selection and malformed records
(`out/b07-state-fault-matrix-host.json`). This is modeled durability, not physical
power-loss qualification. Release Boot derivation against b07-05 passed reviewed
plan roundtrip, predecessor preservation and release exclusion
(`out/b07-returned-release-validation.json`); no release Boot was installed.

The media persistent start took129.625 seconds to host-observed health; retained
phase0x50 measured26.139570 seconds from late Boot quiesce through OS entry.
These intervals do not isolate mount, hashing, runtime initialization or USB.
Photo/video initialization has now moved after the existing80MHz clock setup;
development OSa3ab32d9e985 and release OS92dd2f775181 pass verified builds
(`out/b07-startup-fast-dev.json`, `out/b07-startup-fast-release.json`). Their RAM
and persistent checks remain pending at this checkpoint, with no speed claim.
Physical battery/unplug/full-power-cycle and release-only journeys remain deferred.


### Final continuation confirmation

The pending startup checks above subsequently passed: a3ab32d9e985 is confirmed
in slotA at attempt43, with8495bdea580d retained in slotB. The deliberate crash
probe has been replaced. RAM photo rendering, video open/cleanup, persistent
health, settingsCRC/capacity1200 and final Home/media-idle checks passed.
The updated Boot's returned-candidate regression also passed: clear the actual
crash, restart confirmed fallback, and no obsolete synthetic diagnostic returns.
Receipts: out/b07-returned-fallback-health.json,
out/b07-startup-fast-persistent-health.json, out/b07-autonomous-final-device.json.

The phase50 handoff interval improved26.1396s to23.9921s; host-observed healthy
confirmation improved from129.625/129.541s to126.245s in one optimized run.
These are combined-stage/host observations, not independent stage benchmarks.
See out/b07-startup-fast-comparison.json. Performance and physical release
qualification remain open. Current checkpoint: out/b07-autonomous-continuation.json.
