"""Portable release firmware bundles consumed without a compiler."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
import zipfile

from tools.inspect.image import inspect, verify_release
from tools.studio.targets import ROOT, target_id


FILES = {"os.los", "os.json"} | {
    f"boot-{selector}.{extension}"
    for selector in ("none", "rockbox") for extension in ("los", "json", "ipod")}
MAX_BYTES = 64 * 1024 * 1024


def create(target, output, jobs=2):
    from tools.studio.build import build
    target = target_id(target)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("firmware bundle output already exists")
    payloads = {}
    for kind, selector in (("os", "none"), ("boot", "none"), ("boot", "rockbox")):
        report = build("release", target, verify=True, kind=kind, boot_selector=selector, jobs=jobs)
        name = "os" if kind == "os" else "boot-" + selector
        payloads[name + ".los"] = (ROOT / report["artifacts"]["los"]).read_bytes()
        if kind == "boot":
            payloads[name + ".ipod"] = (ROOT / report["artifacts"]["ipod"]).read_bytes()
        # Keep the verified image contract, without build-machine paths.
        portable = {key: report[key] for key in (
            "kind", "profile", "target_id", "device_serial", "build_id", "image", "release_exclusion")}
        if kind == "boot":
            portable.update(boot_selector=selector, apple_firmware_fallback=report["apple_firmware_fallback"])
        payloads[name + ".json"] = (json.dumps(portable, indent=2) + "\n").encode("utf-8")
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
        load(temporary, dict(target_id=target), "native-preserve")
        load(temporary, dict(target_id=target), "native-selector")
        temporary.rename(output)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(bundle=str(output), target_id=target,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest())


def load(path, identity, installation_method):
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
            if (len(entries) != len(FILES) + 1 or
                    {item.filename for item in entries} != FILES | {"manifest.json"} or
                    any(item.file_size > MAX_BYTES for item in entries) or
                    sum(item.file_size for item in entries) > MAX_BYTES):
                raise ValueError("firmware bundle has unexpected files or sizes")
            manifest = json.loads(bundle.read("manifest.json"))
            if (not isinstance(manifest, dict) or manifest.get("format") != 1 or
                    manifest.get("target_id") != identity["target_id"] or
                    not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != FILES):
                raise ValueError("firmware bundle does not match the detected iPod")
            payloads = {name: bundle.read(name) for name in FILES}
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
    parent = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "Linnet/Firmware"
    parent.mkdir(parents=True, exist_ok=True)
    # Keep each selection private to its installation, including concurrent runs.
    with tempfile.TemporaryDirectory(prefix="verify-", dir=parent) as temporary:
        staging = Path(temporary)
        for name, data in payloads.items():
            (staging / name).write_bytes(data)
        def artifacts(directory):
            return dict(os_image=str(directory / "os.los"), os_report=str(directory / "os.json"),
                        boot_image=str(directory / f"boot-{selector}.los"),
                        boot_report=str(directory / f"boot-{selector}.json"),
                        boot_wrapper=str(directory / f"boot-{selector}.ipod"),
                        build="user", os_profile="release",
                        os_build_id=inspect(payloads["os.los"])["build_id"],
                        boot_build_id=inspect(payloads[f"boot-{selector}.los"])["build_id"],
                        installation_method=method, boot_selector=selector)
        _validate_artifacts(identity, artifacts(staging))
        destination = parent / uuid.uuid4().hex
        destination.mkdir()
        for name in FILES:
            (staging / name).replace(destination / name)
    return artifacts(destination)
