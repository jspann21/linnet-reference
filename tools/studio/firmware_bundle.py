"""Portable release firmware bundles consumed without a compiler."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
import zipfile

from tools.inspect.image import inspect, verify_release
from tools.studio.targets import ROOT, target_id, target_spec


OS_NAME = "firmware/linnet-os"
BOOT_NAMES = {"none": "firmware/linnet-boot-standard",
              "rockbox": "firmware/linnet-boot-multiboot"}
FILES = {OS_NAME + ".los", OS_NAME + ".json", "README.txt"} | {
    f"{name}.{extension}"
    for name in BOOT_NAMES.values() for extension in ("los", "json", "ipod")}
CLASSIC_FILES = {'bootstrap/manifest.json'} | {
    'bootstrap/' + name for name in ('monitor.bin', 'rom_transfer.bin', 'probe.bin', 'sram_bridge.bin')}
PACKAGE_README = """Linnet firmware

Select this entire ZIP in Linnet Media Manager:
iPod setup > Choose firmware ZIP

Do not extract the ZIP or choose individual files. Media Manager verifies your
iPod model and selects the required Linnet bootloader for your installation.

The firmware folder contains Linnet OS and two Linnet bootloader variants:
- standard: Linnet with Apple software fallback.
- multiboot: also allows starting a compatible, existing Rockbox installation.
Both bootloaders are Linnet software. This package does not install Rockbox.
Fresh installations use native Linnet by default, keeping a verified Rockbox
image available in the startup chooser when compatible. Reinstalls and resumes
retain the saved installation method; the existing Rockbox loader is optional.

