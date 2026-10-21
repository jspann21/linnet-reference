# Roadmap

This backlog contains unfinished work only. Current features and completed
hardware checks belong in the [guides](README.md) and
[hardware reference](hardware.md).

P1 covers release readiness, P2 covers remaining performance work and feature
proposals, and P3 covers optional expansion. Priorities are not release dates.
An acceptance item names the specific check still missing; it does not mean the
underlying feature needs to be implemented.

## P1 — Release readiness

- [ ] **Battery runtime, charge current, and dock output.** Measure actual current
  and charging-source transitions, battery-powered runtime and repeated
  sleep/wake, and physical dock audio for release hardware/storage configurations.
  [Power API](../hal/api/power.h), [storage policy](storage.md).

- [ ] **Physical video A/V sync.** Observe sound and picture together during
  extended playback and after seeks on Photo, Video, and Classic. Include
  battery-powered sessions. [Video backends](video-format.md).

- [ ] **Remaining interruption and resource-limit cases.** Check USB loss during
  publication, interruption points beyond the exercised settings/candidate and
  photo-grid cuts, interrupted history writes, full disks, malformed/truncated
  records, and memory pressure. Check Video bus faults beyond the documented
  clock-loss recovery path. Use the existing
  [device checks](device-link.md#existing-device-checks) and
  [M25 qualification record](../targets/video5g-m25/QUALIFICATION.md) to identify
  gaps instead of repeating completed campaigns.

- [ ] **Clean-machine and release-device acceptance.** Run the packaged Windows
  app on a clean computer with the documented FFmpeg setup. Exercise navigation,
  playback, media preparation, install/update, rollback, restore, and uninstall
  with release images on the devices selected for release.
  [Firmware bundles](../tools/studio/firmware_bundle.py),
  [Windows distribution](../tools/studio/media_distribution.py).

- [ ] **First downloadable release.** Publish accepted Windows and firmware ZIPs
  with checksums, installation/recovery notes, and qualified hardware scope.
  Update [Get started](../README.md#get-started) with the downloads.

### Open issues

| Issue | Remaining work |
| --- | --- |
| High-load AAC underruns on rotating M25 | Identify and fix the decoder or scheduling limit for affected tracks. Host-prepared PCM is an available [workaround](music-format.md#playback-compatibility). |
| Intermittent Q21 eject and Windows dirty-volume state | Determine why eject can require a retry and Windows can report a dirty volume despite clean read-only filesystem checks. Verify the fix across repeated mount/eject cycles. |
| Intermittent Q21 Link timeouts | Determine the cause of read/upload timeouts and verify reliable persistent transfer and interruption recovery on A1059 and MP102. |

## P2 — Remaining measurements and device checks

- [ ] **Large-library cold verification and batch conversion.** Measure large,
  ready catalogs with empty verification caches, batch conversion throughput,
  and desktop responsiveness during preparation on rotating and flash storage.
  [Readiness](../tools/content/media_status.py),
  [preparation](../tools/content/media_manager.py).

- [ ] **Unindexed AAC and seek edge cases.** Measure playable unindexed M4A,
  raw ADTS, long files, and rejected-index fallback, including continuity after
  seeking. Optimize only a demonstrated bottleneck.
  [M4A reader](../services/audio/aac/m4a.c), [ADTS reader](../services/audio/aac/aac.c).

- [ ] **Photo recovery with changed content.** Exercise empty albums and restart
  with changed or missing content. Qualify original-JPEG fallback on Photo and
  Video, including uncached reads during audio.
  [Photo viewer](../services/photos/photos.c).

- [ ] **Concurrent history, artwork, and prefetch at track boundaries.** Attribute
  controller time and audio reserve when these operations overlap at a join,
  especially on rotating storage. Tune only if measurements identify starvation
  or a missed deadline. [Music controller](../services/music/controller.c),
  [player](../services/music/player.c).

- [ ] **Search latency at 100,000 tracks.** Evaluate the proposed 75 ms goal per
  storage configuration. Measure first result, visible window, render, and
  display completion on cold/warm storage and during playback.
  [Search](../services/music/search.c), [database](../services/music/database.c).

- [ ] **Release-image startup timings.** Compare cold/warm release boots,
  separating mount, image validation, copy/BSS, resource/display initialization,
  and first usable frame. [Boot](../boot/src/linnet_boot.c),
  [runtime](../kernel/runtime.c).

- [ ] **Long-list wheel feel and theme/panel edge cases.** Observe overshoot,
  selection stability, clipping, brightness, and theme artifacts on physical
  panels beyond the controls and readability checks already recorded in
  [hardware qualification](hardware.md#variant-handling-and-physical-coverage).

- [ ] **Q21 idle power tradeoff.** Attribute idle wake sources and measure actual
  current and physical input response on battery versus external power before
  adjusting clock-switch thresholds. [Q21 manifest](../targets/ipod4g-q21/target.toml),
  [runtime](../kernel/runtime.c).

- [ ] **Classic decoder buffer use.** Compare cache/frame-buffer use for H.264
  and MPEG-4 before changing buffer counts or priming thresholds.
  [Native player](../services/video/native/player.c),
  [decoder](../services/video/native/decoder.c).

- [ ] **Classic alternating buffers and physical tearing.** Check framebuffer
  preservation across alternating draw/present buffers and inspect the panel
  for tearing during small updates. [Display](../targets/classic6g-n25/display.c),
  [panel](../targets/classic6g-n25/panel.c).

- [ ] **Classic startup-selector return to Apple.** Physically verify the
  retail-payload AES/decode and handoff through the portable HAL. NOR restoration
  during uninstall exercises a separate path.
  [Platform implementation](../hal/s5l8702/platform.c),
  [storage caller](../services/storage/storage.c).

## P2 — Feature proposals

These additions are proposed work, not promises for the first release.

| Proposal | Remaining addition |
| --- | --- |
| Podcasts and audiobooks | Series/episode/chapter metadata, dedicated browsing, played state, automatic per-item resume, exclusion from Shuffle Songs, and spoken-audio speed control. |
| Lyrics | Host-prepared embedded/sidecar lyrics and a bounded Now Playing view. |
| Star ratings and desktop history access | 0–5 ratings, device rating controls, and desktop access to listening history, preserving stable track IDs. |
| Album shuffle | Random album order with disc/track order retained within each album, including repeat and resume. |
| Device settings | Saved wheel-adjustable brightness, device-side menu customization, and Reset Settings with explicit treatment of history. |
| Slideshow settings | Saved interval, repeat/shuffle, and optional music-playlist choices. |
| Sound Check compatibility | Import Apple `iTunNORM` values or consistently label normalization as ReplayGain. Consider host loudness analysis for untagged music. |
| Metadata and artwork editing | Single/batch tag overrides and cover replacement, with explicit file-tag write policy, asset invalidation, and track-identity preservation. |
| Smart playlists and larger saved lists | Host-evaluated playlist rules and a bounded design beyond 16 saved lists / 1,024 entries each. |
| Saved sync policies | Persistent folder/playlist selections that determine future syncs. |
| Desktop playback preview | Audio/video playback within Media Manager. |
| Video categories | Movie, show/season/episode, and music-video metadata, editing, and browsing. |

Implementation entry points: [music compiler](../tools/content/music.py),
[music schema](../services/music/database.h), [queue](../services/music/queue.h),
[history](../services/music/history_record.h),
[desktop](../tools/studio/media_desktop.py), and
[video catalog](../tools/content/video_catalog.py).

## P3 — Broader support

| Area | Remaining work |
| --- | --- |
| Utilities | Alarms with measured wake behavior, world clocks, stopwatch/laps, host-prepared contacts and calendar events, and a persisted combination screen lock. |
| Languages | Broader glyph coverage, translated menus, and matching input/search rules. |
| Accessories and TV output | Physically qualify M25 TV commands. Scope dock/car/remote protocols, radio accessories, and recording separately. |
| Hardware variants | Qualify the additional boards, storage, panels, and NOR chips listed in [hardware support](hardware.md), and Classic installation before enabling its automatic installer. |
| Classic games | Physical layout, input, and playback acceptance on Classic hardware. |
| Apple interoperability | Expand exact-device database qualification and music/path support. |
| Optional expansion | Assess local recommendations, proprietary stock features, protected purchases/Audible, and commercial iPod games separately. Consider macOS/Linux packaging and CD ripping. |

## Maintaining the roadmap

Remove completed work. If only part of an item remains, rename it and describe
that specific gap; do not leave the whole feature unchecked or append a history
of results. Record current behavior in the owning guide and completed device
checks in the hardware reference. Keep exact workloads, timings, build identities,
and receipts in [local artifacts](local-artifacts.md).

Close a measurement item when its question is answered, including when the
result shows no optimization is needed. Physical acceptance requires physical
evidence; an implementation or a successful build does not supply it.
