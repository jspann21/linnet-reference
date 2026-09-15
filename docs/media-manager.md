# Linnet Media

Open **Linnet Media.cmd** on Windows or run `python linnet media`.
Requires Python 3.11+ with Tkinter, Pillow and FFmpeg/FFprobe. Use **Locate FFmpeg**
if the tools are not on PATH. Optional Mutagen speeds up music metadata imports.

## Install or restore Linnet

Select **Linnet installation…** in Linnet Media. The installer identifies
the mounted iPod from its RetailOS hardware records, USB identity and storage
geometry, then chooses the build target automatically. Current targets are the
iPod Photo A1099 (`photo4g-p98`) and iPod 4G MP102 (`ipod4g-q21`).
Additional compatible models are discovered from their target manifests; see
[adding a target](../targets/README.md).

The review shows Apple software, Rockbox, iPodLinux/Podzilla markers and any
existing or incomplete Linnet installation before enabling installation. With
a compatible Rockbox file loader, Linnet uses that reversible boot path. Other
supported devices use a verified native directory redirect after normal Windows
administrator approval. Both paths preserve the existing filesystem, partitions,
media and Apple firmware payload. The native path saves the original MBR and
firmware partition under `%LOCALAPPDATA%\Linnet\Installer`, verifies all Linnet
storage files, writes a new loader only into an unused firmware extent, and
publishes one directory sector last.

Before installing, choose **User build** for the normal release OS without
developer transport or instrumentation, or **Developer build** for the
device-bound development OS with Linnet Link. The bootloader uses the same
profile as the OS: user installs exclude USB Link, crash capture, and diagnostic
logging from both images; developer installs bind both images to the detected
iPod. User builds retain boot rollback state and the on-screen fault/reset path.

Choosing either Linnet build makes that build the default boot. The same list
also shows the Apple software, Rockbox, iPodLinux and Podzilla installations
found on the mounted iPod. A detected installation can be selected when Linnet
has a verified recovery path for it: the saved Rockbox boot file for a
Rockbox-based installation, or the original firmware directory for a native
installation. Detected software without a verified activation path remains
visible as unavailable.

Rockbox files can remain after its bootloader is removed. In that state Rockbox
is shown as detected but unavailable, with instructions to install its
first-stage bootloader through Rockbox Utility before making it the default.

The supported default-boot transitions are:

| Current boot state | Selected default | Installer action |
| --- | --- | --- |
| Apple software | Linnet | Back up the firmware partition and publish the native Linnet directory redirect. |
| Rockbox | Linnet | Back up and replace `.rockbox/rockbox.ipod`; retain Rockbox as the recoverable predecessor. |
| Native Linnet | Apple software | Restore the saved original Apple directory sector. |
| Linnet through Rockbox | Rockbox | Restore the saved Rockbox boot file. |
| Rockbox installed and then removed over native Linnet | Apple software | Verify Rockbox's moved payload copies and bounded residue, then restore the saved Apple directory sector. |

Rockbox installed over native Linnet is detected as the current default when its
valid file, Rockbox Utility bootloader record and timestamps supersede Linnet's
older journal. Removing that Rockbox bootloader exposes native Linnet again;
Rockbox's files remain detected but inactive.

If Rockbox Utility installs a valid Rockbox file and records a bootloader update
after Linnet's native installation, the scan identifies Rockbox as the current
default instead of trusting Linnet's older recovery journal. Switching back to
Linnet then preserves the old `LINNET` folder and adopts Rockbox's reversible
file-loader path.

Interrupted file preparation is resumable only when every existing Linnet file
matches the same build byte-for-byte. When a saved recovery record is available,
**Fresh reinstall** first restores the previous boot, renames the old `LINNET`
folder to the first free `LNETOLD0` through `LNETOLD9` archive, and installs a
clean current copy. It does not translate old Linnet state or touch the media
folders. **Restore previous boot** restores the recorded Rockbox file or original
native directory; it leaves media and the `LINNET` data folder in place. Always
use **Eject iPod** before restarting.

The same workflow is available from the command line:

```powershell
python linnet installer inspect --mount E:\
python linnet installer install --mount E:\ --build user
python linnet installer install --mount E:\ --build dev
python linnet installer restore --mount E:\
```

## Update content

The main window shows **Default boot** beneath the connected-iPod selector. It
reports the verified active Linnet build, Rockbox, Apple iPod software, or
Unknown when the scan cannot establish one. When another system is the default,
the installed Linnet build is shown separately as inactive files on the device.

1. Connect in Disk Mode and select **Find iPod**.
2. Review all four media types in the preparation overview. Each shows the
   number of source files and its readiness for Linnet. Music, Notes and Photos
   are prepared as complete libraries; individual file browsing is not needed.
