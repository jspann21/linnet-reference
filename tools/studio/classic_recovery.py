"""Portable, device-bound recovery for the Classic's separate NOR bootstrap."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import uuid

from tools.link import classic_nor as nor
from tools.studio.targets import ROOT

FORMAT = 'linnet-classic-nor-recovery-v1'
FILES = ('ORIGINAL.BIN', 'ORIGINAL.BIN.json', 'INSTALLED.BIN', 'NOR.JSON')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _serial(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9A-F]{16}', value):
        raise ValueError('Classic recovery requires the logic-board USB serial')
    return value


def _scope(serial):
    from tools.studio.installer import cache_root
    return cache_root(dict(target_id=nor.TARGET, disk_serial=_serial(serial))) / 'nor'


def _json(path):
    value = json.loads(nor._read_file(path, 65536))
    if not isinstance(value, dict):
        raise ValueError('Invalid Classic recovery record')
    return value


def _write(path, data):
    """Preserve immutable recovery bytes; never overwrite another snapshot."""
    from tools.content.guard import guarded_path
    path = Path(path)
    guarded_path(path, Path(path.anchor))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if nor._read_file(path, len(data), exact=len(data)) != data:
            raise ValueError('Saved Classic recovery bytes differ: ' + path.name)
        return
    with path.open('xb') as writer:
        writer.write(data)
        writer.flush()
        os.fsync(writer.fileno())
    if path.read_bytes() != data:
        raise OSError('Classic recovery copy failed readback: ' + path.name)


def save_install(plan, original, installed_image, *, installed: bool):
    """Keep a durable host copy before installation and record verified completion."""
    from tools.studio.installer import _save
    serial = _serial(plan['serial'])
    if (plan.get('target_id') != nor.TARGET or len(original) != 1048576 or
            len(installed_image) != 1048576 or _sha(original) != plan['original_sha256'] or
            _sha(installed_image) != plan['result_sha256']):
        raise ValueError('Classic recovery does not match the installation plan')
    directory = _scope(serial) / _sha(installed_image)
    _write(directory / 'ORIGINAL.BIN', original)
    original_receipt = dict(target_id=nor.TARGET, serial=serial, verified=True, sha256=_sha(original))
    _write(directory / 'ORIGINAL.BIN.json', (json.dumps(original_receipt, sort_keys=True) + '\n').encode())
    _write(directory / 'INSTALLED.BIN', installed_image)
    path = directory / 'NOR.JSON'
    value = dict(format=FORMAT, target_id=nor.TARGET, serial=serial,
                 original_sha256=_sha(original), installed_sha256=_sha(installed_image),
                 monitor_build_id=plan['build_id'], phase='installed' if installed else 'prepared')
    if path.exists():
        previous = _json(path)
        if any(previous.get(key) != item for key, item in value.items() if key != 'phase'):
            raise ValueError('Classic recovery record differs from the installation')
        if previous.get('phase') == 'installed':
            return path
    _save(path, value, durable=True)
    return path


def load(path, expected_sha=None):
    """Validate complete recovery snapshots without accessing the device flash."""
    from tools.content.guard import guarded_path
    path = Path(path)
    guarded_path(path, Path(path.anchor))
    raw = nor._read_file(path, 65536)
    if expected_sha is not None and _sha(raw) != expected_sha:
        raise ValueError('Classic recovery record hash differs')
    record = json.loads(raw)
    if (not isinstance(record, dict) or record.get('format') != FORMAT or
            record.get('target_id') != nor.TARGET or record.get('phase') != 'installed'):
        raise ValueError('No verified Classic NOR installation record is available')
    _serial(record.get('serial'))
    for name in FILES:
        guarded_path(path.parent / name, path.parent)
    original = nor._backup(path.parent / 'ORIGINAL.BIN', record['serial'])
    installed = nor._read_file(path.parent / 'INSTALLED.BIN', 1048576, exact=1048576)
    image = installed[nor.START:nor.END]
    entry, size = struct.unpack_from('<II', image, 8)
    if (record.get('original_sha256') != _sha(original) or
            record.get('installed_sha256') != _sha(installed) or
            original[:nor.START] != installed[:nor.START] or original[nor.END:] != installed[nor.END:] or
            image[:8] != b'87021.0\x02' or entry or not size or size % 16 or size > 0x10000 or
            not re.fullmatch(r'[0-9a-f]{64}', record.get('monitor_build_id', ''))):
        raise ValueError('Classic recovery snapshots differ from the verified NOR layout')
    return record, original, installed


def _marker(identity, path, record):
    return dict(target_id=nor.TARGET, device_id=identity['disk_serial'],
                linnet_usb_serial=record['serial'], strategy='native-nor', phase='installed',
                previous_boot='apple', installation_method='native-nor',
                nor_record=str(path), nor_record_sha256=_sha(Path(path).read_bytes()),
                original_sha256=record['original_sha256'], installed_sha256=record['installed_sha256'])


def _restored(marker):
    """Require the durable full-flash readback receipt, not just a journal phase."""
    path = marker.get('nor_restore_receipt')
    if not path:
        return None
    try:
        receipt = _json(path)
        saved = receipt.get('mount_identity', {})
        if (receipt.get('operation') == 'restore-classic-nor' and receipt.get('passed') is True and
                receipt.get('target_id') == nor.TARGET and receipt.get('serial') == marker['linnet_usb_serial'] and
                receipt.get('original_sha256') == marker['original_sha256'] and
                receipt.get('installed_sha256') == marker['installed_sha256'] and
                receipt.get('result_sha256') == marker['original_sha256'] and
                saved.get('linnet_usb_serial') == marker['linnet_usb_serial']):
            return receipt
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def _same_volume(before, after):
    # Apple Disk Mode can hide the firmware prefix exposed by native Disk Mode.
    # Both the disk size and media offset then shrink by exactly that prefix;
    # board identity, filesystem identity, media size and the trailing extent stay.
    keys = ('target_id', 'linnet_usb_serial', 'partition_bytes', 'sector_bytes',
            'volume_serial', 'filesystem')
    error = 'The reconnected Classic or its filesystem differs from the reviewed iPod'
    if any(before.get(key) is None or before[key] != after.get(key) for key in keys):
        raise ValueError(error)
    for identity in (before, after):
        fields = ('disk_bytes', 'partition_offset', 'partition_bytes', 'sector_bytes')
        if (any(type(identity.get(key)) is not int or identity[key] <= 0 for key in fields) or
                any(identity[key] % identity['sector_bytes'] for key in fields[:-1]) or
                identity['partition_offset'] + identity['partition_bytes'] > identity['disk_bytes']):
            raise ValueError(error)
    hidden_bytes = before['disk_bytes'] - after['disk_bytes']
    offset_change = before['partition_offset'] - after['partition_offset']
    if hidden_bytes == offset_change == 0:
        return
    if (before.get('native_target_id') != nor.TARGET or after.get('native_target_id') == nor.TARGET or
            hidden_bytes <= 0 or hidden_bytes != offset_change):
        raise ValueError(error)


def find(identity):
    """Discover portable records, durable host records, or verified legacy plans."""
    if identity.get('target_id') != nor.TARGET:
        return None
    from tools.content.guard import guarded_path
    from tools.studio.installer import JOURNAL
    root = Path(identity['root']).resolve(strict=True)
    guarded_path(root / '.LINNET', root)
    if not (root / '.LINNET').is_dir():
        return None
    serial = _serial(identity.get('linnet_usb_serial'))
    candidates = []
    journal_path = root / JOURNAL
    guarded_path(journal_path, root)
    if journal_path.is_file():
        journal = _json(journal_path)
        if journal.get('strategy') == 'native-nor':
            relative = journal.get('nor_directory', '')
            if not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise ValueError('Classic recovery directory is invalid')
            path = root / JOURNAL.parent / relative / 'NOR.JSON'
            guarded_path(path, root / JOURNAL.parent)
            record, _, _ = load(path, journal.get('nor_record_sha256'))
            if record['serial'] != serial or journal.get('linnet_usb_serial') != serial:
                raise ValueError('Classic recovery belongs to a different iPod')
            marker = _marker(identity, path, record)
            if journal.get('nor_restore_receipt'):
                marker['nor_restore_receipt'] = journal['nor_restore_receipt']
            receipt = _restored(marker)
            if receipt and identity.get('native_target_id') != nor.TARGET:
                _same_volume(receipt['mount_identity'], identity)
                marker['phase'] = 'restored'
            elif journal.get('phase') == 'restored':
                raise ValueError('The verified Classic restoration receipt is missing or the iPod is still running Linnet')
            if marker['phase'] == 'restored' or marker.get('nor_restore_receipt'):
                return marker
            candidates.append((path.stat().st_mtime_ns, marker))
    for path in [*(root / JOURNAL.parent / 'NOR').glob('*/NOR.JSON'), *_scope(serial).glob('*/NOR.JSON')]:
        try:
            record, _, _ = load(path)
            if record['serial'] == serial:
                candidates.append((path.stat().st_mtime_ns, _marker(identity, path, record)))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    # Older developer bootstraps predate Media Manager's recovery journal.
    # Reconstruct only completed, hash-matched NOR transactions for this board.
    for receipt_path in (ROOT / 'out' / nor.TARGET).glob('*.receipt.json'):
        try:
            receipt = _json(receipt_path)
            if (receipt.get('target_id') != nor.TARGET or receipt.get('serial') != serial or
                    receipt.get('phase') != 'persistent-link-verified'):
                continue
            path = receipt_path.with_name(receipt_path.name.removesuffix('.receipt.json') + '.json')
            digest = _sha(nor._read_file(path, 65536))
            plan, original, _, _, installed, _ = nor.load_prepared(path, digest)
            if (plan['serial'] != serial or receipt.get('build_id') != plan['build_id'] or
                    receipt.get('result_sha256') != _sha(installed)):
                continue
            marker = dict(target_id=nor.TARGET, device_id=identity['disk_serial'],
                          linnet_usb_serial=serial, strategy='native-nor', phase='installed',
                          previous_boot='apple', installation_method='native-nor',
                          legacy_plan=str(path), legacy_plan_sha256=digest,
                          original_sha256=_sha(original), installed_sha256=_sha(installed))
            candidates.append((receipt_path.stat().st_mtime_ns, marker))
        except (OSError, ValueError, TypeError, KeyError, struct.error):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def preserve(identity):
    """Publish and verify portable recovery before an OS update or removal."""
    from tools.content.guard import guarded_path, guard_volume
    from tools.content.media_manager import refresh
    from tools.content.publish import _exclusive
    from tools.studio.installer import JOURNAL, _save
    with _exclusive(identity):
        identity = refresh(identity)
        marker = find(identity)
        if marker is None:
            raise ValueError('This Classic needs its verified original NOR backup and completed bootstrap plan')
        if 'legacy_plan' in marker:
            plan, original, _, _, installed, _ = nor.load_prepared(marker['legacy_plan'], marker['legacy_plan_sha256'])
            source = save_install(plan, original, installed, installed=True)
        else:
            source = Path(marker['nor_record'])
        record, original, installed = load(source)
        # Always retain a host copy before leaving Disk Mode or deleting files.
        host = save_install(dict(target_id=nor.TARGET, serial=record['serial'], build_id=record['monitor_build_id'],
                                 original_sha256=_sha(original), result_sha256=_sha(installed)),
                            original, installed, installed=True)
        root = Path(identity['root']).resolve(strict=True)
        if host.stat().st_dev == root.stat().st_dev:
            raise ValueError('Classic recovery must be saved on the computer before removal')
        relative = Path('NOR') / record['installed_sha256']
        destination = root / JOURNAL.parent / relative
        for name in FILES:
            guard_volume(identity)
            guarded_path(destination / name, root)
            _write(destination / name, (host.parent / name).read_bytes())
        copied, _, _ = load(destination / 'NOR.JSON', _sha(host.read_bytes()))
        saved = _marker(identity, destination / 'NOR.JSON', copied)
        saved['nor_directory'] = relative.as_posix()
        saved['phase'] = marker['phase']
        if marker.get('nor_restore_receipt'):
            saved['nor_restore_receipt'] = marker['nor_restore_receipt']
        guard_volume(identity)
        _save(root / JOURNAL, saved, durable=True)
        return saved


def _enter_monitor(record, progress):
    from tools.link.campaign import connect
    from tools.link.session import DeviceError

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        session, endpoint, running = connect(serial_number=record['serial'], deadline_seconds=10)
        try:
            if running['target_id'] != nor.TARGET:
                raise ValueError('The reconnected Link target differs from the Classic')
            if running['image_kind'] == 'boot' and running['build_id'] == record['monitor_build_id']:
                return
            if not running['capabilities'] & 16:
                raise ValueError('This Linnet build cannot enter Classic recovery through Link')
            state = session.storage_state()
            if state[1] != 6 or state[2] or not state[7] or state[8] or state[9]:
                time.sleep(.25)
                continue
            progress('Restarting the Classic into its SRAM recovery monitor…')
            try:
                session.reboot('recovery')
                return
            except DeviceError:
                # An explicit rejection makes no change. The session is poisoned:
                # reconnect and inspect storage before asking again. An ambiguous
                # acknowledgement is never retried here.
                progress('Waiting for Linnet to finish using storage before restarting…')
                time.sleep(.25)
        finally:
            session.close()
    raise RuntimeError('Linnet is still using storage. Return to Disk Mode and retry removal when it is idle.')


def restore(identity, *, progress=lambda _message: None):
    """Restore flash through Link; return the same filesystem in Apple Disk Mode."""
    from tools.content.media_manager import discover, refresh
    from tools.content.guard import guard_volume
    from tools.content.publish import _exclusive
    from tools.studio.installer import JOURNAL, _save
    identity = refresh(identity)
    marker = preserve(identity)
    receipt = _restored(marker)
    if marker['phase'] == 'restored' and receipt:
        return dict(passed=True, boot=receipt, identity=identity, media_preserved=True,
                    linnet_files_preserved=True, requires_safe_eject=True)
    if identity.get('native_target_id') != nor.TARGET:
        raise ValueError('Start Linnet, open Disk Mode, and reconnect this Classic to restore its NOR bootloader')
    record, _, _ = load(marker['nor_record'], marker['nor_record_sha256'])
    host = _scope(record['serial']) / record['installed_sha256'] / 'NOR.JSON'
    load(host, marker['nor_record_sha256'])
    receipt_path = host.parent / ('restore-' + uuid.uuid4().hex + '.json')
    with _exclusive(identity):
        refresh(identity)
        guard_volume(identity)
        marker['nor_restore_receipt'] = str(receipt_path)
        _save(Path(identity['root']) / JOURNAL, marker, durable=True)
        progress('Safely ejecting Classic Disk Mode to enter bootloader recovery…')
        from tools.link.eject import eject
        eject(identity['disk_number'], identity['disk_serial'])
        try:
            _enter_monitor(record, progress)
        except (OSError, RuntimeError) as error:
            raise RuntimeError('The Classic was safely ejected, but its recovery monitor could not be reached. '
                               'No flash was written. A developer build with Linnet Link is required; '
                               'return to Linnet Disk Mode before retrying. ' + str(error)) from error
        # The low-level restore records the mounted identity alongside the durable
        # full-flash readback, before asking Apple to restart.
        boot = nor.restore(host, marker['nor_record_sha256'], receipt_path,
                           progress=progress, mount_identity=identity)
    progress('Waiting for this iPod to reconnect in Apple Disk Mode…')
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        matches = [item for item in discover() if item.get('target_id') == nor.TARGET and
                   item.get('linnet_usb_serial') == record['serial'] and item.get('native_target_id') != nor.TARGET]
        if len(matches) > 1:
            raise RuntimeError('More than one Apple disk has the reviewed Classic identity')
        if matches:
            current = matches[0]
            _same_volume(identity, current)
            preserve(current)
            return dict(passed=True, boot=boot, identity=current, media_preserved=True,
                        linnet_files_preserved=True, requires_safe_eject=True)
        time.sleep(.5)
    raise RuntimeError('Apple boot flash was restored and verified. Reconnect this iPod in Apple Disk Mode, '
                       'then choose Remove Linnet OS again to finish cleanup. Linnet files are still present.')
