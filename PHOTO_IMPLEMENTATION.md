# Batch 5 photos

Batch 5 adds a prepared photo library and native photo service. The user
authorized advancing from Batch 4 with its remaining work in `PROJECT_TODO.md`.
Hardware qualification of this batch remains open.

Compile a selected source folder without modifying its originals:

```powershell
python linnet photos compile --source C:\path\to\photos --output out\photos\library.pimg
python linnet photos inspect out\photos\library.pimg
```

The compiler uses Pillow to apply EXIF orientation, prepare RGB565 thumbnails
and generate resolution levels split into 32×32 tiles. The format and its
validation limits are specified in `PIMG_FORMAT.md`. The service pages catalog
records and tiles through fixed caches, instead of loading every photo or index
into RAM. Rendering uses a separate completed surface, so the shell does not
display partially decoded JPEG output. LCD transfers use the existing COP
display worker.

The photo service admits new work when the player has sufficient PCM queued;
previously accepted storage operations retain their owner until completion or
cancellation is drained. JPEG fallback accepts bounded baseline grayscale or
YCbCr data, applies its declared orientation, and uses cooperative decode steps.
Unsupported formats fail with an unavailable-image state. Normal prepared photos
can originate from formats such as progressive JPEG because the host performs
their conversion.

The native shell provides album selection, a six-thumbnail page, and a viewer.
In the viewer, the wheel zooms, left/right change photos, Play/Pause toggles a
five-second slideshow, Menu returns to the album, and Select opens controls.
Controls choose wheel zoom or horizontal/vertical pan, rotate clockwise, toggle
the slideshow or fit the image. The existing two-second Play/Pause shutdown
gesture remains active. Album folders are listed by their relative names.

Photo resume uses 16 bytes in the shared LDS2 settings envelope. Music and
display preferences are preserved. Restore waits for a matching validated
catalog identity. Background slideshow changes do not count as user activity
for backlight timeout.

Publication uses an explicitly identified Windows Disk Mode volume:

```powershell
python linnet photos publish --package out\photos\library.pimg --disk-number 4 --disk-serial JQ5081G3SAY --volume-serial 3D9E4E60 --drive F:
```

Those example identities describe the current development device and must be
verified for each connection. Publication validates the complete package locally,
retains any previous package, writes and verifies a temporary file, replaces
`/LINNET/PHOTOS/LIBRARY.PIM` last, and records a receipt. It uses normal filesystem
permissions. Safe eject/restart is a separate operation using the existing
plan-bound helper session. FAT rename durability still depends on successful
flush, device power and storage firmware.

## Evidence and remaining qualification

- `out/b05-pimg-host-check.json`: deterministic output and corrupt data rejection.
- `out/b05-pimg-orientation-check.json`: EXIF orientation, fallback reference and
  semantic validation checks.
- `out/b05-jpeg-reference.json`, `out/b05-jpeg-sanitizer.json`,
  `out/b05-jpeg-arm.json`: existing JPEG samples, orientation, bounds and native
  ARM/host pixel equivalence. Instruction counts are not hardware timing proof.
- `out/b05-photo-native-host.json`: compiled-package rendering, navigation,
  resume, cancellation, audio admission, corruption and actual JPEG fallback.
- Existing native simulator navigation and scene tapes ran under
  `out/b05-navigation-simulator` and `out/b05-scenes-simulator`.

Both development and release firmware builds passed, including release exclusion.
Reports are `out/b05-integrated-dev.json` and `out/b05-integrated-release.json`.
The development build's resident region including stacks ends at 3,604,208 bytes,
within the existing 4 MiB limit. This does not include separately reserved update,
recovery and hardware buffers, which remain visible in the complete build report.

