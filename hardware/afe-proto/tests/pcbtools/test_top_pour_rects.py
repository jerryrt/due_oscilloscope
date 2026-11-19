"""The top GND pour of both boards is plain rectangles (TOP_POUR_RECTS in each layout settings file) and pcbtools.fill_clean makes it so.

  - the committed AFE-1 board has one top GND zone per rectangle, outline = the rectangle, no carved keep-out left, and LR-14's pourrect check passes on it;
  - fill_clean on the committed AFE-2 board (main's, carved) gives the rectangles: the check passes, the stored fill is what KiCad refills (fillcheck), every GND pad that had a via of its
    own still has one, every GND via it removes is outside the rectangles with nothing of its own on the top copper, and a second run changes nothing.
Broken on purpose (by hand, recorded in the commit): the old top zone not dropped, the keep-outs not dropped, orphan vias kept, orphan test taking a via inside a rectangle, a rectangle zone
not added, a pad's via moved or lost."""
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]
KIT = AFE.parent / 'pcbkit'
FRAME = (50.0, 150.0)

pytestmark = pytest.mark.pcbnew


def _due(r):
    return (r[0] - FRAME[0], FRAME[1] - r[3], r[2] - FRAME[0], FRAME[1] - r[1])


def _read(path):
    sys.path[:0] = [str(KIT), str(AFE)]
    from pcbkit import board as kb
    from pcbtools.frame import FRAME as F
    return kb.read_board(str(path), {'FRAME': F})


def _cfg(name):
    import importlib
    sys.path[:0] = [str(KIT), str(AFE)]
    m = importlib.import_module('pcbtools.boards.' + name)
    c = {k: getattr(m, k) for k in dir(m) if k.startswith(('FILL_', 'GND'))}
    c['GND'] = '/GND'
    return m, c


def _top_zones(b):
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    out = []
    for z in range(len(b.z_layer)):
        if b.z_layer[z] == 0 and b.z_net[z] == g and not b.z_keepout[z]:
            p = np.vstack([b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]] for j in range(b.z_ring_off[z], b.z_ring_off[z + 1]) if not b.z_ring_hole[j]])
            out.append((float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max())))
    return sorted(out)


def _pourrect(b, cfg):
    from pcbkit import rules
    parts, _ = rules.fill_quality_parts(b, cfg)
    return [p for p in parts if p[0] in ('pourrect', 'shell', 'stale_exception', 'gndpad', 'narrow', 'dead_end', 'rough')]


def test_the_afe1_board_is_the_rectangles_and_nothing_else(pcbnew_required):
    m, cfg = _cfg('v1_layout')
    b = _read(AFE / 'kicad' / 'afe-proto.kicad_pcb')
    zones = _top_zones(b)
    want = sorted(_due(r) for r in m.TOP_POUR_RECTS)
    assert len(zones) == len(want) and all(np.allclose(z, w, atol=1e-6) for z, w in zip(zones, want)), (zones, want)
    assert _pourrect(b, cfg) == []
    text = (AFE / 'kicad' / 'afe-proto.kicad_pcb').read_text()
    assert '"fillkeep"' not in text


def test_the_rectangles_are_what_the_rule_asks_of_them():
    for name in ('v1_layout', 'v2_layout'):
        m, _ = _cfg(name)
        rs = [_due(r) for r in m.TOP_POUR_RECTS]
        assert m.FILL_RECT_LAYERS == ('F',)
        for x0, y0, x1, y1 in rs:
            assert min(x1 - x0, y1 - y0) >= 3.0 and (x1 - x0) * (y1 - y0) >= 100.0
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                assert np.hypot(max(b[0] - a[2], a[0] - b[2], 0), max(b[1] - a[3], a[1] - b[3], 0)) >= 1.0


