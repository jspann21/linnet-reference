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
import uuid

from .publish import _plain, _hash, _same_target, _volume_guard, inspect_target

KINDS = ("Music", "Notes", "Photos", "Videos")
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mpeg", ".wmv", ".ipvf", ".ipv"}
CACHE_VERSION = 2


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
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Could not find the iPod: " + result.stderr.strip())
    items = json.loads(result.stdout.lstrip("\ufeff") or "[]")
    return [inspect_target(item["number"], item["serial"], item["volume"], item["drive"]) for item in items]


def target_args(identity):
    return dict(disk_number=identity["disk_number"], expected_disk_serial=identity["disk_serial"],
                expected_volume_serial=identity["volume_serial"], expected_drive=identity["drive"])


def refresh(identity):
    current = inspect_target(**target_args(identity))
    _same_target(identity, current)
    return current


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


def scan(root, kinds=KINDS):
    root = Path(root).resolve(strict=True)
    result = {}
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        folder = root / kind
        records = _file_records(folder)
        files = [path for path, info in records]
        supported = [p for p in files if p.suffix.lower() in extensions(kind)]
        rows = []
        supported_bytes = 0
        allowed = extensions(kind)
        for path, info in records:
            rows.append((path.relative_to(folder).as_posix(), info.st_size, info.st_mtime_ns))
            if path.suffix.lower() in allowed:
                supported_bytes += info.st_size
        result[kind] = dict(count=len(supported), bytes=supported_bytes,
                            ignored=len(files)-len(supported), files=[str(p) for p in supported],
                            fingerprint=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
    return result


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
        if relative.is_absolute() or relative.drive or ".." in relative.parts or not relative.parts or relative.parts[0] != "LINNET":
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


def video_jobs(root, pending=(), selection=None):
    """Resolve explicit iPod selections and host additions without copying originals."""
    root = Path(root).resolve(strict=True)
    folder = root / "Videos"
    chosen = scan(root, ("Videos",))["Videos"]["files"] if selection is None else selection
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
        include(source, source.relative_to(folder).as_posix())
    for kind, name in pending:
        if kind != "Videos":
            continue
        source = Path(name).absolute()
        _plain(source, Path(source.anchor))
        source = source.resolve(strict=True)
        if source.is_relative_to(root):
            raise ValueError("Use Choose iPod videos for files already on this iPod.")
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


def run(identity, selected, pending=(), **options):
    from .publish_photos import _exclusive
    # The same Windows mutex is recursive for nested publishers on this thread.
    # A second manager must not overwrite the first manager's cache or catalog.
    identity = refresh(identity)
    with _exclusive(identity):
        return _run(identity, selected, pending, **options)


def _run(identity, selected, pending=(), *, progress=lambda message: None, cancelled=lambda: False,
        photo_dimension=640, ffmpeg=None, ffprobe=None, force=False, music_verification="metadata",
        video_selection=None, progress_detail=None):
    """Copy additions, prepare and publish selected folders; retain per-step receipts.

    Stop requests are honored between files and between compiler/publication calls.
    Failed publication is never retried automatically.
    """
    selected = tuple(kind for kind in KINDS if kind in selected)
    if not selected:
        raise ValueError("Select at least one media folder to prepare.")
    identity = refresh(identity)
    if music_verification not in ("metadata", "full"):
        raise ValueError("Music verification must be metadata or full")
    root = Path(identity["root"])
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
        videos = video_jobs(root, pending, video_selection) if "Videos" in selected else []
        plan = additions(root, [item for item in pending if item[0] in selected and item[0] != "Videos"])
        for kind, maximum in (("Notes", 256),):
            if kind in selected:
                existing = scan(root, (kind,))[kind]["count"]
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
        progress("Scanning the iPod folders…")
        inventory = scan(root, selected)
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
            option = photo_dimension if kind == "Photos" else f"{music_verification}-duration-v2-search-names-album-owner" if kind == "Music" else "default"
            signature = (f"ipvf-24-realtime:{item['fingerprint']}" if kind == "Videos"
                         else f"{CACHE_VERSION}:{option}:{item['fingerprint']}")
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
                        if now - last_progress[0] >= 0.2 or event['current'] + 1 == event['total'] or event.get("phase") == "compatibility-copy":
                            action = "Preparing compatible copy" if event.get("phase") == "compatibility-copy" else "Using saved metadata" if event.get("cached") else "Reading metadata"
                            progress(f"{action} {event['current']+1}/{event['total']}: {Path(event['file']).name}")
                            last_progress[0] = now
                    preparation = compile_music(folder, stage, ffprobe=ffprobe or shutil.which("ffprobe"), device_root=root,
                                  verification=music_verification, cache_path=cache / "music-metadata.sqlite3",
                                  bypass_cache=force, progress=music_progress)
                    compatibility = preparation.get("compatibility_copies", [])
                    report["steps"].append(dict(kind=kind, metadata=preparation.get("cache"), integrity=music_verification,
                                               compatibility_copies=compatibility))
                    if compatibility:
                        progress(f"Music: {len(compatibility)} track(s) need compatible playback copies; originals stay in place.")
                    checkpoint()
                    progress("Publishing the music index and artwork…")
                    published.append(publish_music(stage, progress=progress, **target_args(identity)))
                    output_paths = ["LINNET/LIBRARY.PDB"] + [entry["path"].lstrip("/") for entry in preparation["entries"] if entry["storage"] == "staged"] + [
                        "LINNET/ART/" + path.name for path in sorted((stage / "ART").glob("*.RGB"))]
                elif kind == "Photos":
                    from .photos import compile_photos
                    from .publish_photos import publish_photos
                    package = cache / "photos.pimg"
                    compile_photos(folder, package, max_dimension=photo_dimension)
                    checkpoint()
                    progress("Publishing prepared photos…")
                    published.append(publish_photos(package, **target_args(identity)))
                    output_paths = ["LINNET/PHOTOS/LIBRARY.PIM"]
                elif kind == "Notes":
                    from .notes import compile_notes
                    from .publish_notes import publish_notes
                    package = cache / "notes.pnot"
                    preparation = compile_notes(folder, package)
                    report["steps"].append(dict(kind=kind, preparation=preparation))
                    if preparation.get("ascii_converted"):
                        progress("Notes: non-ASCII text was adapted for the iPod font; originals are unchanged. See the report.")
                    checkpoint()
                    progress("Publishing prepared notes…")
                    published.append(publish_notes(package, **target_args(identity)))
                    output_paths = ["LINNET/NOTES/LIBRARY.NNT"]
                else:
                    from .ipvf_encode import encode_ipvf
                    from .ipvf_validate import inspect_file
                    from .publish_video import publish_video
                    from .video_sources import video_title, catalog_contains
                    output_paths = ["LINNET/VIDEOS/INDEX.VID"]
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
                            fingerprint = hashlib.sha256(f"ipvf-24-realtime:{source}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
                            label = video_title(relative)
                            cached = video_state.get(relative, {})
                            if not isinstance(cached, dict):
                                cached = {}
                            output_name = "LINNET/VIDEOS/" + key + ".IPV"
                            native_ipvf = source.suffix.lower() in {".ipvf", ".ipv"}
                            index_in_place = native_ipvf and source.is_relative_to(root)
                            if (not force and cached.get("signature") == fingerprint
                                    and catalog_contains(root, relative, label, path=False if index_in_place else "/" + output_name)
                                    and (index_in_place or _outputs_match(root, cached.get("outputs", [])))):
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
                                    inspect_file(package)
                                except (OSError, ValueError):
                                    reusable = False
                            if not reusable:
                                if native_ipvf:
                                    inspect_file(source)
                                    package.parent.mkdir(parents=True, exist_ok=True)
                                    temporary = package.with_name(package.name + "." + uuid.uuid4().hex + ".tmp")
                                    with source.open("rb") as reader, temporary.open("xb") as writer:
                                        owned_temporaries.append((temporary, cache))
                                        while chunk := reader.read(1024 * 1024):
                                            checkpoint()
                                            writer.write(chunk)
                                        writer.flush()
                                        os.fsync(writer.fileno())
                                    inspect_file(temporary)
                                    os.replace(temporary, package)
                                else:
                                    encode_ipvf(source, package, title=label,
                                                ffmpeg=ffmpeg or shutil.which("ffmpeg"),
                                                ffprobe=ffprobe or shutil.which("ffprobe"),
                                                progress=progress, cancelled=cancelled,
                                                progress_detail=(lambda event: progress_detail(dict(event,
                                                    video_index=index+1, video_total=item['count']))) if progress_detail else None)
                            checkpoint()
                            after = source.stat()
                            if (after.st_size, after.st_mtime_ns) != source_stamp:
                                raise ValueError("Video changed during preparation; scan again before updating")
                            progress(f"Publishing video {index+1}/{item['count']}: {relative}")
                            result = publish_video(package, title=label, library_key=relative, **target_args(identity))
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
                            report["errors"].append(dict(kind=kind, file=relative, message=str(error)))
                            progress(f"Video could not finish, continuing with the next file: {relative}: {error}")
                            record()
                    if failed:
                        progress(f"Videos: {failed} file(s) need attention; completed videos are saved.")
                        continue
                checkpoint()
                # Do not mark a changed source tree up to date.
                current = _video_inventory(videos) if kind == "Videos" else scan(root, (kind,))[kind]
                if current["fingerprint"] != item["fingerprint"]:
                    raise ValueError(f"{kind} changed during processing. Scan again before updating.")
                outputs = [(name, _hash(root / name)) for name in output_paths]
                state[kind] = dict(signature=signature, outputs=outputs)
                _save(state_path, state)
                report["steps"].append(dict(kind=kind, status="published", publications=published))
                progress(f"{kind}: published and verified on your iPod ({root / 'LINNET'}).")
                record()
            except Cancelled:
                raise
            except Exception as error:
                report["errors"].append(dict(kind=kind, message=str(error)))
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
