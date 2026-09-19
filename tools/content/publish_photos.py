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
import zlib

from .photos import HEADER, PHOTO, MAX_FILE, inspect
from .publish import (_plain, _bounded, _hash, inspect_target, _exclusive,
                      _publish_library)


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
    return _publish_library(
        package, candidate, identity, root, number, serial, volume, drive,
        kind="photos", label="photo", filename="LIBRARY.PIM", max_file=MAX_FILE,
        summary=dict(photos=candidate['photos'], albums=candidate['albums']),
        verify_references=lambda root, guard: _verify_fallbacks(references, root, guard),
        receipt_fields=dict(fallback_files=references))
