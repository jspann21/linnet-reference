"""Client for a session-scoped, fixed-operation Windows restart helper.

Only start requests Windows consent. Refresh requests never launch an elevated
process, accept arbitrary commands, or retry an uncertain disk mutation.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'out/restart-helper/session.json'


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_exact(stream, length):
    result = bytearray()
    while len(result) < length:
        part = stream.recv(length - len(result))
        if not part:
            raise RuntimeError('Restart helper disconnected; inspect the admitted request, do not retry')
        result.extend(part)
    return bytes(result)


def _request(state, operation, request_id, disk_number=4):
    request = json.dumps(dict(token=state['token'], op=operation,
                              request_id=request_id, disk_number=disk_number)).encode()
    with socket.create_connection(('127.0.0.1', state['port']), timeout=3) as connection:
        connection.settimeout(55)
        connection.sendall(struct.pack('<I', len(request)) + request)
        size = struct.unpack('<I', _read_exact(connection, 4))[0]
        if size > 65536:
            raise RuntimeError('Restart helper response exceeds limit')
        response = json.loads(_read_exact(connection, size))
    if response.get('request_id') != request_id:
        raise RuntimeError('Restart helper request identity mismatch')
    result = response.get('result')
    if not isinstance(result, dict):
        raise RuntimeError('Restart helper returned a malformed result')
    return result


def status():
    if not STATE.is_file():
        return dict(running=False, reason='Session restart helper has not been started')
    state = json.loads(STATE.read_text())
    try:
        result = _request(state, 'status', uuid.uuid4().hex)
        if result.get('plan_sha256') != state['plan_sha256']:
            raise RuntimeError('Restart helper plan differs from session')
        return dict(result, running=True, ready=not result.get('poisoned', True) and not state.get('pending_request'),
                    pending_request=state.get('pending_request'))
    except (OSError, ValueError, RuntimeError) as exc:
        return dict(running=False, reason=str(exc))


def prepare(plan_path, plan_sha256, volume_serial='3D9E4E60'):
    """Validate and compile locally, without requesting consent or device access."""
    from tools.studio.native_bootstrap import load_plan
    manifest, artifacts, original = load_plan(Path(plan_path), plan_sha256)
    if status()['running']:
        raise RuntimeError('A restart helper is already running; stop it before preparing a replacement')
    directory = ROOT / 'out/restart-helper' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    encode = lambda data: base64.b64encode(data).decode('ascii')
    sha = lambda data: hashlib.sha256(data).hexdigest()
    regions = [dict(offset=p['candidate_partition_offset'], data_base64=encode(a['candidate.bin']),
                    sha256=sha(a['candidate.bin'])) for p, a in artifacts.get('_predecessors', [])]
    regions.append(dict(offset=manifest['candidate_partition_offset'],
                        data_base64=encode(artifacts['candidate.bin']), sha256=sha(artifacts['candidate.bin'])))
    recipe = dict(firmware_base64=encode(original), firmware_sha256=sha(original),
                  mbr_base64=encode(artifacts['mbr.bin']), mbr_sha256=sha(artifacts['mbr.bin']),
                  directory_base64=encode(artifacts['directory-candidate.bin']),
                  directory_sha256=sha(artifacts['directory-candidate.bin']), regions=regions,
                  directory_offset=manifest['directory_partition_offset'],
                  disk_directory_offset=manifest['directory_disk_offset'],
                  partition_offset=manifest['partition_lba'] * 512,
                  disk_bytes=manifest['expected_device_bytes'], serial=manifest['expected_storage_serial'],
                  usbserial=manifest['expected_linnet_usb_serial'], plan_sha256=plan_sha256,
                  plan_path=str(Path(plan_path).resolve()), volume_serial=volume_serial,
                  volume_partition_offset=41126400, boot_build_id=manifest['image']['build_id'],
                  original_payload_offset=manifest['original_osos']['payload_offset'],
                  original_payload_bytes=manifest['original_osos']['payload_bytes'],
                  original_payload_sha256=manifest['original_osos']['payload_sha256'])
    recipe_path = directory / 'recipe.json'; _save(recipe_path, recipe)
    executable = directory / 'restart-helper.exe'
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    result = subprocess.run([str(compiler), '/nologo', '/target:exe', '/optimize+',
                             '/reference:System.Web.Extensions.dll', '/out:' + str(executable),
                             str(ROOT / 'tools/link/windows_restart_broker.cs')],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Restart helper compilation failed: ' + result.stdout + result.stderr)
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1', 0)); port = temporary.getsockname()[1]
    state = dict(version=1, session_id=directory.name, recipe=str(recipe_path), executable=str(executable),
                 recipe_sha256=sha(recipe_path.read_bytes()), executable_sha256=sha(executable.read_bytes()),
                 plan_sha256=plan_sha256, plan=str(Path(plan_path).resolve()),
                 token=secrets.token_hex(32), port=port)
    _save(directory / 'prepared.json', state)
    return dict(prepared=str(directory / 'prepared.json'), plan_sha256=plan_sha256,
                executable_sha256=state['executable_sha256'], elevation=False)


def start(prepared):
    """One normal Windows UAC consent starts an eight-hour restricted helper."""
    raise RuntimeError('Experimental helper disabled after Windows Defender blocked its verification command; do not bypass protection')
    import ctypes
    from ctypes import wintypes as w
    state = json.loads(Path(prepared).read_text())
    if status()['running']:
        raise RuntimeError('A restart helper is already running')
    for key in ('recipe', 'executable'):
        if hashlib.sha256(Path(state[key]).read_bytes()).hexdigest() != state[key + '_sha256']:
            raise ValueError('Prepared restart helper changed before launch')
    if len(state['session_id']) != 32 or any(c not in '0123456789abcdef' for c in state['session_id']):
        raise ValueError('Invalid prepared session ID')
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    # Copy verified bytes into a fresh protected directory before execution.
    # The elevated process never imports Python or workspace modules.
    script = r'''
$ErrorActionPreference='Stop'
$env:PSModulePath=Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\Modules'
$exe=[IO.File]::ReadAllBytes(EXE)
$recipe=[IO.File]::ReadAllBytes(RECIPE)
function Hash($bytes) { $h=[Security.Cryptography.SHA256]::Create(); try { ([BitConverter]::ToString($h.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() } finally { $h.Dispose() } }
if ((Hash $exe) -cne EXEHASH -or (Hash $recipe) -cne RECIPEHASH) { throw 'Prepared helper hash mismatch' }
$base=[Environment]::GetFolderPath('ProgramFiles')
if ((Get-Item -LiteralPath $base).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Program Files reparse point rejected' }
$dest=Join-Path $base SESSION
if (Test-Path -LiteralPath $dest) { throw 'Protected helper session already exists' }
[void][IO.Directory]::CreateDirectory($dest)
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($sid in @('S-1-5-18','S-1-5-32-544')) {
 $rule=New-Object Security.AccessControl.FileSystemAccessRule([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow')
 $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $dest -AclObject $acl
$binary=Join-Path $dest 'restart-helper.exe'
$config=Join-Path $dest 'recipe.json'
[IO.File]::WriteAllBytes($binary,$exe)
[IO.File]::WriteAllBytes($config,$recipe)
$arguments='--recipe "'+$config+'" --recipe-sha256 '+RECIPEHASH+' --port '+PORT+' --token '+TOKEN
Start-Process -FilePath $binary -ArgumentList $arguments -WorkingDirectory $dest -WindowStyle Hidden
'''
    replacements = dict(EXE=quote(state['executable']), RECIPE=quote(state['recipe']),
                        EXEHASH=quote(state['executable_sha256']), RECIPEHASH=quote(state['recipe_sha256']),
                        SESSION=quote('LinnetRestart-' + state['session_id']),
                        PORT=quote(state['port']), TOKEN=quote(state['token']))
    import re
    script = re.sub(r'\b(?:EXEHASH|RECIPEHASH|SESSION|RECIPE|EXE|PORT|TOKEN)\b',
                    lambda match: replacements[match[0]], script)
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    _save(STATE, state)
    result = shell.ShellExecuteW(None, 'runas', powershell,
                                '-NoProfile -NonInteractive -EncodedCommand ' + encoded, None, 0)
    if not result or result <= 32:
        raise RuntimeError('Windows did not launch the restart helper (UAC may have been declined)')
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        observed = status()
        if observed['running']:
            return observed
        time.sleep(.25)
    raise RuntimeError('Helper did not become ready; no disk operation requested')


def refresh(plan_path, plan_sha256, disk_number, receipt_path):
    import msvcrt
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.with_suffix('.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Another restart request owns the session') from exc
        try:return _refresh(plan_path,plan_sha256,disk_number,receipt_path)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def _refresh(plan_path, plan_sha256, disk_number, receipt_path):
    state = json.loads(STATE.read_text()) if STATE.is_file() else None
    if not state or not status().get('ready'):
        raise RuntimeError('Restart helper is unavailable; start it once before unattended sync. Disk has not been ejected')
    if (state['plan_sha256'], state['plan']) != (plan_sha256, str(Path(plan_path).resolve())):
        raise RuntimeError('Restart helper is pinned to a different reviewed plan')
    request_id = uuid.uuid4().hex
    path = Path(receipt_path)
    if path.exists():
        raise RuntimeError('Restart request receipt already exists; refusing replay')
    _save(path, dict(operation='restart-helper-request', request_id=request_id,
                     phase='admitted', passed=False, disk_number=disk_number, plan_sha256=plan_sha256))
    state['pending_request']=str(path.resolve());_save(STATE,state)
    result = _request(state, 'refresh', request_id, disk_number)
    _save(path, result)
    if result.get('idempotency_id')!=request_id or result.get('plan_sha256')!=plan_sha256:
        raise RuntimeError('Restart refresh receipt identity differs; session remains blocked')
    state.pop('pending_request',None);_save(STATE,state)
    if not result.get('passed'):
        raise RuntimeError('Restart refresh failed: ' + str(result.get('failure', result)))
    return result


def stop():
    state = json.loads(STATE.read_text())
    return _request(state, 'stop', uuid.uuid4().hex)
