# Linnet Project Structure and Identifier Specification

## 1. Purpose and precedence

This document defines the public name, product structure, repository naming,
hardware target identifiers, package identifiers, artifact names, command names,
and source-code namespaces for the operating system described in
`A1099OS_GREENFIELD_IMPLEMENTATION_PLAN.md`.

The implementation plan remains authoritative for architecture, scope, batches,
performance goals, testing, and release gates. This document is authoritative
for naming and identity. Where the implementation plan uses provisional names
such as `A1099OS`, `a1099`, or `DevLink`, interpret them as follows:

| Provisional term | Canonical Linnet term |
| --- | --- |
| `A1099OS` | **Linnet OS** |
| `a1099os/` repository root | `linnet/` |
| `a1099` CLI | `linnet` |
| `DevLink` | **Linnet Link** |
| developer Stage 0 loader | **Linnet Boot** |
| desktop/device simulator | **Linnet Simulator** |
| host content/build environment | **Linnet Studio** |

Do not preserve provisional names in new source code, user interfaces, USB
strings, package identifiers, generated artifacts, or documentation. They may
appear only in the original plan filename and in explicit migration notes.

## 2. Canonical project identity

### 2.1 Umbrella name

The project is **Linnet**.

The preferred public description is:

> **Linnet is a fast, native, customizable operating system and compiled
> application platform for classic iPods.**

The compact tagline is:

> **Native open firmware for classic iPods.**

Use `Linnet` when referring to the overall ecosystem. Use `Linnet OS` only when
referring specifically to the firmware that runs on a device.

### 2.2 Product family

```text
Linnet
├── Linnet OS          device operating system and system applications
├── Linnet SDK         AOT application, theme, and target development tools
├── Linnet Studio      host-side build, media preparation, sync, and packaging
├── Linnet Link        development USB protocol and host transport library
├── Linnet Boot        development/recovery loader
└── Linnet Simulator   desktop execution, visual inspection, and scripted input
```

These names describe responsibilities, not mandatory separate repositories or
executables. The initial implementation should remain one monorepo and one
primary command-line executable.

### 2.3 User-facing device names

Use the form:

```text
Linnet for <device family>
```

Examples:

```text
Linnet for iPod Photo
Linnet for iPod mini
Linnet for iPod Video
Linnet for iPod nano
Linnet for iPod classic
```

On constrained screens, display simply `Linnet`. Do not use the hardware model
number as the product name.

## 3. Naming conventions

### 3.1 Human-readable names

| Kind | Convention | Example |
| --- | --- | --- |
| Project/product | Title Case | `Linnet OS` |
| Device family | Apple-style descriptive name | `iPod Photo` |
| Screen/application title | Title Case | `Now Playing` |
| Protocol/product component | Title Case | `Linnet Link` |

### 3.2 Machine-readable names

| Kind | Convention | Example |
| --- | --- | --- |
| CLI executable | lowercase | `linnet` |
| CLI commands and flags | kebab-case | `device cycle`, `--build-id` |
| Repository/package names | kebab-case | `linnet-link` |
| Target IDs | lowercase compact tokens with hyphens | `photo4g-p98` |
| C functions | lowercase snake_case with `ln_` prefix | `ln_audio_start()` |
| C macros | uppercase with `LINNET_` prefix | `LINNET_PROFILE_DEV` |
| Rust crates | kebab-case | `linnet-formats` |
| Rust modules | snake_case | `media_index` |
| TypeScript packages | `@linnet/<name>` | `@linnet/ui` |
| TypeScript symbols | normal TS conventions | `VirtualList` |
| TOML keys | snake_case | `audio_buffer_ms` |
| Environment variables | uppercase with `LINNET_` prefix | `LINNET_TARGET` |
| App/theme/service IDs | dot-separated lowercase identifiers | `linnet.system.music` |

Avoid new abbreviations unless they represent a stable hardware or file-format
term. Prefer `linnet device cycle` over multiple unrelated utility names.

