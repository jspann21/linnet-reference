# Bootstrap tooling

Use [Media Manager](media-manager.md) for supported installation. This map is for
contributors working on the lower-level boot paths.

| Stage | PortalPlayer targets | Classic S5L8702 |
| --- | --- | --- |
| Build | [Shared builder](../tools/studio/build.py) creates Boot/OS images. | Shared builder for ordinary images; [SRAM stage builder](../tools/studio/s5l_bootstrap.py) for initial bootstrap. |
| Inspect and plan | [Installer](../tools/studio/installer.py) assesses the disk; [native bootstrap](../tools/studio/native_bootstrap.py) derives a backup-bound firmware-directory plan. | [S5L bootstrap](../tools/link/s5l_bootstrap.py) captures the device/USB context; [NOR maintenance](../tools/link/classic_nor.py) uses its separate plan. |
| Transfer | [Link Session](../tools/link/session.py) handles ordinary uploads. [Native package](../tools/studio/native_package.py) builds the legacy reviewed maintenance package. | BootROM/DFU transfers the temporary monitor; ordinary OS updates then use Link. |
| Publish and recover | Candidate write and readback precede the directory change; restoration uses the saved original directory. | Persistent NOR work checks its own device, backup, and slot constraints. Automatic Media Manager installation is disabled. |

PortalPlayer directory planning exposes `plan`, `apply`, and `restore` through
`python -m tools.studio.native_bootstrap`. Classic entry uses
`python linnet device sram-bootstrap`. Inspect each command's `--help` before
preparing a plan. The older mounted-volume route is owned by
[bootstrap.py](../tools/studio/bootstrap.py).

These workflows are not interchangeable. Preserve the original firmware, plan,
predecessor files, hashes, and receipt together. A successful build or plan does
not establish the device's current state. See [local artifacts](local-artifacts.md)
and [Linnet Link](device-link.md) for recovery and mode transitions.
