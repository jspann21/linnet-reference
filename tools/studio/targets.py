"""Target manifest discovery shared by build, image and device tooling."""
from pathlib import Path
from pathlib import PurePosixPath
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
SOURCE_KEYS = ("startup_source", "linker_script", "platform_source", "lcd_source",
               "display_source", "target_source")
REQUIRED_KEYS = ("image_target", "target_define", "lcd_width", "lcd_height",
                 "ui_width", "ui_height", "capabilities", "media_video_fps",
                 "media_video_color", "retail", "installer", *SOURCE_KEYS)


def _valid_ascii_list(value):
    return (isinstance(value, list) and
            all(isinstance(item, str) and item and item.isascii() for item in value))


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


def load_targets():
    targets = {}
    aliases = {}
    image_targets = {}
    for path in sorted((ROOT / "targets").glob("*/target.toml")):
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
        target = spec.get("id")
        if (not isinstance(target, str) or path.parent.name != target or
                any(key not in spec for key in REQUIRED_KEYS)):
            raise RuntimeError(f"invalid target manifest: {path}")
        number = spec["image_target"]
        if (not isinstance(number, int) or not 0 <= number <= 0xffffffff or
                number in image_targets or
                not isinstance(spec["capabilities"], dict) or
                any(key not in ("photos", "video", "files", "demo", "themes") or type(value) is not bool
                    for key, value in spec["capabilities"].items()) or
                type(spec["media_video_fps"]) is not int or
                not 4 <= spec["media_video_fps"] <= 30 or
                spec["media_video_color"] not in ("rgb565", "gray4") or
                any(not isinstance(spec[key], str) or not (ROOT / spec[key]).is_file()
                    for key in SOURCE_KEYS)):
            raise RuntimeError(f"invalid target identity or source path: {path}")
        _validate_profiles(path, spec)
        names = [target, *spec.get("aliases", [])]
        if any(not isinstance(name, str) or name in aliases for name in names):
            raise RuntimeError(f"duplicate or invalid target alias: {path}")
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
