"""pcbtools.cap against known answers, against its own grid, and against the old cap.py's recorded and live figures.

Tiers: everything but the last block is numpy only (cached arrays, no pcbnew). `slow` = tens of seconds; the one `pcbnew`
test runs the frozen old tool live and compares unrounded figures and the rasterised masks.

OLD tool, recorded here so that the new deviations sit next to them (old cap.py selftest, 2026-11-12, same host):
    plates ((12,1.0),(6,4.5)) 3.004 %   plates ((8,4.5),(4,1.0)) 6.306 %   plates ((10,2.0)) 0.000 %   (against the continuum)
    microstrip single line  -1.5 % against Hammerstad-Jensen      coupled mutual  -14.6 % against Garg-Bahl
"""
import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys

import numpy as np
import pytest

from pcbtools import boardio, cap
from pcbtools.boards import v2
import synth
from synth import Synth

TESTS = pathlib.Path(__file__).resolve().parents[1]
ARR = TESTS / 'fixtures' / 'arrays'
FX = TESTS / 'fixtures' / 'v2-8a1f7ac'
GOLD = TESTS / 'golden' / 'v2-8a1f7ac'
NAME = 'v2-integrated-990d4b03'
STACKS = (((12, 1.0), (6, 4.5)), ((8, 4.5), (4, 1.0)), ((10, 2.0),))
OLD_PLATES_PCT = (3.004, 6.306, 0.000)


# ---------------------------------------------------------------------------------------------- (a) known answers
@pytest.mark.parametrize('layers', STACKS)
def test_plates_match_the_discrete_series_to_solver_tolerance(layers):
    """parallel plates: the answer is the series of face conductances; the solver must reproduce it to ~1e-6"""
    fd, disc, _ = cap.plates(layers)
    assert fd == pytest.approx(disc, rel=1e-5)


@pytest.mark.parametrize('layers,old_pct', list(zip(STACKS, OLD_PLATES_PCT)))
def test_plates_against_the_continuum_deviate_as_the_old_tool_did(layers, old_pct):
    """the old tool's stated deviation (half a cell of interface position): 3.004, 6.306 and 0.000 %; the new one is the same"""
    fd, _, cont = cap.plates(layers)
    assert abs(fd / cont - 1) * 100 == pytest.approx(old_pct, abs=0.01)


def test_plates_scale_with_the_cell_size_as_area_over_gap():
    """C = e0 er A / d with A and d both scaling with h: a 2 h-cell grid has twice the capacitance"""
    a, _, _ = cap.plates(((6, 3.0),), h=0.1)
    b, _, _ = cap.plates(((6, 3.0),), h=0.2)
    assert b / a == pytest.approx(2.0, rel=1e-5)


def test_plates_on_a_50k_cell_grid_equal_the_series_answer():
    """the small-window known answer of the regular tier: 52 x 32 x 32 = 53 k cells, two dielectrics, the series of face
    conductances to solver tolerance (the full-size windows are the slow tier's)"""
    fd, disc, _ = cap.plates(((25, 1.0), (25, 4.5)), nxy=32)
    assert fd == pytest.approx(disc, rel=1e-5)


@pytest.fixture(scope='module')
def micro():
    return cap.microstrip()


@pytest.mark.slow
def test_single_microstrip_against_hammerstad_jensen(micro):
    """the old tool's -1.5 %: a lid 4 mm up and Neumann sides, so the open-space formula is approached, not met"""
    assert micro['c11_dev'] * 100 == pytest.approx(-1.5, abs=0.05)
    assert abs(micro['c11_dev']) < 0.08                                           # the old selftest's own gate
    assert micro['hj'] == pytest.approx(85.25, abs=0.01) and micro['c11'] == pytest.approx(83.96, abs=0.01)


@pytest.mark.slow
def test_coupled_strips_against_garg_bahl_keep_the_documented_deviation(micro):
    """the old tool's -14.6 % (Garg-Bahl from memory, *(check)*; the FD mutual is the lower one): same here"""
    assert micro['c21_dev'] * 100 == pytest.approx(-14.6, abs=0.05)
    assert 0 < micro['c21'] < micro['c11']
    assert micro['gb_even'] < micro['gb_odd']


@pytest.mark.slow
def test_microstrip_does_not_depend_on_the_solver_tolerance_beyond_it():
    a, b = cap.microstrip(tol=1e-6), cap.microstrip(tol=1e-9)
    assert a['c11'] == pytest.approx(b['c11'], rel=1e-6) and a['c21'] == pytest.approx(b['c21'], rel=2e-5)


