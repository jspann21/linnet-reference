"""Read-only preparation plans and verified library status for the desktop UI."""
import json
from pathlib import Path
import shutil

from . import media_manager as media
from . import media_library


def _video_readiness(inventory, published):
    ready = [row for row in published if row['status'] == 'Ready on iPod']
    missing = [row for row in published if row['status'] != 'Ready on iPod']
    native = {str(Path(value).resolve()).casefold() for value in inventory['files']
              if Path(value).suffix.lower() in ('.ipv', '.ipvf')}
    cataloged = {str(Path(row['path']).resolve()).casefold() for row in ready}
    if missing or not native.issubset(cataloged):
        return 'Needs update'
    if ready:
        return 'Ready'
    return 'Not prepared' if inventory['count'] else 'No content yet'


def inspect(identity, photo_dimension=640, verification="metadata"):
    from tools.studio import installer
    boot_review = installer.assess(identity)
    identity = boot_review['identity']
    root = Path(identity['root'])
    identity['linnet'] = boot_review['linnet']
    identity['default_boot'] = installer.default_boot(boot_review)
    try:
        state = json.loads((media.cache_root(identity) / 'state.json').read_text())
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    skipped = {kind: media._skipped_paths(state, kind) for kind in media.KINDS}
    inventory = media.scan(root, skipped=skipped)
    rows = media_library.list_items(identity)
    readiness = {}
    for kind in media.KINDS:
        saved = state.get(kind, {})
        if not isinstance(saved, dict):
            saved = {}
        published = [r for r in rows if r['kind'] == kind and r['category'] in ('library', 'published')]
        if kind == 'Videos':
            readiness[kind] = _video_readiness(inventory[kind], published)
            continue
        option = media.preparation_option(kind, identity, photo_dimension, verification)
        signature = f"{option}:{inventory[kind]['fingerprint']}"
        if saved.get('signature') == signature and saved.get('outputs') and media._outputs_match(root, saved['outputs']):
            readiness[kind] = 'Ready'
        elif published:
            readiness[kind] = 'Needs update' if inventory[kind]['count'] else 'Prepared library retained'
        else:
            readiness[kind] = 'Not prepared' if inventory[kind]['count'] else 'No content yet'
    return identity, inventory, rows, readiness


def plan(identity, pending, selected, videos):
    identity = media.refresh(identity)
    unsupported = [kind for kind in selected if kind not in media.supported_kinds(identity)]
    if unsupported:
        raise ValueError(f"{', '.join(unsupported)} playback is unavailable on this iPod model.")
    root = Path(identity['root'])
    try:
        state = json.loads((media.cache_root(identity) / 'state.json').read_text())
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    skipped = {kind: media._skipped_paths(state, kind) for kind in media.KINDS}
    videos = [value for value in videos
              if Path(value).resolve().relative_to(root).as_posix().casefold()
              not in skipped['Videos']]
    included = [p for p in pending if p[0] in selected]
    copies = media.additions(root, [p for p in included if p[0] != 'Videos'])
    jobs = media.video_jobs(root, included, videos, skipped=skipped['Videos']) if 'Videos' in selected else []
    previews = {}
    for kind, name in included:
        source = Path(name)
        records = media._file_records(source) if source.is_dir() else [(source, source.stat())]
        supported = sum(p.suffix.lower() in media.extensions(kind) for p, _ in records)
        other = len(records) - supported
        previews[name] = f'{supported} media files' + (f' · {other} supporting/other files' if other else '')
        if kind == 'Videos' and other:
            previews[name] = f'{supported} videos · {other} non-video files skipped'
    needed = sum(p['bytes'] for p in copies)
    if needed + 1048576 > identity['free_bytes']:
        raise ValueError('Not enough iPod space for these originals. Remove additions from the queue.')
    if 'Notes' in selected:
        total = media.scan(root, ('Notes',), skipped=skipped)['Notes']['count'] + sum(p['kind'] == 'Notes' and Path(p['source']).suffix.lower() in media.extensions('Notes') for p in copies)
        if total > 256:
            raise ValueError(f'Notes supports 256 files; this update includes {total}.')
    cache = media.cache_root(identity)
    parent = cache
    while not parent.exists():
        parent = parent.parent
    return dict(copies=len(copies), bytes=needed, videos=len(jobs), free=identity['free_bytes'], previews=previews,
                conversion=any(Path(j['source']).suffix.lower() not in ('.ipv', '.ipvf') for j in jobs),
                computer_free=shutil.disk_usage(parent).free, excluded=len(pending)-len(included))
