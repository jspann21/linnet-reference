"""Batch 2 file provisioning. Native Boot installation is a separate transaction."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zlib
from tools.inspect.image import inspect

SLOT_BYTES = 8 * 1024 * 1024
FILES = ('OS0.LOS', 'OS1.LOS', 'STATE0.BIN', 'STATE1.BIN',
         'SCRATCH.BIN', 'BOOT0.BIN', 'BOOT1.BIN')


def record(payload, generation=1):
    if len(payload) > 480 or not 1 <= generation <= 0xffffffff:
        raise ValueError('invalid transactional record')
    data = bytearray(512)
    struct.pack_into('<4sIII', data, 0, b'LTS1', 1, generation, len(payload))
    data[28:28 + len(payload)] = payload
    struct.pack_into('<I', data, 508, zlib.crc32(data[:508]))
    return bytes(data)


def initial_metadata(image):
    identity = inspect(image)
    if len(image) > SLOT_BYTES or identity['load_address'] != 0:
        raise ValueError('persistent image exceeds the RAM staging policy')
    boot = bytearray(32)
    struct.pack_into('<4sIII3B', boot, 0, b'LBS1', 1, 0, 0, 0, 255, 0)
    struct.pack_into('<I', boot, 28, zlib.crc32(boot[:28]))
    payload = bytearray(184)
    struct.pack_into('<4sI', payload, 0, b'LUP1', 1)
    payload[8:40] = boot
    struct.pack_into('<II', payload, 40, len(image), ('release', 'dev', 'trace').index(identity['profile']))
    payload[48:80] = bytes.fromhex(identity['build_id'])
    payload[80:112] = hashlib.sha256(image).digest()
    return record(payload)


def _write_new(path, data, capacity):
    if len(data) > capacity:
        raise ValueError('file capacity exceeded')
    expected = hashlib.sha256()
    with path.open('xb') as stream:
        stream.write(data)
        expected.update(data)
        remaining = capacity - len(data)
        while remaining:
            chunk = bytes(min(65536, remaining))
            stream.write(chunk)
            expected.update(chunk)
            remaining -= len(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    actual = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            actual.update(chunk)
    if path.stat().st_size != capacity or actual.digest() != expected.digest():
        raise OSError('provisioned file readback mismatch: ' + path.name)
    return dict(bytes=capacity, sha256=actual.hexdigest())


def prepare(image_path, directory):
    """Creates an immutable, locally inspectable file set, never accesses a disk."""
    image = image_path.read_bytes()
    identity = inspect(image)
    build = json.loads(image_path.with_suffix('.json').read_text())
    if build.get('kind') != 'os' or build.get('batch',0) < 2 or build.get('build_id') != identity['build_id']:
        raise ValueError('initial provisioning requires the matching Batch 2 OS build report')
    metadata = initial_metadata(image)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    payloads = ((image, SLOT_BYTES), (b'', SLOT_BYTES), (record(b''), 512),
                (record(b''), 512), (b'', 4 * 1024 * 1024), (metadata, 512), (metadata, 512))
    entries = {name: _write_new(directory / name, data, size)
               for name, (data, size) in zip(FILES, payloads)}
    manifest = dict(schema_version=1, target_id='photo4g-p98', image=identity,
                    files=entries, hardware_qualified=False,
                    purpose='Initial empty installation only; boot metadata is copied last.')
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def _mount_identity(mount, serial):
    if os.name != 'nt' or not re.fullmatch(r'[A-Za-z0-9-]{6,32}', serial):
        raise ValueError('provision requires Windows and an explicit physical disk serial')
    resolved = mount.resolve(strict=True)
    if not re.fullmatch(r'[A-Za-z]:\\', str(resolved)):
        raise ValueError('mount must be a drive root')
    letter = resolved.drive[0]
    script = f"""$ErrorActionPreference='Stop'
    $p=Get-Partition -DriveLetter {letter}
    $d=Get-Disk -Number $p.DiskNumber
    $v=Get-Volume -DriveLetter {letter}
    $w=Get-CimInstance Win32_DiskDrive | Where-Object Index -eq $p.DiskNumber
    if ($v.FileSystem -ne 'FAT32' -or $d.LogicalSectorSize -ne 512 -or $w.Model -ne 'Apple iPod USB Device' -or $d.IsBoot -or $d.IsSystem -or $d.BusType -ne 'USB') {{ throw 'Unexpected storage target' }}
    if ($w.SerialNumber.Trim() -ne '{serial}') {{ throw 'Physical serial mismatch' }}
    @{{disk_number=$p.DiskNumber;serial=$w.SerialNumber.Trim();size=$d.Size;partition_offset=$p.Offset;partition_size=$p.Size;volume_id=$v.UniqueId}} | ConvertTo-Json -Compress
    """
    result = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                            capture_output=True, text=True, timeout=15, check=True)
    return resolved, json.loads(result.stdout)


def provision(package, mount, serial):
    package = package.resolve(strict=True)
    manifest = json.loads((package / 'manifest.json').read_text())
    if manifest.get('schema_version') != 1 or manifest.get('target_id') != 'photo4g-p98' or set(manifest.get('files', {})) != set(FILES):
        raise ValueError('invalid provisioning manifest')
    content = {}
    for name in FILES:
        path = package / name
        if path.is_symlink():
            raise ValueError('package links are unsupported')
        data = path.read_bytes()
        entry = manifest['files'][name]
        expected_size = SLOT_BYTES if name.startswith('OS') else 4 * 1024 * 1024 if name == 'SCRATCH.BIN' else 512
        if len(data) != expected_size or entry != dict(bytes=expected_size, sha256=hashlib.sha256(data).hexdigest()):
            raise ValueError('package identity mismatch: ' + name)
        content[name] = data
    length = 128 + struct.unpack_from('<I', content['OS0.LOS'], 20)[0]
    image = content['OS0.LOS'][:length]
    if inspect(image) != manifest['image'] or any(content['OS0.LOS'][length:]) or any(content['OS1.LOS']):
        raise ValueError('initial OS content mismatch')
    if content['BOOT0.BIN'] != initial_metadata(image) or content['BOOT1.BIN'] != content['BOOT0.BIN']:
        raise ValueError('initial metadata mismatch')
    if any(content[name] != record(b'') for name in ('STATE0.BIN', 'STATE1.BIN')) or any(content['SCRATCH.BIN']):
        raise ValueError('initial state/scratch content mismatch')
    root, identity = _mount_identity(mount, serial)
    destination = root / 'LINNET'
    if destination.exists() and (destination.is_symlink() or destination.resolve().parent != root):
        raise ValueError('unsafe LINNET directory')
    if any((destination / name).exists() for name in FILES):
        raise ValueError('existing Batch 2 files require inspection; initial provisioning never overwrites')
    destination.mkdir(exist_ok=True)
    written = {}
    for name in FILES:  # boot records last: unpublished partial preparation remains unbootable
        _, current = _mount_identity(mount, serial)
        if current != identity:
            raise ValueError('disk identity changed during provisioning')
        written[name] = _write_new(destination / name, content[name], len(content[name]))
    return dict(passed=True, disk=identity, files=written, image=manifest['image'],
                requires_safe_eject=True, hardware_qualified=False)
