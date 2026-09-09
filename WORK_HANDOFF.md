# Linnet work handoff

## Current state: B45 installed, B33 fallback (September 8, 2026)

B45 development OS is persistent in slot A; B33 remains slot B fallback.
Serial 000000F7A765, generation 1, health 31. Installation and post-boot checks
pass: out/b45-install.json and out/b45-postinstall.json. Storage/update clean,
empty crash, audio stopped, Home, synthetic controls cleared, original sound
profile/repeat/shuffle/volume restored. Exact installed build:
85eea59ca0dd61aecd1608d84a0acff0fd50dcb90bed84be44207dc963788e5d;
image SHA256 1ac975af8352124ebcba0852d5d72deed631cdc31f597a192fc6f24e56155b10.
Fallback B33 hashes are retained in the historical baseline below.

Photo loading fix is verified for the two actual prepared photos while playing
MP3 with combined effects: first photo 46.985 -> 5.313 seconds, Next 10.235 ->
2.204 seconds, using matched sparse telemetry. Receipt out/b45-photo-comparison.json.
The full 120.172-second run passes with no sampled audio errors. Exact AAC/ALAC/
AIFF tail plus photo zoom passes two gapless joins and 993132 submitted/consumed
frames; paused seek and 1000-frame EOF checks pass. Both screen captures are
visually correct and content pixels match B34 exactly. Receipts:
out/b45-photo-effects-two-real.json, out/b45-tail-effects-photos.json,
out/b45-controls.json, out/b45-screens.json, out/b45-screen-review.json.

Changes: bounded prepared-image tile batches and ready storage polling, memory
work outside disk admission gates, explicit navigation overriding saved resume,
photo priority outside track tails, and 1.25-second startup PCM buffering.
Startup observation was 2.172 seconds including host UI polling/setup. Prepared
small reads use a 500 ms reserve; opening/validation/JPEG retain 750 ms. B45 also
fixes the diagnosed history FLUSH stall: only completion of an already-written
page can use the normal 750 ms reserve; new writes retain the stricter threshold.
The two-photo 2248192-byte package and original source photographs are unchanged.

Independent installation gate out/b45-final-gate.md passed. Sequential verified
dev/release builds and release exclusions pass; resident margins 816/272200 bytes.
All 454 files matched out/b45-freeze/source-hashes.json before installation;
only subsequent handoff/todo edits create expected source-identity drift.
Artifact reconciliation out/b45-reconciliation.md; unchanged actual photo source
retains B41 ASan/UBSan evidence. Temporary scripts/harnesses removed with hashes
in out/b45-cleanup.json. No commit/push performed. Broader release, arbitrary
catalogs/codecs, non-unity ReplayGain, video and power-loss qualification remain
separate work; this closes the requested two-photo loading fix.

## Historical B35–B45 investigation (superseded by installed state above)

B43 retained the photo speedup but failed the same second transition. Temporary
B44 dev-only PMT diagnostics proved the cause: at 13–16 seconds history was in
FLUSH with no live ticket, its next-record request waiting, while metadata was
complete and roughly 55000 PCM frames remained. The 63488-frame publication
threshold prevented finishing the already-written page. Trace and bit mapping:
out/b44-tail-effects-photos.json, out/b44-diagnostic-map.md. Dense diagnostic
polling also observed an underrun; this diagnostic build is not qualified.
B44 returned cleanly to B33. All temporary firmware/protocol diagnostics were
removed before B45. B45 permits only paged FLUSH/CHECK/ACK completion at the
existing 750 ms background reserve; each new write still requires 63488 frames.
B43's bounded history reads remain a separate scheduling improvement, not the
measured root-cause fix. B45 must pass the original sparse hardware workloads.

B35–B42 candidates are not installed. B42 RAM identity and clean health are in
out/b42-ram-health.json; B33/B19 persistent rollback below remains authoritative.
Matched sparse telemetry shows first-photo completion 46.985 -> 5.344 seconds
and Next 10.235 -> 2.172 seconds. B42 passes 120 seconds MP3 with combined effects
and both complete photos (out/b42-photo-effects-two-real.json). Source/artifact
reconciliation: out/b42-reconciliation.md, out/b42-build-review.json.

