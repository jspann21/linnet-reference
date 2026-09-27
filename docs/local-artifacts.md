# Local artifacts and recovery files

`out/` is ignored scratch space for builds, simulator output and temporary reports.
Keep durable documentation in the source tree and retain useful local outputs.
Each build writes its generated inputs, objects, images, and report to a unique
`out/<profile>/<target>/<kind>/runs/<invocation>/` directory. The paths in a
build report refer to artifacts from that invocation, including when builds
overlap or the source branch changes between builds.
Run `python -m tools.studio.artifact_inventory > out/artifact-inventory.json`
for a read-only inventory. Each recognized build lists its target, profile,
kind, build ID, available content ID, artifact paths and sizes, and known plan
or receipt references. Recovery records list the existing files they reference.
The summary counts referenced files and unclassified files separately. Older
reports may lack a content ID; retain their build ID and report path to identify
them. The inventory does not delete, relocate, or classify unrecognized files
as safe to remove. Inspect any scan errors before relying on its counts.
Compilation uses two workers by default. Set `--jobs` to an integer from 1 to 4
to adjust its CPU and memory use; linking remains serial.
Unchanged objects are reused from the disposable, bounded `out/object-cache-v1/`
cache after source, included-header, generated-input, flags, and compiler checks.
Set `LINNET_OBJECT_CACHE=0` to compile every object for comparison. Whole-image
build IDs and per-invocation artifacts remain independent of object reuse.

Firmware backups, installation plans, predecessor files and recovery receipts
belong to the physical device and installation that produced them. Preserve them
together in a separate local backup before cleaning `out/`. Keep device serials,
hardware GUIDs, disk identities and personal media out of GitHub contributions.
The [target qualification record](../targets/README.md#qualification-record)
points to source-controlled evidence and open checks; retain exact physical
observations with their matching private device receipts.

Plans can reference absolute paths and pinned hashes. If an artifact archive is
relocated, restore the required files and dependencies to the paths expected by
the plan before using it. Do not edit hashes to accommodate relocation.

Inspect the connected device and its matching receipts before a firmware
operation; an old build report does not establish the current installed state.
See [Media Manager](media-manager.md) for installation and restoration, and
[Linnet Link](device-link.md) for low-level device operations.
