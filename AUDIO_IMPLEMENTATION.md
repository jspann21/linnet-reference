# Batch 4 audio status

Batch 4 is in development. The saved device OS remains the accepted Batch 3
build `3ac3673f2188`; music candidates are loaded into RAM for qualification.

The hardware reference is the working Rockbox Photo repository at
`C:/Users/user/Desktop/Projects/ipod`, revision
`a0e9e0c700a51d685c704fa59a28dc859e6ee338`. PocketJS audio is not a working
reference. Imported codec code retains its licenses and provenance under
`third_party/`.

## Listening failure and correction

The first listening check reported tiny clicks, severe distortion, and slow
volume response. The DMA telemetry confirmed PCM starvation: the hardware
continued with silence while the decoder failed to keep its ring filled.
No audio HAL fault was reported. Successful silence/clock checks do not
qualify decoded audio quality.

Implemented processing fixes include ARM libmad arithmetic and synthesis,
bit-exact bypass for the default unity DSP profile, and immediate scheduling
of productive decoding steps when the ring needs samples. Stop also clears
pending seek/pause intents so the immediate deadline cannot spin while idle.
These changes improved production but required CPU cache to meet real-time
playback throughput.

The first cache-enabled startup passed its memory probe and reached
watchdog arming, then reset. The retained diagnostic report is
`out/b04-cache-trace-result.json` (milestone `0xca0e`). Source review identified
a COP watchdog sampling race: its timer sample can precede a newly published
CPU heartbeat. Unsigned subtraction then interprets that newer heartbeat as
a very old one. A signed comparison now ignores negative elapsed time while
preserving the existing 750 ms escalation and 1.5 s reset deadlines. Before
cache activation, the OS verifies and parks the known resident monitor,
updates that single instruction, checks readback, and resumes it. Future
Boot builds contain the corrected comparison directly.

RAM build `0e6bbc03ec8a` reached health 31 with cache enabled. Its first
playback snapshot had 301,056 consumed frames, 14,592 queued frames, zero
underruns, zero inserted silence, and no HAL fault. Evidence is in
`out/b04-cached-audio-first.json`. A later snapshot exceeded one minute with
zero underruns (`out/b04-cached-audio-followup.json`). The user confirmed
clear audio and working pause/resume, but reported slow track changes and
brief startup trouble. Two underruns were observed during a subsequent
track-change check; the complete transition gate is not yet passed.

The next candidate removes idle gaps between metadata steps, makes the
16-entry FAT chain-proof cache associative, and starts next-track preopening
only after current playback begins with a larger buffer reserve. Full-chain
verification and media-generation checks remain in place.

A subsequent RAM update froze on the Home screen with no USB endpoint; the
user confirmed that buttons also stopped responding. The revised cache
transaction discards clean CPU tags before image replacement and cache
initialization. A flush timeout records its state and resets directly from
IRAM, avoiding a return into a still-busy cache. These changes passed a cached
same-image RAM handoff from generation 2 to 3, followed by the next candidate
handoff to generation 4, each reaching health 31. The prior freeze left no fault
record identifying its exact failing instruction.

Build `3395ed32c09e` increases the PCM ring from 16,384 to 65,536 frames
(about 1.49 seconds at 44.1 kHz), within the existing resident memory limit.
Playback still starts after 8,192 frames. Manual Next can promote the already
prepared decoder after draining current I/O, preserving its buffered samples.
The queue advances once, and manual transitions do not count as completed songs.
Development and release builds passed verification. The first native UI start
took 1.891 seconds; prepared Next took 0.250 seconds versus the prior 0.594.
Both checks reached next-track READY with zero underruns, zero inserted silence,
and no HAL fault. Evidence: `out/b04-prepared-skip-start.json` and
`out/b04-prepared-skip-next.json`. The user confirmed much faster changes and
working pause/resume, but reported a small click precisely when the placeholder
changes to album art. Ring-underrun counters remained zero in the following
snapshot; they do not detect hardware FIFO starvation from a late DMA rearm.
The next revision retains matching verified artwork by path and CRC and admits
new artwork reads only at the high-water PCM reserve. FIFO/IRQ measurements
were added to distinguish a short hardware gap from LCD-related noise.
Build `c5d5c1d7950c` reached health 31 after an automatic generation 4-to-5
handoff. Its first 12-second startup capture had zero ring underruns, inserted
silence, HAL faults, empty-FIFO samples at IRQ entry, and positive completion
lateness. Maximum completion interval was 23,220 microseconds. These samples
do not prove absence of all analog noise; renewed listening is pending.
Development/release verification passed. Evidence:
`out/b04-artwork-timing-start.json`, `out/b04-artwork-timing-build.json`, and
`out/b04-artwork-timing-release.json`.

