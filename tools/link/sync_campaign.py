"""Explicit Batch2 host FAT32 write/sync/eject/reconnect campaign.

Importing this module performs no device access. The fixed HOSTSYNC.BIN file
is created exclusively and retained as evidence; an existing file is refused.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

from tools.inspect.image import inspect
from tools.studio.native_bootstrap import load_plan
from tools.studio.storage import _mount_identity
from .campaign import connect, _check_healthy_identity, _run_directory, _save
from .eject import eject_reboot, _token_elevated
from .identity import decode
from .storage_observation import wait_for_disk

FILE_BYTES = 1024 * 1024
FILE_NAME = 'HOSTSYNC.BIN'


def _mounted_root(disk_number):
    # disk_number has already been checked as a nonnegative integer.
    script = ("$ErrorActionPreference='Stop'; "
              f"$parts=@(Get-Partition -DiskNumber {disk_number} | Where-Object {{$_.DriveLetter}}); "
              "if($parts.Count -ne 1){throw 'Expected exactly one mounted partition'}; "
              "@{drive=([string]$parts[0].DriveLetter + ':\\')} | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=15, check=True)
    return Path(json.loads(result.stdout)['drive'])


def _fat_partition(mbr):
    entries = []
    for index in range(4):
        entry = mbr[446 + index*16:462 + index*16]
        if entry[4] in (0x0b, 0x0c):
            start, count = struct.unpack_from('<II', entry, 8)
            if not start or not count:
                raise ValueError('reviewed MBR has an empty FAT32 partition')
            entries.append((start*512, count*512))
    if len(entries) != 1:
        raise ValueError('reviewed MBR must identify exactly one FAT32 partition')
    return entries[0]


def _pattern():
    # A fixed algorithm/seed makes this receipt independently reproducible.
    return b''.join(hashlib.sha256(b'Linnet HOSTSYNC\0' + struct.pack('<I', index)).digest()
                    for index in range(FILE_BYTES // 32))


def cycle(root, image_path, port, disk_number, plan_path, plan_sha256, progress=None):
    from .refresh_session import active
    if os.name!='nt' or (not _token_elevated() and active(plan_path, plan_sha256) is None):
        raise RuntimeError('Unattended Disk Mode sync/restart requires a live matching refresh session or an elevated process; no UAC prompt will be requested')
    """Run only when explicitly invoked with an identified disk and pinned plan."""
    if os.name != 'nt' or type(disk_number) is not int or disk_number < 0:
        raise ValueError('host sync campaign requires Windows and an explicit disk number')
    root, image_path, plan_path = Path(root), Path(image_path), Path(plan_path).resolve(strict=True)
    # Complete immutable local preflight before contacting or changing a device.
    image = image_path.read_bytes()
    image_id = inspect(image)
    build = json.loads(image_path.with_suffix('.json').read_text())
    if (image_id['profile'] == 'release' or image_id['load_address'] != 0 or len(image) > 0x800000 or
        build.get('kind') != 'os' or build.get('batch') != 2 or build.get('build_id') != image_id['build_id']):
        raise ValueError('host sync requires the matching Batch2 development OS and build report')
    plan, artifacts, _ = load_plan(plan_path, plan_sha256)
    plan_sha256 = plan_sha256.lower()
    if image_id['target_id'] != plan['image']['target_id']:
        raise ValueError('expected OS target differs from reviewed native Boot plan')
    partition_offset, partition_size = _fat_partition(artifacts['mbr.bin'])
    pattern = _pattern()
    expected_hash = hashlib.sha256(pattern).hexdigest()
    run_id, directory = _run_directory(root, image_id)
    receipt_path = directory / 'receipt.json'
    receipt = dict(run_id=run_id, batch=2, campaign='host-USB-mount-write-sync-eject-reconnect',
                   image=image_id, plan=str(plan_path), plan_sha256=plan_sha256,
                   disk_number=disk_number, started_at=datetime.now(timezone.utc).isoformat(),
                   passed=False, hardware_qualified=False, device_write_attempted=False,
                   state_change_attempted=False, phase='identity', steps=[],
                   file=dict(path='LINNET/'+FILE_NAME, bytes=FILE_BYTES, sha256=expected_hash,
                             algorithm='SHA256("Linnet HOSTSYNC\\0" || LE32(index)), index0..32767'))
    _save(receipt_path, receipt)
    session = None

    def record(name, **details):
        receipt['phase'] = name
        event = dict(name=name, **details)
        receipt['steps'].append(event)
        _save(receipt_path, receipt)
        if progress:
            progress(dict(run_id=run_id, **event))

    def mounted():
        mount, identity = _mount_identity(_mounted_root(disk_number), plan['expected_storage_serial'])
        if (identity.get('disk_number') != disk_number or identity.get('serial') != plan['expected_storage_serial'] or
            identity.get('size') != plan['expected_device_bytes'] or
            identity.get('partition_offset') != partition_offset or identity.get('partition_size') != partition_size or
            not identity.get('volume_id')):
            raise RuntimeError('mounted disk/partition identity differs from reviewed plan')
        return mount, identity

    try:
        session, device, observed = connect(port=port, serial_number=plan['expected_linnet_usb_serial'])
        _check_healthy_identity(observed, image_id)
        status = decode(session.status())
        _check_healthy_identity(status, image_id)
        if status['generation'] != observed['generation']:
            raise RuntimeError('OS generation changed before disk-mode request')
        record('before', device=device, identity=status)
        receipt['state_change_attempted'] = True
        record('disk-mode-requested')
        session.reboot('disk')  # Never replay this command after an uncertain ACK.
        session.close()
        session = None
        observation = wait_for_disk(plan['expected_storage_serial'], 30)
        mount, identity = mounted()
        record('mounted', observation=observation, identity=identity, mount=str(mount))
        destination = mount / 'LINNET'
        if (not destination.is_dir() or destination.is_symlink() or
            destination.resolve(strict=True).parent != mount.resolve(strict=True)):
            raise ValueError('expected existing LINNET directory on identified volume')
        target = destination / FILE_NAME
        if target.exists() or target.is_symlink():
            raise FileExistsError('HOSTSYNC.BIN already exists; campaign never overwrites or deletes evidence')
        checked_mount, checked_identity = mounted()
        if checked_mount != mount or checked_identity != identity:
            raise RuntimeError('mounted identity changed before file creation')
        receipt['device_write_attempted'] = True
        record('host-write-started', path=str(target))
        with target.open('xb') as stream:
            for offset in range(0, len(pattern), 65536):
                block = pattern[offset:offset+65536]
                if stream.write(block) != len(block):
                    raise OSError('short host file write')
            stream.flush()
            os.fsync(stream.fileno())
        record('host-file-synced', bytes=FILE_BYTES)
        digest, received = hashlib.sha256(), 0
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(65536), b''):
                received += len(block)
                if received > FILE_BYTES:
                    raise OSError('host file grew beyond deterministic write size')
                digest.update(block)
        if received != FILE_BYTES or digest.hexdigest() != expected_hash:
            raise OSError('host file readback mismatch')
        checked_mount, checked_identity = mounted()
        if checked_mount != mount or checked_identity != identity:
            raise RuntimeError('mounted identity changed during write/readback')
        record('host-readback', bytes=received, sha256=digest.hexdigest())
        # Reload pinned artifacts immediately before the reviewed refresh/eject.
        load_plan(plan_path, plan_sha256)
        record('eject-requested')
        result = eject_reboot(disk_number, plan_path, plan_sha256, expected_os=image_id, allow_prompt=False)
        _check_healthy_identity(result['identity'], image_id)
        if result.get('reboot_verified') is not True or result.get('link_reconnected') is not True:
            raise RuntimeError('eject did not prove expected OS reconnection')
        record('expected-os-reconnected', eject=result)
        receipt['passed'] = True
        receipt['scope'] = 'Host file write, fsync, immediate readback, safe eject and exact OS reconnect.'
        receipt['phase'] = 'complete'
    except Exception as exc:
        receipt['error'] = dict(type=type(exc).__name__, message=str(exc),
                                guidance='Inspect retained receipt and device state; never replay uncertain commands automatically.')
        raise
    finally:
        try:
            if session:
                session.close()
        finally:
            receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
            _save(receipt_path, receipt)
    return dict(receipt=str(receipt_path), **receipt)