For a fresh iPod Classic, Media Manager also installs Linnet Boot. Follow its
on-screen connection instructions; it detects the device's mode and continues
automatically. Original startup software and recovery backups are preserved.
"""
MAX_BYTES = 64 * 1024 * 1024


def create(target, output, jobs=2):
    from tools.studio.build import build
    target = target_id(target)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("firmware bundle output already exists")
    from tools.content.apple_font import check_packaged_assets
    check_packaged_assets(ROOT)
    payloads = {"README.txt": PACKAGE_README.encode("utf-8")}
    if target_spec(target)['capabilities']['games']:
        from tools.studio.game_build import build_library,library
        prepared=ROOT/'out/game-packages'/target
        build_library(target,prepared)
        paths=library(prepared,target)
        payloads['games/library.json']=(prepared/'library.json').read_bytes()
        for path in paths.values():payloads['games/'+path.name]=path.read_bytes()
    for kind, selector in (("os", "none"), ("boot", "none"), ("boot", "rockbox")):
        report = build("release", target, verify=True, kind=kind, boot_selector=selector, jobs=jobs)
        name = OS_NAME if kind == "os" else BOOT_NAMES[selector]
        payloads[name + ".los"] = (ROOT / report["artifacts"]["los"]).read_bytes()
        if kind == "boot":
            payloads[name + ".ipod"] = (ROOT / report["artifacts"]["ipod"]).read_bytes()
        # Keep the verified image contract, without build-machine paths.
        portable = {key: report[key] for key in (
            "kind", "profile", "target_id", "device_serial", "build_id", "image", "release_exclusion", "probe")}
        if kind == "boot":
            portable.update(boot_selector=selector, apple_firmware_fallback=report["apple_firmware_fallback"],
                            startup_default_format=report["startup_default_format"])
        payloads[name + ".json"] = (json.dumps(portable, indent=2) + "\n").encode("utf-8")
    if target == 'classic6g-n25':
        from tools.studio.s5l_bootstrap import build as build_bootstrap, TEMPLATE_SERIAL
        with tempfile.TemporaryDirectory(prefix='classic-bootstrap-') as temporary:
            directory=Path(temporary)
            build_bootstrap(TEMPLATE_SERIAL,directory)
            for name in CLASSIC_FILES:
                payloads[name]=(directory/Path(name).name).read_bytes()
    manifest = dict(format=1, target_id=target,
                    files={name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                           for name, data in sorted(payloads.items())})
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            for name, data in sorted(payloads.items()):
                bundle.writestr(name, data)
        # Exercise the consumer's checks before publishing a bundle.
        load(temporary, dict(target_id=target), "native-preserve", verify_only=True)
        load(temporary, dict(target_id=target), "native-selector", verify_only=True)
        temporary.rename(output)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(bundle=str(output), target_id=target,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest())


def load(path, identity, installation_method, *, verify_only=False):
    """Validate a bundle, retaining installation files unless only checking it."""
    from tools.studio.installer import INSTALLATION_METHODS, _validate_artifacts
    method = "native-preserve" if installation_method == "native-volume" else installation_method
    if method not in INSTALLATION_METHODS:
        raise ValueError("unsupported firmware installation method")
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("firmware bundle exceeds its size limit")
    try:
        with zipfile.ZipFile(path) as bundle:
            entries = bundle.infolist()
            names={item.filename for item in entries}
            game_files={name for name in names if name.startswith('games/')}
            from tools.content.game_package import FILE_PATTERN,CATALOGUE_MAX
            if (len(game_files)>CATALOGUE_MAX+1 or any(name!='games/library.json' and
                    not FILE_PATTERN.fullmatch(name.removeprefix('games/')) for name in game_files)
                    or game_files and 'games/library.json' not in game_files):
                raise ValueError('Invalid prepared games in firmware bundle')
            files=FILES | (CLASSIC_FILES if identity['target_id']=='classic6g-n25' else set()) | game_files
            if (len(entries) != len(files) + 1 or
                    names != files | {"manifest.json"} or
                    any(item.file_size > MAX_BYTES for item in entries) or
                    sum(item.file_size for item in entries) > MAX_BYTES):
                raise ValueError("firmware bundle has unexpected files or sizes")
            manifest = json.loads(bundle.read("manifest.json"))
            if (not isinstance(manifest, dict) or manifest.get("format") != 1 or
                    manifest.get("target_id") != identity["target_id"] or
                    not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != files):
                raise ValueError("firmware bundle does not match the detected iPod")
            payloads = {name: bundle.read(name) for name in files}
    except (zipfile.BadZipFile, KeyError, UnicodeError, RuntimeError) as error:
        raise ValueError("invalid firmware bundle") from error
    for name, data in payloads.items():
        if manifest["files"][name] != dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()):
            raise ValueError("firmware bundle checksum mismatch: " + name)
        if name.endswith(".los"):
            verify_release(data, "")
            if inspect(data)["target_id"] != identity["target_id"]:
                raise ValueError("firmware image target mismatch")
    selector = INSTALLATION_METHODS[method]["boot_selector"]
    boot_name = BOOT_NAMES[selector]
    parent = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "Linnet/Firmware"
    parent.mkdir(parents=True, exist_ok=True)
    # Keep each selection private to its installation, including concurrent runs.
    with tempfile.TemporaryDirectory(prefix="verify-", dir=parent) as temporary:
        staging = Path(temporary)
        for name, data in payloads.items():
            (staging / name).parent.mkdir(parents=True, exist_ok=True)
            (staging / name).write_bytes(data)
        if game_files:
            from tools.studio.game_build import library
            prepared=library(staging/'games',identity['target_id'])
            if game_files!={'games/library.json'}|{'games/'+p.name for p in prepared.values()}:
                raise ValueError('Firmware game library contains unlisted files')
        def artifacts(directory):
            return dict(os_image=str(directory / (OS_NAME + ".los")), os_report=str(directory / (OS_NAME + ".json")),
                        boot_image=str(directory / (boot_name + ".los")),
                        boot_report=str(directory / (boot_name + ".json")),
                        boot_wrapper=str(directory / (boot_name + ".ipod")),
                        build="user", os_profile="release",
                        os_build_id=inspect(payloads[OS_NAME + ".los"])["build_id"],
                        boot_build_id=inspect(payloads[boot_name + ".los"])["build_id"],
                        installation_method=method, boot_selector=selector,
                        game_library=str(directory/'games') if game_files else None)
        _validate_artifacts(identity, artifacts(staging))
        if verify_only:
            return None
        destination = parent / uuid.uuid4().hex
        destination.mkdir()
        for name in files:
            (destination / name).parent.mkdir(parents=True, exist_ok=True)
            (staging / name).replace(destination / name)
    result=artifacts(destination)
    if CLASSIC_FILES<=files:result['bootstrap_template']=str(destination/'bootstrap')
    return result
