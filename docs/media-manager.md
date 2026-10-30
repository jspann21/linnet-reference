# Linnet Media Manager

Manage libraries, firmware, games, and screen menus from Windows. For packaged
installation and source setup, start with the [main README](../README.md#get-started).

Use **LinnetSetup.exe** for the standard Windows installation, then open
**Linnet** from the Start menu. The optional portable ZIP runs after extraction.
See [builds and downloads](releases.md) for installation and desktop removal.

The packaged app includes Python and the native Apple database helpers.
Prebuilt firmware installation needs no compiler or WSL. Media conversion
requires FFmpeg and FFprobe; select their folder in **Settings**.

## Will this iPod work?

**iPod setup** identifies your iPod and shows whether installation is available.
Setup checks the device before writing. See [tested models](hardware.md) and
[storage requirements](storage.md); Classic CE-ATA drives are not supported.

If detection fails, enter Disk Mode, try a direct USB port, and follow the
message shown. Save a hardware report if you still need help.

### Send a hardware report

1. Open **iPod setup → Save hardware report…**.
2. Review it, then **Save report…** or **Copy report**.
3. Choose **Contact Linnet support**, describe the problem and any storage changes,
   and attach or paste the report in the GitHub issue.

Reports contain hardware and connection details, excluding serial numbers,
usernames, local paths and media. Collection is read-only; nothing uploads
automatically. GitHub issues and attachments are public and show your account.
Some hardware details require further checks outside Apple Disk Mode.

From source:

```console
python linnet hardware-report --output linnet-hardware-report.json
```

## Take an iPod screenshot

When your iPod is running a **Developer** or **Trace** build through Linnet Link,
choose **Screenshot…** in the device card at the bottom of the sidebar. The
preview offers **Copy image** to paste into another app and **Save PNG…** to
choose a file on your computer. Copy and Save also support Ctrl+C and Ctrl+S.

Screenshots capture the iPod's native screen pixels. They require a running OS
with Linnet Link; the button is disabled in Disk Mode, recovery, and User builds.
The image remains available in the preview if the iPod disconnects.

### Screen recording exploration

The existing screenshot protocol can support short, silent recordings by
capturing successive frames over one persistent Linnet Link connection.
Initial read-only checks on idle Classic and Video devices support prototyping
at **1 frame per second**. Transfer speed varies by target; sustained playback
and video capture still need qualification. Recording controls are proposed work.

The proposed first version is **Record screen → Stop → Preview → Save GIF**,
using Pillow already bundled with Media Manager. Limit a clip to 60 seconds,
preserve actual elapsed time between captures, and bound memory and temporary
storage. Capture one frame at a time and slow sampling when transfers take
longer than the requested interval. Keep one connection open, check boot identity,
and support cancellation between screenshot chunk batches. Disconnects or boot
changes must stop the session rather than silently reconnecting into another clip.

Before adding the control, verify responsiveness and audio underruns during
playback, moving video and fast navigation; also check Stop, unplug, preview,
save failure, and partial-clip recovery. GIF would have no audio and a limited
color palette. Higher frame rates or full video recording need further work on
transport performance and encoding. Detailed local measurements belong in `out/`.

## Set up FFmpeg on Windows

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
replacing the tools. FFprobe-only inspection can run when FFprobe passes its
check, but video conversion remains unavailable until both tools pass.

## Install or restore firmware

1. Connect the iPod with USB and choose **Find or switch iPod**. If it does not
   appear, **iPod setup** shows the Apple Disk Mode button sequence.
2. Open **iPod setup**, above **Preparation** in the sidebar. Check the connected
   device and setup status first. If an installation prerequisite is missing,
   the page explains it before offering firmware or build choices.
3. When installation is available, choose **Choose firmware ZIP** and select the
   whole ZIP **without extracting it**. Media Manager selects the required files.
   Source checkouts also offer a development build option.
4. Choose a build (**User build** for everyday use) and a startup method when
   there is a choice, then install. A fresh Classic finishes connected in Linnet
   Disk Mode: open **Preparation** to add media or **Eject safely** to start Linnet.
   For other installation routes, eject safely to start Linnet, then enter Linnet
   Disk Mode and reconnect before preparing media. Existing
   installations also show default startup and removal options below the
   installation controls.

On a supported native Boot installation, **Default startup** chooses which
installed system starts automatically. Hold **MENU** while the iPod starts to
open the selector and choose a different installed system. The default can be
changed without reinstalling Linnet. **Update startup selector** replaces Boot
while keeping the saved Apple firmware and recovery plan. Finish an interrupted
update with **Resume startup selector update** before making other setup changes.

Firmware installation requires a recognized target, matching USB and mounted
storage identities, and a writable FAT32 iPod volume. Unknown devices and firmware
for another target are rejected. The installer rechecks the connected device and
installation method before writing; the elevated worker also revalidates the
firmware after administrator approval. Selecting a ZIP cannot override these
checks. Photo P98, monochrome Q21, and Video M25 use native directory
installation. Classic N25 uses Media Manager's integrated NOR bootloader setup.
Removal appears only when Linnet files or a recovery record are present, or
interrupted removal can be completed.

If an iPod is detected over USB but Windows has not mounted its storage,
**iPod setup** shows the storage problem even when another iPod is connected.
Assign the existing volume a Windows drive letter, then choose **Find iPod**.

### First installation on a Classic

Choose a current Classic firmware ZIP and **Install Linnet**. The ZIP includes
the temporary bootstrap, so packaged installation needs no compiler.
Media Manager saves the selected firmware and the current USB and disk identity,
safely ejects, then asks you to hold **Menu + Select** for about 12 seconds.
Release the buttons when Media Manager detects DFU and tells you to release.
Keep USB connected throughout; subsequent restarts are automatic.
If setup fails through a hub or dock, connect the same iPod directly and choose
**Resume Classic installation**. If prompted, assign its existing FAT32 volume
a drive letter in Windows Disk Management.
These live hold/release instructions appear in a focused dialog that advances
automatically. Turn the Hold switch off before following them.

When Linnet Link is already connected, Media Manager recognizes the running OS
or recovery connection. Choose **Manage media** from a running OS, or **Open Disk
Mode** from recovery, to reconnect storage automatically. A saved, unfinished Classic setup instead offers **Resume Classic
installation** for that device. During a hosted recovery connection, the iPod
directs you to continue setup on the computer.

For a running OS, iPod setup shows its build and offers **Read startup settings**
and **Change build…**. These actions connect Disk Mode automatically, read the
installed software, and open the selected controls. The **Startup** card shows
the verified saved default in **Start automatically**, with **Save** beside it,
and explains holding Menu for a one-time startup choice. The **Linnet** card shows
the installed build. Choose **Change build or reinstall…** to open its build and
firmware controls; first installations and interrupted setups open these controls
automatically. Choose a matching firmware ZIP for User firmware or build from
source; Developer firmware requires a source checkout. Pending updates show which
build is ready to start and ask you to eject safely. Media is kept.

Linnet Link then checks RAM, panel initialization, disk identity and partition
access, reads and independently verifies the original NOR backup, authenticates
the replacement on that device, and verifies the complete flash after writing.
Unsupported RAM, storage or NOR layouts stop setup before flashing. It reconnects
through Linnet Disk Mode, preserves Apple startup and portable recovery files,
and installs and verifies the OS. The iPod stays mounted so you can prepare media
without another reboot. A successful automated check does not establish physical
LCD appearance, controls, audible output or battery runtime.

If interrupted, use **Resume Classic installation** in iPod setup. The saved
transaction keeps the exact firmware, device identity, original flash and write
receipts. Media Manager rechecks those records and the connected device before
continuing; uncertain writes are not retried automatically. Source installations
use the smaller User Boot with either User or Developer OS to fit the NOR archive.

| Startup method | Behavior |
| --- | --- |
| Existing Rockbox bootloader | Reversibly replaces the loader's firmware file and retains its predecessor for restoration. |
| Native Linnet with Apple fallback | Boots Linnet directly. Hold **MENU** during power-on to choose the preserved Apple OS. Existing Rockbox files remain dormant. |
| Native startup selector | Adds a compatible Rockbox image to the native chooser alongside Linnet and Apple OS. |

Fresh installations default to native Linnet, including when a Rockbox bootloader
is installed. A verified compatible Rockbox image is kept available in the native
startup chooser; otherwise Linnet uses Apple fallback. Reinstalls and resumes
retain their saved method. You can explicitly select the existing Rockbox loader
when it is available.

Only methods valid for the detected installation are available. Detection of
iPodLinux or other files does not imply a supported boot path.

Native installation requests Windows administrator approval for device writes.
It preserves media, partitions, and the original Apple payload, and saves
recovery backups under `%LOCALAPPDATA%/Linnet/Installer`. Firmware hashes provide
integrity checks, not signature authentication.

### Reinstall or remove Linnet

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
original media files. Choose **Remove…** to review removal. If Trash contains
items, the confirmation offers **Review Trash** or **Empty Trash and remove
Linnet**. Continuing permanently empties Trash before removing Linnet.
If the iPod has restarted since removal was reviewed,
Media Manager reconnects the same board through Linnet Link and checks its FAT
volume and disk geometry again before restoring startup software. A failed
removal clears the old connection; choose **Find iPod** to review it again.
Photo, monochrome, and Video iPods can restore through Linnet's native Disk Mode
when the verified original installation record matches. Otherwise, reconnect in
Apple Disk Mode so the saved backup can be matched to the original storage identity.

Classic A1238/N25 installations use a separate NOR flash bootloader. Media
Manager recognizes their completed bootstrap records and verified original NOR
backups. OS updates preserve portable recovery copies under `.LINNET/RECOVERY/NOR` and on
the computer. Reinstalling the OS cannot recreate a missing original NOR backup.
For Classic removal, connect in Linnet Disk Mode with a Developer build that
provides Linnet Link. Media Manager saves recovery, ejects the disk, enters the
SRAM monitor, authenticates the backup with the device, and compares the entire
flash against the saved snapshots. It restores only the original boot slot,
verifies the complete NOR, and restarts into Apple software before removing
Linnet files. Restoration, reconnection, and cleanup run in the same removal
operation; keep USB connected through the restarts. Media Manager allows three
minutes for a fresh, verified Apple disk mount and continues cleanup
automatically. If Windows has not mounted it, a dialog guides reconnection and
the Apple Disk Mode button step: turn Hold off, hold Menu + Select until the
Apple logo appears, then immediately hold Select + Play/Pause until Disk Mode
appears. A verified restoration is not repeated when only file cleanup remains.
If the wait expires, reconnect this same iPod in Apple Disk Mode, choose **Find
iPod**, then **Remove Linnet OS** again to finish cleanup. User builds need a
Developer build before this Link recovery sequence; the original NOR backup
remains the source of restoration.
If Apple is the saved startup default, removal first selects Linnet for its
automatic recovery restart. If recovery stops, Linnet remains selected so Link
can reconnect for a retry. Removal holds exclusive access to this Classic
through its restarts and verifies the recorded recovery monitor before flashing.
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

If you need the same files in Apple's original OS, check **Preparation →
Available in Apple OS** before copying media. That update is limited to the
exact qualified FAT32 devices and file paths described below.

1. Browse **Music**, **Photos**, **Videos**, or **Notes** and add files or folders.
   Adding to the queue does not copy files yet.
2. Open **Preparation**, select the media types to update, and review video choices.
3. Choose **Prepare selected media**, review the plan, and start.
4. Review skipped files or errors, then **Eject safely** and restart Linnet.

The preparation review counts videos separately from file copies. Videos are
prepared for the selected iPod and saved for Linnet playback; a queue containing
only videos does not need any other file copies. Space budgets include temporary
files and recovery copies, so they can exceed the final media size. **Show details**
lists queued sources and conversion information. Changes to existing iPod content
are always shown for review before approval.

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
Packed Video artwork includes a separately checked block index so compatible
firmware can prepare visible covers while the remaining set loads.
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
interruption; unfinished or missing sources remain visible. During preparation,
**Stop** takes effect at a safe operation boundary. The preparation report records
completed, skipped, and failed work. During device search or library scanning,
**Stop** interrupts the reader and its storage queries, discards partial results,
and releases the window for another action. If iTunes is syncing the iPod, stop
reading and let the sync finish before choosing **Refresh**. The app does not
restart a stopped scan automatically. If an iTunes music, photo, or artwork
database is locked or changes during reading, the scan stops with a message to
finish syncing and refresh. Preparation planning honors **Stop** during folder
scans and video checks, including space estimates. If a completed scan finds an
interrupted media-index update, the app keeps the blocked recovery state so it
can be reviewed before another device action.

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

On Photo, Video, and Classic, **Games** lets you choose from Comet Run,
Pulse Path, Solitaire, Sudoku, Brick, Music Quiz, Vortex, Minesweeper, Falling
Blocks, Reversi, Snake, Word Search, Scrub, Dial Heist, Mixtape, Signal,
Clockwork City, and Pocket Pinball. Each game has its own on-device controls and
best score. The Photo uses artwork drawn for its 220 × 176 display; Video and
Classic use artwork drawn for 320 × 240.
**Screens** configures supported menus.
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
combinations. Qualified models and media restrictions are listed in
[Apple OS library updates](apple-stock-music.md#supported-boundary).
The monochrome Q21 workflow offers Music only. Eligibility checks the target,
disk serial, volume serial, sector size, and any required model identity together;
matching the model alone does not qualify another iPod or a reformatted volume.
Other devices can still use Linnet media preparation when their target supports
it, but **Update Apple OS** remains unavailable until that exact device and
volume are qualified.
An iPod can contain Apple firmware while its Apple music library is empty.
Preparing Music, Photos, or Videos for Linnet does not add them to Apple's
databases; select compatible folders and complete **Update Apple OS** on a
qualified device.

The current music path accepts MP3s whose real FAT short path below `/Music`
fits the 23-character Apple limit. Prepare Music for Linnet first so its
metadata is available. Apple videos must be MP4, M4V, or MOV files below
`/Videos` with a short FAT alias that fits the 22-character video limit;
FFprobe checks their codecs and dimensions. Choose existing folders under
`/Music`, `/Photos`, or `/Videos`; Notes are read directly by Apple OS.
Unsupported paths or formats need attention, and the normal workflow does not
rewrite FAT aliases. See [Apple database behavior](apple-stock-music.md).

## iPod theme font

Install current Linnet firmware, then connect a color iPod in Disk Mode and open
**Settings → iPod theme font → Download and use Apple font**. Media Manager
downloads the 3.8 MB iPod Photo 1.2.1 archive directly from Apple's server,
checks the pinned archive and firmware SHA-256 values, and extracts Podium Sans
on your computer. It installs only the optional font file in
`/.LINNET/PODIUM.FNT`. Safely eject and restart Linnet to apply it.

The font applies to iPod Photo, iPod Classic, Classic Split, Video Paper,
Video Night, and Video Copper themes on the supported color targets. Other
themes keep their bundled fonts. The monochrome iPod keeps its own font.
Choose **Use included font**, safely eject, and restart to remove the optional
font. Missing or damaged font files fall back to the included licensed font.

The verified archive and extracted font are cached under
`%LOCALAPPDATA%/Linnet/Fonts`, allowing later installations without downloading
again. The download runs only when requested, can be stopped before publication,
and never runs the Apple updater. Regular Linnet firmware updates and reinstalls
preserve the optional font file. Preparing Notes accounts for both font choices.

Apple's software license terms apply to extraction and reuse. The Settings page
links to those terms. Apple font data is excluded from public source and
packages; keep downloaded firmware, extracted fonts, and local simulator copies
private. See the [source and provenance notice](../sdk/assets/PODIUM-SANS-NOTICE.txt).

## Computer storage settings

**Settings → Computer storage** shows the reusable cache size and location.
The default is `%LOCALAPPDATA%/Linnet/Cache/Media`. **Change location…** moves
reusable data to a dedicated local folder, verifies each copy, and saves the
choice in `%LOCALAPPDATA%/Linnet/media-cache.json`. **Open cache folder** opens
the selected location; **Refresh size** measures it again.

**Clear cache…** removes recognized reusable thumbnails, metadata, and prepared
media. They are recreated when needed. Unknown files, saved selections, recovery
records, and startup backups are kept. Moving or clearing the cache is blocked
while another Media Manager operation uses computer storage.

Saved state and receipts stay under `%LOCALAPPDATA%/Linnet/Media`; startup
backups stay under `%LOCALAPPDATA%/Linnet/Installer`. Settings provides buttons
to open both locations. Changing the cache folder does not move those records.
Removing the desktop app retains the chosen cache, recovery data, FFmpeg paths,
and other saved preferences.

## Removal, recovery, and caching

Use the library's removal controls and **Trash** to restore removed content or
permanently delete it. Moving files to `.LINNET/TRASH` is recoverable and does
not free space. Removing a prepared library does not necessarily remove originals;
preparing those originals again can recreate it.

Trash provides undo for media removals, including the library information needed
to restore playback. Each removal appears as one recoverable entry. The sidebar
badge counts those entries on the selected iPod, hides when Trash is empty, and
updates after removals, restores and permanent deletion. Internal recovery files
do not increase the count. Firmware recovery backups have their own lifecycle.

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

Reusable data uses the [configured cache folder](#computer-storage-settings).
Fast music verification checks file identity, size, and timestamps; full verification also
reads media hashes. Cached readiness is not proof of unchanged file contents.

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
failed steps and open the saved receipt. Receipts are stored under
`%LOCALAPPDATA%/Linnet/Media`; reusable data uses the configured cache folder.
Installation backups are separate under
`%LOCALAPPDATA%/Linnet/Installer`. **Diagnostics** in the footer shows the last
50 recorded operation errors on this computer. **Export support file** saves
that history as JSON with device serials, recognized paths, and email addresses
filtered out. Review the file before sharing it, since an error may still
contain a personal media name. When reporting a problem, include the target
model, the step you attempted, and any relevant preparation receipt after
checking it for personal details. **Settings → Help and About** shows the
Linnet system version reported by the app and quick setup guidance.
