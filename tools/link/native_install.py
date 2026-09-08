"""Validated host orchestration for the fixed-purpose device Boot updater."""
from pathlib import Path
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from tools.studio.native_package import prepare, PACKAGE_BYTES, MAX_PACKAGE_BYTES
from .campaign import connect, _run_directory, _save
from .identity import decode


def validate_package(path, expected_sha):
    path=Path(path).resolve(strict=True)
    if not re.fullmatch('[0-9a-fA-F]{64}',expected_sha) or not PACKAGE_BYTES<=path.stat().st_size<=MAX_PACKAGE_BYTES:
        raise ValueError('native package requires exact size and explicit SHA256')
    package=path.read_bytes()
    if hashlib.sha256(package).hexdigest()!=expected_sha.lower():
        raise ValueError('native package SHA256 mismatch')
    report_path=path.with_suffix(path.suffix+'.json')
    if report_path.stat().st_size>65536:raise ValueError('native package provenance exceeds bound')
    report=json.loads(report_path.read_text())
    if (report.get('format')!='LNB2' or report.get('version') not in (1,2) or report.get('bytes')!=len(package) or
        report.get('sha256')!=expected_sha.lower()):
        raise ValueError('native package provenance mismatch')
    # Re-run all pinned plan/artifact/backup checks before opening a serial port.
    with tempfile.TemporaryDirectory(prefix='linnet-native-validate-') as temporary:
        rebuilt=Path(temporary)/'reviewed.lnb'
        derived=prepare(report['plan'],report['plan_sha256'],rebuilt)
        if rebuilt.read_bytes()!=package:
            raise ValueError('native package differs from the independently reconstructed reviewed plan')
    return package,derived


def install(root,package_path,expected_sha,port,progress=None):
    package,provenance=validate_package(package_path,expected_sha)
    run_id,directory=_run_directory(root,provenance['image'])
    path=directory/'receipt.json'
    receipt=dict(run_id=run_id,operation='device-native-boot-update',passed=False,
        package=str(Path(package_path).resolve()),package_sha256=expected_sha.lower(),
        plan=provenance['plan'],plan_sha256=provenance['plan_sha256'],image=provenance['image'],
        device_write_attempted=False,steps=[],started_at=datetime.now(timezone.utc).isoformat())
    _save(path,receipt);session=None
    def record(step):
        if step.get('device_write_attempted'):receipt['device_write_attempted']=True
        receipt['steps'].append(step);_save(path,receipt)
        if progress:progress(dict(run_id=run_id,**step))
    try:
        session,endpoint,identity=connect(port=port,serial_number=provenance['expected_linnet_usb_serial'])
        status=decode(session.status())
        if any(status[key]!=identity[key] for key in ('target_id','build_id','generation')):
            raise RuntimeError('running image changed during native install preflight')
        if status['target_id']!='photo4g-p98' or status['profile']=='release' or status['image_kind']!='os':
            raise RuntimeError('native install requires the authorized development RAM OS')
        receipt['before']=dict(identity=status,endpoint=endpoint);_save(path,receipt)
        result=session.native_install(status['generation'],package,record)
        receipt.update(result)
    except (ValueError,RuntimeError,OSError) as exc:
        receipt['failure']=f'{type(exc).__name__}: {exc}'
        receipt['inspection_required']=True
    finally:
        if session:session.close()
        receipt['finished_at']=datetime.now(timezone.utc).isoformat();_save(path,receipt)
    return receipt
