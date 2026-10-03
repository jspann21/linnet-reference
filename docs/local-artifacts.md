# Local artifacts and recovery files

`out/` is ignored scratch space for builds, simulator output and temporary reports.
Keep durable documentation in the source tree and retain useful local outputs.
Build artifacts are written to `out/<profile>/<target>/<kind>/`.

Do not use `out/` as a documentation, investigation-note, transcript, or research
archive. Agents and repository tools must not recursively inventory, search, or
load `out/`, sibling artifact archives, or prior worktrees for general context.
Read an exact artifact only when the current operation requires it, check its
size first, and keep the read bounded. Generated receipts and binary evidence
are operation outputs; they are not project documentation or current source of
truth.

Keep only the current device-owned recovery material that is still required to
restore an installed device. Old standalone plan archives are not repository
context and are not retained for future agent use. Keep device serials, hardware
GUIDs, disk identities and personal media out of GitHub contributions.

Archived plans are not inputs to the normal Disk Mode exit workflow. Run
`python linnet device eject --reboot --disk-number N --expected-serial STORAGE_SERIAL --allow-uac` without an
explicit plan so the command resolves the current installation record from the
mounted iPod. Delete obsolete plan archives instead of searching them or old
worktrees to make an eject work. If current metadata fails validation, keep the
volume mounted and repair the current installation state.

Inspect the connected device and its matching receipts before a firmware
operation; an old build report does not establish the current installed state.
See [Media Manager](media-manager.md) for installation and restoration, and
[Linnet Link](device-link.md) for low-level device operations.
