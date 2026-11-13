"""The owner's outline ruling on the v2 integrated board (MC-1 amended): the board overhangs the Due by 5 mm on the analog-header edge only,
the band is a copper keep-out (one rule area), the project carries min_copper_edge_clearance 0.45, the applier is idempotent, and a
rule area is never read as copper by the rules (z_keepout). Text and numpy except the pcbnew-marked arms."""
import json
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np
import pytest

from pcbtools import boardio
from pcbtools.boards import v2_layout as L


LAYOUT = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout'
BOARD = LAYOUT / 'integrated' / 'afe-v2-integrated.kicad_pcb'
PRO = LAYOUT / 'integrated' / 'afe-v2-integrated.kicad_pro'
sys.path.insert(0, str(LAYOUT))
import outline_overhang as O  # noqa: E402


def due_rect_of_edge_cuts(text):
    pts = []
    for _, _, blk in O._edge_blocks(text):
        pts += list(O._pts(blk))
    xs = [p[0] - 50 for p in pts]
    ys = [150 - p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys), len(O._edge_blocks(text))


def band_copper(b, band):
    """what copper lies in the band (x0, y0, x1, y1): tracks (with their half width), vias, pad boxes, filled pours. numpy only"""
    x0, y0, x1, y1 = band
    hit = []
    w = b.s_w / 2
    m = (np.maximum(b.s_x0, b.s_x1) + w > x0) & (np.minimum(b.s_x0, b.s_x1) - w < x1) & (np.maximum(b.s_y0, b.s_y1) + w > y0) & (np.minimum(b.s_y0, b.s_y1) - w < y1)
    hit += [f'track {i}' for i in np.flatnonzero(m)]
    r = b.v_dia / 2
    m = (b.v_x + r > x0) & (b.v_x - r < x1) & (b.v_y + r > y0) & (b.v_y - r < y1)
    hit += [f'via {i}' for i in np.flatnonzero(m)]
    m = (b.p_bx1 > x0) & (b.p_bx0 < x1) & (b.p_by1 > y0) & (b.p_by0 < y1)
    hit += [f'pad {b.fp_ref[b.p_fp[i]]}.{b.p_pin[i]}' for i in np.flatnonzero(m)]
    if len(b.z_xy):
        m = (b.z_xy[:, 1] < y1) & (b.z_xy[:, 1] > y0) & (b.z_xy[:, 0] > x0) & (b.z_xy[:, 0] < x1)
        hit += ['pour fill'] * int(m.any())
    return hit


# ------------------------------------------------------------------------------------------------ the arithmetic and the data
def test_the_outline_arithmetic_is_100_by_58_34_and_overhangs_the_south_edge_only():
    x0, y0, x1, y1 = L.BOARD_RECT
    assert (round(x1 - x0, 6), round(y1 - y0, 6)) == (100.0, 58.34)
    assert round(x1 - x0, 6) <= L.BOARD_MAX_MM[0] and round(y1 - y0, 6) <= L.BOARD_MAX_MM[1]
    assert (x0, y1) == (17.0, 53.34) and x1 == 117.0 and y0 == -5.0                    # the other three edges are the Due's own
    assert L.KEEPOUTS == [(L.BAND_NAME, (17.0, -5.0, 117.0, 0.0))]                       # the band is exactly the overhang
    for lane in (0.55, 0.95, 1.35):                                                    # the strip lanes keep their place, >= 5 mm from the cut
        assert lane - y0 >= 5.0


def test_the_board_file_has_the_overhang_outline_and_one_rule_area_over_the_band():
    t = BOARD.read_text()
    assert due_rect_of_edge_cuts(t) == (17.0, -5.0, 117.0, 53.34, 4)
    zones = re.findall(r'\n\t\(zone\n(.*?)\n\t\)\n', t, re.S)
    band = [z for z in zones if f'(name "{L.BAND_NAME}")' in z]
    assert len(band) == 1
    z = band[0]
    assert '(layers "F.Cu" "B.Cu")' in z and '(tracks not_allowed)' in z and '(vias not_allowed)' in z and '(copperpour not_allowed)' in z
    assert '(xy 67 155) (xy 167 155) (xy 167 150) (xy 67 150)' in z


def test_the_project_carries_the_board_setup_with_edge_clearance_0_45():
    pro = json.loads(PRO.read_text())
    rules = pro['board']['design_settings']['rules']
    assert rules['min_copper_edge_clearance'] == 0.45
    for k, v in L.BOARD_SETUP['board']['design_settings']['rules'].items():
        assert rules[k] == v, k
    c = [c for c in pro['net_settings']['classes'] if c['name'] == 'Default'][0]
    assert (c['clearance'], c['track_width'], c['via_diameter'], c['via_drill']) == (0.15, 0.15, 0.6, 0.3)


def test_the_applier_is_idempotent_and_reproduces_the_board_from_the_old_outline():
    t = BOARD.read_text()
    assert O.apply_outline(t) == t                                                      # already applied: unchanged
    old = re.sub(r'\n\t\(zone\n\t\t\(layers "F.Cu" "B.Cu"\)\n(?:(?!\n\t\)\n).)*?\(name "analog edge band"\).*?\n\t\)\n', '\n', t, count=1, flags=re.S)
    assert old != t and '(name "analog edge band")' not in old
    for s, e, blk in reversed(O._edge_blocks(old)):
        old = old[:s] + blk.replace(' 155)', ' 150)') + old[e:]
    assert due_rect_of_edge_cuts(old)[:4] == (17.0, 0.0, 117.0, 53.34)
    once = O.apply_outline(old)
    assert once == t and O.apply_outline(once) == once
    pro = json.loads(PRO.read_text())
    stale = json.loads(json.dumps(pro))
    stale['board']['design_settings']['rules']['min_copper_edge_clearance'] = 0.2
    assert O.apply_pro(stale) == pro and O.apply_pro(pro) == pro


# ------------------------------------------------------------------------------------------------ the real board: nothing in the band
pcbnew_mark = pytest.mark.pcbnew


@pcbnew_mark
def test_the_band_of_the_integrated_board_holds_no_copper(pcbnew_required):
    b = boardio.read_board(BOARD)
    assert band_copper(b, L.KEEPOUTS[0][1]) == []
    assert b.z_keepout.sum() == 2 and (b.outline[:, 1].min(), b.outline[:, 1].max()) == pytest.approx((-5.0, 53.34), abs=1e-5)


@pcbnew_mark
def test_copper_in_the_band_is_found_and_kicad_calls_it_a_violation(pcbnew_required, tmp_path):
    """broken once: a track and a via put in the band must be reported by the band check and by KiCad's DRC (items_not_allowed)"""
    from pcbtools.editor import edit
    p = tmp_path / 'b.kicad_pcb'
    shutil.copy(BOARD, p)
    with edit(p) as e:
        e.add_tracks('/GND', 'F', 40.0, -2.5, 44.0, -2.5, 0.2)
        e.add_vias('/GND', 60.0, -2.5, 0.6, 0.3)
    hit = band_copper(boardio.read_board(p), L.KEEPOUTS[0][1])
    assert any(h.startswith('track') for h in hit) and any(h.startswith('via') for h in hit), hit
    if not shutil.which('kicad-cli'):
        pytest.skip('no kicad-cli')
    out = tmp_path / 'drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(out), str(p)], capture_output=True)
    types = [v['type'] for v in json.loads(out.read_text())['violations']]
    assert types.count('items_not_allowed') == 2, types
