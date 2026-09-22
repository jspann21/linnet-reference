"""Desktop media workflow. Originals live in the user's four iPod folders.

Preparation is cached on the host; publication uses the existing guarded writers.
No device is modified by discovery or scanning.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import unicodedata
import uuid

from .publish import _plain, _hash, _same_target, _volume_guard, inspect_target

KINDS = ("Music", "Notes", "Photos", "Videos")
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mpeg", ".wmv", ".ipvf"}


def extensions(kind):
    if kind == "Music":
        from .music import EXTENSIONS
        return EXTENSIONS
    if kind == "Photos":
        from .photos import EXTENSIONS
        return EXTENSIONS
    if kind == "Notes":
        from .notes import EXTENSIONS
        return EXTENSIONS
    if kind == "Videos":
        return VIDEO_EXTENSIONS
    raise ValueError("Unknown media folder")


def discover():
    """Find mounted iPods and resolve each through publication guards."""
    if os.name != "nt":
        raise RuntimeError("The media manager currently supports Windows Disk Mode.")
    from tools.studio.targets import TARGETS
    names=["Apple iPod"]+[spec["native_storage"]["friendly_name"] for spec in TARGETS.values() if "native_storage" in spec]
    script = r"""
$ErrorActionPreference='Stop'
$names=ConvertFrom-Json 'NATIVE_NAMES'
$items=@(Get-Disk | Where-Object {$_.BusType -eq 'USB' -and $_.FriendlyName -in $names} | ForEach-Object {
 $disk=$_
 Get-Partition -DiskNumber $disk.Number | Where-Object {$_.DriveLetter} | ForEach-Object {
  $drive=[string]$_.DriveLetter+':'
  $logical=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$drive+"'")
  @{number=[int]$disk.Number;serial=$disk.SerialNumber.Trim();volume=$logical.VolumeSerialNumber;drive=$drive}
 }
})
ConvertTo-Json -InputObject $items -Compress
""".replace('NATIVE_NAMES',json.dumps(names).replace("'","''"))
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "Windows did not finish reading the iPod's storage identity within 30 seconds. "
            "Disconnect it, resolve the disk or cable problem, then reconnect it in Disk Mode "
            "and choose Find iPod."
        ) from error
    if result.returncode:
        raise RuntimeError(
            "We couldn't read your iPod's storage. Reconnect your iPod in Disk Mode, "
            "wait a few seconds, then try again. If the problem continues, try a different "
            "USB cable or port."
        ) from subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr
        )
    items = json.loads(result.stdout.lstrip("\ufeff") or "[]")
    return [_identify(inspect_target(item["number"], item["serial"], item["volume"], item["drive"])) for item in items]


def _identify(identity):
    """Bind Disk Mode storage identity to one target manifest."""
    from tools.inspect.retail_device import detect
    from tools.studio.targets import TARGETS, media_profile
    detected = detect(identity["root"])
    storage = detected["storage"]
    if (detected["device_id"] != identity["disk_serial"] or
            storage["disk_number"] != identity["disk_number"] or
            storage["disk_bytes"] != identity["disk_bytes"] or
            storage["partition_offset"] != identity["partition_offset"]):
        raise RuntimeError("USB and mounted storage identities disagree")
    spec = TARGETS[detected["target_id"]]
    return dict(identity, target_id=detected["target_id"], target_name=spec["name"],
                linnet_usb_serial=detected["linnet_usb_serial"],
                model_number=detected["retail_os"].get("model_number"),
                regulatory_model=(spec["retail"]["regulatory_models"] or [None])[0],
                media_profile=media_profile(detected["target_id"]))


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
    current = _identify(inspect_target(**target_args(identity)))
    _same_target(identity, current)
    if current["target_id"] != identity.get("target_id"):
        raise RuntimeError("iPod target identity changed during media operation")
    return current


def source_folders(root, kind):
    root = Path(root)
    folders = [root / kind]
    if kind in ("Music", "Videos"):
        folders.append(root / "iPod_Control" / "Music")
    return [folder for folder in folders if folder.is_dir()]


def _file_records(folder):
    if not folder.exists():
        return []
    _plain(folder, Path(folder.anchor))
    if not folder.is_dir():
        raise ValueError(f"Expected a folder: {folder}")
    found = []
    directories = [folder]
    while directories:
        with os.scandir(directories.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                    raise ValueError(f"Linked files or folders are unsupported: {path}")
                if stat.S_ISDIR(info.st_mode):
                    directories.append(path)
                elif stat.S_ISREG(info.st_mode):
                    found.append((path, info))
    return sorted(found, key=lambda item: (str(item[0]).casefold(), str(item[0])))


def _files(folder):
    return [path for path, info in _file_records(folder)]


def _records_by_kind(root, kinds=KINDS):
    folders, result = {}, {}
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        result[kind] = []
        for folder in source_folders(root, kind):
            if folder not in folders:
                folders[folder] = _file_records(folder)
            result[kind].extend(folders[folder])
    return result


def _skipped_paths(state, kind):
    skipped = state.get("skipped_files", {}) if isinstance(state, dict) else {}
    values = skipped.get(kind, []) if isinstance(skipped, dict) else []
    if not isinstance(values, list):
        return set()
    result = set()
    prefixes = {(kind.casefold(),)}
    if kind in ("Music", "Videos"):
        prefixes.add(("ipod_control", "music"))
    for value in values:
        if not isinstance(value, str):
            continue
        path = Path(value)
        parts = tuple(part.casefold() for part in path.parts)
        if (path.is_absolute() or path.drive or ".." in path.parts or
                not any(parts[:len(prefix)] == prefix for prefix in prefixes)):
            continue
        result.add(path.as_posix().casefold())
    return result


def preparation_option(kind, identity, photo_dimension=640, music_verification='metadata'):
    """Shared preparation version for compilation and library readiness."""
    if kind == 'Music':
        from tools.studio.targets import TARGETS
        art_version = ('art9' if identity['target_id'] == 'classic6g-n25' else
                       'art8' if TARGETS[identity['target_id']]['lcd_format'] == 'gray2-horizontal' else 'art7')
        return f"{music_verification}-duration-search-names-album-owner2-title-order1-retail2-recent-album-gain-{art_version}-{identity['target_id']}"
    if kind == 'Notes':
        return 'theme-fonts1'
    if kind == 'Photos':
        profile = identity['media_profile']
        return f"retail-photos3-{photo_dimension}-{profile['photo_width']}x{profile['photo_height']}"
    return 'default'


def scan(root, kinds=KINDS, skipped=None, *, records_by_kind=None):
    root = Path(root).resolve(strict=True)
    kinds = tuple(kinds)
    if records_by_kind is None:
        records_by_kind = _records_by_kind(root, kinds)
    skipped = skipped or {}
    result = {}
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        excluded = {Path(value).as_posix().casefold() for value in skipped.get(kind, ())}
        rows, supported = [], []
        supported_bytes = skipped_count = ignored = 0
        allowed = extensions(kind)
        records = records_by_kind[kind]
        for path, info in records:
            relative = path.relative_to(root).as_posix()
            if relative.casefold() in excluded:
                skipped_count += 1
                continue
            rows.append((relative, info.st_size, info.st_mtime_ns))
            if path.suffix.lower() in allowed:
                supported.append(str(path))
                supported_bytes += info.st_size
            else:
                ignored += 1
        if kind in ('Music', 'Videos'):
            database = root / 'iPod_Control/iTunes/iTunesDB'
            _plain(database, root)
            if database.is_file():
                info = database.stat()
                rows.append(('iTunesDB', info.st_size, info.st_mtime_ns))
            artwork_folder = root / 'iPod_Control' / 'Artwork'
            for path, info in _file_records(artwork_folder):
                rows.append((path.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns))
            if kind == 'Music':
                from .album_art import signature as artwork_signature
                from .retail_media import tracks
                rows.append(('album-art', artwork_signature(tracks(root).values())))
        if kind == 'Photos':
            from .retail_media import images
            for photo in images(root):
                if photo['relative'].casefold() in excluded:
                    skipped_count += 1
                    continue
                supported.append(str(root / photo['relative']))
                supported_bytes += photo['bytes']
                rows.append((photo['relative'], photo['bytes'], photo['mtime_ns'], photo['preview']))
        result[kind] = dict(count=len(supported), bytes=supported_bytes,
                            ignored=ignored, files=supported,
                            skipped=skipped_count,
                            fingerprint=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
    return result


def skip_files(identity, items):
    """Persist supported iPod source files that should be omitted from preparation."""
    identity = refresh(identity)
    root = Path(identity["root"]).resolve(strict=True)
    state_path = cache_root(identity) / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    skipped = state.setdefault("skipped_files", {})
    if not isinstance(skipped, dict):
        skipped = state["skipped_files"] = {}
    added = []
    known_by_kind = {}
    for kind, value in items:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        path = Path(value).resolve()
        retail_photo = False
        if kind == 'Photos' and path.is_relative_to(root / 'Photos' / '@iTunes'):
            from .retail_media import images
            retail_photo = any(path == root / photo['relative'] for photo in images(root))
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
                video_state.pop(path.relative_to(root / "Videos").as_posix(), None)
    _save(state_path, state)
    return added


def list_skipped_files(identity):
    """Return cached skip entries with their current source locations."""
    root = Path(identity["root"]).resolve()
    state_path = cache_root(identity) / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    skipped = state.get("skipped_files", {}) if isinstance(state, dict) else {}
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
    root = Path(identity["root"]).resolve(strict=True)
    state_path = cache_root(identity) / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    skipped = state.get("skipped_files", {})
    if not isinstance(skipped, dict):
        return []
    restored = []
    for kind, value in items:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        relative = Path(value).as_posix()
        values = skipped.get(kind, [])
        if not isinstance(values, list):
            continue
        kept = [item for item in values if not isinstance(item, str) or Path(item).as_posix().casefold() != relative.casefold()]
        if len(kept) != len(values):
            skipped[kind] = kept
            restored.append(relative)
            state.pop(kind, None)
    _save(state_path, state)
    return restored


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
    from .music import device_media_path, UnsupportedMediaPath
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
                device_media_path(path, root)
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
                device_media_path(path, root)
            if directory:
                directories.append(path)


def additions(root, pending):
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
        records = _file_records(source) if is_folder else [(source, source.stat())]
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
                if not destination.is_file() or destination.stat().st_size != info.st_size or _hash(destination) != _hash(path):
                    raise ValueError(f"A different file already exists: {destination}. Rename the new file or folder first.")
                continue
            planned[key] = dict(kind=kind, source=str(path), destination=str(destination),
                                bytes=info.st_size, mtime_ns=info.st_mtime_ns)
    return list(planned.values())


def _copy_additions(plan, root, report, owned_temporaries, checkpoint, record, progress):
    # Queue a bounded set of writes before flushing and reading them back. On
    # FAT devices, alternating write/flush/read/rename for every small file is
    # expensive. Keep every handle until its flush, and publish only verified files.
    start = 0
    while start < len(plan):
        batch = []
        batch_bytes = 0
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
        with ExitStack() as handles:
            for offset, (item, temporary) in enumerate(batch):
                checkpoint()
                source, destination = Path(item['source']), Path(item['destination'])
                progress(f"Adding {start + offset + 1}/{len(plan)}: {source.name}")
                _plain(source, Path(source.anchor))
                _plain(destination, root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                _plain(destination.parent, root)
                info = source.stat()
                if (info.st_size, info.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
                    raise ValueError(f"Source changed since selection: {source}")
                digest = hashlib.sha256()
                writer = handles.enter_context(temporary.open('xb'))
                owned_temporaries.append((temporary, root))
                with source.open('rb') as reader:
                    while chunk := reader.read(1024 * 1024):
                        checkpoint()
                        writer.write(chunk)
                        digest.update(chunk)
                writer.flush()
                after = source.stat()
                if (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                    raise ValueError(f"Source changed during copy: {source}")
                copied.append((item, temporary, writer, digest.hexdigest()))
            progress(f"Saving additions {start + 1}–{start + len(batch)}/{len(plan)}…")
            for _, _, writer, _ in copied:
                checkpoint()
                os.fsync(writer.fileno())
        for offset, (item, temporary, _, digest) in enumerate(copied):
            checkpoint()
            destination = Path(item['destination'])
            progress(f"Verifying addition {start + offset + 1}/{len(plan)}: {destination.name}")
            _plain(temporary, root)
            if _hash(temporary, item['bytes']) != digest:
                raise OSError(f"Copy verification failed: {destination}")
        for item, temporary, _, _ in copied:
            checkpoint()
            destination = Path(item['destination'])
            _plain(destination, root)
            # Windows rename refuses an existing destination, preserving both files.
            if destination.exists():
                raise ValueError(f"Destination appeared during copy: {destination}")
            temporary.rename(destination)
            owned_temporaries.remove((temporary, root))
            report['steps'].append(dict(added=str(destination), bytes=item['bytes']))
        report.pop('copies_in_progress', None)
        record()
        start += len(batch)


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


def cache_root(identity):
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "Linnet" / "Media"
    key = hashlib.sha256((identity["disk_serial"] + identity["volume_serial"]).encode()).hexdigest()[:24]
    return base / key


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as writer:
        json.dump(value, writer, indent=2)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.replace(path)


def _outputs_match(root, outputs, *, verified=None):
    """Treat malformed/stale host cache entries as misses, with bounded paths."""
    if not isinstance(outputs, list) or not outputs:
        return False
    for item in outputs:
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
            stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            key = (str(path), digest)
            if verified is not None and verified.get(key) == stamp:
                continue
            if _hash(path) != digest:
                return False
            after = path.stat()
            if stamp != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                return False
            if verified is not None:
                verified[key] = stamp
        except (OSError, ValueError):
            return False
    return True


class Cancelled(Exception):
    pass


def video_jobs(root, pending=(), selection=None, skipped=(), identity=None):
    """Resolve selected conversions and this device's supported on-disk videos."""
    root = Path(root).resolve(strict=True)
    folder = root / "Videos"
    available = scan(root, ("Videos",), skipped={"Videos": skipped})["Videos"]["files"]
    from .video_catalog import read_file
    catalog = root / ".LINNET" / "VIDEOS" / "INDEX.VID"
    _plain(catalog, root)
    entries = read_file(catalog)[1] if catalog.exists() else []
    published = {}
    for catalog_key, name, title in entries:
        path = root / name.lstrip('/')
        _plain(path, root)
        published[path.resolve()] = title
    allowed = video_source_extensions(identity)
    available = [name for name in available if Path(name).suffix.lower() in allowed]
    native_extensions = native_video_extensions(identity)
    native = [name for name in available if Path(name).suffix.lower() in native_extensions]
    chosen = available if not selection else selection
    chosen = list(dict.fromkeys([*native, *chosen]))
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
        if not any(source.is_relative_to(p.resolve()) for p in source_folders(root, 'Videos')):
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
        for path in _files(source) if is_folder else [source]:
            if is_folder and path.suffix.lower() not in allowed:
                continue
            relative = (Path(source.name) / path.relative_to(source)).as_posix() if is_folder else source.name
            existing = folder / relative
            _plain(existing, root)
            if existing.exists():
                if not existing.is_file() or existing.stat().st_size != path.stat().st_size or _hash(existing) != _hash(path):
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


