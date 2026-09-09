# Linnet Media

Double-click `Linnet Media.cmd` in the project folder, or run:

```powershell
python linnet media
```

Requires Windows, Python 3.11+ with Tkinter, Pillow (`python -m pip install Pillow`),
and FFmpeg/FFprobe for compressed music and video conversion. The app detects
executables on PATH; **Locate FFmpeg** selects their folder when needed.
Install the optional fast music tag reader with `python -m pip install mutagen`.
It avoids launching a separate metadata process for each common audio file.

## Everyday workflow

1. Connect the iPod in Disk Mode and choose **Find iPod**. The app verifies the
   Apple USB disk and FAT32 volume without asking for disk serials or elevation.
2. Review file counts in Music, Notes, Photos and Videos. Select the folders to
   update. These are the folders at the root of the iPod, including subfolders.
3. To add content, select its media type and choose **Add files** or **Add folder**.
   A selected folder is preserved beneath that media folder, including its cover
   art and other supporting files. Pending additions appear before any copying.
4. Click **Prepare & update iPod**. Copies are verified, then prepared content is
   published using the existing guarded publication tools. Progress and errors
   remain visible. **Open report** shows detailed receipts.
5. Safely eject the iPod using Windows, then restart Linnet if Disk Mode remains.

## Browse and remove content

After scanning, choose **Browse & remove…**. Filter by folder or search names
and paths. The list distinguishes original files, published libraries/videos on
the iPod, missing video catalog entries, and prepared video copies on the computer.
Select an item to see its exact location or open its containing folder.

**Remove selected from iPod…** reviews the selection, removes video catalog
entries, and moves selected device files to `LINNET/TRASH` with a recovery receipt.
This is reversible file removal and does not reclaim disk space. Removing a video
catalog entry pointing to an original retains that original unless its source row
is also selected. Computer cache rows are read-only.

After removing Music, Notes or Photos source files, update that folder to rebuild
its published library. To clear a whole published library, select its **Entire
published … library** row. This is also necessary when all source files have been
removed, since updating an empty folder preserves the previous library. Updating
a folder with its originals still present can recreate a removed library.

Video conversion shows a percentage, converted/estimated-total frame count,
elapsed time and an approximate time remaining for the current conversion.
The progress bar fills as conversion advances, with the current video's position
in the selection shown beside its status. Estimates settle after conversion
starts and may change with scene complexity. Final validation has its own
progress; copying/publication is a separate step. A stage only reaches 100%
after it completes successfully. Before a total is available, the app shows
frame counts and elapsed time instead of inventing a percentage or ETA.

The app does not install firmware. Build/install the updated firmware using the
existing device workflow before using existing music paths, Extras > Notes, or
the multi-video list. Existing filenames, source documents and source media are
preserved. A different file at the same destination stops additions with a
rename instruction; it is never overwritten automatically.

## Preparation by folder

| Folder | Processing | Current limits |
| --- | --- | --- |
| Music | Metadata, browse/search database and 64×64 artwork; references original audio in place | Up to 100,000 tracks; native codec support still determines playback |
| Notes | UTF-8 or BOM-marked UTF-16 `.txt`, `.text`, `.md` to a prepared text catalog | 256 notes, 63-character display titles, 256 wrapped display lines per note |
| Photos | Orientation, thumbnails and tiled RGB565 images with zoom levels | 65,535 images; standard maximum zoom dimension 640 pixels, high 2048 |
| Videos | Native IPVF indexing or conversion to IPVF, named playback files and a title catalog | 256 named videos; each file at most 2 GiB minus one byte |

The Notes reader displays plain text, including Markdown source. Non-ASCII
characters are adapted to the available font, with affected filenames listed in
the report. Documents beyond the limits fail with instructions to split them;
text is not silently truncated. Select opens a note; wheel and Previous/Next
scroll; Menu returns to the list.

