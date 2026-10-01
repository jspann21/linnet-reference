"""Native MP4 preparation using each device's declared decoder limits."""
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

class _Bits:
    def __init__(self, data):
        self.data, self.at = data, 0

    def read(self, count):
        if self.at + count > len(self.data) * 8:
            raise ValueError("Truncated video configuration")
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.at // 8] >> (7 - self.at % 8)) & 1)
            self.at += 1
        return value

    def expect(self, count, value):
        if self.read(count) != value:
            raise ValueError("Video configuration uses unsupported decoder features")

    def ue(self):
        zeros = 0
        while not self.read(1):
            zeros += 1
            if zeros > 31:
                raise ValueError("Invalid video configuration code")
        return (1 << zeros) - 1 + self.read(zeros)


def _extradata(stream):
    try:
        data = bytes.fromhex("".join(line.split(":", 1)[1].split("  ", 1)[0].replace(" ", "")
                                     for line in stream.get("extradata", "").splitlines() if ":" in line))
    except ValueError as error:
        raise ValueError("Invalid video configuration") from error
    if not data or len(data) > 512:
        raise ValueError("Video configuration exceeds device limits")
    return data


def _check_h264_config(data):
    if len(data) < 7 or data[0] != 1 or data[1] != 66 or data[3] > 30:
        raise ValueError("H.264 needs a Baseline configuration at level 3 or below")
    at, count, sequence_id = 6, data[5] & 31, None
    for kind in (7, 8):
        if count != 1 or at + 2 > len(data):
            raise ValueError("H.264 needs one SPS and one PPS")
        length = int.from_bytes(data[at:at+2], "big")
        at += 2
        if not length or at + length > len(data) or data[at] & 31 != kind:
            raise ValueError("Invalid H.264 parameter set")
        raw, zeros = bytearray(), 0
        for value in data[at+1:at+length]:
            if zeros == 2 and value == 3:
                zeros = 0
                continue
            raw.append(value)
            zeros = zeros + 1 if value == 0 else 0
        bits = _Bits(raw)
        if kind == 7:
            bits.expect(8, 66)
            bits.read(16)
            sequence_id = bits.ue()
        else:
            bits.ue()
            if bits.ue() != sequence_id:
                raise ValueError("H.264 parameter sets disagree")
            bits.expect(1, 0)  # CABAC
            bits.read(1)
            if bits.ue():
                raise ValueError("H.264 slice groups are unsupported")
            bits.ue(); bits.ue()
            bits.expect(3, 0)  # weighted prediction
            bits.ue(); bits.ue(); bits.ue()  # signed QP codes have the same lengths
            bits.read(1)
            bits.expect(1, 0)  # constrained intra prediction
        at += length
        if kind == 7:
            if at >= len(data):
                raise ValueError("Missing H.264 picture parameter set")
            count = data[at]
            at += 1