The user confirmed the cover now remains visible, but isolated the remaining
click to Next/Previous itself. Build `83a82f53ea44` separates a warm stream halt
from full codec shutdown: mute, bounded settling interval, verified DMA idle,
and FIFO reset retain analog power and volume for the replacement stream.
DMA/IIS start before unmute. Explicit Stop and shutdown retain full power-down.
Both prepared Next and ordinary metadata-selected replacements use this path;
seek also reuses the codec. A generation 5-to-6 RAM handoff reached health 31.
Prepared Next measured 0.218 seconds with zero software underruns, inserted
silence, FIFO-empty samples, or positive completion lateness. Development and
release verification passed. The user subsequently confirmed the track-change
click is fixed. Evidence:
`out/b04-warm-track-check.json`, `out/b04-warm-track-build.json`, and
`out/b04-warm-track-release.json`.

## Qualification boundaries

After listening confirmation, follow-up controls were qualified on hardware.
Obsolete waiting metadata is cleared on replacement selection. Paused seeks
prime silently and preserve PAUSE; starting playback waits for history loading
to finish or report an error. Full/unavailable history is visible in options.
Development seek commands now clear the controller's next-track intent so
prefetch can restart. Build `095981b079e1` is running at generation 9, health 31.
The paused seek held frame 22,050 with zero consumed frames; after Resume the
next decoder reached READY. Rapid Next/Previous also passed. Captured checks
show zero ring underruns, inserted silence, HAL faults, FIFO-empty samples,
and completion lateness. Both profiles verify and all 12 existing simulator
frames match the baseline. Evidence: `out/b04-control-state-check.json` and
`out/b04-seek-prefetch-check.json`.

Batch 4 remains incomplete. The candidate now supports virtual queues up to
100,000 occurrences, paged title-prefix search, queue viewing/editing, saved
sound profiles, and a paged 128,000-record history format. Hardware migration,
broader codec/DSP/gapless qualification, and persistent installation remain.
The new OS runs in RAM; the persistent fallback is still Batch 3.

The published Alabama album contains 22 original MP3 files. The first two
passed host decoder/reference sample-count and seek checks; their metadata
does not provide recognized encoder delay/padding, so source-level gapless
trimming is not qualified. Hardware storage activity has been limited to
normal startup, one verified album publication, and short playback attempts.
No exhaustive drive campaign has been run.

### Queue, search, sound, and history integration

Build `86d43aaa8c7c` reached generation 10, health 31. On-device title search
for `f` returned the expected three Alabama tracks, and selecting Five O'Clock
500 started playback. The queue screen displayed the current marker and track
titles correctly. Playback subsequently completed one automatic join with no
reported underruns. Evidence: `out/b04-search-queue-device.json`,
`out/b04-search-device.png`, and `out/b04-queue-device.png`.

Large queues use source descriptors and bounded memory, with affine seeded
shuffle and up to 32 exclusions. Explicit queues retain up to 64 occurrences
and support moves. Moving virtual queue entries is currently unavailable and
reported in the UI. Search is ASCII title-prefix search, paged in 12 results;
it is not full-text search. Host checks covered 100,000-member permutation,
inverse lookup, exclusions, and saved-state round trips. Large-queue hardware
qualification is still pending.

