"""The write path, checked by reading the edited board back with boardio.read_board (a different code path)."""
import pathlib
import shutil

import numpy as np
import pytest

from pcbtools import boardio
from pcbtools.editor import edit

pytestmark = pytest.mark.pcbnew

FIX = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'v2-8a1f7ac'
BOARD = FIX / 'v2-integrated-990d4b03.kicad_pcb'
BASE = FIX / 'v2-BASE-056e1d03.kicad_pcb'


@pytest.fixture()
def board(tmp_path):
    p = tmp_path / 'b.kicad_pcb'
    shutil.copy(BOARD, p)
    return p


def rows(b):
    """segments as a set of rounded tuples, for before/after comparison"""
    return {(round(b.s_x0[i], 4), round(b.s_y0[i], 4), round(b.s_x1[i], 4), round(b.s_y1[i], 4), round(b.s_w[i], 4),
             int(b.s_layer[i]), int(b.s_net[i])) for i in range(len(b.s_idx))}


def test_move_changes_only_that_part(board):
    a = boardio.read_board(board)
    ref = a.fp_ref[0]
    i0 = a.ref_index(ref)
    with edit(board) as e:
        e.move(ref, a.fp_x[i0] + 1.5, a.fp_y[i0] - 0.5, 90.0)
    b = boardio.read_board(board)
    i = b.ref_index(ref)
    assert (b.fp_x[i], b.fp_y[i]) == (pytest.approx(a.fp_x[i0] + 1.5, abs=1e-5), pytest.approx(a.fp_y[i0] - 0.5, abs=1e-5))
    assert b.fp_rot[i] % 360 == pytest.approx(90.0)
    others = np.arange(len(b.fp_ref)) != i
    assert np.allclose(b.fp_x[others], a.fp_x[others], atol=1e-5) and np.allclose(b.fp_y[others], a.fp_y[others], atol=1e-5)
    assert rows(b) == rows(a)


def test_add_tracks_and_vias(board):
    a = boardio.read_board(board)
    net = a.nets[int(a.s_net[0])]
    with edit(board) as e:
        e.add_tracks(net.lstrip('/'), 'F', [10.0, 11.0], [20.0, 20.0], [10.0, 11.0], [22.0, 23.0], 0.25)
        e.add_vias('GND', [30.0, 31.0], 5.0, 0.6, 0.3)
    b = boardio.read_board(board)
    assert len(b.s_idx) == len(a.s_idx) + 2 and len(b.v_idx) == len(a.v_idx) + 2
    new = rows(b) - rows(a)
    assert (10.0, 20.0, 10.0, 22.0, 0.25, 0, int(a.s_net[0])) in new and (11.0, 20.0, 11.0, 23.0, 0.25, 0, int(a.s_net[0])) in new
    gnd = b.net_id('/GND')
    nv = [(round(b.v_x[i], 4), round(b.v_y[i], 4)) for i in range(len(b.v_idx)) if b.v_net[i] == gnd]
    assert (30.0, 5.0) in nv and (31.0, 5.0) in nv


def test_remove_tracks_by_reader_index_removes_exactly_those(board):
    a = boardio.read_board(board)
    gone = a.s_idx[:5]
    with edit(board) as e:
        e.remove_tracks(gone)
    b = boardio.read_board(board)
    assert len(b.s_idx) == len(a.s_idx) - 5
    assert rows(a) - rows(b) == {(round(a.s_x0[i], 4), round(a.s_y0[i], 4), round(a.s_x1[i], 4), round(a.s_y1[i], 4),
                                  round(a.s_w[i], 4), int(a.s_layer[i]), int(a.s_net[i])) for i in range(5)}


def test_remove_vias(board):
    a = boardio.read_board(board)
    with edit(board) as e:
        e.remove_vias(a.v_idx[:3])
    b = boardio.read_board(board)
    assert len(b.v_idx) == len(a.v_idx) - 3 and len(b.s_idx) == len(a.s_idx)


def test_indices_stay_valid_after_additions_in_the_same_edit(board):
    a = boardio.read_board(board)
    with edit(board) as e:
        e.add_vias('GND', 40.0, 6.0)
        e.remove_tracks(a.s_idx[:2])          # the snapshot is from entry: the added via does not shift anything
    b = boardio.read_board(board)
    assert len(b.s_idx) == len(a.s_idx) - 2 and len(b.v_idx) == len(a.v_idx) + 1


def test_silk_reference_and_free_text(board):
    a = boardio.read_board(board)
    ref = a.fp_ref[0]
    with edit(board) as e:
        e.set_ref(ref, 50.0, 25.0, h=1.0, t=0.15, on_silk=True)
        e.add_text('REF/CAL', 60.0, 30.0, h=1.0)
    b = boardio.read_board(board)
    k = b.ref_index(ref)
    j = [i for i in range(len(b.r_fp)) if b.r_fp[i] == k][0]
    assert b.r_on_silk[j] and b.r_h[j] == pytest.approx(1.0) and (b.r_x[j], b.r_y[j]) == (pytest.approx(50.0), pytest.approx(25.0))
    assert 'REF/CAL' in b.t_text


