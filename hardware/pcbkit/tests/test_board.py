"""pcbkit.board: the BoardArrays container, helpers, the frame transform and the npz cache (pure numpy), and read_board against
a board built in the test from KiCad's own footprints (pcbnew)."""
import numpy as np
import pytest

from pcbkit import board as B

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


def test_npz_roundtrip(tmp_path):
    b = synthetic()
    p = tmp_path / 'b.npz'
    B.save_npz(b, p)
    c = B.load_npz(p)
    for n, k in B._ALL:
        u, v = getattr(b, n), getattr(c, n)
        assert (u == v) if k == 'S' else np.array_equal(u, v, equal_nan=(u.dtype.kind == 'f')) and u.dtype == v.dtype, n
    assert c.nets == b.nets and c.copper_layers == 2 and c.path == b.path


# ----------------------------------------------------------------------------- the frame
def test_frame_transform_default_and_given():
    assert [float(v) for v in B.to_frame(60.0, 140.0)] == [60.0, -140.0]                 # default: KiCad's origin, y up
    x, y = B.to_frame(50.0, 150.0, (50.0, 150.0))
    assert (float(x), float(y)) == (0.0, 0.0)
    X, Y = B.to_frame(np.array([88.1, 50.0]), np.array([147.46, 100.0]), (50.0, 150.0))
    assert np.allclose([X[0], Y[0]], [38.1, 2.54]) and np.allclose([X[1], Y[1]], [0.0, 50.0])
    a = np.random.default_rng(1).uniform(0, 200, (50, 2))
    for fr in (B.DEFAULT_FRAME, (50.0, 150.0), (-3.5, 12.25)):
        bx, by = B.from_frame(*B.to_frame(a[:, 0], a[:, 1], fr), fr)
        assert np.allclose(bx, a[:, 0]) and np.allclose(by, a[:, 1])
    assert B.to_frame(60, 140, (50.0, 150.0))[1] > B.to_frame(60, 145, (50.0, 150.0))[1]      # y points up


def test_frame_of_reads_the_configuration_and_refuses_one_without():
    import types
    assert B.frame_of(None) == B.DEFAULT_FRAME
    assert B.frame_of((50, 150)) == (50.0, 150.0)
    assert B.frame_of({'FRAME': (1, 2)}) == (1.0, 2.0)
    assert B.frame_of(types.SimpleNamespace(FRAME=(3, 4))) == (3.0, 4.0)
    with pytest.raises(ValueError, match='FRAME'):
        B.frame_of(types.SimpleNamespace(OTHER=1))
    with pytest.raises(ValueError, match='FRAME'):
        B.frame_of({'OTHER': 1})


# ----------------------------------------------------------------------------- pcbnew: a board built here
@pytest.fixture(scope='module')
def built(pcbnew_mod, tmp_path_factory):
    from synthetic import build
    return build(pcbnew_mod, tmp_path_factory.mktemp('b') / 'b.kicad_pcb')


@pytest.mark.pcbnew
def test_read_board_in_the_given_frame(built):
    b = B.read_board(built, {'FRAME': (50.0, 150.0)})
    assert b.nets == ('', 'GND', 'SIG') or set(b.nets) == {'', 'GND', 'SIG'}
    assert b.fp_ref == ('R1',) and (float(b.fp_x[0]), float(b.fp_y[0])) == (10.0, 10.0)          # (60, 140) -> (10, 10)
    assert np.allclose([b.s_x0[0], b.s_y0[0], b.s_x1[0], b.s_y1[0]], [12, 10, 16, 10]) and np.isclose(b.s_w[0], 0.2)
    assert (float(b.v_x[0]), float(b.v_y[0])) == (20.0, 15.0) and np.isclose(b.v_drill[0], 0.3) and np.isclose(b.v_dia[0], 0.6)
    assert len(b.p_fp) == 2 and set(b.nets[i] for i in b.p_net) == {'GND', 'SIG'} and b.p_smd.all()
    assert b.t_text == ('HELLO',) and (float(b.t_x[0]), float(b.t_y[0])) == (5.0, 25.0)
    xs, ys = b.outline[:, 0], b.outline[:, 1]
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (0.0, 40.0, 0.0, 30.0)                  # (50..90, 120..150) -> (0..40, 0..30)
    assert not np.isnan(b.fp_cx0[0]) and b.fp_cx0[0] < b.fp_x[0] < b.fp_cx1[0] and b.fp_cy0[0] < b.fp_y[0] < b.fp_cy1[0]
    assert (b.p_bx0 <= b.p_x).all() and (b.p_x <= b.p_bx1).all() and (b.p_by0 <= b.p_y).all() and (b.p_y <= b.p_by1).all()


@pytest.mark.pcbnew
def test_read_board_default_frame_and_no_frame_config(built):
    b = B.read_board(built)
    assert (float(b.fp_x[0]), float(b.fp_y[0])) == (60.0, -140.0)
    with pytest.raises(ValueError, match='FRAME'):
        B.read_board(built, {'NOT_FRAME': 1})


@pytest.mark.pcbnew
def test_read_board_retry_child_uses_the_same_frame(built):
    a = B.read_board(built, (50.0, 150.0))
    c = B.read_board_retry(built, (50.0, 150.0))
    for n, k in B._ALL:
        u, v = getattr(a, n), getattr(c, n)
        assert (u == v) if k == 'S' else np.array_equal(u, v), n


@pytest.mark.pcbnew
def test_unreadable_board_raises(pcbnew_mod, tmp_path):
    p = tmp_path / 'junk.kicad_pcb'
    p.write_text('not a board')
    with pytest.raises(Exception):
        B.read_board(str(p))


@pytest.mark.pcbnew
def test_board_object_is_released(built):
    import gc
    import weakref
    B.read_board(built)
    gc.collect()
    assert B.read_board(built).fp_ref == ('R1',)
