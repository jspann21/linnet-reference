# Apple Music database on the A1238

The A1238 can display tracks entered into `iPod_Control/iTunes/iTunesDB` by
libgpod. Playback depends on the path encoding, not just a valid database.
These observations were verified on device `000A2700155D9C10` on 2026-09-24.

| Database location | Actual file | Result |
| --- | --- | --- |
| `:iPod_Control:Music:F00:libgpod144575.mp3` | `/iPod_Control/Music/F00/libgpod144575.mp3` | Plays normally |
| `:Music:311:311:01 Down.mp3` | `/Music/311/311/01 Down.mp3` | Listed, but timer does not advance |
| `:iPod_Control:Music:311:311:01 Down.mp3` | `/iPod_Control/Music/311/311/01 Down.mp3` | Plays normally |
| `:iPod_Control:Music:..:..:Music:311:311:01 Down.mp3` | `/Music/311/311/01 Down.mp3` | Plays normally |
| `:iPod_Control:Music:..:..:Music:311:311:01DOWN~1.MP3` | Same file via its actual FAT short alias | Listed, but does not play |
| `:iPod_Control:Music:..:..:Music:311:311:01DOWN~1.mp3` | Same file via its actual FAT short alias | Plays normally |

The last result proves that the stock Apple software can play an existing file
under `/Music` with a database entry and without copying it. The comparison
file under `/iPod_Control/Music/311/311` was renamed before that test, so it
could not account for playback.

Static analysis of the device's decrypted Apple OS image (SHA-256
`9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a`)
shows the limiting behavior. At runtime `0x080c2294`, the parser discards the
first 20 bytes of the location and retains at most 35 bytes. At `0x08048990`,
normal MP3 playback prepends `iPod_Control\Music\`. Parent-directory components
in the retained path are honored by the filesystem. The full database location
must therefore fit within 55 bytes, including the 20-byte prefix.

The root `/Music` traversal consumes 12 of the 35 retained bytes
(`..:..:Music:`), leaving 23 for the path below `/Music`. An inventory using
Windows' actual FAT short aliases found that only **12 of 2,676** existing
MP3s fit. The music occupies **15,065,620,907 bytes**; the disk had about
**14.37 GB free**, so an identical second copy of the entire library would
not fit. This inventory is specific to the current A1238 volume.

The existing artist, album, and file names under `/Music` were preserved.
Changing the Apple database alone could not address the other 2,664 songs.
Static execution of Apple's MP3 type routine found that it rejects an uppercase
`.MP3` suffix, even though FAT lookup is case-insensitive. Hardware playback
confirmed that `01DOWN~1.mp3` opens the same file that `01DOWN~1.MP3` cannot.

To fit the full library, compact VFAT short aliases were assigned to artist and
album directories, with additional file aliases where required. Long names,
clusters, sizes, and file contents were left in place. A full read-only reparse
of the proposed FAT directory sectors confirmed all 2,676 original paths and
their data links. A one-file rehearsal changed and restored an alias under a
volume lock; Windows resolved both the original long name and the new alias,
and the file contents were unchanged. The full change then updated 2,023 short
entries and their associated long-name checksums across 829 directory sectors.
The longest resulting relative short path is 22 characters, within the
23-character limit. The raw write was journaled, flushed, and read back under
a volume lock. The plan SHA-256 is
`08b29379e21ffbca6201340f03d23bce9f986f3febac6b4ef6b08b273f9f57a7`;
the before/after sector journal is archived under
`%LOCALAPPDATA%/Linnet/AppleAlias/08b29379e21ffbca`. After remount, Windows
opened every original long path and every planned short path, with expected
sizes totaling 15,065,620,907 bytes.

The exact writer used for the one-file rehearsal and full change is preserved
at `tools/maintenance/a1238_apple_alias_journal.py`. Its `restore` mode requires
all 829 current sectors to match the archived after image; its `recover` mode
accepts a mix of archived before and after sectors and returns them to the
before image. Both modes verify the connected device identity, FAT boot sector,
and journal hashes, then lock and dismount the volume around writes. Rebuilding
both databases is necessary after restoring the old aliases.

The stock Apple database was generated with libgpod for all 2,676 MP3s and
installed at `iPod_Control/iTunes/iTunesDB` (SHA-256
`546ecacfe9bdbf5e9cf758107fffcc3eb69ae4c98de82ea8f0d201ddaf7ff375`).
The previous database was retained as
`iPod_Control/iTunes/iTunesDB.before-full-20260924-143319`. Linnet's music
database was rebuilt from the same files and published at `.LINNET/LIBRARY.PDB`
(SHA-256 `e9c7a4cbd0df7bcf1867393c9ddfa17fd7f0c78abed3c0840d3c37631d65e360`).
Both databases contain 2,676 tracks. The disk was safely ejected; full-library
Apple playback is awaiting a hardware spot check.

Future files and folders need their Apple entries and short-path budget checked
again. An added folder depth that cannot fit within 23 characters would require
a firmware resolver. FAT cluster cross-links are not a safe substitute for file
links.

For new probes, preserve a known working libgpod control track, save the
current database before replacing it, verify the candidate database's hash,
and safely eject the disk before entering Apple OS. A track appearing in the
Apple UI is not evidence that it can be opened: confirm timer advance and
audible playback.
