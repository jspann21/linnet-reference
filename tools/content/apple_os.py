"""Apple OS folder availability on the validated A1238 volume.

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
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import tomllib
import uuid
from fractions import Fraction

from . import media_manager as media
from .music import _device_media_path
from .publish import _exclusive, _hash, _plain, _volume_guard


APPLE_SERIAL = '000A2700155D9C10'
APPLE_TARGET = 'classic6g-n25'
ROOTS = ('Music', 'Photos', 'Videos', 'Notes')
SELECTABLE_ROOTS = ROOTS[:3]
APPLE_MUSIC_PREFIX = ':iPod_Control:Music:..:..:Music:'


def supported(identity):
    return (identity.get('target_id') == APPLE_TARGET and
            identity.get('disk_serial') == APPLE_SERIAL and
            identity.get('filesystem') == 'FAT32')


def _state_path(identity):
    return media.cache_root(identity) / 'apple-os.json'


def _load(identity):
    try:
        value = json.loads(_state_path(identity).read_text(encoding='utf-8'))
        if isinstance(value, dict) and value.get('device_serial') == identity['disk_serial']:
            return value
    except (OSError, ValueError, KeyError):
        pass
    return {'device_serial': identity['disk_serial'], 'folders': [],
            'configured': False, 'published': None}


def _valid_folder(root, value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Invalid Apple OS folder selection')
    relative = Path(value)
    if (relative.is_absolute() or relative.drive or '..' in relative.parts or
            not relative.parts or relative.parts[0] not in SELECTABLE_ROOTS or
            relative.as_posix() != value):
        raise ValueError('Apple OS folder is outside the media folders')
    folder = root / relative
    _plain(folder, root)
    if not folder.is_dir() or not folder.resolve(strict=True).is_relative_to(root):
        raise ValueError(f'Apple OS folder is unavailable: {value}')
    return folder


def _normalize(root, folders):
    values = sorted(set(folders), key=lambda x: (x.casefold(), x))
    result = []
    for value in values:
        _valid_folder(root, value)
        if not any(value.casefold() == parent.casefold() or
                   value.casefold().startswith(parent.casefold() + '/') for parent in result):
            result.append(value)
    return result


def _walk_folders(root):
    result = []
    for kind in ROOTS:
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


def _folder_rows(root, records_by_kind):
    paths = set()
    for kind in ROOTS:
        if (root / kind).is_dir():
            paths.add(kind)
        for path, _ in records_by_kind[kind]:
            if not path.is_relative_to(root / kind):
                continue
            parent = path.parent
            while parent.is_relative_to(root / kind):
                paths.add(parent.relative_to(root).as_posix())
                parent = parent.parent
    return [{'path': value, 'kind': value.split('/')[0]}
            for value in sorted(paths, key=lambda x: (ROOTS.index(x.split('/')[0]),
                                                      len(Path(x).parts), x.casefold()))]


def _files(root, folders, kind, extensions, records_by_kind=None):
    found = {}
    for value in folders:
        if value.split('/')[0] != kind:
            continue
        folder = _valid_folder(root, value)
        records = (media._file_records(folder, allowed=extensions) if records_by_kind is None else
                   ((path, info) for path, info in records_by_kind[kind]
                    if path.is_relative_to(folder) and path.suffix.lower() in extensions))
        for path, info in records:
            found[path.relative_to(root).as_posix().casefold()] = (path, info)
    return [found[key] for key in sorted(found)]


def _signature(files):
    rows = [(str(path), info.st_size, info.st_mtime_ns) for path, info in files]
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


def inspect(identity, *, records_by_kind=None):
    """Return folder choices and readiness without writing the device."""
    root = Path(identity['root']).resolve(strict=True)
    if not supported(identity):
        return {'supported': False, 'folders': [], 'selected': [],
                'status': 'Apple OS folder updates are not yet validated for this iPod.',
                'details': []}
    folders = (_folder_rows(root, records_by_kind) if records_by_kind is not None else
               _walk_folders(root))
    state = _load(identity)
    selected = [value for value in state.get('folders', [])
                if isinstance(value, str) and (root / value).is_dir()]
    # Adopt the existing validated Apple music library on this A1238 once.
    adopted = False
    if (not selected and not state.get('configured') and state.get('published') is None
            and (root / 'Music').is_dir()):
        try:
            from .retail_media import available_tracks
            if any(row.get('path', '').casefold().startswith(str(root / 'Music').casefold())
                   for row in available_tracks(root).values()):
                selected = ['Music']
                adopted = True
        except (OSError, ValueError):
            pass
    music = _files(root, selected, 'Music', media.extensions('Music'), records_by_kind)
    published = state.get('published') if isinstance(state.get('published'), dict) else {}
    db = root / 'iPod_Control/iTunes/iTunesDB'
    source_stamp = _signature(music)
    digest = _hash(db) if db.is_file() else None
    same_published = (published.get('music_source_signature') == source_stamp and
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
        stamp = _signature(playable_music)
    if issues and same_published:
        music_status = f'{len(music) - playable_count} music paths need attention'
    elif issues:
        music_status = 'Needs update'
    elif not selected and published.get('music_count', 0):
        music_status = 'Needs update'
    elif not selected:
        music_status = 'No music folders selected'
    elif adopted:
        from .retail_media import available_tracks
        apple_paths = set(available_tracks(root))
        local_paths = {str(path.resolve()).casefold() for path, _ in music}
        music_status = ('Ready' if local_paths <= apple_paths else 'Needs update')
    elif (published.get('music_signature') == stamp and
          published.get('database_sha256') == digest):
        music_status = 'Ready'
    else:
        music_status = 'Needs update'
    details = [{'kind': 'Music', 'count': len(music), 'status': music_status}]
    photos = _files(root, selected, 'Photos', media.extensions('Photos'), records_by_kind)
    photo_db = root / 'Photos/Photo Database'
    photo_digest = _hash(photo_db) if photo_db.is_file() else None
    if photos:
        if photo_digest and published.get('photo_database_sha256') not in (None, photo_digest):
            photo_status = 'Apple photo library changed outside Linnet'
        elif photo_digest and not published.get('photo_database_sha256'):
            photo_status = 'Existing Apple photo library needs review'
        elif (published.get('photo_signature') == _signature(photos) and
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
                 media._file_records(root / 'Notes'))
        notes = [(path, info) for path, info in notes
                 if path.is_relative_to(root / 'Notes') and path.name.casefold() != 'instructions']
        native = [(path, info) for path, info in notes
                  if path.suffix.lower() == '.txt' and info.st_size <= 4096]
        note_issues = len(notes) - len(native)
        note_status = ('Apple Notes reads .txt files here automatically' if len(native) == len(notes) else
                       f'{len(notes) - len(native)} notes need a short plain-text file')
        details.append({'kind': 'Notes', 'count': len(notes), 'status': note_status})
    videos = _files(root, selected, 'Videos', media.extensions('Videos'), records_by_kind)
    video_stamp = _signature(videos)
    saved_video_issues = (published.get('video_issues', [])
                          if published.get('video_source_signature') == video_stamp and
                          isinstance(published.get('video_issues'), list) else [])
    if videos or published.get('video_count', 0):
        if published.get('video_source_signature') != video_stamp or published.get('database_sha256') != digest:
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
            'can_update': can_update}


def save_selection(identity, folders):
    identity = media.refresh(identity)
    if not supported(identity):
        raise ValueError('Apple OS folder updates are not validated for this iPod.')
    root = Path(identity['root']).resolve(strict=True)
    selected = _normalize(root, folders)
    state = _load(identity)
    state['folders'] = selected
    state['configured'] = True
    media._save(_state_path(identity), state)
    return selected


def _wsl_path(path, distribution):
    result = subprocess.run(['wsl.exe', '-d', distribution, '--', 'wslpath', '-a', Path(path).as_posix()],
                            capture_output=True, text=True, timeout=30, check=True)
    return result.stdout.strip()


def _run_wsl(distribution, arguments, *, timeout=120):
    result = subprocess.run(['wsl.exe', '-d', distribution, '--', *arguments],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Apple database tool failed')
    return result


def _writer(distribution, cache, kind='music'):
    if kind not in ('music', 'photos'):
        raise ValueError('Unknown Apple database writer')
    source = Path(__file__).resolve().parent.parent / f'maintenance/a1238_apple/managed_{kind}.c'
    output = cache / f'managed-apple-{kind}'
    if output.is_file() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return output
    flags = _run_wsl(distribution, ['pkg-config', '--cflags', '--libs', 'libgpod-1.0']).stdout
    temporary = output.with_name(output.name + '.tmp')
    _run_wsl(distribution, ['gcc', _wsl_path(source, distribution), *shlex.split(flags),
                            '-o', _wsl_path(temporary, distribution)], timeout=180)
    temporary.replace(output)
    return output


def _update_photos(identity, state, selected, distribution, cache, progress):
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
    if (published.get('photo_signature') == _signature(photos) and
            published.get('photo_database_sha256') == old_digest):
        return
    source_bytes = sum(info.st_size for _, info in photos)
    work_bytes = max(64 * 1024 * 1024, len(photos) * 256 * 1024) if photos else 1024 * 1024
    if source_bytes + work_bytes > shutil.disk_usage(cache).free:
        raise ValueError('Not enough computer space to prepare these Apple photos.')
    progress(f'Preparing {len(photos):,} photos for Apple OS…')
    writer = _writer(distribution, cache, 'photos')
    with tempfile.TemporaryDirectory(prefix='linnet-apple-photos-', dir=cache) as directory:
        stage = Path(directory)
        sysinfo = stage / 'iPod_Control/Device/SysInfo'
        sysinfo.parent.mkdir(parents=True)
        shutil.copy2(root / 'iPod_Control/Device/SysInfo', sysinfo)
        source = stage / 'source'
        source.mkdir()
        linux_source = _wsl_path(source, distribution).rstrip('/')
        lines = []
        for index, (path, info) in enumerate(photos, 1):
            if info.st_size > 128 * 1024 * 1024:
                raise ValueError(f'Photo is too large for Apple OS preparation: {path.relative_to(root)}')
            destination = source / f'{index:06}{path.suffix.lower()}'
            shutil.copy2(path, destination)
            if (destination.stat().st_size, destination.stat().st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                raise ValueError(f'Photo changed during preparation: {path.relative_to(root)}')
            lines.append(linux_source + '/' + destination.name)
        manifest = stage / 'photos.txt'
        manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        _run_wsl(distribution, [_wsl_path(writer, distribution), _wsl_path(stage, distribution),
                                _wsl_path(manifest, distribution)], timeout=max(300, len(photos) * 2))
        prepared = stage / 'Photos/Photo Database'
        if not prepared.is_file() or prepared.stat().st_size < 128:
            raise ValueError('Apple photo writer produced no valid database.')
        from .retail_media import images
        visible = images(stage)
        if len(visible) != len(photos):
            raise ValueError(f'Apple photo database contains {len(visible)} images, expected {len(photos)}.')
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
        changed = []
        with _exclusive(identity):
            _volume_guard(identity)
            try:
                for source_file in outputs:
                    relative = source_file.relative_to(stage)
                    target = root / relative
                    _plain(target, root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    prior = backup / relative
                    if target.exists():
                        prior.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, prior)
                    temporary = target.with_name(target.name + '.linnet-tmp')
                    if temporary.exists():
                        raise ValueError('An interrupted Apple photo update needs attention.')
                    try:
                        shutil.copyfile(source_file, temporary)
                        expected = _hash(source_file)
                        if _hash(temporary) != expected:
                            raise ValueError(f'Apple photo readback failed: {relative}')
                        _volume_guard(identity)
                        temporary.replace(target)
                        changed.append((target, prior))
                    finally:
                        temporary.unlink(missing_ok=True)
            except Exception:
                for target, prior in reversed(changed):
                    if prior.is_file():
                        shutil.copy2(prior, target)
                    else:
                        target.unlink(missing_ok=True)
                raise
        published.update(photo_signature=_signature(photos),
                         photo_database_sha256=_hash(prepared),
                         photo_count=len(photos))
        state['published'] = published
        media._save(_state_path(identity), state)


def _metadata(identity, files):
    root = Path(identity['root']).resolve(strict=True)
    database = media.cache_root(identity) / 'music-metadata.sqlite3'
    if not database.is_file():
        raise ValueError('Prepare Music for Linnet first, then update Apple OS.')
    rows = {}
    with sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True) as connection:
        for relative, size, mtime, value in connection.execute(
                'SELECT relative,size,mtime,value FROM metadata WHERE source=? AND parser=?',
                (str(root), 'existing')):
            rows[relative.casefold()] = (size, mtime, json.loads(value))
    result = []
    aliases = {}
    for path, info in files:
        relative = path.relative_to(root).as_posix()
        cached = rows.get(relative.casefold())
        if cached is None or cached[:2] != (info.st_size, info.st_mtime_ns):
            raise ValueError(f'Prepare Music for Linnet first: {relative}')
        details = cached[2]
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
    if not supported(identity):
        raise ValueError('Apple OS folder updates are not validated for this iPod.')
    root = Path(identity['root']).resolve(strict=True)
    state = _load(identity)
    selected = _normalize(root, state.get('folders', []))
    files = _files(root, selected, 'Music', media.extensions('Music'))
    videos = _files(root, selected, 'Videos', media.extensions('Videos'))
    cache = media.cache_root(identity)
    cache.mkdir(parents=True, exist_ok=True)
    config = Path(__file__).resolve().parents[2] / 'config/toolchain.toml'
    distribution = tomllib.loads(config.read_text(encoding='utf-8'))['toolchain']['windows_wsl_distribution']
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
    if (published.get('music_source_signature') == _signature(files) and
            published.get('video_source_signature') == _signature(videos) and
            not published.get('music_issues') and not published.get('video_issues') and
            source_db.is_file() and published.get('database_sha256') == _hash(source_db)):
        _update_photos(identity, state, selected, distribution, cache, progress)
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
    writer = _writer(distribution, cache)
    progress(f'Preparing Apple OS library for {len(playable_music):,} songs and {len(video_rows):,} videos…')
    with tempfile.TemporaryDirectory(prefix='linnet-apple-', dir=cache) as directory:
        stage = Path(directory)
        stage_db = stage / 'iPod_Control/iTunes/iTunesDB'
        stage_db.parent.mkdir(parents=True)
        if source_db.is_file():
            shutil.copy2(source_db, stage_db)
        stage_sysinfo = stage / 'iPod_Control/Device/SysInfo'
        stage_sysinfo.parent.mkdir(parents=True)
        shutil.copy2(sysinfo, stage_sysinfo)
        manifest_path = stage / 'manifest.tsv'
        with manifest_path.open('w', encoding='ascii', newline='\n') as output:
            for row in manifest:
                output.write('\t'.join(map(str, row)) + '\n')
        _run_wsl(distribution, [_wsl_path(writer, distribution), _wsl_path(stage, distribution),
                                _wsl_path(manifest_path, distribution)], timeout=300)
        if not stage_db.is_file() or stage_db.stat().st_size < 128:
            raise ValueError('Apple database writer produced no valid database.')
        from .retail_media import tracks
        parsed = tracks(stage)
        managed = [row for row in parsed.values()
                   if Path(row['path']).is_relative_to(stage / 'Music')]
        movies = [row for row in parsed.values()
                  if Path(row['path']).is_relative_to(stage / 'Videos') and row['media_type'] == 2]
        if len(managed) != len(playable_music) or len(movies) != len(video_rows):
            raise ValueError('Apple database did not retain the selected songs and videos.')
        digest = _hash(stage_db)
        backup = cache / ('apple-itunesdb-' + _hash(source_db)[:16] + '.bak') if source_db.is_file() else None
        with _exclusive(identity):
            _volume_guard(identity)
            current = media.refresh(identity)
            if current['disk_serial'] != identity['disk_serial']:
                raise ValueError('iPod changed during Apple OS update')
            if backup and not backup.is_file():
                shutil.copy2(source_db, backup)
            source_db.parent.mkdir(parents=True, exist_ok=True)
            temporary = source_db.with_name('iTunesDB.linnet-tmp')
            if temporary.exists():
                raise ValueError('An interrupted Apple database update needs attention.')
            try:
                shutil.copyfile(stage_db, temporary)
                if _hash(temporary) != digest:
                    raise ValueError('Apple database readback did not match the prepared version.')
                _volume_guard(identity)
                temporary.replace(source_db)
            finally:
                temporary.unlink(missing_ok=True)
        published = state.get('published') if isinstance(state.get('published'), dict) else {}
        published.update(music_signature=_signature(playable_music),
                         music_source_signature=_signature(files),
                         video_source_signature=_signature(videos),
                         video_count=len(videos), video_ready_count=len(video_rows),
                         video_issues=video_issues, music_issues=music_issues,
                         database_sha256=digest, music_count=len(playable_music))
        state['published'] = published
        media._save(_state_path(identity), state)
    _update_photos(identity, state, selected, distribution, cache, progress)
    summary = (f'{len(playable_music):,} songs, {len(video_rows):,} videos and '
               f'{state["published"].get("photo_count", 0):,} photos are ready in Apple OS.')
    if music_issues or video_issues:
        summary += f' {len(music_issues) + len(video_issues):,} files need attention.'
    return {'summary': summary + ' Eject safely before switching systems.'}
