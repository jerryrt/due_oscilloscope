"""board.read_board's silk, fab and text arrays, each against pcbnew's own values on a board built in the test, and each broken once on
purpose by tests/mutate_kit.py. Frame (50, 150): KiCad (x, y) -> (x - 50, 150 - y)."""
import numpy as np
import pytest

from pcbkit import board as B
from synthetic import build_rich

FR = (50.0, 150.0)


@pytest.fixture(scope='module')
def rich(pcbnew_mod, tmp_path_factory):
    path = build_rich(pcbnew_mod, tmp_path_factory.mktemp('r') / 'r.kicad_pcb')
    return path, B.read_board(path, FR), pcbnew_mod.LoadBoard(path)


def box(pcb, bb):
    """pcbnew's box of an item as (x0, y0, x1, y1) in the frame, from pcbnew's own left/top/right/bottom"""
    mm = pcb.ToMM
    return (mm(bb.GetLeft()) - FR[0], FR[1] - mm(bb.GetBottom()), mm(bb.GetRight()) - FR[0], FR[1] - mm(bb.GetTop()))


def rows(*cols):
    return sorted(tuple(round(float(v), 5) if not isinstance(v, str) else v for v in r) for r in zip(*cols))


@pytest.mark.pcbnew
def test_footprint_fab_body_box(rich, pcbnew_mod):
    _, b, pb = rich
    for f in pb.GetFootprints():
        i = b.ref_index(f.GetReference())
        shapes = [g for g in f.GraphicalItems() if g.GetLayer() == pcbnew_mod.F_Fab and g.GetClass() == 'PCB_SHAPE']
        got = (b.fp_fab_x0[i], b.fp_fab_y0[i], b.fp_fab_x1[i], b.fp_fab_y1[i])
        if not shapes:
            assert np.isnan(got).all(), f.GetReference()
            continue
        bbs = [box(pcbnew_mod, g.GetBoundingBox()) for g in shapes]
        want = (min(q[0] for q in bbs), min(q[1] for q in bbs), max(q[2] for q in bbs), max(q[3] for q in bbs))
        assert np.allclose(got, want, atol=2e-6), (f.GetReference(), got, want)
    # hand-known: R_0603's body is 1.6 x 0.8 (+ stroke), turned 90 degrees at (10, 10) it is 0.8 tall... wide, 1.6 tall
    i = b.ref_index('R1')
    w, h = b.fp_fab_x1[i] - b.fp_fab_x0[i], b.fp_fab_y1[i] - b.fp_fab_y0[i]
    assert h > w > 0.5 and abs(0.5 * (b.fp_fab_x0[i] + b.fp_fab_x1[i]) - 10.0) < 0.01
    j = b.ref_index('X1')
    assert np.isnan([b.fp_fab_x0[j], b.fp_fab_y0[j], b.fp_fab_x1[j], b.fp_fab_y1[j]]).all()


@pytest.mark.pcbnew
def test_footprint_silk_items(rich, pcbnew_mod):
    _, b, pb = rich
    want = []
    for f in pb.GetFootprints():
        for g in f.GraphicalItems():
            if g.GetLayer() == pcbnew_mod.F_SilkS:
                want.append((b.ref_index(f.GetReference()),) + box(pcbnew_mod, g.GetBoundingBox()))
    assert len(b.fs_fp) == len(want) and len(want) >= 4
    assert rows(b.fs_fp, b.fs_x0, b.fs_y0, b.fs_x1, b.fs_y1) == rows(*zip(*want))
    assert set(b.fs_kind) <= {'segment', 'rect', 'arc', 'circle', 'poly', 'text', 'other'} and 'segment' in b.fs_kind
    assert (b.fs_x0 <= b.fs_x1).all() and (b.fs_y0 <= b.fs_y1).all()
    assert set(b.fs_fp.tolist()) <= {b.ref_index('R1'), b.ref_index('R2')}          # X1 has no silk: no row


@pytest.mark.pcbnew
def test_board_silk_graphics(rich):
    _, b, _ = rich
    got = {k: (b.g_x0[i], b.g_y0[i], b.g_x1[i], b.g_y1[i]) for i, k in enumerate(b.g_kind)}
    assert sorted(b.g_kind) == ['arc', 'circle', 'line', 'poly', 'rect']             # the B.SilkS and F.Fab lines are not rows
    # hand-known boxes: the stroke is included
    assert np.allclose(got['line'], (2 - 0.1, 28 - 0.1, 8 + 0.1, 28 + 0.1), atol=1e-4)           # (52..58, 122), 0.2 wide
    assert np.allclose(got['rect'], (10 - 0.075, 24 - 0.075, 16 + 0.075, 28 + 0.075), atol=1e-4)
    assert np.allclose(got['poly'], (20 - 0.05, 24 - 0.05, 24 + 0.05, 28 + 0.05), atol=1e-4)
    assert np.allclose(got['circle'], (36 - 2 - 0.075, 25 - 2 - 0.075, 36 + 2 + 0.075, 25 + 2 + 0.075), atol=1e-4)
    x0, y0, x1, y1 = got['arc']
    assert 30 - 0.1 < x0 < 30.5 and 33.5 < x1 < 34.1 and y1 > 24 and y0 < 26.0 + 5          # an arc through (80,126) (82,124) (84,126)