def run(identity, selected, pending=(), **options):
    from .publish import _exclusive
    # The same Windows mutex is recursive for nested publishers on this thread.
    # A second manager must not overwrite the first manager's cache or catalog.
    identity = refresh(identity)
    with _exclusive(identity):
        root = Path(identity["root"]).resolve(strict=True)
        automatically_skipped = []
        skipped_keys = set()
        excluded_sources = set()
        while True:
            current_options = dict(options, excluded_sources=excluded_sources)
            report = _run(identity, selected, pending, **current_options)
            remaining = []
            newly_skipped = []
            for error in report["errors"]:
                kind, source_value = error.get("kind"), error.get("source")
                if not kind or not source_value or report.get("stopped"):
                    remaining.append(error)
                    continue
                source = Path(source_value).resolve()
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
            if not newly_skipped:
                report["errors"] = automatically_skipped + remaining
                report["auto_skipped"] = automatically_skipped
                report["complete"] = not remaining and not report.get("stopped")
                if automatically_skipped:
                    count = len(automatically_skipped)
                    outcome = 'stopped' if report.get('stopped') else 'finished'
                    report["summary"] = (
                        f"Update {outcome} with {count} problem file{'s' if count != 1 else ''} skipped. "
                        "Select a skipped file in Media Manager if you want to retry it."
                    )
                    if remaining:
                        report["summary"] += " Some non-file errors still need attention."
                _save(Path(report["receipt"]), report)
                return report


