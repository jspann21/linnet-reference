# Linnet remaining work

## B45 installed — requested photo fix complete

- [x] Improve loading of both actual photos during combined-effects playback:
  first 46.985 -> 5.313 seconds; Next 10.235 -> 2.204 seconds.
- [x] Close the history FLUSH stall during track transitions: photo/zoom workload
  passes two exact gapless joins and 993132 audio frames, with zero sampled errors.
- [x] Pass 120-second MP3/effects/photos, paused seek, short EOF, screen comparison,
  sequential verified builds, source reconciliation and independent install gate.
- [x] Install B45 in slot A with B33 fallback in B; verify generation 1, health 31,
  clean storage/update/crash and restored original settings at Home.

Evidence: out/b45-final-gate.md, out/b45-install.json, out/b45-postinstall.json,
out/b45-photo-comparison.json. Exact hashes and scope are in WORK_HANDOFF.md.
Broader qualification below remains open. Subsequent progress entries are historical.

## Historical B45 preparation

- B44 temporary diagnostics identified history FLUSH admission starvation;
  B45 lets an already-written page finish flush/readback at the 750 ms reserve.
  New writes retain the full-ring threshold. Diagnostics removed before build.
  Require original sparse tail/zoom and sustained photo tests to close the issue.

- B42 RAM: first photo 5.344 s, Next 2.172 s versus matched B33 46.985/10.235 s;
  120-second MP3/effects/two-photo receipt passes and settings restore.
- Still blocked from persistence: second ALAC-to-AIFF transition fails with
  photo/zoom workload (out/b42-tail-effects-photos.json). B43 targets history
  page polling before next-audio preparation. Require exact two joins/993132
  frames, controls/screens and independent final gate before installation.
- B33 persistent/B19 fallback remains unchanged. See WORK_HANDOFF.md for hashes.

The user authorized moving from Batch 4 to Batch 5 while retaining the following
work for later. The user also authorized proceeding to Batch 6 with photo loading
speed and remaining photo qualification retained below. Batch 4's full qualification gate is still open. Advanced audio
features remain in scope; the default playback profile stays flat with effects off.

## B33/B34 verified progress

B33 is persistent with B19 fallback. Combined-effects AAC/ALAC/AIFF passes two
joins and993132 frames; MP3 plus both actual photos passes120 seconds with fully
rendered frames and zero sampled audio errors. Storage readback/five fault
recoveries pass. See out/b34-final-gate.md and out/b34-persistent-install.json.
Host-prepared two-photo package is2.25MB versus20.17MB including prior fixtures;
640px zoom default preserves originals and screen-sized pixels. Initial photo
loading during effects remains45s, Next8s; keep speed and broader acceptance open.
Full details and evidence are in WORK_HANDOFF.md. Prior findings below are historical.

## Batch 4 follow-up

- [ ] Sustain playback with EQ, ReplayGain, crossfeed, balance and preamp combined.
  B20 on persistent B19 passed matched 120-second MP3 runs flat and with Bass
  EQ, ReplayGain on (unity metadata), crossfeed, R10% balance and -1 dB preamp.
  All sampled audio error counters stayed zero; DSP processing advanced and
  sound/options were restored (`out/b20-independent-audit.json`). Non-unity
  ReplayGain, broader codecs and listening remain open. B21 then found an
  ALAC effects underrun before its transition. B26 now joins successfully,
  then underruns in AIFF; standalone AIFF effects fails on both Home and
  Now Playing (B27). B28 investigates deferring nested runtime calls during
  bounded audio storage polls. B28 then passed standalone AIFF effects and
  both flat/effects ALAC-to-AIFF pairs, plus pause/seek/resume/stop. Longer
  codec and mixed-workload/input checks remain open; B19 stays installed
  (`out/b28-integration-outcome.json`). B29 broad sequence underruns in AAC;
  standalone AAC effects reproduces on B19. Photo readiness under MP3
  effects also times out on both builds. The two-minute combined check
  remains incomplete (`out/b29-integration-outcome.json`). Sparse B26 flat pair also passed
  (`out/b21-gapless.json`). The earlier starvation receipt
  `out/b04-throughput-effects-device.json` is historical.
- [ ] Complete broad mixed-codec automatic gapless qualification. The bounded
  ALAC-to-AIFF pair passes on OSc714: one gapless join, zero missed joins,
  underruns, silence, errors, faults and crashes, with441,000 audio/DSP frames
  (220,500 per track). See `out/b07-alac-overlap-queue-device.json`;
  direct playback also passes (`out/b07-alac-overlap-direct-device.json`).
  The older `out/b07-integrated-alac-aiff-gapless.json` remains invalid as
  transition evidence because it observed no join. Broader codec/rate and
  combined-effects transitions remain open.
- [ ] Finish exact AAC seek performance qualification. On OS `4d8301cb1617`,
  paused seeks to 6/10/2/8 seconds reached exact samples in
  2.953/2.078/1.360/3.000 seconds, 27-34% faster than the prior bounded runs.
  Pause/resume and stop overriding seek also passed
  (`out/b07-aac-crc-ui-audio-qualified-device.json`). Broader seek/control and
  listening qualification and the latency gate remain open; earlier timings are historical.
- [ ] Finish the broader mixed-codec seek, control and listening campaign after
  those changes; keep prior successful MP3 listening and control results valid.
- [ ] Revisit the 100,000-track search latency target. Correct results and queue
  behavior passed. Last observed first-result render times were about 729 ms cold
  and 179 ms repeated; the 75 ms target is explicitly deferred. Separate data-ready,
  render and LCD completion measurements before further tuning. The normal
  30-track library has been restored.
- [ ] Qualify display timeout and wake on battery and AC, including persisted
  settings; USB timeout and synthetic wake checks already passed.
- [ ] Physically qualify accelerated scrolling for long lists. Basic wheel
  behavior passed; acceleration passes 28 host cases
  (`out/b07-wheel-motion-validation.json`), with physical feel still pending.

The historical Batch 4 baseline was build
`466c204743470074fefdf27cbdde10a02cc4325a664f9ca5f3afd2eb47f17c3a`.
Its native MP3 flat-profile recheck ran about 42 seconds with zero underruns,
silence frames, audio faults, FIFO-empty samples or positive completion lateness
(`out/b04-original-mp3-baseline-recheck.json`). Installation and reboot evidence
is tracked separately under `out/b04-batch4-*`.

## Batch 5 follow-up

- [x] Compile PIMG photo albums, thumbnails, oriented and prescaled RGB565 tiles.
- [x] Integrate bounded catalog reads, tile/thumbnail caches and audio-aware work.
- [x] Integrate albums, thumbnail browsing, viewing, zoom, pan, rotation,
  slideshow and resume into the native shell.
- [x] Add a bounded baseline JPEG fallback and reject unsupported input cleanly.
- [x] Build and verify development and release firmware, including release exclusion.
- [x] User confirmed the selected photos load on the device.
- [ ] Improve photo loading speed: user reports photos load a little slowly.
  Persistent B19 combines bounded photo intent planning, four cached FAT edges
  per verification poll and request-local reuse of a verified FAT sector.
  Single cold metadata observations improved from B17/B16's 0.891 to 0.547
  seconds idle and 3.891 to 2.860 seconds during MP3 playback, with identical
  completed viewer pixels and clean audio. See `out/b19-device-comparison.json`
  and `out/b19-integration-outcome.json`. Repeated timing and broader workloads
  remain open; these observations do not establish a statistical speedup.
  Measure file open, tile reads, frame preparation and LCD completion separately;
  optimize bounded read coalescing and next-photo preparation.
