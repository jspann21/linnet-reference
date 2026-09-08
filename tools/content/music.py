"""Deterministic, bounded PODB v1 compiler and host validator.

WAV/AIFF PCM metadata is parsed without decoding audio. Optional ffprobe metadata
does not confer device codec support. Staged copies preserve original files.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
import tempfile
import zlib

HEADER = 128
TRACK = 128
GROUP = 32
ART = 32
MAX_TRACKS = 100_000
MAX_DATABASE = 128 * 1024 * 1024
MAX_STRING = 255
NO_INDEX = 0xFFFFFFFF
UNKNOWN_GAIN = -0x80000000
CODECS = {"pcm_le": 1, "pcm_be": 2, "float_le": 3, "float_be": 4,
          "mp3": 16, "aac": 17, "alac": 18, "flac": 19,
          "vorbis": 20, "opus": 21, "wavpack": 22, "unknown": 255}
EXTENSIONS = {".wav", ".aif", ".aiff", ".aifc", ".mp3", ".m4a",
              ".aac", ".flac", ".ogg", ".opus", ".wv"}


def _text(value: object) -> str:
    value = str(value).replace("\x00", " ").strip()
    if len(value.encode("utf-8")) > MAX_STRING:
        raise ValueError("metadata string exceeds 255 UTF-8 bytes")
    return value


def _number(value: object) -> int:
    try:
        number = int(str(value).split("/", 1)[0])
        return number if 0 <= number <= 0xFFFFFFFF else 0
    except (ValueError, TypeError):
        return 0


def _stable(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "little")


def _extended(raw: bytes) -> int:
    exponent, mantissa = struct.unpack(">HQ", raw)
    if exponent & 0x8000 or (exponent & 0x7FFF) > 16401:
        raise ValueError("invalid AIFF sample rate")
    rate = math.ldexp(mantissa, (exponent & 0x7FFF) - 16383 - 63)
    if not math.isfinite(rate) or not 1 <= rate <= 384000 or rate != int(rate):
        raise ValueError("unsupported AIFF sample rate")
    return int(rate)


def _pcm(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as stream:
        top = stream.read(12)
        wave = top[:4] == b"RIFF" and top[8:] == b"WAVE"
        aiff = top[:4] == b"FORM" and top[8:] in (b"AIFF", b"AIFC")
        if not wave and not aiff:
            raise ValueError("not a supported RIFF WAVE or AIFF container")
        endian = "<" if wave else ">"
        end = struct.unpack(endian + "I", top[4:8])[0] + 8
        if end > size or end < 12:
            raise ValueError("truncated audio container")
        result = {"tags": {}, "data_offset": 0, "data_bytes": 0, "frames": 0}
        position = 12
        chunks = 0
        have_data = False
        while position < end:
            chunks += 1
            if chunks > 10000 or end - position < 8:
                raise ValueError("audio chunk bounds")
            stream.seek(position)
            kind, length = struct.unpack(endian + "4sI", stream.read(8))
            start = position + 8
            if length + (length & 1) > end - start:
                raise ValueError("truncated audio chunk")
            if wave and kind == b"fmt ":
                if length < 16 or length > 65536 or "codec" in result:
                    raise ValueError("invalid WAV format chunk")
                raw = stream.read(length)
                encoding, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", raw)
                if encoding == 0xFFFE:
                    if length < 40 or raw[26:40] != bytes.fromhex("000000001000800000aa00389b71"):
                        raise ValueError("unsupported WAV extensible format")
                    encoding = struct.unpack_from("<H", raw, 24)[0]
                    if struct.unpack_from("<H", raw, 18)[0] != bits:
                        raise ValueError("packed valid bits are not supported")
                if encoding not in (1, 3) or bits not in (8, 16, 24, 32) or not channels or not rate:
                    raise ValueError("unsupported WAV PCM encoding")
                if align != channels * ((bits + 7) // 8) or byte_rate != rate * align:
                    raise ValueError("inconsistent WAV sample layout")
                if encoding == 3 and bits != 32:
                    raise ValueError("unsupported WAV float width")
                result.update(codec=CODECS["pcm_le" if encoding == 1 else "float_le"],
                              channels=channels, rate=rate, bits=bits, align=align)
            elif aiff and kind == b"COMM":
                if length < 18 or length > 65536 or "codec" in result:
                    raise ValueError("invalid AIFF common chunk")
                raw = stream.read(length)
                channels, frames, bits = struct.unpack_from(">HIH", raw)
                compression = b"NONE" if top[8:] == b"AIFF" else raw[18:22]
                codec = {b"NONE": "pcm_be", b"twos": "pcm_be", b"sowt": "pcm_le",
                         b"fl32": "float_be", b"FL32": "float_be"}.get(compression)
                if codec is None or bits not in (8, 16, 24, 32) or not channels:
                    raise ValueError("unsupported AIFF PCM encoding")
                if codec == "float_be" and bits != 32:
                    raise ValueError("unsupported AIFF float width")
                result.update(codec=CODECS[codec], channels=channels, frames=frames,
                              rate=_extended(raw[8:18]), bits=bits, align=channels * ((bits + 7) // 8))
            elif (wave and kind == b"data") or (aiff and kind == b"SSND"):
                if have_data:
                    raise ValueError("multiple audio data chunks")
                have_data = True
                if aiff:
                    if length < 8:
                        raise ValueError("short AIFF sound chunk")
                    offset, _block = struct.unpack(">II", stream.read(8))
                    if offset > length - 8:
                        raise ValueError("AIFF sound offset")
                    start += 8 + offset
                    length -= 8 + offset
                result.update(data_offset=start, data_bytes=length)
            elif aiff and kind in (b"NAME", b"AUTH") and length <= 4096:
                key = "title" if kind == b"NAME" else "artist"
                result["tags"][key] = stream.read(length).decode("latin-1").rstrip("\x00")
            elif wave and kind == b"LIST" and length <= 1024 * 1024:
                raw = stream.read(length)
                if raw[:4] == b"INFO":
                    cursor = 4
                    tags = {b"INAM": "title", b"IART": "artist", b"IPRD": "album",
                            b"IGNR": "genre", b"ICRD": "date", b"ITRK": "track"}
                    while cursor + 8 <= len(raw):
                        tag, count = struct.unpack_from("<4sI", raw, cursor)
                        cursor += 8
                        if count > len(raw) - cursor:
                            raise ValueError("truncated WAV INFO tag")
                        if tag in tags:
                            result["tags"][tags[tag]] = raw[cursor:cursor+count].rstrip(b"\0").decode("utf-8", "replace")
                        cursor += count + (count & 1)
            # Use the original chunk length; SSND processing changes local length.
            stream.seek(position + 4)
            original = struct.unpack(endian + "I", stream.read(4))[0]
            position += 8 + original + (original & 1)
        if "codec" not in result or not have_data:
            raise ValueError("audio format or data missing")
        if result["data_bytes"] % result["align"]:
            raise ValueError("incomplete PCM frame")
        frames = result["data_bytes"] // result["align"]
        if aiff and result["frames"] != frames:
            raise ValueError("AIFF frame count disagrees with sound bytes")
        result["frames"] = frames
        if result["channels"] > 8 or result["rate"] > 384000:
            raise ValueError("audio channel/sample-rate bound")
        return result


def _decoded_frames(path: Path, executable: str) -> int:
    """Count decoded samples, never estimate duration from bitrate/container time.

    No PCM is emitted. Bound decoding to 30 seconds and probe output to 1 MiB;
    decode errors, missing sample counts and exceeded budgets reject the import.
    """
    command = [executable, "-v", "error", "-select_streams", "a:0",
               "-show_entries", "frame=nb_samples:frame_side_data=",
               "-of", "csv=p=0", str(path)]
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT) as process:
        timer = threading.Timer(30, lambda: process.kill() if process.poll() is None else None)
        timer.daemon = True
        timer.start()
        output = bytearray()
        try:
            while chunk := process.stdout.read(4096):
                output.extend(chunk)
                if len(output) > 1024 * 1024:
                    raise ValueError("decoded sample-count output exceeds limit")
            if process.wait():
                raise ValueError("decoded sample-count probe failed or exceeded 30 seconds")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
    frames = 0
    for line in output.splitlines():
        if not line:
            continue
        if not re.fullmatch(rb"[1-9][0-9]{0,6},?", line):
            raise ValueError("invalid decoded sample count or audio decode error")
        samples = int(line.rstrip(b","))
        if samples > 1048576:
            raise ValueError("decoded audio frame exceeds sample bound")
        frames += samples
    if not 0 < frames <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("missing or oversized decoded sample count")
    return frames


def _probe(path: Path, executable: str) -> dict:
    # ffprobe is optional host metadata tooling, never a native decoder substitute.
    command = [executable, "-v", "error", "-show_entries",
               "stream=codec_name,codec_type,sample_rate,channels,bits_per_raw_sample:format_tags:stream_tags",
               "-of", "json", str(path)]
    completed = subprocess.run(command, capture_output=True, timeout=30, check=True)
    if len(completed.stdout) > 1024 * 1024:
        raise ValueError("ffprobe metadata exceeds limit")
    info = json.loads(completed.stdout)
    streams = [item for item in info.get("streams", []) if item.get("codec_type") == "audio"]
    if len(streams) != 1:
        raise ValueError("exactly one audio stream required")
    audio = streams[0]
    codec = CODECS.get(audio.get("codec_name"), CODECS["unknown"])
    if codec == CODECS["unknown"]:
        raise ValueError("unrecognized compressed audio codec")
    tags = {str(k).lower(): v for k, v in info.get("format", {}).get("tags", {}).items()}
    tags.update({str(k).lower(): v for k, v in audio.get("tags", {}).items()})
    rate, channels = _number(audio.get("sample_rate")), _number(audio.get("channels"))
    if not 1 <= rate <= 384000 or not 1 <= channels <= 8:
        raise ValueError("audio channel/sample-rate bound")
    bits = _number(audio.get("bits_per_raw_sample"))
    if bits > 64:
        raise ValueError("compressed source bit-depth bound")
    return dict(codec=codec, channels=channels, rate=rate, bits=bits,
                frames=_decoded_frames(path, executable), data_offset=0,
                data_bytes=path.stat().st_size, tags=tags)


def compile_music(source: Path, output: Path, *, ffprobe: str | None = None,
                  artwork: bool = True, playlists: dict[str, list[str]] | None = None) -> dict:
    """Prepare and validate a complete stage before replacing the old directory.

    An interrupted directory swap leaves a sibling backup, restored on the next
    import if the output is absent. Concurrent imports into one output are unsupported.
    """
    from .publish import validate_stage

    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir() or output == source or source in output.parents or output in source.parents:
        raise ValueError("output must be outside the source music directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    backup = output.with_name(output.name + ".music-previous")
    if backup.exists() and not output.exists():
        backup.rename(output)
    if backup.exists():
        raise ValueError(f"previous music stage retained at {backup}; restore or archive it before importing")
    prepared = Path(tempfile.mkdtemp(prefix=output.name + ".music-prepare-", dir=output.parent))
    moved_previous = False
    try:
        if output.exists():
            # Preserve unrelated staged content without copying obsolete music.
            managed = {"MUSIC", "ART", "LIBRARY.PDB", "LIBRARY.TMP", "music-manifest.json"}
            shutil.copytree(output, prepared, dirs_exist_ok=True, symlinks=True,
                            ignore=lambda directory, names: [name for name in names
                                if Path(directory) == output and name in managed])
        report = _compile_music_stage(source, prepared, ffprobe=ffprobe,
                                      artwork=artwork, playlists=playlists)
        report["database"] = str(output / "LIBRARY.PDB")
        (prepared / "music-manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        validate_stage(prepared)
        try:
            if output.exists():
                output.rename(backup)
                moved_previous = True
            prepared.rename(output)
        except BaseException:
            if backup.exists() and not output.exists():
                try:
                    backup.rename(output)
                except OSError as recovery_error:
                    raise RuntimeError(f"music stage publication failed; restore previous stage from {backup}") from recovery_error
            raise
        # Publication has committed. Cleanup failure must not turn a successful
        # replacement into a failed-import result; the backup remains recoverable.
        if moved_previous:
            shutil.rmtree(backup, ignore_errors=True)
        return report
    finally:
        if prepared.exists():
            shutil.rmtree(prepared, ignore_errors=True)


def _compile_music_stage(source: Path, output: Path, *, ffprobe: str | None = None,
                         artwork: bool = True, playlists: dict[str, list[str]] | None = None) -> dict:
    """Stage source audio under MUSIC/8HEX.EXT and write LIBRARY.PDB.

    Install MUSIC and ART below /LINNET and LIBRARY.PDB at /LINNET/LIBRARY.PDB.
    Source-relative playlist paths are exact; unsupported sources fail explicitly.
    """
    source, output = source.resolve(), output.resolve()
    if not source.is_dir() or output == source or source in output.parents or output in source.parents:
        raise ValueError("output must be outside the source music directory")
    paths = []
    for path in source.rglob("*"):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            paths.append(path)
            if len(paths) > MAX_TRACKS:
                raise ValueError("library exceeds 100000 tracks")
    paths.sort(key=lambda p: p.relative_to(source).as_posix())
    output.mkdir(parents=True, exist_ok=True)
    (output / "MUSIC").mkdir(exist_ok=True)
    pool = bytearray(b"\0")
    strings = {"": 0}

    def string(value: object) -> int:
        value = _text(value)
        if value not in strings:
            strings[value] = len(pool)
            pool.extend(value.encode("utf-8") + b"\0")
        return strings[value]

    records, entries, artwork_records = [], [], []
    art_cache: dict[Path, int] = {}
    art_indices: dict[bytes, int] = {}
    filenames: set[str] = set()
    stable_ids: set[int] = set()
    groups: dict[tuple[int, str, str], list[int]] = {}

    def art_for(path: Path) -> int:
        if not artwork:
            return NO_INDEX
        folder = path.parent
        if folder in art_cache:
            return art_cache[folder]
        candidates = [folder / name for name in ("cover.png", "cover.jpg", "folder.jpg", "Folder.jpg")]
        cover = next((p for p in candidates if p.is_file()), None)
        if cover is None:
            art_cache[folder] = NO_INDEX
            return NO_INDEX
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise ValueError("cover conversion requires Pillow, or artwork=False") from exc
        if cover.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("cover source exceeds 32 MiB")
        with Image.open(cover) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError("cover dimensions exceed bound")
            image = ImageOps.fit(image.convert("RGB"), (64, 64))
            pixels = bytearray()
            for red, green, blue in image.getdata():
                pixels.extend(struct.pack("<H", ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)))
        digest = hashlib.sha256(pixels).digest()
        if digest in art_indices:
            art_cache[folder] = art_indices[digest]
            return art_indices[digest]
        name = digest[:4].hex().upper() + ".RGB"
        (output / "ART").mkdir(exist_ok=True)
        destination = output / "ART" / name
        if destination.exists() and destination.read_bytes() != pixels:
            raise ValueError("art filename collision")
        destination.write_bytes(pixels)
        index = len(artwork_records)
        artwork_records.append(struct.pack("<QIHHIIII", int.from_bytes(digest[:8], "little"),
            string("/LINNET/ART/" + name), 64, 64, 1, len(pixels), zlib.crc32(pixels), 0))
        art_cache[folder] = index
        art_indices[digest] = index
        return index

    for path in paths:
        relative = path.relative_to(source).as_posix()
        if path.is_symlink() or source not in path.resolve().parents:
            raise ValueError("audio paths must remain in the source directory")
        before = path.stat()
        metadata = _pcm(path) if path.suffix.lower() in (".wav", ".aif", ".aiff", ".aifc") else (
            _probe(path, ffprobe) if ffprobe else None)
        if metadata is None:
            raise ValueError(f"{relative}: compressed metadata requires explicit ffprobe executable")
        identity = _stable("track:" + relative)
        extension = {".aiff": "AIF", ".aifc": "AIF", ".flac": "FLC", ".opus": "OPS"}.get(path.suffix.lower(), path.suffix[1:].upper())
        name = f"{identity & 0xffffffff:08X}.{extension}"
        if identity in stable_ids or name in filenames:
            raise ValueError("stable track identifier or staged filename collision")
        stable_ids.add(identity)
        filenames.add(name)
        hasher = hashlib.sha256()
        temporary = output / "MUSIC" / (name + ".tmp")
        with path.open("rb") as original, temporary.open("wb") as staged:
            while chunk := original.read(1024 * 1024):
                hasher.update(chunk)
                staged.write(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            temporary.unlink(missing_ok=True)
            raise ValueError("audio source changed during compilation")
        temporary.replace(output / "MUSIC" / name)
        tags = metadata["tags"]
        title = _text(tags.get("title") or path.stem)
        artist = _text(tags.get("artist") or "Unknown Artist")
        album = _text(tags.get("album") or "Unknown Album")
        genre, composer = _text(tags.get("genre", "")), _text(tags.get("composer", ""))
        year = _number(str(tags.get("date", tags.get("year", "")))[:4])
        track, disc = _number(tags.get("track", "")), _number(tags.get("disc", ""))
        gain = UNKNOWN_GAIN
        if "replaygain_track_gain" in tags:
            try:
                db = float(str(tags["replaygain_track_gain"]).lower().replace("db", "").strip())
                if math.isfinite(db) and -60 <= db <= 60:
                    gain = round(db * 65536)
            except ValueError:
                pass
        record = bytearray(TRACK)
        struct.pack_into("<QQQQQIHH", record, 0, identity, before.st_size,
            metadata["data_offset"], metadata["data_bytes"], metadata["frames"],
            metadata["rate"], metadata["channels"], metadata["bits"])
        struct.pack_into("<IIIIIIIIIIIi", record, 48, metadata["codec"], string(title), string(artist),
            string(album), string("/LINNET/MUSIC/" + name), string(genre), string(composer),
            year, track, disc, art_for(path), gain)
        record[96:128] = hasher.digest()
        index = len(records)
        records.append(record)
        for kind, label, parent in ((1, artist, ""), (2, album, artist), (3, genre, ""),
                                    (4, composer, ""), (5, str(year) if year else "", ""),
                                    (6, path.parent.relative_to(source).as_posix(), "")):
            if label:
                groups.setdefault((kind, label, parent), []).append(index)
        entries.append(dict(source=relative, id=f"{identity:016x}", path="/LINNET/MUSIC/" + name,
                            title=title, artist=artist, album=album, track=track, disc=disc,
                            codec=metadata["codec"], sha256=hasher.hexdigest()))
    lookup = {entry["source"]: index for index, entry in enumerate(entries)}
    for name, members in (playlists or {}).items():
        if len(members) > MAX_TRACKS:
            raise ValueError("playlist exceeds track limit")
        try:
            groups[(7, _text(name), "")] = [lookup[member] for member in members]
        except KeyError as exc:
            raise ValueError(f"playlist contains unknown source: {exc}") from exc
    keys = sorted(groups, key=lambda key: (key[0], key[1].casefold(), key[2].casefold(), key))
    group_indices = {key: index for index, key in enumerate(keys)}
    group_records, members, group_ids = [], [], set()
    for key in keys:
        kind, name, parent = key
        indices = groups[key]
        if kind != 7:
            indices = sorted(indices, key=lambda i: (entries[i]["disc"], entries[i]["track"],
                                                      entries[i]["title"].casefold(), i))
        parent_index = group_indices[(1, parent, "")] if kind == 2 else NO_INDEX
        identity = _stable("group:" + json.dumps([kind, parent, name], ensure_ascii=False, separators=(",", ":")))
        if identity in group_ids:
            raise ValueError("stable group identifier collision")
        group_ids.add(identity)
        group_records.append(struct.pack("<IIIIIIQ", kind, string(name), parent_index,
            len(members), len(indices), 0, identity))
        members.extend(indices)
    search = sorted(range(len(entries)), key=lambda i: (entries[i]["title"].casefold(), i))
    search_records = [struct.pack("<II", i, string(entries[i]["title"].casefold())) for i in search]
    track_offset = HEADER
    group_offset = track_offset + TRACK * len(records)
    member_offset = group_offset + GROUP * len(group_records)
    search_offset = member_offset + 4 * len(members)
    art_offset = search_offset + 8 * len(search)
    string_offset = art_offset + ART * len(artwork_records)
    payload = b"".join(records) + b"".join(group_records)
    payload += b"".join(struct.pack("<I", i) for i in members)
    payload += b"".join(search_records)
    payload += b"".join(artwork_records) + pool
    if HEADER + len(payload) > MAX_DATABASE:
        raise ValueError("database exceeds 128 MiB")
    header = bytearray(HEADER)
    struct.pack_into("<4sHH14I", header, 0, b"PODB", 1, HEADER, HEADER + len(payload), 0,
        len(records), len(group_records), len(members), len(search), track_offset, group_offset,
        member_offset, search_offset, string_offset, len(pool), len(artwork_records), art_offset)
    header[64:96] = hashlib.sha256(payload).digest()
    struct.pack_into("<I", header, 124, zlib.crc32(header[:124]))
    database = bytes(header) + payload
    validate_database(database)
    temporary = output / "LIBRARY.TMP"
    temporary.write_bytes(database)
    temporary.replace(output / "LIBRARY.PDB")
    report = dict(format="PODB", version=1, tracks=len(records), groups=len(groups),
                  artwork=len(artwork_records), bytes=len(database), sha256=hashlib.sha256(database).hexdigest(),
                  database=str(output / "LIBRARY.PDB"), entries=entries,
                  limitations=["Codec metadata does not imply native decoder qualification.",
                               "Compressed sample counts use bounded host decoding; native decoder counts take precedence. Gapless trim metadata and seek tables are not emitted.",
                               "No cached FAT extents; paths are resolved by the device."])
    (output / "music-manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def validate_database(data: bytes) -> dict:
    """Strict full host validation; firmware may validate by bounded reads."""
    if len(data) < HEADER or len(data) > MAX_DATABASE:
        raise ValueError("database size")
    magic, version, header_size, *fields = struct.unpack_from("<4sHH14I", data)
    size, flags, tracks, groups, members, searches, to, go, mo, so, po, ps, arts, ao = fields
    if (magic, version, header_size, size, flags) != (b"PODB", 1, HEADER, len(data), 0):
        raise ValueError("database header")
    if tracks > MAX_TRACKS or searches != tracks or any(data[96:124]):
        raise ValueError("database counts/reserved")
    if (to != HEADER or go != to + tracks * TRACK or mo != go + groups * GROUP or
        so != mo + members * 4 or ao != so + searches * 8 or po != ao + arts * ART or po + ps != size or not ps):
        raise ValueError("database section bounds")
    if zlib.crc32(data[:124]) != struct.unpack_from("<I", data, 124)[0]:
        raise ValueError("database header CRC")
    if hashlib.sha256(data[HEADER:]).digest() != data[64:96]:
        raise ValueError("database payload SHA256")
    pool = data[po:]
    if pool[0] or pool[-1]:
        raise ValueError("string pool sentinel")
    strings = {}
    cursor = 0
    while cursor < len(pool):
        end = pool.find(b"\0", cursor)
        if end < 0 or end - cursor > MAX_STRING:
            raise ValueError("string length")
        strings[cursor] = pool[cursor:end].decode("utf-8")
        cursor = end + 1

    def get_string(offset: int) -> str:
        if offset not in strings:
            raise ValueError("string reference")
        return strings[offset]

    titles, ids = [], set()
    for index in range(tracks):
        off = to + index * TRACK
        identity, file_size, start, count, frames, rate, channels, bits = struct.unpack_from("<QQQQQIHH", data, off)
        codec, title, artist, album, path, genre, composer, year, track, disc, art, gain = struct.unpack_from("<IIIIIIIIIIIi", data, off + 48)
        if identity in ids or start > file_size or count > file_size - start or not 1 <= rate <= 384000 or not 1 <= channels <= 8:
            raise ValueError("track identity/range")
        ids.add(identity)
        for offset in (title, artist, album, path, genre, composer):
            get_string(offset)
        location = get_string(path)
        if not re.fullmatch(r"/LINNET/MUSIC/[0-9A-F]{8}\.[A-Z0-9]{1,3}", location):
            raise ValueError("track path")
        if codec not in CODECS.values() or codec == 255 or (art != NO_INDEX and art >= arts):
            raise ValueError("track codec/art")
        if codec <= 4 and (bits not in (8, 16, 24, 32) or count != frames * channels * ((bits + 7) // 8)):
            raise ValueError("PCM frame layout")
        if codec >= 16 and (start or count != file_size):
            raise ValueError("compressed track must cover the complete file")
        if codec in (3, 4) and bits != 32:
            raise ValueError("float sample width")
        if gain != UNKNOWN_GAIN and not -60 * 65536 <= gain <= 60 * 65536:
            raise ValueError("ReplayGain bound")
        titles.append(get_string(title))
    group_ids = set()
    for index in range(groups):
        kind, name, parent, first, count, reserved, identity = struct.unpack_from("<IIIIIIQ", data, go + index * GROUP)
        get_string(name)
        if kind not in range(1, 8) or reserved or first > members or count > members - first:
            raise ValueError("group bounds")
        if identity in group_ids:
            raise ValueError("group identifier collision")
        group_ids.add(identity)
        if kind == 2:
            if parent >= groups or struct.unpack_from("<I", data, go + parent * GROUP)[0] != 1:
                raise ValueError("album artist parent")
        elif parent != NO_INDEX:
            raise ValueError("unexpected group parent")
    for offset in range(mo, so, 4):
        if struct.unpack_from("<I", data, offset)[0] >= tracks:
            raise ValueError("member track index")
    order = []
    for index in range(searches):
        track, key = struct.unpack_from("<II", data, so + index * 8)
        if track >= tracks or get_string(key) != titles[track].casefold():
            raise ValueError("search key")
        order.append(track)
    if sorted(order) != list(range(tracks)) or order != sorted(order, key=lambda i: (titles[i].casefold(), i)):
        raise ValueError("search permutation/order")
    for index in range(arts):
        identity, path, width, height, encoding, count, crc, reserved = struct.unpack_from("<QIHHIIII", data, ao + index * ART)
        if not re.fullmatch(r"/LINNET/ART/[0-9A-F]{8}\.RGB", get_string(path)) or (width, height, encoding, count, reserved) != (64, 64, 1, 8192, 0):
            raise ValueError("art record")
    return dict(tracks=tracks, groups=groups, members=members, artwork=arts, bytes=size)
