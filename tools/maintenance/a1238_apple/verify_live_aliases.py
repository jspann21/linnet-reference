"""Verify the planned Apple short paths and original long paths on the A1238."""
import json
from pathlib import Path


manifest = json.loads(Path('out/apple-link-probe/full-library-manifest.json').read_text(encoding='utf-8'))
rows = manifest['rows']
for row in rows:
    long_path = Path('F:/Music') / row['original']
    short_relative = row['apple_path'].split(':Music:', 2)[2].replace(':', '/')
    short_path = Path('F:/Music') / short_relative
    if not long_path.is_file() or long_path.stat().st_size != row['bytes']:
        raise ValueError(f'Missing or changed file: {long_path}')
    if not short_path.is_file() or short_path.stat().st_size != row['bytes']:
        raise ValueError(f'Apple alias cannot open the same-sized file: {short_path}')
print(json.dumps(dict(verified=len(rows), total_bytes=sum(row['bytes'] for row in rows))))
