"""Read-only preparation plans and verified library status for the desktop UI."""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import stat
import time

from . import media_manager as media
from . import media_library
from .host_state import cache_directory, cache_root, load_json_object, save_json
from .inventory import collect_records_by_kind as records_by_kind, skipped_paths, scan as scan_sources


@lru_cache(maxsize=4)
def _verification_cache(disk_serial, volume_serial, partition_offset, cache_disk_serial):
    # A refresh still stats each file. Reuse a recent hash across app restarts
    # only for this exact disk, volume and partition; changed stamps are read.
    # Native Disk Mode can reuse a verified Apple cache directory. Keep the
    # live disk identity in the memory key while reading the same file we save.
    path = cache_directory(cache_disk_serial or disk_serial, volume_serial) / 'verified-outputs.json'
    cache = dict(verified_at=time.time(), files={})
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return cache
        saved = json.loads(path.read_text(encoding='utf-8'))
        verified_at = saved.get('verified_at')
        if (saved.get('partition_offset') != partition_offset or
                type(verified_at) not in (int, float) or
                not 0 <= cache['verified_at'] - verified_at <= 3600):
            return cache
        rows = saved.get('files', [])
        if not isinstance(rows, list) or len(rows) > 4096:
            return cache
        cache['files'] = {(row[0], row[1]): tuple(row[2:]) for row in rows
                if (isinstance(row, list) and len(row) == 6 and
                    isinstance(row[0], str) and isinstance(row[1], str) and
                    all(type(value) is int for value in row[2:]))}
        cache['verified_at'] = verified_at
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return cache


def _verified_outputs(disk_serial, volume_serial, partition_offset, *, cache_disk_serial=None):
    cache = _verification_cache(disk_serial, volume_serial, partition_offset, cache_disk_serial)
    now = time.time()
    # Expire memory entries too, including after a clock rollback. Preserving
    # the loaded timestamp prevents refreshes from extending persisted hashes.
    if not 0 <= now - cache['verified_at'] <= 3600:
        cache['files'].clear()
        cache['verified_at'] = now
    return cache['files']


def _remember_verified(identity, verified, before):
    if verified == before:
        return
    path = cache_root(identity) / 'verified-outputs.json'
    try:
        # Keep the newest verified stamps when a large library exceeds the
        # cache bound. Older outputs will simply be hashed on the next launch.
        if len(verified) > 4096:
            for key in list(verified)[:-4096]:
                del verified[key]
        verified_at = time.time()
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
            old_time = previous.get('verified_at')
            if (previous.get('partition_offset') == identity['partition_offset'] and
                    type(old_time) in (int, float) and
                    0 <= verified_at - old_time <= 3600):
                verified_at = old_time
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        save_json(path, {'partition_offset': identity['partition_offset'],
                           'verified_at': verified_at,
                           'files': [[name, digest, *stamp]
                                     for (name, digest), stamp in verified.items()]})
    except OSError:
        # This optional host cache must not change device readiness.
        pass


