**Linnet performance and cleanup backlog**

Created and expanded September 26, 2026, from the current code at `55a82c0`. This is a proposed backlog; checked items have passed their stated local completion checks. Device-only checks remain explicit where needed. Items 61–110 extend the review into device additions, target policy, build workflows, Media Manager, device performance, and file organization.

`P1` means start here, `P2` means a useful follow-up, and `P3` means lower expected payoff or cleanup after higher-priority work. `Code` identifies a concrete pattern observed in the source, not a proven speedup. `Profile` requires measurement or design investigation before implementation. Priority reflects expected value and scope, not a confirmed defect severity.

Work through small batches. Use existing checks, focused manual verification, and existing media; follow the current preference against adding tests or fixtures unless requested. Compare full-operation time as well as isolated timing, retain byte-identical output for performance-only changes, and preserve source media, target identity checks, publication verification, and recoverable state. Benchmark conditions and implementation dependencies may change the order.

Completed improvements are deliberately excluded: bounded artwork loading, direct cover painting, verification-cache expiry, external-video title lookup, faster photo tile packing and per-image cancellation, incremental playlist moves, and fallback-cover conversion reuse are already implemented.

**Start here**

- [x] **01 · P1 · Code: Exclude disposable caches from build identity.** The source walk excludes out, .git, __pycache__, and .venv, but includes the existing .ruff_cache directory. Define the generated-directory exclusions explicitly so lint activity cannot change a firmware build identity.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `source_paths / source_identity`.

  Completion check: Running lint leaves the source identity unchanged; editing real source or configuration still changes it. Retain deliberately included untracked source files.

- [x] **02 · P1 · Code: Reuse directory scans while planning imports.** Planning calls additions or video_jobs, then walks each queued folder again to count preview files. Share a bounded snapshot within the planning call, with metadata revalidated when copying starts.

  Location: [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py) — `plan`.

  Completion check: Copy counts, byte totals, preview labels, exclusions, and collision errors match; each selected tree is enumerated once during planning.

- [x] **03 · P1 · Code: Load the iTunes photo list once for a batch of exclusions.** Each selected virtual iTunes photo calls images(root) again. Build the valid-photo path set once per operation and reuse it for the selected batch.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `skip_files`.

  Completion check: Excluding many photos performs one photo-library load and produces the same skip entries; unknown photo paths are still rejected.

- [x] **04 · P1 · Code: Restore skipped entries in one pass per media kind.** The function rebuilds a kind's entire skip list for each restored item. Group requested paths by kind, normalize them once, and filter each stored list once.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `restore_skipped_files`.

  Completion check: Large multi-selection restores scale with stored plus selected entries; duplicate requests, case differences, malformed stored entries, and returned results retain their intended behavior.

- [x] **05 · P1 · Code: Locate one Trash removal without scanning every removal.** recover finds one token by calling removals, which walks every Trash tree. Resolve and validate the requested receipt and tree directly; reuse that path for multi-selection recovery.

  Location: [tools/content/media_trash.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_trash.py) — `recover / removals`.

  Completion check: Restoring one removal does not enumerate unrelated Trash trees. Receipt validation, current-file checks, recovery conflicts, and guarded writes still run.

- [x] **06 · P1 · Code: Keep small artwork at its native decode size.** The requested decode size always fits the image into 320 by 320, including smaller images. Avoid enlarging small previews during loading; let painting handle display scaling.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.read_image`.

  Completion check: Small covers occupy less cache memory, large images retain bounded decoding, and visual checks cover sharpness, aspect ratio, orientation, and high-DPI displays.

  Verification note: A rotated 80 × 50 JPEG decoded to 50 × 80, while a 1600 × 800 image decoded to 320 × 160. Offscreen 1× and 2× renderings preserved aspect ratio, orientation, and smooth scaling. The visual check also exposed and fixed a Qt rectangle overload error in `paint_cover`.

- [x] **07 · P1 · Code: Preserve user column widths during search and view refresh.** Every render resets column widths and resize modes. Apply defaults when the column layout changes rather than on every search, filter, or refresh.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.render_library`.

  Completion check: A user-resized column keeps its width through filtering; switching between song and file columns still gives sensible initial widths.

- [x] **08 · P1 · Code: Add per-file cancellation and progress to Notes preparation.** Notes compilation processes the complete batch without a progress/checkpoint callback. Follow the existing music and photo callback pattern and connect it to Media Manager.

  Location: [tools/content/notes.py](C:/Users/user/Desktop/Projects/linnet/tools/content/notes.py) — `compile_notes`.

  Completion check: Stop is honored between documents, progress identifies the current document, and cancellation preserves the previous package without publication.

- [x] **09 · P1 · Code: Honor Stop during photo package assembly and checking.** Photo callbacks now run between images, but spool copying and final validation can still be lengthy. Add bounded checkpoints to those phases and pass them through the caller.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `compile_photos / inspect`.

  Completion check: A large package can stop during assembly or inspection; temporary output is cleaned up and the previous completed package remains intact.

- [x] **10 · P1 · Code: Make native-video probing cancellable.** ffprobe uses a blocking subprocess.run with a 60-second timeout. Route it through a cancellable process helper while retaining the timeout and bounded diagnostic output.

  Location: [tools/content/native_video.py](C:/Users/user/Desktop/Projects/linnet/tools/content/native_video.py) — `inspect_file / prepare`.

  Completion check: Stop terminates a stalled probe promptly, reaps its process, leaves the prior output intact, and reports cancellation separately from incompatible video.

- [x] **11 · P1 · Code: Read only the retained tail of encoder error logs.** On conversion failure, errors.read() loads the whole temporary log before slicing its last 4,000 bytes. Seek to the tail before reading it.

  Location: [tools/content/native_video.py](C:/Users/user/Desktop/Projects/linnet/tools/content/native_video.py) — `prepare`.

  Completion check: A large error log uses bounded memory and produces the same useful trailing diagnostic, including short logs and incomplete UTF-8 sequences.

- [x] **12 · P1 · Code: Move queued-source filesystem checks off the GUI thread.** Adding sources resolves and stats selected paths on the UI thread and resolves the existing queue again. Keep queue identities from successful validation and perform new filesystem work through the worker.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.queue_sources`.

  Completion check: Adding a large folder selection or a slow/network path keeps the window responsive; duplicates and paths already on the iPod are still handled correctly.


**Reduce repeated scans and metadata work**

- [x] **13 · P2 · Profile: Avoid rescanning adoption receipts on every device refresh.** A refresh may scan and parse session receipts to find an Apple Disk Mode cache. Measure this on a cache with many receipts, then reuse a validated adoption result with explicit invalidation.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_retail_cache_serial`.

  Completion check: Repeated refreshes read fewer receipts without carrying an adoption across a changed volume, partition, target, disk geometry, or relevant cache state.

  Verification note: A1099's native Disk Mode cache had 28 candidate session receipts, 21 matching the Apple identity. A successful refresh read one receipt in about 1 ms; later lookups read none in about 0.5 ms after checking that receipt's file identity, size, and timestamps. Whole identity refreshes still took about 3.4 s each, so this is a bounded I/O reduction rather than a visible speed claim. The cache key includes the current volume, partition, target, and disk geometry; changed geometry forced a full scan and rejected adoption. Local receipt replacement, deletion, volume change, and target change also invalidated the result. Apple and native volume GUIDs differ on this physical device, so the original receipt matching rule remains authoritative.

- [x] **14 · P2 · Profile: Consolidate redundant full identity refreshes within one operation.** run refreshes identity before taking the mutex and _run refreshes again; skip handling can add further full refreshes. Trace these calls and distinguish required boundary checks from redundant discovery.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `run / _run / refresh`.

  Completion check: Fewer expensive discovery calls with the same rejection of device changes; keep the per-write volume guards and required checks after locking.

  Verification note: A cancelled Notes operation on A1099 in native Disk Mode made two full refresh calls in 7.03 s before this change and one after locking in 3.44 s afterward. A changed partition offset was still rejected before any device work. Retry attempts each refresh after locking, and the existing per-write volume guards remain in place.

- [x] **15 · P2 · Code: Resolve video catalog paths once per library refresh.** Catalog paths are validated in _catalog, resolved again to build published_paths, and resolved again when published rows are created. Return or retain the validated mapping for that read-only refresh.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_catalog / list_items / _device_path`.

  Completion check: The catalog produces identical rows and errors with fewer path queries; missing files and changed paths are handled at the appropriate operation boundary.

- [x] **16 · P2 · Profile: Reuse scan evidence when building published music rows.** The directory inventory already supplies paths, but reading the prepared music database performs per-track _plain and resolve calls again. Measure their share of refresh time before designing scoped reuse.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_music_metadata / list_items`.

  Completion check: Read-only refresh gets faster on the actual device while escaped paths, reparses, missing sources, and database references outside the scan remain correctly handled.

  Verification note: On A1099, warm music metadata reading took about 0.63 seconds before the change, about 0.33 seconds of it in repeated path guards. The database uses FAT short aliases while traversal returns long names, so an initial path-string reuse attempt was discarded. Traversal now retains each entry's file ID, and database rows reuse only matching ID, size, and timestamp; other references keep the guarded resolution path. Warm whole refresh improved from 4.50 to 4.13 seconds in alternating old/new runs, with the same 3,252 row digest. A copied one-track database also handled an out-of-scan source, a missing source, a linked source, and a validator-rejected escaped reference as expected. A1099 returned to healthy Link after safe eject.

- [x] **17 · P2 · Profile: Remove duplicate path resolution while parsing Apple tracks.** _path resolves a track to check containment, and _tracks resolves it again for the dictionary key. Consider returning both the original path and its validated resolved identity.

  Location: [tools/content/retail_media.py](C:/Users/user/Desktop/Projects/linnet/tools/content/retail_media.py) — `_path / _tracks`.

  Completion check: Apple track rows and key normalization remain identical, including the supported Music traversal form; unsafe paths remain rejected.

- [x] **18 · P2 · Profile: Reuse thumbnail-file metadata within one Apple image scan.** Many image records can reference the same .ithmb file, but candidate handling repeats path validation and stat calls. Measure the duplication and use a call-local file snapshot where appropriate.

  Location: [tools/content/retail_media.py](C:/Users/user/Desktop/Projects/linnet/tools/content/retail_media.py) — `images`.

  Completion check: Fewer repeated filesystem queries with the same chosen thumbnail, bounds validation, cache invalidation, and behavior when a source file changes.

  Verification note: A1099's 145 Apple photos reference two thumbnail files. A warm profile recorded 290 path validations and 1,458 filesystem stat calls before this change; call-local snapshots reduced those to two path validations and 166 stat calls. Each used thumbnail file is revalidated at the end of the scan, so a source change rejects the scan rather than returning mixed stamps.