@pytest.mark.slow
def test_the_selftest_command_passes(capsys):
    assert cap.main(['selftest']) == 0
    out = capsys.readouterr().out
    assert out.count('selftest plates') == 3 and 'Hammerstad-Jensen' in out and 'Garg-Bahl' in out


def test_a_loose_tolerance_is_visible_and_an_unconverged_solve_raises():
    fd_loose, disc, _ = cap.plates(((12, 1.0), (6, 4.5)), tol=0.3)
    assert abs(fd_loose / disc - 1) > 1e-3                                       # the tolerance is what bounds the answer
    eps = np.ones((6, 6, 6))
    fixed = np.zeros(eps.shape, bool)
    fixed[0] = fixed[-1] = True
    with pytest.raises(RuntimeError, match='did not converge'):
        v = np.zeros(eps.shape)
        v[-1] = 1
        cap.Field(eps, fixed, tol=1e-12, maxiter=1).solve(v)


# --------------------------------------------------------------------------------------------- synthetic boards
def two_tracks(gap=0.4, w=0.4, **extra):
    s = synth.Synth('/A', '/B', '/GND', **{}).s('/A', 'F', 20, 20, 28, 20, w).s('/B', 'F', 20, 20 + w + gap, 28, 20 + w + gap, w)
    return s.build()


@pytest.mark.slow
def test_mutual_capacitance_is_symmetric_and_positive():
    b = two_tracks()
    r = cap.pair_caps(b, ['/A', '/B'], cap.window(b, ['/A', '/B'], 2.0), False, 0.2, cap.Stack(t_air=2.0))
    assert r[('/A', '/B')] > 0 and r[('/A', '/B')] == pytest.approx(r[('/B', '/A')], rel=1e-5)


@pytest.mark.slow
def test_a_closer_track_couples_more_and_a_wider_gap_less():
    st = cap.Stack(t_air=2.0)
    vals = []
    for gap in (0.2, 0.4, 0.8):
        b = two_tracks(gap)
        vals.append(cap.pair_caps(b, ['/A', '/B'], cap.window(b, ['/A', '/B'], 2.0), False, 0.2, st)[('/A', '/B')])
    assert vals[0] > vals[1] > vals[2] > 0


@pytest.mark.slow
def test_grid_convergence_one_halving_0p2_to_0p1():
    """mutual of two 0.4 mm tracks 0.4 mm apart, edges on grid lines at every size: each halving raises it by about 5 %
    (0.1400 -> 0.1471 -> 0.1547 pF at 0.2 / 0.1 / 0.05 mm). It is not converged at these sizes, which is why the old
    docstring says 'good to a factor of about 1.5'; the test pins the size of the step, not a limit."""
    b = two_tracks()
    st = cap.Stack(t_air=2.0)
    v = {h: cap.pair_caps(b, ['/A', '/B'], cap.window(b, ['/A', '/B'], 2.0), False, h, st)[('/A', '/B')] for h in (0.2, 0.1)}
    step = v[0.1] / v[0.2] - 1
    assert 0.03 < step < 0.08, step


@pytest.mark.slow
def test_grid_convergence_second_halving_0p1_to_0p05():
    b = two_tracks()
    st = cap.Stack(t_air=2.0)
    v = {h: cap.pair_caps(b, ['/A', '/B'], cap.window(b, ['/A', '/B'], 2.0), False, h, st)[('/A', '/B')] for h in (0.1, 0.05)}
    step = v[0.05] / v[0.1] - 1
    assert 0.03 < step < 0.08, step
    assert v[0.05] == pytest.approx(0.1547, abs=0.002)


@pytest.mark.slow
def test_self_capacitance_with_the_pour_exceeds_the_one_without_for_a_lone_track():
    b = synth.Synth('/A', '/GND').s('/A', 'F', 20, 20, 26, 20, 0.4).build()
    r = cap.self_cap(b, '/A', pad=2.0, h=0.2, stack=cap.Stack(t_air=2.0))
    assert r[True] > r[False] > 0


