"""refresh_manifest.py FIXTURE_DIR: rewrite MANIFEST.json's file table from the directory (adding or removing files is a
deliberate act: run this, review the diff). Source branch, commit and the notes are kept as they are."""
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
m = json.loads((root / 'MANIFEST.json').read_text())
files = {}
for p in sorted(root.rglob('*')):
    if p.is_file() and p.name != 'MANIFEST.json' and '__pycache__' not in p.parts and p.suffix != '.pyc':
        files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
m['files'] = files
(root / 'MANIFEST.json').write_text(json.dumps(m, indent=1) + '\n')
print(len(files), 'files')