- [x] **19 · P2 · Profile: Reuse bounded readers for shared Apple thumbnail files.** Uncached previews open and seek a thumbnail file separately for each image. Investigate a small set of readers, or contiguous read batches, scoped to one extraction.

  Location: [tools/content/retail_media.py](C:/Users/user/Desktop/Projects/linnet/tools/content/retail_media.py) — `images`.

  Completion check: Cold extraction reduces opens or seeks; all handles close on failure, memory remains bounded, and extracted preview pixels match.

  Verification note: On A1099's 145 Apple photos, fresh preview extraction opened the two shared .ithmb files once each instead of once per image; process open calls fell from 332 to 147 while seeks remained at 145. The ordered reader cache is capped at four files and closes on success or failure. All 145 generated PNGs matched the previous byte digest (`61617ddff9e2bb3ca826e6a707661a6309e68bd3a3dc738bdc430b464fc1c6ea`); an injected decode failure closed its open reader. Warmed-device extractions were about 0.8 s in both versions, so no latency gain is claimed from that timing.

- [x] **20 · P2 · Code: Stop repeated ancestor walks in Apple folder discovery.** Each file climbs through every parent even when those parents were already added by another file in the same folder. Stop once the remaining ancestor chain is already known.

  Location: [tools/content/apple_os.py](C:/Users/user/Desktop/Projects/linnet/tools/content/apple_os.py) — `_folder_rows`.

  Completion check: The same folder choices and ordering are returned for deep trees, with less repeated parent construction on large albums.

- [x] **21 · P2 · Profile: Measure metadata cache work for rows already covered by Apple or Linnet metadata.** The function prefetches and validates host metadata before using Apple or published fallbacks. Profile warm and cold paths to identify rows whose cache work can safely be avoided.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_source_music_metadata`.

  Completion check: Reduce work only where metadata precedence is preserved: cached edits, album artists, duration, track/disc numbers, and artwork remain correct.

  Verification note: On A1099, 3,917 Music inventory files included 2,894 tracks covered by both Apple and published metadata. The warm source-metadata pass took 0.312 s; 2,894 cache validations accounted for 0.100 s and 23 prefetches for 0.022 s. All 2,894 rows had usable host metadata, which can override Apple fields and supply frames, rate, and album-artist values. A fresh empty cache returned the 2,894 fallback rows in 0.110 s without parsing the audio. Skipping warm cache reads would change precedence, so no bypass was added.

- [x] **22 · P2 · Code: Reuse a validated video catalog during unchanged-video checks.** The same small catalog is opened and decoded for each video cache hit. Load an indexed snapshot once for an unchanged batch and invalidate or update it whenever publication changes the catalog.

  Location: [tools/content/video_sources.py](C:/Users/user/Desktop/Projects/linnet/tools/content/video_sources.py) — `catalog_contains`.

  Completion check: Repeated checks require one catalog decode per unchanged snapshot; changed titles, missing files, and newly published entries remain visible.


**Keep browsing responsive and memory bounded**

- [x] **23 · P2 · Profile: Give decoded artwork a byte budget.** The cache is limited to 600 entries rather than decoded bytes. At 320 by 320 and four bytes per pixel, 600 images alone approach 234 MiB before backend overhead. Track retained image cost and tune the budget from scrolling measurements.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.receive`.

  Completion check: Peak memory is bounded without excessive rereads or visible cover flicker; include mixed small and large covers and high-DPI rendering.

  Verification note: The LRU tracks estimated pixmap bytes, evicts above 64 MiB, and retains the 600-entry ceiling for small and failed covers. Offscreen mixed-size and high-DPI cache checks passed. A real A1099 library of 1,222 album cards was scrolled through 19 positions plus quick reversals: the cache peaked at 12,606,400 bytes across 95 entries, while process RSS rose from 101,171,200 to 114,200,576 bytes. It stayed below the budget without evictions; four additional reads on reversal were deferred or newly visible covers, not forced rereads. The 64 MiB cap remains appropriate for this observed workload.

- [x] **24 · P2 · Profile: Coalesce artwork-completion repaints.** Every completed cover requests an update of every registered view. Measure redundant paints and schedule a shared update for visible views, retaining retries for deferred artwork requests.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.receive`.

  Completion check: A burst of completions causes fewer paints, visible covers still fill in, and the previously fixed deferred-details artwork case stays working.

  Verification note: In an offscreen Qt burst of 100 completions, two visible list views now receive one viewport update each instead of 100, while a hidden view receives none. A later completion schedules another update. A details artwork widget whose request was deferred by the six-request limit queued its own cover after another completion freed a slot; its direct completion signal remains in place.

- [x] **25 · P2 · Profile: Share sidecar discovery across artwork requests in one folder.** Separate requests for songs in one folder repeat the COVER_NAMES search. Consider a bounded, generation-scoped folder lookup shared safely by the artwork workers.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.read`.

  Completion check: Repeated folder probes fall while refresh invalidation, disappearing sidecars, embedded fallback, and concurrent requests remain correct.

  Verification note: Forty-one A1099 songs in one album previously required 82 cover-name file checks; shared positive lookup used 42, including a file-existence recheck for each song. The cache holds at most 256 folders and clears on artwork invalidation. Concurrent lookups, a removed or newly added sidecar, stale generation, and embedded-artwork fallback passed offscreen checks.

- [x] **26 · P2 · Profile: Reuse unfiltered album, artist, and genre cards.** Switching group views rebuilds memberships, subtitles, artwork choices, and byte totals. Profile a cache tied to the current row snapshot and grouping mode.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.render_library`.

  Completion check: Switching views gets faster; filtered groups are still derived from matching rows and refreshes cannot retain stale members or cover choices.

  Verification note: With A1099's 2,895 visible Music rows, five repeat renders of Albums, Artists, and Genres had median times of 4.23, 4.32, and 1.57 ms before caching, and 0.53, 0.58, and 0.13 ms afterward. All 1,222 album, 1,036 artist, and 292 genre cards matched the previous content and membership exactly. Search-filtered cards matched as well, and replacing the row snapshot dropped cached members from removed rows.

- [x] **27 · P2 · Profile: Preserve useful selection across equivalent model refreshes.** A full model reset clears selections even when most rows are unchanged. Investigate restoring stable row identities or using smaller model updates where measured worthwhile.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaModel.reset / MediaWindow.render_library`.

  Completion check: Selection follows the same media IDs through filtering, sorting, and refresh; removed items disappear and group selections cannot target stale files.

  Verification note: On A1099's Music library, two selected songs retained their IDs through table sorting and an equivalent render. Filtering to one matching song retained only that selection; removing it from a refreshed row snapshot cleared the selection. A selected album card survived a refresh with one member removed and expanded only to its current members. Device transitions clear the selection context.

- [x] **28 · P2 · Profile: Filter an open group from its current membership.** An open group constructs an ID set and scans all page rows to recover its members. Evaluate using the group's already-refreshed member snapshot directly.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.render_library`.

  Completion check: Opening and searching small groups avoids a whole-library pass while totals, album ordering, exclusions, and refresh replacement remain correct.

  Verification note: On A1099's 2,895-row Music library, repeated rendering of a 20-song open album fell from a 0.114 ms median to 0.041 ms over 20 renders. Member IDs and order matched the previous implementation with and without search, and after replacing the row snapshot and refreshing the group's members.

- [x] **29 · P2 · Code: Debounce and precompute video-picker searches.** Every keystroke rebuilds rows, repeatedly constructs Path objects, and folds the search text inside the list comprehension. Prepare immutable display/search fields once and debounce rendering.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.choose_videos`.

  Completion check: Typing in a large picker stays responsive, and hidden selections survive searches and acceptance exactly as before.

- [x] **30 · P2 · Profile: Restore video-picker selections in one model operation.** The picker calls selectionModel.select once for every selected row after each reset. Build a QItemSelection or contiguous ranges and apply them together.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.choose_videos`.

  Completion check: Many selected videos no longer generate one selection operation per row; noncontiguous selection and filtering preserve the chosen paths.

- [x] **31 · P3 · Profile: Cache playlist search text only if larger libraries justify it.** Filtering repeatedly reads and case-folds each item label. The recent 2,685-track check was already only a few milliseconds, so measure larger supported libraries before adding state.

  Location: [tools/studio/playlist_editor.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/playlist_editor.py) — `PlaylistEditor.filter`.

  Completion check: Keep a change only if it improves interaction measurably; Unicode matching, hidden selections, and Add-button behavior stay correct.

  Verification note: The actual A1099 library has 2,894 tracks. Across five offscreen Qt queries, median filtering time fell from 3.98 to 0.76 ms there, and from 19.44 to 3.58 ms for a 10,000-row library built from its labels. Every visible/hidden row matched the previous implementation. A Unicode `Straße`/`STRASSE` query preserved hidden selection, Add-button state, and the single visible track added to a playlist.

- [x] **32 · P2 · Profile: Update playlist rows incrementally after additions and removals.** Single-row moves now reuse their item, but add and remove still rebuild all members. Measure whether targeted insertions/removals improve large playlists enough to justify the extra bookkeeping.

  Location: [tools/studio/playlist_editor.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/playlist_editor.py) — `PlaylistEditor.add / remove / select`.

  Completion check: Order, duplicate track IDs, missing-track labels, limits, selection, scrolling, and button states match the existing behavior.

  Verification note: With a 1,000-song playlist from A1099's library, the median of 20 single-track add/remove cycles fell from 17.22/19.20 ms to about 0.01/0.01 ms. Incremental rows matched the previous editor after adding duplicates, removing noncontiguous rows including a missing-track label, and rejecting an addition over the 1,024-song limit. Counts, selection controls, and the scrollbar position in a visible dialog matched the previous editor.

- [x] **33 · P3 · Code: Use scoped signal blockers in remaining bulk UI updates.** Several bulk updates still pair blockSignals(True) with blockSignals(False) manually. Convert suitable sites to QSignalBlocker, and apply the same cleanup to PlaylistEditor.render.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `update_filters / choose_apple_folders / completed`.

  Completion check: The prior blocked state is restored even on failure; each bulk operation performs its intended final control update and does not emit intermediate user actions.

