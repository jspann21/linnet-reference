"""PVID streaming converter and strict bounded validator."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

from . import pvid_lz4

HEADER = 512
INDEX = 32
MAX_FILE = 0x7fffffff
MAX_RECORD = 90112
MAX_FRAMES = 1_000_000
RATE = 48000
FPS = (24, 25, 30, 60)
DEVICE_PATH = '/LINNET/VIDEOS/CURRENT.PVD'
DEFAULT_COST = dict(read_us_per_byte=0.125, raw_us_per_pixel=0.025,
                    copy_us_per_pixel=0.025, rle_us_per_run=0.4,
                    delta_us_per_tile=4.0, fixed_us=400.0, present_us=3000.0,
                    measured=False)


def _crc(data):
    return zlib.crc32(data) & 0xffffffff


def _align(n):
    return (n + 511) & ~511


def _exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            break
        chunks.extend(part)
    return bytes(chunks)


def _tiles(width, height):
    for y in range(0, height, 16):
        for x in range(0, width, 16):
            yield x, y, min(16, width-x), min(16, height-y)


def _tile(frame, width, rect):
    x, y, w, h = rect
    return b''.join(frame[((y+r)*width+x)*2:((y+r)*width+x+w)*2] for r in range(h))


def _encodings(frame, previous, width, height, key):
    yield 0, frame, width*height
    runs = bytearray()
    last, count = frame[:2], 0
    for at in range(0, len(frame), 2):
        pixel = frame[at:at+2]
        if pixel != last or count == 65535:
            runs.extend(struct.pack('<H', count) + last)
            last, count = pixel, 0
        count += 1
    runs.extend(struct.pack('<H', count) + last)
    if len(runs) < len(frame):
        yield 3, bytes(runs), len(runs)//4
    if key:
        return
    if frame == previous:
        yield 1, b'', 0
        return
    delta, changed = bytearray(), 0
    for n, rect in enumerate(_tiles(width, height)):
        tile = _tile(frame, width, rect)
        if tile != _tile(previous, width, rect):
            changed += 1
            delta.extend(struct.pack('<HH', n, 0) + tile)
    if len(delta)+4 < len(frame):
        yield 2, struct.pack('<I', changed) + delta, changed


def _model(value):
    model = dict(DEFAULT_COST)
    if value is not None:
        unknown = set(value) - set(model) - {'measurement_id'}
        if unknown:
            raise ValueError(f'unknown cost fields: {sorted(unknown)}')
        model.update(value)
    for name, number in model.items():
        if name in ('measured', 'measurement_id'):
            continue
        if not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
            raise ValueError(f'invalid cost parameter {name}')
    if model['measured'] and (not model.get('measurement_id') or value is None or
                             any(k not in value for k in DEFAULT_COST)):
        raise ValueError('measured profile requires all explicit costs and measurement_id')
    return model


def _cost(model, kind, bytes_, work, pixels):
    decode = (work*model['raw_us_per_pixel'] if kind == 0 else
              work*model['rle_us_per_run'] if kind == 3 else
              pixels*model['copy_us_per_pixel'] + work*model['delta_us_per_tile'])
    return model['fixed_us'] + model['present_us'] + bytes_*model['read_us_per_byte'] + decode


def compile_video(source, output, *, fps=24, width=220, height=176,
                  key_interval=24, cost_model=None, ffmpeg=None, max_frames=None):
    """Convert existing media; stream ffmpeg frames/PCM and atomically publish PVID.

    cost_model estimates are explicitly unqualified unless backed by caller-supplied
    device measurements. Every selected record must fit its declared frame budget.
    """
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or not source.is_file():
        raise ValueError('source must exist and differ from output')
    if any(type(v) is not int for v in (fps, width, height, key_interval)):
        raise ValueError('dimensions, frame rate and key interval must be integers')
    if fps not in FPS or not 1 <= width <= 220 or not 1 <= height <= 176:
        raise ValueError('unsupported dimensions or frame rate')
    if not 1 <= key_interval <= fps*10 or (max_frames is not None and (type(max_frames) is not int or max_frames < 1)):
        raise ValueError('invalid key interval or frame limit')
    model = _model(cost_model)
    executable = ffmpeg or shutil.which('ffmpeg')
    if not executable:
        raise ValueError('ffmpeg is required')
    probe = str(Path(executable).with_name('ffprobe' + Path(executable).suffix))
    result = subprocess.run([probe, '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                            check=True, capture_output=True, text=True)
    streams = json.loads(result.stdout)['streams']
    if not any(s.get('codec_type') == 'video' for s in streams):
        raise ValueError('source contains no video')
    has_audio = any(s.get('codec_type') == 'audio' for s in streams)
    output.parent.mkdir(parents=True, exist_ok=True)
    processes = []
    with tempfile.TemporaryDirectory(prefix='pvid-', dir=output.parent) as temporary:
        tmp = Path(temporary)
        with (tmp/'video.log').open('wb') as vlog, (tmp/'audio.log').open('wb') as alog:
            base = [str(executable), '-v', 'error', '-nostdin', '-i', str(source)]
            vf = (f'fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,'
                  f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1')
            video = subprocess.Popen(base + ['-map', '0:v:0', '-an', '-vf', vf,
                '-pix_fmt', 'rgb565le', '-f', 'rawvideo', 'pipe:1'], stdout=subprocess.PIPE, stderr=vlog)
            processes.append(video)
            audio = None
            try:
                if has_audio:
                    audio = subprocess.Popen(base + ['-map', '0:a:0', '-vn', '-af', 'aresample=48000:first_pts=0',
                        '-ac', '2', '-ar', str(RATE), '-f', 's16le', 'pipe:1'], stdout=subprocess.PIPE, stderr=alog)
                    processes.append(audio)
                count, offset, keyframe, worst, largest = 0, 0, 0, 0.0, 0
                types = [0]*4
                previous = None
                samples = RATE//fps
                with (tmp/'records').open('wb') as records, (tmp/'index').open('wb') as index:
                    while max_frames is None or count < max_frames:
                        frame = _exact(video.stdout, width*height*2)
                        if not frame:
                            break
                        if len(frame) != width*height*2:
                            raise ValueError('ffmpeg produced a partial video frame')
                        pcm = _exact(audio.stdout, samples*4) if audio else b''
                        pcm += bytes(samples*4-len(pcm))
                        choices = []
                        for kind, payload, work in _encodings(frame, previous, width, height,
                                                            count % key_interval == 0):
                            size = _align(32+len(payload)+len(pcm))
                            choices.append((_cost(model, kind, size, work, width*height), kind, payload, size))
                        cost, kind, payload, size = min(choices, key=lambda c: (c[0], c[3], c[1]))
                        if cost > 1_000_000/fps or size > MAX_RECORD:
                            raise ValueError(f'frame {count} exceeds declared frame budget: {cost:.1f} us')
                        if kind in (0, 3):
                            keyframe = count
                        body = payload + pcm
                        record = struct.pack('<4s7I', b'FRAM', count, kind, len(payload),
                                             count*samples, samples, _crc(frame), _crc(body)) + body
                        record += bytes(size-len(record))
                        records.write(record)
                        index.write(struct.pack('<8I', offset, size, count, count*samples,
                                                samples, keyframe, _crc(record), 0))
                        offset += size
                        count += 1
                        if count > MAX_FRAMES or _align(HEADER+count*INDEX)+offset > MAX_FILE or count*samples > 0xffffffff:
                            raise ValueError('PVID exceeds file/sample bounds')
                        types[kind] += 1
                        worst, largest = max(worst, cost), max(largest, size)
                        previous = frame
                if not count:
                    raise ValueError('source produced no frames')
                if max_frames is None and video.wait() != 0:
                    raise ValueError('ffmpeg video conversion failed: ' + (tmp/'video.log').read_text(errors='replace')[-2000:])
                # Audio may exceed video duration; stop after the exact displayed interval.
                if audio and audio.poll() not in (None, 0):
                    raise ValueError('ffmpeg audio conversion failed')
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if process.stdout:
                        process.stdout.close()
        data_at = _align(HEADER+count*INDEX)
        with (tmp/'result').open('w+b') as dest, (tmp/'index').open('rb') as index:
            dest.write(bytes(HEADER))
            metadata_crc = 0
            for _ in range(count):
                fields = list(struct.unpack('<8I', index.read(INDEX)))
                fields[0] += data_at
                entry = struct.pack('<8I', *fields)
                dest.write(entry)
                metadata_crc = zlib.crc32(entry, metadata_crc)
            pad = bytes(data_at-dest.tell())
            dest.write(pad)
            metadata_crc = zlib.crc32(pad, metadata_crc) & 0xffffffff
            with (tmp/'records').open('rb') as records:
                shutil.copyfileobj(records, dest, 1024*1024)
            header = bytearray(HEADER)
            struct.pack_into('<4s13I', header, 0, b'PVID', HEADER, 0, dest.tell(),
                             width, height, fps, RATE, count, HEADER, data_at, largest,
                             metadata_crc, key_interval)
            struct.pack_into('<I', header, 508, _crc(header[:508]))
            dest.seek(0)
            dest.write(header)
            dest.flush()
            os.fsync(dest.fileno())
        report = inspect(tmp/'result')
        os.replace(tmp/'result', output)
    report.update(path=str(output), source=str(source), cost_model=model,
                  qualification='device-measured budget' if model['measured'] else 'unqualified estimate',
                  worst_declared_frame_us=worst, frame_budget_us=1_000_000/fps,
                  source_audio=has_audio)
    return report


def inspect(path):
    """Validate every index, record, decoded frame, PCM interval, CRC and padding."""
    return _inspect(path)


def _inspect(path, frame_visitor=None):
    path = Path(path)
    length = path.stat().st_size
    with path.open('rb') as f:
        header = f.read(HEADER)
        if (len(header) != HEADER or header[:4] != b'PVID' or
            struct.unpack_from('<I', header, 4)[0] != HEADER):
            raise ValueError('invalid PVID header')
        flags, size, width, height, fps, rate, count, index_at, data_at, maximum, crc, interval = struct.unpack_from('<12I', header, 8)
        if (flags or size != length or not HEADER < size <= MAX_FILE or
            not 1 <= width <= 220 or not 1 <= height <= 176 or fps not in FPS or rate != RATE or
            not 1 <= count <= MAX_FRAMES or index_at != HEADER or data_at != _align(HEADER+count*INDEX) or
            data_at >= size or maximum > MAX_RECORD or maximum < 512 or maximum % 512 or
            not 1 <= interval <= fps*10 or count*(RATE//fps) > 0xffffffff or
            any(header[56:508]) or _crc(header[:508]) != struct.unpack_from('<I', header, 508)[0]):
            raise ValueError('invalid PVID bounds/header CRC')
        got = 0
        remaining = data_at-HEADER
        while remaining:
            part = f.read(min(4096, remaining))
            if not part:
                raise ValueError('truncated index')
            got = zlib.crc32(part, got)
            remaining -= len(part)
        if got & 0xffffffff != crc:
            raise ValueError('index CRC mismatch')
        f.seek(HEADER+count*INDEX)
        if any(f.read(data_at-(HEADER+count*INDEX))):
            raise ValueError('nonzero index padding')
        previous, expected, last_key, largest = None, data_at, 0, 0
        types = [0]*5
        samples = RATE//fps
        rects = list(_tiles(width, height))
        for n in range(count):
            f.seek(HEADER+n*INDEX)
            offset, size, frame_no, first, nsamples, key, record_crc, reserved = struct.unpack('<8I', f.read(INDEX))
            if (offset != expected or size < 512 or size > maximum or size % 512 or offset+size > length or
                frame_no != n or first != n*samples or nsamples != samples or key > n or n-key >= interval or reserved):
                raise ValueError(f'invalid index {n}')
            f.seek(offset)
            record = f.read(size)
            if _crc(record) != record_crc:
                raise ValueError(f'record CRC mismatch {n}')
            magic, frame_no, kind, vbytes, first, nsamples, frame_crc, payload_crc = struct.unpack_from('<4s7I', record)
            end = 32+vbytes+samples*4
            if (magic != b'FRAM' or frame_no != n or kind > 4 or first != n*samples or nsamples != samples or
                end > size or _align(end) != size or _crc(record[32:end]) != payload_crc or any(record[end:])):
                raise ValueError(f'invalid record {n}')
            video = record[32:32+vbytes]
            if kind == 4:
                if not 0 < vbytes < width*height*2:
                    raise ValueError('invalid LZ4 payload size')
                decoded = pvid_lz4.decompress(video, width*height*2)
            elif kind == 0:
                if vbytes != width*height*2:
                    raise ValueError('invalid raw length')
                decoded = video
            elif kind == 3:
                if not vbytes or vbytes % 4 or vbytes > width*height*4:
                    raise ValueError('invalid RLE length')
                decoded = bytearray()
                for at in range(0, vbytes, 4):
                    run = struct.unpack_from('<H', video, at)[0]
                    if not run or len(decoded)+run*2 > width*height*2:
                        raise ValueError('invalid RLE run')
                    decoded.extend(video[at+2:at+4]*run)
                if len(decoded) != width*height*2:
                    raise ValueError('incomplete RLE frame')
            else:
                if previous is None:
                    raise ValueError('first frame is not independent')
                decoded = bytearray(previous)
                if kind == 1:
                    if vbytes:
                        raise ValueError('repeat payload must be empty')
                else:
                    if vbytes < 4:
                        raise ValueError('short delta header')
                    tiles = struct.unpack_from('<I', video)[0]
                    if not 1 <= tiles <= len(rects):
                        raise ValueError('invalid delta tile count')
                    at, last = 4, -1
                    for _ in range(tiles):
                        if at+4 > vbytes:
                            raise ValueError('short delta record')
                        tile, reserved = struct.unpack_from('<HH', video, at)
                        at += 4
                        if reserved or tile <= last or tile >= len(rects):
                            raise ValueError('invalid delta tile')
                        x, y, w, h = rects[tile]
                        if at+w*h*2 > vbytes:
                            raise ValueError('short delta pixels')
                        for row in range(h):
                            start = ((y+row)*width+x)*2
                            decoded[start:start+w*2] = video[at:at+w*2]
                            at += w*2
                        last = tile
                    if at != vbytes:
                        raise ValueError('trailing delta payload')
            if kind in (0, 3, 4):
                last_key = n
            if key != last_key or (n % interval == 0 and key != n) or _crc(decoded) != frame_crc:
                raise ValueError(f'keyframe or decoded CRC mismatch {n}')
            if frame_visitor:
                frame_visitor(n, record, bytes(decoded))
            previous = decoded
            expected += size
            largest = max(largest, size)
            types[kind] += 1
        if expected != length or largest != maximum:
            raise ValueError('trailing bytes or noncanonical maximum record')
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            digest.update(block)
    names = ('raw', 'repeat', 'tile_delta', 'rle', 'lz4')
    return dict(path=str(path), format='PVID', file_bytes=length,
                width=width, height=height, fps=fps, sample_rate=rate,
                frames=count, samples=count*samples, duration_seconds=count/fps,
                max_record_bytes=maximum, key_interval=interval,
                record_types=dict(zip(names, types)),
                sha256=digest.hexdigest(), validation='passed')


def repack_spatial(source, output):
    """Compress PVID spatially with exact RGB565/PCM and all CRCs.

    Independent LZ4 frames replace source records only when they save sectors.
    This offline byte reduction is unqualified until measured on the device.
    """
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or not source.is_file():
        raise ValueError('source must exist and differ from output')
    original = inspect(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    count, fps = original['frames'], original['fps']
    data_at = _align(HEADER + count*INDEX)
    samples = RATE//fps
    pcm_digest, frame_digest = hashlib.sha256(), hashlib.sha256()
    largest, last_key, compressed_count = 0, 0, 0
    with tempfile.TemporaryDirectory(prefix='pvid-spatial-', dir=output.parent) as temporary:
        tmp = Path(temporary)
        with (tmp/'result').open('w+b') as dest, (tmp/'index').open('w+b') as index:
            dest.write(bytes(HEADER))
            dest.seek(data_at)

            def frame_visitor(n, record, decoded):
                nonlocal largest, last_key, compressed_count
                fields = list(struct.unpack_from('<4s7I', record))
                kind, video_bytes = fields[2:4]
                pcm = record[32+video_bytes:32+video_bytes+samples*4]
                frame_digest.update(decoded)
                pcm_digest.update(pcm)
                compressed = pvid_lz4.compress(decoded)
                size = _align(32+len(compressed)+len(pcm))
                if size < len(record) and len(compressed) < len(decoded):
                    # Validate the encoder before constructing the new record.
                    if pvid_lz4.decompress(compressed, len(decoded)) != decoded:
                        raise ValueError('LZ4 encoder reconstruction mismatch')
                    kind = 4
                    fields[2:4] = kind, len(compressed)
                    body = compressed + pcm
                    fields[7] = _crc(body)
                    record = struct.pack('<4s7I', *fields) + body
                    record += bytes(size-len(record))
                    compressed_count += 1
                if kind in (0, 3, 4):
                    last_key = n
                index.write(struct.pack('<8I', dest.tell(), len(record), n,
                                        n*samples, samples, last_key, _crc(record), 0))
                dest.write(record)
                largest = max(largest, len(record))

            verified = _inspect(source, frame_visitor)
            if verified != original:
                raise ValueError('source changed during spatial repack')
            file_bytes = dest.tell()
            index.seek(0)
            dest.seek(HEADER)
            metadata_crc = 0
            for block in iter(lambda: index.read(4096), b''):
                dest.write(block)
                metadata_crc = zlib.crc32(block, metadata_crc)
            padding = bytes(data_at-dest.tell())
            dest.write(padding)
            metadata_crc = zlib.crc32(padding, metadata_crc) & 0xffffffff
            header = bytearray(HEADER)
            struct.pack_into('<4s13I', header, 0, b'PVID', HEADER, 0, file_bytes,
                             original['width'], original['height'], fps, RATE, count,
                             HEADER, data_at, largest, metadata_crc, original['key_interval'])
            struct.pack_into('<I', header, 508, _crc(header[:508]))
            dest.seek(0)
            dest.write(header)
            dest.flush()
            os.fsync(dest.fileno())
        report = inspect(tmp/'result')
        os.replace(tmp/'result', output)
    report.update(path=str(output), source=str(source), source_sha256=original['sha256'],
                  source_file_bytes=original['file_bytes'], compressed_frames=compressed_count,
                  bytes_saved=original['file_bytes']-report['file_bytes'],
                  decoded_frames_sha256=frame_digest.hexdigest(), pcm_sha256=pcm_digest.hexdigest(),
                  qualification='unqualified spatial repack; device measurement required')
    return report
