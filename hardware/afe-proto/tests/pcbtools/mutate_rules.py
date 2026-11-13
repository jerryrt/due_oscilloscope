"""Mutation proof for pcbtools.rules and pcbtools.fence: copy the package to a scratch dir, break one comparison / term /
constant at a time with a text edit, run the rule unit, equivalence and fence tests against the broken copy
(PCBTOOLS_ROOT points the suite at it) and require them to FAIL. The unmutated copy must pass first. Each child runs
with a 2 GB address-space limit. The first record is tests/golden/rules_mutation_result.txt (protected); the record of this version, after the review of the port,
is tests/pcbtools/rules_mutation_result_stage4.txt (`--record`).

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
TESTS = ['test_rules_synthetic.py', 'test_rules_review.py', 'test_rules_equivalence.py', 'test_fence.py']

R, F, M, S, K, D = 'rules.py', 'fence.py', 'mutate.py', 'shapes.py', 'check.py', 'drc.py'
RESULT = os.path.join(HERE, 'rules_mutation_result_stage4.txt')
MUTANTS = [
    # LR-1
    (R, 'LR-1 hop length: > becomes >=', "if L > cfg.HOP_MAX or nv > cfg.HOP_MAX_VIAS:", "if L >= cfg.HOP_MAX or nv > cfg.HOP_MAX_VIAS:"),
    (R, 'LR-1 hop vias: > becomes >=', "or nv > cfg.HOP_MAX_VIAS:", "or nv >= cfg.HOP_MAX_VIAS:"),
    (R, 'LR-1 layer count test changed', "if b.copper_layers != 2:", "if b.copper_layers != 4:"),
    (R, 'LR-1 plane pieces: != becomes >', "if pieces_n != 1:", "if pieces_n > 1:"),
    (R, 'LR-1 unfilled plane not reported', "            if not b.z_filled[z]:\n", "            if False:\n"),
    (R, 'LR-1 run join ignores the net', "keep = (i < j) & (net[i] == net[j])", "keep = (i < j)"),
    # review finding 5: a run joins end to end only (a T or a crossing is no join)
    (R, 'LR-1 runs join end to end only (finding 5)', "i, j = geom.within(S, S, 0.01)", "pr = tree.query_pairs(0.01, output_type='ndarray'); i, j = pr[:, 0] % n, pr[:, 1] % n"),
    # review finding 4: every bottom zone
    (R, 'LR-1 other-net bottom zones not reported (finding 4)', "    for zi in bot[b.z_net[bot] != gnd]:", "    for zi in []:"),
    (R, 'LR-1 a second bottom GND zone not reported (finding 4)', "        if len(bz) > 1:\n", "        if False:\n"),
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
    (R, 'LR-4 output resistor: > becomes >=', "pad_c(b, *ch['out_pin'])))) > 5:", "pad_c(b, *ch['out_pin'])))) >= 5:"),
    (R, 'LR-4 decoupling: > becomes >=', "if d > 12:", "if d >= 12:"),
    (R, 'LR-4 FB length: > becomes >=', "if L > cfg.FB_MAX:", "if L >= cfg.FB_MAX:"),
    (R, 'LR-4 keep-back: < becomes <= (pour)', "if g_pour < POUR_KEEP_BACK:", "if g_pour <= POUR_KEEP_BACK:"),
    (R, 'LR-4 keep-back distance halved (pour)', "if g_pour < POUR_KEEP_BACK:", "if g_pour < POUR_KEEP_BACK / 2:"),
    (R, 'LR-4 keep-back distance halved (GND track)', "if g_trk < POUR_KEEP_BACK:", "if g_trk < POUR_KEEP_BACK / 2:"),
    (R, 'LR-4 GND track half width dropped (finding 9)', " - cu.r[:, None] - wg[None, a:a + 1024]", " - cu.r[:, None]"),
    (R, 'LR-4 node copper radius dropped (finding 9)', " - cu.r[:, None] - wg[None, a:a + 1024]", " - wg[None, a:a + 1024]"),
    (R, 'LR-4 only the AWG node judged, the others reported (finding 9)', "if net not in cfg.POUR_NODES:", "if net != '/AWG_FB':"),
    (R, 'LR-4 reported nodes judged too (finding 9)', "if net not in cfg.POUR_NODES:\n            continue", "if False:\n            continue"),
    (S, 'shapes: pour holes ignored (finding 9)', "inside = geom.points_in_polys(P, xy, off, hole=hole).any(axis=1)", "inside = geom.points_in_polys(P, xy, off, hole=None).any(axis=1)"),
    (S, 'shapes: copper on the fill is not distance 0 (finding 9)', "        d[np.unique(own[inside])] = 0.0\n", "        pass\n"),
    (S, 'shapes: pad rotation ignored (finding 9, 10)', "    a = np.radians(rot)[:, None]\n", "    a = np.radians(0 * rot)[:, None]\n"),
    (S, 'shapes: oval axis ignores rotation (finding 9, 10)', "    a = np.radians(rot)\n    ux", "    a = np.radians(0 * rot)\n    ux"),
    (S, 'shapes: circle radius halved (finding 9, 10)', "R.append(np.minimum(sx, sy)[ci] / 2)", "R.append(np.minimum(sx, sy)[ci] / 4)"),
    (S, 'shapes: track half width dropped (finding 10)', "return Copper(C, b.s_w[rows] / 2, np.arange", "return Copper(C, 0 * b.s_w[rows], np.arange"),
    (S, 'shapes: copper inside a box is not distance 0', "        d[np.unique(own[inb])] = 0.0\n", "        pass\n"),
    (R, 'LR-4 INV_MAX: > becomes >=', "if L > cfg.INV_MAX:", "if L >= cfg.INV_MAX:"),
    (R, 'LR-4 INV_MAX counts top copper only', "L = length_of(b, net, top_only=False)", "L = length_of(b, net)"),
    # LR-12
    (R, 'LR-12 decoupling: > becomes >=', "if d > cfg.DECOUP_MAX:", "if d >= cfg.DECOUP_MAX:"),
    (R, 'LR-12 supply pad choice dropped', "ks = [k for k in ('1', '2') if pad_net(b, cap, k) == net] or ['1']", "ks = ['1']"),
    # LR-5
    (R, 'LR-5 segment keep-out: < becomes <=', "        for i in np.flatnonzero(d < cfg.KEEPOUT):\n            near.append(f'{b.nets[b.s_net[rows[i]]]} {d[i]:.1f} mm')", "        for i in np.flatnonzero(d <= cfg.KEEPOUT):\n            near.append(f'{b.nets[b.s_net[rows[i]]]} {d[i]:.1f} mm')"),
    (R, 'LR-5 pad keep-out: < becomes <=', "        for i in np.flatnonzero(d < cfg.KEEPOUT):\n            k = pt.keys[js[i]]", "        for i in np.flatnonzero(d <= cfg.KEEPOUT):\n            k = pt.keys[js[i]]"),
    (R, 'LR-5 generator pads counted', "if pt.keys[j][0] not in cfg.GENERATOR_BLOCK]", "if True]"),
    (R, 'LR-5 pads measured from their centre (finding 10)', "        cu = shapes.pad_copper(b, prow)\n", "        cu = shapes.Copper(np.column_stack([b.p_x[prow], b.p_y[prow], b.p_x[prow], b.p_y[prow]]), np.zeros(len(prow)), np.arange(len(prow)), len(prow))\n"),
    # connectivity: LR-6, LR-8
    (R, 'pieces: track-to-line reach changed', "((e < 0.02) | (D0 < 0.05) | (D1 < 0.05) | (D0.T < 0.05) | (D1.T < 0.05))", "((e < 0.02) | (D0 < 0.03) | (D1 < 0.03) | (D0.T < 0.03) | (D1.T < 0.03))"),
    (R, 'pieces: via-to-track reach changed', "geom.point_seg_dist(V, S) < 0.05", "geom.point_seg_dist(V, S) < 0.03"),
    (R, 'pieces: via-to-via reach changed', "np.triu(dv < 0.05, 1)", "np.triu(dv < 0.03, 1)"),
    (R, 'pieces: track-to-pad margin dropped', "pad=0.02)", "pad=0.0)"),
    (R, 'pieces: via-in-pad margin dropped', "(V[:, None, 0] <= PB[None, :, 2] + 0.02)", "(V[:, None, 0] <= PB[None, :, 2])"),
    (R, 'pieces: bridge pads not joined', "        if ia and ib:\n", "        if False:\n"),
    (R, 'LR-6 star pads not cut', "cut = list(cfg.STAR[net])", "cut = []"),
    (R, 'LR-6 one group per piece: > becomes >=', "if len(hit) > 1:\n                bad.append(f'{net}: one piece", "if len(hit) >= 1:\n                bad.append(f'{net}: one piece"),
    (R, 'LR-8 source pads not cut', "    cut = set(src)\n", "    cut = set()\n"),
    # review findings 1, 2, 3: bridges resolved, reachability, both layers and zones
    (R, 'family: bridge-joined nets not resolved (finding 1)', "            if (a in fam) != (c in fam):", "            if False:"),
    (R, 'graph: the two pads of a bridge part not joined (finding 1)', " + [(r, '1', r, '2') for r, _, _ in getattr(cfg, 'BRIDGES', ())]", ""),
    (R, 'LR-6 reachability not checked (finding 2)', "                elif lost:\n                    bad.append(f'{net}: consumer", "                elif False:\n                    bad.append(f'{net}: consumer"),
    (R, 'LR-6 a group with no pad on the rail passes (finding 1, 2)', "                if not gk:\n", "                if False:\n"),
    (R, 'LR-8 reachability not checked (finding 2)', "                elif lost:\n                    bad.append(f'VREF: branch", "                elif False:\n                    bad.append(f'VREF: branch"),
    (R, 'LR-8 branches checked against a source nobody has', "    if {k[0] for k in src} & refs_on_board:", "    if False:"),
    (R, 'graph: B.Cu tracks ignored (finding 3)', "srow = np.flatnonzero(np.isin(b.s_net, ids) & (b.s_layer < 2))", "srow = np.flatnonzero(np.isin(b.s_net, ids) & (b.s_layer < 1))"),
    (R, 'graph: tracks of two layers touch (finding 3)', " & (SL[:, None] == SL[None, :])", ""),
    (R, 'graph: pad layer mask ignored (finding 3)', " & (((PM[None, :] >> SL[:, None]) & 1) > 0)", ""),
    (R, 'graph: zone fills ignored (finding 3)', "if b.z_filled[z] and b.z_net[z] in ids and b.z_layer[z] < 2]", "if False]"),
    (R, 'graph: zone holes ignored (finding 3)', "off - off[0], hole=b.z_ring_hole[r0:r1]) if len(pts)", "off - off[0], hole=None) if len(pts)"),
    (R, 'graph: a zone joins items of every layer (finding 3)', "                m &= (layer_ok == b.z_layer[z]) | (layer_ok == -1)\n", "                pass\n"),
    (R, 'graph: an arc is dropped', "    if len(arow):                                          # an arc", "    if False:                                              # an arc"),
    # LR-7, LR-9, LR-11
    (R, 'LR-7 DAC0 length: > becomes >=', "if L > 12:", "if L >= 12:"),
    (R, 'LR-7 back-termination reach: > becomes >=', "if dr[r] > 16:", "if dr[r] >= 16:"),
    (R, 'LR-7 shell pads of any net counted', " & (b.p_net == nid(b, cfg.GND))).sum())", ").sum())"),
    (R, 'LR-7 shell pad minimum lowered', "if shell < 3:", "if shell < 2:"),
    (R, 'LR-9 own parts not excused', "hit &= ~own", "hit &= hit"),
    (R, 'LR-9 courtyard margin dropped', "hit = geom.seg_in_box(segs(b)[rows], boxes, pad=cfg.ZONE_PAD + b.s_w[rows] / 2)", "hit = geom.seg_in_box(segs(b)[rows], boxes, pad=b.s_w[rows] / 2)"),
    (R, 'LR-11 outline membership test inverted', "if inside != want:", "if inside == want:"),
    (R, 'LR-11 designator height test inverted', "or b.r_h[k] < cfg.DESIGNATOR_MIN_H:", "or b.r_h[k] > cfg.DESIGNATOR_MIN_H:"),
    (R, 'LR-11 designators with two digits owned', "if len(digits) >= 3 else None", "if len(digits) >= 2 else None"),
    (R, 'LR-11 test point net test dropped', "or pad_net(b, r, cfg.TP_PIN) != n:", "or False:"),
    # config-driven rules: a rule that stops reading its config field must fail
    (R, 'LR-2 only the first channel checked', "    for ch in cfg.CHANNELS:\n        seq", "    for ch in cfg.CHANNELS[:1]:\n        seq"),
    (R, 'LR-4 supply caps not read', "    for cap, ic, pin in cfg.SUPPLY_CAPS:", "    for cap, ic, pin in []:"),
    (R, 'LR-7 shell pin hard-wired', "== awg['shell_pin']", "== '1'"),
    (R, 'LR-8 source net ignored', "family(cfg, cfg.VREF_NET)", "family(cfg, cfg.GND)"),
    # check.py and drc.py: review findings 6, 7, 8
    (K, 'check: an arm on a failing rule counts as caught (finding 6)', "        if not ok0:\n            untestable.append(name)", "        if False:\n            untestable.append(name)"),
    (K, 'check: an untestable arm leaves the exit code 0 (finding 6)', "rc = 1 if (miss or run_arms.untestable or run_arms.not_run) else 0", "rc = 1 if miss else 0"),
    (K, 'check: LR-10 not run prints ALL PASS (finding 8)', "    elif not_run:\n        out('LR-10 NOT RUN')", "    elif False:\n        out('LR-10 NOT RUN')"),
    (K, 'check: LR-10 not run exits 0 (finding 8)', "or run_rows.not_run) else 0", ") else 0"),
    (K, 'check: skipped by request not said (finding 8)', "out('ALL PASS (LR-10 skipped by request)' if skipped_by_request else 'ALL PASS')", "out('ALL PASS')"),
    (D, 'drc: the LR-10 arm without the libraries (finding 7)', "    dst = _work_copy(b.path, arm_dir)\n", "    dst = os.path.join(arm_dir, os.path.basename(b.path))\n    shutil.copyfile(b.path, dst)\n"),
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


def main(argv=None):
    """--range A:B runs mutants A .. B-1 only (the unmutated copy is always run first); --record appends the lines to RESULT
    (a fresh file when A is 0), so a long list can be run in slices each under a job's time limit"""
    argv = sys.argv[1:] if argv is None else argv
    lo, hi = 0, len(MUTANTS)
    if '--range' in argv:
        lo, hi = (int(x) for x in argv[argv.index('--range') + 1].split(':'))
    out = []
    bad = []
    r = run('clean', None)
    out.append('unmutated copy: ' + r)
    print(out[-1], flush=True)
    if not r.startswith('PASSED'):
        return 2
    for i in range(lo, min(hi, len(MUTANTS))):
        f, name, old, new = MUTANTS[i]
        r = run(f'm{i}', (f, old, new))
        ok = r.startswith('FAILED')
        out.append(('caught   ' if ok else 'SURVIVED ') + name + '  [' + r + ']')
        print(out[-1], flush=True)
        if not ok:
            bad.append(name)
    out.append(f'mutants {lo}..{min(hi, len(MUTANTS)) - 1} of {len(MUTANTS)}: ' + ('every mutant caught' if not bad else 'SURVIVORS: ' + '; '.join(bad)))
    print(out[-1], flush=True)
    if '--record' in argv:
        with open(RESULT, 'w' if lo == 0 else 'a') as fh:
            if lo == 0:
                fh.write('working reference, host .venv-pcb, after the review of the port (stage 4)\n')
            fh.write('\n'.join(out) + '\n')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
