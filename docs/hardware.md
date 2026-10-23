# Hardware support

The configurations below have been tested on-device. Physical controls,
audible output and panel appearance require observation in addition to automated
checks. Accessories have not been tested.

For installation, use [Media Manager](media-manager.md). For a new model, use
the [porting guide](../targets/README.md).

## Tested devices

| Device | Target | Storage | RAM | Display |
| --- | --- | --- | --- | --- |
| iPod Photo / Color A1099 | `photo4g-p98` | iFlash, 64 GB | 32 MiB | 220 × 176 color |
| iPod Video A1136 | `video5g-m25` | Toshiba MK3008GAL, 30 GB | 32 MiB | 320 × 240 color |
| iPod Video A1136 | `video5g-m25` | Hitachi HTC426030G5CE00, 30 GB | 32 MiB | 320 × 240 color |
| iPod Video A1136 | `video5g-m25` | iFlash, 125 GB | 32 MiB | 320 × 240 color |
| iPod Video A1136 | `video5g-m25` | Toshiba MK8010GAH, 80 GB | 64 MiB | 320 × 240 color |
| iPod classic A1238 | `classic6g-n25` | iFlash, 125 GB | 64 MiB | 320 × 240 color |
| iPod classic A1238 | `classic6g-n25` | Toshiba MK1634GAL, 160 GB | 64 MiB | 320 × 240 color |
| iPod 4G monochrome A1059 | `ipod4g-q21` | Toshiba MK2006GAL, 20 GB | 32 MiB | 160 × 128 grayscale |
| iPod 4G monochrome MP102 | `ipod4g-q21` | Toshiba MK2006GAL, 20 GB | 32 MiB | 160 × 128 grayscale |

Storage capacities describe the tested configurations, not capacity limits.

## Features

| Target | Features |
| --- | --- |
| [Photo P98](../targets/photo4g-p98/README.md) | Music, photos, prepared IPVF video, Cover Flow, and games |
| [Video M25](../targets/video5g-m25/README.md) | Music, photos, native H.264/MPEG-4 video, Cover Flow, and games |
| [Classic N25](../targets/classic6g-n25/target.toml) | Music, photos, native MP4 video, Cover Flow, and games |
| [Monochrome Q21](../targets/ipod4g-q21/target.toml) | Music and the iPod Mono interface; photos, video, Cover Flow, and games are disabled |

All four targets support native Disk Mode, A/B OS updates, and
[Linnet Link](device-link.md) in development builds. Media Manager handles
installation; Classic requires guided DFU entry for its initial Boot setup.

## Compatibility

Classic requires PATA storage; CE-ATA is not supported. Its NOR writer supports
JEDEC `BF 25 8E`. Native storage uses 512-byte logical sectors.
See [storage compatibility](storage.md) for filesystem and disk requirements,
[video formats](video-format.md) for supported media, and
[Apple OS library updates](apple-stock-music.md) for sharing music with Apple's
original software.
