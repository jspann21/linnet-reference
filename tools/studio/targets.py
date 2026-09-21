"""Target manifest discovery shared by build, image, and device tooling."""
from pathlib import Path, PurePosixPath
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
TARGETS_ROOT = ROOT / "targets"
REQUIRED_KEYS = {
    "id", "name", "aliases", "image_target", "board_id", "model_alias",
    "soc", "cpu", "architecture", "endianness", "sdram_bytes",
    "os_capacity_bytes", "stage_address", "stage_bytes",
    "recovery_snapshot_address", "recovery_snapshot_bytes",
    "storage_max_read_sectors", "lcd_width",
    "lcd_height", "lcd_format", "capabilities", "media_photo_width",
    "media_photo_height", "media_video_width", "media_video_height",
    "media_video_fps", "media_video_color", "media_video_extensions", "media_video_backend",
    "cop_display", "entry_address", "load_address", "mailbox_address",
    "mailbox_bytes", "retail", "installer", "resources",
}
OPTIONAL_KEYS = {"ui", "hal_family", "audio_codec", "idle_clock_hz", "native_video"}
CAPABILITIES = {"photos", "video", "files", "demo", "themes", "cover_flow"}
LCD_FORMATS = {"rgb565-swapped": 1, "gray2-horizontal": 2, "rgb565": 3}


def _valid_ascii_list(value):
    return (isinstance(value, list) and
            all(isinstance(item, str) and item and item.isascii() for item in value))


def _target_sources(path, spec):
    """Resolve the conventional source layout for one target."""
    soc_root = ROOT / "hal" / spec.get("hal_family", spec["soc"])
    target_root = path.parent
    if not re.fullmatch(r"[a-z][a-z0-9-]*", spec.get("hal_family", spec["soc"])):
        raise RuntimeError(f"invalid HAL family: {path}")
    codec = spec.get("audio_codec", "wm8975")
    if codec not in {"wm8975", "wm8758"}:
        raise RuntimeError(f"unsupported audio codec: {path}")
    display = target_root / "display.c"
    if not display.is_file():
        display = soc_root / "display.c"
    sources = {
        "native_update": target_root / "native_update.c" if (target_root / "native_update.c").is_file() else ROOT / "services/update/native.c",
        "hardware": target_root / "hardware.h",
        "startup": soc_root / "startup.S",
        "linker": soc_root / "memory.ld",
        "platform": soc_root / "platform.c",
        "lcd": target_root / "lcd.c",
        "display": display,
        "device": target_root / "device.c",
        "codec": ROOT / "hal" / "codecs" / (codec + ".c"),
    }
    video = target_root / "video.c"
    if video.is_file():
        sources["video"] = video
    coprocessor = target_root / "coprocessor.c"
    if coprocessor.is_file():
        sources["coprocessor"] = coprocessor
    if any(not source.is_file() for source in sources.values()):
        missing = ", ".join(
            source.relative_to(ROOT).as_posix()
            for source in sources.values()
            if not source.is_file()
        )
        raise RuntimeError(f"missing target source for {path}: {missing}")
    return {
        name: source.relative_to(ROOT).as_posix()
        for name, source in sources.items()
    }


def _validate_ui(path, spec):
    ui = spec.get("ui")
    if ui is None:
        return
    if not isinstance(ui, dict) or set(ui) != {"allowed_themes", "default_theme"}:
        raise RuntimeError(f"invalid UI profile: {path}")
    allowed = ui["allowed_themes"]
    default = ui["default_theme"]
    if (not isinstance(allowed, list) or not allowed or
            len(allowed) != len(set(allowed)) or
            any(not isinstance(theme, str) or not theme for theme in allowed) or
            not isinstance(default, str) or default not in allowed):
        raise RuntimeError(f"invalid UI profile: {path}")


