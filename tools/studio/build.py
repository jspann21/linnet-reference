"""Reproducible freestanding ARM build, invoked by the sole Linnet CLI."""
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tomllib
import uuid
from tools.inspect.image import pack, inspect, verify_release
from tools.studio.targets import LCD_FORMATS, ROOT, RUNTIME_POLICIES, presentation_defines, resolved_target_spec, target_id

def run(args):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result.stdout.strip()

def wsl_command(arguments, *, paths=None):
    distribution = tomllib.loads((ROOT / "config/toolchain.toml").read_text(encoding="utf-8"))["toolchain"]["windows_wsl_distribution"]
    windows_paths = [ROOT.as_posix()]
    for path in (paths or {}).values():
        if path is not None and path.drive:
            value = path.resolve().as_posix()
            if value not in windows_paths:
                windows_paths.append(value)
    convert_script = (
        "import json, subprocess, sys\n"
        "paths = json.loads(sys.argv[1])\n"
        "print(json.dumps([subprocess.run(['wslpath', '-a', path], "
        "capture_output=True, text=True, check=True).stdout.strip() for path in paths]))\n"
    )
    converted = json.loads(subprocess.run(
        ["wsl", "-d", distribution, "--", "python3", "-c", convert_script, json.dumps(windows_paths)],
        capture_output=True, text=True, encoding="utf-8", check=True,
        creationflags=subprocess.CREATE_NO_WINDOW).stdout)
    translations = dict(zip(windows_paths, converted))
    forwarded = list(arguments)
    for option, path in (paths or {}).items():
        if path is None:
            continue
        value = translations[path.resolve().as_posix()] if path.drive else path.as_posix()
        # Last occurrence wins for both --option=value and abbreviated flags.
        forwarded.extend(("--" + option, value))
    return ["wsl", "-d", distribution, "--cd", translations[ROOT.as_posix()], "--", "python3", "linnet", *forwarded]

def _tool_stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=16)
def _tool_version(executable, resolved, stamp):
    return run([executable, "--version"])


@lru_cache(maxsize=16)
def _tool_digest(resolved, stamp):
    with Path(resolved).open('rb') as reader:
        before = _tool_stamp(os.fstat(reader.fileno()))
        if before != stamp:
            raise RuntimeError(f"toolchain changed while fingerprinting: {resolved}")
        checksum = hashlib.file_digest(reader, 'sha256').hexdigest()
        if _tool_stamp(os.fstat(reader.fileno())) != before:
            raise RuntimeError(f"toolchain changed while fingerprinting: {resolved}")
    return checksum


def toolchain():
    spec = tomllib.loads((ROOT / "config/toolchain.toml").read_text())["toolchain"]
    result = {}
    for name in ("compiler", "linker", "objcopy", "nm"):
        executable = shutil.which(spec[name])
        if executable is None:
            raise RuntimeError(f"missing {spec[name]}; install LLVM {spec['version']} (Windows: WSL {spec['windows_wsl_distribution']})")
        resolved = Path(executable).resolve(strict=True)
        stamp = _tool_stamp(resolved.stat())
        version = _tool_version(executable, str(resolved), stamp)
        if not re.search(r"\b" + re.escape(spec["version"]) + r"\b", version):
            raise RuntimeError(f"toolchain pin mismatch: {version}; expected {spec['version']}")
        checksum = _tool_digest(str(resolved), stamp)
        if Path(executable).resolve(strict=True) != resolved or _tool_stamp(resolved.stat()) != stamp:
            raise RuntimeError(f"toolchain changed while fingerprinting: {executable}")
        result[name] = dict(path=executable, version=version, sha256=checksum)
    return result

def source_paths(*, with_sizes=False):
    """Prune generated trees before descent; sort only source inputs."""
    excluded = {".git", "out", "__pycache__", ".venv",
                ".ruff_cache", ".pytest_cache", ".mypy_cache"}
    paths = []
    def fail(error):
        raise error
    for directory, directories, files in os.walk(ROOT, onerror=fail, followlinks=False):
        directories[:] = [name for name in directories if name not in excluded]
        for name in files:
            if name in excluded or Path(name).suffix == '.pyc':
                continue
            path = Path(directory) / name
            try:
                info = path.stat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                paths.append((path, info.st_size))
    paths.sort(key=lambda item: item[0])
    return paths if with_sizes else [path for path, _ in paths]

