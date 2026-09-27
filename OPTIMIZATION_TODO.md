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

- [ ] **13 · P2 · Profile: Avoid rescanning adoption receipts on every device refresh.** A refresh may scan and parse session receipts to find an Apple Disk Mode cache. Measure this on a cache with many receipts, then reuse a validated adoption result with explicit invalidation.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_retail_cache_serial`.

  Completion check: Repeated refreshes read fewer receipts without carrying an adoption across a changed volume, partition, target, disk geometry, or relevant cache state.

- [ ] **14 · P2 · Profile: Consolidate redundant full identity refreshes within one operation.** run refreshes identity before taking the mutex and _run refreshes again; skip handling can add further full refreshes. Trace these calls and distinguish required boundary checks from redundant discovery.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `run / _run / refresh`.

  Completion check: Fewer expensive discovery calls with the same rejection of device changes; keep the per-write volume guards and required checks after locking.

- [x] **15 · P2 · Code: Resolve video catalog paths once per library refresh.** Catalog paths are validated in _catalog, resolved again to build published_paths, and resolved again when published rows are created. Return or retain the validated mapping for that read-only refresh.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_catalog / list_items / _device_path`.

  Completion check: The catalog produces identical rows and errors with fewer path queries; missing files and changed paths are handled at the appropriate operation boundary.

- [ ] **16 · P2 · Profile: Reuse scan evidence when building published music rows.** The directory inventory already supplies paths, but reading the prepared music database performs per-track _plain and resolve calls again. Measure their share of refresh time before designing scoped reuse.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_music_metadata / list_items`.

  Completion check: Read-only refresh gets faster on the actual device while escaped paths, reparses, missing sources, and database references outside the scan remain correctly handled.

- [x] **17 · P2 · Profile: Remove duplicate path resolution while parsing Apple tracks.** _path resolves a track to check containment, and _tracks resolves it again for the dictionary key. Consider returning both the original path and its validated resolved identity.

  Location: [tools/content/retail_media.py](C:/Users/user/Desktop/Projects/linnet/tools/content/retail_media.py) — `_path / _tracks`.

  Completion check: Apple track rows and key normalization remain identical, including the supported Music traversal form; unsafe paths remain rejected.

- [ ] **18 · P2 · Profile: Reuse thumbnail-file metadata within one Apple image scan.** Many image records can reference the same .ithmb file, but candidate handling repeats path validation and stat calls. Measure the duplication and use a call-local file snapshot where appropriate.

  Location: [tools/content/retail_media.py](C:/Users/user/Desktop/Projects/linnet/tools/content/retail_media.py) — `images`.

  Completion check: Fewer repeated filesystem queries with the same chosen thumbnail, bounds validation, cache invalidation, and behavior when a source file changes.

- [ ] **19 · P2 · Profile: Reuse bounded readers for shared Apple thumbnail files.** Uncached previews open and seek a thumbnail file separately for each image. Investigate a small set of readers, or contiguous read batches, scoped to one extraction.

  Location: [tools/content/retail_media.py](C:/Users/user/Desktop/Projects/linnet/tools/content/retail_media.py) — `images`.

  Completion check: Cold extraction reduces opens or seeks; all handles close on failure, memory remains bounded, and extracted preview pixels match.

- [x] **20 · P2 · Code: Stop repeated ancestor walks in Apple folder discovery.** Each file climbs through every parent even when those parents were already added by another file in the same folder. Stop once the remaining ancestor chain is already known.

  Location: [tools/content/apple_os.py](C:/Users/user/Desktop/Projects/linnet/tools/content/apple_os.py) — `_folder_rows`.

  Completion check: The same folder choices and ordering are returned for deep trees, with less repeated parent construction on large albums.

- [ ] **21 · P2 · Profile: Measure metadata cache work for rows already covered by Apple or Linnet metadata.** The function prefetches and validates host metadata before using Apple or published fallbacks. Profile warm and cold paths to identify rows whose cache work can safely be avoided.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_source_music_metadata`.

  Completion check: Reduce work only where metadata precedence is preserved: cached edits, album artists, duration, track/disc numbers, and artwork remain correct.

- [x] **22 · P2 · Code: Reuse a validated video catalog during unchanged-video checks.** The same small catalog is opened and decoded for each video cache hit. Load an indexed snapshot once for an unchanged batch and invalidate or update it whenever publication changes the catalog.

  Location: [tools/content/video_sources.py](C:/Users/user/Desktop/Projects/linnet/tools/content/video_sources.py) — `catalog_contains`.

  Completion check: Repeated checks require one catalog decode per unchanged snapshot; changed titles, missing files, and newly published entries remain visible.


**Keep browsing responsive and memory bounded**

- [ ] **23 · P2 · Profile: Give decoded artwork a byte budget.** The cache is limited to 600 entries rather than decoded bytes. At 320 by 320 and four bytes per pixel, 600 images alone approach 234 MiB before backend overhead. Track retained image cost and tune the budget from scrolling measurements.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.receive`.

  Completion check: Peak memory is bounded without excessive rereads or visible cover flicker; include mixed small and large covers and high-DPI rendering.

- [ ] **24 · P2 · Profile: Coalesce artwork-completion repaints.** Every completed cover requests an update of every registered view. Measure redundant paints and schedule a shared update for visible views, retaining retries for deferred artwork requests.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.receive`.

  Completion check: A burst of completions causes fewer paints, visible covers still fill in, and the previously fixed deferred-details artwork case stays working.

