"""boardio: container, helpers, transform and npz cache (pure numpy, run everywhere); read_board against the golden counts
of the OLD loader (pcbnew-marked)."""
import gc
import glob
import json
import os
import numpy as np
import pytest
from pcbtools import boardio as B

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
FX = os.path.join(TESTS, 'fixtures', 'v2-8a1f7ac')
GOLD = os.path.join(TESTS, 'golden', 'v2-8a1f7ac')
ARR = os.path.join(TESTS, 'fixtures', 'arrays')
NAMES = sorted(os.path.basename(p)[:-10] for p in glob.glob(os.path.join(FX, '*.kicad_pcb')))
BOARDS = [n for n in NAMES if 'BASE' not in n]
INTEGRATED = next(n for n in NAMES if 'integrated' in n)
KNOWN_PADS = [('J601', '5', 38.1, 2.54), ('TP404', '1', 30.0, 22.8)]   # TP404: file (at 80 127.2), read off the text


def counts(name):
    return json.load(open(os.path.join(GOLD, f'{name}.counts.json')))['counts']


def synthetic():
    return B.BoardArrays.from_arrays(
        nets=('', '/GND', '/SIG'), copper_layers=2,
        s_idx=[0, 2], s_x0=[0, 5], s_y0=[0, 0], s_x1=[4, 9], s_y1=[0, 0], s_w=[.2, .2], s_layer=[0, 1], s_net=[2, 1],
        v_idx=[1], v_x=[4], v_y=[0], v_dia=[.6], v_drill=[.3], v_net=[2],
        fp_idx=[0, 1], fp_ref=['R1', 'C1'], fp_x=[1, 7], fp_y=[0, 0], fp_rot=[0, 90], fp_side=[0, 0],
        fp_cx0=[0, 6], fp_cy0=[-1, -1], fp_cx1=[2, 8], fp_cy1=[1, 1], fp_kind=['R_0603', 'C_0603'],
        p_fp=[0, 0, 1], p_pin=['1', '2', '1'], p_x=[.5, 1.5, 7], p_y=[0, 0, 0], p_bx0=[0, 1, 6.5], p_by0=[-.4] * 3,
        p_bx1=[1, 2, 7.5], p_by1=[.4] * 3, p_net=[2, 1, 1], p_smd=[1, 1, 1], p_rot=[0, 0, 90], p_shape=[3, 3, 3],
        p_sx=[.9] * 3, p_sy=[.95] * 3, p_layer_mask=[1, 1, 1])


# ----------------------------------------------------------------------------- pure numpy
def test_default_constructor_has_empty_groups():
    b = B.BoardArrays()
    assert len(b.s_idx) == len(b.v_idx) == len(b.fp_idx) == len(b.p_fp) == len(b.z_layer) == 0
    assert b.nets == ('',) and b.fp_ref == () and b.outline.shape == (0, 2) and b.z_ring_off.tolist() == [0]
    with pytest.raises(Exception):
        b.copper_layers = 4            # frozen


def test_group_length_mismatch_is_refused():
    with pytest.raises(ValueError):
        B.BoardArrays(s_idx=[0, 1], s_x0=[0.0])
    with pytest.raises(ValueError):
        B.BoardArrays(z_layer=[0], z_net=[1], z_filled=[True], z_ring_off=[0, 1], z_vert_off=[0, 3], z_ring_hole=[0], z_xy=np.zeros((2, 2)))


def test_helpers():
    b = synthetic()
    assert b.net_id('/GND') == 1 and b.net_id('') == 0
    with pytest.raises(KeyError):
        b.net_id('/NOPE')
    assert b.ref_index('C1') == 1
    with pytest.raises(KeyError):
        b.ref_index('X9')
    assert b.pad_index('R1', '2') == 1 and b.pad_index('C1', '1') == 2
    with pytest.raises(KeyError):
        b.pad_index('R1', '3')
    assert b.seg_mask(net='/SIG').tolist() == [True, False]
    assert b.seg_mask(net='/GND', layer='B').tolist() == [False, True]
    assert b.seg_mask(layer=0).tolist() == [True, False]
    assert b.seg_mask().tolist() == [True, True]
    assert b.pad_mask(net='/GND').tolist() == [False, True, True]
    assert b.pad_mask(net=2).tolist() == [True, False, False]
    c = b.replace(s_net=[1, 1])                    # an edit makes a new board and fresh lookups
    assert c.seg_mask(net='/SIG').sum() == 0 and b.seg_mask(net='/SIG').sum() == 1