## 4. Repository and workspace structure

The canonical repository name is `linnet`. The initial implementation should be
a monorepo:

```text
linnet/
  README.md
  ARCHITECTURE.md
  LINNET_PROJECT_STRUCTURE_AND_IDENTIFIERS.md
  A1099OS_GREENFIELD_IMPLEMENTATION_PLAN.md
  DEVLINK.md
  FORMATS.md

  boot/                         Linnet Boot, vectors, image selection, rollback
  hal/                          hardware access; no product policy
  kernel/                       event loop, deadlines, queues, arenas, watchdog

  targets/
    photo4g-p98/
      target.toml               canonical target facts and capabilities
      memory.ld                 target memory map
      startup/                  target startup and low-level assembly
      hal/                      target implementations of HAL contracts
      release.toml              target release budgets and limits

  services/
    storage/
    state/
    audio/
    library/
    image/
    video/
    power/
    update/

  ui/
    compiler-target/            AOT pixel backend for Linnet targets
    runtime/                    tiny native component ABI
    system/                     shell and first-party system application source

  apps/                         customizable AOT application source
  themes/                       theme source and assets
  formats/                      shared host/device binary definitions

  sdk/
    api/                        stable application-facing APIs
    compiler/                   AOT compiler integration and checks
    templates/                  minimal app and theme starters

  tools/
    cli/                        the `linnet` executable
    studio/                     host build/sync orchestration
    link/                       Linnet Link transport and protocol implementation
    simulator/                  Linnet Simulator
    content/                    PODB, PIMG, PVID, font, icon, and theme compilers
    inspect/                    image, map, memory, and release-exclusion checks

  scenarios/                    one integrated device campaign per major batch
  config/                       system profiles and global memory budgets
  out/                          generated images, packages, receipts, and reports
```

Do not create separate repositories for the SDK, Link, Studio, Boot, or
Simulator until a real release or ownership boundary requires it. A product
name is not a reason to split source control.

Do not create a generic `common/`, `shared/`, or `utils/` dumping ground. Shared
code belongs to the narrowest owner that defines its contract.

## 5. Hardware identity model

Linnet distinguishes a target, board, SoC, model alias, and hardware option.
They are not interchangeable.

### 5.1 Target ID

A **target ID** identifies one firmware ABI, memory map, low-level hardware
contract, and build output. It is the value passed to `linnet build --target`.

Canonical grammar:

```text
<device-family><generation>-<board-id>
```

The initial target is:

```text
photo4g-p98
```

Meaning:

| Field | Value |
| --- | --- |
| Device family | iPod Photo / iPod with color display |
| Generation token | `4g` |
| Board hardware ID | `p98` |
| Initial qualified retail model alias | `a1099` |
| SoC | `pp5020` |
| Display class | `220x176-rgb565` |

The target ID appears in build manifests, artifact names, device receipts,
package admission records, and crash reports.

### 5.2 Accepted aliases

The CLI may accept friendly aliases, but it must normalize them immediately to
the canonical target ID.

Initial aliases:

```text
photo4g          -> photo4g-p98
ipod-photo       -> photo4g-p98
a1099            -> photo4g-p98
photo4g-a1099    -> photo4g-p98
p98              -> photo4g-p98
```

Generated files and machine-readable output always use `photo4g-p98`, never an
alias.

### 5.3 Future target IDs

Reserve the following naming pattern without claiming support before hardware
qualification:

```text
mono4g-<board>
mini1g-<board>
mini2g-<board>
nano1g-<board>
video5g-<board>
video55g-<board>
classic6g-<board>
classic7g-<board>
```

Create a new target only when firmware compatibility actually differs. Storage
capacity, case color, battery capacity, an iFlash adapter, or a different media
card does not create a new target unless it changes the binary hardware
contract.

### 5.4 Model and option identifiers

Use these independent fields in device information and receipts:

