# A1099 Apple library status (2026-09-25)

Device `0000000000F7A765` runs Linnet dev build
`ec80af868c5ef6c9d6eaae0ed3fd40523779d96754c05a561c7af4ff3a5a7585`.
Native Disk Mode mounted as a 64 GB FAT32 disk and returned to Linnet after a
verified eject.

All 2,894 MP3s remain under `/Music` with their original long names. A
journaled change compacted 2,049 FAT aliases across 1,026 sectors so every
Apple path fits the firmware's music path field. The plan SHA-256 is
`768f96d89014522c17fbd95a1e826334ed8296c392dcb54f72cfbd55042c3352`;
its before and after sectors are archived at
`%LOCALAPPDATA%/Linnet/AppleAlias/768f96d89014522c`. Use
`tools/maintenance/a1099_apple_alias_journal.py` with that exact plan and
archive for recovery. After remount, every original MP3 path and Apple alias
opened with its expected size, totaling 17,209,001,550 bytes.

Linnet's rebuilt library has 2,894 tracks and 811 covers. Its previous
database is retained at `.LINNET/LIBBAK/D5B29FFD.PDB`. The Apple `iTunesDB`
has 2,895 tracks: the same 2,894 `/Music` files plus one standard-path control,
“Levels (Apple control)”. Its SHA-256 is
`6b69c24032864013ec0ba74fe95b250a60d4274a2884a15d51256cd5723e4493`.
The preceding two-song probe and original empty Apple database are retained at
`iPod_Control/iTunes/iTunesDB.before-full-a1099-20260925` and
`iPod_Control/iTunes/iTunesDB.before-a1099-probe-20260925`.

After the final eject, Linnet Link reported the new library healthy. It played
“Broken” by 12 Stones and “A Direct Hit” by Joris de Man through the compact
aliases with advancing audio counters and zero errors or underruns. The
existing Apple photo database still contains 145 image entries.

Apple OS playback needs a physical check: boot Apple with the Menu fallback,
then play “Levels (Apple control)”, “Levels” by Avicii from `/Music`, “Broken”,
and “A Direct Hit”. Confirm an advancing timer and audible audio for each.