Persistence is blocked by out/b42-tail-effects-photos.json: AAC joins ALAC, but
ALAC to AIFF restarts instead of making the second exact join. B38/B40 showed
the same failure; B40 without Photos passed. No sampled underruns occurred, but
that does not excuse the failed transition. B43 is addressing ordinary nested
runtime work in the two history-page reads that precede next-audio preparation.
Keep exact tail/zoom, paused seek, short EOF and screen checks as final gates.

Candidate changes include bounded tile batches and ready storage polls, memory
work independent of disk reserve, prepared-photo read reserve of 500 ms (normal
750 ms for opening/validation/JPEG), 1.25-second initial PCM buffering, and
priority for visible photo work outside known track tails. Resume no longer
overrides explicit photo selection. B41 native sanitized photo checks passed;
B42 source freeze has 454 paths. Later handoff edits are documented source drift.
Reference findings: out/b38-reference-notes.md and out/b38-retail-spec.md. Rockbox
informed initial buffering/prepared images; the retail symbol catalog supplies
no measured scheduler or buffering constants.

## Historical baseline: B33 persistent / B34 photos (September 8, 2026)

B33 installed in slot B, B19 fallback in slot A; generation1, health31, clean
storage/update, empty crash. Build ddd46a2b20ca202478f38e8ed74ff4b59527f31c8b2fb7a4fc44f2fdecbe042e;
image SHA256 3b845bc0a8f162df323da894406e13873284cb27fd89eec9711b1600fb81cb7e.
Receipt out/b34-persistent-install.json. Older baseline statements are historical.

Fixes: remove duplicate nested main-loop runtime callback; AAC emits decoded PCM
within one bounded access-unit call; photo reads coalesce to16KiB while validation
stays4KiB, retaining verified metadata in spare frame memory until rendering.
Native full/seek AAC PCM matches exactly with sanitizer checks passing; photo
validation preserves corruption rejection. Receipts out/b31-host/result.json,
out/b32-host/b33-result.json, out/b33-build-review.json. Sequential verified dev/
release builds have3000/274416 bytes headroom and release exclusion passes.
Firmware matches out/b33-freeze/source-hashes.json; later host/docs drift is expected.

Focused hardware passes: AAC to ALAC to AIFF with combined effects, two gapless
joins,993132 consumed/submitted/DSP frames (out/b33-tail-effects.json);120 seconds
MP3/effects with both photos frame_valid AND frame_complete and zero sampled audio
errors (out/b33-photo-effects-two-real.json). Both PNG captures in out/b34-photos
visually inspected. Storage full1MiB readback,256 random reads,file growth and all
five injected recoveries pass with settings restored (out/b34-storage-campaign.json).
Independent focused persistence gate: out/b34-final-gate.md. Original sound profile,
repeat/shuffle/volume restored; media idle, Home, controls cleared before reboot.

Photo package now contains only the two Anna images; seven format fixtures were
removed. Host compiler defaults to640 pixel maximum zoom, CLI --max-dimension 2048 retains higher zoom detail. Originals unchanged; both
first screen-sized levels pixel-identical.20167168 ->2248192 bytes,88.85% reduction
including removal of fixtures. New SHA256
263eb33936ff0734f52f7eb1a53f6eebe849b2af007806b5ab2db80e6f042dd9.
Backup F:/LINNET/PHOTOS/BACKUP/56E826E8.PIM; publish/restart receipts out/b34-photos.
README documents preparation.

Remaining: first photo still takes44.953 seconds from opening Photos during effects
playback; Next portrait8.281 seconds. Fast browsing remains open. Larger libraries,
non-unity ReplayGain/listening,full codec coverage,sustained video,power-loss
publication and release hardware acceptance remain open. Empty-album driver
assertions were diagnostic failures; prior dense-poll readiness timeouts remain
recorded observations. Use one agent by default, concise output, bounded audits,
and existing checks without redundant runs. Reuse the existing refresh helper.
HEAD2493ae15fd9e62ac843f495928f47f320ab1aa34; no commit/push requested.