```toml
target_id = "photo4g-p98"
board_id = "p98"
model_alias = "a1099"
soc_id = "pp5020"
storage_profile = "ata-iflash"
display_profile = "lcd220x176-rgb565swapped"
```

Recommended option tokens:

```text
storage_profile:
  ata-hdd
  ata-iflash
  ata-cf

power_profile:
  stock-battery
  replacement-battery
  unknown-battery
```

Options are diagnostic facts and policy inputs. They must not silently select a
different application ABI.

## 6. Version and ABI identifiers

Track these versions independently:

| Identifier | Purpose |
| --- | --- |
| OS version | Public Linnet OS release version |
| Boot ABI | Contract between Linnet Boot and the main OS image |
| Kernel ABI | Internal native service table version |
| App ABI | Contract consumed by AOT applications |
| Theme ABI | Theme token and asset contract |
| Link protocol version | Linnet Link wire compatibility |
| Format versions | PODB, PIMG, PVID, app, theme, and image metadata |

Use semantic versions for public releases:

```text
0.1.0
0.2.0-beta.1
1.0.0
```

Use unsigned integer ABI versions in binary headers:

```text
boot_abi = 1
kernel_abi = 1
app_abi = 1
theme_abi = 1
link_major = 1
link_minor = 0
```

Rules:

- Increment a major ABI when an existing consumer cannot operate correctly.
- Add fields append-only when a format permits forward-compatible extension.
- Reject unknown major versions.
- Accept a newer minor version only when the header explicitly declares a
  compatible minimum.
- Do not use the public OS version as an ABI version.

## 7. Build profiles, channels, and slots

### 7.1 Build profiles

The only build profile identifiers are:

```text
release
dev
trace
```

Exactly one must be selected at build time.

Canonical compile definitions:

```c
LINNET_PROFILE_RELEASE
LINNET_PROFILE_DEV
LINNET_PROFILE_TRACE
```

The release verifier must reject any image containing symbols, strings,
descriptors, tables, or buffers exclusive to `dev` or `trace`.

### 7.2 Distribution channels

Channels are metadata for distribution and update policy; they are not compiler
profiles:

```text
stable
beta
nightly
local
```

A `release` profile may be distributed through `stable`, `beta`, or `nightly`.
A `dev` or `trace` image is always `local` unless a deliberate engineering
campaign says otherwise.

### 7.3 Boot and update slots

Physical slot IDs:

```text
a
b
```

Logical roles:

```text
active
candidate
fallback
```

Roles change during update and rollback; physical slot IDs do not. Persistent
metadata must store both rather than naming a file `active.img` and renaming it
during every update.

`Linnet Boot` is not an OS slot. It is the stable loader and recovery anchor.

## 8. Application, service, and theme identifiers

### 8.1 Identifier grammar

Use dot-separated lowercase IDs:

```text
<namespace>.<category>.<name>
```

Each segment must match:

```text
[a-z][a-z0-9-]*
```

IDs are permanent once published. Display names may change without changing the
ID.

### 8.2 First-party system application IDs

```text
linnet.system.shell
linnet.system.home
linnet.system.music
linnet.system.now-playing
linnet.system.photos
linnet.system.videos
linnet.system.files
linnet.system.settings
linnet.system.update
linnet.system.recovery
linnet.system.about
```

### 8.3 Native service IDs

```text
linnet.service.audio
linnet.service.storage
linnet.service.library
linnet.service.image
linnet.service.video
linnet.service.power
linnet.service.state
linnet.service.update
linnet.service.input
linnet.service.display
```

These IDs identify capability providers and diagnostics. They do not imply
process isolation or independently loadable daemons.

### 8.4 Theme IDs

```text
linnet.theme.default
linnet.theme.high-contrast
linnet.theme.<name>
```

Third-party/local examples:

```text
local.alex.theme-midnight
local.alex.clock
org-example.reader
```

Before a public package registry exists, `local.<developer>.<name>` is the
preferred namespace for private packages. A future publisher registry can
allocate stable publisher prefixes without changing first-party IDs.

