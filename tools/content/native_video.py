"""Native MP4 preparation for the BCM video target."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
from fractions import Fraction

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

def _check_tables(path, size):
    count = 0
    with path.open("rb") as source:
        def atoms(start, end, depth=0):
            nonlocal count
            if depth > 7:
                raise ValueError("MP4 nesting exceeds device limits")
            while start < end:
                source.seek(start); header = source.read(16)
                if len(header) < 8:
                    raise ValueError("Truncated MP4 atom")
                length, kind = struct.unpack(">I4s", header[:8]); head = 8
                if length == 1:
                    if len(header) < 16: raise ValueError("Truncated extended atom")
                    length = struct.unpack(">Q", header[8:])[0]; head = 16
                elif length == 0: length = end - start
                count += 1
                if length < head or length > end - start or count > 16384:
                    raise ValueError("MP4 atom bounds exceed device limits")
                if kind == b"moof": raise ValueError("Fragmented MP4 is unsupported")
                body, limit = start + head, start + length
                if kind in (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"):
                    atoms(body, limit, depth + 1)
                elif kind in (b"stts", b"stsc", b"ctts", b"elst", b"stsz"):
                    source.seek(body); data = source.read(min(limit-body, 20))
                    if len(data) < 8: raise ValueError("Truncated MP4 table")
                    entries = struct.unpack(">I", data[4:8])[0]
                    if kind == b"stsz":
                        if len(data) < 12: raise ValueError("Truncated sample sizes")
                        samples = struct.unpack(">I", data[8:12])[0]
                        if not 0 < samples <= 1000000 or entries > 65536: raise ValueError("Sample sizes exceed device limits")
                        if not entries:
                            if samples * 4 > limit-body-12: raise ValueError("Truncated sample sizes")
                            source.seek(body+12)
                            for _ in range(samples):
                                value = struct.unpack(">I", source.read(4))[0]
                                if not 0 < value <= 65536: raise ValueError("Compressed sample exceeds device buffer")
                    elif kind == b"elst":
                        if len(data) < 20 or data[0] or entries != 1 or int.from_bytes(data[12:16], "big", signed=True) < 0 or data[16:20] != b"\x00\x01\x00\x00": raise ValueError("Unsupported MP4 edit list")
                    else:
                        maximum = 256 if kind == b"stsc" else 128
                        if not 0 < entries <= maximum: raise ValueError("MP4 index exceeds device limits")
                        if kind == b"ctts":
                            source.seek(body+8)
                            for _ in range(entries):
                                pair=source.read(8)
                                if len(pair)!=8 or int.from_bytes(pair[4:], "big"): raise ValueError("Reordered timestamps are unsupported")
                start = limit
        atoms(0, size)

def inspect_file(path, *, ffprobe=None):
    path = Path(path)
    size = path.stat().st_size
    if not 8 <= size <= 0x7fffffff:
        raise ValueError("Native video must fit the supported 2 GiB file range")
    _check_tables(path, size)
    probe = ffprobe or shutil.which("ffprobe")
    if not probe:
        raise ValueError("ffprobe is required to validate native video")
    result = subprocess.run([str(probe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
    if result.returncode:
        raise ValueError("Could not inspect native video: " + result.stderr[-1000:])
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(video) != 1 or len(audio) > 1 or len(streams) != len(video) + len(audio):
        raise ValueError("Native MP4 needs one video track and at most one AAC track")
    v = video[0]
    if "mp4" not in data.get("format", {}).get("format_name", "") or v.get("codec_tag_string") not in ("avc1", "mp4v"):
        raise ValueError("Native video requires an MP4 container with H.264 or MPEG-4 video")
    width, height = int(v.get("width", 0)), int(v.get("height", 0))
    if not 0 < width <= 640 or not 0 < height <= 480 or int(v.get("has_b_frames", 1)):
        raise ValueError("Native video geometry or frame reordering is unsupported")
    if v.get("codec_name") == "h264":
        if v.get("profile") not in ("Baseline", "Constrained Baseline") or int(v.get("level", 999)) > 13 or width > 320 or height > 240:
            raise ValueError("H.264 needs Baseline level 1.3 at up to 320 x 240")
    elif v.get("codec_name") != "mpeg4" or v.get("profile") != "Simple Profile":
        raise ValueError("MPEG-4 needs Simple Profile")
    fps = Fraction(v.get("avg_frame_rate", "0/1"))
    frames = int(v.get("nb_frames", 0))
    if not 0 < fps <= 30 or not 0 < frames <= 1000000:
        raise ValueError("Unsupported native video frame rate or sample count")
    if audio:
        a = audio[0]
        if a.get("codec_name") != "aac" or a.get("profile") != "LC" or not 1 <= int(a.get("channels", 0)) <= 2 or not 8000 <= int(a.get("sample_rate", 0)) <= 48000:
            raise ValueError("Native video audio needs mono/stereo AAC-LC at 8–48 kHz")
    return dict(format="MP4", width=width, height=height, frames=frames, codec=v["codec_name"], file_bytes=size, bytes=size)

def prepare(source, output, *, ffmpeg=None, ffprobe=None, progress=lambda message: None, cancelled=None):
    source, output = Path(source), Path(output)
    def checkpoint():
        if cancelled and cancelled():
            from .media_manager import Cancelled
            raise Cancelled("Native video preparation cancelled")
    checkpoint()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + "." + uuid.uuid4().hex + ".mp4")
    try:
        try:
            inspect_file(source, ffprobe=ffprobe)
            compatible = True
        except ValueError:
            compatible = False
        if compatible:
            progress("Copying compatible native MP4…")
            with source.open("rb") as reader, temporary.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    checkpoint(); writer.write(chunk)
                writer.flush(); os.fsync(writer.fileno())
        else:
            encoder = ffmpeg or shutil.which("ffmpeg")
            if not encoder:
                raise ValueError("ffmpeg is required to prepare native video")
            progress("Preparing H.264 video and AAC audio…")
            command = [str(encoder), "-nostdin", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-vf", "scale=320:240:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=320:240:(ow-iw)/2:(oh-ih)/2", "-r", "24", "-c:v", "libx264", "-profile:v", "baseline", "-level:v", "1.3", "-pix_fmt", "yuv420p", "-b:v", "800k", "-maxrate", "1000k", "-bufsize", "2000k", "-g", "48", "-bf", "0", "-c:a", "aac", "-profile:a", "aac_low", "-ar", "44100", "-ac", "2", "-b:a", "128k", "-movflags", "+faststart", str(temporary)]
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, creationflags=NO_WINDOW)
                try:
                    while process.poll() is None:
                        checkpoint(); time.sleep(.2)
                    if process.returncode:
                        errors.seek(0); raise ValueError("Native video conversion failed: " + errors.read()[-4000:].decode("utf-8", errors="replace"))
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
        candidate = inspect_file(temporary, ffprobe=ffprobe)
        checkpoint(); os.replace(temporary, output)
        return candidate
    finally:
        if temporary.exists():
            temporary.unlink()
