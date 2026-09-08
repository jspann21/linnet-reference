# Native UI implementation

Batch 3 compiles a constrained TSX language into static native C for the
220 x 176 RGB565 display. The host compiler validates syntax, layout bounds,
scene targets, resources, capabilities and theme tokens. Unsupported JavaScript
is rejected. The device has no parser, JavaScript VM, virtual DOM or UI heap.
The exact language and custom app instructions are in `sdk/README.md`.

The system selects eight shell scenes and the example Notes app through
`config/system.toml`. Music, Files and Photos use sample virtual collections;
playback and real media browsing belong to later batches. Seventeen component
types share the native renderer. Native canvas callbacks receive an explicit
clipping rectangle and remain trusted application code.

The default and Midnight themes include baked font/image resources. Content
manifests record source and output hashes. `.lapp` and `.ltheme` artifacts are
host build packages; the firmware uses their compiled C data. They are not
independently loadable device binaries.

## Rendering and navigation

Wheel input retains the previously qualified eight sensor positions per step.
Select enters a destination, Menu returns home, and left/right change scenes.
Play/Pause has no playback action yet; the existing two-second physical hold
still shuts down through storage quiescence.

Lists and three-column grids draw only visible items. Stable pages avoid
shifting the entire viewport on every wheel step. Within a page, selection
changes repaint the old and new row/cell; page crossings redraw the viewport.
The display copies only damaged regions into the retained scanout buffer.
Idle/no-change input produces no paint. Explicit animation deadlines only
repaint nodes declaring an animation dependency, and terminate on static scenes.

Scene transitions reset the arena generation and invalidate prior references.
Navigation state occupies 188 bytes with the current ABI, independent of the
50,000-row sample list and 100,000-item grid. There is no per-row allocation.

## Verification and evidence

Settings > Display controls the idle backlight timeout for battery, USB and AC
power. Select or Right advances through Never, 5, 10, 15, 30 seconds, 1 minute
and 2 minutes; Left selects the previous value. The default is 30 seconds.
The choice applies immediately and saves alongside the existing music settings
when playback is paused or stopped and storage permits writes. Shutdown and
Disk Mode drain pending settings before handing over storage.

The desktop simulator executes the same generated C and renderer as the iPod,
accepts bounded input tapes and exports RGB565 frames, PNG previews and CRCs.
It qualifies UI behavior, not peripheral emulation. Development and release
builds pass strict ARM compilation; release exclusion passes. The alternate
Midnight configuration also builds as a release image.

An inline desktop comparison checked 990 incremental frames against forced
full renders, including page crossings, reverse movement, large jumps and
clamped endpoints. Compiler checks reject malformed TSX and resources and
confirm deterministic output across Windows and Linux.

Physical scrolling measurements are in `out/b03-scroll-before.json` and
`out/b03-scroll-after.json`: ordinary list steps improved from roughly 290 ms
to 92–96 ms including host command and completion polling. Full page replacement
still measured about 257 ms. These are observed device timings, not a frame-rate
guarantee. The user confirmed clean text/selection and no LCD artifacts on the
first candidate, while reporting slow scrolling; the revised renderer addresses
that feedback.

Final device and installation results are recorded under `out/b03-*`. No
exhaustive storage or power-fault campaign is part of this UI verification.

`out/b03-hardware-final.json` passes on OS `3ac3673f2188`: all shell screens
match the oracle, large-list endpoints match, 202 scene transitions retain
188-byte arena use, no injected events drop, idle/no-change paint remains zero,
static animation terminates and three native canvas animation frames complete.
The storage rail remains off during UI checks with zero idle failures.
Settings routes Sync to the existing storage Disk Mode service; that transition
was not repeated in this UI campaign. The earlier installation/recovery
qualification remains the evidence for the underlying service.

Persistent installation is verified in `out/b03-persistent-verified.json`:
OS build `3ac3673f218852e0b7cf3a666a1257a0adb952a706ab57aa0f7f2206f9426c9e`,
image SHA-256 `3efa191ed442864d5084bfac856878de65b21429eac3abbe95f2fd0021c5ddc1`,
111,512-byte envelope, confirmed slot A, health 31, no pending candidate and
zero storage errors. It was installed over Linnet Link without UAC. Startup
still took over two minutes and remains a performance limitation. The user confirmed the revised
scrolling is much better. Accelerated scrolling for large collections is a
future enhancement; preserve precise slow wheel movement when adding it.