def _check_mpeg4_config(data, width, height):
    # Match the independent VPU adapter's PacketVideo VOL admission rules.
    starts = [i for i in range(len(data) - 3)
              if data[i:i+3] == b"\x00\x00\x01" and 0x20 <= data[i+3] <= 0x2f]
    if len(starts) != 1:
        raise ValueError("MPEG-4 needs one rectangular video object layer")
    bits = _Bits(data[starts[0]+4:])
    bits.read(1)
    bits.expect(8, 1)
    version = 1
    if bits.read(1):
        version = bits.read(4)
        bits.read(3)
    aspect = bits.read(4)
    if not aspect:
        raise ValueError("Invalid MPEG-4 aspect ratio")
    if aspect == 15:
        bits.read(16)
    if bits.read(1):
        bits.expect(2, 1)
        bits.read(1)
        if bits.read(1):
            for count in (15, 15, 15, 14, 15):
                bits.read(count)
                bits.expect(1, 1)
    bits.expect(2, 0)
    bits.expect(1, 1)
    resolution = bits.read(16)
    if not resolution:
        raise ValueError("Invalid MPEG-4 time resolution")
    bits.expect(1, 1)
    if bits.read(1):
        bits.read(max(1, (resolution - 1).bit_length()))
    bits.expect(1, 1)
    bits.expect(13, width)
    bits.expect(1, 1)
    bits.expect(13, height)
    bits.expect(1, 1)
    bits.expect(1, 0)  # progressive
    bits.expect(1, 1)  # OBMC disabled
    bits.expect(1 if version == 1 else 2, 0)  # no sprite
    bits.expect(1, 0)  # eight-bit samples
    bits.expect(1, 0)  # H.263 quantization
    if version != 1:
        bits.expect(1, 0)  # no quarter-pixel motion
    if not bits.read(1):
        method = bits.read(2)
        if method < 2:
            bits.expect(1, 1)  # shape complexity disabled
            if not bits.read(1):
                bits.read(4)
            bits.expect(1, 1)
            if not bits.read(1):
                bits.read(4)
            if not bits.read(1):
                bits.read(6)
            bits.expect(1, 1)
            if method == 1:
                bits.expect(1, 1)
    bits.read(1)  # resynchronization markers
    bits.expect(1, 0)  # no data partitioning
    if version != 1:
        bits.expect(2, 0)  # no newpred or reduced-resolution VOP
    bits.expect(1, 0)  # no scalability


