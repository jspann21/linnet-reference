"""Strict host reader for the Linnet OS envelope; no device writes."""
import hashlib
import struct
import zlib

TARGET = "photo4g-p98"
PROFILES = ("release", "dev", "trace")

def pack(payload, profile, build_id, load, entry):
    header = bytearray(128)
    struct.pack_into("<4sHH7I", header, 0, b"LOS1", 1, 128, 98, 1,
                     PROFILES.index(profile), len(payload), load, entry,
                     zlib.crc32(payload))
    build_digest = bytes.fromhex(build_id)
    if len(build_digest) != 32:
        raise ValueError("build ID must decode to exactly 32 bytes")
    header[36:68] = build_digest
    struct.pack_into("<I", header, 124, zlib.crc32(header[:124]))
    return bytes(header) + payload

def inspect(data):
    if len(data) < 128:
        raise ValueError("truncated LOS header")
    magic, version, size, target, abi, profile, length, load, entry, crc = struct.unpack_from("<4sHH7I", data)
    if (magic, version, size, target, abi) != (b"LOS1", 1, 128, 98, 1):
        raise ValueError("unsupported image identity or ABI")
    if profile >= len(PROFILES) or any(data[68:124]):
        raise ValueError("invalid profile or reserved bytes")
    if len(data) != 128 + length or length < 4:
        raise ValueError("invalid payload size")
    if zlib.crc32(data[:124]) != struct.unpack_from("<I", data, 124)[0] or zlib.crc32(data[128:]) != crc:
        raise ValueError("image CRC mismatch")
    if load % 4 or entry % 4 or not (0 <= load <= entry <= load + length - 4 and load + length <= 0x01fff000):
        raise ValueError("invalid image address range")
    return dict(target_id=TARGET, boot_abi=abi, profile=PROFILES[profile],
                build_id=data[36:68].hex(), payload_bytes=length,
                load_address=load, entry_address=entry,
                sha256=hashlib.sha256(data).hexdigest())

def verify_release(data, symbols):
    identity = inspect(data)
    if identity["profile"] != "release":
        raise ValueError("release verifier requires release profile")
    forbidden = (b"LNK1", b"LNI1", b"linnet-link", b"ln_link_", b"ln_development_", b"ln_recovery_", b"devlink_", b"trace_",
                 b"inject_", b"screenshot_", b"chainload", b".dev_staging", b".dev_trace")
    haystack = data[128:] + symbols.encode("utf-8")
    hits = [item.decode() for item in forbidden if item in haystack]
    if hits:
        raise ValueError("release exclusion failure: " + ", ".join(hits))
    return dict(passed=True, checked_patterns=[item.decode() for item in forbidden], **identity)
