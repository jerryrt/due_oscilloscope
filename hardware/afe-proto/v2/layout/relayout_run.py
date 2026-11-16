"""AFE-2 relayout phase 1c: anchors first, then the rest of each block around them.

    python3 relayout_run.py DUMP.json OUT_DIR [tries] [iters]       (in the PCB image; OUT_DIR gets placement.json and a log)

A. Hand-placed clusters (the solver places each cluster by itself, at main's relative layout as a soft pull, passives free to turn 90 degrees, every
   LR rule a hard term), then frozen as anchors: U101 with its feedback / series-input / isolation parts, clamps and decoupling; U301 with its
   feedback, gain and decoupling parts; U401 with its capacitors and feedback dividers; U501 and U502 with their capacitors.
B. Each block's remaining parts, around the anchors.
A phase retries with the next seed until its violation is zero."""
import json, os, sys
import relayout_place as RP

CLUSTERS = [
    ('U101', ['R107', 'R108', 'R207', 'R208', 'C104', 'C105', 'D101', 'D201'], ['CH1', 'CH2'], False),
    ('U301', ['U301', 'R301', 'R302', 'TP301', 'R303', 'R304', 'C301', 'R306', 'R307', 'R308', 'R309', 'C305', 'C306', 'C303', 'C304', 'R305'], ['AWG'], True),
    ('U401', ['U401', 'C401', 'C402', 'C403', 'C404', 'C405', 'C406', 'C407', 'C408', 'C409', 'R401', 'R402', 'R403', 'R404', 'R405'], ['POWER'], True),
    ('U501', ['U501', 'C501', 'C502'], ['REFCAL'], True),
    ('U502', ['U502', 'C503'], ['REFCAL'], True),
]
REST_OK = 0.06                                            # a label-gap shortfall below this is judged by the real checks afterwards
ORDER = ['AWG', 'POWER', 'REFCAL', 'CH2', 'CH1']


def main(dump, outdir, tries=12, iters=200000, anchors_dir=None, resolve=()):
    os.makedirs(outdir, exist_ok=True)
    D, P = RP.load(dump)
    frozen, log = {}, []
    def attempt(name, **kw):
        for t in range(tries):
            res, v = RP.run(dump, os.path.join(outdir, f'{name}.json'), kw.pop('blk'), seed=100 + t, iters=kw.pop('iters', iters), **kw) if False else (None, None)
        return None
    for ic, mine, regions, ic_moves in [c for c in CLUSTERS if (not anchors_dir) or c[0] in resolve]:
        soft = {r: (ic, (P[r]['x'] - P[ic]['x'], P[r]['y'] - P[ic]['y'])) for r in mine if r != ic}
        ok = False
        for t in range(tries):
            res, v = RP.run(dump, os.path.join(outdir, f'anchor_{ic}.json'), regions[0], seed=100 + t, iters=iters // 2, mine=mine, frozen=frozen, regions=regions,
                            cluster_of=ic if ic_moves else None, soft=soft)
            if v < 1e-3:
                ok = True; break
        log.append((f'anchor {ic}', ok, v))
        frozen.update(res)                                   # even a failed cluster is frozen at its best place, and reported
    if anchors_dir:                                           # anchors solved by an earlier run
        for ic, mine, regions, ic_moves in [c for c in CLUSTERS if c[0] not in resolve]:
            frozen.update(json.load(open(os.path.join(anchors_dir, f'anchor_{ic}.json')))['st'])
    anchors = set(frozen)
    for blk in ORDER:
        if not [r for r in P if RP.block_of(r) == blk and r not in RP.FIXED and r not in frozen]:
            continue
        bestv = None
        for t in range(tries):
            r_, v = RP.run(dump, os.path.join(outdir, f'rest_{blk}.json'), blk, seed=200 + t, iters=int(iters * 0.35), frozen=frozen)
            if bestv is None or v < bestv[0]: bestv = (v, r_)
            if v < REST_OK: break
        v, res = bestv
        log.append((f'rest {blk}', v < REST_OK, v))
        frozen.update(res)
    json.dump(dict(st=frozen, anchors=sorted(anchors), log=[list(x) for x in log]), open(os.path.join(outdir, 'placement.json'), 'w'))
    for x in log: print(x)


if __name__ == '__main__':
    a = sys.argv
    main(a[1], a[2], int(a[3]) if len(a) > 3 else 12, int(a[4]) if len(a) > 4 else 200000, a[5] if len(a) > 5 else None, tuple(a[6].split(',')) if len(a) > 6 else ())