def _validate_identity(path, spec):
    aliases = spec["aliases"]
    dimensions = (spec["lcd_width"], spec["lcd_height"],
                  spec["media_photo_width"], spec["media_photo_height"],
                  spec["media_video_width"], spec["media_video_height"])
    addresses = (spec["entry_address"], spec["load_address"],
                 spec["stage_address"], spec["recovery_snapshot_address"],
                 spec["mailbox_address"])
    regions = ((spec["load_address"], spec["os_capacity_bytes"]),
               (spec["stage_address"], spec["stage_bytes"]),
               (spec["recovery_snapshot_address"], spec["recovery_snapshot_bytes"]),
               (spec["mailbox_address"], spec["mailbox_bytes"]))
    if (not isinstance(spec["name"], str) or not spec["name"] or
            not isinstance(aliases, list) or
            any(not isinstance(alias, str) or
                not re.fullmatch(r"[a-z0-9][a-z0-9-]*", alias)
                for alias in aliases) or
            len(aliases) != len(set(aliases)) or
            not isinstance(spec["board_id"], str) or
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", spec["board_id"]) or
            not isinstance(spec["model_alias"], str) or
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", spec["model_alias"]) or
            not isinstance(spec["soc"], str) or
            not re.fullmatch(r"[a-z][a-z0-9-]*", spec["soc"]) or
            not isinstance(spec["cpu"], str) or
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", spec["cpu"]) or
            any(type(value) is not int or value < 1 for value in dimensions) or
            spec["lcd_width"] > 1024 or spec["lcd_height"] > 1024 or
            spec["lcd_width"] * spec["lcd_height"] > 131072 or
            spec["media_photo_width"] > spec["lcd_width"] or
            spec["media_photo_height"] > spec["lcd_height"] or
            spec["media_video_width"] > spec["lcd_width"] or
            spec["media_video_height"] > spec["lcd_height"] or
            spec["lcd_format"] not in LCD_FORMATS or
            spec["architecture"] not in {"armv4t", "armv5te", "armv6"} or
            spec["endianness"] not in {"little", "big"} or
            type(spec["sdram_bytes"]) is not int or spec["sdram_bytes"] < 8 * 1024 * 1024 or
            any(type(value) is not int or not 0 <= value <= 0xffffffff
                for value in addresses) or
            any(type(size) is not int or size < 4096 for _, size in regions) or
            spec["stage_bytes"] < spec["os_capacity_bytes"] or
            spec["os_capacity_bytes"] % 512 or
            any(address + size > spec["sdram_bytes"] for address, size in regions) or
            any(a0 < a1+s1 and a1 < a0+s0 for index,(a0,s0) in enumerate(regions)
                for a1,s1 in regions[index+1:]) or
            spec["mailbox_address"] < 8192 or
            spec["recovery_snapshot_address"] + spec["recovery_snapshot_bytes"] +
                spec["lcd_width"] * spec["lcd_height"] * 2 > spec["mailbox_address"] - 8192 or
            spec["entry_address"] < spec["load_address"] or
            spec["entry_address"] >= spec["load_address"] + spec["os_capacity_bytes"] or
            type(spec["storage_max_read_sectors"]) is not int or
            not 8 <= spec["storage_max_read_sectors"] <= 1024 or
            type(spec["mailbox_bytes"]) is not int or spec["mailbox_bytes"] < 1 or
            spec["mailbox_address"] + spec["mailbox_bytes"] > 0x100000000 or
            type(spec["cop_display"]) is not bool):
        raise RuntimeError(f"invalid target identity: {path}")


def _validate_resources(path, spec):
    r=spec["resources"]
    if not isinstance(r,dict) or set(r)!={"music_titles_address","music_titles_bytes","coverflow_catalog_slots"}:
        raise RuntimeError(f"invalid resource budget: {path}")
    start,size,slots=(r[k] for k in ("music_titles_address","music_titles_bytes","coverflow_catalog_slots"))
    if (any(type(v) is not int for v in (start,size,slots)) or start%32 or size<840896 or
        not 16<=slots<=2048 or start < spec["recovery_snapshot_address"]+spec["recovery_snapshot_bytes"]+spec["lcd_width"]*spec["lcd_height"]*2 or
        start+size>spec["mailbox_address"]-8192):
        raise RuntimeError(f"resource budget overlaps recovery or exceeds limits: {path}")


