"""Optional native host preparation for exact IPVF audio and video records."""
from functools import lru_cache
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_worker_path = False


@lru_cache(maxsize=1)
def library_path():
    if os.name != "nt":
        raise RuntimeError("Native IPVF preparation requires Windows")
    if getattr(sys, "frozen", False):
        destination = Path(sys._MEIPASS) / "ipvf-host.dll"
        if not destination.is_file():
            raise RuntimeError("IPVF host preparation helper is missing")
        return destination.resolve()
    from tools.studio.build import toolchain
    compiler = toolchain()["compiler"]
    flags = ["-shared", "-O3", "-flto", "-fwrapv", "-I."]
    inputs = ("tools/content/ipvf_host.c", "services/video/ipvf/ima_lookup.h")
    digest = hashlib.sha256(compiler["sha256"].encode())
    digest.update("\0".join(flags).encode())
    for name in inputs:
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    directory = ROOT / "out/ipvf-host" / digest.hexdigest()[:24]
    destination = directory / "ipvf-host.dll"
    if destination.is_file():
        return destination
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (uuid.uuid4().hex + ".dll")
    try:
        result = subprocess.run([compiler["path"], *flags, inputs[0], "-o", str(temporary)],
                                cwd=ROOT, capture_output=True, text=True, timeout=120,
                                creationflags=NO_WINDOW)
        if result.returncode:
            raise RuntimeError("IPVF host helper build failed: " + result.stderr[-4000:])
        try:
            # Windows rename never replaces an existing file. Another caller
            # may have published and loaded this exact recipe while we built.
            temporary.rename(destination)
        except OSError:
            if not destination.is_file():
                raise
    finally:
        temporary.unlink(missing_ok=True)
    return destination


@lru_cache(maxsize=1)
def _library():
    if os.name != "nt" or _worker_path is None:
        return None
    try:
        library = ctypes.CDLL(_worker_path or str(library_path()))
        function = library.ln_ipvf_encode_audio
        function.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                             ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        function.restype = ctypes.c_int32
        function = library.ln_ipvf_coalesce
        function.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                             ctypes.c_uint32]
        function.restype = ctypes.c_int32
        function = library.ln_ipvf_estimate_translation
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.POINTER(ctypes.c_int32)]
        function.restype = ctypes.c_int32
        return library
    except (OSError, RuntimeError, AttributeError, subprocess.SubprocessError):
        return None


def available():
    return _library() is not None


def worker_path():
    library = _library()
    return library._name if library is not None else None


def configure_worker(path):
    global _worker_path
    _worker_path = path
    _library.cache_clear()


def coalesce(packed, raw, minimum):
    if (type(packed) is not bytes or type(raw) is not bytes or
            not 0 < len(packed) <= 524288 or not 0 < len(raw) <= 262144 or
            type(minimum) is not int or not 4 <= minimum <= 262145):
        return None
    library = _library()
    if library is None:
        return None
    output = ctypes.create_string_buffer(len(raw) + len(raw) // 255 + 16)
    size = library.ln_ipvf_coalesce(packed, len(packed), raw, len(raw), minimum,
                                   output, len(output))
    if not 0 <= size <= len(output):
        raise RuntimeError("IPVF native match rewriter returned an invalid block")
    return ctypes.string_at(output, size)


def estimate_translation(previous, current, width, height, max_shift, sample_step):
    if (type(previous) is not bytes or type(current) is not bytes or
            any(type(value) is not int for value in
                (width, height, max_shift, sample_step)) or
            not 1 <= width <= 1024 or not 1 <= height <= 1024 or
            width * height > 131072 or len(previous) != width * height * 2 or
            len(current) != len(previous) or
            not 0 <= max_shift <= 32 or max_shift >= min(width, height) or
            not 1 <= sample_step <= 1024):
        return None
    library = _library()
    if library is None:
        return None
    state = (ctypes.c_int32 * 2)()
    result = library.ln_ipvf_estimate_translation(previous, current, len(current),
                width, height, max_shift, sample_step, state)
    if result != 0 or any(not -max_shift <= value <= max_shift for value in state):
        raise RuntimeError("IPVF native motion search returned an invalid vector")
    return tuple(state)


def encode_audio(pcm, frames, left_index, right_index):
    # Keep the Python path for unusual caller types and inputs outside this
    # bounded ABI; ordinary IPVF PCM blocks contain at most 11,025 frames.
    if (type(pcm) is not bytes or any(type(value) is not int for value in
            (frames, left_index, right_index)) or not 0 < frames <= 0x3fffffff or
            len(pcm) != frames * 4 or len(pcm) > 0xffffffff or
            not 0 <= left_index <= 88 or not 0 <= right_index <= 88):
        return None
    library = _library()
    if library is None:
        return None
    output = ctypes.create_string_buffer(frames + 7)
    state = (ctypes.c_uint32 * 3)()
    size = library.ln_ipvf_encode_audio(pcm, len(pcm), frames, left_index, right_index,
                                      output, len(output), state)
    kind = state[2]
    if (kind > 2 or size != (0, 4 + frames // 2, frames + 7)[kind] or
            state[0] > 88 or state[1] > 88):
        raise RuntimeError("IPVF native audio encoder returned an invalid block")
    return ctypes.string_at(output, size), state[0], state[1], ("silence", "mono", "stereo")[kind]