- [x] **34 · P3 · Profile: Reduce startup artwork conversion overhead.** Startup loads the same asset for three crops and uses per-pixel QColor access to derive transparency. Measure the actual startup-sized crops before choosing shared loading or a faster exact transformation.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `boot_artwork`.

  Completion check: Startup improves measurably with identical pixels, alpha, and device-pixel ratio; avoid adding a new dependency for a negligible gain.

  Verification note: The source pixmap is loaded once per process and the existing transparency calculation writes the ARGB32 buffer directly. All three startup crops matched the previous implementation byte for byte, including alpha, dimensions, and device-pixel ratio. Across five fresh offscreen GUI processes per version, median `MediaWindow` construction fell from 120.7 to 84.4 ms; the three-crop median fell from 40.4 to 9.3 ms. No dependency was added.


**Improve preparation and validation**

- [x] **35 · P2 · Profile: Reuse unchanged per-photo preparation between builds.** One changed photo currently causes the complete selected collection to be decoded and tiled again. Design a bounded cache for immutable per-image outputs, keyed by source identity and the complete rendering recipe.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `compile_photos`.

  Completion check: A one-photo update reuses unchanged work; full PIMG bytes match a clean build across orientation, titles, viewport, detail level, and additional iTunes sources.

  Verification note: A disposable 512 MiB host cache keys each bounded rendered image by source bytes, path, title, fallback reference, Pillow version, and rendering recipe. A one-photo edit reused three of four images and regenerated one; the complete PIMG matched a clean build byte for byte. Clean, warm, retitled, viewport/detail, EXIF orientation, JPEG fallback, and additional iTunes preview builds also matched the prior compiler byte for byte. Corrupt payload and metadata entries regenerated safely, including an invalid orientation with a recomputed entry digest. A1099 remained healthy after a guarded Disk Mode identity check; its existing 205 MB photo library was left intact.

- [x] **36 · P2 · Profile: Store photo tile CRCs more compactly.** tile_crcs retains a Python integer per tile while payloads are spooled. Measure peak memory on large valid packages and compare a packed integer array or equivalent bounded representation.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `compile_photos`.

  Completion check: Peak memory falls, package limits still apply before oversized work, and serialized metadata and payload bytes remain identical.

  Verification note: The packed unsigned-integer array compiled 64 prepared 512 × 512 JPEGs into 26,432 tiles and the same 54,878,208-byte PIMG with identical SHA-256 (`5a23f2a7...b1b97`) as the prior list implementation. In separate processes, traced Python peak fell from 6,656,327 to 5,920,839 bytes and sampled RSS peak from 38,440,960 to 33,603,584 bytes. Both paths completed in about 14.8 seconds; the existing tile and package bounds are checked before each level is tiled.

- [x] **37 · P2 · Code: Enforce the Notes count bound during traversal.** All matching documents are collected and sorted before the 256-note limit is checked. Stop collecting once the supported count is exceeded instead of retaining an arbitrarily large list.

  Location: [tools/content/notes.py](C:/Users/user/Desktop/Projects/linnet/tools/content/notes.py) — `compile_notes`.

  Completion check: Oversized folders fail early; exclusions, supported-file rules, link handling, and valid-folder ordering remain correct.

- [x] **38 · P2 · Profile: Decode new cover images once for playback and Cover Flow.** A new cover can be decoded by _cover_pixels and then decoded again by coverflow.original_cover. Evaluate sharing a decoded source while keeping each rendering recipe distinct.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `art_for / _cover_pixels`.

  Completion check: Playback RGB files and Cover Flow output remain byte-identical across alpha, EXIF, ICC profiles, and all artwork targets; image lifetime stays bounded.

  Verification note: New covers now open and decode once, then pass the loaded image through the separate playback and Cover Flow recipes; already-seen playback digests still skip Cover Flow rendering. A1099's real sidecar and A1136's real embedded cover produced byte-identical playback RGB565 and Cover Flow pixels for all four targets. Local alpha, EXIF-rotated, and ICC-tagged examples also matched. On A1099's sidecar, a warm ten-run median fell from 1.59 to 1.22 ms per paired render; file opens fell from two to one. The full-resolution image is closed after each cover, and only the bounded 96 × 96 Cover Flow image is retained.

- [x] **39 · P2 · Profile: Bound cancellation latency while waiting for music metadata.** Cancellation is checked around progress callbacks, but future.result and executor shutdown can wait for an active metadata parser or decoder. Measure the longest waits and thread cancellation through the underlying work.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `_metadata_rows / compile_music`.

  Completion check: Stop latency improves for slow inputs; subprocesses and worker tasks finish cleanly and no incomplete stage replaces the previous library.

  Verification note: Metadata futures now poll Stop, in-process tag and PCM readers check between reads, and a cancellation watcher terminates active FFprobe processes before the executor joins. With identical three-second stalled subprocesses, the previous metadata and frame probes waited 3.05 seconds; the new paths returned Cancelled in 0.35 and 0.31 seconds. A blocked metadata future returned in 0.31 seconds. On A1099's real music source, a cold cancelled import took 9.52 seconds from first progress before cancellable reads were added; a warm run with the new reader took 0.81 seconds, with the previous host stage marker intact. Old and new metadata matched for MP3, M4A, FLAC, and WAV; a one-track PDB matched byte for byte. A1099 returned to healthy Link after safe eject.

- [x] **40 · P2 · Code: Bound the persistent Cover Flow cache.** The embedded-image cache has a byte cap, but the coverflow table has no visible eviction policy. Add a measured size or age policy for disposable generated artwork.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `_MetadataCache.coverflow_get / coverflow_put`.

  Completion check: Repeated imports cannot grow this table indefinitely; eviction merely causes recomputation, and cache hits still verify stored digests.

  Verification note: Cover Flow rows hold 14,080-byte tiles; 4096 retained entries cap tile payloads at 55 MiB before SQLite overhead. Oldest inserted rows are pruned on opening an older cache, every 128 writes, and at close. An in-memory cache check covered opening an oversized table, pruning at close, retained hits, and damaged digest rejection.

- [x] **41 · P3 · Profile: Make metadata-cache commit accounting consistent.** Metadata and embedded-image writes use pending_writes, while Cover Flow writes rely on later commits. Initialization can also commit pending work. Trace actual transaction sizes before unifying the accounting.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `_MetadataCache.put / embedded_cover / coverflow_put / close`.

  Completion check: Commit frequency is predictable without excessive fsyncs; cancellation, partial batches, cache errors, and close preserve the disposable-cache fallback behavior.

  Verification note: A trace of 300 Cover Flow writes previously recorded no commit until close. The shared counter now commits every 128 mixed metadata, embedded-cover, or Cover Flow writes and commits a final partial batch on close. A 385-write mixed trace recorded three batch commits and one final commit; all rows reopened correctly. A 300-entry run with a 64-entry limit retained the newest 64. Embedded-cover maintenance resets the counter after its own commit.

- [x] **42 · P3 · Profile: Optimize Cover Flow cache misses only with unchanged rendering.** The recent isolated profile spent most tile time in Pillow quantization, with reflection work secondary. Profile representative art and cache-hit rates before changing the cold path.

  Location: [tools/content/coverflow.py](C:/Users/user/Desktop/Projects/linnet/tools/content/coverflow.py) — `_prepare_tile / _indexed_tile`.

  Verification note: Rebuilding A1099's published 798-art Cover Flow without supplied originals first exposed a fallback path that dropped `.LINNET`; that path is corrected and both complete passes validated. The first pass had one cache hit and 797 misses in 107.0 s: 58.4 s was thumbnail-file I/O, 45.1 s tile preparation, including 32.3 s in indexed quantization. The next pass had 798 hits, no misses, and finished in 1.69 s with byte-identical 11,876,352-byte output (SHA-256 `756539ef8076c311a6a0bd5a3dc99729049f4c28f97eb1c5192f1dbebd86870d`). A reflection-only rewrite would leave the dominant quantization and device-I/O costs, so no cold rendering change was added.

  Completion check: A retained optimization reduces measured preparation time and produces identical packed artwork; do not trade quantization quality for an unrequested recipe change.

- [x] **43 · P2 · Profile: Reduce repeated local reads during PIMG validation.** inspect checks metadata and payloads, then opens the file again for SHA-256; publication adds further hashing. Map the complete read sequence and evaluate hashing during an already-required ordered pass.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `inspect`.

  Completion check: Fewer full-file reads with every record, bounds, CRC, digest, and changed-file check preserved. Measure the complete compile-and-publish preparation path.

  Verification note: Full payload validation now hashes the header, metadata, thumbnails, and tile payloads in their existing ordered reads; metadata-only inspection retains its complete digest pass. On a 54,878,208-byte, 26,432-tile PIMG, measured process reads fell from 110,215,168 to 55,336,960 bytes and 323 to 111 read calls with identical SHA-256. Five runs of the local publication preflight (two separate change-detection hashes, inspection, and fallback extraction) had medians of 0.1618 s before and 0.1557 s after; the 64-photo compilation took about 14.8 s. A concurrent header change and a corrupted tile were rejected. The publisher's two independent hashes remain in place.

- [x] **44 · P2 · Profile: Measure a verified-copy fast path for compatible native videos.** Compatible input is inspected, copied, and inspected again through ffprobe. Determine whether a validated source plus verified byte-for-byte copying can avoid repeated probing without weakening source/output checks.

  Location: [tools/content/native_video.py](C:/Users/user/Desktop/Projects/linnet/tools/content/native_video.py) — `prepare`.

  Completion check: Use the fast path only with demonstrated equivalent guarantees for changed sources, truncated copies, container details, and target limits; otherwise retain reinspection.

  Verification note: A1136's compatible 22,234,203-byte H.264 MP4 produced byte-identical output (SHA-256 `3794fac87abc4bcfb5735725ff15dbab154d22fd9c37d1477405302a2a4decf5`) in three preparations. The first, cold-device run took 58.86 s; warmed runs took 0.265 and 0.297 s. Five warm probes had 0.125 s medians for both source and copy, while hashing either file took 0.016 s. A verified-copy path could save roughly 0.1 s warm but would need source identity checks before/after inspection and copying plus a complete output hash; it would barely affect the cold-device run. The existing second container probe remains in place until that extra complexity has a representative workload benefit.


**Simplify operations and make failures easier to handle**

