"""Read-only preparation plans and verified library status for the desktop UI."""
import json
from pathlib import Path
import shutil

from . import media_manager as media
from . import media_library


def inspect(identity, photo_dimension=640, verification="metadata"):
    identity = media.refresh(identity)
    root = Path(identity['root'])
    from tools.studio.installer import installed_state
    identity['linnet'] = installed_state(root, identity['target_id'])
    inventory = media.scan(root)
    rows = media_library.list_items(identity)
    try:
        state = json.loads((media.cache_root(identity) / 'state.json').read_text())
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    readiness = {}
    for kind in media.KINDS:
        saved = state.get(kind, {})
        if not isinstance(saved, dict):
            saved = {}
        published = [r for r in rows if r['kind'] == kind and r['category'] in ('library', 'published')]
        if kind == 'Videos':
            readiness[kind] = f"{sum(r['status'] == 'Ready on iPod' for r in published)} in playback library"
            continue
        option = photo_dimension if kind == 'Photos' else f'{verification}-duration-search-names-album-owner' if kind == 'Music' else 'default'
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
    included = [p for p in pending if p[0] in selected]
    copies = media.additions(root, [p for p in included if p[0] != 'Videos'])
    jobs = media.video_jobs(root, included, videos) if 'Videos' in selected else []
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
        total = media.scan(root, ('Notes',))['Notes']['count'] + sum(p['kind'] == 'Notes' and Path(p['source']).suffix.lower() in media.extensions('Notes') for p in copies)
        if total > 256:
            raise ValueError(f'Notes supports 256 files; this update includes {total}.')
    cache = media.cache_root(identity)
    parent = cache
    while not parent.exists():
        parent = parent.parent
    return dict(copies=len(copies), bytes=needed, videos=len(jobs), free=identity['free_bytes'], previews=previews,
                conversion=any(Path(j['source']).suffix.lower() not in ('.ipv', '.ipvf') for j in jobs),
                computer_free=shutil.disk_usage(parent).free, excluded=len(pending)-len(included))