def _validate_profiles(path, spec):
    retail = spec["retail"]
    if (not isinstance(retail, dict) or
            type(retail.get("usb_vid")) is not int or not 0 <= retail["usb_vid"] <= 0xffff or
            type(retail.get("usb_pid")) is not int or not 0 <= retail["usb_pid"] <= 0xffff or
            not _valid_ascii_list(retail.get("board_names")) or
            not _valid_ascii_list(retail.get("model_numbers")) or
            not _valid_ascii_list(retail.get("regulatory_models")) or
            not (retail["board_names"] or retail["model_numbers"])):
        raise RuntimeError(f"invalid retail detection profile: {path}")
    install = spec["installer"]
    loader = PurePosixPath(str(install.get("file_loader", ""))) if isinstance(install, dict) else PurePosixPath()
    required = {"enabled", "boot_layout", "file_loader", "wrapper_model",
                "wrapper_checksum_seed", "firmware_header_magic", "firmware_header_field",
                "firmware_partition_types", "media_partition_types", "firmware_entry_type",
                "max_firmware_bytes"}
    if (not isinstance(install, dict) or set(install) != required or type(install["enabled"]) is not bool or
            not re.fullmatch(r"[a-z][a-z0-9-]*", install["boot_layout"]) or
            (install["enabled"] and install["boot_layout"] != "ipod-directory") or
            loader.is_absolute() or ".." in loader.parts or len(loader.parts) < 2 or
            not re.fullmatch(r"[\x20-\x7e]{4}", install["wrapper_model"]) or
            type(install["wrapper_checksum_seed"]) is not int or not 0 <= install["wrapper_checksum_seed"] <= 0xffffffff or
            not re.fullmatch(r"[0-9a-fA-F]{8}", install["firmware_header_magic"]) or
            type(install["firmware_header_field"]) is not int or not 0 <= install["firmware_header_field"] <= 0xffff or
            any(not isinstance(values, list) or not values or len(values) != len(set(values)) or
                any(type(value) is not int or not 0 <= value <= 0xff for value in values)
                for values in (install["firmware_partition_types"], install["media_partition_types"])) or
            set(install["firmware_partition_types"]) & set(install["media_partition_types"]) or
            not re.fullmatch(r"[\x20-\x7e]{4}", install["firmware_entry_type"]) or
            type(install["max_firmware_bytes"]) is not int or
            not 512 <= install["max_firmware_bytes"] <= 1024 * 1024 * 1024 or
            install["max_firmware_bytes"] % 512):
        raise RuntimeError(f"invalid installer profile: {path}")


def _validate_media(path, spec):
    backend = spec.get("media_video_backend")
    enabled = spec["capabilities"].get("video", True)
    if backend not in ("none", "ipvf", "bcm-mp4") or (backend != "none") != enabled:
        raise RuntimeError(f"invalid media video backend: {path}")
    expected = {"none": {".ipvf"}, "ipvf": {".ipvf"}, "bcm-mp4": {".mp4", ".m4v"}}[backend]
    if set(spec["media_video_extensions"]) != expected:
        raise RuntimeError(f"video extensions disagree with backend: {path}")
    native = spec.get("native_video", {})
    fields = {"h264_width", "h264_height", "h264_level", "mpeg4_width", "mpeg4_height",
              "max_fps", "video_kbps", "max_video_kbps", "buffer_kbits", "audio_kbps"}
    if backend == "bcm-mp4":
        if (not isinstance(native, dict) or set(native) != fields or any(type(v) is not int or v <= 0 for v in native.values()) or
                spec["media_video_width"] > native["h264_width"] or
                spec["media_video_height"] > native["h264_height"] or
                spec["media_video_fps"] > native["max_fps"] or
                native["video_kbps"] > native["max_video_kbps"]):
            raise RuntimeError(f"invalid native video profile: {path}")
    elif native:
        raise RuntimeError(f"unexpected native video profile: {path}")


