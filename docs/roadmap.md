# Roadmap

Current features and tested devices are documented in the [guides](README.md)
and [hardware reference](hardware.md). This roadmap tracks release packaging,
performance work, and future features. Priorities are not release dates.

## P1 — Release readiness

- [ ] **Remaining interruption and resource-limit cases.** Check USB loss during
  publication, interruption points beyond the exercised settings/candidate and
  photo-grid cuts, interrupted history writes, full disks, malformed/truncated
  records, and memory pressure. Check Video bus faults beyond the documented
  clock-loss recovery path. Use the existing
  [device checks](device-link.md#existing-device-checks).

- [ ] **Clean-machine packaging check.** Run the packaged Windows app on a
  clean computer with the documented FFmpeg setup.
  [Windows distribution](../tools/studio/media_distribution.py).

- [ ] **First downloadable release.** Publish accepted Windows and firmware ZIPs
  with checksums, installation/recovery notes, and a link to supported hardware.
  Update [Get started](../README.md#get-started) with the downloads.

## P2 — Performance

- [ ] **Large-library cold verification and batch conversion.** Measure large,
  ready catalogs with empty verification caches, batch conversion throughput,
  and desktop responsiveness during preparation on rotating and flash storage.
  [Readiness](../tools/content/media_status.py),
  [preparation](../tools/content/media_manager.py).

- [ ] **Unindexed AAC and seek edge cases.** Measure playable unindexed M4A,
  raw ADTS, long files, and rejected-index fallback, including continuity after
  seeking. Optimize only a demonstrated bottleneck.
  [M4A reader](../services/audio/aac/m4a.c), [ADTS reader](../services/audio/aac/aac.c).

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

- [ ] **Q21 idle power tradeoff.** Attribute idle wake sources and measure actual
  current and physical input response on battery versus external power before
  adjusting clock-switch thresholds. [Q21 manifest](../targets/ipod4g-q21/target.toml),
  [runtime](../kernel/runtime.c).

- [ ] **Classic decoder buffer use.** Compare cache/frame-buffer use for H.264
  and MPEG-4 before changing buffer counts or priming thresholds.
  [Native player](../services/video/native/player.c),
  [decoder](../services/video/native/decoder.c).

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
| Screen recording | Short, silent GIF clips over Linnet Link, starting at 1 fps with bounded duration, Stop, preview and Save. Qualify playback, cancellation and disconnect behavior; see [capture exploration](media-manager.md#screen-recording-exploration). |
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
| Accessories and TV output | Add support for docks, remotes, radio, recording, and TV output. |
| Hardware variants | Extend support to additional boards, storage adapters, panels, and NOR chips. |
| Apple interoperability | Expand exact-device database qualification and music/path support. |
| Optional expansion | Assess local recommendations, proprietary stock features, protected purchases/Audible, and commercial iPod games separately. Consider macOS/Linux packaging and CD ripping. |
