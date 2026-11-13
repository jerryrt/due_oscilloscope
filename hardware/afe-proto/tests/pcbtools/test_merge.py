"""merge.py against the OLD merge_blocks.py (frozen v1, 34b2e51): the same base and block copies go through both and the
merged boards must agree on every part pose, designator pose, track and via. Boards are built with the editor from the v1
baseline fixture, which has no copper: the base gets copper inside and outside the fences, the blocks change it."""
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

from pcbtools import boardio, fence
from pcbtools import merge as mg
from pcbtools.boards import v1 as cfg
from pcbtools.editor import edit

pytestmark = pytest.mark.pcbnew

FIX = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'v1-34b2e51' / 'kicad'


def rows(b):
    segs = {(round(b.s_x0[i], 4), round(b.s_y0[i], 4), round(b.s_x1[i], 4), round(b.s_y1[i], 4), round(b.s_w[i], 4),
             b.nets[b.s_net[i]], int(b.s_layer[i])) for i in range(len(b.s_idx))}
    vias = {(round(b.v_x[i], 4), round(b.v_y[i], 4), round(b.v_dia[i], 4), round(b.v_drill[i], 4), b.nets[b.v_net[i]])
            for i in range(len(b.v_idx))}
    return segs, vias


def poses(b):
    out = {}
    for i, r in enumerate(b.fp_ref):
        j = np.flatnonzero(b.r_fp == i)
        out[r] = (round(b.fp_x[i], 4), round(b.fp_y[i], 4), round(b.fp_rot[i] % 360, 3), int(b.fp_side[i]),
                  (round(b.r_x[j[0]], 4), round(b.r_y[j[0]], 4), round(b.r_ang[j[0]] % 360, 3)) if len(j) else None)
    return out


_PADS = None


def _pads():
    global _PADS
    if _PADS is None:
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='merge-pads-')) / 'b.kicad_pcb'
        shutil.copy(FIX / 'afe-proto.kicad_pcb', tmp)        # pcbnew writes a .kicad_prl next to a board it loads: never in a fixture
        b = boardio.read_board(tmp)
        _PADS = np.column_stack([b.p_x, b.p_y])
    return _PADS


def inside(block, dx=0.0, dy=0.0):
    """a point inside the block's first fence with no pad within 3 mm of it or of its +dx/+dy neighbours (KiCad gives a via that
    lands on a pad that pad's net, so test vias must sit on bare board)"""
    x0, y0, x1, y1 = cfg.FENCES[block][0]
    pads = _pads()
    for gx in np.arange(x0 + 2.0, x1 - 8.0, 1.0):
        for gy in np.arange(y0 + 2.0, y1 - 4.0, 1.0):
            pts = np.array([[gx + k, gy + m] for k in range(0, 7) for m in range(0, 3)])
            if np.min(np.hypot(pts[:, None, 0] - pads[None, :, 0], pts[:, None, 1] - pads[None, :, 1])) > 1.5:
                return (gx + dx, gy + dy)
    raise AssertionError(f'no bare spot in the {block} fence')


@pytest.fixture(scope='module')
def boards(tmp_path_factory):
    d = tmp_path_factory.mktemp('merge')
    base = d / 'base.kicad_pcb'
    shutil.copy(FIX / 'afe-proto.kicad_pcb', base)
    ax, ay = inside('AWG')
    px, py = inside('POWER')
    with edit(base) as e:
        e.add_tracks('GND', 'F', ax, ay, ax + 3.0, ay, 0.25)                 # A: inside AWG: the AWG block will remove it
        e.add_tracks('GND', 'F', 99.0, 30.0, 99.0, 34.0, 0.25)               # B: outside every fence: must survive
        e.add_vias('GND', px, py)                                           # C: inside POWER: the POWER block will remove it
        e.add_tracks('VNEG', 'F', 15.0, 45.0, 16.0, 45.0, 0.2)               # D: outside every fence, other net
    b0 = boardio.read_board(base)
    ia = [i for i in range(len(b0.s_idx)) if b0.s_x0[i] == pytest.approx(ax)][0]
    awg_part = next(r for r in b0.fp_ref if fence.owner_of(r, cfg) == 'AWG')
    pwr_part = next(r for r in b0.fp_ref if fence.owner_of(r, cfg) == 'POWER')
    ji = b0.ref_index(awg_part)
    # AWG block: remove A, add two new segments and a via inside, move+rotate one of its parts and its designator
    awg = d / 'awg.kicad_pcb'
    shutil.copy(base, awg)
    with edit(awg) as e:
        e.remove_tracks([b0.s_idx[ia]])
        e.add_tracks('GND', 'F', ax + 1, ay + 1, ax + 4, ay + 1, 0.2)
        e.add_tracks('VNEG', 'B', ax + 1, ay + 2, ax + 4, ay + 2, 0.3)
        e.add_vias('GND', ax + 5, ay + 1, 0.6, 0.3)
        e.move(awg_part, float(b0.fp_x[ji]) + 1.0, float(b0.fp_y[ji]) - 0.5, 90.0)
        e.set_ref_pose(awg_part, float(b0.fp_x[ji]) + 2.0, float(b0.fp_y[ji]) + 1.5, 90.0)
    # POWER block: remove C, add a via
    pwr = d / 'pwr.kicad_pcb'
    shutil.copy(base, pwr)
    with edit(pwr) as e:
        e.remove_vias([b0.v_idx[0]])
        e.add_vias('GND', px + 2, py + 1)
        e.move(pwr_part, float(b0.fp_x[b0.ref_index(pwr_part)]) - 0.7, float(b0.fp_y[b0.ref_index(pwr_part)]), 0.0)
    # SCOPE block that breaks the rule: moves a part of POWER
    bad = d / 'scope_bad.kicad_pcb'
    shutil.copy(base, bad)
    with edit(bad) as e:
        e.move(pwr_part, float(b0.fp_x[b0.ref_index(pwr_part)]) + 3.0, float(b0.fp_y[b0.ref_index(pwr_part)]), 0.0)
    # REFCAL block that breaks the rule differently: copper outside its fences
    bad2 = d / 'refcal_bad.kicad_pcb'
    shutil.copy(base, bad2)
    with edit(bad2) as e:
        e.add_tracks('GND', 'F', 99.0, 40.0, 99.0, 41.0, 0.25)
    return dict(dir=d, base=base, awg=awg, pwr=pwr, bad=bad, bad2=bad2, awg_part=awg_part, pwr_part=pwr_part)


