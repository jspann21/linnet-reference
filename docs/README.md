# Linnet documentation

Start with the [project README](../README.md) for installation, source setup,
builds, and the simulator. The [hardware reference](hardware.md) lists tested
configurations and compatibility limits. The [roadmap](roadmap.md) tracks the
work remaining before release and possible future features.

## Using Linnet

| Guide | What it covers |
| --- | --- |
| [Media Manager](media-manager.md) | Install and restore firmware, prepare libraries, manage playlists, and recover interrupted work |
| [Device menus](navigation.md) | Menu organization, playback controls, and saved customization |
| [Files](files.md) | Browse the disk, open media and text, and understand prepared previews |
| [Hardware support](hardware.md) | Tested devices, board and storage variants, and qualification limits |
| [Storage compatibility](storage.md) | Filesystems, disk geometry, storage power, and diagnostics |
| [Apple OS library updates](apple-stock-music.md) | Qualification and path restrictions for sharing media with Apple's original software |

## Developing Linnet

| Guide | What it covers |
| --- | --- |
| [Architecture](architecture.md) | Source map, boot/update model, and runtime services |
| [SDK](../sdk/README.md) | Build apps, themes, and screens; use the simulator |
| [UI compiler](ui-compiler.md) | Static TSX compilation and the native renderer contract |
| [Linnet Link](device-link.md) | USB diagnostics, input, captures, RAM boot, and persistent updates |
| [Adding an iPod target](../targets/README.md) | Manifests, HAL integration, installation policy, and physical qualification |
| [Bootstrap tooling](bootstrap-tooling.md) | PortalPlayer directory installation and Classic NOR recovery |
| [Local artifacts](local-artifacts.md) | Build outputs, recovery backups, and information to keep out of public reports |
| [Builds and releases](releases.md) | GitHub builds, Windows executable, firmware ZIPs, source archives, and publishing |
| [Contributing](../CONTRIBUTING.md) | Contribution scope, validation, and issue reports |
| [Roadmap](roadmap.md) | Release acceptance, known issues, performance work, and feature proposals |

## Media and binary formats

| Reference | What it covers |
| --- | --- |
| [Binary contracts](formats.md) | Format owners and links to encoders, validators, and readers |
| [Music library](music-format.md) | PODB records, identities, paths, and publication |
| [Album artwork and Cover Flow](artwork.md) | Prepared renditions, resident previews, caching, and validation |
| [Prepared photos](photo-format.md) | LPIC libraries, tile packs, grids, and publication |
| [Video formats](video-format.md) | IPVF and target-specific native MP4 preparation |

Public guides describe current behavior and usable workflows. Hardware references
state what was exercised and what remains unqualified; the roadmap records open
work. Keep session notes, raw measurements, device identifiers, and build receipts
in local artifacts. Exact binary fields belong with their producer and reader.
