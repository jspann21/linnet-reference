# Hardware variants

Observed configurations: [2026-10-03 hardware inventory](device-hardware-inventory.md).
The configurations below are historical; the current inventory records subsequent storage replacements.

Updated 2026-09-29. Scope: Linnet's four current target families. **Tested** means
physical evidence for the stated unit/path; **implemented** means code exists but
that variant still needs a physical check. A tested family does not qualify every
replacement part or board revision. This change uses referenced register facts
in Linnet's own drivers and bounded startup state machine.

| Physically tested unit | Observed hardware | Evidence |
| --- | --- | --- |
| Q21 A1059, USB `000000FA3188` | PP5020, 32 MiB, HD66753 monochrome LCD, WM8975; MK2004GAL 20GB, 512-byte sectors | Boot, library, stereo headphones, wheel/buttons/Hold, backlight, USB charging, sleep/wake, native USB read/write; `out/a1059-hardware-session/` |
| Q21 MP102, USB `2CD515103M` | PP5020, 32 MiB, monochrome LCD, WM8975; MK2006GAL 20GB, 512-byte sectors | Original bring-up; USB/charging diagnostics checked in an earlier RAM build. `out/a1059-hardware-session/mp102-*.json` |
| P98 Photo/Color, USB `000000F7A765` | PP5020, 32 MiB, LCD type 1, WM8975; iFlash 64GB, firmware `iFlash85` | Existing physical bring-up, display/video and storage checks; LCD type read over Link. `out/a1136-hardware-session/p98-*.json`, `out/variants-hardware-detection.json` |
| M25 A1136 30GB, USB `000A27001596FB5F` | PP5022, 32 MiB, WM8758/BCM2722, board `0x000b0010`; MK3008GAL, 512-byte sectors | Existing boot/media/input/power/video/sleep and USB checks; `out/a1136-hardware-session/COM8-*.json` |
| M25 A1136 80GB, USB `000A270015E30DA1` | PP5022, 64 MiB, WM8758/BCM2722, board `0x000b0011`; MK8010GAH, logical 512 / physical 1024 bytes | Extra RAM/cache, aligned read/write, audio/video, wheel/buttons/Hold, charging and sleep tested; `out/a1136-hardware-session/80gb-*.json` |
| N25 A1238, USB `000A2700155D9C10` | S5L8702, 64 MiB, CS42L55, LCD type 1; tested with MK3008GAL PATA disk and NOR ID `BF 25 8E` | Existing native Boot/NOR, OS, display, audio/video, storage and power bring-up; `out/classic6g-n25/`, `out/dev/classic6g-n25/bootstrap/` |

Current pass: development/release OS and release Boot builds verified for all four
targets, plus development Classic Boot. RAM playback/navigation passed on A1059,
Photo, and both A1136s: zero audio underruns/faults, ATA errors/retries, or dropped
input events. Receipts: `out/variants-*-audio-scroll.json`,
`out/variants-audio-scroll.json`, `out/variants-playback-final.json`.
These are RAM checks, not persistent installations. Classic's new LCD paths await
physical testing; MP102's latest RAM recheck is incomplete.

