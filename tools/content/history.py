"""Prepare an offline JRN1-to-paged-history migration; never writes input banks.

Output contains verified original backups, complete replacement banks and a
hash-bound plan. Installing/growing the live FAT files is a separate operation
owned by the device publication tool. Keep both original backups until the new
pair is installed and verified. Never install just one bank beside a JRN1 bank.
"""
from pathlib import Path
import hashlib
import json
import os
import struct
import time
import uuid
import zlib

PAGE_BYTES = 4096
PAGE_COUNT = 1024
PAGE_RECORDS = 125
BANK_BYTES = (PAGE_COUNT + 1) * PAGE_BYTES


def validate_superblock(data: bytes) -> bytes:
    if len(data) != PAGE_BYTES:
        raise ValueError('history superblock must be4096 bytes')
    expected = (b'JH2\0', 2, 64, BANK_BYTES, PAGE_COUNT, PAGE_RECORDS, 32)
    if struct.unpack_from('<4sHHIIII', data) != expected or any(data[40:4092]):
        raise ValueError('invalid paged history geometry/reserved bytes')
    if struct.unpack_from('<I', data, 4092)[0] != zlib.crc32(data[:4092]):
        raise ValueError('invalid history superblock CRC')
    return data[24:40]


def validate_paged_bank(data: bytes) -> dict:
    """Full staged-bank verification, including lookup reachability and IDs."""
    if len(data) != BANK_BYTES:
        raise ValueError('invalid paged bank length')
    epoch = validate_superblock(data[:PAGE_BYTES])
    counts, records = [], {}
    for index in range(PAGE_COUNT):
        page = data[(index + 1) * PAGE_BYTES:(index + 2) * PAGE_BYTES]
        magic, version, header, page_index, _, count, _ = struct.unpack_from('<4sHHIIII', page)
        if (magic, version, header, page_index) != (b'JP2\0', 2, 64, index) or count > PAGE_RECORDS:
            raise ValueError('invalid history page geometry')
        if page[40:56] != epoch or any(page[56:64]) or any(page[64 + count * 32:4092]):
            raise ValueError('invalid history page epoch/padding')
        if int.from_bytes(page[24:40], 'little') != (1 << count) - 1:
            raise ValueError('invalid history occupancy bitmap')
        if struct.unpack_from('<I', page, 4092)[0] != zlib.crc32(page[:4092]):
            raise ValueError('invalid history page CRC')
        counts.append(count)
        for slot in range(count):
            record = struct.unpack_from('<QIIQQ', page, 64 + slot * 32)
            track_id, flags, _, bookmark, resume = record
            if track_id in records or flags & ~7 or (not flags & 2 and bookmark) or (not flags & 4 and resume):
                raise ValueError('invalid or duplicate history record')
            records[track_id] = (index, record)
    # An ID must be reachable before the first non-full page in its probe chain.
    for track_id, (index, _) in records.items():
        probe = page_hash(track_id)
        while probe != index:
            if counts[probe] != PAGE_RECORDS:
                raise ValueError('unreachable history record')
            probe = (probe + 1) & 1023
    return {'epoch': epoch.hex(), 'records': [record for _, record in records.values()]}


def page_hash(track_id: int) -> int:
    x = (track_id & 0xffffffff) ^ (track_id >> 32)
    x ^= x >> 16
    x = (x * 0x7feb352d) & 0xffffffff
    x ^= x >> 15
    x = (x * 0x846ca68b) & 0xffffffff
    return (x ^ (x >> 16)) & 1023


def _legacy(data: bytes):
    if len(data) != 4608 or data[:8] != b'JRN1\x01\x00\x40\x00':
        raise ValueError('invalid JRN1 geometry')
    if struct.unpack_from('<I', data, 4604)[0] != zlib.crc32(data[:4604]):
        raise ValueError('invalid JRN1 CRC')
    sequence, count = struct.unpack_from('<II', data, 8)
    if count > 128 or any(data[52:64]) or any(data[64 + count * 32:4604]):
        raise ValueError('invalid JRN1 padding/count')
    records = [struct.unpack_from('<QIIQQ', data, 64 + i * 32) for i in range(count)]
    if len({r[0] for r in records}) != count:
        raise ValueError('duplicate JRN1 IDs')
    for _, flags, _, bookmark, resume in records:
        if flags & ~7 or (not flags & 2 and bookmark) or (not flags & 4 and resume):
            raise ValueError('invalid JRN1 record')
    return sequence, records


