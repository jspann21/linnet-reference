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
from .publish import (_plain, _bounded, _hash, _copy_verified, inspect_target, _exclusive,
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


def _publish_packs(packs, identity, root, candidate_bytes, grid_bytes):
    """Publish immutable tile packs before either catalog can name them."""
    from .publish import _same_target

    if not packs:
        return []

    directory = root/'.LINNET'/'PHOTOS'/'PACKS'
    guard = lambda: _volume_guard(identity)
    pending = []
    verified_existing = {}
    distinct = {}
    for item in packs:
        source = Path(item['path'])
        _plain(source, Path(source.anchor))
        suffix = item['sha256'][:16].upper()
        expected = f'/.LINNET/PHOTOS/PACKS/{suffix[:8]}/{suffix[8:]}.PAK'
        if item['device_path'] != expected or not 0 < item['bytes'] <= 1 << 27:
            raise ValueError('invalid staged photo pack identity')
        active = root.joinpath(*expected.lstrip('/').split('/'))
        _plain(active, root)
        previous = distinct.get(active)
        if previous is not None:
            if (previous['bytes'], previous['sha256']) != (item['bytes'], item['sha256']):
                raise ValueError('different photo packs share one immutable name')
            continue
        distinct[active] = item
        guard()
        if active.exists():
            before = _pack_stamp(active)
            if _hash(active, item['bytes']) != item['sha256']:
                raise ValueError(f'photo pack name collision or changed iPod bytes: {active}')
            after = _pack_stamp(active)
            if before != after:
                raise OSError(f'photo pack changed during verification: {active}')
            verified_existing[active] = after
        else:
            pending.append(item)
    needed = sum(item['bytes'] for item in pending) + (2*1024*1024 if pending else 0)
    if identity['free_bytes'] < needed:
        raise ValueError('insufficient iPod space for photo packs and catalogs')
    results = []
    for active, item in distinct.items():
        guard()
        source = Path(item['path'])
        if _hash(source, item['bytes']) != item['sha256']:
            raise ValueError(f'staged photo pack changed: {source}')
        reused = active.exists()
        if not reused:
            for part in (root/'.LINNET', root/'.LINNET'/'PHOTOS', directory, active.parent):
                guard(); _plain(part, root); part.mkdir(exist_ok=True)
            temporary = active.parent/('P'+os.urandom(4).hex().upper()[:7]+'.TMP')
            _plain(temporary, root)
            _copy_verified(source, temporary, item, root, guard)
            guard()
            if active.exists():
                raise RuntimeError(f'photo pack appeared during publication: {active}')
            os.rename(temporary, active)
        guard()
        _plain(active, root)
        if reused:
            stamp = _pack_stamp(active)
            if stamp != verified_existing[active]:
                raise OSError(f'photo pack changed after verification: {active}')
        else:
            before = _pack_stamp(active)
            if _hash(active, item['bytes']) != item['sha256']:
                raise OSError(f'photo pack readback mismatch: {active}')
            stamp = _pack_stamp(active)
            if before != stamp:
                raise OSError(f'photo pack changed during readback: {active}')
        results.append(dict(path=item['device_path'].lstrip('/'), package=str(active),
                            bytes=item['bytes'], sha256=item['sha256'], reused=reused, stamp=stamp))
    _same_target(identity, inspect_target(identity['disk_number'], identity['disk_serial'],
                                          identity['volume_serial'], identity['drive']))
    return results


def _pack_stamp(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _verify_pack_proofs(results, identity, root):
    for item in results:
        _volume_guard(identity)
        path = Path(item['package'])
        _plain(path, root)
        if _pack_stamp(path) != item['stamp']:
            raise OSError(f"photo pack changed after readback: {path}")


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
    from .media_manager import _identify
    target = identity.get('native_target_id') or _identify(identity)['target_id']
    if candidate['version'] != (0 if target == 'photo4g-p98' else 1):
        raise ValueError('photo package layout differs from the device target')
    if package.drive.casefold() == root.drive.casefold():
        raise ValueError('photo package must be staged on a different volume from the iPod')
    if grid is not None and grid.drive.casefold() == root.drive.casefold():
        raise ValueError('native photo grid must be staged on a different volume from the iPod')
    with _exclusive(identity):
        pack_results = _publish_packs(candidate.get('packs', []), identity, root, candidate['bytes'],
                                      grid_candidate['bytes'] if grid_candidate else 0)
        if grid is not None:
            return _publish_pair(package, candidate, references, grid, grid_candidate, identity, root,
                                 disk_number, expected_disk_serial, expected_volume_serial, expected_drive, pack_results)
        receipt = _publish(package, candidate, references, identity, root, disk_number,
                           expected_disk_serial, expected_volume_serial, expected_drive,
                           retain_backup=bool(pack_results), receipt_fields=dict(packs=pack_results))
        try:
            _verify_pack_proofs(pack_results, identity, root)
        except Exception as exc:
            receipt.update(passed=False, phase='pack-verification-failed', error=str(exc))
            _write_receipt(Path(receipt['receipt']), receipt)
            raise
        if pack_results:
            _finish_backups(receipt, [Path(value) for value in receipt.get('backups_retained', [])], root,
                            lambda: _volume_guard(identity), host_root=package.parent)
            _write_receipt(Path(receipt['receipt']), receipt)
        return receipt


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
                  number, serial, volume, drive, pack_results):
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
                           receipt_fields=dict(grid=grid_receipt, packs=pack_results))
    except Exception as exc:
        raise RuntimeError(f"Photo pair stopped after native grid publication; inspect {grid_receipt['receipt']} and the PIMG receipt. Do not replay automatically: {exc}") from exc
    try:
        _verify_pack_proofs(pack_results, identity, root)
    except Exception as exc:
        receipt.update(passed=False, phase='pack-verification-failed', error=str(exc))
        _write_receipt(Path(receipt['receipt']), receipt)
        raise
    # Both guarded readbacks and all pack proofs have succeeded; recovery copies remain until here.
    for result, staged in ((grid_receipt, grid), (receipt, package)):
        _finish_backups(result, [Path(value) for value in result.get('backups_retained',[])], root,
                        lambda: _volume_guard(identity), host_root=staged.parent)
        _write_receipt(Path(result['receipt']), result)
    return receipt
