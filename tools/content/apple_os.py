"""Apple OS folder availability on validated iPod volumes.

Selections live on the computer. Discovery never changes the iPod. The Apple
database writer runs against a staged mount and installs only a verified DB.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import struct
import subprocess
import tempfile
import tomllib
import uuid
from contextlib import closing
from fractions import Fraction
from functools import lru_cache

from . import media_manager as media
from .host_state import cache_root, cache_volume_scope, file_stamp, save_json
from .inventory import file_records
from .music import _device_media_path
from .guard import guarded_path as _plain, guard_volume as _volume_guard, hash_file as _hash
from .publish import _exclusive


QUALIFICATIONS = Path(__file__).resolve().parents[2] / 'config/apple-os-qualified.toml'
ROOTS = ('Music', 'Photos', 'Videos', 'Notes')
SELECTABLE_ROOTS = ROOTS[:3]
APPLE_MUSIC_PREFIX = ':iPod_Control:Music:..:..:Music:'


def selectable_roots(identity):
    return ('Music',) if identity.get('target_id') == 'ipod4g-q21' else SELECTABLE_ROOTS


@lru_cache(maxsize=1)
def _qualified_specimens():
    """Load exact Apple OS specimens; a missing or invalid record enables none."""
    try:
        rows = tomllib.loads(QUALIFICATIONS.read_text(encoding='utf-8'))['specimen']
        if not isinstance(rows, list):
            return ()
        required = {'target_id', 'disk_serial', 'volume_serial', 'sector_bytes', 'model'}
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != required:
                return ()
            if (not all(isinstance(row[key], str) and row[key] for key in
                        ('target_id', 'disk_serial', 'volume_serial', 'model')) or
                    len(row['disk_serial']) != 16 or len(row['volume_serial']) != 8 or
                    any(char not in '0123456789ABCDEF' for char in
                        row['disk_serial'] + row['volume_serial']) or
                    type(row['sector_bytes']) is not int or row['sector_bytes'] not in (512, 2048, 4096)):
                return ()
            identity = (row['target_id'], row['disk_serial'], row['volume_serial'],
                        row['sector_bytes'])
            if identity in seen:
                return ()
            seen.add(identity)
        return tuple(rows)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _qualified_device(identity):
    if identity.get('filesystem') != 'FAT32':
        return None
    return next((row for row in _qualified_specimens()
                 if (identity.get('target_id') == row['target_id'] and
                     identity.get('disk_serial') == row['disk_serial'] and
                     identity.get('volume_serial') == row['volume_serial'] and
                     identity.get('sector_bytes') == row['sector_bytes'] and
                     (row['target_id'] != 'ipod4g-q21' or
                      identity.get('model_number') == row['model']))), None)


def _eligibility(identity):
    """Explain the exact specimen gate and the media paths this writer accepts."""
    if identity.get('filesystem') != 'FAT32':
        reason = 'Apple OS updates require a FAT32 iPod volume.'
    elif not _qualified_specimens():
        reason = 'No audited Apple OS device specimens are configured.'
    elif not any(row['target_id'] == identity.get('target_id') for row in _qualified_specimens()):
        reason = 'This iPod model has not been physically qualified for Apple OS updates.'
    elif _qualified_device(identity) is None:
        reason = ('This iPod unit does not match the audited disk serial, volume serial and '
                  'sector size for its model.')
    else:
        reason = 'This exact iPod unit is qualified for Apple OS updates.'
    if identity.get('target_id') == 'ipod4g-q21':
        return reason + ' Music requires MP3 files under /Music with short FAT paths. Compatible text files in /Notes are available automatically.'
    return (reason + ' Music requires MP3 files under /Music with short FAT paths; videos require '
            'compatible MP4, M4V or MOV files under /Videos with short FAT paths. Photos must be '
            'selected under /Photos, and an existing Apple photo library must match its Linnet receipt.')


def supported(identity):
    return _qualified_device(identity) is not None


def _state_path(identity):
    return cache_root(identity) / 'apple-os.json'


def _load(identity):
    try:
        value = json.loads(_state_path(identity).read_text(encoding='utf-8'))
        if isinstance(value, dict) and value.get('device_serial') == identity['disk_serial']:
            return value
    except (OSError, ValueError, KeyError):
        pass
    return {'device_serial': identity['disk_serial'], 'folders': [],
            'configured': False, 'published': None}


def _valid_folder(root, value, allowed=SELECTABLE_ROOTS):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Invalid Apple OS folder selection')
    relative = Path(value)
    if (relative.is_absolute() or relative.drive or '..' in relative.parts or
            not relative.parts or relative.parts[0] not in allowed or
            relative.as_posix() != value):
        raise ValueError('Apple OS folder is outside the media folders')
    folder = root / relative
    _plain(folder, root)
    if not folder.is_dir() or not folder.resolve(strict=True).is_relative_to(root):
        raise ValueError(f'Apple OS folder is unavailable: {value}')
    return folder


def _normalize(root, folders, allowed=SELECTABLE_ROOTS):
    values = sorted(set(folders), key=lambda x: (x.casefold(), x))
    result = []
    for value in values:
        _valid_folder(root, value, allowed)
        if not any(value.casefold() == parent.casefold() or
                   value.casefold().startswith(parent.casefold() + '/') for parent in result):
            result.append(value)
    return result


def _walk_folders(root, kinds=ROOTS):
    result = []
    for kind in kinds:
        start = root / kind
        if not start.is_dir():
            continue
        stack = [start]
        while stack:
            folder = stack.pop()
            _plain(folder, root)
            relative = folder.relative_to(root).as_posix()
            result.append({'path': relative, 'kind': kind})
            if len(result) > 10000:
                raise ValueError('Too many media folders for Apple OS selection')
            children = []
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        raise ValueError(f'Linked media folder is unsupported: {entry.path}')
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
            stack.extend(sorted(children, key=lambda p: p.name.casefold(), reverse=True))
    return result


def _folder_rows(root, records_by_kind, kinds=ROOTS):
    paths = set()
    for kind in kinds:
        kind_root = root / kind
        if kind_root.is_dir():
            paths.add(kind)
        last_parent = None
        for path, _ in records_by_kind[kind]:
            parent = path.parent
            parent_key = str(parent)
            if parent != root and parent_key == last_parent:
                continue
            last_parent = parent_key if parent != root else None
            if not path.is_relative_to(kind_root):
                continue
            while parent.is_relative_to(kind_root):
                relative = parent.relative_to(root).as_posix()
                if relative in paths:
                    break
                paths.add(relative)
                parent = parent.parent
    return [{'path': value, 'kind': value.split('/')[0]}
            for value in sorted(paths, key=lambda x: (kinds.index(x.split('/')[0]),
                                                      len(Path(x).parts), x.casefold()))]


def _source_info(path, info):
    if os.name == 'nt' and not info.st_ino:
        # Windows directory records omit the file ID needed to recognize a
        # replacement that preserves size and modification time.
        current = path.lstat()
        if (not stat.S_ISREG(current.st_mode) or
                getattr(current, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400) or
                (current.st_size, current.st_mtime_ns, current.st_ctime_ns) !=
                (info.st_size, info.st_mtime_ns, info.st_ctime_ns)):
            raise ValueError(f'Media changed while reading Apple OS sources: {path}')
        return current
    return info


def _files(root, folders, kind, extensions, records_by_kind=None):
    found = {}
    selected = [_valid_folder(root, value) for value in folders
                if value.split('/')[0] == kind]
    if not selected:
        return []
    if records_by_kind is not None:
        selected_dirs = set(selected)
        kind_root = root / kind
        whole_kind = kind_root in selected_dirs
        last_parent, relative_prefix, included = None, None, False
        for path, info in records_by_kind[kind]:
            if path.suffix.lower() not in extensions:
                continue
            parent = path.parent
            parent_key = str(parent)
            if parent == root or parent_key != last_parent:
                included = ((whole_kind and path.is_relative_to(kind_root)) or
                            any(folder in selected_dirs for folder in path.parents))
                last_parent = parent_key if parent != root else None
                relative_prefix = None
            if included:
                if relative_prefix is None:
                    relative = path.relative_to(root).as_posix()
                    relative_prefix = relative[:relative.rfind('/') + 1]
                else:
                    relative = relative_prefix + path.name
                found[relative.casefold()] = (path, info)
    else:
        for folder in selected:
            for path, info in file_records(folder, allowed=extensions):
                found[path.relative_to(root).as_posix().casefold()] = (path, info)
    return [(path, _source_info(path, info)) for _, (path, info) in sorted(found.items())]


def _signature(root, files):
    rows = [(path.relative_to(root).as_posix(), *file_stamp(info))
            for path, info in files]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def _apple_music_path(path, root, aliases):
    if not path.is_relative_to(root / 'Music'):
        raise ValueError('Apple music must be under /Music')
    if path.suffix.lower() != '.mp3':
        raise ValueError(f'Apple music currently supports MP3 only: {path.relative_to(root)}')
    short = _device_media_path(path, root, aliases)
    if not short.startswith('/MUSIC/'):
        raise ValueError(f'Cannot resolve Apple music path: {path}')
    relative = short[len('/MUSIC/'):].replace('/', ':')
    if len(relative) > 23:
        raise ValueError(f'Apple path needs a shorter FAT alias: {path.relative_to(root)}')
    result = APPLE_MUSIC_PREFIX + relative[:-4] + '.mp3'
    if len(result.encode('ascii')) > 55:
        raise ValueError(f'Apple path is too long: {path.relative_to(root)}')
    return result


def _apple_video_path(path, root, aliases):
    if path.suffix.lower() not in ('.mp4', '.m4v', '.mov') or not path.is_relative_to(root / 'Videos'):
        raise ValueError('Apple video needs an MP4, M4V or MOV file under /Videos')
    short = _device_media_path(path, root, aliases)
    if not short.startswith('/VIDEOS/'):
        raise ValueError(f'Cannot resolve Apple video path: {path}')
    relative = short[len('/VIDEOS/'):].replace('/', ':')
    if len(relative) > 22:
        raise ValueError(f'Apple video path needs a shorter FAT alias: {path.relative_to(root)}')
    prefix = ':iPod_Control:Music:..:..:Videos:'
    result = prefix + relative[:-len(path.suffix)] + path.suffix.lower()
    if len(result.encode('ascii')) > 55:
        raise ValueError(f'Apple video path is too long: {path.relative_to(root)}')
    return result


def _video_probe(path, ffprobe):
    if not ffprobe:
        raise ValueError('FFprobe is needed to check video for Apple OS.')
    try:
        result = subprocess.run([ffprobe, '-v', 'error', '-show_entries',
                                 'format=duration,bit_rate:format_tags=title,artist:stream=codec_type,codec_name,profile,width,height,level,r_frame_rate,sample_rate,channels,bit_rate',
                                 '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise ValueError(f'Video inspection timed out: {path.name}') from None
    if result.returncode:
        raise ValueError(f'Could not inspect video: {path.name}')
    data = json.loads(result.stdout)
    video = next((item for item in data.get('streams', []) if item.get('codec_type') == 'video'), None)
    audio = next((item for item in data.get('streams', []) if item.get('codec_type') == 'audio'), None)
    if not video or not audio:
        raise ValueError(f'Apple video needs video and AAC audio: {path.name}')
    width, height = int(video.get('width', 0)), int(video.get('height', 0))
    if width <= 0 or height <= 0 or width > 640 or height > 480:
        raise ValueError(f'Apple video exceeds 640×480: {path.name}')
    rate = Fraction(video.get('r_frame_rate', '0/1'))
    if rate <= 0 or rate > 30:
        raise ValueError(f'Apple video exceeds 30 frames per second: {path.name}')
    codec, profile = video.get('codec_name'), video.get('profile', '')
    if codec == 'h264':
        if profile not in ('Baseline', 'Constrained Baseline') or int(video.get('level', 99)) > 30:
            raise ValueError(f'Apple video needs H.264 Baseline Level 3.0 or lower: {path.name}')
    elif codec == 'mpeg4':
        if profile != 'Simple Profile':
            raise ValueError(f'Apple video needs MPEG-4 Simple Profile: {path.name}')
    else:
        raise ValueError(f'Apple video does not support {codec}: {path.name}')
    bitrate = int(video.get('bit_rate') or data.get('format', {}).get('bit_rate') or 0)
    if bitrate <= 0 or bitrate > 2_500_000:
        raise ValueError(f'Apple video bitrate exceeds 2.5 Mbps: {path.name}')
    if audio.get('codec_name') != 'aac' or audio.get('profile') != 'LC':
        raise ValueError(f'Apple video needs AAC-LC audio: {path.name}')
    sample_rate, channels = int(audio.get('sample_rate', 0)), int(audio.get('channels', 0))
    if sample_rate <= 0 or sample_rate > 48000 or channels not in (1, 2):
        raise ValueError(f'Apple video needs mono or stereo AAC at 48 kHz or less: {path.name}')
    # Encoder bitrates are often rounded just above the nominal 160 kbps cap.
    audio_rate = int(audio.get('bit_rate') or 0)
    if audio_rate > 192_000:
        raise ValueError(f'Apple video audio bitrate is too high: {path.name}')
    duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0 or duration * 1000 > 2_147_483_647:
        raise ValueError(f'Apple video duration is invalid: {path.name}')
    tags = data.get('format', {}).get('tags') or {}
    return {'duration_ms': round(duration * 1000), 'bitrate_kbps': round(bitrate / 1000),
            'sample_rate': sample_rate, 'title': str(tags.get('title') or path.stem),
            'artist': str(tags.get('artist') or 'Unknown Artist')}


def inspect(identity, *, records_by_kind=None, retail_tracks=None):
    """Return folder choices and readiness without writing the device."""
    root = Path(identity['root']).resolve(strict=True)
    allowed = selectable_roots(identity)
    folder_kinds = (*allowed, 'Notes')
    if not supported(identity):
        database = root / 'iPod_Control/iTunes/iTunesDB'
        if database.is_file():
            try:
                from .retail_media import tracks
                count = len(retail_tracks) if retail_tracks else len(tracks(root))
                library = f'Apple music database lists {count:,} track' + ('' if count == 1 else 's') + '. '
            except (OSError, ValueError, UnicodeError, struct.error):
                library = 'Apple music database could not be read. '
        else:
            library = 'No Apple music database found. '
        return {'supported': False, 'folders': [], 'selected': [],
                'status': library.strip(), 'eligibility': _eligibility(identity),
                'details': []}
    folders = (_folder_rows(root, records_by_kind, folder_kinds) if records_by_kind is not None else
               _walk_folders(root, folder_kinds))
    state = _load(identity)
    selected = [value for value in state.get('folders', [])
                if isinstance(value, str) and value.split('/')[0] in allowed and (root / value).is_dir()]
    # Adopt an existing validated Apple music library once.
    adopted = False
    adopted_tracks = None
    if (not selected and not state.get('configured') and state.get('published') is None
            and (root / 'Music').is_dir()):
        try:
            from .retail_media import available_tracks
            adopted_tracks = set(retail_tracks if retail_tracks is not None else available_tracks(root))
            prefix = str(root / 'Music').casefold() + os.sep
            if any(path.startswith(prefix) for path in adopted_tracks):
                selected = ['Music']
                adopted = True
        except (OSError, ValueError):
            pass
    music = _files(root, selected, 'Music', media.extensions('Music'), records_by_kind)
    published = state.get('published') if isinstance(state.get('published'), dict) else {}
    db = root / 'iPod_Control/iTunes/iTunesDB'
    source_stamp = _signature(root, music)
    digest = _hash(db) if (selected or published) and db.is_file() else None
    adopted_ready = False
    if adopted and adopted_tracks is not None and digest:
        local_paths = {str(path.resolve()).casefold() for path, _ in music}
        if (music and all(path.suffix.lower() == '.mp3' and 0 < info.st_size <= 0xffffffff
                for path, info in music) and local_paths <= adopted_tracks):
            adopted_ready = True
            published.update(music_signature=source_stamp, music_source_signature=source_stamp,
                             database_sha256=digest, music_count=len(music), music_issues=[])
            state.update(folders=selected, configured=True, published=published)
            save_json(_state_path(identity), state)
    source_matches = published.get('music_source_signature') == source_stamp
    same_published = (source_matches and
                      published.get('database_sha256') == digest and
                      isinstance(published.get('music_count'), int))
    if same_published:
        # A verified, unchanged selection needs no thousands of FAT alias lookups.
        issues = published.get('music_issues', [])
        playable_count = published['music_count']
        stamp = published.get('music_signature')
    else:
        aliases, issues, playable_music = {}, [], []
        for path, info in music:
            try:
                if info.st_size <= 0 or info.st_size > 0xffffffff:
                    raise ValueError(f'Apple music file size is unsupported: {path.relative_to(root)}')
                _apple_music_path(path, root, aliases)
                playable_music.append((path, info))
            except (OSError, ValueError) as error:
                if len(issues) < 20:
                    issues.append(str(error))
        playable_count = len(playable_music)
        stamp = _signature(root, playable_music)
    if issues and same_published:
        music_status = f'{len(music) - playable_count} music paths need attention'
    elif issues:
        music_status = 'Needs update'
    elif not selected and published.get('music_count', 0):
        music_status = 'Needs update'
    elif not selected:
        music_status = 'No music folders selected'
    elif adopted:
        music_status = 'Ready' if adopted_ready else 'Needs update'
    else:
        if same_published:
            signature_matches = published.get('music_signature') == stamp
        elif (published.get('music_signature') == published.get('music_source_signature') and
              playable_count == len(music) and stamp == source_stamp):
            # The playable subset is the full source list, so the first
            # signature comparison already checked these same files.
            signature_matches = source_matches
        else:
            signature_matches = published.get('music_signature') == stamp
        music_status = ('Ready' if signature_matches and
                        published.get('database_sha256') == digest else 'Needs update')
    details = [{'kind': 'Music', 'count': len(music), 'status': music_status}]
    photos = _files(root, selected, 'Photos', media.extensions('Photos'), records_by_kind)
    photo_db = root / 'Photos/Photo Database'
    photo_digest = (_hash(photo_db) if (photos or published.get('photo_count', 0)) and
                    photo_db.is_file() else None)
    if photos:
        if photo_digest and published.get('photo_database_sha256') not in (None, photo_digest):
            photo_status = 'Apple photo library changed outside Linnet'
        elif photo_digest and not published.get('photo_database_sha256'):
            photo_status = 'Existing Apple photo library needs review'
        elif (published.get('photo_signature') == _signature(root, photos) and
              published.get('photo_database_sha256') == photo_digest):
            photo_status = 'Ready'
        else:
            photo_status = 'Needs update'
        details.append({'kind': 'Photos', 'count': len(photos), 'status': photo_status})
    elif published.get('photo_count', 0):
        photo_status = 'Needs update'
        details.append({'kind': 'Photos', 'count': 0, 'status': photo_status})
    else:
        photo_status = 'No photo folders selected'
    note_issues = 0
    if (root / 'Notes').is_dir():
        notes = (records_by_kind['Notes'] if records_by_kind is not None else
                 file_records(root / 'Notes'))
        notes = [(path, info) for path, info in notes
                 if path.is_relative_to(root / 'Notes') and path.name.casefold() != 'instructions']
        native = [(path, info) for path, info in notes
                  if path.suffix.lower() == '.txt' and info.st_size <= 4096]
        note_issues = len(notes) - len(native)
        note_status = ('Apple Notes reads .txt files here automatically' if len(native) == len(notes) else
                       f'{len(notes) - len(native)} notes need a short plain-text file')
        details.append({'kind': 'Notes', 'count': len(notes), 'status': note_status})
    videos = _files(root, selected, 'Videos', media.extensions('Videos'), records_by_kind)
    video_stamp = _signature(root, videos)
    video_matches = published.get('video_source_signature') == video_stamp
    saved_video_issues = (published.get('video_issues', [])
                          if video_matches and
                          isinstance(published.get('video_issues'), list) else [])
    if videos or published.get('video_count', 0):
        if not video_matches or published.get('database_sha256') != digest:
            video_status = 'Needs update'
        elif saved_video_issues:
            video_status = f'{len(saved_video_issues)} videos need attention'
        else:
            video_status = 'Ready'
        details.append({'kind': 'Videos', 'count': len(videos), 'status': video_status})
        issues.extend(str(value) for value in saved_video_issues[:max(0, 20 - len(issues))])
    else:
        video_status = 'No video folders selected'
    photo_conflict = photo_status.startswith(('Apple photo library', 'Existing Apple photo'))
    can_update = not photo_conflict and (any(value == 'Needs update' for value in
                                             (music_status, photo_status, video_status)) or
                                         bool(issues))
    if photo_conflict:
        status = 'Needs attention'
    elif any(value == 'Needs update' for value in (music_status, photo_status, video_status)):
        status = 'Needs Apple OS update'
    elif issues or note_issues:
        status = 'Needs attention'
    elif selected:
        status = 'Ready in Apple OS'
    else:
        status = 'Choose folders to make available in Apple OS'
    return {'supported': True, 'folders': folders, 'selected': selected,
            'status': status, 'details': details, 'issues': issues,
             'can_update': can_update, 'eligibility': _eligibility(identity),
             'selectable_roots': allowed}


def save_selection(identity, folders):
    identity = media.refresh(identity)
    if not supported(identity):
        raise ValueError(_eligibility(identity))
    root = Path(identity['root']).resolve(strict=True)
    selected = _normalize(root, folders, selectable_roots(identity))
    state = _load(identity)
    state['folders'] = selected
    state['configured'] = True
    save_json(_state_path(identity), state)
    return selected


def _run_writer(arguments, *, timeout=120):
    result = subprocess.run([str(argument) for argument in arguments],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                            timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Apple database tool failed')
    return result


def _writer(cache, kind='music'):
    from tools.studio.apple_tools import writer
    return writer(kind, cache)


def _revalidate_device(identity, *paths):
    """Check the full disk identity and mounted volume before a device mutation."""
    media.refresh(identity)
    _volume_guard(identity)
    root = Path(identity['root'])
    for path in paths:
        _plain(path, root)


def _recovery_error(kind, failure, recovery, stopped):
    return RuntimeError(
        f'Apple {kind} update failed ({failure}); automatic recovery stopped ({stopped}). '
        f'Recovery information is at {recovery}. Reconnect the original iPod, inspect the '
        'listed device paths and saved originals, then restore or retry only after verifying its identity.'
    )


def _update_photos(identity, state, selected, cache, progress):
    device = _qualified_device(identity)
    if device is None:
        raise ValueError(_eligibility(identity))
    root = Path(identity['root']).resolve(strict=True)
    photos = _files(root, selected, 'Photos', media.extensions('Photos'))
    published = state.get('published') or {}
    if not photos and not published.get('photo_count', 0):
        return
    photo_db = root / 'Photos/Photo Database'
    _plain(photo_db, root)
    old_digest = _hash(photo_db) if photo_db.is_file() else None
    if old_digest and old_digest != published.get('photo_database_sha256'):
        raise ValueError('The Apple photo library changed outside Linnet. Review it before updating Photos.')
    if (published.get('photo_signature') == _signature(root, photos) and
            published.get('photo_database_sha256') == old_digest):
        return
    source_bytes = sum(info.st_size for _, info in photos)
    work_bytes = max(64 * 1024 * 1024, len(photos) * 256 * 1024) if photos else 1024 * 1024
    if source_bytes + work_bytes > shutil.disk_usage(cache).free:
        raise ValueError('Not enough computer space to prepare these Apple photos.')
    progress(f'Preparing {len(photos):,} photos for Apple OS…')
    writer = _writer(cache, 'photos')
    with tempfile.TemporaryDirectory(prefix='linnet-apple-photos-', dir=cache) as directory:
        stage = Path(directory)
        sysinfo = stage / 'iPod_Control/Device/SysInfo'
        sysinfo.parent.mkdir(parents=True)
        shutil.copy2(root / 'iPod_Control/Device/SysInfo', sysinfo)
        source = stage / 'source'
        source.mkdir()
        from PIL import Image, ImageOps
        lines = []
        for index, (path, info) in enumerate(photos, 1):
            if info.st_size > 128 * 1024 * 1024:
                raise ValueError(f'Photo is too large for Apple OS preparation: {path.relative_to(root)}')
            original = source / ('original' + path.suffix.lower())
            shutil.copy2(path, original)
            copied = original.stat()
            if ((copied.st_size, copied.st_mtime_ns) != (info.st_size, info.st_mtime_ns) or
                    file_stamp(path.stat()) != file_stamp(info)):
                raise ValueError(f'Photo changed during preparation: {path.relative_to(root)}')
            destination = source / f'{index:06}.png'
            with Image.open(original) as image:
                if (not image.width or not image.height or max(image.size) > 16384 or
                        image.width * image.height > 32_000_000):
                    raise ValueError(f'Photo dimensions exceed the decode limit: {path.relative_to(root)}')
                if image.width * image.height * 4 + work_bytes > shutil.disk_usage(cache).free:
                    raise ValueError('Not enough computer space to prepare this Apple photo.')
                with ImageOps.exif_transpose(image) as oriented:
                    with oriented.convert('RGBA' if 'A' in oriented.getbands() or
                                           'transparency' in oriented.info else 'RGB') as pixels:
                        pixels.save(destination, format='PNG')
            shutil.copystat(original, destination)
            original.chmod(0o600)  # A copied read-only photo must remain removable on Windows.
            original.unlink()
            lines.append(str(destination))
        manifest = stage / 'photos.txt'
        manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        _run_writer([writer, stage, manifest, device['model'], '0x' + device['disk_serial']],
                 timeout=max(300, len(photos) * 2))
        prepared = stage / 'Photos/Photo Database'
        if not prepared.is_file() or prepared.stat().st_size < 128:
            raise ValueError('Apple photo writer produced no valid database.')
        from .retail_media import image_count
        visible = image_count(stage)
        if visible != len(photos):
            raise ValueError(f'Apple photo database contains {visible} images, expected {len(photos)}.')
        outputs = [p for p in (stage / 'Photos').rglob('*') if p.is_file() and p != prepared]
        if photos and not outputs:
            raise ValueError('Apple photo thumbnails are missing.')
        outputs.append(prepared)  # Publish the database last.
        existing = [(source_file, root / source_file.relative_to(stage)) for source_file in outputs]
        if any(target.exists() and not target.is_file() for _, target in existing):
            raise ValueError('An Apple photo library path is occupied by a folder.')
        backup_bytes = sum(target.stat().st_size for _, target in existing if target.is_file())
        if backup_bytes + 1024 * 1024 > shutil.disk_usage(cache).free:
            raise ValueError('Not enough computer space to retain the previous Apple photo library.')
        new_bytes = sum(source_file.stat().st_size for source_file, target in existing if not target.exists())
        largest_replacement = max((source_file.stat().st_size for source_file, target in existing
                                   if target.exists()), default=0)
        if new_bytes + largest_replacement + 1024 * 1024 > shutil.disk_usage(root).free:
            raise ValueError('Not enough iPod space for the Apple photo library.')
        backup = cache / 'apple-photo-recovery' / uuid.uuid4().hex
        backup.mkdir(parents=True)
        recovery = backup / 'recovery.json'
        prepared_hashes = {source_file.relative_to(stage): _hash(source_file)
                           for source_file in outputs}
        changed = []
        temporary = None
        temporary_created = False
        with _exclusive(identity):
            _revalidate_device(identity, photo_db)
            current_photo_digest = _hash(photo_db) if photo_db.is_file() else None
            if current_photo_digest != old_digest:
                raise ValueError('The Apple photo library changed during preparation. Review it before retrying.')
            previous_hashes = {}
            for relative in prepared_hashes:
                target = root / relative
                _plain(target, root)
                if target.exists() and not target.is_file():
                    raise ValueError(f'An Apple photo library path is occupied by a folder: {target}')
                previous_hashes[relative] = _hash(target) if target.is_file() else None
            if previous_hashes[photo_db.relative_to(root)] != old_digest:
                raise ValueError('The Apple photo library changed during preparation. Review it before retrying.')
            record = {'kind': 'Apple photos', 'disk_serial': identity['disk_serial'],
                      'volume_serial': identity['volume_serial'],
                      'volume_unique_id': identity['volume_unique_id'],
                      'device_root': str(root), 'status': 'in_progress',
                      'files': [{'path': relative.as_posix(),
                                 'previous_exists': previous_hashes[relative] is not None,
                                 'previous_sha256': previous_hashes[relative],
                                 'prepared_sha256': digest,
                                 'backup_path': str(backup / relative)}
                                for relative, digest in prepared_hashes.items()]}
            save_json(recovery, record)
            try:
                for source_file in outputs:
                    relative = source_file.relative_to(stage)
                    target = root / relative
                    _plain(target, root)
                    _revalidate_device(identity, target.parent)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    prior = backup / relative
                    old_hash = previous_hashes[relative]
                    if old_hash is not None:
                        if not target.is_file() or _hash(target) != old_hash:
                            raise ValueError(f'Apple photo changed during preparation: {relative}')
                        prior.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, prior)
                        if _hash(prior) != old_hash or _hash(target) != old_hash:
                            raise ValueError(f'Apple photo changed while backing up: {relative}')
                    elif target.exists():
                        raise ValueError(f'Apple photo appeared during preparation: {relative}')
                    temporary = target.with_name(target.name + '.linnet-tmp')
                    if temporary.exists():
                        raise ValueError('An interrupted Apple photo update needs attention.')
                    expected = prepared_hashes[relative]
                    _revalidate_device(identity, temporary)
                    with temporary.open('xb') as destination:
                        temporary_created = True
                        with source_file.open('rb') as prepared_source:
                            shutil.copyfileobj(prepared_source, destination)
                    if _hash(temporary) != expected:
                        raise ValueError(f'Apple photo readback failed: {relative}')
                    _revalidate_device(identity, target, temporary)
                    if old_hash is None:
                        if target.exists():
                            raise ValueError(f'Apple photo appeared during publication: {relative}')
                    elif not target.is_file() or _hash(target) != old_hash:
                        raise ValueError(f'Apple photo changed during publication: {relative}')
                    _revalidate_device(identity, target, temporary)
                    temporary.replace(target)
                    temporary_created = False
                    changed.append((target, prior, old_hash, expected))
                record['status'] = 'published'
                save_json(recovery, record)
            except Exception as failure:
                try:
                    if temporary_created:
                        _revalidate_device(identity, temporary)
                        temporary.unlink(missing_ok=True)
                    for target, prior, old_hash, expected in reversed(changed):
                        _revalidate_device(identity, target)
                        if not target.is_file() or _hash(target) != expected:
                            raise RuntimeError(f'Apple photo changed after publication: {target}')
                        if old_hash is None:
                            _revalidate_device(identity, target)
                            target.unlink()
                        else:
                            if not prior.is_file() or _hash(prior) != old_hash:
                                raise RuntimeError(f'Apple photo backup is incomplete: {prior}')
                            rollback_temp = target.with_name(target.name + '.linnet-rollback-tmp')
                            _plain(rollback_temp, root)
                            if rollback_temp.exists():
                                raise RuntimeError(f'An earlier rollback needs attention: {rollback_temp}')
                            _revalidate_device(identity, rollback_temp)
                            shutil.copy2(prior, rollback_temp)
                            if _hash(rollback_temp) != old_hash:
                                raise RuntimeError(f'Apple photo rollback readback failed: {target}')
                            _revalidate_device(identity, target, rollback_temp)
                            rollback_temp.replace(target)
                except Exception as stopped:
                    record['status'] = 'needs_manual_recovery'
                    try:
                        save_json(recovery, record)
                    except OSError:
                        pass
                    raise _recovery_error('photo', failure, recovery, stopped) from failure
                record['status'] = 'rolled_back'
                save_json(recovery, record)
                raise
        published.update(photo_signature=_signature(root, photos),
                         photo_database_sha256=_hash(prepared),
                         photo_count=len(photos))
        state['published'] = published
        try:
            save_json(_state_path(identity), state)
        except OSError as error:
            record['status'] = 'published_without_host_state'
            try:
                save_json(recovery, record)
            except OSError:
                pass
            raise RuntimeError(f'Apple photos were published, but their host state could not be saved. '
                               f'Inspect recovery information at {recovery} before retrying.') from error


def _metadata(identity, files):
    root = Path(identity['root']).resolve(strict=True)
    database = cache_root(identity) / 'music-metadata.sqlite3'
    if not database.is_file():
        raise ValueError('Prepare Music for Linnet first, then update Apple OS.')
    rows = {}
    scope = cache_volume_scope(root)
    with closing(sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True)) as connection:
        for relative, size, mtime, value in connection.execute(
                'SELECT relative,size,mtime,value FROM metadata WHERE parser=? AND source=?',
                ('existing', scope)):
            key = (relative.casefold(), size, mtime)
            if key not in rows:
                rows[key] = json.loads(value)
    result = []
    aliases = {}
    for path, info in files:
        relative = path.relative_to(root).as_posix()
        cached = rows.get((relative.casefold(), info.st_size, info.st_mtime_ns))
        current = path.lstat()
        if (not isinstance(cached, dict) or
                cached.get('_source_stamp') != list(file_stamp(current))):
            raise ValueError(f'Prepare Music for Linnet first: {relative}')
        details = cached
        if details.get('rate', 0) <= 0 or details.get('frames', 0) <= 0:
            raise ValueError(f'Invalid music duration: {relative}')
        tags = details.get('tags') or {}
        def tag(name, fallback=''):
            return str(tags.get(name) or fallback).replace('\x00', '').strip()
        def number(value):
            first = str(value or '').split('/')[0]
            return int(first) if first.isdecimal() else 0
        def encoded(value):
            return base64.b64encode(value.encode('utf-8')).decode('ascii')
        artist = tag('artist', 'Unknown Artist')
        result.append([_apple_music_path(path, root, aliases), info.st_size,
                       round(details['frames'] * 1000 / details['rate']),
                       round(details['data_bytes'] * 8 * details['rate'] / details['frames'] / 1000),
                       details['rate'], number(tags.get('tracknumber') or tags.get('track')),
                       number(tags.get('discnumber') or tags.get('disc')),
                       encoded(tag('title', path.stem)), encoded(artist),
                       encoded(tag('album', 'Unknown Album')),
                       encoded(tag('albumartist', artist)), encoded(tag('genre'))])
    return result


def _video_rows(identity, files, ffprobe):
    root = Path(identity['root']).resolve(strict=True)
    rows, issues = [], []
    aliases = {}
    def encoded(value):
        return base64.b64encode(str(value).encode('utf-8')).decode('ascii')
    for path, info in files:
        try:
            if info.st_size <= 0 or info.st_size > 0xffffffff:
                raise ValueError(f'Apple video file size is unsupported: {path.relative_to(root)}')
            location = _apple_video_path(path, root, aliases)
            details = _video_probe(path, ffprobe)
            rows.append([location, info.st_size, details['duration_ms'],
                         details['bitrate_kbps'], details['sample_rate'], 0, 0,
                         encoded(details['title']), encoded(details['artist']),
                         encoded('Movies'), encoded(details['artist']), encoded('Video'),
                         'movie'])
        except (OSError, ValueError, TypeError, OverflowError, ZeroDivisionError) as error:
            issues.append(str(error))
    return rows, issues


def update(identity, *, ffprobe=None, progress=lambda text: None):
    """Update selected Apple media while preserving unrelated Apple entries."""
    identity = media.refresh(identity)
    device = _qualified_device(identity)
    if device is None:
        raise ValueError(_eligibility(identity))
    root = Path(identity['root']).resolve(strict=True)
    state = _load(identity)
    selected = _normalize(root, state.get('folders', []), selectable_roots(identity))
    files = _files(root, selected, 'Music', media.extensions('Music'))
    videos = _files(root, selected, 'Videos', media.extensions('Videos'))
    cache = cache_root(identity)
    cache.mkdir(parents=True, exist_ok=True)
    source_db = root / 'iPod_Control/iTunes/iTunesDB'
    sysinfo = root / 'iPod_Control/Device/SysInfo'
    _plain(source_db, root)
    _plain(sysinfo, root)
    if not sysinfo.is_file():
        raise ValueError('Apple device identity is missing from this iPod.')
    published = state.get('published') if isinstance(state.get('published'), dict) else {}
    # Resolve a photo ownership conflict before changing the music database.
    if _files(root, selected, 'Photos', media.extensions('Photos')) or published.get('photo_count', 0):
        photo_db = root / 'Photos/Photo Database'
        _plain(photo_db, root)
        photo_digest = _hash(photo_db) if photo_db.is_file() else None
        if photo_digest and photo_digest != published.get('photo_database_sha256'):
            raise ValueError('The Apple photo library changed outside Linnet. Review it before updating Photos.')
    if (published.get('music_source_signature') == _signature(root, files) and
            published.get('video_source_signature') == _signature(root, videos) and
            not published.get('music_issues') and not published.get('video_issues') and
            source_db.is_file() and published.get('database_sha256') == _hash(source_db)):
        _update_photos(identity, state, selected, cache, progress)
        counts = state['published']
        attention = len(counts.get('music_issues', [])) + len(counts.get('video_issues', []))
        summary = (f'{counts.get("music_count", 0):,} songs, '
                   f'{counts.get("video_ready_count", 0):,} videos and '
                   f'{counts.get("photo_count", 0):,} photos are ready in Apple OS.')
        if attention:
            summary += f' {attention:,} files need attention.'
        return {'summary': summary + ' Eject safely before switching systems.'}
    playable_music, music_issues, aliases = [], [], {}
    for path, info in files:
        try:
            if info.st_size <= 0 or info.st_size > 0xffffffff:
                raise ValueError(f'Apple music file size is unsupported: {path.relative_to(root)}')
            _apple_music_path(path, root, aliases)
            playable_music.append((path, info))
        except (OSError, ValueError) as error:
            music_issues.append(str(error))
    manifest = _metadata(identity, playable_music) if playable_music else []
    video_tool = ffprobe or shutil.which('ffprobe')
    if videos and not video_tool:
        raise ValueError('Choose FFprobe in Settings to check videos for Apple OS.')
    video_rows, video_issues = _video_rows(identity, videos, video_tool)
    manifest.extend(video_rows)
    writer = _writer(cache)
    progress(f'Preparing Apple OS library for {len(playable_music):,} songs and {len(video_rows):,} videos…')
    with tempfile.TemporaryDirectory(prefix='linnet-apple-', dir=cache) as directory:
        stage = Path(directory)
        stage_db = stage / 'iPod_Control/iTunes/iTunesDB'
        stage_db.parent.mkdir(parents=True)
        source_digest = _hash(source_db) if source_db.is_file() else None
        if source_db.is_file():
            shutil.copy2(source_db, stage_db)
        stage_sysinfo = stage / 'iPod_Control/Device/SysInfo'
        stage_sysinfo.parent.mkdir(parents=True)
        shutil.copy2(sysinfo, stage_sysinfo)
        manifest_path = stage / 'manifest.tsv'
        with manifest_path.open('w', encoding='ascii', newline='\n') as output:
            for row in manifest:
                output.write('\t'.join(map(str, row)) + '\n')
        _run_writer([writer, stage, manifest_path, device['model'],
                     '0x' + device['disk_serial']], timeout=300)
        if not stage_db.is_file() or stage_db.stat().st_size < 128:
            raise ValueError('Apple database writer produced no valid database.')
        from .retail_media import tracks, _path as apple_path
        parsed = tracks(stage)
        expected = {str(apple_path(stage, row[0]).resolve()).casefold():
                    2 if len(row) == 13 else 1 for row in manifest}
        # Existing Apple entries may also point into Music or Videos. Verify
        # the selected entries without counting those unrelated tracks.
        if len(expected) != len(manifest) or any(
                parsed.get(path, {}).get('media_type') != kind for path, kind in expected.items()):
            raise ValueError('Apple database did not retain the selected songs and videos.')
        digest = _hash(stage_db)
        backup = cache / ('apple-itunesdb-' + source_digest[:16] + '.bak') if source_digest else None
        recovery = cache / 'apple-database-recovery' / uuid.uuid4().hex / 'recovery.json'
        record = {'kind': 'Apple database', 'disk_serial': identity['disk_serial'],
                  'volume_serial': identity['volume_serial'],
                  'volume_unique_id': identity['volume_unique_id'],
                  'device_path': str(source_db), 'temporary_path': str(source_db.with_name('iTunesDB.linnet-tmp')),
                  'previous_sha256': source_digest, 'prepared_sha256': digest,
                  'previous_backup': str(backup) if backup else None, 'status': 'in_progress'}
        save_json(recovery, record)
        for path, original in (*files, *videos):
            current = path.stat()
            if file_stamp(current) != file_stamp(original):
                raise ValueError(f'Media changed during Apple OS preparation: {path.relative_to(root)}')
        with _exclusive(identity):
            _revalidate_device(identity, source_db)
            current_digest = _hash(source_db) if source_db.is_file() else None
            if current_digest != source_digest:
                raise ValueError('Apple database changed during preparation; review it before retrying.')
            if backup and not backup.is_file():
                shutil.copy2(source_db, backup)
            if backup and _hash(backup) != source_digest:
                raise ValueError(f'Apple database backup needs attention: {backup}')
            _revalidate_device(identity, source_db.parent)
            source_db.parent.mkdir(parents=True, exist_ok=True)
            temporary = source_db.with_name('iTunesDB.linnet-tmp')
            if temporary.exists():
                raise ValueError(f'An interrupted Apple database update needs attention: {temporary}')
            temporary_created = False
            try:
                _revalidate_device(identity, temporary)
                with temporary.open('xb') as destination:
                    temporary_created = True
                    with stage_db.open('rb') as prepared_source:
                        shutil.copyfileobj(prepared_source, destination)
                if _hash(temporary) != digest:
                    raise ValueError('Apple database readback did not match the prepared version.')
                _revalidate_device(identity, source_db, temporary)
                temporary.replace(source_db)
                temporary_created = False
            except Exception as failure:
                if temporary_created:
                    try:
                        _revalidate_device(identity, temporary)
                        temporary.unlink(missing_ok=True)
                    except Exception as stopped:
                        record['status'] = 'needs_manual_recovery'
                        try:
                            save_json(recovery, record)
                        except OSError:
                            pass
                        raise _recovery_error('database', failure,
                                              recovery,
                                              stopped) from failure
                raise
            record['status'] = 'published'
            try:
                save_json(recovery, record)
            except OSError as error:
                raise RuntimeError(f'Apple database was published, but its recovery record could not be '
                                   f'updated at {recovery}. The previous backup is {backup}.') from error
        published = state.get('published') if isinstance(state.get('published'), dict) else {}
        published.update(music_signature=_signature(root, playable_music),
                         music_source_signature=_signature(root, files),
                         video_source_signature=_signature(root, videos),
                         video_count=len(videos), video_ready_count=len(video_rows),
                         video_issues=video_issues, music_issues=music_issues,
                         database_sha256=digest, music_count=len(playable_music))
        state['published'] = published
        try:
            save_json(_state_path(identity), state)
        except OSError as error:
            record['status'] = 'published_without_host_state'
            try:
                save_json(recovery, record)
            except OSError:
                pass
            raise RuntimeError(f'Apple database was published, but its host state could not be saved. '
                               f'Inspect recovery information at {recovery} before retrying.') from error
    _update_photos(identity, state, selected, cache, progress)
    summary = (f'{len(playable_music):,} songs, {len(video_rows):,} videos and '
               f'{state["published"].get("photo_count", 0):,} photos are ready in Apple OS.')
    if music_issues or video_issues:
        summary += f' {len(music_issues) + len(video_issues):,} files need attention.'
    return {'summary': summary + ' Eject safely before switching systems.'}