- [ ] Finish photo hardware qualification: detailed physical control feedback, concurrent
  audio, reboot resume and native JPEG fallback. Nine selected images are installed;
  exact portrait/landscape pixels, zoom/rotation, second-page grid and slideshow
  advance passed. Cached-view audio reentry still recorded an underrun; compare
  the same playback interval on Home before assigning a cause. The subsequent
  Home12s/preloaded-viewer4s comparison passed with a filled audio ring; early
  playback entry and uncached photo interaction remain open.
  A corrected B08-A concurrent run kept direct MP3 playback healthy but could
  not make the photo-album row selectable in 20 bounded retries, identifying
  storage arbitration/starvation rather than a navigation-driver failure
  (`out/b08-a-photo-audio-device-v5.json`). A narrow low-runway metadata
  candidate built cleanly as B08-C (+260 text bytes, no data/BSS growth) but
  missed the fixed five-second album-to-grid gate and exposed no visible tiles.
  It was rejected, production was restored byte-for-byte, and the device
  returned to persistent B08-B with health31 and no crash
  (`out/b08-c-photo-audio-rejection.json`). Source review then found the IDLE
  phase still requested a zero-byte/full-runway policy before scheduling RECORD,
  and the deadline retained 200 ms sleeps; the run therefore does not isolate
  owner starvation. Continue with explicit request intent, real sector/proof
  bounds and owner telemetry (`out/b08-c-photo-audio-assessment.md`). A cold
  B08-B trace reached VERIFY offset 25,088/80,384 in five seconds with audio
  continuous, then completed the remainder 0.485 seconds after audio stopped.
  HEADER held storage while queued PCM fell to 11,648 frames, followed by about
  1.8 seconds of reserve refill before VERIFY resumed. Treat cold proof cost,
  VERIFY admission and post-ready row intent as separate gates
  (`out/b08-b-photo-audio-gate-cold.json`,
  `out/b08-fair-media-astra/consultation.md`).
- [ ] Measure first-open catalog verification on larger photo libraries; the
  initial implementation scans metadata in bounded chunks before browsing.
- [x] Implement exact empty-folder selection resume within the existing compact
  LDS4 record. Six native roundtrips, legacy views, bounds rejection and settings
  preservation pass (`out/b07-photo-resume-cache-validation.json`).
- [ ] Qualify empty-folder resume on the device, including persistent restart.
  Photo OS550949694b90 is RAM-launched and healthy
  (`out/b07-photo-ram-health.json`). First/next/previous navigation passed with
  stable screenshots of the expected images, 35/20 visible tiles, and no error
  or crash (`out/b07-photo-device.json`). PHOTOS_STATE does not prove exact
  render completion, so this establishes no loading-speed improvement. The
  historical persistent OS at that checkpoint was f7124a979a4b; the current
  compatible baseline is recorded below.
- [x] Resolve persistent OS startup and confirmation. The Batch 7 retained
  diagnostic identified the assembly BSS-clear watchdog gap; the corrected
  installed OS passed three persistent starts (attempts 32, 33, 34).
  See `out/b07-startup-progress-result.json` and `out/b07-final-cycle-os.json`.

Storage qualification remains bounded and light. Original drives, iFlash and
other adapters/capacities must retain their device-specific power and timing
handling; this work does not authorize a drive stress campaign.

The earlier unsigned COP watchdog comparison and one-shot confirmation findings
were repaired. The subsequent retained startup record proved a separate watchdog
gap before runtime initialization; Batch 7 closed that gap. These successful
native restarts do not establish full power-removal qualification.

## Batch 6 follow-up â€” deferred with user authorization

- [x] Implement PVID converter/validator, native buffered playback, video controls
  and compact backward-readable shared resume settings.
- [x] Build development/release firmware and run the existing native UI simulator.
- [x] Validate the authorized 12-second clip conversion and exact native frame
  reconstruction on the host; all four PVID record types and seek/resume passed.
- [x] Integrate the earlier IPVF container, spatial/temporal LZ4 reconstruction,
  rational cadence and IMA audio directly into Linnet's video player and catalog.
- [ ] Remove measured LCD and storage bottlenecks and prevent video from starving
  audio. Current PVID hardware playback has not passed qualification.
  Bounded decode-progress changes pass local native validation
  (`out/b07-video-decode-progress-host.json`); device throughput remains open.
- [ ] Qualify 24/25/30 fps, A/V synchronization, seek/exit and corruption handling.

The user authorized proceeding to Batch 7. The IPVF comparison produced a
10,514,992-byte validated clip versus PVID's 19,265,024 bytes (45.4% smaller).
That historical bounded device run recorded six audio underruns; this is an open
release blocker, not a passed video gate. See VIDEO_IMPLEMENTATION.md and
out/b06-video-sample/blit-device.json.

## Batch 7 integration and remaining qualification

- [x] Provide copyable app/theme starters and current Batch 7 SDK instructions.
- [x] Unify media cleanup on navigation, sleep, shutdown and USB transitions.
- [x] Implement fresh-sample low-battery protection and optional-persistence
  suppression; host policy checks pass. Capacity is configurable, default1200mAh.
- [ ] Qualify low-battery shutdown, charging and unplug behavior on hardware;
  cable presence alone is insufficient when USB is suspended.
- [x] Resolve persistent candidate boot/confirmation and add Update / Recovery status.
- [x] Verify development/release builds and bounded mixed-use device transitions.
- [ ] Complete release-only hardware and physical user-journey acceptance after
  deferred media and performance gates are resolved.

- [x] Add cached Update / Recovery status and a drained Sync action.
- [x] Add release fault code/build display and physical recovery instructions.
- [ ] Qualify the bounded initial USB re-enumeration recovery trigger on hardware.
  Host policy validation and builds pass; the trigger has not been fault-injected.
- [x] Validate release Boot plan derivation while preserving pinned predecessor tools.

- [x] Install the expanded native Boot package without UAC and verify all
  firmware publication hashes (out/b07-usb-native-installed.json).
- [x] Capture the interrupted startup and resolve the assembly watchdog gap.
  Persistent OS promotion now passes; early USB probes can still precede
  completion of startup. Measure and improve startup latency separately.

The earlier cfb8afb3ef70 startup correction passed native restart checks; the BSS
watchdog blocker remains resolved. Installed OSf7124a979a4b with Boot14eefb8d8c56
subsequently passed healthy confirmed-slotA return after a failed slotB candidate.
At that checkpoint the post-eject persistent check reached attempt39 with health31, no crash,
no pending candidate, valid settings CRC and capacity1200mAh retained
(`out/b07-history-post-eject-health.json`).

- [ ] Reduce startup latency and measure mount/validation/BSS time separately.
  Preferred-slot validation with retained selected bytes is implemented and
  locally validated (`out/b07-history-selection-validation.json`). Persistent
  stage timing now exists, including the measured SHA/FAT improvement below;
  further startup reduction and clock-boost qualification remain open.
- [x] Implement Boot-compatible durable rollback history in optional LRH1 sidecars.
  LUP1 and LDS4 remain unchanged. Host provisioning and dev/release builds pass.
- [x] Install and qualify the rollback/startup batch: OSf7124a979a4b and
  Boot14eefb8d8c56 were installed at that checkpoint. A failed slotB candidate fell back to confirmed
  slotA; disk inspection verified UPDATE1 history generation2 for attempt37.
  See `out/b07-history-native-installed.json`,
  `out/b07-history-rollback-observed.json`,
  `out/b07-history-durable-records.json` and
  `out/b07-history-post-eject-health.json`. These later receipts supersede the
  canceled-consent/uninstalled snapshot in `out/b07-history-checkpoint.json`.
- [ ] Finish the physical full-power-cycle and release-only journey after deferred
  media qualification; two native restarts are not a power-removal campaign.

- [x] Reauthorize the finite Windows helper for installed Bootb07-04 and verify
  programmatic Disk Mode entry, safe eject, automatic Boot restart and healthy
  confirmed OS return without an additional UAC prompt during that cycle.
  Current-scope receipts: `out/b07-history-newhelper-start.json`,
  `out/b07-history-durable-eject.json` and
  `out/b07-history-post-eject-health.json`. The earlier b07-03 helper receipts
  describe the predecessor Boot installation.

Batch7 integration is installed and the startup/recovery pass is complete.
Release acceptance remains open for the explicitly deferred media/performance
work and physical battery/full-power-cycle/user-journey qualifications above.

The continuation audit also keeps final performance counters/baseline comparison,
parser and transaction fault-corpus coverage, and release installer acceptance
open where no matching receipt exists. Existing bounded transition receipts do
not establish every planned memory-pressure or fault campaign. Exhaustive drive
stress remains outside the authorized scope.

Startup source review found 1,290,368 bytes read and validated by the prior slot
selection for a 589,428-byte selected image: both populated slots are validated,
then the selected image was loaded again into shared scratch. The implemented
Boot change evaluates the preferred candidate then confirmed fallback and retains
the selected validated bytes. The prior byte count does not explain the
minute-scale startup delay. Separate Boot mount, slot read/hash/CRC, copy, OS BSS,
OS mount, first frame, confirmation and first successful host identity timing.


## Autonomous continuation — installed September 7, 2026