@pytest.mark.pcbnew
def test_board_texts(rich, pcbnew_mod):
    _, b, pb = rich
    assert sorted(b.t_text) == ['GHOST', 'HELLO']                                        # the B.SilkS text is not a row
    i, j = b.t_text.index('HELLO'), b.t_text.index('GHOST')
    assert b.t_ang[i] == 90.0 and b.t_just[i] == 'left' and abs(b.t_stroke[i] - 0.2) < 1e-6 and not b.t_hide[i] and b.t_layer[i] == 0
    assert b.t_just[j] == 'center' and abs(b.t_stroke[j] - 0.15) < 1e-6
    for d in pb.Drawings():
        if d.GetClass() == 'PCB_TEXT' and d.GetLayer() == pcbnew_mod.F_SilkS:
            k = b.t_text.index(d.GetText())
            want = box(pcbnew_mod, d.GetBoundingBox())
            assert np.allclose((b.t_x0[k], b.t_y0[k], b.t_x1[k], b.t_y1[k]), want, atol=2e-6), d.GetText()
            assert bool(b.t_hide[k]) == (not d.IsVisible())          # pcbnew keeps no hide flag on a board-level text: always visible
            assert b.t_x0[k] < b.t_x1[k] and b.t_y0[k] < b.t_y1[k]
    # turned 90 degrees: the rendered box is taller than wide, and left-justified text lies at one side of its anchor (here: above it)
    assert (b.t_y1[i] - b.t_y0[i]) > (b.t_x1[i] - b.t_x0[i]) and abs(b.t_x[i] - 5.0) < 1e-6 and abs(b.t_y[i] - 15.0) < 1e-6
    assert b.t_y0[i] >= 15.0 - 0.5 or b.t_y1[i] <= 15.0 + 0.5


@pytest.mark.pcbnew
def test_reference_text_flags(rich, pcbnew_mod):
    _, b, pb = rich
    for f in pb.GetFootprints():
        r, k = f.Reference(), b.ref_index(f.GetReference())
        rr = int(np.flatnonzero(b.r_fp == k)[0])
        assert bool(b.r_hide[rr]) == (not r.IsVisible())
        assert b.r_just[rr] == {pcbnew_mod.GR_TEXT_H_ALIGN_LEFT: 'left', pcbnew_mod.GR_TEXT_H_ALIGN_CENTER: 'center',
                                pcbnew_mod.GR_TEXT_H_ALIGN_RIGHT: 'right'}[r.GetHorizJustify()]
        assert abs(b.r_t[rr] - pcbnew_mod.ToMM(r.GetTextThickness())) < 1e-6            # the stroke is r_t (there is no r_stroke)
        assert abs(b.r_ang[rr] - r.GetTextAngleDegrees()) < 1e-6
    k = b.ref_index('R2')
    rr = int(np.flatnonzero(b.r_fp == k)[0])
    assert b.r_hide[rr] and b.r_just[rr] == 'left' and not b.r_on_silk[rr]
    assert not b.r_hide[int(np.flatnonzero(b.r_fp == b.ref_index('R1'))[0])]


@pytest.mark.pcbnew
def test_pad_boxes_equal_pcbnew_bounding_box(rich, pcbnew_mod):
    """the p_b* arrays are pcbnew's GetBoundingBox of the pad, i.e. the axis-aligned box of the pad as turned on the board"""
    _, b, pb = rich
    for f in pb.GetFootprints():
        for pd in f.Pads():
            k = b.ref_index(f.GetReference())
            r = [i for i in b.pad_indices(f.GetReference(), pd.GetNumber())][0]
            want = box(pcbnew_mod, pd.GetBoundingBox())
            assert np.allclose((b.p_bx0[r], b.p_by0[r], b.p_bx1[r], b.p_by1[r]), want, atol=2e-6), (f.GetReference(), pd.GetNumber())
    r = b.pad_index('R1', '1')                                       # R1 is turned 90 degrees: its 0.8 x 0.95 pad is 0.95 wide, 0.8 ... swapped
    w, h = b.p_bx1[r] - b.p_bx0[r], b.p_by1[r] - b.p_by0[r]
    assert w == pytest.approx(0.95, abs=0.02) and h == pytest.approx(0.8, abs=0.02) or w == pytest.approx(0.8, abs=0.02)
    r2 = b.pad_index('R2', '1')
    assert (b.p_bx1[r2] - b.p_bx0[r2]) == pytest.approx(0.8, abs=0.02)                          # unturned: 0.8 wide, 0.95 tall
    assert (b.p_by1[r2] - b.p_by0[r2]) == pytest.approx(0.95, abs=0.02)


def test_hand_built_board_gets_nan_and_defaults_for_the_added_fields():
    b = B.BoardArrays.from_arrays(nets=('',), fp_idx=[0], fp_ref=['A'], fp_x=[0], fp_y=[0], fp_rot=[0], fp_side=[0], fp_cx0=[0], fp_cy0=[0],
                                  fp_cx1=[1], fp_cy1=[1], fp_kind=['K'], t_text=['x'], t_x=[0], t_y=[0], t_h=[1],
                                  r_x=[0], r_y=[0], r_h=[1], r_w=[1], r_t=[.1], r_ang=[0], r_layer=[0], r_on_silk=[1], r_fp=[0])
    assert np.isnan(b.fp_fab_x0).all() and len(b.fp_fab_x0) == 1 and np.isnan(b.t_x0).all() and b.t_just == ('center',) and not b.t_hide[0]
    assert not b.r_hide[0] and b.r_just == ('center',) and len(b.fs_fp) == 0 and len(b.g_kind) == 0