def test_only_top_copper_of_the_chosen_nets_and_pads_are_conductors():
    """B.Cu tracks and vias are not modelled, an F.Cu pad is its bounding box, an arc is two chords"""
    s = synth.Synth('/A', '/GND').part('U1', 20, 20, silk=None).p('U1', '1', 21.0, 22.0, net='/A', size=1.0)
    s.s('/A', 'F', 20, 20, 24, 20, 0.2).s('/A', 'B', 20, 21, 24, 21, 0.2).v('/A', 22, 20)
    b = s.build()
    arc = dataclasses.replace(b, a_idx=[9], a_x0=[24.0], a_y0=[20.0], a_xm=[25.0], a_ym=[21.0], a_x1=[26.0], a_y1=[20.0], a_w=[0.3],
                              a_layer=[0], a_net=[b.net_id('/A')])
    cu = cap.copper(arc, ('/A',), '/GND')
    assert len(cu.segs['/A']) == 1 + 2 and len(cu.rects['/A']) == 1 and not len(cu.segs['__other__']) and not len(cu.rects['__gnd__'])
    xa = cu.rects['/A'][0]
    assert (xa[2] - xa[0], xa[3] - xa[1]) == pytest.approx((1.0, 1.0)) and xa[0] == pytest.approx(21.0 + 50 - 0.5)
    assert cu.segs['/A'][0][1] == pytest.approx(150 - 20)                           # KiCad y = 150 - y


def test_kicad_coordinates_are_the_exact_nanometre_doubles_pcbnew_gives():
    """Due y = 150 - 20.1 is 129.9 and 150 - 129.9 is 20.099999999999994 in floats: unrounded, a cell centre sitting exactly on a
    track edge (a 0.2 mm track on a 0.1 mm grid does that) is decided by noise. The grid sees nm / 1e6, as the old tool's ToMM."""
    points = ((20.1, 20.1), (61.7, 100.3), (48.3, 7.7), (91.45, 33.35))
    plain_is_inexact = 0
    for k_x, k_y in points:
        d = synth.Synth('/A').s('/A', 'F', k_x - 50, 150 - k_y, k_x - 50 + 1, 150 - k_y, 0.2).build()
        xa, ya, xb, yb, _ = cap.copper(d, ('/A',)).segs['/A'][0]
        assert (xa, ya) == (k_x, k_y)                                                  # exact float equality, not approx
        px, py = boardio.from_due(d.s_x0[0], d.s_y0[0])
        plain_is_inexact += (px, py) != (k_x, k_y)
    assert plain_is_inexact >= 1                                                       # the check can fail: the plain transform is off


def test_nets_are_grouped_other_and_ground():
    s = synth.Synth('/A', '/B', '/GND').s('/A', 'F', 0, 0, 1, 0).s('/B', 'F', 0, 1, 1, 1).s('/GND', 'F', 0, 2, 1, 2).s('', 'F', 0, 3, 1, 3)
    cu = cap.copper(s.build(), ('/A',), '/GND')
    assert [len(cu.segs[g]) for g in ('/A', '__other__', '__gnd__')] == [1, 2, 1]
    cu = cap.copper(s.build(), ('/A',))                                   # no ground net named: nothing is ground
    assert [len(cu.segs[g]) for g in ('/A', '__other__', '__gnd__')] == [1, 3, 0]


def test_a_window_without_copper_is_an_error():
    b = synth.Synth('/A', '/B').s('/B', 'F', 0, 0, 1, 0).build()
    with pytest.raises(ValueError):
        cap.window(b, ['/A'], 1.0)
    with pytest.raises(ValueError):
        cap.self_cap(b, '/A')


# ----------------------------------------------------------------------------------------------- rasterisation
def test_a_rect_is_closed_at_its_cell_centres():
    """h = 0.125 (binary exact): centres at 0.0625, 0.1875, 0.3125; a rect from 0.0625 to 0.3125 holds all three (closed, as the old tool)"""
    m = cap.raster_rects(np.array([[0.0625, 0.0625, 0.3125, 0.1875]]), 0.0, 0.0, 6, 4, 0.125)
    assert m.sum() == 3 * 2 and m[0:2, 0:3].all()


def test_a_capsule_is_the_set_of_cells_within_half_the_width():
    m = cap.raster_segs(np.array([[0.58, 0.55, 2.02, 0.55, 0.42]]), 0.0, 0.0, 30, 12, 0.1)
    ys, xs = np.nonzero(m)
    assert (ys.min(), ys.max(), xs.min(), xs.max()) == (3, 7, 4, 21)                  # 0.21 mm on each side, round ends
    assert not m[3, 4] and m[5, 4] and m[3, 10]                                        # the corner of the end cap is cut