def test_dtypes_and_rounding():
    b = synthetic()
    assert b.s_x0.dtype == np.float64 and b.s_layer.dtype == np.int8 and b.s_net.dtype == np.int32 and b.p_smd.dtype == bool
    assert b.p_layer_mask.dtype == np.uint8 and b.fp_ref == ('R1', 'C1')


def test_due_transform():
    x, y = B.to_due(50.0, 150.0)
    assert (x, y) == (0.0, 0.0)
    X, Y = B.to_due(np.array([88.1, 50.0]), np.array([147.46, 100.0]))
    assert np.allclose([X[0], Y[0]], [38.1, 2.54]) and np.allclose([X[1], Y[1]], [0.0, 50.0])
    a = np.random.default_rng(1).uniform(0, 200, (50, 2))
    bx, by = B.from_due(*B.to_due(a[:, 0], a[:, 1]))
    assert np.allclose(bx, a[:, 0]) and np.allclose(by, a[:, 1])
    # y points up in Due mm: a point lower on the KiCad page (larger y) has the smaller Due y
    assert B.to_due(60, 140)[1] > B.to_due(60, 145)[1]


def test_npz_roundtrip(tmp_path):
    b = synthetic()
    p = tmp_path / 'b.npz'
    B.save_npz(b, p)
    c = B.load_npz(p)
    for n, k in B._ALL:
        u, v = getattr(b, n), getattr(c, n)
        assert (u == v) if k == 'S' else np.array_equal(u, v) and u.dtype == v.dtype, n
    assert c.nets == b.nets and c.copper_layers == 2 and c.path == b.path


def test_every_fixture_has_a_cached_array_file_with_a_floor():
    assert len(BOARDS) >= 6 and len(NAMES) == len(BOARDS) + 1
    for n in NAMES:
        assert os.path.exists(os.path.join(ARR, n + '.npz')), n


@pytest.mark.parametrize('name', NAMES)
def test_cached_arrays_match_old_loader_counts(name):
    b = B.load_npz(os.path.join(ARR, name + '.npz'))
    check_counts(b, counts(name))


def check_counts(b, g):
    assert len(b.s_idx) + len(b.a_idx) == g['n_segs']
    assert g['track_classes'].get('PCB_TRACK', 0) == len(b.s_idx) and g['track_classes'].get('PCB_VIA', 0) == len(b.v_idx)
    assert len(b.v_idx) == g['n_vias'] and len(b.fp_idx) == g['n_fps'] and len(b.z_layer) == g['n_zones']
    assert len(b.t_text) == g['n_silk'] and b.copper_layers == g['copper_layers']
    # the old loader keys pads by (ref, pin) and the last one wins: reproduce that
    last = {}
    for k, (f, pin) in enumerate(zip(b.p_fp, b.p_pin)):
        last[(b.fp_ref[f], pin)] = k
    assert len(last) == g['n_pads']
    pn = {}
    for k in last.values():
        pn[b.nets[b.p_net[k]]] = pn.get(b.nets[b.p_net[k]], 0) + 1
    assert pn == g['pads_per_net']
    # per (net, layer) track length: all of it, within the 1e-6 per-coordinate rounding
    ln = np.hypot(b.s_x1 - b.s_x0, b.s_y1 - b.s_y0)
    got = {}
    for k in range(len(ln)):
        key = f"{b.nets[b.s_net[k]]}|{'F' if b.s_layer[k] == 0 else 'B'}"
        got[key] = got.get(key, 0.0) + ln[k]
    assert set(got) == set(g['netlen_by_net_layer'])
    tol = 4e-6 * max(1, len(ln))
    for key, v in g['netlen_by_net_layer'].items():
        assert got[key] == pytest.approx(v, abs=tol), key
    assert ln.sum() == pytest.approx(g['total_len'], abs=tol)


