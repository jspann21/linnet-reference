"""Browse media locations and remove selected items to recoverable iPod trash."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
from pathlib import Path, PurePosixPath
import time
import uuid

from . import media_manager as manager
from .host_state import cache_root, save_json
from .inventory import collect_records_by_kind, skipped_paths, scan as scan_sources
from .guard import guarded_path as _plain, guard_volume as _volume_guard, hash_file
from .publish import _bounded, _exclusive, _write_verified, _finish_backups
from .video_catalog import encode as _encode_catalog, read_file as _read_catalog_file


def _device_path(root, value):
    parts = PurePosixPath(value).parts
    if not value.startswith('/') or value.startswith('//') or '\\' in value or ':' in value or any(p in ('..', '.') for p in value.split('/')):
        raise ValueError('Unsafe catalog path')
    media_folder = len(parts) >= 3 and (parts[1].casefold() in ('videos', '.linnet') or
                   (len(parts) >= 4 and parts[1].casefold() in ('ipod_control', 'ipod_c~1')
                    and parts[2].casefold() == 'music'))
    if not media_folder or PurePosixPath(value).suffix.lower() not in ('.ipv', '.ipvf', '.mp4', '.m4v', '.mov'):
        raise ValueError('Unsupported catalog media path')
    path = root.joinpath(*parts[1:])
    _plain(path, root)
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Catalog path escaped the iPod')
    return resolved


def _catalog(root, *, with_paths=False):
    path = root / '.LINNET' / 'VIDEOS' / 'INDEX.VID'
    _plain(path, root)
    if not path.exists():
        return (path, None, [], []) if with_paths else (path, None, [])
    data, entries = _read_catalog_file(path)
    resolved = [_device_path(root, name) for _, name, _ in entries]
    return (path, data, entries, resolved) if with_paths else (path, data, entries)


def _row(category, kind, title, path, status, *, info=None, **extra):
    if info is None:
        try:
            info = path.stat()
        except FileNotFoundError:
            pass
    return dict(id=category + ':' + str(extra.get('key', path)), category=category,
                kind=kind, title=title, path=str(path), source='', status=status,
                bytes=info.st_size if info else 0, mtime_ns=info.st_mtime_ns if info else None,
                removable=category != 'cache', **extra)


def list_items(identity, *, records_by_kind=None, retail_photos=None, retail_tracks=None,
               _validated_identity=False):
    """Read file names, timestamps and the bounded catalog; never decode media."""
    if not _validated_identity:
        identity = manager.refresh(identity)
    root = Path(identity['root']).resolve(strict=True)
    if records_by_kind is None:
        records_by_kind = collect_records_by_kind(root)
    _, _, entries, resolved_videos = _catalog(root, with_paths=True)
    published_paths = {str(path).casefold() for path in resolved_videos}
    source_video_extensions = manager.video_source_extensions(identity)
    native_video_extensions = manager.native_video_extensions(identity)
    result = []
    music_records = records_by_kind['Music']
    metadata = _music_metadata(root, music_records=music_records,
                               music_inodes=getattr(records_by_kind, 'inodes', None))
    from .retail_media import metadata as retail_metadata, images as retail_images
    retail = retail_metadata(root, tracks_rows=retail_tracks)
    source_metadata = _source_music_metadata(root, music_records, cache_root(identity), retail, metadata)
    for kind in manager.KINDS:
        allowed = manager.extensions(kind)
        records = records_by_kind[kind]
        # Traversal already supplied absolute, reparse-free paths under root.
        # Resolving each file again adds an iPod filesystem query per row.
        for path, info in records:
            if kind == 'Videos' and str(path).casefold() in published_paths:
                continue
            if path.suffix.lower() in allowed:
                key = str(path).casefold()
                indexed = metadata.get(key, {}) if kind == 'Music' else {}
                tags = dict(indexed, **source_metadata.get(key, {})) if kind == 'Music' else retail.get(key, {})
                if indexed.get('artwork') and tags.get('artwork') == str(path):
                    tags['artwork'] = indexed['artwork']
                result.append(_row('original', kind, tags.get('title') or path.name, path,
                    ('Not supported on this iPod' if kind == 'Videos' and path.suffix.lower() not in source_video_extensions
                     else 'Indexed on iPod' if indexed else 'Source on iPod'), info=info,
                    artist=tags.get('artist', ''), album=tags.get('album', ''), genre=tags.get('genre', ''),
                    artwork=tags.get('artwork', ''), duration=tags.get('duration', 0), track=tags.get('track', 0),
                    album_artist=tags.get('album_artist', ''), disc=tags.get('disc', 0),
                    description='Removing this source requires preparing its media type afterward.'))
    photos = retail_photos if retail_photos is not None else retail_images(root)
    for photo in photos:
        result.append(dict(id='retail-photo:' + str(photo['key']), category='original', kind='Photos',
                           title=photo['title'], path=str(root / photo['relative']), source=photo['source'],
                           artwork=photo['preview'], bytes=photo['bytes'], mtime_ns=photo['mtime_ns'],
                           status='iTunes photo · Needs preparation', removable=False, retail_photo=True,
                           description='Prepared from the existing iTunes photo library; the Apple original is retained.'))
    for kind, name in (('Music', '.LINNET/LIBRARY.PDB'), ('Photos', '.LINNET/PHOTOS/LIBRARY.PIM'), ('Notes', '.LINNET/NOTES/LIBRARY.NNT')):
        path = root / name
        _plain(path, root)
        if path.is_file():
            result.append(_row('library', kind, 'Entire published ' + kind.lower() + ' library', path, 'Published library on iPod',
                description='Remove this entire published library. Original source files and cached conversions are retained. Updating this folder can restore it.'))
    for (key, _, title), path in zip(entries, resolved_videos):
        tags = retail.get(str(path).casefold(), {})
        result.append(_row('published', 'Videos', title, path,
            ('Not supported on this iPod' if path.suffix.lower() not in native_video_extensions
             else 'Ready on iPod' if path.is_file() else 'Missing published file'), key=key.hex(),
            artist=tags.get('artist', ''), album=tags.get('album', ''), genre=tags.get('genre', ''),
            artwork=tags.get('artwork', ''), duration=tags.get('duration', 0),
            description='Remove this video from the playback catalog and move its file to Trash.'))
    cache = cache_root(identity)
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
        for path in sorted(video_dir.iterdir()):
            if path.suffix.lower() not in {'.ipvf', '.mp4', '.m4v', '.mov'}:
                continue
            _plain(path, cache)
            if not path.is_file():
                continue
            title = names.get(path.name.split('-')[0], path.name)
            result.append(_row('cache', 'Videos', title, path, 'Prepared copy on computer',
                description='Reusable conversion cache. Published videos are listed separately; this file alone does not prove publication.'))
    return result


def _source_music_metadata(root, records, cache_root, retail=None, published=None):
    from .music import _MetadataCache, _quick_metadata, _pcm, _number, _album_artist, EXTENSIONS
    records = [(path, info) for path, info in records if path.suffix.lower() in EXTENSIONS]
    if not records:
        return {}
    cache = _MetadataCache(cache_root / 'music-metadata.sqlite3')
    result = {}
    prefetched = {}
    try:
        for index, (path, before) in enumerate(records):
            if index % 128 == 0:
                prefetched = cache.prefetch(root, [p.relative_to(root).as_posix()
                                                 for p, _ in records[index:index + 128]])
            try:
                relative = path.relative_to(root).as_posix()
                key = str(path).casefold()
                saved = (retail or {}).get(key, {})
                value = cache.get(root, relative, before, prefetched=prefetched)
                if value is None and saved:
                    result[key] = dict(saved,
                        album_artist=_album_artist({k: str(v) for k, v in saved.items()}, saved.get('artist', '')),
                        artwork=saved.get('artwork') or str(path))
                    continue
                if value is None and key in (published or {}):
                    # The verified on-device database already carries title,
                    # credits, duration and artwork. A new host cache should
                    # not reopen every audio file merely to show the library.
                    continue
                if value is None:
                    value = (_pcm(path) if path.suffix.lower() in ('.wav', '.aif', '.aiff', '.aifc')
                             else _quick_metadata(path))
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        continue
                    if value is not None:
                        cache.put(root, relative, before, value)
                if value is None:
                    if saved:
                        result[key] = saved
                    continue
                tags = {**{k: str(v) for k, v in saved.items() if v},
                        **{k: v for k, v in value['tags'].items() if v}}
                artist = tags.get('artist', '')
                result[key] = dict(
                    title=tags.get('title') or path.stem, artist=artist,
                    album=tags.get('album', ''), genre=tags.get('genre', ''),
                    album_artist=_album_artist(tags, artist), track=_number(tags.get('track')),
                    disc=_number(tags.get('disc')), duration=value['frames'] / value['rate'],
                    artwork=saved.get('artwork') or str(path))
            except (OSError, ValueError, TypeError, KeyError, struct.error):
                continue
    finally:
        cache.close()
    return result


def _music_metadata(root, *, music_records=None, music_inodes=None):
    """Read the prepared metadata once, without opening individual audio files."""
    from .music import validate_database, MAX_DATABASE, TRACK
    database = root / '.LINNET' / 'LIBRARY.PDB'
    _plain(database, root)
    if not database.is_file():
        return {}
    try:
        scanned, direct_paths, alias_roots = {}, {}, {}
        if music_records is not None:
            for path, info in music_records:
                if not path.is_relative_to(root):
                    continue
                key = str(path).casefold()
                if key in direct_paths:
                    direct_paths[key] = None
                else:
                    direct_paths[key] = path
                if music_inodes is not None:
                    inode = music_inodes.get(path)
                    if inode:
                        if inode in scanned:
                            scanned[inode] = None  # Ambiguous file identity needs the guarded path.
                        else:
                            scanned[inode] = (path, info.st_size, info.st_mtime_ns)

        def source_path(location):
            candidate = root / location.lstrip('/')
            parts = location.split('/')
            if (direct_paths and len(parts) >= 3 and parts[0] == '' and
                    all(part and part not in ('.', '..') and '\\' not in part and ':' not in part
                        for part in parts[1:])):
                # The traversal already rejected reparse points for these
                # read-only rows. Retail databases often spell iPod_Control
                # as its FAT short alias; verify that folder alias once.
                known = direct_paths.get(str(candidate).casefold())
                if known is None and len(parts) >= 4 and parts[2].casefold() == 'music':
                    alias = parts[1].casefold()
                    if alias not in alias_roots:
                        prefix = root / parts[1]
                        try:
                            _plain(prefix, root)
                            alias_roots[alias] = prefix.resolve(strict=True) == root / 'iPod_Control'
                        except (OSError, ValueError):
                            alias_roots[alias] = False
                    if alias_roots[alias]:
                        canonical = root / 'iPod_Control' / 'Music' / Path(*parts[3:])
                        known = direct_paths.get(str(canonical).casefold())
                if known is not None:
                    return known
                try:
                    info = candidate.lstat()
                except OSError:
                    pass
                else:
                    if (stat.S_ISREG(info.st_mode) and not
                            getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                        known = scanned.get(info.st_ino)
                        if known is not None and (info.st_size, info.st_mtime_ns) == known[1:]:
                            return known[0]
            _plain(candidate, root)
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError('Music database path escaped the iPod')
            return resolved

        if database.stat().st_size > MAX_DATABASE:
            return {}
        data = _bounded(database, MAX_DATABASE)
        validate_database(data)
        width = TRACK
        fields = struct.unpack_from('<14I', data, 8)
        count, offset, pool = fields[2], fields[6], fields[10]
        strings = {}
        def string(at):
            if at not in strings:
                start = pool + at
                strings[at] = data[start:data.index(b'\0', start)].decode('utf-8')
            return strings[at]
        owners = {}
        for index in range(fields[3]):
            kind, name, parent, first, length = struct.unpack_from('<5I', data, fields[7] + index * 32)
            if kind == 2:
                owner = string(struct.unpack_from('<I', data, fields[7] + parent * 32 + 4)[0])
                start = fields[8] + first * 4
                for (member,) in struct.iter_unpack('<I', memoryview(data)[start:start + length * 4]):
                    owners[member] = owner
        result, artwork_paths = {}, {}
        for index in range(count):
            title, artist, album, location, genre = map(string, struct.unpack_from('<5I', data, offset + index * width + 52))
            path = source_path(location)
            art = struct.unpack_from('<I', data, offset + index * width + 88)[0]
            if art < fields[12] and art not in artwork_paths:
                location = string(struct.unpack_from('<I', data, fields[13] + art * 32 + 8)[0])
                candidate = root / location.lstrip('/')
                _plain(candidate, root)
                artwork_paths[art] = str(candidate) if candidate.is_relative_to(root / '.LINNET' / 'ART') else ''
            artwork = artwork_paths.get(art, '')
            frames, rate = struct.unpack_from('<QI', data, offset + index * width + 32)
            track = struct.unpack_from('<I', data, offset + index * width + 80)[0]
            disc = struct.unpack_from('<I', data, offset + index * width + 84)[0]
            result[str(path).casefold()] = dict(title=title, artist=artist, album=album, genre=genre,
                artwork=artwork, duration=frames / rate if rate else 0, track=track, disc=disc, album_artist=owners.get(index, artist))
        return result
    except (OSError, ValueError, UnicodeError, struct.error):
        return {}


def remove_items(identity, items):
    """Revalidate selected rows and move their files to trash; retain a recovery receipt."""
    identity = manager.refresh(identity)
    with _exclusive(identity):
        return _remove(identity, items)


def organize_videos(identity):
    """Give managed videos readable names and reconcile files deleted in Explorer."""
    from .publish_video import video_filename, device_video_path
    identity = manager.refresh(identity)
    root = Path(identity['root']).resolve(strict=True)
    with _exclusive(identity):
        catalog, before, entries = _catalog(root)
        if before is None:
            return dict(summary='No prepared videos found.', receipt='')
        moves, updated = [], []
        token = uuid.uuid4().hex
        recovery = root / '.LINNET' / 'VIDEOS' / 'BACKUP' / (token[:8] + '.VID')
        _plain(recovery, root)
        _volume_guard(identity)
        recovery.parent.mkdir(exist_ok=True)
        _write_verified(recovery, before, 'Could not verify catalog backup')
        temporary = catalog.with_name(token[:8] + '.TMP')
        owned_temporaries = []
        published = False
        try:
            for key, name, title in entries:
                source = _device_path(root, name)
                if not source.is_file():
                    continue
                destination = source
                if source.parent == catalog.parent:
                    extension = source.suffix.lower() if source.suffix.lower() in ('.mp4', '.m4v', '.mov') else '.ipvf'
                    filename = video_filename(title, extension)
                    destination = source.with_name(filename)
                    if destination.exists() and destination != source:
                        destination = source.with_name(Path(filename).stem + ' [' + key.hex()[:8] + ']' + extension)
                    _plain(destination, root)
                    if destination != source:
                        if destination.exists():
                            raise ValueError('Video name already exists: ' + destination.name)
                        _volume_guard(identity)
                        source.rename(destination)
                        moves.append((source, destination))
                updated.append((key, device_video_path(destination, root), title))
            data = _encode_catalog(updated)
            _write_verified(temporary, data, 'Video catalog changed; refresh before organizing', owned=owned_temporaries)
            if catalog.read_bytes() != before:
                raise OSError('Video catalog changed; refresh before organizing')
            _volume_guard(identity)
            os.replace(temporary, catalog)
            published = True
            if catalog.read_bytes() != data:
                raise OSError('Video catalog verification failed')
        except Exception:
            if not published:
                for source, destination in reversed(moves):
                    _volume_guard(identity)
                    destination.rename(source)
            raise
        finally:
            if temporary in owned_temporaries and temporary.exists():
                _volume_guard(identity)
                _plain(temporary, root)
                temporary.unlink()
        cleanup = {}
        _finish_backups(cleanup, [recovery], root, lambda: _volume_guard(identity))
        state_path = cache_root(identity) / 'state.json'
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
            renamed = {source.relative_to(root).as_posix().casefold(): destination.relative_to(root).as_posix() for source, destination in moves}
            for saved in [state.get('Videos', {}), *state.get('video_files', {}).values()]:
                if isinstance(saved, dict) and isinstance(saved.get('outputs'), list):
                    saved['outputs'] = [(renamed.get(name.casefold(), name), hash_file(catalog) if name.casefold() == '.linnet/videos/index.vid' else digest) for name, digest in saved['outputs']]
            save_json(state_path, state)
        except (OSError, ValueError, AttributeError, TypeError):
            pass  # A missing preparation cache is rebuilt on the next update.
        return dict(summary=f'{len(moves)} videos renamed · {len(entries) - len(updated)} missing entries cleared.', receipt='', **cleanup)


def _removal_items(root):
    """Validate mutation IDs and file stamps without loading display metadata."""
    from .retail_media import images as retail_images
    records_by_kind = collect_records_by_kind(root)
    _, _, entries, resolved_videos = _catalog(root, with_paths=True)
    published_paths = {str(path).casefold() for path in resolved_videos}
    result = {}
    for kind in manager.KINDS:
        allowed = manager.extensions(kind)
        for path, info in records_by_kind[kind]:
            if path.suffix.lower() not in allowed or (kind == 'Videos' and str(path).casefold() in published_paths):
                continue
            row = _row('original', kind, path.name, path, 'Source on iPod', info=info)
            result[row['id']] = row
    for photo in retail_images(root, render=False):
        key = 'retail-photo:' + str(photo['key'])
        result[key] = dict(id=key, category='original', kind='Photos', removable=False)
    for kind, name in (('Music', '.LINNET/LIBRARY.PDB'), ('Photos', '.LINNET/PHOTOS/LIBRARY.PIM'), ('Notes', '.LINNET/NOTES/LIBRARY.NNT')):
        path = root / name
        _plain(path, root)
        if path.is_file():
            row = _row('library', kind, 'Entire published ' + kind.lower() + ' library', path,
                       'Published library on iPod')
            result[row['id']] = row
    for (key, _, title), path in zip(entries, resolved_videos):
        row = _row('published', 'Videos', title, path, 'Ready on iPod', key=key.hex())
        result[row['id']] = row
    return result


def _remove(identity, items):
    root = Path(identity['root']).resolve(strict=True)
    identity = manager.refresh(identity)
    fresh = _removal_items(root)
    selected = []
    selected_ids = set()
    for item in items:
        row = fresh.get(item['id'])
        if row is None or not row['removable']:
            raise ValueError('Selection changed or cannot be removed; refresh the library.')
        if any(row.get(field) != item.get(field) for field in ('path', 'bytes', 'mtime_ns')):
            raise ValueError('Selected file changed; refresh before removing: ' + row['title'])
        if row['id'] not in selected_ids:
            if isinstance(item.get('title'), str):
                row['title'] = item['title']
            selected.append(row)
            selected_ids.add(row['id'])
    if not selected:
        raise ValueError('Select an iPod item to remove.')
    # When the last source is removed, retire its packed library as part of the
    # same recoverable removal; preparation intentionally retains empty libraries.
    for kind in manager.KINDS:
        originals = [row for row in fresh.values() if row['kind'] == kind and row['category'] == 'original']
        if kind != 'Videos' and originals and all(row['id'] in selected_ids for row in originals):
            selected.extend(row for row in fresh.values() if row['kind'] == kind and row['category'] == 'library' and row['id'] not in selected_ids)
    if any(row['kind']=='Photos' and row['category']=='library' for row in selected):
        grid = root/'.LINNET'/'PHOTOS'/'GRID.PGR'
        _plain(grid, root)
        if grid.exists():
            selected.append(_row('library','Photos','Prepared photo grid',grid,'Native thumbnails',info=grid.stat()))
    catalog, before, entries = _catalog(root)
    selected_keys = {row['key'] for row in selected if row['category'] == 'published'}
    paths = {}
    expected_by_path = {}
    for row in selected:
        path = Path(row['path'])
        _plain(path, root)
        if row['category'] in ('original', 'library', 'published'):
            if path.exists():
                key = str(path.resolve()).casefold()
                paths[key] = path
                expected_by_path.setdefault(key, row)
    music_index = root / '.LINNET' / 'LIBRARY.PDB'
    music_before = music_after = None
    music_cache = None
    music_needs_update = False
    cover_index = root / ".LINNET" / "COVERS.CFL"
    cover_temporary = None
    cover_digest = None
    music_sources = [row for row in selected if row['kind'] == 'Music' and row['category'] == 'original']
    if music_sources and str(music_index.resolve()).casefold() not in paths and music_index.is_file():
        from .music import MAX_DATABASE, TRACK, _stable, validate_database, remove_database_tracks
        _plain(music_index, root)
        if music_index.stat().st_size > MAX_DATABASE:
            raise ValueError('Music database exceeds supported size')
        music_before = music_index.read_bytes()
        validate_database(music_before)
        width = TRACK
        fields = struct.unpack_from('<14I', music_before, 8)
        source_ids = {_stable('track:' + Path(row['path']).relative_to(root).as_posix()) for row in music_sources}
        removed_tracks = []
        for index in range(fields[2]):
            offset = fields[6] + index * width
            track_id = struct.unpack_from('<Q', music_before, offset)[0]
            start = fields[10] + struct.unpack_from('<I', music_before, offset + 64)[0]
            location = music_before[start:music_before.index(b'\0', start)].decode('utf-8')
            if track_id in source_ids or str((root / location.lstrip('/')).resolve()).casefold() in paths:
                removed_tracks.append(index)
        music_after = remove_database_tracks(music_before, removed_tracks)
        # Cover Flow records reference the old database identity and group indexes.
        music_needs_update = music_after != music_before and (root / '.LINNET' / 'COVERS.CFL').exists()
        # Carry forward readiness only if the saved source snapshot and index
        # matched before deletion. This scan reads file stats, never audio tags.
        try:
            cache_path = cache_root(identity) / 'state.json'
            saved_state = json.loads(cache_path.read_text(encoding='utf-8'))
            saved_music = saved_state.get('Music', {})
            skipped = {'Music': skipped_paths(saved_state, 'Music')}
            fingerprint = scan_sources(root, ('Music',), skipped=skipped)['Music']['fingerprint']
            signature = saved_music.get('signature', '')
            outputs = saved_music.get('outputs', [])
            if signature.endswith(':' + fingerprint) and any(
                    name.casefold() == '.linnet/library.pdb' and digest == hashlib.sha256(music_before).hexdigest()
                    for name, digest in outputs):
                music_cache = cache_path, saved_state, skipped
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    # Removing a cataloged original must also remove its catalog reference.
    remaining = [entry for entry in entries if entry[0].hex() not in selected_keys
                 and str(_device_path(root, entry[1]).resolve()).casefold() not in paths]
    token = uuid.uuid4().hex
    trash = root / '.LINNET' / 'TRASH' / token
    _plain(trash, root)
    receipt = cache_root(identity) / ('remove-' + token + '.json')
    report = dict(operation='remove-media', started=time.time(), complete=False, receipt=str(receipt),
                  trash=str(trash), removed=[], requires_update=sorted({r['kind'] for r in selected if r['category'] == 'original'}),
                  catalog_paths={key.hex(): _device_path(root, path).relative_to(root).as_posix() for key, path, _ in entries},
                  selected=selected, moves=[dict(source=str(p), trash=str(trash / p.relative_to(root))) for p in paths.values()])
    save_json(receipt, report)
    temporary = None
    temporary_owned = False
    try:
        _volume_guard(identity)
        trash.mkdir(parents=True, exist_ok=False)
        if music_before is not None:
            backup = trash / 'LIBRARY.PDB.before'
            _write_verified(backup, music_before, 'Music index backup verification failed')
            report['music_backup'] = str(backup)
            save_json(receipt, report)
        if music_needs_update:
            from . import coverflow
            from .publish import _hash, _copy_verified
            _plain(cover_index, root)
            cover_before = dict(bytes=cover_index.stat().st_size, sha256=_hash(cover_index))
            staged_cover = cover_index.with_name('C' + token[:7].upper() + '.TMP')
            _plain(staged_cover, root)
            try:
                coverflow.remove_tracks(cover_index, music_before, music_after, staged_cover)
            except ValueError:
                pass  # A stale or invalid existing catalog still needs normal preparation.
            else:
                cover_temporary = staged_cover
                cover_digest = _hash(staged_cover)
                backup = trash / 'COVERS.CFL.before'
                _copy_verified(cover_index, backup, cover_before, root, lambda: _volume_guard(identity))
                report['coverflow_backup'] = str(backup)
                save_json(receipt, report)
        if remaining != entries:
            backup = trash / 'INDEX.VID.before'
            _plain(backup, root)
            _write_verified(backup, before, 'Video catalog backup verification failed')
            report['catalog_backup'] = str(backup)
            save_json(receipt, report)
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
            save_json(receipt, report)
        for move in report['moves']:
            source, destination = Path(move['source']), Path(move['trash'])
            _volume_guard(identity)
            _plain(source, root); _plain(destination, root)
            expected = expected_by_path[str(source.resolve()).casefold()]
            info = source.stat()
            if (info.st_size, info.st_mtime_ns) != (expected['bytes'], expected['mtime_ns']):
                raise ValueError('File changed during removal: ' + str(source))
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            report['removed'].append(move)
            save_json(receipt, report)
        if music_after is not None:
            temporary = music_index.with_name('M' + token[:7].upper() + '.TMP')
            temporary_owned = False
            _plain(temporary, root); _volume_guard(identity)
            with temporary.open('xb') as writer:
                temporary_owned = True
                writer.write(music_after); writer.flush(); os.fsync(writer.fileno())
            if temporary.read_bytes() != music_after or music_index.read_bytes() != music_before:
                raise OSError('Music index changed during removal')
            _volume_guard(identity); _plain(music_index, root)
            os.replace(temporary, music_index)
            if music_index.read_bytes() != music_after:
                raise OSError('Music index update verification failed')
            report['music_updated'] = True
            from .browse import prepare as prepare_browse
            browse_index = music_index.with_name('BROWSE.BIN')
            browse_temporary = music_index.with_name('B' + token[:7].upper() + '.TMP')
            _plain(browse_index, root); _plain(browse_temporary, root); _volume_guard(identity)
            browse_data = prepare_browse(music_after)
            _write_verified(browse_temporary, browse_data, 'Browse index verification failed')
            os.replace(browse_temporary, browse_index)
            if browse_index.read_bytes() != browse_data:
                raise OSError('Browse index update verification failed')
            if cover_temporary is not None:
                _volume_guard(identity); _plain(cover_index, root)
                if _hash(cover_index) != cover_before['sha256']:
                    raise OSError('Cover Flow changed during removal')
                with cover_temporary.open('rb+') as writer:
                    writer.flush(); os.fsync(writer.fileno())
                os.replace(cover_temporary, cover_index)
                if _hash(cover_index) != cover_digest:
                    raise OSError('Cover Flow update verification failed')
                coverflow.validate(cover_index, music_after)
                report['coverflow_updated'] = True
                music_needs_update = False
            if not music_needs_update:
                report['requires_update'].remove('Music')
            save_json(receipt, report)
            if music_cache and not music_needs_update:
                try:
                    cache_path, saved_state, skipped = music_cache
                    saved_music = saved_state['Music']
                    fingerprint = scan_sources(root, ('Music',), skipped=skipped)['Music']['fingerprint']
                    saved_music['signature'] = saved_music['signature'].rsplit(':', 1)[0] + ':' + fingerprint
                    saved_music['outputs'] = [(name, hashlib.sha256(music_after).hexdigest()
                        if name.casefold() == '.linnet/library.pdb' else cover_digest
                        if name.casefold() == '.linnet/covers.cfl' and cover_digest else digest) for name, digest in saved_music['outputs']]
                    save_json(cache_path, saved_state)
                except (OSError, ValueError, TypeError, AttributeError):
                    pass  # Cache failure must not undo a verified device update.
        remaining_kinds = set()
        if report['requires_update']:
            manager.refresh(identity)
            remaining_kinds = {row['kind'] for row in _removal_items(root).values()
                               if row['category'] == 'original'}
        empty = [kind for kind in report['requires_update'] if kind not in remaining_kinds]
        report['empty_folders'] = empty
        report['complete'] = True
        report['summary'] = f'Removed {len(selected)} selected item(s). Recoverable files and catalog backup: {trash}'
        if report['requires_update']:
            report['summary'] += '. Update ' + ', '.join(report['requires_update']) + ' to rebuild its library.'
        if empty:
            report['summary'] += ' Empty playback libraries were also moved to Trash.'
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
        if cover_temporary is not None:
            try:
                _volume_guard(identity); _plain(cover_temporary, root)
                cover_temporary.unlink(missing_ok=True)
            except Exception as error:
                report['coverflow_temporary'] = str(cover_temporary)
                report['cleanup_error'] = str(error)
        report['finished'] = time.time()
        save_json(receipt, report)
