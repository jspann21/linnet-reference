"""Apply a verified A1238 FAT directory-sector journal under a volume lock."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


SECTOR = 4096
DRIVE = r'\\.\F:'
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel.DeviceIoControl.restype = wintypes.BOOL
kernel.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                    ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
kernel.SetFilePointerEx.restype = wintypes.BOOL
kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel.ReadFile.restype = wintypes.BOOL
kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel.WriteFile.restype = wintypes.BOOL
kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
kernel.FlushFileBuffers.restype = wintypes.BOOL
kernel.CloseHandle.argtypes = [wintypes.HANDLE]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def control(handle, code):
    count = wintypes.DWORD()
    if not kernel.DeviceIoControl(handle, code, None, 0, None, 0, ctypes.byref(count), None):
        raise ctypes.WinError(ctypes.get_last_error())


def read_sector(handle, index):
    if not kernel.SetFilePointerEx(handle, index * SECTOR, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    backing = ctypes.create_string_buffer(SECTOR * 2)
    aligned = (ctypes.addressof(backing) + SECTOR - 1) & ~(SECTOR - 1)
    count = wintypes.DWORD()
    if not kernel.ReadFile(handle, ctypes.c_void_p(aligned), SECTOR, ctypes.byref(count), None) or count.value != SECTOR:
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.string_at(aligned, SECTOR)


def write_sector(handle, index, data):
    if len(data) != SECTOR or not kernel.SetFilePointerEx(handle, index * SECTOR, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    backing = ctypes.create_string_buffer(SECTOR * 2)
    aligned = (ctypes.addressof(backing) + SECTOR - 1) & ~(SECTOR - 1)
    ctypes.memmove(aligned, data, SECTOR)
    count = wintypes.DWORD()
    if not kernel.WriteFile(handle, ctypes.c_void_p(aligned), SECTOR, ctypes.byref(count), None) or count.value != SECTOR:
        raise ctypes.WinError(ctypes.get_last_error())


def identify(expected):
    result = subprocess.run([sys.executable, 'linnet', 'device', 'detect-retail', '--mount', 'F:\\'],
                            capture_output=True, text=True, check=True)
    identity = json.loads(result.stdout)
    if (identity['target_id'] != 'classic6g-n25' or
            identity['device_id'] != expected or
            identity['storage']['disk_serial'] != expected or
            identity['storage']['filesystem'] != 'FAT32' or
            identity['storage']['sector_bytes'] != SECTOR or
            identity['storage']['drive'].upper() != 'F:'):
        raise ValueError('Connected volume is not the planned A1238')


def durable_copy(source, destination):
    if destination.exists():
        if sha(destination.read_bytes()) != sha(source.read_bytes()):
            raise ValueError(f'Existing recovery journal differs: {destination}')
        return
    with source.open('rb') as reader, destination.open('xb') as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--mode', choices=('apply', 'restore', 'recover'), required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    args = parser.parse_args()
    if sha(args.plan.read_bytes()) != args.expected_plan_sha256.lower():
        raise ValueError('Plan hash changed')
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if plan['device_serial'] != '000A2700155D9C10' or plan['sector_bytes'] != SECTOR:
        raise ValueError('Plan is not for this A1238')
    rows = plan['sectors']
    if len(rows) != plan['sector_count'] or len({row['index'] for row in rows}) != len(rows):
        raise ValueError('Malformed sector plan')
    before = args.before.read_bytes()
    after = args.after.read_bytes()
    if len(before) != len(rows) * SECTOR or len(after) != len(before):
        raise ValueError('Malformed sector journal')
    for offset, row in enumerate(rows):
        if not (3586 <= row['index'] < 7276358):
            raise ValueError('Planned write is outside FAT data area')
        if (sha(before[offset*SECTOR:(offset+1)*SECTOR]) != row['before_sha256'] or
                sha(after[offset*SECTOR:(offset+1)*SECTOR]) != row['after_sha256']):
            raise ValueError('Sector journal hash mismatch')
    identify(plan['device_serial'])
    archive = Path(os.environ['LOCALAPPDATA']) / 'Linnet/AppleAlias' / sha(args.plan.read_bytes())[:16]
    archive.mkdir(parents=True, exist_ok=True)
    for source in (args.plan, args.before, args.after):
        durable_copy(source, archive / source.name)
    handle = kernel.CreateFileW(DRIVE, 0xc0000000, 3, None, 3, 0xa0000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    locked = False
    try:
        control(handle, 0x90018)  # FSCTL_LOCK_VOLUME
        locked = True
        boot = read_sector(handle, 0)
        if (sha(boot) != plan['boot_sha256'] or boot[67:71].hex() !=
                bytes.fromhex(plan['volume_serial'])[::-1].hex()):
            raise ValueError('FAT boot sector changed')
        old = before if args.mode == 'apply' else after
        new = after if args.mode == 'apply' else before
        recover_indices = set()
        for offset, row in enumerate(rows):
            current = read_sector(handle, row['index'])
            expected = old[offset*SECTOR:(offset+1)*SECTOR]
            if args.mode == 'recover':
                before_sector = before[offset*SECTOR:(offset+1)*SECTOR]
                after_sector = after[offset*SECTOR:(offset+1)*SECTOR]
                if current == after_sector:
                    recover_indices.add(row['index'])
                elif current != before_sector:
                    raise ValueError(f'Sector {row["index"]} is outside the recovery journal')
            elif current != expected:
                raise ValueError(f'Sector {row["index"]} changed since the plan')
        written = []
        try:
            for offset, row in enumerate(rows):
                index = row['index']
                if args.mode == 'recover' and index not in recover_indices:
                    continue
                written.append((offset, index))
                write_sector(handle, index, new[offset*SECTOR:(offset+1)*SECTOR])
            if not kernel.FlushFileBuffers(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            for offset, row in enumerate(rows):
                if read_sector(handle, row['index']) != new[offset*SECTOR:(offset+1)*SECTOR]:
                    raise IOError(f'Raw sector readback differs: {row["index"]}')
        except BaseException:
            for offset, index in reversed(written):
                write_sector(handle, index, old[offset*SECTOR:(offset+1)*SECTOR])
            if not kernel.FlushFileBuffers(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            for offset, index in written:
                if read_sector(handle, index) != old[offset*SECTOR:(offset+1)*SECTOR]:
                    raise IOError(f'Rollback readback differs: {index}')
            raise
        control(handle, 0x90020)  # FSCTL_DISMOUNT_VOLUME, while still locked
        print(json.dumps(dict(mode=args.mode, sectors=len(rows), archive=str(archive), verified=True)))
    finally:
        try:
            if locked:
                control(handle, 0x9001c)  # FSCTL_UNLOCK_VOLUME
        finally:
            kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
