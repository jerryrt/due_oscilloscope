"""pcbkit.board on the AFE's recorded boards: the cached arrays against the golden counts of the OLD loader (pure numpy, run everywhere), and
read_board in the AFE's frame against those counts and against the caches (pcbnew-marked). The container, helpers, transform and npz round trip
are tested on synthetic boards in hardware/pcbkit/tests/test_board.py."""
import gc
import glob
import json
import os
import numpy as np
import pytest
from pcbkit import board as B
from pcbtools.frame import FRAME

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


FIRST = [f for f in B._ALL if f[0] not in B.LATER_FIELDS]       # the fields the recorded caches hold (the first release)


# ----------------------------------------------------------------------------- pure numpy
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
            cache[name] = B.read_board(os.path.join(FX, name + '.kicad_pcb'), FRAME)
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
    for n, k in FIRST:
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
    B.read_board(os.path.join(FX, INTEGRATED + '.kicad_pcb'), FRAME)
    gc.collect()
    assert not [o for o in gc.get_objects() if isinstance(o, pcbnew.BOARD)], 'a BOARD survived read_board'


@pytest.mark.pcbnew
def test_read_board_retry_subprocess(pcbnew_required):
    b = B.read_board_retry(os.path.join(FX, NAMES[0] + '.kicad_pcb'), FRAME)
    assert len(b.fp_idx) > 0
