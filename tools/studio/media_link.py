"""Recognize and open an identified Linnet Link connection from Media Manager."""
import time
from contextlib import ExitStack


def _classic_record(connection):
    from tools.studio.classic_recovery import _scope, load
    for path in _scope(connection['serial']).glob('*/NOR.JSON'):
        try:
            record, _, _ = load(path)
            if (record['monitor_build_id'] == connection['identity']['build_id'] and
                    record.get('startup_default_format') == 1):
                return record
        except (OSError, ValueError):
            continue
    return None


def discover():
    from tools.link.transport import SerialTransport
    from tools.link.session import Session
    from tools.link.identity import decode
    from tools.studio.targets import TARGETS
    connections = []
    for port in SerialTransport.discover():
        if (port['vid'], port['pid']) != (0x1209, 0x504a) or not port['serial_number']:
            continue
        session = None
        try:
            session = Session(SerialTransport(port['port']), timeout=2)
            identity = decode(session.hello())
            connection = dict(serial=port['serial_number'], identity=identity,
                              target_name=TARGETS[identity['target_id']]['name'])
            connection['can_open_disk'] = bool(identity['capabilities'] & 32 or
                identity['target_id'] == 'classic6g-n25' and identity['image_kind'] == 'boot' and
                _classic_record(connection))
            connections.append(connection)
        except (OSError, RuntimeError, ValueError):
            continue
        finally:
            if session is not None:
                session.close()
    return connections


def open_disk(connection, *, progress=lambda _message: None):
    from tools.content.publish import _exclusive
    with ExitStack() as locks:
        if connection['identity']['target_id'] == 'classic6g-n25':
            locks.enter_context(_exclusive(dict(volume_unique_id='classic-setup:'+connection['serial'])))
        return _open_disk(connection, progress=progress)


def open_setup(connection, *, section, progress=lambda _message: None):
    """Connect storage and read setup for the user's selected task."""
    if section not in ('startup', 'build', 'remove'):
        raise ValueError('Unknown iPod setup section')
    from tools.studio.installer import assess
    result = open_disk(connection, progress=progress)
    identity = result['reconnected_identity']
    progress('Reading installed builds and startup choices…')
    # Retain the mounted identity if assessment fails: storage has already
    # changed mode and the old Link connection is no longer usable.
    try:
        from tools.content.publish import pending_publications
        groups = pending_publications(identity)
        if groups:
            return dict(result, section=section, publication_recovery_pending=True,
                        identity=identity, groups=groups)
        review = assess(identity)
    except (OSError, RuntimeError, ValueError) as error:
        return dict(result, section=section, review=None, setup_error=str(error))
    return dict(result, section=section, review=review)


def _open_disk(connection, *, progress):
    from tools.link.campaign import connect
    from tools.content.media_manager import discover as disks
    session, _, current = connect(serial_number=connection['serial'])
    try:
        if any(current[key] != connection['identity'][key] for key in
               ('target_id', 'image_kind', 'build_id', 'generation')):
            raise ValueError('The connected software changed. Choose Refresh before opening Disk Mode.')
        progress('Opening Disk Mode automatically. Keep your iPod connected…')
        if current['capabilities'] & 32:
            session.reboot('disk')
        elif current['target_id'] == 'classic6g-n25' and current['image_kind'] == 'boot' and _classic_record(connection):
            from tools.link.classic_nor import _operation
            _operation(session, 67, 0x52454254, size=0)
        else:
            raise ValueError('Resume Classic installation to finish setting up this iPod.')
    finally:
        session.close()
    deadline = time.monotonic() + 90
    last_error = ''
    while time.monotonic() < deadline:
        try:
            result = disks(detailed=True)
        except (OSError, RuntimeError, ValueError) as error:
            last_error = str(error)
            time.sleep(.5)
            continue
        last_error = '; '.join(result['errors'])
        matches = [item for item in result['devices'] if item.get('linnet_usb_serial') == connection['serial'] and
                   item.get('native_target_id') == current['target_id']]
        if len(matches) > 1:
            raise ValueError('More than one mounted iPod matches this Link connection.')
        if matches:
            return dict(passed=True, reconnected_identity=matches[0], summary='Your iPod is ready for media management.')
        time.sleep(.5)
    raise TimeoutError('Disk Mode has not reconnected. Keep USB connected and choose Refresh.' +
                       (' '+last_error if last_error else ''))
