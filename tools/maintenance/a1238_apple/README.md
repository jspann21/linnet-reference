# A1238 Apple music database maintenance

These scripts support the A1238 with USB serial `000A2700155D9C10` and FAT32
volume serial `5FC88A5C`, mounted as `F:`. They keep MP3s under `/Music` with
their existing long names and folder structure. Apple's database points through
`iPod_Control/Music/../../Music` using short FAT aliases and a lowercase
`.mp3` suffix. The relative path below `/Music` must fit in 23 characters.
The planner checks the path budget, FAT geometry and volume serial, and alias
uniqueness. The manifest builder checks cached metadata. The journal writer
also checks the Linnet USB identity before a write.

Run from the repository root with the device in Linnet disk mode. The three
Python scripts below prepare files under ignored `out/apple-link-probe` without
writing the device:

```powershell
python tools/maintenance/a1238_apple/fat_alias_plan.py
python tools/maintenance/a1238_apple/compact_alias_plan.py
$cache = Join-Path $env:LOCALAPPDATA 'Linnet\Media\32f93cab99ca10ad98a6d622\music-metadata.sqlite3'
python tools/maintenance/a1238_apple/generate_library_manifest.py --cache $cache
```

The planner reparses the proposed VFAT directory tree and confirms that every
original long path, file cluster, and size remains intact. Inspect the plan and
keep its `alias-before.bin`, `alias-after.bin`, and `alias-plan.json` together.
If `changes` is zero, the existing short aliases already fit and no raw write
is needed.
The journal writer is `tools/maintenance/a1238_apple_alias_journal.py`; it
requires the exact plan SHA-256 and archives all three files under
`%LOCALAPPDATA%/Linnet/AppleAlias/` before a write. `--mode apply` writes the
planned aliases; `--mode restore` returns a fully applied plan to its before
image; `--mode recover` returns a mixed before/after state to the before image.
Do not modify `/Music` between planning and applying or restoring a journal.

Build the Apple database with libgpod in WSL after the manifest is generated:

```bash
gcc tools/maintenance/a1238_apple/full_library.c $(pkg-config --cflags --libs libgpod-1.0) -o out/apple-link-probe/full-library
./out/apple-link-probe/full-library out/apple-link-probe/libgpod-library out/apple-link-probe/full-library-manifest.tsv
```

After applying aliases, `verify_live_aliases.py` checks each original path and
each Apple short path against the manifest. Publish Linnet's rebuilt music
index and install the libgpod `iTunesDB` with a verified copy and retained
backup, then safely eject before testing Apple playback. The exact procedure
and hardware results from the first run are in `docs/apple-stock-music.md`.

New files should first be indexed by Linnet's Media Manager so its metadata
cache includes them. These scripts support the mounted MP3 library within the
stock Apple path limit; a deeper path that cannot fit requires a firmware
resolver.
