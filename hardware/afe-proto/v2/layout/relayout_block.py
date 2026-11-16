"""One block at a time: python3 relayout_block.py DUMP.json OUT.json BLOCK TRIES ITERS [FROZEN.json ...]
Places every movable part of BLOCK (rows, pin lines, hard LR rows, labels) around the parts frozen in the FROZEN files ({"st": {ref: [x, y, rot, ls]}});
keeps the best attempt; violation 0 means every rule held, alignment included."""
import json, os, sys
import relayout_place as RP
dump, out, blk, tries, iters = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
frozen = {}
INIT = json.loads(os.environ['RP_INIT']) if 'RP_INIT' in os.environ else None
if os.environ.get('RP_START'):                                  # polish a previous result: its positions, rotations (as steps from the dump) and label shifts
    import relayout_place as _RP
    _D, _P = _RP.load(dump)
    INIT = {r: (v[0], v[1], int(round((v[2] - _P[r]['rot']) / 90.0)) % 4, v[3]) for r, v in json.load(open(os.environ['RP_START']))['st'].items()}
for f in sys.argv[6:]:
    frozen.update(json.load(open(f))['st'])
best = None
for t in range(tries):
    res, v = RP.run(dump, out + '.try', blk, seed=int(os.environ.get('RP_SEED0', 300)) + t, iters=iters, frozen=frozen, init={k: tuple(v) for k, v in (INIT or {}).items()})
    if best is None or v < best[0]:
        best = (v, res)
        json.dump(dict(st=res, viol=v, blk=blk), open(out, 'w'))
    if v < 0.06: break
print('best', blk, best[0])
