"""Prepare read-only Notes for the device's bounded ASCII display."""
from pathlib import Path
from itertools import islice
import hashlib
import struct
import json
import tomllib
import unicodedata
import os
import tempfile
from . import SourceError

MAX_NOTES = 256
TITLE = 64
LINES = 256
LINE = 32
RECORD = 4 + LINES * LINE
MAX_FILE = 16 + MAX_NOTES * (TITLE + RECORD)
EXTENSIONS = {'.txt', '.md', '.text'}


def _display_widths():
    # Fit the narrowest built-in list (Aurora), accounting for proportional
    # glyph widths in every bundled theme so switching themes loses no text.
    widths = [8] * 95
    root = Path(__file__).resolve().parents[2]
    paths = set()
    for manifest in (root/'themes').glob('*/theme.toml'):
        theme = tomllib.loads(manifest.read_text(encoding='utf-8'))['theme']
        paths.add((manifest.parent/theme.get('font', '../../sdk/assets/font.json')).resolve())
    for path in paths:
        font = json.loads(path.read_text(encoding='utf-8'))
        advances = font.get('advances', [font['advance']] * 95)
        widths = [max(a, b) for a, b in zip(widths, advances)]
    return widths


def _display_lines(text, widths=None):
    if widths is None:
        widths = _display_widths()
    for paragraph in text.split('\n'):
        if not paragraph:
            yield ''
            continue
        start, stop = 0, len(paragraph)
        while start < stop:
            length, pixels = 0, 0
            for char in paragraph[start:start+31]:
                advance = widths[ord(char)-32]
                if pixels + advance > 140:
                    break
                pixels += advance
                length += 1
            end = start + length
            if end < stop:
                space = paragraph.rfind(' ', start, end+1)
                if space > start:
                    end = space
            yield paragraph[start:end]
            start = end
            while start < stop and paragraph[start] == ' ':
                start += 1


def _ascii(text):
    if text.isascii():
        return text
    text = text.translate(str.maketrans({'“': '"', '”': '"', '’': "'", '‘': "'", '—': '-', '–': '-', '…': '...'}))
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return normalized.encode('ascii', 'replace').decode('ascii')


def compile_notes(source, output, *, excluded=None):
    from .publish import _plain
    original_source = Path(os.path.abspath(source))
    _plain(original_source, Path(original_source.anchor))
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir():
        raise ValueError('Notes source must be a folder')
    if output.is_relative_to(source):
        raise ValueError('Stage the Notes package outside the source folder')
    excluded = {Path(value).as_posix().casefold() for value in (excluded or ())}
    files = sorted((p for p in source.rglob('*')
                    if p.suffix.lower() in EXTENSIONS
                    and p.relative_to(source).as_posix().casefold() not in excluded and p.is_file()),
                   key=lambda p: p.as_posix().casefold())
    if len(files) > MAX_NOTES:
        raise ValueError(f'Notes supports at most {MAX_NOTES} documents; found {len(files)}')
    titles, records, changed = bytearray(), bytearray(), []
    widths = _display_widths()
    for path in files:
        _plain(path, source)
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError(f'Note links cannot escape or alias the source: {path}')
        if path.stat().st_size > 1024 * 1024:
            raise SourceError(f'Note is too large: {path}', path)
        with path.open('rb') as reader:
            raw = reader.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise SourceError(f'Note is too large: {path}', path)
        try:
            original = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        except UnicodeError as exc:
            raise SourceError(f'Note must be UTF-8 or BOM-marked UTF-16: {path}', path) from exc
        text = _ascii(original).replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
        text = ''.join(c if c == '\n' or 32 <= ord(c) <= 126 else '?' for c in text)
        title = _ascii(path.relative_to(source).with_suffix('').as_posix())
        title = ''.join(c if 32 <= ord(c) <= 126 else '?' for c in title)
        if len(title) > 63:
            raise SourceError(f'Note title exceeds 63 display characters: {path}', path)
        lines = list(islice(_display_lines(text, widths), LINES + 1))
        if len(lines) > LINES:
            raise SourceError(f'Note exceeds {LINES} display lines; split it into smaller documents: {path}', path)
        if not original.isascii() or not path.relative_to(source).as_posix().isascii():
            changed.append(path.relative_to(source).as_posix())
        titles += title.encode('ascii').ljust(TITLE, b'\0')
        record = struct.pack('<I', len(lines)) + b''.join(line.encode('ascii').ljust(LINE, b'\0') for line in lines)
        records += record.ljust(RECORD, b'\0')
    data = struct.pack('<4sIII', b'NOTE', 0, len(files), RECORD) + titles + records
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=output.name+'.', suffix='.tmp', dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        report = inspect(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    report['package'] = str(output)
    report.update(source=str(source), ascii_converted=changed, note='Prepared ASCII display copies; original documents are unchanged.')
    return report


def inspect(path):
    path = Path(path)
    with path.open('rb') as reader:
        size = os.fstat(reader.fileno()).st_size
        if size > MAX_FILE:
            raise ValueError('Notes package is too large')
        data = reader.read(size + 1)
        if len(data) != size:
            raise ValueError('Notes package changed while reading')
    if len(data) < 16:
        raise ValueError('Notes header is missing')
    magic, reserved, count, record = struct.unpack_from('<4sIII', data)
    if magic != b'NOTE' or reserved or count > MAX_NOTES or record != RECORD or len(data) != 16 + count * (TITLE + RECORD):
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