@pytest.mark.parametrize('chunk', [1, 7, 1000])
def test_chunking_does_not_change_the_raster(monkeypatch, chunk):
    rng = np.random.default_rng(3)
    segs = np.column_stack([rng.uniform(0, 5, (40, 4)), rng.uniform(0.1, 0.5, 40)])
    rects = np.column_stack([rng.uniform(0, 4, (30, 2)), rng.uniform(4, 5, (30, 2))])
    ref = (cap.raster_segs(segs, 0, 0, 50, 50, 0.1), cap.raster_rects(rects, 0, 0, 50, 50, 0.1))
    monkeypatch.setattr(cap, 'CHUNK', chunk)
    got = (cap.raster_segs(segs, 0, 0, 50, 50, 0.1), cap.raster_rects(rects, 0, 0, 50, 50, 0.1))
    assert (ref[0] == got[0]).all() and (ref[1] == got[1]).all() and ref[0].sum() > 100


def test_items_outside_the_window_leave_no_cells():
    assert not cap.raster_segs(np.array([[-9.0, -9, -8, -9, 0.4], [40, 40, 41, 40, 0.4]]), 0, 0, 10, 10, 0.1).any()
    assert not cap.raster_rects(np.array([[-9.0, -9, -8, -8], [40, 40, 41, 41]]), 0, 0, 10, 10, 0.1).any()


def test_the_pour_keep_back_is_a_disc_and_does_not_wrap_round_the_window():
    occ = np.zeros((21, 21), bool)
    occ[10, 10] = True
    kb = cap.keep_back(occ, 0.3, 0.1)
    assert kb.sum() == 29 and kb[10, 13] and not kb[10, 14] and not kb[13, 13]       # radius 3 cells, dx^2 + dy^2 <= 9
    edge = np.zeros((21, 21), bool)
    edge[10, 0] = True
    kb = cap.keep_back(edge, 0.3, 0.1)
    assert kb[10, 3] and not kb[10, 20] and not kb[10, 19] and kb[:, 18:].sum() == 0  # the old np.roll put copper on column 20


# -------------------------------------------------------------------------- (c) equivalence to the old tool's goldens
@pytest.fixture(scope='module')
def integrated():
    return boardio.load_npz(str(ARR / f'{NAME}.npz'))


@pytest.fixture(scope='module')
def rep(integrated):
    return cap.report(integrated, v2)


def golden_lines():
    return json.loads((GOLD / f'{NAME}.cap.json').read_text())['raw'].splitlines()


NUM = re.compile(r'-?\d+\.\d+')


@pytest.mark.slow
def test_report_has_the_old_tools_rows_and_windows(rep):
    assert [k for k in rep.pairs] == [('N-N', False), ('N-N', True), ('NP-NP (+IN pads)', False), ('NP-NP (+IN pads)', True)]
    assert list(rep.selfs) == ['/AWG_FB', '/CH1_N', '/CH2_N']
    assert [tuple(round(v) for v in d['window']) for d in rep.pairs.values()] == [(8, 30), (8, 30), (7, 24), (7, 24)]
    assert [d['cell'] for d in rep.pairs.values()] == [0.2, 0.2, 0.1, 0.1]


@pytest.mark.slow
def test_figures_equal_the_old_tools_golden_within_two_percent(rep):
    """N-N 0.00 fF, NP-NP 0.15 / 0.04 fF, AWG_FB 0.730 / 0.856 pF. Tolerance: the larger of 2 % and one unit of the printed
    last digit. The unrounded figures agree to 1e-15 (no pour) and 4e-7 (pour) in test_live_*: 2 % is the grid, not the solver:
    a flipped cell at a 0.2 mm edge moves a figure by several percent, and the rasters are identical cell for cell."""
    new, old = rep.lines(), golden_lines()
    assert len(old) == 5 and len(new) == 7                                         # the old five lines, then the two divider-node lines
    new = new[:5]
    for n, o in zip(new, old):
        nn, oo = [float(x) for x in NUM.findall(n)], [float(x) for x in NUM.findall(o)]
        assert len(nn) == len(oo)
        for a, b in zip(nn, oo):
            digits = len(re.findall(r'\.(\d+)', o)[0])
            assert abs(a - b) <= max(0.02 * abs(b), 10.0 ** -digits), (n, o)


@pytest.mark.slow
def test_printed_text_is_the_golden_text(rep):
    """the old tool's five lines are the first five of the report; CAP_SELF's divider-node entries add lines after them"""
    assert rep.lines()[:5] == golden_lines()
    assert [l.split(' ')[0] for l in rep.lines()[5:]] == ['/CH1_N', '/CH2_N']


