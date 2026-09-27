# Bootstrap tooling map

The CLI in `tools/cli/main.py` is the public entry point. The modules below
separate image creation, device-bound planning, transport, and execution. A
module's directory describes its current location, not permission to skip the
identity or recovery checks in the next stage.

| Stage | Shared and PortalPlayer path | Classic S5L8702 path |
| --- | --- | --- |
| Build | `tools/studio/build.py` selects target sources, compiles Boot or OS, and writes an image report. | The same builder handles ordinary Classic images. `tools/studio/s5l_bootstrap.py` separately builds the temporary SRAM monitor and BootROM transfer stages for an observed Classic serial. |
| Inspect and plan | `tools/studio/installer.py` assesses a mounted iPod and chooses an installation method. `tools/studio/native_bootstrap.py` derives a directory Boot redirect from the original firmware, MBR, device identity, and matching Boot report; its `plan` writes a manifest and sibling recovery artifacts. | `tools/link/s5l_bootstrap.py` prepares a device and USB-location record from the mounted Classic. Classic NOR maintenance uses its own device-bound plan; the PortalPlayer directory plan is not interchangeable with it. |
| Package | `tools/studio/native_package.py` makes a fixed maintenance package from a reviewed, SHA-pinned directory Boot plan when the native update path is used. | `tools/link/s5l_bootstrap.py` pairs the built SRAM monitor with the prepared Classic identity before transfer. |
| Transfer | `tools/link/transport.py` and `tools/link/session.py` own serial discovery, handshakes, uploads, and verified responses. `tools/link/campaign.py` records device cycles and exact image identity. | `tools/link/s5l_bootstrap.py` handles the Classic BootROM/DFU entry and SRAM monitor transfer; ordinary Linnet Link transfers still use `transport.py` and `session.py`. |
| Execute and recover | `tools/studio/installer.py` coordinates installed-state checks and transactions. `tools/studio/native_bootstrap.py` revalidates the plan and exact disk, writes the candidate before the directory, verifies readback, and restores the original directory when requested. `tools/studio/native_update.py` handles the separate native-volume publication path. | The Classic link and target maintenance modules verify the pinned specimen and NOR state before persistent work. `tools/studio/installer.py` keeps unsupported automatic methods disabled. |

The PortalPlayer directory procedure is exposed by
`python -m tools.studio.native_bootstrap` with `plan`, `apply`, and `restore`.
The fixed maintenance package builder is
`python -m tools.studio.native_package --plan <plan> --plan-sha256 <hash> --output <path>`.
The Classic SRAM procedure is exposed by `python linnet device sram-bootstrap`
with its own build, prepare, transfer, diagnostic, and maintenance actions.
`python linnet device bootstrap` and `bootstrap-status` use
`tools/studio/bootstrap.py` for the older mounted-volume entry path. Keep these
command and import routes working if files are reorganized.

Plans, original firmware, predecessor files, receipts, and package hashes are
device-specific. Preserve their paths and matching artifacts as described in
[local artifacts](local-artifacts.md). The [device procedure](device-link.md)
lists the live Link and Disk Mode checks; a successful host build or plan does
not establish the connected device's current state.