Sound options wire EQ presets, track ReplayGain, crossfeed, balance, channel
mode, and preamp into per-track DSP admission. The UI explicitly applies
changes to the next track. Saved sound preferences restore independently of
the queue's library identity. Defaults retain the qualified flat audio path.
DSP performance and renewed listening checks are pending.

The JH2/JP2 history implementation uses two 4,198,400-byte banks, four cached
pages, and stable track IDs. The playing track's page and missing-record proof
are pinned against eviction. Dirty pages require paused/stopped flushing;
four distinct dirty pages can delay further admission until a flush, so
uninterrupted gapless playback under that pressure is not yet qualified.
The migration tool preserves all selected legacy records, verifies host and
device backups, and records each bank replacement. The live migration passed
after recovery into Disk Mode; both legacy banks contained zero records, and
both new banks passed full readback. Verified backups exist on host and iPod.
Receipt: `out/b04-history-migration-live/history-install-receipt.json`.
Two FAT replacements are not atomic, and an
interrupted migration requires inspecting its retained receipt and backups.

Six existing short media files were qualified against host reference decoders
and staged unchanged: two FLACs, Ogg Vorbis, mono and stereo WAV, and AAC/M4A.
AAC iTunes priming/padding metadata now trims the valid sample interval;
native seek results match linear decoding. See
`out/b04-existing-multicodec-reference.json`. The expanded 28-track library is
compiled in `out/b04-expanded-library` and published with verified reuse of
the original 22 media files; see `out/b04-expanded-publication.json`.
ALAC, AIFF, raw ADTS,
and these additional codecs on the device remain unqualified.

### Power interruption during qualification

Battery telemetry declined to 3,404 mV during development playback despite
USB being present. The prior descriptor requested only 100 mA. Development
audio builds now request 500 mA and select that budget only after USB
configuration is acknowledged, returning to safe limits on bus state changes.
Build `cc5b318d537b` responded at generation 11; initial health was 27 while
startup was incomplete. A Settings Sync request then disconnected USB, and
the user reported the iPod died. No history migration or library publication
had started. The exact cause is not established. Review found that USB stop
disabled charger input across reboot; the next candidate retains the safe
100 mA limit on an attached, nonsuspended bus during handoff, while suspended
or detached buses remain disabled. The user recovered the device using wall
power and returned it to USB Disk Mode. After the migration/publication,
Windows safely ejected it, but Apple Disk Mode did not restart automatically.
A manual reset is pending; the elevated firmware-directory refresh was not
invoked. Corrected charging and paged history still await hardware checks.

Build `e375b08d44af` includes the charging handoff correction, current-history
pin, independent sound-profile restore, AAC atom bounds hardening, and a
64 KiB MP3 no-valid-frame recovery bound. Initial ID3 tags are exempt from
that recovery budget. Existing MP3 decoding remained byte-identical; random
and zero junk now terminate without reading the entire file. This deliberately
rejects files with very large corrupt intervals instead of attempting lengthy
salvage. Development and release verification passed, and all 12 existing
simulator frames match the Batch 3 baseline. Evidence:
`out/b04-expanded-ready-build.json`, `out/b04-expanded-ready-release.json`,
`out/b04-mp3-bounded-recovery.json`, and `out/b04-aac-metadata-bounds.json`.

### Restart and expanded-library hardware follow-up

The original reviewed directory refresh restored automatic Disk Mode restart:
`out/b04-restored-restart.json` proves storage removal and exact Boot reconnect.
A subsequent upload raced Boot's automatic persistent-OS handoff. The user
confirmed a responsive Home screen, and HELLO/STATUS identified the saved
Batch 3 OS at generation 1, health 31. A fresh upload from that stable OS loaded
`e375b08d44af` at generation 2, health 31. The host now waits for healthy startup
before sending upload bytes; it does not replay an uncertain upload.

The expanded library verified all 28 tracks and 33 groups. Both FLAC clips,
Ogg Vorbis, and both WAV clips completed with zero underruns, inserted silence,
or audio faults (`out/b04-multicodec-device.json`). AAC did not meet real-time
throughput. AAC-specific `-O2` preserved host PCM exactly but still underruns
on hardware (`out/b04-aac-o2-device.json`); ARM optimization remains pending.