# the self capacitance of the divider nodes (LR-3's test: the extracted capacitance of the high-impedance node to everything else).
# 0.1 mm cells, computed with this code on the integrated board; the SCOPE block's agent measured /CH1_N 0.529 pF no pour and 0.700
# pF with the pour on the east board, and the integrated board gives the same to the printed digit (the divider copper is identical
# there). Neither cell size is converged: see the AWG_FB test below for the size of the step from 0.2 to 0.1 mm.
N_SELF = {'/CH1_N': (0.52906, 0.69953), '/CH2_N': (0.53550, 0.69273)}


@pytest.mark.slow
def test_divider_node_self_capacitance_figures(rep):
    for n, (no, yes) in N_SELF.items():
        assert rep.selfs[n][False] == pytest.approx(no, rel=2e-3), n
        assert rep.selfs[n][True] == pytest.approx(yes, rel=2e-3), n
        assert rep.selfs[n][True] > rep.selfs[n][False]
    assert any(l.startswith('/CH1_N self capacitance') and 'no pour 0.529 pF' in l and 'pour (kept 0.3 mm off) 0.700 pF' in l
               for l in rep.lines())


def test_cap_self_entries_are_what_the_report_uses(integrated, monkeypatch):
    """dropping an entry of cfg.CAP_SELF drops its line from the report, and its cell size is the one used"""
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(cap, 'self_cap', lambda b, net, pad, h, stack, tol, gnd: calls.append((net, pad, h)) or {False: 1.0, True: 2.0})
    cfg = SimpleNamespace(CAP_PAIRS=(), CAP_SELF=v2.CAP_SELF[:2] + (('/CH2_N', 3.0, 0.2),), GND='/GND')
    r = cap.report(integrated, cfg)
    assert list(r.selfs) == ['/AWG_FB', '/CH1_N', '/CH2_N'] and calls[-1] == ('/CH2_N', 3.0, 0.2) and len(r.lines()) == 3
    cfg = SimpleNamespace(CAP_PAIRS=(), CAP_SELF=v2.CAP_SELF[:1], GND='/GND')
    assert list(cap.report(integrated, cfg).selfs) == ['/AWG_FB']
    assert [e[0] for e in v2.CAP_SELF] == ['/AWG_FB', '/CH1_N', '/CH2_N'] and all(e[2] == 0.1 for e in v2.CAP_SELF)


@pytest.mark.slow
def test_figures_have_the_physical_ordering(rep):
    """the pour only adds ground near the nets (more self capacitance, less mutual) and the NP pair is the larger one"""
    p = rep.pairs
    assert p[('NP-NP (+IN pads)', True)]['c'] < p[('NP-NP (+IN pads)', False)]['c']
    assert p[('N-N', False)]['c'] < p[('NP-NP (+IN pads)', False)]['c']
    assert rep.selfs['/AWG_FB'][True] > rep.selfs['/AWG_FB'][False]
    for d in p.values():
        assert d['c'] == pytest.approx(d['reverse'], rel=1e-3, abs=1e-7)   # N-N is 1e-5 fF: noise


@pytest.mark.slow
def test_self_capacitance_of_awg_fb_changes_by_the_stated_amount_when_the_cell_is_halved(integrated):
    """0.2 -> 0.1 mm: no pour 0.699 -> 0.730 pF (+4.5 %), pour 0.934 -> 0.856 pF (-8.3 %); neither is converged"""
    a = cap.self_cap(integrated, '/AWG_FB', 3.0, 0.2, gnd='/GND')
    b = cap.self_cap(integrated, '/AWG_FB', 3.0, 0.1, gnd='/GND')
    assert b[False] / a[False] - 1 == pytest.approx(0.045, abs=0.01)
    assert b[True] / a[True] - 1 == pytest.approx(-0.083, abs=0.01)
    assert abs(b[True] / a[True] - 1) < 0.10 and abs(b[False] / a[False] - 1) < 0.10


