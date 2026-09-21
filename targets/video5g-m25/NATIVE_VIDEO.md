# Native M25 video

The target uses BCM2722 H.264/MPEG-4 playback with ARM AAC audio. Vendor
resources come from this device's checksum-verified firmware backup and stay
outside the source tree. The portable MP4 reader is in `services/video/mp4.*`;
BCM transport, display ownership and recovery remain in this target.

Verified on the 30 GB MA146 (SysCfg revision 0x000B0010):
- Native H.264 Baseline and MPEG-4 Simple Profile presentation observed by camera.
- Both 20-second samples completed 480 video frames and 882,000 AAC audio frames,
  with zero reported underruns, inserted silence or driver faults.
- Normal playback controls: pause, resume, forward/backward keyframe seek while
  paused, Menu stop, saved-position reopen and missing-file failure.
- NOR display-runtime restoration and responsive Link after stop and EOF.
- All 27 enabled UI scenes and scrolled lists rendered in all three themes.
- Published H.264/MPEG-4 catalog entries open from Videos; populated Notes render.
- Owner-confirmed stereo headphone audio, buttons, wheel, Hold and headphone changes.
- Development fault injection: BCM clock loss restores the NOR display runtime;
  fatal restoration failure automatically reboots the healthy persistent OS.

Seek selects a sync sample and aligns AAC to its actual timestamp. This is
keyframe seeking, not exact-frame seeking. Native video owns the full display;
Play or Select pauses, Left/Right seeks, the wheel changes volume, and Menu exits.
Audio cache hits can proceed during video disk reads, with audio serviced first
and a larger reserve in the existing PCM ring. EOF waits for the final audio
block to drain. Repeated published-file playback and paused seeks passed with
zero underruns or inserted silence after these corrections.

Physical charging transitions, dock output and release-image operation remain
manual acceptance checks. Windows Disk Mode verification uses bounded 64 KiB
reads, but a repeated read-only run still lost the USB device descriptor before
any write. USB stability remains unresolved. Clock-loss recovery does not prove
recovery from every possible external-bus stall.
A later traced run survived 70 seconds idle, full read-only guards and guarded
eject back to the exact healthy OS, but Windows performed three hidden USB
re-enumerations during reads. A successful roundtrip does not close that issue.

The retail ARM code establishes the stream contract: configuration serialization
at 0xc8770/0x288f40, Annex B SPS/PPS construction at 0x1cab08, encoded NAL length
at 0x1cab94, and frame fragments at 0x288c14. A complete sample uses first|last
fragment bits (3). LCD model selection at 0x265518 maps this device's recorded
0x000B0010 interface revision to model 2; production admission must select from
actual board revision rather than a universal M25 default. Retail startup at
0x1aff9c also writes that model to VMCS offset 0x1f4 before execution.

References: [original firmware research](https://github.com/giek2000/ipod-classic-firmware-research),
[resource analysis](https://github.com/siggifly/ipod-emulator/blob/dev/research/10-the-resource-image.md),
[runtime analysis](https://github.com/siggifly/ipod-emulator/blob/dev/research/11-the-videocore-runtime.md),
[openVC02](https://gitlab.com/cmdly/openVC02). Protocol observations are checked
against the device's own ARM image; emulator replies are not hardware evidence.
