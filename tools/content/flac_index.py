"""Add native FLAC seek points to an iPod copy without changing audio frames."""
from bisect import bisect_right
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import uuid

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
MAX_METADATA = 16 * 1024 * 1024
MAX_PACKET_INDEX = 64 * 1024 * 1024


def _layout(path):
    size = path.stat().st_size
    with path.open('rb') as reader:
        if reader.read(4) != b'fLaC':
            return None
        at, first, seek = 4, True, False
        while at + 4 <= size and at < MAX_METADATA:
            reader.seek(at)
            header = reader.read(4)
            kind, length = header[0] & 127, int.from_bytes(header[1:], 'big')
            if at + 4 + length > size:
                return None
            if first:
                if kind != 0 or length != 34:
                    return None
                stream = reader.read(34)
                rate = int.from_bytes(stream[10:13], 'big') >> 4
                total = ((stream[13] & 15) << 32) | int.from_bytes(stream[14:18], 'big')
                if not rate or not total:
                    return None
                first = False
            elif kind == 0:
                return None
            seek |= kind == 3
            last = at
            at += 4 + length
            if header[0] & 128:
                return (at, last, rate, total, seek) if at < size and at <= MAX_METADATA else None
    return None


def same_original(source, destination):
    """Recognize this metadata-only augmentation during repeat imports."""
    source, destination = Path(source), Path(destination)
    original, prepared = _layout(source), _layout(destination)
    if not original or not prepared or original[4] or not prepared[4]:
        return False
    audio_at, last_header, rate, total, _ = original
    if prepared[1] != audio_at or prepared[2:4] != (rate, total):
        return False
    added = prepared[0] - audio_at
    if (added < 22 or added > 4 + 64 * 18 or
            source.stat().st_size + added != destination.stat().st_size):
        return False
    with source.open('rb') as left, destination.open('rb') as right:
        metadata = bytearray(left.read(audio_at))
        if len(metadata) != audio_at or not metadata[last_header] & 128:
            return False
        metadata[last_header] &= 127
        if metadata != right.read(audio_at):
            return False
        block = right.read(added)
        if (len(block) != added or block[0] != 0x83 or
                int.from_bytes(block[1:4], 'big') != added - 4 or (added - 4) % 18):
            return False
        remaining = source.stat().st_size - audio_at
        while remaining:
            size = min(remaining, 1024 * 1024)
            if left.read(size) != right.read(size):
                return False
            remaining -= size
    return True


