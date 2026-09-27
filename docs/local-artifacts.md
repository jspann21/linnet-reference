# Local artifacts and recovery files

`out/` is ignored scratch space for builds, simulator output and temporary reports.
Keep durable documentation in the source tree and retain useful local outputs.
Each build writes its generated inputs, objects, images, and report to a unique
`out/<profile>/<target>/<kind>/runs/<invocation>/` directory. The paths in a
build report refer to artifacts from that invocation, including when builds
overlap or the source branch changes between builds.
Compilation uses two workers by default. Set `--jobs` to an integer from 1 to 4
to adjust its CPU and memory use; linking remains serial.

Firmware backups, installation plans, predecessor files and recovery receipts
belong to the physical device and installation that produced them. Preserve them
together in a separate local backup before cleaning `out/`. Keep device serials,
hardware GUIDs, disk identities and personal media out of GitHub contributions.

Plans can reference absolute paths and pinned hashes. If an artifact archive is
relocated, restore the required files and dependencies to the paths expected by
the plan before using it. Do not edit hashes to accommodate relocation.

Inspect the connected device and its matching receipts before a firmware
operation; an old build report does not establish the current installed state.
See [Media Manager](media-manager.md) for installation and restoration, and
[Linnet Link](device-link.md) for low-level device operations.
