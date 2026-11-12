"""Mutation proof for pcbtools.rules and pcbtools.fence: copy the package to a scratch dir, break one comparison / term /
constant at a time with a text edit, run the rule unit, equivalence and fence tests against the broken copy
(PCBTOOLS_ROOT points the suite at it) and require them to FAIL. The unmutated copy must pass first. Each child runs
with a 2 GB address-space limit. Output is recorded in tests/golden/rules_mutation_result.txt.

    python tests/pcbtools/mutate_rules.py        (exit 1 if any mutant survives or any pattern is not found exactly once)

Not mutated, on purpose: `e < 0.02` in pieces(): it is implied by the `< 0.05` end-to-line tests next to it (an end within
0.02 of an end is within 0.05 of the line), so no test can tell the two apart.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))              # hardware/afe-proto
SCR = os.path.join(ROOT, 'pcbtools', '.scratch', 'mutr')
TESTS = ['test_rules_synthetic.py', 'test_rules_equivalence.py', 'test_fence.py']

R, F, M = 'rules.py', 'fence.py', 'mutate.py'
MUTANTS = [
    # LR-1
    (R, 'LR-1 hop length: > becomes >=', "if L > cfg.HOP_MAX or nv > cfg.HOP_MAX_VIAS:", "if L >= cfg.HOP_MAX or nv > cfg.HOP_MAX_VIAS:"),
    (R, 'LR-1 hop vias: > becomes >=', "or nv > cfg.HOP_MAX_VIAS:", "or nv >= cfg.HOP_MAX_VIAS:"),
    (R, 'LR-1 layer count test changed', "if b.copper_layers != 2:", "if b.copper_layers != 4:"),
    (R, 'LR-1 plane pieces: != becomes >', "if pieces_n != 1:", "if pieces_n > 1:"),
    (R, 'LR-1 unfilled plane not reported', "        if not b.z_filled[z]:\n", "        if False:\n"),
    (R, 'LR-1 run join ignores the net', " & (net[pr[:, 0] % n] == net[pr[:, 1] % n])", ""),
    (R, 'LR-1 via of another net counted', "(b.v_net[vi] == net[ei % n])", "True"),
    (R, 'LR-1 under-part margin dropped', "hit = geom.seg_in_box(S, boxes, pad=cfg.ZONE_PAD + b.s_w[rows] / 2)", "hit = geom.seg_in_box(S, boxes, pad=b.s_w[rows] / 2)"),
    (R, 'LR-1 top-net crossing margin dropped', "close = D < (w[:, None] + b.s_w[trows][None, :]) / 2 + 0.1", "close = D < (w[:, None] + b.s_w[trows][None, :]) / 2"),
    (R, 'LR-1 pad crossing margin dropped', "pad=0.1 + w / 2)", "pad=0.1)"),
    (R, 'LR-1 GND via reach: <= becomes <', "d[i] <= 3.0", "d[i] < 3.0"),
    (R, 'LR-1 a ground via may serve many pads', "            used[i] = True\n", "            pass\n"),
    # LR-2
    (R, 'LR-2 x must fall strictly: > becomes >=', "all(x > y for x, y in", "all(x >= y for x, y in"),
    (R, 'LR-2 output run: <= becomes <', "if outl <= hiz:", "if outl < hiz:"),
    (R, 'LR-2 5 V pad distance: > becomes >=', "if d5 > 15:", "if d5 >= 15:"),
    (R, 'LR-2 BNC distance: < becomes <=', "if dj[j] < 50:", "if dj[j] <= 50:"),
    (R, 'LR-2 reference keep-out: < becomes <=', "if dref[r] < cfg.KEEPOUT:", "if dref[r] <= cfg.KEEPOUT:"),
    (R, 'LR-2 divider gap limit changed', "if gap < 5.0:", "if gap < 4.0:"),
    # LR-3
    (R, 'LR-3 length: > becomes >=', "if L > 14:", "if L >= 14:"),
    (R, 'LR-3 clearance changed', "lim = 0.6 + (", "lim = 0.5 + ("),
    (R, 'LR-3 own net counted as a neighbour', " & (b.s_net[ia][:, None] != b.s_net[ot][None, :])", ""),
    (R, 'LR-3 ground counted as a neighbour', "ot = np.flatnonzero((b.s_layer == 0) & (b.s_net != gnd))", "ot = np.flatnonzero((b.s_layer == 0))"),
    # LR-4
    (R, 'LR-4 output resistor: > becomes >=', "pad_c(b, *pinpad)))) > 5:", "pad_c(b, *pinpad)))) >= 5:"),
    (R, 'LR-4 decoupling: > becomes >=', "if d > 12:", "if d >= 12:"),
    (R, 'LR-4 FB length: > becomes >=', "if L > cfg.FB_MAX:", "if L >= cfg.FB_MAX:"),
    (R, 'LR-4 GND track reach changed', "if (D < 0.5).any():", "if (D < 0.3).any():"),
    (R, 'LR-4 pour probe -y dropped', "((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5))", "((0.5, 0), (-0.5, 0), (0, 0.5))"),
    (R, 'LR-4 pour probe +x dropped', "((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5))", "((-0.5, 0), (0, 0.5), (0, -0.5))"),
    (R, 'LR-4 pour holes ignored', "hole=b.z_ring_hole[r0:r1])", "hole=None)"),
    (R, 'LR-4 INV_MAX: > becomes >=', "if L > cfg.INV_MAX:", "if L >= cfg.INV_MAX:"),
    (R, 'LR-4 INV_MAX counts top copper only', "L = length_of(b, net, top_only=False)", "L = length_of(b, net)"),
    # LR-12
    (R, 'LR-12 decoupling: > becomes >=', "if d > cfg.DECOUP_MAX:", "if d >= cfg.DECOUP_MAX:"),
    (R, 'LR-12 supply pad choice dropped', "ks = [k for k in ('1', '2') if pad_net(b, cap, k) == net] or ['1']", "ks = ['1']"),
    # LR-5
    (R, 'LR-5 segment keep-out: < becomes <=', "for i in np.flatnonzero(d < cfg.KEEPOUT):", "for i in np.flatnonzero(d <= cfg.KEEPOUT):"),
    (R, 'LR-5 pad keep-out: < becomes <=', "        if d < cfg.KEEPOUT:\n            near.append(f'{b.nets[b.p_net[r]]} pad", "        if d <= cfg.KEEPOUT:\n            near.append(f'{b.nets[b.p_net[r]]} pad"),
    (R, 'LR-5 generator pads counted', "if k[0] in cfg.GENERATOR_BLOCK:", "if False:"),
    (R, 'LR-5 distance of an inside segment', "return np.where(geom.seg_in_box(S, np.asarray(bx, float)), 0.0, d)", "return d"),
    # connectivity: LR-6, LR-8
    (R, 'pieces: track-to-line reach changed', "T = (e < 0.02) | (D0 < 0.05) | (D1 < 0.05) | (D0.T < 0.05) | (D1.T < 0.05)", "T = (e < 0.02) | (D0 < 0.03) | (D1 < 0.03) | (D0.T < 0.03) | (D1.T < 0.03)"),
    (R, 'pieces: via-to-track reach changed', "geom.point_seg_dist(V, S) < 0.05", "geom.point_seg_dist(V, S) < 0.03"),
    (R, 'pieces: via-to-via reach changed', "np.triu(dv < 0.05, 1)", "np.triu(dv < 0.03, 1)"),
    (R, 'pieces: track-to-pad margin dropped', "pad=0.02)", "pad=0.0)"),
    (R, 'pieces: via-in-pad margin dropped', "(V[:, None, 0] <= PB[None, :, 2] + 0.02)", "(V[:, None, 0] <= PB[None, :, 2])"),
    (R, 'pieces: bridge pads not joined', "        if ia and ib:\n", "        if False:\n"),
    (R, 'LR-6 star pads not cut', "cut = list(cfg.STAR[net])", "cut = []"),
    (R, 'LR-6 one group per piece: > becomes >=', "if len(hit) > 1:\n                bad.append(f'{net}: one piece", "if len(hit) >= 1:\n                bad.append(f'{net}: one piece"),
    (R, 'LR-8 source pads not cut', "cut = {tuple(s.split('.')) for s in cfg.VREF_SOURCE}", "cut = set()"),
    # LR-7, LR-9, LR-11
    (R, 'LR-7 DAC0 length: > becomes >=', "if L > 12:", "if L >= 12:"),
    (R, 'LR-7 back-termination reach: > becomes >=', "if dr[r] > 16:", "if dr[r] >= 16:"),
    (R, 'LR-7 shell pads of any net counted', " & (b.p_net == nid(b, '/GND'))).sum())", ").sum())"),
    (R, 'LR-7 shell pad minimum lowered', "if shell < 3:", "if shell < 2:"),
    (R, 'LR-9 own parts not excused', "hit &= ~own", "hit &= hit"),
    (R, 'LR-9 courtyard margin dropped', "hit = geom.seg_in_box(segs(b)[rows], boxes, pad=cfg.ZONE_PAD + b.s_w[rows] / 2)", "hit = geom.seg_in_box(segs(b)[rows], boxes, pad=b.s_w[rows] / 2)"),
    (R, 'LR-11 outline membership test inverted', "if inside != want:", "if inside == want:"),
    (R, 'LR-11 designator height test inverted', "or b.r_h[k] < cfg.DESIGNATOR_MIN_H:", "or b.r_h[k] > cfg.DESIGNATOR_MIN_H:"),
    (R, 'LR-11 designators with two digits owned', "if len(digits) >= 3 else None", "if len(digits) >= 2 else None"),
    (R, 'LR-11 test point net test dropped', "or pad_net(b, r, '1') != n:", "or False:"),
    # fence
    (F, 'fence: a track is inside if ANY point is', ").all(axis=1)", ").any(axis=1)"),
    (F, 'fence: closed rectangle becomes open', "(X <= x1 + EPS)", "(X <= x1 - EPS)"),
    (F, 'fence: owner needs only one digit', "if len(d) >= 3 else None", "if len(d) >= 1 else None"),
    (F, 'fence: position tolerance widened', "> cfg.TOL_MM", "> 0.1"),
    (F, 'fence: rotation / side not compared', "or pa[r][2:] != pb[r][2:]", ""),
    (F, 'fence: B.Cu keyed as 3', "0 if code == 0 else 2 if code == 1 else 4", "0 if code == 0 else 3"),
    (F, 'fence: duplicate items not reported', "if len(kb) != len(ka) and sb == sa:", "if False:"),
    (F, 'fence: added copper not reported', "for k in sorted(sa - sb):", "for k in []:"),
    # the arms' vocabulary
    (M, 'arms: appended track layer swapped', "s_layer=0 if layer == 'F' else 1", "s_layer=0 if layer == 'B' else 1"),
    (M, 'arms: appended via loses its net', "v_drill=drill, v_net=net(b, netname))", "v_drill=drill, v_net=0)"),
]


def run(tag, edit):
    d = os.path.join(SCR, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    shutil.copytree(os.path.join(ROOT, 'pcbtools'), os.path.join(d, 'pcbtools'), ignore=shutil.ignore_patterns('.scratch', '__pycache__'))
    os.symlink(os.path.join(ROOT, 'tests'), os.path.join(d, 'tests'))            # boards/v2.py finds its fixtures relative to the package
    if edit:
        f, old, new = edit
        p = os.path.join(d, 'pcbtools', f)
        s = open(p).read()
        if s.count(old) != 1:
            return 'BAD-MUTANT (pattern found %d times)' % s.count(old)
        open(p, 'w').write(s.replace(old, new))

    def limit():
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', '-c', os.path.join(ROOT, 'tests', 'pytest.ini'),
                        *[os.path.join(HERE, t) for t in TESTS]], capture_output=True, text=True, cwd=ROOT, timeout=300, preexec_fn=limit,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PCBTOOLS_ROOT=d))
    tail = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:]
    return ('PASSED' if p.returncode == 0 else 'FAILED') + ' | ' + tail


def main():
    bad = []
    r = run('clean', None)
    print('unmutated copy:', r, flush=True)
    if not r.startswith('PASSED'):
        return 2
    for i, (f, name, old, new) in enumerate(MUTANTS):
        r = run(f'm{i}', (f, old, new))
        ok = r.startswith('FAILED')
        print(('caught   ' if ok else 'SURVIVED ') + name + '  [' + r + ']', flush=True)
        if not ok:
            bad.append(name)
    print(f'{len(MUTANTS)} mutants:', 'every mutant caught' if not bad else 'SURVIVORS: ' + '; '.join(bad), flush=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
