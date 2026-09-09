# Linnet

Native open firmware for classic iPods, initially the iPod Photo A1099
(`photo4g-p98`). Includes music, photos, video, notes, themes, settings and
persistent updates. Development firmware is working; release acceptance and
some media, performance and power checks remain open in [PROJECT_TODO.md](PROJECT_TODO.md).

## Manage media

On Windows, open **Linnet Media.cmd** or run `python linnet media`.
Requires Python 3.11+ with Tkinter, Pillow and FFmpeg/FFprobe; optional Mutagen
speeds up music indexing.

1. Connect the iPod in Disk Mode and select **Find iPod**.
2. Select Music, Notes, Photos or Videos; optionally add files or folders.
3. Select **Prepare & update iPod**, then safely eject and restart Linnet.

Originals are preserved. Music and native IPVF video can be indexed in place;
photos and other videos need prepared copies. See [MEDIA_MANAGER.md](MEDIA_MANAGER.md)
for supported formats, removal, caching and recovery.

Hold **Play/Pause alone for two seconds** to shut down. A short press toggles
music playback or the photo slideshow. Hold blocks input.

## Build and develop

Requires Python 3.11+ and LLVM **18.1.3**: `clang`, `ld.lld`, `llvm-objcopy`,
`llvm-nm`. Windows builds use the `Ubuntu-24.04` WSL distribution.

```powershell
python linnet doctor
python linnet build --batch 7 --target photo4g-p98 --profile dev --device-serial <device-serial> --verify
python linnet build --batch 7 --target photo4g-p98 --profile release --verify
python linnet simulator --output out/simulator
```

On Linux use `python3 linnet`. Build artifacts go under `out/<profile>/<target>/<kind>/`.
Use `python linnet --help` and subcommand `--help` for available operations.
Device Link access requires `pyserial==3.5` and the observed device identity.

Select apps and the default theme in `config/system.toml`. Applications use
constrained TSX compiled ahead of time to native C. Start with the
[SDK guide](sdk/README.md) and `sdk/templates/`.

Firmware installation is device-specific. Native Boot plans require a matching
firmware backup, disk identity and pinned hashes; they are not general installers.
RAM boot does not install a persistent image. See [architecture](ARCHITECTURE.md)
and [Linnet Link](DEVLINK.md) before working on boot or device updates.

## Documentation

- [Architecture and source map](ARCHITECTURE.md)
- [Open work](PROJECT_TODO.md)
- [Media manager](MEDIA_MANAGER.md) and [storage compatibility](STORAGE_COMPATIBILITY.md)
- [Binary contracts](FORMATS.md), [device protocol](DEVLINK.md),
  [music database](services/music/FORMAT.md), [photos](PIMG_FORMAT.md), [video](PVID_FORMAT.md)
- [Local outputs and recovery artifacts](LOCAL_ARTIFACTS.md)

Keep documentation about current behavior, useful instructions and unresolved
work. Update existing sections; remove resolved TODOs. Keep session transcripts,
build-by-build histories, benchmark dumps and generated reports out of project
docs. Read technical references only when the task needs them. Third-party
licenses and provenance stay with their source.