At this historical checkpoint the device ran development OS `a3ab32d9e985` in confirmed slot A,
with healthy prior OS `8495bdea580d` retained in slot B and Boot `b6fa9efeb198`
installed under plan b07-05. Attempt43 passed, no candidate/pending update or
crash remains, capacity1200mAh and settings CRC are intact, and the device was
left at Home with audio/video idle. See `out/b07-autonomous-final-device.json`
and `out/b07-autonomous-continuation.json` for that historical checkpoint.

- [x] Verify the returned-candidate diagnostic fix on hardware: deliberate A
  failure, confirmed B fallback, explicit crash clear, native restart and no
  resurrected diagnostic. `out/b07-returned-fallback-health.json` passed.
- [x] Replace the deliberate failing slot with the verified startup candidate.
- [x] Optimize OS BSS clearing in32-byte batches while retaining completed1KiB
  watchdog renewals; move large media initialization after clock/cache setup.
  Dev/release builds,1030-size assembly validation, RAM health/photo/video
  cleanup and persistent confirmation passed.
- [x] Extend host state fault coverage:28 cases/261 assertions, including torn
  publication and poisoned retry rejection; no hardware durability claim.

The retained phase50 interval fell from26.1396s to23.9921s. Host-observed healthy
confirmation was126.245s versus129.625s/129.541s in the previous two runs.
This is one optimized hardware observation, not an isolated BSS benchmark;
Boot mount/validation, later initialization and USB delays still need separate
measurement. See `out/b07-startup-fast-comparison.json`.

Sustained video and full-effects music remain failed performance gates in the
bounded device measurements. Sound defaults were restored. Detailed physical
checks remain deferred at the user's request. The new b07-05 Windows helper
UAC was canceled(error1223); the existing24h b07-04 helper cannot service the
new plan. Native installation/restarts completed independently of that helper.


## Physical feedback — September 7, 2026

The user is now available and confirmed screen readability, wheel in both
directions, Select/Menu navigation, and Hold blocking/restoring input. Physical
photo next/previous, zoom, rotation and back navigation worked; initial loading
still felt slow. Battery operation, Play/Pause shutdown/staying off, and USB wake
to Home worked. Automated return confirmed attempt44, no crash, settings CRC
and1200mAh preserved. The long blue startup screen remains a user-visible delay.
These are development-build checks, not release or low-battery qualification.

Music listening/control feedback identified a stationary progress bar and slower
rapid track changes. The bar's cause is zero compressed-track duration in the
library; a validated30-track metadata update preserves IDs/paths/audio hashes.
On persistent B08-A, framebuffer captures at positions 47,104 and 182,272 differ
inside the progress-bar region, proving that the visible bar now advances; the
run had zero audio underruns or faults (`out/b08-a-progress-bar/receipt.json`).
Rapid-skip measurements show prepared Next at0.203s but the final request of
three rapid skips at5.234s, mostly waiting behind the prior track's audio runway.
The B08-A stale-prefetch cancellation also passed a four-action rapid
Next/Previous sequence without underrun, silence or fault, but perceived
track-change latency still needs physical follow-up. Receipts:
out/b07-physical-session.json, out/b07-physical-power-after.json,
out/b07-progress-import-validation.json, out/b07-rapid-skip-before.json and
out/b08-a-audio-device-v2.json.

The b07-05 Windows helper was approved at that checkpoint for24h at
2026-09-07T19:07:22Z (out/b07-physical-helper-started.json).


### Physical music repair follow-up

The duration importer now counts decoded samples for compressed tracks. The
30-track metadata refresh was published with all31 media/art files reused and
verified. Queue generation390 retains order, cursor, position and settings;
active STATE0 and both history banks were verified unchanged.

Development OS `67d33bb353f15` retires superseded library jobs and promptly stops
the previous track on an accepted manual fallback selection. Existing host
checks and dev/release builds passed. Hardware final playback after three rapid
Next requests improved from5.234s to1.500s. A prepared-next run still recorded
one prefetch-related underrun, so uninterrupted playback remains an open gate.
The actual progress-bar before/after recheck passed
(`out/b07-bundle-progress-device.json`). Broader rapid-selection and
interruption qualification remains bounded by the corresponding receipts.

Startup follow-up: nibble CRC processing and retained STT1 diagnostics are
implemented and locally validated. BTT1 also has measured persistent device
timelines, summarized below. Host correctness checks and measured startup
latency are separate evidence; the skipped clock-boost attempt is not a pass.

Historical OS `67d33bb353f15` was confirmed in slotB on attempt45: health31,
no pending candidate, no crash, valid settings CRC and1200mAh retained.
Prior OS `a3ab32d9e985` remains in slotA. Receipt:
`out/b07-physical-music-persistent-health.json`.


### Bundled fixes requested before the next device test

The first refreshed-library boot exposed native parser error-2: compressed
records were still required to have zero sample counts. The library itself
passed hash verification. Removing that legacy requirement passes native
verification of both old/new databases and all30 records, plus eight malformed
record rejections. The correction is included in the current compatible
baseline; the earlier OS67d rejection is historical. Broader physical music
acceptance remains open.

The bundle adds nibble CRC processing to Boot/OS validation and photo metadata,
and more PCM before next-track I/O admission. Ordinary background admission
remains750ms; the next decoder requires1250ms, capped below ring capacity.
Detailed startup timestamps are implemented as development diagnostics.
Later integrated receipts establish bounded audio passes; they do not close
sustained playback or release qualification. The next combined timeline, layout
and video bundle requires fresh coherent builds and device qualification.


Parallel TODO follow-up adds exact forward/equal AAC decoder reuse. Native
M4A/ADTS whole-stream and repeated-seek PCM comparisons passed; a late M4A
forward seek fell from2815 to750 decode calls. Initial/backward seeks still
restart and retain their latency limitation. Photos now fetch each photo's
contiguous level descriptors once: nine sample photos required9 reads versus19,
with identical decoded descriptors and corruption/cancellation checks passed.

Video review found no justified service-only microfix: record reads reached
285.976ms while individual decode/CRC stages were roughly14-16ms. Next bounded
measurement compares identical reads with presentation inactive before IPVF
integration. The full-effects audit isolates a short active-playback interval:
42,286DSPframes/s versus44,100required; decode took1.346s and DSP0.359s over
2.016s. Keep the gate open and compare matched steady-state profiles on hardware.
Receipts: out/b07-aac-forward-seek-validation.json,
out/b07-photo-level-coalescing-host.json,
out/b07-video-next-measurement.json, out/b07-full-effects-followup-audit.json.

### Current compatible baseline and next combined batch

OS `8e7eb8bd29c374b78774095fb491897e2291ab1606b38467d4cd129eaa70ac5f`
was confirmed in slotA on attempt46, with healthy status, all30 library tracks,
valid settings CRC and no crash (`out/b07-compatible-baseline-health.json`).
This remains a compatible historical baseline; the newer attempt50 is below.
A fallback OS must
accept nonzero compressed sample counts in the current PDB; boot health alone
does not establish compatibility with the updated library.

Five distinct theme layouts are implemented with visual QA in progress. Theme
sidecars remain optional, and old shared settings must stay readable. The first
combined layout build exposed a development resident-memory overrun and an RTC
division link dependency; both were repaired and subsequent four-build matrices
passed. The throughput matrix and independent memory review at that checkpoint are below.

The video v2 alignment fix and host-side optimizations pass local validation
and builds. Video v2 has since been published and measured in bounded native
playback; underrun and throughput/A/V gates remain open (checkpoint below). The bounded ALAC-to-AIFF
automatic join now passes as described above; broad mixed-codec and effects
qualification remains open.

Historical persistent startup measurements distinguish these native pairs:

- Boot `b7c9c6655157` / OS `f384eb5cb156`: first frame at 86.492944 seconds
  (`out/b07-native-startup-timeline-device.json`).
- SHA/FAT pair Boot `05d688fe1130` / OS `bc38da716f8f`: first frame at 65.531741 seconds
  (`out/b07-storage-speed-native-timeline-device.json`).
- Boot `f13358d5bc9c` / OS `75fb30e5a6c6`: first frame at 67.816887 seconds.
  Clock boost was skipped, so this is not successful boost qualification.
  OS75fb was healthy and confirmed in slotB on attempt49, with all30 library
  tracks, valid settings CRC and no crash
  (`out/b07-clock-native-timeline-device.json`).

The throughput development/release OS/Boot matrix passes with the same frozen
451 source files (`out/b07-throughput-build-validation.json`). Independent
map review found no overlaps: development OS `f5ab33c7ec3f` has25,304 bytes of
resident headroom and release OS has293,784 bytes; audio IRAM uses1,024 of8,192
bytes (`out/b07-throughput-memory-audit.json`). These are host build/memory
checks. The f5ab RAM health check also passed
(`out/b07-throughput-ram-health.json`); later c714 native and bounded media
results below supersede that checkpoint without closing every media gate.

