"""Disposable object cache with compiler-reported dependency sets.

The first compile records all dependencies selected by the effective flags.
Later builds hash those same files before object reuse. A changed include graph
changes a parent dependency and forces a fresh compile and dependency record.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


MAX_OBJECT_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 1024 * 1024 * 1024


def _dependencies(path):
    data = path.read_text(encoding='utf-8').replace('\\\n', '')
    if not data.startswith('cache:'):
        raise ValueError('compiler dependency output has an unexpected target')
    result, word, index = [], [], 6
    while index < len(data):
        char = data[index]
        if char == '\\' and index + 1 < len(data) and data[index + 1] in (' ', '\\', '#'):
            word.append(data[index + 1])
            index += 2
            continue
        if char.isspace():
            if word:
                result.append(''.join(word))
                word = []
        else:
            word.append(char)
        index += 1
    if word:
        result.append(''.join(word))
    if not result:
        raise ValueError('compiler returned no source dependencies')
    return result


def _identity(path, root, generated):
    path = path.resolve(strict=True)
    if path.is_relative_to(generated):
        return 'generated/' + path.relative_to(generated).as_posix()
    if path.is_relative_to(root):
        return 'source/' + path.relative_to(root).as_posix()
    return 'external/' + path.as_posix()


def _path(identity, root, generated):
    if identity.startswith('generated/'):
        return generated / identity[len('generated/'):]
    if identity.startswith('source/'):
        return root / identity[len('source/'):]
    if identity.startswith('external/'):
        return Path(identity[len('external/'):])
    raise ValueError('invalid object dependency identity')


def _base_key(command, source, root, generated, compiler_sha256):
    flags = [str(value).replace(str(generated), '<generated>')
             for value in command[1:-4]]
    source_name = _identity(source, root, generated)
    return hashlib.sha256(json.dumps([compiler_sha256, flags, source_name],
        separators=(',', ':')).encode()).hexdigest()


def _hash_file(path):
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError(f'build dependency changed while hashing: {path}')
    return checksum


def _fingerprints(values, root, generated):
    result = {}
    for value in values:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        identity = _identity(path, root, generated)
        if identity not in result:
            result[identity] = _hash_file(path)
    return result


def _restore(directory, output, root, generated, source_name):
    for manifest in directory.glob('*.json'):
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                continue
            dependencies = data.get('dependencies')
            if (not isinstance(dependencies, dict) or source_name not in dependencies or
                    any(_hash_file(_path(name, root, generated)) != checksum
                        for name, checksum in dependencies.items())):
                continue
            path = manifest.with_suffix('.bin')
            if not path.is_file() or not 1 <= path.stat().st_size <= MAX_OBJECT_BYTES:
                continue
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != data.get('object_sha256'):
                continue
            output.write_bytes(payload)
            os.utime(manifest, None)
            os.utime(path, None)
            return True
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return False


def _atomic_bytes(path, payload):
    fd, name = tempfile.mkstemp(prefix=path.stem + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(name, path)
    finally:
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            pass


def _save(directory, dependencies, output):
    try:
        if output.stat().st_size > MAX_OBJECT_BYTES:
            return
        payload = output.read_bytes()
        if len(payload) > MAX_OBJECT_BYTES:
            return
        checksum = hashlib.sha256(json.dumps(dependencies, sort_keys=True).encode()).hexdigest()
        path = directory / checksum
        directory.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(path.with_suffix('.bin'), payload)
        manifest = dict(dependencies=dependencies,
                        object_sha256=hashlib.sha256(payload).hexdigest())
        _atomic_bytes(path.with_suffix('.json'), json.dumps(manifest, sort_keys=True).encode())
    except OSError:
        pass  # A host cache failure does not invalidate the compiled object.


def compile_object(command, root, generated, compiler_sha256, cache_root, run):
    """Return whether a validated cached object replaced a compiler invocation."""
    source, output = Path(command[-3]), Path(command[-1])
    source_name = _identity(source, root, generated)
    base = _base_key(command, source, root, generated, compiler_sha256)
    directory = cache_root / base[:2] / base
    if _restore(directory, output, root, generated, source_name):
        return True
    dependency_file = output.with_suffix(output.suffix + '.d')
    try:
        # On a miss, bracket code generation with dependency snapshots. A
        # concurrent header edit must not be published under the later bytes.
        run([*command[:-4], '-M', '-MT', 'cache', '-MF', dependency_file, source])
        before = _fingerprints(_dependencies(dependency_file), root, generated)
        run([*command, '-MD', '-MT', 'cache', '-MF', dependency_file])
        dependencies = _fingerprints(_dependencies(dependency_file), root, generated)
        if source_name not in dependencies:
            raise ValueError(f'compiler dependency output omitted source: {source}')
        if before != dependencies:
            raise RuntimeError(f'build dependency changed while compiling: {source}')
        _save(directory, dependencies, output)
    finally:
        dependency_file.unlink(missing_ok=True)
    return False


def trim(cache_root):
    """Remove oldest disposable versions only after an invocation has linked."""
    try:
        entries = [(path, path.stat()) for path in cache_root.glob('*/*/*.bin')]
        total = sum(info.st_size for _, info in entries)
        for path, info in sorted(entries, key=lambda item: item[1].st_mtime_ns):
            if total <= MAX_CACHE_BYTES:
                break
            try:
                path.unlink()
                path.with_suffix('.json').unlink(missing_ok=True)
                total -= info.st_size
            except OSError:
                pass
    except OSError:
        pass