def test_known_pads_on_cached_arrays():
    b = B.load_npz(os.path.join(ARR, INTEGRATED + '.npz'))
    for ref, pin, x, y in KNOWN_PADS:
        i = b.pad_index(ref, pin)
        assert (b.p_x[i], b.p_y[i]) == pytest.approx((x, y), abs=1e-6), ref


def test_cached_arrays_are_sane():
    b = B.load_npz(os.path.join(ARR, INTEGRATED + '.npz'))
    assert b.nets[0] == '' and b.nets[1] == '/GND'
    assert (b.s_idx[1:] > b.s_idx[:-1]).all() and (np.diff(b.fp_idx) == 1).all()          # enumeration order kept
    allidx = np.sort(np.concatenate([b.s_idx, b.a_idx, b.v_idx]))
    assert np.array_equal(allidx, np.arange(len(allidx)))                                  # tracks partition GetTracks()
    assert np.array_equal(np.round(b.s_x0, 6), b.s_x0)                                      # 1e-6 rounding
    assert b.z_ring_off[-1] == len(b.z_vert_off) - 1 == len(b.z_ring_hole) and b.z_vert_off[-1] == len(b.z_xy)
    # KiCad hands these pours back fractured (a cut-out is a slit in the outline, HoleCount 0), so the hole flags are all 0 here
    assert set(b.z_ring_hole.tolist()) == {0}
    has = ~np.isnan(b.fp_cx0)
    assert has.sum() > 50 and (b.fp_cx1[has] > b.fp_cx0[has]).all() and (b.fp_cy1[has] > b.fp_cy0[has]).all()
    inside = (b.fp_x >= b.outline[:, 0].min() - 1) & (b.fp_x <= b.outline[:, 0].max() + 1)
    assert inside.all()


# ----------------------------------------------------------------------------- pcbnew
@pytest.fixture(scope='module')
def live():
    cache = {}

    def get(name):
        if name not in cache:
            cache[name] = B.read_board(os.path.join(FX, name + '.kicad_pcb'))
        return cache[name]
    return get


@pytest.mark.pcbnew
@pytest.mark.parametrize('name', NAMES)
def test_read_board_matches_old_loader_counts(pcbnew_required, live, name):
    b = live(name)
    assert b.path.endswith(name + '.kicad_pcb')
    check_counts(b, counts(name))


@pytest.mark.pcbnew
@pytest.mark.parametrize('name', NAMES)
def test_read_board_equals_cached_arrays(pcbnew_required, live, name):
    a, c = live(name), B.load_npz(os.path.join(ARR, name + '.npz'))
    for n, k in B._ALL:
        if n == 'z_keepout':         # added after the caches were recorded (frozen): they load as all False, and a live read finds the rule areas
            continue
        u, v = getattr(a, n), getattr(c, n)
        assert (u == v if k == 'S' else np.array_equal(u, v, equal_nan=True)), n
    assert not c.z_keepout.any() and len(c.z_keepout) == len(a.z_keepout)
    assert not (a.z_keepout & a.z_filled).any()          # a rule area is never filled copper


@pytest.mark.pcbnew
def test_known_pads_live(pcbnew_required, live):
    b = live(INTEGRATED)
    for ref, pin, x, y in KNOWN_PADS:
        i = b.pad_index(ref, pin)
        assert (b.p_x[i], b.p_y[i]) == pytest.approx((x, y), abs=1e-6), ref
    # J601: the old tool's own value, from the old loader's golden is not stored per pad; pin 5 is the spec's anchor


@pytest.mark.pcbnew
def test_board_object_is_released(pcbnew_required):
    import pcbnew
    B.read_board(os.path.join(FX, INTEGRATED + '.kicad_pcb'))
    gc.collect()
    assert not [o for o in gc.get_objects() if isinstance(o, pcbnew.BOARD)], 'a BOARD survived read_board'


@pytest.mark.pcbnew
def test_unreadable_board_raises(pcbnew_required, tmp_path):
    p = tmp_path / 'junk.kicad_pcb'
    p.write_text('not a board')
    with pytest.raises(Exception):
        B.read_board(str(p))


@pytest.mark.pcbnew
def test_read_board_retry_subprocess(pcbnew_required):
    b = B.read_board_retry(os.path.join(FX, NAMES[0] + '.kicad_pcb'))
    assert len(b.fp_idx) > 0
