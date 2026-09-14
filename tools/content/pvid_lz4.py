"""Independent raw LZ4 blocks for bounded PVID RGB565 frames.

No LZ4 frame wrapper, dictionary or optional decoded-size inference is used.
Decoded input/output is bounded by the supported target framebuffer size.
The encoder may return a slightly larger literal block; callers retain raw
records unless compression saves sectors.
"""
from collections import deque

MAX_BYTES = 131072 * 2


def compress(data):
    """Deterministic, bounded 32-candidate matching with standard LZ4 tails."""
    data = bytes(data)
    size = len(data)
    if not 1 <= size <= MAX_BYTES:
        raise ValueError('invalid LZ4 source size')
    chains, output = {}, bytearray()
    anchor = position = 0

    def remember(at):
        if at + 4 <= size:
            chains.setdefault(data[at:at+4], deque(maxlen=32)).append(at)

    def match(at):
        best, distance = 3, 0
        if at + 12 > size:
            return 0, 0
        for prior in reversed(chains.get(data[at:at+4], ())):
            offset = at - prior
            if offset <= 0 or offset > 65535:
                continue
            length = 4
            while at + length < size - 5 and data[prior+length] == data[at+length]:
                length += 1
            if length > best:
                best, distance = length, offset
            if at + length == size - 5:
                break
        return (best, distance) if distance else (0, 0)

    def extension(length):
        if length >= 15:
            length -= 15
            while length >= 255:
                output.append(255)
                length -= 255
            output.append(length)

    while position + 12 <= size:
        length, offset = match(position)
        remember(position)
        if not length:
            position += 1
            continue
        next_length, _ = match(position + 1)
        if next_length > length + 1:
            position += 1
            continue
        literals = position - anchor
        output.append((min(literals, 15) << 4) | min(length - 4, 15))
        extension(literals)
        output.extend(data[anchor:position])
        output.extend(offset.to_bytes(2, 'little'))
        extension(length - 4)
        for at in range(position + 1, position + length):
            remember(at)
        position += length
        anchor = position
    literals = size - anchor
    output.append(min(literals, 15) << 4)
    extension(literals)
    output.extend(data[anchor:])
    return bytes(output)


def decompress(data, expected_size):
    """Reject malformed, noncanonical or out-of-bounds independent blocks.

    Compressed input is capped at MAX_BYTES. compress() can return a larger
    literal block for caller rejection; the PVID packer applies its stricter
    record-size savings gate before invoking this decoder.
    """
    if not data or not 1 <= expected_size <= MAX_BYTES or len(data) > MAX_BYTES:
        raise ValueError('invalid LZ4 bounds')
    position, output, last_match = 0, bytearray(), None

    def length(nibble):
        nonlocal position
        value = nibble
        if value == 15:
            while True:
                if position >= len(data):
                    raise ValueError('truncated LZ4 length')
                extra = data[position]
                position += 1
                value += extra
                if value > expected_size:
                    raise ValueError('oversized LZ4 length')
                if extra != 255:
                    break
        return value

    while position < len(data):
        token = data[position]
        position += 1
        literals = length(token >> 4)
        if literals > len(data)-position or literals > expected_size-len(output):
            raise ValueError('invalid LZ4 literal bounds')
        output.extend(data[position:position+literals])
        position += literals
        if position == len(data):
            if not literals or (expected_size >= 5 and literals < 5):
                raise ValueError('invalid LZ4 terminal literals')
            if len(output) != expected_size:
                raise ValueError('LZ4 decoded size mismatch')
            if last_match is not None and expected_size-last_match < 12:
                raise ValueError('invalid LZ4 terminal match')
            return bytes(output)
        if len(data)-position < 2:
            raise ValueError('truncated LZ4 offset')
        offset = int.from_bytes(data[position:position+2], 'little')
        position += 2
        count = length(token & 15) + 4
        if not offset or offset > len(output) or count > expected_size-len(output):
            raise ValueError('invalid LZ4 match bounds')
        last_match = len(output)
        while count:
            chunk = min(offset, count)
            start = len(output)-offset
            output.extend(output[start:start+chunk])
            count -= chunk
    raise ValueError('missing LZ4 terminal sequence')
