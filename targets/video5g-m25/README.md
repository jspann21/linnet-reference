# iPod Video M25 (A1136, 30 GB)

This target is independent Linnet firmware for the 32 MiB M25 board, using the
PP5022 register family, WM8758 audio and BCM2722 320 × 240 RGB565 display.
MA146 is the currently enumerated model. Other A1136 variants, including 64 MiB
models, need their own confirmed identity and memory profile before enabling
installation. Retail serials and build USB identities belong in local receipts,
not source defaults.

## Ownership

- `device.c`: board pin wiring, disk power, charging and backlight steps.
- `hardware.h`: ROM Disk Mode marker and bounded compatibility policies.
- `lcd.c` / `display.c`: BCM mailbox transfer and incremental scanout.
- `games.c`: native Comet Run, Pulse Path and Solitaire gameplay, drawing and sound cues.
- `screens/`: complete native 320 × 240 screen set.
- `ui/profiles/color320/themes/`: native editions of Linnet (default), Midnight, Graphite, Aurora,
  Sunset, Blueprint, Album Colors, Minimal Dark and Minimal Light.
- `system.toml`: default applications, features and theme.
- `target.toml`: discovery, image, memory, media and resource contracts.

Shared PP502x transport and CPU code is under `hal/pp502x`; the WM8758 driver
is under `hal/codecs`. The display inherits the ROM-initialized BCM VMCS image.
Linnet embeds no Apple firmware and does not use Rockbox's runtime or build.
The boot font derives from `sdk/assets/font-hint11.json` under the accompanying
`sdk/assets/FONT-LICENSE.txt`.

Theme editions retain their shared IDs and palettes, with a larger Sans font
and complete 320 × 240 scene geometry in `ui/profiles/color320/layouts.py`.
Graphite and Sunset retain bottom transport chrome, Aurora its side rail,
Blueprint its bottom status bar and two-column menus, and Minimal its battery
line. The target allowlist replaces the provisional Video palettes with these
nine themes. iPod Photo remains exclusive to `photo4g-p98`; an iPod-style M25
theme is not included.

## Games

Open **Games** from Home to play Comet Run, Pulse Path or Solitaire. In Comet
Run and Pulse Path, use the wheel to steer or choose a pad, Select to activate a shield or tap a pad, Play to pause, and
Menu to leave. Comet Run awards points for dodged meteors. Pulse Path awards
points for repeating each growing light pattern. A wrong pad costs one life and
replays the pattern; clearing all 24 rounds ends the game. Both games have three
lives, retry from the result screen, and save their best scores in the optional
theme state records created by a current Linnet installation.

