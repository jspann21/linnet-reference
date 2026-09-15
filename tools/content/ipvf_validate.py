# Adapted from ../ipod/tools/ipvf/validate.py (Rockbox IPVF host tools).
#!/usr/bin/env python3
"""Strict streaming validator and reconstructor for IPVF files."""
from __future__ import annotations

import struct
import zlib
from collections import Counter
from fractions import Fraction
from pathlib import Path

from . import ipvf_reference as ipvf


TYPE_NAMES = {
    ipvf.TYPE_KEY: "key",
    ipvf.TYPE_RECTS: "rect",
    ipvf.TYPE_REPEAT: "repeat",
    ipvf.TYPE_KEY_LZ4: "key_lz4",
    ipvf.TYPE_RECTS_LZ4: "rect_lz4",
    ipvf.TYPE_XOR_LZ4: "xor_lz4",
    ipvf.TYPE_MOTION_LZ4: "motion_lz4",
}


# zlib uses the reflected polynomial. Reverse each input byte and the CRC
# state to retain Rockbox's MSB-first polynomial and no-final-XOR contract.
_REVERSE_BITS = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))


def _reverse_crc(value):
    return int.from_bytes(value.to_bytes(4, "little").translate(_REVERSE_BITS), "big")


def rockbox_crc32(data: bytes, crc: int = 0xFFFFFFFF) -> int:
    return _reverse_crc(zlib.crc32(data.translate(_REVERSE_BITS),
                                  _reverse_crc(crc) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _apply_rects(previous: bytes, payload: bytes, count: int, frame_width: int, frame_height: int) -> bytes:
    current = bytearray(previous)
    position = 0
    for index in range(count):
        _require(position + 8 <= len(payload),
                 f"rectangle {index}: truncated header")
        x, y, width, height, data_size = struct.unpack_from(
            "<BBBBI", payload, position
        )
        position += 8
        _require(width > 0 and height > 0,
                 f"rectangle {index}: empty geometry")
        _require(x + width <= frame_width and y + height <= frame_height,
                 f"rectangle {index}: geometry out of bounds")
        _require((x & 1) == 0 and (width & 1) == 0,
                 f"rectangle {index}: non-native pixel-pair alignment")
        _require(data_size == width * height * 2,
                 f"rectangle {index}: invalid byte count")
        _require(position + data_size <= len(payload),
                 f"rectangle {index}: truncated pixels")
        for row in range(height):
            source = position + row * width * 2
            target = ((y + row) * frame_width + x) * 2
            current[target:target + width * 2] = \
                payload[source:source + width * 2]
        position += data_size
    _require(position == len(payload), "rectangle payload has trailing bytes")
    return bytes(current)


def inspect_file(
    path: Path,
    on_frame=None,
    cancelled=None,
    expected_width=None,
    expected_height=None,
    max_record_sectors=1024,
) -> dict:
    file_size = path.stat().st_size
    verify_audio = True

    with path.open("rb") as stream:
        header = stream.read(ipvf.DATA_OFFSET)
        _require(len(header) == ipvf.DATA_OFFSET, "truncated IPVF header")
        _require(header[:4] == ipvf.MAGIC, "bad IPVF magic")
        header_size, width, height, fps_num, fps_den, first_sectors, \
            frame_count, \
            flags, data_offset = struct.unpack_from("<HHHHHHIII", header, 4)
        _require(expected_width is None or width == expected_width,
                 "video width does not match the target")
        _require(expected_height is None or height == expected_height,
                 "video height does not match the target")
        _require(1 <= width <= 1024 and 1 <= height <= 1024 and
                 width * height <= 131072 and width * height % 2 == 0 and
                 type(max_record_sectors) is int and 8 <= max_record_sectors <= 1024,
                 "invalid IPVF target geometry")
        frame_bytes = width * height * 2
        audio_format, channels, bits, sample_rate, audio_frames = \
            struct.unpack_from("<HHHII", header, 28)
        pre_media_reserved = struct.unpack_from("<H", header, 42)[0]
        media_end_offset = struct.unpack_from("<Q", header, 44)[0]
        index_offset = struct.unpack_from("<Q", header, 52)[0]
        index_count = struct.unpack_from("<I", header, 60)[0]
        index_entry_size = struct.unpack_from("<H", header, 64)[0]
        metadata_length = struct.unpack_from("<H", header, 66)[0]
        metadata_offset = struct.unpack_from("<I", header, 68)[0]
        index_crc = struct.unpack_from("<I", header, 72)[0]
        media_id = struct.unpack_from("<I", header, 76)[0]

        _require(header_size == ipvf.HEADER_SIZE, "invalid logical header size")
        _require(fps_num > 0 and fps_den > 0, "unsupported frame rate")
        rate = Fraction(fps_num, fps_den)
        _require(ipvf.MIN_FPS <= rate <= ipvf.MAX_FPS,
                  "frame rate outside IPVF bounds")
        _require(frame_count > 0, "empty IPVF file")
        _require(flags in (ipvf.FLAGS,
                           ipvf.FLAGS | ipvf.FLAG_TEMPORAL_XOR),
                 "invalid flags")
        temporal_flag = (flags & ipvf.FLAG_TEMPORAL_XOR) != 0
        _require(data_offset == ipvf.DATA_OFFSET, "invalid data offset")
        _require(1 <= first_sectors <= max_record_sectors,
                 "invalid first record size")
        _require((audio_format, channels, bits, sample_rate) == (
            ipvf.AUDIO_FORMAT_IMA_ADPCM,
            ipvf.AUDIO_CHANNELS,
            ipvf.AUDIO_BITS_PER_SAMPLE,
            ipvf.AUDIO_SAMPLE_RATE,
        ), "invalid audio format")
        _require(audio_frames == ipvf.audio_boundary(frame_count, rate),
                 "audio duration does not match video")
        _require(pre_media_reserved == 0,
                 "nonzero reserved pre-media header field")
        _require(metadata_offset == ipvf.METADATA_OFFSET,
                 "invalid metadata offset")
        _require(metadata_length <= ipvf.METADATA_CAPACITY,
                 "metadata exceeds superblock bounds")
        metadata_end = metadata_offset + metadata_length
        _require(metadata_end <= ipvf.DATA_OFFSET,
                 "metadata exceeds superblock bounds")
        metadata = ipvf.parse_metadata(header[metadata_offset:metadata_end])
        _require(not any(header[metadata_end:ipvf.DATA_OFFSET]),
                 "nonzero superblock padding")
        _require(media_end_offset > ipvf.DATA_OFFSET,
                 "invalid media end offset")
        _require(media_end_offset <= file_size,
                 "media end offset exceeds file")
        _require(media_end_offset % ipvf.RECORD_SECTOR_SIZE == 0,
                 "media end offset is not sector aligned")
        _require(index_offset == media_end_offset,
                 "index does not begin at media end")
        _require(index_entry_size == ipvf.INDEX_ENTRY_SIZE,
                 "invalid index entry size")
        _require(index_count > 0 and index_count <= frame_count,
                 "invalid index entry count")
        index_bytes = index_count * index_entry_size
        _require(index_offset + index_bytes == file_size,
                 "index bounds do not match file end")

        counts: Counter[str] = Counter()
        audio_modes: Counter[str] = Counter()
        current_sectors = first_sectors
        position = ipvf.DATA_OFFSET
        previous: bytes | None = None
        stored_video_total = 0
        audio_total = 0
        padding_total = 0
        largest_record_sectors = 0
        decoded_audio_crc = 0xFFFFFFFF
        calculated_media_id = 0xFFFFFFFF
        keyframe_entries: list[tuple[int, int, int, int]] = []
        record_info: dict[int, tuple[int, int, int]] = {}

        for frame in range(frame_count):
            if cancelled is not None and cancelled():
                raise RuntimeError("Update cancelled")
            _require(1 <= current_sectors <= max_record_sectors,
                     f"frame {frame}: invalid sector chain")
            record_size = current_sectors * ipvf.RECORD_SECTOR_SIZE
            record_offset = position
            _require(record_offset + record_size <= media_end_offset,
                     f"frame {frame}: record exceeds media end")
            record = stream.read(record_size)
            _require(len(record) == record_size,
                     f"frame {frame}: truncated record")
            calculated_media_id = rockbox_crc32(
                record, calculated_media_id
            )
            kind, rect_count, next_sectors, stored_size, decoded_size, \
                audio_size = struct.unpack_from("<BBHIII", record)
            _require(kind in TYPE_NAMES, f"frame {frame}: unknown type {kind}")
            record_info[record_offset] = (frame, kind, current_sectors)
            audio_count = (ipvf.audio_boundary(frame + 1, rate) -
                           ipvf.audio_boundary(frame, rate))
            _require(audio_count > 0, f"frame {frame}: empty audio block")
            stereo_size = 8 + audio_count - 1
            mono_size = 4 + audio_count // 2
            _require(audio_size in (0, mono_size, stereo_size),
                     f"frame {frame}: invalid adaptive audio size")
            audio_modes[
                "silence" if audio_size == 0 else
                "mono" if audio_size == mono_size else "stereo"
            ] += 1
            used_size = ipvf.RECORD_HEADER_SIZE + stored_size + audio_size
            expected_sectors = (
                used_size + ipvf.RECORD_SECTOR_SIZE - 1
            ) // ipvf.RECORD_SECTOR_SIZE
            _require(expected_sectors == current_sectors,
                     f"frame {frame}: record sector count mismatch")
            _require(used_size <= record_size,
                     f"frame {frame}: payload exceeds record")
            _require(not any(record[used_size:]),
                     f"frame {frame}: nonzero sector padding")
            _require((frame + 1 < frame_count and next_sectors != 0) or
                     (frame + 1 == frame_count and next_sectors == 0),
                     f"frame {frame}: invalid next-record link")

            stored = record[
                ipvf.RECORD_HEADER_SIZE:
                ipvf.RECORD_HEADER_SIZE + stored_size
            ]
            audio = record[
                ipvf.RECORD_HEADER_SIZE + stored_size:used_size
            ]
            if verify_audio:
                decoded_audio = ipvf.decode_ima_adpcm(audio, audio_count)
                _require(len(decoded_audio) == audio_count *
                         ipvf.AUDIO_FRAME_BYTES,
                         f"frame {frame}: decoded audio length mismatch")
                decoded_audio_crc = rockbox_crc32(
                    decoded_audio, decoded_audio_crc
                )

            compressed = kind in (
                ipvf.TYPE_KEY_LZ4,
                ipvf.TYPE_RECTS_LZ4,
                ipvf.TYPE_XOR_LZ4,
                ipvf.TYPE_MOTION_LZ4,
            )
            expected_temporal_crc = None
            if compressed:
                _require(0 < stored_size < decoded_size,
                         f"frame {frame}: invalid compressed sizes")
                compressed_payload = stored
                if kind in (ipvf.TYPE_XOR_LZ4, ipvf.TYPE_MOTION_LZ4):
                    _require(temporal_flag and stored_size >= 5,
                             f"frame {frame}: temporal flag/size mismatch")
                    crc_offset = 2 if kind == ipvf.TYPE_MOTION_LZ4 else 0
                    _require(stored_size >= crc_offset + 5,
                             f"frame {frame}: temporal payload too small")
                    expected_temporal_crc = struct.unpack_from(
                        "<I", stored, crc_offset
                    )[0]
                    compressed_payload = stored[crc_offset + 4:]
                    _require(
                        rockbox_crc32(compressed_payload) ==
                        expected_temporal_crc,
                        f"frame {frame}: temporal payload CRC mismatch",
                    )
                payload = ipvf.lz4_decompress(
                    compressed_payload, decoded_size
                )
            else:
                _require(stored_size == decoded_size,
                         f"frame {frame}: raw size mismatch")
                payload = stored

            if kind in (ipvf.TYPE_KEY, ipvf.TYPE_KEY_LZ4):
                _require(rect_count == 0 and decoded_size == frame_bytes,
                         f"frame {frame}: invalid keyframe")
                current = payload
            elif kind in (ipvf.TYPE_RECTS, ipvf.TYPE_RECTS_LZ4):
                _require(previous is not None and rect_count > 0 and
                         decoded_size > 0,
                         f"frame {frame}: invalid rectangle record")
                current = _apply_rects(previous, payload, rect_count, width, height)
            elif kind == ipvf.TYPE_REPEAT:
                _require(previous is not None and rect_count == 0 and
                         stored_size == 0 and decoded_size == 0,
                         f"frame {frame}: invalid repeat")
                current = previous
            elif kind == ipvf.TYPE_XOR_LZ4:
                _require(previous is not None and rect_count == 0 and
                         decoded_size == frame_bytes,
                         f"frame {frame}: invalid temporal record")
                current = (int.from_bytes(previous, "big") ^
                           int.from_bytes(payload, "big")).to_bytes(frame_bytes, "big")
            else:
                _require(previous is not None and rect_count == 0 and
                         decoded_size == frame_bytes,
                         f"frame {frame}: invalid motion record")
                dx, dy = struct.unpack_from("<bb", stored)
                prediction = ipvf.translate_frame(previous, dx, dy, width=width, height=height)
                current = (int.from_bytes(prediction, "big") ^
                           int.from_bytes(payload, "big")).to_bytes(frame_bytes, "big")

            _require(len(current) == frame_bytes,
                     f"frame {frame}: reconstructed size mismatch")
            if kind in (ipvf.TYPE_KEY, ipvf.TYPE_KEY_LZ4):
                keyframe_entries.append((
                    frame,
                    record_offset,
                    current_sectors,
                    ipvf.index_flags_for_kind(kind),
                ))
            if on_frame is not None:
                on_frame(frame, frame_count, current, decoded_audio)

            previous = current
            counts[TYPE_NAMES[kind]] += 1
            stored_video_total += stored_size
            audio_total += audio_size
            padding_total += record_size - used_size
            largest_record_sectors = max(largest_record_sectors, current_sectors)
            position += record_size
            current_sectors = next_sectors

        _require(current_sectors == 0, "record chain does not terminate")
        _require(position == media_end_offset,
                 "record chain does not end at media end offset")
        _require(calculated_media_id == media_id,
                 "media identity CRC mismatch")
        assert previous is not None
        final_crc = rockbox_crc32(previous)

        stream.seek(index_offset)
        index_data = stream.read(index_bytes)
        _require(len(index_data) == index_bytes, "truncated index")
        _require(rockbox_crc32(index_data) == index_crc,
                 "index CRC mismatch")

        parsed_index: list[tuple[int, int, int, int]] = []
        previous_frame = -1
        previous_offset = ipvf.DATA_OFFSET - 1
        for entry_number in range(index_count):
            entry_offset = entry_number * ipvf.INDEX_ENTRY_SIZE
            entry = struct.unpack_from("<IQHH", index_data, entry_offset)
            frame, offset, sectors, entry_flags = entry
            _require(entry_number != 0 or frame == 0,
                     "index must begin with frame 0")
            _require(frame > previous_frame,
                     f"index entry {entry_number}: frames are not monotonic")
            _require(offset > previous_offset,
                     f"index entry {entry_number}: offsets are not monotonic")
            _require(offset >= ipvf.DATA_OFFSET and
                     offset % ipvf.RECORD_SECTOR_SIZE == 0,
                     f"index entry {entry_number}: invalid record offset")
            _require(1 <= sectors <= max_record_sectors,
                     f"index entry {entry_number}: invalid record sectors")
            _require(offset + sectors * ipvf.RECORD_SECTOR_SIZE <=
                     media_end_offset,
                     f"index entry {entry_number}: record exceeds media")
            info = record_info.get(offset)
            _require(info is not None,
                     f"index entry {entry_number}: offset is not a record start")
            assert info is not None
            record_frame, record_kind, record_sectors = info
            _require(record_frame == frame,
                     f"index entry {entry_number}: frame identity mismatch")
            _require(record_kind in (ipvf.TYPE_KEY, ipvf.TYPE_KEY_LZ4),
                     f"index entry {entry_number}: not a keyframe record")
            _require(record_sectors == sectors,
                     f"index entry {entry_number}: sector identity mismatch")
            _require(entry_flags == ipvf.index_flags_for_kind(record_kind),
                     f"index entry {entry_number}: keyframe flags mismatch")
            parsed_index.append(entry)
            previous_frame = frame
            previous_offset = offset

        _require(parsed_index and parsed_index[0][0] == 0,
                 "index must begin with frame 0")
        _require(parsed_index == keyframe_entries,
                 "index does not enumerate every keyframe")

    return {
        "path": str(path),
        "file_bytes": file_size,
        "frames": frame_count,
        "fps": fps_num if fps_den == 1 else f"{fps_num}/{fps_den}",
        "fps_num": fps_num,
        "fps_den": fps_den,
        "width": width,
        "height": height,
        "duration_seconds": frame_count * fps_den / fps_num,
        "counts": dict(sorted(counts.items())),
        "stored_video_bytes": stored_video_total,
        "audio_bytes": audio_total,
        "audio_modes": dict(sorted(audio_modes.items())),
        "decoded_audio_crc": (
            f"{decoded_audio_crc:08x}" if verify_audio else None
        ),
        "padding_bytes": padding_total,
        "record_bytes": media_end_offset - ipvf.DATA_OFFSET,
        "max_record_sectors": largest_record_sectors,
        "final_crc": f"{final_crc:08x}",
        "source_verified": False,
        "media_end_offset": media_end_offset,
        "index_offset": index_offset,
        "index_count": index_count,
        "index_entry_size": index_entry_size,
        "index_crc": f"{index_crc:08x}",
        "media_id": f"{media_id:08x}",
        "index": [
            {
                "frame": frame,
                "offset": offset,
                "sectors": sectors,
                "flags": entry_flags,
            }
            for frame, offset, sectors, entry_flags in parsed_index
        ],
        "metadata": metadata,
    }