## Historical handoff entries

Latest live state: B18 RAM generation3/health31 after successful storage campaign; B16 still persistent. B18 entry below supersedes the earlier current-device statement.

## Latest authoritative state: B16 (September 8, 2026)

Persistent B16 development OS in slotB, generation1 health31. Build `005cd0f327409431ad933a14d9834f41b7b0b7aa78f0fe2fa71c1e26e2759aa3`, image SHA256 `37ac65ea75ad0ce7298f704d90b9bcd65b698dfc622989714a8843b326cd2eb1`. B14 remains fallback slotA; B12 was replaced. Artifact `out/dev/photo4g-p98/os/linnet-os-0.1.0-photo4g-p98-dev-005cd0f32740.los`. Home, media idle, controls clear; storage/update clean, crash empty. See out/b16-integration-outcome.json and B16 entry below.

Current HEAD `2493ae15fd9e62ac843f495928f47f320ab1aa34`; this turn changes photos.c and these two documents without commit/push. Latest source freeze out/b16-freeze/source-hashes.json; documentation drift is expected. User explicitly authorized verified B14 as this installation's baseline. Historical B08/B09/B12 instructions below are superseded by this section.

B15/B16 implement bounded photo intent planning and share its implementation, keeping reserve/render/JPEG rules. Next photo step is a measured cold I/O-cost investigation, not an unqualified fairness or retry change. Broad throughput gates remain open.

## Historical handoff entries

Latest: B15 RAM candidate, B14 persistent/B12 fallback. B15 entry below supersedes older baseline/Git statements. User explicitly confirmed B14 baseline.

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


### B15 photo planning RAM batch (2026-09-08)

- [x] B14 freeze reconciliation: 452 non-document files exact; expected todo/handoff drift only. Starting HEAD2493ae15fd9e62ac843f495928f47f320ab1aa34. User confirmed B14 baseline; live generation1/health31 matched. Refresh helper remained active without UAC.
- [x] Bounded IDLE planning integrated with unchanged read reserve, pending drain, render/JPEG gates. Source SHA5b345f0ff1cc73393cf4f794eb643040a81abeedbc71d13999bd53fabaafa993. Sequential feature-batch7 builds pass; native UI2781events/9frames. Dev6cec92ac3430b854ca97b2f2f3eb181210f6682b6e2fb51ad34998056e5f8413 SHA7cf43394b17d8008a459fa0fe622d63bb8e650912538b7f288a8c551a699d50f; release0ccedc3e1596ea21021923faab22d7e7ddb8d3625538953e6616d6750c437242 SHA5274f10a24e4a608aafd90d22c0306e7907b86fe90000e7b0389bc3a83c0a848. Headroom3400dev/274752release, BSS/stack/IRAM unchanged.
- [x] Exact RAM generation2/health31. Album/grid/viewer and next/previous during MP3 pass with zero underruns/silence/faults; viewer screenshot exactly matches B14 and inspected. Metadata3.875s to3.641s is one observation, not established speed gain. Storage/update clean, crash empty. out/b15-integration-outcome.json and out/b15-independent-reconciliation.json retain scope.
- [ ] Persistence deferred while removing duplicated planning code to recover dev headroom. B14 persistent/B12 fallback retained. Low-reserve intent latency and broad cold/JPEG/audio gates remain open.
- Temporary harness used WAKE2 instead of CLEAR_SYNTHETIC6; all button presses were released. Corrected harness; explicit final clear follows. Driver cleanup correction, not product defect.
- Freeze out/b15-freeze/source-hashes.json remains authoritative; post-build docs intentionally drift.


### B16 qualified persistent photo planning (2026-09-08)

