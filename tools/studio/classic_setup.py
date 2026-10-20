"""Media Manager's device-bound first installation for an Apple-mode Classic.

The only manual transition is entry into Apple's DFU mode. Once the temporary
monitor runs, Link owns diagnostics, backup, flash, and the native disk handoff.
All artifacts and receipts remain on the host if a stage cannot complete.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import time
import uuid

TARGET = 'classic6g-n25'
FORMAT = 'linnet-classic-setup-v1'


class Cancelled(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _scope(serial):
    from tools.studio.classic_recovery import _scope as recovery_scope
    return recovery_scope(serial).parent / 'setup'


def _load(path):
    from tools.link.classic_nor import _read_file
    value=json.loads(_read_file(path,1024*1024))
    if not isinstance(value,dict) or value.get('format')!=FORMAT:
        raise ValueError('Invalid Classic setup record')
    from tools.studio.classic_recovery import _serial
    _serial(value.get('serial'))
    if value.get('target_id')!=TARGET or value.get('build') not in ('user','dev'):
        raise ValueError('Invalid Classic setup identity')
    expected=_scope(value['serial']).resolve()
    if Path(path).resolve().parent.parent!=expected:
        raise ValueError('Classic setup record is outside its device directory')
    return value


def pending(identity=None):
    """Find unfinished host transactions; no device reads or writes."""
    from tools.studio.installer import cache_root
    if identity is not None and identity.get('target_id')!=TARGET:return []
    parent=cache_root(dict(target_id=TARGET,disk_serial='scope')).parent
    paths=(_scope(identity['linnet_usb_serial']).glob('*/setup.json') if identity is not None else
           parent.glob(TARGET+'-*/setup/*/setup.json'))
    found=[]
    for path in paths:
        try:
            state=_load(path)
            if state.get('phase') not in ('complete','cancelled'):
                found.append(dict(state,path=str(path),modified=path.stat().st_mtime_ns))
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return sorted(found,key=lambda item:item['modified'],reverse=True)


def _artifacts(state):
    from tools.studio.installer import _validate_artifacts
    artifacts=state['artifacts']
    _validate_artifacts(state['identity'],artifacts)
    for name,digest in state['artifact_hashes'].items():
        if _sha(artifacts[name])!=digest:raise ValueError('Saved Classic firmware changed: '+name)
    return artifacts


def prepare(identity, *, firmware=None, from_source=False, build='user', progress=lambda _message:None):
    from tools.content.media_manager import refresh
    from tools.studio import installer
    from tools.link import s5l_bootstrap as link
    identity=refresh(identity)
    if identity['target_id']!=TARGET or identity.get('native_target_id')==TARGET:
        raise ValueError('First-time Classic setup requires the selected Apple-mode iPod')
    if installer.installed_state(identity['root'],TARGET)['state']!='absent':
        raise ValueError('Inspect the existing Linnet installation before changing Classic Boot')
    if pending(identity):raise ValueError('Resume the existing Classic installation before starting another')
    directory=_scope(identity['linnet_usb_serial'])/uuid.uuid4().hex
    directory.mkdir(parents=True,exist_ok=False)
    if from_source:
        progress('Building Linnet for the connected Classic…')
        artifacts=installer.build_artifacts(identity,progress,build,'native-preserve',boot_profile='release')
    else:
        if firmware is None or build!='user':raise ValueError('Choose a User firmware ZIP or build from source')
        from tools.studio.firmware_bundle import load
        progress('Checking the selected Classic firmware ZIP…')
        artifacts=load(firmware,identity,'native-preserve')
        if not artifacts.get('bootstrap_template'):
            raise ValueError('This older Classic ZIP contains OS updates only. Choose a current ZIP with initial setup support.')
    persisted=installer._persist_artifacts(artifacts,directory)
    bootstrap=directory/'bootstrap'
    from tools.studio import s5l_bootstrap
    if from_source:s5l_bootstrap.build(identity['linnet_usb_serial'],bootstrap)
    else:s5l_bootstrap.bind(artifacts['bootstrap_template'],identity['linnet_usb_serial'],bootstrap)
    device=link.prepare(identity['root'],output=directory/'device.json',artifacts=bootstrap)
    state=dict(format=FORMAT,target_id=TARGET,serial=identity['linnet_usb_serial'],identity=identity,
               build=build,artifacts=persisted,phase='prepared',persistent_writes=False,
               device_plan=device['prepared'],device_plan_sha256=_sha(device['prepared']),
               artifact_hashes={name:_sha(persisted[name]) for name in
                   ('boot_image','boot_report','boot_wrapper','os_image','os_report')},
               bootstrap_hashes={name:_sha(bootstrap/name) for name in
                   ('manifest.json','monitor.bin','rom_transfer.bin','probe.bin','sram_bridge.bin','monitor.lnos','monitor-bridge.lnos')})
    installer._save(directory/'setup.json',state,durable=True)
    return directory/'setup.json'


def _mounted(state):
    from tools.content.media_manager import discover
    from tools.link.s5l_bootstrap import location
    from tools.studio.classic_recovery import _same_volume
    device=json.loads(Path(state['device_plan']).read_text())
    matches=[item for item in discover() if item.get('native_target_id')==TARGET and
             item.get('linnet_usb_serial')==state['serial']]
    if len(matches)>1:raise ValueError('More than one native disk matches this Classic')
    if not matches:return None
    current=matches[0]
    if location(current['usb_pnp_id'])!=device['usb_location']:
        raise ValueError('The Classic reconnected at a different USB port')
    _same_volume(current,state['identity'])
    return current


def _wait_disk(state, progress):
    progress('Waiting for the Classic to reconnect automatically in Linnet Disk Mode…')
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        current=_mounted(state)
        if current:return current
        time.sleep(.5)
    raise RuntimeError('Linnet Boot was installed, but its disk did not reconnect. Keep this iPod connected and use Resume Classic installation.')


def run(path, *, progress=lambda _message:None, instruction=lambda _message:None,
        cancelled=lambda:False):
    """Run or explicitly resume the exact saved installation, with no write retries."""
    from tools.studio import installer, classic_recovery
    from tools.content.publish import _exclusive
    from tools.link import s5l_bootstrap as link, classic_nor as nor
    from tools.link.transport import SerialTransport
    from tools.link.campaign import connect
    from tools.link.eject import eject
    path=Path(path);state=_load(path)
    if state['phase']=='complete':raise ValueError('This Classic installation is already complete')
    if _sha(state['device_plan'])!=state['device_plan_sha256']:
        raise ValueError('Classic device plan changed after preparation')
    bootstrap=link.artifacts_directory(json.loads(Path(state['device_plan']).read_text()))
    for name,digest in state['bootstrap_hashes'].items():
        if _sha(bootstrap/name)!=digest:raise ValueError('Saved Classic bootstrap changed: '+name)
    artifacts=_artifacts(state)
    def save():installer._save(path,state,durable=True)
    def guide(message, action=None):
        instruction(dict(message=message,can_stop=not state['persistent_writes'],action=action))
    def check_cancel():
        if cancelled() and not state['persistent_writes']:
            state['phase']='cancelled';save();raise Cancelled('Classic setup stopped before bootloader installation. No flash was written.')
    # A board-level mutex survives all storage mode transitions. Volume writers
    # also participate in their usual volume-specific exclusion at publication.
    with ExitStack() as locks:
        locks.enter_context(_exclusive(dict(volume_unique_id='classic-setup:'+state['serial'])))
        try:
            native=_mounted(state) if state.get('nor_plan') else None
            if native is None:
                check_cancel()
                ports=[p for p in SerialTransport.discover() if p['vid']==0x1209 and p['pid']==0x504a and
                       p['serial_number']==state['serial']]
                if len(ports)>1:raise ValueError('Classic Link identity is ambiguous')
                if not ports:
                    from tools.content.media_manager import discover, refresh
                    retail=[item for item in discover() if item.get('target_id')==TARGET and
                            item.get('linnet_usb_serial')==state['serial'] and not item.get('native_target_id')]
                    if len(retail)>1:raise ValueError('Classic Apple storage identity is ambiguous')
                    if retail:
                        current=refresh(retail[0])
                        classic_recovery._same_volume(state['identity'],current)
                        device=json.loads(Path(state['device_plan']).read_text())
                        if link.location(current['usb_pnp_id'])!=device['usb_location']:
                            raise ValueError('The Classic moved to a different USB port before DFU')
                        locks.enter_context(_exclusive(current))
                        progress('Safely ejecting the Classic before bootloader setup…')
                        eject(current['disk_number'],current['disk_serial'])
                    state['phase']='waiting-dfu';save()
                    guide('Turn the Hold switch off. Hold Menu + Select (the centre button) together for about 12 seconds, '
                                'through the restart, until this screen tells you to release them. Keep USB connected.',action='hold')
                    deadline=time.monotonic()+180
                    device=json.loads(Path(state['device_plan']).read_text())
                    while True:
                        check_cancel()
                        matches=[]
                        for item in link.interfaces():
                            instance='\\'.join(item['path'][4:].split('#')[:3])
                            if link.location(instance)==device['usb_location']:matches.append(item)
                        if len(matches)>1:raise ValueError('Classic DFU identity is ambiguous')
                        if matches:
                            if matches[0]['pid']!=0x1223:raise ValueError('This Classic has an unsupported BootROM')
                            break
                        if time.monotonic()>=deadline:raise TimeoutError('DFU mode was not detected. Use Resume Classic installation to try the button step again.')
                        time.sleep(.2)
                    guide('Release Menu + Select now. Your iPod’s screen will stay black briefly. Media Manager will continue automatically.',action='release')
                    # A continued button hold resets DFU again after eight seconds.
                    # Allow release/reset to settle before loading or writing flash.
                    until=time.monotonic()+10
                    while time.monotonic()<until:check_cancel();time.sleep(.1)
                    progress('Loading temporary Linnet Link; your original bootloader is unchanged…')
                    link.load(state['device_plan'],progress=progress)
                else:
                    session,_,running=connect(serial_number=state['serial'],deadline_seconds=15)
                    session.close()
                    manifest=json.loads((link.artifacts_directory(json.loads(Path(state['device_plan']).read_text()))/'manifest.json').read_text())
                    if running['image_kind']!='boot' or running['build_id']!=manifest['build_id']:
                        raise ValueError('The connected Link image differs from this installation’s monitor')
                state['phase']='monitor';save()
                guide('Linnet Link is connected. Checking this iPod’s hardware and saving recovery. No more buttons are needed.')
                progress('Checking Classic RAM, display, disk identity, and partition layout…')
                diagnostic=link.diagnose(state['device_plan'],display=True)
                diagnostic_path=path.parent/'hardware.json'
                installer._save(diagnostic_path,diagnostic,durable=True)
                state['hardware']=str(diagnostic_path);save()
                board=dict(line.split('=',1) for line in diagnostic['board'].splitlines() if '=' in line)
                if (int(board.get('ram_ready','0'),16)!=1 or int(board.get('ram_failure','1'),16) or
                    diagnostic['disk'].get('mbr_signature')!='55aa' or
                    diagnostic['disk'].get('native_storage_compatible') is not True or
                    diagnostic['disk'].get('sectors',0)*512<state['identity']['disk_bytes'] or
                    not diagnostic['display'].get('frame_transfer_complete')):
                    raise ValueError('This Classic did not pass its hardware checks; the original bootloader has not been changed')
                backup=Path(state.get('original_backup',path.parent/'original-nor.bin'))
                verified=False
                if backup.exists() or backup.with_suffix(backup.suffix+'.json').exists():
                    try:
                        nor._backup(backup,state['serial']);verified=True
                    except (OSError,ValueError):
                        # Never replace an artifact referenced by a flash plan.
                        # An incomplete read before planning gets a new name on
                        # explicit resume, retaining the failed read and receipt.
                        if state.get('nor_plan'):raise
                        backup=path.parent/('original-nor-'+uuid.uuid4().hex+'.bin')
                state['original_backup']=str(backup);save()
                if not verified:
                    progress('Saving and independently checking the complete original boot flash…')
                    link.backup_nor(state['device_plan'],backup)
                if not state.get('nor_plan'):
                    progress('Preparing the device-authenticated Linnet bootloader…')
                    planned=nor.prepare(state['device_plan'],backup,path.parent/'nor.json',boot_image=artifacts['boot_image'])
                    state.update(nor_plan=planned['prepared'],nor_plan_sha256=planned['plan_sha256'])
                    save()
                check_cancel()
                # From this point the guarded flash transaction must finish.
                state.update(phase='installing-boot',persistent_writes=True);save()
                guide('Installing and verifying Linnet Boot. Keep the iPod connected; Media Manager will restart it automatically.')
                nor.install(state['nor_plan'],state['nor_plan_sha256'],progress=progress,reboot_mode='disk')
                state['phase']='waiting-native-disk';save()
                native=_wait_disk(state,progress)
            locks.enter_context(_exclusive(native))
            from tools.content.media_manager import refresh
            native=refresh(native)
            state['phase']='installing-os';save()
            guide('Linnet Disk Mode is connected. Installing the OS and preserving Apple startup and recovery files…')
            # Establish the directory before portable recovery discovery; a
            # completed host NOR record is authoritative only for this serial.
            from tools.content.guard import guarded_path, guard_volume
            system=Path(native['root'])/'.LINNET'
            guarded_path(system,Path(native['root']));guard_volume(native);system.mkdir(exist_ok=True)
            classic_recovery.preserve(native)
            nor.preserve_apple(state['device_plan'],state['original_backup'],native['root'])
            from tools.studio.native_update import publish
            existing=installer.installed_state(native['root'],TARGET)
            if existing['state']=='installed':
                if existing.get('build_id')!=artifacts['os_build_id'] or existing.get('candidate_pending'):
                    raise ValueError('The installed OS differs from this saved Classic setup; inspect it before continuing')
                result=dict(passed=True,initial_installation=True,requires_safe_eject=True)
            else:
                result=publish(native,artifacts['os_image'])
            if not result.get('passed'):raise RuntimeError('OS installation did not verify')
            classic_recovery.preserve(native)
            state.update(phase='complete',result=result);state.pop('error',None);save()
            guide('Linnet is installed. Open Preparation to add media, or choose Eject safely to start your iPod.')
            return dict(passed=True,reconnected_identity=native,summary='Linnet Boot and OS installed and verified. Add media in Preparation, or eject safely to start Linnet.',
                        setup_receipt=str(path),hardware=state.get('hardware'))
        except Exception as error:
            state['error']=str(error);save()
            raise