def load_targets():
    targets = {}
    aliases = {}
    image_targets = {}
    for path in sorted(TARGETS_ROOT.glob("*/target.toml")):
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
        target = spec.get("id")
        if (not isinstance(target, str) or
                not re.fullmatch(r"[a-z][a-z0-9-]*", target) or
                path.parent.name != target or
                not REQUIRED_KEYS <= set(spec) or
                set(spec) - REQUIRED_KEYS - OPTIONAL_KEYS):
            raise RuntimeError(f"invalid target manifest: {path}")
        if spec.get("idle_clock_hz",0) not in (0,30000000):
            raise RuntimeError(f"unsupported idle clock: {path}")
        _validate_identity(path, spec)
        spec["target_define"] = "LINNET_TARGET_" + target.upper().replace("-", "_")
        number = spec["image_target"]
        if (type(number) is not int or not 0 <= number <= 0xffffffff or
                number in image_targets or target in spec["aliases"] or
                not isinstance(spec["capabilities"], dict) or
                any(key not in CAPABILITIES or type(value) is not bool
                    for key, value in spec["capabilities"].items()) or
                type(spec["media_video_fps"]) is not int or
                not 4 <= spec["media_video_fps"] <= 30 or
                spec["media_video_color"] not in ("rgb565", "gray4") or
                not _valid_ascii_list(spec["media_video_extensions"]) or
                not spec["media_video_extensions"] or
                len(set(spec["media_video_extensions"])) != len(spec["media_video_extensions"]) or
                any(not re.fullmatch(r"\.[a-z0-9]+", extension)
                    for extension in spec["media_video_extensions"]) or
                (spec["capabilities"].get("video", True) and
                 spec["storage_max_read_sectors"] * 512 <
                 spec["media_video_width"] * spec["media_video_height"] * 2 + 16384)):
            raise RuntimeError(f"invalid target identity: {path}")
        _validate_media(path, spec)
        _validate_resources(path, spec)
        _validate_profiles(path, spec)
        _validate_ui(path, spec)
        names = [target, *spec.get("aliases", [])]
        if any(name in aliases for name in names):
            raise RuntimeError(f"duplicate or invalid target alias: {path}")
        spec["sources"] = _target_sources(path, spec)
        targets[target] = spec
        image_targets[number] = target
        aliases.update((name, target) for name in names)
    if not targets:
        raise RuntimeError("no target manifests found")
    return targets, aliases, image_targets


TARGETS, ALIASES, TARGET_IDS_BY_NUMBER = load_targets()
TARGET_NUMBERS = {target: number for number, target in TARGET_IDS_BY_NUMBER.items()}


def target_id(value):
    if value not in ALIASES:
        raise ValueError(f"unsupported target: {value}")
    return ALIASES[value]


def target_spec(value):
    return TARGETS[target_id(value)]


def media_profile(value):
    """Resolve Media Manager capabilities from the same manifest as firmware."""
    spec = target_spec(value)
    return dict(photo_enabled=spec["capabilities"].get("photos", True),
                video_enabled=spec["capabilities"].get("video", True),
                video_backend=spec["media_video_backend"],
                video_extensions=list(spec["media_video_extensions"]),
                video_fps=spec["media_video_fps"], video_color=spec["media_video_color"],
                photo_width=spec["media_photo_width"], photo_height=spec["media_photo_height"],
                video_width=spec["media_video_width"], video_height=spec["media_video_height"],
                max_read_sectors=spec["storage_max_read_sectors"],
                native_video=dict(spec.get("native_video", {})))