- [x] **45 · P2 · Code: Split media preparation into focused per-kind helpers.** The main operation contains long music, photo, note, and video branches plus shared receipt and cleanup handling. Extract bounded helpers with explicit inputs and results.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_run`.

  Completion check: Publication order, checkpoints, outputs, receipts, source-error reporting, and partial completion remain unchanged; callers become easier to review.

  Verification note: Music, Photos, Notes, and Videos now enter separate preparation helpers while `_run` retains receipt, error, and cleanup handling. The moved video branch has the same Python AST apart from its explicit publication marker. Per-kind helper smoke checks, Python compilation, and Ruff F checks passed.

- [x] **46 · P3 · Code: Consolidate repeated host-state JSON loading.** Several modules repeat read/parse/type-check/default logic with slightly different exception handling. Identify the genuinely shared cases and give them a small helper with explicit defaults.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_run / skip_files / restore_skipped_files`.

  Completion check: Malformed, absent, and unreadable optional state behaves consistently; required-state failures are not silently converted into successful operations.

- [x] **47 · P2 · Code: Use unique temporary files for atomic host-state saves.** The writer uses a fixed .tmp sibling and lacks a finally cleanup around the full write/replace sequence. Use a shared, clearly owned atomic-write routine where existing callers have equivalent durability needs.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_save`.

  Completion check: A failed write preserves the prior JSON, cleans only its own temporary file, and cannot collide with another save; flushing and replacement guarantees remain explicit.

- [x] **48 · P2 · Code: Unify cancellation reporting across video backends.** IPVF reports cancellation as RuntimeError, while native video uses media_manager.Cancelled. Define a consistent internal cancellation contract and adapt public entry points deliberately.

  Location: [tools/content/ipvf_encode.py](C:/Users/user/Desktop/Projects/linnet/tools/content/ipvf_encode.py) — `encode_ipvf`.

  Completion check: Stop is never reported as corrupt source media or automatically skipped as a bad file; caller-visible behavior remains compatible where required.

- [x] **49 · P3 · Code: Share progress throttling without obscuring checkpoints.** Music and photo branches duplicate last-progress timing and message throttling. Extract only the common throttling behavior, keeping cancellation checks frequent and phase-specific messages clear.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_run music_progress / photo_progress`.

  Completion check: The last item is reported, fast batches do not flood Qt signals, and every required checkpoint still executes even when its message is throttled.

- [x] **50 · P2 · Profile: Resume source-error retries without restarting unrelated work.** After automatically excluding a problem file, run invokes the entire workflow again. Measure repeated scans, planning, and completed-kind checks, then isolate the affected preparation stage.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `run / _run`.

  Completion check: Several bad sources do not repeatedly redo unrelated work; completed publications are retained and uncertain publication failures are never replayed automatically.

- [x] **51 · P2 · Profile: Validate removal selections without rebuilding unrelated display metadata.** Removing selected items rebuilds the full library row set, including display metadata and artwork lookup. Investigate a lighter validated inventory for mutation decisions.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_remove / list_items`.

  Completion check: Removal remains tied to fresh paths, sizes, timestamps, removability, catalog state, and last-source retirement rules while avoiding unrelated artwork work.

  Verification note: On A1099, the lightweight post-lock removal inventory matched all 3,246 removable or retail-photo IDs from the full library, including category, kind, path, size, timestamp, and removability. With the required identity refresh included, inventory time fell from 5.34 to 3.61 s; Apple thumbnail records are validated without rendering previews, and music display metadata is omitted. A temporary Notes file was removed to the device Trash, restored byte for byte, then deleted; a stale Music size was rejected without creating a Trash entry. The selected UI title is carried into the receipt after its file identity is validated.

- [x] **52 · P2 · Code: Batch native MP4 chunk-map parsing.** stsz samples are read in bounded batches, but stsc still reads and unpacks 12 bytes per entry. Apply similarly bounded batching while preserving validation across batch boundaries.

  Location: [tools/content/native_video.py](C:/Users/user/Desktop/Projects/linnet/tools/content/native_video.py) — `_check_tables`.

  Completion check: Large tables use fewer Python reads/unpacks; ordering, sample counts, description IDs, short reads, and malformed tables are rejected correctly.

- [x] **53 · P3 · Code: Compute supported video extension sets once per picker render.** The source-selection comprehension calls video_source_extensions and native_video_extensions repeatedly for individual paths. Compute the sets once for the current identity and reuse them.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.choose_videos`.

  Completion check: The same source list is produced for every target profile, with fewer repeated set constructions and suffix conversions.

- [ ] **54 · P2 · Profile: Record whole-operation baselines alongside isolated improvements.** Use existing profiling commands and retained local media to separate discovery, traversal, metadata, conversion, validation, and publication time. Record warm and cold cases for rotating and flash storage.

  Location: [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py) — `inspect; related preparation entry points`.

  Completion check: Each accepted speed claim states its workload and scope, includes comparable repeated timings, and is not inferred solely from a microbenchmark. No new test infrastructure is needed.


**Build tooling and device-side investigations**

- [x] **55 · P2 · Code: Batch WSL path conversions.** The helper launches wslpath separately for the repository and every forwarded Windows path. Convert all required paths in one WSL call or reuse conversions within that invocation.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `wsl_command`.

  Completion check: Command arguments remain exact for spaces, Unicode, relative paths, and the configured distribution; process launch count drops.

  Local check: Two Windows paths and the repository root produced identical forwarded arguments. In a warm four-run comparison, the three-call version took 0.303 s and the batched version 0.092–0.096 s; this measures command construction only.

- [x] **56 · P2 · Code: Stream files into the build source hash.** Every source file is read into one bytes object before hashing. Stream large files while preserving the existing name-length, name, size, and content hashing format.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `source_identity`.

  Completion check: Unchanged inputs produce the exact same source identity with lower peak memory; files changing during hashing are detected or the build is retried explicitly.

  Local check: The 840-file source identity matched the prior byte-reading format. Paired warm calculations took 0.100–0.104 s streamed and 0.104–0.115 s with the prior method; the only file over 1 MiB was streamed.

  Follow-up: The before/after file metadata check now also covers small files. The guarded hash still matches the original digest format; one local warm read took 0.119 s, so the earlier timing comparison does not describe the final version.

- [x] **57 · P3 · Profile: Reuse verified toolchain fingerprints during a target matrix build.** Each build probes and hashes compiler, linker, objcopy, and nm executables. Measure repeated work, including tools that share the same underlying LLVM binary.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `toolchain`.

  Completion check: A single build session can reuse verified fingerprints without masking executable replacement, version mismatch, configuration changes, or distinct tool roles.

  Verification note: Five in-process WSL toolchain checks returned byte-identical records. Their warm median fell from 0.0405 s to 0.0021 s after the first verified lookup; the first check still measured about 0.04 s with warmed OS file cache. The bounded caches key versions by invocation path and file identity, and hashes by resolved file identity so shared binaries are hashed once while role-specific version output stays separate. A replaced executable, changed version pin, and file mutation during fingerprinting were all rejected or recomputed in local checks.

- [ ] **58 · P2 · Profile: Measure MP4 sample-table I/O on the device.** Packet processing requests small sample-size, chunk-offset, and sync-table reads. Measure how effectively the existing lower-level caches satisfy them before adding any new table cache.

  Location: [services/video/mp4.c](C:/Users/user/Desktop/Projects/linnet/services/video/mp4.c) — `read_at / ln_mp4_next / ln_mp4_seek_step`.

  Completion check: Any change lowers physical reads or seek latency on real media without increasing underruns, exceeding memory budgets, or breaking table bounds and seek behavior.

- [x] **59 · P2 · Profile: Measure photo panning and zooming at tile boundaries.** The viewer already has a viewport-sized tile cache, grouped reads, hints, and timing counters. Use those counters to identify remaining misses or repeated rendering during direction changes and zoom.

  Location: [services/photos/photos.c](C:/Users/user/Desktop/Projects/linnet/services/photos/photos.c) — `tile cache, tile_records, render phases`.

  Completion check: A targeted change improves frame-ready latency with identical visible output, bounded memory, correct cancellation, and no interference with audio playback.

  Verification note: On A1099, a matched photo 159 zoom and pan reversal fell from 79.8 ms and 21 physical sectors to 65.6 ms and one sector. The viewer screenshot CRC stayed `56381ec1`; returning to the grid reloaded its thumbnails. A settled viewer → grid → same viewer round trip also kept CRC `e602f4eb` after thumbnail writes invalidated overlapping tile metadata. Repeated pans during music playback produced zero audio underruns and zero silence frames. Both A1099 and A1136 booted development images, and Photo 4G, Video 5G, and Classic release builds passed their memory budgets.

- [x] **60 · P2 · Profile: Tune Cover Flow scheduling from cache and I/O measurements.** Cover Flow already has packed-art caches, decoded slots, preview fallback, and hit/miss counters. Measure rapid reversal, long traversal, and playback before tuning read scheduling or eviction.

  Location: [services/music/coverflow.c](C:/Users/user/Desktop/Projects/linnet/services/music/coverflow.c) — `cache / io_due / directional loading`.

  Completion check: Visible covers become ready sooner without extra idle disk activity, audio underruns, stale artwork, or regressions in existing device and simulator checks.

  Hardware check: After booting the exact development images, a cold traversal and reversal to album 192 produced a selected full cover in 54.6 ms on A1099 flash and 634.2 ms on A1136 rotating storage. The flash run's longest selected full-art latency was 124.0 ms. The rotating run reached its full cover while catalog loading continued; device-wide physical reads rose from 4349 to 4591 sectors during that interval, including concurrent startup work. After both caches settled, reversing away and back added zero physical sectors and left the same framebuffer CRC (`9fd58599` flash, `51e9143a` rotating). A separate warm long traversal to album 1024 and reversal on A1136 found 14 catalog misses but no additional full-art reads. Three 64-album reversals during playback kept player phase 4 and zero underruns. The existing priority and eviction behavior met this workload, so no scheduling change was made.

**Device additions, target policy, and porting**

