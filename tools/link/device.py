"""Shared Linnet device discovery, identity, and receipt helpers."""
from datetime import datetime, timezone
import json
import time

from .identity import decode
from .session import Session
from .transport import SerialTransport


def connect(port=None, serial_number=None, deadline_seconds=15):
    """Probe only a selected port or identified Linnet USB endpoints."""
    deadline = time.monotonic() + deadline_seconds
    errors = []
    while time.monotonic() < deadline:
        inventory = SerialTransport.discover()
        candidates = [item for item in inventory
                      if (not port or item['port'] == port)
                      and (not serial_number or item['serial_number'] == serial_number)
                      and (port or serial_number or 'Linnet' in (item['description'] or ''))]
        if serial_number and len(candidates) > 1:
            raise RuntimeError("multiple USB endpoints have the requested serial identity")
        if not port and not serial_number and len(candidates) > 1:
            raise RuntimeError("multiple Linnet endpoints found; select a port or USB serial identity")
        for candidate in candidates:
            session = None
            try:
                session = Session(SerialTransport(candidate['port']), timeout=2)
                identity = decode(session.hello())
                if not candidate['serial_number']:
                    raise RuntimeError("Linnet USB endpoint has no stable hardware serial identity")
                return session, candidate, identity
            except (ValueError, RuntimeError, OSError) as exc:
                errors.append(str(exc))
                errors = errors[-4:]
                if session:
                    session.close()
        time.sleep(min(0.2, max(0, deadline-time.monotonic())))
    detail = ": " + '; '.join(errors) if errors else ""
    raise TimeoutError("no responding Linnet endpoint before deadline" + detail)


def wait_upload_ready(session, device, identity, timeout=180):
    """Resolve cold Boot's automatic handoff before sending upload bytes."""
    if identity.get('healthy'):
        return session, device, identity
    serial = device.get('serial_number')
    target = identity['target_id']
    if not serial:
        session.close()
        raise RuntimeError('Waiting for startup requires a stable USB serial')
    deadline = time.monotonic() + timeout
    session.close()
    while time.monotonic() < deadline:
        candidate = None
        ready = False
        try:
            candidate, observed_device, observed = connect(
                serial_number=serial,
                deadline_seconds=min(5, max(.1, deadline-time.monotonic())))
            confirmed = decode(candidate.status())
            if observed['target_id'] != target or confirmed['target_id'] != target:
                raise ValueError('Device target changed while waiting for startup')
            if ((observed['build_id'], observed['generation']) ==
                    (confirmed['build_id'], confirmed['generation']) and confirmed['healthy']):
                ready = True
                return candidate, observed_device, confirmed
        except (RuntimeError, OSError):
            pass
        finally:
            if candidate is not None and not ready:
                candidate.close()
        time.sleep(min(.2, max(0, deadline-time.monotonic())))
    raise TimeoutError('Startup did not settle; no upload was sent')


def check_healthy_identity(identity, image):
    if (identity.get('image_kind') != 'os' or identity.get('healthy') is not True or
            identity.get('health_flags') != 31 or identity.get('build_id') != image['build_id'] or
            identity.get('image_sha256') != image['sha256'] or
            any(identity.get(key) != image[key] for key in ('target_id', 'profile'))):
        raise ValueError('healthy image identity, hash, or health flags differ')


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def create_run_directory(root, identity):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root.mkdir(parents=True, exist_ok=True)
    for sequence in range(1, 10000):
        run_id = f"{stamp}-{identity['target_id']}-{identity['build_id'][:12]}-{sequence:04d}"
        directory = root / run_id
        try:
            directory.mkdir()
            return run_id, directory
        except FileExistsError:
            continue
    raise RuntimeError('run sequence exhausted')
