"""Host-prepared, bounded About snapshot for Linnet's memory-only UI.

ABOUT.BIN is 1024 bytes: ABT2, version/count/used percent, twenty-eight 35-byte
ASCII rows at offset 16, and CRC32 at offset 1020. An absent record is valid;
the iPod never scans its filesystem to fill this screen.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import uuid
import zlib

from .guard import guarded_path, guard_volume, require_same_target
from .inventory import extensions

ROW_COUNT = 28
ROW_BYTES = 35
SIZE = 1024


def _size(value):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value} B"
        value /= 1024


def _device_serial(root):
    from tools.inspect.retail_device import _sysinfo
    path = root / "iPod_Control" / "Device" / "SysInfo"
    guarded_path(path, root)
    try:
        value = _sysinfo(root).get("pszSerialNumber", "").upper()
    except (OSError, ValueError, UnicodeError):
        return None
    return value if re.fullmatch(r"[A-Z0-9]{6,16}", value) else None


def _category_bytes(root):
    """One metadata-only walk; do not follow links or read media payloads."""
    suffixes = {kind: extensions(kind) for kind in ("Music", "Videos", "Photos")}
    totals = {kind: 0 for kind in suffixes}
    totals["Data"] = 0
    totals["Trash"] = 0
    directories = [root]
    while directories:
        with os.scandir(directories.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ValueError(f"Linked files or folders are unsupported: {entry.path}")
                if stat.S_ISDIR(info.st_mode):
                    directories.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    relative = Path(entry.path).relative_to(root)
                    top = relative.parts[0].casefold()
                    if top in (".trashes", ".trash", "$recycle.bin") or top.startswith(".trash-"):
                        totals["Trash"] += info.st_size
                        continue
                    suffix = Path(entry.name).suffix.lower()
                    matched = False
                    for kind, allowed in suffixes.items():
                        if suffix in allowed:
                            totals[kind] += info.st_size
                            matched = True
                            break
                    # User files without a known media suffix are data. Linnet
                    # and Apple control files are accounted for under Other.
                    if not matched and not top.startswith(".") and top not in ("ipod_control", "system volume information"):
                        totals["Data"] += info.st_size
    return totals


def make_record(identity):
    root = Path(identity["root"]).resolve(strict=True)
    usage = shutil.disk_usage(root)
    by_kind = _category_bytes(root)
    used = usage.total - usage.free
    categorized = sum(by_kind.values())
    other = max(0, used - categorized)
    serial = _device_serial(root) or identity.get("linnet_usb_serial") or identity["disk_serial"]
    model = identity.get("model_number") or identity.get("regulatory_model") or "Unknown"
    def detail(label, value):
        if value is None or value == "":
            return None
        row = f"{label}  {value}"
        # Values such as USB storage model names are supplied by Windows.
        # Keep identifiers intact and omit optional labels that cannot fit.
        ascii_row = row.encode("ascii", errors="replace").decode("ascii")
        return ascii_row if len(ascii_row) < ROW_BYTES else None

    rows = [
        detail("Name", identity.get("volume_label")),
        f"Device  {identity['target_name']}",
        f"Model no.  {model}",
        detail("Regulatory", identity.get("regulatory_model")
               if identity.get("regulatory_model") != model else None),
        detail("Board", identity.get("board_name")),
        detail("Apple OS", identity.get("apple_build")),
        detail("Family", identity.get("ipod_family")),
        detail("Region", identity.get("region_code")),
        f"Serial  {serial}",
        detail("USB serial", identity.get("linnet_usb_serial")),
        detail("Disk ID", identity.get("disk_serial")),
        detail("USB model", identity.get("usb_storage_model")),
        detail("USB", identity.get("usb_vid_pid")),
        f"Volume ID  {identity['volume_serial']}",
        detail("Disk size", _size(identity["disk_bytes"])),
        detail("Partition", _size(identity["partition_bytes"])),
        detail("Sector", f"{identity['sector_bytes']} B"),
        f"Capacity  {_size(usage.total)}",
        f"Used  {_size(used)}",
        f"Free  {_size(usage.free)}",
        f"Audio  {_size(by_kind['Music'])}",
        f"Video  {_size(by_kind['Videos'])}",
        f"Photos  {_size(by_kind['Photos'])}",
        f"Data  {_size(by_kind['Data'])}",
        f"Trash  {_size(by_kind['Trash'])}",
        f"Other  {_size(other)}",
        "Storage at last sync",
        f"Synced  {datetime.now().astimezone():%Y-%m-%d %H:%M}",
    ]
    rows = [row for row in rows if row is not None]
    if len(rows) > ROW_COUNT or any(len(row.encode("ascii")) >= ROW_BYTES for row in rows):
        raise ValueError("About details exceed the firmware display record")
    record = bytearray(SIZE)
    record[:4] = b"ABT2"
    record[4] = 2
    record[5] = len(rows)
    record[6] = min(100, (used * 100 + usage.total // 2) // usage.total) if usage.total else 0
    for index, row in enumerate(rows):
        start = 16 + index * ROW_BYTES
        record[start:start + len(row)] = row.encode("ascii")
    struct.pack_into("<I", record, SIZE - 4, zlib.crc32(record[:-4]))
    return bytes(record)


def publish(identity, verify):
    """Replace the optional record after confirming the mounted target."""
    root = Path(identity["root"]).resolve(strict=True)
    directory = root / ".LINNET"
    guarded_path(directory, root)
    if not directory.is_dir():
        raise ValueError("Linnet system storage is unavailable for the About snapshot")
    require_same_target(identity, verify(identity))
    data = make_record(identity)
    require_same_target(identity, verify(identity))
    guard_volume(identity)
    target = directory / "ABOUT.BIN"
    temporary = directory / ("AB" + uuid.uuid4().hex[:6].upper() + ".TMP")
    guarded_path(target, root)
    guarded_path(temporary, root)
    try:
        with temporary.open("xb") as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        if temporary.read_bytes() != data:
            raise OSError("About snapshot verification failed")
        guard_volume(identity)
        os.replace(temporary, target)
        guard_volume(identity)
        if target.read_bytes() != data:
            raise OSError("About snapshot verification failed after publication")
    finally:
        temporary.unlink(missing_ok=True)
    return dict(path=".LINNET/ABOUT.BIN", bytes=SIZE, used_percent=data[6])


def read_details(identity, verify):
    """Read the same facts for Media Manager without writing to the iPod."""
    current = verify(identity)
    data = make_record(current)
    require_same_target(current, verify(current))
    rows = [data[16 + i * ROW_BYTES:16 + (i + 1) * ROW_BYTES].split(b"\0", 1)[0].decode("ascii")
            for i in range(data[5])]
    rows[-1] = rows[-1].replace("Synced", "Read", 1)
    return dict(name=current.get("volume_label") or "Unnamed iPod", rows=rows, used_percent=data[6])
