# Linnet TODO

Single backlog for Linnet OS, Media Manager, performance, and hardware acceptance.
Reviewed October 3, 2026 against source at `24b45d1`, Git history, target manifests,
and recorded qualification notes. The initial audit did not repeat physical checks;
subsequent results are noted under their items.

The older 110-item optimization checklist at `5f228fb` had **104 items marked
complete and six open**. Those six are retained below with their remaining
measurement or qualification requirements; the separate optimization list is retired.
Current code retains the implemented scan reuse, caches, cancellation,
publication/recovery, build isolation, and portable HAL work. Keep completed items
checked and visible. The former roadmap's eight entries mostly require measurement
or acceptance; AAC seek indexing is already implemented.

`Add` identifies a feature gap. `Improve` identifies a limitation in an existing
feature. `Measure` and `Qualify` require evidence before closing. Priorities are
proposed: P1 covers reliable daily use and release readiness, P2 covers performance
and useful parity, and P3 covers optional expansion. New product suggestions are
separate from the carried-over acceptance work.

## Current coverage

| Area | Already implemented | Source |
| --- | --- | --- |
| Music and browsing | PCM/WAV/AIFF, MP3, AAC/M4A, ALAC, FLAC, Vorbis; artist/album/genre/composer/album-artist/year/folder browsing, search, artwork, and enabled Cover Flow | [Decoder](../services/music/decoder.c), [browser](../services/music/browser.c), [compiler](../tools/content/music.py) |
| Playback and playlists | Song shuffle; repeat off/all/one; gapless transitions; Play Next; queue editing; device playlist create/rename/delete; save queue as playlist; desktop playlist editor and M3U import/export | [Controller](../services/music/controller.c), [queue](../services/music/queue.c), [browser](../services/music/browser.c), [editor](../tools/studio/playlist_editor.py) |
| State and sound | Favorites, play counts, recent/most played, bookmarks, queue/position restoration, EQ, track/album ReplayGain, volume limit, clicker, balance, channels, crossfeed, and supported dock line out | [History](../services/music/history.c), [controller](../services/music/controller.c), [profile](../services/music/profile.c) |
| Media and utilities | Photo albums/grid, zoom/pan/rotation/slideshow and saved navigation; prepared/native video, pause, seek and saved position; Files, Notes, clock/date editing, sleep timer, and twelve games on Photo/Video | [Photos](../services/photos/photos.c), [video paths](video-format.md), [runtime](../kernel/runtime.c), [games](../services/games/games.c) |
| Desktop and recovery | Per-device import queue, incremental preparation/caches, progress/Stop, space planning, recoverable Trash, index recovery, video catalog restore, diagnostics export, firmware ZIP install, startup choice, restore/uninstall, and safe eject | [Desktop](../tools/studio/media_desktop.py), [preparation](../tools/content/media_manager.py), [installer](../tools/studio/installer.py) |

Availability follows the target and system configuration. Q21 disables photos,
video, Cover Flow, and games; its manifest enables two monochrome themes. Classic
has native video but disables automatic installation and currently does not enable
games. Existing Apple-library reading and the narrowly qualified Apple database
writer are implemented; broad iTunes interoperability remains incomplete.

The stock comparison uses Apple's [iPod classic 160 GB guide](https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf)
for music/display behavior and [120 GB guide](https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf)
for utilities/accessories. Features vary by generation; Classic-only and
accessory-dependent features are expansion suggestions for other targets.

## P1 — Daily use and release readiness

- [x] **Improve: music compatibility reporting and optional conversion.** Host
  metadata accepts Opus/WavPack and some channel counts/rates that firmware cannot
  play. Report compatibility for the detected target before preparation, with
  actionable skipped-file reasons. Offer optional conversion of incompatible,
  unprotected audio while preserving originals. Close when such files cannot
  silently appear ready to play. [Host codecs](../tools/content/music.py),
  [device codecs](../services/music/decoder.c), [planner](../tools/content/media_status.py).
  Complete: host compilation and Media Manager report target playback limits and
  actionable reasons; queued and existing incompatible files can be converted to
  host-prepared PCM while retaining originals and metadata. Focused imports and a
  physical device run verified library preparation and converted-track playback.

