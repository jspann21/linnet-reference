"""Guarded, unelevated single-video publication with verified previous backup."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from .video import inspect
from .publish import _plain, _hash, _copy_verified, _same_target, _volume_guard, inspect_target
from .publish_photos import _exclusive
MAX_FILE=0x7fffffff

def publish_video(package, *, disk_number, expected_disk_serial,
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
    candidate = inspect(package)
    candidate['bytes']=candidate['file_bytes']
    if candidate['sha256'] != digest:
        raise ValueError('video package changed during validation')
    if _hash(package, candidate['bytes']) != digest:
        raise ValueError('video package changed during reference validation')
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root'])
    if package.drive.casefold() == root.drive.casefold():
        raise ValueError('video package must be staged on a different volume from the iPod')
    with _exclusive(identity):
        return _publish(package, candidate, identity, root, disk_number,
                        expected_disk_serial, expected_volume_serial, expected_drive)


def _publish(package, candidate, identity, root, number, serial, volume, drive):
    def guard():
        _volume_guard(identity)
    linnet, directory = root/'LINNET', root/'LINNET'/'VIDEOS'
    active, backups = directory/'CURRENT.PVD', directory/'BACKUP'
    guard()
    for path in (linnet, directory, active, backups):
        _plain(path, root)
    previous = None
    if active.exists():
        # Preserve exact previous bytes even if its content is corrupt; replacing
        # a damaged package must not require deleting recovery evidence first.
        size = active.stat().st_size
        if not 0 <= size <= MAX_FILE:
            raise ValueError('existing video package exceeds the supported backup size')
        previous = dict(bytes=size, sha256=_hash(active, size))
    needed = candidate['bytes'] + (previous['bytes'] if previous else 0) + 3*65536 + 1024*1024
    if identity['free_bytes'] < needed:
        raise ValueError('insufficient free space for new video package and retained backup')
    _same_target(identity, inspect_target(number, serial, volume, drive))
    receipt_path = package.parent/('publish-videos-'+uuid.uuid4().hex+'.json')
    receipt = dict(operation='publish-videos', passed=False, phase='preflight-complete',
                   identity=identity, candidate_sha256=candidate['sha256'], candidate_bytes=candidate['bytes'],
                   previous=previous, started_at=time.time(),
                   elevation=False, receipt=str(receipt_path),
                   durability='file fsync and complete readback; FAT rename is not a power-loss journal')

    def record():
        with receipt_path.open('w', encoding='utf-8', newline='\n') as writer:
            json.dump(receipt, writer, indent=2)
            writer.write('\n')
            writer.flush()
            os.fsync(writer.fileno())

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
            backup = backups/(previous['sha256'][:8].upper()+'.PVD')
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
            raise RuntimeError('video source package changed during publication')
        _same_target(identity, inspect_target(number, serial, volume, drive))
        guard()
        _plain(active, root)
        if previous:
            if _hash(active, previous['bytes']) != previous['sha256']:
                raise RuntimeError('active video package changed during publication')
        elif active.exists():
            raise RuntimeError('another video package appeared during publication')
        receipt['phase'] = 'replacing-package'
        record()
        os.replace(temporary, active)
        guard()
        with active.open('rb+') as writer:
            writer.flush()
            os.fsync(writer.fileno())
        if _hash(active, candidate['bytes']) != candidate['sha256']:
            raise OSError('published video package readback mismatch')
        receipt.update(passed=True, phase='published', finished_at=time.time(), package=str(active),
                       frames=candidate['frames'])
        record()
        return receipt
    except Exception as exc:
        receipt.update(error=str(exc), finished_at=time.time())
        try:
            record()
        except OSError:
            pass
        raise RuntimeError(f"Video publication stopped in {receipt['phase']}: {exc}. Inspect {receipt_path}; do not replay automatically") from exc