Solitaire uses draw-one Klondike. The wheel cycles through stock, waste, four
foundations, and seven tableau piles. Select on stock draws one card; after the
stock empties, Select turns the entire waste over for another pass. Select a
face-up card, turn the wheel to its destination, and Select again to move it.
Previous/Next chooses a different face-up card in the focused tableau pile so
you can move a sequence; Select on the same pile cancels a pickup. Tableau
stacks descend in alternating colors, empty columns take Kings, and foundations
build by suit from Ace to King. Revealing a covered card happens automatically.
Play pauses or resumes, Select while paused starts a new deal, Menu returns to
Games, and Select after a win deals again. The move counter resets on each deal
and completed games add to the persistent win count.
The J/Q/K card illustrations are downsampled from Austin Gabriel's
[Public Domain Playing Cards](https://github.com/AustinGabriel/Public-Domain-and-CC0-Playing-Cards)
(CC0); they are stored as a compact RGB565 palette in `solitaire_courts.h`.

In Linnet Media Manager, open **Games** while this iPod is in Disk Mode. Choose
the games to show, save, then eject safely. The selection is read from
`.LINNET/GAMES.BIN` at the next Linnet startup. An empty selection removes Games
from Home until a game is selected again.

## Hardware evidence (2026-09-19)

Native Boot boots from the Apple firmware directory and provides USB Link.
The development OS RAM-boots with health flags 31 at a verified 80 MHz.
The first-frame and subsequent presentation counters complete without failure;
a CRC-checked 320 × 240 screenshot was retrieved through Link. The OS compiles 29 scenes, with 27 enabled. The corrected software Disk Mode transition re-enumerates the
original FAT32 USB disk without button presses. The restart marker lives at
`0x4001ff00`, unlike PP5020's `0x40017f00`.

The observed factory FAT32 BPB includes one final physical sector omitted by
its MBR partition length. The target admits that sector only when the volume
ends exactly one sector before disk end and no partition claims the tail.
It does not alter the MBR or relax FAT32 structural checks.

The FAT32 volume mounts with all seven installation files validated and no I/O
failures. Link publishes an A/B OS candidate, and a persistent restart loads
that exact image and reaches health flags 31. Remote wheel navigation, a
brightness change and a timed sleep/wake cycle completed with no event drops.
WM8758 initialization and DMA playback at 44.1 kHz work without a driver fault.
The existing AAC sample ran for 52 seconds with zero underruns and zero injected
silence frames after fixing the independent M4A reader to retain all three
working regions (STCO, STSZ and compressed audio). This is one sample, not
format-wide qualification. Existing third-party audio codec libraries retain
their original provenance and licenses; they are permitted dependencies.

The owner confirmed stereo headphone audio, buttons, wheel, Hold and headphone
changes. Native H.264/MPEG-4 playback, NOR display restoration and automatic
recovery after a forced restoration failure passed device checks. Charging
transitions, dock output and release operation remain manual acceptance checks.
An intermittent USB descriptor failure also occurred during read-only Apple
Disk Mode verification; USB stability remains unresolved. See `NATIVE_VIDEO.md`.

## Development through Link

Use `python linnet device info --port <port>` to confirm the attached target,
then build with `python linnet build --target video5g-m25 --profile dev --verify
--device-serial <enumerated-usb-serial>` (one command). Upload the generated
`.los` envelope with `python linnet device boot --port <port> --image <image.los>`.
The `.bin` artifact is a raw payload and is not a Link upload envelope.

`python linnet device install --port <port> --image <image.los>` publishes an
A/B candidate. `python linnet device reboot --port <port> --mode persistent`
loads it from disk. Wait for health flags 31 before judging startup complete.
After media browsing, the installer explicitly refreshes the read-only FAT
ownership proof through Link before attempting any persistent write.

Link also injects input and retrieves screenshots, so development does not
require a functioning Select switch. Software Disk Mode plus the finite,
plan-bound elevated Windows refresh session supports a disk-to-Link roundtrip.
Use `python linnet device refresh-session status` to check the helper lifetime.
Each session is bound to its reviewed native installation plan; a new boot
maintenance plan requires its own reviewed session. Normal OS updates use Link.

The nominal M25 voltage-to-percentage curve is board-local. It is an estimate,
not a measurement of this battery's remaining capacity. The fitted Toshiba
MK3008GAL receives its documented 4,200 RPM classification by exact model match;
replacement drives retain their own IDENTIFY-derived classification.

## References

Hardware facts and protocol descriptions were consulted; third-party firmware
is not incorporated into this target:

- [Original firmware research](https://github.com/giek2000/ipod-classic-firmware-research/blob/main/specs/iPod_5th_Gen_Video_13_1_2_1.md)
- [BCM LCD registers and command protocol](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/ipod/video/lcd-video.c)
- [PP502x clocks](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/pp/system-pp502x.c)
- [ROM Disk Mode marker](https://github.com/Rockbox/rockbox/blob/master/bootloader/ipod.c)
- [M25 nominal battery measurements](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/ipod/powermgmt-ipod-pcf.c)
- [Toshiba MK3008GAL specifications](https://datasheet4u.com/pdf/636644/MK4008GAH.pdf)
- [WM8758 register definitions](https://github.com/Rockbox/rockbox/blob/master/firmware/export/wm8758.h)
- [M25 board configuration](https://github.com/Rockbox/rockbox/blob/master/firmware/export/config/ipodvideo.h)

Original Apple payload and firmware-directory backups are preserved locally.
Media contents were not backed up. Elevated Windows sessions remain finite,
identity-checked and bound to a reviewed installation plan.
