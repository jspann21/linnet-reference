# Open work

Completed implementation and investigation history belong in Git, not this list.

## Media

- Improve AAC seek latency.
- Measure large photo catalogs, uncached navigation during audio, JPEG fallback,
  and resume after restart, including empty folders.
- Improve video storage/display throughput and audio scheduling.
- Revisit the deferred 75 ms search target for 100,000 tracks; measure data-ready,
  rendering and display completion separately.

## Startup, power and release

- Reduce startup delay using separate mount, validation, copy/BSS and first-frame timings.
- Physically assess accelerated scrolling on long lists.
- Fault-inject the initial USB re-enumeration recovery trigger.
- Complete parser/transaction fault coverage, memory-pressure and performance
  acceptance using existing checks where available.
