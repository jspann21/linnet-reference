# Builds and downloads

The **Build downloads** GitHub Actions workflow builds on pushes to `main`, pull
requests, version tags (`v*`), and manual runs. After it succeeds, open the run
under **Actions** and download `linnet-downloads`. These build artifacts expire
after 14 days. Public release assets remain on the repository's Releases page.

## Download contents

| File | Purpose |
| --- | --- |
| `linnet-media-windows.zip` | Windows x64 Media Manager, including `Linnet Media.exe`, Python, Qt, media preparation helpers, and Apple database helpers |
| `linnet-photo4g-p98.zip` | iPod Photo firmware |
| `linnet-video5g-m25.zip` | iPod Video firmware; consult the target qualification guide for supported boards |
| `linnet-ipod4g-q21.zip` | Monochrome fourth-generation iPod firmware |
| `linnet-classic6g-n25.zip` | iPod Classic firmware and initial Boot setup; follow Media Manager's connection and button prompts |
| `linnet-source.zip` | Repository source at the exact commit used for these builds, including build scripts and vendor notices |
| `SHA256SUMS.txt` | SHA-256 checksums of the downloads and these instructions |

Extract the entire Media Manager ZIP, then open `Linnet Media/Linnet Media.exe`.
Keep `_internal` beside the executable. This is a portable app, without an MSI or
setup wizard. End users do not need Python, a compiler, or WSL. FFmpeg and FFprobe
are installed separately and selected in Settings; see the Media Manager guide.
The executable is currently unsigned.

Select the whole firmware ZIP for the detected target inside Media Manager
**without extracting it**. Media Manager selects the required files for your
installation. Each ZIP has a `README.txt`, a checksum manifest, and a `firmware/`
folder containing `linnet-os`, `linnet-boot-standard`, and `linnet-boot-multiboot`
images and reports. Both bootloaders are Linnet software; the multiboot variant
can also start a compatible Rockbox installation already on the device. The
package does not install Rockbox. Packaging runs image verification and the installer's bundle
validation. Release OS/Boot images exclude the developer transport and device
serials. The Classic ZIP additionally includes a precompiled bootstrap template;
Media Manager binds it to the inspected iPod, prompts for DFU, then owns the
remaining Link, NOR and native Disk Mode installation steps. Compilation does
not establish hardware qualification; unsupported storage and flash layouts
stop setup before flashing. Consult the hardware and recovery guides for coverage.

## Publish a version

1. Review the successful build from the commit to release. Check the packaged
   Windows app and the relevant hardware qualification results.
2. Resolve the project's license before public distribution; preserve vendor
   notices and provide corresponding source alongside binaries.
3. Push a version tag such as `v0.1.0` on that commit. This starts a fresh build
   and creates a **draft GitHub Release** containing all downloads and checksums.
4. Review the draft's downloads and edit its notes to describe that version and
   its hardware limits, then publish it from GitHub Releases.

All packages must build successfully before the draft is created. Rerunning a
tag build can update its draft assets; the workflow refuses to replace a
published release. A normal branch push or manual run only produces Actions
artifacts. No personal access token is needed: only the tag release job has
repository write permission, through GitHub's built-in token.

## Build locally on Windows

Use Python 3.14 x64, then run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools/studio/requirements-build.txt
.\.venv\Scripts\python.exe linnet setup
.\.venv\Scripts\python.exe linnet doctor
.\.venv\Scripts\python.exe linnet release bundle --target photo4g-p98 --output out/releases/linnet-photo4g-p98.zip
.\.venv\Scripts\python.exe linnet release media --output out/releases/linnet-media-windows.zip
```

Repeat the bundle command for the other target IDs in the table. Output ZIPs
must not already exist; choose a fresh output directory when rebuilding. Local
builds use the current working files, while GitHub uses the checked-out commit.
Keep generated artifacts in `out/`, which is excluded from Git.