def _check_tables(path, size, sample_bytes=65536):
    count = 0
    metadata_at = media_at = None
    with path.open("rb") as source:
        def atoms(start, end, depth=0):
            nonlocal count, metadata_at, media_at
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
                if depth == 0:
                    if kind == b"moov": metadata_at = start
                    elif kind == b"mdat" and media_at is None: media_at = start
                if kind in (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"):
                    atoms(body, limit, depth + 1)
                elif kind in (b"stts", b"stsc", b"ctts", b"elst", b"stsz"):
                    source.seek(body); data = source.read(min(limit-body, 20))
                    if len(data) < 8: raise ValueError("Truncated MP4 table")
                    entries = struct.unpack(">I", data[4:8])[0]
                    if kind == b"stsz":
                        if len(data) < 12: raise ValueError("Truncated sample sizes")
                        samples = struct.unpack(">I", data[8:12])[0]
                        if not 0 < samples <= 1000000 or entries > sample_bytes: raise ValueError("Sample sizes exceed device limits")
                        if not entries:
                            if samples * 4 > limit-body-12: raise ValueError("Truncated sample sizes")
                            source.seek(body+12)
                            remaining = samples
                            while remaining:
                                batch = min(remaining, 16384)
                                values = source.read(batch * 4)
                                if len(values) != batch * 4: raise ValueError("Truncated sample sizes")
                                if any(not 0 < value <= sample_bytes for (value,) in struct.iter_unpack(">I", values)):
                                    raise ValueError("Compressed sample exceeds device buffer")
                                remaining -= batch
                    elif kind == b"elst":
                        if len(data) < 20 or data[0] or entries != 1 or int.from_bytes(data[12:16], "big", signed=True) < 0 or data[16:20] != b"\x00\x01\x00\x00": raise ValueError("Unsupported MP4 edit list")
                    else:
                        maximum = 1000000 if kind == b"stsc" else 128
                        if not 0 < entries <= maximum: raise ValueError("MP4 index exceeds device limits")
                        if kind == b"stsc":
                            if entries*12 != limit-body-8: raise ValueError("Truncated chunk map")
                            source.seek(body+8);previous=0;processed=0
                            while processed<entries:
                                batch=min(entries-processed,4096)
                                values=source.read(batch*12)
                                if len(values)!=batch*12: raise ValueError("Truncated chunk map")
                                for first,samples_per_chunk,description in struct.iter_unpack(">III",values):
                                    if first<=previous or (processed==0 and first!=1) or not 0<samples_per_chunk<=65536 or description!=1: raise ValueError("Unsupported chunk map")
                                    previous=first;processed+=1
                        if kind == b"ctts":
                            source.seek(body+8)
                            for _ in range(entries):
                                pair=source.read(8)
                                if len(pair)!=8 or int.from_bytes(pair[4:], "big"): raise ValueError("Reordered timestamps are unsupported")
                start = limit
        atoms(0, size)
    return metadata_at is not None and media_at is not None and metadata_at < media_at

def inspect_file(path, *, profile, ffprobe=None, cancelled=None):
    def checkpoint():
        if cancelled and cancelled():
            from .media_manager import Cancelled
            raise Cancelled("Native video preparation cancelled")

    if profile["video_backend"] not in ("bcm-mp4", "native-mp4"):
        raise ValueError("This target does not support native MP4")
    limits = profile["native_video"]
    path = Path(path)
    size = path.stat().st_size
    if not 8 <= size <= 0x7fffffff:
        raise ValueError("Native video must fit the supported 2 GiB file range")
    checkpoint()
    fast_start = _check_tables(path, size, limits.get("sample_bytes", 65536))
    checkpoint()
    probe = ffprobe or shutil.which("ffprobe")
    if not probe:
        raise ValueError("ffprobe is required to validate native video")
    command = [str(probe), "-v", "error", "-show_streams", "-show_data", "-show_format", "-of", "json", str(path)]
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                   creationflags=NO_WINDOW)
        started = time.monotonic()
        try:
            while process.poll() is None:
                checkpoint()
                remaining = 60 - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 60)
                try:
                    process.wait(timeout=min(.1, remaining))
                except subprocess.TimeoutExpired:
                    pass
            checkpoint()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode:
            errors.seek(0, os.SEEK_END)
            errors.seek(max(0, errors.tell() - 4000))
            raise ValueError("Could not inspect native video: " + errors.read().decode('utf-8', errors='replace')[-1000:])
        output.seek(0, os.SEEK_END)
        if output.tell() > 8 * 1024 * 1024:
            raise ValueError("Native video probe metadata exceeds 8 MiB")
        output.seek(0)
        data = json.loads(output.read().decode('utf-8'))
    streams = data.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(video) != 1 or len(audio) > 1 or len(streams) != len(video) + len(audio):
        raise ValueError("Native MP4 needs one video track and at most one AAC track")
    v = video[0]
    if "mp4" not in data.get("format", {}).get("format_name", "") or v.get("codec_tag_string") not in ("avc1", "mp4v"):
        raise ValueError("Native video requires an MP4 container with H.264 or MPEG-4 video")
    width, height = int(v.get("width", 0)), int(v.get("height", 0))
    if not 0 < width <= limits["mpeg4_width"] or not 0 < height <= limits["mpeg4_height"] or int(v.get("has_b_frames", 1)):
        raise ValueError("Native video geometry or frame reordering is unsupported")
    if v.get("codec_name") == "h264":
        if v.get("profile") not in ("Baseline", "Constrained Baseline", "66", "578") or int(v.get("level", 999)) > limits["h264_level"] or width > limits["h264_width"] or height > limits["h264_height"]:
            raise ValueError(f"H.264 exceeds this target’s Baseline level {limits['h264_level'] / 10:g} or {limits['h264_width']} x {limits['h264_height']} limits")
        if profile["video_backend"] == "native-mp4":
            if (width | height) & 1:
                raise ValueError("H.264 needs even video dimensions")
            _check_h264_config(_extradata(v))
    elif v.get("codec_name") not in profile.get("video_codecs", ["h264", "mpeg4"] if profile["video_backend"] == "bcm-mp4" else ["h264"]):
        raise ValueError("This target does not support this native video codec")
    elif v.get("codec_name") != "mpeg4" or v.get("profile") not in ("Simple Profile", "0"):
        raise ValueError("MPEG-4 needs Simple Profile")
    if (profile["video_backend"] == "bcm-mp4" and v.get("codec_name") == "mpeg4" and
            (width > limits["h264_width"] or height > limits["h264_height"]) and
            int(v.get("bit_rate") or 0) > limits["max_video_kbps"] * 1000):
        raise ValueError("MPEG-4 VGA bitrate exceeds this iPod's video limit")
    if profile["video_backend"] == "native-mp4" and v.get("codec_name") == "mpeg4":
        if (width | height) & 1:
            raise ValueError("MPEG-4 needs even video dimensions")
        _check_mpeg4_config(_extradata(v), width, height)
    fps = Fraction(v.get("avg_frame_rate", "0/1"))
    frames = int(v.get("nb_frames", 0))
    if not 0 < fps <= limits["max_fps"] or not 0 < frames <= 1000000:
        raise ValueError("Unsupported native video frame rate or sample count")
    if audio:
        a = audio[0]
        if a.get("codec_name") != "aac" or a.get("profile") not in ("LC", "1") or not 1 <= int(a.get("channels", 0)) <= 2 or not 8000 <= int(a.get("sample_rate", 0)) <= 48000:
            raise ValueError("Native video audio needs mono/stereo AAC-LC at 8–48 kHz")
        if float(a.get("duration") or 0) > float(v.get("duration") or 0) + .25:
            raise ValueError("Native video audio extends beyond the picture")
    brand = data.get("format", {}).get("tags", {}).get("major_brand", "").strip()
    extension = ".mov" if brand == "qt" else ".mp4"
    if extension not in profile["video_extensions"]:
        raise ValueError("This video container is unsupported by the selected iPod target")
    return dict(format="MP4", extension=extension, width=width, height=height, frames=frames, codec=v["codec_name"], file_bytes=size, bytes=size, fast_start=fast_start)