3. Check the types to prepare. Uncheck a type to skip it without removing files.
   Use **Choose music…** to select audio files from the computer to copy into the
   iPod's Music folder and include in the prepared song library.
   Use **Choose videos…** to open one video preparation window. Select originals
   already in the iPod's Videos folder for conversion, or add videos from the
   computer to the conversion list. Native `.ipv` and `.ipvf` files already on
   the iPod are shown separately, cannot be selected for conversion, and are
   added to the playback library automatically.
4. Select **Prepare selected media**. Unchanged content is reused. **View report**
   provides operation details. If a specific file fails, Media Manager skips it
   automatically and finishes the rest of the update. Select it in **Files that
   need attention** to open its folder or retry it after fixing it. Settings
   contains preparation options and library recovery.
5. Select **Eject iPod**, then restart Linnet if Disk Mode remains active.

The main window is a fixed preparation overview with no page scrollbar. Place
source media in the Music, Notes, Photos and Videos folders on the iPod, then
choose **Check readiness** to detect changes.

Original files are preserved during preparation. Firmware installation is
separate.

| Folder | Preparation and limits |
| --- | --- |
| Music | Indexes original audio, metadata and 64×64 artwork; up to 100,000 tracks. Native codec support determines playback. |
| Notes | UTF-8 or BOM-marked UTF-16 `.txt`, `.text`, `.md`; 256 notes, 63-character titles, 256 wrapped lines per note. |
| Photos | JPEG, PNG, BMP, TIFF and WebP via Pillow; orientation, thumbnails and tiled RGB565 copies. Up to 65,535 images; zoom dimension 640 pixels by default or 2048 for higher detail. |
| Videos | Indexes native IPVF in place; converts FFmpeg-readable video to IPVF. Up to 256 named videos; each under 2 GiB. |

Notes display plain text, including Markdown source. Unsupported characters
are adapted to the font and reported; oversized notes must be split. Select
opens a note, wheel or Previous/Next scrolls, and Menu returns.

Music indexing uses actual FAT short aliases, with limits of 16 path components
and 255 path bytes. Albums are grouped by album artist, with compilation and
guest-credit handling; individual track artist credits are preserved.
Unsupported aliases get verified compatibility copies under
`LINNET/MUSIC`; originals remain. Missing files or alias lookup failures stop
import. Compressed audio is decoded once on the computer to count samples for
track duration and playback progress, including files without duration headers.
Up to four tracks are processed concurrently, and counts are cached for subsequent updates.

To prepare photos separately:

```powershell
python linnet photos compile --source "C:\Photos" --output out/photos.pimg
python linnet photos inspect out/photos.pimg
```

Add `--max-dimension 2048` for more zoom detail and larger files. In the device
viewer, wheel zooms, Previous/Next changes photos, Play/Pause toggles slideshow,
Menu goes back, and Select opens pan/rotation/fit controls.

## Remove content

Use **Settings… → Prepared library recovery…** to remove an entire prepared
library or restore previous removals. Manage original files in Windows Explorer.
Device files move to `LINNET/TRASH` with a recovery receipt; this does not reclaim
space. Removing a video catalog entry retains its original unless that source
is also selected. Computer cache entries are read-only.

Rebuild Music, Notes or Photos after removing source files. Empty folders preserve
the previous published library; use the **Entire published … library** row to
clear it. Updating a folder whose originals remain can recreate removed content.
Video updates add or replace entries without automatically pruning old ones.

## Caching and interrupted updates

Cache and receipts live under `%LOCALAPPDATA%\Linnet\Media`, separated by device
identity. Completed music metadata and prepared videos are reused on retry.
Preparation needs additional host and device space.

Files skipped after an error remain in their original folders but are omitted
from future prepared libraries. Each media row shows the skipped count. Retry a
file from **Files that need attention**, or use **Settings… → Files skipped during
preparation** to include it again without immediately updating.

Fast music indexing checks paths, sizes and modification times and reuses cached
sample counts, without hashing all existing audio. The first update reads compressed
tracks to determine duration. **Verify entire audio files (slow)** also hashes them.
Use **Rebuild unchanged content** when files changed without size/time changes.
Prepared database/artwork and newly copied files are verified independently.

**Stop after current step** waits for a safe stopping point. Video conversion and
file copying can stop midstream; leave the window open while partial files are
cleaned up. Completed content remains. After errors or disconnection, inspect
**Open report** for incomplete publication, backups and scratch files before
retrying. Failed publication is not automatically replayed.

Media Manager shows the confirmed installed OS as **User build**, **Developer
build**, or **Developer trace build**, with its build ID and any pending candidate.
Choose **Linnet installation…**, select the desired boot software, then choose
the default-boot action. Linnet User and Developer builds are available alongside
the detected boot software. Selecting the current Linnet profile also allows a
reinstall. Switching to another installation restores its saved, verified boot
path; switching back to Linnet uses the same reversible fresh-install process
described above, including archiving the previous Linnet folder. A saved boot
recovery record is required to replace an existing installation. Interrupted
installs must resume with their original profile before switching.
