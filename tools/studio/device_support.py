"""Read-only compatibility explanations and shareable device reports.

Reports are evidence for investigation, never authority to install firmware.
Only allowlisted hardware fields leave this module; no media is enumerated.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

from .targets import TARGETS, ROOT


def describe(identity=None, review=None):
    target = (identity or {}).get("target_id")
    if target not in TARGETS:
        return dict(
            status="unidentified",
            title="Compatibility not established",
            detail="Find iPod to identify it. If detection fails, save a hardware report below.",
        )
    spec = TARGETS[target]
    if not spec.get("build_enabled", True):
        return dict(
            status="unsupported",
            title="Installation unavailable",
            detail=spec.get(
                "bringup_blocker",
                "This model is recognized, but no supported firmware is available.",
            ),
        )
    if review and review.get("action") in ("unsupported", "attention"):
        return dict(
            status=review["action"],
            title="Installation unavailable"
            if review["action"] == "unsupported"
            else "Setup needs attention",
            detail=review["summary"],
        )
    if review and review.get("linnet", {}).get("state") == "installed":
        return dict(
            status="installed",
            title="Linnet installed",
            detail="This model family is supported. Installed software and recovery information have been read.",
        )
    classic = spec["installer"]["boot_layout"] == "s5l-nor"
    return dict(
        status="supported-family",
        title="Supported model family",
        detail=(
            "Classic setup checks the BootROM, RAM, display, PATA storage and supported boot flash before writing boot flash. "
            "CE-ATA storage is not supported."
            if classic
            else "Installation requires a supported disk layout and a verified backup of the original startup software. "
            "Drive geometry and other hardware are also checked when Linnet starts."
        ),
    )


def _inventory():
    if os.name != "nt":
        raise RuntimeError("Hardware reports currently require Windows")
    script = r"""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$usb=@(Get-PnpDevice -PresentOnly | Where-Object {
 $_.InstanceId -match '^USB\\VID_(05AC|0000)&PID_' -or
 $_.InstanceId -match '^USB\\VID_1209&PID_504[A-F]\\'
} | Select-Object -First 32 | ForEach-Object {
 $problem=Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_ProblemCode -ErrorAction SilentlyContinue
 $driver=Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_DriverVersion -ErrorAction SilentlyContinue
 @{instance=$_.InstanceId;status=[string]$_.Status;problem=$problem.Data;driver_version=$driver.Data}
})
$disks=@(Get-CimInstance Win32_DiskDrive | Where-Object {
 $_.InterfaceType -eq 'USB' -and ($_.Model -eq 'Apple iPod USB Device' -or $_.Model -like 'LINNET IPOD*')
} | Select-Object -First 16 | ForEach-Object {
 $w=$_
 try {
 $d=Get-Disk -Number $w.Index
 $parts=@(Get-Partition -DiskNumber $d.Number | ForEach-Object {
  $p=$_;$v=$null;$letter=[string]$p.DriveLetter
  if ($letter -notmatch '^[A-Za-z]$') {$letter=''}
  if ($letter) {$v=Get-Volume -Partition $p -ErrorAction SilentlyContinue}
  @{offset=[long]$p.Offset;bytes=[long]$p.Size;type=[string]$p.Type;
    drive=$letter;filesystem=[string]$v.FileSystemType;
    volume_id=[string]$v.UniqueId}
 })
 @{pnp_id=$w.PNPDeviceID;bytes=[long]$d.Size;logical_sector_bytes=[int]$d.LogicalSectorSize;
   physical_sector_bytes=[int]$d.PhysicalSectorSize;read_only=[bool]$d.IsReadOnly;
   offline=[bool]$d.IsOffline;partitions=$parts}
 } catch {@{pnp_id=$w.PNPDeviceID;error='storage-query-failed'}}
})
ConvertTo-Json -Depth 6 -Compress -InputObject @{usb=$usb;disks=$disks}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json.loads(result.stdout.lstrip("\ufeff"))


def _usb_id(instance):
    match = re.match(r"^USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", instance, re.I)
    return (int(match[1], 16), int(match[2], 16)) if match else None


def _family(pair):
    return [
        key
        for key, spec in TARGETS.items()
        if pair
        in (
            (spec["retail"]["usb_vid"], spec["retail"]["usb_pid"]),
            (
                spec.get("native_storage", {}).get("usb_vid"),
                spec.get("native_storage", {}).get("usb_pid"),
            ),
        )
    ]


def _fields(value, names):
    return {
        name: value[name]
        for name in names
        if name in value and isinstance(value[name], (str, int, bool, type(None)))
    }