## 9. Package and format names

The canonical media format names remain:

| Format | Meaning | Recommended extension |
| --- | --- | --- |
| PODB | Linnet packed music/library database | `.podb` |
| PIMG | Linnet prepared image package | `.pimg` |
| PVID | Linnet prepared video package | `.pvid` |

Linnet package names:

| Package | Recommended extension |
| --- | --- |
| AOT application package | `.lapp` |
| Theme package | `.ltheme` |
| Optional multi-item distribution bundle | `.lbundle` |
| Native OS payload before iPod wrapping | `.los` |
| Bootable iPod image | `.ipod` |

Extensions are names only; magic bytes, binary layouts, signing, alignment,
and compatibility rules belong in `FORMATS.md`.

Package filenames are conveniences and may be changed by the user. Package IDs
inside manifests are authoritative.

Example manifest identity:

```toml
id = "linnet.system.music"
display_name = "Music"
version = "0.1.0"
app_abi = 1
targets = ["photo4g-p98"]
entry = "music_main"
```

## 10. Artifact naming

### 10.1 Build ID

Every build receives a content-derived build ID. The full build ID is a digest
of the normalized source revision, target description, compiler/toolchain
identity, feature set, and relevant generated inputs.

Use the first 12 lowercase hexadecimal characters in filenames and UI/log
summaries. Store the complete digest in image metadata and run receipts.

Example:

```text
build_id = 6a12f0e4c93b
```

A dirty source tree must be reflected in the normalized build identity. Do not
reuse a build ID after changing any linked code or packaged system resource.

### 10.2 OS and loader artifacts

Canonical filenames:

```text
linnet-os-<version>-<target>-<profile>-<build-id>.ipod
linnet-os-<version>-<target>-<profile>-<build-id>.los
linnet-boot-<version>-<target>-<profile>-<build-id>.ipod
```

Examples:

```text
linnet-os-0.1.0-photo4g-p98-dev-6a12f0e4c93b.ipod
linnet-os-0.1.0-photo4g-p98-release-9d31d44ae102.ipod
linnet-boot-0.1.0-photo4g-p98-dev-210fc2b7a84e.ipod
```

Stable convenience copies may exist inside `out/<profile>/<target>/`:

```text
linnet.ipod
linnet-boot.ipod
```

They must never replace uniquely identified artifacts in receipts or release
manifests.

### 10.3 Application and theme artifacts

```text
<package-id>-<version>-<target>.lapp
<theme-id>-<version>.ltheme
```

For filesystem-friendly export, the packaging tool may generate a short on-disk
name. The manifest ID remains authoritative.

### 10.4 Run IDs and receipts

A device campaign run ID uses UTC time, target, build ID, and a monotonic local
sequence:

```text
<utc>-<target>-<build-id>-<sequence>
```

Example:

```text
20260906T021455Z-photo4g-p98-6a12f0e4c93b-0042
```

Receipt path:

```text
out/runs/<run-id>/receipt.json
```

Every screenshot, log, crash record, performance sample, and test result from
that campaign belongs under the same run directory.

## 11. Command-line structure

The primary executable is `linnet`.

Canonical command tree:

```text
linnet doctor
linnet build
linnet clean
linnet inspect
linnet package
linnet content
linnet sim
linnet device
linnet report
linnet release
```

Representative commands:

```sh
linnet build --target photo4g-p98 --profile dev
linnet build --target photo4g-p98 --profile release --verify
linnet sim --target photo4g-p98 --app linnet.system.music

linnet content library --source /music --output out/content/library.podb
linnet content photos --source /photos --output out/content/photos.pimg
linnet content video input.mkv --output out/content/movie.pvid

linnet device info
linnet device cycle --image out/dev/photo4g-p98/linnet.ipod \
  --scenario scenarios/b03-ui.json
linnet device boot --mode ram --image <image>
linnet device reboot --mode os
linnet device reboot --mode boot
linnet device reboot --mode disk
linnet device collect --run <run-id>
linnet device install --slot b --image <release-image>

linnet report <run-id>
linnet release verify <release-image>
```