def _video_readiness(inventory, published, identity=None, state=None, verified=None):
    state = state if isinstance(state, dict) else {}
    video_state = state.get('Videos', {})
    if not isinstance(video_state, dict):
        video_state = {}
    video_files = state.get('video_files', {})
    if not isinstance(video_files, dict):
        video_files = {}
    source_extensions = media.video_source_extensions(identity)
    native_extensions = media.native_video_extensions(identity)
    compatible_files = [value for value in inventory['files']
                        if Path(value).suffix.lower() in source_extensions]
    published = [row for row in published
                 if Path(row['path']).suffix.lower() in native_extensions]
    root = Path(identity['root']).resolve() if identity else None
    if ((compatible_files or published) and identity and
            identity['media_profile'].get('video_backend') == 'bcm-mp4' and
            any(not (root / '.LINNET' / 'BCM' / name).is_file() for name in
                ('VMCS.BIN', 'MPLAYER.VLL', 'H264DEC.VLL', 'MPG4DEC.VLL',
                 'AACDEC.VLL', 'PASSTHRU.VLL'))):
        return 'Video resources missing on iPod'
    if compatible_files and identity and video_state.get('media_profile') != identity['media_profile']:
        return 'Needs update'
    ready = [row for row in published if row['status'] == 'Ready on iPod']
    missing = [row for row in published if row['status'] != 'Ready on iPod']
    cataloged = {row['path'].casefold() for row in ready}
    if missing:
        return 'Needs update'
    # Scan and library rows already carry absolute device paths. Recheck each
    # source without following a link that appeared since traversal.
    for value in compatible_files:
        source = Path(value)
        if str(source).casefold() in cataloged:
            continue
        if root is None:
            return 'Needs update'
        relative = source.relative_to(root / 'Videos').as_posix() if source.is_relative_to(root / 'Videos') else source.relative_to(root).as_posix()
        saved = video_files.get(relative, {})
        if not isinstance(saved, dict):
            return 'Needs update'
        try:
            info = source.lstat()
        except OSError:
            return 'Needs update'
        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            return 'Needs update'
        if (saved.get('source_stamp') != [info.st_size, info.st_mtime_ns] or
                not media._outputs_match(root, saved.get('outputs', []), verified=verified)):
            return 'Needs update'
    if ready:
        return 'Ready'
    return 'Not prepared' if compatible_files else 'No compatible videos' if inventory['count'] else 'No content yet'


def _preparation_state(identity):
    try:
        return load_json_object(cache_root(identity) / 'state.json', encoding=None)
    except (OSError, ValueError):
        return {}


def inspect(identity, photo_dimension=640, verification="metadata"):
    from tools.studio import installer
    boot_review = installer.assess(identity)
    identity = boot_review['identity']
    root = Path(identity['root'])
    verified = _verified_outputs(identity['disk_serial'], identity['volume_serial'],
                                 identity['partition_offset'],
                                 cache_disk_serial=identity.get('media_cache_disk_serial'))
    if len(verified) > 4096:
        verified.clear()
    verified_before = verified.copy()
    identity['linnet'] = boot_review['linnet']
    identity['default_boot'] = installer.default_boot(boot_review)
    state = _preparation_state(identity)
    skipped = {kind: skipped_paths(state, kind) for kind in media.KINDS}
    # Inventory and visible rows describe the same refresh. Traverse the iPod
    # once, retaining excluded files for the library's removal controls.
    records = records_by_kind(root)
    from .retail_media import images
    retail_photos = images(root)
    inventory = scan_sources(root, skipped=skipped, records_by_kind=records, retail_photos=retail_photos,
                           fingerprint_kinds=('Music', 'Notes', 'Photos'))
    rows = media_library.list_items(identity, records_by_kind=records, retail_photos=retail_photos,
                                    _validated_identity=True)
    readiness = {}
    for kind in media.KINDS:
        saved = state.get(kind, {})
        if not isinstance(saved, dict):
            saved = {}
        published = [r for r in rows if r['kind'] == kind and r['category'] in ('library', 'published')]
        if kind == 'Videos':
            readiness[kind] = _video_readiness(inventory[kind], published, identity, state, verified)
            continue
        option = media.preparation_option(kind, identity, photo_dimension, verification)
        signature = f"{option}:{inventory[kind]['fingerprint']}"
        if (saved.get('signature') == signature and saved.get('outputs') and
                media._outputs_match(root, saved['outputs'], verified=verified)):
            readiness[kind] = 'Ready'
        elif published:
            readiness[kind] = 'Needs update' if inventory[kind]['count'] else 'Prepared library retained'
        else:
            readiness[kind] = 'Not prepared' if inventory[kind]['count'] else 'No content yet'
    for row in rows:
        if row['id'].startswith('retail-photo:'):
            relative = Path(row['path']).relative_to(root).as_posix().casefold()
            row['status'] = ('Excluded from preparation' if relative in skipped['Photos']
                             else 'iTunes photo · ' + readiness['Photos'])
    for row in rows:
        path = Path(row['path'])
        if path.is_relative_to(root) and path.relative_to(root).as_posix().casefold() in skipped.get(row['kind'], set()):
            row['status'] = 'Excluded from preparation'
    from . import apple_os
    apple = apple_os.inspect(identity, records_by_kind=records)
    _remember_verified(identity, verified, verified_before)
    return identity, inventory, rows, readiness, apple, boot_review