- [x] Shared planner removes B15 duplicate gated tail while preserving admission, pending drain, epoch/resume and JPEG/render policy. Source SHA256 7ff6ed3a92c6f1377782b7b910eeca6d21bea52eb4a46f64b3f66ce227a016f4. Root and independent review pass.
- [x] Sequential verified feature-batch7 builds and independent source/artifact/map/release reconciliation pass. Dev 005cd0f327409431ad933a14d9834f41b7b0b7aa78f0fe2fa71c1e26e2759aa3, image SHA256 37ac65ea75ad0ce7298f704d90b9bcd65b698dfc622989714a8843b326cd2eb1; release c6b340a4f21bb6ac9ee623650aeefa34a7858b005ba7fd93be856e0dda00da02, image SHA256 23fa97475f31ac35772f88765123e1ed1353144ffcd833fa5426b7e55f56387e. Frozen inputs out/b16-freeze/source-hashes.json.
- [x] Headroom4168dev/275616release, recovering768/864 resident bytes versus B15. Text delta vs B14+452/+564bytes; BSS/stack/IRAM unchanged.
- [x] Exact RAM generation3/health31; MP3 plus album/grid/viewer/next/previous passes with zero underruns/silence/faults and identical photo-area pixels. Header-only screenshot difference excluded from photo equality. Settings/Menu, library and clean storage/crash/update gates pass. Independent out/b16-promotion-audit.json passed before installation.
- [x] Returned to exact persistent B14 generation1/health31, inspected clean state, installed B16 once into slotB and rebooted once. Exact B16 generation1/health31 confirmed; B14 remains fallback slotA, replacing B12. Post-install8s playback consumed352256frames, zero underruns/silence/faults. Final Home/media idle/controls clear, storage prepared/error0/quarantine0/pending0, candidate255/attempt0, empty crash.
- [x] Driver cleanup repaired: clear action6, active theme Settings row4, numeric diagnostic dictionaries. Earlier probe errors were driver mistakes; corrected receipts retained. out/b16-persistent-health.json includes numeric SIO1/SPT1/RND1.
- [ ] Cold-load speed, direct low-reserve planning latency, JPEG/audio, broad codec gaplessness and sustained video remain open. Single-run metadata3.828s versus B14 3.875s is not an established speed gain.
- Receipts and exact identities: out/b16-integration-outcome.json. No Boot update or UAC prompt; live refresh helper retained. No Git commit/push requested. Post-build docs intentionally differ from source freeze; compiled sources/artifacts remain exact.


### B17 cold catalog attribution (2026-09-08; diagnostics only)

- [x] Two fresh persistent-B16 OS reboot traces, idle and MP3, pass with numeric SIO1/SPT1/SCD1 snapshots. Same build005cd0f327409431ad933a14d9834f41b7b0b7aa78f0fe2fa71c1e26e2759aa3, generation1/health31. Metadata readiness0.891s idle versus3.891s audio. No audio underruns/silence/faults. These are software-cold observations, not physical-cold timing or established speedup.
- HEADER request max read513578us idle/482986us audio. Audio VERIFY stayed at512 bytes,pending0 from observed0.610 through1.672s with queued PCM21760..32896, below33075 reserve; first subsequent pending1 sample at1.750s. This supports reserve waiting after admitted header cost, not complete owner starvation.
- Audio after snapshot is in-flight (SIO idle_endpoint=false); do not use its interval for closed terminal accounting or sum overlapping SPT timings. Drained cleanup is a separate endpoint. Idle endpoints are both idle. Receipts out/b17-idle.json, out/b17-audio.json, out/b17-attribution.json and independent attribution preserve limits.
- [ ] Next focused implementation investigation: admitted512-byte HEADER chain-proof/positioning cost, including the exact-read-ahead boundary. Do not lower reserve, shorten retry, or add owner fairness without evidence. Local Rockbox/pocketjs references have different threading/storage models; out/b16-next-photo-work.md records the comparison.
- Final B16 remains persistent slotB/B14 fallback slotA, Home/media stopped/controls cleared, clean storage/update/crash. No firmware source change, build, persistent install, Boot write or UAC in B17. Temporary trace driver removed after evidence capture.


### B18 cached chain-proof batching (2026-09-08)

