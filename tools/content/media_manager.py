"""Desktop media workflow. Originals live in the user's four iPod folders.

Preparation is cached on the host; publication uses the existing guarded writers.
No device is modified by discovery or scanning.
"""
from __future__ import annotations

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid

from .guard import guarded_path as _plain, hash_file as _hash, require_same_target as _same_target, guard_volume as _volume_guard, inspect_target
from .host_state import cache_directory as _cache_directory, cache_root, load_json_object as _optional_state, save_json as _save
from .inventory import KINDS, VIDEO_EXTENSIONS, extensions, source_folders, file_records as _file_records, skipped_paths as _skipped_paths, scan

_RETAIL_ADOPTION = None


def _receipt_stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _save_seek_state(path, state):
    try:
        _save(path, state)
    except OSError:
        pass  # Seek checks are disposable; publication and recovery continue.


def _append_audio_journal(path, kind, change):
    entry = json.dumps(dict(kind=kind, change=change), separators=(',', ':')).encode('utf-8') + b'\n'
    with path.open('ab') as writer:
        writer.write(entry)
        writer.flush()
        os.fsync(writer.fileno())


def discover(*, detailed=False):
    """Find mounted iPods and resolve each through publication guards."""
    if os.name != "nt":
        raise RuntimeError("The media manager currently supports Windows Disk Mode.")
    from tools.studio.targets import TARGETS
    names=["Apple iPod"]+[spec["native_storage"]["friendly_name"] for spec in TARGETS.values() if "native_storage" in spec]
    script = r"""
$ErrorActionPreference='Stop'
$names=ConvertFrom-Json 'NATIVE_NAMES'
$items=@()
$errors=@()
foreach ($disk in @(Get-Disk | Where-Object {$_.BusType -eq 'USB' -and $_.FriendlyName -in $names})) {
 try {$partitions=@(Get-Partition -DiskNumber $disk.Number | Where-Object {$_.DriveLetter})}
 catch {$errors+=@{drive="Disk $($disk.Number)";message=[string]$_};continue}
 foreach ($partition in $partitions) {
  $drive=[string]$partition.DriveLetter+':'
  try {
   $logical=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$drive+"'")
   if (!$logical) {throw 'Volume identity is unavailable'}
   $items+=@{number=[int]$disk.Number;serial=$disk.SerialNumber.Trim();volume=$logical.VolumeSerialNumber;drive=$drive}
  }
  catch {$errors+=@{drive=$drive;message=[string]$_}}
 }
}
ConvertTo-Json -InputObject @{items=@($items);errors=@($errors)} -Compress
""".replace('NATIVE_NAMES',json.dumps(names).replace("'","''"))
    for attempt in range(2):
        try:
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                    capture_output=True, text=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            break
        except subprocess.TimeoutExpired as error:
            if attempt:
                raise RuntimeError(
                    "Windows did not finish reading the iPod's storage identity. "
                    "Reconnect it in Disk Mode and choose Find iPod."
                ) from error
            # A just-enumerated hard disk can finish mounting after the first
            # storage query stalls. Retry with a fresh Windows provider query.
    if result.returncode:
        raise RuntimeError(
            "We couldn't read your iPod's storage. Reconnect your iPod in Disk Mode, "
            "wait a few seconds, then try again. If the problem continues, try a different "
            "USB cable or port."
        ) from subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr
        )
    discovered = json.loads(result.stdout.lstrip("\ufeff") or "{}")
    items = discovered.get('items', [])
    devices = []
    errors = [f"{entry.get('drive', '?')}: {entry.get('message', '')[:240]}"
              for entry in discovered.get('errors', [])[:16] if isinstance(entry, dict)]
    for item in items:
        try:
            args = dict(disk_number=item["number"], expected_disk_serial=item["serial"],
                        expected_volume_serial=item["volume"], expected_drive=item["drive"])
            devices.append(_inspect_identify(args, Path(item["drive"] + "\\")))
        except Exception as error:
            if len(errors) < 16:
                drive = item.get('drive', '?') if isinstance(item, dict) else '?'
                errors.append(f"{drive}: {(str(error) or type(error).__name__)[:240]}")
    if detailed:
        return dict(devices=devices, errors=errors)
    if not devices and errors:
        raise RuntimeError('Could not read a connected iPod: ' + '; '.join(errors))
    return devices


def _inspect_identify(args, root):
    """Run independent storage probes together, then require matching identities."""
    from tools.inspect.retail_device import detect

    with ThreadPoolExecutor(max_workers=2) as pool:
        guarded = pool.submit(inspect_target, **args)
        retail = pool.submit(detect, root)
        identity, detected = guarded.result(), retail.result()
    if Path(root).resolve(strict=True) != Path(identity["root"]).resolve(strict=True):
        raise RuntimeError("USB and mounted storage roots disagree")
    return _identify(identity, detected)


def _identify(identity, detected=None):
    """Bind Disk Mode storage identity to one target manifest."""
    from tools.inspect.retail_device import detect
    from tools.studio.targets import TARGETS, media_profile
    if detected is None:
        detected = detect(identity["root"])
    storage = detected["storage"]
    if (detected["device_id"] != identity["disk_serial"] or
            storage["disk_number"] != identity["disk_number"] or
            storage["disk_bytes"] != identity["disk_bytes"] or
            storage["partition_offset"] != identity["partition_offset"]):
        raise RuntimeError("USB and mounted storage identities disagree")
    spec = TARGETS[detected["target_id"]]
    model_number = detected["retail_os"].get("model_number")
    regulatory_models = spec["retail"]["regulatory_models"]
    regulatory_model = spec["retail"].get("regulatory_model_by_model", {}).get(model_number)
    if regulatory_model is None and len(regulatory_models) == 1:
        regulatory_model = regulatory_models[0]
    result = dict(identity, target_id=detected["target_id"], target_name=spec["name"],
                linnet_usb_serial=detected["linnet_usb_serial"],
                model_number=model_number,
                regulatory_model=regulatory_model,
                media_profile=media_profile(detected["target_id"]))
    if identity.get("native_target_id"):
        result["media_cache_disk_serial"] = _retail_cache_serial(result)
    return result


def _retail_cache_serial(identity):
    """Reuse a verified cache from this volume's former Apple Disk Mode identity."""
    global _RETAIL_ADOPTION
    from tools.inspect.retail_device import _sysinfo
    root = Path(identity["root"])
    try:
        _plain(root / "iPod_Control" / "Device" / "SysInfo", root)
        serial = _sysinfo(root).get("pszSerialNumber", "").upper()
        if not re.fullmatch(r"[A-Z0-9]{6,16}", serial):
            return None
        candidate = _cache_directory(serial, identity["volume_serial"])
        if not candidate.is_dir():
            return None
        key = (serial, str(candidate), *(identity.get(field) for field in (
            'root', 'volume_serial', 'volume_unique_id', 'target_id', 'disk_number',
            'disk_unique_id', 'disk_bytes', 'partition_number', 'partition_offset',
            'partition_bytes', 'sector_bytes')))
        cached = _RETAIL_ADOPTION
        if cached is not None and cached[0] == key:
            receipt, stamp = cached[1:]
            try:
                if not receipt.is_symlink() and _receipt_stamp(receipt.stat()) == stamp:
                    return serial
            except OSError:
                pass
        for receipt in candidate.glob("session-*.json"):
            if receipt.is_symlink():
                continue
            try:
                info = receipt.stat()
                if info.st_size > 1048576:
                    continue
                record = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                continue
            saved = record.get("identity", {}) if isinstance(record, dict) else {}
            if not isinstance(saved, dict):
                continue
            if all(saved.get(field) == identity[field] for field in
                   ("volume_serial", "target_id", "disk_bytes", "partition_offset", "partition_bytes")) and saved.get("disk_serial") == serial:
                _RETAIL_ADOPTION = (key, receipt, _receipt_stamp(info))
                return serial
    except (OSError, ValueError, UnicodeError, KeyError, TypeError):
        pass
    return None


def supported_kinds(identity):
    """Return the media services declared by the resolved device target."""
    profile = identity.get("media_profile", {})
    return tuple(kind for kind in KINDS
                 if (kind != "Videos" or profile.get("video_enabled", True))
                 and (kind != "Photos" or profile.get("photo_enabled", True)))


def native_video_extensions(identity=None):
    profile = (identity or {}).get("media_profile", {})
    return set(profile.get("video_extensions", [".ipvf"])) if profile.get("video_enabled", True) else set()


def video_source_extensions(identity):
    profile = (identity or {}).get("media_profile", {})
    if not profile.get("video_enabled", True):
        return set()
    allowed = set(VIDEO_EXTENSIONS)
    if profile.get("video_backend") in ("bcm-mp4", "native-mp4"):
        allowed.discard(".ipvf")
    return allowed


def target_args(identity):
    return dict(disk_number=identity["disk_number"], expected_disk_serial=identity["disk_serial"],
                expected_volume_serial=identity["volume_serial"], expected_drive=identity["drive"])


def refresh(identity):
    current = _inspect_identify(target_args(identity), Path(identity["root"]))
    _same_target(identity, current)
    if current["target_id"] != identity.get("target_id"):
        raise RuntimeError("iPod target identity changed during media operation")
    return current


def preparation_option(kind, identity, photo_dimension=640, music_verification='metadata'):
    """Shared preparation version for compilation and library readiness."""
    if kind == 'Music':
        from tools.studio.targets import TARGETS
        target = TARGETS[identity['target_id']]
        art_version = ('art-row' if target.get('presentation_profile') == 'color320' else
                       'art9' if target['media_art_side'] == 128 else
                       'art8' if target['lcd_format'] == 'gray2-horizontal' else 'art7')
        return f"{music_verification}-aac-seek1-duration-search-prefix2-browse-id-names-album-owner2-title-order1-retail2-recent-album-gain-icc-srgb1-{art_version}-{identity['target_id']}"
    if kind == 'Notes':
        from .notes import _display_recipe
        return f"target-wrap2-{_display_recipe(identity['target_id'])[2]}"
    if kind == 'Photos':
        profile = identity['media_profile']
        return f"retail-photos3-native-grid1-{identity['target_id']}-{photo_dimension}-{profile['photo_width']}x{profile['photo_height']}"
    return 'default'


