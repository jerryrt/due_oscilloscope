"""netdiff BOARD: the board's parts and pad nets against kicad/design.py (pcbtools.boards.v1.PARTS). Prints 'netdiff N' where N is the
number of differences: parts on one side only, pads whose net differs, netless pads of a part that has a net in the design."""
import sys
from pcbtools import boardio
from pcbtools.boards import v1
b = boardio.read_board(sys.argv[1])
want = {}
for p in v1.PARTS:
    for pin, net in p['pins'].items():
        want[(p['ref'], str(pin))] = v1._n(net) if hasattr(v1, '_n') else '/' + net
have = {}
for j in range(len(b.p_fp)):
    have[(b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j]))] = b.nets[int(b.p_net[j])]
refs_w = {p['ref'] for p in v1.PARTS if not p['ref'].startswith('MH')}; refs_h = {k[0] for k in have if not k[0].startswith(('MH',))}
bad = []
bad += [f'part only in design: {r}' for r in sorted(refs_w - refs_h)]
bad += [f'part only on board: {r}' for r in sorted(refs_h - refs_w)]
for k, n in sorted(want.items()):
    if k[0] not in refs_h: continue
    h = have.get(k)
    if h is None: bad.append(f'{k[0]}.{k[1]}: pad missing on the board (design {n})')
    elif h != n:
        bad.append(f'{k[0]}.{k[1]}: board {h!r} design {n!r}' + (' (netless)' if not h else ''))
for x in bad[:40]: print(' ', x)
print('netdiff', len(bad))
sys.exit(1 if bad else 0)