Do not introduce separate top-level commands such as `a1099-tool`,
`ipod-runner`, `devlink-cli`, or `media-builder`. They should become `linnet`
subcommands or internal libraries.

## 12. Linnet Link identity

### 12.1 Product and protocol name

The development protocol is **Linnet Link**. In source and machine-readable
fields, use `link` or `linnet_link`, not `devlink`.

Suggested protocol identifiers:

```text
protocol_name = "linnet-link"
wire_magic = "LNK1"
link_major = 1
link_minor = 0
```

Numeric command IDs, frame layouts, retry semantics, and transactional rules
belong in `DEVLINK.md`.

### 12.2 USB product strings

Recommended strings:

| Image | USB product string |
| --- | --- |
| Linnet Boot development image | `Linnet Boot - Photo 4G` |
| Linnet OS development image | `Linnet OS Dev - Photo 4G` |
| Linnet OS trace image | `Linnet OS Trace - Photo 4G` |
| Release sync/storage mode | `Linnet OS - Photo 4G` |

Use ASCII-safe strings in descriptors. The visible user interface may use a
proper typographic dash.

The USB serial identity should be stable for a physical device and derived from
hardware identity, not from a mutable device name, OS slot, or current build.
The build ID and target ID are returned by the protocol status command.

### 12.3 Source names

```text
tools/link/
linnet_link_*()              C functions
linnet-link                  Rust crate when needed
@linnet/link                 TypeScript host package
LINNET_LINK_*                macros/constants
```

The complete Linnet Link implementation must be absent from `release` unless a
specific release USB function requires a separately implemented, narrowly scoped
protocol. Development commands must never be reachable through the release
storage/sync interface.

## 13. Source namespaces and ABI symbols

### 13.1 C and assembly

All externally visible Linnet C symbols use the `ln_` prefix:

```c
ln_kernel_init()
ln_audio_open()
ln_audio_start()
ln_storage_submit()
ln_image_render_region()
ln_video_present()
ln_power_request_sleep()
```

Private file-local functions require no project prefix and should be `static`.
Assembly exports use the same `ln_` prefix.

Subsystem constants use full names:

```c
LINNET_AUDIO_PCM_RING_FRAMES
LINNET_STORAGE_MAX_REQUESTS
LINNET_TARGET_PHOTO4G_P98
```

Do not use ambiguous global prefixes such as `sys_`, `os_`, `app_`, or `pjs_`.

### 13.2 Rust

Crates:

```text
linnet-core
linnet-formats
linnet-library
linnet-package
linnet-update
```

The target-specific crate, when one is needed:

```text
linnet-target-photo4g-p98
```

Rust code that crosses the C boundary exports explicit `ln_*` C ABI symbols.
Do not expose Rust layouts directly across the boundary.

### 13.3 TypeScript

Recommended package namespace:

```text
@linnet/compiler
@linnet/ui
@linnet/host
@linnet/sdk
@linnet/link
@linnet/simulator
@linnet/formats
```

Recommended application imports:

```ts
import { mount, ref, computed } from "@linnet/ui";
import { Audio, Library, Photos, Video } from "@linnet/host";
```

The AOT compiler may use another implementation internally, but generated app
source and public examples should expose Linnet-owned APIs. Public app code must
not import target MMIO, the kernel, USB implementation details, or private
compiler internals.

## 14. Configuration identifiers

The primary system configuration remains `system.toml`.

Recommended root keys:

```toml
[system]
name = "Linnet"
target = "photo4g-p98"
profile = "release"

[ui]
theme = "linnet.theme.default"

[audio]
buffer_ms = 750

[power]
idle_sleep_seconds = 30

[features]
photos = true
video = true
files = true
```