Still required: physical image-quality and control checks, reboot resume, native JPEG fallback on hardware,
and successful concurrent audio qualification. The previous audio baseline's candidate was
published, but the device subsequently returned to confirmed Batch 3 firmware.
The persistent candidate is no longer offered, and its failed boot needs
diagnosis (`out/b04-persistent-fallback-storage.json`). Batch 5 was then loaded
into RAM and reached health 31 with the normal 30-track library intact
(`out/b05-ram-healthy.json`). It has not been published as the persistent OS.
The 25.875-second native MP3/navigation check passed with zero underruns, silence
frames, audio faults, FIFO-empty samples or positive completion lateness
(`out/b05-device-baseline-check.json`). This checks the absent-photo-library path;
it does not qualify decoding or photo reads concurrently with playback.

Large catalogs currently undergo a complete metadata check in bounded chunks
before browsing. Its first-open latency remains to be measured. Exact empty-folder
resume is implemented below; persistent device qualification remains open.

### Small selected hardware sample

The user limited selection to needed types and sizes. Only two Anna JPEGs
(landscape and portrait) and seven existing local format/dimension samples were
copied. `out/b05-photo-sample/selection.json` records source hashes. The installed
9-photo PIMG is 20,167,168 bytes; its publication and automatic restart receipts
are in the same directory. No complete source-folder package was published.

Hardware exposed a reentrant storage-poll callback that advanced the photo state
machine twice. A step guard and cancellation-epoch completion checks fix it.
`out/b05-photo-reentrancy-native-host.json` reproduces the old failure and verifies
the correction. A completed-frame latch also removes repeated idle tile scans.
Development and release checks passed in `out/b05-photo-idle-dev.json` and
`out/b05-photo-idle-release.json`. RAM build
`e307f3ef0592569d6b0172445ca16fa3e4516b33b48fd16d3350646699d5efb8`
reached health 31, generation 5.

`out/b05-photo-sample/controls-current.json` records successful native portrait
pixel equality, zoom, rotation, second-page thumbnail selection and slideshow
advance. Landscape pixel equality passed in `first-view-fixed.json`. Physical
control feel and image appearance still require the user. `audio-controls-idle-fix.json`
recorded one underrun and 1,024 silence frames when reopening a preloaded viewer
early in playback; this remains a failed concurrency result pending comparison
with an equal-duration Home baseline. It is not evidence of clean concurrent audio.

The bounded comparison `out/b05-photo-sample/audio-home-comparison.json` passed
12 seconds on Home followed by 4 seconds in a preloaded photo viewer with zero
underruns, silence frames, FIFO-empty or completion lateness. The ring had filled
before entering Photos. Early-playback entry and uncached photo interaction remain
unqualified; this limited comparison does not close the concurrency gate.

The user confirmed photos load, with noticeable loading latency, and authorized
continuing to Batch 6. Loading speed and the remaining qualification gates are
tracked in PROJECT_TODO.md; Batch 5 is not claimed fully qualified.

## Empty-folder resume and descriptor cache follow-up

Empty album selection now roundtrips through the existing16-byte resume and LDS4
envelope. Photo index65535, outside valid PIMG indices0..65534, identifies an
empty album; the pan word carries its album index. Restore verifies catalog,
album bounds and zero count. Legacy records and music/battery fields are preserved.

A512-byte cache holds up to64 adjacent tile descriptors, replacing repeated8-byte
metadata requests. It publishes only after a completed current-generation read,
and invalidates on cancellation/failure. Tile payload sizes, CRCs, padding checks
and audio admission stay bounded. Ephemeral native checks and independent review
passed (`out/b07-photo-resume-cache-validation.json`); device speed is not yet measured.

RAM OS550949694b90 reached health31. First, next and previous image navigation
passed with stable screenshots of the expected images, 35/20 visible tiles and
no photo error or crash (`out/b07-photo-ram-health.json`,
`out/b07-photo-device.json`). PHOTOS_STATE omits render-completion flags, so its
idle phase and revision changes cannot establish exact loading latency. These
checks demonstrate navigation and visual output, not a measured speed gain.
Empty-album persistent resume, physical controls and concurrent uncached audio
remain open; the existing nine-image sample was retained.

The integrated media OS8495bdea580d subsequently reached persistent confirmed
slotB, attempt40, health31, no pending candidate or crash, and retained1200mAh
settings (`out/b07-media-persistent-health.json`). This startup result does not
replace the remaining photo-specific qualifications.
