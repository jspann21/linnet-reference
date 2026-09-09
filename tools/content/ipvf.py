"""Host conversion of existing Rockbox IPVF videos into Linnet packages."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from .ipvf_validate import inspect_file


def compile_ipvf(source, output, *, ffmpeg=None, progress=None, cancelled=None):
    """Strictly reconstruct IPVF on the host, then use the normal PVID compiler."""
    from .video import compile_video
    source, output = Path(source), Path(output)
    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        raise ValueError("ffmpeg is required to prepare IPVF videos")
    progress = progress or (lambda message: None)
    cancelled = cancelled or (lambda: False)
    with source.open("rb") as reader:
        header = reader.read(80)
    if len(header) != 80 or header[:4] != b"IPVF":
        raise ValueError("Invalid IPVF header")
    header_size, width, height, numerator, denominator, _, frames = struct.unpack_from("<HHHHHHI", header, 4)
    if header_size != 80 or (width, height) != (220, 176) or not denominator or not 4 <= numerator / denominator <= 240 or not frames:
        raise ValueError("Unsupported IPVF geometry or frame rate")
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = frames * denominator / numerator
    # Raw decoded streams, a lossless intermediate, and the final package can
    # coexist. Reserve conservatively before starting any expensive decode.
    needed = int(frames * width * height * 2 * 2 + duration * (44100 * 4 * 2 + 24 * width * height * 2 + 48000 * 4) + 32 * 1024 * 1024)
    if shutil.disk_usage(output.parent).free < needed:
        raise ValueError(f"IPVF conversion needs about {needed / 1024**3:.1f} GB of free host cache space")
    with tempfile.TemporaryDirectory(prefix="ipvf-", dir=output.parent) as temporary:
        directory = Path(temporary)
        raw, pcm, intermediate = directory / "frames.rgb", directory / "audio.pcm", directory / "decoded.mkv"
        with raw.open("wb") as video_writer, pcm.open("wb") as audio_writer:
            def frame_ready(index, count, pixels, audio):
                video_writer.write(pixels)
                audio_writer.write(audio)
                if index % max(1, numerator // denominator) == 0:
                    progress(f"Decoding IPVF {source.name}: {index + 1}/{count} frames")
            inspect_file(source, on_frame=frame_ready, cancelled=cancelled)
        if cancelled():
            raise RuntimeError("Update cancelled")
        progress(f"Preparing decoded video: {source.name}")
        command = [str(executable), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-f", "rawvideo", "-pixel_format", "rgb565be", "-video_size", "220x176",
                   "-framerate", f"{numerator}/{denominator}", "-i", str(raw),
                   "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", str(pcm),
                   "-map", "0:v:0", "-map", "1:a:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
                   "-c:a", "pcm_s16le", str(intermediate)]
        with (directory / "ffmpeg.log").open("wb") as log:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
            try:
                while process.poll() is None:
                    if cancelled():
                        raise RuntimeError("Update cancelled")
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if process.returncode:
            raise ValueError("IPVF intermediate conversion failed: " + (directory / "ffmpeg.log").read_text(errors="replace")[-2000:])
        raw.unlink()
        pcm.unlink()
        if cancelled():
            raise RuntimeError("Update cancelled")
        progress(f"Compiling Linnet video: {source.name}")
        return compile_video(intermediate, output, ffmpeg=executable)
