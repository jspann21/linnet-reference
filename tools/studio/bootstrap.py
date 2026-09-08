"""Verified file-level bootstrap for an already installed file bootloader."""
import hashlib
import json
import os
from pathlib import Path
import struct
from tools.inspect.image import inspect

def digest(data):
    return hashlib.sha256(data).hexdigest()

def ipod_payload(data):
    if len(data)<40:
        raise ValueError('truncated iPod image')
    checksum,model=struct.unpack_from('>I4s',data)
    payload=data[8:]
    if model!=b'ipco' or checksum!=(3+sum(payload))&0xffffffff:
        raise ValueError('wrong iPod model or wrapper checksum')
    return payload

def sync_write(path,data):
    with path.open('xb') as writer:
        writer.write(data);writer.flush();os.fsync(writer.fileno())
    if path.read_bytes()!=data:
        raise OSError('readback verification failed: '+str(path))

def state_write(path,state):
    temporary=path.with_suffix('.new')
    with temporary.open('w',encoding='utf-8',newline='\n') as writer:
        json.dump(state,writer,indent=2);writer.write('\n');writer.flush();os.fsync(writer.fileno())
    temporary.replace(path)

def install(mount, image, envelope, expected_original):
    mount=mount.resolve(strict=True)
    target=mount/'.rockbox/rockbox.ipod'
    original=target.read_bytes()
    ipod_payload(original)
    if digest(original)!=expected_original:
        raise ValueError('installed boot file differs from reviewed original hash')
    candidate=image.read_bytes();payload=ipod_payload(candidate)
    los=envelope.read_bytes();identity=inspect(los)
    if payload!=los[128:] or identity['profile']=='release':
        raise ValueError('bootstrap requires matching development Boot envelope and wrapper')
    report_path=image.with_suffix('.json')
    report=json.loads(report_path.read_text())
    if report.get('kind')!='boot' or report.get('build_id')!=identity['build_id']:
        raise ValueError('matching Boot build report is required')
    recovery=mount/'LINNET/RECOVERY';recovery.mkdir(parents=True,exist_ok=True)
    state_path=recovery/'BOOTSTRAP.JSON'
    if state_path.exists():
        raise ValueError('existing bootstrap transaction requires status/restore before replacement')
    backup=recovery/'ORIGINAL.IPOD'
    if backup.exists():
        if backup.read_bytes()!=original:
            raise ValueError('existing recovery backup differs; refusing to overwrite')
    else: sync_write(backup,original)
    state=dict(schema_version=1,target_id=identity['target_id'],build_id=identity['build_id'],
               entry_mode='existing-file-bootloader',target='.rockbox/rockbox.ipod',
               backup='LINNET/RECOVERY/ORIGINAL.IPOD',original_sha256=digest(original),
               candidate_sha256=digest(candidate),phase='backup-verified')
    state_write(state_path,state)
    temporary=target.with_name('linnet-new.ipod')
    if temporary.exists():
        raise ValueError('staging file already exists; inspect transaction before continuing')
    sync_write(temporary,candidate)
    state['phase']='candidate-verified';state_write(state_path,state)
    if digest(target.read_bytes())!=expected_original:
        raise ValueError('boot file changed during staging; original retained')
    temporary.replace(target)
    if digest(target.read_bytes())!=state['candidate_sha256']:
        raise OSError('published boot file failed readback; restore required')
    state['phase']='installed';state_write(state_path,state)
    return state

def status(mount):
    mount=mount.resolve(strict=True)
    state=json.loads((mount/'LINNET/RECOVERY/BOOTSTRAP.JSON').read_text())
    # Paths in external journal are never used to select write destinations.
    if state.get('schema_version')!=1 or state.get('target_id')!='photo4g-p98':
        raise ValueError('unsupported bootstrap journal')
    result=dict(state)
    result['active_sha256']=digest((mount/'.rockbox/rockbox.ipod').read_bytes())
    result['backup_valid']=digest((mount/'LINNET/RECOVERY/ORIGINAL.IPOD').read_bytes())==state['original_sha256']
    return result

def restore(mount):
    mount=mount.resolve(strict=True);state=status(mount)
    if not state['backup_valid']:
        raise ValueError('recovery backup hash mismatch')
    if state['active_sha256'] not in (state['original_sha256'],state['candidate_sha256']):
        raise ValueError('boot file was changed independently; refusing to overwrite')
    original=(mount/'LINNET/RECOVERY/ORIGINAL.IPOD').read_bytes()
    target=mount/'.rockbox/rockbox.ipod'
    if state['active_sha256']!=state['original_sha256']:
        temporary=target.with_name('linnet-restore.ipod')
        if temporary.exists():
            raise ValueError('restore staging already exists; inspect before continuing')
        sync_write(temporary,original);temporary.replace(target)
    if digest(target.read_bytes())!=state['original_sha256']:
        raise OSError('restored boot file failed verification')
    state['phase']='restored';state['active_sha256']=state['original_sha256']
    state_write(mount/'LINNET/RECOVERY/BOOTSTRAP.JSON',state)
    return state
