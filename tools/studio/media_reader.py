"""Interruptible desktop discovery and scanning; never write to the iPod."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


class ReadError(RuntimeError):
    def __init__(self, message, error_type):
        super().__init__(message)
        self.error_type = error_type


class _BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', w.DWORD), ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t), ('active_processes', w.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', _BasicLimits), ('io_counters', ctypes.c_uint64 * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


@contextmanager
def _reader_job(process):
    """Own the reader and its PowerShell probes, including on app exit."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = kernel.OpenProcess(0x0101, False, process.pid)  # SET_QUOTA | TERMINATE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not kernel.AssignProcessToJobObject(job, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.CloseHandle(handle)
        yield
    finally:
        kernel.CloseHandle(job)


def read(action, *, identity=None, photo_dimension=640, verification='metadata',
         cancelled=lambda: False):
    """Cancel even a blocked device read without abandoning a running thread."""
    from tools.content.media_manager import Cancelled
    from tools.studio.targets import ROOT

    if action not in ('devices', 'scan'):
        raise ValueError('Unknown device read operation')
    if cancelled():
        raise Cancelled()
    with tempfile.TemporaryDirectory(prefix='linnet-reader-') as temporary:
        request = Path(temporary) / 'request.json'
        response = Path(temporary) / 'response.json'
        request.write_text(json.dumps(dict(action=action, identity=identity,
            photo_dimension=photo_dimension, verification=verification)), encoding='utf-8')
        command = ([sys.executable, '--media-read'] if getattr(sys, 'frozen', False) else
                   [sys.executable, '-m', 'tools.studio.media_reader'])
        process = subprocess.Popen([*command, str(request), str(response)], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with _reader_job(process):
                # Do not let the worker touch the device or spawn probes until
                # all of those processes are covered by the same Windows job.
                if cancelled():
                    raise Cancelled()
                request.with_suffix('.ready').touch()
                while True:
                    if cancelled():
                        raise Cancelled()
                    try:
                        process.wait(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancelled():
                    raise Cancelled()
                if not response.is_file():
                    raise RuntimeError('The iPod read worker stopped without a result. Refresh to try again.')
                result = json.loads(response.read_text(encoding='utf-8'))
                if cancelled():
                    raise Cancelled()
                if result.get('error_type'):
                    raise ReadError(result['error'], result['error_type'])
                if process.returncode or 'value' not in result:
                    raise RuntimeError('The iPod read worker returned an incomplete result. Refresh to try again.')
                return result['value']
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    'Windows has not released the iPod read process. Let iTunes finish syncing before refreshing.'
                ) from error


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 2:
        return 2
    request, response = map(Path, arguments)
    try:
        deadline = time.monotonic() + 30
        while not request.with_suffix('.ready').is_file():
            if time.monotonic() >= deadline:
                raise RuntimeError('The iPod read worker was not started by its window.')
            time.sleep(0.05)
        options = json.loads(request.read_text(encoding='utf-8'))
        from tools.content import media_manager as media, media_status, publish
        if options['action'] == 'devices':
            value = media.discover(detailed=True)
            if not value['devices']:
                from tools.studio.media_link import discover
                value['links'] = discover()
        elif options['action'] == 'scan':
            identity = options['identity']
            media._volume_guard(identity)
            from tools.content.retail_media import check_tracks_access
            check_tracks_access(identity['root'])
            pending = publish.pending_publications(identity)
            value = (dict(publication_recovery_pending=True, identity=media.refresh(identity), groups=pending)
                     if pending else media_status.inspect(identity, options['photo_dimension'], options['verification']))
        else:
            raise ValueError('Unknown device read operation')
        result = dict(value=value)
        # Serialize inside the error boundary so an unsupported result is
        # reported to the window instead of leaving it without an explanation.
        data = json.dumps(result)
    except Exception as error:
        data = json.dumps(dict(error=str(error) or type(error).__name__, error_type=type(error).__name__))
        response.write_text(data, encoding='utf-8')
        return 1
    response.write_text(data, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
