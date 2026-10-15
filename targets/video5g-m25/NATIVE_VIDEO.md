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

The player prioritizes audio and drains its final block at EOF. On a prepared
M25 installation, the verified native display runtime starts once before Home.
The UI and movies then share that runtime, avoiding a display reset at every
video start. A separate native UI layer keeps the selected video's startup
message visible until the selected frame has a compositor acknowledgement,
including after a saved-position seek. Audio waits for that same acknowledgement.
Video startup does not turn the backlight off.
The first selected frame already shows "Starting video...", including time
spent draining prior media work. Its dim theme background remains visible;
there is no initial empty black frame while waiting to admit the video open.

The native UI uses two independently allocated RGB565 surfaces and the existing
ARM framebuffer. Only the inactive surface receives pixel uploads. Presentation
swaps surfaces after the update acknowledgement. Partial uploads combine the
previous committed frame's original damaged rows with the current frame's
damage, matching the two-buffer scheme in the device's RetailOS. Full frames
retain the existing transfer size; small updates can repair an additional prior
row span. The second surface costs 153,600 bytes of coprocessor memory.

Stopping waits for a fresh native stream-stop request and its published host
reply, then verifies idle before unloading the exact application task returned
by the native loader. TV output disables its DAC before releasing ownership.
An early cancellation that loaded an application but never sent selectplay
unloads that known task directly; no stream-stop handshake exists in that state.
The UI layer returns through the same native display runtime. A bounded failure
path restores the verified NOR display runtime. Handoffs to another image also
restore that original runtime before leaving Linnet.

Completed BCM file-service responses copy in fragments of up to 512 bytes per
service call. Ring reads stay limited to 128 bytes. Space is checked for the
complete response, and its producer pointer publishes only after all fragments
are copied. Normal playback prepares its PCM reserve while the native runtime
starts. After the display-region command completes, playback waits for that
reserve instead of an unconditional two-second settle. Running, non-buffering
status permits checking the first picture; it does not by itself start audio
or remove the startup message. The revision-specific check validates the full
application task token, bounded native allocator extents, video descriptor and
frame-array membership, completed update counters, and current stream sequence.
The selected PASSTHRU admission path increments the host sequence once, so the
comparison converts it back before checking the saved-seek floor and published
frame ceiling. Repeated reads reject changing task, descriptor and frame state.
This orders UI removal after the current movie object enters the compositor;
it does not independently measure an LCD scanline. Optical qualification remains
necessary, and black frames encoded in a video are separate from a display gap.

Checks run only during the picture handoff, at most once per 10 ms, with an
absolute five-second timeout and normal display restoration on failure. File,
stream and audio preparation continue between checks. An unfinished picture
requirement survives pause/resume during a seek. Audio and its playback clock
start after the acknowledged frame, avoiding a soundtrack that advances during
native decoder startup. Ordinary pause/resume after a committed frame retains
its existing status synchronization.
Preparation yields extra audio decoding once the startup reserve is ready so
the native stream can produce its first picture. Running playback retains its
normal, larger audio buffer target. For normal playback below 44.1 kHz, startup
and seek reserves preserve at least the original 32,768 / 44,100 second duration,
rounded up to a whole 1,024-frame AAC block. Higher rates retain 32,768 frames;
steady playback retains its 49,152-frame target.

Native firmware and read-through decoder-library bytes borrow an idle music
decoder workspace. The lease ends before returning to idle UI or music. Only
completed reads from the five qualified immutable native libraries enter the
cache; no extra disk reads run to populate it. Byte coverage and file metadata
bind the current mount, and music decoder reuse invalidates coverage. Accepted
storage recovery explicitly invalidates it even if a new FAT mount reuses an
epoch value. Cached responses retain the same complete-response publication
and bounded BCM transfer rules.

Idle native UI does not poll display rings without pending presentation work.
Its native power policy is `min`; a foreground development query can inspect
native power status. CPU-idle, drive-standby and power-fault measurements are
regression checks, not a substitute for an unplugged battery-runtime test.

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

The tag-2 protocol was additionally checked against the locally extracted,
verified RetailOS: surface allocation at 0x286CA8, pixel upload at 0x287BE8,
and two-surface presentation at 0x164F44. Its damage helper at 0x164D68 takes
the minimum starting row and maximum ending row; presentation saves the current
original damage for the next frame. Vendor binaries remain outside the source
tree. The VMCS display-clear iterator returns its own fixed object at
0xC000FB50 rather than traversing independently allocated tag-2 elements.