# ----------------------------------------------------------------------------- pcbnew tier: the old tool, live
LIVE = r'''
import sys, json
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import cap as old, numpy as np
from pcbtools import boardio, cap as new
from pcbtools.boards import v2
import pcbnew
o = old.main(sys.argv[3])
b = boardio.load_npz(sys.argv[4])
r = new.report(b, v2)
out = {'pairs': {f'{k[0]}|{k[1]}': [float(o[k]), float(d['c'])] for k, d in r.pairs.items()},
       'selfs': {f'{n}|{p}': [float(o[(n, 'self')][p]), float(d[p])] for n, d in r.selfs.items() if (n, 'self') in o for p in (False, True)}}
# the rasters, cell for cell: AWG_FB window at 0.1 and the N pair window at 0.2
board = pcbnew.LoadBoard(sys.argv[3])
same = {}
for name, nets, h, pad in (('awg_fb', ('/AWG_FB',), 0.1, 3.0), ('n_pair', ('/CH1_N', '/CH2_N'), 0.2, 3.0), ('np_pair', ('/CH1_NP', '/CH2_NP'), 0.1, 3.0)):
    old.H = h
    cu_o = old.copper(board, nets)
    cu_n = new.copper(b, nets, '/GND')
    if len(nets) == 1:
        its = cu_o[nets[0]]
        xs = [v for it in its for v in (it[1], it[3])]; ys = [v for it in its for v in (it[2], it[4])]
        w = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    else:
        w = new.window(b, nets, pad)
    nx, ny = int(round((w[2] - w[0]) / h)), int(round((w[3] - w[1]) / h))
    for g in list(nets) + ['__other__', '/GND']:
        mo = old.raster(cu_o.get(g, []), w[0], w[1], nx, ny)
        mn = new.raster(cu_n, '__gnd__' if g == '/GND' else g, w[0], w[1], nx, ny, h)
        same[f'{name}:{g}'] = [bool((mo == mn).all()), int(mo.sum())]
print(json.dumps(dict(out, masks=same)))
'''


@pytest.fixture(scope='module')
def live():
    cap_ = os.environ.get('CAPPED', '')
    cmd = ([cap_, '-m', '3G', '-t', '600'] if cap_ else []) + [sys.executable, '-B', '-c', LIVE, str(FX / 'tools'), os.environ.get('PCBTOOLS_ROOT') or str(TESTS.parent),
                                                               str(FX / f'{NAME}.kicad_pcb'), str(ARR / f'{NAME}.npz')]
    for _ in range(3):
        p = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        if p.returncode not in (139, -11, 134, -6):
            break
    assert p.returncode == 0, p.stderr[-500:]
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.pcbnew
@pytest.mark.slow
def test_live_unrounded_figures_equal_the_old_tools(pcbnew_required, live):
    """no pour: identical to 1e-12 (same arithmetic on identical cells); pour: the old np.roll dilation wraps round the
    window edge, mine does not, and the figures differ by 4e-7 (AWG_FB) and 7e-5 (NP pair) relative"""
    for k, (o, n) in {**live['pairs'], **live['selfs']}.items():
        pour = k.endswith('True')
        assert n == pytest.approx(o, rel=2e-3 if pour else 1e-9, abs=1e-12), (k, o, n)


@pytest.mark.pcbnew
@pytest.mark.slow
def test_live_rasters_are_cell_for_cell_the_old_tools(pcbnew_required, live):
    assert live['masks'] and all(v[0] for v in live['masks'].values()), live['masks']
    assert sum(v[1] for v in live['masks'].values()) > 1000                            # compared real copper, not empty masks


# ---------------------------------------------------------------------------------------------- the grid-size guard
def test_a_grid_over_the_cell_limit_is_refused_before_anything_is_built(monkeypatch):
    assert cap.MAX_CELLS == 3_000_000
    assert cap.check_grid(100, 100, 58) == 580_000
    assert cap.check_grid(100, 100, 300) == 3_000_000                           # exactly the limit is allowed
    with pytest.raises(cap.GridTooLarge, match=r'3,000,001 cells, over the limit of 3,000,000'):
        cap.check_grid(3_000_001, 1, 1)
    assert issubclass(cap.GridTooLarge, ValueError)
    built = []
    monkeypatch.setattr(cap, '_eps', lambda *a, **k: built.append(a))
    s = Synth('/CH1_N', '/CH2_N', '/AWG_FB').part('R1', 0, 0).p('R1', '1', 0, 0, '/CH1_N').p('R1', '2', 400, 300, '/CH2_N')
    b = s.build()
    win = cap.window(b, ('/CH1_N', '/CH2_N'), 3.0)
    with pytest.raises(cap.GridTooLarge):
        cap.pair_caps(b, ['/CH1_N', '/CH2_N'], win, False, h=0.1)
    s = Synth('/AWG_FB').part('R1', 0, 0).p('R1', '1', 0, 0, '/AWG_FB').p('R1', '2', 400, 300, '/AWG_FB')
    with pytest.raises(cap.GridTooLarge):
        cap.self_cap(s.build(), '/AWG_FB', pad=3.0, h=0.1)
    assert built == []                                                          # refused before the first allocation