The attempt50 native Boot `6c5c48a291cc` / OS `c714ee95d2af` pair has BTT3 first frame at
62.566561 seconds and confirmation at66.004285 seconds. It is confirmed in
slotA on attempt50 with health31, all30 library tracks, valid settings CRC and
no crash (`out/b07-boot-reason-native-timeline-device.json`). The clock boost
was skipped because the USB clock was disabled; this recorded reason explains
the skip and is not a successful boost measurement.

The earlier Windows helper UAC request was canceled with error1223. A later
24-hour helper started at 22:31:10 UTC on September 7 for the Boot6c5c plan
(`out/b07-boot-reason-helper-started.json`). Video v2 publication and bounded
device measurements are recorded below; sustained qualification remains open.

Earlier host diagnostics and acceptance audits remain in
`out/b07-boot-timeline-host.json`, `out/b07-next-acceptance-audit.json` and the
map receipts. Physical full-power-cycle, release journey and the explicitly
open playback gates remain separate from the successful native restart evidence.



### September 7 publication and RAM checkpoint

Video v2 was published with verified SHA-256
`e68412f2601aa03aef1b68ea8ea36b65c9f6f3ff1dfd88da2fed2644ce1bb80b`
(`out/b07-video-v2-published.json`). On native OSc714, bounded normal
presentation produced 51 frames and 47 underruns; presentation suppressed
produced 56 frames and 32 underruns (`out/b07-video-v2-baseline-analysis.json`).
Both measurements leave the video performance gate failed/open. Post-eject
native health reached attempt51, confirmed slotA, no crash and valid settings
CRC (`out/b07-video-v2-post-eject-inspection.json`).

The span/boost matrix verifies development/release OS and Boot over the same
451 frozen source files (`out/b07-span-boost-build-validation.json`). OS
`8b9a9591c67b` then passed RAM health31 with all30 library tracks, valid settings
CRC and no crash (`out/b07-span-boost-ram-health.json`). Boot `f4dd30c5a8a9`
was built and its native plan validated, but had not been installed at this
checkpoint. Installed native Boot6c5c/OSc714 and the RAM-launched OS are separate
identities; RAM health does not establish persistent startup qualification.

Both optional THEME sidecars were provisioned
(`out/b07-theme-sidecars-provisioned.json`). Blueprint selection6 survived the
8b9 RAM reload and default selection0 was restored
(`out/b07-theme-persistence-ram-verified.json`). Native-reboot persistence remains
pending. The helper start above records a finite24-hour session; it does not
establish continued availability beyond that session.


### Earlier AAC/CRC/UI native checkpoint - September 7, 2026

Native Boot `331b69f8378b` installation passed full readback; persistent OS
`4d8301cb1617` was healthy and confirmed on attempt58 with no crash. First frame
was 11.278308 seconds from Boot C entry and confirmation 13.720126 seconds,
versus the prior
15.266548/17.759715 seconds. These are bounded observations, not full-power-cycle
or release qualification (`out/b07-aac-crc-ui-persistent-device.json`).
Development/release Boot and OS builds passed over 452 frozen source files
(`out/b07-aac-crc-ui-build-validation.json`).

Warm fixed-min6 video runs improved from 59 to 62 frames with normal presentation and from
67 to 69 with LCD presentation suppressed; silence decreased by 4,096 samples
in both modes. Sustained playback still fails. These combined changes do not
isolate UI, CRC or ATA gains (`out/b07-aac-crc-ui-video-analysis.json`).
The Home screenshot passed visual review. The lower-cost runtime observer
failed its hardware overhead comparison: 60 versus 62 frames with normal
presentation, and 67 versus 69 with LCD presentation suppressed. The observer
was exactly rolled back (`out/b07-rta-lowcost-video-device.json`,
`out/b07-runtime-attribution-lowcost-rollback.json`); attribution remains open.

Mixed-codec/effects playback, broader UI interaction, startup timing, physical
full-power-cycle and release acceptance gates remain open as listed above.


### Earlier render/copy checkpoint - September 7, 2026

- [x] Implement opaque video render coverage and paired scanout copying.
  Development and release OS builds pass on the frozen source set
  (`out/b07-video-render-copy-promotion.json`,
  `out/b07-video-render-copy-build-validation.json`).
- [x] Verify native persistent OS `fbed17427f4d`: attempt61 returned healthy31
  with no crash (`out/b07-video-render-copy-persistent-device.json`).
- [x] Measure the bounded render/copy improvement: normal-presentation frame
  count rose from 62 to 65, mean rendering time fell 25.94%, and mean publication
  time fell 39.61% (`out/b07-video-render-copy-comparison.json`). These fixed
  eight-second probes include the repeated intro and measure frame acceptance,
  not LCD completion or steady-state frame rate.
- [ ] Pass sustained video playback. The eight-second probe still recorded
  47 underruns and 254,976 silence samples (`out/b07-video-render-copy-device.json`).
  A/V, seek/exit, corruption and physical qualification gates remain open.
- [x] Host-validate and publish the HC video candidate
  (`out/b07-video-hc-publication.json`).
- [x] Complete the bounded HC A/B comparison on native OS `fbed17427f4d`.
  Fixed eight-second normal-presentation runs reached 66 versus 65 frames;
  silence fell from 254,976 to 251,904 samples, but underruns rose from 47 to 48.
  With LCD presentation suppressed, frames rose from 70 to 71 and silence fell
  from 245,760 to 241,664 samples, while underruns rose from 44 to 46.
  No errors, audio faults or crash were observed. Normal-run peak decode time
  fell from 32.23 to 29.20 ms; this is not a mean timing or steady-state fps claim
  (`out/b07-video-hc-comparison.json`, `out/b07-video-hc-device.json`).
  HC remains installed; the production host video compiler is unchanged.
  Sustained video remains failed/open despite the completed bounded comparison.
  Temporal compression and COP scheduling research remain staged only
  (`out/b07-video-online-research/temporal-summary.json`,
  `out/b07-video-online-research/cop-scheduling-assessment.md`).
- [x] Integrate the five staged photo changes: JPEG coordinate mapping,
  slideshow dwell after render completion, tile-padding checks, metadata
  fragment traversal and host photo packing. B08-A hardware verified the
  nine-photo library in 1.562 seconds with zero errors; first-photo and rapid
  next/previous navigation also passed. Visible dwell, concurrent audio and
  broader cold/JPEG timing remain open. Evidence is under
  `out/photo-todo-agent/manifest.json`, `out/photo-todo-agent/padding/manifest.json`,
  `out/photo-todo-agent/metadata/manifest.json` and
  `out/photo-todo-agent/host-packing/manifest.json`, with device evidence in
  `out/b08-a-photo-device.json`.
- [x] Combine, integrate and verify strict UI configuration, integer font range
  fields and per-compilation packed-font reuse. Compiler `b136696d` is promoted;
  default/demo generated outputs match and dev/release builds pass
  (`out/apps-todo-agent/compiler-combined/manifest.json`,
  `out/b07-ui-host-queue-build-validation.json`).

### Latest integration and handoff - September 8, 2026

- [x] Integrate the combined UI fill, blend and image-copy optimizations (`a3ba96cf`).
  OS dev `3d2618dc4721` and release `398284fb80a8` build and memory checks pass.
  Dev headroom is 12,184 bytes, with no added static RAM
  (`out/b07-ui-host-queue-memory-audit.json`).
- [x] Publish OS `3d2618dc4721` persistently and verify native generation1,
  attempt63, health31 and no crash (`out/b07-ui-host-queue-persistent-device.json`).
- [x] Measure the same HC asset on the new OS: normal probe 67 versus 66 frames,
  mean render 8.65 versus 12.46 ms (30.57% lower). These are bounded eight-second
  observations, not sustained fps; 45 underruns and 249,856 silence frames remain
  (`out/b07-ui-host-queue-video-comparison.json`).
- [x] Verify populated queue titles persist across pause/resume and stale actions
  are rejected on the device; no crash (`out/b07-ui-host-queue-controls-device.json`).
  Initial screenshot was taken before titles loaded and is explicitly excluded
  from retention evidence. Broader transition qualification remains open.