- [ ] **25 · P2 · Profile: Share sidecar discovery across artwork requests in one folder.** Separate requests for songs in one folder repeat the COVER_NAMES search. Consider a bounded, generation-scoped folder lookup shared safely by the artwork workers.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Covers.read`.

  Completion check: Repeated folder probes fall while refresh invalidation, disappearing sidecars, embedded fallback, and concurrent requests remain correct.

- [ ] **26 · P2 · Profile: Reuse unfiltered album, artist, and genre cards.** Switching group views rebuilds memberships, subtitles, artwork choices, and byte totals. Profile a cache tied to the current row snapshot and grouping mode.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.render_library`.

  Completion check: Switching views gets faster; filtered groups are still derived from matching rows and refreshes cannot retain stale members or cover choices.

- [ ] **27 · P2 · Profile: Preserve useful selection across equivalent model refreshes.** A full model reset clears selections even when most rows are unchanged. Investigate restoring stable row identities or using smaller model updates where measured worthwhile.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaModel.reset / MediaWindow.render_library`.

  Completion check: Selection follows the same media IDs through filtering, sorting, and refresh; removed items disappear and group selections cannot target stale files.

- [ ] **28 · P2 · Profile: Filter an open group from its current membership.** An open group constructs an ID set and scans all page rows to recover its members. Evaluate using the group's already-refreshed member snapshot directly.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.render_library`.

  Completion check: Opening and searching small groups avoids a whole-library pass while totals, album ordering, exclusions, and refresh replacement remain correct.

- [x] **29 · P2 · Code: Debounce and precompute video-picker searches.** Every keystroke rebuilds rows, repeatedly constructs Path objects, and folds the search text inside the list comprehension. Prepare immutable display/search fields once and debounce rendering.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.choose_videos`.

  Completion check: Typing in a large picker stays responsive, and hidden selections survive searches and acceptance exactly as before.

- [x] **30 · P2 · Profile: Restore video-picker selections in one model operation.** The picker calls selectionModel.select once for every selected row after each reset. Build a QItemSelection or contiguous ranges and apply them together.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow.choose_videos`.

  Completion check: Many selected videos no longer generate one selection operation per row; noncontiguous selection and filtering preserve the chosen paths.

- [ ] **31 · P3 · Profile: Cache playlist search text only if larger libraries justify it.** Filtering repeatedly reads and case-folds each item label. The recent 2,685-track check was already only a few milliseconds, so measure larger supported libraries before adding state.

  Location: [tools/studio/playlist_editor.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/playlist_editor.py) — `PlaylistEditor.filter`.

  Completion check: Keep a change only if it improves interaction measurably; Unicode matching, hidden selections, and Add-button behavior stay correct.

- [ ] **32 · P2 · Profile: Update playlist rows incrementally after additions and removals.** Single-row moves now reuse their item, but add and remove still rebuild all members. Measure whether targeted insertions/removals improve large playlists enough to justify the extra bookkeeping.

  Location: [tools/studio/playlist_editor.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/playlist_editor.py) — `PlaylistEditor.add / remove / select`.

  Completion check: Order, duplicate track IDs, missing-track labels, limits, selection, scrolling, and button states match the existing behavior.

- [x] **33 · P3 · Code: Use scoped signal blockers in remaining bulk UI updates.** Several bulk updates still pair blockSignals(True) with blockSignals(False) manually. Convert suitable sites to QSignalBlocker, and apply the same cleanup to PlaylistEditor.render.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `update_filters / choose_apple_folders / completed`.

  Completion check: The prior blocked state is restored even on failure; each bulk operation performs its intended final control update and does not emit intermediate user actions.

- [ ] **34 · P3 · Profile: Reduce startup artwork conversion overhead.** Startup loads the same asset for three crops and uses per-pixel QColor access to derive transparency. Measure the actual startup-sized crops before choosing shared loading or a faster exact transformation.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `boot_artwork`.

  Completion check: Startup improves measurably with identical pixels, alpha, and device-pixel ratio; avoid adding a new dependency for a negligible gain.


**Improve preparation and validation**

- [ ] **35 · P2 · Profile: Reuse unchanged per-photo preparation between builds.** One changed photo currently causes the complete selected collection to be decoded and tiled again. Design a bounded cache for immutable per-image outputs, keyed by source identity and the complete rendering recipe.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `compile_photos`.

  Completion check: A one-photo update reuses unchanged work; full PIMG bytes match a clean build across orientation, titles, viewport, detail level, and additional iTunes sources.

- [ ] **36 · P2 · Profile: Store photo tile CRCs more compactly.** tile_crcs retains a Python integer per tile while payloads are spooled. Measure peak memory on large valid packages and compare a packed integer array or equivalent bounded representation.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `compile_photos`.

  Completion check: Peak memory falls, package limits still apply before oversized work, and serialized metadata and payload bytes remain identical.

  Progress: Tile CRCs now use an unsigned integer array. A two-photo package matched the prior compiler byte for byte; peak memory on a large valid package still needs measurement.

- [x] **37 · P2 · Code: Enforce the Notes count bound during traversal.** All matching documents are collected and sorted before the 256-note limit is checked. Stop collecting once the supported count is exceeded instead of retaining an arbitrarily large list.

  Location: [tools/content/notes.py](C:/Users/user/Desktop/Projects/linnet/tools/content/notes.py) — `compile_notes`.

  Completion check: Oversized folders fail early; exclusions, supported-file rules, link handling, and valid-folder ordering remain correct.

- [ ] **38 · P2 · Profile: Decode new cover images once for playback and Cover Flow.** A new cover can be decoded by _cover_pixels and then decoded again by coverflow.original_cover. Evaluate sharing a decoded source while keeping each rendering recipe distinct.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `art_for / _cover_pixels`.

  Completion check: Playback RGB files and Cover Flow output remain byte-identical across alpha, EXIF, ICC profiles, and all artwork targets; image lifetime stays bounded.

