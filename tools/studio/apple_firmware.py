"""Publish a target-bound, verified Apple firmware fallback on an iPod volume."""
import hashlib
import os
from pathlib import Path
import struct
import zlib

from tools.studio.targets import TARGETS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(target_id, payload, expected_sha256=None):
    if target_id not in TARGETS:
        raise ValueError("Apple firmware fallback target is unsupported")
    payload = bytes(payload)
    actual = digest(payload)
    if (expected_sha256 is not None and actual != expected_sha256.lower()) or not 32 <= len(payload) <= TARGETS[target_id]["stage_bytes"]:
        raise ValueError("Apple firmware fallback failed its reviewed bounds or hash")
    config = bytearray(512)
    config[:8] = b"APPLEOS1"
    struct.pack_into("<II", config, 8, TARGETS[target_id]["image_target"], len(payload))
    config[16:48] = hashlib.sha256(payload).digest()
    struct.pack_into("<I", config, 508, zlib.crc32(config[:508]))
    return payload, bytes(config)


def publish(root, target_id, payload, expected_sha256=None):
    root = Path(root).resolve(strict=True)
    system = root / ".LINNET"
    if not system.is_dir() or system.is_symlink():
        raise ValueError("the mounted iPod has no ordinary .LINNET system directory")
    payload, config = encode(target_id, payload, expected_sha256)
    from tools.content.publish import _plain
    published = []
    for name, data in (("APPLE.BIN", payload), ("APPLE.CFG", config)):
        target = system / name
        _plain(target, root)
        if target.exists():
            if target.is_symlink() or target.read_bytes() != data:
                raise ValueError("the existing Apple firmware fallback differs: " + name)
        else:
            temporary = target.with_name(name + ".new")
            _plain(temporary, root)
            if temporary.exists():
                raise ValueError("Apple firmware fallback staging already exists: " + name)
            with temporary.open("xb") as writer:
                writer.write(data)
                writer.flush()
                os.fsync(writer.fileno())
            if temporary.read_bytes() != data:
                raise OSError("Apple firmware fallback staging failed verification: " + name)
            temporary.replace(target)
        if target.read_bytes() != data:
            raise OSError("Apple firmware fallback failed verification: " + name)
        published.append(dict(path=str(target.relative_to(root)).replace("\\", "/"),
                              bytes=len(data), sha256=digest(data)))
    return dict(target_id=target_id, payload_sha256=digest(payload), files=published)
