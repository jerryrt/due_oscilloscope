"""LR-11: number the v1 reference designators by functional block (1xx CH1, 2xx CH2, 3xx AWG, 4xx POWER, 5xx REFCAL, 6xx edge).

    python3 -I renumber.py            print the old -> new map (stdout) and write renumber_map.json
    python3 -I renumber.py --apply    rewrite the designators in the sources named in FILES, once, from the map

The map is generated from design.py's blocks, never typed: within a block the parts keep their old order, so the
numbers inside a hundred follow the old ones.  --apply is idempotent only on the old names: run it once on a tree that
still carries them (renumber_map.json then records what was done).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

HUNDRED = {'ch1': 1, 'ch2': 2, 'awg': 3, 'power': 4, 'cal': 5, 'due': 6}
# bridges belong to the block that owns the net they carry (the spec lead, with v2): VREF D2 spur -> REFCAL,
# AWG_BNC sense -> AWG, the scope's +3V3A branch -> the scope (CH1 series, with the shared dual)
BLOCK_OVERRIDE = {'R98': 'cal', 'R100': 'cal', 'R97': 'awg', 'R102': 'awg', 'R103': 'ch1', 'R104': 'ch1'}
FILES = ['design.py', 'layout.py', 'build_pcb.py', 'build_sch.py', 'check.py', 'route.py', 'lr_check.py', 'pcb_mutate.py',
         'floorplan.py', 'layout_view.py', '../whatif/bom.txt', '../whatif/bom.md']


def split(ref):
    m = re.fullmatch(r'([A-Z]+)(\d+)', ref)
    return m.group(1), int(m.group(2))


def build():
    blk = {p['ref']: BLOCK_OVERRIDE.get(p['ref'], p['block']) for p in design.PARTS}
    new, used = {}, {}
    for ref in sorted(blk, key=lambda r: (split(r)[0], split(r)[1])):
        pre, n = split(ref)
        h = HUNDRED[blk[ref]]
        k = used.get((pre, h), 0) + 1
        used[(pre, h)] = k
        new[ref] = f'{pre}{h}{k:02d}'
    assert len(set(new.values())) == len(new), 'duplicate new designators'
    return new, blk


def apply(new, files):
    # longest names first and word-bounded, so R10 never eats R100; one pass through a placeholder avoids chains
    names = sorted(new, key=len, reverse=True)
    pat = re.compile(r'(?<![A-Za-z0-9_])(' + '|'.join(names) + r')(?![A-Za-z0-9_])')
    for f in files:
        p = HERE / f
        if not p.exists():
            continue
        t = p.read_text()
        t2 = pat.sub(lambda m: new[m.group(1)], t)
        if t2 != t:
            p.write_text(t2)
            print('rewrote', f, sum(1 for _ in pat.finditer(t)), 'names')


if __name__ == '__main__':
    new, blk = build()
    if '--apply' in sys.argv:
        apply(new, FILES)
        (HERE / 'renumber_map.json').write_text(json.dumps({'map': new, 'block': blk}, indent=1))
    else:
        for k in sorted(new, key=lambda r: (new[r])):
            print(f'{k:6s} -> {new[k]:6s} {blk[k]}')
        print(len(new), 'parts')
