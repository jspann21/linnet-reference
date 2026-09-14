"""Non-wiping Linnet installer orchestration for mounted Windows iPods.

The ordinary process identifies the target and builds exact artifacts. Native
firmware access is isolated in an elevated worker whose inputs and receipts are
persisted under LocalAppData. Existing media is never enumerated for deletion,
formatted, repartitioned, or overwritten by this module.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

from tools.inspect.image import inspect as inspect_image
from tools.studio.targets import ROOT, TARGETS


CORE_FILES = ("OS0.LOS", "OS1.LOS", "STATE0.BIN", "STATE1.BIN",
              "SCRATCH.BIN", "BOOT0.BIN", "BOOT1.BIN")
JOURNAL = Path("LINNET/RECOVERY/INSTALL.JSON")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _save(path, value, *, replace=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace:
        with path.open("x", encoding="utf-8", newline="\n") as writer:
            json.dump(value, writer, indent=2, sort_keys=True)
            writer.write("\n")
            writer.flush()
            os.fsync(writer.fileno())
        return
    temporary = path.with_suffix(path.suffix + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8", newline="\n") as writer:
        json.dump(value, writer, indent=2, sort_keys=True)
        writer.write("\n")
        writer.flush()
        os.fsync(writer.fileno())
    temporary.replace(path)


def cache_root(identity):
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    serial = re.sub(r"[^A-Za-z0-9-]", "_", identity["disk_serial"])
    return base / "Linnet" / "Installer" / f"{identity['target_id']}-{serial}"


def identity_for_mount(mount):
    from tools.content.media_manager import discover
    wanted = Path(mount).resolve(strict=True)
    matches = [item for item in discover() if Path(item["root"]).resolve() == wanted]
    if len(matches) != 1:
        raise ValueError("the selected mount does not resolve to exactly one supported iPod")
    return matches[0]


def _wrapper(path, install_spec):
    if not path.is_file() or path.is_symlink() or path.stat().st_size < 40:
        return None
    try:
        from tools.studio.bootstrap import ipod_payload
        _payload, model = ipod_payload(path.read_bytes(), install_spec["wrapper_model"].encode("ascii"),
                                       install_spec["wrapper_checksum_seed"])
        return model.decode("ascii")
    except (ValueError, OSError, UnicodeDecodeError):
        return None


BUILD_LABELS = {"release": "User build", "dev": "Developer build", "trace": "Developer trace build"}


def build_description(state):
    if state.get("state") == "installed":
        label = BUILD_LABELS.get(state.get("profile"), "Unknown build")
        pending = " · candidate pending" if state.get("candidate_pending") else ""
        return f"{label} · {state['build_id'][:12]}{pending}"
    return {"absent": "Not installed", "incomplete": "Incomplete installation",
            "invalid": "Installation needs attention"}.get(state.get("state"), "Unknown installation")


def installed_state(root, target_id):
    root = Path(root)
    capacity = TARGETS[target_id]["os_capacity_bytes"]
    directory = root / "LINNET"
    present = [name for name in CORE_FILES if (directory / name).exists()]
    if not present:
        return dict(state="absent", present=0, required=len(CORE_FILES))
    if len(present) != len(CORE_FILES):
        return dict(state="incomplete", present=len(present), required=len(CORE_FILES),
                    detail="An interrupted Linnet file transaction is present and can only be resumed with the same build.")
    try:
        from tools.studio.update_history import _boot_record
        records = [_boot_record(directory / name, capacity) for name in ("BOOT0.BIN", "BOOT1.BIN")]
        if records[0][1] == records[1][1] and records[0][0] != records[1][0]:
            raise ValueError("conflicting boot records at the same generation")
        selected = max(records, key=lambda item: item[1])
        build_id = selected[2]
        confirmed_slot = selected[0][52]
        metadata_offset = 68 + confirmed_slot * 72
        expected_length, expected_profile = struct.unpack_from("<II", selected[0], metadata_offset)
        expected_sha = selected[0][metadata_offset + 40:metadata_offset + 72].hex()
        images = []
        for slot, name in enumerate(("OS0.LOS", "OS1.LOS")):
            path = directory / name
            with path.open("rb") as reader:
                header = reader.read(128)
                if not any(header):
                    continue
                length = struct.unpack_from("<I", header, 20)[0]
                if not 4 <= length <= capacity - 128:
                    raise ValueError("invalid installed image length")
                image = header + reader.read(length)
            identity = inspect_image(image)
            if identity["target_id"] != target_id:
                raise ValueError("installed Linnet image targets a different device")
            identity["slot"] = slot
            images.append(identity)
        confirmed = next((item for item in images if item["slot"] == confirmed_slot), None)
        if confirmed is None:
            raise ValueError("confirmed Linnet image is missing")
        if (confirmed["build_id"] != build_id or confirmed["payload_bytes"] + 128 != expected_length or
                ("release", "dev", "trace").index(confirmed["profile"]) != expected_profile or
                confirmed["sha256"] != expected_sha):
            raise ValueError("confirmed image differs from boot metadata")
        return dict(state="installed", present=len(present), required=len(CORE_FILES),
                    build_id=build_id, profile=confirmed["profile"], build="user" if confirmed["profile"] == "release" else "dev", images=images,
                    candidate_pending=bool(selected[3]))
    except (ValueError, OSError, KeyError, struct.error) as error:
        return dict(state="invalid", present=len(present), required=len(CORE_FILES), detail=str(error))


def _resume_context(identity, linnet):
    if linnet["state"] not in ("incomplete", "installed"):
        return None
    transactions = cache_root(identity) / "transactions"
    if not transactions.is_dir():
        return None
    root = Path(identity["root"])
    for transaction in sorted(transactions.iterdir(), reverse=True):
        context_path = transaction / "context.json"
        package = transaction / "storage"
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
            if (context.get("target_id") != identity["target_id"] or
                    context.get("device_id") != identity["disk_serial"] or
                    context.get("strategy") not in ("rockbox-file", "native-directory") or
                    context.get("build") not in ("user", "dev")):
                continue
            artifacts = context["artifacts"]
            if artifacts.get("build") != context["build"]:
                continue
            if any(not Path(artifacts[name]).is_file() for name in ("os_image", "boot_image", "boot_wrapper")):
                continue
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("image", {}).get("build_id") != artifacts["os_build_id"]:
                continue
            matches = True
            for name in CORE_FILES:
                installed, expected = root / "LINNET" / name, package / name
                if installed.exists() and (installed.is_symlink() or installed.read_bytes() != expected.read_bytes()):
                    matches = False
                    break
            if not matches:
                if linnet["state"] == "incomplete":
                    raise ValueError("partial Linnet files differ from the saved install transaction")
                continue
            return dict(context, transaction=str(transaction))
        except (KeyError, OSError, json.JSONDecodeError):
            continue
    return None


def assess(identity):
    """Inspect a mounted device without changing it."""
    from tools.content.media_manager import refresh
    identity = refresh(identity)
    root = Path(identity["root"]).resolve(strict=True)
    target_id = identity["target_id"]
    spec = TARGETS[target_id]
    install_spec = spec["installer"]
    expected_model = install_spec["wrapper_model"]
    linnet = installed_state(root, target_id)
    resume = None
    rockbox_file = root.joinpath(*install_spec["file_loader"].split("/"))
    wrapper = _wrapper(rockbox_file, install_spec)
    rockbox = dict(present=(root / ".rockbox").is_dir(), boot_file=str(rockbox_file),
                   boot_file_present=rockbox_file.is_file(), model_code=wrapper,
                   compatible=wrapper == expected_model)
    marker = None
    marker_path = root / JOURNAL
    if marker_path.is_file() and not marker_path.is_symlink() and marker_path.stat().st_size <= 65536:
        try:
            value = json.loads(marker_path.read_text(encoding="utf-8"))
            if (value.get("target_id") == target_id and
                    value.get("device_id") == identity["disk_serial"] and
                    value.get("strategy") in ("rockbox-file", "native-directory") and
                    value.get("phase") in ("installed", "restored")):
                marker = value
        except (ValueError, OSError):
            marker = None
    if marker is None and linnet["state"] != "absent":
        bootstrap_path = root / "LINNET" / "RECOVERY" / "BOOTSTRAP.JSON"
        if bootstrap_path.is_file() and not bootstrap_path.is_symlink():
            try:
                from tools.studio.bootstrap import status as bootstrap_status
                bootstrap = bootstrap_status(root)
                phase = bootstrap.get("phase")
                active = bootstrap.get("candidate_sha256") if phase == "installed" else bootstrap.get("original_sha256")
                if (bootstrap.get("target_id") == target_id and phase in ("installed", "restored") and
                        bootstrap.get("active_sha256") == active and bootstrap.get("backup_valid")):
                    marker = dict(target_id=target_id, device_id=identity["disk_serial"],
                                  strategy="rockbox-file", phase=phase, recovered_from="BOOTSTRAP.JSON")
            except (ValueError, OSError):
                pass
    if marker is None or marker.get("phase") == "restored":
        resume = _resume_context(identity, linnet)
    others = []
    for name, paths in (("iPodLinux", ("iPodLinux", "linux.bin", "loader2")),
                        ("Podzilla", ("podzilla", ".podzilla"))):
        if any((root / value).exists() for value in paths):
            others.append(name)
    if rockbox["present"]:
        others.insert(0, "Rockbox")
    if linnet["state"] != "absent" and marker:
        action, strategy = "replace", marker["strategy"]
        if linnet["state"] == "installed":
            summary = f"{build_description(linnet)} is installed. Switch builds or reinstall, including the same version."
        else:
            summary = "The existing Linnet files use another layout and can be preserved before a fresh install."
    elif resume:
        action, strategy = "resume", resume["strategy"]
        summary = "A matching interrupted Linnet installation is ready to resume."
    elif linnet["state"] == "installed":
        action, strategy = "installed", "existing"
        summary = f"{build_description(linnet)} is installed, but no installer recovery record is available."
    elif linnet["state"] in ("incomplete", "invalid"):
        action, strategy = "attention", None
        summary = linnet.get("detail", "The existing Linnet installation needs inspection.")
    elif not install_spec["enabled"]:
        action, strategy = "unsupported", None
        summary = "This target is recognized, but installation is not enabled for it."
    elif rockbox["compatible"]:
        action, strategy = "install", "rockbox-file"
        summary = "Ready to install through the existing Rockbox file loader."
    else:
        action, strategy = "install", "native-directory"
        summary = "Ready for a native, reversible installation with an original firmware backup."
    return dict(checked_at=_now(), identity=identity,
                target=dict(id=target_id, name=spec["name"],
                            installer_enabled=install_spec["enabled"], boot_layout=install_spec["boot_layout"],
                            wrapper_model=expected_model),
                retail_os=True, linnet=linnet, rockbox=rockbox, other_installations=others,
                recovery=marker, resume=resume, action=action, strategy=strategy, summary=summary,
                preservation=dict(formats_disk=False, repartitions_disk=False, deletes_media=False,
                                  overwrites_existing_linnet_files=False, archives_previous_linnet=True,
                                  original_boot_backed_up=True))


def _run_build(arguments):
    command = [sys.executable, str(ROOT / "linnet"), "build", *arguments]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Linnet build failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Linnet build returned an unreadable report") from error


def build_artifacts(identity, progress=lambda _message: None, build="user"):
    if build not in ("user", "dev"):
        raise ValueError("installer build must be user or dev")
    target, serial = identity["target_id"], identity["linnet_usb_serial"]
    os_profile = "release" if build == "user" else "dev"
    progress(f"Building the Linnet {build} OS for {TARGETS[target]['name']}…")
    os_arguments = ["--target", target, "--profile", os_profile,
                    "--kind", "os", "--verify"]
    if os_profile == "dev":
        os_arguments += ["--device-serial", serial]
    os_report = _run_build(os_arguments)
    progress("Building the recoverable device loader…")
    boot_arguments = ["--target", target, "--profile", os_profile,
                      "--kind", "boot", "--verify"]
    if os_profile == "dev":
        boot_arguments += ["--device-serial", serial]
    boot_report = _run_build(boot_arguments)
    def artifact(report, name):
        path = ROOT / report["artifacts"][name]
        return path.resolve(strict=True)
    os_image, boot_image = artifact(os_report, "los"), artifact(boot_report, "los")
    boot_wrapper = artifact(boot_report, "ipod")
    artifacts = dict(os_image=str(os_image), os_report=str(os_image.with_suffix(".json")),
                     boot_image=str(boot_image), boot_wrapper=str(boot_wrapper),
                     boot_report=str(boot_image.with_suffix(".json")),
                     build=build, os_profile=os_profile, os_build_id=os_report["build_id"],
                     boot_build_id=boot_report["build_id"])
    _validate_artifacts(identity, artifacts)
    return artifacts


def _validate_artifacts(identity, artifacts):
    spec = TARGETS[identity["target_id"]]
    install_spec = spec["installer"]
    paths = {key: Path(artifacts[key]).resolve(strict=True) for key in
             ("os_image", "os_report", "boot_image", "boot_wrapper", "boot_report")}
    os_data, boot_data = paths["os_image"].read_bytes(), paths["boot_image"].read_bytes()
    os_identity, boot_identity = inspect_image(os_data), inspect_image(boot_data)
    if len(os_data) > spec["os_capacity_bytes"] or len(boot_data) > spec["os_capacity_bytes"]:
        raise ValueError("installer image exceeds the target OS capacity")
    build = artifacts.get("build")
    expected_profile = "release" if build == "user" else "dev" if build == "dev" else None
    if expected_profile is None or expected_profile != artifacts.get("os_profile"):
        raise ValueError("installer artifact build selection is invalid")
    if ((os_identity["target_id"], os_identity["profile"], os_identity["build_id"]) !=
            (identity["target_id"], expected_profile, artifacts["os_build_id"]) or
            (boot_identity["target_id"], boot_identity["profile"], boot_identity["build_id"]) !=
            (identity["target_id"], expected_profile, artifacts["boot_build_id"])):
        raise ValueError("installer image identity does not match the detected iPod")
    from tools.studio.bootstrap import ipod_payload
    wrapped, _model = ipod_payload(paths["boot_wrapper"].read_bytes(),
                                   install_spec["wrapper_model"].encode("ascii"),
                                   install_spec["wrapper_checksum_seed"])
    if wrapped != boot_data[128:]:
        raise ValueError("installer Boot wrapper differs from its validated image")
    for kind, report_path, image_identity in (("os", paths["os_report"], os_identity),
                                               ("boot", paths["boot_report"], boot_identity)):
        if report_path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("installer build report exceeds its bound")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        expected_serial = "" if build == "user" else identity["linnet_usb_serial"]
        if (report.get("kind") != kind or report.get("profile") != expected_profile or
                report.get("target_id") != identity["target_id"] or
                report.get("device_serial") != expected_serial or
                report.get("build_id") != image_identity["build_id"] or
                report.get("image", {}).get("sha256") != image_identity["sha256"]):
            raise ValueError("installer build report does not match its image")
        if build == "user" and (report.get("release_exclusion") or {}).get("passed") is not True:
            raise ValueError("user installer artifacts require release exclusion verification")


def _same_device(expected, observed):
    def values(item):
        return (item["target_id"], item["disk_number"], item["disk_serial"], item["disk_bytes"],
                item["partition_offset"], item["partition_bytes"], item["linnet_usb_serial"])
    if values(expected) != values(observed):
        raise RuntimeError("iPod identity changed after installation review")


def _transaction(identity, artifacts):
    return cache_root(identity) / "transactions" / f"{artifacts['build']}-{artifacts['os_build_id'][:16]}-{uuid.uuid4().hex}"


def _persist_artifacts(artifacts, transaction):
    destination = transaction / "artifacts"
    destination.mkdir(parents=True, exist_ok=True)
    names = {"os_image": "operating-system.los", "os_report": "operating-system.json",
             "boot_image": "boot.los", "boot_wrapper": "boot.ipod",
             "boot_report": "boot.json"}
    persisted = dict(artifacts)
    for key, name in names.items():
        source, target = Path(artifacts[key]).resolve(strict=True), destination / name
        data = source.read_bytes()
        if target.exists():
            if target.is_symlink() or target.read_bytes() != data:
                raise ValueError("saved installer artifact differs: " + name)
        else:
            with target.open("xb") as writer:
                writer.write(data)
                writer.flush()
                os.fsync(writer.fileno())
            if target.read_bytes() != data:
                raise OSError("saved installer artifact failed verification: " + name)
        persisted[key] = str(target.resolve())
    return persisted


def _package_storage(identity, artifacts, transaction):
    from tools.studio import storage
    package = transaction / "storage"
    if package.exists():
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("image", {}).get("build_id") != artifacts["os_build_id"]:
            raise ValueError("saved storage transaction belongs to another build")
    else:
        storage.prepare(Path(artifacts["os_image"]), package)
    return storage.provision(package, Path(identity["root"]), identity["disk_serial"])


def _journal(identity, artifacts, strategy, transaction, extra=None):
    value = dict(target_id=identity["target_id"], device_id=identity["disk_serial"],
                 linnet_usb_serial=identity["linnet_usb_serial"], strategy=strategy,
                 build=artifacts["build"],
                 os_build_id=artifacts["os_build_id"], boot_build_id=artifacts["boot_build_id"],
                 transaction=str(transaction), installed_at=_now(), phase="installed")
    if extra:
        value.update(extra)
    root = Path(identity["root"]).resolve(strict=True)
    path = root / JOURNAL
    from tools.content.publish import _plain
    _plain(path, root)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        stable = (set(existing) | set(value)) - {"phase", "installed_at", "restored_at"}
        if any(existing.get(key) != value.get(key) for key in stable) or existing.get("phase") != "restored":
            raise ValueError("an installation recovery journal already exists")
        _save(path, value)
    else:
        _save(path, value, replace=False)
    return value


def _install_rockbox(identity, artifacts, progress, transaction):
    from tools.studio import bootstrap
    transaction.mkdir(parents=True, exist_ok=True)
    progress("Preparing Linnet’s transactional storage files…")
    storage_receipt = _package_storage(identity, artifacts, transaction)
    boot_path = Path(identity["root"]).joinpath(*TARGETS[identity["target_id"]]["installer"]["file_loader"].split("/"))
    bootstrap_journal = Path(identity["root"]) / "LINNET" / "RECOVERY" / "BOOTSTRAP.JSON"
    original_sha = (json.loads(bootstrap_journal.read_text(encoding="utf-8"))["original_sha256"]
                    if bootstrap_journal.is_file() else _sha(boot_path.read_bytes()))
    progress("Backing up the Rockbox loader and installing Linnet’s loader…")
    boot_receipt = bootstrap.install(Path(identity["root"]), Path(artifacts["boot_wrapper"]),
                                     Path(artifacts["boot_image"]), original_sha)
    marker = _journal(identity, artifacts, "rockbox-file", transaction,
                      dict(original_boot_sha256=original_sha))
    return dict(passed=True, strategy="rockbox-file", storage=storage_receipt,
                boot=boot_receipt, recovery=marker, requires_safe_eject=True)


def _encode(value):
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _run_elevated(job_path):
    if os.name != "nt":
        raise RuntimeError("native installation currently requires Windows")
    python, job, working = map(_encode, (sys.executable, job_path, ROOT))
    ps = f"""