- [ ] **Qualify: power, charging, dock audio, and sustained playback.** Measure
  charging current/source changes, battery runtime, sleep/wake, shutdown/startup,
  and dock output per hardware/storage configuration. Run long audio/video
  sessions, repeated seeks, and A/V sync checks; record physical results and
  underrun/error counters. Implementations and sample playback already exist.
  [Target scope](../targets/README.md#qualification-record), [power API](../hal/api/power.h),
  [storage policy](storage.md).
  Partial: a rotating M25 completed a 12-track queue observed for five minutes;
  counters ended at 11 gapless joins with zero missed joins, underruns, or audio
  faults. A 60-second M25 video clip finished after forward/backward seeks with
  zero reported audio underruns or faults; an automated sleep/wake cycle also
  completed. A separate seven-minute Repeat All run crossed 15 joins with zero
  reported underruns or faults; Repeat Off was restored afterward. Current,
  dock, battery runtime, long audio/video, and A/V sync measurements remain open.

- [ ] **Qualify: remaining recovery, parser, transaction, and memory-pressure cases.**
  Cover interrupted media/firmware publication, corrupt/truncated records, full
  disks, device loss, settings/history durability, and native Video external-bus
  stalls beyond the exercised clock-loss fault. Use existing fault controls/checks
  and focused manual campaigns; close with explicit coverage and successful recovery.
  [Publisher](../tools/content/publish.py), [state](../services/state/store.c),
  [Video recovery](../targets/video5g-m25/coprocessor.c), [update](../services/update/update.c).
  Partial: verified media copies and index publication completed on device. A
  Photo hardware storage campaign passed scratch readback, settings restore,
  file growth, and five injected fault recoveries. On rotating M25, a guarded
  external-bus stall restored the display and a subsequent video played to EOF;
  a separate forced restore failure recorded a recovery crash and rebooted to
  the same healthy image. Three guarded native USB roundtrips also passed.
  A full track boundary increased the CRC-checked history play count across a
  guarded reboot. Four settings publication cuts exposed only intact old/new
  records; the original was restored and verified after a final reboot (one cut
  needed a retry after an explicit write rejection). Other history interruption
  cases, media/firmware publication cuts, rollback, and USB device loss remain open.

- [ ] **Qualify: packaged release workflows.** Exercise navigation, playback,
  install/update, rollback, restore/uninstall and media preparation using release
  images and the packaged Windows app on supported devices. Include a clean
  computer and documented FFmpeg setup. Development builds and simulator output
  do not certify the release path. [Firmware packaging](../tools/studio/firmware_bundle.py),
  [desktop distribution](../tools/studio/media_distribution.py), [installer](../tools/studio/installer.py).
  Partial: the local M25 release image and both ZIPs built; archive checks passed,
  and the packaged Windows app launched locally. A clean Windows computer and the
  supported-device release campaign remain pending.

- [ ] **Add: first downloadable release after acceptance.** Packaging is implemented;
  the README still says downloads are unavailable. Publish versioned Windows and
  qualified firmware ZIPs with checksums and installation/recovery notes, then
  update Get started. [Release status](../README.md#get-started),
  [distribution](../tools/studio/media_distribution.py).
  Blocker: release qualification and a publishing destination are pending.

## P2 — Existing performance and hardware work

- [ ] **Measure: whole-operation Media Manager baselines.** Compare cold/warm
  discovery, planning, preparation, conversion, verification and publication on
  rotating and flash storage, including large catalogs and UI responsiveness.
  Scan/metadata/conversion reuse is already implemented; establish its combined
  effect before proposing more cache changes. [Status](../tools/content/media_status.py),
  [preparation](../tools/content/media_manager.py), [desktop](../tools/studio/media_desktop.py).
  Partial: flash conversion and rotating-library reads were measured; verified
  converted-audio hashes reuse unchanged host cache entries, and direct Apple music
  browsing reuses scanned file records. Repeated original-copy plans now hash the
  host source against a verified device digest without rereading device content;
  focused equal/changed checks passed. Discovery, inspection, and empty planning
  were timed on first and repeated passes on rotating and flash devices. Incremental
  Music/Files runs completed on rotating (12 tracks) and flash (426 tracks)
  devices. The rotating run published an updated Files index; the flash run and
  unchanged repeats reused both libraries. Source file stamps and sampled hashes
  matched, and subsequent playback reported no faults. Conversion, large catalog,
  and UI responsiveness baselines remain open.

- [ ] **Measure/Improve: remaining AAC seek latency.** Host checkpoints and indexed
  M4A seeking are implemented. Measure prepared M4A separately from unindexed M4A
  and raw ADTS, whose backward/restart paths can decode from the beginning. Check
  long files, rapid retargets, rejected indexes and audio continuity; optimize the
  measured fallback bottleneck. [Host indexes](../tools/content/aac_index.py),
  [M4A](../services/audio/aac/m4a.c), [ADTS](../services/audio/aac/aac.c).
  Partial: prepared M4A seeks resumed on flash hardware without reported underruns;
  unindexed M4A, raw ADTS, long-file and rapid-retarget cases remain open.

- [ ] **Qualify: large photo catalogs and saved navigation.** Grid preloading,
  JPEG fallback, saved focus and empty-album resume are implemented. Exercise large
  catalogs, uncached navigation during audio, fallback decoding, empty folders,
  and restart with changed/missing content. Measure first usable frame and audio
  reserve. [Photos](../services/photos/photos.c), [saved state](../services/display/settings.c).
  Partial: physical catalog and photo navigation continued during PCM playback
  without reported underruns; fallback, empty-folder, and restart cases remain.

- [ ] **Measure/Improve: competing media work during playback.** Profile artwork,
  photos, metadata/history and next-track preparation at track boundaries. Measure
  video storage/display throughput and audio scheduling per backend. Existing
  budgets, read-ahead, PCM reserves and gapless joins are in place; verify tuning
  does not add underruns or missed joins. [Controller](../services/music/controller.c),
  [player](../services/music/player.c), [M25](../targets/video5g-m25/coprocessor.c),
  [Classic](../services/video/native/player.c).
  Partial: photo navigation and an AAC-to-PCM track boundary stayed active on flash
  hardware without reported underruns or missed joins. A rotating M25 video
  startup comparison isolated a longer media-open stage that shortened on the
  next start with the disk active; a short clip completed with seeks and no
  reported audio faults. Artwork, history, backend throughput, and A/V sync remain.

- [ ] **Measure/Improve: deferred 75 ms search goal at 100,000 tracks.** Search,
  retained pages and lower-bound caching are implemented. Measure first result,
  full visible window, render and display completion separately on cold/warm
  storage, including playback. Decide feasibility per configuration.
  [Search counters](../services/music/search.c), [database](../services/music/database.c),
  [render timing](../kernel/runtime_render_timing.h).

- [ ] **Measure/Improve: remaining startup delay.** Separate mount, validation,
  copy/BSS, resource/display initialization and first usable frame. Boot handoff
  and initialization improvements already exist; find the remaining bottleneck
  using current release images on cold/warm boots. [Boot](../boot/src/linnet_boot.c),
  [entry](../kernel/main.c), [runtime](../kernel/runtime.c).
  Partial: a physical development timeline isolated image validation and first-frame
  stages; release-image cold/warm comparison remains open.

- [ ] **Qualify: physical wheel response and display quality.** Accelerated scrolling
  is implemented. Check long lists, overshoot, selection stability, readability,
  clipping, brightness, theme switching and artifacts on real panels. Synthetic
  input/captures do not establish physical wheel or LCD quality.
  [Input](../kernel/runtime.c), [UI](../ui/runtime/ui.c),
  [qualification scope](../targets/video5g-m25/QUALIFICATION.md).

- [ ] **Measure: Q21 idle wake sources and clock-switch break-even.** Idle clock
  switching is enabled. Compare battery/external power, wake frequency, input
  response and actual current draw before changing the policy.
  [Runtime](../kernel/runtime.c), [manifest](../targets/ipod4g-q21/target.toml).

- [ ] **Measure/Qualify: Classic native video startup and MPEG-4.** Measure decoder
  startup stages and buffer use before changing priming thresholds or frame
  buffers. H.264 playback is recorded; MPEG-4 acceptance remains open. M25 uses a
  different BCM backend. [Player](../services/video/native/player.c),
  [decoder](../services/video/native/decoder.c), [video scope](video-format.md).
  Partial: two MPEG-4 clips completed on Classic hardware without errors or
  dropped frames; startup counters were captured. Buffer and broader A/V acceptance remain.

- [ ] **Measure: Classic small-update display costs.** Measure framebuffer
  preservation and panel transfer for status/list updates. Full-repaint copy
  avoidance already exists; verify alternating buffers, theme acknowledgement and
  physical tearing before narrowing transfers. [Display](../targets/classic6g-n25/display.c),
  [panel](../targets/classic6g-n25/panel.c).

- [ ] **Qualify: Classic Apple handoff after the portable HAL refactor.** The
  retail-payload decode API is implemented. Verify its Classic AES/handoff path
  on matching hardware before closing the original optimization item.
  [API](../hal/api/platform.h), [Classic implementation](../hal/s5l8702/platform.c),
  [caller](../services/storage/storage.c).

## P2 — New product suggestions from the audit

- [ ] **Add: dedicated podcasts and audiobooks.** M4B import, bookmarks, 10-second
  jumps and queue resume exist. Add media-kind/series/episode/chapter metadata,
  dedicated browsing, played/unplayed state, automatic per-item resume, exclusion
  from Shuffle Songs and spoken-audio speed control. History stores per-track
  resume positions, but ordinary selection does not restore them.
  [Compiler](../tools/content/music.py), [schema](../services/music/database.h),
  [controller](../services/music/controller.c), [history](../services/music/history_record.h).

- [ ] **Add: lyrics.** Extract embedded/sidecar text on the host, publish bounded
  per-track data and expose a readable Now Playing view. Lyrics are absent from
  the track schema and playback options. [Schema](../services/music/database.h),
  [options](../services/music/controller.c).

- [ ] **Add: star ratings and desktop listening-history access.** Favorites and
  play counts exist. Add 0–5 ratings to mutable history, device controls and
  desktop display/editing; preserve state during preparation using stable IDs.
  [History](../services/music/history_record.h), [desktop library](../tools/content/media_library.py).

- [ ] **Add: album shuffle.** The queue has a boolean song-shuffle mode. Randomize
  album order while retaining track/disc order within albums, including repeat,
  resume and large virtual queues. [Queue](../services/music/queue.h),
  [controls](../services/music/controller.c).

- [ ] **Add: persistent user brightness and device settings controls.** Brightness
  currently changes through a development control; Display exposes timeout/themes.
  Add saved wheel-adjustable brightness on suitable targets, device-side menu
  customization and Reset Settings. Desktop menu editing already exists. Reset
  should preserve media and make listening-history treatment explicit.
  [Runtime](../kernel/runtime.c), [settings](../services/display/settings.c),
  [desktop menus](../tools/studio/screen_settings.py).

- [ ] **Improve: slideshow settings.** Slideshows use a fixed five-second delay.
  Add saved interval, repeat/shuffle and optional music-playlist choices; verify
  slide changes preserve audio reserve. [Slideshow](../services/photos/photos.c),
  [controls](../services/music/ui.c).

- [ ] **Improve: stock Sound Check compatibility.** ReplayGain works and some
  targets label it Sound Check, but the host reads ReplayGain tags rather than
  Apple `iTunNORM` values. Import Apple normalization data or consistently label
  the control ReplayGain. Offer optional host loudness analysis for untagged music.
  [Extraction](../tools/content/music.py), [labels/application](../services/music/controller.c).

- [ ] **Add: desktop metadata/artwork editing.** Media details are read-only.
  Add single/batch tag overrides and cover replacement, define optional file-tag
  writes explicitly, invalidate affected prepared assets and retain track identity.
  [Details](../tools/studio/media_desktop.py), [metadata](../tools/content/music.py),
  [artwork](../tools/content/album_art.py).

- [ ] **Add: smart playlists and expand saved-playlist limits.** Static playlists,
  M3U exchange and built-in activity views exist. Add host-evaluated rules using
  tags/ratings/history, and a bounded design beyond 16 saved lists / 1,024 entries
  each. Ordinary virtual music queues already support 100,000 tracks.
  [Editor](../tools/studio/playlist_editor.py), [saved format](../tools/content/playlists.py),
  [collections](../services/music/collections.h), [queue](../services/music/queue.h).

- [ ] **Add: saved sync policies and desktop playback preview.** Per-device queues,
  change detection and reconciliation exist. Add saved folder/playlist selections
  and an explicit sync preview of additions, replacements, removals and space.
  Add audio/video playback preview; existing details/artwork previews are not a
  media player. [Desktop](../tools/studio/media_desktop.py),
  [plan/reconciliation](../tools/content/media_status.py).

- [ ] **Add: video library categories.** The catalog is a flat title/path list.
  Add movie, show/season/episode and music-video metadata, host editing and device
  browsing while preserving prepared entries and resume state.
  [Host catalog](../tools/content/video_catalog.py), [device catalog](../services/video/catalog.c).

## P3 — Optional parity and broader support

- [ ] **Add: alarms, world clocks and a stopwatch.** Clock/date editing and sleep
  timer exist. Add persisted utility settings, lap recording and measured alarm
  wake behavior, accounting for the target's audible outputs.
  [Clock](../services/display/clock.c), [power API](../hal/api/power.h),
  [Extras](../ui/system/extras/screen.tsx).

- [ ] **Add: contacts, calendar events and a combination screen lock.** Prepare
  bounded vCard/iCalendar data on the host and add device viewers. The HAL calendar
  represents RTC time, not events. Hold-switch handling exists; a combination-lock
  UI and saved combination do not. [Extras](../ui/system/extras/screen.tsx),
  [clock API](../hal/api/power.h), [settings](../services/display/settings.c).

- [ ] **Add: broader glyph coverage and translated menus.** Metadata is UTF-8,
  but current fonts are ASCII and device search input is English. Add bounded
  glyph coverage, matching input/search rules and language selection; exercise
  accented and non-Latin libraries on every supported display.
  [Font baker](../tools/content/font.py), [renderer](../ui/runtime/ui.c),
  [search input](../services/music/search.c).

- [ ] **Qualify/Add: accessories and TV output.** Physically qualify M25's TV
  commands. Photo IPVF exposes TV choices without functioning output selection;
  Classic reports TV unavailable. Implement or hide unsupported controls. Scope
  dock/car/remote protocols, optional radio accessories and voice recording
  separately; general accessory/recording services are absent. Dock line out exists.
  [M25 TV](../targets/video5g-m25/coprocessor.c), [Photo](../services/video/ipvf/player.c),
  [Classic](../services/video/native/player.c), [audio API](../hal/api/audio.h).

- [ ] **Qualify/Improve: wider hardware and Apple-library interoperability.** Qualify
  additional board/RAM/storage variants and guarded Classic installation before
  enabling its automatic installer. Enable Classic games after layout/input/playback
  acceptance. Expand Apple database support beyond two exact qualified volumes and
  current music/path restrictions; add optional desktop iTunes-library/playlist
  migration. Existing Apple media reading and playlist preservation already work.
  [Targets](../targets/README.md), [Classic policy](../targets/classic6g-n25/target.toml),
  [Apple boundary](apple-stock-music.md), [reader](../tools/content/retail_media.py).

- [ ] **Decide: proprietary stock features and broader desktop scope.** Native
  Genius, protected purchases/Audible formats and commercial iPod games are absent;
  they require separate feasibility work. Consider local playlist recommendations.
  macOS/Linux packaging and CD ripping are optional companion expansion.
  [Audio](../services/music/decoder.c), [distribution](../tools/studio/media_distribution.py).

## Closing items

Keep completed items checked and visible with a short evidence note. Record partial
work separately from remaining acceptance. Update target evidence notes when
qualification passes; keep outstanding tasks here. Keep workloads,
timings, build identities and receipts in [local artifacts](local-artifacts.md).
Use existing checks and manual verification; add new tests only when requested.
Measurement items close with comparable evidence or a documented decision that
further optimization is unnecessary. Physical acceptance requires physical evidence.