Target facts belong in `targets/<target-id>/target.toml`, not in user-editable
`system.toml`.

Example target identity:

```toml
id = "photo4g-p98"
display_name = "iPod Photo 4G"
board_id = "p98"
soc_id = "pp5020"
boot_abi = 1
app_abi = 1

[display]
width = 220
height = 176
pixel_format = "rgb565-swapped"

[input]
kind = "click-wheel"
relative_axis = true
```

## 15. On-device paths

Use one top-level data directory:

```text
/LINNET/
```

Recommended layout:

```text
/LINNET/
  SYSTEM/                       OS-owned persistent data
  APPS/                         installed `.lapp` packages
  THEMES/                       installed `.ltheme` packages
  LIBRARY/                      PODB and related generated indexes
  PHOTOS/                       PIMG packages
  VIDEOS/                       PVID packages
  STATE/                        transactional user state and journals
  UPDATE/                       validated candidate update staging
  RECOVERY/                     minimal recovery metadata/resources
```

Release firmware must tolerate missing optional directories and recreate only
OS-owned structure. It must never silently delete unknown user files.

Development-only transient data should not share the release state namespace.
When disk persistence is required in a development build, use:

```text
/LINNET/DEV/
```

This directory must not be required for release boot.

## 16. Public communication rules

Use these descriptions consistently:

- **Correct:** `Linnet is a new operating system for classic iPods.`
- **Correct:** `Linnet for iPod Photo currently targets photo4g-p98.`
- **Correct:** `Applications are compiled ahead of time into native code.`
- **Correct:** `Linnet Link automates upload, boot, diagnostics, and test cycles.`
- **Avoid:** `A1099OS`, except when naming the legacy plan file.
- **Avoid:** presenting `A1099` as the complete scope of Linnet.
- **Avoid:** calling Linnet a Rockbox distribution, skin, plugin, or compatibility
  layer.
- **Avoid:** claiming support for a target before its hardware qualification gate
  passes.

Use Apple product names descriptively in compatibility statements. The primary
brand remains Linnet.

## 17. Codex naming rules

Codex must apply these rules from the first commit:

1. Initialize the repository as `linnet/`.
2. Name the primary CLI executable `linnet`.
3. Use `photo4g-p98` as the canonical first target and accept `a1099` only as a
   CLI alias.
4. Use Linnet product names in user-visible text and USB descriptors.
5. Rename the development protocol concept from `DevLink` to `Linnet Link` in
   new implementation files. The existing plan's `DEVLINK.md` filename may be
   retained to avoid unnecessary churn, but its title must be `Linnet Link
   Protocol`.
6. Use `ln_`, `LINNET_`, `linnet-*`, and `@linnet/*` namespaces as defined
   above.
7. Emit unique artifacts containing target, profile, and build ID.
8. Put all device campaign output under one run ID and include that ID in every
   machine-readable result.
9. Do not add compatibility aliases inside firmware unless required for an
   existing installed image. Host CLI aliases are sufficient.
10. Do not create additional brands, tool names, package prefixes, or target
    naming schemes without updating this file first.

## 18. Initial canonical identity set

Use this set for Batch 0:

```text
Project:              Linnet
Device OS:            Linnet OS
Developer loader:     Linnet Boot
USB protocol:         Linnet Link
Host environment:     Linnet Studio
Development platform: Linnet SDK
Desktop runtime:      Linnet Simulator
Repository:           linnet
CLI:                  linnet
Initial target:       photo4g-p98
Initial target alias: a1099
Initial SoC ID:       pp5020
Release profiles:     release, dev, trace
Boot slots:           a, b
First app ABI:        1
First boot ABI:       1
First Link version:   1.0
First-party prefix:   linnet.
C ABI prefix:         ln_
Macro prefix:         LINNET_
TypeScript scope:     @linnet/
On-device root:       /LINNET/
```

This identity set is intentionally small. Add identifiers only when an
implemented contract needs them.
