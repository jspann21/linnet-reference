"""Desktop media workflow. Originals live in the user's four iPod folders.

Preparation is cached on the host; publication uses the existing guarded writers.
No device is modified by discovery or scanning.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
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
    """Find mounted Apple USB iPods and resolve each through publication guards."""
    if os.name != "nt":
        raise RuntimeError("The media manager currently supports Windows Disk Mode.")
    script = r"""
$ErrorActionPreference='Stop'
$items=@(Get-Disk | Where-Object {$_.BusType -eq 'USB' -and $_.FriendlyName -eq 'Apple iPod'} | ForEach-Object {
 $disk=$_
 Get-Partition -DiskNumber $disk.Number | Where-Object {$_.DriveLetter} | ForEach-Object {
  $drive=[string]$_.DriveLetter+':'
  $logical=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$drive+"'")
  @{number=[int]$disk.Number;serial=$disk.SerialNumber.Trim();volume=$logical.VolumeSerialNumber;drive=$drive}
 }
})
ConvertTo-Json -InputObject $items -Compress
"""
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
    from tools.studio.targets import TARGETS
    detected = detect(identity["root"])
    storage = detected["storage"]
    if (detected["device_id"] != identity["disk_serial"] or
            storage["disk_number"] != identity["disk_number"] or
            storage["disk_bytes"] != identity["disk_bytes"] or
            storage["partition_offset"] != identity["partition_offset"]):
        raise RuntimeError("RetailOS and mounted storage identities disagree")
    spec = TARGETS[detected["target_id"]]
    enabled = spec.get("capabilities", {}).get("video", True)
    fps, color = spec.get("media_video_fps", 24), spec.get("media_video_color", "rgb565")
    photo_size=(spec.get("media_photo_width"),spec.get("media_photo_height"))
    video_size=(spec.get("media_video_width"),spec.get("media_video_height"))
    if (type(enabled) is not bool or type(fps) is not int or not 4 <= fps <= 30 or
            color not in ("rgb565", "gray4") or
            any(type(value) is not int or value < 1 for value in (*photo_size,*video_size))):
        raise RuntimeError(f"invalid media profile in target manifest: {detected['target_id']}")
    return dict(identity, target_id=detected["target_id"], target_name=spec["name"],
                linnet_usb_serial=detected["linnet_usb_serial"],
                model_number=detected["retail_os"].get("model_number"),
                regulatory_model=(spec["retail"]["regulatory_models"] or [None])[0],
                media_profile=dict(video_enabled=enabled, video_fps=fps, video_color=color,
                    video_extensions=spec["media_video_extensions"],
                    photo_width=photo_size[0],photo_height=photo_size[1],
                    video_width=video_size[0],video_height=video_size[1],
                    max_read_sectors=spec["storage_max_read_sectors"]))


def supported_kinds(identity):
    """Return the media services declared by the resolved device target."""
    profile = identity.get("media_profile", {})
    return tuple(kind for kind in KINDS if kind != "Videos" or profile.get("video_enabled", True))


def native_video_extensions(identity=None):
    return set((identity or {}).get("media_profile", {}).get("video_extensions", [".ipvf"]))


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
    if kind == "Music":
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


def _skipped_paths(state, kind):
    skipped = state.get("skipped_files", {}) if isinstance(state, dict) else {}
    values = skipped.get(kind, []) if isinstance(skipped, dict) else []
    if not isinstance(values, list):
        return set()
    result = set()
    prefixes = {(kind.casefold(),)}
    if kind == "Music":
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
        art_version = 'art3' if identity['target_id'] == 'ipod4g-q21' else 'art2'
        return f"{music_verification}-duration-search-names-album-owner-title-order1-music-folder1-{art_version}-{identity['target_id']}"
    return f'flat-photos1-{photo_dimension}' if kind == 'Photos' else 'default'


def scan(root, kinds=KINDS, skipped=None, *, records_by_kind=None):
    root = Path(root).resolve(strict=True)
    skipped = skipped or {}
    result = {}
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        excluded = {Path(value).as_posix().casefold() for value in skipped.get(kind, ())}
        rows, supported = [], []
        supported_bytes = skipped_count = ignored = 0
        allowed = extensions(kind)
        records = (records_by_kind[kind] if records_by_kind is not None else
                   (record for folder in source_folders(root, kind) for record in _file_records(folder)))
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
    for kind, value in items:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        path = Path(value).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in extensions(kind):
            raise ValueError(f"This is not a supported {kind.lower()} file: {path}")
        if not any(path.is_relative_to(folder.resolve()) for folder in source_folders(root, kind)):
            raise ValueError(f"The file is outside this iPod's {kind} sources: {path}")
        relative = path.relative_to(root).as_posix()
        values = skipped.setdefault(kind, [])
        if not isinstance(values, list):
            values = skipped[kind] = []
        if relative.casefold() not in {Path(item).as_posix().casefold() for item in values if isinstance(item, str)}:
            values.append(relative)
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
    punctuation = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                "‐": "-", "‑": "-", "–": "-", "—": "-", "…": "..."})
    normalized = unicodedata.normalize("NFD", name.translate(punctuation))
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    if normalized.isascii():
        return normalized.replace('"', "'")
    # A readable ASCII prefix also gives names in other scripts a usable alias.
    return "Music - " + name


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
                    candidate = f"{name} ({number})" if directory else f"{Path(name).stem} ({number}){Path(name).suffix}"
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
        files = _files(source) if source.is_dir() else [source]
        for path in files:
            # Preserve supporting files (cover art, playlists) inside selected folders.
            if not source.is_dir() and path.suffix.lower() not in extensions(kind):
                raise ValueError(f"{path.name} is not a supported {kind.lower()} source.")
            relative = Path(source.name) / path.relative_to(source) if source.is_dir() else Path(source.name)
            if kind == "Music":
                relative = Path(*(_music_import_name(part) for part in relative.parts))
            destination = root / kind / relative
            _plain(destination, root)
            key = str(destination).casefold()
            if key in planned and planned[key]["source"] != str(path):
                raise ValueError(f"Two selected files have the same destination: {destination}")
            if destination.exists():
                if not destination.is_file() or destination.stat().st_size != path.stat().st_size or _hash(destination) != _hash(path):
                    raise ValueError(f"A different file already exists: {destination}. Rename the new file or folder first.")
                continue
            info = path.stat()
            planned[key] = dict(kind=kind, source=str(path), destination=str(destination),
                                bytes=info.st_size, mtime_ns=info.st_mtime_ns)
    return list(planned.values())


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


def _outputs_match(root, outputs):
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
                relative.parts[0].casefold() not in {".linnet", "music", "videos"}):
            return False
        path = root / relative
        try:
            _plain(path, root)
            if not path.is_file() or _hash(path) != digest:
                return False
        except (OSError, ValueError):
            return False
    return True


class Cancelled(Exception):
    pass


def video_jobs(root, pending=(), selection=None, skipped=(), identity=None):
    """Resolve selected conversions plus every native IPVF already on the iPod."""
    root = Path(root).resolve(strict=True)
    folder = root / "Videos"
    available = scan(root, ("Videos",), skipped={"Videos": skipped})["Videos"]["files"]
    from .video_catalog import read_file
    catalog = root / ".LINNET" / "VIDEOS" / "INDEX.VID"
    _plain(catalog, root)
    entries = read_file(catalog)[1] if catalog.exists() else []
    published = set()
    for _, name, _ in entries:
        path = root / name.lstrip('/')
        _plain(path, root)
        published.add(path.resolve())
    native = [name for name in available if Path(name).suffix.lower() in native_video_extensions(identity)]
    chosen = available if selection is None else selection
    chosen = list(dict.fromkeys([*native, *chosen]))
    jobs = {}

    def include(source, relative):
        _plain(source, Path(source.anchor))
        source = source.resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"Unsupported video: {source}")
        key = relative.casefold()
        if key in jobs and jobs[key]["source"] != str(source):
            raise ValueError(f"Two videos have the same library name: {relative}. Rename one first.")
        info = source.stat()
        jobs[key] = dict(source=str(source), relative=relative, bytes=info.st_size, mtime_ns=info.st_mtime_ns)

    for name in chosen:
        source = Path(name).absolute()
        _plain(source, root)
        source = source.resolve(strict=True)
        if not source.is_relative_to(folder):
            raise ValueError(f"Selected video is outside this iPod's Videos folder: {source}")
        if source.is_relative_to(folder / "IPVF") and source in published:
            continue
        include(source, source.relative_to(folder).as_posix())
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
            if is_folder and path.suffix.lower() not in VIDEO_EXTENSIONS:
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
    message = str(error)
    folded = message.casefold()
    matches = [Path(value) for value in inventory.get("files", []) if str(value).casefold() in folded]
    record = dict(kind=kind, message=message)
    if len(matches) == 1:
        source = matches[0]
        record.update(file=source.relative_to(root).as_posix(), source=str(source))
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
                        if kind != "Videos" or source.suffix.lower() not in VIDEO_EXTENSIONS:
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
                    report["summary"] = (
                        f"Update finished with {count} problem file{'s' if count != 1 else ''} skipped. "
                        "Select a skipped file in Media Manager if you want to retry it."
                    )
                    if remaining:
                        report["summary"] += " Some non-file errors still need attention."
                _save(Path(report["receipt"]), report)
                return report


def _run(identity, selected, pending=(), *, progress=lambda message: None, cancelled=lambda: False,
        photo_dimension=640, ffmpeg=None, ffprobe=None, force=False, music_verification="metadata",
        video_selection=None, progress_detail=None, excluded_sources=None):
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
    skipped = {kind: _skipped_paths(state, kind) for kind in KINDS}
    report = dict(started=time.time(), identity=identity, steps=[], errors=[], complete=False,
                  stopped=False, cache_directory=str(cache), cleanup=dict(removed=[], retained=[]))
    owned_temporaries = []
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
        for index, item in enumerate(plan):
            checkpoint()
            source, destination = Path(item["source"]), Path(item["destination"])
            progress(f"Adding {index+1}/{len(plan)}: {source.name}")
            _plain(source, Path(source.anchor))
            _plain(destination, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _plain(destination.parent, root)
            info = source.stat()
            if (info.st_size, info.st_mtime_ns) != (item["bytes"], item["mtime_ns"]):
                raise ValueError(f"Source changed since selection: {source}")
            temporary = destination.parent / ("L" + uuid.uuid4().hex[:7] + ".TMP")
            report["copy_in_progress"] = dict(source=str(source), destination=str(destination), temporary=str(temporary))
            record()
            digest = hashlib.sha256()
            with source.open("rb") as reader, temporary.open("xb") as writer:
                owned_temporaries.append((temporary, root))
                while chunk := reader.read(1024 * 1024):
                    checkpoint()
                    writer.write(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if (source.stat().st_size, source.stat().st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                raise ValueError(f"Source changed during copy: {source}")
            _volume_guard(identity)
            if _hash(temporary, item["bytes"]) != digest.hexdigest():
                raise OSError(f"Copy verification failed: {destination}")
            # Windows rename refuses an existing destination, preserving both files.
            if destination.exists():
                raise ValueError(f"Destination appeared during copy: {destination}")
            temporary.rename(destination)
            report.pop("copy_in_progress", None)
            report["steps"].append(dict(added=str(destination), bytes=item["bytes"]))
            record()
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
                progress(f"{kind}: no supported files; existing prepared library retained.")
                continue
            option = preparation_option(kind, identity, photo_dimension, music_verification)
            signature = (f"ipvf-videos-ipvf-{media_profile['video_fps']}-{media_profile['video_color']}-realtime:{item['fingerprint']}" if kind == "Videos"
                         else f"{option}:{item['fingerprint']}")
            saved = state.get(kind, {})
            if not isinstance(saved, dict):
                saved = {}
            outputs = saved.get("outputs", [])
            if not force and not (kind == "Music" and music_verification == "full") and signature == saved.get("signature") and _outputs_match(root, outputs):
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
                elif kind == "Photos":
                    from .photos import compile_photos
                    from .publish_photos import publish_photos
                    package = cache / "photos.pimg"
                    compile_photos(folder, package, max_dimension=photo_dimension,
                                   viewport_width=media_profile["photo_width"],
                                   viewport_height=media_profile["photo_height"],
                                   excluded={Path(value).relative_to("Photos").as_posix()
                                             for value in skipped["Photos"]})
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
                            profile_key = (f"{media_profile['video_width']}x{media_profile['video_height']}-"
                                           f"{media_profile['video_fps']}-{media_profile['video_color']}-realtime")
                            fingerprint = hashlib.sha256(f"ipvf-{profile_key}:{source}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
                            label = video_title(relative)
                            cached = video_state.get(relative, {})
                            if not isinstance(cached, dict):
                                cached = {}
                            output_name = cached['outputs'][0][0] if cached.get('outputs') else ""
                            native_ipvf = source.suffix.lower() in native_video_extensions(identity)
                            index_in_place = native_ipvf and source.is_relative_to(root)
                            if (not force and cached.get("signature") == fingerprint
                                    and catalog_contains(root, relative, label, path=False)
                                    and (index_in_place or (output_name.casefold().startswith("videos/ipvf/")
                                         and _outputs_match(root, cached.get("outputs", []))))):
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
                                video_state[relative] = dict(signature=fingerprint, outputs=[])
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
                            video_state[relative] = dict(signature=fingerprint,
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
        for pattern in ("ipvf-encode-*", "music-prepare-*", "*.tmp"):
            for path in cache.rglob(pattern):
                report["cleanup"]["retained"].append(dict(path=str(path),
                    reason="Preparation scratch remains; review before removing if another update is running."))
        for path in cache.rglob("publish-*.json"):
            try:
                publication = json.loads(path.read_text(encoding="utf-8"))
                for warning in publication.get("cleanup_warnings", []):
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