def test_the_real_windows_are_under_the_limit():
    b = boardio.load_npz(str(ARR / 'v2-integrated-990d4b03.npz'))
    for label, nets, pad, h in v2.CAP_PAIRS:
        x0, y0, x1, y1 = cap.window(b, nets, pad)
        nzb, nz = cap._grid(h, cap.STACK)
        assert cap.check_grid(round((x1 - x0) / h), round((y1 - y0) / h), nz) < cap.MAX_CELLS


# ------------------------------------------------------------------------------------------ grid convergence step
def _geometric(c0, a, p, hs=(0.2, 0.1, 0.05)):
    return [c0 + a * h ** p for h in hs]


@pytest.mark.parametrize('p', (0.5, 1.0, 1.7, 2.0, 2.5))
@pytest.mark.parametrize('sign', (+1, -1))
def test_extrapolate_recovers_the_limit_of_a_known_order(p, sign):
    """C(h) = C0 + A h^p at 0.2/0.1/0.05: the observed order is p and the limit is C0 exactly (either sign of A)"""
    r = cap.extrapolate(_geometric(0.77, sign * 0.4, p))
    assert r['order'] == pytest.approx(p, abs=1e-9)
    assert r['extrapolated'] == pytest.approx(0.77, abs=1e-12)
    assert r['uncertainty'] == pytest.approx(abs(0.77 - r['values'][2]), abs=1e-12)
    assert r['status'].startswith('converging')


def test_extrapolate_uses_the_actual_cell_ratio():
    """a ratio of 3 (0.3/0.1/0.0333) is not mistaken for 2"""
    hs = (0.3, 0.1, 0.1 / 3)
    r = cap.extrapolate([1.5 + 2.0 * h ** 1.3 for h in hs], hs)
    assert r['order'] == pytest.approx(1.3, abs=1e-9) and r['extrapolated'] == pytest.approx(1.5, abs=1e-12)
    with pytest.raises(ValueError):
        cap.extrapolate([1, 2, 3], (0.2, 0.1, 0.07))                                # not a constant ratio


def test_extrapolate_falls_back_when_not_monotone():
    for v in ([0.526, 0.5166, 0.5208], [1.0, 1.2, 1.1]):
        r = cap.extrapolate(v)
        assert r['status'].startswith('not converging monotonically')
        assert r['order'] is None
        assert r['extrapolated'] == v[2]                                            # the finest value stands
        assert r['uncertainty'] == pytest.approx(max(v) - min(v))                   # with the full spread


def test_extrapolate_falls_back_when_the_order_is_out_of_range():
    steep = cap.extrapolate([0.8084, 0.6843, 0.6832])                               # order ~ 6.9
    assert steep['order'] > 2.5 and steep['status'].startswith('not converging monotonically')
    assert steep['extrapolated'] == 0.6832 and steep['uncertainty'] == pytest.approx(0.8084 - 0.6832)
    flat = cap.extrapolate(_geometric(1.0, 1.0, 0.2))                               # order 0.2: too slow to believe
    assert flat['order'] == pytest.approx(0.2) and flat['extrapolated'] == flat['values'][2]
    stuck = cap.extrapolate([1.0, 0.9, 0.9])                                        # d2 = 0, d1 != 0: infinite order
    assert stuck['status'].startswith('not converging monotonically') and stuck['extrapolated'] == 0.9


def test_extrapolate_equal_values_are_converged_with_zero_uncertainty():
    r = cap.extrapolate([0.5, 0.5, 0.5])
    assert r['extrapolated'] == 0.5 and r['uncertainty'] == 0.0 and r['order'] is None and r['status'].startswith('converged')


def test_extrapolate_needs_three_values():
    with pytest.raises(ValueError):
        cap.extrapolate([1.0, 2.0])


def _plate_pF(h, t=((1.6, 1.0), (1.6, 4.5)), side=2.0):
    """physical parallel plates, 2 mm square, an air layer 1.6 mm under a 1.6 mm FR4 layer, at cell size h"""
    return cap.plates(tuple((round(d / h), er) for d, er in t), nxy=round(side / h), h=h)[0]


@pytest.fixture(scope='module')
def plate_levels():
    return [_plate_pF(h) for h in cap.CONVERGE_H]


def test_plate_discretisation_error_is_visible_at_every_level(plate_levels):
    analytic = cap.E0 * (2e-3 * 2e-3) / (1.6e-3 / 1.0 + 1.6e-3 / 4.5) * 1e12
    errs = [abs(c / analytic - 1) for c in plate_levels]
    assert errs[0] > 0.03 and errs[1] > 0.015 and errs[2] > 0.007                  # first order: 4 %, 2 %, 1 %, all visible
    assert errs[0] > errs[1] > errs[2]