- [ ] **39 · P2 · Profile: Bound cancellation latency while waiting for music metadata.** Cancellation is checked around progress callbacks, but future.result and executor shutdown can wait for an active metadata parser or decoder. Measure the longest waits and thread cancellation through the underlying work.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `_metadata_rows / compile_music`.

  Completion check: Stop latency improves for slow inputs; subprocesses and worker tasks finish cleanly and no incomplete stage replaces the previous library.

- [ ] **40 · P2 · Code: Bound the persistent Cover Flow cache.** The embedded-image cache has a byte cap, but the coverflow table has no visible eviction policy. Add a measured size or age policy for disposable generated artwork.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `_MetadataCache.coverflow_get / coverflow_put`.

  Completion check: Repeated imports cannot grow this table indefinitely; eviction merely causes recomputation, and cache hits still verify stored digests.

- [ ] **41 · P3 · Profile: Make metadata-cache commit accounting consistent.** Metadata and embedded-image writes use pending_writes, while Cover Flow writes rely on later commits. Initialization can also commit pending work. Trace actual transaction sizes before unifying the accounting.

  Location: [tools/content/music.py](C:/Users/user/Desktop/Projects/linnet/tools/content/music.py) — `_MetadataCache.put / embedded_cover / coverflow_put / close`.

  Completion check: Commit frequency is predictable without excessive fsyncs; cancellation, partial batches, cache errors, and close preserve the disposable-cache fallback behavior.

- [ ] **42 · P3 · Profile: Optimize Cover Flow cache misses only with unchanged rendering.** The recent isolated profile spent most tile time in Pillow quantization, with reflection work secondary. Profile representative art and cache-hit rates before changing the cold path.

  Location: [tools/content/coverflow.py](C:/Users/user/Desktop/Projects/linnet/tools/content/coverflow.py) — `_prepare_tile / _indexed_tile`.

  Completion check: A retained optimization reduces measured preparation time and produces identical packed artwork; do not trade quantization quality for an unrequested recipe change.

- [ ] **43 · P2 · Profile: Reduce repeated local reads during PIMG validation.** inspect checks metadata and payloads, then opens the file again for SHA-256; publication adds further hashing. Map the complete read sequence and evaluate hashing during an already-required ordered pass.

  Location: [tools/content/photos.py](C:/Users/user/Desktop/Projects/linnet/tools/content/photos.py) — `inspect`.

  Completion check: Fewer full-file reads with every record, bounds, CRC, digest, and changed-file check preserved. Measure the complete compile-and-publish preparation path.

- [ ] **44 · P2 · Profile: Measure a verified-copy fast path for compatible native videos.** Compatible input is inspected, copied, and inspected again through ffprobe. Determine whether a validated source plus verified byte-for-byte copying can avoid repeated probing without weakening source/output checks.

  Location: [tools/content/native_video.py](C:/Users/user/Desktop/Projects/linnet/tools/content/native_video.py) — `prepare`.

  Completion check: Use the fast path only with demonstrated equivalent guarantees for changed sources, truncated copies, container details, and target limits; otherwise retain reinspection.


**Simplify operations and make failures easier to handle**

- [ ] **45 · P2 · Code: Split media preparation into focused per-kind helpers.** The main operation contains long music, photo, note, and video branches plus shared receipt and cleanup handling. Extract bounded helpers with explicit inputs and results.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `_run`.

  Completion check: Publication order, checkpoints, outputs, receipts, source-error reporting, and partial completion remain unchanged; callers become easier to review.

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

- [ ] **50 · P2 · Profile: Resume source-error retries without restarting unrelated work.** After automatically excluding a problem file, run invokes the entire workflow again. Measure repeated scans, planning, and completed-kind checks, then isolate the affected preparation stage.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `run / _run`.

  Completion check: Several bad sources do not repeatedly redo unrelated work; completed publications are retained and uncertain publication failures are never replayed automatically.

- [ ] **51 · P2 · Profile: Validate removal selections without rebuilding unrelated display metadata.** Removing selected items rebuilds the full library row set, including display metadata and artwork lookup. Investigate a lighter validated inventory for mutation decisions.

  Location: [tools/content/media_library.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_library.py) — `_remove / list_items`.

  Completion check: Removal remains tied to fresh paths, sizes, timestamps, removability, catalog state, and last-source retirement rules while avoiding unrelated artwork work.

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

- [ ] **57 · P3 · Profile: Reuse verified toolchain fingerprints during a target matrix build.** Each build probes and hashes compiler, linker, objcopy, and nm executables. Measure repeated work, including tools that share the same underlying LLVM binary.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `toolchain`.

  Completion check: A single build session can reuse verified fingerprints without masking executable replacement, version mismatch, configuration changes, or distinct tool roles.

- [ ] **58 · P2 · Profile: Measure MP4 sample-table I/O on the device.** Packet processing requests small sample-size, chunk-offset, and sync-table reads. Measure how effectively the existing lower-level caches satisfy them before adding any new table cache.

  Location: [services/video/mp4.c](C:/Users/user/Desktop/Projects/linnet/services/video/mp4.c) — `read_at / ln_mp4_next / ln_mp4_seek_step`.

  Completion check: Any change lowers physical reads or seek latency on real media without increasing underruns, exceeding memory budgets, or breaking table bounds and seek behavior.

- [ ] **59 · P2 · Profile: Measure photo panning and zooming at tile boundaries.** The viewer already has a viewport-sized tile cache, grouped reads, hints, and timing counters. Use those counters to identify remaining misses or repeated rendering during direction changes and zoom.

  Location: [services/photos/photos.c](C:/Users/user/Desktop/Projects/linnet/services/photos/photos.c) — `tile cache, tile_records, render phases`.

  Completion check: A targeted change improves frame-ready latency with identical visible output, bounded memory, correct cancellation, and no interference with audio playback.