The first live history check exposed an existing filesystem integration bug:
registering a new media directory invalidated the write proof permanently.
Incremental renewal now checks only newly registered directory chains against
retained protected-file/directory terminal proofs, with writes blocked until
success. Aliases, cycles and failed proofs remain rejected. Paused history and
settings writes defer while renewal runs, and shutdown waits for it when writes
are needed. In build `561354531cfa`, generation 3, favorites/bookmarks showed
their saved state without a history error and storage returned `prepared=1`,
with zero failed I/O or retries. Evidence: `out/b04-history-proof-live.json` and
`out/b04-history-proof-after.png`. Reload persistence still needs verification.


### AAC read-ahead and history reload

Build `3119c3d7b394` reached generation 5, health 31. AAC ARM fixed-point
optimization alone still underruns. The actual I/O bottleneck was repeated
small sample-table and compressed-packet reads. Two bounded 16 KiB windows
reduce the existing clip from 1,656 source reads to 13, with identical PCM,
exact existing seek checks, and stable pending-read identities. The device
then decoded and consumed all 552,132 trimmed frames with zero underruns,
inserted silence, HAL faults, FIFO-empty samples, or completion lateness.
Evidence: `out/b04-aac-readcache-host.json`, `out/b04-aac-arm-emulation.json`,
`out/b04-aac-cache-device.json`. Both development and release builds passed.

Favorites and the bookmark survived a firmware reload: the options view
showed Favorite: Yes and Update bookmark (`out/b04-history-reload.png`).
This closes the first record persistence check; sustained history cache
pressure and the wider Batch 4 campaign remain open.


### Asynchronous history and measured effects follow-up

Paged history now submits bounded fixed-file read/write/flush/readback operations
through the storage arbiter and drains each admitted operation regardless of
later PCM admission changes. Dirty pages remain pinned until publication ACK;
a waiting fifth page can advance after one oldest unpinned page becomes durable.
Concurrent edits preserve a newer dirty version. Existing inline checks covered
ownership, exact request identity, permission-drop draining, mutation during
publication, reload, and proof rejection. Shutdown uses the existing 30-second
wall deadline rather than a fixed 128-step count. Eligible history phases now
receive a 1 ms deadline between operations to avoid the idle 200 ms gaps.
Hardware pressure qualification remains open.

The combined Bass EQ, ReplayGain, crossfeed, R10% balance, karaoke and -1 dB
preamp profile still underruns after DSP optimization. Host/ARM checks preserve
PCM and full DSP state, but instruction reductions alone do not close the
hardware gate. Development command 120 reports saturating decode/DSP call,
frame, elapsed and maximum duration counters since accepted primary open;
these include both current and prefetched slots. Release builds exclude them.

Two user-authorized five-second ALAC/AIFF clips decode exactly against FFmpeg
(220,500 stereo frames each) and pass host seeks. They were added to the library
with two media copies and 29 reused objects. `out/b04-full-codec-publication.json`
and `out/b04-full-codec-restart.json` record publication and a second successful
reviewed refresh/restart. Native hardware codec checks remain pending.


### Codec completion, history pressure, and large-library preparation

Bounded read-ahead for ALAC and PCM plus aligned ARM memory primitives now
allow the full ALAC, AIFF, and AAC qualification clips to complete with zero
underruns, inserted silence, HAL faults, FIFO-empty events, or completion
lateness (`out/b04-buffered-codecs-device.json`). ALAC and AIFF each consume
220,500 frames; AAC consumes 552,132 trimmed frames. Canceled pending cache
fills also pass seek/drain checks against the native decoder references
(`out/b04-additional-codecs/cancel-seek-reference.json`).

Six successive MP3 tracks touched six distinct history pages, exceeding the
four-page cache, with no audio underruns or storage failures/retries
(`out/b04-history-pressure-device.json`). A RAM firmware reload restored
Feels So Right and its saved position (`out/b04-resume-reload.json`). Normal
shutdown and persistent OS qualification are still pending.