def test_plate_extrapolation_lands_closer_to_the_analytic_answer_than_the_finest_grid(plate_levels, capsys):
    """the interface sits half a cell off, so the error is first order in h; the extrapolation must beat the 0.05 mm figure"""
    analytic = cap.E0 * (2e-3 * 2e-3) / (1.6e-3 / 1.0 + 1.6e-3 / 4.5) * 1e12
    r = cap.extrapolate(plate_levels)
    fine_err, ext_err = abs(r['values'][2] - analytic), abs(r['extrapolated'] - analytic)
    with capsys.disabled():
        print(f'\nplates 1.6 mm air + 1.6 mm er 4.5, 2 x 2 mm: analytic {analytic * 1e3:.4f} fF; '
              f'0.2/0.1/0.05 mm {[round(c * 1e3, 4) for c in plate_levels]} fF; observed order {r["order"]:.3f}; '
              f'finest error {fine_err / analytic * 100:.3f} %, extrapolated {r["extrapolated"] * 1e3:.4f} fF '
              f'error {ext_err / analytic * 100:.4f} %')
    assert ext_err < fine_err
    assert r['order'] == pytest.approx(1.0, abs=0.05)
    assert ext_err / analytic < 1e-3


def test_fit_pad_shrinks_the_window_until_the_finest_level_fits():
    size = lambda p: (4 + 2 * p, 4 + 2 * p)
    st = cap.Stack(t_air=2.0)
    nz = cap._grid(0.05, st)[1]
    full = int(round(10 / 0.05)) ** 2 * nz
    assert cap._fit_pad(3.0, 0.05, size, st, full) == 3.0                           # fits: untouched
    used = cap._fit_pad(3.0, 0.05, size, st, full - 1)
    assert 0 <= used < 3.0
    wx, wy = size(used)
    assert int(round(wx / 0.05)) * int(round(wy / 0.05)) * nz <= full - 1


def test_fit_pad_raises_grid_too_large_when_even_no_pad_fits():
    with pytest.raises(cap.GridTooLarge, match='pad at 0'):
        cap._fit_pad(3.0, 0.05, lambda p: (4 + 2 * p, 4 + 2 * p), cap.Stack(t_air=2.0), 1000)


def test_converge_pair_reports_a_shrunk_window_and_its_pad_effect():
    b = two_tracks(gap=0.4)
    st = cap.Stack(t_air=1.0, t_board=0.8)
    hs = (0.4, 0.2, 0.1)
    win = cap.window(b, ['/A', '/B'], 1.5)
    nz = cap._grid(0.1, st)[1]
    cells = int(round((win[2] - win[0]) / 0.1)) * int(round((win[3] - win[1]) / 0.1)) * nz
    r = cap.converge_pair(b, ['/A', '/B'], 1.5, False, hs, st, max_cells=cells // 2)
    assert r['window_limited'] and r['pad_used'] < 1.5 and r['pad_requested'] == 1.5
    assert 'pad_effect' in r and r['extrapolated_padcorrected'] == pytest.approx(r['extrapolated'] + r['pad_effect'])
    assert len(r['values']) == 3 and all(v > 0 for v in r['values'])
    with pytest.raises(cap.GridTooLarge):
        cap.converge_pair(b, ['/A', '/B'], 1.5, False, hs, st, max_cells=1000)
    assert not cap.converge_pair(b, ['/A', '/B'], 1.5, False, hs, st)['window_limited']


def test_converge_self_is_marked_not_validated_and_the_report_lines_are_extra():
    b = two_tracks()
    st = cap.Stack(t_air=1.0, t_board=0.8)
    r = cap.converge_self(b, '/A', 1.0, (0.4, 0.2, 0.1), st, gnd='/GND')
    assert set(r) == {False, True} and all(x['validated'] == 'not validated against a field solver' for x in r.values())
    line = cap.converged_line(('/A', True), r[True])
    assert 'not validated against a field solver' in line and 'extrapolated' in line

    class Cfg:
        CAP_PAIRS = (('A-B', ('/A', '/B'), 1.0, 0.2),)
        CAP_SELF = (('/A', 1.0, 0.2),)
        GND = '/GND'
    plain = cap.report(b, Cfg, st)
    conv = cap.report(b, Cfg, st, converge=True, hs=(0.4, 0.2, 0.1))
    assert conv.lines() == plain.lines() and plain.converged is None and plain.converged_lines() == []
    assert len(conv.converged_lines()) == 4                                         # 2 pair + 2 self