| Variation accounted for | Linnet handling | Physical status |
| --- | --- | --- |
| A1059 versus the existing MP102 identity | One Q21 hardware target; retail model-to-label mapping, native USB target identity | **Tested: both** |
| PP5020 / PP5022 / S5L8702 | Separate SoC register, cache, interrupt, clock and DMA implementations | **Tested: all three** |
| Q21/P98 32 MiB; N25 64 MiB | Target memory layouts; startup checks | **Tested** on the units above; other RAM chips unqualified |
| M25 32 / 64 MiB | Preserving upper-bank alias probe; 64 MiB boards use extra metadata and clean-read caches | **Tested: both**; 60GB unit not available |
| Q21 monochrome panel | HD66753 wake, contrast/scanout and monochrome conversion | **Tested: A1059 and MP102** |
| P98 original ROM revision `0x60000` | Force panel type 0 because original straps are unreliable | **Implemented**; that ROM revision not separately recorded |
| P98 LCD types 0/2 versus 1/3 | Detect straps; distinct command/window protocols; specialized COP video blit only on compatible even types | **Tested: type 1**; types 0/2/3 implemented, untested |
| M25 BCM board revisions `0x000b0010` / `0x000b0011` | Explicit admission and image identity check; common display/video service | **Tested: both**; other revisions/firmware images rejected |
| N25 LCD type 1 | Existing 8-bit initialization and RGB565 DMA | **Tested previously**; current expansion build-checked |
| N25 LCD type 0 | Strap selection; its own pixel-format/sleep-out setup | **Implemented, untested** |
| N25 LCD types 2/3 | 16-bit register setup, bounded power settling and GRAM addressing; same frame DMA | **Implemented, untested** |
| Old Q21 disks omit rotation information | Exact 4200-rpm fallback for MK2004GAL, MK2006GAL, MK4004GAH | **Tested: first two**; 40GB untested |
| Old P98 disks omit rotation information | Exact 4200-rpm fallback for MK2006GAL, MK3006GAL, MK4006GAH, MK6006GAH | **Implemented**; factory disks untested on P98 |
| Old M25 disks omit rotation information | Exact 4200-rpm fallback for MK3008GAL, MK6008GAH, MK8010GAH | **Tested: 30/80GB**; 60GB untested |
| Other PATA HDD/SSD models | IDENTIFY capabilities, capacity and timing; model/capacity are not used to guess sector size or RAM | **Implemented**; only listed drive/board combinations physically qualified |
| ATA LBA28 / LBA48 | Capability-based addressing; range checks | **Tested: both**; capacity beyond the tested drives unqualified |
| PP logical 512, physical 512/1024/2048/4096 bytes | Physical-sector alignment and edge read/modify/write | **Tested: 512/1024**; 2048/4096 physical sectors untested |
| CF/Delkin identifiers; malformed CFA capability words | PP CFA admission plus actual LBA read verification; no arbitrary adapter exemption | **Tested: P98 iFlash case**; other CFA adapters untested |
| iFlash model and firmware `iFlash85` | PP flash classification/power handling; P98-specific DMA qualification | **Tested: P98 only**; other models, firmware and cards unqualified |
| DMA versus PIO | Advertised modes plus board qualification; M25 two tested HDDs and P98 iFlash use qualified DMA; other PP drives use PIO | **Tested** on the stated combinations; added 60GB fallback does not enable speculative DMA |
| ATA physical power removal | PP fallback model names alone do not enable rail removal; flush/standby and qualified media rules remain | **Tested** on existing units; replacement adapters unqualified |
| USB disk sectors 512/2048/4096 | Host uses reported geometry; per-target admission; ATA geometry stays distinct | **Tested** on existing retail/native combinations; not every size on every board |
| USB Link versus mass storage speed | Q21/M25 native high speed; P98 retains its qualified full-speed path; separate diagnostic transport | **Tested**; MP102 high-speed check was a RAM build |
| Optical wheels, buttons, Hold, jack detection, clickers | Board-specific controller/GPIO paths | **Tested** on existing units; replacement wheel assemblies unqualified |
| WM8975 / WM8758 / CS42L55 playback | Separate codec/rate/power configuration and bounded audio DMA | **Tested** on existing units |
| PCF50605 / PCF50635; different charger-state pins | Target PMU/ADC paths; Q21 GPIOB versus P98 GPO32 versus M25 wiring | **Tested** on existing units |
| USB 100/500 mA and suspend | Negotiated limit controls; cached power diagnostics report limit and charging state | **Tested charging**; A1059/MP102 report 500 mA. Actual current not measured |
| USB versus FireWire power | Separate source detection on PP targets | USB **tested**; FireWire electrical charging untested; no native FireWire data stack |
| Disk-directory boot versus N25 NOR boot | Separate boot/install/recovery paths and target-bound images | **Tested** on existing units |

| Known remaining gap | Current behavior / required qualification |
| --- | --- |
| Classic CE-ATA storage | Detected by board strap and rejected before PATA pin configuration; native MMC/CE-ATA transport still missing |
| Native ATA logical sectors other than 512 bytes | Rejected; host USB 4K-sector handling does not provide a native 4Kn ATA driver |
| Classic CF/iFlash quirks and physical-sector edge handling | PP-specific support is not present in the S5L ATA driver; requires separate implementation and qualification |
| Alternative Classic NOR chips | Writes admit only JEDEC `BF 25 8E`; other programming/erase/protection protocols need qualification |
| Classic 2007/2008/2009 board populations | A1238 label alone is insufficient. Only the observed panel/disk/NOR/RAM combination is physically qualified |
| Headset inline buttons / Classic Mikey controller | Not implemented; A1136 headset controls were physically tried and did not work. Classic Mikey-equipped variants need their own driver and hardware check |
| Dock line-out, microphone/line-in, TV-out, remote/FM accessories | Playback codec hooks do not qualify these electrical paths. Independent WM8975 line-out control, recording, TV-out and accessory protocols remain incomplete/unverified |
| Replacement batteries / chargers / display and wheel assemblies | No assumption based on shell label or advertised battery capacity; electrical behavior and compatibility need an actual sample |
| MP102 current RAM recheck | RAM launch accepted, old installed image subsequently observed without a crash record, then USB disappeared. Latest build remains unqualified on this unit; earlier physical results are retained |

Hardware references: [Apple model families](https://support.apple.com/en-us/103823),
[Classic LCD register facts](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/s5l8702/ipod6g/lcd-6g.c),
[Photo panel detection](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/ipod/lcd-color_nano.c),
[PP power wiring](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/ipod/power-ipod.c),
[Classic storage protocols](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/s5l8702/ipod6g/storage_ata-6g.c),
[Classic Mikey variants](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/s5l8702/ipod6g/mikey-6g.c),
[Toshiba 30/60GB specifications](https://cdn.centralpoint.nl/objects/pdf/4/4a0/1348033326_1_interne-harde-schijven-toshiba-60gb-4572-cm-18-ata-4200rpm-mk6006gah.pdf),
[Toshiba MK4006GAH family specification](https://manualmachine.com/toshiba/mk3006gal/450125-user-manual/),
[Toshiba MK6008GAH specifications](https://auto.manualsonline.com/manuals/mfg/toshiba/mk6008gah_hdd1724.html?p=6).
