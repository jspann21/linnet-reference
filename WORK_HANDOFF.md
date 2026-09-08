# Linnet work handoff

Updated September 8, 2026 after B14 persistent qualification. This section supersedes historical device-state entries below.

## Current device and artifacts

- Persistent B14 development OS in slot A, generation1 health31: `85b084e7bac6a36db8b52d2af38bb61a8babbb4c0968e69a7479c48f54070efc`.
- Image SHA256 `8faabd6b90c57df5cc5c06e2a8ba683f3cc34a75d490dc58a4b107bfde2a9e22`; artifact `out/dev/photo4g-p98/os/linnet-os-0.1.0-photo4g-p98-dev-85b084e7bac6.los`.
- B12 remains in slot B as fallback; B09 was replaced by B14. Home, media idle, synthetic controls clear, storage prepared/error0/quarantine0/pending0, crash empty. Candidate255, attempt pending0. Serial000000F7A765, COM6.
- B14 includes B12 fixes, B13 corrected short-title search cache/SCD1 diagnostics, and AUD-05 CPU idle during proven hardware waits. Runnable FAT, completions and expired/queued work retain the veto; ATA is timer-polled, no ATA IRQ wake assumed.
- Verified sequential dev/release builds and identity: dev headroom4648, release276192. Frozen sources `out/b14-freeze/source-hashes.json`; subsequent docs intentionally differ. Development text+252/BSS0 versus B13. Release excludes SCD1 while retaining actual idle policy.
- Paired8-second playback: both353280 frames, zero underruns/silence/faults. Runtime calls2343→1340; measured idle950821→1162099us. Single observation with different boot/cache histories; no power or battery-life claim.
- Existing storage campaign passed1MiB SHA readback,256 random reads, WORK growth16384→24576, exact settings restoration, all5 injected fault/recovery checks. `out/runs/20260908T123920Z-photo4g-p98-85b084e7bac6-0001/receipt.json`.
- Final receipts: `out/b14-integration-outcome.json`, `out/b14-persistent-install.json`, `out/b14-persistent-identity.json`. No Boot update performed.
- Root independently verified Luna gapless player harness dev/release5cases; no source bug. Actual codecs/queue/controller/DMA/listening remain open. `out/luna-gapless/root-review.json`.
- Completed temporary search/gapless/root playback harness sources/binaries removed after verification; hashes retained in `out/b14-completed-harness-cleanup.json`. Staged candidate sources and result receipts retained.
- Startup CRC candidate remains staged under `out/luna-startup-final`. Root requested correcting claims about nonexistent B12 Boot/alternate Boot slot and wrong headroom reference. Ordinary OS slots are distinct from installed Boot/native-bootstrap workflow. Do not use the original unrepaired candidate.
- Initial local commit `e1c458c` remains last commit; subsequent changes are uncommitted. No push requested. Video paused. New work uses Luna Max under root review; no further Sol assignments.

## B09 changes and evidence

- Validated replacement preparation/recoverable publication for music stages
  (AUD-01); eight focused manual checks pass.
- Compiler input identity enters firmware identity (AUD-02); pruned traversal
  (AUD-11); seven focused checks pass.
- AUD-03 slideshow/AUD-07 JPEG fixes were already integrated and are reconciled
  to their historical exact comparisons. PIMG slideshow device dwell passed;
  JPEG device decode speed/fallback remains open.
- PHT5 v2 diagnostics retain v1 host compatibility. Extra counters are dev-only;
  software readiness and step intervals must not be called LCD/isolated CPU time.
- Tile hint cache plus row-affine transform reduced render intervals by 36.80%
  Landscape and 52.76% Portrait. All rotations/zoom/pan and flat pixels match.
  Four cached-photo changes during settled MP3 added zero underruns/silence/faults.
  This does not close concurrent cold-catalog or uncached-photo audio gates.
- `out/b09-photo-render/comparison.json`, `affine-device.json`,
  `rotation-baseline.json`, `affine-review.json` carry evidence.
- Sequential verified dev/release builds: `out/b09-affine-dev-os.json`,
  `out/b09-affine-release-os.json`. Independent reconciliation:
  `out/b09-affine-independent-audit.json`. Source freeze:
  `out/b09-affine-freeze/source-hashes.json` and `photos.c`.