- [x] Ordinary VERIFY_CHAIN now uses existing SET_CHAIN bound of up to4 cached edges per poll. Full EOC/Brent/length/seek proof and at-most-one I/O callback retained. FAT C SHA674c53c8f06beafb326c2a54efbbd870c58707f1839d6b60cfe06270b18e858d. Root and independent source review pass.
- [x] Sequential verified feature-batch7 builds and independent hash/map/release reconciliation pass. Dev c36ce67a230090fb68e9475ebeaf15b935a5131f78af48bca96294f3abc5dc28 SHA0e4a5053f50842a9a8966c58dd040708df90314e42059cb63c53c08e103a915a; release 5ecdfbeaf4d9cfce7b7442580d778b1c51eb55ee37e0ececbd0fb40313685642 SHA15e4d528c10fca0803794444871d7358ddcaf6b294a778591754e76bed83e4d0. Text+92bytes each, BSS/stack/IRAM unchanged; headroom4104dev/275520release. Freeze out/b18-freeze/source-hashes.json.
- [x] Exact RAM trials generation2(audio)/3(idle),health31; photo catalog/viewer/next/previous pixels match B16. Zero audio errors. Single observations: idle metadata0.891s to0.672s, HEADER513578us to261731us; MP3 metadata3.891s to2.969s, HEADER482986us to457127us. No established statistical gain; timing spans are not isolated ATA cost.
- [x] Existing storage campaign 20260908T143429Z-photo4g-p98-c36ce67a2300-0001 passes1MiB SHA readback,256 random reads, settings restoration, WORK growth and all5 fault/recovery modes. Final clean storage/update/crash. Historical native harness sources were deleted, so no claim of rerunning them; no new tests created.
- [ ] Persistence deferred pending next bounded request-local FAT sector reuse candidate. Current B18 RAM generation3; B16 persistent slotB/B14 fallback slotA. Receipts out/b18-integration-outcome.json.
- Post-build docs intentionally drift; compiled-source/artifact identity stays frozen.


### B19 request-local validated FAT sector (2026-09-08)

- [x] VERIFY_CHAIN reuses its validated primary FAT sector with explicit request-local tag; mirror/edge/Brent/length validation and cached4-edge bound retained. Tag invalidated at admission, read overwrite, terminal, cancellation, abandon and EOC. FAT C SHA66957fa4013fb88ec366af35dbe1f9163cfa2cb64d6c345181b11f15b42156a4; H SHA2ea82be6d44fd450f400823dcffbfc307bf2f8058896381092ef7a076ff1cca6. Root and independent writer/lifetime audits pass.
- [x] Sequential feature-batch7 dev/release verified builds/reconciliation pass. Devdbbbf9fc72c30ce046e6563a105dad6e207744e0419372350a90b71b106e5802 SHA61532da3584719569ada754abd3a188ce3b3221fdff7fc58d1d079636ee86640; release053721c6b2b0316d58d5ec8124b5875dd6fa3e7a9a89e8749b02bdae98fffaab SHAd177380f30ca1ad5855f02cce6610b4f105ba33922f188232e21573f815c943c. Source freeze out/b19-freeze/source-hashes.json. Headroom4872dev/276320release. Compiler outlined shared FAT io/admit helpers, accounting for all788bytes less text vsB18. ARM context remains7168bytes: tag fits padding; BSS/stack/IRAM unchanged.
- [x] Exact RAM4/5 health31, idle/audio photo journeys with identical full viewer pixels, no audio errors. HEADER idle261731us to152784us and audio457127us to337956us versusB18. Single observations, not statistical claims.
- [x] Existing campaign 20260908T144256Z-photo4g-p98-dbbbf9fc72c3-0001 passes1MiB full SHA readback,256 random reads, settings exact restoration, WORK32768 to40960 and all5 fault/recovery modes. Independent promotion audit passed.
- [x] Returned exact persistent B16 generation1/health31 with clean state, installed B19 once and rebooted once. B19 confirmedgeneration1/health31 in slotA; B16 fallbackslotB retained, replacingB14. Clean storage/update/crash. No Boot update/UAC. Receipts out/b19-integration-outcome.json.
- B20 begins120s flat/effects controller-driven MP3 qualification. MP3 total frames may be0 in player diagnostics despite known library duration; initial driver assertion corrected and aborted receipt retained, not a product defect. Broader mixed-codec/non-unity ReplayGain/listening gates remain open.
- Post-build todo/handoff edits intentionally drift; compiled sources/artifacts remain exact.