- [x] Qualify and install the alignment-aware HC asset `c7685daa`. Matched
  eight-second probes were unchanged at 67 normal and 71 no-LCD frames, with
  identical underrun and silence counts; peak decode fell about 0.7%, too little
  for a meaningful throughput claim (`out/b08-aligned-video-comparison.json`).
- [x] Measure exact frame-zero completion on OS `3d2618dc4721` with aligned HC:
  all 288 frames and 576,000 samples completed in 48.407 seconds with no error,
  audio fault, crash or COP reset. The 12-second clip incurred 265 underruns and
  1,740,800 silence frames, confirming a severe sustained producer deficit
  (`out/b08-frame-zero-full-video-device.json`).
- [x] Prototype and measure a bounded video-owned storage service path that
  avoids recursively running the full UI/runtime callback during read progress,
  while retaining audio, watchdog, USB, power, input and cancellation service.
  Full-run counters recorded 31,421 nested runtime callbacks and 16.599 seconds
  of inclusive callback time; spans overlap and are not additive CPU attribution.
  The B08-B composite passed native storage/video checks, coherent dev/release
  builds and hardware playback. Normal/no-LCD eight-second runs reached 69/73
  frames, and the complete frame-zero clip presented 288/288 frames and consumed
  all 576,000 PCM samples with no storage or media fault. Completion improved
  from 48.407 to 46.375 seconds and silence fell by 106,496 frames, while 264
  underruns keep sustained throughput open. See `out/b08-video-astra-consultation.md`,
  `out/b08-video-storage-service` and `out/b08-b-frame-zero-full-video-device.json`.
- [ ] Complete temporal PVID3 validation before promotion. Malformed data, CRC,
  version/type, dependency/index, cancellation and seek checks now pass, as do
  ARM object and temporary link gates (+432 dev / +500 release bytes). A full
  production build and bounded hardware qualification remain open; see
  `out/b07-video-temporal-prototype/temporal-qualification-receipt.json`.
- [x] Integrate B08-A: five photo fixes, provider-kind gate, source-directory
  pruning and audio prefetch cancellation. Dev `7adcbfa247b0` and release
  `083b056e5a99` pass exact source, artifact, release-exclusion and memory audits;
  linked growth is 344 text bytes with no data/BSS/stack/IRAM growth. Hardware
  photo, rapid Next/Previous audio and bounded video regression checks passed.
  B08-A is confirmed persistently with health31 and no crash
  (`out/b08-a-build-audit/manifest.json`, `out/b08-a-photo-device.json`,
  `out/b08-a-audio-device-v2.json`, `out/b08-a-video-device.json`,
  `out/b08-a-persistent-device-final.json`). Aligned SHA remains staged.
- [x] Build and RAM-qualify B08-B with the scoped video-owned storage poll and
  paused-video idle deadline. Dev `3c80fcc0434b` and release `50c7867d9f40`
  passed with +316/+304 linked text bytes respectively versus B08-A and no
  data, BSS, stack or audio-IRAM growth. Normal/no-LCD video, a complete
  frame-zero clip, pause/resume, paused seek and clean stop all passed without
  a crash. B08-B is confirmed persistently in slot 1 with generation 1,
  health31, no pending candidate and empty crash data
  (`out/b08-b-persistent-device.json`). Evidence also includes
  `out/b08-b-video-normal-device.json`,
  `out/b08-b-video-nolcd-device.json`,
  `out/b08-b-video-paused-qualification-v2.json`,
  `out/b08-b-frame-zero-full-video-device.json`). The independent audit reports
  PASS WITH LIMITATIONS and no binary or device safety blocker; its disclosures
  preserve the post-build documentation drift and aggressive-seek underrun
  (`out/b08-b-independent-audit/receipt.json`).

Luna Max agents resumed bounded validation and staging work at the user's request.
Research artifacts are not completed product features; sustained video,
physical checks and the Notes application remain open.

Physical full-power-cycle, battery, release journey and broader media acceptance
remain open. Completed host checks and native restart observations do not close them.


## Notes application

- [ ] Implement a functional Notes application with note browsing, editing and
  durable storage. `local.example.notes` currently contains only the SDK UI Demo;
  it has no note editing or storage. Consumer Home/Extras hide the demo by default.
  Explicit `[features] demo = true` exposes the component example while preserving
  its existing scene ID and canvas API.
  A Notes format/compiler prototype is staged under
  `out/apps-todo-agent/notes-format/INTEGRATION.md`; native browsing, editing,
  persistence integration and device acceptance remain pending.

## Code audit - September 7, 2026

The checked items below are implemented; original findings are retained for context. The two host
correctness issues were reproduced with temporary local inputs. Firmware
findings follow from source inspection; performance gains remain unmeasured.
These items supplement the existing qualification gates and their evidence.
P2 means normal-priority corrective work; P3 is lower-priority host cleanup.
Use existing checks and focused manual verification, without new test infrastructure.
References identify the audited source lines.

### Correctness and cancellation

- [x] **AUD-01 / P2 - Preserve a valid music stage after a failed reimport.**
  `tools/content/music.py:342` replaces stable media files before all sources
  validate; database validation/replacement follows at `:422-425`.
  Reproduced: import a WAV, change it, add a later invalid WAV, and reimport.
  The failure leaves the old database referencing overwritten media;
  `validate_stage` reports `staged media hash mismatch`.
  Prepare and validate the complete replacement stage separately, then publish
  with recoverable replacement of media, artwork, database and manifest.
  Verify successful reimport and preservation of the previous stage after failure.

- [x] **AUD-02 / P2 - Hash selected system configuration contents.**
  `tools/studio/build.py:39-48,63-64,101` excludes `out` from source hashing
  but includes only the override path in configuration identity.
  `tools/content/compiler.py:24-28,75` accepts configuration beneath `out`.
  Reproduced: editing those configuration bytes leaves `source_identity`
  unchanged, although the compiler can consume different settings.
  Hash the selected configuration and any other excluded compiler inputs before
  emitting firmware. Verify changed effective inputs change the build ID and
  identical inputs retain it.

- [x] **AUD-03 / P2 - Start slideshow dwell when the image is ready.**
  `services/photos/photos.c:177,184` starts the five-second timer before loading;
  `:238` advances when a frame becomes valid after the deadline. A slow image
  can therefore disappear immediately after rendering.
  Arm dwell once per image at render/JPEG completion (`:149,292`), handling
  slideshow enable on an already loaded image. Verify delayed uncached loads,
  JPEG fallback and cached transitions each receive the full dwell interval.

- [x] **AUD-04 / P2 - Stop canceled media work after draining owned I/O.**
  Implemented in B11 and included in local commit e1c458c. Completed block
  results are consumed before cancel; real errors retain quarantine. Focused
  host checks and linked builds passed. Device cancellation qualification remains
  in the B11/B12 qualification gate below. Original finding follows.
  `services/storage/storage.c:297` only sets a flag; `:271-290` continues the
  whole operation before returning stale. A first read can include full FAT
  chain verification (`services/storage/fat32.c:429`). Superseded media retains
  the shared lock and continues reads during navigation/replacement playback.
  Add safe read/open cancellation that drains the current block request,
  discards incomplete proof state and releases ownership before more sectors.
  Preserve buffer lifetime and distinguish cancellation from corruption.
  Verify cancellation during lookup, chain verification and multi-sector reads,
  no late buffer writes, and successful reads by the next owner.

### Firmware CPU, I/O and responsiveness

- [x] **AUD-05 / P2 - Idle the CPU during storage hardware waits.**
  Sol delivered diagnostics only under `out/sol-storage-schedule-diagnostics`;
  no scheduler-policy change is integrated. Review, build and measurement remain.
  `kernel/runtime.c:823-826` obtains a storage deadline but returns whenever
  storage is busy. `hal/pp5020/ata.c:355` already exposes hardware wait deadlines.
  Mount/reset/pending read waits can keep the cooperative loop running.
  Distinguish runnable FAT transitions from waiting block I/O and allow timed
  idle for the latter, preserving audio/input/watchdog deadlines. Do not simply
  remove the busy guard. Verify cached immediate progress, delayed ATA states,
  cancellation and timeouts; compare CPU idle time and worst service latency.

