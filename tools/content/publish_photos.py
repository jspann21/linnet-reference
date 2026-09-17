"""Guarded, unelevated PIMG publication to an explicitly identified iPod.

The verified package replaces LIBRARY.PIM last, after its previous bytes have a
verified backup. Existing optional JPEG references must already match on-device.
No raw device access, UAC, eject, automatic retry, rollback or cleanup is used.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import time
import uuid
import zlib

from .photos import HEADER, PHOTO, MAX_FILE, inspect
from .publish import (_plain, _bounded, _hash, _copy_verified, _same_target,
                      _volume_guard, inspect_target, _exclusive, _write_receipt)


def _fallbacks(package):
    """Extract only already-validated, bounded optional device references."""
    result = {}
    with package.open('rb') as reader:
        header = reader.read(HEADER)
        count, offset = struct.unpack_from('<I', header, 20)[0], struct.unpack_from('<I', header, 36)[0]
        pool_offset, pool_bytes = struct.unpack_from('<II', header, 48)
        reader.seek(pool_offset)
        pool = reader.read(pool_bytes)
        for index in range(count):
            reader.seek(offset+index*PHOTO)
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
                   expected_volume_serial, expected_drive=None):
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
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root'])
    if package.drive.casefold() == root.drive.casefold():
        raise ValueError('photo package must be staged on a different volume from the iPod')
    with _exclusive(identity):
        return _publish(package, candidate, references, identity, root, disk_number,
                        expected_disk_serial, expected_volume_serial, expected_drive)


def _publish(package, candidate, references, identity, root, number, serial, volume, drive):
    def guard():
        _volume_guard(identity)
    linnet, directory = root/'LINNET', root/'LINNET'/'PHOTOS'
    active, backups = directory/'LIBRARY.PIM', directory/'BACKUP'
    guard()
    for path in (linnet, directory, active, backups):
        _plain(path, root)
    _verify_fallbacks(references, root, guard)
    previous = None
    if active.exists():
        # Preserve exact previous bytes even if its content is corrupt; replacing
        # a damaged package must not require deleting recovery evidence first.
        size = active.stat().st_size
        if not 0 <= size <= MAX_FILE:
            raise ValueError('existing photo package exceeds the supported backup size')
        previous = dict(bytes=size, sha256=_hash(active, size))
    needed = candidate['bytes'] + (previous['bytes'] if previous else 0) + 3*65536 + 1024*1024
    if identity['free_bytes'] < needed:
        raise ValueError('insufficient free space for new photo package and retained backup')
    _same_target(identity, inspect_target(number, serial, volume, drive))
    receipt_path = package.parent/('publish-photos-'+uuid.uuid4().hex+'.json')
    receipt = dict(operation='publish-photos', passed=False, phase='preflight-complete',
                   identity=identity, candidate_sha256=candidate['sha256'], candidate_bytes=candidate['bytes'],
                   previous=previous, fallback_files=references, started_at=time.time(),
                   elevation=False, receipt=str(receipt_path),
                   durability='file fsync and complete readback; FAT rename is not a power-loss journal')

    def record():
        _write_receipt(receipt_path, receipt)

    record()
    try:
        for path in (linnet, directory, backups):
            guard()
            _plain(path, root)
            path.mkdir(exist_ok=True)
            _plain(path, root)
        if previous:
            receipt['phase'] = 'backing-up-previous'
            record()
            backup = backups/(previous['sha256'][:8].upper()+'.PIM')
            _copy_verified(active, backup, previous, root, guard)
            receipt['backup'] = str(backup)
        temporary = directory/('P'+uuid.uuid4().hex[:7].upper()+'.TMP')
        receipt.update(phase='copying-candidate', temporary=str(temporary))
        record()
        _plain(package, Path(package.anchor))
        _copy_verified(package, temporary, candidate, root, guard)
        receipt['phase'] = 'candidate-verified'
        record()
        _plain(package, Path(package.anchor))
        if _hash(package, candidate['bytes']) != candidate['sha256']:
            raise RuntimeError('photo source package changed during publication')
        _verify_fallbacks(references, root, guard)
        _same_target(identity, inspect_target(number, serial, volume, drive))
        guard()
        _plain(active, root)
        if previous:
            if _hash(active, previous['bytes']) != previous['sha256']:
                raise RuntimeError('active photo package changed during publication')
        elif active.exists():
            raise RuntimeError('another photo package appeared during publication')
        receipt['phase'] = 'replacing-package'
        record()
        os.replace(temporary, active)
        guard()
        with active.open('rb+') as writer:
            writer.flush()
            os.fsync(writer.fileno())
        if _hash(active, candidate['bytes']) != candidate['sha256']:
            raise OSError('published photo package readback mismatch')
        receipt.update(passed=True, phase='published', finished_at=time.time(), package=str(active),
                       photos=candidate['photos'], albums=candidate['albums'])
        record()
        return receipt
    except Exception as exc:
        receipt.update(error=str(exc), finished_at=time.time())
        try:
            record()
        except OSError:
            pass
        raise RuntimeError(f"Photo publication stopped in {receipt['phase']}: {exc}. Inspect {receipt_path}; do not replay automatically") from exc
