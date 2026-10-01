"""Build sparse MP3 decoder checkpoints on the computer for fast device seeks."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
SENTINEL = b'LNMP3SEEKDATA\0\0\0'
MAGIC = b'LNMP3IX!'
RECORD_BYTES = 560


@lru_cache(maxsize=1)
def executable():
    bundled = Path(getattr(sys, '_MEIPASS', ROOT)) / 'mp3-index.exe'
    if getattr(sys, 'frozen', False):
        if not bundled.is_file():
            raise RuntimeError('MP3 preparation tool is missing from this Media Manager')
        return bundled
    from tools.studio.build import toolchain
    compiler = toolchain()['compiler']
    sources = ['tools/content/mp3_index.c', 'services/audio/mp3/mp3.c']
    sources += ['third_party/libmad/' + name + '.c' for name in
                ('bit', 'frame', 'huffman', 'layer12', 'layer3', 'stream', 'synth')]
    flags = ['-O3', '-fwrapv', '-fno-strict-aliasing', '-DLINNET_PROFILE_RELEASE=1', '-I.']
    digest = hashlib.sha256(compiler['sha256'].encode())
    digest.update('\0'.join(flags).encode())
    inputs = set(sources)
    for folder in ('services/audio/mp3', 'third_party/libmad', 'boot/include', 'hal/api'):
        inputs.update(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).rglob('*.h'))
    for name in sorted(inputs):
        digest.update(name.encode()); digest.update((ROOT / name).read_bytes())
    directory = ROOT / 'out/mp3-index' / digest.hexdigest()[:24]
    destination = directory / ('mp3-index.exe' if os.name == 'nt' else 'mp3-index')
    if destination.is_file():
        return destination
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (uuid.uuid4().hex + destination.suffix)
    try:
        result = subprocess.run([compiler['path'], *flags, *sources, '-o', str(temporary)],
                                cwd=ROOT, capture_output=True, text=True, timeout=120,
                                creationflags=NO_WINDOW)
        if result.returncode:
            raise RuntimeError('MP3 preparation build failed: ' + result.stderr[-4000:])
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def original_size(path, size=None):
    """Recognize the exact Linnet trailer and return its source prefix length."""
    path = Path(path)
    size = path.stat().st_size if size is None else size
    if size < 16 + 2 * RECORD_BYTES + 64:
        return None
    with path.open('rb') as reader:
        reader.seek(size - 64)
        footer = reader.read(64)
        if (len(footer) != 64 or footer[:8] != MAGIC or any(footer[52:60]) or
                zlib.crc32(footer[:60]) != struct.unpack_from('<I', footer, 60)[0]):
            return None
        original, count, samples, rate, channels, lead, tail, total, frames = struct.unpack_from(
            '<QIIIIIIQI', footer, 8)
        if (count < 2 or count > 1_000_000 or samples not in (576, 1152) or
                rate not in (32000, 44100, 48000, 16000, 22050, 24000, 8000, 11025, 12000) or
                channels not in (1, 2) or not total or
                frames * samples != total + lead + tail or
                original + 16 + count * RECORD_BYTES + 64 != size):
            return None
        reader.seek(original)
        if reader.read(16) != SENTINEL:
            return None
        for index in range(count):
            record = reader.read(RECORD_BYTES)
            if (len(record) != RECORD_BYTES or
                    zlib.crc32(record[:556]) != struct.unpack_from('<I', record, 556)[0]):
                return None
    return original


def same_original(source, destination, *, checkpoint=lambda: None):
    source, destination = Path(source), Path(destination)
    if not destination.is_file():
        return False
    size = original_size(destination)
    if size is None or source.stat().st_size != size:
        return False
    with source.open('rb') as left, destination.open('rb') as right:
        while size:
            checkpoint()
            count = min(size, 1024 * 1024)
            if left.read(count) != right.read(count):
                return False
            size -= count
    return True


def import_suffix(source, *, checkpoint=lambda: None):
    """Return prepared bytes only for complete long gapless MP3s without EOF tags."""
    source = Path(source)
    before = source.stat()
    if (before.st_size < 8 * 1024 * 1024 or before.st_size > 0xffffffff - 10000000 or
            original_size(source, before.st_size) is not None):
        return b''
    with source.open('rb') as reader:
        reader.seek(-128, 2)
        if reader.read(3) == b'TAG':
            return b''
        reader.seek(-32, 2)
        if reader.read(8) == b'APETAGEX':
            return b''
        reader.seek(-9, 2)
        if reader.read(9) in (b'LYRICS200', b'LYRICSEND'):
            return b''
    checkpoint()
    with tempfile.TemporaryDirectory(prefix='mp3-index-') as folder:
        records = Path(folder) / 'records.bin'
        try:
            result = subprocess.run([str(executable()), str(source), str(records)],
                                    capture_output=True, text=True, timeout=120,
                                    creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            checkpoint()
            return b''
        checkpoint()
        if result.returncode:
            return b''
        info = json.loads(result.stdout)
        count = info['records']
        if count < 2 or count > 1_000_000 or records.stat().st_size != count * RECORD_BYTES:
            return b''
        body = records.read_bytes()
        if before.st_size + len(SENTINEL) + len(body) + 64 > 0xffffffff:
            return b''
        footer = bytearray(64)
        footer[:8] = MAGIC
        struct.pack_into('<QIIIIIIQI', footer, 8, before.st_size, count,
                         info['samples_per_frame'], info['rate'], info['channels'],
                         info['lead_trim'], info['tail_trim'], info['total_frames'],
                         info['compressed_frames'])
        struct.pack_into('<I', footer, 60, zlib.crc32(footer[:60]))
        if (source.stat().st_size, source.stat().st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError(f'MP3 changed during checkpoint preparation: {source}')
        return SENTINEL + body + footer