def test_remove_and_add_footprint_from_another_board(board):
    base = boardio.read_board(BASE)
    ref = next(r for r in base.fp_ref if r.startswith('R'))
    with edit(board) as e:
        e.remove_footprint(ref)
    assert ref not in boardio.read_board(board).fp_ref
    with edit(board) as e:
        e.add_footprint_from(BASE, ref)
    b = boardio.read_board(board)
    assert ref in b.fp_ref
    i, j = b.ref_index(ref), base.ref_index(ref)
    assert (b.fp_x[i], b.fp_y[i], b.fp_rot[i]) == (pytest.approx(base.fp_x[j], abs=1e-5), pytest.approx(base.fp_y[j], abs=1e-5),
                                                    pytest.approx(base.fp_rot[j], abs=1e-5))


def test_a_failing_block_writes_nothing(board):
    before = board.read_bytes()
    with pytest.raises(RuntimeError):
        with edit(board) as e:
            e.add_vias('GND', 1.0, 1.0)
            raise RuntimeError('boom')
    assert board.read_bytes() == before


def test_unknown_names_raise(board):
    with edit(board) as e:
        with pytest.raises(KeyError):
            e.move('NOPE', 0, 0)
        with pytest.raises(KeyError):
            e.add_vias('NO_SUCH_NET', 0, 0)
    # the block ended cleanly, so the board was saved unchanged


def test_out_path_leaves_the_source_alone(board, tmp_path):
    src = board.read_bytes()
    out = tmp_path / 'o.kicad_pcb'
    with edit(board, out=out) as e:
        e.add_vias('GND', 2.0, 2.0)
    assert board.read_bytes() == src and out.exists()
    assert len(boardio.read_board(out).v_idx) == len(boardio.read_board(board).v_idx) + 1


def test_many_edits_with_removals_in_one_process_do_not_crash(board):
    first = len(boardio.read_board(board).s_idx)
    for k in range(6):
        a = boardio.read_board(board)
        with edit(board) as e:
            e.remove_tracks(a.s_idx[:3])
            e.add_tracks('GND', 'F', 10.0 + k, 1.0, 12.0 + k, 1.0, 0.2)
    assert len(boardio.read_board(board).s_idx) == first + 6 * (1 - 3)


def test_pour_creates_or_refills_a_ground_zone(board):
    with edit(board) as e:
        z = e.pour('GND', 'B')
        assert z is not None
    b = boardio.read_board(board)
    gnd = b.net_id('/GND')
    assert any(b.z_net[i] == gnd and b.z_layer[i] == 1 and b.z_filled[i] for i in range(len(b.z_layer)))


def test_pour_has_the_old_routers_zone_settings(board):
    import pcbnew
    pre = pcbnew.LoadBoard(str(board))
    taken = {(z.GetNetname(), z.GetLayer()) for z in pre.Zones()}
    net = next(n for n in boardio.read_board(board).nets if n.startswith('/') and (n, pcbnew.F_Cu) not in taken)
    del pre
    with edit(board) as e:
        e.pour(net.lstrip('/'), 'F')          # a net with no zone on F.Cu: an existing zone would only be refilled
    b = pcbnew.LoadBoard(str(board))
    zs = [z for z in b.Zones() if z.GetLayer() == pcbnew.F_Cu and z.GetNetname() == net]
    assert len(zs) == 1
    z = zs[0]
    assert z.GetPadConnection() == pcbnew.ZONE_CONNECTION_FULL                      # solid to pads, not spokes
    assert z.GetLocalClearance() == pcbnew.FromMM(0.25) and z.GetMinThickness() == pcbnew.FromMM(0.2)
    assert z.GetIslandRemovalMode() == pcbnew.ISLAND_REMOVAL_MODE_ALWAYS and z.IsFilled()
    del z, zs, b


def test_stub_via_runs_from_the_pad_centre_to_the_offset_and_ends_in_a_via(board):
    b0 = boardio.read_board(board)
    gnd = b0.net_id('/GND')
    i = int(next(k for k in range(len(b0.p_pin)) if b0.p_net[k] == gnd and b0.p_pin[k]))
    ref, pin = b0.fp_ref[b0.p_fp[i]], b0.p_pin[i]
    s0, v0 = len(b0.s_idx), len(b0.v_idx)
    with edit(board) as e:
        assert e.pad_xy(ref, pin) == pytest.approx((b0.p_x[i], b0.p_y[i]), abs=1e-4)
        end = e.stub_via('GND', ref, pin, 0.0, -1.5, w=0.3)
    b = boardio.read_board(board)
    assert end == pytest.approx((b0.p_x[i], b0.p_y[i] - 1.5), abs=1e-4)
    assert len(b.s_idx) == s0 + 1 and len(b.v_idx) == v0 + 1
    k = [j for j in range(len(b.s_idx)) if abs(b.s_x0[j] - b0.p_x[i]) < 1e-4 and abs(b.s_y0[j] - b0.p_y[i]) < 1e-4
         and abs(b.s_y1[j] - (b0.p_y[i] - 1.5)) < 1e-4 and abs(b.s_x1[j] - b0.p_x[i]) < 1e-4]
    assert len(k) == 1 and b.s_w[k[0]] == pytest.approx(0.3)
    j = [m for m in range(len(b.v_idx)) if abs(b.v_x[m] - end[0]) < 1e-4 and abs(b.v_y[m] - end[1]) < 1e-4]
    assert len(j) == 1
    with pytest.raises(KeyError):
        with edit(board) as e:
            e.pad_xy(ref, 'nope')
