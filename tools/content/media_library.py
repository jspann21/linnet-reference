"""Browse media locations and remove selected items to recoverable iPod trash."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import time
import uuid

from . import media_manager as manager
from .publish import _plain, _volume_guard
from .publish_photos import _exclusive
from .publish_video import _read_catalog, _encode_catalog


def _device_path(root, value):
    parts = PurePosixPath(value).parts
    if not value.startswith('/') or value.startswith('//') or '\\' in value or ':' in value or any(p in ('..', '.') for p in value.split('/')):
        raise ValueError('Unsafe catalog path')
    if len(parts) < 3 or parts[1].casefold() not in ('videos', 'linnet') or PurePosixPath(value).suffix.lower() not in ('.ipv', '.ipvf', '.pvd', '.pvid'):
        raise ValueError('Unsupported catalog media path')
    path = root.joinpath(*parts[1:])
    _plain(path, root)
    if not path.resolve().is_relative_to(root):
        raise ValueError('Catalog path escaped the iPod')
    return path


def _catalog(root):
    path = root / 'LINNET' / 'VIDEOS' / 'INDEX.VID'
    _plain(path, root)
    if not path.exists():
        return path, None, []
    if path.stat().st_size > 16 + 256 * 416:
        raise ValueError('Video catalog exceeds supported size')
    data = path.read_bytes()
    entries = _read_catalog(data)
    for _, name, _ in entries:
        _device_path(root, name)
    return path, data, entries


def _row(category, kind, title, path, status, **extra):
    info = path.stat() if path.exists() else None
    return dict(id=category + ':' + str(extra.get('key', path)), category=category,
                kind=kind, title=title, path=str(path), source='', status=status,
                bytes=info.st_size if info else 0, mtime_ns=info.st_mtime_ns if info else None,
                removable=category != 'cache', **extra)


def list_items(identity):
    """Read file names, timestamps and the bounded catalog; never decode media."""
    identity = manager.refresh(identity)
    root = Path(identity['root']).resolve(strict=True)
    _, _, entries = _catalog(root)
    result = []
    for kind in manager.KINDS:
        for path, _ in manager._file_records(root / kind):
            if path.suffix.lower() in manager.extensions(kind):
                result.append(_row('original', kind, path.relative_to(root / kind).as_posix(), path,
                    'Original on iPod', description='Removing this source requires updating its folder afterward.'))
    for kind, name in (('Music', 'LINNET/LIBRARY.PDB'), ('Photos', 'LINNET/PHOTOS/LIBRARY.PIM'), ('Notes', 'LINNET/NOTES/LIBRARY.NNT')):
        path = root / name
        _plain(path, root)
        if path.is_file():
            result.append(_row('library', kind, 'Entire published ' + kind.lower() + ' library', path, 'Published library on iPod',
                description='Remove this entire published library. Original source files and cached conversions are retained. Updating this folder can restore it.'))
    published_paths = set()
    for key, name, title in entries:
        path = _device_path(root, name)
        published_paths.add(str(path).casefold())
        managed = path.parent == root / 'LINNET' / 'VIDEOS'
        result.append(_row('published', 'Videos', title, path,
            'Ready on iPod' if path.is_file() else 'Missing published file', key=key.hex(),
            description=('Remove this video from the iPod catalog and move its converted file to Trash.' if managed
                         else 'Remove from the video catalog; the original file is retained.')))
    cache = manager.cache_root(identity)
    names = {}
    try:
        state = json.loads((cache / 'state.json').read_text(encoding='utf-8'))
        for relative in state.get('video_files', {}):
            names[hashlib.sha256(relative.encode()).hexdigest()[:8].upper()] = relative
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    video_dir = cache / 'videos'
    if video_dir.exists():
        _plain(video_dir, Path(video_dir.anchor))
        for path in sorted(video_dir.glob('*.ipvf')):
            _plain(path, cache)
            if not path.is_file():
                continue
            title = names.get(path.name.split('-')[0], path.name)
            result.append(_row('cache', 'Videos', title, path, 'Prepared copy on computer',
                description='Reusable conversion cache. Published videos are listed separately; this file alone does not prove publication.'))
    return result


def remove_items(identity, items):
    """Revalidate selected rows and move their files to trash; retain a recovery receipt."""
    identity = manager.refresh(identity)
    with _exclusive(identity):
        return _remove(identity, items)


def _remove(identity, items):
    root = Path(identity['root']).resolve(strict=True)
    fresh = {row['id']: row for row in list_items(identity)}
    selected = []
    for item in items:
        row = fresh.get(item['id'])
        if row is None or not row['removable']:
            raise ValueError('Selection changed or cannot be removed; refresh the library.')
        if any(row.get(field) != item.get(field) for field in ('path', 'bytes', 'mtime_ns')):
            raise ValueError('Selected file changed; refresh before removing: ' + row['title'])
        if row['id'] not in {r['id'] for r in selected}:
            selected.append(row)
    if not selected:
        raise ValueError('Select an iPod item to remove.')
    catalog, before, entries = _catalog(root)
    selected_keys = {row['key'] for row in selected if row['category'] == 'published'}
    paths = {}
    for row in selected:
        path = Path(row['path'])
        _plain(path, root)
        if row['category'] in ('original', 'library') or path.parent == root / 'LINNET' / 'VIDEOS':
            if path.exists():
                paths[str(path.resolve()).casefold()] = path
    # Removing a cataloged original must also remove its catalog reference.
    remaining = [entry for entry in entries if entry[0].hex() not in selected_keys
                 and str(_device_path(root, entry[1]).resolve()).casefold() not in paths]
    token = uuid.uuid4().hex
    trash = root / 'LINNET' / 'TRASH' / token
    _plain(trash, root)
    receipt = manager.cache_root(identity) / ('remove-' + token + '.json')
    report = dict(operation='remove-media', started=time.time(), complete=False, receipt=str(receipt),
                  trash=str(trash), removed=[], requires_update=sorted({r['kind'] for r in selected if r['category'] == 'original'}),
                  selected=selected, moves=[dict(source=str(p), trash=str(trash / p.relative_to(root))) for p in paths.values()])
    manager._save(receipt, report)
    temporary = None
    temporary_owned = False
    try:
        _volume_guard(identity)
        trash.mkdir(parents=True, exist_ok=False)
        if remaining != entries:
            backup = trash / 'INDEX.VID.before'
            _plain(backup, root)
            with backup.open('xb') as writer:
                writer.write(before); writer.flush(); os.fsync(writer.fileno())
            if backup.read_bytes() != before:
                raise OSError('Video catalog backup verification failed')
            report['catalog_backup'] = str(backup)
            manager._save(receipt, report)
            temporary = catalog.with_name('I' + token[:7].upper() + '.TMP')
            data = _encode_catalog(remaining)
            _plain(temporary, root)
            with temporary.open('xb') as writer:
                temporary_owned = True
                writer.write(data); writer.flush(); os.fsync(writer.fileno())
            if temporary.read_bytes() != data or catalog.read_bytes() != before:
                raise OSError('Video catalog changed during removal')
            _volume_guard(identity)
            _plain(catalog, root)
            os.replace(temporary, catalog)
            if catalog.read_bytes() != data:
                raise OSError('Video catalog removal verification failed')
            report['catalog_updated'] = True
            manager._save(receipt, report)
        for move in report['moves']:
            source, destination = Path(move['source']), Path(move['trash'])
            _volume_guard(identity)
            _plain(source, root); _plain(destination, root)
            expected = next(r for r in selected if Path(r['path']).resolve() == source.resolve())
            info = source.stat()
            if (info.st_size, info.st_mtime_ns) != (expected['bytes'], expected['mtime_ns']):
                raise ValueError('File changed during removal: ' + str(source))
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            report['removed'].append(move)
            manager._save(receipt, report)
        empty = [kind for kind in report['requires_update'] if not any(row['category'] == 'original' and row['kind'] == kind for row in list_items(identity))]
        report['empty_folders'] = empty
        report['complete'] = True
        report['summary'] = f'Removed {len(selected)} selected item(s). Recoverable files and catalog backup: {trash}'
        if report['requires_update']:
            report['summary'] += '. Update ' + ', '.join(report['requires_update']) + ' to rebuild its library.'
        if empty:
            report['summary'] += ' Empty source folders do not clear a published library during Update; select its Entire published library row to remove it.'
        return report
    except Exception as error:
        report['error'] = str(error)
        raise RuntimeError(f'Removal could not finish: {error}. Recovery details: {receipt}') from error
    finally:
        if temporary is not None and temporary_owned:
            try:
                _volume_guard(identity); _plain(temporary, root)
                temporary.unlink(missing_ok=True)
            except Exception as error:
                report['temporary'] = str(temporary)
                report['cleanup_error'] = str(error)
        report['finished'] = time.time()
        manager._save(receipt, report)