def test_fill_clean_makes_the_rectangle_pour_on_the_carved_afe2_board_and_a_second_run_changes_nothing(pcbnew_required, tmp_path):
    from pcbtools import fillcheck
    src = AFE / 'v2' / 'layout' / 'integrated'
    for f in ('afe-v2-integrated.kicad_pcb', 'afe-v2-integrated.kicad_pro', 'fp-lib-table', 'sym-lib-table'):
        shutil.copyfile(src / f, tmp_path / f)
    (tmp_path / 'lib').symlink_to(src / 'lib')
    board, out, out2 = tmp_path / 'afe-v2-integrated.kicad_pcb', tmp_path / 'out.kicad_pcb', tmp_path / 'out2.kicad_pcb'
    m, cfg = _cfg('v2_layout')
    before = _read(board)
    assert len(_pourrect(before, cfg)) > 100                                                  # main's carved pour fails the rule
    for a, b in ((board, out), (out, out2)):
        r = subprocess.run([sys.executable, '-m', 'pcbtools.fill_clean', str(a), str(b), '--config', 'v2_layout', '--reference', str(board)], cwd=AFE, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    after, again = _read(out), _read(out2)
    assert _pourrect(after, cfg) == []
    assert len(_top_zones(after)) == len(m.TOP_POUR_RECTS)
    assert 'fillkeep' in board.read_text() and 'fillkeep' not in out.read_text()                # main's carved keep-outs are gone from the result
    rows = fillcheck.compare(out)
    assert fillcheck.ok(rows), rows
    gnd = [i for i, n in enumerate(before.nets) if n.lstrip('/') == 'GND'][0]
    vias = lambda b: {(round(float(b.v_x[i]), 3), round(float(b.v_y[i]), 3)) for i in range(len(b.v_x)) if b.v_net[i] == gnd}
    assert vias(after) == vias(again)                                                         # idempotent: nothing added, nothing removed on a second run
    rects = [_due(r) for r in m.TOP_POUR_RECTS]
    gone = vias(before) - vias(after)
    assert gone and all(not any(x0 + 0.3 <= x <= x1 - 0.3 and y0 + 0.3 <= y <= y1 - 0.3 for x0, y0, x1, y1 in rects) for x, y in gone)
    for x, y in gone:                                                                         # nothing of theirs on the top copper: no track end, no pad
        assert not np.any((np.hypot(before.s_x0 - x, before.s_y0 - y) <= 0.45) | (np.hypot(before.s_x1 - x, before.s_y1 - y) <= 0.45))
        assert not np.any((before.p_bx0 - 0.3 <= x) & (x <= before.p_bx1 + 0.3) & (before.p_by0 - 0.3 <= y) & (y <= before.p_by1 + 0.3))
    assert not (vias(after) - vias(before)) or all(any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in rects) for x, y in vias(after) - vias(before))


