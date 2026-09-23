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
from tools.studio.targets import LCD_FORMATS, ROOT, TARGETS, RUNTIME_POLICIES, target_id

def run(args):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result.stdout.strip()

def wsl_command(arguments, *, paths=None):
    distribution = tomllib.loads((ROOT / "config/toolchain.toml").read_text(encoding="utf-8"))["toolchain"]["windows_wsl_distribution"]
    def convert(path):
        return subprocess.run(
            ["wsl", "-d", distribution, "--", "wslpath", "-a", path.as_posix()],
            capture_output=True, text=True, encoding="utf-8", check=True,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    converted = convert(ROOT)
    forwarded = list(arguments)
    for option, path in (paths or {}).items():
        if path is None:
            continue
        value = convert(path.resolve()) if path.drive else path.as_posix()
        # Last occurrence wins for both --option=value and abbreviated flags.
        forwarded.extend(("--" + option, value))
    return ["wsl", "-d", distribution, "--cd", converted, "--", "python3", "linnet", *forwarded]

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
        with Path(executable).open('rb') as reader:
            checksum = hashlib.file_digest(reader, 'sha256').hexdigest()
        result[name] = dict(path=executable, version=version, sha256=checksum)
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
        digest.update(struct.pack("<I", len(name)))
        digest.update(name)
        digest.update(struct.pack("<Q", len(data)))
        digest.update(data)
    digest.update(json.dumps(configuration, sort_keys=True).encode())
    digest.update(json.dumps({k: {field: v[field] for field in ('version', 'sha256')} for k, v in chain.items()}, sort_keys=True).encode())
    return digest.hexdigest()

def build(profile, target, verify=False, kind="os", probe="frame", device_serial="", system_config=None,
          boot_selector="none"):
    target = target_id(target)
    spec = TARGETS[target]
    if not spec.get("build_enabled", True):
        raise ValueError(f"{target}: {spec['bringup_blocker']}")
    if system_config is None and (ROOT / "targets" / target / "system.toml").is_file():
        system_config = f"targets/{target}/system.toml"
    chain = toolchain()
    if profile == "release" and probe != "frame":
        raise ValueError("deliberate crash probes require dev or trace")
    if device_serial and not re.fullmatch(r"[A-Za-z0-9-]{1,32}", device_serial):
        raise ValueError("device serial must be 1..32 letters, digits or hyphens")
    if profile != "release" and not device_serial:
        raise ValueError("development USB requires --device-serial from physical device enumeration")
    if boot_selector not in ("none", "rockbox"):
        raise ValueError("boot selector must be none or rockbox")
    if kind != "boot" and boot_selector != "none":
        raise ValueError("a startup selector is valid only for Boot images")
    configuration = dict(profile=profile, target_id=target, kind=kind,
                          probe=probe, device_serial=device_serial)
    if kind == "boot":
        configuration["boot_selector"] = boot_selector
        configuration["apple_firmware_fallback"] = True
    if kind == "os":
        configuration["system_config"] = str(system_config or "config/system.toml")
    dest = ROOT / "out" / profile / target / kind
    dest.mkdir(parents=True, exist_ok=True)
    generated = dest / "generated"
    generated.mkdir(exist_ok=True)
    presentation = {}
    if spec.get("presentation_profile"):
        presentation = tomllib.loads((ROOT / "ui/profiles" / spec["presentation_profile"] / "profile.toml").read_text())
    target_header = [
        "#ifndef LINNET_TARGET_H",
        "#define LINNET_TARGET_H",
        f'#include "targets/{target}/hardware.h"',
        f'#define LINNET_TARGET_ID "{target}"',
        f'#define LINNET_TARGET_NAME "{spec["name"]}"',
        f'#define LINNET_BOARD_ID "{spec["board_id"]}"',
        f'#define LINNET_MODEL_ALIAS "{spec["model_alias"]}"',
        f'#define LINNET_SOC_ID "{spec["soc"]}"',
        f'#define LINNET_CPU_ID "{spec["cpu"]}"',
        f'#define LINNET_ARCHITECTURE_ID "{spec["architecture"]}"',
        f'#define LINNET_TARGET_NUMBER {spec["image_target"]}u',
        f'#define LINNET_LCD_WIDTH {spec["lcd_width"]}u',
        f'#define LINNET_LCD_HEIGHT {spec["lcd_height"]}u',
        f'#define LINNET_SOC_{spec["soc"].upper().replace("-","_")} 1',
        f'#define LINNET_LCD_FORMAT {LCD_FORMATS[spec["lcd_format"]]}u',
        f'#define LINNET_LCD_WIDTH_ASM {spec["lcd_width"]}',
        f'#define LINNET_LCD_HEIGHT_ASM {spec["lcd_height"]}',
        f'#define LINNET_UI_WIDTH {spec["lcd_width"]}u',
        f'#define LINNET_ACTIVE_CLOCK_HZ {spec.get("active_clock_hz",80000000)}u',
        f'#define LINNET_IDLE_CLOCK_HZ {spec.get("idle_clock_hz",0)}u',
        f'#define LINNET_MUSIC_TITLES_ADDRESS {spec["resources"]["music_titles_address"]}',
        f'#define LINNET_MUSIC_TITLES_BYTES {spec["resources"]["music_titles_bytes"]}',
        f'#define LINNET_COVERFLOW_CATALOG_SLOTS {spec["resources"]["coverflow_catalog_slots"]}u',
        f'#define LINNET_COVERFLOW_EXPANDED {int(spec["coverflow_cache"] == "expanded")}u',
        f'#define LINNET_UI_HEIGHT {spec["lcd_height"]}u',
        f'#define LINNET_PHOTO_WIDTH {spec["media_photo_width"]}u',
        f'#define LINNET_PHOTO_HEIGHT {spec["media_photo_height"]}u',
        f'#define LINNET_VIDEO_WIDTH {spec["media_video_width"]}u',
        f'#define LINNET_VIDEO_HEIGHT {spec["media_video_height"]}u',
        f'#define LINNET_VIDEO_FPS {spec["media_video_fps"]}u',
        f'#define LINNET_ART_MAX_SIDE {spec["media_art_side"]}u',
        f'#define LINNET_VIDEO_CATALOG_PAGED {int(spec.get("video_catalog_cache") == "paged")}u',
        f'#define LINNET_VIDEO_PACKET_BYTES {spec.get("native_video", {}).get("sample_bytes", 65536)}u',
        f'#define LINNET_VIDEO_COLOR_GRAY4 {int(spec["media_video_color"] == "gray4")}u',
        f'#define LINNET_STORAGE_MAX_READ_SECTORS {spec["storage_max_read_sectors"]}u',
        f'#define LINNET_COP_DISPLAY {int(spec["cop_display"])}u',
        f'#define LINNET_COVERFLOW_SCANLINE {int(presentation.get("coverflow_renderer") == "scanline")}',
        f'#define LINNET_COP_DISPLAY_SOURCE "targets/{target}/cop-display.inc"',
        f'#define LINNET_SDRAM_BYTES {spec["sdram_bytes"]}',
        f'#define LINNET_LOAD_ADDRESS {spec["load_address"]}',
        f'#define LINNET_ENTRY_ADDRESS {spec["entry_address"]}',
        f'#define LINNET_OS_CAPACITY {spec["os_capacity_bytes"]}',
        f'#define LINNET_STAGE_ADDRESS {spec["stage_address"]}',
        f'#define LINNET_STAGE_CAPACITY {spec["stage_bytes"]}',
        f'#define LINNET_LOADER_SNAPSHOT {spec["recovery_snapshot_address"]}',
        f'#define LINNET_LOADER_CAPACITY {spec["recovery_snapshot_bytes"]}',
        f'#define LINNET_MAILBOX_ADDRESS {spec["mailbox_address"]}',
        f'#define LINNET_MAILBOX_BYTES {spec["mailbox_bytes"]}',
        f'#define LINNET_FILE_WRAPPER_MODEL "{spec["installer"]["wrapper_model"]}"',
        f'#define LINNET_FILE_WRAPPER_CHECKSUM_SEED {spec["installer"]["wrapper_checksum_seed"]}u',
        '#define LINNET_BOOT_APPLE_FALLBACK 1',
        f'#define LINNET_BOOT_SELECTOR_ROCKBOX {int(boot_selector == "rockbox")}',
        f'#define {spec["target_define"]} 1',
        "#endif",
    ]
    target_header[-1:-1] = [f'#define LINNET_{name.upper()} {int(spec.get("runtime_policy", {}).get(name, False))}'
                            for name in sorted(RUNTIME_POLICIES)]
    (generated / "linnet_target.h").write_text("\n".join(target_header) + "\n")
    ui_report = None
    if kind == "os":
        from tools.content.compiler import compile_system
        ui_report = compile_system(ROOT, generated, Path(system_config) if system_config else None,
                                   target_override=target)
        # The compiler identity covers the exact selected input bytes, including
        # configuration/assets under excluded output or cache directories.
        configuration["content_id"] = ui_report["content_id"]
    build_id = source_identity(configuration, chain)
    (generated / "linnet_build.h").write_text('#define LINNET_BUILD_ID "' + build_id + '"\n#define LINNET_BUILD_ID_BYTES {' + ','.join('0x' + build_id[i:i+2] for i in range(0, 64, 2)) + '}\n')
    with (generated / "linnet_build.h").open('a') as header:
        header.write('#define LINNET_USB_SERIAL "' + device_serial + '"\n')
    prefix = f"linnet-{kind}-0.1.0-{target}-{profile}-{build_id[:12]}"
    target_sources = spec["sources"]
    hal = ROOT / "hal" / spec.get("hal_family", spec["soc"])
    sources = [ROOT / target_sources["startup"], hal / "entry.S",
               ROOT / target_sources["platform"], ROOT / target_sources["lcd"],
               ROOT / "kernel/main.c", ROOT / "kernel/memory.S"]
    sources += [ROOT / "boot/src/linnet_boot.c"]
    sources += [hal / name for name in ("core.c", "input.c")]
    sources += [ROOT / target_sources["power"]]
    for directory in (hal, ROOT / "targets" / target):
        source_list=directory / "SOURCES"
        if source_list.is_file():
            for name in source_list.read_text().splitlines():
                source=(ROOT / name).resolve()
                if not name or not source.is_relative_to(ROOT) or not source.is_file():
                    raise ValueError(f"Invalid platform source in {source_list}: {name}")
                sources.append(source)
    sources += [ROOT / target_sources["display"], ROOT / target_sources["device"], ROOT / target_sources["codec"]]
    if "display_assembly" in target_sources:
        sources += [ROOT / target_sources["display_assembly"]]
    if kind == "os" and "coprocessor" in target_sources:
        sources += [ROOT / target_sources["coprocessor"]]
    if kind == "os" and spec.get("cop_display", False):
        sources += [ROOT / "targets" / target / name for name in ("video_blit.c", "video_blit.S")]
    if kind == "os":
        sources += [ROOT / name for name in
                    ("kernel/executive.c", "kernel/runtime.c", "kernel/wheel_motion.c")]
        sources += [ROOT / "ui/runtime/shell_adapter.c", ROOT / "services/display/clock.c"]
    if profile != "release":
        sources += sorted((ROOT / "hal/link").glob("*.c"))
        sources += [ROOT / name for name in ("boot/src/loader.c", "boot/src/sha256.c")]
        sources += [hal / name for name in ("usb.c", "recovery.c")]
        if (hal / "recovery.S").is_file():sources.append(hal / "recovery.S")
        sources += [ROOT / "kernel/development.c"]
        if kind == "os":
            sources += [ROOT / "kernel/platform_link.c"]
    sources += [ROOT / name for name in (
        "services/storage/block.c", "services/storage/fat32.c",
        "services/storage/storage.c", "services/state/store.c",
        "services/update/update.c")]
    sources += [hal / "persistent_enter.S"]
    sources += [hal / "ata.c"]
    if profile == "release":
        sources += [ROOT / "boot/src/sha256.c"]
    else:
        sources += [ROOT / "kernel/storage_link.c"]
        if kind == "os":
            sources += [ROOT / target_sources["native_update"]]
    if kind == "os":
        sources += [ROOT/"ui/runtime/ui.c",generated/"linnet_ui.c",ROOT/"services/display/settings.c"]
    compiler_target = "arm-none-eabi" if spec["endianness"] == "little" else "armeb-none-eabi"
    # N25 Boot shares a fixed NOR slot with the SRAM recovery monitor.
    optimization = "-Oz" if target == "classic6g-n25" and kind == "boot" else "-Os"
    flags = [f"--target={compiler_target}", f'-mcpu={spec["cpu"]}', f'-march={spec["architecture"]}', "-marm", "-mfloat-abi=soft", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-ffunction-sections", "-fdata-sections", optimization, "-Wall", "-Wextra", "-Werror", "-I.", "-Iboot/include", f"-DLINNET_PROFILE_{profile.upper()}=1", f"-DLINNET_IMAGE_{kind.upper()}=1", f'-D{spec["target_define"]}=1']
    flags += ["-I" + str(generated), f"-DLINNET_PROBE_CRASH={int(probe == 'crash')}", f"-DLINNET_PROBE_HANG={int(probe == 'hang')}"]
    flags += ["-DLINNET_PLATFORM_CORE=1", "-DLINNET_STORAGE=1"]
    if kind == "os":
        flags += ["-DLINNET_NATIVE_UI=1"]
        flags += ["-DLINNET_AUDIO=1"]
        sources += [hal/'audio.c',ROOT/'services/audio/codec_pcm.c']
        sources += [ROOT/'services/music/player.c',ROOT/'services/music/database.c']
        sources += [ROOT/'services/music/library.c',ROOT/'services/music/controller.c',ROOT/'services/music/queue.c',ROOT/'services/music/ui.c']
        sources += [ROOT/'services/music/artwork.c']
        sources += [ROOT/'services/music/browser.c']
        sources += [ROOT/'services/music/search.c',ROOT/'services/music/profile.c',ROOT/'services/music/settings.c']
        sources += [ROOT/'services/music/queue_view.c',ROOT/'services/music/collections.c']
        sources += [ROOT/'services/music/decoder.c']
        sources += [ROOT/'services/audio/dsp.c',ROOT/'services/audio/dsp_arm.S']
        sources += [ROOT/'services/audio/mp3/mp3.c']
        sources += [ROOT/'services/music/history.c']
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
    if kind == 'os' and ui_report['features'].get('cover_flow', False):
        flags += ['-DLINNET_COVERFLOW=1']
    if kind == 'os' and ui_report['features'].get('video', True):
        flags += ['-DLINNET_VIDEO=1']
        video_backend = spec['media_video_backend']
        sources += [ROOT/'services/video/catalog.c', ROOT/target_sources['video']]
        if video_backend == 'ipvf':
            sources += sorted((ROOT/'services/video/ipvf').glob('*.S'))
        if video_backend in ('native-mp4', 'bcm-mp4'):
            sources += [ROOT/'services/video/mp4.c']
        if video_backend == 'native-mp4':
            flags += [f"-DLINNET_H264_MAX_WIDTH={spec['native_video']['h264_width']}",
                      f"-DLINNET_H264_MAX_HEIGHT={spec['native_video']['h264_height']}"]
            sources += [ROOT/'services/video/native/decoder.c',ROOT/'services/video/native/yuv.c']
            sources += sorted((ROOT/'third_party/h264bsd').glob('*.c'))
            if spec['cpu'] == 'arm926ej-s':
                flags += ['-DLINNET_ARM926_YUV=1']
                sources += [ROOT/'hal/arm926/yuv.S']
            if spec.get('mpeg4_decoder') in ('pvmp4','s5l8702-vpu'):
                flags += ['-DLINNET_MPEG4=1']
                sources += [ROOT/'services/video/native/mpeg4_memory.c']
                sources += [ROOT/('hal/s5l8702/mpeg4.cpp' if spec.get('mpeg4_decoder') == 's5l8702-vpu' else 'services/video/native/mpeg4.cpp')]
                if spec.get('mpeg4_decoder') == 's5l8702-vpu':
                    flags += ['-DLINNET_MPEG4_VPU=1']
                    sources += [ROOT/'hal/s5l8702/mpeg4_vpu.c']
                sources += [ROOT/'third_party/pvmp4'/name for name in (ROOT/'third_party/pvmp4/SOURCES').read_text().splitlines() if name]
            decoder = spec.get('h264_decoder', 'software')
            if decoder == 's5l8702-vpu' and spec['soc'] == 's5l8702':
                flags += ['-DLINNET_H264_VPU=1']
                sources += [ROOT/'hal/s5l8702/h264.c', ROOT/'hal/s5l8702/vpu.c']
            elif decoder == 'software':
                sources += [ROOT/'services/video/native/h264.c']
            else:
                raise ValueError(f'Unsupported H.264 decoder: {decoder}')
    if kind == 'os':
        flags += ['-DLINNET_BATTERY_GUARD=1']
        if profile!='release':flags += ['-DLINNET_AUDIO_CACHE_DIAGNOSTIC=1']
        sources += [ROOT/'services/power/battery.c']
    if kind == 'os':
        flags += ['-DLINNET_NOTES=1']
        sources += sorted((ROOT/'services/notes').glob('*.c'))
    if kind == 'os' and ui_report['features'].get('photos', True):
        flags += ['-DLINNET_PHOTOS=1']
        sources += sorted((ROOT/'services/photos').glob('*.c'))
        sources += sorted((ROOT/'third_party/jpeg').glob('*.c'))
    objects = []
    for source in sources:
        obj = dest / (source.relative_to(ROOT).as_posix().replace("/", "_") + ".o")
        relative=source.relative_to(ROOT).as_posix()
        codec_flags=[]
        if optimization == '-Oz' and relative == 'services/storage/block.c':
            # Keep constant pointer-distance division inline; -Oz emits an
            # unavailable __aeabi_idiv helper in this freestanding build.
            codec_flags=['-Os']
        if relative.startswith('third_party/h264bsd/'):
            codec_flags=['-O3','-fomit-frame-pointer','-Wno-unused-parameter','-Wno-unused-but-set-variable','-include','services/video/native/compat.h']
        elif relative.startswith('third_party/pvmp4/') or relative in ('services/video/native/mpeg4.cpp','hal/s5l8702/mpeg4.cpp'):
            codec_flags=['-O3','-fomit-frame-pointer','-fno-exceptions','-fno-rtti','-DDEC_NOPOSTPROC','-Ithird_party/pvmp4/compat','-Ithird_party/pvmp4','-Wno-unused-parameter','-Wno-unused-but-set-variable','-Wno-sign-compare']
        elif relative.startswith('services/video/native/') or relative == 'hal/s5l8702/h264.c':
            codec_flags=['-O3','-fomit-frame-pointer']
        elif relative.startswith(('third_party/aac/','services/audio/aac/')):
            codec_flags=['-Ithird_party/aac','-Ithird_party/aac/faad','-Ithird_party/aac/lib','-O3','-fomit-frame-pointer','-DCPU_ARM=1','-DARM_ARCH=4']
        elif source == generated/'linnet_ui.c' and ui_report['features'].get('cover_flow', False):
            codec_flags=['-O2']
        elif relative in ('services/audio/dsp.c','services/video/ipvf/player.c'):
            codec_flags=['-O2']
        elif relative.startswith(('third_party/vorbis/','services/audio/vorbis/')):
            codec_flags=['-Ithird_party/vorbis','-Ithird_party/aac/lib']
        elif relative.startswith(('third_party/libmad/','services/audio/mp3/')):
            # MP3 decoding dominates 44.1 kHz playback CPU time on ARM7.  Clang's
            # size-oriented default and -O2 both leave useful loop transforms on
            # the table in libmad's requantization and synthesis hot paths.
            codec_flags=['-Ithird_party/libmad','-O3','-fomit-frame-pointer','-DCPU_ARM_CLASSIC=1']
        run([chain['compiler']['path'], *flags, *codec_flags, "-c", source, "-o", obj])
        objects.append(obj)
    elf = dest / (prefix + ".elf")
    mapfile = dest / (prefix + ".map")
    script = generated / "memory.ld"
    memory_flags = ["-DLINNET_PLATFORM_CORE=1", "-DLINNET_STORAGE=1"]
    if kind == 'os':
        memory_flags += ['-DLINNET_AUDIO=1']
        if ui_report['features'].get('cover_flow',False):memory_flags += ['-DLINNET_COVERFLOW=1']
    run([chain['compiler']['path'], "-E", "-P", "-x", "c", "-I" + str(ROOT), "-I" + str(generated), f"-DLINNET_PROFILE_{profile.upper()}=1", f"-DLINNET_IMAGE_{kind.upper()}=1", *memory_flags, ROOT / target_sources["linker"], "-o", script])
    run([chain['linker']['path'], "-T", script, "--gc-sections", "-Map=" + str(mapfile), "-o", elf, *objects])
    raw = dest / (prefix + ".bin")
    run([chain['objcopy']['path'], "-O", "binary", elf, raw])
    symbols = run([chain['nm']['path'], "-S", "--size-sort", elf])
    sections = []
    raw_elf = elf.read_bytes()
    byte_order = "<" if spec["endianness"] == "little" else ">"
    section_offset = struct.unpack_from(byte_order + "I", raw_elf, 32)[0]
    section_size, section_count, string_index = struct.unpack_from(byte_order + "HHH", raw_elf, 46)
    section_headers = [struct.unpack_from(byte_order + "10I", raw_elf, section_offset + i * section_size) for i in range(section_count)]
    strings_header = section_headers[string_index]
    strings = raw_elf[strings_header[4]:strings_header[4] + strings_header[5]]
    for section in section_headers:
        if section[2] & 2:
            name = strings[section[0]:].split(b'\0', 1)[0].decode()
            sections.append(dict(name=name, address=section[3], bytes=section[5], stored=section[1] != 8))
    (dest / (prefix + ".symbols")).write_text(symbols + "\n")
    payload = raw.read_bytes()
    envelope = pack(payload, profile, build_id, spec["load_address"],
                    spec["entry_address"], target)
    los = dest / (prefix + ".los")
    los.write_bytes(envelope)
    ipod = dest / (prefix + ".ipod")
    install = spec["installer"]
    model_code = install["wrapper_model"].encode("ascii")
    ipod.write_bytes(struct.pack(">I4s", (install["wrapper_checksum_seed"] + sum(payload)) & 0xffffffff, model_code) + payload)
    verification = verify_release(envelope, symbols + mapfile.read_text()) if profile == "release" else None
    watchdog_limitation = None if spec.get("hal_family") == "s5l8702" else (
        "FIQ watchdog depends on FIQ delivery; COP reset escalation requires a live COP monitor."
        if "coprocessor" in target_sources else "Watchdog recovery requires FIQ delivery.")
    report = dict(**configuration, build_id=build_id, toolchain=chain, image=inspect(envelope),
                  source_files=[p.relative_to(ROOT).as_posix() for p in sources],
                  artifacts={key: str(path.relative_to(ROOT)) for key, path in dict(elf=elf, los=los, ipod=ipod, map=mapfile).items()},
                  memory=dict(regions=sections, total_allocated_bytes=sum(s['bytes'] for s in sections), resident_limit_bytes=(8126464 if ui_report['features'].get('cover_flow',False) else 5505024) if kind=='os' else 1048576, retained_limit_bytes=spec['mailbox_bytes']),
                  release_exclusion=verification, limitation=watchdog_limitation)
    if ui_report is not None:report["ui"]=ui_report
    (dest / (prefix + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    return report