def skip_files(identity, items):
    """Persist supported iPod source files that should be omitted from preparation."""
    identity = refresh(identity)
    root = Path(identity["root"]).resolve(strict=True)
    state_path = cache_root(identity) / "state.json"
    state = _optional_state(state_path)
    skipped = state.setdefault("skipped_files", {})
    if not isinstance(skipped, dict):
        skipped = state["skipped_files"] = {}
    added = []
    known_by_kind = {}
    retail_photo_paths = None
    for kind, value in items:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        path = Path(value).resolve()
        retail_photo = False
        if kind == 'Photos' and path.is_relative_to(root / 'Photos' / '@iTunes'):
            if retail_photo_paths is None:
                from .retail_media import images
                retail_photo_paths = {root / photo['relative'] for photo in images(root)}
            retail_photo = path in retail_photo_paths
        if not retail_photo and (not path.is_file() or path.suffix.lower() not in extensions(kind)):
            raise ValueError(f"This is not a supported {kind.lower()} file: {path}")
        if not any(path.is_relative_to(folder.resolve()) for folder in source_folders(root, kind)):
            raise ValueError(f"The file is outside this iPod's {kind} sources: {path}")
        relative = path.relative_to(root).as_posix()
        values = skipped.setdefault(kind, [])
        if not isinstance(values, list):
            values = skipped[kind] = []
        if kind not in known_by_kind:
            known_by_kind[kind] = {Path(item).as_posix().casefold() for item in values if isinstance(item, str)}
        if relative.casefold() not in known_by_kind[kind]:
            values.append(relative)
            known_by_kind[kind].add(relative.casefold())
            added.append(relative)
        state.pop(kind, None)
        if kind == "Videos":
            video_state = state.get("video_files", {})
            if isinstance(video_state, dict):
                video_key = path.relative_to(root / "Videos").as_posix() if path.is_relative_to(root / "Videos") else relative
                video_state.pop(video_key, None)
    _save(state_path, state)
    return added


def list_skipped_files(identity):
    """Return cached skip entries with their current source locations."""
    root = Path(identity["root"]).resolve()
    state_path = cache_root(identity) / "state.json"
    state = _optional_state(state_path)
    skipped = state.get("skipped_files", {})
    if not isinstance(skipped, dict):
        return []
    result = []
    for kind in KINDS:
        values = skipped.get(kind, [])
        if not isinstance(values, list):
            continue
        allowed = _skipped_paths(state, kind)
        for relative in sorted((Path(value).as_posix() for value in values
                                if isinstance(value, str) and Path(value).as_posix().casefold() in allowed),
                               key=str.casefold):
            result.append(dict(kind=kind, relative=relative, source=str(root / Path(relative))))
    return result


def restore_skipped_files(identity, items):
    """Remove files from the persistent preparation skip list."""
    identity = refresh(identity)
    state_path = cache_root(identity) / "state.json"
    state = _optional_state(state_path)
    skipped = state.get("skipped_files", {})
    if not isinstance(skipped, dict):
        return []
    requested = {}
    requested_order = []
    for kind, value in items:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        relative = Path(value).as_posix()
        key = relative.casefold()
        if key not in requested.setdefault(kind, {}):
            requested[kind][key] = relative
            requested_order.append((kind, key, relative))
    restored_keys = set()
    for kind, relatives in requested.items():
        values = skipped.get(kind, [])
        if not isinstance(values, list):
            continue
        present = {Path(item).as_posix().casefold() for item in values if isinstance(item, str)}
        kept = [item for item in values if not isinstance(item, str) or
                Path(item).as_posix().casefold() not in relatives]
        if len(kept) != len(values):
            skipped[kind] = kept
            restored_keys.update((kind, key) for key in relatives if key in present)
            state.pop(kind, None)
    _save(state_path, state)
    return [relative for kind, key, relative in requested_order if (kind, key) in restored_keys]


def _music_import_name(name):
    # Non-ASCII FAT aliases cannot be opened by the firmware. Keep readable
    # names, transliterating accents and punctuation before Windows makes aliases.
    if name.isascii():
        result = name.replace('"', "'")
    else:
        punctuation = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                    "‐": "-", "‑": "-", "–": "-", "—": "-", "…": "..."})
        normalized = unicodedata.normalize("NFD", name.translate(punctuation))
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        if normalized.isascii():
            result = normalized.replace('"', "'")
        else:
            # A readable ASCII prefix also gives names in other scripts a usable alias.
            result = "Music - " + name
    if len(result) > 127 and len(result.encode('utf-16-le')) > 510:
        suffix = Path(result).suffix
        marker = '-' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]
        budget = 255 - len((marker + suffix).encode('utf-16-le')) // 2
        if budget < 1:
            raise ValueError('Music filename extension is too long; rename it before importing.')
        stem = result[:-len(suffix)] if suffix else result
        stem = stem.encode('utf-16-le')[:budget * 2].decode('utf-16-le', errors='ignore')
        result = stem + marker + suffix
    return result


def _normalize_music_paths(root, checkpoint, renamed):
    from .music import _device_media_path, UnsupportedMediaPath
    resolved_root = Path(root).resolve(strict=True)
    alias_cache = {}
    directories = source_folders(root, "Music")
    while directories:
        folder = directories.pop()
        _plain(folder, root)
        for path in sorted(folder.iterdir()):
            checkpoint()
            _plain(path, root)
            directory = path.is_dir()
            if not directory and path.suffix.lower() not in extensions("Music"):
                continue
            try:
                _device_media_path(path, resolved_root, alias_cache)
            except UnsupportedMediaPath:
                name = _music_import_name(path.name)
                if name == path.name:
                    raise ValueError(f"Music path is too long or deep; move it closer to /Music: {path}")
                destination = path.with_name(name)
                number = 2
                while destination.exists():
                    suffix = '' if directory else Path(name).suffix
                    stem = name[:-len(suffix)] if suffix else name
                    ending = f" ({number}){suffix}"
                    budget = 255 - len(ending.encode('utf-16-le')) // 2
                    stem = stem.encode('utf-16-le')[:budget * 2].decode('utf-16-le', errors='ignore')
                    candidate = stem + ending
                    destination = path.with_name(candidate)
                    number += 1
                _plain(destination, root)
                checkpoint()
                path.rename(destination)
                renamed(path, destination)
                path = destination
                _device_media_path(path, resolved_root, alias_cache)
            if directory:
                directories.append(path)


def _planning_records(source, snapshots):
    if snapshots is not None and source in snapshots:
        return snapshots[source]
    records = _file_records(source) if source.is_dir() else [(source, source.stat())]
    if snapshots is not None:
        snapshots[source] = records
    return records


def _same_file_bytes(left, right, size):
    paths = (left, right)
    before = [path.stat() for path in paths]
    if any(not stat.S_ISREG(info.st_mode) or info.st_size != size for info in before):
        raise ValueError('file changed while comparing existing media')
    equal = True
    with left.open('rb') as source, right.open('rb') as destination:
        remaining, chunk_size = size, 16 * 1024
        while remaining:
            count = min(remaining, chunk_size)
            a, b = source.read(count), destination.read(count)
            if len(a) != count or len(b) != count:
                raise ValueError('file changed while comparing existing media')
            if a != b:
                equal = False
                break
            remaining -= count
            chunk_size = 1024 * 1024
        if equal and (source.read(1) or destination.read(1)):
            raise ValueError('file changed while comparing existing media')
    after = [path.stat() for path in paths]
    if any((a.st_size, a.st_mtime_ns, a.st_ino) != (b.st_size, b.st_mtime_ns, b.st_ino)
           for a, b in zip(before, after)):
        raise ValueError('file changed while comparing existing media')
    return equal


def additions(root, pending, *, snapshots=None):
    """Resolve selected files/folders to concrete destinations without writing."""
    root = Path(root).resolve(strict=True)
    planned = {}
    for kind, selected in pending:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        source = Path(selected).absolute()
        _plain(source, Path(source.anchor))
        source = source.resolve(strict=True)
        if source.is_relative_to(root):
            raise ValueError(f"{source.name} is already on this iPod. Use its existing {kind} folder.")
        is_folder = source.is_dir()
        records = _planning_records(source, snapshots)
        for path, info in records:
            # Preserve supporting files (cover art, playlists) inside selected folders.
            if not is_folder and path.suffix.lower() not in extensions(kind):
                raise ValueError(f"{path.name} is not a supported {kind.lower()} source.")
            if info.st_size > 0xFFFFFFFF:
                raise ValueError(f"{path.name} exceeds the iPod's FAT32 file size limit (4 GiB minus 1 byte).")
            relative = Path(source.name) / path.relative_to(source) if is_folder else Path(source.name)
            if kind == "Music":
                relative = Path(*(_music_import_name(part) for part in relative.parts))
            destination = root / kind / relative
            _plain(destination, root)
            key = str(destination).casefold()
            if key in planned and planned[key]["source"] != str(path):
                raise ValueError(f"Two selected files have the same destination: {destination}")
            if destination.exists():
                if not destination.is_file() or destination.stat().st_size != info.st_size or not _same_file_bytes(path, destination, info.st_size):
                    equivalent = False
                    if kind == 'Music' and path.suffix.lower() in ('.m4a', '.m4b'):
                        from .aac_index import same_original
                        equivalent = same_original(path, destination)
                    elif kind == 'Music' and path.suffix.lower() in ('.flac', '.flc'):
                        from .flac_index import same_original
                        equivalent = same_original(path, destination)
                    if not equivalent:
                        raise ValueError(f"A different file already exists: {destination}. Rename the new file or folder first.")
                continue
            planned[key] = dict(kind=kind, source=str(path), destination=str(destination),
                                bytes=info.st_size, mtime_ns=info.st_mtime_ns)
    return list(planned.values())


def _prepare_import_aac(item, scratch, cache, ffprobe, cancelled, stopped):
    from .aac_index import import_suffix

    def should_stop():
        return stopped.is_set() or cancelled()

    def check():
        if should_stop():
            raise Cancelled('Stopped while preparing AAC on the computer.')

    source = Path(item['source'])
    _plain(source, Path(source.anchor))
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
        raise ValueError(f"Source changed since selection: {source}")
    local = scratch / ('source' + source.suffix.lower())
    with source.open('rb') as reader, local.open('xb') as frozen:
        while chunk := reader.read(1024 * 1024):
            check()
            frozen.write(chunk)
    if (_receipt_stamp(before) != _receipt_stamp(source.stat()) or
            local.stat().st_size != before.st_size):
        raise ValueError(f"Source changed during preparation: {source}")
    suffix, unsupported = import_suffix(local, cache / 'aac-import', checkpoint=check)
    metadata_seed = None
    try:
        from .music import _read_metadata
        metadata = _read_metadata(local, ffprobe, True, should_stop, include_cover=True)
        metadata_seed = (metadata, metadata.pop('_embedded_cover', None))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # A cache miss lets normal library preparation retry.
    check()
    return local, suffix, unsupported, metadata_seed, _receipt_stamp(before)


