# M25 qualification

A check passes only for its stated observable. Link observes firmware counters,
returned data and captured framebuffer pixels. It cannot observe sound at the
headphone socket, light from the panel, or actual USB current without external
measurement. Synthetic input does not qualify physical switches.

## Checked on the 30 GB M25

| Area | Check and result |
| --- | --- |
| Native startup | Firmware-directory Boot, RAM OS and persistent OS reach health flags 31. |
| Display transport | Native 320 x 240 CRC-checked framebuffer captures and repeated completed presentations. |
| Input/executive | 256 balanced wheel events, synthetic button/hold/headphone transitions, no event drops; bounded latency check passed. |
| Power scheduling | Three timed sleep/wake cycles, brightness acknowledgement and idle-without-redraw check passed. |
| Audio timing | 8, 11.025, 12, 16, 22.05, 24, 32, 44.1 and 48 kHz: 8,192 samples each consumed without underruns, inserted silence or driver faults. |
| AAC in M4A | Entire 10,210,620-frame track at 44.1 kHz decoded and drained with zero underruns and zero inserted silence; backward seek also passed. |
| Codec families | PCM, MP3, FLAC, ALAC, raw AAC and Vorbis samples completed with zero underruns, in addition to the full AAC/M4A track. |
| Photos | Native fit, zoom, quarter-turn rotation and slideshow advance passed after sizing the cache from viewport geometry. |
| Host USB roundtrip | 1 MiB host write, fsync, complete readback, safe eject and exact healthy OS reconnect passed with the finite elevated helper. |
| Storage | 1 MiB SHA-256 write/readback, 256 random reads, file creation/growth and settings restoration passed. |
| Storage recovery | All five existing injected fault modes rejected the affected transaction and recovered with verified readback. |
| Persistent recovery | Good candidate confirmation, deliberate crash rollback, and all four reset boundaries for both settings and firmware publication passed. |
| Build isolation | Development M25 plus release Boot/OS builds for M25, Photo P98 and monochrome Q21 pass image/release checks. Older boards require their own hardware regression run. |

## Remaining qualification

- Implement and qualify native H.264/MPEG-4 playback through BCM2722. The IPVF
  experiment does not qualify this requirement; further IPVF adaptation is
  out of scope. See [native video](NATIVE_VIDEO.md).
- Theme persistence and storage preparation after media directory discovery passed.
- Physically verify analog headphone output, panel/backlight appearance, wheel,
  hold and headphone sensing, and actual charging current/source transitions.
  The repaired Select switch opened Music from Home on hardware, confirmed by
  the owner and the live scene state with synthetic input disabled.

The entry contract inherits ROM-initialized BCM and SDRAM. The development-only
native-video probe now verifies independent BCM power cycling, retail runtime
startup and automatic restoration of the NOR display runtime while Link remains
responsive. Native frame delivery and the remaining presentation boundary are
recorded in [native video](NATIVE_VIDEO.md).

The USB camera confirmed the native home screen, legible text, backlight response
and Copper theme persistence across a RAM reload. Select was physically repaired
and confirmed working. Analog sound and charging current still require physical
observation or measurement; no measurement equipment is connected.

Machine-specific build IDs, raw measurements, images and recovery receipts are
retained in local `out/a1136/qualification/` and `out/runs/`; they do not belong
in portable source defaults.