- [x] **AUD-06 / P2 - Let fully buffered paused video become quiescent.**
  `services/video/video.c:544-547` requests a wake in 1 ms when INDEX has no
  free frame slot, including after paused buffering fills all slots.
  `kernel/runtime.c:809` propagates the deadline although consumption awaits input.
  Use an idle deadline when paused without runnable work; continue pending I/O,
  cancellation and requested seek preparation. Verify reduced wake counts and
  prompt resume/seek/stop. Measure power separately from active-video throughput.
  B08-B reduced settled timer service from the saved baseline's 638.2 to 11.8
  iterations/second (98.15%) over a ten-second bracket with unchanged paused
  video, PCM, render and read counters. Three pause/resume cycles responded in
  16-31 ms, six paused seeks settled in 219-625 ms, stop completed in 94 ms,
  and crash storage remained empty. Direct current metering remains part of the
  broader physical power gate (`out/b08-b-video-paused-qualification-v2.json`).

- [x] **AUD-07 / P2 - Remove avoidable JPEG software division per pixel.**
  `services/photos/jpeg.c:7-8,159-168` runs a 32-iteration divider for output x
  and two chroma coordinates per color pixel. The chroma divisors are 1 or 2
  (`:78-84`) and can use shifts. At 220 x 156 pixels, those two divisions alone
  account for 2,196,480 divider-loop iterations.
  Reuse bounded scaling coordinate mappings and simplify restricted block
  division at `:137`, respecting resident-memory limits. Verify exact RGB565
  output across supported subsampling/orientations, then measure native decode
  time. This gives the existing photo-speed gate a concrete CPU optimization.

- [x] **AUD-08 / P2 - Scan free FAT entries in bounded sector batches.**
  Implemented in B11 and included in local commit e1c458c. Final-source host
  checks confirm at most 128 entries per scan poll and mirror/error quarantine;
  linked dev/release builds pass. Device mutation qualification remains open.
  Original finding follows.
  `services/storage/fat32.c:575` restarts allocation at cluster 2; `:599-604`
  calls `edit_fat` per occupied entry. `:256-262` submits mirrored reads and
  compares the whole sector again, up to 128 times per occupied sector.
  Block caching avoids some disk reads but leaves submissions/copies/comparisons.
  Scan one validated mirrored sector in bounded batches and retain a validated
  allocation hint within the mount. Preserve mirror checks and mutation/flush
  ordering. Compare request/poll counts for occupied prefixes and fragmented
  space, and run existing mutation fault checks.

- [x] **AUD-09 / P2 - Bound battery/RTC work per runtime tick.**
  B12 preserves ADC/RTC phase age across cancellation and spaces failed codec
  volume retries by 100 ms. Root reran actual-C power (15 scenarios) and
  controller deadline checks; sequential dev/release builds and normal device
  playback passed. One transfer attempt per sampler poll retains a worst bound
  of 10 ms plus fixed work. Physical bus-failure and direct current measurement
  remain separate open qualification; invalid readings are explicit fault outcomes.
  Receipts: `out/b12-integration-outcome.json`, `out/luna-power-revision/`.

- [x] **AUD-10 / P2 - Separate queue label invalidation from settings revisions.**
  Implemented in queue_view `78330b5d`, preserving title mappings and pending
  lookups while invalidating structural changes and stale actions. Existing
  28 focused native checks pass; query count fell 220 to 171. Dev/release builds
  and device pause/resume title retention plus stale-action rejection pass
  (`out/audio-next-queue-audit/validation.json`,
  `out/b07-ui-host-queue-controls-device.json`).
- [ ] Broaden native queue transition qualification: automatic cursor advance,
  structural reorder/remove/shuffle and library replacement under pending reads.

### Host cleanup

- [x] **AUD-11 / P3 - Prune excluded directories before build enumeration.**
  `tools/studio/build.py:41-42` enumerates/sorts the entire tree and calls
  `is_file()` before rejecting output, Git, virtualenv and cache paths.
  The bounded audit counted 22,682 paths, with 22,137 (97.6%) excluded;
  enumeration/sorting took approximately 0.254 seconds in this workspace.
  Prune directories during traversal and sort only included inputs, preserving
  deterministic hash order. Verify identical IDs on a frozen tree and compare
  enumeration/stat work with populated output. This is a modest host improvement.


## B09 autonomous continuation - September 8, 2026

- [x] AUD-03/AUD-07 match already integrated source and prior 256 JPEG/nine
  slideshow checks (out/b09-jpeg/integration-audit.json). JPEG device speed and
  fallback qualification remain open.
- [x] AUD-01: validate a complete replacement music stage before publication,
  roll back failed directory publication and retain recoverable previous stage.
  Eight checks pass (out/b09-music-stage/validation.json). Concurrent imports
  remain unsupported; replacement requires temporary disk space.
- [x] AUD-02/AUD-11: include compiler content identity in firmware identity and
  prune build enumeration. Seven checks pass, including changed excluded config
  and deterministic hash parity (out/b09-build-identity/validation.json).
- [x] PHT5 v2 readiness/timing diagnostics: dev/release builds, native simulator
  and five protocol checks pass. RAM OS618dd8b45a9e is healthy, crash empty,
  storage/update clean. Persistent rollback remains B08-B.
- [x] Landscape ready in 475470 us; Portrait in 332255 us; render intervals
  63822/53834 us. Portrait dwell armed 5000002 us after render readiness.
  Receipt out/b09-photo-device-v2.json. The earlier b09-photo-device.json
  selected an empty album and is not image-loading evidence. First screenshot
  also waited for LCD completion; physical LCD dwell remains separate.
- [x] Qualify the 64-byte tile lookup hint cache and per-row affine rotation
  calculation. Landscape render time fell 63850 to 40352.5 us (36.80%);
  Portrait fell 53822 to 25423.3 us (52.76%). All four rotations, zoom, pan and
  flat-view pixels match exactly. Cached-photo playback added zero underruns,
  silence or faults while consuming 90112 frames. Five-second slideshow dwell
  and pause/resume also pass (out/b09-photo-render/affine-device.json,
  out/b09-photo-render/comparison.json). These are render interval improvements,
  not equivalent cold-load gains; metadata/read/audio-admission gates remain open.
- [x] Freeze and reconcile 454 source inputs; sequential dev/release builds,
  artifact integrity, generated content and release exclusion pass. Resident
  headroom is 10592 bytes dev / 280536 bytes release; versus B08-B resident
  usage grows 920 / 224 bytes respectively. See out/b09-affine-independent-audit.json.
- [x] Return to exact B08-B, inspect clean state, publish once, restart and
  confirm persistent B09 in slot A, retaining B08-B in slot B. Build
  98a95bd0028ce2b18b417e50d6be030603fbdd73b47c40f56fe992b640cbe3b7,
  image SHA256 209369339cc23e2e91abc548ed991ca5c9b8a6576395c16f980191bc43b0f270.
  Generation1, health31, candidate255, pending0, clean storage and empty crash;
  Home with audio/video idle. Receipts out/b09-persistent-preflight.json,
  out/b09-persistent-install.json and out/b09-persistent-device.json.
- [ ] Next video batch: integrate PVID3 semantics onto current production while
  preserving paused-quiescence and recent I/O fixes, then compare matched v2/v3
  assets on hardware. Prototype saves 22.92% sample bytes but retains the same
  maximum record size; inverse/CRC CPU work and PCM-after-video preparation
  still need measurement. Research: out/b09-next-video-assessment.md. This is
  planned work, not a qualified video/audio fix.

Completed physical button/wheel/Hold/photo/listening/battery operation/shutdown/
USB return checks remain accepted. Sustained video, concurrent cold photos/audio,
low-battery thresholds and release journeys retain their existing open gates.


## B10 temporal video - staged; hardware performance rejected

- [x] Stage rebased strict PVID3/type5 support onto current video code, preserving B08
  paused and storage polling behavior and B09 photo fixes.
- [x] Qualify current native pipeline, old/new host inspection, malformed data,
  inverse cancellation and seek/preroll; prepare matched aligned v2/v3 assets.
- [ ] Freeze source, build dev/release sequentially, reconcile independently,
  RAM test legacy playback, publish the backed-up asset using the live helper,
  and measure temporal throughput/control/audio behavior before promotion.
- [x] Recheck B09 persistent identity/health and active unpoisoned refresh helper.
  Matched eight-second current-asset baseline:69 frames,46 underruns,245760
  silence frames, zero fault (out/b10-baseline-video.json). This reproduces
  B08-B's performance and keeps the real-time video gate open.

The interrupted fair-media candidate remains rejected as-is; reviewed scope
and scheduling concerns are recorded in out/b09-photo-review.md. No fairness
or ATA timing changes are combined with B10.


### Managed Sol Medium work