def _run(identity, selected, pending=(), *, progress=lambda message: None, cancelled=lambda: False,
        photo_dimension=640, ffmpeg=None, ffprobe=None, force=False, music_verification="metadata",
        video_selection=None, progress_detail=None, excluded_sources=None, online_artwork=False):
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
    identity = refresh(identity)
    if music_verification not in ("metadata", "full"):
        raise ValueError("Music verification must be metadata or full")
    root = Path(identity["root"])
    media_profile = identity["media_profile"]
    cache = cache_root(identity)
    if cache.drive.casefold() == root.drive.casefold():
        raise ValueError("The preparation cache must be on the computer, not the iPod.")
    cache.mkdir(parents=True, exist_ok=True)
    state_path = cache / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    if not isinstance(state.get("skipped_files", {}), dict):
        state["skipped_files"] = {}
    skipped = {kind: _skipped_paths(state, kind) for kind in KINDS}
    report = dict(started=time.time(), identity=identity, steps=[], errors=[], complete=False,
                  stopped=False, cache_directory=str(cache), cleanup=dict(removed=[], retained=[]))
    owned_temporaries = []
    verified_outputs = {}
    receipt = cache / ("session-" + uuid.uuid4().hex + ".json")
    report["receipt"] = str(receipt)

    def checkpoint():
        if cancelled():
            raise Cancelled("Stopped between steps. Completed copies and publications have been retained.")
        _volume_guard(identity)

    def record():
        _save(receipt, report)

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
        for kind, maximum in (("Notes", 256),):
            if kind in selected:
                existing = scan(root, (kind,), skipped=skipped)[kind]["count"]
                added = sum(item["kind"] == kind and Path(item["source"]).suffix.lower() in extensions(kind) for item in plan)
                if existing + added > maximum:
                    raise ValueError(f"{kind} supports {maximum} files; this selection contains {existing + added}. Choose a smaller source folder.")
        needed = sum(item["bytes"] for item in plan)
        if needed + 1024 * 1024 > identity["free_bytes"]:
            raise ValueError("There is not enough space for the selected originals. Choose fewer files.")
        _copy_additions(plan, root, report, owned_temporaries, checkpoint, record, progress)
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
        progress("Scanning the iPod folders…")
        inventory = scan(root, selected, skipped=skipped)
        if "Videos" in selected:
            inventory["Videos"] = _video_inventory(videos)
        for kind in KINDS:
            if kind not in selected:
                continue
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
            video_version = 5 if media_profile.get("video_backend") == "native-mp4" else 3
            signature = (f"videos-v{video_version}-{json.dumps(media_profile, sort_keys=True)}:{item['fingerprint']}" if kind == "Videos"
                         else f"{option}:{item['fingerprint']}")
            saved = state.get(kind, {})
            if not isinstance(saved, dict):
                saved = {}
            outputs = saved.get("outputs", [])
            if not force and not (kind == "Music" and music_verification == "full") and signature == saved.get("signature") and _outputs_match(root, outputs, verified=verified_outputs):
                progress(f"{kind}: already up to date.")
                report["steps"].append(dict(kind=kind, status="unchanged"))
                continue
            progress(f"Preparing {kind.lower()} ({item['count']:,} files)…")
            try:
                folder = root / kind
                published = []
                if kind == "Music":
                    from .music import compile_music
                    from .publish import publish_music
                    stage = cache / "music"
                    last_progress = [0.0]
                    def music_progress(event):
                        checkpoint()
                        now = time.monotonic()
                        if now - last_progress[0] >= 0.2 or event['current'] + 1 == event['total']:
                            action = "Using saved metadata" if event.get("cached") else "Reading metadata"
                            progress(f"{action} {event['current']+1}/{event['total']}: {Path(event['file']).name}")
                            last_progress[0] = now
                    roots = source_folders(root, "Music")
                    preparation = compile_music(root, stage, ffprobe=ffprobe or shutil.which("ffprobe"), device_root=root,
                                  verification=music_verification, cache_path=cache / "music-metadata.sqlite3",
                                  bypass_cache=force, progress=music_progress, include_roots=roots,
                                  excluded=skipped["Music"], target=identity["target_id"])
                    report["steps"].append(dict(kind=kind, metadata=preparation.get("cache"), integrity=music_verification))
                    checkpoint()
                    progress("Publishing the music index and artwork…")
                    published.append(publish_music(stage, progress=progress, **target_args(identity)))
                    output_paths = [".LINNET/LIBRARY.PDB"] + [entry["path"].lstrip("/") for entry in preparation["entries"] if entry["storage"] == "staged"] + [
                        ".LINNET/ART/" + path.name for path in sorted((stage / "ART").glob("*.RGB"))]
                    if (stage / "COVERS.CFL").exists():output_paths.append(".LINNET/COVERS.CFL")
                    if (stage / "BROWSE.BIN").exists():output_paths.append(".LINNET/BROWSE.BIN")
                elif kind == "Photos":
                    from .photos import compile_photos
                    from .publish_photos import publish_photos
                    from .retail_media import images
                    package = cache / "photos.pimg"
                    compile_photos(folder, package, max_dimension=photo_dimension,
                                   viewport_width=media_profile["photo_width"],
                                   viewport_height=media_profile["photo_height"],
                                   excluded={Path(value).relative_to("Photos").as_posix()
                                             for value in skipped["Photos"]},
                                   additional_sources={Path(p['relative']).relative_to('Photos').as_posix():
                                                       (p['preview'], p['title']) for p in images(root)})
                    checkpoint()
                    progress("Publishing prepared photos…")
                    published.append(publish_photos(package, **target_args(identity)))
                    output_paths = [".LINNET/PHOTOS/LIBRARY.PIM"]
                elif kind == "Notes":
                    from .notes import compile_notes
                    from .publish_notes import publish_notes
                    package = cache / "notes.pnot"
                    preparation = compile_notes(folder, package,
                        excluded={Path(value).relative_to("Notes").as_posix()
                                  for value in skipped["Notes"]})
                    report["steps"].append(dict(kind=kind, preparation=preparation))
                    if preparation.get("ascii_converted"):
                        progress("Notes: non-ASCII text was adapted for the iPod font; originals are unchanged. See the report.")
                    checkpoint()
                    progress("Publishing prepared notes…")
                    published.append(publish_notes(package, **target_args(identity)))
                    output_paths = [".LINNET/NOTES/LIBRARY.NNT"]
                else:
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
                    for index, job in enumerate(videos):
                        checkpoint()
                        source = Path(job["source"])
                        relative = job["relative"]
                        try:
                            key = hashlib.sha256(relative.encode()).hexdigest()[:8].upper()
                            source_info = source.stat()
                            source_stamp = (source_info.st_size, source_info.st_mtime_ns)
                            if media_profile["video_backend"] in ("bcm-mp4", "native-mp4"):
                                from .native_video import inspect_file as inspect_native, prepare as prepare_native
                                from .publish_video import index_video
                                native_version = 4 if media_profile["video_backend"] == "native-mp4" else 2
                                fingerprint = hashlib.sha256(f"native-mp4-v{native_version}:{json.dumps(media_profile, sort_keys=True)}:{source}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
                                from .retail_media import tracks
                                label = video_title(job.get('catalog_title') or tracks(root).get(str(source.resolve()).casefold(), {}).get('title') or relative)
                                cached = video_state.get(relative, {})
                                if (not force and isinstance(cached, dict) and cached.get("signature") == fingerprint
                                        and catalog_contains(root, relative, label, path=False)
                                        and _outputs_match(root, cached.get("outputs", []), verified=verified_outputs)):
                                    output_paths.extend(name for name, digest in cached.get("outputs", []))
                                    report["steps"].append(dict(kind=kind, file=relative, status="unchanged"))
                                    continue
                                compatible = False
                                if source.suffix.lower() in native_video_extensions(identity):
                                    try:
                                        inspect_native(source, ffprobe=ffprobe, profile=media_profile)
                                        compatible = True
                                    except ValueError:
                                        pass
                                progress(f"Preparing native video {index+1}/{item['count']}: {relative}")
                                if compatible and source.is_relative_to(root):
                                    result = index_video(source, title=label, library_key=relative, ffprobe=ffprobe, **target_args(identity))
                                    outputs = [(source.relative_to(root).as_posix(), _hash(source))]
                                    output_paths.append(source.relative_to(root).as_posix())
                                else:
                                    package = cache / "videos" / (key + "-" + fingerprint[:16] + ".mp4")
                                    reusable = package.exists() and not force
                                    if reusable:
                                        try: inspect_native(package, ffprobe=ffprobe, profile=media_profile)
                                        except (OSError, ValueError): reusable = False
                                    if not reusable:
                                        prepare_native(source, package, profile=media_profile, ffmpeg=ffmpeg, ffprobe=ffprobe, progress=progress, cancelled=cancelled)
                                    checkpoint()
                                    after = source.stat()
                                    if (after.st_size, after.st_mtime_ns) != source_stamp:
                                        raise ValueError("Video changed during preparation; scan again")
                                    result = publish_video(package, title=label, library_key=relative, ffprobe=ffprobe, **target_args(identity))
                                    output_name = Path(result['package']).relative_to(root).as_posix()
                                    outputs = [(output_name, result["candidate_sha256"])]
                                    output_paths.append(output_name)
                                after = source.stat()
                                if (after.st_size, after.st_mtime_ns) != source_stamp:
                                    raise ValueError("Video changed during publication; scan again")
                                published.append(result)
                                video_state[relative] = dict(signature=fingerprint, outputs=outputs, source_stamp=source_stamp)
                                _save(state_path, state)
                                report["steps"].append(dict(kind=kind, file=relative, status="published", publication=result))
                                record()
                                continue
                            profile_key = (f"{media_profile['video_width']}x{media_profile['video_height']}-"
                                           f"{media_profile['video_fps']}-{media_profile['video_color']}-realtime")
                            fingerprint = hashlib.sha256(f"ipvf-{profile_key}:{source}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
                            from .retail_media import tracks
                            label = video_title(job.get('catalog_title') or tracks(root).get(str(source.resolve()).casefold(), {}).get('title') or relative)
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
                                    and catalog_contains(root, relative, label, path=False)
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
                                result = index_ipvf(source, title=label, library_key=relative, **target_args(identity))
                                published.append(result)
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
                            result = publish_video(package, title=label, library_key=relative, **target_args(identity))
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
                            checkpoint()
                            failed += 1
                            video_state.pop(relative, None)
                            state.pop(kind, None)
                            _save(state_path, state)
                            report["errors"].append(dict(kind=kind, file=relative,
                                                         source=str(source), message=str(error)))
                            progress(f"Video could not finish, continuing with the next file: {relative}: {error}")
                            record()
                    if failed:
                        progress(f"Videos: {failed} file(s) need attention; completed videos are saved.")
                        continue
                checkpoint()
                # Do not mark a changed source tree up to date.
                current = (_video_inventory(videos) if kind == "Videos" else
                           scan(root, (kind,), skipped=skipped)[kind])
                if current["fingerprint"] != item["fingerprint"]:
                    raise ValueError(f"{kind} changed during processing. Scan again before updating.")
                outputs = [(name, _hash(root / name)) for name in output_paths]
                state[kind] = dict(signature=signature, outputs=outputs)
                if kind == "Videos":
                    state[kind]["media_profile"] = media_profile
                _save(state_path, state)
                report["steps"].append(dict(kind=kind, status="published", publications=published))
                progress(f"{kind}: published and verified on your iPod ({root / '.LINNET'}).")
                record()
            except Cancelled:
                raise
            except Exception as error:
                report["errors"].append(_error_record(kind, error, item, root))
                progress(f"{kind} could not finish: {error}")
                record()
        report["complete"] = not report["errors"]
    except Exception as error:
        report["stopped"] = isinstance(error, Cancelled) or cancelled()
        report["errors"].append(dict(message=str(error)))
        progress(str(error))
    finally:
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
                    '.music-prepare-' in name or name.endswith(('.tmp', '.music-previous'))):
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
    return report
