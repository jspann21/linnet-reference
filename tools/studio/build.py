"""Reproducible freestanding ARM build, invoked by the sole Linnet CLI."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tomllib
from tools.inspect.image import pack, inspect, verify_release

ROOT = Path(__file__).resolve().parents[2]
ALIASES = {name: "photo4g-p98" for name in ("photo4g-p98", "photo4g", "ipod-photo", "a1099", "photo4g-a1099", "p98")}

def target_id(value):
    if value not in ALIASES:
        raise ValueError(f"unsupported target: {value}")
    return ALIASES[value]

def run(args):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result.stdout.strip()

def toolchain():
    spec = tomllib.loads((ROOT / "config/toolchain.toml").read_text())["toolchain"]
    result = {}
    for name in ("compiler", "linker", "objcopy", "nm"):
        executable = shutil.which(spec[name])
        if executable is None:
            raise RuntimeError(f"missing {spec[name]}; install LLVM {spec['version']} (Windows: WSL {spec['windows_wsl_distribution']})")
        version = run([executable, "--version"])
        if not re.search(r"\b" + re.escape(spec["version"]) + r"\b", version):
            raise RuntimeError(f"toolchain pin mismatch: {version}; expected {spec['version']}")
        result[name] = dict(path=executable, version=version, sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest())
    return result

def source_paths():
    """Prune generated trees before descent; sort only source inputs."""
    excluded = {".git", "out", "__pycache__", ".venv"}
    paths = []
    def fail(error):
        raise error
    for directory, directories, files in os.walk(ROOT, onerror=fail, followlinks=False):
        directories[:] = [name for name in directories if name not in excluded]
        paths.extend(Path(directory) / name for name in files
                     if name not in excluded and Path(name).suffix != ".pyc"
                     and (Path(directory) / name).is_file())
    return sorted(paths)

def source_identity(configuration, chain):
    digest = hashlib.sha256()
    for path in source_paths():
        data = path.read_bytes()
        name = path.relative_to(ROOT).as_posix().encode()
        digest.update(struct.pack("<I", len(name)) + name + struct.pack("<Q", len(data)) + data)
    digest.update(json.dumps(configuration, sort_keys=True).encode())
    digest.update(json.dumps({k: {field: v[field] for field in ('version', 'sha256')} for k, v in chain.items()}, sort_keys=True).encode())
    return digest.hexdigest()

def build(profile, target, verify=False, kind="os", probe="frame", device_serial="", batch=0, system_config=None):
    target = target_id(target)
    chain = toolchain()
    if profile == "release" and probe != "frame":
        raise ValueError("deliberate crash probes require dev or trace")
    if device_serial and not re.fullmatch(r"[A-Za-z0-9-]{1,32}", device_serial):
        raise ValueError("device serial must be 1..32 letters, digits or hyphens")
    if profile != "release" and not device_serial:
        raise ValueError("development USB requires --device-serial from physical device enumeration")
    if batch not in (0, 1, 2, 3, 4, 5, 6, 7):
        raise ValueError("supported build batches are 0 through 7; Batch 7 is under qualification")
    configuration = dict(profile=profile, target_id=target, kind=kind, probe=probe, device_serial=device_serial, batch=batch)
    if batch>=3:configuration["system_config"]=str(system_config or "config/system.toml")
    dest = ROOT / "out" / profile / target / kind
    dest.mkdir(parents=True, exist_ok=True)
    generated = dest / "generated"
    generated.mkdir(exist_ok=True)
    ui_report = None
    if batch >= 3 and kind == "os":
        from tools.content.compiler import compile_system
        ui_report = compile_system(ROOT, generated, Path(system_config) if system_config else None)
        # The compiler identity covers the exact selected input bytes, including
        # configuration/assets under excluded output or cache directories.
        configuration["content_id"] = ui_report["content_id"]
    build_id = source_identity(configuration, chain)
    (generated / "linnet_build.h").write_text('#define LINNET_BUILD_ID "' + build_id + '"\n#define LINNET_BUILD_ID_BYTES {' + ','.join('0x' + build_id[i:i+2] for i in range(0, 64, 2)) + '}\n')
    with (generated / "linnet_build.h").open('a') as header:
        header.write('#define LINNET_USB_SERIAL "' + device_serial + '"\n')
    prefix = f"linnet-{kind}-0.1.0-{target}-{profile}-{build_id[:12]}"
    sources = [ROOT / "targets" / target / "startup.S", ROOT / "hal/pp5020/entry.S", ROOT / "hal/pp5020/platform.c", ROOT / "kernel/main.c", ROOT / "kernel/memory.S"]
    sources += [ROOT / "boot/src/linnet_boot.c"]
    if batch >= 1:
        sources += [ROOT / name for name in ("hal/pp5020/core.c", "hal/pp5020/input.c", "hal/pp5020/power.c", "hal/pp5020/display.c")]
        if batch >= 6 and kind == "os":
            sources += [ROOT / name for name in ("hal/pp5020/video_blit.c", "hal/pp5020/video_blit.S")]
        if kind == "os":
            sources += [ROOT / name for name in ("kernel/executive.c", "kernel/runtime.c", "kernel/wheel_motion.c")]
            sources += [ROOT / ("ui/runtime/shell_adapter.c" if batch>=3 else "kernel/shell.c")]
            if batch>=3: sources += [ROOT / "services/display/clock.c"]
    if profile != "release":
        sources += sorted((ROOT / "hal/link").glob("*.c"))
        sources += [ROOT / name for name in ("boot/src/loader.c", "boot/src/sha256.c", "hal/pp5020/usb.c", "hal/pp5020/recovery.c", "hal/pp5020/recovery.S", "kernel/development.c")]
        if batch >= 1 and kind == "os":
            sources += [ROOT / "kernel/platform_link.c"]
    if batch >= 2:
        sources += [ROOT / name for name in (
            "hal/pp5020/ata.c", "services/storage/block.c", "services/storage/fat32.c",
            "services/storage/storage.c", "services/state/store.c", "services/update/update.c", "boot/src/persistent_enter.S")]
        if profile == "release":
            sources += [ROOT / "boot/src/sha256.c"]
        else:
            sources += [ROOT / "kernel/storage_link.c"]
            if kind == "os":
                sources += [ROOT / "services/update/native.c"]
    if batch>=3 and kind=="os":
        sources += [ROOT/"ui/runtime/ui.c",generated/"linnet_ui.c",ROOT/"services/display/settings.c"]
    flags = ["--target=arm-none-eabi", "-mcpu=arm7tdmi", "-marm", "-mfloat-abi=soft", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-ffunction-sections", "-fdata-sections", "-Os", "-Wall", "-Wextra", "-Werror", "-I.", "-Iboot/include", f"-DLINNET_PROFILE_{profile.upper()}=1", f"-DLINNET_IMAGE_{kind.upper()}=1"]
    flags += ["-I" + str(generated), f"-DLINNET_PROBE_CRASH={int(probe == 'crash')}", f"-DLINNET_PROBE_HANG={int(probe == 'hang')}"]
    if batch >= 1:
        flags += ["-DLINNET_PLATFORM_CORE=1"]
    if batch >= 2:
        flags += ["-DLINNET_STORAGE=1"]
    if batch>=3 and kind=="os":flags += ["-DLINNET_NATIVE_UI=1"]
    if batch>=4 and kind=="os":
        flags += ["-DLINNET_AUDIO=1"]
        sources += [ROOT/'hal/pp5020/audio.c',ROOT/'services/audio/codec_pcm.c']
        sources += [ROOT/'services/music/player.c',ROOT/'services/music/database.c']
        sources += [ROOT/'services/music/library.c',ROOT/'services/music/controller.c',ROOT/'services/music/queue.c',ROOT/'services/music/ui.c']
        sources += [ROOT/'services/music/artwork.c']
        sources += [ROOT/'services/music/browser.c']
        sources += [ROOT/'services/music/search.c',ROOT/'services/music/profile.c',ROOT/'services/music/settings.c']
        sources += [ROOT/'services/music/queue_view.c']
        sources += [ROOT/'services/music/decoder.c']
        sources += [ROOT/'services/audio/dsp.c',ROOT/'services/audio/dsp_arm.S']
        sources += [ROOT/'services/audio/mp3/mp3.c']
        sources += [ROOT/'services/music/history.c',ROOT/'services/music/journal.c']
        sources += [ROOT/'services/music/history_pages.c',ROOT/'services/music/journal_pages.c']
        sources += [ROOT/'services/audio/flac/flac.c',ROOT/'third_party/flac/decoder.c']
        sources += [ROOT/'services/audio/alac/alac.c',ROOT/'third_party/alac/alac.c']
        sources += [ROOT/'services/audio/aac/aac.c',ROOT/'services/audio/aac/m4a.c']
        sources += [ROOT/'third_party/aac'/name for name in (ROOT/'third_party/aac/SOURCES').read_text().splitlines() if name]
        sources += [ROOT/'services/audio/vorbis'/name for name in ('vorbis.c','pool.c','division.c')]
        sources += [ROOT/'third_party/vorbis'/name for name in ('bitwise.c','block.c','codebook.c','floor0.c','floor1.c','info.c','mapping0.c','registry.c','res012.c','sharedbook.c','synthesis.c','window.c')]
        sources += [ROOT/'third_party/libmad'/name for name in ('bit.c','frame.c','huffman.c','layer12.c','layer3.c','stream.c','synth.c','imdct_l_arm.S','synth_full_arm.S')]
        flags += ['-fwrapv']
        if profile!='release':sources += [ROOT/'kernel/audio_link.c']
    if batch>=6 and kind=='os':
        flags += ['-DLINNET_VIDEO=1']
        sources += sorted((ROOT/'services/video').glob('*.c'))
        sources += sorted((ROOT/'services/video').glob('*.S'))
    if batch>=7 and kind=='os':
        flags += ['-DLINNET_BATTERY_GUARD=1']
        if profile!='release':flags += ['-DLINNET_AUDIO_CACHE_DIAGNOSTIC=1']
        sources += [ROOT/'services/power/battery.c']
    if batch>=5 and kind=='os':
        flags += ['-DLINNET_PHOTOS=1', '-DLINNET_NOTES=1']
        sources += sorted((ROOT/'services/notes').glob('*.c'))
        sources += sorted((ROOT/'services/photos').glob('*.c'))
        sources += sorted((ROOT/'third_party/jpeg').glob('*.c'))
    objects = []
    for source in sources:
        obj = dest / (source.relative_to(ROOT).as_posix().replace("/", "_") + ".o")
        relative=source.relative_to(ROOT).as_posix()
        codec_flags=[]
        if relative.startswith(('third_party/aac/','services/audio/aac/')):
            codec_flags=['-Ithird_party/aac','-Ithird_party/aac/faad','-Ithird_party/aac/lib','-O2','-DCPU_ARM=1','-DARM_ARCH=4']
        elif relative in ('services/audio/dsp.c','services/video/video.c'):
            codec_flags=['-O2']
        elif relative.startswith(('third_party/vorbis/','services/audio/vorbis/')):
            codec_flags=['-Ithird_party/vorbis','-Ithird_party/aac/lib']
        elif relative.startswith(('third_party/libmad/','services/audio/mp3/')):
            # MP3 decoding dominates 44.1 kHz playback CPU time on ARM7.  Clang's
            # size-oriented default and -O2 both leave useful loop transforms on
            # the table in libmad's requantization and synthesis hot paths.
            codec_flags=['-Ithird_party/libmad','-O3','-DCPU_ARM_CLASSIC=1']
        run([chain['compiler']['path'], *flags, *codec_flags, "-c", source, "-o", obj])
        objects.append(obj)
    elf = dest / (prefix + ".elf")
    mapfile = dest / (prefix + ".map")
    script = generated / "memory.ld"
    memory_flags = ["-DLINNET_PLATFORM_CORE=1"] if batch >= 1 else []
    if batch >= 2:
        memory_flags += ["-DLINNET_STORAGE=1"]
    if batch>=4 and kind=='os':memory_flags += ['-DLINNET_AUDIO=1']
    run([chain['compiler']['path'], "-E", "-P", "-x", "c", f"-DLINNET_PROFILE_{profile.upper()}=1", f"-DLINNET_IMAGE_{kind.upper()}=1", *memory_flags, ROOT / "targets" / target / "memory.ld", "-o", script])
    run([chain['linker']['path'], "-T", script, "--gc-sections", "-Map=" + str(mapfile), "-o", elf, *objects])
    raw = dest / (prefix + ".bin")
    run([chain['objcopy']['path'], "-O", "binary", elf, raw])
    symbols = run([chain['nm']['path'], "-S", "--size-sort", elf])
    sections = []
    raw_elf = elf.read_bytes()
    section_offset = struct.unpack_from("<I", raw_elf, 32)[0]
    section_size, section_count, string_index = struct.unpack_from("<HHH", raw_elf, 46)
    section_headers = [struct.unpack_from("<10I", raw_elf, section_offset + i * section_size) for i in range(section_count)]
    strings_header = section_headers[string_index]
    strings = raw_elf[strings_header[4]:strings_header[4] + strings_header[5]]
    for section in section_headers:
        if section[2] & 2:
            name = strings[section[0]:].split(b'\0', 1)[0].decode()
            sections.append(dict(name=name, address=section[3], bytes=section[5], stored=section[1] != 8))
    (dest / (prefix + ".symbols")).write_text(symbols + "\n")
    payload = raw.read_bytes()
    envelope = pack(payload, profile, build_id, 0, 0)
    los = dest / (prefix + ".los")
    los.write_bytes(envelope)
    ipod = dest / (prefix + ".ipod")
    ipod.write_bytes(struct.pack(">I4s", (3 + sum(payload)) & 0xffffffff, b"ipco") + payload)
    verification = verify_release(envelope, symbols + mapfile.read_text()) if profile == "release" else None
    report = dict(**configuration, build_id=build_id, toolchain=chain, image=inspect(envelope),
                  source_files=[p.relative_to(ROOT).as_posix() for p in sources],
                  artifacts={key: str(path.relative_to(ROOT)) for key, path in dict(elf=elf, los=los, ipod=ipod, map=mapfile).items()},
                  memory=dict(regions=sections, total_allocated_bytes=sum(s['bytes'] for s in sections), resident_limit_bytes=4718592 if batch>=4 and kind=='os' else 1048576, retained_limit_bytes=4096),
                  release_exclusion=verification, hardware_qualified=False,
                  limitation=f"Integrated Batch {batch} candidate; physical USB, recovery and peripheral behavior require device qualification. FIQ watchdog depends on FIQ delivery; COP reset escalation requires a live COP monitor.")
    if ui_report is not None:report["ui"]=ui_report
    (dest / (prefix + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    return report
