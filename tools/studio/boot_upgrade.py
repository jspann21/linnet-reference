"""Upgrade an installed native Boot while retaining its Apple recovery path."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid

from tools.studio import native_bootstrap as native
from tools.studio.targets import TARGETS


def _eligible(review):
    identity = review['identity']
    marker = review.get('recovery') or {}
    return (identity.get('native_target_id') == identity['target_id'] and
            TARGETS[identity['target_id']]['installer']['boot_layout'] == 'ipod-directory' and
            review['linnet']['state'] == 'installed' and
            marker.get('strategy') == 'native-directory' and
            marker.get('phase') == 'installed' and
            marker.get('startup_default_format') != 1 and
            marker.get('linnet_usb_serial') == identity.get('linnet_usb_serial') and
            not review['rockbox'].get('supersedes_linnet_recovery'))


def available(review):
    return _eligible(review)


def _rebind_plan(path, digest, output, *, identity, expected_serial, new_serial):
    """Copy an exact reviewed plan with only its live storage serial changed."""
    manifest, _artifacts, _backup = native.load_plan(path, digest)
    if (manifest['target_id'] != identity['target_id'] or
            manifest['expected_storage_serial'] != expected_serial or
            manifest['expected_linnet_usb_serial'] != identity['linnet_usb_serial'] or
            manifest['expected_device_bytes'] != identity['disk_bytes'] or
            manifest.get('sector_bytes', native.SECTOR) != identity['sector_bytes']):
        raise ValueError('Saved boot plan does not match this iPod')
    output.mkdir(parents=True, exist_ok=False)
    for name in native.ARTIFACTS:
        shutil.copyfile(Path(path).parent / name, output / name)
    rebound = dict(manifest, expected_storage_serial=new_serial)
    native.save_json(output / 'plan.json', rebound)
    result_path = output / 'plan.json'
    result_hash = native.sha(result_path.read_bytes())
    native.load_plan(result_path, result_hash)
    return result_path, result_hash


def _apple_recovery_plan(path, digest, output, *, identity, apple_serial):
    manifest, _artifacts, _backup = native.load_plan(path, digest)
    if (manifest['target_id'] != identity['target_id'] or
            manifest['expected_storage_serial'] != identity['disk_serial'] or
            manifest['expected_linnet_usb_serial'] != identity['linnet_usb_serial']):
        raise ValueError('New boot plan does not match this iPod')
    return _rebind_plan(path, digest, output, identity=identity,
                        expected_serial=identity['disk_serial'], new_serial=apple_serial)


def upgrade(identity, *, build='dev', firmware=None, from_source=False,
            progress=lambda _message: None):
    from tools.studio import installer

    reviewed = installer.assess(identity)
    if not _eligible(reviewed):
        raise ValueError('This iPod does not have a verified native Boot upgrade path')
    if build not in ('user', 'dev') or (build == 'dev' and not from_source):
        raise ValueError('Choose a supported Linnet firmware source')
    method = reviewed['recovery'].get('installation_method', 'native-preserve')
    if method not in ('native-preserve', 'native-selector'):
        raise ValueError('The installed Boot method cannot be upgraded here')
    current = reviewed['identity']
    progress('Preparing the new startup firmware…')
    if from_source:
        artifacts = installer.build_artifacts(current, progress=progress, build=build,
                                              installation_method=method)
    else:
        if firmware is None:
            raise ValueError('Choose a Linnet firmware ZIP before upgrading Boot')
        from tools.studio.firmware_bundle import load
        artifacts = load(firmware, current, method)
    transaction = installer._transaction(current, artifacts)
    transaction.mkdir(parents=True, exist_ok=False)
    artifacts = installer._persist_artifacts(artifacts, transaction)
    installer._validate_artifacts(current, artifacts)
    result_path = transaction / ('upgrade-' + uuid.uuid4().hex + '.result.json')
    job = dict(mode='upgrade-boot', identity=current, marker=reviewed['recovery'],
               artifacts=artifacts, transaction=str(transaction), result=str(result_path))
    job_path = transaction / ('worker-' + uuid.uuid4().hex + '.json')
    installer._save(job_path, job, replace=False)
    progress('Requesting administrator access to upgrade the startup selector…')
    result = installer._run_elevated(job_path)
    return dict(passed=True, result=result, requires_safe_eject=True)


def worker(job):
    """Run inside the installer's finite elevated worker."""
    from tools.inspect.retail_device import detect
    from tools.studio import installer
    from tools.studio.apple_firmware import available as apple_available

    expected = job['identity']
    marker = job['marker']
    transaction = Path(job['transaction']).resolve(strict=True)
    observed = detect(expected['root'])
    live = dict(target_id=observed['target_id'], disk_number=observed['storage']['disk_number'],
                disk_serial=observed['storage']['disk_serial'],
                disk_bytes=observed['storage']['disk_bytes'],
                partition_offset=observed['storage']['partition_offset'],
                partition_bytes=observed['storage']['partition_bytes'],
                linnet_usb_serial=observed['linnet_usb_serial'])
    installer._same_device(expected, live)
    review = installer.assess(expected)
    if not _eligible(review) or review['recovery'] != marker:
        raise RuntimeError('The installed Boot changed after upgrade review')
    installer._validate_artifacts(expected, job['artifacts'])
    root = Path(expected['root']).resolve(strict=True)
    if not apple_available(root, expected['target_id']):
        raise ValueError('The preserved Apple firmware is unavailable')
    old_transaction = Path(marker['transaction']).resolve(strict=True)
    old_plan = Path(marker['plan']).resolve(strict=True)
    original_identity = dict(expected, disk_serial=marker['device_id'])
    if (old_plan != old_transaction / 'native-plan/plan.json' or
            old_transaction.parent.parent != installer.cache_root(original_identity)):
        raise ValueError('The saved native Boot plan is outside this iPod’s recovery records')
    old_manifest, _old_files, _old_backup = native.load_plan(old_plan, marker['plan_sha256'])
    if (old_manifest['image']['build_id'] != marker['boot_build_id'] or
            old_manifest['expected_storage_serial'] != marker['device_id']):
        raise ValueError('The saved Boot plan differs from the installation journal')
    rebound_path, rebound_hash = _rebind_plan(
        old_plan, marker['plan_sha256'], transaction / 'prior-plan-native',
        identity=expected, expected_serial=marker['device_id'],
        new_serial=expected['disk_serial'])
    restored = native.execute('restore', rebound_path, rebound_hash, expected['disk_number'])
    if not restored.get('passed'):
        raise RuntimeError(restored.get('failure', 'Could not restore the Apple boot directory'))
    installer._save(root / installer.JOURNAL,
                    dict(marker, phase='restored', restored_at=installer._now()))
    mbr, firmware = installer._read_raw_backup(expected, transaction)
    device_path = transaction / 'device.json'
    installer._save(device_path, observed, replace=False)
    planned = native.plan(firmware, mbr, device_path,
                          Path(job['artifacts']['boot_image']), transaction / 'native-plan')
    applied = native.execute('apply', planned['plan'], planned['plan_sha256'], expected['disk_number'])
    if not applied.get('passed'):
        raise RuntimeError(applied.get('failure', 'Could not publish the new Boot'))
    recovery_path, recovery_hash = _apple_recovery_plan(
        planned['plan'], planned['plan_sha256'], transaction / 'apple-recovery-plan',
        identity=expected, apple_serial=marker['device_id'])
    updated = dict(marker, phase='installed', installed_at=installer._now(),
                   boot_build_id=job['artifacts']['boot_build_id'],
                   startup_default_format=1, transaction=str(transaction),
                   plan=str(recovery_path), plan_sha256=recovery_hash,
                   firmware_backup_sha256=native.sha(firmware.read_bytes()))
    updated.pop('restored_at', None)
    installer._save(root / installer.JOURNAL, updated)
    return dict(passed=True, restored=restored, applied=applied,
                recovery=updated, requires_safe_eject=True)