def select_legacy(a: bytes, b: bytes):
    states = []
    for data in (a, b):
        try:
            states.append(_legacy(data))
        except ValueError:
            states.append(None)
    if not any(states):
        raise ValueError('both JRN1 banks invalid; migration refused')
    if not states[0]:
        return 1, states[1][1]
    if not states[1]:
        return 0, states[0][1]
    difference = (states[1][0] - states[0][0]) & 0xffffffff
    if difference == 0x80000000 or (difference == 0 and a != b):
        raise ValueError('JRN1 sequence conflict; migration refused')
    bank = int(0 < difference < 0x80000000)
    return bank, states[bank][1]


def build_paged_bank(records, epoch: bytes) -> bytes:
    """Host-memory builder; bounded128000 records, all stable IDs retained."""
    if len(epoch) != 16 or len(records) > PAGE_COUNT * PAGE_RECORDS:
        raise ValueError('invalid epoch or capacity')
    if len({r[0] for r in records}) != len(records):
        raise ValueError('duplicate IDs')
    buckets = [[] for _ in range(PAGE_COUNT)]
    for record in records:
        track_id, flags, count, bookmark, resume = record
        if not 0 <= track_id < 1 << 64 or not 0 <= count < 1 << 32 or flags & ~7 or flags < 0:
            raise ValueError('invalid record')
        if not 0 <= bookmark < 1 << 64 or not 0 <= resume < 1 << 64 or (not flags & 2 and bookmark) or (not flags & 4 and resume):
            raise ValueError('invalid position')
        index = page_hash(track_id)
        for _ in range(PAGE_COUNT):
            if len(buckets[index]) < PAGE_RECORDS:
                buckets[index].append(record)
                break
            index = (index + 1) & 1023
        else:
            raise ValueError('capacity exhausted')
    bank = bytearray(BANK_BYTES)
    struct.pack_into('<4sHHIIII16s', bank, 0, b'JH2\0', 2, 64, BANK_BYTES, PAGE_COUNT, PAGE_RECORDS, 32, epoch)
    struct.pack_into('<I', bank, 4092, zlib.crc32(bank[:4092]))
    for index, bucket in enumerate(buckets):
        start = (index + 1) * PAGE_BYTES
        struct.pack_into('<4sHHIIII', bank, start, b'JP2\0', 2, 64, index, 0, len(bucket), 0)
        bank[start + 40:start + 56] = epoch
        for slot, record in enumerate(bucket):
            bank[start + 24 + slot // 8] |= 1 << (slot & 7)
            struct.pack_into('<QIIQQ', bank, start + 64 + slot * 32, *record)
        struct.pack_into('<I', bank, start + 4092, zlib.crc32(bank[start:start + 4092]))
    return bytes(bank)


def prepare_history_migration(bank_a: Path, bank_b: Path, output: Path) -> dict:
    """Creates a new staging directory only; input files remain byte-for-byte."""
    inputs = [Path(bank_a).resolve(), Path(bank_b).resolve()]
    if inputs[0] == inputs[1]:
        raise ValueError('two distinct input banks required')
    originals = [p.read_bytes() for p in inputs]
    selected, records = select_legacy(*originals)
    epoch = uuid.uuid4().bytes
    replacement = build_paged_bank(records, epoch)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = {'format': 'Linnet history migration', 'version': 1, 'source_format': 'JRN1',
            'target_format': 'JH2/JP2', 'epoch': epoch.hex(), 'records_preserved': len(records),
            'selected_source_bank': selected, 'target_bank_bytes': BANK_BYTES,
            'capacity_records': PAGE_COUNT * PAGE_RECORDS, 'inputs': [], 'outputs': [],
            'installation': 'Not installed. Grow and replace both live banks only after retaining verified backups; verify the complete pair before enabling paged history.'}
    for i in range(2):
        backup = output / f'MUSIC{i}.JRN1.backup'
        backup.write_bytes(originals[i])
        if backup.read_bytes() != originals[i]:
            raise OSError('backup readback mismatch')
        target = output / f'MUSIC{i}.BIN'
        target.write_bytes(replacement)
        if target.read_bytes() != replacement:
            raise OSError('replacement readback mismatch')
        plan['inputs'].append({'path': str(inputs[i]), 'backup': str(backup), 'sha256': hashlib.sha256(originals[i]).hexdigest()})
        plan['outputs'].append({'path': str(target), 'sha256': hashlib.sha256(replacement).hexdigest()})
    if any(p.read_bytes() != original for p, original in zip(inputs, originals)):
        raise OSError('source bank changed during staging; migration not approved')
    (output / 'migration-plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan


def install_history_migration(stage: Path, *, disk_number: int, expected_disk_serial: str,
                              expected_volume_serial: str, expected_drive: str | None = None) -> dict:
    """Install a verified staged pair in explicit Windows Disk Mode.

    A fixed host receipt admits this staging directory only once. Any failure
    after admission retains backups, staged files and the last recorded phase;
    never automatically retry, roll back, or reboot. FAT cannot atomically rename
    two files: interruption between replacements leaves a deliberately rejected
    mixed pair, recoverable from verified backups under manual inspection.
    """
    from .publish import (_plain, _bounded, _hash, _volume_guard, _same_target,
                          _copy_verified, inspect_target)
    stage = Path(os.path.abspath(stage))
    _plain(stage, Path(stage.anchor))
    plan_path = stage / 'migration-plan.json'
    receipt_path = stage / 'history-install-receipt.json'
    for path in (plan_path, receipt_path):
        _plain(path, stage)
    if receipt_path.exists():
        raise ValueError('migration already admitted; inspect its receipt, never replay automatically')
    plan_bytes = _bounded(plan_path, 65536)
    plan_hash = hashlib.sha256(plan_bytes).hexdigest()
    plan = json.loads(plan_bytes)
    if (plan.get('format'), plan.get('version'), plan.get('source_format'), plan.get('target_format')) != (
            'Linnet history migration', 1, 'JRN1', 'JH2/JP2'):
        raise ValueError('invalid migration plan format')
    if plan.get('target_bank_bytes') != BANK_BYTES or plan.get('capacity_records') != PAGE_COUNT * PAGE_RECORDS:
        raise ValueError('invalid migration plan capacity')
    if not isinstance(plan.get('inputs'), list) or not isinstance(plan.get('outputs'), list) or len(plan['inputs']) != 2 or len(plan['outputs']) != 2:
        raise ValueError('migration plan requires two inputs and outputs')
    originals, candidates, original_hashes, candidate_hashes = [], [], [], []
    for i in range(2):
        backup, candidate = stage / f'MUSIC{i}.JRN1.backup', stage / f'MUSIC{i}.BIN'
        for path in (backup, candidate):
            _plain(path, stage)
        original, new = _bounded(backup, 4608), _bounded(candidate, BANK_BYTES)
        original_hash, candidate_hash = hashlib.sha256(original).hexdigest(), hashlib.sha256(new).hexdigest()
        if original_hash != plan['inputs'][i].get('sha256') or candidate_hash != plan['outputs'][i].get('sha256'):
            raise ValueError('staged bank/backup hash differs from migration plan')
        originals.append(original); candidates.append(new)
        original_hashes.append(original_hash); candidate_hashes.append(candidate_hash)
    selected, source_records = select_legacy(*originals)
    verified = validate_paged_bank(candidates[0])
    # Initial migration copies are identical. This proves the second full bank
    # matches the fully validated first bank without repeating its page scan.
    if candidates[0] != candidates[1] or verified['epoch'] != plan.get('epoch'):
        raise ValueError('replacement pair/epoch differs')
    if (selected != plan.get('selected_source_bank') or len(source_records) != plan.get('records_preserved') or
            sorted(source_records) != sorted(verified['records'])):
        raise ValueError('replacement does not preserve every selected JRN1 record')
    identity = inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive)
    root = Path(identity['root'])
    if stage.drive.casefold() == root.drive.casefold():
        raise ValueError('migration stage must reside on a different volume')
    guard = lambda: _volume_guard(identity)
    linnet = root / 'LINNET'
    active = [linnet / f'MUSIC{i}.BIN' for i in range(2)]
    guard(); _plain(linnet, root)
    for i, path in enumerate(active):
        _plain(path, root)
        if _hash(path, 4608) != original_hashes[i]:
            raise ValueError('live journal differs from staged migration source')
    if identity['free_bytes'] < 2 * BANK_BYTES + 2 * 4608 + 6 * 65536 + 1024 * 1024:
        raise ValueError('insufficient space to stage both banks and verified backups')
    _same_target(identity, inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive))
    token = uuid.uuid4().hex[:6].upper()
    backups = [linnet / f'H{token}{i}.BAK' for i in range(2)]
    temporary = [linnet / f'H{token}{i}.TMP' for i in range(2)]
    for path in (*backups, *temporary):
        _plain(path, root)
        if path.exists():
            raise ValueError('migration staging name collision')
    receipt = dict(operation='install-history-migration', passed=False, phase='admitted', identity=identity,
                   plan_sha256=plan_hash, epoch=plan['epoch'], started_at=time.time(), elevation=False,
                   backups=[str(p) for p in backups], temporary=[str(p) for p in temporary],
                   source_sha256=original_hashes, candidate_sha256=candidate_hashes,
                   replaced_banks=[], durability='file fsync/readback; two FAT replacements are not atomic')

    def record(mode='w'):
        _plain(receipt_path, stage)
        with receipt_path.open(mode, encoding='utf-8', newline='\n') as writer:
            json.dump(receipt, writer, indent=2); writer.write('\n'); writer.flush(); os.fsync(writer.fileno())

    record('x')  # admission is durable on the host before any device mutation
    try:
        receipt['phase'] = 'backing-up-live-pair'; record()
        for i in range(2):
            guard(); _plain(active[i], root)
            _copy_verified(active[i], backups[i], {'bytes': 4608, 'sha256': original_hashes[i]}, root, guard)
        receipt['phase'] = 'live-backups-verified'; record()
        for i in range(2):
            candidate = stage / f'MUSIC{i}.BIN'
            _plain(candidate, stage)
            _copy_verified(candidate, temporary[i], {'bytes': BANK_BYTES, 'sha256': candidate_hashes[i]}, root, guard)
        receipt['phase'] = 'both-candidates-verified'; record()
        for i in range(2):
            if _hash(plan_path) != plan_hash:
                raise RuntimeError('migration plan changed during installation')
            _same_target(identity, inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive))
            guard()
            for path in (*active, *backups, temporary[i]):
                _plain(path, root)
            for j in range(2):
                if _hash(backups[j], 4608) != original_hashes[j]:
                    raise RuntimeError('verified live backup changed')
                expected = candidate_hashes[j] if j < i else original_hashes[j]
                expected_size = BANK_BYTES if j < i else 4608
                if _hash(active[j], expected_size) != expected:
                    raise RuntimeError('active pair changed before replacement')
            if _hash(temporary[i], BANK_BYTES) != candidate_hashes[i]:
                raise RuntimeError('staged device candidate changed')
            receipt['phase'] = f'replacing-bank-{i}'; record()
            guard()
            # Last source check is immediately before its one-way replacement.
            _plain(active[i], root)
            if _hash(active[i], 4608) != original_hashes[i]:
                raise RuntimeError('original bank changed immediately before replacement')
            os.replace(temporary[i], active[i])
            guard(); _plain(active[i], root)
            with active[i].open('rb+') as writer:
                writer.flush(); os.fsync(writer.fileno())
            if _hash(active[i], BANK_BYTES) != candidate_hashes[i]:
                raise OSError('replaced bank readback mismatch')
            receipt['replaced_banks'].append(i)
            receipt['phase'] = f'bank-{i}-verified'; record()
        _same_target(identity, inspect_target(disk_number, expected_disk_serial, expected_volume_serial, expected_drive))
        for i in range(2):
            guard(); _plain(active[i], root)
            if _hash(active[i], BANK_BYTES) != candidate_hashes[i]:
                raise OSError('final pair readback mismatch')
        receipt.update(passed=True, phase='pair-verified', finished_at=time.time(), receipt=str(receipt_path))
        record(); return receipt
    except Exception as exc:
        receipt.update(error=str(exc), finished_at=time.time(), receipt=str(receipt_path))
        try:
            record()
        except OSError:
            pass
        raise RuntimeError(f"History installation stopped in {receipt['phase']}: {exc}. Inspect {receipt_path}; do not replay automatically") from exc
