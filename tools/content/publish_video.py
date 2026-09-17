"""Guarded, unelevated single-video publication with verified previous backup."""
import hashlib
import os
import ctypes
from pathlib import Path
import time
import uuid
from .ipvf_validate import inspect_file
from .publish import _plain, _hash, _copy_verified, _same_target, _volume_guard, inspect_target, _exclusive, _write_receipt, _write_verified
from .video_catalog import encode as _encode_catalog, decode as _read_catalog, read_file as _read_catalog_file
MAX_FILE=0x7fffffff


def video_filename(title):
    """A Windows/FAT-safe name; collisions are resolved against the actual folder."""
    name = Path(str(title).replace('\\', '/')).stem
    name = ''.join(c if ord(c) >= 32 and c not in '<>:"/\\|?*' else '_' for c in name)
    name = name[:160].strip(' .') or 'Video'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + name
    return name + '.ipvf'


def _catalog_title(value):
    label = ''.join(c if ord(c) >= 32 else ' ' for c in str(value)).strip() or 'Video'
    return label.encode('utf-8')[:127].decode('utf-8', errors='ignore')


def device_video_path(source, root):
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(source), buffer, len(buffer)):
        raise OSError('Could not resolve the video FAT short path')
    path = '/' + Path(buffer.value).relative_to(root).as_posix()
    _read_catalog(_encode_catalog([(bytes(32), path, 'Video')]))
    return path


def _target_profile(root):
    from tools.inspect.retail_device import detect
    from tools.studio.targets import TARGETS
    detected = detect(root)
    spec = TARGETS[detected["target_id"]]
    return (spec["media_video_width"], spec["media_video_height"],
            spec["storage_max_read_sectors"])


def _target_check(candidate, root):
    width, height, sectors = _target_profile(root)
    if (candidate.get("width"), candidate.get("height")) != (width, height):
        raise ValueError("video geometry does not match the selected iPod target")
    maximum = candidate["max_record_sectors"]
    if not 1 <= maximum <= sectors:
        raise ValueError("video record size exceeds the selected iPod target")

def publish_video(package, *, disk_number, expected_disk_serial,
                   expected_volume_serial, expected_drive=None, library_key=None, title=None):
    """Validate all local bytes, preserve the previous package, publish last.

    A failure after replacement is an uncertain publication; inspect the host
    receipt and retained package/backup instead of automatically replaying it.
    The iPod must remain exclusively in Disk Mode throughout the operation.
    """
    package = Path(os.path.abspath(package))
    _plain(package, Path(package.anchor))
    package = package.resolve(strict=True)
    digest = _hash(package)
    candidate = inspect_file(package)
    candidate['sha256'] = digest
    candidate['format'] = 'IPVF'
    candidate['bytes']=candidate['file_bytes']
    if _hash(package, candidate['bytes']) != digest:
        raise ValueError('video package changed during reference validation')
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root'])
    _target_check(candidate, root)
    if package.drive.casefold() == root.drive.casefold():
        raise ValueError('video package must be staged on a different volume from the iPod')
    with _exclusive(identity):
        return _publish(package, candidate, identity, root, disk_number,
                        expected_disk_serial, expected_volume_serial, expected_drive, library_key, title)


def _publish(package, candidate, identity, root, number, serial, volume, drive, library_key=None, title=None):
    def guard():
        _volume_guard(identity)
    linnet, directory = root/'LINNET', root/'LINNET'/'VIDEOS'
    key = hashlib.sha256(str(library_key if library_key is not None else package.stem).encode('utf-8')).digest()
    filename = video_filename(title or package.stem)
    active, backups = directory/filename, directory/'BACKUP'
    catalog = directory/'INDEX.VID'
    catalog_before = None
    _plain(catalog, root)
    entries = []
    if catalog.exists():
        catalog_before, entries = _read_catalog_file(catalog)
    existing = next((root / entry[1].lstrip('/') for entry in entries if entry[0] == key), None)
    if existing is not None and existing.is_file() and existing.parent == directory:
        active = existing.resolve()
    elif active.exists():
        active = directory / (Path(filename).stem + ' [' + key.hex()[:8] + '].ipvf')
        if active.exists():
            raise ValueError('Video filename already exists; rename the source first')
    path = '/LINNET/VIDEOS/' + key.hex()[:8].upper() + '.IPV'
    for entry in entries:
        if entry[1].casefold() == path.casefold() and entry[0] != key:
            raise ValueError('video library filename collision; use a different library key')
    entries = [entry for entry in entries if entry[0] != key]
    label = _catalog_title(title or package.stem)
    entries.append((key, path, label))
    if len(entries)>256:
        raise ValueError('video library supports up to 256 videos')
    entries.sort(key=lambda entry: (entry[2].casefold(), entry[1]))
    catalog_bytes = _encode_catalog(entries)
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
            backup = backups/(previous['sha256'][:8].upper()+'.IPV')
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
        path = device_video_path(active, root)
        entries = [(k, path if k == key else p, t) for k, p, t in entries]
        catalog_bytes = _encode_catalog(entries)
        receipt['phase'] = 'publishing-catalog'
        record()
        _plain(catalog, root)
        if (catalog.read_bytes() if catalog.exists() else None) != catalog_before:
            raise RuntimeError('video catalog changed during publication')
        if catalog_before is not None:
            saved = backups/(hashlib.sha256(catalog_before).hexdigest()[:8].upper()+'.VID')
            _plain(saved, root)
            if saved.exists():
                if saved.read_bytes() != catalog_before:
                    raise RuntimeError('video catalog backup collision')
            else:
                _write_verified(saved, catalog_before, 'video catalog backup readback mismatch')
            if saved.read_bytes()!=catalog_before:
                raise OSError('video catalog backup readback mismatch')
        temp_index = directory/('I'+uuid.uuid4().hex[:7].upper()+'.TMP')
        guard(); _plain(temp_index, root)
        _write_verified(temp_index, catalog_bytes, 'video catalog readback mismatch')
        guard(); _plain(catalog, root)
        os.replace(temp_index, catalog)
        if catalog.read_bytes()!=catalog_bytes:
            raise OSError('published video catalog readback mismatch')
        receipt['catalog'] = str(catalog)
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


