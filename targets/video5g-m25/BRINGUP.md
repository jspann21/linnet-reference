# iPod Video bringup checklist

Status: 2026-09-20. Scope: the verified 30 GB MA146 / M25 board with 32 MiB RAM,
PP5022, WM8758 and BCM2722. Bringup is not complete: intermittent USB descriptor
loss remains unresolved. The PHY handoff correction is installed and boots
healthy, but traced USB transaction errors persist. Work is stopped at the owner's
request with the device healthy at Home and the elevated helper stopped.
The cable reportedly works with other devices; a cable fault is not established. Other A1136 variants are
outside the verified scope.

Checked items describe implemented work and the evidence stated beside it;
they do not imply every feature has passed final physical acceptance.

## Ported and exercised

- [x] **Board and build support:** dedicated target identity, memory layout,
  board wiring, storage policy and development/release images; build and memory
  checks pass.
- [x] **Boot and updates:** native Boot, RAM boot, persistent OS boot, A/B OS
  publication and rollback exercised. Original firmware backups are retained.
- [x] **Storage and host integration:** existing FAT32 volume mounted; media
  publication and guarded Disk Mode/eject roundtrips exercised. USB reliability
  is still an open issue below.
- [x] **Display:** native 320 × 240 output, backlight/brightness, screenshots,
  BCM display ownership and restoration exercised on the device.
- [x] **UI and themes:** 29 scene definitions, 27 enabled scenes; all enabled
  scenes checked in the simulator across Paper, Night and Copper (81 combinations).
  Music, Cover Flow, Photos, Videos, Notes and settings have model-sized layouts.
- [x] **Physical input:** wheel, buttons, Menu, Hold and headphone changes
  confirmed by the owner, with device observations logged.
- [x] **Audio:** WM8758/DMA playback, volume and stereo headphones exercised;
  sample checks passed for MP3, AAC, M4A, FLAC, WAV and Ogg Vorbis, plus nine
  sample rates. This is sample coverage, not exhaustive format qualification.
- [x] **Native video:** H.264 Baseline and MPEG-4 Simple playback with AAC audio;
  host preparation/publication and normal Videos menu launch exercised.
  Both 20-second samples completed with zero reported audio underruns/faults.
- [x] **Video controls:** pause/resume, keyframe seeking, Menu stop, saved-position
  reopen, EOF and missing-file handling exercised. Published MPEG-4 audio
  starvation and premature audio-tail shutdown were corrected; repeated playback
  and paused seeking passed with no underruns or inserted silence.
- [x] **Photos and Notes:** populated views, photo fit/zoom/rotation/slideshow,
  and published Notes exercised; Cover Flow checked with device content.
- [x] **Power foundations:** battery readings, charge-budget control, backlight
  policy and sleep/wake implemented; automated sleep/wake exercised.
- [x] **Recovery and developer tools:** Link diagnostics/input/capture, ordinary
  recovery campaigns, BCM clock-loss restoration and fatal display-restoration
  fallback exercised. Release builds pass development-code exclusion checks.

## Required to finish bringup — in order

- [x] **P0 — Restore access.** The device is reachable and the traced roundtrip
  returned the exact healthy installed OS.
- [ ] **P0 — Stabilize USB.** Compare a known-good
  cable/alternate port and cold/manual Disk Mode against software handoff. Capture
  USB events and prove sustained Link and Disk Mode operation. Root cause is
  unresolved; smaller reads alone did not fix it. A subsequent 70-second idle and
  full guarded roundtrip passed, but tracing showed three hidden re-enumerations
  during reads. A reusable, port-pinned UAC helper now captures bounded traces and
  restarts the device; its restart succeeded. Four further byte-exact firmware
  reads passed, with one hidden USB reset. Disk health remains unproven.
  This is not yet a clean USB qualification. See the
  [recovery procedure](../../docs/device-link.md#windows-loses-the-ipod-during-disk-mode).
- [x] **P0 — Publish the current qualified development build.** The helper was
  renewed; the audio fixes are persistently installed with exact image identity,
  healthy startup and clean update state verified. Release builds also pass
  image, memory and development-code exclusion checks.
- [ ] **P1 — Finish physical power/audio acceptance.** Check unplugged operation,
  charging transitions, sleep/wake, shutdown/startup and dock line output. Confirm
  sensible battery reporting; measure runtime rather than infer capacity from voltage.
- [ ] **P1 — Run release firmware on hardware.** Verify normal navigation,
  playback, power behavior and recovery with development services absent.
- [ ] **P1 — Qualify longer and larger workloads.** Long video/audio sessions,
  A/V sync, repeated seeks, large catalogs, uncached browsing during playback,
  photo JPEG fallback, empty folders and persistence across restart.
- [ ] **P1 — Close remaining recovery coverage.** Initial USB enumeration recovery,
  external-bus stalls beyond the tested clock-loss case, parser/transaction faults,
  memory pressure and recovery after interrupted operations.
- [ ] **P2 — Tune measured performance.** Startup/first-frame latency, AAC seek,
  native video throughput, long-list wheel acceleration and large-library search.
- [ ] **P2 — Final UI acceptance.** Check readability, clipping, scrolling,
  backlight levels and artifacts on the physical screen across all three themes.

Manual checks remain deferred until the owner is ready. Completion requires USB
stability, final installed-image verification, recovery evidence and physical
acceptance; passing builds and simulator renders alone is insufficient.

## New feature candidates — proposed, not implemented commitments

| Priority | Feature | Benefit and main work |
| --- | --- | --- |
| First | Video library artwork and details | Use the larger screen for posters, duration and codec details; generate thumbnails on the host to reduce device work. |
| First | Persistent video bookmarks and chapters | Resume across restarts and jump to chapters; add durable per-title state and chapter import beyond the existing playback resume controls. |
| First | Audiobook/podcast library mode | Per-item bookmarks, progress and a dedicated browsing view; reuse audio playback and the existing sleep timer. |
| Next | Richer Now Playing and lyrics | Larger artwork, optional metadata pages and imported timed lyrics; keep rendering within measured playback budgets. |
| Next | Slideshow with music | Combine photo presentation with audio after qualifying shared storage and memory use. |
| Next | On-device health/status page | Make disk errors, USB state, battery readings and recovery reasons understandable without a developer console. |
| Next | Optional file browser | Enable and qualify the currently disabled Files app with explicit supported-format handling. |
| Research | Native USB media transfer | Avoid repeated Apple Disk Mode transitions for publishing; requires a new transfer protocol or mass-storage implementation and strict filesystem ownership. It is not a quick fix for the current USB fault. |
| Research | TV-out and dock accessories | Investigate hardware/protocol support and obtain suitable accessories before promising support. |
| Separate port | Additional Video variants | Admit 64 MiB and other board revisions only after confirming hardware identity, memory, display and installation behavior on each. |

New features follow the P0/P1 bringup work. Keep detailed run logs and device
identifiers in local qualification receipts; maintain this file as the single
model-level checklist.