def source_identity(configuration, chain, source_inventory=None):
    digest = hashlib.sha256()
    for path, size in source_paths(with_sizes=True):
        if source_inventory is not None:
            source_inventory.append(path)
        name = path.relative_to(ROOT).as_posix().encode()
        digest.update(struct.pack("<I", len(name)))
        digest.update(name)
        with path.open("rb") as reader:
            before = os.fstat(reader.fileno())
            if before.st_size != size:
                raise RuntimeError(f"Source changed during build identity calculation: {path}")
            digest.update(struct.pack("<Q", before.st_size))
            if size <= 1024 * 1024:
                data = reader.read(before.st_size + 1)
                digest.update(data)
                counted = len(data)
            else:
                counted = 0
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
                    counted += len(chunk)
            after = os.fstat(reader.fileno())
            if counted != before.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                raise RuntimeError(f"Source changed during build identity calculation: {path}")
    digest.update(json.dumps(configuration, sort_keys=True).encode())
    digest.update(json.dumps({k: {field: v[field] for field in ('version', 'sha256')} for k, v in chain.items()}, sort_keys=True).encode())
    return digest.hexdigest()

def memory_budget(sections, spec, resident_limit):
    """Report linked placement and separate manifest reservations, not a sum of lifetimes."""
    base = spec['load_address']
    capacity = spec['os_capacity_bytes']
    resident = [item for item in sections if base <= item['address'] < base + capacity]
    extent = max((item['address'] + item['bytes'] - base for item in resident), default=0)
    artwork = [item for item in sections if item['name'] in
               ('.cover_low', '.cover_high', '.cover_catalog')]
    stage = [item for item in sections if item['name'] in ('.update_staging', '.dev_staging')]
    snapshot = [item for item in sections if item['name'] == '.dev_snapshot']
    retained = [item for item in sections if spec['mailbox_address'] <= item['address'] <
                spec['mailbox_address'] + spec['mailbox_bytes']]
    return dict(
        basis='linked sections and manifest reservations; runtime high-water is not measured',
        resident=dict(address=base, capacity_bytes=capacity, limit_bytes=resident_limit,
                      linked_extent_bytes=extent, headroom_bytes=resident_limit - extent,
                      linked_section_bytes=sum(item['bytes'] for item in resident),
                      stack_bytes=sum(item['bytes'] for item in resident if item['name'] == '.stacks')),
        artwork=dict(linked_section_bytes=sum(item['bytes'] for item in artwork),
                     sections={item['name']: item['bytes'] for item in artwork}),
        staging=dict(address=spec['stage_address'], capacity_bytes=spec['stage_bytes'],
                     linked_section_bytes=sum(item['bytes'] for item in stage)),
        recovery=dict(address=spec['recovery_snapshot_address'],
                      capacity_bytes=spec['recovery_snapshot_bytes'],
                      linked_section_bytes=sum(item['bytes'] for item in snapshot)),
        retained=dict(address=spec['mailbox_address'], capacity_bytes=spec['mailbox_bytes'],
                      linked_section_bytes=sum(item['bytes'] for item in retained)))