def index_ipvf(source, *, disk_number, expected_disk_serial,
               expected_volume_serial, expected_drive=None, library_key=None, title=None):
    """Validate an existing iPod IPVF and publish only its bounded 8.3 catalog path."""
    source = Path(os.path.abspath(source))
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root']).resolve(strict=True)
    _plain(source, root)
    source = source.resolve(strict=True)
    if not source.is_relative_to(root) or source.suffix.lower() not in ('.ipvf', '.ipv'):
        raise ValueError('native IPVF source must already be on this iPod')
    before = source.stat()
    candidate = inspect_file(source)
    _target_check(candidate, root)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('IPVF changed during validation')
    path = device_video_path(source, root)
    key = hashlib.sha256(str(library_key or source.relative_to(root)).replace('\\', '/').encode('utf-8')).digest()
    label = _catalog_title(title or source.stem)
    catalog = root/'LINNET'/'VIDEOS'/'INDEX.VID'
    backups = root/'LINNET'/'VIDEOS'/'BACKUP'
    receipt_path = Path(os.environ.get('LOCALAPPDATA', source.parent))/'Linnet'/'Media'/('index-ipvf-'+uuid.uuid4().hex+'.json')
    receipt = dict(operation='index-ipvf', passed=False, phase='validated', identity=identity,
                   source=str(source), device_path=path, frames=candidate['frames'], media_id=candidate['media_id'],
                   started_at=time.time(), receipt=str(receipt_path))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    def record():
        _write_receipt(receipt_path, receipt)
    record()
    with _exclusive(identity):
        try:
            _volume_guard(identity); _plain(catalog, root); _plain(backups, root)
            previous, entries = _read_catalog_file(catalog) if catalog.exists() else (None, [])
            entries = [entry for entry in entries if entry[0] != key]
            if any(entry[1].casefold() == path.casefold() for entry in entries):
                raise ValueError('IPVF path is already cataloged under a different library key')
            entries.append((key, path, label)); entries.sort(key=lambda entry: (entry[2].casefold(), entry[1]))
            if len(entries) > 256: raise ValueError('video library supports up to 256 videos')
            data = _encode_catalog(entries)
            _same_target(identity, inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive))
            backups.mkdir(parents=True, exist_ok=True)
            if previous is not None:
                saved = backups/(hashlib.sha256(previous).hexdigest()[:8].upper()+'.VID')
                if saved.exists() and saved.read_bytes() != previous: raise RuntimeError('video catalog backup collision')
                if not saved.exists():
                    _write_verified(saved, previous, 'video catalog backup readback mismatch')
            temporary = catalog.parent/('I'+uuid.uuid4().hex[:7].upper()+'.TMP')
            _write_verified(temporary, data, 'video catalog staging readback mismatch')
            _volume_guard(identity); os.replace(temporary, catalog)
            if catalog.read_bytes() != data: raise OSError('video catalog readback mismatch')
            receipt.update(passed=True, phase='published', finished_at=time.time(), catalog=str(catalog)); record(); return receipt
        except Exception as exc:
            receipt.update(error=str(exc), finished_at=time.time()); record()
            raise RuntimeError(f"IPVF indexing stopped in {receipt['phase']}: {exc}. Inspect {receipt_path}; do not replay automatically") from exc