- Release build: `e0edbc56864fc4ea0bb9eb02b1d7a55eec6affa00c19160d7084863d325695ab`.
- Resident headroom 10592 bytes dev / 280536 bytes release. Relative to B08-B,
  resident growth is 920/224 bytes. Tile hints add64 static bytes; diagnostics
  account for development-only extra storage. No audio IRAM/stack region growth.
- Post-build todo/handoff edits intentionally differ from source freeze; compiled
  source files and delivered artifacts remain exactly audited. Do not rebuild
  merely to absorb evidence documentation into the ID.

## B10 trial and managed work

B10 temporal candidate was host/native correct but rejected for real-time audio.
It was never persistently installed. Candidate sources/artifacts remain in
out/b10-freeze, out/b10-dev-os.json and out/b10-release-os.json. Version2 legacy
playback stayed at69 frames per bounded run; temporal version3 reached72 but
recorded49 underruns/239616 silence frames. NoLCD77/52/229376 also fails.
The prior v2 asset and exact production video.c/video.py were restored; current
persistent B09 state above remains authoritative. Receipts:
out/b10-restored-device.json, out/b10-video-restored.json, out/b10-source-restored.json.

Frame-zero normalization for a full temporal device run did not settle, so no
full-run result exists. Independent native full288-frame/576000-PCM checks,
seek/preroll/cancellation, and bounded device control checks did pass.

Both refresh/eject cycles had early HELLO timeouts after verified directory
refresh. No mutation was replayed; subsequent read-only checks confirmed B09.
The power task has this host-readiness issue as follow-on work. The helper remains
active and unpoisoned, with no new UAC or Boot changes.

Four user-requested Sol Medium tasks work on isolated copies and report to this
coordinator01a07f1f-95c4-7de1-a7a4-c72ae4dc0115. Registry:
out/sol-task-coordination.json. Tasks own AUD-04 cancellation, AUD-09 power,
AUD-08 allocation, and video-throughput follow-up. Do not duplicate their staged
implementation. Root owns production integration, build sequencing and device.
When a worker reports, review its patch/evidence, give fixes or next work, and
keep the todo current. No independent task may promote a source/device change.

## Next work

Prioritize staged PVID3 integration and measured video preparation bottlenecks;
see `out/b09-next-video-assessment.md`. Preserve current production fixes rather
than copying the older prototype wholesale. Broad video throughput remains failed.
Photo cold proof/read admission and scheduling intent are separate gates;
`out/b09-photo-review.md` reviews the unfinished fair-media staging, which must
not be promoted as-is. Physical checks already completed by the user remain
accepted; only genuinely new physical behavior needs interaction.

Before any new persistent update, return to THIS known persistent B09, require
exact build/generation1/health31 and clean update/storage/crash state, then publish
once. Never retry ambiguous mutation. No Git commit/push requested; repo has no HEAD.

## Historical B08-B handoff

Updated September 8, 2026 after B08-B persistent qualification.

## Device and elevated helper

- Device serial: `000000F7A765` (normally `COM6`).
- Persistent OS: B08-B development build
  `3c80fcc0434b97daaee6b375245b5a5dd5a6b17c64348b23be4545747bfdd78f`,
  image SHA-256
  `72db5c9d157accc7b86673f2c0c0f34b6bf6276cf777d3f19ebd12f4546e7418`.
- Persistent receipt: `out/b08-b-persistent-device.json`. It confirms generation
  1, health flags 31, slot 1 confirmed, candidate 255, attempt pending 0,
  clean storage state and zero crash bytes.
- Installed aligned video asset SHA-256:
  `c7685daabeed9d17c4d570e0d1bb4b70dcbf23557dbc218498cfb0bb31ca7d6b`.
- Active refresh helper session:
  `8d2e95de8d0e4b558de094a7640c1253`, PID 310748, started
  `2026-09-08T03:06:19.279758+00:00`, duration 86,400 seconds. It is unpoisoned
  and bound to `out/native-bootstrap-b07-sprint-dev/plan.json`, plan SHA-256
  `ad8006671f75c7177599291a640590e6e3cb7098e353356e1c9f2a6294f2aa92`.
  It authorizes refresh only; `install_reviewed_boot` is false.

