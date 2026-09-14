"""Read and identify a mounted RetailOS iPod without raw-device access."""
import json
import os
from pathlib import Path
import re
import subprocess
from tools.studio.targets import TARGETS


def _sysinfo(root):
    path = root / "iPod_Control" / "Device" / "SysInfo"
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("RetailOS SysInfo is missing or exceeds its bound")
    fields = {}
    for line in path.read_text(encoding="ascii", errors="strict").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def _windows_storage(root):
    if os.name != "nt" or not re.fullmatch(r"[A-Za-z]:\\", str(root)):
        raise ValueError("retail-device inspection requires a Windows drive root")
    letter = root.drive[0]
    script = f"""$ErrorActionPreference='Stop'
$p=Get-Partition -DriveLetter {letter}
$d=Get-Disk -Number $p.DiskNumber
$v=Get-Volume -DriveLetter {letter}
$w=Get-CimInstance Win32_DiskDrive | Where-Object Index -eq $p.DiskNumber
$parent=(Get-PnpDeviceProperty -InstanceId $w.PNPDeviceID -KeyName 'DEVPKEY_Device_Parent').Data
$u=@(Get-CimInstance Win32_PnPEntity | Where-Object {{ $_.DeviceID -eq $parent }})
if ($u.Count -ne 1) {{ throw 'Could not resolve the mounted iPod USB identity' }}
@{{disk_number=$p.DiskNumber;disk_serial=$w.SerialNumber.Trim();disk_bytes=[long]$d.Size;
model=$w.Model;pnp_id=$w.PNPDeviceID;usb_pnp_id=$u[0].DeviceID;bus_type=[string]$d.BusType;sector_bytes=$d.LogicalSectorSize;
partition_offset=[long]$p.Offset;partition_bytes=[long]$p.Size;drive='{letter}:';
volume_label=$v.FileSystemLabel;filesystem=$v.FileSystem;volume_id=$v.UniqueId}} | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                text=True, capture_output=True, timeout=15, check=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "Windows storage query failed").strip()
        raise RuntimeError("Could not inspect the mounted iPod: " + detail) from error
    storage = json.loads(result.stdout)
    if (storage.get("model") != "Apple iPod USB Device" or
            storage.get("bus_type") != "USB" or storage.get("filesystem") != "FAT32" or
            storage.get("sector_bytes") != 512):
        raise ValueError("mounted volume is not a supported RetailOS iPod disk")
    return storage


def detect(mount):
    root = Path(mount).resolve(strict=True)
    info = _sysinfo(root)
    firewire = info.get("FirewireGuid", "").removeprefix("0x").upper()
    if not re.fullmatch(r"[0-9A-F]{16}", firewire):
        raise ValueError("RetailOS FirewireGuid is unavailable")
    storage = _windows_storage(root)
    pnp = storage["usb_pnp_id"]
    match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})\\([^\\]+)$", pnp, re.I)
    if not match:
        raise ValueError("iPod USB identity is unavailable")
    vid, pid = int(match.group(1), 16), int(match.group(2), 16)
    usb_serial = match.group(3).upper()
    if not re.fullmatch(r"[0-9A-F]{6,15}", usb_serial):
        raise ValueError("iPod USB serial identity is unavailable")
    matches = []
    for target, spec in TARGETS.items():
        retail = spec["retail"]
        boards = retail["board_names"]
        models = retail["model_numbers"]
        if (retail["usb_vid"], retail["usb_pid"]) == (vid, pid) and (
                info.get("BoardHwName") in boards or info.get("ModelNumStr") in models):
            matches.append(target)
    if len(matches) != 1:
        raise ValueError("RetailOS identity does not resolve to exactly one Linnet target")
    retail_serial = info.get("pszSerialNumber", "").upper()
    if not retail_serial or storage["disk_serial"].upper() != retail_serial:
        raise ValueError("SysInfo and mounted iPod serial identities disagree")
    return dict(target_id=matches[0], device_id=storage["disk_serial"],
                linnet_usb_serial=usb_serial, retail_usb=dict(vid=vid, pid=pid, pnp_id=pnp),
                retail_os=dict(board=info.get("BoardHwName"), model_number=info.get("ModelNumStr"),
                               build=info.get("visibleBuildID"), family=info.get("iPodFamily"),
                               updater_family=info.get("updaterFamily"), region=info.get("RegionCode")),
                storage=storage, sysinfo=info, read_only=True)