## B20 / B21 audio qualification (September 8, 2026)

- B20: persistent B19, same Five O'Clock500 MP3 from startup, flat120.329s and combined profile120.297s. All sampled audio faults/underruns/silence/FIFO-empty/lateness remain0. Independent audit confirms consumed/DSP progress and original profile, repeat, shuffle and volume restored. Queue cursor/seed/resume changed through playback; full settings are not byte-identical. Receipts: out/b20-integration-outcome.json and out/b20-independent-audit.json. ReplayGain On uses unknown/unity metadata; listening and non-unity gain remain open.
- B21: existing All Tracks30-item queue, select28ALAC then automatic29AIFF, repeat/shuffleOff. Sparse flat control with0.5s sampling and no active screenshots passed one join/missed0, exactly441000 consumed/submitted/DSP frames, final per-track220500 and clean state (out/b21-sparse-flat.json). Persisted queue CRC/order/cursor verified.
- Combined effects failed before transition even with sparse observation: at4.718s, position181248/220500, joins0, underruns2/silence4096 (out/b21-sparse-effects.json). Intrusive0.1s/screenshot runs also failed: effects beforejoin, flat atjoin. These retained failures demonstrate limited observation margin, not a universal flat gapless pass. Timing spans overlap; decode timing includes demux/read/poll work.
- All runs stopped through controller and restored Flat/effectsOff/center/stereo/preamp0, repeatOff/shuffleOff/volume-48dB; storage/update clean and crash empty. Hardware remains B19 with B16 fallback. No Boot/UAC work. Frozen B19 compiled sources still match; docs drift intentionally.
- Next B22: review a bounded byte-chunk ALAC bitreader candidate, preserving exact packet bounds/cursor/error behavior, before build and matched hardware trials. Broader codec/rate/effects/listening gates remain open.

## B22 qualification / B23 preparation

B22 bounded byte-chunk ALAC reader passed independent source/build review,5322240 exact reader cases under ASan/UBSan, and full220500-frame plus seek5371 PCM comparison with baseline/FFmpeg. Source622dbda90c3d16fb8ef4401c8a6ce1f6b2cd65bc3f5acec89e0b39708c4e005c; dev361b8b0fa623f184de681ab56c60a4ecffc2bb1a27ed4f3559404708a1a1f399 imageca7d92e20aedfa04c15106bfbf84cd6dd9764616d62d52602646d5e087a265da. Sequential build text+692/BSS0/stack0, headroom4200dev/275616release.

RAM generation2/health31 passed sparse flat ALAC-to-AIFF441000frames/onejoin, but effects still failed beforejoin at4.703s with1underrun/1024silence. Observed maxdecode73796us vs B21's81780us is insufficient and not a statistical speed claim. No promotion. Exact persistent B19 generation1/health31 returned clean (out/b22-return-persistent.json); B16 fallback retained. Full outcome out/b22-integration-outcome.json. Flat/profile/options restored; no Boot/UAC work.

B23 adds only bounded five-step leading-zero counting to B22. Independent proof review,2114112 exact CLZ comparisons under ASan/UBSan, and full/seek PCM equivalence passed before building. Candidate source912e8ccfbad90cf3c22ab26ab40a57e445d3ec197b6ca292440473ba0b05b96e. Device benefit remains unproven; matched sparse qualification is next. Existing build closure will be frozen before sequential builds; subsequent docs may drift intentionally.

## B23 qualification / B24 preparation

