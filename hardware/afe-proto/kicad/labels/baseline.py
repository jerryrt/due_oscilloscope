import sys, collections
sys.path.insert(0, '.')
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
path = sys.argv[1]
b = boardio.read_board(path)
txt = open(path).read()
keys = silkread.read_keys(txt)
f = silkread.findings(b, keys, {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}, {}, {})
print('findings', len(f))
kinds = collections.Counter(x.split(':')[1].split()[0] if ':' in x else x for x in f)
print(kinds.most_common(8))
for x in f[:12]: print('  ', x[:150])
print('keys', len(keys))
bd = pcbnew.LoadBoard(path); mm = pcbnew.ToMM
n_ref_silk = 0; fpitems = collections.Counter()
for fp in bd.GetFootprints():
    r = fp.Reference()
    if r.GetLayer() == pcbnew.F_SilkS and r.IsVisible(): n_ref_silk += 1
    for it in fp.GraphicalItems():
        fpitems[(it.GetLayerName(), it.GetClass())] += 1
print('visible F.SilkS designators', n_ref_silk, 'of', len(list(bd.GetFootprints())))
print([(k, v) for k, v in fpitems.items() if 'Silk' in k[0]])
bi = collections.Counter((d.GetLayerName(), d.GetClass()) for d in bd.GetDrawings() if 'Silk' in d.GetLayerName())
print('board silk drawings', dict(bi))