def _sysinfo(partition):
    """Read only bounded, non-identifying SysInfo fields from a pinned volume."""
    from tools.content.guard import guarded_path
    from tools.inspect.retail_device import _sysinfo as read_sysinfo
    import ctypes
    from ctypes import wintypes

    # A diagnostic read also rejects mount-point replacement and reparse paths.
    drive = partition.get("drive", "")
    if not re.fullmatch("[A-Za-z]", drive) or partition.get("filesystem") != "FAT32":
        return {}
    root = Path(drive + ":\\")

    def pinned():
        volume = ctypes.create_unicode_buffer(1024)
        api = ctypes.WinDLL(
            "kernel32", use_last_error=True
        ).GetVolumeNameForVolumeMountPointW
        api.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        api.restype = wintypes.BOOL
        if (
            not api(str(root), volume, len(volume))
            or volume.value.casefold() != partition["volume_id"].casefold()
        ):
            raise RuntimeError("Diagnostic volume changed")

    pinned()
    guarded_path(root / "iPod_Control" / "Device" / "SysInfo", root)
    info = read_sysinfo(root)
    pinned()
    names = (
        "BoardHwName",
        "ModelNumStr",
        "visibleBuildID",
        "iPodFamily",
        "updaterFamily",
        "RegionCode",
    )
    return {
        key: "".join(c for c in info[key][:96] if c.isprintable())
        for key in names
        if key in info
    }


def collect(discovery=None, identity=None):
    """Capture observations without raw disk access, mode changes or writes."""
    from tools.inspect.windows_pnp import usb_parent

    report = dict(
        format="linnet-hardware-report",
        version=1,
        collected_at=datetime.now(timezone.utc).isoformat(),
        linnet_version=str(
            tomllib.loads((ROOT / "config/system.toml").read_text())["system"][
                "version"
            ]
        ),
        privacy="The report includes model, firmware, disk geometry and connection status. Device serial numbers, "
        "volume labels, computer/user names, local paths and media contents are excluded. "
        "Collection does not write to the iPod or upload anything. Review the report before sharing it.",
        usb=[],
        disks=[],
        recognized=[],
        runtime=[],
        limitations=[
            "Apple Disk Mode normally hides the internal ATA drive and other board components.",
            "A report does not prove that an untested device is safe to install or add firmware support automatically.",
        ],
        errors=[],
    )
    try:
        inventory = _inventory()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        inventory = {}
        report["errors"].append(
            dict(stage="windows-inventory", type=type(error).__name__)
        )
    for item in inventory.get("usb", [])[:32]:
        pair = _usb_id(item.get("instance", ""))
        if not pair:
            continue
        targets = _family(pair)
        mode = (
            "unidentified"
            if pair[0] == 0
            else "linnet-link"
            if pair == (0x1209, 0x504A)
            else "dfu"
            if pair == (0x05AC, 0x1223)
            else "disk-family"
            if targets
            else "other-apple"
        )
        report["usb"].append(
            dict(
                vid_pid=f"{pair[0]:04X}:{pair[1]:04X}",
                targets=targets,
                mode=mode,
                **_fields(item, ("status", "problem", "driver_version")),
            )
        )
    for item in inventory.get("disks", [])[:16]:
        try:
            pair = _usb_id(usb_parent(item["pnp_id"]))
            if not pair or not (pair[0] == 0x05AC or _family(pair)):
                continue
            disk = dict(
                vid_pid=f"{pair[0]:04X}:{pair[1]:04X}",
                **_fields(
                    item,
                    (
                        "bytes",
                        "logical_sector_bytes",
                        "physical_sector_bytes",
                        "read_only",
                        "offline",
                        "error",
                    ),
                ),
                partitions=[],
            )
            for partition in item.get("partitions", [])[:16]:
                entry = _fields(partition, ("offset", "bytes", "type", "filesystem"))
                entry["mounted"] = bool(
                    re.fullmatch("[A-Za-z]", partition.get("drive", ""))
                )
                try:
                    entry["sysinfo"] = _sysinfo(partition)
                except (OSError, RuntimeError, ValueError, UnicodeError) as error:
                    entry["sysinfo_error"] = type(error).__name__
                disk["partitions"].append(entry)
            report["disks"].append(disk)
        except (OSError, RuntimeError, ValueError) as error:
            report["errors"].append(
                dict(stage="disk-identity", type=type(error).__name__)
            )
    if discovery is None:
        from tools.content.media_manager import discover

        try:
            discovery = discover(detailed=True)
        except (OSError, RuntimeError, ValueError) as error:
            discovery = {}
            report["errors"].append(dict(stage="discovery", type=type(error).__name__))
    devices = discovery.get("devices", [])
    for device in devices:
        report["recognized"].append(
            dict(
                **_fields(
                    device,
                    (
                        "target_id",
                        "usb_vid_pid",
                        "board_name",
                        "model_number",
                        "apple_build",
                        "disk_bytes",
                        "sector_bytes",
                        "partition_offset",
                        "partition_bytes",
                        "filesystem",
                    ),
                ),
                compatibility=describe(device),
            )
        )
    from .media_link import discover as links

    try:
        connections = discovery["links"] if "links" in discovery else links()
    except (OSError, RuntimeError, ValueError) as error:
        connections = []
        report["errors"].append(dict(stage="link-discovery", type=type(error).__name__))
    report["discovery_issue_count"] = len(discovery.get("errors", []))
    for connection in connections[:16]:
        current = connection["identity"]
        # Developer build hashes are device-bound, so omit them along with serials.
        entry = dict(
            identity=_fields(
                current,
                ("target_id", "profile", "image_kind", "healthy", "health_flags"),
            )
        )
        if current["image_kind"] == "os":
            from tools.link.campaign import connect

            session = None
            try:
                session, _, observed = connect(
                    serial_number=connection["serial"], deadline_seconds=5
                )
                if observed != current:
                    raise RuntimeError("Runtime identity changed")
                info = session.media_info()
                entry["ata"] = _fields(
                    info,
                    (
                        "model",
                        "firmware",
                        "logical_sector_bytes",
                        "physical_sector_bytes",
                        "sectors",
                        "capabilities",
                        "quirks",
                        "media_kind",
                        "rotation_rpm",
                    ),
                )
                entry["power"] = _fields(
                    session.power_state(),
                    ("failures", "bus_resets", "battery_mv", "charge_limit_ma"),
                )
            except (OSError, RuntimeError, ValueError) as error:
                entry["runtime_error"] = type(error).__name__
            finally:
                if session:
                    session.close()
        report["runtime"].append(entry)
    known = bool(devices or report["runtime"])
    if known:
        report["summary"] = (
            "Supported model family detected. Review iPod setup for installation and recovery checks."
        )
    elif any(item["targets"] for item in report["usb"]):
        report["summary"] = (
            "A supported USB family is present, but a usable iPod disk was not verified. Check Disk Mode, the drive letter and FAT32 formatting. Save this report if detection still fails."
        )
    elif any(item["mode"] == "linnet-link" for item in report["usb"]):
        report["summary"] = (
            "Linnet USB is present, but Link did not answer. Reconnect directly to the computer, then choose Find iPod. Save this report if it still fails."
        )
    elif any(item["mode"] == "dfu" for item in report["usb"]):
        report["summary"] = (
            "Apple DFU mode is present. Resume the saved Classic installation for this iPod, or return to Disk Mode to begin setup. A device identity has not been verified yet."
        )
    elif any(item["mode"] == "unidentified" for item in report["usb"]):
        report["summary"] = (
            "Windows sees a USB connection with an unreadable identity. Try a direct computer port and another cable, then choose Find iPod. Installation is unavailable until the iPod is identified."
        )
    elif report["usb"]:
        report["summary"] = (
            "An Apple USB device is present, but its model is not identified as a supported iPod. Installation is unavailable. Save this report for investigation."
        )
    elif report["errors"]:
        report["summary"] = (
            "Windows device inspection did not finish. Save this partial report and retry detection."
        )
    else:
        report["summary"] = (
            "No Apple iPod or Linnet USB connection was found. Connect the iPod in Disk Mode and choose Find iPod."
        )
    report["how_to_share"] = sharing()["instructions"]
    return report


