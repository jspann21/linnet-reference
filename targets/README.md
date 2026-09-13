# Adding a Linnet target

Each supported device has one `targets/<target-id>/target.toml`. Build, image,
RetailOS detection, Media Manager capabilities and installation all load that
manifest through `tools/studio/targets.py`; target IDs and USB/model tables are
not duplicated in the installer.

For another PP5020-era iPod with the supported Apple firmware directory
layout:

1. Add the target directory, startup/linker/device/display sources and UI compiler
   description.
2. Add its build identity, screen geometry and capabilities to `target.toml`.
3. Fill `[retail]` from observed RetailOS `SysInfo` and Windows USB enumeration.
   Detection requires the VID/PID plus either an exact board name or exact model
   number, and confirms the SysInfo hardware GUID against USB enumeration.
4. Fill `[installer]` from the model's verified wrapper and disk layout. Set
   `enabled = true` only after the declared layout and bounds have been checked
   against that device. Compatible targets use `boot_layout =
   "ipod-directory"`. A target can use a
   descriptive unimplemented layout such as `boot_layout = "unqualified"` with
   `enabled = false` while it is being brought up; Media Manager will recognize
   the device and clearly report that installation is unavailable.
5. Run `python linnet doctor`, build Batch 7 release OS and development Boot
   images for the new target, and exercise installer inspection, interrupted
   provisioning, native plan guards, installation, restart and restoration on
   physical hardware.

The target loader validates every required field at startup. Duplicate aliases or
numeric image IDs, invalid USB IDs, unsafe loader paths, overlapping partition
types, enabling an unsupported install layout, malformed wrapper identifiers and
unaligned or unbounded firmware sizes stop before discovery or build.

The installer never chooses a model from display size or a friendly drive name.
Adding aliases alone does not make a device installable; the RetailOS and installer
profiles are mandatory and the generated image target must match the detected
target exactly.
