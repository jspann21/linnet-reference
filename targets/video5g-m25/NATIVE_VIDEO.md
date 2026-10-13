# Native M25 video

M25 plays H.264 Baseline and MPEG-4 Simple Profile through BCM2722, with AAC audio
decoded on the ARM. Required vendor resources come from the device's verified
firmware backup and remain outside the source tree.

The shared [MP4 reader](../../services/video/mp4.c) validates the container.
BCM transfer, display ownership, resource selection, and recovery are target
responsibilities. Board revision determines display/runtime configuration;
do not treat one observed revision as universal.

## Playback

Native video owns the display. Play or Select pauses; Left/Right seeks to a
keyframe; the wheel changes volume; Menu exits. Seeking aligns audio to the
selected keyframe's timestamp rather than promising exact-frame access.

The player prioritizes audio and drains its final block at EOF. Stopping video
restores the display runtime before returning to the UI.

Completed BCM file-service responses copy in fragments of up to 512 bytes per
service call. Ring reads stay limited to 128 bytes. Space is checked for the
complete response, and its producer pointer publishes only after all fragments
are copied. The existing pre-play settle and audio reserve remain in place.

## Verified boundary

On the qualified 30 GB MA146 board, H.264 and MPEG-4 samples exercised playback,
pause/resume, seeking, EOF, saved-position reopen, and missing-file handling.
Camera observation confirmed video presentation; device counters checked audio
and transfer behavior. Clock-loss injection exercised display restoration and
reboot fallback when restoration failed.

This does not establish all-file compatibility, long-duration A/V quality, or
recovery from every external-bus stall. See [qualification](QUALIFICATION.md)
and the [Linnet TODO](../../docs/roadmap.md).

## References

- [Original firmware research](https://github.com/giek2000/ipod-classic-firmware-research)
- [Resource image analysis](https://github.com/siggifly/ipod-emulator/blob/dev/research/10-the-resource-image.md)
- [VideoCore runtime analysis](https://github.com/siggifly/ipod-emulator/blob/dev/research/11-the-videocore-runtime.md)
- [openVC02](https://gitlab.com/cmdly/openVC02)

Protocol observations must be checked against the device's resources.
Emulator responses are not hardware evidence.
