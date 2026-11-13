import re, sys, collections
sys.path.insert(0, '/work/hardware/afe-proto/kicad')
import design
jl = [p for p in design.PARTS if p['fitted_by'] == 'JLC' and not p['dnp']]
cnt = collections.Counter(p['lcsc'] for p in jl)
refs = collections.defaultdict(list)
for p in jl: refs[p['lcsc']].append(p['ref'])
print('design JLC placements', len(jl), 'types', len(cnt))
txt = open('/work/hardware/afe-proto/bom/v1/bom.txt').read()
bom = {}
for m in re.finditer(r'^\s*\d+\s+(.+?)\s+(C\d+)\s+(Basic|Extended)\s+.*?\s(\d+)\s+[\d.]+\s+[\d.]+\s*$', txt, re.M):
    bom[m.group(2)] = int(m.group(4))
print('bom.txt types', len(bom), 'sum qty', sum(bom.values()))
for k in sorted(set(cnt) | set(bom)):
    if cnt.get(k, 0) != bom.get(k, 0): print('DIFF', k, 'design', cnt.get(k, 0), 'bom', bom.get(k, 0), sorted(refs.get(k, []))[:30])
print('0Rb', len(refs['C21189']), sorted(refs['C21189']))
for p in jl:
    if p['lcsc'] == 'C21189': print(p['ref'], p['pins'], p['block'])