Music indexing resolves actual FAT short aliases for long Rockbox filenames.
The firmware supports up to 16 path components and 255 path bytes. Paths with
unsupported aliases get a verified compatibility copy under `LINNET/MUSIC`,
while the original remains in place. This covers accented short names such as
`BEYONCÉ`, which the native file reader cannot open. Only affected tracks are
copied; compatible tracks continue to be indexed in place. The report lists
these copies. Missing files and drive/alias lookup failures still stop the import;
aliases are never guessed and originals are never renamed.
In-place indexing does not decode every song on the host to count samples.
Compressed duration starts unknown in the database until the native decoder
provides it. Importing a codec does not establish that its playback is qualified.

Photos accept JPEG, PNG, BMP, TIFF and WebP through Pillow. Videos accept MP4,
M4V, MOV, MKV, AVI, WebM, MPEG and WMV containers when FFmpeg can decode them;
existing PVID/PVD files are validated and copied as prepared videos. Subfolders
are included recursively, with folder paths in video titles. Rockbox IPVF files
(including files under `Videos/IPVF`) are strictly validated and indexed in
place through their real FAT 8.3 paths. Linnet plays their RGB565, LZ4 and IMA
ADPCM records directly, so no duplicate or host conversion is created. Video
playback throughput remains subject to the existing qualification limits in
`VIDEO_IMPLEMENTATION.md`.

## Large libraries, caching and interruptions

The default first music import reads metadata, without full-song SHA-256 passes
or audio copying. Each track's metadata is saved immediately in a host SQLite
cache. Restarted imports reuse completed tracks; later updates probe only added
or changed files. Unchanged library snapshots skip preparation. Folder scanning
uses directory-entry metadata instead of repeatedly checking every parent path.
Photo/video preparation requires additional host and device space.
Higher photo detail and long videos can substantially increase prepared size.

Fast music publication checks paths, sizes and modification times again before
replacing the index. It still verifies the database and prepared artwork. This
mode does not claim full audio-content integrity. Choose **Verify entire audio
files (slow)** to read and hash existing audio; newly staged/copied files retain
their existing complete verification. Fast mode cannot detect audio changes that
preserve both size and modification time; **Rebuild unchanged content** refreshes
metadata, while full verification checks content against the newly generated
hashes. Neither mode certifies the absence of source audio corruption.

The host cache and receipts live under `%LOCALAPPDATA%\Linnet\Media`, separated
by disk and volume identity. Source names, sizes and modification times identify
unchanged folders; prepared device files are hash-checked before skipping work.
Publication writes the prepared library to the iPod under `LINNET`; the computer
cache is an additional reusable copy. Completion messages name the folders on
the iPod and any folders that failed, so a photo error does not imply successful
music or video publication was undone.
Use **Rebuild unchanged content** if files were replaced while preserving their
size and modification time. Video conversions also reuse prepared host files.
Successfully published videos are cached individually, so retrying after one
failed clip skips completed siblings. An unreadable video is reported with its
relative path while other subfolders continue processing.

Removing source files does not erase originals or prepared videos automatically.
Music/photo/notes catalogs reflect a newly prepared nonempty source folder;
video publication adds or updates entries. Empty folders retain the previous
prepared library. Automatic pruning and deletion are intentionally not part of
this additive workflow.

**Stop after current step** waits for the current compiler or verified
publication operation to return. Video conversion and file copying can stop midstream;
their partial scratch files are removed before the update finishes. Leave
the window open until it finishes. Successfully completed content remains;
interrupted copy paths and publication backups are recorded in receipts. A
failed publication is not automatically retried. Resolve the reported error
and inspect its receipt before starting another update. The log and Open report
show cleanup results, exact locations of any remaining scratch or incomplete
publication receipts, and the host cache directory. Completed prepared packages
and the music metadata cache are retained to speed up retries. A forced app exit
or disconnected drive can prevent cleanup; remaining host scratch is reported on
the next update, without deleting files that might belong to another running job.

Host checks and firmware builds do not replace an on-device qualification run.

The native Notes and video lists use small paged caches, keeping library size
out of the resident RAM budget. Development screenshots now occupy a separate
77,824-byte diagnostic reservation at `0x01f00000`; the recovery snapshot remains
unchanged at `0x01e00000`. The release image contains no screenshot reservation.
The 4 MiB resident-image limit is unchanged.
