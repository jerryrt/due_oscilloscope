"""Rewrite tests/golden/MANIFEST.sha256 (sha256sum format, paths relative to this folder).

    python tests/golden/update_manifest.py --i-changed-a-golden

A golden is a recorded fact about the OLD tools: changing one silently turns an equivalence test into a lie.
So the manifest is committed, tests/pcbtools/test_golden_manifest.py fails on any difference, and this script refuses to
run without the flag. Add, change or delete a golden, run this, and commit both in the same commit.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, 'MANIFEST.sha256')
FLAG = '--i-changed-a-golden'


def golden_files(root=HERE):
    """every golden file, relative with '/' separators, sorted; the manifest itself and bytecode are not goldens"""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/')
            if rel == 'MANIFEST.sha256' or f.endswith('.pyc'):
                continue
            out.append(rel)
    return sorted(out)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def render(root=HERE):
    return ''.join(f'{digest(os.path.join(root, rel))}  {rel}\n' for rel in golden_files(root))


def read_manifest(path=MANIFEST):
    """-> {relative path: sha256}"""
    out = {}
    for ln in open(path).read().splitlines():
        if ln.strip():
            h, rel = ln.split('  ', 1)
            out[rel] = h
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != [FLAG]:
        print(f'refused: this rewrites the committed record of the old tools. Pass {FLAG} if you did change a golden, '
              'and commit the manifest with it.', file=sys.stderr)
        return 2
    text = render()
    with open(MANIFEST, 'w') as f:
        f.write(text)
    print(f'wrote {MANIFEST}: {len(text.splitlines())} files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