## Runtime themes and simulator evidence (September 2026)

Settings > Themes selects Linnet, Midnight, iPod Photo, Graphite, Aurora,
Sunset, or Blueprint. Wheel highlights a choice; Select applies immediately.
The active choice has an asterisk. Menu returns to Settings. The picker,
Extras and Clock scenes are appended, preserving existing scene indices.

Each theme compiles a complete immutable scene table and font descriptor.
`tools/content/layouts.py` lowers semantic application nodes into different
bounded rectangles on the 220 x 176 display. Graphite uses cards and a footer,
Aurora a status rail, Sunset numbered serif lists, Blueprint two-column menu
tiles with bottom status, and iPod Photo full-width 22-pixel menu rows.
The iPod Photo geometry is based on Apple's color iPod user guide screen images:
https://cdsassets.apple.com/live/6GJYWVAV/user/ma92_ipod_user_guide_color_display.pdf
The licensed font approximates Apple's original typography.

All 17 components resolve 13 semantic color roles, including status, battery,
selection, borders, scrollbars, progress, dialogs, toasts and the Notes canvas.
Decorative images are tinted; dynamic media pixels retain their appearance.
Theme changes invalidate the full frame. List movement keeps bounded damage.
The native navigation state occupies 196 bytes. Visible capacities derive from
the selected layout, including the iPod Photo grid's 20 thumbnails.

Battery charge, charger/external power, headphones, Hold and music/video
playback symbols use live cached state. The PCF50605 RTC is read at the existing
one-second power poll, with BCD/calendar validation and no reads from the painter.
Clock minutes and validity trigger repaint; invalid time is `--:--`.
Clock > Select opens `linnet.system.clock-edit`, appended after existing scenes.
The memory-only draft exposes year/month/day/hour/minute and an explicit Save
row. Wheel selects a field; Select enters editing, wheel adjusts the value,
and Select accepts it. Menu cancels unsaved changes and returns to Clock.
Month/year edits clamp the day to the valid calendar range (2000 through 2099).
An invalid or unavailable calendar opens an explicitly unverified draft; it is
never written automatically. Save sets seconds to zero and HAL computes weekday.

Foreground entry and Save reject initialized/playing/paused audio, pending music,
active/pending video, pending photos, busy storage, Hold and shutdown/sleep.
Saving is rendered and drained before a later iteration calls the HAL setter.
The admission checks run again immediately before that call. Verified success
returns to Clock; unavailable, invalid, restored or unknown results remain visible
and never claim success. Calendar writes are bounded but not power-loss atomic.
Physical RTC programming and reboot persistence require the separate scheduled
device check. Rendering and draft editing never perform I2C operations.

Persistence uses optional THEME0/1 records, preserving the existing LDS4
music/photo/video/display/battery envelope. For an existing identified Disk
Mode installation, use the additive provisioning command before installing a
theme-enabled OS (replace every identity placeholder with an observed value):

```console
python linnet storage theme-provision --mount DRIVE --disk-serial SERIAL --disk-bytes BYTES --confirmed-build FULL_SHA256
```

Without those files the theme remains usable for the current session; the
footer reports `This session`. Host provisioning validation covered payload
bounds, IDs, defaults, idempotent preservation, missing-copy repair and
same-generation conflicts. Eight legacy settings functions were compared
byte-for-byte with the earlier source snapshot and remain identical.

Current simulator output is under `out/theme-layouts/`: seven tapes select
through Settings, visit all 25 screens, and exercise Hold, headphones, empty/full
battery, charging/external power, unknown battery/time, midnight and play/pause.
Each run saves native RGB565 frames, PNGs, CRC/SHA records and a gallery.
The simulator's metadata and hardware inputs are explicit samples. Device LCD,
physical input transitions, real playback and durable persistence require the
integrated device checks coordinated with the Continue building conversation.