Coordinator owns source promotion/builds/device. Workers stage isolated copies
and report here; no shared source or device mutations are delegated.
- AUD-04: task01a07f3e-4466-7852-8e26-2dcb7cd0d6ed,
  out/sol-media-cancellation; next read-only AUD-05 deadline analysis.
- AUD-09: task01a07f3e-4872-76a2-b935-3baa7c5b11fb,
  out/sol-power-sampling; next startup-timing analysis.
- AUD-08: task01a07f3e-4d1c-7080-84ce-f4f49d95fa14,
  out/sol-fat-allocation; next cold media proof-cost analysis.

Assignment/status record: out/sol-task-coordination.json. All use gpt-5.6-sol
with medium reasoning. Candidate receipts do not close hardware gates.


### B10 outcome and continuing assignments

- [x] Sequential dev/release builds, frozen-source identity/integrity and release
  exclusion pass (out/b10-build-reconciliation.json). Independent source review
  has no blocking findings (out/b10-independent-source-review.json). Candidate
  dev8ef75f0728cb / release4a1a987b0262, headroom10136/280048 bytes.
- [x] Legacy v2 on new firmware matches baseline69frames/46underruns/245760
  silence. Matched v3 saves22.92% bytes, reconstructs all frames/PCM exactly on
  host/native and reaches72frames/49underruns/239616silence on device. NoLCD
  reaches77frames/52underruns/229376silence. No media faults, but real-time
  playback FAILS; no persistent B10 promotion. Receipts out/b10-legacy-video-device.json,
  out/b10-temporal-video-device.json and out/b10-temporal-controls-device.json.
- [x] Paused seeks respond in219-610ms; pause/resume/stop checks pass. Native
  seek/preroll and inverse/read cancellation pass. The attempted device full run
  did not start because frame-zero normalization missed its expected state;
  no full-clip timing claim (out/b10-temporal-full-device.json). Investigate
  early paused-seek normalization separately before broad acceptance.
- [x] Restore exact aligned v2 assetc7685daabeed and production video.c/host
  video.py baselines; keep candidate sources in out/b10-freeze. Persistent B09
  remains health31, generation1, candidate255/pending0, no crash, Home/media idle
  (out/b10-video-restored.json, out/b10-source-restored.json,
  out/b10-restored-device.json). PVID3 specification remains staged only.
- [ ] Repair host post-eject readiness check: twice early HELLO timed out after
  verified refresh; fresh read-only reconnect confirmed healthy B09. Never replay
  refresh/eject. Receipts out/disk-restart-57008142bbc0487a810e8c9780c86eff.json,
  out/disk-restart-d9a0fbcd4da5497cace608a7eed3431e.json and corresponding
  b10-post-eject-identity/b10-restored-identity. Assigned as power-task follow-on.
- Video throughput task01a07f49-9f6b-7330-8ddb-aba2f0fc0066, Sol Medium,
  stages under out/sol-video-throughput using these measured results.

All four Sol Medium tasks are instructed to report candidates and blockers to
this coordinator, retain exact baselines/patches/receipts, and proceed to assigned
follow-up work. Root reviews/integrates and alone performs builds/device actions.

### Sol Medium coordination review (2026-09-08)

- [ ] AUD-08: sector-batched allocation candidate received. Worker reports 510 to 6 callbacks for a 254-entry occupied prefix, +772 bytes ARM text and unchanged context/BSS. Combined review with AUD-04 cancellation assigned; independent integration, linked headroom and device gates remain open. Receipts: `out/sol-fat-allocation/manifest.json`.
- [ ] AUD-09: first power sampler candidate returned for revision. Require aggregate ADC/RTC age bounds across scheduling gaps and prevent repeated foreground I2C cancellation from indefinitely postponing sampling. No production integration approved. Next assignment remains host post-eject read-only readiness recovery.
- [ ] Video: staged inverse/CRC locality experiment continues with reconstructed-frame CRC required before PCM publication. Measurement and corruption/cancellation checks remain pending.

B09 remains the installed baseline. Task assignments and review state: `out/sol-task-coordination.json`.

- [x] Integrate host post-eject readiness retries constrained to the exact USB serial. Refresh/eject remain single operations outside the read-only discovery/open/HELLO retry loop. Production matches the validated candidate and parses; hardware qualification is pending the next batch. Receipt: `out/sol-power-sampling/host-integration-review.json`. The 20s retry budget can be exceeded by an in-flight HELLO.
- [ ] AUD-09 v2 received: aggregate ADC 100ms and RTC 60ms expiry plus prompt restart after foreground cancellation. Staged ARM checks pass (+1240 text/+20 BSS); linked and device gates remain open. Worker continues startup CRC provenance audit.

- [ ] AUD-04 review found that block cancel relabels untaken completed failures as CANCELED. V1 is superseded and must not be integrated. V2 must consume completed results before canceling active requests, retaining IO quarantine for failures and normal stale retirement for completed success. Allocation integration task notified to await v2; production remains unchanged.

- [ ] Temporal video inverse/CRC candidate passed exact 288-frame/576000-PCM host checks, corruption gate, seek and cancellation checks. ARM text +348, BSS unchanged, step stack +16. Host timing gains do not establish device throughput. Candidate remains staged on B10 only; B09 production per-record diagnostics assigned next. Receipts: `out/sol-video-throughput/validation.json`.

- [ ] Stage initial development chainload reuse of the just-validated payload CRC after provenance audit. Warm command32 full current-byte CRC remains required. Historical redundant scan was 1.043s; actual savings remain unmeasured. Power task assigned isolated implementation and mismatch/invalidation checks under `out/sol-startup-crc`; no device or production change approved by this entry. Audit: `out/sol-power-sampling/startup-crc-provenance-audit.md`.

- [ ] AUD-04 v2 frozen at `out/sol-media-cancellation-v2`. Root verified patch hash and strict apply check and reviewed take-before-cancel ordering. Combined allocation validation resumed. Reported +636/+640 dev/release text, zero data/BSS growth; linked and device gates remain open. AUD-05 diagnostics work resumes separately.

### B11 integrated candidate (2026-09-08)

- [ ] Root integrated frozen AUD-04 v2 + AUD-08 combined patch and AUD-09 v2 power sampler. Host post-eject readiness fix is included in source identity. Development/release builds and device qualification pending; B09 still installed.
- Startup CRC reuse, scheduler diagnostics, and temporal video optimization remain separate staged work and are excluded from B11.

- [x] B11 sequential dev/release verified builds pass with matching frozen identities and no source drift. Development headroom 8128 bytes; release 278072. Release exclusion passed. Receipt: `out/b11-build-reconciliation.json`.
- [x] B11 initial RAM boot and bounded MP3 check: build f6d2616df6b3, generation2, health31; 535552 consumed frames during steady observation, zero underruns/silence/audio faults. Post-stop storage prepared, pending0/error0/quarantine0, crash empty. Receipts: `out/b11-ram-playback-device.json`, `out/b11-post-playback-drained.json`.
- [ ] B11 cancellation/mutation and broader peripheral qualification remain open; no persistent promotion. B09 stays installed. The old deleted host harnesses cannot be rerun as an integrated corpus; inherited assertion counts are historical, with fresh final-source checks being prepared by the allocation task.

### Delegation and priority change (2026-09-08)

User paused video todo work. Existing Sol tasks finish only their current non-video assignments and then stop; video task instructed to preserve/report current state and stop. No new Sol assignments.

Luna Max subagents now own bounded staged work: native queue transition qualification (`out/luna-queue`), measured photo metadata/catalog optimization (`out/luna-photo`), and independent B11 power/cancellation/allocation review (`out/luna-b11-review`). Root verifies evidence and integrates; all device work stays with root. Video candidates remain deferred.

- Sol allocation task finished: root verified final report/validation hashes. Thirty fresh final-source assertions pass; CPU scan bound128 entries plus separate512-byte mirror comparison. Historical deleted harness counts were not rerun. Device mutation/cancellation qualification remains open. Receipt: `out/sol-fat-allocation/corpus-review/validation.json`.
- Sol video task stopped per user. Staged artifacts preserved; host decoder is incomplete/unvalidated and diagnostics package has unfinished documentation/manifest. Do not integrate these deferred video candidates.

- [x] Bounded native queue transition qualification: Luna Max linked actual queue/queue-view sources to asynchronous library mock; 64 assertions pass for cursor advance, reorder/remove/shuffle, stale actions and library replacement with pending reads. Root independently reran successfully. This does not qualify actual controller/library I/O, device gaplessness or listening. Receipt: `out/luna-queue/validation.json`.
- [ ] Luna queue worker next investigates exact AAC seek performance; photo and independent B11 reviews continue. All candidate edits remain staged until root verification.