- [x] **61 · P1 · Code: Declare game availability in the target manifest.** Game support is repeated as the same two-target tuple in host code and as target macros in settings code, while CAPABILITIES has no games entry. Introduce one explicit capability and use it for build inclusion, menu availability, and Media Manager controls.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/content/games.py](C:/Users/user/Desktop/Projects/linnet/tools/content/games.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [services/display/settings.c](C:/Users/user/Desktop/Projects/linnet/services/display/settings.c) — `CAPABILITIES / game availability`.

  Completion check: Existing targets keep their current game support; a new qualified target can enable games through its manifest without editing host target-name lists.

- [x] **62 · P2 · Code: Select game assets through an explicit presentation profile.** games.c chooses Photo court assets when the width is 220 and Video assets otherwise, with further target-owned graphics includes. Define supported game layouts and asset ownership explicitly instead of treating every other resolution as the Video layout.

  Location: [services/games/games.c](C:/Users/user/Desktop/Projects/linnet/services/games/games.c), [targets/photo4g-p98/games_graphics.h](C:/Users/user/Desktop/Projects/linnet/targets/photo4g-p98/games_graphics.h), [targets/video5g-m25/games_arcade.h](C:/Users/user/Desktop/Projects/linnet/targets/video5g-m25/games_arcade.h) — `game asset includes and layout selection`.

  Completion check: Unsupported resolutions fail clearly during content/build validation; current game pixels and behavior remain unchanged. Coordinate with item 61 before enabling games on another model.

  Verification note: A1099 ran the Photo development OS in RAM and rendered the Games menu, Comet Run, and Solitaire on its 220 × 176 framebuffer. Its saved Home menu was temporarily extended to expose Games, then restored byte for byte (SHA-256 `7e9e981b4ccaccb140cb0ecb78cae5f8f7f498726093d14cc1b1eea373623b36`). A1136 rendered the same three screens at 320 × 240 with its existing menu. Both original persistent OS images returned healthy. These observations used synthetic Link input and framebuffer captures.

- [x] **63 · P2 · Profile: Give editable menus a shared definition with stable item identifiers.** The host repeats menu labels, defaults, and required indices; Home index 7 changes from UI Demo to Games for certain targets. Design a shared menu definition for host and firmware, preserving the existing MENUS.BIN numbering and migration behavior.

  Location: [tools/studio/screen_settings.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/screen_settings.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [services/display/settings.c](C:/Users/user/Desktop/Projects/linnet/services/display/settings.c) — `SCREENS / DEFAULTS / REQUIRED / menu decoding`.

  Completion check: Labels, availability, defaults, and required navigation agree on every target, and previously saved menu files retain their meaning.

  Verification note: Host and firmware now consume one stable-ID definition. All four target defaults and availability sets were checked against compiled scenes; Video Settings is shown only where that scene exists and locked in the editor because firmware restores it automatically. An older MENUS.BIN fixture retained its Home Extras and Settings migration. Photo and Video development images booted in RAM on A1099 and A1136, reached healthy Link, and rendered Home and Settings through synthetic input.

- [x] **64 · P1 · Code: Report the precise failing target field.** Several manifest checks combine many unrelated fields into errors such as invalid target identity or invalid native video profile. Break these into named field and cross-field diagnostics that show the target, rejected value, and applicable bound.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py) — `_validate_identity / _validate_media / load_targets`.

  Completion check: An invalid dimension, decoder combination, duplicate alias, or memory region produces an actionable message while preserving all existing rejection rules.

- [x] **65 · P2 · Profile: Normalize target defaults once into a resolved specification.** Consumers repeatedly supply defaults for hal_family, capability booleans, clocks, and decoder selection. Define a resolved target representation alongside the source manifest so build, host media, and content code consume the same defaults without mutating shared target data.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [tools/content/compiler.py](C:/Users/user/Desktop/Projects/linnet/tools/content/compiler.py) — `target_spec / media_profile / manifest defaults`.

  Completion check: Resolved values for all existing targets match current behavior, callers cannot accidentally change shared defaults, and a newly added field has one documented default.

  Verification note: `resolve_target` supplies immutable effective values, with optional and capability defaults centralized in targets.py. Existing target values and media profiles were compared to the former defaults; mutation of resolved capabilities raises TypeError. UI outputs for all four targets matched byte for byte against the previous compiler. Verified OS builds passed for Q21, Photo, Video, and Classic. The new Photo and Video development images RAM booted on A1099 and A1136 respectively, and both reported healthy Link with the new build IDs.

- [x] **66 · P2 · Profile: Provide a disabled target scaffold.** The porting guide currently directs contributors to copy a complete existing target. Provide a small scaffold workflow that creates the manifest and conventional file skeletons with explicit placeholders, a bring-up blocker, build_enabled=false, and installer.enabled=false.

  Location: [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md), [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py) — `Add a model / disabled target validation`.

  Completion check: A scaffold is discoverable as an incomplete port, copies no specimen identity or qualified writer, and reports the remaining required fields and native files before builds can be enabled.

  Verification note: The scaffold creates an inert manifest, placeholder native files, and a bring-up README. Target validation accepts the disabled manifest, the target report lists missing HAL, codec, and target system configuration inputs, and build rejects the port while `build_enabled` is false.

- [x] **67 · P2 · Profile: Expose a read-only resolved target report.** doctor lists supported and bring-up targets, but source overrides, theme resolution, decoder choices, and memory reservations require reading several files. Add a target inspection view that explains these resolved choices and where each came from.

  Location: [tools/cli/main.py](C:/Users/user/Desktop/Projects/linnet/tools/cli/main.py), [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/content/compiler.py](C:/Users/user/Desktop/Projects/linnet/tools/content/compiler.py) — `doctor / _target_sources / presentation resolution`.

  Completion check: A contributor can inspect a disabled or enabled port without compiling or connecting hardware and see missing prerequisites, selected sources, capabilities, and memory ranges.

  Verification note: `python linnet target-report --target <id>` reads manifests and source/theme paths without invoking the compiler or probing a device. All four current targets report present prerequisites and their selected theme; an in-memory disabled-port check retained the bring-up blocker and showed its expected paths.

- [x] **68 · P2 · Code: Validate the complete build source set before compilation.** _target_sources validates conventional files, while build.py later adds SOURCES entries, optional blitters, codec groups, and feature sources. Resolve the final ordered source set in one preflight step, detect duplicates, and retain each selection's origin.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [hal/s5l8702/SOURCES](C:/Users/user/Desktop/Projects/linnet/hal/s5l8702/SOURCES) — `_target_sources / source-list assembly`.

  Completion check: Missing or duplicate selected sources fail before compiler work begins; existing targets retain their intended source and link order, including Boot versus OS differences.

  Verification note: The source list now records each selection origin in the build report and checks missing, external, and duplicate paths before starting compiler workers. Injected missing and duplicate S5L8702 SOURCES entries failed before compilation, then the original file was restored. Photo and Video OS source order matched prior reports after normalizing invocation paths; Photo Boot, Photo dev OS, Classic Boot, and Classic OS builds passed. The Classic OS check also exposed a color320 Home target mismatch, which was repaired and verified through all three target UI configurations.

- [ ] **69 · P2 · Profile: Move remaining private hardware dependencies behind portable interfaces.** storage.c directly includes PP502x disk-mode and S5L8702 AES headers despite the portable-layer contract. Review those operations and expose narrowly scoped HAL interfaces or adapters so adding a family does not grow storage-service hardware branches.

  Location: [services/storage/storage.c](C:/Users/user/Desktop/Projects/linnet/services/storage/storage.c), [hal/api/platform.h](C:/Users/user/Desktop/Projects/linnet/hal/api/platform.h), [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md) — `disk-mode include / selector_apple`.

  Completion check: Portable storage code no longer includes these family-private headers; retail handoff, decryption, quiescence, watchdog behavior, and target checks remain equivalent on qualified hardware.

- [x] **70 · P2 · Code: Replace remaining board-name UI and playback policies with named settings.** The music hint names Q21, the battery renderer names Photo, and native video priming names Classic. Record the actual reason for each exception and represent it as an explicit presentation or runtime policy where appropriate.

  Location: [services/music/ui.c](C:/Users/user/Desktop/Projects/linnet/services/music/ui.c), [ui/runtime/ui.c](C:/Users/user/Desktop/Projects/linnet/ui/runtime/ui.c), [services/video/native/player.c](C:/Users/user/Desktop/Projects/linnet/services/video/native/player.c) — `music hint / battery monochrome choice / START_AUDIO_FRAMES`.

  Completion check: Each existing exception keeps its behavior and rationale; a future target with the same requirement selects the policy without adding a target-name branch. Do not infer policy solely from resolution.

  Verification note: Q21 explicitly chooses the compact Menu hint, Photo keeps its color battery gradient independent of a theme's monochrome flag, and Classic starts native video with 12288 PCM frames (about 0.28 s at 44.1 kHz). Other targets retain their previous defaults. Release OS builds passed for all four targets, including a local Q21 content configuration, and Q21, Photo, and Classic simulators passed.

- [x] **71 · P2 · Code: Share relevant target defines with the simulator.** The simulator writes a target header containing only UI dimensions, while firmware generates a larger header and passes target defines; ui.c contains a Photo-specific rendering branch. Share the presentation-related definitions so simulation follows the intended target behavior.

  Location: [tools/simulator/runner.py](C:/Users/user/Desktop/Projects/linnet/tools/simulator/runner.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [ui/runtime/ui.c](C:/Users/user/Desktop/Projects/linnet/ui/runtime/ui.c) — `linnet_target.h generation / simulator compile command`.

  Completion check: Existing scene captures are reviewed for the intended target policy, and simulator/firmware presentation defines agree without pulling hardware-only code into the simulator.

- [x] **72 · P2 · Profile: Make Notes wrapping aware of the selected target and themes.** Notes currently wraps at 140 pixels and gathers fonts only from root themes. Profile and design target-aware wrapping using the resolved screen width and allowed fonts, including shared presentation and target-local themes.

  Location: [tools/content/notes.py](C:/Users/user/Desktop/Projects/linnet/tools/content/notes.py), [tools/content/compiler.py](C:/Users/user/Desktop/Projects/linnet/tools/content/compiler.py) — `_display_widths / _display_lines / compile_notes`.

  Completion check: Notes fit monochrome, Photo, and 320-pixel layouts; format limits and truncation stay explicit, and any new wrapping recipe participates in preparation identity.

  Verification note: The recipe resolves target and profile screens, allowed root/profile/target themes, font advances, list geometry, and target presentation width adjustments. It keeps the 31-character and 256-line limits, and its digest participates in preparation identity. Packages for Q21, Photo, Video, and Classic passed host width checks. Temporary packages rendered legibly on A1099 and A1136 screens; each exact package was removed after a hash check, and both devices returned to healthy Link.

- [x] **73 · P1 · Code: Bring the porting guide into agreement with source resolution.** The guide omits the HAL/target SOURCES convention and board.c/power.c fallbacks, and describes M25 screens as local although color320 is shared. Document the actual override rules and current validation entry points.

  Location: [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md), [docs/architecture.md](C:/Users/user/Desktop/Projects/linnet/docs/architecture.md), [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `Repository contract / Validate a port / source map`.

  Completion check: Every named path and command resolves in the current checkout, and a contributor can distinguish shared defaults, target overrides, extra sources, and available hardware validation procedures.

- [x] **74 · P2 · Code: Use a consistent per-target qualification record.** Video has BRINGUP and QUALIFICATION documents, while the Classic target directory lacks the same entry-point README. Define a compact common format for support state, hardware/storage variants, recovery requirements, known blockers, and evidence locations.

  Location: [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md), [targets/video5g-m25/QUALIFICATION.md](C:/Users/user/Desktop/Projects/linnet/targets/video5g-m25/QUALIFICATION.md), [docs/roadmap.md](C:/Users/user/Desktop/Projects/linnet/docs/roadmap.md), [docs/local-artifacts.md](C:/Users/user/Desktop/Projects/linnet/docs/local-artifacts.md) — `target status and qualification documentation`.

  Completion check: Each target has a discoverable status record; simulator results and physical-device evidence remain distinct, with private device identifiers and receipts kept in local artifacts.

  Verification note: `targets/README.md` now has a per-target qualification matrix with local checks, exact physical scope, recovery path, open checks, and evidence links. It distinguishes the manifest's accepted storage variants from qualified specimens and points private receipts to local artifacts.

- [x] **75 · P3 · Profile: Separate qualified Apple OS specimens from general model support.** apple_os.py embeds exact serial, volume, sector size, and model tuples directly in APPLE_DEVICES. Design a dedicated qualification-record boundary so adding an audited specimen does not require editing the media workflow itself.

  Location: [tools/content/apple_os.py](C:/Users/user/Desktop/Projects/linnet/tools/content/apple_os.py), [config/apple-os-qualified.toml](C:/Users/user/Desktop/Projects/linnet/config/apple-os-qualified.toml), [docs/apple-stock-music.md](C:/Users/user/Desktop/Projects/linnet/docs/apple-stock-music.md) — `qualified specimens / supported`.

  Completion check: Current exact-device gates remain equally strict, model capability never grants specimen authorization, and unsupported or missing qualification records stay disabled.

  Verification note: Exact A1238 and A1136 Apple OS tuples now live in `config/apple-os-qualified.toml`; the media workflow loads only complete records and fails closed on absent or invalid configuration. Synthetic checks passed for both exact matches, serial/volume/sector/filesystem/target mismatches, and missing or incomplete records. Compileall and Ruff F passed. Native A1136 Disk Mode is not the Apple volume and does not meet the gate.

**Build speed, branch switching, and host tooling structure**

- [x] **76 · P1 · Profile: Compile independent translation units with bounded concurrency.** build.py launches and waits for each compiler process sequentially. Measure a modest worker limit on the native and WSL toolchains, keeping source selection, header generation, and final linking ordered.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `per-source compile loop`.

  Completion check: Clean builds become faster within a bounded memory budget, diagnostics identify the failing source, failed workers cannot publish a successful report, and output is equivalent to the serial build.

  Verification note: Two compiler jobs are the default, with `--jobs 1..4` available. Earlier WSL runs took 24.4/13.4 s for Photo and 24.2/14.4 s for Video at one/two jobs. A current Photo release run took 23.33, 14.06, and 10.35 s at one, two, and four jobs. All three had identical build IDs and byte-identical ELF, LOS, and iPod images. An injected worker failure named the source and caused the build to raise before publication. The worker cap bounds concurrent compiler processes; header generation and linking stay ordered. This machine has no separate native Linux host for a second platform measurement.

- [x] **77 · P2 · Profile: Reuse unchanged object files with complete dependency keys.** Every build recompiles every selected source. Investigate an object cache keyed by compiler fingerprint, effective flags, source and included-header contents, target/profile, and generated inputs; keep whole-image provenance separate from object reuse.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `source_identity / compiler loop / generated headers`.

  Completion check: Clean and cached builds produce equivalent artifacts after source edits, header edits, configuration changes, and branch switches. Sources consuming linnet_build.h rebuild whenever image identity changes.

  Verification note: The compiler records the effective dependency set on misses; cached objects are reused only after every source, included header, generated input, compiler fingerprint, effective flag, and candidate include name matches. Cache entries and complete manifests are hash-checked and bounded to 1 GiB; `LINNET_OBJECT_CACHE=0` bypasses reuse. Source and header edits rebuilt 4 and 5 objects respectively, restoring the source reused all prior objects, and a changed theme rebuilt 4. Adding a higher-priority header invalidated reuse; its cached and uncached ELF and LOS matched. Other cached and uncached ELF and LOS images matched byte for byte across source, header, configuration, Photo, and Video builds. Photo and Classic warm runs reused all 114 and 179 objects, respectively, but on this WSL/NTFS host took about the same time as uncached builds (10.57 versus 10.56 s, and 13.38 versus 13.37 s); source identity, content generation, and file I/O dominate. Photo and Video development images RAM booted on A1099 and A1136; both reached healthy Link and rendered Home.

- [x] **78 · P1 · Code: Isolate intermediate output for concurrent builds.** Generated headers and object files share out/<profile>/<target>/<kind> even when build identities differ. Add explicit workspace ownership or per-invocation staging so two builds with different content, serials, or branch states cannot overwrite each other's inputs.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [docs/local-artifacts.md](C:/Users/user/Desktop/Projects/linnet/docs/local-artifacts.md) — `dest / generated / object outputs`.

  Completion check: Overlapping builds are either safely isolated or rejected clearly; each published report references its own complete artifacts, and sequential branch switching leaves no ambiguous intermediate state.

  Verification note: Two overlapping Photo release builds with the same identity wrote distinct invocation directories and produced identical image hashes. Every artifact path in each report stays inside its invocation directory; branch changes likewise get a fresh directory.

- [x] **79 · P2 · Code: Use collision-free object paths.** Object names flatten repository paths by replacing slashes with underscores, which can collide as directories and filenames grow. Preserve the source directory structure under an object root or use a deterministic unambiguous mapping.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `object filename construction`.

  Completion check: Different source paths always receive distinct object paths, generated sources remain covered, and link order and final firmware bytes are preserved.

  Verification note: The current Video source set has no flattened collisions, so its object names and linker map are unchanged. Two repeat builds had the same firmware hash. As expected, the source edit changes the embedded build identity, so binaries from before and after the edit are not byte-identical.

- [x] **80 · P2 · Code: Organize codec source and compiler rules by backend.** Build source lists and per-source optimization flags are spread across long branches for AAC, MP3, Vorbis, H.264, and MPEG-4. Group each backend's sources, include paths, flags, and rationale into a small explicit build description.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [third_party/aac/SOURCES](C:/Users/user/Desktop/Projects/linnet/third_party/aac/SOURCES), [third_party/pvmp4/SOURCES](C:/Users/user/Desktop/Projects/linnet/third_party/pvmp4/SOURCES) — `codec source selection / codec_flags`.

  Completion check: Each backend is reviewable in one place, ARM4 versus ARM926 assumptions remain explicit, and existing release exclusions, source order, warning exceptions, and optimization choices are unchanged.

  Verification note: Backend flags now travel with selected sources and are recorded in `source_selections`. Before/after builds using the same source tree and build identity produced byte-identical ELF and LOS files for Video OS, Photo OS, Classic OS (native H.264/MPEG-4), and size-tuned Classic Boot. Link order, existing release exclusions, and the block-source `-Os` exception remained intact.

- [x] **81 · P2 · Code: Split CLI command registration and execution by domain.** parser and main contain the full build, media, simulator, device, and installation command surface. Move cohesive command groups into modules while retaining one public linnet entry point and shared argument helpers.

  Location: [tools/cli/main.py](C:/Users/user/Desktop/Projects/linnet/tools/cli/main.py) — `parser / main`.

  Completion check: Existing command names, aliases, defaults, exit codes, JSON output, and WSL forwarding remain compatible; adding a domain command no longer expands both central functions.

  Verification note: Command registration and execution now live in studio, media, and device modules with shared argument groups; the public entry and Windows WSL forwarding stay in main. A recursive parser comparison against the previous CLI found identical actions, choices, defaults, help, and ordering. Target report, missing media inputs, invalid report ID, and live A1136 device info produced matching output and exit codes before and after the split. Compileall and Ruff F passed.

- [x] **82 · P2 · Code: Reject invalid build requests before hashing the toolchain.** build resolves and fingerprints the toolchain before checking the requested probe, development serial, and Boot selector combination. Perform cheap request validation first, followed by source/configuration preflight and expensive tool discovery.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `build argument checks / toolchain`.

  Completion check: Invalid requests fail promptly with the same intended validation message; valid requests still enforce pinned tool versions and fingerprints.

**Media Manager workflow and maintainability**

- [x] **83 · P2 · Code: Separate Media Manager pages from the main window controller.** MediaWindow owns page construction, selection, queue management, device state, installation controls, and a large completion dispatcher. Extract cohesive page components and small controllers with explicit state dependencies.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow / build_* / completed`.

  Completion check: Page behavior and settings remain compatible, widget work stays on the GUI thread, and changes to one workflow do not require editing unrelated page logic. This complements the preparation split in item 45.

  Verified: Six page builders and the Games and Screens controllers now have explicit window dependencies. An offscreen Qt run constructed all six pages, navigated their controls, moved and reset a screen item, and closed cleanly; compilation and focused Ruff checks passed.

- [x] **84 · P2 · Profile: Give background jobs explicit context and results.** work and completed route operations through string tags, mutable window state, and an error string. Define an operation context containing the captured device identity, operation ID, cancellation contract, and structured outcome; use explicit completion handlers.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Events / work / completed`.

  Completion check: Completions apply only to the device and operation that started them, unknown outcomes fail clearly, and cancellation, partial success, and failure are distinguishable without parsing messages.

  Verification note: Jobs now capture device identity, operation ID, and a per-operation cancellation contract; outcomes carry success, partial, cancelled, or failed status plus error type. Completion rejects stale IDs and changed devices, reports unknown tags/status, and dispatches named handlers. The moved handler bodies match the prior Python AST except for the deliberate device snapshot in Scan. Offscreen window, worker, routing, and cancellation checks, Python compilation, and Ruff F passed.

- [x] **85 · P1 · Code: Reuse the setup assessment already produced during a scan.** media_status.inspect calls installer.assess but returns only selected assessment fields. When the setup page is active, completed('scan') immediately schedules installer.assess again. Carry the full read-only assessment with the scan result for that page.

  Location: [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `inspect / completed scan / setup`.

  Completion check: One refresh performs one setup assessment and displays that result consistently; writes still perform their own required current-device validation, and later refreshes replace stale assessments.

- [x] **86 · P2 · Code: Load skipped-file details through the background worker.** review_skipped invokes media.list_skipped_files directly from the GUI callback before opening its dialog. Load those details asynchronously and report loading, empty, and failure states through the existing worker mechanism.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `review_skipped`.

  Completion check: Opening a large skipped list keeps the window responsive, and returned rows remain bound to the selected device. Existing retry and source-exclusion behavior is preserved.

- [x] **87 · P1 · Code: Validate saved FFmpeg and FFprobe locations before declaring readiness.** update_tools reports ready when both stored path strings are nonempty; locate_tools can retain an older path for a tool missing from the newly selected folder. Resolve and validate the selected pair in a worker, with distinct actionable errors.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `__init__ / locate_tools / update_tools / prepare`.

  Completion check: Moved or missing tools are caught before a conversion starts, readiness reflects the validated executables, and replacing either executable invalidates its cached readiness result.

- [x] **88 · P2 · Profile: Keep queue completion state per submitted source.** The prepare completion handler removes every submitted queue entry only when the whole operation is complete. Carry per-source outcomes through the existing receipt so successful, skipped, and unfinished sources can be presented and retried separately.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `completed prepare / submitted / operation receipt`.

  Completion check: A partial failure leaves only actionable work queued, successful publication is not repeated needlessly, and skipped sources remain visible with their reason and retry action.

  Verification note: Receipts now carry per-submitted-source outcomes. Completed original copies or video publications leave the queue even when another source fails; skipped and unfinished entries retain their reason and retry guidance in the queue and saved device draft. Copy, published-video, incomplete-copy, missing-plan, and skipped-source matching were checked with synthetic records. Compileall and Ruff F passed. The A1136 read-only Notes operation from item 92 exercised the revised receipt path without changing its media.

- [x] **89 · P2 · Profile: Preserve a device-bound preparation draft across restarts.** Queued sources and selected videos currently live in memory, while a few presentation preferences use QSettings. Persist a small versioned preparation draft keyed to stable device identity, then revalidate source paths and capabilities when reopening it.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `pending / video_selection / QSettings / refresh`.

  Completion check: Restarting restores an understandable draft for the same device, stale sources are flagged, and switching devices cannot silently apply another device's queue or video selection.

  Verification note: Version 2 QSettings drafts bind target, disk serial, and volume serial. Selected video paths are stored relative to the device so drive-letter changes can be remapped. Queue sources are rechecked on load and refresh; missing or unavailable entries remain visible with a reason and block their selected preparation. Removed device videos are reported. A temporary-settings check verified restart restoration, drive remapping, a missing source warning, and isolation between two device identities. Compileall and Ruff F passed.

- [x] **90 · P1 · Profile: Make all, selected, and no video conversions explicit.** An empty video_selection currently means all existing videos, including after the picker selection is cleared or intersected with a refreshed inventory. Represent selection mode separately from its member set and describe the resulting conversion scope clearly.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `choose_videos / update_preparation / video_jobs`.

  Completion check: Selecting no conversions never expands to all conversions after refresh, and selecting all remains intentional. Preserve the separate automatic inclusion of compatible device-format videos.

- [x] **91 · P2 · Profile: Show the preparation plan before starting substantial work.** plan already computes copy counts, source previews, free device space, computer free space, and conversion need, but prepare mainly uses its conversion flag. Present a concise plan with reusable outputs and space estimates, including unknown conversion sizes.

  Location: [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `plan / prepare`.

  Completion check: Users can see what will be copied, prepared, reused, or excluded and which volume needs space; execution revalidates changing conditions and no estimate is presented as guaranteed. Reuse item 02's scan work.

  Verification note: Preparation now runs a read-only plan in the existing worker and presents a bounded review before starting. It shows selected types, original-copy counts and bytes by kind, host and iPod free space, video jobs, likely reusable libraries from the current scan, skipped queue entries, and the unknown conversion-size caveat. The actual operation still refreshes identity and rechecks sources, space, signatures, and outputs. On A1136 native Disk Mode, the plan reported zero queued copies and seven existing video jobs; a read-only README.md Notes candidate reported one 5,787-byte copy; a matching saved Music signature appeared as likely reusable. Compileall and Ruff F passed.

- [x] **92 · P2 · Profile: Show whole-operation progress and the current stopping boundary.** Detailed percentages currently describe video conversion/checking, while the main progress bar remains indeterminate. Define stage-aware progress for copying, preparing, checking, and publishing, and expose whether the current stage can stop immediately or must finish its guarded write.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `show_conversion_progress / work / stop / _run`.

  Completion check: Progress never claims the entire operation is complete while verification or publication remains, and cancellation feedback matches the actual stopping boundary without reducing existing cancellation checks.

  Verification note: Structured stage events now cover batched copy and verification, scanning, per-kind preparation, publication, final checks, and cleanup. The UI caps its overall bar below 100% until completion, retains detailed video conversion feedback, and disables Stop during guarded publication and cleanup. Existing checkpoints remain in place. An offscreen Qt check confirmed monotonic stage values and Stop state transitions; compileall and Ruff F passed. A read-only empty Notes operation on A1136 in native Disk Mode emitted the expected five stages and completed without errors; the device returned to healthy Link after safe eject.

- [x] **93 · P1 · Code: Report discovery failures per candidate device.** discover identifies mounted candidates in one list comprehension; one failing candidate aborts the result for all devices. Collect validated candidates and bounded per-candidate errors so one unreadable or unsupported iPod does not hide another valid one.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `discover / completed devices`.

  Completion check: A valid connected device remains selectable when another candidate fails; failed candidates cannot reach write actions, and the UI explains the detection issue without weakening identity checks.

- [x] **94 · P2 · Code: Link preparation summaries to their detailed receipts.** The backend already saves a receipt, but the window reduces results to a summary and error-message lines before refresh replaces the status text. Add an operation-details view or local receipt link that retains per-file outcomes and skipped reasons.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `run receipt / completed prepare / prep_results`.

  Completion check: After refresh, users can still inspect the last operation's completed, skipped, and failed work and its saved receipt; local source paths and device data are not published externally.

- [x] **95 · P2 · Code: Centralize device-session reset behavior.** The no-device, changed-device, and ejected branches independently reset artwork, menus, games, rows, setup state, selections, and readiness. Extract one device-session transition routine with explicit handling for user drafts and display state.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `completed devices / completed eject / update_device`.

  Completion check: Disconnect, reconnect, selection of another iPod, and safe eject consistently clear device-derived state while retaining only explicitly device-bound drafts and applicable user preferences.

  Verification note: The shared transition resets device rows, artwork, setup, game/screen state, video selection, filters, and capacity. Queued computer sources and the last receipt remain bound to their iPod across disconnect/eject, then clear on a different iPod; view settings remain user preferences. Offscreen checks covered disconnect, same-device reconnect, device switch, discovery with no devices, and eject.

- [x] **96 · P2 · Code: Unify the Media Manager launch path and import errors.** media_app.launch catches every ImportError as a missing PySide6 dependency, while the CLI has a separate narrower ModuleNotFoundError path. Route both launchers through one helper that identifies missing Qt packages without disguising unrelated import failures.

  Location: [tools/studio/media_app.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_app.py), [tools/cli/main.py](C:/Users/user/Desktop/Projects/linnet/tools/cli/main.py) — `launch / media command`.

  Completion check: Missing PySide6 or shiboken6 produces the installation guidance; unrelated import problems retain their actual diagnostic, and both launch entry points behave consistently.

**Device scheduling, power, memory, and rendering**

- [ ] **97 · P2 · Profile: Measure service fairness under sustained executive load.** ln_exec_take always scans service queues from index zero; metrics aggregate accepted, processed, dropped, and maximum latency. Measure per-service latency under combined input, display, media, and transport load before considering a different fairness policy.

  Location: [kernel/executive.c](C:/Users/user/Desktop/Projects/linnet/kernel/executive.c), [kernel/runtime.c](C:/Users/user/Desktop/Projects/linnet/kernel/runtime.c) — `ln_exec_take / executive service loop`.

  Completion check: Any scheduling change reduces demonstrated starvation or tail latency while preserving deliberate priorities, watchdog progress, button handling, and audio continuity.

- [ ] **98 · P2 · Profile: Measure idle wake sources and clock-switch break-even.** ln_runtime_idle already computes service deadlines, caps its fallback wait, and lowers the clock only for waits of at least 20 ms under strict conditions. Attribute wakeups and measure the actual energy and latency tradeoff before adjusting thresholds.

  Location: [kernel/runtime.c](C:/Users/user/Desktop/Projects/linnet/kernel/runtime.c) — `ln_runtime_idle / idle_clock_cycles / idle_clock_us`.

  Completion check: Representative battery and external-power sessions show fewer unnecessary wakes or lower energy use without changing active audio/storage clocks, increasing missed deadlines, or compromising wake reliability.

- [ ] **99 · P2 · Profile: Tune block read-ahead against physical I/O amplification.** The block layer has two cache ways, sequential-read detection, bounded read-ahead, request merging, and power management. Compare physical sectors read versus requested sectors during mixed browsing and playback on rotating and flash storage.

  Location: [services/storage/block.c](C:/Users/user/Desktop/Projects/linnet/services/storage/block.c) — `cache / sequential ceiling / read_ahead_sectors`.

  Completion check: Any tuning improves measured latency or disk activity rather than only cache-hit counts, preserves deadlines and write barriers, and does not cause additional wake cycles or audio underruns.

- [ ] **100 · P2 · Profile: Measure the competing background work budgets during playback.** Music controller scheduling contains separate reserves and bounded loops for audio, visible artwork, photos, metadata, history, and next-track preparation. Use existing counters and timing spans to identify which budget limits responsiveness at track boundaries.

  Location: [services/music/controller.c](C:/Users/user/Desktop/Projects/linnet/services/music/controller.c), [services/music/player.c](C:/Users/user/Desktop/Projects/linnet/services/music/player.c), [kernel/runtime.c](C:/Users/user/Desktop/Projects/linnet/kernel/runtime.c) — `background reserve / metadata budget / render admission`.

  Completion check: A targeted adjustment improves a measured interaction while preserving gapless transitions, PCM reserve, bounded service time, and existing storage-priority behavior.

- [ ] **101 · P2 · Profile: Measure avoidable settings publications during rapid interactions.** Settings already track dirty state and revision snapshots, yet resume, menu, and theme interactions can repeatedly make state publishable. Count completed writes and disk wakeups during scrolling, zooming, and repeated preference changes before introducing bounded coalescing.

  Location: [services/display/settings.c](C:/Users/user/Desktop/Projects/linnet/services/display/settings.c), [services/state/store.c](C:/Users/user/Desktop/Projects/linnet/services/state/store.c), [kernel/runtime.c](C:/Users/user/Desktop/Projects/linnet/kernel/runtime.c) — `settings_work / settings_step / ln_state_publish`.

  Completion check: Only measured redundant writes are reduced; acknowledged theme frames, revision matching, shutdown flushes, readback verification, and recovery behavior remain intact.

- [ ] **102 · P2 · Profile: Measure native video startup and buffer usage by decoder.** The native player reserves 64 cache slots and three frame buffers and already tracks index-ready, first-present, audio-start, decode, and lateness timing. Compare these stages and cache usage for each supported decoder before changing buffer counts or priming policy.

  Location: [services/video/native/player.c](C:/Users/user/Desktop/Projects/linnet/services/video/native/player.c), [services/video/native/decoder.c](C:/Users/user/Desktop/Projects/linnet/services/video/native/decoder.c) — `CACHE_SLOTS / pixels / startup timing fields`.

  Completion check: A proposed buffer or startup adjustment improves measured first-frame latency or memory usage without worse steady playback, seek behavior, audio synchronization, or decoder bounds. Keep MP4 table I/O work in item 58 separate.

- [ ] **103 · P2 · Profile: Measure framebuffer preservation and transfer costs for small updates.** Classic's framebuffer accessor copies the last presented frame when the draw buffer is invalid, and presentation sends the frame through the panel driver. Measure status-only updates and list movement before considering damage tracking or a narrower transfer path.

  Location: [targets/classic6g-n25/display.c](C:/Users/user/Desktop/Projects/linnet/targets/classic6g-n25/display.c), [targets/classic6g-n25/panel.c](C:/Users/user/Desktop/Projects/linnet/targets/classic6g-n25/panel.c), [kernel/runtime.c](C:/Users/user/Desktop/Projects/linnet/kernel/runtime.c) — `ln_display_framebuffer / ln_display_present / render timing`.

  Completion check: Any optimization lowers measured copy or transfer work with identical screenshots, valid alternating buffers, correct theme-frame acknowledgement, and no tearing on hardware.

- [x] **104 · P2 · Profile: Report useful memory headroom for each target and profile.** Build reports include allocated sections and limits, and linker scripts already protect reserved regions. Add a readable breakdown of resident memory, stacks, staging, artwork, and retained areas, with measured high-water data kept distinct from static reservations.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [hal/pp502x/memory.ld](C:/Users/user/Desktop/Projects/linnet/hal/pp502x/memory.ld), [hal/s5l8702/memory.ld](C:/Users/user/Desktop/Projects/linnet/hal/s5l8702/memory.ld), [kernel/executive.c](C:/Users/user/Desktop/Projects/linnet/kernel/executive.c) — `report.memory / linker assertions / arena high-water marks`.

  Completion check: A port or feature change can be compared against its prior memory budget without double-counting overlapping lifetimes; existing overlap assertions and hardware qualification requirements remain authoritative.

  Verification note: Build reports now separate linked resident extent and headroom from the stack subset, artwork sections, staging, recovery, and retained regions. Runtime high-water is explicitly unmeasured. Existing Photo, Video, Classic, Q21, Boot, and dev section reports produced plausible nonnegative headroom; a fresh Photo release report contains the breakdown and still passes the linker and release checks.

**File organization, ownership, and reviewable cleanup**

- [x] **105 · P2 · Code: Document ownership and regeneration of generated target assets.** Boot fonts, disk-screen runs, game graphics, and court assets sit beside native target sources, while generation entry points live elsewhere. Add a small asset index identifying authoritative inputs, generator commands where available, output paths, licenses, and manually maintained assets.

  Location: [tools/studio/boot_menu_font.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/boot_menu_font.py), [tools/studio/disk_screen_asset.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/disk_screen_asset.py), [targets/photo4g-p98/boot_menu_font.h](C:/Users/user/Desktop/Projects/linnet/targets/photo4g-p98/boot_menu_font.h), [targets/photo4g-p98/disk_screen_runs.h](C:/Users/user/Desktop/Projects/linnet/targets/photo4g-p98/disk_screen_runs.h) — `generated asset ownership`.

  Completion check: Each listed asset has a reproducible command or an explicit manual-source designation; regeneration is deterministic and preserves license/provenance information without moving build output into Git.

  Verification note: The two Photo generators reproduced their checked-in headers after line-ending normalization. The target guide now lists their inputs, commands, font license, and the direct-source/CC0 provenance of each game presentation header.

- [x] **106 · P2 · Profile: Clarify shared host-media boundaries.** Media helpers import private symbols such as _plain, _volume_guard, _save, and scan helpers across publication, library, planning, and settings modules. Define a small supported internal API for identities, guarded paths, scans, and receipts, then migrate callers incrementally.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py), [tools/content/publish.py](C:/Users/user/Desktop/Projects/linnet/tools/content/publish.py), [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py), [tools/studio/screen_settings.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/screen_settings.py) — `cross-module private imports`.

  Completion check: Shared invariants have one owner, circular workflow dependencies are reduced, and moving a helper does not bypass publication checks or silently change error handling. Coordinate persistence changes with items 46–47.

  Verification note: Guarded paths and device identity checks now have supported imports through `tools.content.guard`, read-only inventory traversal and fingerprints live in `tools.content.inventory`, and host cache paths and atomic JSON receipts live in `tools.content.host_state`. Status, library, trash, Apple OS, Media Manager, and screen settings callers use those boundaries. The moved scan and receipt bodies match the prior Python AST after naming changes; module imports, a read-only scan, compilation, and Ruff F checks passed.

- [x] **107 · P3 · Code: Index vendor provenance and local build adaptations.** Dependency metadata is spread among PROVENANCE.md, README.linnet.md, LICENSE, NOTICE, and SOURCES files, while compiler exceptions live in build.py. Add a central index linking each dependency's origin, license, local changes, and integration rules.

  Location: [third_party/aac/PROVENANCE.md](C:/Users/user/Desktop/Projects/linnet/third_party/aac/PROVENANCE.md), [third_party/vorbis/README.linnet.md](C:/Users/user/Desktop/Projects/linnet/third_party/vorbis/README.linnet.md), [third_party/flac/README.linnet.md](C:/Users/user/Desktop/Projects/linnet/third_party/flac/README.linnet.md), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `vendor documentation and build integration`.

  Completion check: A reviewer can trace every included codec to its existing provenance and local adaptations; unknown version or patch information is marked for investigation rather than invented.

  Verification note: `third_party/README.md` now indexes all eight vendor directories with provenance, license, adaptations, and build selection/flags. The repository README links it; local links resolve. Unknown exact upstream revisions for h264bsd and PacketVideo are explicit.

- [x] **108 · P2 · Profile: Provide an artifact inventory before any cleanup of local output.** out contains builds and scratch results, but local-artifacts.md warns that plans can depend on exact paths, backups, predecessor files, and receipts. Design a read-only inventory showing artifact type, source identity, target, size, and known receipt/plan references before proposing retention rules.

  Location: [docs/local-artifacts.md](C:/Users/user/Desktop/Projects/linnet/docs/local-artifacts.md), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [tools/studio/native_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/native_bootstrap.py), [tools/studio/installer.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/installer.py) — `build reports / installation plans / recovery artifacts`.

  Completion check: Builds from earlier branch states are identifiable, durable recovery dependencies are protected, and unknown or in-use artifacts remain retained. Any later cleanup must be explicit and separate from inventory.

  Verification note: The read-only inventory recognized 882 reports across existing invocation layouts, including 662 with content IDs; it found 8 recovery records, 43 referenced files, and retained 37,665 unclassified files. The scan reported no errors. No cleanup occurs.

- [x] **109 · P3 · Code: Expand dense control flow in the modules being changed.** Several core modules compress multiple state updates and conditional actions onto single lines. Apply focused readability cleanup around future changes, especially manifest validation, build rules, job completion, and executive state transitions; avoid a repository-wide formatting pass.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [kernel/executive.c](C:/Users/user/Desktop/Projects/linnet/kernel/executive.c) — `dense conditionals and state transitions`.

  Completion check: A reviewer can follow ownership, early returns, and failure paths without reconstructing semicolon chains; behavior and outputs remain equivalent, with formatting kept local to the substantive work.

- [x] **110 · P3 · Profile: Make bootstrap tooling roles easier to find.** tools/studio holds desktop UI alongside image builders and guarded native maintenance, while tools/link contains the corresponding device transports. Clarify the naming and module layout for build, plan, package, transfer, and execute responsibilities before moving files.

  Location: [tools/studio/s5l_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/s5l_bootstrap.py), [tools/link/s5l_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/link/s5l_bootstrap.py), [tools/studio/native_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/native_bootstrap.py), [tools/studio/native_package.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/native_package.py) — `bootstrap module responsibilities`.

  Completion check: A contributor can locate each stage from one workflow map; any later reorganization preserves CLI/import compatibility, keeps hardware-family code explicit, and retains exact-device checks and hash-pinned plans.

  Verification note: `docs/bootstrap-tooling.md` maps each stage to its current module and public command, distinguishes PortalPlayer directory installation from Classic SRAM/NOR work, and links exact-device and recovery requirements. The architecture guide links the map.

**Starting sequence**

Take items 01–07 first for contained build, planning, browsing, and batch-operation improvements. Then address cancellation and error handling in 08–12. Larger caches, shared snapshots, and validation changes should follow their profiling steps. Device investigations require the existing device-specific checks and appropriate hardware; desktop-only results do not certify firmware behavior.

For the added work, start with field diagnostics and porting documentation (64, 73), duplicated setup assessment (85), tool readiness (87), and per-device discovery results (93). Address output ownership (78) before supporting concurrent build invocations; measure bounded translation-unit concurrency (76) within that contract. Resolve capabilities and asset selection (61–62) before expanding game support. Broader module moves and shared schemas should follow the small fixes, with the dependent items implemented in separate reviewable batches. No branch creation, branch switching, or publishing is required by this backlog.

Earlier measurements are useful constraints: cold Apple metadata loading was dominated by device filesystem work; a previous path-lookup rewrite did not materially improve that workload. Photo tile packing improved in isolation without a reliable whole-package speedup, and playlist filtering at roughly 2,700 songs was already fast. Revisit these only with evidence that the workload or approach has changed.
