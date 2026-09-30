"""Host-side JSON cache reads and atomic state and receipt writes."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


def cache_directory(disk_serial, volume_serial):
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "Linnet" / "Media"
    key = hashlib.sha256((disk_serial + volume_serial).encode()).hexdigest()[:24]
    return base / key


def cache_root(identity):
    return cache_directory(identity.get("media_cache_disk_serial") or identity["disk_serial"],
                           identity["volume_serial"])


def load_json_object(path, *, encoding='utf-8'):
    """Missing, unreadable, or non-object cache state is a cache miss."""
    try:
        value = json.loads(path.read_text(encoding=encoding))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '-' + uuid.uuid4().hex + '.tmp')
    owned = False
    try:
        with temporary.open('x', encoding='utf-8') as writer:
            owned = True
            json.dump(value, writer, indent=2)
            writer.flush()
            os.fsync(writer.fileno())
        # Indexers and antivirus can briefly open the existing receipt without
        # delete sharing on Windows. Keep the fsynced temporary and retry only
        # those transient sharing/access failures; other errors remain fatal.
        for attempt in range(7):
            try:
                temporary.replace(path)
                break
            except OSError as error:
                if (os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33)
                        or attempt == 6):
                    raise
                time.sleep(min(0.05 * (2 ** attempt), 0.5))
    finally:
        if owned:
            temporary.unlink(missing_ok=True)