def build(profile, target, verify=False, kind="os", probe="frame", device_serial="", system_config=None,
          boot_selector="none", jobs=2):
    target = target_id(target)
    spec = resolved_target_spec(target)
    if not spec["build_enabled"]:
        raise ValueError(f"{target}: {spec['bringup_blocker']}")
    if system_config is None and (ROOT / "targets" / target / "system.toml").is_file():
        system_config = f"targets/{target}/system.toml"
    if profile not in ("release", "dev", "trace"):
        raise ValueError("profile must be release, dev or trace")
    if kind not in ("os", "boot"):
        raise ValueError("image kind must be os or boot")
    if probe not in ("frame", "crash", "hang"):
        raise ValueError("probe must be frame, crash or hang")
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
    if type(jobs) is not int or not 1 <= jobs <= 4:
        raise ValueError("build jobs must be an integer from 1 to 4")
    chain = toolchain()
    configuration = dict(profile=profile, target_id=target, kind=kind,
                          probe=probe, device_serial=device_serial)
    if kind == "boot":
        configuration["boot_selector"] = boot_selector
        configuration["apple_firmware_fallback"] = True
    if kind == "os":
        configuration["system_config"] = str(system_config or "config/system.toml")
    # Keep generated inputs, objects, and final artifacts together for this
    # invocation. Build identities alone are insufficient: two builds with the
    # same identity can still overlap while one is writing its objects.
    dest = ROOT / "out" / profile / target / kind / "runs" / uuid.uuid4().hex
    dest.mkdir(parents=True, exist_ok=False)
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
        f'#define LINNET_NATIVE_STORAGE_USB_PID {spec.get("native_storage", {}).get("usb_pid", 0)}u',
        f'#define LINNET_NATIVE_STORAGE_INQUIRY "LINNET  {spec.get("native_storage", {}).get("friendly_name", "LINNET IPOD").removeprefix("LINNET ")[:16].ljust(16)}0001"',
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
        f'#define LINNET_ACTIVE_CLOCK_HZ {spec["active_clock_hz"]}u',
        f'#define LINNET_IDLE_CLOCK_HZ {spec["idle_clock_hz"]}u',
        f'#define LINNET_MUSIC_TITLES_ADDRESS {spec["resources"]["music_titles_address"]}',
        f'#define LINNET_MUSIC_TITLES_BYTES {spec["resources"]["music_titles_bytes"]}',
        f'#define LINNET_COVERFLOW_CATALOG_SLOTS {spec["resources"]["coverflow_catalog_slots"]}u',
        f'#define LINNET_RESIDENT_LIMIT_BYTES {spec["resident_limit_bytes"]}',
        f'#define LINNET_COVERFLOW_EXPANDED {int(spec.get("coverflow_cache") == "expanded")}u',
        f'#define LINNET_PHOTO_WIDTH {spec["media_photo_width"]}u',
        f'#define LINNET_PHOTO_HEIGHT {spec["media_photo_height"]}u',
        f'#define LINNET_VIDEO_WIDTH {spec["media_video_width"]}u',
        f'#define LINNET_VIDEO_HEIGHT {spec["media_video_height"]}u',
        f'#define LINNET_VIDEO_FPS {spec["media_video_fps"]}u',
        f'#define LINNET_ART_MAX_SIDE {spec["media_art_side"]}u',
        f'#define LINNET_VIDEO_CATALOG_PAGED {int(spec.get("video_catalog_cache") == "paged")}u',
        f'#define LINNET_VIDEO_PACKET_BYTES {spec.get("native_video", {}).get("sample_bytes", 65536)}u',
        f'#define LINNET_VIDEO_START_AUDIO_FRAMES {spec["video_start_audio_frames"]}u',
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
        "#endif",
    ]
    target_header[-1:-1] = [f'#define {name} {value}' for name, value in presentation_defines(spec).items()]
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
    source_inventory = []
    build_id = source_identity(configuration, chain, source_inventory)
    (generated / "linnet_build.h").write_text('#define LINNET_BUILD_ID "' + build_id + '"\n#define LINNET_BUILD_ID_BYTES {' + ','.join('0x' + build_id[i:i+2] for i in range(0, 64, 2)) + '}\n')
    with (generated / "linnet_build.h").open('a') as header:
        header.write('#define LINNET_USB_SERIAL "' + device_serial + '"\n')
    prefix = f"linnet-{kind}-0.1.0-{target}-{profile}-{build_id[:12]}"
    target_sources = spec["sources"]
    hal = ROOT / "hal" / spec["hal_family"]
    # A target may trade Boot speed for size when it shares a fixed NOR slot.
    optimization = "-Oz" if spec["boot_size_optimization"] and kind == "boot" else "-Os"
    # Each backend keeps its include paths, optimization, and warning exceptions
    # beside its selected sources below. ARM4 codec tuning also applies to the
    # ARM926 build; native video decoding has its own target-independent rule.
    backend_flags = {
        'aac': ['-Ithird_party/aac','-Ithird_party/aac/faad','-Ithird_party/aac/lib',
                '-O3','-fomit-frame-pointer','-DCPU_ARM=1','-DARM_ARCH=4'],
        # libmad requantization and synthesis need O3 on the ARM7 playback path.
        'mp3': ['-Ithird_party/libmad','-O3','-fomit-frame-pointer','-DCPU_ARM_CLASSIC=1'],
        'vorbis': ['-Ithird_party/vorbis','-Ithird_party/aac/lib'],
        'h264bsd': ['-O3','-fomit-frame-pointer','-Wno-unused-parameter',
                    '-Wno-unused-but-set-variable','-include','services/video/native/compat.h'],
        'pvmp4': ['-O3','-fomit-frame-pointer','-fno-exceptions','-fno-rtti',
                  '-DDEC_NOPOSTPROC','-Ithird_party/pvmp4/compat','-Ithird_party/pvmp4',
                  '-Wno-unused-parameter','-Wno-unused-but-set-variable','-Wno-sign-compare'],
        'native_video': ['-O3','-fomit-frame-pointer'],
    }
    sources, source_origins, source_flags = [], [], []
    def add_sources(paths, origin, extra_flags=()):
        if not paths:
            raise ValueError(f"no build sources selected for {origin}")
        sources.extend(paths)
        source_origins.extend([origin] * len(paths))
        source_flags.extend([list(extra_flags) for _ in paths])
    add_sources([ROOT / target_sources["startup"], hal / "entry.S",
                 ROOT / target_sources["platform"], ROOT / target_sources["lcd"],
                 ROOT / "kernel/main.c", ROOT / "kernel/memory.S"], "base startup")
    add_sources([ROOT / "boot/src/linnet_boot.c"], "boot service")
    add_sources([hal / name for name in ("core.c", "input.c")], "HAL core")
    add_sources([ROOT / target_sources["power"]], "target power")
    for directory in (hal, ROOT / "targets" / target):
        source_list=directory / "SOURCES"
        if source_list.is_file():
            for line_number, name in enumerate(source_list.read_text().splitlines(), 1):
                source=(ROOT / name).resolve()
                if not name or not source.is_relative_to(ROOT) or not source.is_file():
                    raise ValueError(f"Invalid platform source in {source_list}: {name}")
                add_sources([source], f"{source_list.relative_to(ROOT).as_posix()}:{line_number}")
    add_sources([ROOT / target_sources["display"], ROOT / target_sources["device"],
                 ROOT / target_sources["codec"]], "target display, device, codec")
    if "display_assembly" in target_sources:
        add_sources([ROOT / target_sources["display_assembly"]], "target display assembly")
    if kind == "os" and "coprocessor" in target_sources:
        add_sources([ROOT / target_sources["coprocessor"]], "target coprocessor")
    if kind == "os" and spec.get("cop_display", False):
        add_sources([ROOT / "targets" / target / name for name in ("video_blit.c", "video_blit.S")], "COP display")
    if kind == "os":
        add_sources([ROOT / name for name in
                     ("kernel/executive.c", "kernel/runtime.c", "kernel/wheel_motion.c")], "OS runtime")
        add_sources([ROOT / "ui/runtime/shell_adapter.c", ROOT / "services/display/clock.c"], "OS display")
    if profile != "release":
        add_sources(sorted((ROOT / "hal/link").glob("*.c")), "development link")
        add_sources([ROOT / name for name in ("boot/src/loader.c", "boot/src/sha256.c")], "development loader")
        add_sources([hal / name for name in ("usb.c", "recovery.c")], "development HAL")
        if (hal / "recovery.S").is_file():
            add_sources([hal / "recovery.S"], "development recovery")
        add_sources([ROOT / "kernel/development.c"], "development kernel")
        if kind == "os":
            add_sources([ROOT / "kernel/platform_link.c"], "development OS")
    if spec["hal_family"] == "pp502x" and (profile != "release" or kind == "os"):
        add_sources([hal / "disk_mode.c"], "PP502x disk mode")
        if profile == "release":
            add_sources([hal / "usb.c"], "PP502x release USB")
    # -Oz emits an unavailable __aeabi_idiv helper for block's pointer-distance
    # division, so this translation unit keeps -Os in a size-tuned Boot.
    add_sources([ROOT / "services/storage/block.c"], "storage block",
                ['-Os'] if optimization == '-Oz' else ())
    add_sources([ROOT / name for name in (
        "services/storage/fat32.c",
        "services/storage/storage.c", "services/state/store.c",
        "services/update/update.c")], "storage and state")
    add_sources([hal / "persistent_enter.S"], "HAL persistence")
    add_sources([hal / "ata.c"], "HAL ATA")
    if profile == "release":
        add_sources([ROOT / "boot/src/sha256.c"], "release integrity")
    else:
        add_sources([ROOT / "kernel/storage_link.c"], "development storage")
        if kind == "os":
            add_sources([ROOT / target_sources["native_update"]], "target native update")
    if kind == "os":
        add_sources([ROOT/"ui/runtime/ui.c"], "OS UI runtime")
        add_sources([generated/"linnet_ui.c"], "generated OS UI",
                    ('-O2',) if ui_report['features'].get('cover_flow', False) else ())
        add_sources([ROOT/"services/display/settings.c"], "OS display settings")
    compiler_target = "arm-none-eabi" if spec["endianness"] == "little" else "armeb-none-eabi"
    flags = [f"--target={compiler_target}", f'-mcpu={spec["cpu"]}', f'-march={spec["architecture"]}', "-marm", "-mfloat-abi=soft", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-ffunction-sections", "-fdata-sections", optimization, "-Wall", "-Wextra", "-Werror", "-I.", "-Iboot/include", f"-DLINNET_PROFILE_{profile.upper()}=1", f"-DLINNET_IMAGE_{kind.upper()}=1", f'-D{spec["target_define"]}=1']
    flags += ["-I" + str(generated), f"-DLINNET_PROBE_CRASH={int(probe == 'crash')}", f"-DLINNET_PROBE_HANG={int(probe == 'hang')}"]
    flags += ["-DLINNET_PLATFORM_CORE=1", "-DLINNET_STORAGE=1"]
    if kind == "os":
        flags += ["-DLINNET_NATIVE_UI=1"]
        flags += ["-DLINNET_AUDIO=1"]
        add_sources([hal/'audio.c',ROOT/'services/audio/codec_pcm.c'], "OS audio")
        add_sources([ROOT/'services/music/player.c',ROOT/'services/music/database.c'], "music playback")
        add_sources([ROOT/'services/music/library.c',ROOT/'services/music/controller.c',ROOT/'services/music/queue.c',ROOT/'services/music/ui.c'], "music library")
        add_sources([ROOT/'services/music/artwork.c'], "music artwork")
        add_sources([ROOT/'services/music/browser.c'], "music browser")
        add_sources([ROOT/'services/music/search.c',ROOT/'services/music/profile.c',ROOT/'services/music/settings.c'], "music settings")
        add_sources([ROOT/'services/music/queue_view.c',ROOT/'services/music/collections.c'], "music views")
        add_sources([ROOT/'services/music/decoder.c'], "music decoder")
        add_sources([ROOT/'services/audio/dsp.c'], "audio DSP", ['-O2'])
        add_sources([ROOT/'services/audio/dsp_arm.S'], "audio DSP assembly")
        add_sources([ROOT/'services/audio/mp3/mp3.c'], "MP3 service", backend_flags['mp3'])
        add_sources([ROOT/'services/music/history.c'], "music history")
        add_sources([ROOT/'services/music/history_pages.c',ROOT/'services/music/journal_pages.c'], "music history pages")
        add_sources([ROOT/'services/audio/flac/flac.c',ROOT/'third_party/flac/decoder.c'], "FLAC backend")
        add_sources([ROOT/'services/audio/alac/alac.c',ROOT/'third_party/alac/alac.c'], "ALAC backend")
        add_sources([ROOT/'services/audio/aac/aac.c',ROOT/'services/audio/aac/m4a.c'], "AAC service", backend_flags['aac'])
        add_sources([ROOT/'third_party/aac'/name for name in (ROOT/'third_party/aac/SOURCES').read_text().splitlines() if name], "third_party/aac/SOURCES", backend_flags['aac'])
        add_sources([ROOT/'services/audio/vorbis'/name for name in ('vorbis.c','pool.c','division.c')], "Vorbis service", backend_flags['vorbis'])
        add_sources([ROOT/'third_party/vorbis'/name for name in ('bitwise.c','block.c','codebook.c','floor0.c','floor1.c','info.c','mapping0.c','registry.c','res012.c','sharedbook.c','synthesis.c','window.c')], "Vorbis backend", backend_flags['vorbis'])
        add_sources([ROOT/'third_party/libmad'/name for name in ('bit.c','frame.c','huffman.c','layer12.c','layer3.c','stream.c','synth.c','imdct_l_arm.S','synth_full_arm.S')], "MP3 backend", backend_flags['mp3'])
        flags += ['-fwrapv']
        if profile!='release':
            add_sources([ROOT/'kernel/audio_link.c'], "development audio")
    if kind == 'os' and ui_report['features'].get('cover_flow', False):
        flags += ['-DLINNET_COVERFLOW=1']
    if kind == 'os' and ui_report['features'].get('video', True):
        flags += ['-DLINNET_VIDEO=1']
        video_backend = spec['media_video_backend']
        add_sources([ROOT/'services/video/catalog.c'], "video catalog")
        player_flags = (backend_flags['native_video'] if video_backend == 'native-mp4' else
                        ['-O2'] if video_backend == 'ipvf' else ())
        add_sources([ROOT/target_sources['video']], "target video player", player_flags)
        if video_backend == 'ipvf':
            add_sources(sorted((ROOT/'services/video/ipvf').glob('*.S')), "IPVF assembly")
        if video_backend in ('native-mp4', 'bcm-mp4'):
            add_sources([ROOT/'services/video/mp4.c'], "MP4 service")
        if video_backend == 'native-mp4':
            flags += [f"-DLINNET_H264_MAX_WIDTH={spec['native_video']['h264_width']}",
                      f"-DLINNET_H264_MAX_HEIGHT={spec['native_video']['h264_height']}"]
            add_sources([ROOT/'services/video/native/decoder.c',ROOT/'services/video/native/yuv.c'],
                        "native video decoder", backend_flags['native_video'])
            add_sources(sorted((ROOT/'third_party/h264bsd').glob('*.c')), "H.264 backend", backend_flags['h264bsd'])
            if spec['cpu'] == 'arm926ej-s':
                flags += ['-DLINNET_ARM926_YUV=1']
                add_sources([ROOT/'hal/arm926/yuv.S'], "ARM926 YUV")
            if spec['mpeg4_decoder'] in ('pvmp4','s5l8702-vpu'):
                flags += ['-DLINNET_MPEG4=1']
                add_sources([ROOT/'services/video/native/mpeg4_memory.c'],
                            "MPEG-4 memory", backend_flags['native_video'])
                add_sources([ROOT/('hal/s5l8702/mpeg4.cpp' if spec['mpeg4_decoder'] == 's5l8702-vpu' else 'services/video/native/mpeg4.cpp')],
                            "MPEG-4 decoder", backend_flags['pvmp4'])
                if spec['mpeg4_decoder'] == 's5l8702-vpu':
                    flags += ['-DLINNET_MPEG4_VPU=1']
                    add_sources([ROOT/'hal/s5l8702/mpeg4_vpu.c'], "S5L8702 MPEG-4 VPU")
                add_sources([ROOT/'third_party/pvmp4'/name for name in (ROOT/'third_party/pvmp4/SOURCES').read_text().splitlines() if name],
                            "third_party/pvmp4/SOURCES", backend_flags['pvmp4'])
            decoder = spec['h264_decoder']
            if decoder == 's5l8702-vpu' and spec['soc'] == 's5l8702':
                flags += ['-DLINNET_H264_VPU=1']
                add_sources([ROOT/'hal/s5l8702/h264.c'], "S5L8702 H.264 decoder", backend_flags['native_video'])
                add_sources([ROOT/'hal/s5l8702/vpu.c'], "S5L8702 VPU")
            elif decoder == 'software':
                add_sources([ROOT/'services/video/native/h264.c'], "software H.264 decoder", backend_flags['native_video'])
            else:
                raise ValueError(f'Unsupported H.264 decoder: {decoder}')
    if kind == 'os':
        flags += ['-DLINNET_BATTERY_GUARD=1']
        if profile!='release':flags += ['-DLINNET_AUDIO_CACHE_DIAGNOSTIC=1']
        add_sources([ROOT/'services/power/battery.c'], "OS battery")
    if kind == 'os':
        flags += ['-DLINNET_NOTES=1']
        add_sources(sorted((ROOT/'services/notes').glob('*.c')), "Notes service")
    if kind == 'os' and ui_report['features'].get('photos', True):
        flags += ['-DLINNET_PHOTOS=1']
        add_sources(sorted((ROOT/'services/photos').glob('*.c')), "Photos service")
        add_sources(sorted((ROOT/'third_party/jpeg').glob('*.c')), "JPEG backend")
    seen_sources = {}
    source_selections = []
    for source, origin, extra_flags in zip(sources, source_origins, source_flags):
        if not source.is_relative_to(ROOT) or not source.is_file():
            raise ValueError(f"missing or external build source {source} selected by {origin}")
        resolved = source.resolve()
        if not resolved.is_relative_to(ROOT):
            raise ValueError(f"external build source {source} selected by {origin}")
        if resolved in seen_sources:
            raise ValueError(f"duplicate build source {source.relative_to(ROOT)} selected by "
                             f"{seen_sources[resolved]} and {origin}")
        seen_sources[resolved] = origin
        source_selections.append(dict(path=source.relative_to(ROOT).as_posix(),
                                      origin=origin, compiler_flags=extra_flags))
    objects = []
    compile_commands = []
    object_names = Counter(source.relative_to(ROOT).as_posix().replace('/', '_') + '.o'
                           for source in sources)
    for source, codec_flags in zip(sources, source_flags):
        source_path = source.relative_to(ROOT)
        flat_name = source_path.as_posix().replace('/', '_') + '.o'
        obj = (dest / flat_name if object_names[flat_name] == 1 else
               dest / 'objects' / source_path.with_suffix(source_path.suffix + '.o'))
        obj.parent.mkdir(parents=True, exist_ok=True)
        compile_commands.append([chain['compiler']['path'], *flags, *codec_flags,
                                 "-c", source, "-o", obj])
        objects.append(obj)
    # Header generation and source selection have finished. Compile only the
    # independent translation units here; the linker retains source order.
    use_object_cache = os.environ.get('LINNET_OBJECT_CACHE', '1') != '0'
    cache_hits = 0
    if use_object_cache:
        from .object_cache import compile_object, include_names
        object_cache_root = ROOT / 'out' / 'object-cache-v1'
        name_inventory = include_names(ROOT, generated, chain['compiler']['path'],
                                       source_inventory, run)

        def compile_one(command):
            return compile_object(command, ROOT, generated, chain['compiler']['sha256'],
                                  name_inventory, object_cache_root, run)
    else:
        def compile_one(command):
            run(command)
            return False
    if jobs == 1:
        for command in compile_commands:
            cache_hits += compile_one(command)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = [executor.submit(compile_one, command) for command in compile_commands]
            try:
                for future in as_completed(futures):
                    cache_hits += future.result()
            except Exception:
                for future in futures:
                    future.cancel()
                raise
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
    watchdog_limitation = None if spec["hal_family"] == "s5l8702" else (
        "FIQ watchdog depends on FIQ delivery; COP reset escalation requires a live COP monitor."
        if "coprocessor" in target_sources else "Watchdog recovery requires FIQ delivery.")
    resident_limit = 1048576
    if kind == 'os':
        resident_limit = spec['resident_limit_bytes']
        if spec['hal_family'] == 'pp502x' and not ui_report['features'].get('cover_flow', False):
            resident_limit = 5505024
    report = dict(**configuration, build_id=build_id, toolchain=chain, image=inspect(envelope),
                  object_cache=dict(enabled=use_object_cache, hits=cache_hits,
                                    misses=len(compile_commands)-cache_hits),
                  source_files=[selection['path'] for selection in source_selections],
                  source_selections=source_selections,
                  artifacts={key: str(path.relative_to(ROOT)) for key, path in dict(elf=elf, los=los, ipod=ipod, map=mapfile).items()},
                  memory=dict(regions=sections, total_allocated_bytes=sum(s['bytes'] for s in sections), resident_limit_bytes=resident_limit, retained_limit_bytes=spec['mailbox_bytes'],
                              static_budget=memory_budget(sections, spec, resident_limit)),
                  release_exclusion=verification, limitation=watchdog_limitation)
    if ui_report is not None:report["ui"]=ui_report
    (dest / (prefix + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    if use_object_cache:
        from .object_cache import trim
        trim(object_cache_root)
    return report
