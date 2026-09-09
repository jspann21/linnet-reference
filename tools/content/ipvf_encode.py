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
import time
from collections import deque
from contextlib import contextmanager

from .ipvf_validate import inspect_file


@contextmanager
def _scratch_directory(parent, progress):
    """Remove only this conversion's scratch and identify any cleanup failure."""
    parent = Path(parent).resolve()
    directory = Path(tempfile.mkdtemp(prefix="ipvf-encode-", dir=parent))
    failure = None
    try:
        yield directory
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            # Do not follow a directory replaced with a link outside our cache.
            if directory.resolve().parent != parent or directory.is_symlink():
                raise OSError("Temporary directory changed location")
            shutil.rmtree(directory)
        except OSError as cleanup_error:
            message = (f"Could not remove video temporary files: {directory}. "
                       f"Cleanup error: {cleanup_error}")
            try:
                progress(message)
            except Exception:
                pass
            error = RuntimeError(f"{failure}. {message}" if failure else message)
            error.cleanup_paths = [str(directory)]
            raise error from (failure or cleanup_error)
        else:
            # Reporting must not turn successful cleanup into a conversion failure.
            try:
                progress(f"Removed video temporary files: {directory}")
            except Exception:
                pass


def _duration_text(seconds):
    seconds = max(0, math.ceil(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


class _StageProgress:
    def __init__(self, stage, name, progress, detail):
        self.stage, self.name = stage, name
        self.progress, self.detail = progress, detail
        self.started = time.monotonic()
        self.samples = deque()
        self.frames, self.total = 0, None

    def emit(self, frames=None, total=None, *, complete=False):
        now = time.monotonic()
        elapsed = now - self.started
        if frames is not None:
            self.frames = frames
        if total is not None:
            self.total = total
        self.samples.append((now, self.frames))
        while len(self.samples) > 2 and now - self.samples[1][0] > 15:
            self.samples.popleft()
        rate = self.frames / elapsed if elapsed > 0 else 0
        recent_time = now - self.samples[0][0]
        if recent_time >= 2:
            recent = (self.frames - self.samples[0][1]) / recent_time
            rate = 0.5 * rate + 0.5 * recent
        percent = (min(99, 100 * self.frames / self.total)
                   if self.total else None)
        eta = ((self.total - self.frames) / rate
               if self.total and self.frames < self.total and elapsed >= 3 and rate > 0
               else None)
        label = "Converting" if self.stage == "convert" else "Checking IPVF"
        if complete:
            percent, eta = 100, 0
            status = "100% · complete"
        else:
            status = f"{percent:.0f}%" if percent is not None else f"{self.frames} frames"
            if eta is not None:
                status += f" · about {_duration_text(eta)} left in this stage"
            elif self.total and self.frames >= self.total:
                status += (" · finishing checks" if self.stage == "verify"
                           else " · duration estimate reached; finishing conversion")
            else:
                status += " · estimating time remaining"
        message = f"{label} {self.name}: {status} · {_duration_text(elapsed)} elapsed"
        if self.total:
            message += f" · {self.frames:,}/{self.total:,} frames"
        if rate > 0:
            message += f" · {rate:.1f} fps"
        self.progress(message)
        if self.detail:
            self.detail({"stage": self.stage, "percent": percent, "message": message,
                         "frames": self.frames, "total_frames": self.total,
                         "eta_seconds": eta, "elapsed_seconds": elapsed,
                         "frames_per_second": rate})


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
                progress=None, progress_detail=None, ffmpeg=None, ffprobe=None):
    """Create validated 220x176, 24-fps IPVF with 44.1-kHz adaptive IMA audio.

    Callbacks are ``cancelled() -> bool``, ``progress(message)``, and optional
    ``progress_detail(dict)`` (stage, percent, message, frames, total_frames,
    eta_seconds). Percent and ETA can be None; ETA covers only the named stage. The
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
    with _scratch_directory(destination.parent, progress) as temporary:
        directory = Path(temporary)
        encoded, log_path = directory / "video.ipvf", directory / "encode.log"
        request = directory / "request.json"
        request.write_text(json.dumps({"source": str(source), "output": str(encoded),
                                      "ffmpeg": executable, "ffprobe": probe,
                                      "title": title}), encoding="utf-8")
        conversion = _StageProgress("convert", source.name, progress, progress_detail)
        conversion.emit()
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW}
                   if os.name == "nt" else {"start_new_session": True})
        command = [sys.executable, "-u", "-m", "tools.content.ipvf_encode", str(request)]
        with log_path.open("wb") as log, log_path.open("rb") as updates:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                                       stdout=log, stderr=log, **options)
            try:
                pending = b""
                last_refresh = time.monotonic()
                while True:
                    if cancelled():
                        raise RuntimeError("Update cancelled")
                    pending += updates.read(65536)
                    lines = pending.split(b"\n")
                    pending = lines.pop()[-4096:]
                    for line in lines:
                        if line.startswith(b"IPVF_PROGRESS:"):
                            conversion.emit(int(line.partition(b":")[2].strip()))
                            last_refresh = time.monotonic()
                        elif line.startswith(b"IPVF_METADATA:"):
                            metadata = json.loads(line.partition(b":")[2])
                            conversion.emit(total=metadata.get("total_frames"))
                            last_refresh = time.monotonic()
                    if process.poll() is not None:
                        # Drain every remaining line, including short conversions.
                        tail = pending + updates.read()
                        for line in tail.splitlines():
                            if line.startswith(b"IPVF_PROGRESS:"):
                                conversion.emit(int(line.partition(b":")[2].strip()))
                            elif line.startswith(b"IPVF_METADATA:"):
                                conversion.emit(total=json.loads(line.partition(b":")[2]).get("total_frames"))
                        break
                    if time.monotonic() - last_refresh >= 5:
                        conversion.emit()
                        last_refresh = time.monotonic()
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
        conversion.emit(complete=True)
        verification = _StageProgress("verify", source.name, progress, progress_detail)
        verification.emit()
        last_update = time.monotonic()
        def checked(frame, count, pixels, audio):
            nonlocal last_update
            now = time.monotonic()
            if frame == 0 or frame + 1 == count or now - last_update >= 1:
                verification.emit(frame + 1, count)
                last_update = now
        result = inspect_file(encoded, cancelled=cancelled, on_frame=checked)
        if cancelled():
            raise RuntimeError("Update cancelled")
        os.replace(encoded, destination)
        verification.emit(result["frames"], result["frames"], complete=True)
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
                            "format=duration:stream=codec_type,duration", "-of", "json", str(source)],
                           capture_output=True, text=True, check=True)
    information = json.loads(probe.stdout)
    def finite_duration(value):
        try:
            value = float(value)
            return value if math.isfinite(value) and value > 0 else None
        except (TypeError, ValueError):
            return None
    video = next((stream for stream in information.get("streams", [])
                  if stream.get("codec_type") == "video"), {})
    format_duration = finite_duration(information.get("format", {}).get("duration"))
    duration = finite_duration(video.get("duration")) or format_duration
    if duration is None:
        raise ValueError("Video must have a known finite duration")
    print("IPVF_METADATA:" + json.dumps({"total_frames": math.ceil(duration * 24)}), flush=True)
    # Full PCM and the bounded encoded file coexist; decoded video is streamed.
    needed = math.ceil(max(duration, format_duration or duration) * 44100 * 4) + min(
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
    with output.open("rb") as encoded:
        header = encoded.read(20)
    print(f"IPVF_PROGRESS:{struct.unpack_from('<I', header, 16)[0]}", flush=True)


if __name__ == "__main__":
    _worker(sys.argv[1])