Sol assignments are finished/stopped with final reports. AUD-05 schedule diagnostics and startup CRC reuse are frozen under `out/sol-storage-schedule-diagnostics` and `out/sol-startup-crc`; both remain unintegrated pending root review/full builds/device gates. No further Sol assignments. Initial local commit captures current B11 production and project baseline; generated/staged output excluded.

### B12 follow-through (non-video)

- [x] Root retrieved Luna photo/AAC/B11 review results and integrated the bounded photo tile-descriptor validation fast path. Existing descriptor validator, metadata CRC, split-record fallback and I/O ownership preserved. Host processing improvement is not a device loading-speed claim. Receipt: `out/luna-photo/root-integration-review.json`.
- [ ] Fix newly found B11 repeated foreground I2C cancellation starvation. Initial Luna patch needs stronger RTC restart review; `power_revision` owns actual-C adversarial validation and staged revision. Invalid/fault publication must not be described as a guarantee of valid low-battery readings when the bus is unavailable.
- [ ] Independently verify AAC skip-synthesis optimization before integration; `luna_b11_review` now reviews AAC under `out/luna-aac-review`.
- B11 device baseline exact AAC seeks 6/10/2/8s: 2.860/1.984/1.312/2.860s, all exact paused positions. Receipt: `out/b12-aac-baseline-device.json`.
- B11 first photo metadata readiness during MP3: 4.484s, zero underruns/silence/faults. Initial viewer check was invalid (frame_complete alone); corrected separate warm viewer check passes with frame_valid and frame_complete and inspected screenshot. Receipts: `out/b12-photo-baseline-device.json`, `out/b12-photo-baseline-warm-device.json`.

- B12 root integrated AAC intermediate synthesis-skip optimization after independent recurrence/PCM review and root full M4A rerun (552132 frames, exact SHA1c66fb2c...). Integrated power revision preserves ADC/RTC phase age across cancellation and restarts RTC without redoing ADC; failed volume application retries wait100ms, successful/direct volume remains immediate, resolved mismatch clears retry deadline. Root actual-C power harness passes15 scenarios; controller harness expectation corrections remain pending. Source frozen for sequential builds; no device qualification/promotion yet.

### B12 verified result

- [x] Integrate photo descriptor fast path, exact AAC seek optimization, phase-preserving sampler restart, and failed-volume retry backoff. Root reviewed source and reran actual-C power/controller and AAC fixtures. `out/b12-integration-outcome.json` records scope/limitations.
- [x] Sequential dev/release builds passed with no source drift and release exclusion passed. Dev build1219d6c50a3e, headroom7384; release0bba10ed7c9b, headroom277328. Receipt: `out/b12-build-reconciliation.json`.
- [x] B12 RAM health31/generation3. Four exact paused AAC seeks improved9.4-13.1% in one paired device run (2.500/1.797/1.140/2.516s at6/10/2/8s). Photo metadata readiness4.344s versus4.484s baseline during MP3, zero audio underruns/silence/faults; this single photo observation is not a statistically established speed gain. Viewer screenshot exact baseline match. `out/b12-device-comparison.json`.
- [x] Photo exit and subsequent MP3 owner passed cleanly; active pending I/O was not observed, so canceled-read hardware qualification remains open. `out/b12-photo-cancel-device.json`.
- [ ] B12 persistent promotion and broader mutation/cancellation/fault qualification remain open. B09 remains persistent. No new physical interaction requested.
- Startup CRC candidate: root found dropped short-payload/alignment checks and proof-consumption discrepancy; Luna delivered repaired staged package `out/sol-startup-review`. It remains excluded from B12 pending ARM/full builds/device proof. SCD1 diagnostics independent review continues; video remains paused.


### B12 storage campaign (2026-09-08)

- [x] Existing device storage campaign passed: 1 MiB full SHA readback, 256 seeded random reads, settings publication with exact restoration, WORK creation/growth to 16384 bytes preserving prior data and zero extension, and five injected fault/recovery modes. Final storage prepared, error0/quarantine0/pending0. Receipt: `out/runs/20260908T114616Z-photo4g-p98-1219d6c50a3e-0001/receipt.json`.
- [ ] Reset at every metadata publication stage and persistent crash rollback remain unqualified by this campaign; automated_passed does not mean complete hardware qualification.

- [x] B12 persistent installation and healthy boot passed in slot B; B09 retained in slot A. Post-install MP3 consumed353280 frames with zero underruns/silence/faults; storage clean and crash empty. `out/b12-persistent-identity.json`, `out/b12-persistent-playback.json`.
- [ ] Next non-video batch: current-source SCD1 diagnostic validation and measured 100000-track search optimization; repaired startup CRC candidate remains staged. Root integrates after review and checks linked development headroom (B12 has7384 bytes).


### B13 preparation (non-video)

- [ ] Root review found that the first search key-cache candidate incorrectly assumed a32-byte database prefix limit; the public API accepts255 bytes. Luna is repairing long-prefix fallback and checking repeated queries after intervening reads. Do not integrate the original candidate.
- [ ] SCD1 diagnostics need the saturation decoder correction and current FAT-source revalidation; scheduler policy remains unchanged until measurements support it.
- [ ] Final independent startup CRC proof review is assigned to Luna Max, including current-source ARM checks and warm-reboot CRC preservation. Repaired candidate remains staged.
- B12 idle/startup baseline captured in `out/b13-idle-baseline.json`; current persistent candidate CRC scan took1051905us for713468 payload bytes. This is a measured baseline, not an achieved startup saving.

- [x] B13 root integrated corrected SCD1 diagnostics after source/decoder review and current-source ARM checks. Scheduler behavior unchanged; linked build/device gates pending. Receipt: `out/b13-integration/scd1-root-review.json`.

- [x] B13 search cache integrated after root review/repair and independently rebuilt native harness:101016 checks plus matching/mismatching33/255-byte prefixes and long-title-to-short-title reuse pass. Direct repeated lookup saves2 reads; cold proof unchanged. Device75ms UI gate remains open. `out/b13-integration/search-root-review.json`.
- [ ] B13 source freeze contains SCD1 diagnostics and bounded search cache only; startup CRC remains staged. Sequential dev/release builds and RAM device qualification follow.

- [x] B13 verified dev/release builds and reconciliation pass; development headroom4872 bytes, release277056. RAM generation2 health31, MP3 zero underruns/silence/faults, SCD1 valid counters and250us completed cancellation span. Early post-stop check sampled preparation phase7; separate read-only followup confirmed phase6/prepared1, no crash. `out/b13-integration-outcome.json`.
- [x] B13 normal-library search UI: query five returned Five O'Clock500; repeated result screenshot byte-identical; selecting played correct title, screenshot inspected. Returned Home with clean storage. 100000-track75ms device display target remains open.
- [ ] B13 persistent promotion remains separate; B12 persistent retained. Next bounded Luna tasks: storage-idle policy safety, mixed-codec gapless transitions, final startup CRC proof review. Root verification required before integration.

- [x] Root independently rebuilt actual-player gapless harness for dev/release: same-rate PCM order/retirement, rate-change drain/reinit, pending next stop/retarget and terminal config mismatch pass. No source bug reproduced. Actual codec, queue/controller integration and hardware/listening remain open. `out/luna-gapless/root-review.json`.
- [ ] AUD-05 release-available storage-wait idle policy candidate received under `out/luna-storage-idle`; root source review begun, not integrated. Full builds and device before/after evidence required.

- [x] B14 root integrated AUD-05 after independent source/timer review and rebuilt actual-C block/runtime harnesses. Busy storage sleep restricted to pending hardware waits; runnable work veto preserved. Corrected timer/endpoint evidence. Full build/device gates pending. `out/luna-storage-idle/root-review.json`.

- [x] B14 AUD-05 linked dev/release builds and source reconciliation pass (headroom4648dev/276192release). RAM playback and all five storage fault/recovery modes pass; settings restored, storage clean. Persistently installed in slotA, exact identity/health31 verified; B12 fallback slotB retained. `out/b14-integration-outcome.json`.
- Paired playback measured runtime calls2343→1340 and idle950821→1162099us for353280 frames each. Single observation, no measured power/battery-life conclusion. Direct current measurement and broader acceptance remain open.
- Startup CRC reuse remains staged; root review requires accurate Boot deployment/fallback/map assumptions before any Boot write. Video remains paused.


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
