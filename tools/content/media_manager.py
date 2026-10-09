"""Desktop media workflow. Originals live in the user's four iPod folders.

Preparation is cached on the host; publication uses the existing guarded writers.
No device is modified by discovery or scanning.
"""
from __future__ import annotations

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid

from .guard import guarded_path as _plain, hash_file as _hash, require_same_target as _same_target, guard_volume as _volume_guard, inspect_target
from .host_state import cache_directory as _cache_directory, cache_root, cache_volume_scope, file_stamp as _receipt_stamp, load_json_object as _optional_state, save_json as _save
from .inventory import KINDS, VIDEO_EXTENSIONS, extensions, source_folders, file_records as _file_records, skipped_paths as _skipped_paths, scan

_RETAIL_ADOPTION = None
_RECENT_OUTPUT_NS = 5_000_000_000


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
foreach ($disk in @(Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_Disk -Filter 'BusType=7' | Where-Object {$_.FriendlyName -in $names})) {
 try {$partitions=@(Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_Partition -Filter ('DiskNumber='+$disk.Number) | Where-Object {$_.DriveLetter})}
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
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as pool:
        pending = []
        for item in items:
            try:
                args = dict(disk_number=item["number"], expected_disk_serial=item["serial"],
                            expected_volume_serial=item["volume"], expected_drive=item["drive"])
                pending.append((item, pool.submit(_inspect_identify, args, Path(item["drive"] + "\\"))))
            except Exception as error:
                if len(errors) < 16:
                    drive = item.get('drive', '?') if isinstance(item, dict) else '?'
                    errors.append(f"{drive}: {(str(error) or type(error).__name__)[:240]}")
        for item, future in pending:
            try:
                devices.append(future.result())
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
    from tools.inspect.retail_device import detect, _sysinfo
    from tools.studio.targets import TARGETS, media_profile
    if detected is None:
        detected = detect(identity["root"])
    storage = detected["storage"]
    if (detected["device_id"] != identity["disk_serial"] or
            storage["disk_number"] != identity["disk_number"] or
            storage["disk_bytes"] != identity["disk_bytes"] or
            storage["partition_offset"] != identity["partition_offset"] or
            storage["partition_bytes"] != identity["partition_bytes"] or
            storage["sector_bytes"] != identity["sector_bytes"] or
            storage["filesystem"] != identity["filesystem"] or
            storage["pnp_id"] != identity["pnp_id"] or
            storage["volume_id"].casefold() != identity["volume_unique_id"].casefold()):
        raise RuntimeError("USB and mounted storage identities disagree")
    native_target = identity.get("native_target_id")
    if (bool(native_target) != (detected.get("identity_source") == "linnet-usb") or
            native_target and (native_target != detected["target_id"] or
                               storage["usb_pnp_id"] != identity["usb_pnp_id"])):
        raise RuntimeError("USB and mounted storage target identities disagree")
    spec = TARGETS[detected["target_id"]]
    retail = dict(detected["retail_os"])
    if identity.get("native_target_id"):
        # Native USB identifies the running board. Retained Apple SysInfo is
        # optional display metadata and never decides the target identity.
        try:
            root = Path(identity["root"])
            _plain(root / "iPod_Control" / "Device" / "SysInfo", root)
            saved = _sysinfo(root)
            for key, field in (("ModelNumStr", "model_number"), ("BoardHwName", "board"),
                               ("visibleBuildID", "build"), ("iPodFamily", "family"),
                               ("RegionCode", "region")):
                retail[field] = retail.get(field) or saved.get(key)
        except (OSError, ValueError, UnicodeError):
            pass
    model_number = retail.get("model_number")
    regulatory_models = spec["retail"]["regulatory_models"]
    regulatory_model = spec["retail"].get("regulatory_model_by_model", {}).get(model_number)
    if regulatory_model is None and len(regulatory_models) == 1:
        regulatory_model = regulatory_models[0]
    result = dict(identity, target_id=detected["target_id"], target_name=spec["name"],
                volume_label=storage.get("volume_label") or "",
                linnet_usb_serial=detected["linnet_usb_serial"],
                model_number=model_number,
                regulatory_model=regulatory_model,
                board_name=retail.get("board"),
                apple_build=retail.get("build"),
                ipod_family=retail.get("family"),
                region_code=retail.get("region"),
                usb_storage_model=storage.get("model"),
                usb_vid_pid=(f"{detected['native_usb']['vid']:04X}:{detected['native_usb']['pid']:04X}"
                             if "native_usb" in detected else
                             f"{detected['retail_usb']['vid']:04X}:{detected['retail_usb']['pid']:04X}"),
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
        art_version = ('art-native130-playback160-exact-np-bridge1' if target.get('presentation_profile') == 'color320' else
                       'art9' if target['media_art_side'] == 128 else
                       'art8' if target['lcd_format'] == 'gray2-horizontal' else 'art7')
        return f"{music_verification}-aac-seek1-duration-search-prefix2-browse-id-names-album-owner2-title-order1-retail2-recent-album-gain-icc-srgb1-audio-compat1-{art_version}-{identity['target_id']}"
    if kind == 'Notes':
        from .notes import _display_recipe
        return f"target-wrap2-{_display_recipe(identity['target_id'])[2]}"
    if kind == 'Photos':
        profile = identity['media_profile']
        layout = '-pack32-sequential8' if identity['target_id'] in ('video5g-m25', 'classic6g-n25') else ''
        return f"lpic-hc-photos-native-grid{layout}-jpeg-fallback2-{identity['target_id']}-{photo_dimension}-{profile['photo_width']}x{profile['photo_height']}"
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


def _music_import_name(name, preserved_suffix=None):
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
        suffix = preserved_suffix or Path(result).suffix
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
        with os.scandir(folder) as iterator:
            entries = sorted(((folder / entry.name, entry) for entry in iterator),
                             key=lambda item: item[0])
        for path, entry in entries:
            checkpoint()
            # The parent was checked above. DirEntry keeps the leaf's file
            # attributes from enumeration, including Windows junctions.
            info = entry.stat(follow_symlinks=False)
            if (stat.S_ISLNK(info.st_mode) or
                    getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError(f"reparse/symlink path rejected: {path}")
            directory = entry.is_dir(follow_symlinks=False)
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


def _same_file_bytes(left, right, size, digest=None, stable_right=None, *, checkpoint=lambda: None):
    checkpoint()
    paths = (left, right)
    before = [path.stat() for path in paths]
    if any(not stat.S_ISREG(info.st_mode) or info.st_size != size for info in before):
        raise ValueError('file changed while comparing existing media')
    equal = True
    with left.open('rb') as source, right.open('rb') as destination:
        remaining, chunk_size = size, 16 * 1024
        while remaining:
            checkpoint()
            count = min(remaining, chunk_size)
            a, b = source.read(count), destination.read(count)
            if len(a) != count or len(b) != count:
                raise ValueError('file changed while comparing existing media')
            if a != b:
                equal = False
                break
            if digest is not None:
                digest.update(a)
            remaining -= count
            chunk_size = 1024 * 1024
        if equal and (source.read(1) or destination.read(1)):
            raise ValueError('file changed while comparing existing media')
    checkpoint()
    after = [path.stat() for path in paths]
    if any((a.st_size, a.st_mtime_ns, a.st_ctime_ns, a.st_ino) !=
           (b.st_size, b.st_mtime_ns, b.st_ctime_ns, b.st_ino)
           for a, b in zip(before, after)):
        raise ValueError('file changed while comparing existing media')
    if stable_right is not None:
        stable_right.append(after[1])
    return equal


def _same_existing_file(source, destination, size, root, verified, known, info, *, checkpoint=lambda: None):
    checkpoint()
    relative = destination.relative_to(root).as_posix()
    stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
    recent = os.name == 'nt' and info.st_mtime_ns > time.time_ns() - _RECENT_OUTPUT_NS
    if not recent and stamp in known.get(relative, {}):
        before = source.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size != size:
            raise ValueError('file changed while comparing existing media')
        digest = _hash(source, progress=lambda _current, _total: checkpoint())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
            raise ValueError('file changed while comparing existing media')
        current = destination.stat()
        if stamp != (current.st_size, current.st_mtime_ns, current.st_ctime_ns, current.st_ino):
            raise ValueError('file changed while comparing existing media')
        valid = {value for value in known[relative][stamp]
                 if verified.get((relative, value)) == stamp}
        if valid:
            return digest in valid
    digest, stable_right = hashlib.sha256(), []
    same = _same_file_bytes(source, destination, size, digest, stable_right, checkpoint=checkpoint)
    current = stable_right[0]
    if same and not recent and stamp == (
            current.st_size, current.st_mtime_ns, current.st_ctime_ns, current.st_ino):
        value = digest.hexdigest()
        verified[(relative, value)] = stamp
        known.setdefault(relative, {}).setdefault(stamp, set()).add(value)
    return same


def additions(root, pending, *, snapshots=None, verify_existing=True, unverified=None,
              replacements=None, convert_audio=False, target=None, ffprobe=None,
              cancelled=lambda: False, reused_audio=None, verified=None):
    """Resolve selected files/folders to concrete destinations without writing."""
    root = Path(root).resolve(strict=True)
    planned = {}
    known = {}

    def check():
        if cancelled():
            raise Cancelled('Stopped while checking queued media.')

    if verified is not None:
        for (relative, digest), stamp in verified.items():
            if isinstance(relative, str) and isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest):
                known.setdefault(relative, {}).setdefault(stamp, set()).add(digest)
    for kind, selected in pending:
        if kind not in KINDS:
            raise ValueError("Unknown media folder")
        source = Path(selected).absolute()
        _plain(source, Path(source.anchor))
        source = source.resolve(strict=True)
        on_device = source.is_relative_to(root)
        music_source = next((folder for folder in (root / 'Music', root / 'iPod_Control' / 'Music')
                             if source.is_relative_to(folder)), None)
        if on_device and not (kind == 'Music' and convert_audio and source.is_file() and
                              music_source is not None and not source.name.casefold().endswith('.linnet.wav')):
            raise ValueError(f"{source.name} is already on this iPod. Use its existing {kind} folder.")
        is_folder = source.is_dir()
        records = _planning_records(source, snapshots)
        for path, info in records:
            check()
            # Preserve supporting files (cover art, playlists) inside selected folders.
            if not is_folder and path.suffix.lower() not in extensions(kind):
                raise ValueError(f"{path.name} is not a supported {kind.lower()} source.")
            if info.st_size > 0xFFFFFFFF:
                raise ValueError(f"{path.name} exceeds the iPod's FAT32 file size limit (4 GiB minus 1 byte).")
            relative = (path.relative_to(music_source) if on_device else
                        Path(source.name) / path.relative_to(source) if is_folder else Path(source.name))
            if kind == "Music":
                relative = Path(*(_music_import_name(part) for part in relative.parts))
            converted_bytes = None
            converted_frames = None
            issue = None
            if target and kind == 'Music' and path.suffix.lower() in extensions('Music'):
                from .music import CODECS, _decoded_frames, _pcm, _quick_metadata, _probe, _read_metadata, compatibility_issue
                try:
                    if path.suffix.lower() in ('.wav', '.aif', '.aiff', '.aifc'):
                        try:
                            metadata = _pcm(path, cancelled)
                        except (ValueError, struct.error):
                            if not ffprobe:
                                raise
                            metadata = _probe(path, ffprobe, exact_frames=False,
                                              cancelled=cancelled, allow_unknown=True)
                    else:
                        metadata = _quick_metadata(path, cancelled, allow_unknown=True)
                    if metadata is None:
                        if not ffprobe:
                            raise ValueError('FFprobe is needed to check this audio file')
                        metadata = _probe(path, ffprobe, exact_frames=False,
                                          cancelled=cancelled, allow_unknown=True)
                    issue = compatibility_issue(metadata, target)
                    if (issue or on_device) and convert_audio:
                        if metadata['codec'] == CODECS['unknown']:
                            if not ffprobe:
                                raise ValueError('FFprobe is needed to size audio conversion')
                            metadata = _probe(path, ffprobe, exact_frames=True, cancelled=cancelled,
                                              allow_unknown=True)
                            issue = compatibility_issue(metadata, target)
                        elif metadata['codec'] == CODECS['mp3']:
                            if not ffprobe:
                                raise ValueError('FFprobe is needed to size MP3 conversion')
                            metadata['frames'] = _decoded_frames(path, ffprobe, codec=metadata['codec'],
                                                                  cancelled=cancelled)
                        elif not metadata['frames']:
                            metadata = _read_metadata(path, ffprobe, True, cancelled)
                except (OSError, ValueError, struct.error, subprocess.SubprocessError) as error:
                    metadata = None
                    issue = f'Cannot inspect audio: {error}'
                if (issue or on_device) and convert_audio and metadata is not None:
                    relative = (relative.with_name(_music_import_name(
                        relative.name + '.linnet.wav', preserved_suffix='.linnet.wav'))
                                if on_device else relative.with_suffix('.wav'))
                    converted_frames = math.ceil(metadata['frames'] * 44100 / metadata['rate'])
                    converted_bytes = (math.ceil(converted_frames * 4 * 1.1)
                                       + min(info.st_size, 32 * 1024 * 1024) + 4096)
                    if converted_bytes > 0xffffffff:
                        raise ValueError(f'{path.name} would exceed the iPod file limit after PCM conversion.')
                after = path.stat()
                if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                    raise ValueError(f'Source changed during audio planning: {path}')
            if on_device and converted_bytes is None:
                if issue:
                    from . import SourceError
                    raise SourceError(f'{path}: {issue}', path)
                continue
            destination = root / kind / relative
            _plain(destination, root)
            key = str(destination).casefold()
            if key in planned and planned[key]["source"] != str(path):
                raise ValueError(f"Two selected files have the same destination: {destination}")
            if destination.exists():
                if not destination.is_file():
                    raise ValueError(f"A different file already exists: {destination}. Rename the new file or folder first.")
                if converted_bytes is not None:
                    from .music import CODECS, _pcm, compatibility_issue
                    try:
                        prepared = _pcm(destination)
                        if (prepared['container'] == 'wav' and prepared['codec'] == CODECS['pcm_le'] and
                                prepared['bits'] == 16 and prepared['channels'] == 2 and
                                prepared['rate'] == 44100 and not compatibility_issue(prepared, target) and
                                prepared['frames'] >= converted_frames - max(2205, converted_frames // 100) and
                                _verified_audio_hash(path, root, prepared['tags'].get('source_sha256'), verified, checkpoint=check) and
                                _verified_audio_hash(destination, root, prepared['tags'].get('pcm_sha256'),
                                                     verified, prepared, checkpoint=check)):
                            if on_device and reused_audio is not None:
                                reused_audio.append((path, destination))
                            continue
                    except (OSError, ValueError, KeyError, struct.error):
                        pass
                old = destination.stat()
                different = converted_bytes is not None
                if not different and not verify_existing:
                    # Planning only estimates work. The preparation call checks
                    # the complete original before it copies or publishes.
                    if old.st_size != info.st_size and not (
                            kind == 'Music' and path.suffix.lower() in ('.m4a', '.m4b', '.flac', '.flc', '.mp3')):
                        different = True
                    elif unverified is not None:
                        unverified.append(kind)
                elif not different and (old.st_size != info.st_size or not (
                        _same_existing_file(path, destination, info.st_size, root, verified, known, old, checkpoint=check)
                        if verified is not None else _same_file_bytes(path, destination, info.st_size, checkpoint=check))):
                    equivalent = False
                    if kind == 'Music' and path.suffix.lower() in ('.m4a', '.m4b'):
                        from .aac_index import same_original
                        equivalent = same_original(path, destination, checkpoint=check)
                    elif kind == 'Music' and path.suffix.lower() in ('.flac', '.flc'):
                        from .flac_index import same_original
                        equivalent = same_original(path, destination, checkpoint=check)
                    elif kind == 'Music' and path.suffix.lower() == '.mp3':
                        from .mp3_index import same_original
                        equivalent = same_original(path, destination, checkpoint=check)
                    different = not equivalent
                if not different:
                    continue
                if replacements is None:
                    raise ValueError(f"A different file already exists: {destination}. Review its replacement before preparing.")
                replacements.append(dict(action='replace', kind=kind, source=str(path),
                    destination=str(destination), old_bytes=old.st_size,
                    old_mtime_ns=old.st_mtime_ns, new_bytes=info.st_size,
                    new_mtime_ns=info.st_mtime_ns,
                    old_sha256=_hash(destination, progress=lambda _current, _total: check()),
                    new_sha256=_hash(path, progress=lambda _current, _total: check())))
            planned[key] = dict(kind=kind, source=str(path), destination=str(destination),
                                bytes=info.st_size, mtime_ns=info.st_mtime_ns,
                                **({'compatibility_issue': issue} if issue else {}),
                                **({'converted_bytes': converted_bytes, 'converted_frames': converted_frames}
                                   if converted_bytes is not None else {}))
    reserved = {str(value).casefold() for source, destination in (reused_audio or ())
                for value in (source, destination)}
    reserved.update(str(item['source']).casefold() for item in planned.values()
                    if 'converted_bytes' in item and Path(item['source']).is_relative_to(root))
    if reserved.intersection(planned):
        raise ValueError('Queued sources overlap an iPod conversion. Remove one before preparing.')
    return list(planned.values())


def _import_metadata_seed(local, ffprobe, should_stop):
    from .music import _embedded_cover, _quick_metadata, _read_metadata, _probe
    try:
        metadata = _read_metadata(local, ffprobe, True, should_stop, include_cover=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        metadata = _quick_metadata(local, should_stop, include_cover=True, allow_unknown=True)
        if metadata is None and ffprobe:
            try:
                metadata = _probe(local, ffprobe, exact_frames=False, cancelled=should_stop,
                                  allow_unknown=True)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        if metadata is not None and '_embedded_cover' not in metadata:
            metadata['_embedded_cover'] = _embedded_cover(local)
    return (metadata, metadata.pop('_embedded_cover', None)) if metadata else None


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
    metadata_seed = _import_metadata_seed(local, ffprobe, should_stop)
    check()
    return local, suffix, unsupported, metadata_seed, _receipt_stamp(before)


def _prepare_import_mp3(item, scratch, ffprobe, cancelled, stopped):
    def should_stop():
        return stopped.is_set() or cancelled()
    def check():
        if should_stop():
            raise Cancelled('Stopped while preparing MP3 on the computer.')

    source = Path(item['source'])
    _plain(source, Path(source.anchor))
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
        raise ValueError(f"Source changed since selection: {source}")
    local = source
    suffix = b''
    if before.st_size >= 8 * 1024 * 1024:
        local = scratch / 'source.mp3'
        with source.open('rb') as reader, local.open('xb') as frozen:
            while chunk := reader.read(1024 * 1024):
                check()
                frozen.write(chunk)
        if (_receipt_stamp(before) != _receipt_stamp(source.stat()) or
                local.stat().st_size != before.st_size):
            raise ValueError(f"Source changed during preparation: {source}")
        from .mp3_index import import_suffix
        suffix = import_suffix(local, checkpoint=check)
    metadata_seed = _import_metadata_seed(local, ffprobe, should_stop)
    if should_stop():
        raise Cancelled('Stopped while reading MP3 metadata on the computer.')
    if _receipt_stamp(source.stat()) != _receipt_stamp(before):
        raise ValueError(f"Source changed during preparation: {source}")
    return local, suffix, metadata_seed, _receipt_stamp(before)


def _prepare_import_flac(item, scratch, cache, ffprobe, cancelled, stopped):
    from .flac_index import prepare_file, same_original

    def should_stop():
        return stopped.is_set() or cancelled()

    def check():
        if should_stop():
            raise Cancelled('Stopped while preparing FLAC on the computer.')

    source = Path(item['source'])
    _plain(source, Path(source.anchor))
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
        raise ValueError(f"Source changed since selection: {source}")
    local = scratch / 'source.flac'
    with source.open('rb') as reader, local.open('xb') as frozen:
        while chunk := reader.read(1024 * 1024):
            check()
            frozen.write(chunk)
    if (_receipt_stamp(before) != _receipt_stamp(source.stat()) or
            local.stat().st_size != before.st_size):
        raise ValueError(f"Source changed during preparation: {source}")
    outcome = prepare_file(local, cache / 'flac-import', ffprobe=ffprobe, checkpoint=check)
    if outcome and not same_original(source, local, checkpoint=check):
        raise ValueError(f"FLAC preparation changed original audio: {source}")
    metadata_seed = _import_metadata_seed(local, ffprobe, should_stop)
    check()
    if _receipt_stamp(source.stat()) != _receipt_stamp(before):
        raise ValueError(f"Source changed during preparation: {source}")
    return local, metadata_seed, outcome is not None, _receipt_stamp(before)


def _wave_pcm_hash(path, metadata, *, checkpoint=lambda: None):
    digest = hashlib.sha256()
    with path.open('rb') as wave:
        wave.seek(metadata['data_offset'])
        remaining = metadata['data_bytes']
        while remaining:
            checkpoint()
            chunk = wave.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError('Converted WAV data changed while checking it')
            digest.update(chunk)
            remaining -= len(chunk)
    checkpoint()
    return digest.hexdigest()


def _verified_audio_hash(path, root, expected, verified, metadata=None, *, checkpoint=lambda: None):
    checkpoint()
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        return False
    before = path.stat()
    stamp = (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
    recent = os.name == 'nt' and before.st_mtime_ns > time.time_ns() - _RECENT_OUTPUT_NS
    relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else None
    key = (relative, 'pcm:' + expected if metadata else expected) if relative else None
    if key and verified is not None and not recent and verified.get(key) == stamp:
        return True
    actual = (_wave_pcm_hash(path, metadata, checkpoint=checkpoint) if metadata else
              _hash(path, progress=lambda _current, _total: checkpoint()))
    after = path.stat()
    if stamp != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
        raise ValueError(f'Audio changed during verification: {path}')
    if actual == expected and key and verified is not None and not recent:
        verified[key] = stamp
    return actual == expected


def _wave_metadata(output, tags):
    fields = {'title': b'INAM', 'artist': b'IART', 'album': b'IPRD', 'genre': b'IGNR',
              'date': b'ICRD', 'track': b'ITRK', 'album_artist': b'IAMP',
              'composer': b'ICMP', 'disc': b'IDIS', 'replaygain_track_gain': b'IGAN',
              'replaygain_album_gain': b'IGAL', 'compilation': b'ICPL',
              'source_sha256': b'IHS1', 'pcm_sha256': b'IHC1'}
    body = bytearray(b'INFO')
    for key, atom in fields.items():
        text = tags.get(key) or (tags.get('albumartist') if key == 'album_artist' else '')
        value = str(text or '').encode('utf-8')[:1024]
        if value:
            value += b'\0'
            body += atom + struct.pack('<I', len(value)) + value + (b'\0' if len(value) & 1 else b'')
    if len(body) == 4:
        return
    chunk = b'LIST' + struct.pack('<I', len(body)) + body + (b'\0' if len(body) & 1 else b'')
    with output.open('r+b') as wave:
        if wave.read(4) != b'RIFF':
            raise ValueError('Audio conversion did not produce standard RIFF WAV')
        wave.seek(0, os.SEEK_END)
        size = wave.tell() + len(chunk)
        if size > 0xffffffff + 8:
            raise ValueError('Converted WAV exceeds the iPod file limit')
        wave.write(chunk)
        wave.seek(4)
        wave.write(struct.pack('<I', size - 8))


def _convert_audio(source, output, ffmpeg, checkpoint, max_bytes, expected_frames,
                   tags=None, cover=None, source_sha256=None):
    if not ffmpeg:
        raise ValueError('Audio conversion needs FFmpeg on the computer.')
    if shutil.disk_usage(output.parent).free < max_bytes + 1024 * 1024:
        raise ValueError('Not enough computer space for audio conversion.')
    command = [str(ffmpeg), '-nostdin', '-v', 'error', '-i', str(source), '-map', '0:a:0',
               '-vn', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', '-map_metadata', '0',
               '-fs', str(max_bytes), '-f', 'wav', str(output)]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errors,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            while process.poll() is None:
                checkpoint()
                if output.exists() and output.stat().st_size >= max_bytes:
                    raise ValueError('Audio conversion exceeded its planned size.')
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
        if process.returncode:
            errors.seek(0)
            raise ValueError(f'Audio conversion failed: {errors.read(1000).decode("utf-8", "replace")}')
    if output.stat().st_size >= max_bytes * 0.95:
        raise ValueError('Audio conversion reached its size limit; source duration may be incorrect.')
    from .music import _pcm, compatibility_issue
    metadata = _pcm(output)
    if metadata['frames'] < expected_frames - max(2205, expected_frames // 100):
        raise ValueError('Audio conversion ended before the source duration.')
    _wave_metadata(output, {**(tags or {}), 'source_sha256': source_sha256 or _hash(source),
                            'pcm_sha256': _wave_pcm_hash(output, metadata)})
    if cover:
        from mutagen.id3 import APIC
        from mutagen.wave import WAVE
        wave = WAVE(output)
        if wave.tags is None:
            wave.add_tags()
        mime = 'image/png' if cover.startswith(b'\x89PNG') else 'image/jpeg'
        wave.tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=cover))
        wave.save()
    metadata = _pcm(output)
    if compatibility_issue(metadata):
        raise ValueError(f'Audio conversion produced an unsupported WAV: {source}')
    return metadata


def _copy_additions(plan, root, report, owned_temporaries, checkpoint, record, progress,
                    *, cache, cancelled, ffmpeg=None, ffprobe=None,
                    stage_progress=lambda current, total, phase: None,
                    completed_batch=lambda items: None):
    # Queue a bounded set of writes before flushing and reading them back. On
    # FAT devices, alternating write/flush/read/rename for every small file is
    # expensive. Keep every handle until its flush, and publish only verified files.
    start = 0
    remaining_original = sum(item.get('converted_bytes', item['bytes']) for item in plan)
    seek_state_path = cache / 'seek-checked.json'
    seek_state = (_optional_state(seek_state_path) if any(
        item['kind'] == 'Music' and Path(item['destination']).suffix.lower() in ('.m4a', '.m4b', '.flac', '.flc')
        for item in plan) else {})
    device_keys = {str(Path(item['source'])).casefold() for item in plan if 'converted_bytes' in item and
                   Path(item['source']).is_relative_to(root)}
    retail_rows, retail_artwork = {}, None
    if device_keys:
        from .retail_media import available_tracks
        tracks = available_tracks(root)
        retail_rows = {key: tracks[key] for key in device_keys if key in tracks}
    while start < len(plan):
        batch = []
        batch_bytes = 0
        seek_state_changed = False
        for item in plan[start:start + 16]:
            if batch and batch_bytes + item.get('converted_bytes', item['bytes']) > 64 * 1024 * 1024:
                break
            destination = Path(item['destination'])
            temporary = destination.parent / ('L' + uuid.uuid4().hex[:7] + '.TMP')
            batch.append((item, temporary))
            batch_bytes += item.get('converted_bytes', item['bytes'])
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
            flac_positions = [offset for offset, (item, _) in enumerate(batch)
                              if item['kind'] == 'Music' and
                              Path(item['destination']).suffix.lower() in ('.flac', '.flc')]
            preparation_positions = sorted((*aac_positions, *mp3_positions, *flac_positions))
            scratches = {offset: Path(handles.enter_context(tempfile.TemporaryDirectory(
                prefix='audio-source-', dir=cache))) for offset in preparation_positions}
            stopped = threading.Event()
            if aac_positions:
                from .aac_index import executable
                executable()
            if mp3_positions and any(batch[offset][0]['bytes'] >= 8 * 1024 * 1024 for offset in mp3_positions):
                from .mp3_index import executable
                executable()
            executor = handles.enter_context(ThreadPoolExecutor(max_workers=2)) if preparation_positions else None
            if executor is not None:
                handles.callback(stopped.set)
            upcoming = iter(preparation_positions)
            futures = {}
            seek_probe = (ffprobe or shutil.which('ffprobe')) if preparation_positions else None
            def fill_preparation():
                while executor is not None and len(futures) < 2:
                    offset = next(upcoming, None)
                    if offset is None:
                        break
                    if offset in aac_positions:
                        futures[offset] = executor.submit(_prepare_import_aac, batch[offset][0],
                            scratches[offset], cache, seek_probe, cancelled, stopped)
                    elif offset in flac_positions:
                        futures[offset] = executor.submit(_prepare_import_flac, batch[offset][0],
                            scratches[offset], cache, seek_probe, cancelled, stopped)
                    else:
                        futures[offset] = executor.submit(_prepare_import_mp3, batch[offset][0],
                            scratches[offset], seek_probe, cancelled, stopped)
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
                    flac_seek_checked = False
                    copy_source = source
                    if offset in futures:
                        prepared = futures.pop(offset).result()
                        fill_preparation()
                        if offset in aac_positions:
                            copy_source, suffix, unsupported_aac, metadata_seed, source_stamp = prepared
                        elif offset in flac_positions:
                            copy_source, metadata_seed, flac_seek_checked, source_stamp = prepared
                        else:
                            copy_source, suffix, metadata_seed, source_stamp = prepared
                        if _receipt_stamp(info) != source_stamp:
                            raise ValueError(f"Source changed during preparation: {source}")
                        checkpoint()
                    if 'converted_bytes' in item:
                        scratch = Path(handles.enter_context(tempfile.TemporaryDirectory(prefix='audio-convert-', dir=cache)))
                        copy_source = scratch / 'audio.wav'
                        progress(f'Converting on computer: {source.name}')
                        seed = _import_metadata_seed(source, ffprobe, cancelled)
                        saved = retail_rows.get(str(source).casefold())
                        if saved:
                            metadata, cover = seed or ({'tags': {}}, None)
                            metadata['tags'] = {**{key: str(value) for key, value in saved.items()
                                                   if key in ('title', 'artist', 'album', 'album_artist',
                                                              'genre', 'composer', 'date', 'year', 'track',
                                                              'disc', 'compilation') and value},
                                                **{key: value for key, value in metadata['tags'].items() if value}}
                            if cover is None:
                                if retail_artwork is None:
                                    from .retail_media import metadata as retail_metadata
                                    retail_artwork = retail_metadata(root, tracks_rows=retail_rows)
                                artwork = retail_artwork.get(str(source).casefold(), {}).get('artwork')
                                if artwork:
                                    art_path = Path(artwork)
                                    if art_path.is_file() and 0 < art_path.stat().st_size <= 32 * 1024 * 1024:
                                        cover = art_path.read_bytes()
                            seed = metadata, cover
                        conversion_source, source_sha256 = source, None
                        if source.is_relative_to(root):
                            conversion_source = scratch / ('source' + source.suffix)
                            digest = hashlib.sha256()
                            with source.open('rb') as reader, conversion_source.open('xb') as frozen:
                                while chunk := reader.read(1024 * 1024):
                                    checkpoint()
                                    frozen.write(chunk)
                                    digest.update(chunk)
                            if (conversion_source.stat().st_size != info.st_size or
                                    _receipt_stamp(source.stat()) != _receipt_stamp(info)):
                                raise ValueError(f'Source changed during conversion: {source}')
                            source_sha256 = digest.hexdigest()
                        converted = _convert_audio(conversion_source, copy_source, ffmpeg, checkpoint,
                                                   item['converted_bytes'], item['converted_frames'],
                                                   seed[0]['tags'] if seed else None,
                                                   seed[1] if seed else None, source_sha256)
                        if conversion_source != source:
                            conversion_source.unlink()
                        if copy_source.stat().st_size > 0xffffffff:
                            raise ValueError(f'Converted audio exceeds the iPod file limit: {source}')
                        converted['tags'] = {**converted['tags'], **(seed[0]['tags'] if seed else {})}
                        metadata_seed = (converted, seed[1] if seed else None)
                        if _receipt_stamp(source.stat()) != _receipt_stamp(info):
                            raise ValueError(f'Source changed during conversion: {source}')
                    target_bytes = copy_source.stat().st_size + len(suffix or b'')
                    if shutil.disk_usage(root).free < remaining_original - item.get('converted_bytes', item['bytes']) + target_bytes + 1024 * 1024:
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
                                   copy_source.stat().st_size + len(suffix or b''), unsupported_aac,
                                   metadata_seed, flac_seek_checked))
                    remaining_original -= item.get('converted_bytes', item['bytes'])
            except BaseException:
                stopped.set()
                for future in futures.values():
                    future.cancel()
                raise
            progress(f"Saving additions {start + 1}–{start + len(batch)}/{len(plan)}…")
            for _, _, writer, _, _, _, _, _ in copied:
                checkpoint()
                os.fsync(writer.fileno())
        verified_stamps = {}
        for offset, (item, temporary, _, digest, prepared_bytes, _, _, flac_seek_checked) in enumerate(copied):
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
            if prepared_bytes != item['bytes'] and not flac_seek_checked and 'converted_bytes' not in item:
                if destination.suffix.lower() == '.mp3':
                    from .mp3_index import original_size
                    valid = original_size(temporary, prepared_bytes, checkpoint=checkpoint) == item['bytes']
                else:
                    from .aac_index import original_size
                    valid = original_size(temporary, prepared_bytes, checkpoint=checkpoint) == item['bytes']
                if not valid:
                    raise ValueError(f"Prepared audio seek data is invalid: {destination}")
        for item, temporary, _, digest, prepared_bytes, unsupported_aac, metadata_seed, flac_seek_checked in copied:
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
            elif item['kind'] == 'Music' and 'converted_bytes' in item and metadata_seed is not None:
                music_seeds.append((destination, info, *metadata_seed))
            elif item['kind'] == 'Music' and destination.suffix.lower() in ('.flac', '.flc'):
                if flac_seek_checked:
                    key = destination.relative_to(root).as_posix().casefold()
                    seek_state[key] = [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
                    seek_state_changed = True
                if metadata_seed is not None:
                    music_seeds.append((destination, info, *metadata_seed))
            report['steps'].append(dict(added=str(destination), bytes=prepared_bytes,
                                        **({'converted_from': str(item['source'])} if 'converted_bytes' in item else {})))
            completed_batch([item])
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
                value = dict(metadata, data_bytes=before.st_size if metadata['codec'] >= 16 else metadata['data_bytes'])
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
    from .about import publish as publish_about
    from tools.studio.installer import installed_state
    from tools.link.eject import eject
    with _exclusive(identity):
        current = refresh(identity)
        warning = None
        if installed_state(current['root'], current['target_id'])['state'] == 'installed':
            try:
                publish_about(current, refresh)
            except (OSError, ValueError) as error:
                # Optional About data must not prevent a requested safe eject.
                warning = str(error)
        report = eject(current['disk_number'], current['disk_serial'], wait_link=False)
        report['about_warning'] = warning
        return report


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
    prepass = verified is not None and (len(outputs) >= 64 or progress is None)
    pending = []
    cached_count = 0
    last_cached = None
    last_prepass = time.monotonic()
    for index, item in enumerate(outputs):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return False
        name, digest = item
        if not isinstance(name, str) or not isinstance(digest, str):
            return False
        if prepass and progress and time.monotonic() - last_prepass >= 0.2:
            # A long stat/path pass still needs to service Stop and volume checks.
            progress(dict(current=0, total=len(outputs), file=name,
                          bytes=0, file_bytes=1))
            last_prepass = time.monotonic()
        relative = Path(name)
        if (relative.is_absolute() or relative.drive or ".." in relative.parts or not relative.parts or
                relative.parts[0].casefold() not in {".linnet", "music", "videos", "ipod_control"}):
            return False
        path = root / relative
        try:
            info = _plain(path, root)
            if info is None or not stat.S_ISREG(info.st_mode):
                return False
            stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
            # The cache is already scoped to this disk, volume and partition.
            # A Windows drive-letter change must not discard a recent hash.
            key = (relative.as_posix(), digest)
            # NTFS can report the same timestamps for two immediate writes of
            # equal size. Hash recent files on every check until that window
            # has passed, then reuse the verified stamp on later refreshes.
            recent = os.name == "nt" and info.st_mtime_ns > time.time_ns() - _RECENT_OUTPUT_NS
            def notify(current, total):
                if progress:
                    progress(dict(current=index, total=len(outputs), file=name,
                                  bytes=current, file_bytes=total))
            if verified is not None and not recent and verified.get(key) == stamp:
                if prepass:
                    cached_count += 1
                    last_cached = (name, info.st_size)
                else:
                    notify(info.st_size, info.st_size)
                continue
            if prepass:
                pending.append((path, digest, stamp, key, recent, name))
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
    if progress and cached_count:
        progress(dict(current=cached_count - 1, total=len(outputs),
                      file=last_cached[0], bytes=last_cached[1], file_bytes=last_cached[1]))
    if pending:
        if progress is None:
            pending.sort(key=lambda entry: entry[2][0])
        stop = threading.Event()
        def stop_check(_current, _total):
            if stop.is_set():
                raise Cancelled('Stopped while checking published output.')
        def check(entry):
            path, digest, stamp = entry[:3]
            try:
                # Recheck the path immediately before each concurrent read.
                _plain(path, root)
                if _hash(path, progress=stop_check) != digest:
                    return False
                after = path.stat()
                return stamp == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino)
            except (OSError, ValueError):
                return False
        def report(entry, current, completed):
            if progress:
                size = entry[2][0]
                progress(dict(current=current, total=len(outputs), file=entry[5],
                              bytes=size if completed else 0,
                              file_bytes=size if completed else max(1, size)))

        if len(pending) < 8 or len(outputs) < 64:
            for index, entry in enumerate(pending):
                current = cached_count + index
                try:
                    _plain(entry[0], root)
                    notify = (lambda done, total: progress(dict(
                            current=current, total=len(outputs), file=entry[5],
                            bytes=done, file_bytes=total))) if progress else None
                    if _hash(entry[0], progress=notify) != entry[1]:
                        return False
                    after = entry[0].stat()
                    if entry[2] != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
                        return False
                except (OSError, ValueError):
                    return False
                if not entry[4]:
                    verified[entry[3]] = entry[2]
        else:
            completed = cached_count
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = []
                try:
                    # Bound outstanding reads and keep a corrupt early output cheap.
                    for start in range(0, len(pending), 32):
                        batch = pending[start:start + 32]
                        futures = [pool.submit(check, entry) for entry in batch]
                        for entry, future in zip(batch, futures):
                            while True:
                                try:
                                    matched = future.result(timeout=0.2 if progress else None)
                                    break
                                except FutureTimeout:
                                    if future.done():
                                        future.result()
                                    report(entry, completed, False)
                            if not matched:
                                return False
                            if not entry[4]:
                                verified[entry[3]] = entry[2]
                            report(entry, completed, True)
                            completed += 1
                finally:
                    stop.set()
                    for future in futures:
                        future.cancel()
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
    if (output_paths[:2] != [expected, '.LINNET/PHOTOS/GRID.PGR'] or
            len(published) != 1 or not isinstance(published[0], dict)):
        raise RuntimeError('Photo publication did not return its expected output')
    receipt = published[0]
    outputs, stamps = [], {}
    for name, item in [(expected, receipt), ('.LINNET/PHOTOS/GRID.PGR', receipt.get('grid'))]:
        outputs.append(_photo_output(root, identity, name, item, MAX_FILE))
    packs = receipt.get('packs', [])
    if output_paths[2:] != [item.get('path') for item in packs]:
        raise RuntimeError('Photo pack output list differs from its publication receipt')
    for item in packs:
        path = root/item['path']
        _volume_guard(identity)
        _plain(path, root)
        info = path.stat()
        if (Path(item['package']) != path or not stat.S_ISREG(info.st_mode) or
                tuple(item.get('stamp', ())) != _receipt_stamp(info) or
                info.st_size != item['bytes'] or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise RuntimeError('Photo pack changed after verified publication')
        outputs.append((item['path'], item['sha256']))
        # Reused packs were hashed during publication. A fresh copy still
        # needs a hash after Windows' recent-write window before caching it.
        hash_started_ns = item.get('hash_started_ns')
        if (item.get('reused') is True and type(hash_started_ns) is int and
                (os.name != 'nt' or info.st_mtime_ns <= hash_started_ns - _RECENT_OUTPUT_NS)):
            stamps[(item['path'], item['sha256'])] = (
                info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
    return outputs, stamps


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


def _video_is_native(source, identity, *, ffprobe=None, cancelled=None, details=None):
    """Check the actual container and codecs before treating a suffix as native."""
    if source.suffix.lower() not in native_video_extensions(identity):
        return False
    profile = identity['media_profile']
    try:
        if profile['video_backend'] in ('bcm-mp4', 'native-mp4'):
            from .native_video import inspect_file
            inspected = inspect_file(source, profile=profile, ffprobe=ffprobe, cancelled=cancelled)
            if details is not None:
                details.update(inspected)
        else:
            from .ipvf_validate import inspect_file
            inspect_file(source, expected_width=profile['video_width'],
                         expected_height=profile['video_height'],
                         max_record_sectors=profile['max_read_sectors'])
        return True
    except (OSError, ValueError):
        return False


def _native_check_reusable(job, source, profile):
    proof = job.get('_native_check')
    if (not isinstance(proof, tuple) or len(proof) != 3 or
            not isinstance(proof[2], tuple) or len(proof[2]) != 5 or
            not all(type(value) is int for value in proof[2]) or
            proof[0] != str(source) or proof[1] != json.dumps(profile, sort_keys=True) or
            (os.name == 'nt' and proof[2][3] > time.time_ns() - _RECENT_OUTPUT_NS)):
        return False
    try:
        return (source.resolve(strict=True) == source and
                _receipt_stamp(source.stat()) == proof[2])
    except OSError:
        return False


def _video_duration(source, ffprobe):
    probe = ffprobe or shutil.which('ffprobe')
    if not probe:
        raise ValueError('FFprobe is required to estimate video conversion space.')
    command = [str(probe), '-v', 'error', '-show_entries',
               'stream=duration:format=duration', '-of', 'json', str(source)]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=60, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        data = json.loads(result.stdout[:1024 * 1024])
        from .native_video import _probe_duration
        duration = _probe_duration(data)
        if duration:
            return duration
    except (OSError, ValueError, subprocess.SubprocessError, TypeError, AttributeError):
        pass
    raise ValueError(f'Could not determine video duration for space planning: {source.name}')


def video_jobs(root, pending=(), selection=None, skipped=(), *, identity, snapshots=None,
               ffprobe=None, cancelled=None, replacements=None):
    """Resolve selected conversions and this device's supported on-disk videos."""
    root = Path(root).resolve(strict=True)
    folder = root / "Videos"

    def check():
        if cancelled and cancelled():
            raise Cancelled('Stopped while checking queued videos.')

    allowed = video_source_extensions(identity)
    native_extensions = native_video_extensions(identity)
    scan_allowed = native_extensions if selection is not None else allowed
    excluded = {Path(value).as_posix().casefold() for value in skipped}
    generated = set()
    try:
        saved = json.loads((cache_root(identity) / 'state.json').read_text(encoding='utf-8'))
        for name in saved.get('video_generated', []):
            path = Path(name)
            if (path.parts and path.parts[0].casefold() == 'videos' and
                    not path.is_absolute() and '..' not in path.parts):
                generated.add(str(root / path).casefold())
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
    queued_relatives = set()

    def include(source, relative):
        check()
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
            check()
            relative = (Path(source.name) / path.relative_to(source)).as_posix() if is_folder else source.name
            if relative.casefold() in queued_relatives:
                raise ValueError(f"Two queued videos have the same library name: {relative}.")
            queued_relatives.add(relative.casefold())
            existing = folder / relative
            _plain(existing, root)
            if existing.exists():
                if not existing.is_file():
                    raise ValueError(f"A different video already exists: {relative}. Rename the new file first.")
                old = existing.stat()
                if old.st_size != info.st_size or not _same_file_bytes(path, existing, info.st_size, checkpoint=check):
                    if replacements is None:
                        raise ValueError(f"A different video already exists: {relative}. Review its replacement before preparing.")
                    replacements.append(dict(action='replace', kind='Videos', source=str(path),
                        destination=str(existing), old_bytes=old.st_size,
                        old_mtime_ns=old.st_mtime_ns, new_bytes=info.st_size,
                        new_mtime_ns=info.st_mtime_ns,
                        old_sha256=_hash(existing, progress=lambda _current, _total: check()),
                        new_sha256=_hash(path, progress=lambda _current, _total: check())))
                    jobs.pop(relative.casefold(), None)
                else:
                    path = existing
            include(path, relative)
    if len(jobs) > 256:
        raise ValueError("Choose at most 256 videos per update.")
    if selection is not None and not selection:
        if (identity['media_profile']['video_backend'] in ('bcm-mp4', 'native-mp4')
                and not (ffprobe or shutil.which('ffprobe')) and jobs):
            raise ValueError('FFprobe is required to check native video compatibility.')
        # No conversions includes only videos whose content is playable as-is.
        # A queued source must be called out instead of silently discarded.
        def check_native(job, stop=None):
            source = Path(job['source'])
            proof_before = None
            if source.suffix.lower() in native_extensions:
                try:
                    proof_before = _receipt_stamp(source.stat())
                except OSError:
                    pass
            details = {}
            should_stop = (lambda: stop.is_set() or bool(cancelled and cancelled())) if stop else cancelled
            native = _video_is_native(source, identity, ffprobe=ffprobe, cancelled=should_stop,
                                      details=details)
            proof_after = None
            if native and proof_before is not None:
                try:
                    proof_after = _receipt_stamp(source.stat())
                except OSError:
                    pass
            reusable = (proof_before is not None and proof_before == proof_after and
                        (os.name != 'nt' or
                         proof_after[3] <= time.time_ns() - _RECENT_OUTPUT_NS))
            return native, details, proof_after if reusable else None

        def collect(items, futures=None):
            ready = []
            for job in items:
                source = Path(job['source'])
                native, details, proof = (
                    futures[id(job)].result() if futures and id(job) in futures else check_native(job))
                if native:
                    if proof is not None:
                        job['_native_check'] = (str(source),
                            json.dumps(identity['media_profile'], sort_keys=True), proof)
                        if details:
                            job['_native_details'] = details
                    ready.append(job)
                elif not source.is_relative_to(root) or job['relative'].casefold() in queued_relatives:
                    raise ValueError(f"{source.name} needs conversion or is not a playable native video. Choose a conversion mode or remove it from the queue.")
            return ready

        all_jobs = list(jobs.values())
        host_checks = [job for job in all_jobs
                       if (identity['media_profile']['video_backend'] in ('bcm-mp4', 'native-mp4') and
                           Path(job['source']).suffix.lower() in native_extensions and
                           not Path(job['source']).is_relative_to(root))]
        host_ids = {id(job) for job in host_checks}
        first_host = next((index for index, job in enumerate(all_jobs) if id(job) in host_ids), len(all_jobs))
        # The device's own videos precede queued host files. Complete those
        # reads before starting several FFprobe processes on host sources.
        if len(host_checks) > 1 and all(id(job) in host_ids for job in all_jobs[first_host:]):
            ready = collect(all_jobs[:first_host])
            stop = threading.Event()
            with ThreadPoolExecutor(max_workers=min(4, len(host_checks))) as pool:
                try:
                    futures = {id(job): pool.submit(check_native, job, stop) for job in host_checks}
                    return ready + collect(all_jobs[first_host:], futures)
                finally:
                    stop.set()
        return collect(all_jobs)
    return list(jobs.values())


def preparation_space(identity, copies, jobs, selected, cache, *, photo_dimension=640,
                      current_inventory=None, ffprobe=None, ffmpeg=None,
                      no_conversions=False, force=False, skipped=None):
    """Bound peak free-space needs before the first device copy.

    Estimates include originals, prepared outputs, host scratch, existing
    publication backups, and the staged index recovery groups. Publishers
    still make their own exact checks immediately before individual writes.
    """
    root = Path(identity['root'])
    cache = Path(cache)
    inventory = (current_inventory if current_inventory is not None else
                 scan(root, tuple(k for k in selected if k != 'Videos'), skipped=skipped))
    counts = {kind: inventory.get(kind, {}).get('count', 0) for kind in KINDS}
    for copy in copies:
        if Path(copy['source']).suffix.lower() in extensions(copy['kind']):
            counts[copy['kind']] += 1
    original_bytes = sum(item.get('converted_bytes', item['bytes']) for item in copies)
    converted_sizes = [item['converted_bytes'] for item in copies if 'converted_bytes' in item]
    audio_scratch = min(sum(converted_sizes), max(64 * 1024 * 1024, max(converted_sizes, default=0)))
    staged_sizes = [item['bytes'] for item in copies if 'converted_bytes' in item and
                    Path(item['source']).is_relative_to(root)]
    audio_scratch += max(staged_sizes, default=0)
    # Audio index, artwork and transaction files grow with the track count.
    music_bytes = 0
    if 'Music' in selected and counts['Music']:
        music_bytes = 8 * 1024 * 1024 + counts['Music'] * 384 * 1024
    photo_bytes = 0
    if 'Photos' in selected and counts['Photos']:
        photo_bytes = 8 * 1024 * 1024 + counts['Photos'] * (
            2 * photo_dimension * photo_dimension * 2 + 16 * 1024)
    notes_bytes = (1024 * 1024 + counts['Notes'] * 64 * 1024
                   if 'Notes' in selected and counts['Notes'] else 0)
    audio_backup = 0
    largest_audio = 0
    if 'Music' in selected:
        seek_state = {} if force else _optional_state(cache / 'seek-checked.json')
        for value in inventory.get('Music', {}).get('files', []):
            path = Path(value)
            if not path.is_relative_to(root) or path.suffix.lower() not in ('.m4a', '.m4b', '.flac', '.flc'):
                continue
            info = path.stat()
            stamp = [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
            if seek_state.get(path.relative_to(root).as_posix().casefold()) != stamp:
                audio_backup += info.st_size
                largest_audio = max(largest_audio, info.st_size)
        for copy in copies:
            if copy['kind'] == 'Music' and Path(copy['source']).suffix.lower() in ('.m4a', '.m4b', '.flac', '.flc'):
                audio_backup += copy['bytes']
                largest_audio = max(largest_audio, copy['bytes'])
    video_bytes = 0
    video_host = 0
    video_conversion_required = False
    if 'Videos' in selected:
        backend = identity['media_profile']['video_backend']
        native_extensions = native_video_extensions(identity)

        def checked_duration(source, probe):
            seconds, before = probe.get('seconds'), probe.get('stamp')
            if not seconds or before is None:
                return None
            try:
                after = _receipt_stamp(Path(source).stat())
            except (OSError, ValueError):
                return None
            if (before != after or
                    (os.name == 'nt' and after[3] > time.time_ns() - _RECENT_OUTPUT_NS)):
                return None
            return seconds, after

        def inspect_host(job, stop):
            from .native_video import inspect_file
            probe = {}
            try:
                details = inspect_file(job['source'], profile=identity['media_profile'],
                                       ffprobe=ffprobe, cancelled=stop.is_set,
                                       duration_probe=probe)
            except (OSError, ValueError):
                details = None
            return details, checked_duration(job['source'], probe) if details is None else None

        def estimate_jobs(items, futures=None):
            nonlocal video_bytes, video_host, video_conversion_required
            for index, job in enumerate(items):
                source = Path(job['source'])
                details = duration_hint = None
                if backend in ('bcm-mp4', 'native-mp4') and source.suffix.lower() in native_extensions:
                    hint = job.get('_native_details') if no_conversions else None
                    if (isinstance(hint, dict) and type(hint.get('fast_start')) is bool and
                            hint.get('file_bytes') == job['bytes'] and
                            _native_check_reusable(job, source, identity['media_profile'])):
                        details = hint
                    elif futures is not None:
                        details, duration_hint = futures[index].result()
                    else:
                        from .native_video import inspect_file
                        probe = {}
                        try:
                            details = inspect_file(source, profile=identity['media_profile'],
                                                   ffprobe=ffprobe, duration_probe=probe)
                        except (OSError, ValueError):
                            pass
                        if details is None:
                            duration_hint = checked_duration(source, probe)
                    native = details is not None
                else:
                    native = (no_conversions and
                              _native_check_reusable(job, source, identity['media_profile']))
                    if not native:
                        native = _video_is_native(source, identity, ffprobe=ffprobe)
                encoder = ffmpeg or shutil.which('ffmpeg')
                if native:
                    if backend in ('bcm-mp4', 'native-mp4'):
                        converts = (not details['fast_start'] or backend == 'bcm-mp4') and bool(encoder)
                        video_conversion_required |= converts
                        direct = no_conversions or not converts
                    else:
                        direct = True
                    if direct and source.is_relative_to(root):
                        continue
                    estimate = job['bytes'] if direct else min(0x7fffffff, job['bytes'] * 2)
                    scratch = 0
                else:
                    video_conversion_required = True
                    duration = None
                    if duration_hint is not None:
                        seconds, stamp = duration_hint
                        try:
                            if _receipt_stamp(source.stat()) == stamp:
                                duration = seconds
                        except (OSError, ValueError):
                            pass
                    if duration is None:
                        duration = _video_duration(source, ffprobe)
                    if backend in ('bcm-mp4', 'native-mp4'):
                        limit = identity['media_profile']['native_video']['max_video_kbps'] + 256
                        estimate = min(0x7fffffff, max(job['bytes'] * 3,
                            math.ceil(duration * limit * 1000 / 8 * 1.25)))
                        scratch = 0
                    else:
                        profile = identity['media_profile']
                        estimate = min(0x7fffffff,
                            math.ceil(duration * profile['video_fps'] * profile['max_read_sectors'] * 512))
                        scratch = math.ceil(duration * 44100 * 4) + 32 * 1024 * 1024
                video_bytes += estimate
                video_host += estimate * 2 + scratch

        all_jobs = list(jobs)
        host_checks = [not no_conversions and backend in ('bcm-mp4', 'native-mp4') and
                       Path(job['source']).suffix.lower() in native_extensions and
                       not Path(job['source']).is_relative_to(root) for job in all_jobs]
        first_host = next((index for index, eligible in enumerate(host_checks) if eligible), len(all_jobs))
        host_count = sum(host_checks)
        if host_count > 1 and all(host_checks[first_host:]):
            estimate_jobs(all_jobs[:first_host])
            stop = threading.Event()
            with ThreadPoolExecutor(max_workers=min(4, host_count)) as pool:
                try:
                    futures = [pool.submit(inspect_host, job, stop) for job in all_jobs[first_host:]]
                    estimate_jobs(all_jobs[first_host:], futures)
                finally:
                    stop.set()
        else:
            estimate_jobs(all_jobs)
    files_entries = sum(counts.values()) + len(jobs)
    preview_sources = counts['Photos'] + counts['Notes'] + len(jobs)
    files_bytes = 4 * 1024 * 1024 + files_entries * 512 + preview_sources * 256 * 1024
    prepared = music_bytes + photo_bytes + notes_bytes + video_bytes + files_bytes
    previous = 0
    fixed = []
    if 'Music' in selected:
        fixed += ['.LINNET/COVERS.CFL', '.LINNET/BROWSE.BIN', '.LINNET/LIBRARY.PDB']
    if 'Photos' in selected:
        fixed += ['.LINNET/PHOTOS/GRID.PGR', '.LINNET/PHOTOS/LIBRARY.PIM']
    if 'Notes' in selected:
        fixed += ['.LINNET/NOTES/LIBRARY.NNT']
    if 'Videos' in selected:
        fixed += ['.LINNET/VIDEOS/INDEX.VID']
    fixed += ['.LINNET/FILES/INDEX.FIL']
    for name in fixed:
        path = root / name
        _plain(path, root)
        if path.is_file():
            previous += path.stat().st_size
    # A video replacement can keep both the prior active package and backup.
    # Budget a previous package as large as the candidate when the exact old
    # path is unavailable from a host receipt.
    previous += video_bytes
    device_needed = original_bytes + prepared + previous * 2 + largest_audio + 16 * 1024 * 1024
    host_needed = (music_bytes * 2 + photo_bytes * 2 + notes_bytes * 2 + video_host + audio_scratch +
                   files_bytes * 2 + audio_backup * 2 + 16 * 1024 * 1024)
    parent = cache
    while not parent.exists():
        parent = parent.parent
    return dict(device_peak_bytes=device_needed, computer_peak_bytes=host_needed,
                device_free_bytes=shutil.disk_usage(root).free,
                computer_free_bytes=shutil.disk_usage(parent).free,
                video_conversion_required=video_conversion_required)


def reconciliation_actions(identity, selected, copies, *, replacements=(),
                           current_inventory=None, skipped=None):
    """Describe removals that require explicit review before preparation."""
    root = Path(identity['root'])
    actions = list(replacements)
    if current_inventory is None:
        if skipped is None:
            state = _optional_state(cache_root(identity) / 'state.json')
            skipped = {kind: _skipped_paths(state, kind) for kind in KINDS}
        inventory = scan(root, tuple(k for k in selected if k != 'Videos'), skipped=skipped)
    else:
        inventory = current_inventory
    for kind, name in (('Music', '.LINNET/LIBRARY.PDB'),
                       ('Photos', '.LINNET/PHOTOS/LIBRARY.PIM'),
                       ('Notes', '.LINNET/NOTES/LIBRARY.NNT')):
        if kind not in selected:
            continue
        count = inventory.get(kind, {}).get('count', 0)
        count += sum(item['kind'] == kind and
                     Path(item['source']).suffix.lower() in extensions(kind) for item in copies)
        path = root / name
        _plain(path, root)
        if not count and path.is_file():
            info = path.stat()
            actions.append(dict(action='retire-library', kind=kind, destination=str(path),
                                old_bytes=info.st_size, old_mtime_ns=info.st_mtime_ns))
    if 'Videos' in selected:
        from .media_library import _catalog, _device_path
        _, _, entries = _catalog(root)
        for key, name, title in entries:
            path = _device_path(root, name)
            if not path.is_file():
                actions.append(dict(action='prune-video', kind='Videos',
                                    destination=str(path), key=key.hex(), title=title))
    return sorted(actions, key=lambda row: (row['kind'], row['action'], row['destination'].casefold()))


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
                if any(attempt.get('reconciliation') for attempt in attempts):
                    current_options['approved_reconciliation'] = None
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
    """Return publication digests and stamps safe for the status hash cache."""
    _volume_guard(identity)
    outputs, stamps = [], {}
    for name in output_paths:
        proof = verified_outputs.get(name)
        path = root / name
        _plain(path, root)
        if proof is None:
            before = path.stat()
            hash_started = time.time_ns()
            digest = _hash(path)
            info = path.stat()
            if _receipt_stamp(before) != _receipt_stamp(info):
                raise ValueError(f"music output changed after verification: {path}")
            # Match _outputs_match's cache admission rule. A hash of a recent
            # write cannot become a trusted cache entry once the window ends.
            cacheable = os.name != "nt" or before.st_mtime_ns <= hash_started - _RECENT_OUTPUT_NS
        else:
            if not isinstance(proof, tuple) or len(proof) != 2:
                raise ValueError(f"invalid music publication proof: {name}")
            digest, stamp = proof
            info = path.stat()
            if _receipt_stamp(info) != stamp:
                raise ValueError(f"music output changed after publication: {path}")
            # Publication proofs do not record when their readback happened.
            # Fresh copies must get one hash after the recent-write window.
            cacheable = os.name != "nt"
        outputs.append((name, digest))
        if cacheable:
            stamps[(name, digest)] = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
    return outputs, stamps


def _video_outputs_from_publication(root, identity, output_paths, proofs):
    """Reuse active-package readbacks, hashing outputs without publication proofs."""
    outputs = []
    for name in output_paths:
        _volume_guard(identity)
        path = root / name
        _plain(path, root)
        proof = proofs.get(name)
        if proof is None:
            before = path.stat()
            digest = _hash(path)
            if _receipt_stamp(path.stat()) != _receipt_stamp(before):
                raise ValueError(f"video output changed during final verification: {path}")
        else:
            if (not isinstance(proof, dict) or not isinstance(proof.get('path'), str) or
                    Path(proof['path']) != path or
                    not isinstance(proof.get('sha256'), str) or
                    re.fullmatch('[0-9a-f]{64}', proof['sha256']) is None or
                    not isinstance(proof.get('stamp'), tuple) or len(proof['stamp']) != 5 or
                    not all(type(value) is int for value in proof['stamp'])):
                raise ValueError(f"invalid video publication proof: {name}")
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or _receipt_stamp(info) != proof['stamp']:
                raise ValueError(f"video output changed after publication: {path}")
            digest = proof['sha256']
        outputs.append((name, digest))
    return outputs


def _prepare_photos(root, cache, identity, media_profile, skipped, retail_photos, *,
                    dimension, checkpoint, progress, begin_publication):
    from .photos import FAT_PATH, compile_photos, fallback_jpeg_header_compatible
    from .publish_photos import publish_photos
    from .music import _device_media_path
    from PIL import Image

    fallbacks = {}
    for path, info in _file_records(root / 'Photos', allowed={'.jpg'}):
        checkpoint()
        if info.st_size > 262144 or path.relative_to(root).as_posix().casefold() in skipped:
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
                eligible = (image.format == 'JPEG' and image.mode in ('RGB', 'L') and
                            not image.info.get('progressive') and not image.info.get('progression') and
                            max(width, height) <= 2048 and width * height <= 4_000_000)
            if not eligible:
                continue
            with path.open('rb') as source:
                if not fallback_jpeg_header_compatible(source.read(262145)):
                    continue
            device_path = _device_media_path(path, root)
            if len(device_path) <= 127 and FAT_PATH.fullmatch(device_path):
                fallbacks[path.relative_to(root / 'Photos').as_posix()] = device_path
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            pass  # The photo compiler reports unreadable originals separately.

    package = cache / "photos.pimg"
    photo_progress = _throttled_progress(checkpoint, progress,
        lambda event: f'Preparing photos {event["current"]+1}/{event["total"]}: {Path(event["file"]).name}')
    prepared = compile_photos(root / "Photos", package, max_dimension=dimension,
                   target=identity['target_id'],
                   viewport_width=media_profile["photo_width"],
                   viewport_height=media_profile["photo_height"],
                   cache_dir=cache / "photo-cache", progress=photo_progress, checkpoint=checkpoint,
                   fallback_paths=fallbacks,
                   excluded={Path(value).relative_to("Photos").as_posix() for value in skipped},
                   additional_sources={Path(item['relative']).relative_to('Photos').as_posix():
                                       (item['preview'], item['title']) for item in retail_photos})
    checkpoint()
    progress("Publishing prepared photos…")
    begin_publication("Photos")
    return [".LINNET/PHOTOS/LIBRARY.PIM", ".LINNET/PHOTOS/GRID.PGR"] + list(dict.fromkeys(
        item['device_path'].lstrip('/') for item in prepared.get('packs', []))), [
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
                    mark_publication, no_conversions=False):
    kind = "Videos"
    published = []
    video_proofs = {}
    from .ipvf_encode import encode_ipvf
    from .ipvf_validate import inspect_file
    from .publish_video import publish_video
    from .video_sources import video_title, catalog_contains
    output_paths = [".LINNET/VIDEOS/INDEX.VID"]
    video_state = state.get("video_files", {})
    if not isinstance(video_state, dict):
        video_state = {}
    state["video_files"] = video_state
    volume_scope = cache_volume_scope(root)
    failed = 0
    retail_titles = None
    catalog_snapshot = {}
    def remember_generated(source, outputs):
        if media_profile['video_backend'] != 'bcm-mp4':
            return
        original = source.relative_to(root).as_posix().casefold() if source.is_relative_to(root) else None
        generated = set(state.get('video_generated', []))
        generated.update(name for name, digest in outputs if name.casefold() != original)
        state['video_generated'] = sorted(generated)
    for index, job in enumerate(videos):
        emit_stage('Preparing Videos', unit, index / len(videos))
        checkpoint()
        source = Path(job["source"])
        relative = job["relative"]
        source_key = (f'{volume_scope}:{source.relative_to(root).as_posix()}'
                      if source.is_relative_to(root) else str(source))
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
                native_version = 5 if media_profile["video_backend"] == "native-mp4" else 4
                native_mode = (':chunked' if not no_conversions and (ffmpeg or shutil.which('ffmpeg')) else ':copy') if media_profile['video_backend'] == 'bcm-mp4' else ''
                fingerprint = hashlib.sha256(f"native-mp4-v{native_version}{native_mode}:{json.dumps(media_profile, sort_keys=True)}:{source_key}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
                cached = video_state.get(relative, {})
                if not isinstance(cached, dict):
                    cached = {}
                outputs = cached.get('outputs', [])
                remember_generated(source, outputs)
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
                # Native preparation checks conversion-enabled host sources.
                # No-conversion planning supplies a short-lived proof for host
                # sources; the copied package is still validated below. Device
                # sources need this check to decide on indexing in place.
                if (source.suffix.lower() in native_video_extensions(identity) and
                        (source.is_relative_to(root) or
                         (no_conversions and not _native_check_reusable(job, source, media_profile)))):
                    try:
                        native_info = inspect_native(source, ffprobe=ffprobe, profile=media_profile, cancelled=cancelled)
                        compatible = (no_conversions or (native_info['fast_start'] and media_profile['video_backend'] != 'bcm-mp4') or
                                      not (ffmpeg or shutil.which('ffmpeg')))
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
                    reusable = package.exists() and not force and not no_conversions
                    if reusable:
                        try:
                            inspect_native(package, ffprobe=ffprobe, profile=media_profile,
                                           cancelled=cancelled)
                        except (OSError, ValueError):
                            reusable = False
                    if not reusable:
                        if no_conversions:
                            checkpoint()
                            package.parent.mkdir(parents=True, exist_ok=True)
                            temporary = package.with_name(package.stem + '.' + uuid.uuid4().hex + '.mp4')
                            owned_temporaries.append((temporary, cache))
                            with source.open('rb') as reader, temporary.open('xb') as writer:
                                while chunk := reader.read(1024 * 1024):
                                    checkpoint()
                                    writer.write(chunk)
                                writer.flush()
                                os.fsync(writer.fileno())
                            inspect_native(temporary, ffprobe=ffprobe, profile=media_profile,
                                           cancelled=cancelled)
                            os.replace(temporary, package)
                            owned_temporaries.remove((temporary, cache))
                        else:
                            prepare_native(source, package, profile=media_profile, ffmpeg=ffmpeg,
                                           ffprobe=ffprobe, progress=progress, cancelled=cancelled,
                                           progress_detail=(lambda event: progress_detail(dict(event,
                                               video_index=index+1, video_total=item['count'])))
                                               if progress_detail else None)
                    checkpoint()
                    after = source.stat()
                    if (after.st_size, after.st_mtime_ns) != source_stamp:
                        raise ValueError("Video changed during preparation; scan again")
                    emit_stage('Publishing Videos', unit,
                               (index + 0.5) / len(videos), can_stop=False)
                    mark_publication()
                    file_publication_started = True
                    readback_proof = {}
                    result = publish_video(package, title=label, library_key=relative,
                                           ffprobe=ffprobe,
                                           source_to_preserve=source if source.is_relative_to(root) else None,
                                           readback_proof=readback_proof,
                                           **target_args(identity))
                    output_name = Path(result['package']).relative_to(root).as_posix()
                    if readback_proof:
                        video_proofs[output_name] = readback_proof
                    outputs = [(output_name, result["candidate_sha256"])]
                    output_paths.append(output_name)
                after = source.stat()
                if (after.st_size, after.st_mtime_ns) != source_stamp:
                    raise ValueError("Video changed during publication; scan again")
                published.append(result)
                catalog_snapshot.clear()
                remember_generated(source, outputs)
                video_state[relative] = dict(signature=fingerprint, outputs=outputs, source_stamp=source_stamp)
                _save(state_path, state)
                report["steps"].append(dict(kind=kind, file=relative, status="published", publication=result))
                record()
                continue
            profile_key = (f"{media_profile['video_width']}x{media_profile['video_height']}-"
                           f"{media_profile['video_fps']}-{media_profile['video_color']}-realtime")
            fingerprint = hashlib.sha256(f"ipvf-{profile_key}:{source_key}:{source_stamp[0]}:{source_stamp[1]}".encode()).hexdigest()
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
                    and ((index_in_place and output_name.casefold() ==
                          source.relative_to(root).as_posix().casefold()) or
                         output_name.casefold().startswith("videos/ipvf/"))
                    and _outputs_match(root, cached.get("outputs", []), verified=verified_outputs)):
                if not index_in_place:
                    output_paths.append(output_name)
                progress(f"Video {index+1}/{item['count']} already ready: {relative}")
                report["steps"].append(dict(kind=kind, file=relative, status="unchanged"))
                continue
            package = cache / "videos" / (key + "-" + fingerprint[:16] + ".ipvf")
            progress(f"Preparing video {index+1}/{item['count']}: {relative}")
            if index_in_place:
                from .publish_video import index_video
                emit_stage('Publishing Videos', unit,
                           (index + 0.5) / len(videos), can_stop=False)
                mark_publication()
                file_publication_started = True
                result = index_video(source, title=label, library_key=relative, **target_args(identity))
                published.append(result)
                catalog_snapshot.clear()
                video_state[relative] = dict(signature=fingerprint,
                    outputs=[(source.relative_to(root).as_posix(), _hash(source))],
                    source_stamp=source_stamp)
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
                    # No-conversion planning already validated this exact
                    # source. The copied temporary is checked again below.
                    if not (no_conversions and _native_check_reusable(job, source, media_profile)):
                        inspect_file(source,expected_width=media_profile["video_width"],
                                     expected_height=media_profile["video_height"],
                                     max_record_sectors=media_profile["max_read_sectors"])
                    checkpoint()
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
            readback_proof = {}
            result = publish_video(package, title=label, library_key=relative,
                                   source_to_preserve=source if source.is_relative_to(root) else None,
                                   readback_proof=readback_proof,
                                   **target_args(identity))
            catalog_snapshot.clear()
            output_name = Path(result['package']).relative_to(root).as_posix()
            if readback_proof:
                video_proofs[output_name] = readback_proof
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
    return output_paths, published, failed, video_proofs


def _run(identity, selected, pending=(), *, progress=lambda message: None, cancelled=lambda: False,
        photo_dimension=640, ffmpeg=None, ffprobe=None, force=False, music_verification="metadata",
        video_selection=None, progress_detail=None, progress_stage=lambda event: None,
        excluded_sources=None, online_artwork=False, approved_reconciliation=None,
        convert_audio=False):
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
    from .media_status import _remember_verified, _verified_outputs
    verified_outputs = _verified_outputs(identity['disk_serial'], identity['volume_serial'],
                                         identity['partition_offset'], identity['volume_unique_id'],
                                         cache_disk_serial=identity.get('media_cache_disk_serial'))
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
        replacements = []
        videos = video_jobs(root, pending, video_selection, skipped=skipped["Videos"],
                            identity=identity, ffprobe=ffprobe, cancelled=cancelled,
                            replacements=replacements) if "Videos" in selected else []
        excluded_sources = {str(Path(value).resolve()).casefold() for value in (excluded_sources or ())}
        videos = [job for job in videos if str(Path(job["source"]).resolve()).casefold() not in excluded_sources]
        reused_audio = []
        verified_before = verified_outputs.copy()
        plan = additions(root, [item for item in pending if item[0] in selected and item[0] != "Videos"],
                         replacements=replacements, convert_audio=convert_audio,
                         target=identity['target_id'], ffprobe=ffprobe, cancelled=cancelled,
                         reused_audio=reused_audio, verified=verified_outputs)
        _remember_verified(identity, verified_outputs, verified_before)
        device_conversions = [source for source, _ in reused_audio] + [Path(item['source']) for item in plan
            if 'converted_bytes' in item and Path(item['source']).is_relative_to(root)]
        projected_skipped = {kind: paths.copy() for kind, paths in skipped.items()}
        for source in device_conversions:
            projected_skipped['Music'].add(source.relative_to(root).as_posix().casefold())
        for _, destination in reused_audio:
            projected_skipped['Music'].discard(destination.relative_to(root).as_posix().casefold())
        if any('converted_bytes' in item for item in plan) and not ffmpeg:
            raise ValueError('Audio conversion needs FFmpeg on the computer.')
        planned = True
        current_inventory = scan(root, tuple(kind for kind in selected if kind != "Videos"),
                                 skipped=projected_skipped) if any(kind != "Videos" for kind in selected) else {}
        reconciliation = reconciliation_actions(identity, selected, plan,
            replacements=replacements, current_inventory=current_inventory, skipped=projected_skipped)
        report['reconciliation'] = reconciliation
        if ((reconciliation and approved_reconciliation is None) or
                (approved_reconciliation is not None and approved_reconciliation != reconciliation)):
            raise ValueError('Source replacement or library cleanup needs review. Refresh the preparation plan and approve its exact actions.')
        for kind, maximum in (("Notes", 256),):
            if kind in selected:
                existing = current_inventory[kind]["count"]
                replacing = {action['destination'].casefold() for action in replacements
                             if action['kind'] == kind and
                             Path(action['destination']).relative_to(root).as_posix().casefold()
                             not in skipped[kind]}
                added = sum(item["kind"] == kind and
                            Path(item["source"]).suffix.lower() in extensions(kind) and
                            item['destination'].casefold() not in replacing for item in plan)
                if existing + added > maximum:
                    raise ValueError(f"{kind} supports {maximum} files; this selection contains {existing + added}. Choose a smaller source folder.")
        space = preparation_space(identity, plan, videos, selected, cache,
            photo_dimension=photo_dimension, ffprobe=ffprobe, ffmpeg=ffmpeg,
            no_conversions=video_selection is not None and not video_selection,
            force=force, current_inventory=current_inventory, skipped=projected_skipped)
        report['space'] = space
        if space['device_peak_bytes'] > min(identity['free_bytes'], space['device_free_bytes']):
            raise ValueError('Not enough iPod space for originals, prepared media, and recovery copies.')
        if space['computer_peak_bytes'] > space['computer_free_bytes']:
            raise ValueError('Not enough computer space for prepared media and conversion scratch.')
        if reconciliation:
            from .media_library import list_items, remove_items, remove_supporting_file
            supporting = [action for action in reconciliation
                if action['action'] == 'replace' and
                Path(action['destination']).suffix.lower() not in extensions(action['kind'])]
            normal = [action for action in reconciliation if action not in supporting]
            selected_rows = []
            if normal:
                # A damaged video catalog must not prevent reviewed changes to
                # other categories; video removals still require the catalog.
                rows = (list_items(identity) if any(action['kind'] == 'Videos' for action in normal)
                        else list_items(identity, category_errors=[]))
                for action in normal:
                    matches = [row for row in rows if row['kind'] == action['kind'] and
                        (row.get('key') == action.get('key') if action['action'] == 'prune-video' else
                         row['path'].casefold() == action['destination'].casefold()) and
                        row['category'] == ('library' if action['action'] == 'retire-library' else
                                            'published' if action['action'] == 'prune-video' else row['category']) and
                        row.get('removable')]
                    if len(matches) != 1:
                        raise ValueError('A reconciliation target changed. Refresh the preparation plan.')
                    selected_rows.append(matches[0])
            checkpoint()
            if selected_rows:
                removal = remove_items(identity, selected_rows)
                report['steps'].append(dict(kind='Reconciliation', actions=normal, removal=removal))
                record()
            for action in supporting:
                checkpoint()
                relative = Path(action['destination']).relative_to(root).as_posix()
                removal = remove_supporting_file(identity, action['kind'], relative,
                    expected_bytes=action['old_bytes'],
                    expected_mtime_ns=action['old_mtime_ns'],
                    expected_sha256=action['old_sha256'])
                report['steps'].append(dict(kind='Reconciliation', actions=[action], removal=removal))
                record()
            for action in reconciliation:
                if action['action'] == 'retire-library':
                    state.pop(action['kind'], None)
                elif action['action'] == 'prune-video':
                    state.pop('Videos', None)
                    saved_videos = state.get('video_files', {})
                    if isinstance(saved_videos, dict):
                        for relative, saved in list(saved_videos.items()):
                            if not isinstance(saved, dict):
                                continue
                            outputs = saved.get('outputs', [])
                            if not isinstance(outputs, list):
                                continue
                            if any(isinstance(output, (list, tuple)) and len(output) == 2
                                   and isinstance(output[0], str) and
                                   str(root / output[0]).casefold() == action['destination'].casefold()
                                   for output in outputs):
                                saved_videos.pop(relative, None)
            _save(state_path, state)
        if reused_audio:
            for source, destination in reused_audio:
                skipped['Music'].add(source.relative_to(root).as_posix().casefold())
                skipped['Music'].discard(destination.relative_to(root).as_posix().casefold())
            state.setdefault('skipped_files', {})['Music'] = sorted(skipped['Music'])
            _save(state_path, state)
        emit_stage('Copying originals', 0)
        def include_copied(items):
            changed = False
            for copied in items:
                kind = copied['kind']
                key = Path(copied['destination']).relative_to(root).as_posix().casefold()
                if key in skipped[kind]:
                    skipped[kind].remove(key)
                    changed = True
                source = Path(copied['source'])
                if 'converted_bytes' in copied and source.is_relative_to(root):
                    source_key = source.relative_to(root).as_posix().casefold()
                    if source_key not in skipped['Music']:
                        skipped['Music'].add(source_key)
                        changed = True
            if changed:
                saved_skipped = state.setdefault('skipped_files', {})
                for kind, paths in skipped.items():
                    saved_skipped[kind] = sorted(paths)
                _save(state_path, state)
        _copy_additions(plan, root, report, owned_temporaries, checkpoint, record, progress,
                        cache=cache, cancelled=cancelled, ffmpeg=ffmpeg, ffprobe=ffprobe,
                        completed_batch=include_copied,
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
                progress(f"{kind}: no supported files to prepare.")
                continue
            option = preparation_option(kind, identity, photo_dimension, music_verification)
            video_version = 6 if media_profile.get("video_backend") == "native-mp4" else 5 if media_profile.get("video_backend") == "bcm-mp4" else 4
            video_mode = (':chunked' if (video_selection is None or video_selection) and (ffmpeg or shutil.which('ffmpeg')) else ':copy') if media_profile.get('video_backend') == 'bcm-mp4' else ''
            signature = (f"videos-v{video_version}{video_mode}-{json.dumps(media_profile, sort_keys=True)}:{item['fingerprint']}" if kind == "Videos"
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
                verified_before = verified_outputs.copy()
                if _outputs_match(root, outputs, verified=verified_outputs, progress=checking):
                    _remember_verified(identity, verified_outputs, verified_before)
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
                    output_paths, published, failed, video_proofs = _prepare_videos(
                        root, cache, identity, media_profile, state, state_path, videos, item,
                        ffmpeg=ffmpeg, ffprobe=ffprobe, force=force, cancelled=cancelled,
                        checkpoint=checkpoint, progress=progress, emit_stage=emit_stage, unit=unit,
                        record=record, report=report, verified_outputs=verified_outputs,
                        owned_temporaries=owned_temporaries, progress_detail=progress_detail,
                        mark_publication=mark_publication,
                        no_conversions=video_selection is not None and not video_selection)
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
                    outputs, photo_stamps = _published_photo_output(root, identity, output_paths, published)
                elif kind == 'Music':
                    outputs, music_stamps = _music_outputs_from_publication(root, output_paths, music_proofs, identity)
                elif kind == 'Videos':
                    outputs = _video_outputs_from_publication(root, identity, output_paths, video_proofs)
                else:
                    outputs = [(name, _hash(root / name)) for name in output_paths]
                state[kind] = dict(signature=signature, outputs=outputs)
                if kind == 'Music':
                    state[kind]['seek_probe_deferred'] = probe_deferred
                if kind == "Videos":
                    state[kind]["media_profile"] = media_profile
                _save(state_path, state)
                if kind == 'Music':
                    # Reuse publication readbacks for later preparation and
                    # status checks without rereading unchanged iPod covers.
                    before = verified_outputs.copy()
                    verified_outputs.update(music_stamps)
                    _remember_verified(identity, verified_outputs, before)
                elif kind == 'Photos':
                    # Publication already hashed reused immutable tile packs.
                    before = verified_outputs.copy()
                    verified_outputs.update(photo_stamps)
                    _remember_verified(identity, verified_outputs, before)
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
        # Include the managed Files folder in the first snapshot. Its contents
        # are excluded by compile_files, so publication cannot add a new row
        # that forces an otherwise unchanged second update to rewrite INDEX.FIL.
        files_dir = root / '.LINNET' / 'FILES'
        _plain(files_dir, root)
        files_dir.mkdir(parents=True, exist_ok=True)
        files_package = cache / 'files.fil'
        next_files_guard = 0.0
        def files_checkpoint():
            nonlocal next_files_guard
            now = time.monotonic()
            if cancelled() or now >= next_files_guard:
                checkpoint()
                next_files_guard = time.monotonic() + 0.05
        files_report = compile_files(root, files_package, cache / 'file-previews',
            target=identity['target_id'],
            width=media_profile['photo_width'] if 'Photos' in supported_kinds(identity) else 0,
            height=media_profile['photo_height'] if 'Photos' in supported_kinds(identity) else 0,
            text_columns=20 if media_profile['photo_width'] < 220 else 24,
            checkpoint=files_checkpoint, progress=progress)
        checkpoint()
        emit_stage('Publishing Files', total_stages - 2, can_stop=False)
        files_outputs = [('.LINNET/FILES/INDEX.FIL', files_report['sha256'])]
        files_outputs.extend((item['path'], item['sha256']) for item in files_report['previews'])
        verified_before = verified_outputs.copy()
        if _outputs_match(root, files_outputs, verified=verified_outputs):
            checkpoint()
            _remember_verified(identity, verified_outputs, verified_before)
            files_publication = dict(operation='publish-files', passed=True, phase='verified',
                                     reused_index=True, previews_added=0,
                                     entries=files_report['entries'],
                                     preview_files=len(files_report['previews']))
        else:
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