def sharing():
    """An optional public support destination, configured by the distributor."""
    from urllib.parse import urlsplit

    config = tomllib.loads((ROOT / "config/support.toml").read_text(encoding="utf-8"))
    url = config.get("contact_url", "")
    email = config.get("email", "")
    if url:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or email
        ):
            raise ValueError("Support contact must be one HTTPS URL or email address")
    if email and not re.fullmatch(
        r"[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email
    ):
        raise ValueError("Invalid support email address")
    return dict(
        url=url,
        email=email,
        instructions=(
            "1. Save the report on your computer, or copy it below.\n"
            "2. Contact Linnet support and attach the JSON file or paste the report.\n"
            "3. Describe your iPod, storage modifications, what you tried, and the message or screen you saw.\n"
            "No code changes or pull request are needed. "
            + (
                "GitHub issues and attachments are public; your GitHub account is separate from this report."
                if url and urlsplit(url).hostname == "github.com"
                else "Your support account or email address is separate from this report."
            )
            if url or email
            else "1. Save the report on your computer, or copy it below.\n"
            "2. Send it to the person helping you with Linnet, along with what you tried and the message or screen you saw.\n"
            "This build has no public support address configured and cannot send the report automatically."
        ),
    )


def contact_link():
    from urllib.parse import urlencode

    config = sharing()
    if config["url"]:
        return config["url"]
    if config["email"]:
        return (
            "mailto:"
            + config["email"]
            + "?"
            + urlencode(
                dict(
                    subject="Linnet iPod hardware report",
                    body="Please attach linnet-hardware-report.json and describe your iPod, storage changes and the problem.",
                )
            )
        )
    return None