Full stereo Bass EQ, ReplayGain, crossfeed, R10% balance and -1 dB preamp
still exceed the hardware timing budget. Moving DSP code to audited internal
RAM preserves reference PCM and Boot layout, but the live candidate still
underruns (`out/b04-dsp-iram-device.json`); no effects qualification is claimed.
Development timing version 3 includes runtime/music/storage/Link aggregates.
These counters overlap through nested storage progress; they are not exclusive
CPU accounting and must not be summed.

The user approved a temporary 100,000-entry library using one existing ALAC
file. Its 17,400,303-byte database passed host validation and an identity-guarded
metadata-only swap (`out/b04-large-library/install-receipt.json`). Original
30-track library, settings, and both history banks have verified local backups.
Hardware checks and exact restoration remain pending at this checkpoint.
Production publication validation remains unchanged; the synthetic duplicate
media paths are explicitly confined to this temporary qualification database.


Windows canceled the normal restart elevation request (error 1223) before the
helper ran. No hardware large-library test occurred. The original 30-track
PODB was restored and read back; both settings and both history bank hashes
still match their pre-check backups exactly
(`out/b04-large-library/restore-receipt.json`). Device remains in Disk Mode.
The synthetic library remains local for a later approved restart window.


The next DSP candidate uses a bounded 32-frame stage pipeline to retain filter
coefficients and histories across a block. It reduces measured ARM memory
accesses about 50% for the full stereo profile. Exact PCM and complete state
match across 180 profiles, 75,240 frames and chunk boundaries 0/1/31/32/33/65/256;
relocated ARM execution also matches. Development d1fc701d and release 98d91dc9
build and verification pass (`out/b04-dsp-block-*.json`). This candidate includes
the separately requested backlight timeout setting; both changes await hardware
qualification. No new persistent OS or Boot image was installed in this check.


### Large-library hardware findings and repair

After normal UAC restart consent succeeded, the temporary 100,000-track database
loaded with its exact expected payload hash. First/last browsing and a virtual
queue resolved correctly, with no dropped input or storage failures/retries.
However, distant pages remained Loading after 1.2 seconds and cold prefix search
was still Searching after five seconds. This failed responsiveness qualification.

The reader now caches a completed prefix lower bound and uses eight bounded
per-file FAT seek maps, each with 64 spaced anchors and proven contiguous runs.
Maps are populated during the existing full chain proof, keyed by first cluster
and published size, and invalidated with mount/mutation/error lifecycle. They do
not weaken chain validation or add a drive scan. Added volume state is 4,232
bytes. Host database-through-FAT checks reduce first-result metadata reads from
20,008 to zero on contiguous 32 KiB clusters, and to 228 on the deliberately
fragmented layout. Search pages reuse the lower bound. Boundary, permutation,
removal, async identity, cancellation/error and corrupt-chain checks pass.
Evidence: `out/b04-large-library/host-search-seek-qualification.json`.
Development bd093504 and release 0a261f63 verify; hardware recheck is underway.
The temporary database is currently installed again; exact original library,
settings and history restoration remains required after the recheck.


The device recheck shows first matching search text at an observed upper bound
of 0.823 seconds, down from more than five seconds. All ten matches, next/previous
result pages, a single match, and no matches were visually checked. Middle/last
browse titles were present by the 0.5-second observation; ALL queue repeat wraps
99999→0→99999 and removal of entry0 exposes entry1. There were no dropped inputs.
The 75 ms search target remains open. Eight-sector read-ahead on tiny metadata
is the next measured-cost candidate. Group-source full permutations and boundary
mapping are host-qualified; the device wrap check used ALL, not GROUP.

The original30-track database, both settings records and both history banks were
restored exactly and read back (`out/b04-large-library/final-restore-receipt.json`).
The subsequent restart reused the retained elevated session with no UAC prompt,
verified storage disappearance and reconnected exact Boot. The temporary corpus
remains local; no synthetic library is left on the iPod.


