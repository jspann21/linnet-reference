# Apple OS library updates

Linnet uses its own PODB music index. Media Manager can separately update Apple's
music/video database and photo library so selected folders are also available
when booting the original Apple OS.

Use [Media Manager's Apple OS workflow](media-manager.md#make-folders-available-in-apple-os)
for normal updates. Native Windows helpers are included in the packaged app and
built by `python linnet setup` in a source checkout.

## Supported boundary

Updates require FAT32 and an exact qualified device/volume match. General target
support does not enable Apple database writes. The qualification loader and
admission checks are in [apple_os.py](../tools/content/apple_os.py); device
identifiers and validation receipts are not documentation examples.

The managed writer stages and verifies updates, preserves existing Apple entries
and playlists, and retains backups. Selected folder contents remain in their
original locations. Apple OS support is narrower than Linnet's media support.

## Music path constraints

The current shared-library path accepts MP3 files beneath `/Music`.
It uses real FAT short aliases and a lowercase `.mp3` suffix in Apple's
database. The relative path below `/Music` must fit 23 characters. Long filenames
alone do not determine whether their aliases fit.

A track appearing in Apple's menu does not prove playback: qualification must
confirm that it opens, its timer advances, and audio is audible.

The normal update workflow reports unsupported paths without renaming originals
or rewriting FAT directories. Historical alias-repair tools are
[device-specific maintenance tools](../tools/maintenance/a1238_apple/README.md),
not a general import requirement. Alias changes require revalidation and rebuilt
indexes in both operating systems.

See [managed music](../tools/maintenance/a1238_apple/managed_music.c) and
[managed photos](../tools/maintenance/a1238_apple/managed_photos.c) for the writers.
