"""Prepare read-only Notes for the device's bounded ASCII display."""
from pathlib import Path
import hashlib
import struct
import json
import unicodedata
import os

MAX_NOTES = 256
TITLE = 64
LINES = 256
LINE = 32
RECORD = 4 + LINES * LINE
MAX_FILE = 16 + MAX_NOTES * (TITLE + RECORD)
EXTENSIONS = {'.txt', '.md', '.text'}


def _display_lines(text):
    # Fit the narrowest built-in list (Aurora), accounting for proportional
    # glyph widths in every bundled theme so switching themes loses no text.
    widths = [8] * 95
    for path in (Path(__file__).resolve().parents[2]/'sdk/assets').glob('font*.json'):
        font = json.loads(path.read_text(encoding='utf-8'))
        advances = font.get('advances', [font['advance']] * 95)
        widths = [max(a, b) for a, b in zip(widths, advances)]
    for paragraph in text.split('\n'):
        if not paragraph:
            yield ''
        while paragraph:
            length, pixels = 0, 0
            for char in paragraph[:31]:
                advance = widths[ord(char)-32]
                if pixels + advance > 140:
                    break
                pixels += advance
                length += 1
            end = length
            if length < len(paragraph):
                space = paragraph.rfind(' ', 0, length+1)
                if space > 0:
                    end = space
            yield paragraph[:end]
            paragraph = paragraph[end:].lstrip(' ')


def _ascii(text):
    text = text.translate(str.maketrans({'“': '"', '”': '"', '’': "'", '‘': "'", '—': '-', '–': '-', '…': '...'}))
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return normalized.encode('ascii', 'replace').decode('ascii')


def compile_notes(source, output):
    from .publish import _plain
    original_source = Path(os.path.abspath(source))
    _plain(original_source, Path(original_source.anchor))
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir():
        raise ValueError('Notes source must be a folder')
    if output.is_relative_to(source):
        raise ValueError('Stage the Notes package outside the source folder')
    files = sorted((p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: p.as_posix().casefold())
    if len(files) > MAX_NOTES:
        raise ValueError(f'Notes supports at most {MAX_NOTES} documents; found {len(files)}')
    titles, records, changed = bytearray(), bytearray(), []
    for path in files:
        _plain(path, source)
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError(f'Note links cannot escape or alias the source: {path}')
        if path.stat().st_size > 1024 * 1024:
            raise ValueError(f'Note is too large: {path}')
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ValueError(f'Note is too large: {path}')
        try:
            original = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        except UnicodeError as exc:
            raise ValueError(f'Note must be UTF-8 or BOM-marked UTF-16: {path}') from exc
        text = _ascii(original).replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
        text = ''.join(c if c == '\n' or 32 <= ord(c) <= 126 else '?' for c in text)
        title = _ascii(path.relative_to(source).with_suffix('').as_posix())
        title = ''.join(c if 32 <= ord(c) <= 126 else '?' for c in title)
        if len(title) > 63:
            raise ValueError(f'Note title exceeds 63 display characters: {path}')
        lines = list(_display_lines(text))
        if len(lines) > LINES:
            raise ValueError(f'Note exceeds {LINES} display lines; split it into smaller documents: {path}')
        if any(ord(c) > 127 for c in original + path.relative_to(source).as_posix()):
            changed.append(path.relative_to(source).as_posix())
        titles += title.encode('ascii').ljust(TITLE, b'\0')
        record = struct.pack('<I', len(lines)) + b''.join(line.encode('ascii').ljust(LINE, b'\0') for line in lines)
        records += record.ljust(RECORD, b'\0')
    data = struct.pack('<4sIII', b'NNT1', 1, len(files), RECORD) + titles + records
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    report = inspect(output)
    report.update(source=str(source), ascii_converted=changed, note='Prepared ASCII display copies; original documents are unchanged.')
    return report


def inspect(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Notes package is too large')
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError('Notes header is missing')
    magic, version, count, record = struct.unpack_from('<4sIII', data)
    if magic != b'NNT1' or version != 1 or count > MAX_NOTES or record != RECORD or len(data) != 16 + count * (TITLE + RECORD):
        raise ValueError('Invalid Notes package')
    def string(raw):
        if 0 not in raw or any(c and not 32 <= c <= 126 for c in raw):
            raise ValueError('Invalid Notes display text')
    for index in range(count):
        string(data[16+index*TITLE:16+(index+1)*TITLE])
        offset = 16 + count*TITLE + index*RECORD
        lines = struct.unpack_from('<I', data, offset)[0]
        if not 1 <= lines <= LINES:
            raise ValueError('Invalid Notes line count')
        for line in range(LINES):
            string(data[offset+4+line*LINE:offset+4+(line+1)*LINE])
    return dict(package=str(path), notes=count, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
