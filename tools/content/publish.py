"""Guarded, unelevated publication of staged PODB music to Windows Disk Mode.

This module never opens a physical disk or requests elevation. Media is immutable
by staged name: an existing different hash is a collision and stops publication.
The old database is backed up before the new database is replaced last. File
fsync and readback detect normal I/O failures; FAT rename is not a power-loss
journal and storage firmware may retain volatile caches. Safely eject afterward.
Failures leave evidence and copied files in place; there is no automatic cleanup,
rollback, or replay. The caller must keep the mounted iPod exclusively in Disk
Mode throughout publication and handle reboot only after a successful receipt.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import time
import uuid
import zlib
from typing import Callable

from .music import ART, HEADER, MAX_DATABASE, TRACK, validate_database

CHUNK = 1024 * 1024


def _plain(path: Path, boundary: Path) -> None:
    """Reject symlinks/junctions before resolving any publication path."""
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise ValueError("path escaped its declared root") from exc
    cursor = boundary
    for component in (None, *relative.parts):
        if component is not None:
            cursor /= component
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"reparse/symlink path rejected: {cursor}")


def _bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as reader:
        data = reader.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"file exceeds limit: {path.name}")
    return data


def _hash(path: Path, expected_size: int | None = None) -> str:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or (expected_size is not None and before.st_size != expected_size):
        raise ValueError(f"unexpected file type/size: {path}")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as reader:
        while chunk := reader.read(CHUNK):
            count += len(chunk)
            digest.update(chunk)
    after = path.stat()
    if count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f"file changed while hashing: {path}")
    return digest.hexdigest()


def _pool_string(database: bytes, pool: int, offset: int) -> str:
    start = pool + offset
    return database[start:database.index(0, start)].decode("utf-8")


def _existing_stat(local: Path, root: Path, size: int, mtime_ns: int | None = None):
    """Check referenced media without reading its audio payload."""
    _plain(local, root)
    info = local.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
        raise ValueError(f"existing iPod media type/size changed: {local}")
    if mtime_ns is not None and info.st_mtime_ns != mtime_ns:
        raise ValueError(f"existing iPod media timestamp changed: {local}")
    return info


def validate_stage(stage: Path, *, device_root: Path | None = None,
                   progress: Callable[[str], None] | None = None) -> dict:
    """Validate PODB, manifest and art; existing metadata references use stat checks."""
    stage = Path(os.path.abspath(stage))
    _plain(stage, Path(stage.anchor))
    stage = stage.resolve(strict=True)
    if not stage.is_dir():
        raise ValueError("stage must be a directory")
    for name in ("LIBRARY.PDB", "music-manifest.json"):
        _plain(stage / name, stage)
    database = _bounded(stage / "LIBRARY.PDB", MAX_DATABASE)
    info = validate_database(database)
    manifest_bytes = _bounded(stage / "music-manifest.json", 128 * 1024 * 1024)
    manifest = json.loads(manifest_bytes)
    db_hash = hashlib.sha256(database).hexdigest()
    expected = dict(format="PODB", version=1, tracks=info["tracks"], groups=info["groups"],
                    artwork=info["artwork"], bytes=len(database), sha256=db_hash)
    if not isinstance(manifest, dict) or any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("music manifest does not match the complete database")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != info["tracks"]:
        raise ValueError("manifest track inventory mismatch")
    track_offset, pool, art_offset = (struct.unpack_from("<I", database, offset)[0] for offset in (32, 48, 60))
    files: dict[str, dict] = {}
    sources = set()
    external = []
    external_paths = set()
    if device_root is not None:
        _plain(Path(os.path.abspath(device_root)), Path(Path(os.path.abspath(device_root)).anchor))
        device_root = Path(device_root).resolve(strict=True)
    for index, entry in enumerate(entries):
        if progress and (index % 100 == 0 or index + 1 == len(entries)):
            progress(f"Checking music references {index + 1:,}/{len(entries):,}…")
        if not isinstance(entry, dict):
            raise ValueError("invalid manifest entry")
        offset = track_offset + index * TRACK
        identity, size = struct.unpack_from("<QQ", database, offset)
        path = _pool_string(database, pool, struct.unpack_from("<I", database, offset + 64)[0])
        sha = database[offset + 96:offset + 128].hex()
        if entry.get("id") != f"{identity:016x}" or entry.get("path") != path or entry.get("sha256") != sha:
            raise ValueError("manifest track identity/path/hash mismatch")
        source = entry.get("source")
        if (not isinstance(source, str) or not source or "\0" in source or "\\" in source or
            PurePosixPath(source).is_absolute() or ".." in PurePosixPath(source).parts or source in sources or
            int.from_bytes(hashlib.sha256(("track:" + source).encode()).digest()[:8], "little") != identity):
            raise ValueError("manifest source identity mismatch")
        sources.add(source)
        storage = entry.get("storage", "staged")
        if storage not in ("staged", "existing"):
            raise ValueError("unknown music storage mode")
        integrity = entry.get("integrity", "sha256")
        if integrity not in ("sha256", "metadata") or (integrity == "metadata" and storage != "existing"):
            raise ValueError("invalid music integrity mode")
        if integrity == "metadata" and (sha != "0" * 64 or type(entry.get("bytes")) is not int or
                entry["bytes"] != size or type(entry.get("mtime_ns")) is not int or entry["mtime_ns"] < 0):
            raise ValueError("invalid metadata-only music reference")
        if storage == "staged" and Path(path).stem != f"{identity & 0xffffffff:08X}":
            raise ValueError("media short name does not match track identity")
        for field, position in (("title", 52), ("artist", 56), ("album", 60)):
            if entry.get(field) != _pool_string(database, pool, struct.unpack_from("<I", database, offset + position)[0]):
                raise ValueError("manifest text mismatch")
        for field, position in (("codec", 48), ("track", 80), ("disc", 84)):
            if entry.get(field) != struct.unpack_from("<I", database, offset + position)[0]:
                raise ValueError("manifest numeric metadata mismatch")
        if storage == "existing":
            if device_root is None:
                raise ValueError("This library references existing iPod files; connect the iPod and supply device_root")
            local = device_root / path.lstrip("/")
            snapshot = _existing_stat(local, device_root, size,
                                      entry["mtime_ns"] if integrity == "metadata" else None)
            if integrity == "sha256" and _hash(local, size) != sha:
                raise ValueError(f"existing iPod media hash mismatch: {path}")
            if path in external_paths:
                raise ValueError("duplicate existing media path")
            external_paths.add(path)
            external.append(dict(path=path, bytes=size, sha256=sha, kind="music", integrity=integrity,
                                 mtime_ns=snapshot.st_mtime_ns, inode=snapshot.st_ino))
            continue
        if not re.fullmatch(r"/LINNET/MUSIC/[0-9A-F]{8}\.[A-Z0-9]{1,3}", path):
            raise ValueError("staged media must use its managed short name")
        relative = path.removeprefix("/LINNET/")
        if relative in files:
            raise ValueError("duplicate staged media path")
        local = stage / relative
        _plain(local, stage)
        if _hash(local, size) != sha:
            raise ValueError(f"staged media hash mismatch: {relative}")
        files[relative] = dict(path=relative, bytes=size, sha256=sha, kind="music")
    for index in range(info["artwork"]):
        offset = art_offset + index * ART
        identity, path_offset = struct.unpack_from("<QI", database, offset)
        path = _pool_string(database, pool, path_offset)
        relative = path.removeprefix("/LINNET/")
        local = stage / relative
        _plain(local, stage)
        pixels = _bounded(local, 8192)
        digest = hashlib.sha256(pixels).digest()
        if (len(pixels) != 8192 or int.from_bytes(digest[:8], "little") != identity or
            zlib.crc32(pixels) != struct.unpack_from("<I", database, offset + 24)[0] or
            Path(path).stem != digest[:4].hex().upper()):
            raise ValueError(f"staged artwork identity/CRC mismatch: {relative}")
        record = dict(path=relative, bytes=8192, sha256=digest.hex(), kind="art")
        if relative in files and files[relative] != record:
            raise ValueError("conflicting artwork short name")
        files[relative] = record
    return dict(stage=str(stage), database=expected, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                files=list(files.values()), existing_files=external, media_bytes=sum(item["bytes"] for item in files.values()))


def _volume_serial(value: str) -> str:
    value = str(value).replace("-", "").strip().upper()
    if not re.fullmatch("[0-9A-F]{8}", value):
        raise ValueError("expected volume serial must be eight hex digits (XXXX-XXXX is accepted)")
    return value


def inspect_target(disk_number: int, expected_disk_serial: str, expected_volume_serial: str,
                   expected_drive: str | None = None) -> dict:
    """Query Windows storage identity without opening devices or requesting UAC."""
    if os.name != "nt":
        raise RuntimeError("music publication requires Windows Disk Mode")
    if type(disk_number) is not int or disk_number < 0 or not isinstance(expected_disk_serial, str) or not expected_disk_serial.strip():
        raise ValueError("explicit disk number and disk serial required")
    volume_serial = _volume_serial(expected_volume_serial)
    drive = None if expected_drive is None else str(expected_drive).rstrip("\\/").upper()
    if drive is not None and not re.fullmatch("[A-Z]:", drive):
        raise ValueError("expected drive must be a drive letter such as F:")
    config = base64.b64encode(json.dumps(dict(number=disk_number, serial=expected_disk_serial.strip(),
                                            volume=volume_serial, drive=drive)).encode()).decode()
    script = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$cfg=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('CONFIG')) | ConvertFrom-Json
$disk=Get-Disk -Number $cfg.number -ErrorAction Stop
$physical=Get-CimInstance Win32_DiskDrive -Filter ('Index='+$cfg.number)
if ($disk.SerialNumber.Trim() -cne $cfg.serial -or [string]$disk.BusType -ne 'USB' -or
    [string]$disk.FriendlyName -ne 'Apple iPod' -or $disk.IsBoot -or $disk.IsSystem -or
    $disk.IsOffline -or $disk.IsReadOnly -or $disk.LogicalSectorSize -ne 512 -or
    $physical.PNPDeviceID -notmatch '^USBSTOR\\.*VEN_APPLE.*PROD_IPOD') {
    throw 'Require expected serial, Apple USB iPod, writable online non-system disk and 512-byte sectors'
}
$parts=@(Get-Partition -DiskNumber $disk.Number | Where-Object {$_.DriveLetter})
if ($parts.Count -ne 1) {throw 'Require exactly one mounted partition'}
$part=$parts[0]
$volume=Get-Volume -Partition $part
$drive=[string]$part.DriveLetter+':'
$logical=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$drive+"'")
if ([string]$volume.FileSystemType -ne 'FAT32' -or $logical.VolumeSerialNumber.ToUpper() -cne $cfg.volume -or
    ($cfg.drive -and $drive -cne $cfg.drive) -or $drive -eq $env:SystemDrive) {throw 'Volume identity rejected'}
@{disk_number=[int]$disk.Number;disk_serial=$disk.SerialNumber.Trim();disk_unique_id=[string]$disk.UniqueId;
  disk_bytes=[uint64]$disk.Size;partition_number=[int]$part.PartitionNumber;partition_offset=[uint64]$part.Offset;
  partition_bytes=[uint64]$part.Size;drive=$drive;root=$drive+'\';volume_unique_id=[string]$volume.UniqueId;
  volume_serial=$logical.VolumeSerialNumber.ToUpper();filesystem=[string]$volume.FileSystemType;
  pnp_id=[string]$physical.PNPDeviceID;free_bytes=[uint64]$volume.SizeRemaining} | ConvertTo-Json -Compress
'''.replace("CONFIG", config)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("iPod identity inspection failed: " + result.stderr.strip())
    identity = json.loads(result.stdout.lstrip("\ufeff"))
    if (identity.get("disk_number") != disk_number or identity.get("disk_serial") != expected_disk_serial.strip() or
        identity.get("volume_serial") != volume_serial or not re.fullmatch(r"[A-Z]:\\", identity.get("root", "")) or
        not identity.get("disk_unique_id") or not identity.get("volume_unique_id")):
        raise RuntimeError("incomplete Windows disk/volume identity")
    return identity


def _same_target(before: dict, after: dict) -> None:
    for key in ("disk_number", "disk_serial", "disk_unique_id", "disk_bytes", "partition_number", "partition_offset",
                "partition_bytes", "drive", "root", "volume_unique_id", "volume_serial", "filesystem", "pnp_id"):
        if before.get(key) != after.get(key):
            raise RuntimeError(f"iPod identity changed during publication: {key}")


def _volume_guard(identity: dict) -> None:
    """Cheap per-file mounted-volume identity guard; does not open raw storage."""
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetVolumeInformationW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD),
        ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD]
    kernel.GetVolumeInformationW.restype = w.BOOL
    kernel.GetVolumeNameForVolumeMountPointW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    kernel.GetVolumeNameForVolumeMountPointW.restype = w.BOOL
    serial, maximum, flags = w.DWORD(), w.DWORD(), w.DWORD()
    filesystem, volume = ctypes.create_unicode_buffer(32), ctypes.create_unicode_buffer(1024)
    if not kernel.GetVolumeInformationW(identity["root"], None, 0, ctypes.byref(serial), ctypes.byref(maximum),
                                        ctypes.byref(flags), filesystem, len(filesystem)):
        raise OSError(ctypes.get_last_error(), "iPod volume is unavailable")
    if not kernel.GetVolumeNameForVolumeMountPointW(identity["root"], volume, len(volume)):
        raise OSError(ctypes.get_last_error(), "iPod volume GUID is unavailable")
    if (f"{serial.value:08X}" != identity["volume_serial"] or filesystem.value != "FAT32" or
        volume.value.casefold() != identity["volume_unique_id"].casefold()):
        raise RuntimeError("mounted iPod volume changed during publication")


def _copy_verified(source: Path, destination: Path, item: dict, root: Path, guard) -> bool:
    """Create only; preserve existing different objects and failed partial files."""
    guard()
    _plain(destination, root)
    if destination.exists():
        if _hash(destination, item["bytes"]) != item["sha256"]:
            raise ValueError(f"existing different object is a hash collision: {destination}")
        return False
    hasher = hashlib.sha256()
    count = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(CHUNK):
            guard()
            writer.write(chunk)
            count += len(chunk)
            hasher.update(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    guard()
    if count != item["bytes"] or hasher.hexdigest() != item["sha256"] or _hash(destination, count) != item["sha256"]:
        raise OSError(f"copied file failed complete readback: {destination}")
    return True


def publish_music(stage: Path, *, disk_number: int, expected_disk_serial: str,
                  expected_volume_serial: str, expected_drive: str | None = None,
                  progress: Callable[[str], None] | None = None) -> dict:
    """Validate locally, guard the explicit iPod, then publish media before PODB.

    No elevation, cleanup deletions, raw writes, ejection, or reboot is performed.
    An exception after the final replace is an uncertain publication: inspect
    LIBRARY.PDB and retained LIBBAK backup; never automatically replay the call.
    """
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity["root"])
    inventory = validate_stage(stage, device_root=root, progress=progress)
    stage = Path(inventory["stage"])
    if stage.drive.casefold() == root.drive.casefold():
        raise ValueError("local stage must reside on a different volume from the iPod")
    guard = lambda: _volume_guard(identity)
    guard()
    linnet = root / "LINNET"
    _plain(linnet, root)
    # Preflight existing media before any device mutation, including collisions.
    needed = inventory["database"]["bytes"]
    for item in inventory["files"]:
        destination = linnet / item["path"]
        _plain(destination, root)
        if destination.exists():
            if _hash(destination, item["bytes"]) != item["sha256"]:
                raise ValueError(f"existing media differs; refusing overwrite: {item['path']}")
        else:
            needed += item["bytes"] + 65536  # conservative FAT cluster allowance
    active = linnet / "LIBRARY.PDB"
    journals=[linnet/'MUSIC0.BIN',linnet/'MUSIC1.BIN']
    for journal in journals:_plain(journal,root)
    journal_exists=[p.exists() for p in journals]
    if any(journal_exists) and not all(journal_exists):
        raise ValueError('Incomplete music journal pair; inspect existing state before publication')
    if all(journal_exists):
        sizes=[p.stat().st_size for p in journals]
        if sizes!=[4608,4608]:
            from .history import BANK_BYTES, validate_superblock
            if sizes!=[BANK_BYTES,BANK_BYTES]:
                raise ValueError('Unexpected/mismatched music journal sizes; preserving existing state')
            epochs=[]
            for journal in journals:
                guard()
                with journal.open('rb') as reader:epochs.append(validate_superblock(reader.read(4096)))
            if epochs[0]!=epochs[1]:
                raise ValueError('Music journal epoch mismatch; preserving existing state')
    needed+=2*65536
    _plain(active, root)
    previous = None
    if active.exists():
        old_data = _bounded(active, MAX_DATABASE)
        validate_database(old_data)
        previous = dict(bytes=len(old_data), sha256=hashlib.sha256(old_data).hexdigest())
        needed += len(old_data) + 65536
    if identity["free_bytes"] < needed + 1024 * 1024:
        raise ValueError("insufficient free space for media, new database, and retained backup")
    _same_target(identity, inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive))
    guard()
    linnet.mkdir(exist_ok=True)
    _plain(linnet, root)
    for name in ("MUSIC", "ART", "LIBBAK"):
        path = linnet / name
        _plain(path, root)
        path.mkdir(exist_ok=True)
    receipt = dict(operation="publish-music", passed=False, phase="copying-media", identity=identity,
                   candidate_sha256=inventory["database"]["sha256"], previous=previous,
                   copied=0, reused=len(inventory["existing_files"]), started_at=time.time(), elevation=False,
                   existing_metadata_checked=sum(item["integrity"] == "metadata" for item in inventory["existing_files"]),
                   existing_sha256_checked=sum(item["integrity"] == "sha256" for item in inventory["existing_files"]),
                   durability="file fsync and readback; FAT rename is not a power-loss journal")
    # Receipt stays on the host; it records uncertainty without writing extra
    # mutable state beside the device's immutable database.
    receipt_path = stage / ("publish-" + uuid.uuid4().hex + ".json")

    def record() -> None:
        with receipt_path.open("w", encoding="utf-8", newline="\n") as writer:
            json.dump(receipt, writer, indent=2)
            writer.write("\n")
            writer.flush()
            os.fsync(writer.fileno())

    record()
    try:
        for item in inventory["files"]:
            local = stage / item["path"]
            _plain(local, stage)
            copied = _copy_verified(local, linnet / item["path"], item, root, guard)
            receipt["copied" if copied else "reused"] += 1
        receipt["phase"] = "media-verified"
        record()
        if not any(journal_exists):
            bank=bytearray(4608)
            struct.pack_into('<4sHHII',bank,0,b'JRN1',1,64,0,0)
            bank[16:48]=_bounded(stage/'LIBRARY.PDB',MAX_DATABASE)[64:96]
            struct.pack_into('<I',bank,4604,zlib.crc32(bank[:4604]))
            digest=hashlib.sha256(bank).hexdigest()
            receipt['phase']='initializing-music-state';record()
            for journal in journals:
                guard();_plain(journal,root)
                with journal.open('xb') as writer:
                    writer.write(bank);writer.flush();os.fsync(writer.fileno())
                if _hash(journal,4608)!=digest:raise OSError('Music journal initialization readback mismatch')
            receipt['initialized_music_state']=True
        # Preserve previous published bytes before replacing the active entry.
        if previous:
            backup = linnet / "LIBBAK" / (previous["sha256"][:8].upper() + ".PDB")
            _copy_verified(active, backup, previous, root, guard)
            receipt["backup"] = str(backup)
        temporary = linnet / ("L" + uuid.uuid4().hex[:7].upper() + ".TMP")
        _copy_verified(stage / "LIBRARY.PDB", temporary, inventory["database"], root, guard)
        receipt["temporary"] = str(temporary)
        receipt["phase"] = "candidate-verified"
        record()
        # Database and manifest are immutable inputs to this logical operation.
        if (_hash(stage / "LIBRARY.PDB", inventory["database"]["bytes"]) != inventory["database"]["sha256"] or
            _hash(stage / "music-manifest.json") != inventory["manifest_sha256"]):
            raise RuntimeError("stage changed during publication")
        _same_target(identity, inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive))
        guard()
        for index, item in enumerate(inventory["existing_files"]):
            if progress and index % 100 == 0:
                progress(f"Confirming music references {index + 1:,}/{len(inventory['existing_files']):,}…")
            snapshot = _existing_stat(root / item["path"].lstrip("/"), root, item["bytes"], item["mtime_ns"])
            if snapshot.st_ino != item["inode"]:
                raise RuntimeError(f"existing iPod media replaced during publication: {item['path']}")
        guard()
        _plain(active, root)
        if previous:
            if _hash(active, previous["bytes"]) != previous["sha256"]:
                raise RuntimeError("active database changed during publication")
        elif active.exists():
            raise RuntimeError("another database appeared during publication")
        receipt["phase"] = "replacing-database"
        record()
        os.replace(temporary, active)
        guard()
        with active.open("rb+") as writer:
            writer.flush()
            os.fsync(writer.fileno())
        if _hash(active, inventory["database"]["bytes"]) != inventory["database"]["sha256"]:
            raise OSError("published database readback mismatch")
        receipt.update(passed=True, phase="published", finished_at=time.time(), database=str(active),
                       receipt=str(receipt_path), tracks=inventory["database"]["tracks"])
        record()
        return receipt
    except Exception as exc:
        receipt.update(error=str(exc), finished_at=time.time(), receipt=str(receipt_path))
        try:
            record()
        except OSError:
            pass
        raise RuntimeError(f"Music publication stopped in {receipt['phase']}: {exc}. Inspect {receipt_path}; do not replay automatically") from exc
