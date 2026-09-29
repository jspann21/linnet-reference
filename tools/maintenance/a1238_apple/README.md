# Apple database maintenance tools

For ordinary library updates, use [Media Manager](../../../docs/media-manager.md#make-folders-available-in-apple-os).
This directory contains its native database writers and older A1238 investigation
tools. The older planners are bound to particular hardware and local artifacts;
their defaults are not portable examples.

## Native writers

- `managed_music.c`: updates staged Apple music/video databases while preserving existing entries and playlists.
- `managed_photos.c`: creates staged Apple photo data.
- `managed_io.h`: native Windows filesystem and helper compatibility.

Run `python linnet setup` from the repository root to build the Windows tools.
The [tool builder](../../studio/apple_tools.py) downloads pinned dependencies,
verifies them, and supplies the packaged app's helper distribution. Media Manager
validates device admission and publishes the verified staged output.

## Legacy alias investigation

`fat_alias_plan.py`, `compact_alias_plan.py`,
`generate_library_manifest.py`, and `verify_live_aliases.py` supported a
specific Apple path-length investigation. Review their hardcoded assumptions
before any reuse. They are not a supported general-purpose alias repair command.

The [journal writer](../a1238_apple_alias_journal.py) applies only an exact,
reviewed plan. Its before/after sector images, plan hash, geometry, and device
identity must agree. Restore handles a fully applied plan; recovery handles a
recognized mixture of before and after sectors. Keep those artifacts together,
and do not change the library between planning and recovery.

Do not publish device identities, manifests, sector journals, or media inventories.
The portable conclusions and current path limits are in
[Apple OS library updates](../../../docs/apple-stock-music.md).
