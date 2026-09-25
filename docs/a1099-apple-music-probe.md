# Apple music probe on the A1099

On 2026-09-25, the A1099 with Linnet Link serial `000000F7A765` was updated to
dev OS build `ec80af868c5ef6c9d6eaae0ed3fd40523779d96754c05a561c7af4ff3a5a7585`.
Its native Disk Mode enumerated as a 64 GB FAT32 iPod disk with serial
`0000000000F7A765`. A verified eject returned it to healthy Linnet Link.

The existing Apple `iTunesDB` contained zero tracks. The existing Apple photo
database contained 145 image entries and was left in place. `/Music` contained
2,894 MP3 files. Only 108 of their current short paths fit the 23-character
relative budget established on the A1238. The preserved A1099 Apple firmware
contains a 36-byte music path field and constructs paths using the
`iPod_Control\Music\` prefix. Its Apple playback behavior for a path that
traverses to `/Music` still needs a device check.

A two-track database was installed for that check. Both entries point to the
same MP3 content:

| Apple title | Database location | File |
| --- | --- | --- |
| Levels (Apple control) | `:iPod_Control:Music:F00:LEVELS.mp3` | `/iPod_Control/Music/F00/LEVELS.MP3` |
| Levels (Music folder) | `:iPod_Control:Music:..:..:Music:AVICII~1.mp3` | `/Music/Avicii - Levels.mp3` |

Both database locations resolve to existing files on the mounted volume. The
database SHA-256 is `96ea46efce7a1d4e435299db639543de45c04a8d2b7e5c1b4a378ce8b43d4650`.
The previous empty database was saved on the device as
`iPod_Control/iTunes/iTunesDB.before-a1099-probe-20260925` (SHA-256
`e62d8cd913720a81e61de465e42b522639566317d63d012b3d4c4f22879ddff9`).
The control MP3 matches the `/Music` source by SHA-256
`f0f7d480243aaee6da323d5a886eb8c531df57043a477483fad8cce43678fab3`.

To finish verification, boot Apple OS using the Menu fallback and play both
named entries. Record whether each timer advances and audio is audible. A
listed entry alone does not establish that Apple can open its file. The Linnet
player already opened the `/Music` source after Disk Mode, advanced decoded
and rendered samples, and reported zero errors and underruns.

The full library needs a confirmed Apple path result before changing thousands
of FAT aliases. No existing long names, file contents, or folder layout were
changed for this probe.