## B08-B source and builds

- Production source hashes:
  - `services/storage/storage.c`: `88fcd218b6f4f59f1346f0a279dabb139511bab4a40f8f7ee8fb5fdbb49e6a0e`
  - `services/storage/storage.h`: `7d08619579b1200912468137680024593d7f28d7466d7edb125596283c182a28`
  - `services/video/video.c`: `5455ba1302aee09ed5f356f89af8b59da7849af694077a0a21b7e5e5173d971e`
- Composite freeze and snapshots:
  `out/b08-video-storage-paused-composite/`.
- Development build receipt: `out/b08-b-dev-os.json`; release build receipt:
  `out/b08-b-release-os.json`. The release exclusion gate passed.
- Relative to B08-A, linked text grew 316 bytes in development and 304 bytes
  in release, with no data, BSS, stack or audio-IRAM growth.

## Device results

- Normal eight-second video: 69 frames, 46 underruns, 245,760 silence frames,
  zero faults (`out/b08-b-video-normal-device.json`).
- No-display eight-second video: 73 frames, 48 underruns, 237,568 video silence
  frames, zero faults (`out/b08-b-video-nolcd-device.json`).
- Settled paused video reduced timer service by 98.15%. Three pause/resume
  cycles responded in 16-31 ms, six paused seeks settled in 219-625 ms, and
  stop completed in 94 ms (`out/b08-b-video-paused-qualification-v2.json`).
- Full frame-zero playback completed 288/288 frames and 576,000/576,000 PCM
  samples in 46.375 seconds with zero media/storage faults and empty crash data.
  It still recorded 264 underruns and 1,634,304 silence frames, so sustained
  video throughput remains open (`out/b08-b-frame-zero-full-video-device.json`).
- Post-run health, Home wheel input, library, storage and update checks passed:
  `out/b08-b-post-video-health.json`.

## Open work

- Active video throughput remains the main video blocker. Temporal PVID3 has
  host and ARM prototype evidence in
  `out/b07-video-temporal-prototype/temporal-qualification-receipt.json`, but
  still needs coherent production integration and device qualification.
- B08-A concurrent music/photo evidence found that MP3 playback remained
  healthy while the photo album row never became selectable in 20 bounded
  retries: `out/b08-a-photo-audio-device-v5.json`. The staged investigation is
  under `out/b08-photo-audio-window/`. Its low-runway metadata candidate built
  as B08-C but missed the fixed five-second album-to-grid gate and showed no
  visible tiles. B08-C was rejected, production `services/photos/photos.c` was
  restored to SHA-256 `e8dec923b5431b6c0fc5848b0d10b3a3f0ae48dda8f3188fb6e116aca4500650`,
  and the device returned to persistent B08-B
  (`out/b08-c-photo-audio-rejection.json`). Astra review found that the IDLE
  phase still applied a zero-byte/full-runway gate before scheduling RECORD and
  retained 200 ms sleeps, so this run does not isolate owner starvation. The
  next experiment must expose request intent, actual sector/proof cost and media
  owner state before adding fairness (`out/b08-c-photo-audio-assessment.md`).
  A cold persistent trace reached VERIFY offset 25,088/80,384 during five
  seconds of uninterrupted MP3 playback, then finished 0.485 seconds after
  audio stopped. HEADER storage work depleted queued PCM to 11,648 frames and
  VERIFY then waited about 1.8 seconds for refill. Qualify cold proof cost,
  VERIFY admission and post-ready row intent independently
  (`out/b08-b-photo-audio-gate-cold.json`,
  `out/b08-fair-media-astra/consultation.md`).
- Track-change latency, photo first-load speed, direct power-current measurement,
  broader release journeys, and the Notes application remain open in
  `PROJECT_TODO.md`.

Before any future persistent update, inspect identity, update status, storage
state and crash bytes. If testing a RAM generation, first reboot to this known
persistent B08-B image, reconnect on generation 1, and require candidate 255,
attempt pending 0 and clean storage state before publishing exactly once.

## B11 RAM candidate, 2026-09-08

