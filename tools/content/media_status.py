"""Read-only preparation plans and verified library status for the desktop UI."""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
from pathlib import Path
import stat
import time

from . import media_manager as media
from . import media_library
from .host_state import cache_directory, cache_root, load_json_object, save_json
from .inventory import collect_records_by_kind as records_by_kind, skipped_paths, scan as scan_sources


def _verification_name(name):
    """Validate device-relative file names stored in the verification cache."""
    path = Path(name)
    if (path.is_absolute() or path.drive or not path.parts or '..' in path.parts or
            path.parts[0].casefold() not in {'.linnet', 'music', 'videos', 'ipod_control'}):
        return None
    return path.as_posix()


class _VerifiedFiles(dict):
    """Expire retained hashes even during a long preparation or status scan."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def refresh(self):
        now = time.time()
        if not 0 <= now - self.owner['verified_at'] <= 3600:
            super().clear()
            self.owner['verified_at'] = now

    def get(self, key, default=None):
        self.refresh()
        return super().get(key, default)

    def __setitem__(self, key, value):
        self.refresh()
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        self.refresh()
        super().update(*args, **kwargs)

    def copy(self):
        self.refresh()
        return dict(self)


@lru_cache(maxsize=4)
def _verification_cache(disk_serial, volume_serial, partition_offset, volume_unique_id,
                        cache_disk_serial):
    # A refresh still stats each file. Reuse a recent hash across app restarts
    # only for this exact disk, volume and partition; changed stamps are read.
    # Native Disk Mode can reuse a verified Apple cache directory. Keep the
    # live disk identity in the memory key while reading the same file we save.
    path = cache_directory(cache_disk_serial or disk_serial, volume_serial) / 'verified-outputs.json'
    cache = dict(verified_at=time.time())
    cache['files'] = _VerifiedFiles(cache)
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return cache
        saved = json.loads(path.read_text(encoding='utf-8'))
        verified_at = saved.get('verified_at')
        if (saved.get('partition_offset') != partition_offset or
                saved.get('volume_unique_id', '').casefold() != volume_unique_id.casefold() or
                type(verified_at) not in (int, float) or
                not 0 <= cache['verified_at'] - verified_at <= 3600):
            return cache
        rows = saved.get('files', [])
        if not isinstance(rows, list) or len(rows) > 4096:
            return cache
        for row in rows:
            if (not isinstance(row, list) or len(row) != 6 or
                    not isinstance(row[0], str) or not isinstance(row[1], str) or
                    not all(type(value) is int for value in row[2:])):
                continue
            name = _verification_name(row[0])
            if name is not None:
                cache['files'][(name, row[1])] = tuple(row[2:])
        cache['verified_at'] = verified_at
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return cache


def _verified_outputs(disk_serial, volume_serial, partition_offset, volume_unique_id,
                      *, cache_disk_serial=None):
    cache = _verification_cache(disk_serial, volume_serial, partition_offset,
                                volume_unique_id, cache_disk_serial)
    now = time.time()
    # Expire memory entries too, including after a clock rollback. Preserving
    # the loaded timestamp prevents refreshes from extending persisted hashes.
    if not 0 <= now - cache['verified_at'] <= 3600:
        cache['files'].clear()
        cache['verified_at'] = now
    return cache['files']


def _remember_verified(identity, verified, before):
    verified.refresh()
    if verified == before:
        return
    if not verified:
        return
    path = cache_root(identity) / 'verified-outputs.json'
    try:
        # Keep the newest verified stamps when a large library exceeds the
        # cache bound. Older outputs will simply be hashed on the next launch.
        if len(verified) > 4096:
            for key in list(verified)[:-4096]:
                del verified[key]
        now = time.time()
        verified_at = verified.owner['verified_at']
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
            old_time = previous.get('verified_at')
            if (previous.get('partition_offset') == identity['partition_offset'] and
                    previous.get('volume_unique_id', '').casefold() == identity['volume_unique_id'].casefold() and
                    type(old_time) in (int, float) and
                    0 <= now - old_time <= 3600):
                verified_at = min(verified_at, old_time)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        save_json(path, {'partition_offset': identity['partition_offset'],
                           'volume_unique_id': identity['volume_unique_id'],
                           'verified_at': verified_at,
                           'files': [[name, digest, *stamp]
                                     for (name, digest), stamp in verified.items()]})
    except OSError:
        # This optional host cache must not change device readiness.
        pass


def _video_readiness(inventory, published, identity, state=None, verified=None):
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
    root = Path(identity['root']).resolve()
    if ((compatible_files or published) and
            identity['media_profile'].get('video_backend') == 'bcm-mp4' and
            any(not (root / '.LINNET' / 'BCM' / name).is_file() for name in
                ('VMCS.BIN', 'MPLAYER.VLL', 'H264DEC.VLL', 'MPG4DEC.VLL',
                 'AACDEC.VLL', 'PASSTHRU.VLL'))):
        return 'Video resources missing on iPod'
    if compatible_files and video_state.get('media_profile') != identity['media_profile']:
        return 'Needs update'
    ready = [row for row in published if row['status'] == 'Ready on iPod']
    missing = [row for row in published if row['status'] != 'Ready on iPod']
    cataloged = {row['path'].casefold() for row in ready}
    generated = {str(root / output[0]).casefold()
                 for relative, saved in video_files.items()
                 if isinstance(relative, str) and isinstance(saved, dict)
                 for output in (saved.get('outputs') if isinstance(saved.get('outputs'), list) else [])
                 if isinstance(output, (list, tuple))
                 and len(output) == 2 and isinstance(output[0], str)
                 and output[0].casefold().startswith('videos/')
                 and output[0].casefold() != ('Videos/' + relative).casefold()}
    if missing:
        return 'Needs update'
    if any(not Path(path).resolve().is_relative_to(root) or Path(path).is_file()
           for path in generated - cataloged):
        return 'Needs update'
    # A computer import can have only its published package on the iPod. It
    # still needs a stored digest and a readback, even with no source row.
    saved_outputs = {}
    if ready:
        for saved in video_files.values():
            if not isinstance(saved, dict):
                continue
            outputs = saved.get('outputs')
            if not isinstance(outputs, list):
                continue
            for output in outputs:
                if (isinstance(output, (list, tuple)) and len(output) == 2 and
                        isinstance(output[0], str)):
                    saved_outputs.setdefault(str(root / output[0]).casefold(), output)
    for row in ready:
        output = saved_outputs.get(row['path'].casefold())
        if output is None or not media._outputs_match(root, [output], verified=verified):
            return 'Needs update'
    # Scan and library rows already carry absolute device paths. Recheck each
    # source without following a link that appeared since traversal.
    for value in compatible_files:
        source = Path(value)
        if str(source).casefold() in generated:
            continue
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
        outputs = saved.get('outputs', [])
        if (saved.get('source_stamp') != [info.st_size, info.st_mtime_ns] or
                not media._outputs_match(root, outputs, verified=verified)):
            return 'Needs update'
        if str(source).casefold() in cataloged and not any(
                str(root / name).casefold() == str(source).casefold()
                for name, _ in outputs):
            return 'Needs update'
    if ready:
        return 'Ready'
    return 'Not prepared' if compatible_files else 'No compatible videos' if inventory['count'] else 'No content yet'


def _preparation_state(identity):
    try:
        return load_json_object(cache_root(identity) / 'state.json', encoding=None)
    except (OSError, ValueError):
        return {}


def _library_snapshot(identity):
    root = Path(identity['root'])
    state = _preparation_state(identity)
    skipped = {kind: skipped_paths(state, kind) for kind in media.KINDS}
    # Inventory and visible rows share one traversal, including excluded files.
    # File IDs are needed only when resolving either music metadata database.
    # Without those databases, avoid a separate Windows query for every track.
    try:
        music_inodes = ((root / 'iPod_Control/iTunes/iTunesDB').is_file() or
                        (root / '.LINNET/LIBRARY.PDB').is_file())
    except (OSError, ValueError):
        # Let the existing metadata readers handle inaccessible databases.
        music_inodes = True
    records = records_by_kind(root, include_inodes=music_inodes)
    from .retail_media import available_tracks, images
    retail_tracks = available_tracks(root, known_records=records['Music'], known_inodes=records.inodes)
    retail_photos = images(root)
    inventory = scan_sources(root, skipped=skipped, records_by_kind=records, retail_photos=retail_photos,
                             fingerprint_kinds=('Music', 'Notes', 'Photos'), retail_tracks=retail_tracks)
    category_errors = []
    rows = media_library.list_items(identity, records_by_kind=records, retail_photos=retail_photos,
                                    retail_tracks=retail_tracks, category_errors=category_errors,
                                    _validated_identity=True)
    for row in rows:
        if row.get('category') == 'error' and row.get('kind') in inventory:
            inventory[row['kind']].setdefault('errors', []).append(
                str(row.get('error') or row.get('status') or 'Catalog damaged'))
    return state, skipped, records, inventory, rows


def inspect(identity, photo_dimension=640, verification="metadata"):
    from tools.studio import installer
    media._volume_guard(identity)
    root = Path(identity['root'])
    # A discovered identity already binds the mounted volume. Revalidate it
    # while collecting read-only library data, then use the refreshed identity
    # before reporting readiness or returning anything to the caller.
    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh_future = pool.submit(media.refresh, identity)
        snapshot_future = pool.submit(_library_snapshot, identity)
        refreshed = refresh_future.result()
        boot_future = pool.submit(installer.assess, refreshed, _validated_identity=True)
        state, skipped, records, inventory, rows = snapshot_future.result()
        if identity.get('media_cache_disk_serial') != refreshed.get('media_cache_disk_serial'):
            state, skipped, records, inventory, rows = _library_snapshot(refreshed)
        identity = refreshed
        verified = _verified_outputs(identity['disk_serial'], identity['volume_serial'],
                                     identity['partition_offset'], identity['volume_unique_id'],
                                     cache_disk_serial=identity.get('media_cache_disk_serial'))
        if len(verified) > 4096:
            verified.clear()
        verified_before = verified.copy()
        boot_review = boot_future.result()
    identity = boot_review['identity']
    identity['linnet'] = boot_review['linnet']
    identity['default_boot'] = installer.default_boot(boot_review)
    if inventory['Videos'].get('errors'):
        try:
            inventory['Videos']['repair'] = media_library.video_catalog_recovery_options(identity)
        except (OSError, ValueError, UnicodeError) as error:
            media._volume_guard(identity)
            inventory['Videos']['repair'] = dict(status='unavailable', options=[],
                explanation='Video catalog backup inspection failed: ' + str(error))
    readiness = {}
    published_by_kind = {kind: [] for kind in media.KINDS}
    for row in rows:
        if row['category'] in ('library', 'published'):
            bucket = published_by_kind.get(row['kind'])
            if bucket is not None:
                bucket.append(row)
    for kind in media.KINDS:
        if inventory[kind].get('errors'):
            readiness[kind] = 'Needs repair'
            continue
        saved = state.get(kind, {})
        if not isinstance(saved, dict):
            saved = {}
        published = published_by_kind[kind]
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
        if row.get('category') == 'error':
            continue
        if row['id'].startswith('retail-photo:'):
            relative = Path(row['path']).relative_to(root).as_posix().casefold()
            row['status'] = ('Excluded from preparation' if relative in skipped['Photos']
                             else 'iTunes photo · ' + readiness['Photos'])
        excluded = skipped.get(row['kind'])
        if not excluded:
            continue
        path = Path(row['path'])
        if path.is_relative_to(root) and path.relative_to(root).as_posix().casefold() in excluded:
            row['status'] = 'Excluded from preparation'
    if any(row['kind'] == 'Music' and row['status'].startswith('Needs conversion:') for row in rows):
        readiness['Music'] = 'Needs conversion'
    from . import apple_os
    apple = apple_os.inspect(identity, records_by_kind=records)
    _remember_verified(identity, verified, verified_before)
    return identity, inventory, rows, readiness, apple, boot_review


def plan(identity, pending, selected, videos, *, current_inventory=None,
         photo_dimension=640, music_verification='metadata', force=False,
         online_artwork=False, ffprobe=None, ffmpeg=None, convert_audio=False,
         cancelled=lambda: False):
    identity = media.refresh(identity)
    unsupported = [kind for kind in selected if kind not in media.supported_kinds(identity)]
    if unsupported:
        raise ValueError(f"{', '.join(unsupported)} playback is unavailable on this iPod model.")
    if current_inventory:
        damaged = [kind for kind in selected if current_inventory.get(kind, {}).get('errors')]
        if damaged:
            raise ValueError(f"{', '.join(damaged)} catalog needs repair before preparing this category.")
    root = Path(identity['root'])
    state = _preparation_state(identity)
    skipped = {kind: skipped_paths(state, kind) for kind in media.KINDS}
    if videos is not None:
        videos = [value for value in videos
                  if Path(value).resolve().relative_to(root).as_posix().casefold()
                  not in skipped['Videos']]
    included = [p for p in pending if p[0] in selected]
    snapshots = {}
    unverified = []
    replacements = []
    reused_audio = []
    verified = _verified_outputs(identity['disk_serial'], identity['volume_serial'],
                                 identity['partition_offset'], identity['volume_unique_id'],
                                 cache_disk_serial=identity.get('media_cache_disk_serial'))
    verified_before = verified.copy()
    copies = media.additions(root, [p for p in included if p[0] != 'Videos'], snapshots=snapshots,
                             verify_existing=True, unverified=unverified, replacements=replacements,
                             convert_audio=convert_audio, target=identity['target_id'], ffprobe=ffprobe,
                             cancelled=cancelled, reused_audio=reused_audio, verified=verified)
    _remember_verified(identity, verified, verified_before)
    device_conversions = [source for source, _ in reused_audio] + [Path(item['source']) for item in copies
        if 'converted_bytes' in item and Path(item['source']).is_relative_to(root / 'Music')]
    for source in device_conversions:
        skipped['Music'].add(source.relative_to(root).as_posix().casefold())
    for _, destination in reused_audio:
        skipped['Music'].discard(destination.relative_to(root).as_posix().casefold())
    if device_conversions and current_inventory is not None:
        current_inventory = {**current_inventory, **media.scan(
            root, tuple(kind for kind in selected if kind != 'Videos'), skipped=skipped)}
    audio_conversions = sum('converted_bytes' in item for item in copies)
    audio_unplayable = sum('compatibility_issue' in item and 'converted_bytes' not in item for item in copies)
    audio_issues = [dict(source=item['source'], reason=item['compatibility_issue']) for item in copies
                    if 'compatibility_issue' in item][:5]
    if audio_conversions and not ffmpeg:
        raise ValueError('Audio conversion needs FFmpeg on the computer. Choose its folder in Settings.')
    jobs = media.video_jobs(root, included, videos, skipped=skipped['Videos'], identity=identity,
                            snapshots=snapshots, ffprobe=ffprobe,
                            replacements=replacements) if 'Videos' in selected else []
    reconciliation = media.reconciliation_actions(identity, selected, copies,
        replacements=replacements, current_inventory=current_inventory, skipped=skipped)
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
    needed = sum(p.get('converted_bytes', p['bytes']) for p in copies)
    if 'Notes' in selected:
        replacing_notes = {action['destination'].casefold() for action in replacements
                           if action['kind'] == 'Notes' and
                           Path(action['destination']).relative_to(root).as_posix().casefold()
                           not in skipped['Notes']}
        total = scan_sources(root, ('Notes',), skipped=skipped)['Notes']['count'] + sum(
            p['kind'] == 'Notes' and Path(p['source']).suffix.lower() in media.extensions('Notes')
            and p['destination'].casefold() not in replacing_notes for p in copies)
        if total > 256:
            raise ValueError(f'Notes supports 256 files; this update includes {total}.')
    cache = cache_root(identity)
    space = media.preparation_space(identity, copies, jobs, selected, cache,
        photo_dimension=photo_dimension, current_inventory=current_inventory,
        ffprobe=ffprobe, ffmpeg=ffmpeg, no_conversions=videos is not None and not videos,
        force=force, skipped=skipped)
    if space['device_peak_bytes'] > min(identity['free_bytes'], space['device_free_bytes']):
        raise ValueError('Not enough iPod space for originals, prepared media, and recovery copies.')
    if space['computer_peak_bytes'] > space['computer_free_bytes']:
        raise ValueError('Not enough computer space for prepared media and conversion scratch.')
    copy_kinds = {kind: sum(item['kind'] == kind for item in copies) for kind in selected}
    reusable = []
    if current_inventory and not force:
        for kind in selected:
            if copy_kinds[kind] or kind in unverified or kind == 'Videos' or (kind == 'Music' and
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
    return dict(copies=len(copies), bytes=needed, videos=len(jobs), audio_conversions=audio_conversions,
                audio_unplayable=audio_unplayable, audio_issues=audio_issues,
                free=space['device_free_bytes'], previews=previews,
                existing_unverified=len(unverified),
                conversion=space['video_conversion_required'] if videos is None or videos else False,
                computer_free=space['computer_free_bytes'],
                device_peak_bytes=space['device_peak_bytes'], computer_peak_bytes=space['computer_peak_bytes'],
                excluded=len(pending)-len(included),
                copy_kinds=copy_kinds, selected=list(selected), reusable=reusable,
                reconciliation=reconciliation)
