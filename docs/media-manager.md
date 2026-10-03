# Linnet Media Manager

Manage libraries, firmware, games, and screen menus from Windows. For packaged
installation and source setup, start with the [main README](../README.md#get-started).

The packaged app includes Python and the native Apple database helpers.
Prebuilt firmware installation needs no compiler or WSL. Media conversion
requires FFmpeg and FFprobe; select their folder in **Settings**.

## Install or restore firmware

1. Connect the iPod in Disk Mode and choose **Find or switch iPod**.
2. Open **iPod setup**, choose a firmware ZIP or build from source, and review the detected installation.
3. Choose the Linnet version and available installation method, install, then **Eject safely**.

On a supported native Boot installation, **Default startup** chooses which
installed system starts automatically. Hold **MENU** while the iPod starts to
open the selector and choose a different installed system. The default can be
changed without reinstalling Linnet. Older native installations offer **Update
startup selector** first; that guarded update keeps the saved Apple firmware
and recovery plan. Finish an interrupted update with **Resume startup selector
update** before making other setup changes.

The installer checks hardware identity, geometry, checksums, and image
compatibility. Automatic native installation is enabled for Photo P98,
monochrome Q21, and Video M25. Classic N25 requires its separate
[bootstrap procedure](bootstrap-tooling.md); building a Classic ZIP does not
enable automatic installation.

| Startup method | Behavior |
| --- | --- |
| Existing Rockbox bootloader | Reversibly replaces the loader's firmware file and retains its predecessor for restoration. |
| Native Linnet with Apple fallback | Boots Linnet directly. Hold **MENU** during power-on to choose the preserved Apple OS. Existing Rockbox files remain dormant. |
| Native startup selector | Adds a compatible Rockbox image to the native chooser alongside Linnet and Apple OS. |

Only methods valid for the detected installation are available. Detection of
iPodLinux or other files does not imply a supported boot path.

Native installation requests Windows administrator approval for device writes.
It preserves media, partitions, and the original Apple payload, and saves
recovery backups under `%LOCALAPPDATA%/Linnet/Installer`. Firmware hashes provide
integrity checks, not signature authentication.

**Fresh reinstall** uses the saved recovery record, replaces system files, and
retains settings and prepared media. **Restore previous boot** restores the
recorded predecessor while leaving Linnet files and media in place. **Remove
Linnet OS** in **iPod setup** restores and verifies the saved previous startup
software, then removes the `.LINNET` system directory, including Linnet settings
and prepared libraries. The Music, Photos, Videos, and Notes folders remain.
The previous startup software is Apple OS when the verified recovery record
identifies Apple, or Rockbox when the iPod was installed using its loader. Media
that was prepared only for Linnet may need an Apple library sync before it appears
in Apple OS. Removal is unavailable without a verified recovery record.
Restore or empty Media Manager Trash before removal, since it can contain
original media files. If the iPod is connected through Linnet's native Disk
Mode, restart into Apple iPod software and reconnect in Apple Disk Mode so the
saved firmware backup can be matched to the original storage identity.
If cleanup is interrupted, reconnect the same iPod and choose **Remove Linnet OS**
again. Media Manager matches its host recovery copy to that iPod and resumes
the removal.
Keep the matching backup and receipt; restoration cannot be inferred from files
merely remaining on the disk.
An OS-only Link update does not replace Boot or add a newer startup chooser.

From a configured source checkout, equivalent commands are:

```console
python linnet installer inspect --mount X:/
python linnet installer install --mount X:/ --firmware path/to/firmware.zip
python linnet installer restore --mount X:/
python linnet installer uninstall --mount X:/
```

Replace the drive and file placeholders with the inspected device and package.

### Fresh development builds

Run Media Manager from source and enable **Build from source (development)**.
**User build** creates regular firmware; **Developer build** adds device-bound
diagnostics and [Linnet Link](device-link.md). Both use the native compiler
installed by `python linnet setup`.

The CLI equivalent is `installer install --mount X:/ --from-source`; add
`--build dev` for development. The default app workflow uses a prebuilt ZIP.

## Prepare your library

1. Browse **Music**, **Photos**, **Videos**, or **Notes** and add files or folders.
   Adding to the queue does not copy files yet.
2. Open **Preparation**, select the media types to update, and review video choices.
3. Choose **Prepare selected media**, review the plan, and start.
4. Review skipped files or errors, then **Eject safely** and restart Linnet.

| Media | Current behavior |
| --- | --- |
| Music | Indexes original audio and prepares artwork; up to 100,000 tracks. Playback depends on the target's native decoders. Artwork is 64 pixels on Photo/4G. Video/Classic use a 160 px cover with exact Now Playing renditions (112 px, plus 126 px on Classic) and native 130 px Cover Flow art. |
| Photos | Prepares orientation-correct thumbnails and tiled RGB565 images through Pillow. Up to 65,535 photos; default zoom dimension 640 pixels, optionally 2048. |
| Videos | Validates existing compatible video or converts for the selected target. Photo uses IPVF; Video and Classic use native MP4 backends. See [formats and limits](video-format.md). |
| Notes | Prepares plain text from UTF-8 or BOM-marked UTF-16 text/Markdown files. Up to 256 notes, 63-character titles, and 256 wrapped lines per note. |

Each preparation also updates **Files**, the device's browser for the mounted
disk. Media Manager sorts directories, resolves FAT names, prepares native-size
image previews, and wraps text for the target's fonts on the computer. It connects
source videos to their existing prepared copies. Unchanged image/text conversions
reuse the host cache; previews are copied before the directory index is published.
The device reads bounded pages as you browse. Right in Files shows the live folder
when files have changed since preparation. See [Files](files.md) for controls,
supported opening behavior, and limits.

Music uses actual FAT short aliases; verified compatibility copies handle
unsupported paths without changing originals. Notes wrap for the target's fonts;
Markdown is displayed as text. Photo and video features are unavailable on Q21.

Search with **Ctrl+F**, refresh with **F5**, and use **Clear filters** to reset a
search. Enter opens a group or file details. **Show in folder** opens a file's
location. Queue removal leaves source files intact.

Queue choices are retained per device. Completed work is reused after an
interruption; unfinished or missing sources remain visible. Stop takes effect at
a safe operation boundary. The preparation report records completed, skipped,
and failed work.

## Games and screens

On Photo and Video, **Games** selects Comet Run, Pulse Path, and Solitaire.
**Screens** configures supported menus. See the [device menu hierarchy](navigation.md)
for the default organization and controls. Save changes, eject, and restart to apply
them. Game availability follows the target manifest; it is not enabled on every
color iPod.

## Make folders available in Apple OS

**Preparation → Available in Apple OS → Choose folders…** selects existing Music,
Photos, and Videos folders. **Update Apple OS** prepares the Apple databases;
check readiness again after changing those folders. Compatible plain-text Notes
are read directly by Apple OS.

This is a separate update to Apple's library, not Linnet adopting iTunesDB as its
own index. Existing Apple tracks and playlists are preserved by the managed
writer. It is enabled only for explicitly qualified device/volume combinations.
An iPod can contain Apple firmware while its Apple music library is empty.
Preparing Music, Photos, or Videos for Linnet does not add them to Apple's
databases; select compatible folders and complete **Update Apple OS** on a
qualified device.

The current music path accepts MP3s whose real FAT short path below `/Music`
fits the 23-character Apple limit. Unsupported paths or formats need attention;
the normal workflow does not rewrite FAT aliases. Native videos are checked with
FFprobe, and photos use the supported preparation formats.
See [Apple database behavior](apple-stock-music.md).

## Removal, recovery, and caching

Use the library's removal controls and **Trash** to restore removed content or
permanently delete it. Moving files to `.LINNET/TRASH` is recoverable and does
not free space. Removing a prepared library does not necessarily remove originals;
preparing those originals again can recreate it.

After source changes, rebuild the affected library. Empty source folders do not
implicitly erase the previous published library. Video updates do not
automatically prune every older catalog entry.

Caches and receipts live under `%LOCALAPPDATA%/Linnet/Media`. Fast music
verification checks sizes and modification times; full verification reads media
hashes. Cached readiness is not proof of unchanged file contents.

Use the skipped-file controls to retry repaired sources. Preserve installation
backups and device receipts independently of disposable caches; see
[local artifacts](local-artifacts.md).
