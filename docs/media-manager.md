# Linnet Media

Open **Linnet Media.cmd** on Windows or run `python linnet media`.
Requires Python 3.11+ with Tkinter, Pillow and FFmpeg/FFprobe. Use **Locate FFmpeg**
if the tools are not on PATH. Optional Mutagen speeds up music metadata imports.

## Install or restore Linnet

Select **Install or restore Linnet…** in Linnet Media. The installer identifies
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

1. Connect in Disk Mode and select **Find iPod**.
2. Select the root Music, Notes, Photos or Videos folders to update. Subfolders
   are included. **Add files** / **Add folder** queues additions from the computer.
3. Select **Prepare & update iPod**. Progress shows preparation and publication;
   **Open report** provides details when an operation fails.
4. Safely eject, then restart Linnet if Disk Mode remains active.

Original files are preserved. A conflicting destination file stops additions
and asks for a rename. The manager prepares content; firmware installation is
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

Choose **Browse & remove…**, select entries and review **Remove selected from iPod…**.
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
Choose **Install / switch build…**, select the desired build, then choose
**Switch to User build** or **Switch to Developer build**. Switching is available
even when the version is unchanged; selecting the current profile also allows a
reinstall. This uses the same reversible fresh-install process described above,
including archiving the previous Linnet folder. A saved boot recovery record is
required to replace an existing installation. Interrupted installs must resume
with their original profile before switching.