def prepare(source, output, *, profile, ffmpeg=None, ffprobe=None, progress=lambda message: None, cancelled=None):
    source, output = Path(source), Path(output)
    if source.suffix.lower() in (".ipvf", ".ipv"):
        raise ValueError("IPVF is not supported by this target")
    def checkpoint():
        if cancelled and cancelled():
            from .media_manager import Cancelled
            raise Cancelled("Native video preparation cancelled")
    checkpoint()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + "." + uuid.uuid4().hex + ".mp4")
    try:
        try:
            source_info = inspect_file(source, profile=profile, ffprobe=ffprobe, cancelled=cancelled)
            compatible = True
        except ValueError:
            compatible = False
        encoder = ffmpeg or shutil.which("ffmpeg")
        relocate = compatible and not source_info['fast_start'] and encoder
        if compatible and not relocate:
            progress("Copying compatible native video…")
            with source.open("rb") as reader, temporary.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    checkpoint(); writer.write(chunk)
                writer.flush(); os.fsync(writer.fileno())
        else:
            if not encoder:
                raise ValueError("ffmpeg is required to prepare native video")
            progress("Preparing video for faster loading…" if relocate else "Preparing H.264 video and AAC audio…")
            limits = profile["native_video"]
            width, height, fps = profile["video_width"], profile["video_height"], profile["video_fps"]
            if profile["video_backend"] == "native-mp4":
                width,height=limits["h264_width"],limits["h264_height"]
            if relocate:
                command = [str(encoder), "-nostdin", "-v", "error", "-i", str(source),
                           "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", str(temporary)]
            else:
                probe = ffprobe or shutil.which("ffprobe")
                if not probe:
                    raise ValueError("ffprobe is required to prepare native video")
                duration_probe = [str(probe), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=start_time,duration:format=start_time", "-of", "json", str(source)]
                with tempfile.TemporaryFile() as duration_output:
                    process = subprocess.Popen(duration_probe, stdin=subprocess.DEVNULL, stdout=duration_output,
                                               stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
                    try:
                        deadline = time.monotonic() + 60
                        while process.poll() is None:
                            checkpoint()
                            if time.monotonic() >= deadline:
                                raise ValueError("Could not determine the video track duration")
                            try:
                                process.wait(timeout=.2)
                            except subprocess.TimeoutExpired:
                                pass
                        duration_output.seek(0)
                        metadata = json.loads(duration_output.read(4096).decode("utf-8"))
                        picture = metadata.get("streams", [{}])[0]
                        container = metadata.get("format", {})
                        def timestamp(value):
                            try:
                                return Fraction(str(value))
                            except (ValueError, ZeroDivisionError):
                                return None
                        picture_start = timestamp(picture.get("start_time"))
                        container_start = timestamp(container.get("start_time"))
                        origin = container_start if container_start is not None else picture_start
                        picture_duration = timestamp(picture.get("duration"))
                        duration = (picture_start + picture_duration - origin
                                    if picture_start is not None and picture_duration is not None and origin is not None
                                    else Fraction(0))
                        if process.returncode:
                            raise ValueError("Could not determine the video track duration")
                    finally:
                        if process.poll() is None:
                            process.kill(); process.wait()
                if not duration:
                    # Matroska often omits stream.duration. Read the picture
                    # packet timeline instead of the container duration, which
                    # may include a much longer damaged soundtrack.
                    packet_probe = [str(probe), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(source)]
                    with tempfile.TemporaryFile() as packet_output:
                        process = subprocess.Popen(packet_probe, stdin=subprocess.DEVNULL, stdout=packet_output,
                                                   stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
                        try:
                            deadline = time.monotonic() + 60
                            while process.poll() is None:
                                checkpoint()
                                if time.monotonic() >= deadline:
                                    raise ValueError("Could not determine the video track duration")
                                try:
                                    process.wait(timeout=.2)
                                except subprocess.TimeoutExpired:
                                    pass
                            if process.returncode:
                                raise ValueError("Could not determine the video track duration")
                            packet_output.seek(0)
                            last_step = Fraction(0)
                            first_pts = None
                            picture_end = None
                            for count, line in enumerate(packet_output):
                                if count >= 1000000:
                                    raise ValueError("Video packet count exceeds preparation limits")
                                if not count % 4096:
                                    checkpoint()
                                fields = line.decode("ascii", errors="replace").strip().split(",")
                                try:
                                    pts = Fraction(fields[0])
                                except (ValueError, ZeroDivisionError):
                                    continue
                                first_pts = pts if first_pts is None else min(first_pts, pts)
                                try:
                                    step = Fraction(fields[1])
                                    if step > 0:
                                        last_step = step
                                except (IndexError, ValueError, ZeroDivisionError):
                                    step = last_step
                                end = pts + max(step, 0)
                                picture_end = end if picture_end is None else max(picture_end, end)
                            if picture_end is not None:
                                duration = picture_end - (origin if origin is not None else first_pts)
                        finally:
                            if process.poll() is None:
                                process.kill(); process.wait()
                if not 0 < duration <= 86400:
                    raise ValueError("Could not determine the video track duration")
                duration_text = f"{float(duration):.6f}"
                command = [str(encoder), "-nostdin", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2", "-r", str(fps), "-c:v", "libx264", "-profile:v", "baseline", "-level:v", str(limits["h264_level"] / 10), "-pix_fmt", "yuv420p", "-b:v", f"{limits['video_kbps']}k", "-maxrate", f"{limits['max_video_kbps']}k", "-bufsize", f"{limits['buffer_kbits']}k", "-g", str(fps * 2), "-bf", "0", "-af", "aresample=async=1:first_pts=0,apad", "-c:a", "aac", "-profile:a", "aac_low", "-ar", "44100", "-ac", "2", "-b:a", f"{limits['audio_kbps']}k", "-t", duration_text, "-movflags", "+faststart", str(temporary)]
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, creationflags=NO_WINDOW)
                try:
                    while process.poll() is None:
                        checkpoint()
                        try:
                            process.wait(timeout=.2)
                        except subprocess.TimeoutExpired:
                            pass
                    if process.returncode:
                        errors.seek(0, os.SEEK_END)
                        errors.seek(max(0, errors.tell() - 4000))
                        raise ValueError("Native video conversion failed: " + errors.read().decode("utf-8", errors="replace"))
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
        candidate = inspect_file(temporary, profile=profile, ffprobe=ffprobe, cancelled=cancelled)
        checkpoint(); os.replace(temporary, output)
        return candidate
    finally:
        if temporary.exists():
            temporary.unlink()
