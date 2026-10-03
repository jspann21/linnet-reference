"""Cancellable, validated source-video conversion using our canonical IPVF creator."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile

from .ipvf_validate import inspect_file


def _stop(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait()


def encode_ipvf(source, destination, *, title=None, cancelled=None,
                progress=None, ffmpeg=None, ffprobe=None):
    """Create validated 220x176, 24-fps IPVF with 44.1-kHz adaptive IMA audio.

    Callbacks are ``cancelled() -> bool`` and ``progress(message)``. The
    destination is replaced atomically only after complete strict validation.
    Cancellation raises RuntimeError; conversion failures raise ValueError.
    FFmpeg and FFprobe are required; liblz4 is optional (built-in fallback).
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    cancelled = cancelled or (lambda: False)
    progress = progress or (lambda message: None)
    if cancelled():
        raise RuntimeError("Update cancelled")
    if not source.is_file():
        raise ValueError(f"Video source does not exist: {source}")
    if source == destination:
        raise ValueError("IPVF output must differ from the source video")
    executable = str(ffmpeg or shutil.which("ffmpeg") or "")
    probe = str(ffprobe or "")
    if not probe and executable:
        sibling = Path(executable).with_name("ffprobe" + Path(executable).suffix)
        probe = str(sibling) if sibling.is_file() else (shutil.which("ffprobe") or "")
    if not executable or not probe:
        raise ValueError("FFmpeg and FFprobe are required to convert videos to IPVF")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ipvf-encode-", dir=destination.parent) as temporary:
        directory = Path(temporary)
        encoded, log_path = directory / "video.ipvf", directory / "encode.log"
        request = directory / "request.json"
        request.write_text(json.dumps({"source": str(source), "output": str(encoded),
                                      "ffmpeg": executable, "ffprobe": probe,
                                      "title": title}), encoding="utf-8")
        progress(f"Converting to IPVF: {source.name}")
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW}
                   if os.name == "nt" else {"start_new_session": True})
        command = [sys.executable, "-u", "-m", "tools.content.ipvf_encode", str(request)]
        with log_path.open("wb") as log, log_path.open("rb") as updates:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                                       stdout=log, stderr=log, **options)
            try:
                pending = b""
                while process.poll() is None:
                    if cancelled():
                        raise RuntimeError("Update cancelled")
                    pending += updates.read(65536)
                    lines = pending.split(b"\n")
                    pending = lines.pop()[-4096:]
                    for line in lines:
                        if line.startswith(b"IPVF_PROGRESS:"):
                            frame = line.partition(b":")[2].strip().decode("ascii", "replace")
                            progress(f"Converting {source.name}: {frame} frames")
                    try:
                        process.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                _stop(process)
        if cancelled():
            raise RuntimeError("Update cancelled")
        if process.returncode:
            with log_path.open("rb") as log:
                log.seek(max(0, log_path.stat().st_size - 2000))
                detail = log.read().decode("utf-8", "replace").strip()
            raise ValueError("IPVF conversion failed: " + detail)
        progress(f"Checking IPVF: {source.name}")
        result = inspect_file(encoded, cancelled=cancelled)
        if cancelled():
            raise RuntimeError("Update cancelled")
        os.replace(encoded, destination)
        result["path"] = str(destination)
        return result


def _pvid_intermediate(source, directory, ffmpeg):
    from .video import _inspect
    info = _inspect(source)
    width, height = info["width"], info["height"]
    frames, fps = info["frames"], info["fps"]
    needed = math.ceil(frames * width * height * 4 + frames / fps * 48000 * 8) + 32 * 1024**2
    if shutil.disk_usage(directory).free < needed:
        raise ValueError(f"Preparing PVID needs about {needed / 1024**3:.1f} GB of free cache space")
    raw, pcm, intermediate = directory / "frames.rgb", directory / "audio.pcm", directory / "source.mkv"
    with raw.open("wb") as pixels, pcm.open("wb") as audio:
        def visit(index, record, decoded):
            video_bytes = struct.unpack_from("<I", record, 12)[0]
            samples = struct.unpack_from("<I", record, 20)[0]
            pixels.write(decoded)
            audio.write(record[32 + video_bytes:32 + video_bytes + samples * 4])
        _inspect(source, frame_visitor=visit)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "rawvideo", "-pixel_format", "rgb565le", "-video_size", f"{width}x{height}",
                    "-framerate", str(fps), "-i", str(raw), "-f", "s16le", "-ar", "48000",
                    "-ac", "2", "-i", str(pcm), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "ffv1", "-pix_fmt", "bgr0", "-c:a", "pcm_s16le", str(intermediate)],
                   check=True)
    raw.unlink()
    pcm.unlink()
    return intermediate


def _worker(request):
    from . import ipvf_encoder as creator
    data = json.loads(Path(request).read_text(encoding="utf-8"))
    source, output = Path(data["source"]), Path(data["output"])
    source_name = source.stem
    if source.suffix.lower() in (".pvid", ".pvd"):
        source = _pvid_intermediate(source, output.parent, data["ffmpeg"])
    probe = subprocess.run([data["ffprobe"], "-v", "error", "-show_entries",
                            "format=duration", "-of", "json", str(source)],
                           capture_output=True, text=True, check=True)
    try:
        duration = float(json.loads(probe.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Video must have a known finite duration") from error
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video must have a known finite duration")
    # Full PCM and the bounded encoded file coexist; decoded video is streamed.
    needed = math.ceil(duration * 44100 * 4) + min(
        creator.DEVICE_FILE_SIZE_MAX, math.ceil(duration * 24 * 98304)) + 32 * 1024**2
    if shutil.disk_usage(output.parent).free < needed:
        raise ValueError(f"IPVF conversion needs about {needed / 1024**3:.1f} GB of free cache space")
    metadata = creator.probe_source_metadata(source, data["ffprobe"])
    metadata["title"] = data["title"] or metadata.get("title") or source_name
    # Format metadata has byte limits; truncate on UTF-8 character boundaries.
    metadata = {key: value.encode("utf-8")[:120].decode("utf-8", "ignore")
                for key, value in metadata.items() if value}
    creator.encode(source, output, 24, 120, data["ffmpeg"], video_mode="realtime",
                   metadata=metadata,
                   source_has_audio=creator.probe_source_has_audio(source, data["ffprobe"]))


if __name__ == "__main__":
    _worker(sys.argv[1])