B23 bounded CLZ passed exact-source review,2114112 native comparisons and full/seek PCM equivalence under ASan/UBSan. Sequential artifacts audited: devc25f19a4876ae1a4edc0731c80a798676a8b5072de72ef0fbfc07cb7492eb692 image628b777eceeb953c6898232c624f72bf65b884ec181f9d90f7f4fbaa7c98f4b3. Text+84vsB22 (+776vsB19), headroom4104dev/275552release; BSS/stack/IRAM unchanged.

RAM generation2 health31 sparseflat passed441000frames/onejoin. Effects completed ALAC without observed underrun but missedjoin1: next_phase0 persisted until firsttrackEOF, queuedPCM max29696 below existing33075-frame library reserve. Audio reinitialized for AIFF; no same-stream/gapless claim. Maxdecode60589us is one observed peak, not pure decoder CPU or statistical evidence. No promotion. Returned exact B19 generation1 health31 clean (out/b23-return-persistent.json); profile/options restored. Outcome out/b23-integration-outcome.json.

B24 investigation follows actual ARM lowering: single-bit Rice reads retain general fragment logic despite inlining. Prepare a dedicated bounded readbit preserving current packet/cursor/failure invariants. Keep metadata/admission reserve policy unchanged. Independent review and exact native PCM checks precede build; B19/B16 persistent slots remain unchanged.

## B24 qualification / B25 preparation

B24 dedicated ALAC readbit passed source/ARM/native/build audit.152064 reader states plus full/seek PCM byteexact under ASan/UBSan. Dev71ddb9949d9f5b7a9be1ca32226a8c5612dab3e20e2ddf25d77f93bdbce88996 imagebfc1bec073d3e85e7bd99355b150ffed71878622e292d85abfadffdfa8214723; text-64vsB23, headroom4168dev/275616release. Sparse flat441000frame/onejoin passed. Effects failed atEOF5.781s: ALAC220500complete, nextopening, underrun1/silence1024. No promotion; returned exact B19generation1health31 clean, settings restored. See out/b24-integration-outcome.json.

B25 addresses redundant next-row reads without lowering reserve gates. Browser window rows contain track/title/artist/path but omit album/artwork; existing full-row cache shortcut was already present. Prefetch now enriches a validated partial row under the existing job/token/drain rules. Actual library/database native diagnostic with existingPDB and delayedreads reduced AIFF29 reads5to1 and MP3art0 reads7to3, matching full reference rows. Full-cache0reads, pausedI/O, inflight supersede/cancel and pending-window move passed under ASan/UBSan (out/b25-host/library-result.json). Sourcefeaab551ac817749c3c367263a0a3fc8f982a1ddd1fea864338f4d70a3eef02d independently reviewed; builds/device pending. B24 ALAC optimizations retained in candidate source only; B19 remains persistent.

## B25 qualification / B26 preparation

B25 partial-row enrichment passed independent source/native/build audits; native actual parser/storage-owner diagnostics independently rerun. Sequential devcf1c8bd4f02b4b642d373582e906d7a8102f40b3bae66f0b6d24ba3cd5c0b095 imageb50f6c2296b2eba170d45ad3f43b1af5878728d00090fdb629c03b19e49ae6fd; text+228vsB24, headroom3944dev/275392release; BSS/stack/IRAM unchanged. Sparseflat441000frame/onejoin passed. Combined effects still failedEOF5.734s,nextopening1,underrun1/silence1024. No promotion; exactB19g1health31 returned clean; all original profile/options restored (out/b25-return-persistent.json). Outcome out/b25-integration-outcome.json.

B26 unrolls only the six-term sum in ALAC's general order6 predictor; adaptation/warmup/signextension/othercounts unchanged. Existing asset uses this order for70.28% channel-frames. Source256a595a28f91aff3e61437cc8762be456a8fdbcbb2ff6329bb47f5bac468c78 independently reviewed with existing-fwrapv arithmetic; native full220500frame andseek5371 outputs byteexact to FFmpeg under ASan/UBSan (out/b26-host/decode-result.json). B25 cache work retained; no reserve policy change. B26 build/device gates pending; B19/B16 remain persistent slots.