def plan(identity, pending, selected, videos, *, current_inventory=None,
         photo_dimension=640, music_verification='metadata', force=False,
         online_artwork=False):
    identity = media.refresh(identity)
    unsupported = [kind for kind in selected if kind not in media.supported_kinds(identity)]
    if unsupported:
        raise ValueError(f"{', '.join(unsupported)} playback is unavailable on this iPod model.")
    root = Path(identity['root'])
    state = _preparation_state(identity)
    skipped = {kind: skipped_paths(state, kind) for kind in media.KINDS}
    if videos is not None:
        videos = [value for value in videos
                  if Path(value).resolve().relative_to(root).as_posix().casefold()
                  not in skipped['Videos']]
    included = [p for p in pending if p[0] in selected]
    snapshots = {}
    copies = media.additions(root, [p for p in included if p[0] != 'Videos'], snapshots=snapshots)
    jobs = media.video_jobs(root, included, videos, skipped=skipped['Videos'], identity=identity,
                            snapshots=snapshots) if 'Videos' in selected else []
    previews = {}
    for kind, name in included:
        source = Path(name).absolute().resolve(strict=True)
        records = snapshots[source]
        allowed = media.video_source_extensions(identity) if kind == 'Videos' else media.extensions(kind)
        supported = sum(p.suffix.lower() in allowed for p, _ in records)
        other = len(records) - supported
        previews[name] = f'{supported} media files' + (f' · {other} supporting/other files' if other else '')
        if kind == 'Videos' and other:
            previews[name] = f'{supported} videos · {other} non-video files skipped'
    needed = sum(p['bytes'] for p in copies)
    if needed + 1048576 > identity['free_bytes']:
        raise ValueError('Not enough iPod space for these originals. Remove additions from the queue.')
    if 'Notes' in selected:
        total = scan_sources(root, ('Notes',), skipped=skipped)['Notes']['count'] + sum(p['kind'] == 'Notes' and Path(p['source']).suffix.lower() in media.extensions('Notes') for p in copies)
        if total > 256:
            raise ValueError(f'Notes supports 256 files; this update includes {total}.')
    cache = cache_root(identity)
    parent = cache
    while not parent.exists():
        parent = parent.parent
    copy_kinds = {kind: sum(item['kind'] == kind for item in copies) for kind in selected}
    reusable = []
    if current_inventory and not force:
        for kind in selected:
            if copy_kinds[kind] or kind == 'Videos' or (kind == 'Music' and
                    (online_artwork or music_verification == 'full')):
                continue
            item = current_inventory.get(kind)
            saved = state.get(kind)
            if not isinstance(item, dict) or not isinstance(saved, dict) or not item.get('count'):
                continue
            option = media.preparation_option(kind, identity, photo_dimension, music_verification)
            if (saved.get('signature') == f"{option}:{item.get('fingerprint')}" and
                    isinstance(saved.get('outputs'), list) and saved['outputs']):
                reusable.append(kind)
    return dict(copies=len(copies), bytes=needed, videos=len(jobs), free=identity['free_bytes'], previews=previews,
                conversion=any(Path(j['source']).suffix.lower() not in media.native_video_extensions(identity) for j in jobs),
                computer_free=shutil.disk_usage(parent).free, excluded=len(pending)-len(included),
                copy_kinds=copy_kinds, selected=list(selected), reusable=reusable)
