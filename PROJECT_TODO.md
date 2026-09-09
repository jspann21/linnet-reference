# Open work

Release acceptance remains open. Completed implementation and investigation
history belong in Git, not this list. The selected two-photo loading fix is
complete; broader workloads still need qualification.

## Media

- Qualify sustained mixed-codec playback and automatic gapless transitions with
  combined effects, non-unity ReplayGain and listening checks.
- Complete AAC seek latency and broader seek/pause/stop qualification.
- Qualify queue advance, reorder/remove/shuffle and library replacement with pending reads.
- Measure large photo catalogs, uncached navigation during audio, JPEG fallback,
  and resume after restart, including empty folders.
- Fix video storage/display throughput and audio starvation; qualify 24/25/30 fps,
  A/V sync, seek/exit and corrupt input. Video remains a release blocker.
- Revisit the deferred 75 ms search target for 100,000 tracks; measure data-ready,
  rendering and display completion separately.

## Startup, power and release

- Reduce startup delay using separate mount, validation, copy/BSS and first-frame timings.
- Qualify battery/AC display timeout and wake, low-battery shutdown, charging,
  USB suspend/unplug behavior and full power removal.
- Physically assess accelerated scrolling on long lists.
- Fault-inject the initial USB re-enumeration recovery trigger.
- Complete parser/transaction fault coverage, memory-pressure and performance
  acceptance using existing checks where available.
- Complete release installer and release-only device journeys after media and
  power blockers are resolved.

Storage compatibility beyond the inspected iFlash remains unqualified. Keep
storage checks bounded; exhaustive drive stress is outside the current scope.
