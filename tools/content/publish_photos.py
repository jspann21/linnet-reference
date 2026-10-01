"""Guarded, unelevated PIMG publication to an explicitly identified iPod.

The verified package replaces LIBRARY.PIM last, after its previous bytes have a
verified backup. Existing optional JPEG references must already match on-device.
No raw device access, UAC, eject, automatic retry, rollback or cleanup is used.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import struct
import zlib

from .photos import HEADER, PHOTO, MAX_FILE, inspect
from .publish import (_plain, _bounded, _hash, inspect_target, _exclusive,
                      _publish_library, _volume_guard, _finish_backups, _write_receipt)


def _fallbacks(package):
    """Extract only already-validated, bounded optional device references."""
    result = {}
    with package.open('rb') as reader:
        header = reader.read(HEADER)
        count, offset = struct.unpack_from('<I', header, 20)[0], struct.unpack_from('<I', header, 36)[0]
        pool_offset, pool_bytes = struct.unpack_from('<II', header, 48)
        reader.seek(pool_offset)
        pool = reader.read(pool_bytes)
        reader.seek(offset)
        for _ in range(count):
            photo = reader.read(PHOTO)
            start, length = struct.unpack_from('<II', photo, 12)
            if not length:
                continue
            path = pool[start:start+length].decode('ascii')
            size, crc = struct.unpack_from('<II', photo, 44)
            item = dict(path=path, bytes=size, crc32=crc)
            if path in result and result[path] != item:
                raise ValueError('conflicting JPEG fallback references in the package')
            result[path] = item
    return list(result.values())


def _verify_fallbacks(items, root, guard):
    for item in items:
        guard()
        path = root.joinpath(*item['path'].lstrip('/').split('/'))
        _plain(path, root)
        digest = _hash(path, item['bytes'])
        data = _bounded(path, 262144)
        if (len(data) != item['bytes'] or zlib.crc32(data) & 0xffffffff != item['crc32'] or
            hashlib.sha256(data).hexdigest() != digest):
            raise ValueError(f"existing JPEG fallback differs: {item['path']}")


def publish_photos(package, *, disk_number, expected_disk_serial,
                   expected_volume_serial, expected_drive=None, grid=None):
    """Validate all local bytes, preserve the previous package, publish last.

    A failure after replacement is an uncertain publication; inspect the host
    receipt and retained package/backup instead of automatically replaying it.
    The iPod must remain exclusively in Disk Mode throughout the operation.
    """
    package = Path(os.path.abspath(package))
    _plain(package, Path(package.anchor))
    package = package.resolve(strict=True)
    digest = _hash(package)
    candidate = inspect(package, verify_payloads=True)
    if candidate['sha256'] != digest:
        raise ValueError('photo package changed during validation')
    references = _fallbacks(package)
    if _hash(package, candidate['bytes']) != digest:
        raise ValueError('photo package changed during reference validation')
    grid_candidate = None
    if grid is not None:
        from .photo_grid import inspect_grid
        grid = Path(os.path.abspath(grid))
        _plain(grid, Path(grid.anchor));grid = grid.resolve(strict=True)
        grid_digest = _hash(grid)
        grid_candidate = inspect_grid(grid, package=package)
        if grid_candidate['sha256'] != grid_digest:
            raise ValueError('native photo grid changed during validation')
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root'])
    if package.drive.casefold() == root.drive.casefold():
        raise ValueError('photo package must be staged on a different volume from the iPod')
    if grid is not None and grid.drive.casefold() == root.drive.casefold():
        raise ValueError('native photo grid must be staged on a different volume from the iPod')
    with _exclusive(identity):
        if grid is not None:
            return _publish_pair(package, candidate, references, grid, grid_candidate, identity, root,
                                 disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
        return _publish(package, candidate, references, identity, root, disk_number,
                        expected_disk_serial, expected_volume_serial, expected_drive)


def _publish(package, candidate, references, identity, root, number, serial, volume, drive,
             receipt_fields=None, **options):
    return _publish_library(
        package, candidate, identity, root, number, serial, volume, drive,
        kind="photos", label="photo", filename="LIBRARY.PIM", max_file=MAX_FILE,
        summary=dict(photos=candidate['photos'], albums=candidate['albums']),
        verify_references=lambda root, guard: _verify_fallbacks(references, root, guard),
        receipt_fields=dict(fallback_files=references, **(receipt_fields or {})),
        backup_on_host=True, **options)


def _publish_pair(package, candidate, references, grid, grid_candidate, identity, root,
                  number, serial, volume, drive):
    from .media_manager import _identify
    target = identity.get('native_target_id') or _identify(identity)['target_id']
    if target != grid_candidate['target']:
        raise ValueError('native photo grid target differs from the iPod')
    previous, needed = {}, 0
    host_backup_space = {}
    for name, item, staged in (('GRID.PGR', grid_candidate, grid), ('LIBRARY.PIM', candidate, package)):
        _volume_guard(identity)
        active = root/'.LINNET'/'PHOTOS'/name
        _plain(active, root)
        hint = None
        if active.exists():
            info = active.stat()
            if not 0 <= info.st_size <= MAX_FILE:
                raise ValueError('existing photo output exceeds the supported backup size')
            hint = dict(bytes=info.st_size, sha256=_hash(active, info.st_size),
                        stamp=(info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_ino))
        previous[name] = hint
        if hint is None or (hint['bytes'],hint['sha256']) != (item['bytes'],item['sha256']):
            needed += item['bytes']+3*65536+1024*1024
            if hint is not None:
                location = staged.parent
                host_device = location.stat().st_dev
                representative, required = host_backup_space.get(host_device, (location, 0))
                host_backup_space[host_device] = (representative, required + hint['bytes'])
    if identity['free_bytes'] < needed:
        raise ValueError('insufficient free space for both photo outputs and retained backups')
    for location, required in host_backup_space.values():
        if shutil.disk_usage(location).free < required + 1024*1024:
            raise ValueError('insufficient computer space for both previous photo outputs')
    grid_receipt = _publish_library(
        grid, grid_candidate, identity, root, number, serial, volume, drive,
        kind='photos', label='native photo grid', filename='GRID.PGR', max_file=MAX_FILE,
        summary=dict(photos=grid_candidate['photos'],target=grid_candidate['target']),
        previous_hint=previous['GRID.PGR'], retain_backup=True, backup_on_host=True)
    try:
        receipt = _publish(package, candidate, references, identity, root, number, serial, volume, drive,
                           previous_hint=previous['LIBRARY.PIM'], retain_backup=True,
                           receipt_fields=dict(grid=grid_receipt))
    except Exception as exc:
        raise RuntimeError(f"Photo pair stopped after native grid publication; inspect {grid_receipt['receipt']} and the PIMG receipt. Do not replay automatically: {exc}") from exc
    # Both guarded readbacks have succeeded; recovery copies remain until here.
    for result, staged in ((grid_receipt, grid), (receipt, package)):
        _finish_backups(result, [Path(value) for value in result.get('backups_retained',[])], root,
                        lambda: _volume_guard(identity), host_root=staged.parent)
        _write_receipt(Path(result['receipt']), result)
    return receipt