Root integrated combined AUD-04 v2/AUD-08 and corrected AUD-09 v2 plus host eject readiness. Frozen inputs: out/b11-freeze/source-hashes.json. Dev f6d2616df6b32edd14b844728f7a1c2da11a129412f902145d05155732f960af (SHA06c78b857b2b93ce876d8c4507ddf2a2a3eddd7ec7178e8bdd2ba1bf55cad14d); release5eb34c819e6db398b62309cc72ee08e1ec7ef8516499e9cd627c7618a274e0c9. Sequential verified builds/reconciliation pass, dev headroom8128. Post-build todo/handoff edits intentionally differ from frozen source identity.

Device currently runs B11 in RAM, generation2 health31, after bounded MP3 playback with zero underruns/silence/faults. Final read-only storage is prepared/error0/quarantine0/pending0, crash empty. See out/b11-post-playback-drained.json. B09 remains persistent; no B11 persistent install. Next root gate: cancellation/mutation/device qualification, including allocation worker final-source evidence. All four Sol Medium tasks continue staged work: combined-source fault review, AUD-05 schedule diagnostics, B09 video per-record diagnostics/host decoder, startup initial-dev-chainload CRC reuse. No diagnostics or startup candidate included in B11. Do not repeat physical checks already passed.

User authorized one initial local Git commit after Sol tasks complete. Relevant production/project files form the first main-branch baseline; generated out/ and unintegrated Sol/Luna candidates are excluded. Git text normalization means a future fresh checkout may have different byte-based build identities from the retained Windows source freeze; current B11 identities and receipts remain authoritative for the tested images. No push requested. Video work remains paused. New work uses Luna Max subagents under root review.

## B12 latest state (supersedes B11 RAM state)

User requested retrieving/integrating ongoing Luna results. Root integrated photos.c fast tile-descriptor verification, FAAD specrec.c discarded-synthesis work reduction, power.c/h phase-age-preserving cancellation, and controller.c failed-volume100ms retry backoff (including clearing resolved deadlines). Source freeze out/b12-freeze/source-hashes.json; dev1219d6c50a3e35f5e456028a4ea10600b1b01db790665c89c295a050161e7dab SHA3b2c4f6ec35d98ca34913d9f97106e0487bfae525aa8b48e7db0bd702917768d. Release0bba10ed7c9bd018e690d2543ea9bad0a1c7d054df69a3075959266ef7f45104. Both verified builds/reconciliation pass; headroom7384dev/277328release. Post-build docs intentionally differ from source freeze.

Device currently B12 RAM generation3 health31, Home, media stopped, controls cleared, storage prepared/error0/quarantine0/pending0, crash empty (out/b12-photo-cancel-device.json). B09 remains persistent and B08-B fallback retained. B12 exact AAC seek paired gains9-13%; photos+MP3 passed with exact viewer screenshot and no audio faults. The cancellation probe did not observe pending I/O: exit/next-owner evidence only. Fault-path power tests are native actual-C with MMIO mock, not physical bus-failure qualification. Original controller harness expectations and mock-time regression were corrected before acceptance. out/b12-integration-outcome.json and out/b12-device-comparison.json summarize evidence.

Luna tasks: power_revision packaging integrated power/controller validation; luna_b11_review completed independent AAC and repaired staged startup checks, now reviews SCD1 diagnostics. No new Sol work; video paused. Startup repaired package out/sol-startup-review remains unintegrated; never apply original startup candidate (dropped size/alignment admission checks). Initial local commit e1c458c remains last commit; B12 changes are local uncommitted work. No push requested.


### B12 storage campaign (2026-09-08)

- [x] Existing device storage campaign passed: 1 MiB full SHA readback, 256 seeded random reads, settings publication with exact restoration, WORK creation/growth to 16384 bytes preserving prior data and zero extension, and five injected fault/recovery modes. Final storage prepared, error0/quarantine0/pending0. Receipt: `out/runs/20260908T114616Z-photo4g-p98-1219d6c50a3e-0001/receipt.json`.
- [ ] Reset at every metadata publication stage and persistent crash rollback remain unqualified by this campaign; automated_passed does not mean complete hardware qualification.

Root returned from B12 RAM to exact persistent B09 generation1 health31, clean storage/crash/update state. B12 alternate-slot publication is in progress; inspect update state before any repeat if interrupted. Preflight receipts out/b12-promotion-preflight.json and out/b12-persistent-base-preflight.json.