- [ ] **60 · P2 · Profile: Tune Cover Flow scheduling from cache and I/O measurements.** Cover Flow already has packed-art caches, decoded slots, preview fallback, and hit/miss counters. Measure rapid reversal, long traversal, and playback before tuning read scheduling or eviction.

  Location: [services/music/coverflow.c](C:/Users/user/Desktop/Projects/linnet/services/music/coverflow.c) — `cache / io_due / directional loading`.

  Completion check: Visible covers become ready sooner without extra idle disk activity, audio underruns, stale artwork, or regressions in existing device and simulator checks.

**Device additions, target policy, and porting**

- [x] **61 · P1 · Code: Declare game availability in the target manifest.** Game support is repeated as the same two-target tuple in host code and as target macros in settings code, while CAPABILITIES has no games entry. Introduce one explicit capability and use it for build inclusion, menu availability, and Media Manager controls.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/content/games.py](C:/Users/user/Desktop/Projects/linnet/tools/content/games.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [services/display/settings.c](C:/Users/user/Desktop/Projects/linnet/services/display/settings.c) — `CAPABILITIES / game availability`.

  Completion check: Existing targets keep their current game support; a new qualified target can enable games through its manifest without editing host target-name lists.

- [x] **62 · P2 · Code: Select game assets through an explicit presentation profile.** games.c chooses Photo court assets when the width is 220 and Video assets otherwise, with further target-owned graphics includes. Define supported game layouts and asset ownership explicitly instead of treating every other resolution as the Video layout.

  Location: [services/games/games.c](C:/Users/user/Desktop/Projects/linnet/services/games/games.c), [targets/photo4g-p98/games_graphics.h](C:/Users/user/Desktop/Projects/linnet/targets/photo4g-p98/games_graphics.h), [targets/video5g-m25/games_arcade.h](C:/Users/user/Desktop/Projects/linnet/targets/video5g-m25/games_arcade.h) — `game asset includes and layout selection`.

  Completion check: Unsupported resolutions fail clearly during content/build validation; current game pixels and behavior remain unchanged. Coordinate with item 61 before enabling games on another model.

- [ ] **63 · P2 · Profile: Give editable menus a shared definition with stable item identifiers.** The host repeats menu labels, defaults, and required indices; Home index 7 changes from UI Demo to Games for certain targets. Design a shared menu definition for host and firmware, preserving the existing MENUS.BIN numbering and migration behavior.

  Location: [tools/studio/screen_settings.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/screen_settings.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [services/display/settings.c](C:/Users/user/Desktop/Projects/linnet/services/display/settings.c) — `SCREENS / DEFAULTS / REQUIRED / menu decoding`.

  Completion check: Labels, availability, defaults, and required navigation agree on every target, and previously saved menu files retain their meaning.

- [x] **64 · P1 · Code: Report the precise failing target field.** Several manifest checks combine many unrelated fields into errors such as invalid target identity or invalid native video profile. Break these into named field and cross-field diagnostics that show the target, rejected value, and applicable bound.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py) — `_validate_identity / _validate_media / load_targets`.

  Completion check: An invalid dimension, decoder combination, duplicate alias, or memory region produces an actionable message while preserving all existing rejection rules.

- [ ] **65 · P2 · Profile: Normalize target defaults once into a resolved specification.** Consumers repeatedly supply defaults for hal_family, capability booleans, clocks, and decoder selection. Define a resolved target representation alongside the source manifest so build, host media, and content code consume the same defaults without mutating shared target data.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [tools/content/compiler.py](C:/Users/user/Desktop/Projects/linnet/tools/content/compiler.py) — `target_spec / media_profile / manifest defaults`.

  Completion check: Resolved values for all existing targets match current behavior, callers cannot accidentally change shared defaults, and a newly added field has one documented default.

- [ ] **66 · P2 · Profile: Provide a disabled target scaffold.** The porting guide currently directs contributors to copy a complete existing target. Provide a small scaffold workflow that creates the manifest and conventional file skeletons with explicit placeholders, a bring-up blocker, build_enabled=false, and installer.enabled=false.

  Location: [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md), [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py) — `Add a model / disabled target validation`.

  Completion check: A scaffold is discoverable as an incomplete port, copies no specimen identity or qualified writer, and reports the remaining required fields and native files before builds can be enabled.

- [ ] **67 · P2 · Profile: Expose a read-only resolved target report.** doctor lists supported and bring-up targets, but source overrides, theme resolution, decoder choices, and memory reservations require reading several files. Add a target inspection view that explains these resolved choices and where each came from.

  Location: [tools/cli/main.py](C:/Users/user/Desktop/Projects/linnet/tools/cli/main.py), [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/content/compiler.py](C:/Users/user/Desktop/Projects/linnet/tools/content/compiler.py) — `doctor / _target_sources / presentation resolution`.

  Completion check: A contributor can inspect a disabled or enabled port without compiling or connecting hardware and see missing prerequisites, selected sources, capabilities, and memory ranges.

- [x] **68 · P2 · Code: Validate the complete build source set before compilation.** _target_sources validates conventional files, while build.py later adds SOURCES entries, optional blitters, codec groups, and feature sources. Resolve the final ordered source set in one preflight step, detect duplicates, and retain each selection's origin.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [hal/s5l8702/SOURCES](C:/Users/user/Desktop/Projects/linnet/hal/s5l8702/SOURCES) — `_target_sources / source-list assembly`.

  Completion check: Missing or duplicate selected sources fail before compiler work begins; existing targets retain their intended source and link order, including Boot versus OS differences.

  Verification note: The source list now records each selection origin in the build report and checks missing, external, and duplicate paths before starting compiler workers. Injected missing and duplicate S5L8702 SOURCES entries failed before compilation, then the original file was restored. Photo and Video OS source order matched prior reports after normalizing invocation paths; Photo Boot, Photo dev OS, Classic Boot, and Classic OS builds passed. The Classic OS check also exposed a color320 Home target mismatch, which was repaired and verified through all three target UI configurations.

- [ ] **69 · P2 · Profile: Move remaining private hardware dependencies behind portable interfaces.** storage.c directly includes PP502x disk-mode and S5L8702 AES headers despite the portable-layer contract. Review those operations and expose narrowly scoped HAL interfaces or adapters so adding a family does not grow storage-service hardware branches.

  Location: [services/storage/storage.c](C:/Users/user/Desktop/Projects/linnet/services/storage/storage.c), [hal/api/platform.h](C:/Users/user/Desktop/Projects/linnet/hal/api/platform.h), [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md) — `disk-mode include / selector_apple`.

  Completion check: Portable storage code no longer includes these family-private headers; retail handoff, decryption, quiescence, watchdog behavior, and target checks remain equivalent on qualified hardware.

- [ ] **70 · P2 · Code: Replace remaining board-name UI and playback policies with named settings.** The music hint names Q21, the battery renderer names Photo, and native video priming names Classic. Record the actual reason for each exception and represent it as an explicit presentation or runtime policy where appropriate.

  Location: [services/music/ui.c](C:/Users/user/Desktop/Projects/linnet/services/music/ui.c), [ui/runtime/ui.c](C:/Users/user/Desktop/Projects/linnet/ui/runtime/ui.c), [services/video/native/player.c](C:/Users/user/Desktop/Projects/linnet/services/video/native/player.c) — `music hint / battery monochrome choice / START_AUDIO_FRAMES`.

  Completion check: Each existing exception keeps its behavior and rationale; a future target with the same requirement selects the policy without adding a target-name branch. Do not infer policy solely from resolution.

- [x] **71 · P2 · Code: Share relevant target defines with the simulator.** The simulator writes a target header containing only UI dimensions, while firmware generates a larger header and passes target defines; ui.c contains a Photo-specific rendering branch. Share the presentation-related definitions so simulation follows the intended target behavior.

  Location: [tools/simulator/runner.py](C:/Users/user/Desktop/Projects/linnet/tools/simulator/runner.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [ui/runtime/ui.c](C:/Users/user/Desktop/Projects/linnet/ui/runtime/ui.c) — `linnet_target.h generation / simulator compile command`.

  Completion check: Existing scene captures are reviewed for the intended target policy, and simulator/firmware presentation defines agree without pulling hardware-only code into the simulator.

- [ ] **72 · P2 · Profile: Make Notes wrapping aware of the selected target and themes.** Notes currently wraps at 140 pixels and gathers fonts only from root themes. Profile and design target-aware wrapping using the resolved screen width and allowed fonts, including shared presentation and target-local themes.

  Location: [tools/content/notes.py](C:/Users/user/Desktop/Projects/linnet/tools/content/notes.py), [tools/content/compiler.py](C:/Users/user/Desktop/Projects/linnet/tools/content/compiler.py) — `_display_widths / _display_lines / compile_notes`.

  Completion check: Notes fit monochrome, Photo, and 320-pixel layouts; format limits and truncation stay explicit, and any new wrapping recipe participates in preparation identity.

- [x] **73 · P1 · Code: Bring the porting guide into agreement with source resolution.** The guide omits the HAL/target SOURCES convention and board.c/power.c fallbacks, and describes M25 screens as local although color320 is shared. Document the actual override rules and current validation entry points.

  Location: [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md), [docs/architecture.md](C:/Users/user/Desktop/Projects/linnet/docs/architecture.md), [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `Repository contract / Validate a port / source map`.

  Completion check: Every named path and command resolves in the current checkout, and a contributor can distinguish shared defaults, target overrides, extra sources, and available hardware validation procedures.

- [ ] **74 · P2 · Code: Use a consistent per-target qualification record.** Video has BRINGUP and QUALIFICATION documents, while the Classic target directory lacks the same entry-point README. Define a compact common format for support state, hardware/storage variants, recovery requirements, known blockers, and evidence locations.

  Location: [targets/README.md](C:/Users/user/Desktop/Projects/linnet/targets/README.md), [targets/video5g-m25/QUALIFICATION.md](C:/Users/user/Desktop/Projects/linnet/targets/video5g-m25/QUALIFICATION.md), [docs/roadmap.md](C:/Users/user/Desktop/Projects/linnet/docs/roadmap.md), [docs/local-artifacts.md](C:/Users/user/Desktop/Projects/linnet/docs/local-artifacts.md) — `target status and qualification documentation`.

  Completion check: Each target has a discoverable status record; simulator results and physical-device evidence remain distinct, with private device identifiers and receipts kept in local artifacts.

- [ ] **75 · P3 · Profile: Separate qualified Apple OS specimens from general model support.** apple_os.py embeds exact serial, volume, sector size, and model tuples directly in APPLE_DEVICES. Design a dedicated qualification-record boundary so adding an audited specimen does not require editing the media workflow itself.

  Location: [tools/content/apple_os.py](C:/Users/user/Desktop/Projects/linnet/tools/content/apple_os.py), [docs/apple-stock-music.md](C:/Users/user/Desktop/Projects/linnet/docs/apple-stock-music.md) — `APPLE_DEVICES / supported`.

  Completion check: Current exact-device gates remain equally strict, model capability never grants specimen authorization, and unsupported or missing qualification records stay disabled.

**Build speed, branch switching, and host tooling structure**

- [ ] **76 · P1 · Profile: Compile independent translation units with bounded concurrency.** build.py launches and waits for each compiler process sequentially. Measure a modest worker limit on the native and WSL toolchains, keeping source selection, header generation, and final linking ordered.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `per-source compile loop`.

  Completion check: Clean builds become faster within a bounded memory budget, diagnostics identify the failing source, failed workers cannot publish a successful report, and output is equivalent to the serial build.

  Progress: Two compiler jobs are the default, with `--jobs 1..4` available. On this WSL toolchain, Photo release took 24.4 s serial and 13.4 s with two jobs; Video release took 24.2 s serial and 14.4 s with two jobs. Both pairs had identical build IDs and byte-identical ELF, LOS, and iPod images. A separate native Linux host is unavailable for the remaining measurement.

- [ ] **77 · P2 · Profile: Reuse unchanged object files with complete dependency keys.** Every build recompiles every selected source. Investigate an object cache keyed by compiler fingerprint, effective flags, source and included-header contents, target/profile, and generated inputs; keep whole-image provenance separate from object reuse.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `source_identity / compiler loop / generated headers`.

  Completion check: Clean and cached builds produce equivalent artifacts after source edits, header edits, configuration changes, and branch switches. Sources consuming linnet_build.h rebuild whenever image identity changes.

- [x] **78 · P1 · Code: Isolate intermediate output for concurrent builds.** Generated headers and object files share out/<profile>/<target>/<kind> even when build identities differ. Add explicit workspace ownership or per-invocation staging so two builds with different content, serials, or branch states cannot overwrite each other's inputs.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [docs/local-artifacts.md](C:/Users/user/Desktop/Projects/linnet/docs/local-artifacts.md) — `dest / generated / object outputs`.

  Completion check: Overlapping builds are either safely isolated or rejected clearly; each published report references its own complete artifacts, and sequential branch switching leaves no ambiguous intermediate state.

  Verification note: Two overlapping Photo release builds with the same identity wrote distinct invocation directories and produced identical image hashes. Every artifact path in each report stays inside its invocation directory; branch changes likewise get a fresh directory.

- [x] **79 · P2 · Code: Use collision-free object paths.** Object names flatten repository paths by replacing slashes with underscores, which can collide as directories and filenames grow. Preserve the source directory structure under an object root or use a deterministic unambiguous mapping.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `object filename construction`.

  Completion check: Different source paths always receive distinct object paths, generated sources remain covered, and link order and final firmware bytes are preserved.

  Verification note: The current Video source set has no flattened collisions, so its object names and linker map are unchanged. Two repeat builds had the same firmware hash. As expected, the source edit changes the embedded build identity, so binaries from before and after the edit are not byte-identical.

- [ ] **80 · P2 · Code: Organize codec source and compiler rules by backend.** Build source lists and per-source optimization flags are spread across long branches for AAC, MP3, Vorbis, H.264, and MPEG-4. Group each backend's sources, include paths, flags, and rationale into a small explicit build description.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [third_party/aac/SOURCES](C:/Users/user/Desktop/Projects/linnet/third_party/aac/SOURCES), [third_party/pvmp4/SOURCES](C:/Users/user/Desktop/Projects/linnet/third_party/pvmp4/SOURCES) — `codec source selection / codec_flags`.

  Completion check: Each backend is reviewable in one place, ARM4 versus ARM926 assumptions remain explicit, and existing release exclusions, source order, warning exceptions, and optimization choices are unchanged.

- [ ] **81 · P2 · Code: Split CLI command registration and execution by domain.** parser and main contain the full build, media, simulator, device, and installation command surface. Move cohesive command groups into modules while retaining one public linnet entry point and shared argument helpers.

  Location: [tools/cli/main.py](C:/Users/user/Desktop/Projects/linnet/tools/cli/main.py) — `parser / main`.

  Completion check: Existing command names, aliases, defaults, exit codes, JSON output, and WSL forwarding remain compatible; adding a domain command no longer expands both central functions.

- [x] **82 · P2 · Code: Reject invalid build requests before hashing the toolchain.** build resolves and fingerprints the toolchain before checking the requested probe, development serial, and Boot selector combination. Perform cheap request validation first, followed by source/configuration preflight and expensive tool discovery.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `build argument checks / toolchain`.

  Completion check: Invalid requests fail promptly with the same intended validation message; valid requests still enforce pinned tool versions and fingerprints.

**Media Manager workflow and maintainability**

- [ ] **83 · P2 · Code: Separate Media Manager pages from the main window controller.** MediaWindow owns page construction, selection, queue management, device state, installation controls, and a large completion dispatcher. Extract cohesive page components and small controllers with explicit state dependencies.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `MediaWindow / build_* / completed`.

  Completion check: Page behavior and settings remain compatible, widget work stays on the GUI thread, and changes to one workflow do not require editing unrelated page logic. This complements the preparation split in item 45.

- [ ] **84 · P2 · Profile: Give background jobs explicit context and results.** work and completed route operations through string tags, mutable window state, and an error string. Define an operation context containing the captured device identity, operation ID, cancellation contract, and structured outcome; use explicit completion handlers.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `Events / work / completed`.

  Completion check: Completions apply only to the device and operation that started them, unknown outcomes fail clearly, and cancellation, partial success, and failure are distinguishable without parsing messages.

- [x] **85 · P1 · Code: Reuse the setup assessment already produced during a scan.** media_status.inspect calls installer.assess but returns only selected assessment fields. When the setup page is active, completed('scan') immediately schedules installer.assess again. Carry the full read-only assessment with the scan result for that page.

  Location: [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `inspect / completed scan / setup`.

  Completion check: One refresh performs one setup assessment and displays that result consistently; writes still perform their own required current-device validation, and later refreshes replace stale assessments.

- [x] **86 · P2 · Code: Load skipped-file details through the background worker.** review_skipped invokes media.list_skipped_files directly from the GUI callback before opening its dialog. Load those details asynchronously and report loading, empty, and failure states through the existing worker mechanism.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `review_skipped`.

  Completion check: Opening a large skipped list keeps the window responsive, and returned rows remain bound to the selected device. Existing retry and source-exclusion behavior is preserved.

- [x] **87 · P1 · Code: Validate saved FFmpeg and FFprobe locations before declaring readiness.** update_tools reports ready when both stored path strings are nonempty; locate_tools can retain an older path for a tool missing from the newly selected folder. Resolve and validate the selected pair in a worker, with distinct actionable errors.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `__init__ / locate_tools / update_tools / prepare`.

  Completion check: Moved or missing tools are caught before a conversion starts, readiness reflects the validated executables, and replacing either executable invalidates its cached readiness result.

- [ ] **88 · P2 · Profile: Keep queue completion state per submitted source.** The prepare completion handler removes every submitted queue entry only when the whole operation is complete. Carry per-source outcomes through the existing receipt so successful, skipped, and unfinished sources can be presented and retried separately.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `completed prepare / submitted / operation receipt`.

  Completion check: A partial failure leaves only actionable work queued, successful publication is not repeated needlessly, and skipped sources remain visible with their reason and retry action.

- [ ] **89 · P2 · Profile: Preserve a device-bound preparation draft across restarts.** Queued sources and selected videos currently live in memory, while a few presentation preferences use QSettings. Persist a small versioned preparation draft keyed to stable device identity, then revalidate source paths and capabilities when reopening it.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `pending / video_selection / QSettings / refresh`.

  Completion check: Restarting restores an understandable draft for the same device, stale sources are flagged, and switching devices cannot silently apply another device's queue or video selection.

- [x] **90 · P1 · Profile: Make all, selected, and no video conversions explicit.** An empty video_selection currently means all existing videos, including after the picker selection is cleared or intersected with a refreshed inventory. Represent selection mode separately from its member set and describe the resulting conversion scope clearly.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `choose_videos / update_preparation / video_jobs`.

  Completion check: Selecting no conversions never expands to all conversions after refresh, and selecting all remains intentional. Preserve the separate automatic inclusion of compatible device-format videos.

- [ ] **91 · P2 · Profile: Show the preparation plan before starting substantial work.** plan already computes copy counts, source previews, free device space, computer free space, and conversion need, but prepare mainly uses its conversion flag. Present a concise plan with reusable outputs and space estimates, including unknown conversion sizes.

  Location: [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `plan / prepare`.

  Completion check: Users can see what will be copied, prepared, reused, or excluded and which volume needs space; execution revalidates changing conditions and no estimate is presented as guaranteed. Reuse item 02's scan work.

- [ ] **92 · P2 · Profile: Show whole-operation progress and the current stopping boundary.** Detailed percentages currently describe video conversion/checking, while the main progress bar remains indeterminate. Define stage-aware progress for copying, preparing, checking, and publishing, and expose whether the current stage can stop immediately or must finish its guarded write.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py) — `show_conversion_progress / work / stop / _run`.

  Completion check: Progress never claims the entire operation is complete while verification or publication remains, and cancellation feedback matches the actual stopping boundary without reducing existing cancellation checks.

- [x] **93 · P1 · Code: Report discovery failures per candidate device.** discover identifies mounted candidates in one list comprehension; one failing candidate aborts the result for all devices. Collect validated candidates and bounded per-candidate errors so one unreadable or unsupported iPod does not hide another valid one.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `discover / completed devices`.

  Completion check: A valid connected device remains selectable when another candidate fails; failed candidates cannot reach write actions, and the UI explains the detection issue without weakening identity checks.

- [x] **94 · P2 · Code: Link preparation summaries to their detailed receipts.** The backend already saves a receipt, but the window reduces results to a summary and error-message lines before refresh replaces the status text. Add an operation-details view or local receipt link that retains per-file outcomes and skipped reasons.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `run receipt / completed prepare / prep_results`.

  Completion check: After refresh, users can still inspect the last operation's completed, skipped, and failed work and its saved receipt; local source paths and device data are not published externally.

- [ ] **95 · P2 · Code: Centralize device-session reset behavior.** The no-device, changed-device, and ejected branches independently reset artwork, menus, games, rows, setup state, selections, and readiness. Extract one device-session transition routine with explicit handling for user drafts and display state.

  Location: [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py) — `completed devices / completed eject / update_device`.

  Completion check: Disconnect, reconnect, selection of another iPod, and safe eject consistently clear device-derived state while retaining only explicitly device-bound drafts and applicable user preferences.

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

- [ ] **104 · P2 · Profile: Report useful memory headroom for each target and profile.** Build reports include allocated sections and limits, and linker scripts already protect reserved regions. Add a readable breakdown of resident memory, stacks, staging, artwork, and retained areas, with measured high-water data kept distinct from static reservations.

  Location: [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [hal/pp502x/memory.ld](C:/Users/user/Desktop/Projects/linnet/hal/pp502x/memory.ld), [hal/s5l8702/memory.ld](C:/Users/user/Desktop/Projects/linnet/hal/s5l8702/memory.ld), [kernel/executive.c](C:/Users/user/Desktop/Projects/linnet/kernel/executive.c) — `report.memory / linker assertions / arena high-water marks`.

  Completion check: A port or feature change can be compared against its prior memory budget without double-counting overlapping lifetimes; existing overlap assertions and hardware qualification requirements remain authoritative.

**File organization, ownership, and reviewable cleanup**

- [x] **105 · P2 · Code: Document ownership and regeneration of generated target assets.** Boot fonts, disk-screen runs, game graphics, and court assets sit beside native target sources, while generation entry points live elsewhere. Add a small asset index identifying authoritative inputs, generator commands where available, output paths, licenses, and manually maintained assets.

  Location: [tools/studio/boot_menu_font.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/boot_menu_font.py), [tools/studio/disk_screen_asset.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/disk_screen_asset.py), [targets/photo4g-p98/boot_menu_font.h](C:/Users/user/Desktop/Projects/linnet/targets/photo4g-p98/boot_menu_font.h), [targets/photo4g-p98/disk_screen_runs.h](C:/Users/user/Desktop/Projects/linnet/targets/photo4g-p98/disk_screen_runs.h) — `generated asset ownership`.

  Completion check: Each listed asset has a reproducible command or an explicit manual-source designation; regeneration is deterministic and preserves license/provenance information without moving build output into Git.

  Verification note: The two Photo generators reproduced their checked-in headers after line-ending normalization. The target guide now lists their inputs, commands, font license, and the direct-source/CC0 provenance of each game presentation header.

- [ ] **106 · P2 · Profile: Clarify shared host-media boundaries.** Media helpers import private symbols such as _plain, _volume_guard, _save, and scan helpers across publication, library, planning, and settings modules. Define a small supported internal API for identities, guarded paths, scans, and receipts, then migrate callers incrementally.

  Location: [tools/content/media_manager.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_manager.py), [tools/content/publish.py](C:/Users/user/Desktop/Projects/linnet/tools/content/publish.py), [tools/content/media_status.py](C:/Users/user/Desktop/Projects/linnet/tools/content/media_status.py), [tools/studio/screen_settings.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/screen_settings.py) — `cross-module private imports`.

  Completion check: Shared invariants have one owner, circular workflow dependencies are reduced, and moving a helper does not bypass publication checks or silently change error handling. Coordinate persistence changes with items 46–47.

- [ ] **107 · P3 · Code: Index vendor provenance and local build adaptations.** Dependency metadata is spread among PROVENANCE.md, README.linnet.md, LICENSE, NOTICE, and SOURCES files, while compiler exceptions live in build.py. Add a central index linking each dependency's origin, license, local changes, and integration rules.

  Location: [third_party/aac/PROVENANCE.md](C:/Users/user/Desktop/Projects/linnet/third_party/aac/PROVENANCE.md), [third_party/vorbis/README.linnet.md](C:/Users/user/Desktop/Projects/linnet/third_party/vorbis/README.linnet.md), [third_party/flac/README.linnet.md](C:/Users/user/Desktop/Projects/linnet/third_party/flac/README.linnet.md), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py) — `vendor documentation and build integration`.

  Completion check: A reviewer can trace every included codec to its existing provenance and local adaptations; unknown version or patch information is marked for investigation rather than invented.

- [ ] **108 · P2 · Profile: Provide an artifact inventory before any cleanup of local output.** out contains builds and scratch results, but local-artifacts.md warns that plans can depend on exact paths, backups, predecessor files, and receipts. Design a read-only inventory showing artifact type, source identity, target, size, and known receipt/plan references before proposing retention rules.

  Location: [docs/local-artifacts.md](C:/Users/user/Desktop/Projects/linnet/docs/local-artifacts.md), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [tools/studio/native_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/native_bootstrap.py), [tools/studio/installer.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/installer.py) — `build reports / installation plans / recovery artifacts`.

  Completion check: Builds from earlier branch states are identifiable, durable recovery dependencies are protected, and unknown or in-use artifacts remain retained. Any later cleanup must be explicit and separate from inventory.

- [ ] **109 · P3 · Code: Expand dense control flow in the modules being changed.** Several core modules compress multiple state updates and conditional actions onto single lines. Apply focused readability cleanup around future changes, especially manifest validation, build rules, job completion, and executive state transitions; avoid a repository-wide formatting pass.

  Location: [tools/studio/targets.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/targets.py), [tools/studio/build.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/build.py), [tools/studio/media_desktop.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/media_desktop.py), [kernel/executive.c](C:/Users/user/Desktop/Projects/linnet/kernel/executive.c) — `dense conditionals and state transitions`.

  Completion check: A reviewer can follow ownership, early returns, and failure paths without reconstructing semicolon chains; behavior and outputs remain equivalent, with formatting kept local to the substantive work.

- [ ] **110 · P3 · Profile: Make bootstrap tooling roles easier to find.** tools/studio holds desktop UI alongside image builders and guarded native maintenance, while tools/link contains the corresponding device transports. Clarify the naming and module layout for build, plan, package, transfer, and execute responsibilities before moving files.

  Location: [tools/studio/s5l_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/s5l_bootstrap.py), [tools/link/s5l_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/link/s5l_bootstrap.py), [tools/studio/native_bootstrap.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/native_bootstrap.py), [tools/studio/native_package.py](C:/Users/user/Desktop/Projects/linnet/tools/studio/native_package.py) — `bootstrap module responsibilities`.

  Completion check: A contributor can locate each stage from one workflow map; any later reorganization preserves CLI/import compatibility, keeps hardware-family code explicit, and retains exact-device checks and hash-pinned plans.

**Starting sequence**

Take items 01–07 first for contained build, planning, browsing, and batch-operation improvements. Then address cancellation and error handling in 08–12. Larger caches, shared snapshots, and validation changes should follow their profiling steps. Device investigations require the existing device-specific checks and appropriate hardware; desktop-only results do not certify firmware behavior.

For the added work, start with field diagnostics and porting documentation (64, 73), duplicated setup assessment (85), tool readiness (87), and per-device discovery results (93). Address output ownership (78) before supporting concurrent build invocations; measure bounded translation-unit concurrency (76) within that contract. Resolve capabilities and asset selection (61–62) before expanding game support. Broader module moves and shared schemas should follow the small fixes, with the dependent items implemented in separate reviewable batches. No branch creation, branch switching, or publishing is required by this backlog.

Earlier measurements are useful constraints: cold Apple metadata loading was dominated by device filesystem work; a previous path-lookup rewrite did not materially improve that workload. Photo tile packing improved in isolation without a reliable whole-package speedup, and playlist filtering at roughly 2,700 songs was already fast. Revisit these only with evidence that the workload or approach has changed.
