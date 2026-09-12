"""Readable catalog labels for recursively discovered video sources."""
import hashlib
from pathlib import Path


def catalog_contains(root, relative, title, path=None):
    """Check the small bounded device catalog before trusting a video cache hit."""
    from .publish import _plain
    from .publish_video import _read_catalog, CATALOG_MAX_BYTES
    catalog = Path(root) / "LINNET" / "VIDEOS" / "INDEX.VID"
    try:
        _plain(catalog, Path(root))
        if not catalog.is_file() or catalog.stat().st_size > CATALOG_MAX_BYTES:
            return False
        entries = _read_catalog(catalog.read_bytes())
        key = hashlib.sha256(relative.encode("utf-8")).digest()
        expected = path or "/LINNET/VIDEOS/" + key.hex()[:8].upper() + ".IPV"
        return (key, expected, title) in entries if path is not False else any(k == key and t == title for k, p, t in entries)
    except (OSError, ValueError):
        return False


def video_title(relative):
    """Keep folder context and extensions within the firmware's 127-byte label.

    A stable source digest distinguishes long paths after shortening; keeping
    the end of the path preserves the actual video name instead of just a
    potentially long series of parent folders.
    """
    source = str(relative).replace("\\", "/")
    label = "".join(character if ord(character) >= 32 else " " for character in source).strip()
    if not label:
        label = "Video"
    encoded = label.encode("utf-8")
    if len(encoded) <= 127:
        return label
    suffix = " [" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16] + "]"
    prefix = encoded[:32].decode("utf-8", errors="ignore")
    separator = "…"
    budget = 127 - len((prefix + separator + suffix).encode("utf-8"))
    tail = encoded[-budget:].decode("utf-8", errors="ignore")
    return prefix + separator + tail + suffix