@pytest.fixture(scope='module')
def new_merge(boards):
    out = boards['dir'] / 'new.kicad_pcb'
    res = mg.merge(boards['base'], {'AWG': boards['awg'], 'POWER': boards['pwr'], 'SCOPE': boards['bad'], 'REFCAL': boards['bad2']},
                   out, cfg)
    return res, out


def test_the_clean_blocks_merge_and_the_two_bad_ones_are_refused(new_merge):
    res, _ = new_merge
    assert res.merged == ['AWG', 'POWER'] and set(res.refused) == {'SCOPE', 'REFCAL'} and not res.ok
    assert any('belongs to POWER' in m for m in res.refused['SCOPE'])
    assert any('copper outside the REFCAL fence added' in m for m in res.refused['REFCAL'])
    assert res.items == {'AWG': 3, 'POWER': 1}
    assert 'AWG: merged (3 tracks/vias in its fences)' in res.report


def test_merged_copper_is_the_base_outside_plus_the_blocks_inside(boards, new_merge):
    _, out = new_merge
    segs, vias = rows(boardio.read_board(out))
    ax, ay = inside('AWG')
    px, py = inside('POWER')
    assert (round(ax, 4), round(ay, 4), round(ax + 3.0, 4), round(ay, 4), 0.25, '/GND', 0) not in segs      # A removed
    assert (99.0, 30.0, 99.0, 34.0, 0.25, '/GND', 0) in segs and (15.0, 45.0, 16.0, 45.0, 0.2, '/VNEG', 0) in segs   # B, D kept
    assert (round(ax + 1, 4), round(ay + 1, 4), round(ax + 4, 4), round(ay + 1, 4), 0.2, '/GND', 0) in segs        # added
    assert any(s[5] == '/VNEG' and s[6] == 1 and s[4] == 0.3 for s in segs)                                          # layer + width kept
    assert (round(px, 4), round(py, 4), 0.6, 0.3, '/GND') not in vias                                                # C removed
    assert (round(px + 2, 4), round(py + 1, 4), 0.6, 0.3, '/GND') in vias and (round(ax + 5, 4), round(ay + 1, 4), 0.6, 0.3, '/GND') in vias


def test_owned_parts_take_the_block_pose_and_nobody_elses_do(boards, new_merge):
    _, out = new_merge
    base, m, awg = (boardio.read_board(p) for p in (boards['base'], out, boards['awg']))
    pb, pm, pa = poses(base), poses(m), poses(awg)
    assert pm[boards['awg_part']] == pa[boards['awg_part']] != pb[boards['awg_part']]
    assert pm[boards['pwr_part']] != pb[boards['pwr_part']]                  # moved by the POWER block (merged), not by SCOPE's bad copy
    others = [r for r in pb if r not in (boards['awg_part'], boards['pwr_part'])]
    assert all(pm[r] == pb[r] for r in others)


def test_same_result_as_the_old_merge_blocks(boards, new_merge, tmp_path):
    _, out = new_merge
    old_dir = tmp_path / 'old'
    shutil.copytree(FIX, old_dir)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    oldout = tmp_path / 'old_merged.kicad_pcb'
    r = subprocess.run([sys.executable, '-I', str(old_dir / 'merge_blocks.py'), str(oldout), '--base', str(boards['base']),
                        f'AWG={boards["awg"]}', f'POWER={boards["pwr"]}', f'SCOPE={boards["bad"]}', f'REFCAL={boards["bad2"]}'],
                       cwd=old_dir, capture_output=True, text=True, env=env)
    assert r.returncode == 1, r.stderr[-300:]                    # 1 = a block refused, as the new one reports
    assert 'AWG: merged (3 tracks/vias' in r.stdout and 'SCOPE: REFUSED' in r.stdout and 'REFCAL: REFUSED' in r.stdout
    a, b = boardio.read_board(out), boardio.read_board(oldout)
    assert rows(a) == rows(b)
    assert poses(a) == poses(b)


def test_nothing_is_written_when_no_block_merges_cleanly_except_the_base_copy(boards, tmp_path):
    res = mg.merge(boards['base'], {'SCOPE': boards['bad']}, tmp_path / 'o.kicad_pcb', cfg)
    assert res.merged == [] and not res.ok
    a, b = boardio.read_board(boards['base']), boardio.read_board(tmp_path / 'o.kicad_pcb')
    assert rows(a) == rows(b) and poses(a) == poses(b)


def test_fences_of_the_v1_config_do_not_overlap(boards, tmp_path):
    res = mg.merge(boards['base'], {}, tmp_path / 'o.kicad_pcb', cfg)
    assert [m for m in res.report if m.startswith('warning')] == []
