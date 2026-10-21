"""Bind original firmware recovery records to the same iPod in Linnet Disk Mode."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid

from tools.studio import native_bootstrap as native
from tools.studio.targets import TARGETS


def eligible(identity):
    return (identity.get('native_target_id') == identity.get('target_id') and
            TARGETS[identity['target_id']]['installer']['boot_layout'] == 'ipod-directory')


def _directory_target(identity):
    spec = TARGETS[identity['target_id']]['installer']
    return spec['enabled'] and spec['boot_layout'] == 'ipod-directory'


def _inputs(identity, transaction, path, digest, device_id):
    from tools.studio import installer

    transaction = Path(transaction).resolve(strict=True)
    path = Path(path).resolve(strict=True)
    original_identity = dict(identity, disk_serial=device_id)
    if (not _directory_target(identity) or transaction.parent.parent != installer.cache_root(original_identity) or
            path not in (transaction / 'native-plan/plan.json', transaction / 'apple-recovery-plan/plan.json')):
        raise ValueError('Native recovery record is outside this iPod’s original transaction')
    manifest, artifacts, firmware = native.load_plan(path, digest)
    saved = json.loads(artifacts['device.json'])
    storage = saved['storage']
    if (manifest['target_id'] != identity['target_id'] or
            saved['target_id'] != identity['target_id'] or
            manifest['expected_storage_serial'] != device_id or
            storage['disk_serial'] != device_id or
            manifest['expected_linnet_usb_serial'] != identity['linnet_usb_serial'] or
            saved['linnet_usb_serial'] != identity['linnet_usb_serial'] or
            identity['disk_serial'] != (identity['linnet_usb_serial'] if eligible(identity) else device_id) or
            Path(manifest['firmware_backup']).resolve(strict=True) != transaction / 'backup/firmware.bin' or
            manifest['expected_device_bytes'] != identity['disk_bytes'] or
            manifest.get('sector_bytes', native.SECTOR) != identity['sector_bytes'] or
            any(storage[key] != identity[key] for key in ('disk_bytes', 'sector_bytes', 'partition_offset', 'partition_bytes'))):
        raise ValueError('Original firmware plan does not match this native iPod')
    # Old device.json records lack the FAT serial. The original install receipt
    # contains it, independently of Windows' mode-specific volume GUID.
    originals = []
    for receipt_path in transaction.glob('install-*.json'):
        if receipt_path.name.endswith('.result.json'):
            continue
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        original = receipt.get('identity', {})
        if (receipt.get('operation') == 'install-linnet' and
                original.get('disk_serial') == device_id and
                original.get('volume_unique_id') == storage.get('volume_id') and
                original.get('volume_serial') == identity['volume_serial'] and
                all(original.get(key) == identity[key] for key in
                    ('target_id', 'linnet_usb_serial', 'disk_bytes', 'sector_bytes', 'partition_offset', 'partition_bytes'))):
            originals.append(original)
    if not originals:
        raise ValueError('The original installation has no matching FAT volume identity')
    return manifest, artifacts, firmware


def _context(identity, linnet, transaction):
    from tools.studio import installer

    transaction = Path(transaction).resolve(strict=True)
    context = json.loads((transaction / 'context.json').read_text(encoding='utf-8'))
    if (context.get('target_id') != identity['target_id'] or
            context.get('strategy') != 'native-directory' or context.get('build') not in ('user', 'dev') or
            linnet.get('state') != 'installed' or linnet.get('candidate_pending')):
        raise ValueError('An interrupted native installation cannot be verified in its current state')
    method = installer._saved_method(context)
    if installer.INSTALLATION_METHODS[method]['strategy'] != 'native-directory':
        raise ValueError('The saved installation does not use native firmware recovery')
    artifacts = dict(context['artifacts'])
    artifacts.setdefault('installation_method', method)
    artifacts.setdefault('boot_selector', installer.INSTALLATION_METHODS[method]['boot_selector'])
    installer._validate_artifacts(identity, artifacts)
    path = transaction / 'native-plan/plan.json'
    digest = (transaction / 'native-plan.sha256').read_text(encoding='ascii').strip()
    manifest, plan_artifacts, _firmware = _inputs(identity, transaction, path, digest, context['device_id'])
    if (artifacts['build'] != context['build'] or linnet.get('build') != context['build'] or
            linnet.get('build_id') != artifacts['os_build_id'] or
            linnet.get('image_sha256') != installer.inspect_image(Path(artifacts['os_image']).read_bytes())['sha256'] or
            manifest['image']['build_id'] != artifacts['boot_build_id'] or
            Path(artifacts['boot_image']).read_bytes() != plan_artifacts['boot.los']):
        raise ValueError('Installed software differs from the saved native installation')
    return dict(context, artifacts=artifacts, transaction=str(transaction), installation_method=method,
                initialized_resume=True)


def pending(identity, linnet):
    from tools.studio import installer

    if not _directory_target(identity) or linnet.get('state') != 'installed':
        return None
    base = installer.cache_root(identity).parent
    matches = []
    for transaction in base.glob(identity['target_id'] + '-*/transactions/*'):
        try:
            matches.append(_context(identity, linnet, transaction))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if len(matches) > 1:
        raise ValueError('Multiple original installations match this iPod; resolve their recovery records first')
    return matches[0] if matches else None


def available(identity, marker):
    if not eligible(identity) or not marker or marker.get('strategy') != 'native-directory':
        return False
    try:
        manifest, _artifacts, _firmware = _inputs(identity, marker['transaction'], marker['plan'],
                                                marker['plan_sha256'], marker['device_id'])
        return (manifest['image']['build_id'] == marker['boot_build_id'] and
                manifest['firmware_backup_sha256'] == marker['firmware_backup_sha256'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def bind(identity, transaction, path, digest, device_id):
    """Derive an execution descriptor; retain original plan and every raw byte."""
    from tools.inspect.retail_device import detect
    from tools.studio import installer
    from tools.content.media_manager import refresh

    current = refresh(identity)
    installer._same_device(identity, current)
    manifest, artifacts, _firmware = _inputs(current, transaction, path, digest, device_id)
    detected = detect(current['root'])
    storage = detected['storage']
    if (detected['target_id'] != current['target_id'] or
            detected['linnet_usb_serial'] != current['linnet_usb_serial'] or
            storage['volume_id'] != current['volume_unique_id'] or
            any(storage[key] != current[key] for key in
                ('disk_number', 'disk_serial', 'disk_bytes', 'sector_bytes', 'partition_offset', 'partition_bytes'))):
        raise ValueError('Native storage changed before recovery binding')
    output = Path(transaction) / ('native-binding-' + uuid.uuid4().hex)
    output.mkdir(exist_ok=False)
    for name in native.ARTIFACTS:
        shutil.copyfile(Path(path).parent / name, output / name)
    native.save_json(output / 'device.json', detected)
    data = (output / 'device.json').read_bytes()
    entries = dict(manifest['artifacts'])
    entries['device.json'] = dict(bytes=len(data), sha256=native.sha(data))
    rebound = dict(manifest, expected_storage_serial=current['disk_serial'], artifacts=entries)
    native.save_json(output / 'plan.json', rebound)
    result_path = output / 'plan.json'
    result_hash = native.sha(result_path.read_bytes())
    _new, new_artifacts, _backup = native.load_plan(result_path, result_hash)
    if any(new_artifacts[name] != artifacts[name] for name in native.ARTIFACTS if name != 'device.json'):
        raise ValueError('Native binding changed a firmware recovery artifact')
    return result_path, result_hash


def finish(job):
    from tools.studio import installer

    identity = job['identity']
    root = Path(identity['root'])
    if (root / installer.JOURNAL).exists():
        raise ValueError('Installation recovery changed before verification')
    context = _context(identity, installer.installed_state(root, identity['target_id']), job['transaction'])
    if (context['artifacts'] != job['artifacts'] or context['installation_method'] != job['installation_method'] or
            installer._saved_previous_boot(context) != job['previous_boot']):
        raise ValueError('The saved installation changed before verification')
    transaction = Path(context['transaction'])
    path = transaction / 'native-plan/plan.json'
    digest = (transaction / 'native-plan.sha256').read_text(encoding='ascii').strip()
    bound_path, bound_sha = bind(identity, transaction, path, digest, context['device_id'])
    applied = native.execute('apply', bound_path, bound_sha, identity['disk_number'])
    if not applied.get('passed'):
        raise RuntimeError(applied.get('failure', 'Native installation verification failed'))
    # Initial provisioning must not overwrite metadata updated by a successful
    # first boot. Validate the current confirmed image again instead.
    _context(identity, installer.installed_state(root, identity['target_id']), transaction)
    apple = installer._install_apple_firmware(identity, path, digest)
    manifest, _artifacts, firmware = native.load_plan(path, digest)
    if identity['target_id'] == 'video5g-m25':
        from tools.studio.apple_firmware import publish_video_resources
        saved = json.loads(_artifacts['device.json'])
        parsed = native.parse_backup(firmware, _artifacts['mbr.bin'], saved)
        apple['video_resources'] = publish_video_resources(identity, firmware, parsed['entries'])
    selector = (installer._install_selector_config(identity)
                if context['installation_method'] == 'native-selector' else None)
    marker = installer._journal(dict(identity, disk_serial=context['device_id']), context['artifacts'],
        'native-directory', transaction, dict(plan=str(path), plan_sha256=digest,
        firmware_backup_sha256=manifest['firmware_backup_sha256'],
        installation_method=context['installation_method'], previous_boot=installer._saved_previous_boot(context),
        apple_firmware=apple, selector=selector))
    return dict(passed=True, strategy='native-directory', boot=applied, recovery=marker,
                requires_safe_eject=True, resumed_through_native_disk=True)