def _prepare_import_mp3(item, ffprobe, cancelled, stopped):
    def should_stop():
        return stopped.is_set() or cancelled()

    source = Path(item['source'])
    _plain(source, Path(source.anchor))
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
        raise ValueError(f"Source changed since selection: {source}")
    metadata_seed = None
    try:
        from .music import _read_metadata
        metadata = _read_metadata(source, ffprobe, True, should_stop, include_cover=True)
        metadata_seed = (metadata, metadata.pop('_embedded_cover', None))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # The compiler can retry from the copied file if host parsing fails.
    if should_stop():
        raise Cancelled('Stopped while reading MP3 metadata on the computer.')
    if _receipt_stamp(source.stat()) != _receipt_stamp(before):
        raise ValueError(f"Source changed during preparation: {source}")
    return metadata_seed, _receipt_stamp(before)


def _copy_additions(plan, root, report, owned_temporaries, checkpoint, record, progress,
                    *, cache, cancelled, stage_progress=lambda current, total, phase: None):
    # Queue a bounded set of writes before flushing and reading them back. On
    # FAT devices, alternating write/flush/read/rename for every small file is
    # expensive. Keep every handle until its flush, and publish only verified files.
    start = 0
    remaining_original = sum(item['bytes'] for item in plan)
    seek_state_path = cache / 'seek-checked.json'
    seek_state = (_optional_state(seek_state_path) if any(
        item['kind'] == 'Music' and Path(item['destination']).suffix.lower() in ('.m4a', '.m4b')
        for item in plan) else {})
    while start < len(plan):
        batch = []
        batch_bytes = 0
        seek_state_changed = False
        for item in plan[start:start + 16]:
            if batch and batch_bytes + item['bytes'] > 64 * 1024 * 1024:
                break
            destination = Path(item['destination'])
            temporary = destination.parent / ('L' + uuid.uuid4().hex[:7] + '.TMP')
            batch.append((item, temporary))
            batch_bytes += item['bytes']
        checkpoint()
        # Persist all candidate scratch paths before creating any of them. The
        # receipt stays bounded during a batch instead of growing twice per song.
        report['copies_in_progress'] = [dict(source=item['source'], destination=item['destination'],
                                           temporary=str(temporary)) for item, temporary in batch]
        record()
        copied = []
        music_seeds = []
        with ExitStack() as handles:
            aac_positions = [offset for offset, (item, _) in enumerate(batch)
                             if item['kind'] == 'Music' and
                             Path(item['destination']).suffix.lower() in ('.m4a', '.m4b')]
            mp3_positions = [offset for offset, (item, _) in enumerate(batch)
                             if item['kind'] == 'Music' and
                             Path(item['destination']).suffix.lower() == '.mp3']
            preparation_positions = sorted((*aac_positions, *mp3_positions))
            scratches = {offset: Path(handles.enter_context(tempfile.TemporaryDirectory(
                prefix='aac-source-', dir=cache))) for offset in aac_positions}
            stopped = threading.Event()
            if aac_positions:
                from .aac_index import executable
                executable()
            executor = handles.enter_context(ThreadPoolExecutor(max_workers=2)) if preparation_positions else None
            if executor is not None:
                handles.callback(stopped.set)
            upcoming = iter(preparation_positions)
            futures = {}
            ffprobe = shutil.which('ffprobe') if preparation_positions else None
            def fill_preparation():
                while executor is not None and len(futures) < 2:
                    offset = next(upcoming, None)
                    if offset is None:
                        break
                    if offset in scratches:
                        futures[offset] = executor.submit(_prepare_import_aac, batch[offset][0],
                            scratches[offset], cache, ffprobe, cancelled, stopped)
                    else:
                        futures[offset] = executor.submit(_prepare_import_mp3, batch[offset][0],
                            ffprobe, cancelled, stopped)
            fill_preparation()
            try:
                for offset, (item, temporary) in enumerate(batch):
                    checkpoint()
                    stage_progress(start + offset / 2, len(plan), 'Copying originals')
                    source, destination = Path(item['source']), Path(item['destination'])
                    progress(f"Adding {start + offset + 1}/{len(plan)}: {source.name}")
                    _plain(source, Path(source.anchor))
                    _plain(destination, root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    _plain(destination.parent, root)
                    info = source.stat()
                    if (info.st_size, info.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
                        raise ValueError(f"Source changed since selection: {source}")
                    suffix = None
                    unsupported_aac = False
                    metadata_seed = None
                    copy_source = source
                    if offset in futures:
                        prepared = futures.pop(offset).result()
                        fill_preparation()
                        if offset in scratches:
                            copy_source, suffix, unsupported_aac, metadata_seed, source_stamp = prepared
                        else:
                            metadata_seed, source_stamp = prepared
                        if _receipt_stamp(info) != source_stamp:
                            raise ValueError(f"Source changed during preparation: {source}")
                        checkpoint()
                    if shutil.disk_usage(root).free < remaining_original + len(suffix or b'') + 1024 * 1024:
                        raise ValueError('Not enough space for prepared additions')
                    digest = hashlib.sha256()
                    writer = handles.enter_context(temporary.open('xb'))
                    owned_temporaries.append((temporary, root))
                    with copy_source.open('rb') as reader:
                        while chunk := reader.read(1024 * 1024):
                            checkpoint()
                            writer.write(chunk)
                            digest.update(chunk)
                    if suffix:
                        writer.write(suffix)
                        digest.update(suffix)
                    writer.flush()
                    after = source.stat()
                    if _receipt_stamp(after) != _receipt_stamp(info):
                        raise ValueError(f"Source changed during copy: {source}")
                    copied.append((item, temporary, writer, digest.hexdigest(),
                                   item['bytes'] + len(suffix or b''), unsupported_aac, metadata_seed))
                    remaining_original -= item['bytes']
            except BaseException:
                stopped.set()
                for future in futures.values():
                    future.cancel()
                raise
            progress(f"Saving additions {start + 1}–{start + len(batch)}/{len(plan)}…")
            for _, _, writer, _, _, _, _ in copied:
                checkpoint()
                os.fsync(writer.fileno())
        verified_stamps = {}
        for offset, (item, temporary, _, digest, prepared_bytes, _, _) in enumerate(copied):
            checkpoint()
            stage_progress(start + (len(batch) + offset) / 2, len(plan), 'Checking copied files')
            destination = Path(item['destination'])
            progress(f"Verifying addition {start + offset + 1}/{len(plan)}: {destination.name}")
            _plain(temporary, root)
            before_readback = _receipt_stamp(temporary.stat())
            if _hash(temporary, prepared_bytes) != digest:
                raise OSError(f"Copy verification failed: {destination}")
            after_readback = _receipt_stamp(temporary.stat())
            if before_readback != after_readback:
                raise OSError(f"Copied file changed during readback: {destination}")
            verified_stamps[temporary] = after_readback
            if prepared_bytes != item['bytes']:
                from .aac_index import original_size
                if original_size(temporary, prepared_bytes) != item['bytes']:
                    raise ValueError(f"Prepared AAC seek data is invalid: {destination}")
        for item, temporary, _, digest, prepared_bytes, unsupported_aac, metadata_seed in copied:
            checkpoint()
            destination = Path(item['destination'])
            _plain(destination, root)
            # Windows rename refuses an existing destination, preserving both files.
            if destination.exists():
                raise ValueError(f"Destination appeared during copy: {destination}")
            if _receipt_stamp(temporary.stat()) != verified_stamps[temporary]:
                raise OSError(f"Copied file changed before rename: {destination}")
            temporary.rename(destination)
            owned_temporaries.remove((temporary, root))
            info = destination.stat()
            if _receipt_stamp(info) != verified_stamps[temporary]:
                before_recheck = _receipt_stamp(info)
                if info.st_size != prepared_bytes or _hash(destination, prepared_bytes) != digest:
                    raise OSError(f"Copied file changed after readback: {destination}")
                info = destination.stat()
                if _receipt_stamp(info) != before_recheck:
                    raise OSError(f"Copied file changed during final readback: {destination}")
            if unsupported_aac:
                from .aac_index import mark_unsupported
                mark_unsupported(destination, cache / 'aac-seek')
            if item['kind'] == 'Music' and destination.suffix.lower() in ('.m4a', '.m4b'):
                key = destination.relative_to(root).as_posix().casefold()
                seek_state[key] = [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
                seek_state_changed = True
                if metadata_seed is not None:
                    music_seeds.append((destination, info, *metadata_seed))
            elif item['kind'] == 'Music' and destination.suffix.lower() == '.mp3' and metadata_seed is not None:
                music_seeds.append((destination, info, *metadata_seed))
            report['steps'].append(dict(added=str(destination), bytes=prepared_bytes))
        report.pop('copies_in_progress', None)
        record()
        if seek_state_changed:
            _save_seek_state(seek_state_path, seek_state)
        if music_seeds:
            _seed_imported_music(root, cache, music_seeds)
        start += len(batch)
        stage_progress(start, len(plan), 'Copying originals')


def _seed_imported_music(root, cache, rows):
    """Reuse host-read tags and artwork after the verified iPod copy is published."""
    import sqlite3
    from .music import _MetadataCache
    try:
        saved = _MetadataCache(cache / 'music-metadata.sqlite3')
    except (OSError, sqlite3.Error):
        return
    try:
        source = Path(os.path.abspath(root))
        for path, before, metadata, cover in rows:
            try:
                relative = path.relative_to(root).as_posix()
                value = dict(metadata, data_bytes=before.st_size)
                if _MetadataCache._valid(value, relative, before):
                    saved.embedded_cover_lookup(path, before, bypass=True)
                    saved.put(source, relative, before, value)
                    saved.embedded_cover_store(path, before, cover)
            except (OSError, ValueError, TypeError, KeyError):
                continue  # Disposable cache; the normal compiler will reread.
    finally:
        saved.close()


def format_size(value):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:,.1f} {unit}"
        value /= 1024


def eject_device(identity):
    from .publish import _exclusive
    from tools.link.eject import eject
    with _exclusive(identity):
        current = refresh(identity)
        return eject(current['disk_number'], current['disk_serial'], wait_link=False)


def _throttled_progress(checkpoint, progress, describe):
    last = 0.0
    def report(event):
        nonlocal last
        checkpoint()
        now = time.monotonic()
        if now - last >= 0.2 or event['current'] + 1 == event['total']:
            progress(describe(event))
            last = now
    return report


def _outputs_match(root, outputs, *, verified=None, progress=None):
    """Treat malformed/stale host cache entries as misses, with bounded paths."""
    if not isinstance(outputs, list) or not outputs:
        return False
    for index, item in enumerate(outputs):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return False
        name, digest = item
        if not isinstance(name, str) or not isinstance(digest, str):
            return False
        relative = Path(name)
        if (relative.is_absolute() or relative.drive or ".." in relative.parts or not relative.parts or
                relative.parts[0].casefold() not in {".linnet", "music", "videos", "ipod_control"}):
            return False
        path = root / relative
        try:
            _plain(path, root)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                return False
            stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
            key = (str(path), digest)
            # NTFS can report the same timestamps for two immediate writes of
            # equal size. Hash recent files on every check until that window
            # has passed, then reuse the verified stamp on later refreshes.
            recent = os.name == "nt" and info.st_mtime_ns > time.time_ns() - 5_000_000_000
            def notify(current, total):
                if progress:
                    progress(dict(current=index, total=len(outputs), file=name,
                                  bytes=current, file_bytes=total))
            if verified is not None and not recent and verified.get(key) == stamp:
                notify(info.st_size, info.st_size)
                continue
            if _hash(path, progress=notify if progress else None) != digest:
                return False
            after = path.stat()
            if stamp != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
                return False
            if verified is not None and not recent:
                verified[key] = stamp
        except (OSError, ValueError):
            return False
    return True


def _checking_progress(kind, checkpoint, progress, stage):
    last, current_file, started = 0.0, -1, 0.0
    def report(event):
        nonlocal last, current_file, started
        now = time.monotonic()
        if event['current'] != current_file:
            current_file, started = event['current'], now
        finished = (event['current'] + 1 == event['total'] and
                    event['bytes'] == event['file_bytes'])
        if now - last < 0.2 and not finished:
            return
        checkpoint()
        fraction = (1.0 if event['bytes'] == event['file_bytes'] else
                    min(1.0, event['bytes'] / max(1, event['file_bytes'])))
        stage((event['current'] + fraction) / event['total'])
        detail = ''
        if event['file_bytes'] >= 1024 * 1024:
            detail = f" · {fraction:.0%} ({format_size(event['bytes'])} / {format_size(event['file_bytes'])})"
            elapsed = now - started
            if elapsed >= 1 and event['bytes'] and fraction < 1:
                seconds = elapsed * (event['file_bytes'] - event['bytes']) / event['bytes']
                detail += (f' · about {max(1, round(seconds / 60))}m left' if seconds >= 60 else
                           f' · about {max(1, round(seconds))}s left')
        progress(f"Checking {kind} {event['current']+1}/{event['total']}: {Path(event['file']).name}{detail}")
        last = now
    return report


def _published_photo_output(root, identity, output_paths, published):
    from .photos import MAX_FILE
    expected = '.LINNET/PHOTOS/LIBRARY.PIM'
    if output_paths not in ([expected], [expected, '.LINNET/PHOTOS/GRID.PGR']) or len(published) != 1 or not isinstance(published[0], dict):
        raise RuntimeError('Photo publication did not return its expected output')
    receipt = published[0]
    outputs = []
    for name, item in [(expected, receipt)] + ([('.LINNET/PHOTOS/GRID.PGR', receipt.get('grid'))] if len(output_paths)==2 else []):
        outputs.append(_photo_output(root, identity, name, item, MAX_FILE))
    return outputs


def _photo_output(root, identity, expected, receipt, max_file):
    if not isinstance(receipt,dict):
        raise RuntimeError('Photo publication did not return its expected receipt')
    if (receipt.get('passed') is not True or receipt.get('operation') != 'publish-photos' or
            receipt.get('phase') not in ('published', 'reused')):
        raise RuntimeError('Photo publication did not complete')
    _same_target(identity, receipt['identity'])
    active = root / expected
    if Path(receipt['package']) != active:
        raise RuntimeError('Photo publication output path changed')
    digest, size = receipt['candidate_sha256'], receipt['candidate_bytes']
    if (not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None or
            type(size) is not int or not 512 <= size <= max_file):
        raise RuntimeError('Photo publication returned invalid output metadata')
    _plain(active, root)
    info = active.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
        raise RuntimeError('Photo publication output changed after readback')
    return expected, digest


class Cancelled(RuntimeError):
    pass


def video_jobs(root, pending=(), selection=None, skipped=(), identity=None, *, snapshots=None):
    """Resolve selected conversions and this device's supported on-disk videos."""
    root = Path(root).resolve(strict=True)
    folder = root / "Videos"
    allowed = video_source_extensions(identity)
    native_extensions = native_video_extensions(identity)
    scan_allowed = native_extensions if selection is not None else allowed
    excluded = {Path(value).as_posix().casefold() for value in skipped}
    generated = set()
    if identity is not None:
        try:
            saved = json.loads((cache_root(identity) / 'state.json').read_text(encoding='utf-8'))
            for relative, item in saved.get('video_files', {}).items():
                for output in item.get('outputs', []):
                    name = output[0]
                    path = Path(name)
                    if (path.parts and path.parts[0].casefold() == 'videos' and
                            not path.is_absolute() and '..' not in path.parts and
                            name.casefold() != ('Videos/' + relative).casefold()):
                        generated.add(str(root / path).casefold())
        except (OSError, ValueError, UnicodeError, TypeError, AttributeError, IndexError):
            pass
    available = [str(path) for source in source_folders(root, "Videos")
                 for path, _ in _file_records(source, allowed=scan_allowed)
                 if str(path).casefold() not in generated and
                 (not excluded or path.relative_to(root).as_posix().casefold() not in excluded)]
    from .video_catalog import read_file
    catalog = root / ".LINNET" / "VIDEOS" / "INDEX.VID"
    _plain(catalog, root)
    entries = read_file(catalog)[1] if catalog.exists() else []
    published = {}
    for catalog_key, name, title in entries:
        path = root / name.lstrip('/')
        _plain(path, root)
        published[path.resolve()] = title
    native = [name for name in available if Path(name).suffix.lower() in native_extensions]
    chosen = available if selection is None else selection
    chosen = list(dict.fromkeys([*native, *chosen]))
    source_roots = [path.resolve() for path in source_folders(root, 'Videos')]
    jobs = {}

    def include(source, relative):
        _plain(source, Path(source.anchor))
        source = source.resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in allowed:
            raise ValueError(f"Unsupported video: {source}")
        key = relative.casefold()
        if key in jobs and jobs[key]["source"] != str(source):
            raise ValueError(f"Two videos have the same library name: {relative}. Rename one first.")
        info = source.stat()
        jobs[key] = dict(source=str(source), relative=relative, bytes=info.st_size, mtime_ns=info.st_mtime_ns,
                         catalog_title=published.get(source))

    for name in chosen:
        source = Path(name).absolute()
        _plain(source, root)
        source = source.resolve(strict=True)
        if not any(source.is_relative_to(folder) for folder in source_roots):
            raise ValueError(f"Selected video is outside this iPod's video sources: {source}")
        include(source, source.relative_to(folder).as_posix() if source.is_relative_to(folder)
                else source.relative_to(root).as_posix())
    for kind, name in pending:
        if kind != "Videos":
            continue
        source = Path(name).absolute()
        _plain(source, Path(source.anchor))
        source = source.resolve(strict=True)
        if source.is_relative_to(root):
            raise ValueError("Use Choose videos and select this file under Videos on this iPod.")
        is_folder = source.is_dir()
        records = _planning_records(source, snapshots)
        for path, info in (records if not is_folder else
                        ((path, info) for path, info in records if path.suffix.lower() in allowed)):
            relative = (Path(source.name) / path.relative_to(source)).as_posix() if is_folder else source.name
            existing = folder / relative
            _plain(existing, root)
            if existing.exists():
                if not existing.is_file() or existing.stat().st_size != info.st_size or not _same_file_bytes(path, existing, info.st_size):
                    raise ValueError(f"A different video already exists: {relative}. Rename the new file first.")
                path = existing
            include(path, relative)
    if len(jobs) > 256:
        raise ValueError("Choose at most 256 videos per update.")
    return list(jobs.values())


def _video_inventory(jobs):
    rows = []
    for job in jobs:
        info = Path(job["source"]).stat()
        rows.append((job["relative"], job["source"], info.st_size, info.st_mtime_ns))
    return dict(count=len(rows), files=[job["source"] for job in jobs],
                fingerprint=hashlib.sha256(json.dumps(rows).encode()).hexdigest())


def _error_record(kind, error, inventory, root):
    """Attach a concrete source when a compiler identifies one in its error."""
    from . import SourceError
    message = str(error)
    if isinstance(error, TimeoutError):
        return dict(kind=kind, message=message)
    if isinstance(error, SourceError):
        folded = str(error.source).casefold()
        matches = [Path(value) for value in inventory.get("files", []) if str(value).casefold() == folded]
    else:
        folded = message.casefold()
        matches = [Path(value) for value in inventory.get("files", []) if str(value).casefold() in folded]
    record = dict(kind=kind, message=message)
    if len(matches) == 1:
        source = matches[0]
        name = source.relative_to(root).as_posix() if source.is_relative_to(root) else source.name
        record.update(file=name, source=str(source))
    return record


def _source_error(kind, name, errors):
    source = Path(name)
    for error in errors:
        if error.get('kind') != kind:
            continue
        value = error.get('source')
        if value and (Path(value) == source or Path(value).is_relative_to(source)):
            return error
        relative = str(error.get('file') or '').replace('\\', '/')
        for prefix in (source.name, f'{kind}/{source.name}'):
            if relative == prefix or relative.startswith(prefix + '/'):
                return error
    return None


def _pending_outcomes(pending, selected, plan, videos, steps, errors, planned):
    added = {step['added'] for step in steps if 'added' in step}
    ready_videos = {step['file'] for step in steps
                    if step.get('kind') == 'Videos' and
                    step.get('status') in ('published', 'unchanged', 'catalog-updated') and
                    'file' in step}
    pending_video_names = {Path(name).name for kind, name in pending if kind == 'Videos'}
    unfinished_videos = set()
    for job in (videos if pending_video_names else ()):
        if job['relative'] not in ready_videos:
            first = job['relative'].split('/', 1)[0]
            if first in pending_video_names:
                unfinished_videos.add(first)
    pending_sources = {(kind, Path(name)) for kind, name in pending if kind != 'Videos'}
    pending_kinds = {kind for kind, _ in pending_sources}
    unfinished = set()
    for item in (plan if pending_sources else ()):
        kind = item['kind']
        if kind not in pending_kinds or item['destination'] in added:
            continue
        source = Path(item['source'])
        if source.drive:
            drive_source = Path(source.drive)
            key = kind, drive_source
            if key in pending_sources and source.is_relative_to(drive_source):
                unfinished.add(key)
        while True:
            key = kind, source
            if key in pending_sources:
                unfinished.add(key)
            if source == source.parent:
                break
            source = source.parent
    outcomes = []
    for kind, name in pending:
        source = Path(name)
        if kind == 'Videos':
            finished = kind in selected and planned and source.name not in unfinished_videos
        else:
            finished = kind in selected and planned and (kind, source) not in unfinished
        matching_error = _source_error(kind, name, errors)
        outcomes.append(dict(kind=kind, source=name,
                             status='completed' if finished else 'unfinished',
                             reason='' if finished else (matching_error or {}).get('message', 'Source did not finish.')))
    return outcomes


def _finish_retries(attempts, skipped, unresolved):
    report = attempts[-1]
    report['started'] = attempts[0]['started']
    report['steps'] = [step for attempt in attempts for step in attempt['steps']]
    report['cleanup'] = {
        key: [entry for attempt in attempts for entry in attempt['cleanup'][key]]
        for key in ('removed', 'retained')
    }
    outcomes = {}
    for attempt in attempts:
        for row in attempt.get('source_outcomes', []):
            outcomes[(row['kind'], row['source'])] = row
    report['source_outcomes'] = list(outcomes.values())
    report['errors'] = skipped + unresolved
    report['auto_skipped'] = skipped
    report['complete'] = not unresolved and not report.get('stopped')
    if len(attempts) > 1:
        report['retry_receipts'] = [attempt['receipt'] for attempt in attempts[:-1]]
    for outcome in report['source_outcomes']:
        matching = _source_error(outcome['kind'], outcome['source'], skipped)
        if matching:
            outcome.update(status='skipped', reason=matching['message'])
    if skipped:
        count = len(skipped)
        outcome = 'stopped' if report.get('stopped') else 'finished'
        report['summary'] = (
            f"Update {outcome} with {count} problem file{'s' if count != 1 else ''} skipped. "
            'Select a skipped file in Media Manager if you want to retry it.'
        )
        if unresolved:
            report['summary'] += ' Some non-file errors still need attention.'
    _save(Path(report['receipt']), report)
    return report


def run(identity, selected, pending=(), **options):
    from .publish import _exclusive
    # The same Windows mutex is recursive for nested publishers on this thread.
    # A second manager must not overwrite the first manager's cache or catalog.
    with _exclusive(identity):
        automatically_skipped = []
        skipped_keys = set()
        excluded_sources = set()
        attempts = []
        unresolved = []
        retry_selected = selected
        while True:
            # Verify the device after taking the mutex, including on a source-error retry.
            identity = refresh(identity)
            root = Path(identity["root"]).resolve(strict=True)
            allowed = video_source_extensions(identity)
            current_options = dict(options, excluded_sources=excluded_sources)
            if attempts:
                current_options['force'] = False
            retry_pending = tuple(item for item in pending if item[0] in retry_selected)
            report = _run(identity, retry_selected, retry_pending, **current_options)
            attempts.append(report)
            remaining = []
            newly_skipped = []
            for error in report["errors"]:
                kind, source_value = error.get("kind"), error.get("source")
                if not kind or not source_value or report.get("stopped"):
                    remaining.append(error)
                    continue
                try:
                    source = Path(source_value).resolve()
                except (OSError, ValueError):
                    remaining.append(error)
                    continue
                key = (kind, str(source).casefold())
                if key in skipped_keys:
                    remaining.append(error)
                    continue
                try:
                    if source.is_relative_to(root):
                        if not skip_files(identity, [(kind, str(source))]):
                            remaining.append(error)
                            continue
                    else:
                        if kind != "Videos" or source.suffix.lower() not in allowed:
                            remaining.append(error)
                            continue
                        excluded_sources.add(str(source).casefold())
                except (OSError, ValueError):
                    remaining.append(error)
                    continue
                skipped_keys.add(key)
                skipped = dict(error, status="skipped")
                newly_skipped.append(skipped)
                automatically_skipped.append(skipped)
                options.get("progress", lambda message: None)(
                    f"Skipped problem file and continuing: {source}"
                )
            unresolved.extend(remaining)
            unsafe = {error.get('kind') for error in remaining}
            retry_kinds = {error['kind'] for error in newly_skipped} - unsafe
            if not retry_kinds or None in unsafe:
                return _finish_retries(attempts, automatically_skipped, unresolved)
            retry_selected = tuple(kind for kind in KINDS if kind in retry_kinds)


def _prepare_audio(root, cache, skipped, ffprobe, checkpoint, progress, report,
                   aac_recovery, flac_recovery, record, stage_progress=lambda fraction: None,
                   force=False, cancelled=lambda: False, audio_journal=None):
    from .aac_index import prepare_file as prepare_aac
    from .flac_index import prepare_file as prepare_flac
    supported = ('.m4a', '.m4b', '.flac', '.flc')
    checkpoint()
    next_check = time.monotonic() + 0.05
    pending = []
    for folder in source_folders(root, 'Music'):
        for path in folder.rglob('*'):
            if time.monotonic() >= next_check:
                checkpoint()
                next_check = time.monotonic() + 0.05
            suffix = path.suffix.lower()
            if suffix not in supported or not path.is_file():
                continue
            if path.relative_to(root).as_posix().casefold() in skipped:
                continue
            pending.append((path, suffix))
    totals = {'aac': sum(suffix in ('.m4a', '.m4b') for _, suffix in pending),
              'flac': sum(suffix in ('.flac', '.flc') for _, suffix in pending)}
    completed = {'aac': 0, 'flac': 0}
    seek_state_path = cache / 'seek-checked.json'
    seek_state = {} if force else _optional_state(seek_state_path)
    seen = set()
    pending_checks = 0
    prepared = False
    probe_deferred = False
    durations = {'aac': [], 'flac': []}
    music_seeds = []
    seed_bytes = 0
    for path, suffix in pending:
        checkpoint()
        _plain(path, root)
        kind = 'aac' if suffix in ('.m4a', '.m4b') else 'flac'
        key = path.relative_to(root).as_posix().casefold()
        seen.add(key)
        before = path.stat()
        stamp = [before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino]
        if seek_state.get(key) == stamp:
            completed[kind] += 1
            stage_progress((completed['aac'] + completed['flac']) / len(pending))
            continue
        label = 'AAC' if kind == 'aac' else 'FLAC'
        left = totals[kind] - completed[kind]
        recent = durations[kind]
        seconds = sum(recent) / len(recent) * left if len(recent) >= 2 else None
        eta = (f' · about {max(1, round(seconds / 60))}m left' if seconds >= 60 else
               ' · <1m left') if seconds is not None else ''
        stage_progress((completed['aac'] + completed['flac']) / len(pending))
        progress(f'{label} seeks {completed[kind]}/{totals[kind]} · {left} left{eta}: {path.name}')
        started = time.monotonic()
        metadata_seed = None
        verified_stamp = None
        if suffix in ('.m4a', '.m4b'):
            def seed_local(local):
                nonlocal metadata_seed
                try:
                    from .music import _read_metadata
                    metadata = _read_metadata(local, ffprobe or shutil.which('ffprobe'), True,
                                              cancelled, include_cover=True)
                    metadata_seed = (metadata, metadata.pop('_embedded_cover', None))
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass  # The library compiler can still read the iPod copy.
            def retain_verified(info):
                nonlocal verified_stamp
                verified_stamp = _receipt_stamp(info)
            outcome = prepare_aac(path, cache / 'aac-seek', checkpoint=checkpoint,
                                  recovery=aac_recovery,
                                  journal=(lambda: audio_journal('AAC', aac_recovery[-1])) if audio_journal else record,
                                  local_copy=seed_local if not force else None,
                                  verified_copy=retain_verified if not force else None)
            if outcome:
                prepared = True
                report['steps'].append(dict(prepared_aac=str(path.relative_to(root))))
                if audio_journal is None:
                    record()
        else:
            outcome = prepare_flac(path, cache / 'flac-seek', ffprobe=ffprobe,
                                   checkpoint=checkpoint, recovery=flac_recovery,
                                   journal=(lambda: audio_journal('FLAC', flac_recovery[-1])) if audio_journal else record)
            if outcome is None:
                probe_deferred = True
            elif outcome:
                prepared = True
                report['steps'].append(dict(prepared_flac=str(path.relative_to(root))))
                if audio_journal is None:
                    record()
        if outcome is not None:
            after = path.stat()
            if outcome and metadata_seed is not None and verified_stamp == _receipt_stamp(after):
                music_seeds.append((path, after, *metadata_seed))
                seed_bytes += len(metadata_seed[1] or b'')
                if len(music_seeds) >= 128 or seed_bytes >= 32 * 1024 * 1024:
                    _seed_imported_music(root, cache, music_seeds)
                    music_seeds.clear()
                    seed_bytes = 0
            if not outcome and _receipt_stamp(before) != _receipt_stamp(after):
                raise ValueError(f'Audio source changed during seek check: {path}')
            seek_state[key] = [after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino]
            pending_checks += 1
            if pending_checks >= 128:
                _save_seek_state(seek_state_path, seek_state)
                pending_checks = 0
        recent.append(time.monotonic() - started)
        if len(recent) > 8:
            recent.pop(0)
        completed[kind] += 1
    if music_seeds:
        _seed_imported_music(root, cache, music_seeds)
    seek_state = {key: value for key, value in seek_state.items() if key in seen}
    _save_seek_state(seek_state_path, seek_state)
    stage_progress(1)
    for kind, label in (('aac', 'AAC'), ('flac', 'FLAC')):
        if totals[kind]:
            progress(f'{label} seeks {completed[kind]}/{totals[kind]} complete')
    checkpoint()
    return prepared, probe_deferred


def _prepare_music(root, cache, identity, skipped, *, ffprobe, verification, force,
                   cancelled, checkpoint, progress, report, begin_publication):
    from .music import compile_music
    from .publish import publish_music
    stage = cache / "music"
    music_progress = _throttled_progress(checkpoint, progress,
        lambda event: f'{"Using saved metadata" if event.get("cached") else "Reading metadata"} '
                      f'{event["current"]+1}/{event["total"]}: {Path(event["file"]).name}')
    preparation = compile_music(root, stage, ffprobe=ffprobe or shutil.which("ffprobe"), device_root=root,
                  verification=verification, cache_path=cache / "music-metadata.sqlite3",
                  bypass_cache=force, progress=music_progress, include_roots=source_folders(root, "Music"),
                  excluded=skipped, target=identity["target_id"], cancelled=cancelled)
    report["steps"].append(dict(kind="Music", metadata=preparation.get("cache"), integrity=verification))
    checkpoint()
    progress("Publishing the music index and artwork…")
    begin_publication("Music")
    publication = publish_music(stage, progress=progress, **target_args(identity))
    verified_outputs = publication.pop('_verified_outputs')
    published = [publication]
    output_paths = [".LINNET/LIBRARY.PDB"] + [entry["path"].lstrip("/") for entry in preparation["entries"]
                    if entry["storage"] == "staged"] + [
        ".LINNET/ART/" + path.name for path in sorted((stage / "ART").glob("*.RGB"))]
    if (stage / "COVERS.CFL").exists(): output_paths.append(".LINNET/COVERS.CFL")
    if (stage / "BROWSE.BIN").exists(): output_paths.append(".LINNET/BROWSE.BIN")
    return output_paths, published, verified_outputs


def _music_outputs_from_publication(root, output_paths, verified_outputs, identity):
    """Reuse fresh artwork readbacks and hash all other published outputs."""
    _volume_guard(identity)
    outputs = []
    for name in output_paths:
        proof = verified_outputs.get(name)
        path = root / name
        _plain(path, root)
        if proof is None:
            outputs.append((name, _hash(path)))
            continue
        if not isinstance(proof, tuple) or len(proof) != 2:
            raise ValueError(f"invalid music publication proof: {name}")
        digest, stamp = proof
        info = path.stat()
        if _receipt_stamp(info) != stamp:
            raise ValueError(f"music output changed after publication: {path}")
        outputs.append((name, digest))
    return outputs


def _prepare_photos(root, cache, identity, media_profile, skipped, retail_photos, *,
                    dimension, checkpoint, progress, begin_publication):
    from .photos import compile_photos
    from .publish_photos import publish_photos
    package = cache / "photos.pimg"
    photo_progress = _throttled_progress(checkpoint, progress,
        lambda event: f'Preparing photos {event["current"]+1}/{event["total"]}: {Path(event["file"]).name}')
    compile_photos(root / "Photos", package, max_dimension=dimension,
                   target=identity['target_id'],
                   viewport_width=media_profile["photo_width"],
                   viewport_height=media_profile["photo_height"],
                   cache_dir=cache / "photo-cache", progress=photo_progress, checkpoint=checkpoint,
                   excluded={Path(value).relative_to("Photos").as_posix() for value in skipped},
                   additional_sources={Path(item['relative']).relative_to('Photos').as_posix():
                                       (item['preview'], item['title']) for item in retail_photos})
    checkpoint()
    progress("Publishing prepared photos…")
    begin_publication("Photos")
    return [".LINNET/PHOTOS/LIBRARY.PIM", ".LINNET/PHOTOS/GRID.PGR"], [
        publish_photos(package, grid=package.with_suffix('.pgr'), **target_args(identity))]


def _prepare_notes(root, cache, identity, skipped, *, checkpoint, progress,
                   report, begin_publication):
    from .notes import compile_notes
    from .publish_notes import publish_notes
    package = cache / "notes.pnot"
    note_progress = _throttled_progress(checkpoint, progress,
        lambda event: f'Preparing notes {event["current"]+1}/{event["total"]}: {Path(event["file"]).name}')
    preparation = compile_notes(root / "Notes", package, target=identity['target_id'],
        progress=note_progress, checkpoint=checkpoint,
        excluded={Path(value).relative_to("Notes").as_posix() for value in skipped})
    report["steps"].append(dict(kind="Notes", preparation=preparation))
    if preparation.get("ascii_converted"):
        progress("Notes: non-ASCII text was adapted for the iPod font; originals are unchanged. See the report.")
    checkpoint()
    progress("Publishing prepared notes…")
    begin_publication("Notes")
    return [".LINNET/NOTES/LIBRARY.NNT"], [publish_notes(package, **target_args(identity))]


def _prepare_videos(root, cache, identity, media_profile, state, state_path, videos, item, *,
                    ffmpeg, ffprobe, force, cancelled, checkpoint, progress, emit_stage, unit,
                    record, report, verified_outputs, owned_temporaries, progress_detail,
                    mark_publication):
    kind = "Videos"
    published = []
    from .ipvf_encode import encode_ipvf
    from .ipvf_validate import inspect_file
    from .publish_video import publish_video
    from .video_sources import video_title, catalog_contains
    output_paths = [".LINNET/VIDEOS/INDEX.VID"]
    video_state = state.get("video_files", {})
    if not isinstance(video_state, dict):
        video_state = {}
    state["video_files"] = video_state
    failed = 0
    retail_titles = None
    catalog_snapshot = {}
    for index, job in enumerate(videos):
        emit_stage('Preparing Videos', unit, index / len(videos))
        checkpoint()
        source = Path(job["source"])
        relative = job["relative"]
        file_publication_started = False
        try:
            key = hashlib.sha256(relative.encode()).hexdigest()[:8].upper()
            source_info = source.stat()
            source_stamp = (source_info.st_size, source_info.st_mtime_ns)
            label = job.get('catalog_title')
            if not label and source.is_relative_to(root):
                if retail_titles is None:
                    from .retail_media import available_tracks
                    retail_titles = available_tracks(root)
                label = retail_titles.get(str(source).casefold(), {}).get('title')
            label = video_title(label or relative)
            if media_profile["video_backend"] in ("bcm-mp4", "native-mp4"):
                from .native_video import inspect_file as inspect_native, prepare as prepare_native
                from .publish_video import device_video_path, index_video
                native_version = 5 if media_profile["video_backend"] == "native-mp4" else 3
                fingerprint = hashlib.sha256(f"native-mp4-v{native_version}:{json.dumps(media_profile, sort_keys=True)}:{source}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
                cached = video_state.get(relative, {})
                if not isinstance(cached, dict):
                    cached = {}
                outputs = cached.get('outputs', [])
                cached_output_ready = False
                if (not force and cached.get("signature") == fingerprint and len(outputs) == 1 and
                        _outputs_match(root, outputs, verified=verified_outputs)):
                    try:
                        inspect_native(root / outputs[0][0], profile=media_profile,
                                       ffprobe=ffprobe, cancelled=cancelled)
                        cached_output_ready = True
                    except (OSError, ValueError):
                        pass
                if cached_output_ready:
                    if catalog_contains(root, relative, label, path=False,
                                        snapshot=catalog_snapshot):
                        output_paths.extend(name for name, digest in outputs)
                        report["steps"].append(dict(kind=kind, file=relative, status="unchanged"))
                        continue
                    if len(outputs) == 1:
                        published_path = root / outputs[0][0]
                        if catalog_contains(root, relative, None,
                                            path=device_video_path(published_path, root),
                                            snapshot=catalog_snapshot):
                            emit_stage('Publishing Videos', unit,
                                       (index + 0.5) / len(videos), can_stop=False)
                            mark_publication()
                            file_publication_started = True
                            result = index_video(published_path, title=label,
                                                 library_key=relative, ffprobe=ffprobe,
                                                 **target_args(identity))
                            catalog_snapshot.clear()
                            output_paths.append(outputs[0][0])
                            report["steps"].append(dict(kind=kind, file=relative,
                                                        status="catalog-updated", publication=result))
                            record()
                            continue
                compatible = False
                if source.suffix.lower() in native_video_extensions(identity):
                    try:
                        native_info = inspect_native(source, ffprobe=ffprobe, profile=media_profile, cancelled=cancelled)
                        compatible = native_info['fast_start'] or not (ffmpeg or shutil.which('ffmpeg'))
                    except ValueError:
                        pass
                progress(f"Preparing native video {index+1}/{item['count']}: {relative}")
                if compatible and source.is_relative_to(root):
                    emit_stage('Publishing Videos', unit,
                               (index + 0.5) / len(videos), can_stop=False)
                    mark_publication()
                    file_publication_started = True
                    result = index_video(source, title=label, library_key=relative, ffprobe=ffprobe, **target_args(identity))
                    outputs = [(source.relative_to(root).as_posix(), _hash(source))]
                    output_paths.append(source.relative_to(root).as_posix())
                else:
                    package = cache / "videos" / (key + "-" + fingerprint[:16] + ".mp4")
                    reusable = package.exists() and not force
                    if reusable:
                        try:
                            inspect_native(package, ffprobe=ffprobe, profile=media_profile,
                                           cancelled=cancelled)
                        except (OSError, ValueError):
                            reusable = False
                    if not reusable:
                        prepare_native(source, package, profile=media_profile, ffmpeg=ffmpeg, ffprobe=ffprobe, progress=progress, cancelled=cancelled)
                    checkpoint()
                    after = source.stat()
                    if (after.st_size, after.st_mtime_ns) != source_stamp:
                        raise ValueError("Video changed during preparation; scan again")
                    emit_stage('Publishing Videos', unit,
                               (index + 0.5) / len(videos), can_stop=False)
                    mark_publication()
                    file_publication_started = True
                    result = publish_video(package, title=label, library_key=relative,
                                           ffprobe=ffprobe,
                                           source_to_preserve=source if source.is_relative_to(root) else None,
                                           **target_args(identity))
                    output_name = Path(result['package']).relative_to(root).as_posix()
                    outputs = [(output_name, result["candidate_sha256"])]
                    output_paths.append(output_name)
                after = source.stat()
                if (after.st_size, after.st_mtime_ns) != source_stamp:
                    raise ValueError("Video changed during publication; scan again")
                published.append(result)
                catalog_snapshot.clear()
                video_state[relative] = dict(signature=fingerprint, outputs=outputs, source_stamp=source_stamp)
                _save(state_path, state)
                report["steps"].append(dict(kind=kind, file=relative, status="published", publication=result))
                record()
                continue
            profile_key = (f"{media_profile['video_width']}x{media_profile['video_height']}-"
                           f"{media_profile['video_fps']}-{media_profile['video_color']}-realtime")
            fingerprint = hashlib.sha256(f"ipvf-{profile_key}:{source}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
            cached = video_state.get(relative, {})
            if not isinstance(cached, dict):
                cached = {}
            cached_outputs = cached.get('outputs')
            first_output = cached_outputs[0] if isinstance(cached_outputs, list) and cached_outputs else None
            output_name = (first_output[0] if isinstance(first_output, (list, tuple))
                           and len(first_output) == 2 and isinstance(first_output[0], str) else "")
            native_ipvf = source.suffix.lower() in native_video_extensions(identity)
            index_in_place = native_ipvf and source.is_relative_to(root)
            if (not force and cached.get("signature") == fingerprint
                    and catalog_contains(root, relative, label, path=False,
                                         snapshot=catalog_snapshot)
                    and (index_in_place or (output_name.casefold().startswith("videos/ipvf/")
                         and _outputs_match(root, cached.get("outputs", []), verified=verified_outputs)))):
                if not index_in_place:
                    output_paths.append(output_name)
                progress(f"Video {index+1}/{item['count']} already ready: {relative}")
                report["steps"].append(dict(kind=kind, file=relative, status="unchanged"))
                continue
            package = cache / "videos" / (key + "-" + fingerprint[:16] + ".ipvf")
            progress(f"Preparing video {index+1}/{item['count']}: {relative}")
            if index_in_place:
                from .publish_video import index_ipvf
                emit_stage('Publishing Videos', unit,
                           (index + 0.5) / len(videos), can_stop=False)
                mark_publication()
                file_publication_started = True
                result = index_ipvf(source, title=label, library_key=relative, **target_args(identity))
                published.append(result)
                catalog_snapshot.clear()
                video_state[relative] = dict(signature=fingerprint, outputs=[], source_stamp=source_stamp)
                _save(state_path, state)
                report["steps"].append(dict(kind=kind, file=relative, status="published", publication=result))
                record()
                continue
            reusable = package.exists() and not force
            if reusable:
                try:
                    inspect_file(package,expected_width=media_profile["video_width"],
                                 expected_height=media_profile["video_height"],
                                 max_record_sectors=media_profile["max_read_sectors"])
                except (OSError, ValueError):
                    reusable = False
            if not reusable:
                if native_ipvf:
                    inspect_file(source,expected_width=media_profile["video_width"],
                                 expected_height=media_profile["video_height"],
                                 max_record_sectors=media_profile["max_read_sectors"])
                    package.parent.mkdir(parents=True, exist_ok=True)
                    temporary = package.with_name(package.name + "." + uuid.uuid4().hex + ".tmp")
                    with source.open("rb") as reader, temporary.open("xb") as writer:
                        owned_temporaries.append((temporary, cache))
                        while chunk := reader.read(1024 * 1024):
                            checkpoint()
                            writer.write(chunk)
                        writer.flush()
                        os.fsync(writer.fileno())
                    inspect_file(temporary,expected_width=media_profile["video_width"],
                                 expected_height=media_profile["video_height"],
                                 max_record_sectors=media_profile["max_read_sectors"])
                    os.replace(temporary, package)
                else:
                    encode_ipvf(source, package, title=label,
                                ffmpeg=ffmpeg or shutil.which("ffmpeg"),
                                ffprobe=ffprobe or shutil.which("ffprobe"),
                                fps=media_profile["video_fps"],
                                color_depth=media_profile["video_color"],
                                width=media_profile["video_width"],
                                height=media_profile["video_height"],
                                max_record_sectors=media_profile["max_read_sectors"],
                                progress=progress, cancelled=cancelled,
                                progress_detail=(lambda event: progress_detail(dict(event,
                                    video_index=index+1, video_total=item['count']))) if progress_detail else None)
            checkpoint()
            after = source.stat()
            if (after.st_size, after.st_mtime_ns) != source_stamp:
                raise ValueError("Video changed during preparation; scan again before updating")
            progress(f"Publishing video {index+1}/{item['count']}: {relative}")
            emit_stage('Publishing Videos', unit,
                       (index + 0.5) / len(videos), can_stop=False)
            mark_publication()
            file_publication_started = True
            result = publish_video(package, title=label, library_key=relative,
                                   source_to_preserve=source if source.is_relative_to(root) else None,
                                   **target_args(identity))
            catalog_snapshot.clear()
            output_name = Path(result['package']).relative_to(root).as_posix()
            published.append(result)
            output_paths.append(output_name)
            after = source.stat()
            if (after.st_size, after.st_mtime_ns) != source_stamp:
                raise ValueError("Video changed during publication; scan again before updating")
            video_state[relative] = dict(signature=fingerprint, source_stamp=source_stamp,
                outputs=[(output_name, result["candidate_sha256"])])
            _save(state_path, state)
            report["steps"].append(dict(kind=kind, file=relative, status="published", publication=result))
            record()
        except Cancelled:
            raise
        except Exception as error:
            catalog_snapshot.clear()
            checkpoint()
            failed += 1
            video_state.pop(relative, None)
            state.pop(kind, None)
            _save(state_path, state)
            failure = dict(kind=kind, file=relative, message=str(error))
            if file_publication_started:
                failure["status"] = "publication-uncertain"
            else:
                failure["source"] = str(source)
            report["errors"].append(failure)
            progress(f"Video could not finish, continuing with the next file: {relative}: {error}")
            record()
    return output_paths, published, failed


def _run(identity, selected, pending=(), *, progress=lambda message: None, cancelled=lambda: False,
        photo_dimension=640, ffmpeg=None, ffprobe=None, force=False, music_verification="metadata",
        video_selection=None, progress_detail=None, progress_stage=lambda event: None,
        excluded_sources=None, online_artwork=False):
    """Copy additions, prepare and publish selected folders; retain per-step receipts.

    Stop requests are honored between files and between compiler/publication calls.
    Failed publication is never retried automatically.
    """
    requested = tuple(kind for kind in KINDS if kind in selected)
    unsupported = tuple(kind for kind in requested if kind not in supported_kinds(identity))
    if unsupported:
        raise ValueError(f"{', '.join(unsupported)} playback is unavailable on this iPod model.")
    selected = requested
    if not selected:
        raise ValueError("Select at least one media folder to prepare.")
    total_stages = 4 + 2 * len(selected)
    def emit_stage(name, unit, fraction=0, can_stop=True):
        progress_stage(dict(name=name, completed=unit, total=total_stages,
                            fraction=fraction, can_stop=can_stop))
    if music_verification not in ("metadata", "full"):
        raise ValueError("Music verification must be metadata or full")
    root = Path(identity["root"])
    media_profile = identity["media_profile"]
    cache = cache_root(identity)
    if cache.drive.casefold() == root.drive.casefold():
        raise ValueError("The preparation cache must be on the computer, not the iPod.")
    cache.mkdir(parents=True, exist_ok=True)
    state_path = cache / "state.json"
    state = _optional_state(state_path)
    if not isinstance(state.get("skipped_files", {}), dict):
        state["skipped_files"] = {}
    skipped = {kind: _skipped_paths(state, kind) for kind in KINDS}
    report = dict(started=time.time(), identity=identity, steps=[], errors=[], complete=False,
                  stopped=False, cache_directory=str(cache), cleanup=dict(removed=[], retained=[]))
    plan, videos, planned = [], [], False
    owned_temporaries = []
    verified_outputs = {}
    receipt = cache / ("session-" + uuid.uuid4().hex + ".json")
    report["receipt"] = str(receipt)
    audio_journal_path = receipt.with_suffix('.audio.jsonl')
    report['audio_journal'] = str(audio_journal_path)
    aac_recovery = report['aac_preparations'] = []
    flac_recovery = report['flac_preparations'] = []
    aac_committed = aac_publication_started = False

    def checkpoint():
        if cancelled():
            raise Cancelled("Stopped between steps. Completed copies and publications have been retained.")
        _volume_guard(identity)

    def record():
        _save(receipt, report)

    def journal_audio(kind, change):
        _append_audio_journal(audio_journal_path, kind, change)

    record()
    try:
        if video_selection is not None:
            video_selection = [value for value in video_selection
                               if Path(value).resolve().relative_to(root).as_posix().casefold()
                               not in skipped["Videos"]]
        videos = video_jobs(root, pending, video_selection, skipped=skipped["Videos"], identity=identity) if "Videos" in selected else []
        excluded_sources = {str(Path(value).resolve()).casefold() for value in (excluded_sources or ())}
        videos = [job for job in videos if str(Path(job["source"]).resolve()).casefold() not in excluded_sources]
        plan = additions(root, [item for item in pending if item[0] in selected and item[0] != "Videos"])
        planned = True
        for kind, maximum in (("Notes", 256),):
            if kind in selected:
                existing = scan(root, (kind,), skipped=skipped)[kind]["count"]
                added = sum(item["kind"] == kind and Path(item["source"]).suffix.lower() in extensions(kind) for item in plan)
                if existing + added > maximum:
                    raise ValueError(f"{kind} supports {maximum} files; this selection contains {existing + added}. Choose a smaller source folder.")
        needed = sum(item["bytes"] for item in plan)
        if needed + 1024 * 1024 > identity["free_bytes"]:
            raise ValueError("There is not enough space for the selected originals. Choose fewer files.")
        emit_stage('Copying originals', 0)
        _copy_additions(plan, root, report, owned_temporaries, checkpoint, record, progress,
                        cache=cache, cancelled=cancelled,
                        stage_progress=lambda current, total, name:
                            emit_stage(name, 0, current / total if total else 1))
        checkpoint()
        if "Music" in selected:
            def renamed_music(old, new):
                old_key = old.relative_to(root).as_posix().casefold()
                new_key = new.relative_to(root).as_posix().casefold()
                skipped["Music"] = {new_key + key[len(old_key):]
                                    if key == old_key or key.startswith(old_key + "/") else key
                                    for key in skipped["Music"]}
                state.setdefault("skipped_files", {})["Music"] = sorted(skipped["Music"])
                _save(state_path, state)
                progress(f"Renamed for music playback: {old.name} → {new.name}")
                report["steps"].append(dict(renamed=str(old), destination=str(new)))
                record()
            _normalize_music_paths(root, checkpoint, renamed_music)
            if online_artwork:
                from .album_art import fetch
                report['steps'].append(dict(kind='Music', artwork_lookup=fetch(root, progress=progress,
                    checkpoint=checkpoint, retry_missing=force)))
        emit_stage('Scanning folders', 1)
        progress("Scanning the iPod folders…")
        retail_photos = None
        if "Photos" in selected:
            from .retail_media import images
            retail_photos = images(root)
        inventory = scan(root, selected, skipped=skipped, retail_photos=retail_photos,
                         fingerprint_kinds=(kind for kind in selected if kind != "Videos"))
        if "Videos" in selected:
            inventory["Videos"] = _video_inventory(videos)
        for kind in KINDS:
            if kind not in selected:
                continue
            unit = 2 + 2 * selected.index(kind)
            emit_stage(f'Preparing {kind}', unit)
            checkpoint()
            item = inventory[kind]
            if not item["count"]:
                if kind == 'Photos' and item.get('skipped'):
                    from .media_library import list_items, remove_items
                    libraries = [row for row in list_items(identity)
                                 if row['kind'] == 'Photos' and row['category'] == 'library']
                    if libraries:
                        remove_items(identity, libraries)
                    state.pop(kind, None)
                    _save(state_path, state)
                    progress('Photos: all sources excluded; Linnet photo index retired.')
                    continue
                progress(f"{kind}: no supported files; existing prepared library retained.")
                continue
            option = preparation_option(kind, identity, photo_dimension, music_verification)
            video_version = 6 if media_profile.get("video_backend") == "native-mp4" else 4
            signature = (f"videos-v{video_version}-{json.dumps(media_profile, sort_keys=True)}:{item['fingerprint']}" if kind == "Videos"
                         else f"{option}:{item['fingerprint']}")
            saved = state.get(kind, {})
            if not isinstance(saved, dict):
                saved = {}
            outputs = saved.get("outputs", [])
            probe = (ffprobe or shutil.which('ffprobe')) if kind == 'Music' else None
            probe_retry = bool(kind == 'Music' and saved.get('seek_probe_deferred') and probe)
            if not force and not probe_retry and not (kind == "Music" and music_verification == "full") and signature == saved.get("signature"):
                emit_stage(f'Checking saved {kind}', unit)
                checking = _checking_progress(kind, checkpoint, progress,
                    lambda fraction: emit_stage(f'Checking saved {kind}', unit, fraction))
                if _outputs_match(root, outputs, verified=verified_outputs, progress=checking):
                    videos_compatible = True
                    if kind == 'Videos' and media_profile['video_backend'] in ('bcm-mp4', 'native-mp4'):
                        from .native_video import inspect_file as inspect_native
                        video_outputs = [root / name for name, _ in outputs
                                         if Path(name).suffix.lower() in native_video_extensions(identity)]
                        videos_compatible = bool(video_outputs)
                        for path in video_outputs:
                            try:
                                inspect_native(path, profile=media_profile, ffprobe=ffprobe,
                                               cancelled=cancelled)
                            except (OSError, ValueError):
                                videos_compatible = False
                                break
                    if videos_compatible:
                        progress(f"{kind}: already up to date.")
                        report["steps"].append(dict(kind=kind, status="unchanged"))
                        continue
            if kind == 'Music':
                prepared, probe_deferred = _prepare_audio(root, cache, skipped['Music'], probe,
                                                          checkpoint, progress, report, aac_recovery, flac_recovery, record,
                                                          stage_progress=lambda fraction: emit_stage('Preparing audio seeks', unit, fraction),
                                                          force=force, cancelled=cancelled,
                                                          audio_journal=journal_audio)
                if prepared:
                    # Seek atoms change source sizes and timestamps. Publish
                    # the fingerprint of the prepared files.
                    item = scan(root, ('Music',), skipped=skipped, fingerprint_kinds=('Music',))['Music']
                    inventory[kind] = item
                    signature = f"{option}:{item['fingerprint']}"
            progress(f"Preparing {kind.lower()} ({item['count']:,} files)…")
            publication_started = False
            try:
                def begin_publication(published_kind):
                    nonlocal publication_started, aac_publication_started
                    emit_stage(f'Publishing {published_kind}', unit + 1, can_stop=False)
                    publication_started = True
                    if published_kind == 'Music':aac_publication_started = True
                def mark_publication():
                    nonlocal publication_started
                    publication_started = True
                if kind == "Music":
                    output_paths, published, music_proofs = _prepare_music(root, cache, identity, skipped["Music"],
                        ffprobe=ffprobe, verification=music_verification, force=force,
                        cancelled=cancelled, checkpoint=checkpoint, progress=progress,
                        report=report, begin_publication=begin_publication)
                    aac_committed = True
                elif kind == "Photos":
                    output_paths, published = _prepare_photos(root, cache, identity, media_profile,
                        skipped["Photos"], retail_photos, dimension=photo_dimension,
                        checkpoint=checkpoint, progress=progress, begin_publication=begin_publication)
                elif kind == "Notes":
                    output_paths, published = _prepare_notes(root, cache, identity, skipped["Notes"],
                        checkpoint=checkpoint, progress=progress, report=report,
                        begin_publication=begin_publication)
                else:
                    output_paths, published, failed = _prepare_videos(
                        root, cache, identity, media_profile, state, state_path, videos, item,
                        ffmpeg=ffmpeg, ffprobe=ffprobe, force=force, cancelled=cancelled,
                        checkpoint=checkpoint, progress=progress, emit_stage=emit_stage, unit=unit,
                        record=record, report=report, verified_outputs=verified_outputs,
                        owned_temporaries=owned_temporaries, progress_detail=progress_detail,
                        mark_publication=mark_publication)
                    if failed:
                        progress(f"Videos: {failed} file(s) need attention; completed videos are saved.")
                        continue
                emit_stage(f'Checking {kind}', unit + 1, 0.5)
                checkpoint()
                # Do not mark a changed source tree up to date.
                current = (_video_inventory(videos) if kind == "Videos" else
                           scan(root, (kind,), skipped=skipped)[kind])
                if current["fingerprint"] != item["fingerprint"]:
                    raise ValueError(f"{kind} changed during processing. Scan again before updating.")
                if kind == 'Photos':
                    checkpoint()
                    outputs = _published_photo_output(root, identity, output_paths, published)
                elif kind == 'Music':
                    outputs = _music_outputs_from_publication(root, output_paths, music_proofs, identity)
                else:
                    outputs = [(name, _hash(root / name)) for name in output_paths]
                state[kind] = dict(signature=signature, outputs=outputs)
                if kind == 'Music':
                    state[kind]['seek_probe_deferred'] = probe_deferred
                if kind == "Videos":
                    state[kind]["media_profile"] = media_profile
                _save(state_path, state)
                report["steps"].append(dict(kind=kind, status="published", publications=published))
                progress(f"{kind}: published and verified on your iPod ({root / '.LINNET'}).")
                record()
            except Cancelled:
                raise
            except Exception as error:
                if publication_started:
                    report["errors"].append(dict(kind=kind, message=str(error),
                                                 status="publication-uncertain"))
                else:
                    report["errors"].append(_error_record(kind, error, item, root))
                progress(f"{kind} could not finish: {error}")
                record()
        # File ordering, names, text wrapping and image conversion belong on
        # the host. Publish this snapshot after the media libraries and files.
        checkpoint()
        emit_stage('Preparing Files', total_stages - 2)
        from .files import compile_files, publish_files
        files_package = cache / 'files.fil'
        files_report = compile_files(root, files_package, cache / 'file-previews',
            target=identity['target_id'],
            width=media_profile['photo_width'] if 'Photos' in supported_kinds(identity) else 0,
            height=media_profile['photo_height'] if 'Photos' in supported_kinds(identity) else 0,
            text_columns=20 if media_profile['photo_width'] < 220 else 24,
            checkpoint=checkpoint, progress=progress)
        checkpoint()
        emit_stage('Publishing Files', total_stages - 2, can_stop=False)
        files_publication = publish_files(files_package, files_report, **target_args(identity))
        files_status = 'unchanged' if files_publication.get('reused_index') and not files_publication['previews_added'] else 'published'
        report['steps'].append(dict(kind='Files', status=files_status, publication=files_publication,
                                   warnings=files_report['warnings']))
        record()
        emit_stage('Finishing checks', total_stages - 2)
        report["complete"] = not report["errors"]
    except Exception as error:
        report["stopped"] = isinstance(error, Cancelled) or cancelled()
        report["errors"].append(dict(message=str(error)))
        progress(str(error))
    finally:
        emit_stage('Cleaning up', total_stages - 1, can_stop=False)
        from .aac_index import finish_preparation
        for change in aac_recovery + flac_recovery:
            try:
                _volume_guard(identity)
                _plain(Path(change['path']), root)
                _plain(Path(change['backup']), cache)
                if aac_publication_started and not aac_committed:
                    raise OSError('Music publication is uncertain; audio original retained for recovery')
                finish_preparation(change, committed=aac_committed, kind=change.get('kind', 'AAC'))
                change['outcome'] = 'published' if aac_committed else 'restored'
            except Exception as error:
                report['complete'] = False
                report['errors'].append(dict(kind='Music', message=str(error)))
                report['cleanup']['retained'].append(dict(path=change['backup'], reason=str(error)))
        for temporary, boundary in owned_temporaries:
            try:
                if boundary == root:
                    _volume_guard(identity)
                _plain(temporary, boundary)
                if temporary.exists():
                    temporary.unlink()
                    report["cleanup"]["removed"].append(str(temporary))
            except Exception as error:
                report["cleanup"]["retained"].append(dict(path=str(temporary), reason=str(error)))
        # Audit scratch locations without deleting files that could belong to another run.
        publications = []
        publication_name = re.compile(r'publish-.*\.json', re.DOTALL | (re.IGNORECASE if os.name == 'nt' else 0)).fullmatch
        for path in cache.rglob('*'):
            name = path.name.casefold()
            if publication_name(path.name):
                publications.append(path)
            if (name.startswith(('ipvf-encode-', 'music-prepare-')) or
                    '.music-prepare-' in name or name.endswith((
                        '.tmp', '.music-previous', '.aac-original', '.aac-append', '.flac-original'))):
                report["cleanup"]["retained"].append(dict(path=str(path),
                    reason="Preparation scratch remains; review before removing if another update is running."))
        for path in publications:
            try:
                publication = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(publication, dict):
                    raise ValueError("invalid publication receipt")
                warnings = publication.get("cleanup_warnings", [])
                if not isinstance(warnings, list) or any(
                        not isinstance(warning, dict) or
                        any(not isinstance(warning.get(key), str) for key in ("path", "error"))
                        for warning in warnings):
                    raise ValueError("invalid publication cleanup warnings")
                for warning in warnings:
                    report["cleanup"]["retained"].append(dict(path=warning["path"], reason=warning["error"]))
                if not publication.get("passed"):
                    report["cleanup"]["retained"].append(dict(path=str(path),
                        reason="Incomplete publication receipt: inspect its temporary and backup paths before cleanup."))
            except (OSError, ValueError):
                report["cleanup"]["retained"].append(dict(path=str(path), reason="Unreadable publication receipt; review required."))
        count = len(report["cleanup"]["removed"])
        progress(f"Cleanup: removed {count} temporary file(s).")
        for item in report["cleanup"]["retained"]:
            progress(f"Retained for review: {item['path']} — {item['reason']}")
        if not report["cleanup"]["retained"]:
            progress("Cleanup: no preparation scratch files remain.")
        report['source_outcomes'] = _pending_outcomes(pending, selected, plan, videos,
                                                      report['steps'], report['errors'], planned)
        ready = [kind for kind in KINDS if any(step.get("kind") == kind and
                 step.get("status") in ("published", "unchanged") for step in report["steps"])]
        failed = list(dict.fromkeys(error["kind"] for error in report["errors"] if error.get("kind")))
        summary = []
        if ready:
            summary.append(f"On your iPod ({root}): {', '.join(ready)}.")
        if failed:
            summary.append(f"Could not finish: {', '.join(failed)}. Open report for the errors.")
        for step in report['steps']:
            artwork = step.get('artwork_lookup')
            if artwork:
                summary.append(f"Album covers: {artwork['downloaded']} downloaded; {artwork.get('cached', 0)} reused; {artwork['unmatched']} without a confident match.")
                if artwork['errors']:
                    summary.append('Artwork service unavailable; cached covers were kept. Prepare again to retry.')
        if report["stopped"]:
            summary.append("Update stopped; completed work is retained on the iPod.")
        elif report["errors"] and not failed:
            summary.append("Update could not finish. Open report for the error.")
        report["summary"] = " ".join(summary)
        progress(f"Computer cache for faster retries (separate from the published iPod files): {cache}")
        if report["summary"]:
            progress(report["summary"])
        report["finished"] = time.time()
        record()
        try:
            audio_journal_path.unlink(missing_ok=True)
        except OSError as error:
            report['cleanup']['retained'].append(dict(path=str(audio_journal_path), reason=str(error)))
            try:
                record()
            except OSError:
                pass  # The prior receipt is durable; return the retained path in this report.
    return report
