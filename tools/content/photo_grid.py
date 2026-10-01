"""Host-prepared native photo grids, bound to the exact PIMG header."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import tempfile

from .photos import _crc, _title, FAT_PATH, MAX_FILE, MAX_PHOTOS, MAX_ALBUMS, MAX_STRINGS

GRID_SHAPES = {'classic6g-n25': (1238, 56, 56), 'video5g-m25': (25, 50, 38),
               'photo4g-p98': (98, 40, 30)}
DEVICE_PATH = '/.LINNET/PHOTOS/GRID.PGR'


def _pim_header(header):
    if (len(header) != 512 or header[:4] != b'LPIC' or
            struct.unpack_from('<HH', header, 4) != (0, 512) or any(header[72:508]) or
            _crc(header[:508]) != struct.unpack_from('<I', header, 508)[0]):
        raise ValueError('invalid grid PIMG binding header')
    flags, size, ac, pc, lc, tc, ao, po, lo, to, so, sb, mc, do = struct.unpack_from('<14I', header, 8)
    if (flags or not 1 <= ac <= MAX_ALBUMS or not 1 <= pc <= MAX_PHOTOS or
            not pc <= lc <= pc*6 or not 1 <= tc <= 1_000_000 or not 1 <= sb <= MAX_STRINGS or
            struct.unpack_from('<4H', header, 64) != (64, 64, 32, 1) or
            ao != 512 or po != ao+ac*32 or lo != po+pc*64 or to != lo+lc*24 or
            so != to+tc*12 or do != (so+sb+511)&~511 or
            size < do+pc*8192+tc or size > do+pc*8192+tc*2048 or size > MAX_FILE):
        raise ValueError('invalid grid PIMG binding ranges')
    return dict(size=size, albums=ac, photos=pc, levels=lc, photo_at=po,
                level_at=lo, string_at=so, string_bytes=sb, data_at=do)


def _catalog(prefix, strings, h):
    pool = strings[:h['string_bytes']]
    if not pool or pool[0] or pool[-1] or any(strings[len(pool):]):
        raise ValueError('invalid grid string pool or padding')
    for raw in pool.split(b'\0'):
        if raw:
            value = raw.decode('utf-8', errors='strict')
            if _title(value) != value:
                raise ValueError('invalid grid text')

    def text(at, n, path=False):
        if (n > (127 if path else 191) or at >= len(pool) or n >= len(pool)-at or
                pool[at+n] or (at and pool[at-1]) or b'\0' in pool[at:at+n]):
            raise ValueError('invalid grid text reference')
        value = pool[at:at+n].decode('ascii' if path else 'utf-8', errors='strict')
        if path:
            if (not value and at != 0) or (value and (not FAT_PATH.fullmatch(value) or not value.endswith(('.JPG', '.JPEG')))):
                raise ValueError('invalid grid JPEG reference')
        elif not value or _title(value) != value:
            raise ValueError('invalid grid title')
    intervals, count = [], 0
    for index in range(h['albums']):
        record = prefix[index*32:(index+1)*32]
        title, n, first, photos, parent, r0, r1, crc = struct.unpack('<8I', record)
        if (_crc(record[:28]) != crc or r0 or r1 or first != count or photos > h['photos']-count or
                (parent != 0xffffffff if not index else parent >= index)):
            raise ValueError('invalid grid album record')
        text(title, n);intervals.append((first, first+photos));count += photos
    if count != h['photos']:
        raise ValueError('grid album coverage mismatch')
    base, next_level = h['albums']*32, 0
    for index in range(h['photos']):
        record = prefix[base+index*64:base+(index+1)*64]
        album, title, n, source, sn, w, height, first, levels, thumb, thumb_crc, jb, jc, orient, reserved, crc = struct.unpack('<16I', record)
        if (_crc(record[:60]) != crc or reserved or album >= h['albums'] or
                not intervals[album][0] <= index < intervals[album][1] or
                not 1 <= w <= 16384 or not 1 <= height <= 16384 or w*height > 32_000_000 or
                first != next_level or not 1 <= levels <= 6 or levels > h['levels']-first or
                thumb != h['data_at']+index*8192 or
                (not sn and (source or jb or jc or orient)) or
                (sn and (not 1 <= jb <= 262144 or not 1 <= orient <= 8 or max(w,height) > 2048 or w*height > 4_000_000))):
            raise ValueError('invalid grid photo record')
        text(title, n);text(source, sn, True);next_level += levels
    if next_level != h['levels']:
        raise ValueError('grid level coverage mismatch')


def inspect_grid(path, *, package=None, target=None, checkpoint=None):
    check = checkpoint or (lambda: None)
    path = Path(path);size = path.stat().st_size
    if not 1024 <= size <= MAX_FILE:
        raise ValueError('invalid native grid file size')
    hashed = hashlib.sha256()
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        header = stream.read(1024)
        own, binding = header[:512], header[512:]
        if (len(header) != 1024 or own[:4] != b'LPGR' or
                struct.unpack_from('<HH', own, 4) != (1, 1024) or any(own[44:508]) or
                _crc(own[:508]) != struct.unpack_from('<I', own, 508)[0]):
            raise ValueError('invalid native grid header')
        total, model, w, height, count, prefix_bytes, string_bytes, data_at, crc, pim_size = struct.unpack_from('<IIHH6I', own, 8)
        shape = next((name for name, values in GRID_SHAPES.items() if values == (model,w,height)), None)
        h = _pim_header(binding)
        stride = w*height*2+4
        if (shape is None or (target is not None and shape != target) or total != size or count != h['photos'] or
                pim_size != h['size'] or prefix_bytes != h['level_at']-512 or
                string_bytes != h['data_at']-h['string_at'] or
                data_at != (1024+prefix_bytes+string_bytes+511)&~511 or size != data_at+count*stride):
            raise ValueError('invalid native grid contract/ranges')
        if package is not None:
            package = Path(package)
            with package.open('rb') as pim:
                if os.fstat(pim.fileno()).st_size != pim_size or pim.read(512) != binding:
                    raise ValueError('native grid belongs to a different PIMG')
        check();metadata = stream.read(data_at-1024)
        if len(metadata) != data_at-1024 or _crc(metadata) != crc or any(metadata[prefix_bytes+string_bytes:]):
            raise ValueError('native grid catalog CRC/padding mismatch')
        _catalog(metadata[:prefix_bytes], metadata[prefix_bytes:prefix_bytes+string_bytes], h)
        hashed.update(header);hashed.update(metadata)
        for first in range(0,count,128):
            check();block = stream.read(min(128,count-first)*stride)
            if len(block) != min(128,count-first)*stride:
                raise ValueError('truncated native grid pixels')
            hashed.update(block)
            for offset in range(0,len(block),stride):
                if _crc(block[offset:offset+stride-4]) != struct.unpack_from('<I',block,offset+stride-4)[0]:
                    raise ValueError('native grid thumbnail CRC mismatch')
        after = os.fstat(stream.fileno())
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('native grid changed during validation')
    return dict(format='LPGR',passed=True,target=shape,photos=count,bytes=size,sha256=hashed.hexdigest(),
                width=w,height=height,metadata_bytes=prefix_bytes+string_bytes,
                output=str(path),device_path=DEVICE_PATH)


def write_grid(package, output, target, pixels, checkpoint):
    package, output = Path(package), Path(output)
    model,w,height = GRID_SHAPES[target]
    with package.open('rb') as pim:
        binding = pim.read(512);h = _pim_header(binding)
        if os.fstat(pim.fileno()).st_size != h['size']:
            raise ValueError('PIMG size changed before native grid preparation')
        prefix = pim.read(h['level_at']-512)
        pim.seek(h['string_at']);strings = pim.read(h['data_at']-h['string_at'])
    metadata = prefix+strings
    data_at = (1024+len(metadata)+511)&~511
    metadata += bytes(data_at-1024-len(metadata))
    total = data_at+h['photos']*(w*height*2+4)
    header = bytearray(512)
    struct.pack_into('<4sHHIIHH6I',header,0,b'LPGR',1,1024,total,model,w,height,h['photos'],
                     len(prefix),len(strings),data_at,_crc(metadata),h['size'])
    struct.pack_into('<I',header,508,_crc(header[:508]))
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,name = tempfile.mkstemp(prefix=output.name+'.',suffix='.tmp',dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(header);stream.write(binding);stream.write(metadata);pixels.seek(0)
            while chunk := pixels.read(1024*1024):
                checkpoint();stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
        report = inspect_grid(temporary,package=package,target=target,checkpoint=checkpoint)
        checkpoint();temporary.replace(output);report['output'] = str(output)
        return report
    finally:
        temporary.unlink(missing_ok=True)
