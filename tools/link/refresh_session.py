"""Finite, plan-bound Windows directory-refresh session; ordinary UAC bootstrap.

The approved bootstrap copies hash-pinned source/data into an administrator-only
directory before starting the server. The pipe accepts no paths or payloads.
This is independent of the disabled experimental restart broker.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
import locale  # preload subprocess text decoding before elevated readiness
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DATA = (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) /
        'Linnet' / 'Refresh')
STATE = DATA / 'state.json'
SOURCES = ('tools/link/refresh_session.py', 'tools/studio/native_bootstrap.py',
           'tools/inspect/image.py', 'tools/studio/targets.py',
           # Target discovery validates each manifest's conventional source layout.
           'targets/photo4g-p98/target.toml', 'targets/ipod4g-q21/target.toml',
           'hal/pp5020/startup.S', 'hal/pp5020/memory.ld',
           'hal/pp5020/platform.c', 'hal/pp5020/display.c',
           'targets/photo4g-p98/lcd.c', 'targets/photo4g-p98/device.c',
           'targets/ipod4g-q21/lcd.c', 'targets/ipod4g-q21/device.c',
           'targets/ipod4g-q21/display.c')
MAX_MESSAGE = 65536


def _json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def _pack(value):
    if isinstance(value, bytes):
        return {'$bytes': base64.b64encode(value).decode('ascii')}
    if isinstance(value, (list, tuple)):
        return [_pack(item) for item in value]
    if isinstance(value, dict):
        return {key: _pack(item) for key, item in value.items()}
    return value


def _unpack(value):
    if isinstance(value, dict):
        if set(value) == {'$bytes'}:
            return base64.b64decode(value['$bytes'], validate=True)
        return {key: _unpack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unpack(item) for item in value]
    return value


class Windows:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('refresh sessions require Windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        signatures = {
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'LocalFree': ([ctypes.c_void_p], ctypes.c_void_p),
            'GetCurrentProcess': ([], w.HANDLE),
            'GetWindowsDirectoryW': ([w.LPWSTR, w.UINT], w.UINT),
            'CreateDirectoryW': ([w.LPCWSTR, ctypes.c_void_p], w.BOOL),
            'CreateNamedPipeW': ([w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p], w.HANDLE),
            'ConnectNamedPipe': ([w.HANDLE, ctypes.c_void_p], w.BOOL),
            'DisconnectNamedPipe': ([w.HANDLE], w.BOOL),
            'CreateFileW': ([w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            'ReadFile': ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            'WriteFile': ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            'PeekNamedPipe': ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            'GetNamedPipeServerProcessId': ([w.HANDLE, ctypes.POINTER(w.ULONG)], w.BOOL),
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result
        self.a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        self.a.OpenProcessToken.restype = w.BOOL
        self.a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
        self.a.GetTokenInformation.restype = w.BOOL
        self.a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
        self.a.ConvertSidToStringSidW.restype = w.BOOL
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL

    def check(self, value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def token(self, process=None):
        token = w.HANDLE()
        self.check(self.a.OpenProcessToken(process or self.k.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            size = w.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            data = ctypes.create_string_buffer(size.value)
            self.check(self.a.GetTokenInformation(token, 1, data, size, ctypes.byref(size)))
            sid = w.LPWSTR()
            self.check(self.a.ConvertSidToStringSidW(ctypes.c_void_p.from_buffer(data), ctypes.byref(sid)))
            try:
                text = sid.value
            finally:
                self.k.LocalFree(sid)
            elevated = w.DWORD()
            self.check(self.a.GetTokenInformation(token, 20, ctypes.byref(elevated), 4, ctypes.byref(size)))
            return text, bool(elevated.value)
        finally:
            self.k.CloseHandle(token)

    def security(self, sid, *, directory=False):
        if not re.fullmatch(r'S-1-5-(?:\d+-)*\d+', sid):
            raise ValueError('invalid owner SID')
        flags = 'OICI' if directory else ''
        access = 'GR' if directory else 'GRGW'
        sddl = f'O:BAG:BAD:P(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)(A;{flags};{access};;;{sid})'
        descriptor = ctypes.c_void_p()
        self.check(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None))
        class Attributes(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', w.BOOL)]
        return Attributes(ctypes.sizeof(Attributes), descriptor, False), descriptor

    def read(self, handle, timeout):
        deadline = time.monotonic() + timeout
        available = w.DWORD()
        while time.monotonic() < deadline:
            self.check(self.k.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None))
            if available.value:
                if available.value > MAX_MESSAGE:
                    raise ValueError('oversize pipe message')
                data, count = ctypes.create_string_buffer(MAX_MESSAGE), w.DWORD()
                self.check(self.k.ReadFile(handle, data, MAX_MESSAGE, ctypes.byref(count), None))
                return json.loads(data.raw[:count.value])
            time.sleep(.025)
        raise TimeoutError('session response timeout; do not replay refresh')

    def write(self, handle, value):
        data = json.dumps(value, separators=(',', ':')).encode('utf-8')
        if len(data) > MAX_MESSAGE:
            raise ValueError('oversize pipe message')
        count = w.DWORD()
        self.check(self.k.WriteFile(handle, data, len(data), ctypes.byref(count), None))
        if count.value != len(data):
            raise OSError('incomplete pipe response')


def prepare(plan_path, plan_sha256, *, hours=8, install_reviewed_boot=False):
    """Read-only device preparation; creates local immutable-content snapshot."""
    from tools.studio.native_bootstrap import load_plan
    if type(hours) is not int or not 1 <= hours <= 24:
        raise ValueError('session duration must be 1..24 hours')
    plan_path = Path(plan_path).resolve()
    manifest, artifacts, original = load_plan(plan_path, plan_sha256)
    artifacts=dict(artifacts)
    sid, _ = Windows().token()
    session_id = uuid.uuid4().hex
    directory = DATA / 'sessions' / session_id
    directory.mkdir(parents=True)
    config = dict(session_id=session_id, owner_sid=sid, seconds=hours * 3600,
                  install_reviewed_boot=bool(install_reviewed_boot),
                  plan=str(plan_path), plan_sha256=plan_sha256,
                  interpreter=str(Path(sys.executable).resolve()),
                  interpreter_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                  manifest=manifest, artifacts=_pack(artifacts), original=_pack(original))
    sources = {}
    for relative in SOURCES:
        data = (ROOT / relative).read_bytes()
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        sources[relative] = hashlib.sha256(data).hexdigest()
    config['sources'] = sources
    path = directory / 'snapshot.json'
    _json(path, config)
    prepared = dict(session_id=session_id, plan=str(plan_path), plan_sha256=plan_sha256,
                    snapshot=str(path), snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    script=str(directory / SOURCES[0]), interpreter=config['interpreter'],
                    interpreter_sha256=config['interpreter_sha256'], sources=sources,
                    owner_sid=sid, hours=hours,install_reviewed_boot=bool(install_reviewed_boot))
    _json(directory / 'prepared.json', prepared)
    return prepared


def bootstrap(snapshot, expected_hash):
    """The ordinary reviewed script is the UAC trust boundary, like an installer."""
    win = Windows()
    if not win.token()[1]:
        raise RuntimeError('bootstrap needs normal UAC elevation')
    data = Path(snapshot).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('snapshot hash differs from approved preparation')
    config = json.loads(data)
    if str(Path(sys.executable).resolve()) != config['interpreter'] or hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() != config['interpreter_sha256']:
        raise ValueError('interpreter differs from approved preparation')
    if set(config['sources']) != set(SOURCES):
        raise ValueError('unexpected source closure')
    source_bytes = {}
    for relative in SOURCES:
        source = (Path(snapshot).parent / relative).read_bytes()
        if hashlib.sha256(source).hexdigest() != config['sources'][relative]:
            raise ValueError('reviewed source hash mismatch')
        source_bytes[relative] = source
    windows = ctypes.create_unicode_buffer(32768)
    win.check(win.k.GetWindowsDirectoryW(windows, len(windows)))
    directory = Path(windows.value) / 'Temp' / ('LinnetRefresh-' + uuid.uuid4().hex)
    attributes, descriptor = win.security(config['owner_sid'], directory=True)
    try:
        win.check(win.k.CreateDirectoryW(str(directory), ctypes.byref(attributes)))
    finally:
        win.k.LocalFree(descriptor)
    # Parent is a system-owned directory; creation must be new and atomic. Its
    # protected DACL grants the caller read only, including inherited child ACLs.
    for relative, source in source_bytes.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
    protected_config = directory / 'snapshot.json'
    protected_config.write_bytes(data)
    child = subprocess.Popen([sys.executable, '-I', str(directory / SOURCES[0]),
                              '--serve', str(protected_config)], cwd=str(directory),
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if (directory / 'ready.json').is_file():
            return
        if child.poll() is not None:
            raise RuntimeError(f'protected refresh server exited ({child.returncode})')
        time.sleep(.1)
    raise TimeoutError('protected refresh server did not publish readiness')


def serve(snapshot):
    win = Windows()
    if not win.token()[1]:
        raise RuntimeError('server requires the elevated bootstrap')
    config = json.loads(Path(snapshot).read_text(encoding='utf-8'))
    # These imports are from the protected closure, before the pipe exists.
    sys.path.insert(0, str(ROOT))
    from tools.studio import native_bootstrap as native
    manifest, artifacts, original = config['manifest'], _unpack(config['artifacts']), _unpack(config['original'])
    device = json.loads(artifacts['device.json'])
    derived, candidate, old_directory, new_directory = native.derive(
        original, artifacts['mbr.bin'], artifacts['boot.los'], device)
    if (candidate, old_directory, new_directory) != (artifacts['candidate.bin'], artifacts['directory-original.bin'], artifacts['directory-candidate.bin']):
        raise ValueError('snapshot candidate derivation mismatch')
    if (len(new_directory) != 512 or manifest['directory_disk_offset'] !=
            manifest['partition_lba'] * 512 + manifest['directory_partition_offset']):
        raise ValueError('snapshot directory bounds mismatch')
    pipe = r'\\.\pipe\LinnetRefresh-' + config['session_id']
    attributes, descriptor = win.security(config['owner_sid'])
    try:
        # Duplex, first instance, message mode, nonblocking, reject remote clients.
        handle = win.k.CreateNamedPipeW(pipe, 3 | 0x80000, 4 | 2 | 1 | 8, 1, MAX_MESSAGE, MAX_MESSAGE, 0, ctypes.byref(attributes))
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        win.k.LocalFree(descriptor)
    directory = Path(snapshot).parent
    expires = time.monotonic() + config['seconds']
    status = dict(session_id=config['session_id'], plan=config['plan'], plan_sha256=config['plan_sha256'],
                  install_reviewed_boot=config.get('install_reviewed_boot') is True,
                  pid=os.getpid(), owner_sid=config['owner_sid'], poisoned=False,
                  started_at=datetime.now(timezone.utc).isoformat(), seconds=config['seconds'])
    _json(directory / 'ready.json', status)
    receipts = {}
    stop = False
    try:
        while time.monotonic() < expires and not stop:
            connected = win.k.ConnectNamedPipe(handle, None)
            if not connected and ctypes.get_last_error() not in (535,):
                if ctypes.get_last_error() == 536:  # no client yet
                    time.sleep(.05)
                    continue
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                response = None
                request = win.read(handle, 5)
                if not isinstance(request, dict) or request.get('session_id') != config['session_id']:
                    raise ValueError('session identity mismatch')
                command = request.get('command')
                if command in ('status', 'stop') and set(request) == {'session_id', 'command'}:
                    stop = command == 'stop'
                    response = dict(status, remaining_seconds=max(0, int(expires-time.monotonic())), stopping=stop)
                elif command in ('refresh','install') and set(request) == {'session_id', 'command', 'request_id', 'disk_number'}:
                    if command=='install' and config.get('install_reviewed_boot') is not True:
                        raise ValueError('approved session permits refresh only')
                    request_id, number = request['request_id'], request['disk_number']
                    if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id) or type(number) is not int or not 0 <= number <= 1024:
                        raise ValueError('invalid refresh identity')
                    if request_id in receipts:
                        prior = receipts[request_id]
                        if prior.get('requested_disk_number') != number or prior.get('command') != command:
                            raise ValueError('request ID reused with different disk')
                        response = prior
                    elif status['poisoned'] or len(receipts) >= 512:
                        raise RuntimeError('session writes revoked; inspect its receipts')
                    else:
                        response = dict(operation='install-reviewed-boot' if command=='install' else 'refresh-installed-directory', command=command, plan=config['plan'], plan_sha256=config['plan_sha256'],
                                        passed=False, device_write_attempted=False, writes=[], phase='identify-device',
                                        started_at=datetime.now(timezone.utc).isoformat(), requested_disk_number=number,
                                        request_id=request_id, session_id=config['session_id'])
                        receipts[request_id] = response
                        receipt_path = directory / (request_id + '.json')
                        try:
                            # Pin executable lookup: the native utility uses a fixed
                            # integer-only, read-only Get-Disk query. System PATH and
                            # protected cwd exclude workspace executables.
                            response['device'] = native.identify_disk(number, manifest)
                            with open(r'\\.\PhysicalDrive' + str(number), 'r+b', buffering=0) as device:
                                response['before'] = native.guard_device(device, manifest, artifacts, original)
                                if command=='install':
                                    if response['before']['staging']!='candidate':
                                        native.write_verified(device,manifest['candidate_disk_offset'],artifacts['candidate.bin'],response,receipt_path,'install-reviewed-payload')
                                    native.guard_device(device,manifest,artifacts,original)
                                elif response['before']['directory'] != 'candidate':
                                    raise RuntimeError('refresh requires exact installed candidate')
                                native.write_verified(device, manifest['directory_disk_offset'], new_directory, response, receipt_path, 'refresh-identical-directory')
                                response['after'] = native.guard_device(device, manifest, artifacts, original)
                                if command=='install' and (response['after']['directory']!='candidate' or response['after']['staging']!='candidate'):
                                    raise RuntimeError('installed Boot failed full guard')
                                if command=='refresh' and response['before'] != response['after']:
                                    raise RuntimeError('directory refresh changed firmware state')
                            response.update(passed=True, phase='complete')
                            if command=='refresh':response['bytes_changed']=0
                        except Exception as exc:
                            response['failure'] = f'{type(exc).__name__}: {exc}'
                            if response['device_write_attempted']:
                                status['poisoned'] = True
                        response['finished_at'] = datetime.now(timezone.utc).isoformat()
                        _json(receipt_path, response)
                else:
                    raise ValueError('unsupported command or fields')
                win.write(handle, response)
                if command in ('refresh','install'):
                    if win.read(handle, 5) != {'ack': request_id}:
                        raise RuntimeError('refresh completion was not acknowledged')
                # Give the client a bounded interval to consume the message before
                # DisconnectNamedPipe discards unread data.
                deadline = time.monotonic() + 5
                available = w.DWORD()
                while time.monotonic() < deadline and win.k.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                    time.sleep(.025)
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                if response and response.get('device_write_attempted'):
                    status['poisoned'] = True
                    _json(directory / 'revoked.json', dict(status, reason='refresh response was not acknowledged'))
                elif response is None:
                    try:
                        win.write(handle, dict(session_id=config['session_id'], plan_sha256=config['plan_sha256'],
                                               error=f'{type(exc).__name__}: {exc}'))
                        time.sleep(.1)
                    except OSError:
                        pass
            finally:
                win.k.DisconnectNamedPipe(handle)
    finally:
        win.k.CloseHandle(handle)
        _json(directory / 'closed.json', dict(status, closed_at=datetime.now(timezone.utc).isoformat()))


def request(state, command='status', *, disk_number=None, request_id=None):
    win = Windows()
    session_id = state.get('session_id', '')
    if not re.fullmatch('[0-9a-f]{32}', session_id):
        raise ValueError('invalid session ID')
    deadline = time.monotonic() + 5
    while True:
        handle = win.k.CreateFileW(r'\\.\pipe\LinnetRefresh-' + session_id, 0xC0000000, 0, None, 3, 0, None)
        if handle != ctypes.c_void_p(-1).value:
            break
        error = ctypes.get_last_error()
        if error != 231 or time.monotonic() >= deadline:
            raise ctypes.WinError(error)
        time.sleep(.025)  # connection discovery only; no request has been sent
    try:
        pid = w.ULONG()
        win.check(win.k.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)))
        process = win.check(win.k.OpenProcess(0x1000, False, pid.value))
        try:
            sid, elevated = win.token(process)
            if not elevated or sid != state['owner_sid']:
                raise RuntimeError('pipe server is not the approved elevated owner')
        finally:
            win.k.CloseHandle(process)
        message = dict(session_id=session_id, command=command)
        if command in ('refresh','install'):
            message.update(disk_number=disk_number, request_id=request_id or uuid.uuid4().hex)
        win.write(handle, message)
        response = win.read(handle, 60)
        if response.get('session_id') != session_id or response.get('plan_sha256') != state['plan_sha256']:
            raise RuntimeError('session response identity mismatch')
        if response.get('error'):
            raise RuntimeError(response['error'])
        if command in ('refresh','install'):
            if response.get('request_id') != message['request_id']:
                raise RuntimeError('refresh request identity mismatch')
            win.write(handle, {'ack': message['request_id']})
        return response
    finally:
        win.k.CloseHandle(handle)


def active(plan_path=None, plan_sha256=None):
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        if plan_path is not None and (state.get('plan'), state.get('plan_sha256')) != (str(Path(plan_path).resolve()), plan_sha256):
            return None
        status = request(state)
        if status.get('poisoned') or status.get('remaining_seconds', 0) <= 0:
            return None
        return state
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyError):
        return None


def start(prepared, *, allow_prompt=False):
    """Launch a reviewed preparation once; later clients reuse the live pipe."""
    from tools.link.eject import _elevated_refresh
    existing = active(prepared['plan'], prepared['plan_sha256'])
    if existing:
        status=request(existing)
        if prepared.get('install_reviewed_boot') and not status.get('install_reviewed_boot'):
            raise RuntimeError('active session permits refresh only; stop it before approving installation capability')
        return status
    arguments = subprocess.list2cmdline(['-I', prepared['script'], '--bootstrap', prepared['snapshot'],
                                        '--snapshot-sha256', prepared['snapshot_sha256']])
    _elevated_refresh(prepared['interpreter'], arguments, str(Path(prepared['snapshot']).parent),
                      allow_prompt=allow_prompt)
    status = request(prepared)
    if status.get('poisoned') or status.get('remaining_seconds', 0) <= 0:
        raise RuntimeError('new session is not ready')
    STATE.parent.mkdir(parents=True, exist_ok=True)
    _json(STATE, {key: prepared[key] for key in ('session_id', 'plan', 'plan_sha256', 'owner_sid')})
    return status


def refresh(plan_path, plan_sha256, disk_number, receipt_path):
    if not STATE.is_file():
        return False
    state = json.loads(STATE.read_text(encoding='utf-8'))
    if (state.get('plan'), state.get('plan_sha256')) != (str(Path(plan_path).resolve()), plan_sha256):
        return False
    try:
        status = request(state)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 2:  # pipe no longer exists
            return False
        raise  # a busy/uncertain live session must never cause a second writer
    if status.get('poisoned') or status.get('remaining_seconds', 0) <= 0:
        raise RuntimeError('session writes revoked or expired; inspect its receipts')
    request_id = uuid.uuid4().hex
    # Persist request identity before IPC so a caller can investigate uncertainty.
    _json(Path(receipt_path), dict(operation='refresh-installed-directory', passed=False,
                                 phase='request-session', session_id=state['session_id'],
                                 request_id=request_id, plan=str(Path(plan_path).resolve()),
                                 plan_sha256=plan_sha256))
    result = request(state, 'refresh', disk_number=disk_number, request_id=request_id)
    _json(Path(receipt_path), result)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap', type=Path)
    parser.add_argument('--snapshot-sha256')
    parser.add_argument('--serve', type=Path)
    args = parser.parse_args()
    if args.bootstrap and args.snapshot_sha256 and not args.serve:
        bootstrap(args.bootstrap, args.snapshot_sha256)
    elif args.serve and not args.bootstrap:
        # Pin executable search before importing the protected native utility.
        api = Windows()
        windows = ctypes.create_unicode_buffer(32768)
        api.check(api.k.GetWindowsDirectoryW(windows, len(windows)))
        system = Path(windows.value) / 'System32'
        os.environ['PATH'] = str(system) + os.pathsep + str(system / 'WindowsPowerShell/v1.0')
        serve(args.serve)
    else:
        parser.error('use the reviewed bootstrap or its protected server')
