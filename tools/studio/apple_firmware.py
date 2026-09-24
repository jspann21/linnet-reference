"""Publish a target-bound, verified Apple firmware fallback on an iPod volume."""
import hashlib
import os
from pathlib import Path
import struct
import zlib

from tools.studio.targets import TARGETS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def matches_signature(target_id, payload):
    """Apply an optional target-owned marker for the archived Apple format."""
    signature = TARGETS[target_id]["retail"].get("firmware_signature")
    if signature is None:
        return True
    marker = signature["ascii"].encode("ascii")
    start = signature["offset"]
    return payload[start:start + len(marker)] == marker


def encode(target_id, payload, expected_sha256=None):
    if target_id not in TARGETS:
        raise ValueError("Apple firmware fallback target is unsupported")
    payload = bytes(payload)
    actual = digest(payload)
    if (expected_sha256 is not None and actual != expected_sha256.lower()) or not 32 <= len(payload) <= TARGETS[target_id]["stage_bytes"]:
        raise ValueError("Apple firmware fallback failed its reviewed bounds or hash")
    if not matches_signature(target_id, payload):
        raise ValueError("Apple firmware is missing its target's image signature")
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


def available(root, target_id):
    """Match Boot's on-disk Apple fallback checks before listing it in Media Manager."""
    if target_id not in TARGETS:
        return False
    system = Path(root) / ".LINNET"
    config_path, image_path = system / "APPLE.CFG", system / "APPLE.BIN"
    try:
        if not config_path.is_file() or not image_path.is_file():
            return False
        if config_path.is_symlink() or image_path.is_symlink():
            return False
        config = config_path.read_bytes()
        if len(config) != 512 or config[:8] != b"APPLEOS1" or any(config[48:508]):
            return False
        target, size = struct.unpack_from("<II", config, 8)
        if (target != TARGETS[target_id]["image_target"] or not 32 <= size <= TARGETS[target_id]["stage_bytes"] or
                image_path.stat().st_size != size or zlib.crc32(config[:508]) != struct.unpack_from("<I", config, 508)[0]):
            return False
        image = image_path.read_bytes()
        return (len(image) == size and hashlib.sha256(image).digest() == config[16:48] and
                matches_signature(target_id, image))
    except OSError:
        # The volume may disappear during a Media Manager refresh.
        return False
