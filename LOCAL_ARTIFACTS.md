# Local artifacts

`out/` is ignored scratch space for builds, simulator output and temporary reports.
Do not scan or load it wholesale for routine work. Keep durable documentation in
the source tree and retain only useful local outputs.

The previous output tree was moved intact on September 9, 2026 to:

`C:\Users\user\Desktop\Projects\linnet-artifacts\2026-09-09-doc-cleanup\out`

It contains firmware backups, pinned installation plans, images and historical
receipts. This is an archive, not a supported build input. Before reusing old
recovery tooling, restore the required files to their original `out/` paths,
including referenced dependencies; plans may contain absolute paths and hashes.
Do not edit hashes to accommodate relocation.

Last recorded device state (September 8; not re-inspected during doc cleanup):
B45 development OS in slot A, B33 fallback in slot B. The archive contains
`b45-install.json` and `b45-postinstall.json`. Inspect the connected device and
matching receipts before any firmware operation.