def _points(path, probe, audio_at, rate, total, checkpoint):
    packet_path = path.with_name('packets.json')
    with packet_path.open('wb') as output:
        child = subprocess.Popen([str(probe), '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=sample_rate,time_base,duration_ts',
            '-show_entries', 'packet=pts,duration,pos,size', '-of', 'json', str(path)],
            stdout=output, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        started = time.monotonic()
        oversized = False
        try:
            while child.poll() is None:
                checkpoint()
                if packet_path.stat().st_size > MAX_PACKET_INDEX:
                    oversized = True
                    break
                if time.monotonic() - started > 600:
                    raise TimeoutError('FLAC seek preparation exceeded ten minutes')
                time.sleep(.05)
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=10)
    if oversized or child.returncode or packet_path.stat().st_size > MAX_PACKET_INDEX:
        return None
    try:
        with packet_path.open('rb') as reader:
            result = json.load(reader)
        streams = result['streams']
        packets = result['packets']
        if len(streams) != 1 or len(packets) < 2 or len(packets) > 1_000_000:
            return None
        stream = streams[0]
        if (int(stream['sample_rate']) != rate or stream['time_base'] != f'1/{rate}'
                or int(stream['duration_ts']) != total):
            return None
        rows = [(int(row['pts']), int(row['pos']), int(row['size']), int(row['duration']))
                for row in packets]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if rows[0][0] != 0 or rows[0][1] != audio_at:
        return None
    for left, right in zip(rows, rows[1:]):
        if (left[0] + left[3] != right[0] or left[1] + left[2] != right[1]
                or left[2] <= 0 or not 1 <= left[3] <= 65535):
            return None
    if (rows[-1][0] + rows[-1][3] != total or rows[-1][1] + rows[-1][2] != path.stat().st_size
            or rows[-1][2] <= 0 or not 1 <= rows[-1][3] <= 65535):
        return None
    starts = [row[0] for row in rows]
    indices = sorted({max(0, bisect_right(starts, i * total // 64) - 1) for i in range(64)})
    return b''.join(struct.pack('>QQH', rows[i][0], rows[i][1] - audio_at, rows[i][3])
                    for i in indices)


def prepare_file(path, cache, *, ffprobe, checkpoint=lambda: None, recovery=None, journal=None):
    """Atomically index an iPod FLAC copy; retain tags and compressed audio."""
    from .guard import hash_file
    path, cache = Path(path), Path(cache)
    checkpoint()
    layout = _layout(path)
    if not layout or layout[4] or not ffprobe or layout[3] < layout[2] * 30:
        return False
    audio_at, last_header, rate, total, _ = layout
    before = path.stat()
    key = hashlib.sha256(f'{path}:{before.st_size}:{before.st_mtime_ns}'.encode()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    unsupported = cache / (key + '.unsupported')
    if unsupported.exists():
        return False
    with tempfile.TemporaryDirectory(prefix='flac-', dir=cache) as scratch:
        local = Path(scratch) / 'source.flac'
        source_hash = hashlib.sha256()
        with path.open('rb') as reader, local.open('wb') as writer:
            while chunk := reader.read(1024 * 1024):
                checkpoint(); writer.write(chunk); source_hash.update(chunk)
            if recovery is not None:
                writer.flush(); os.fsync(writer.fileno())
        if path.stat().st_size != before.st_size or path.stat().st_mtime_ns != before.st_mtime_ns:
            raise OSError('FLAC source changed during preparation')
        points = _points(local, ffprobe, audio_at, rate, total, checkpoint)
        if not points:
            unsupported.touch(); return False
        block = bytes((0x83,)) + len(points).to_bytes(3, 'big') + points
        if before.st_size + len(block) > 0xffffffff:
            return False
        temporary = path.with_name('L' + uuid.uuid4().hex[:7] + '.TMP')
        owned = False
        try:
            digest = hashlib.sha256()
            with temporary.open('xb') as writer, local.open('rb') as reader:
                owned = True
                metadata = bytearray(reader.read(audio_at))
                if len(metadata) != audio_at or not metadata[last_header] & 128:
                    raise OSError('FLAC metadata changed during preparation')
                metadata[last_header] &= 127
                for chunk in (metadata, block):
                    writer.write(chunk); digest.update(chunk)
                while chunk := reader.read(1024 * 1024):
                    checkpoint(); writer.write(chunk); digest.update(chunk)
                writer.flush(); os.fsync(writer.fileno())
            checkpoint()
            if hash_file(temporary, before.st_size + len(block)) != digest.hexdigest():
                raise OSError('FLAC prepared copy did not verify')
            prepared = _layout(temporary)
            if (not prepared or prepared[0] != audio_at + len(block) or
                    prepared[3] != total or not prepared[4]):
                raise OSError('FLAC seek table has invalid geometry')
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise OSError('FLAC source changed during preparation')
            if recovery is not None:
                backup = cache / (uuid.uuid4().hex + '.flac-original')
                recovery.append(dict(kind='FLAC', path=str(path), backup=str(backup),
                    source_copy=str(local), temporary=str(temporary),
                    original_bytes=before.st_size, original_sha256=source_hash.hexdigest(),
                    atime_ns=before.st_atime_ns, mtime_ns=before.st_mtime_ns,
                    prepared_bytes=before.st_size + len(block), prepared_sha256=digest.hexdigest()))
                if journal is not None:
                    journal()
                local.replace(backup)
            temporary.replace(path)
        finally:
            if owned:
                temporary.unlink(missing_ok=True)
    return True