$ErrorActionPreference='Stop'
function D([string]$s) {{ [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s)) }}
$p=Start-Process -FilePath (D '{python}') -ArgumentList @('-m','tools.studio.installer','--worker-token','{job}') -WorkingDirectory (D '{working}') -Verb RunAs -WindowStyle Hidden -Wait -PassThru
exit $p.ExitCode
"""
    encoded = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True)
    job_value = json.loads(job_path.read_text(encoding="utf-8"))
    response_path = Path(job_value["result"])
    if not response_path.is_file():
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or "administrator approval was cancelled or the installer worker did not finish")
    response = json.loads(response_path.read_text(encoding="utf-8"))
    if not response.get("passed"):
        raise RuntimeError(response.get("failure", "native installation failed; inspect its receipt"))
    return response


def _archive_destination(root):
    """Choose a FAT-safe sibling name without changing the mounted volume."""
    from tools.content.publish import _plain
    root = Path(root).resolve(strict=True)
    source = root / "LINNET"
    _plain(source, root)
    if not source.is_dir() or source.is_symlink():
        raise ValueError("the existing LINNET directory is unsafe or missing")
    for index in range(10):
        candidate = root / f"LNETOLD{index}"
        _plain(candidate, root)
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ValueError("LNETOLD0 through LNETOLD9 already exist; move one off the iPod before reinstalling")


def _archive_linnet(root, destination):
    from tools.content.publish import _plain
    root, destination = Path(root).resolve(strict=True), Path(destination)
    source = root / "LINNET"
    _plain(source, root)
    _plain(destination, root)
    if destination.parent != root or destination.exists() or destination.is_symlink():
        raise ValueError("the selected Linnet archive destination is no longer available")
    source.replace(destination)
    if source.exists() or not destination.is_dir():
        raise OSError("the previous Linnet folder was not archived completely")
    return str(destination)


def install(identity, progress=lambda _message: None, build="user"):
    if build not in ("user", "dev"):
        raise ValueError("installer build must be user or dev")
    reviewed = assess(identity)
    if reviewed["action"] not in ("install", "resume", "replace"):
        raise ValueError(reviewed["summary"])
    identity = reviewed["identity"]
    archive = _archive_destination(identity["root"]) if reviewed["action"] == "replace" else None
    if reviewed["action"] == "resume":
        progress("Verifying the saved interrupted installation…")
        artifacts = reviewed["resume"]["artifacts"]
        if reviewed["resume"].get("build") != build or artifacts.get("build") != build:
            raise ValueError("resume must use the build selected by the saved installation")
        transaction = Path(reviewed["resume"]["transaction"])
        _validate_artifacts(identity, artifacts)
    else:
        artifacts = build_artifacts(identity, progress=progress, build=build)
        transaction = _transaction(identity, artifacts)
    transaction.mkdir(parents=True, exist_ok=True)
    if reviewed["action"] != "resume":
        artifacts = _persist_artifacts(artifacts, transaction)
        _validate_artifacts(identity, artifacts)
    context = dict(target_id=identity["target_id"], device_id=identity["disk_serial"],
                   strategy=reviewed["strategy"], build=build, artifacts=artifacts)
    context_path = transaction / "context.json"
    if context_path.exists():
        if json.loads(context_path.read_text(encoding="utf-8")) != context:
            raise ValueError("saved install context differs from this transaction")
    else:
        _save(context_path, context, replace=False)
    receipt_path = transaction / ("install-" + uuid.uuid4().hex + ".json")
    receipt = dict(operation="install-linnet", started_at=_now(), passed=False,
                   strategy=reviewed["strategy"], build=build,
                   identity=identity, artifacts=artifacts,
                   preservation=reviewed["preservation"], device_write_attempted=False)
    _save(receipt_path, receipt)
    try:
        current = assess(identity)
        if current["action"] != reviewed["action"] or current["strategy"] != reviewed["strategy"]:
            raise RuntimeError("installation state changed after review")
        if reviewed["action"] == "replace":
            receipt["device_write_attempted"] = True
            receipt["phase"] = "restore-before-reinstall"
            _save(receipt_path, receipt)
            progress("Restoring and verifying the previous boot before the fresh install…")
            receipt["restored_boot"] = restore(identity)
            progress("Preserving the previous Linnet folder before the fresh install…")
            receipt["previous_linnet_archive"] = _archive_linnet(identity["root"], archive)
            _save(receipt_path, receipt)
            current = assess(identity)
            if current["action"] != "install" or current["strategy"] != reviewed["strategy"]:
                raise RuntimeError("fresh installation state differs after preserving the previous Linnet folder")
        receipt["device_write_attempted"] = True
        receipt["phase"] = "device-transaction"
        _save(receipt_path, receipt)
        if reviewed["strategy"] == "rockbox-file":
            result = _install_rockbox(identity, artifacts, progress, transaction)
        else:
            progress("Requesting administrator access to back up and update the iPod boot partition…")
            job = dict(mode="install", identity=identity, artifacts=artifacts,
                       transaction=str(transaction), result=str(receipt_path.with_suffix(".result.json")))
            job_path = transaction / ("worker-" + uuid.uuid4().hex + ".json")
            _save(job_path, job, replace=False)
            result = _run_elevated(job_path)
        receipt.update(passed=True, result=result, phase="complete")
    except BaseException as error:
        receipt.update(failure=f"{type(error).__name__}: {error}", phase="failed")
        raise
    finally:
        receipt["finished_at"] = _now()
        receipt["receipt"] = str(receipt_path)
        _save(receipt_path, receipt)
    return receipt


def _read_raw_backup(identity, transaction):
    from tools.studio.native_bootstrap import SECTOR
    install_spec = TARGETS[identity["target_id"]]["installer"]
    if not install_spec["enabled"] or install_spec["boot_layout"] != "ipod-directory":
        raise ValueError("the detected target does not enable native directory installation")
    backup = transaction / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    disk_number = identity["disk_number"]
    path = r"\\.\PhysicalDrive" + str(disk_number)
    with open(path, "rb", buffering=0) as device:
        mbr = device.read(SECTOR)
        if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
            raise ValueError("the iPod MBR is invalid")
        partitions = []
        for index in range(4):
            offset = 446 + index * 16
            kind = mbr[offset + 4]
            lba, sectors = struct.unpack_from("<II", mbr, offset + 8)
            if sectors:
                partitions.append((kind, lba, sectors))
        firmware = [item for item in partitions if item[0] in install_spec["firmware_partition_types"]]
        media = [item for item in partitions if item[0] in install_spec["media_partition_types"]]
        if len(firmware) != 1 or len(media) != 1:
            raise ValueError("expected one firmware partition and one media partition")
        _kind, firmware_lba, firmware_sectors = firmware[0]
        if (media[0][1] * SECTOR, media[0][2] * SECTOR) != (identity["partition_offset"], identity["partition_bytes"]):
            raise ValueError("raw and mounted partition geometry disagree")
        firmware_bytes = firmware_sectors * SECTOR
        if not SECTOR <= firmware_bytes <= min(install_spec["max_firmware_bytes"], identity["disk_bytes"]):
            raise ValueError("firmware partition exceeds the installer bound")
        device.seek(firmware_lba * SECTOR)
        firmware_data = device.read(firmware_bytes)
        if len(firmware_data) != firmware_bytes:
            raise OSError("short firmware backup read")
    for name, data in (("mbr.bin", mbr), ("firmware.bin", firmware_data)):
        target = backup / name
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("saved original backup differs from the connected iPod")
        else:
            with target.open("xb") as writer:
                writer.write(data)
                writer.flush()
                os.fsync(writer.fileno())
            if target.read_bytes() != data:
                raise OSError("saved firmware backup failed verification")
    return backup / "mbr.bin", backup / "firmware.bin"


def _native_worker(job):
    from tools.inspect.retail_device import detect
    from tools.studio import native_bootstrap as native
    transaction = Path(job["transaction"]).resolve()
    expected = job["identity"]
    detected = detect(expected["root"])
    observed = dict(target_id=detected["target_id"], disk_number=detected["storage"]["disk_number"],
                    disk_serial=detected["storage"]["disk_serial"], disk_bytes=detected["storage"]["disk_bytes"],
                    partition_offset=detected["storage"]["partition_offset"],
                    partition_bytes=detected["storage"]["partition_bytes"],
                    linnet_usb_serial=detected["linnet_usb_serial"])
    _same_device(expected, observed)
    if job["mode"] == "restore":
        result = native.execute("restore", Path(job["plan"]), job["plan_sha256"], expected["disk_number"])
        if not result.get("passed"):
            raise RuntimeError(result.get("failure", "native restore failed"))
        return result
    mbr, firmware = _read_raw_backup(expected, transaction)
    device_path = transaction / "device.json"
    device_value = detected
    if device_path.exists():
        if json.loads(device_path.read_text(encoding="utf-8")) != device_value:
            raise ValueError("saved device identity differs")
    else:
        _save(device_path, device_value, replace=False)
    plan_dir = transaction / "native-plan"
    hash_path = transaction / "native-plan.sha256"
    if plan_dir.exists():
        plan_path = plan_dir / "plan.json"
        plan_sha = hash_path.read_text(encoding="ascii").strip()
        native.load_plan(plan_path, plan_sha)
    else:
        planned = native.plan(firmware, mbr, device_path, Path(job["artifacts"]["boot_image"]), plan_dir)
        plan_path, plan_sha = Path(planned["plan"]), planned["plan_sha256"]
        hash_path.write_text(plan_sha + "\n", encoding="ascii")
    storage_receipt = _package_storage(expected, job["artifacts"], transaction)
    applied = native.execute("apply", plan_path, plan_sha, expected["disk_number"])
    if not applied.get("passed"):
        raise RuntimeError(applied.get("failure", "native boot publication failed"))
    marker = _journal(expected, job["artifacts"], "native-directory", transaction,
                      dict(plan=str(plan_path), plan_sha256=plan_sha,
                           firmware_backup_sha256=_sha(firmware.read_bytes())))
    return dict(passed=True, strategy="native-directory", storage=storage_receipt,
                boot=applied, recovery=marker, requires_safe_eject=True)


def restore(identity):
    reviewed = assess(identity)
    marker = reviewed.get("recovery")
    if not marker or marker.get("phase") not in ("installed", "restored"):
        raise ValueError("no Linnet installation with a verified recovery journal was found")
    if marker["strategy"] == "rockbox-file":
        from tools.studio.bootstrap import restore as restore_file
        result = restore_file(Path(reviewed["identity"]["root"]))
    elif marker["strategy"] == "native-directory":
        transaction = Path(marker["transaction"]).resolve(strict=True)
        result_path = transaction / ("restore-" + uuid.uuid4().hex + ".result.json")
        job = dict(mode="restore", identity=reviewed["identity"],
                   transaction=str(transaction), plan=marker["plan"], plan_sha256=marker["plan_sha256"],
                   result=str(result_path))
        job_path = transaction / ("restore-worker-" + uuid.uuid4().hex + ".json")
        _save(job_path, job, replace=False)
        result = _run_elevated(job_path)
    else:
        raise ValueError("unsupported recovery strategy")
    marker = dict(marker, phase="restored", restored_at=_now())
    _save(Path(reviewed["identity"]["root"]) / JOURNAL, marker)
    return dict(passed=True, boot=result, media_preserved=True, linnet_files_preserved=True,
                requires_safe_eject=True)


def worker(job_path):
    job_path = Path(job_path).resolve(strict=True)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    result_path = Path(job["result"]).resolve()
    response = dict(passed=False, operation=job.get("mode"), started_at=_now())
    try:
        if job.get("mode") not in ("install", "restore"):
            raise ValueError("unsupported installer worker job")
        response.update(_native_worker(job))
    except BaseException as error:
        response["failure"] = f"{type(error).__name__}: {error}"
    response["finished_at"] = _now()
    _save(result_path, response)
    return response


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--worker", type=Path)
    cli.add_argument("--worker-token")
    commands = cli.add_subparsers(dest="command")
    for name in ("inspect", "install", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--mount", type=Path, required=True)
        if name == "install":
            command.add_argument("--build", choices=("user", "dev"), default="user")
    args = cli.parse_args()
    if args.worker or args.worker_token:
        worker_path = args.worker or Path(base64.b64decode(args.worker_token).decode("utf-8"))
        result = worker(worker_path)
    else:
        if not args.command:
            cli.error("choose inspect, install, or restore")
        identity = identity_for_mount(args.mount)
        result = (assess(identity) if args.command == "inspect" else
                  install(identity, progress=print, build=args.build)
                  if args.command == "install" else restore(identity))
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