The per-request read-ahead candidate bc6a778f completed all eight non-MP3 format
clips on hardware with the normal profile: two FLAC, AAC, ALAC, AIFF, mono and
stereo WAV, and Ogg. Rendered and consumed frame counts equal each reference;
underruns, silence, HAL faults, FIFO-empty events and positive completion lateness
are zero (`out/b04-read-ahead-codec-regression.json`). Development/release builds
and request-ownership/bounds checks pass. The temporary large corpus was already
restored, so the new read-ahead policy has not received another physical100k
latency run; its host physical-sector reduction is160→29.

The full stereo effects combination still underruns on the internal-memory
block-DSP candidate (`out/b04-block-dsp-stereo-device.json`). A placement-only
cached-SDRAM candidate c9472bed passes native/ARM exact-output comparisons and
startup verification; its hardware A/B is in progress. No effects gate closure
or Batch4 completion is claimed.


### ARM filter hardware follow-up and queued-short-track finding

The cached-SDRAM ARM filter candidate e7c5586a passes development and release
verification and exact PCM/state checks. Hardware full-profile processing costs
about 4.57 us/frame versus 5.24 for the C cached-SDRAM candidate. Native first
MP3 playback remains error-free for the observed 20 seconds, but queued PCM
falls from 16,256 to 5,888 frames, so this is not a sustainable playback pass
(`out/b04-dsp-arm-native-first-device.json`). Another native track underruns
at 6.3 seconds (`out/b04-dsp-arm-filter-device.json`). The confirmed profile is
Bass EQ, ReplayGain on, Crossfeed on, balance R10%, stereo, preamp -1 dB.
Direct development player-open resets DSP to bypass; its separate first-MP3
result does not qualify effects, regardless of the UI's saved profile.

The flat ALAC-to-AIFF native queue check fails to prepare the next decoder and
subsequently underruns in AIFF (`out/b04-alac-aiff-join-device.json`). The ALAC
queue never reaches the 63,488-frame background admission threshold. Metadata,
next-open and background-read scheduling are under repair. Standalone codec
completion does not establish queued-transition correctness.


### Read-ahead search remeasurement and normal-library restoration

The already approved 100,000-entry fixture was reused on f4e283f8. Exact
payload verification passed. The correct first result Scale 099990 was observed
in the UI render state at 0.729 seconds cold and 0.179 seconds repeated, versus
the earlier 0.823-second cold observation. These are render observations, not
physical LCD completion: paint_count increments before transfer completion.
The 75 ms target remains unmet. Full refresh on every search/library revision
adds an LCD-transfer wait; dependent search I/O remains significant. Evidence:
`out/b04-large-library/read-ahead-search-device.json` and its captures.

The normal 30-track database and all four backed-up state files were restored
and readback verified in `read-ahead-retest-restored.json`. Both entry/exit
restarts reused the existing approved helper with no new UAC prompt. The
temporary fixture is no longer installed. The search-cache investigation is
read-only: a complete fixture cache needs about 3.8 MB and would exceed the
current 4 MiB resident-budget assertion, so no such budget change was made.


### User-approved search performance deferral

On September 6, the user explicitly deferred the 75 ms search performance
target: proceed with the batch and return to it as a later optimization.
The target originates in section 9 of the implementation plan (initial
engineering performance budgets), with final performance acceptance in Batch 7.
The functional 100k browse/search/queue checks remain passed; measured cold
first-result rendering is 0.729 s and repeated-prefix rendering is 0.179 s.
TODO: separate validated-result, render and LCD-completion timing; reduce
whole-screen search refreshes; review a bounded index/cache design within
the resident-memory budget. This latency does not block Batch 4 completion.
# Batch transition

The user authorized proceeding to Batch 5 photos with outstanding audio and
search qualification retained in `PROJECT_TODO.md`. Advanced effects and
mixed-codec gapless remain planned features. The flat native MP3 baseline was
rechecked on build `466c20474347` for approximately 42 seconds with zero audio
error diagnostics (`out/b04-original-mp3-baseline-recheck.json`). Full Batch 4
qualification is not complete.