def test_a_gnd_pad_that_had_a_via_of_its_own_keeps_it(pcbnew_required, tmp_path):
    """every top SMD GND pad of main's AFE-2 board has a GND via within 0.4 mm of its edge; after the rectangle pour each still has one, unless the pad is now in a rectangle"""
    src = AFE / 'v2' / 'layout' / 'integrated'
    for f in ('afe-v2-integrated.kicad_pcb', 'afe-v2-integrated.kicad_pro', 'fp-lib-table', 'sym-lib-table'):
        shutil.copyfile(src / f, tmp_path / f)
    (tmp_path / 'lib').symlink_to(src / 'lib')
    board, out = tmp_path / 'afe-v2-integrated.kicad_pcb', tmp_path / 'out.kicad_pcb'
    r = subprocess.run([sys.executable, '-m', 'pcbtools.fill_clean', str(board), str(out), '--config', 'v2_layout', '--reference', str(board)], cwd=AFE, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    a, b = _read(board), _read(out)
    gnd = [i for i, n in enumerate(a.nets) if n.lstrip('/') == 'GND'][0]

    def has_via(bd, i):
        return any(bd.v_net[k] == gnd and np.hypot(max(bd.p_bx0[i] - bd.v_x[k], bd.v_x[k] - bd.p_bx1[i], 0), max(bd.p_by0[i] - bd.v_y[k], bd.v_y[k] - bd.p_by1[i], 0)) <= bd.v_dia[k] / 2 + 0.05 for k in range(len(bd.v_x)))
    pads = [i for i in range(len(a.p_x)) if a.p_net[i] == gnd and a.p_smd[i] and (a.p_layer_mask[i] & 1)]
    had = [i for i in pads if has_via(a, i)]
    assert had
    lost = [(a.fp_ref[a.p_fp[i]], a.p_pin[i]) for i in had if not has_via(b, i)]
    assert lost == []


def _afe2_copy(tmp_path, drop=None):
    """main's AFE-2 board with its project in tmp_path; `drop(b, gnd)` -> the via enumeration indices to remove from it first"""
    src = AFE / 'v2' / 'layout' / 'integrated'
    for f in ('afe-v2-integrated.kicad_pcb', 'afe-v2-integrated.kicad_pro', 'fp-lib-table', 'sym-lib-table'):
        shutil.copyfile(src / f, tmp_path / f)
    (tmp_path / 'lib').symlink_to(src / 'lib')
    board = tmp_path / 'afe-v2-integrated.kicad_pcb'
    if drop is not None:
        sys.path[:0] = [str(KIT), str(AFE)]
        from pcbtools.editor import edit
        b = _read(board)
        gnd = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
        idx = [int(b.v_idx[i]) for i in drop(b, gnd)]
        assert idx
        cut = tmp_path / 'cut.kicad_pcb'
        with edit(str(board), str(cut)) as e:
            e.remove_vias(idx)
        shutil.copyfile(cut, board)
    return board


def _fill_clean(board, out):
    r = subprocess.run([sys.executable, '-m', 'pcbtools.fill_clean', str(board), str(out), '--config', 'v2_layout', '--reference', str(board)], cwd=AFE, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    return r.stdout


def test_a_gnd_pad_outside_the_rectangles_with_no_via_gets_one_at_its_edge(pcbnew_required, tmp_path):
    m, _ = _cfg('v2_layout')
    rects = [_due(r) for r in m.TOP_POUR_RECTS]
    chosen = []

    def drop(b, gnd):
        for i in range(len(b.p_x)):
            if b.p_net[i] == gnd and b.p_smd[i] and (b.p_layer_mask[i] & 1) and not any(x0 <= b.p_x[i] <= x1 and y0 <= b.p_y[i] <= y1 for x0, y0, x1, y1 in rects):
                near = [k for k in range(len(b.v_x)) if b.v_net[k] == gnd and np.hypot(max(b.p_bx0[i] - b.v_x[k], b.v_x[k] - b.p_bx1[i], 0), max(b.p_by0[i] - b.v_y[k], b.v_y[k] - b.p_by1[i], 0)) <= b.v_dia[k] / 2 + 0.05]
                if len(near) == 1:
                    chosen.append((b.fp_ref[b.p_fp[i]], b.p_pin[i], float(b.p_x[i]), float(b.p_y[i])))
                    return near
        raise AssertionError('no pad to test')
    board = _afe2_copy(tmp_path, drop)
    out = tmp_path / 'out.kicad_pcb'
    log = _fill_clean(board, out)
    ref, pin, px, py = chosen[0]
    assert '%s.%s' % (ref, pin) in log
    b = _read(out)
    gnd = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    pad = [i for i in range(len(b.p_x)) if b.fp_ref[b.p_fp[i]] == ref and b.p_pin[i] == pin and abs(b.p_x[i] - px) < 0.01 and abs(b.p_y[i] - py) < 0.01][0]
    assert any(b.v_net[k] == gnd and np.hypot(max(b.p_bx0[pad] - b.v_x[k], b.v_x[k] - b.p_bx1[pad], 0), max(b.p_by0[pad] - b.v_y[k], b.v_y[k] - b.p_by1[pad], 0)) <= b.v_dia[k] / 2 + 0.05 for k in range(len(b.v_x)))


def test_a_rectangle_with_no_via_is_stitched_inside_itself_apart_and_clear_of_courtyards(pcbnew_required, tmp_path):
    m, cfg = _cfg('v2_layout')
    big = _due(m.TOP_POUR_RECTS[1])                                                           # the 26 x 20 mm rectangle
    inside = lambda b, i: big[0] <= b.v_x[i] <= big[2] and big[1] <= b.v_y[i] <= big[3]
    board = _afe2_copy(tmp_path, lambda b, gnd: [i for i in range(len(b.v_x)) if b.v_net[i] == gnd and inside(b, i)])
    out = tmp_path / 'out.kicad_pcb'
    _fill_clean(board, out)
    before, after = _read(board), _read(out)
    gnd = [i for i, n in enumerate(after.nets) if n.lstrip('/') == 'GND'][0]
    assert not [i for i in range(len(before.v_x)) if before.v_net[i] == gnd and inside(before, i)]
    new = [(float(after.v_x[i]), float(after.v_y[i])) for i in range(len(after.v_x)) if after.v_net[i] == gnd and inside(after, i)]
    assert 1 <= len(new) <= 6
    assert all(np.hypot(a[0] - c[0], a[1] - c[1]) >= 8.0 - 1e-6 for i, a in enumerate(new) for c in new[i + 1:])
    court = [(after.fp_cx0[i], after.fp_cy0[i], after.fp_cx1[i], after.fp_cy1[i]) for i in range(len(after.fp_ref)) if not np.isnan(after.fp_cx0[i])]
    assert not any(c[0] - 0.3 <= x <= c[2] + 0.3 and c[1] - 0.3 <= y <= c[3] + 0.3 for x, y in new for c in court)
    assert _pourrect(after, cfg) == []
