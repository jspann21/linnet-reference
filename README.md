# Linnet

Native firmware for classic iPods, developed first for the iPod Photo A1099
(`photo4g-p98`). Includes music, photos, video, notes, themes, settings and
persistent updates. See the [roadmap](docs/roadmap.md) for planned improvements.

## Device support

| Target ID | Model | Status |
| --- | --- | --- |
| `photo4g-p98` | iPod Photo A1099, 220 × 176 color | Primary development target. |
| `ipod4g-q21` | iPod 4G MP102, 160 × 128 monochrome | Photos, video and theme selection disabled. |

Installer profiles exist for both targets.

**Want to support another iPod?** Follow the [model porting guide](targets/README.md)
for the required files, manifest fields, hardware assumptions and validation.

## Manage media

On Windows, open **Linnet Media.cmd** or run `python linnet media`.
Requires Python 3.11+ with Tkinter, Pillow and FFmpeg/FFprobe; optional Mutagen
speeds up music indexing.

1. Connect the iPod in Disk Mode and select **Find iPod**.
2. Select Music, Notes, Photos or Videos; optionally add files or folders.
3. Select **Prepare & update iPod**. If Linnet entered Apple Disk Mode for this
   session, leave it with `python linnet device eject --reboot --disk-number N --expected-serial STORAGE_SERIAL --allow-uac`;
   do not use a storage-only eject.

Originals are preserved. Music and native IPVF video can be indexed in place;
photos and other videos need prepared copies. See the [Media Manager guide](docs/media-manager.md)
for supported formats, removal, caching and recovery.

Hold **Play/Pause alone for two seconds** to shut down. A short press toggles
music playback or the photo slideshow. Hold blocks input.

## Build and develop

Run commands from the repository root after cloning or extracting the source.
Requires Python 3.11+ and LLVM **18.1.3**: `clang`, `ld.lld`, `llvm-objcopy`,
`llvm-nm`. Windows builds use the `Ubuntu-24.04` WSL distribution.
Install Python and the pinned LLVM tools inside that distribution; the Windows
CLI forwards build, doctor and simulator commands to WSL. LLVM executable names
must be available on `PATH` as listed in [the toolchain configuration](config/toolchain.toml).
The doctor command rejects other LLVM versions.

For host media/content tools, install Python dependencies in your environment:

```console
python -m pip install Pillow pyserial==3.5
python -m pip install Mutagen
```

Mutagen is optional. Install Tkinter through your Python/OS distribution and put
FFmpeg and FFprobe on `PATH` for media preparation. Install content dependencies
inside WSL too when running the compiler or simulator there.

```powershell
python linnet doctor
python linnet build --target photo4g-p98 --profile dev --device-serial YOUR_SERIAL --verify
python linnet build --target photo4g-p98 --profile release --verify
python linnet simulator --output out/simulator
```

`YOUR_SERIAL` is the serial observed from the physical device; development and
trace builds require it. Release builds do not. Every build contains the current
integrated firmware for its selected target, profile and image kind.

On Linux use `python3 linnet`. Build artifacts go under `out/<profile>/<target>/<kind>/`.
Use `python linnet --help` and subcommand `--help` for available operations.
Device Link access requires `pyserial==3.5` and the observed device identity.

On Windows, **Linnet Media.cmd** includes a target-aware, non-wiping installer.
It recognizes supported iPod hardware and existing Linnet, Rockbox and common
iPodLinux installations, preserves media and the original boot path, and keeps
verified recovery receipts. See [Linnet Media](docs/media-manager.md) for the UI and
CLI workflows.

Select apps and the default theme in `config/system.toml`. Applications use
constrained TSX compiled ahead of time to native C. Start with the
[SDK guide](sdk/README.md) and `sdk/templates/`.

Firmware installation remains device-specific. The Media installer creates and
applies the matching backup-bound plan for the detected target; low-level native
Boot commands still require a matching firmware backup, disk identity and pinned hashes.
RAM boot does not install a persistent image. See [architecture](docs/architecture.md)
and [Linnet Link](docs/device-link.md) before working on boot or device updates.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development checks, useful bug reports
and what to include in a contribution. Hardware ports start with the
[model porting guide](targets/README.md); apps and themes start with the [SDK](sdk/README.md).

## Documentation

- [Adding an iPod model](targets/README.md) and [contributing](CONTRIBUTING.md)
- [Architecture and source map](docs/architecture.md)
- [Open work](docs/roadmap.md)
- [Media manager](docs/media-manager.md) and [storage compatibility](docs/storage.md)
- [Binary contracts](docs/formats.md), [device protocol](docs/device-link.md),
  [music database](docs/music-format.md), [photos](docs/photo-format.md), [video](docs/video-format.md)
- [Local outputs and recovery artifacts](docs/local-artifacts.md)

Keep documentation about current behavior, useful instructions and unresolved
work. Update existing sections; remove resolved TODOs. Keep session transcripts,
build-by-build histories, benchmark dumps and generated reports out of project
docs. Read technical references only when the task needs them. Third-party
licenses and provenance stay with their source.
