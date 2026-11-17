import sys, json, collections
sys.path.insert(0, 'v2/kicad')
import design as D
P = json.load(open('v2/layout/scratch-outputs/relayout-mock/hand/pads.json'))
board = {}                                   # (ref, pin) -> net
for p in P:
    n = p['net'].lstrip('/') if p['net'] else ''
    board[(p['ref'], p['pin'])] = '' if n.startswith('unconnected-') else n
design = {}
for p in D.PARTS:
    for pin, net in p['pins'].items(): design[(p['ref'], pin)] = net
brefs = {r for r, _ in board}; drefs = {p['ref'] for p in D.PARTS}
BRN = {'3V3A_K', '3V3A_S', '3V3A_U', '3V3A_R', 'VNEG_G', 'AWG_BNC_L', 'AWG_BNC_M', 'VREF_M', 'VREF_P', 'TAP4_A', 'SNS_B_N', 'SCL_A', 'SDA_A'}
BRN = {'+' + n if n.startswith('3V3') else n for n in BRN}
only_b = sorted(brefs - drefs); only_d = sorted(drefs - brefs)
print('parts on the board:', len(brefs), ' in design.py:', len(drefs))
print('only on the board (%d):' % len(only_b), only_b)
print('only in design.py (%d):' % len(only_d), only_d)
# per pin differences for parts on both sides
diff = []
for k in sorted(set(board) | set(design)):
    r, pin = k
    if r not in brefs or r not in drefs: continue
    b, d = board.get(k), design.get(k)
    if (b or None) != (d or None): diff.append((r, pin, b, d))
print('pins on parts present in both whose net differs:', len(diff))
def is_bridge(item):
    r, pin, b, d = item
    return b in BRN or d in BRN or r.startswith('BR')
cat = collections.Counter()
out = collections.defaultdict(list)
for it in diff:
    r, pin, b, d = it
    if is_bridge(it): c = 'bridge net on one side'
    elif b == '' and d is None: continue
    elif b is None: c = 'pin absent on the board'
    elif d is None: c = 'pin absent in design.py'
    else: c = 'other'
    cat[c] += 1; out[c].append(it)
print(dict(cat))
for c, v in out.items():
    print('---', c, len(v))
    for it in v[:60]: print('   ', it)
# net-level: nets whose pad set differs
def nets_of(m):
    n = collections.defaultdict(set)
    for (r, pin), net in m.items():
        if net: n[net].add((r, pin))
    return n
nb, nd = nets_of({k: v for k, v in board.items() if k[0] in drefs & brefs}), nets_of({k: v for k, v in design.items() if k[0] in drefs & brefs})
names = sorted(set(nb) | set(nd))
differ = [n for n in names if nb.get(n, set()) != nd.get(n, set())]
print('nets (restricted to parts on both sides):', len(names), ' pad set differs:', len(differ))
print('   of which a bridge net name:', sum(1 for n in differ if n in BRN), '; board-only names:', sorted(set(nb) - set(nd))[:30], '; design-only names:', sorted(set(nd) - set(nb))[:30])
