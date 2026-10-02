# Linnet Media Manager

Manage libraries, firmware, games, and screen menus from Windows. For packaged
installation and source setup, start with the [main README](../README.md#get-started).

The packaged app includes Python and the native Apple database helpers.
Prebuilt firmware installation needs no compiler or WSL. Media conversion
requires FFmpeg and FFprobe; select their folder in **Settings**.

### Set up FFmpeg on Windows

1. Obtain a Windows FFmpeg build and extract it to a folder you can keep. Find
   `ffmpeg.exe` and `ffprobe.exe` together, usually in its `bin` folder.
2. In Media Manager, open **Settings → Choose FFmpeg folder** and select the
   folder containing both executables. The app runs each tool's `-version`
   check and shows **FFmpeg and FFprobe are ready** when both pass.
3. Return to **Preparation** and review the video plan. Video conversion needs
   both tools; checking videos for Apple OS needs FFprobe. Some music metadata
   and FLAC preparation also use FFprobe.

Media Manager checks for both commands on `PATH` when it starts, but choosing
their folder records exact paths. If the check fails, confirm that you selected
the folder containing both `.exe` files and that each runs from PowerShell:

```powershell
& 'C:\path\to\ffmpeg\bin\ffmpeg.exe' -version
& 'C:\path\to\ffmpeg\bin\ffprobe.exe' -version
```

Replace the example path with your extracted folder. The status in Settings
reports which tool could not run. Choose the folder again after moving or
replacing the tools; conversion will remain unavailable until both checks pass.

## Install or restore firmware

1. Connect the iPod in Disk Mode and choose **Find iPod**.
2. Open **iPod setup**, choose the firmware ZIP for the device, and review the detected installation.
3. Choose an available startup method, install, then **Eject safely**.

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
recorded predecessor while leaving media in place. Keep the matching backup and
receipt; restoration cannot be inferred from files merely remaining on the disk.
An OS-only Link update does not replace Boot or add a newer startup chooser.

From a configured source checkout, equivalent commands are:

```console
python linnet installer inspect --mount X:/
python linnet installer install --mount X:/ --firmware path/to/firmware.zip
python linnet installer restore --mount X:/
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

If you need the same files in Apple's original OS, check **Preparation →
Available in Apple OS** before copying media. That update is limited to the
exact qualified FAT32 devices and file paths described below.

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
and failed work. During a scan, device search, or preparation planning, **Stop**
waits for the current read-only check to return and discards its result; the
window remains busy until that check finishes.

## Playlists, games, and screens

After preparing Music, open **Music → Playlists** to create a playlist, search
the prepared song library, add songs, and arrange their playback order with
**Up**, **Down**, **Move to top**, and **Move to bottom**. Choose **Save to iPod**,
then eject safely. A device holds up to **16 playlists**, each with up to
**1,024 song entries**. Names can use
1–31 UTF-8 bytes; a character outside ASCII may use more than one byte.
Missing tracks are shown in the editor so you can remove or replace their
entries. Changes in the editor take effect only when you choose **Save to iPod**.

**Import M3U…** reads a UTF-8 `.m3u` or `.m3u8` file and creates a new playlist.
Review matched and unmatched entries before choosing **Import matched songs**;
unmatched or ambiguous entries are skipped, and the imported playlist still
needs **Save to iPod**. Import is blocked when 16 playlists already exist or
more than 1,024 songs match. Files above 2 MiB or 10,000 entries are rejected.
**Export M3U…** writes the selected playlist in its current order as UTF-8
M3U text. If a track is missing from the prepared library, export reports it
instead of writing an incomplete playlist.

On Photo and Video, **Games** lets you choose from twelve games: Comet Run,
Pulse Path, Solitaire, Sudoku, Brick, Music Quiz, Vortex, Minesweeper, Falling
Blocks, Reversi, Snake, and Word Search. **Screens** configures supported menus.
See the [device menu hierarchy](navigation.md) for the default organization and
controls. Save changes, eject, and restart to apply them. Game availability
follows the target manifest; it is not enabled on every color iPod. If game
settings cannot be read because they are damaged, use **Replace damaged game
settings** to choose and save a new selection.

## Make folders available in Apple OS

**Preparation → Available in Apple OS → Choose folders…** selects existing Music,
Photos, and Videos folders. **Update Apple OS** prepares the Apple databases;
check readiness again after changing those folders. Compatible plain-text Notes
are read directly by Apple OS.

This is a separate update to Apple's library, not Linnet adopting iTunesDB as its
own index. Existing Apple tracks and playlists are preserved by the managed
writer. It is enabled only for explicitly qualified **FAT32** device/volume
combinations. The current allowlist contains one **iPod Video MA146** specimen
and one **iPod classic MB147** specimen. Eligibility checks the target, disk
serial, volume serial, and sector size together; matching the model alone does
not qualify another iPod or a reformatted volume. Other devices can still use
Linnet media preparation when their target supports it, but **Update Apple OS**
remains unavailable until that exact device and volume are qualified.

The current music path accepts MP3s whose real FAT short path below `/Music`
fits the 23-character Apple limit. Prepare Music for Linnet first so its
metadata is available. Apple videos must be MP4, M4V, or MOV files below
`/Videos` with a short FAT alias that fits the 22-character video limit;
FFprobe checks their codecs and dimensions. Choose existing folders under
`/Music`, `/Photos`, or `/Videos`; Notes are read directly by Apple OS.
Unsupported paths or formats need attention, and the normal workflow does not
rewrite FAT aliases. See [Apple database behavior](apple-stock-music.md).

## Removal, recovery, and caching

Use the library's removal controls and **Trash** to restore removed content or
permanently delete it. Moving files to `.LINNET/TRASH` is recoverable and does
not free space. Removing a prepared library does not necessarily remove originals;
preparing those originals again can recreate it.

After source changes, prepare the affected library again. When a same-name
source would replace an existing file, an empty source folder would retire a
published library, or a video catalog contains a missing entry, the
**Review preparation changes** dialog lists each proposed action. Check that
list before **Approve changes and prepare**. Approved existing files and
retired libraries move to recoverable Trash; the video catalog is backed up
before missing entries are removed from its index. Canceling the review leaves
those changes unapplied.

If Videos shows **Needs repair** because its catalog is damaged, open
**Preparation → Review catalog backups**. The picker shows validated on-device
backups and their titles; restoring one saves the damaged catalog bytes for
recovery. Videos added after that backup may need preparation again. If no
complete backup is available, the app keeps the damaged catalog and prepared
videos in place for manual recovery.

Caches and receipts live under `%LOCALAPPDATA%/Linnet/Media`. Fast music
verification checks sizes and modification times; full verification reads media
hashes. Cached readiness is not proof of unchanged file contents.

Use the skipped-file controls to retry repaired sources. Preserve installation
backups and device receipts independently of disposable caches; see
[local artifacts](local-artifacts.md).

### Reconnect and collect diagnostics

If an iPod disconnects during an operation, reconnect it in Disk Mode and use
**Refresh** to rediscover and inspect its current state. **Choose iPod** in the
sidebar is available whenever you need to select a device; when multiple iPods
are found, choose the intended one in the picker. A failed scan clears the old
connection so the next Refresh can rediscover the volume. Review the library
and preparation status before another write; do not assume that an interrupted
step finished.

If the app shows **Media index recovery needed**, choose **Recover media indexes**
and review the affected Music or Photos groups. Keep the iPod connected while
the app checks its saved recovery record and restores a verified index set.
The app holds normal library actions and eject until recovery finishes, then
rescans the collection. Leave the recovery files on the iPod for the app to
inspect; an invalid record needs manual attention.

After preparation, open **Preparation details** to see completed, skipped, and
failed steps and open the saved receipt. Receipts and cache data are stored under
`%LOCALAPPDATA%/Linnet/Media`; installation backups are separate under
`%LOCALAPPDATA%/Linnet/Installer`. **Diagnostics** in the footer shows the last
50 recorded operation errors on this computer. **Export support file** saves
that history as JSON with device serials, recognized paths, and email addresses
filtered out. Review the file before sharing it, since an error may still
contain a personal media name. When reporting a problem, include the target
model, the step you attempted, and any relevant preparation receipt after
checking it for personal details. **Settings → Help and About** shows the
Linnet system version reported by the app and quick setup guidance.
