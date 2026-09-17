"""Guarded recovery and permanent deletion of removed media."""
import json
import os
from pathlib import Path
import uuid

from . import media_manager as media, media_library as library
from .publish import _plain, _volume_guard, _exclusive
from .publish_video import _read_catalog, _encode_catalog, CATALOG_MAX_BYTES


def removals(identity):
    root = Path(identity['root']).resolve(strict=True)
    found = []
    for receipt in media.cache_root(identity).glob('remove-*.json'):
        try:
            report = json.loads(receipt.read_text())
            token = receipt.stem.removeprefix('remove-')
            if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
                continue
            trash = root / 'LINNET' / 'TRASH' / token
            _plain(trash, root)
            if not trash.is_dir():
                continue
            files = media._file_records(trash)
            found.append(dict(id=token, receipt=str(receipt), path=str(trash), bytes=sum(i.st_size for _, i in files),
                              title=', '.join(r['title'] for r in report.get('selected', [])[:3]),
                              started=report.get('started', 0)))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(found, key=lambda r: r['started'], reverse=True)


def recover(identity, token, *, erase=False):
    identity = media.refresh(identity)
    with _exclusive(identity):
        root = Path(identity['root']).resolve(strict=True)
        removal = next((item for item in removals(identity) if item['id'] == token), None)
        if removal is None:
            raise ValueError('This Trash removal changed. Refresh before continuing.')
        trash = Path(removal['path'])
        receipt = Path(removal['receipt'])
        report = json.loads(receipt.read_text())
        if erase:
            # Enumerate guarded ordinary files before deleting any of them.
            files = media._file_records(trash)
            for path, info in files:
                _volume_guard(identity)
                _plain(path, trash)
                current = path.stat()
                if (current.st_size, current.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                    raise ValueError('Trash changed during removal; refresh to continue.')
                path.unlink()
            directories = sorted((p for p in trash.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
            for path in directories:
                _volume_guard(identity)
                _plain(path, trash)
                path.rmdir()
            _volume_guard(identity)
            trash.rmdir()
            report['trash_emptied'] = True
            media._save(receipt, report)
            return dict(receipt=str(receipt), summary='Trash removal permanently deleted. Its storage is now available.')
        moves = []
        # Derive destinations from the guarded removal tree; never trust absolute receipt paths.
        for source, info in media._file_records(trash):
            relative = source.relative_to(trash)
            if relative.as_posix() == 'INDEX.VID.before':
                continue
            allowed = relative.parts[0] in media.KINDS or relative.parts[:2] == ('iPod_Control', 'Music') or relative.as_posix() in ('LINNET/LIBRARY.PDB', 'LINNET/PHOTOS/LIBRARY.PIM', 'LINNET/NOTES/LIBRARY.NNT') or (relative.parent.as_posix() == 'LINNET/VIDEOS' and relative.suffix.lower() in ('.ipv', '.ipvf'))
            if not allowed:
                raise ValueError('Unexpected file in Trash; inspect the report before restoring.')
            destination = root / relative
            _plain(destination, root)
            if destination.exists():
                raise ValueError(f'Cannot restore over an existing file: {relative}. Move that file first.')
            moves.append((source, destination, info))
        catalog, before, entries = library._catalog(root)
        backup = trash / 'INDEX.VID.before'
        restore_entries = []
        restore_paths = {}
        if backup.exists():
            _plain(backup, trash)
            if backup.stat().st_size > CATALOG_MAX_BYTES:
                raise ValueError('Unexpected catalog backup size.')
            old = _read_catalog(backup.read_bytes())
            selected_keys = {r.get('key') for r in report.get('selected', []) if r.get('category') == 'published'}
            restored_paths = {str(d).casefold() for _, d, _ in moves}
            for row in report.get('selected', []):
                if row.get('category') == 'original' and row.get('kind') == 'Videos':
                    path = root / 'Videos' / row['title']
                    _plain(path, root / 'Videos')
                    if path.is_file():
                        restored_paths.add(str(path).casefold())
            for entry in old:
                relative = report.get('catalog_paths', {}).get(entry[0].hex())
                path = library._device_path(root, '/' + relative if relative else entry[1])
                if entry[0].hex() in selected_keys or str(path).casefold() in restored_paths:
                    existing = next((e for e in entries if e[0] == entry[0]), None)
                    if existing is not None and existing != entry:
                        raise ValueError('A newer video uses this library entry. Resolve the conflict before restoring.')
                    if existing is None:
                        if not path.exists() and str(path).casefold() not in restored_paths:
                            raise ValueError('The original video needed for recovery is missing.')
                        restore_entries.append(entry)
                        restore_paths[entry[0]] = path
        data = _encode_catalog(entries + restore_entries) if restore_entries else None
        if data is not None:
            _read_catalog(data)  # Check count, duplicate paths, and keys before restoring any files.
        for source, destination, info in moves:
            _volume_guard(identity)
            _plain(source, trash)
            _plain(destination, root)
            current = source.stat()
            if (current.st_size, current.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                raise ValueError('Trash changed during recovery; refresh to continue.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        if data is not None:
            from .publish_video import device_video_path
            restore_entries = [(key, device_video_path(restore_paths[key], root), title) for key, _, title in restore_entries]
            data = _encode_catalog(entries + restore_entries)
            _read_catalog(data)
            _volume_guard(identity)
            current = catalog.read_bytes() if catalog.exists() else None
            if current != before:
                raise ValueError('Video catalog changed. Files restored; retry to restore playback entries.')
            temporary = catalog.with_name('R' + uuid.uuid4().hex[:7] + '.TMP')
            _plain(temporary, root)
            try:
                with temporary.open('xb') as writer:
                    writer.write(data)
                    writer.flush()
                    os.fsync(writer.fileno())
                if temporary.read_bytes() != data:
                    raise OSError('Restored catalog verification failed.')
                _volume_guard(identity)
                _plain(catalog, root)
                os.replace(temporary, catalog)
                if catalog.read_bytes() != data:
                    raise OSError('Published recovery catalog verification failed.')
            finally:
                if temporary.exists():
                    _volume_guard(identity)
                    temporary.unlink()
        report['restored'] = True
        media._save(receipt, report)
        # Backup is no longer needed only after file and catalog restoration succeeded.
        if backup.exists():
            _volume_guard(identity)
            backup.unlink()
        for path in sorted((p for p in trash.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            _volume_guard(identity)
            _plain(path, trash)
            path.rmdir()
        _volume_guard(identity)
        trash.rmdir()
        return dict(receipt=str(receipt), summary='Content restored. Update the affected categories to refresh their libraries.',
                    requires_update=sorted({row['kind'] for row in report.get('selected', []) if row['kind'] in ('Music', 'Photos', 'Notes')}))
