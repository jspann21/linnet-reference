"""Plan an exact P98 OSOS directory redirect; raw writes require apply/restore.

This utility supports only the inspected device/layout described below. It never
writes a complete firmware partition or modifies the existing native payload.
Planning uses backup files only. Apply/restore are explicit Windows operations
and require the SHA-256 of the reviewed plan as a separate command argument.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.inspect.image import inspect

SECTOR = 512
PARTITION_LBA = 63
PARTITION_SECTORS = 80262
DEVICE_BYTES = 64021856256
STORAGE_SERIAL = "JQ5081G3SAY"
LINK_SERIAL = "000000F7A765"
DIRECTORY_OFFSET = 0x4200
BACKUP_SHA256 = "6da0350100a9d6946a4d716c84fdb2ad7f67475cc254d4dae8b3da8fb75832f7"
ORIGINAL_OSOS_SHA256 = "0e21c2bc8cbabdeed6e3d6a034eacc8e3ca7d6fb04cd2d5d1b4cfc5fd85d9611"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(size):
    return (size + SECTOR - 1) // SECTOR * SECTOR


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_backup(firmware, mbr):
    if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
        raise ValueError("invalid 512-byte MBR backup")
    partition = mbr[446:462]
    lba, sectors = struct.unpack_from("<II", partition, 8)
    if (partition[4], lba, sectors) != (0, PARTITION_LBA, PARTITION_SECTORS):
        raise ValueError("MBR does not match the inspected firmware partition")
    if len(firmware) != PARTITION_SECTORS * SECTOR or sha(firmware) != BACKUP_SHA256:
        raise ValueError("firmware backup is not the exact inspected original")
    if firmware[0x100:0x104] != b"]ih[" or struct.unpack_from("<H", firmware, 0x10a)[0] != 3:
        raise ValueError("unsupported Apple firmware header/version")
    if struct.unpack_from("<I", firmware, 0x104)[0] + SECTOR != DIRECTORY_OFFSET:
        raise ValueError("unexpected firmware-directory location")
    directory = firmware[DIRECTORY_OFFSET:DIRECTORY_OFFSET + SECTOR]
    entries = []
    # This inspected directory has two images, followed by an empty entry.
    # Each devOffset is relative to one sector into the firmware partition.
    for offset in range(0, SECTOR - 39, 40):
        entry = directory[offset:offset + 40]
        if entry[:4] == bytes(4):
            break
        if entry[:4] != b"!ATA":
            raise ValueError("unknown firmware-directory entry")
        kind = entry[4:8]
        ident, dev_offset, size, address, start, checksum, version, load = struct.unpack_from("<8I", entry, 8)
        payload_offset = dev_offset + SECTOR
        if not size or payload_offset < DIRECTORY_OFFSET + SECTOR or payload_offset + size > len(firmware):
            raise ValueError("firmware image extent is out of bounds")
        entries.append(dict(directory_entry_offset=offset, type=kind.decode("ascii"), id=ident,
                            dev_offset=dev_offset, payload_offset=payload_offset, payload_bytes=size,
                            address=address, entry_offset=start, checksum=checksum,
                            version=version, load_address=load,
                            payload_sha256=sha(firmware[payload_offset:payload_offset + size])))
    osos = [entry for entry in entries if entry["type"] == "soso"]
    if len(osos) != 1:
        raise ValueError("expected exactly one original OSOS entry")
    original = osos[0]
    if (original["dev_offset"], original["payload_bytes"], original["entry_offset"],
        original["payload_sha256"]) != (20971008, 1549256, 0, ORIGINAL_OSOS_SHA256):
        raise ValueError("original OSOS payload identity differs from inspection")
    old_payload = firmware[original["payload_offset"]:original["payload_offset"] + original["payload_bytes"]]
    if sum(old_payload) & 0xffffffff != original["checksum"]:
        raise ValueError("original OSOS additive checksum mismatch")
    return entries, original, directory


def derive(firmware, mbr, image, predecessors=()):
    entries, original, directory = parse_backup(firmware, mbr)
    identity = inspect(image)
    payload = image[128:]
    if identity["profile"] not in ("dev", "trace") or identity["load_address"] != 0 or identity["entry_address"] != 0:
        raise ValueError("bootstrap requires a development image loaded and entered at zero")
    if not 32 <= len(payload) <= 0x100000:
        raise ValueError("native Boot payload must fit its 1 MiB snapshot region")
    span = max(65536, align(len(payload)))
    first = align(max(entry["payload_offset"] + entry["payload_bytes"] for entry in entries))
    # Never overwrite bytes still referenced by a predecessor directory. Each
    # upgrade stages after all pinned predecessor extents before publication.
    for previous, _artifacts in predecessors:
        first = max(first, align(previous["candidate_partition_offset"] + previous["candidate_write_bytes"]))
    stage = None
    for offset in range(first, len(firmware) - span + 1, SECTOR):
        if not any(firmware[offset:offset + span]):
            stage = offset
            break
    if stage is None:
        raise ValueError("no sufficiently large all-zero region after every referenced image")
    candidate = payload + bytes(span - len(payload))
    patched = bytearray(directory)
    entry_offset = original["directory_entry_offset"]
    for field, value in ((12, stage - SECTOR), (16, len(payload)), (24, 0), (28, sum(payload) & 0xffffffff)):
        struct.pack_into("<I", patched, entry_offset + field, value)
    details = dict(image=identity, original_entries=entries, original_osos=original,
                   directory_partition_offset=DIRECTORY_OFFSET,
                   directory_disk_offset=PARTITION_LBA * SECTOR + DIRECTORY_OFFSET,
                   candidate_partition_offset=stage, candidate_disk_offset=PARTITION_LBA * SECTOR + stage,
                   candidate_write_bytes=span, candidate_payload_bytes=len(payload),
                   candidate_dev_offset=stage - SECTOR, candidate_checksum=sum(payload) & 0xffffffff,
                   directory_changed_field_offsets=[entry_offset + value for value in (12, 16, 24, 28)])
    return details, candidate, directory, bytes(patched)


def plan(firmware_path, mbr_path, boot_path, output, previous_plan=None, previous_plan_sha256=None):
    firmware_path, mbr_path, boot_path, output = [Path(p).resolve() for p in (firmware_path, mbr_path, boot_path, output)]
    firmware, mbr, image = firmware_path.read_bytes(), mbr_path.read_bytes(), boot_path.read_bytes()
    if bool(previous_plan) != bool(previous_plan_sha256):
        raise ValueError("previous plan path and reviewed SHA-256 must be provided together")
    predecessors = []
    previous_reference = None
    if previous_plan:
        previous_path = Path(previous_plan).resolve()
        previous, prior_artifacts, prior_firmware = load_plan(previous_path, previous_plan_sha256, _historical=True)
        if prior_firmware != firmware or prior_artifacts["mbr.bin"] != mbr:
            raise ValueError("predecessor uses a different original firmware or MBR backup")
        predecessors = [*prior_artifacts.get("_predecessors", []), (previous, prior_artifacts)]
        if len(predecessors) >= 8:
            raise ValueError("bootstrap history is limited to eight reviewed plans")
        previous_reference = dict(path=str(previous_path), sha256=previous_plan_sha256.lower())
    details, candidate, original_sector, patched_sector = derive(firmware, mbr, image, predecessors)
    report_path = boot_path.with_suffix(".json")
    report = json.loads(report_path.read_text())
    if (report.get("kind"), report.get("probe"), report.get("device_serial"), report.get("build_id")) != (
            "boot", "frame", LINK_SERIAL, details["image"]["build_id"]):
        raise ValueError("matching Boot/frame build report with the inspected USB serial is required")
    if report.get("image", {}).get("sha256") != sha(image):
        raise ValueError("Boot build report does not match the supplied LOS file")
    if output.exists() and any(output.iterdir()):
        raise ValueError("plan output directory must be empty; do not overwrite a reviewed plan")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {"mbr.bin": mbr, "boot.los": image, "candidate.bin": candidate,
                 "directory-original.bin": original_sector, "directory-candidate.bin": patched_sector,
                 "boot-build-report.json": report_path.read_bytes()}
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    manifest = dict(schema_version=2, operation="p98-native-osos-redirect", device_write_attempted=False,
                    hardware_qualified=False, expected_device_bytes=DEVICE_BYTES,
                    expected_storage_serial=STORAGE_SERIAL, expected_linnet_usb_serial=LINK_SERIAL,
                    partition_lba=PARTITION_LBA, partition_sectors=PARTITION_SECTORS,
                    firmware_backup=str(firmware_path), firmware_backup_sha256=sha(firmware),
                    previous_plan=previous_reference,
                    tool_sha256=sha(Path(__file__).read_bytes()),
                    artifacts={name: dict(bytes=len(data), sha256=sha(data)) for name, data in artifacts.items()},
                    **details)
    manifest_path = output / "plan.json"
    save_json(manifest_path, manifest)
    return dict(plan=str(manifest_path), plan_sha256=sha(manifest_path.read_bytes()),
                device_write_attempted=False, candidate_disk_offset=manifest["candidate_disk_offset"],
                candidate_write_bytes=len(candidate), directory_disk_offset=manifest["directory_disk_offset"],
                directory_write_bytes=SECTOR, original_payload_preserved=True)


def load_plan(path, expected_sha, *, _historical=False, _seen=()):
    path = Path(path).resolve()
    if len(_seen) >= 8 or str(path) in _seen:
        raise ValueError("bootstrap predecessor history is cyclic or exceeds eight plans")
    raw = path.read_bytes()
    if len(expected_sha) != 64 or sha(raw) != expected_sha.lower():
        raise ValueError("reviewed plan SHA-256 does not match")
    manifest = json.loads(raw)
    if manifest.get("schema_version") not in (1, 2) or manifest.get("operation") != "p98-native-osos-redirect":
        raise ValueError("unsupported bootstrap plan")
    # A pinned predecessor was reviewed with an older tool. Its bytes, backup,
    # artifact digests and directory derivation are still checked in full. Only
    # the current plan must match the executable tool hash before any raw open.
    if not _historical and manifest.get("tool_sha256") != sha(Path(__file__).read_bytes()):
        raise ValueError("bootstrap tool changed after planning; generate and review a new plan")
    if manifest.get("schema_version") == 1 and manifest.get("previous_plan") is not None:
        raise ValueError("version 1 bootstrap plans cannot have predecessors")
    if (manifest.get("expected_device_bytes"), manifest.get("expected_storage_serial"),
        manifest.get("partition_lba"), manifest.get("partition_sectors")) != (
            DEVICE_BYTES, STORAGE_SERIAL, PARTITION_LBA, PARTITION_SECTORS):
        raise ValueError("plan device identity or partition geometry mismatch")
    required = {"mbr.bin", "boot.los", "candidate.bin", "directory-original.bin", "directory-candidate.bin", "boot-build-report.json"}
    if set(manifest["artifacts"]) != required:
        raise ValueError("unexpected plan artifact set")
    artifacts = {}
    for name in required:
        data = (path.parent / name).read_bytes()
        if manifest["artifacts"][name] != dict(bytes=len(data), sha256=sha(data)):
            raise ValueError(f"plan artifact changed: {name}")
        artifacts[name] = data
    report = json.loads(artifacts["boot-build-report.json"])
    if (report.get("kind"), report.get("probe"), report.get("device_serial"), report.get("build_id"),
        report.get("image", {}).get("sha256")) != (
            "boot", "frame", LINK_SERIAL, manifest["image"]["build_id"], sha(artifacts["boot.los"])):
        raise ValueError("reviewed report does not identify this Boot/frame image")
    firmware = Path(manifest["firmware_backup"]).read_bytes()
    predecessors = []
    previous = manifest.get("previous_plan")
    if previous is not None:
        if not isinstance(previous, dict) or set(previous) != {"path", "sha256"}:
            raise ValueError("invalid predecessor reference")
        prior, prior_artifacts, prior_firmware = load_plan(
            Path(previous["path"]), previous["sha256"], _historical=True, _seen=(*_seen, str(path)))
        if prior_firmware != firmware or prior_artifacts["mbr.bin"] != artifacts["mbr.bin"]:
            raise ValueError("predecessor backup differs from the current plan")
        predecessors = [*prior_artifacts.get("_predecessors", []), (prior, prior_artifacts)]
    details, candidate, original, patched = derive(firmware, artifacts["mbr.bin"], artifacts["boot.los"], predecessors)
    if any(manifest.get(key) != value for key, value in details.items()) or manifest["firmware_backup_sha256"] != sha(firmware):
        raise ValueError("manifest does not match independently derived backup layout")
    if (candidate, original, patched) != (artifacts["candidate.bin"], artifacts["directory-original.bin"], artifacts["directory-candidate.bin"]):
        raise ValueError("candidate bytes or directory changes differ from the derived plan")
    artifacts["_predecessors"] = predecessors
    return manifest, artifacts, firmware


def identify_disk(number):
    if os.name != "nt" or type(number) is not int or number < 0 or number > 1024:
        raise RuntimeError("raw apply/restore require an explicit Windows disk number")
    # Number is validated as an integer before constructing this read-only query.
    script = (f"$d = Get-Disk -Number {number} -ErrorAction Stop; "
              "$d | Select-Object Number,FriendlyName,SerialNumber,Size,BusType,LogicalSectorSize | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15, check=True)
    disk = json.loads(result.stdout)
    if (disk.get("Number"), str(disk.get("SerialNumber", "")).strip(), int(disk.get("Size", 0)),
        int(disk.get("LogicalSectorSize", 0))) != (number, STORAGE_SERIAL, DEVICE_BYTES, SECTOR):
        raise RuntimeError("disk number, storage serial, capacity or sector size differs from reviewed device")
    if "ipod" not in str(disk.get("FriendlyName", "")).casefold() or disk.get("BusType") not in (7, "USB"):
        raise RuntimeError("selected disk is not the inspected USB iPod")
    return disk


def read_at(device, offset, length):
    device.seek(offset)
    data = device.read(length)
    if len(data) != length:
        raise OSError("short raw device read")
    return data


def guard_device(device, manifest, artifacts, original):
    if read_at(device, 0, SECTOR) != artifacts["mbr.bin"]:
        raise RuntimeError("device MBR changed; refusing any write")
    observed = read_at(device, PARTITION_LBA * SECTOR, len(original))
    directory = observed[DIRECTORY_OFFSET:DIRECTORY_OFFSET + SECTOR]
    predecessors = artifacts.get("_predecessors", [])
    allowed_directories = [artifacts["directory-original.bin"], artifacts["directory-candidate.bin"]]
    allowed_directories.extend(prior_artifacts["directory-candidate.bin"] for _, prior_artifacts in predecessors)
    if directory not in allowed_directories:
        raise RuntimeError("directory matches no original, pinned predecessor or reviewed candidate sector")
    stage = manifest["candidate_partition_offset"]
    span = manifest["candidate_write_bytes"]
    staged = observed[stage:stage + span]
    if staged not in (bytes(span), artifacts["candidate.bin"]):
        raise RuntimeError("staging region is neither original zeroes nor the exact candidate; partial writes require investigation")
    if directory == artifacts["directory-candidate.bin"] and staged != artifacts["candidate.bin"]:
        raise RuntimeError("candidate directory references absent candidate bytes")
    normalized = bytearray(observed)
    normalized[stage:stage + span] = bytes(span)
    predecessor_states = []
    for prior, prior_artifacts in predecessors:
        prior_start, prior_span = prior["candidate_partition_offset"], prior["candidate_write_bytes"]
        prior_bytes = observed[prior_start:prior_start + prior_span]
        if prior_bytes not in (bytes(prior_span), prior_artifacts["candidate.bin"]):
            raise RuntimeError("predecessor staging differs from its pinned candidate or original zeroes")
        if directory == prior_artifacts["directory-candidate.bin"] and prior_bytes != prior_artifacts["candidate.bin"]:
            raise RuntimeError("predecessor directory references absent predecessor bytes")
        normalized[prior_start:prior_start + prior_span] = bytes(prior_span)
        predecessor_states.append(dict(build_id=prior["image"]["build_id"],
                                       staging="candidate" if prior_bytes == prior_artifacts["candidate.bin"] else "zero"))
    normalized[DIRECTORY_OFFSET:DIRECTORY_OFFSET + SECTOR] = artifacts["directory-original.bin"]
    if normalized != original:
        raise RuntimeError("firmware changed outside the reviewed staging region and directory sector")
    old = manifest["original_osos"]
    if sha(observed[old["payload_offset"]:old["payload_offset"] + old["payload_bytes"]]) != ORIGINAL_OSOS_SHA256:
        raise RuntimeError("original OSOS payload is no longer intact")
    state = "candidate" if directory == artifacts["directory-candidate.bin"] else (
        "original" if directory == artifacts["directory-original.bin"] else "predecessor")
    return dict(directory=state, staging="candidate" if staged == artifacts["candidate.bin"] else "zero",
                predecessor_staging=predecessor_states, original_payload_intact=True)


def write_verified(device, offset, payload, receipt, receipt_path, phase):
    if offset % SECTOR or len(payload) % SECTOR:
        raise ValueError("raw writes must be aligned complete sectors")
    receipt.update(phase=phase, device_write_attempted=True)
    receipt["writes"].append(dict(offset=offset, bytes=len(payload), sha256=sha(payload), complete=False))
    save_json(receipt_path, receipt)
    device.seek(offset)
    written = device.write(payload)
    receipt["writes"][-1]["returned_bytes"] = written
    if written != len(payload):
        raise OSError("short raw write; outcome is partial and will not be retried")
    device.flush()
    os.fsync(device.fileno())
    if read_at(device, offset, len(payload)) != payload:
        raise OSError("raw write readback mismatch; mutation will not be retried")
    receipt["writes"][-1]["complete"] = True
    save_json(receipt_path, receipt)


def execute(mode, plan_path, expected_sha, disk_number):
    plan_path = Path(plan_path).resolve()
    receipt_directory = plan_path.parent if plan_path.parent.is_dir() else ROOT / "out/native-bootstrap-receipts"
    receipt_directory.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_directory / (f"{mode}-receipt-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".json")
    receipt = dict(operation=mode, plan=str(plan_path), reviewed_plan_sha256=expected_sha,
                   started_at=datetime.now(timezone.utc).isoformat(), phase="validate-plan", passed=False,
                   device_write_attempted=False, writes=[], hardware_qualified=False)
    try:
        save_json(receipt_path, receipt)
        if mode not in ("apply", "restore"):
            raise ValueError("unsupported raw operation")
        manifest, artifacts, original = load_plan(plan_path, expected_sha)
        receipt["device"] = identify_disk(disk_number)
        receipt["phase"] = "guard-device"
        save_json(receipt_path, receipt)
        # This is the only raw writable open in the utility. Planning never
        # reaches it. The entire firmware is read for guards, never written.
        with open(r"\\.\PhysicalDrive" + str(disk_number), "r+b", buffering=0) as device:
            receipt["before"] = guard_device(device, manifest, artifacts, original)
            save_json(receipt_path, receipt)
            if mode == "apply":
                if receipt["before"]["staging"] != "candidate":
                    write_verified(device, manifest["candidate_disk_offset"], artifacts["candidate.bin"],
                                   receipt, receipt_path, "write-candidate")
                # Full firmware and original OSOS guards are repeated after
                # staged bytes are durable, immediately before publication.
                staged = guard_device(device, manifest, artifacts, original)
                if staged["directory"] != "candidate":
                    write_verified(device, manifest["directory_disk_offset"], artifacts["directory-candidate.bin"],
                                   receipt, receipt_path, "publish-directory")
            elif receipt["before"]["directory"] != "original":
                write_verified(device, manifest["directory_disk_offset"], artifacts["directory-original.bin"],
                               receipt, receipt_path, "restore-directory")
            receipt["after"] = guard_device(device, manifest, artifacts, original)
            desired = "candidate" if mode == "apply" else "original"
            if receipt["after"]["directory"] != desired:
                raise RuntimeError("directory did not reach the requested state")
        receipt.update(passed=True, phase="complete")
    except BaseException as exc:
        receipt.update(failure=f"{type(exc).__name__}: {exc}")
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt["receipt"] = str(receipt_path)
        save_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    planner = commands.add_parser("plan", help="read backup files and create a reviewable local plan; no device access")
    planner.add_argument("--firmware-backup", type=Path, required=True)
    planner.add_argument("--mbr-backup", type=Path, required=True)
    planner.add_argument("--boot-los", type=Path, required=True)
    planner.add_argument("--out", type=Path, required=True)
    planner.add_argument("--previous-plan", type=Path,
                         help="pinned plan currently or previously installed; its staged bytes are preserved")
    planner.add_argument("--previous-plan-sha256", help="reviewed SHA-256 of the predecessor plan")
    for mode in ("apply", "restore"):
        writer = commands.add_parser(mode, help=f"explicitly {mode} the reviewed directory redirect on the identified raw iPod")
        writer.add_argument("--plan", type=Path, required=True)
        writer.add_argument("--plan-sha256", required=True)
        writer.add_argument("--disk-number", type=int, required=True)
    args = parser.parse_args()
    if args.mode == "plan":
        try:
            result = plan(args.firmware_backup, args.mbr_backup, args.boot_los, args.out,
                          args.previous_plan, args.previous_plan_sha256)
        except (ValueError, OSError, KeyError) as exc:
            failure_directory = ROOT / "out/native-bootstrap-receipts"
            failure_directory.mkdir(parents=True, exist_ok=True)
            failure_path = failure_directory / ("plan-failure-" + uuid.uuid4().hex + ".json")
            save_json(failure_path, dict(operation="plan", passed=False, device_write_attempted=False,
                                       failure=f"{type(exc).__name__}: {exc}", output=str(args.out),
                                       finished_at=datetime.now(timezone.utc).isoformat()))
            print(f"bootstrap plan: {exc}", file=sys.stderr)
            print(f"failure receipt: {failure_path}", file=sys.stderr)
            return 2
    else:
        result = execute(args.mode, args.plan, args.plan_sha256, args.disk_number)
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
