"""The owner's outline ruling on the v2 integrated board (MC-1 amended): the board overhangs the Due by 2.5 mm on each long edge,
each band is a top-layer keep-out (one rule area per band, none on the bottom), the project carries min_copper_edge_clearance 0.45, the applier is idempotent, and a
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
    """what TOP-layer copper lies in the band (x0, y0, x1, y1): F.Cu tracks (with their half width), vias (through all layers), pad boxes,
    F.Cu filled pours. The bottom layer is not a keep-out there (the ground plane fills it), so B.Cu tracks and pours are not counted. numpy only"""
    x0, y0, x1, y1 = band
    hit = []
    w = b.s_w / 2
    m = (b.s_layer == 0) & (np.maximum(b.s_x0, b.s_x1) + w > x0) & (np.minimum(b.s_x0, b.s_x1) - w < x1) & (np.maximum(b.s_y0, b.s_y1) + w > y0) & (np.minimum(b.s_y0, b.s_y1) - w < y1)
    hit += [f'track {i}' for i in np.flatnonzero(m)]
    r = b.v_dia / 2
    m = (b.v_x + r > x0) & (b.v_x - r < x1) & (b.v_y + r > y0) & (b.v_y - r < y1)
    hit += [f'via {i}' for i in np.flatnonzero(m)]
    m = (b.p_bx1 > x0) & (b.p_bx0 < x1) & (b.p_by1 > y0) & (b.p_by0 < y1)
    hit += [f'pad {b.fp_ref[b.p_fp[i]]}.{b.p_pin[i]}' for i in np.flatnonzero(m)]
    for z in np.flatnonzero((b.z_layer == 0) & b.z_filled & ~b.z_keepout):
        v0, v1 = b.z_vert_off[b.z_ring_off[z]], b.z_vert_off[b.z_ring_off[z + 1]]
        xy = b.z_xy[v0:v1]
        if len(xy) and ((xy[:, 1] < y1) & (xy[:, 1] > y0) & (xy[:, 0] > x0) & (xy[:, 0] < x1)).any():
            hit.append('pour fill')
    return hit


# ------------------------------------------------------------------------------------------------ the arithmetic and the data
def test_the_outline_arithmetic_is_100_by_58_34_split_over_both_long_edges():
    x0, y0, x1, y1 = L.BOARD_RECT
    dx0, dy0, dx1, dy1 = L.DUE_RECT
    assert (round(x1 - x0, 6), round(y1 - y0, 6)) == (100.0, 58.34)
    assert round(x1 - x0, 6) <= L.BOARD_MAX_MM[0] and round(y1 - y0, 6) <= L.BOARD_MAX_MM[1]
    assert (x0, x1) == (dx0, dx1)                                                      # the short edges are the Due's own
    assert (round(dy0 - y0, 6), round(y1 - dy1, 6)) == (L.OVERHANG, L.OVERHANG)         # the same overhang on both long edges: centred over the Due
    assert L.KEEPOUTS == [(L.BAND_NAME, (x0, y0, x1, dy0)), (L.FAR_BAND_NAME, (x0, dy1, x1, y1))]      # each band is exactly its overhang
    assert L.KEEPOUT_LAYERS == ('F.Cu',)                                                # top only
    for lane in (0.55, 0.95, 1.35):                                                    # the strip lanes keep their place, >= 3 mm from the cut
        assert lane - y0 >= 3.0


def test_the_board_file_has_the_split_outline_and_one_top_rule_area_per_band():
    t = BOARD.read_text()
    x0, y0, x1, y1 = L.BOARD_RECT
    assert due_rect_of_edge_cuts(t) == (x0, y0, x1, y1, 4)
    zones = re.findall(r'\n\t\(zone\n(.*?)\n\t\)(?=\n)', t, re.S)
    for name, rect in L.KEEPOUTS:
        band = [z for z in zones if f'(name "{name}")' in z]
        assert len(band) == 1
        z = band[0]
        assert '(layer "F.Cu")' in z and 'B.Cu' not in z                                # top only: the bottom ground plane fills the band
        assert '(tracks not_allowed)' in z and '(vias not_allowed)' in z and '(copperpour not_allowed)' in z
        a, b = O.sheet(rect[0], rect[1]), O.sheet(rect[2], rect[3])
        assert f'(xy {O.fmt(a[0])} {O.fmt(a[1])}) (xy {O.fmt(b[0])} {O.fmt(a[1])}) (xy {O.fmt(b[0])} {O.fmt(b[1])}) (xy {O.fmt(a[0])} {O.fmt(b[1])})' in z
    bottom = [z for z in zones if '(net "/GND")' in z and '(layer "B.Cu")' in z]           # the bottom GND zone outline is the board grown by ZONE_MARGIN
    assert len(bottom) == 1
    m = L.ZONE_MARGIN
    n, s_ = O.sheet(x0 - m, y1 + m), O.sheet(x1 + m, y0 - m)
    assert f'(xy {O.fmt(n[0])} {O.fmt(n[1])}) (xy {O.fmt(s_[0])} {O.fmt(n[1])}) (xy {O.fmt(s_[0])} {O.fmt(s_[1])}) (xy {O.fmt(n[0])} {O.fmt(s_[1])})' in bottom[0]


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
    old = t
    for name, _ in L.KEEPOUTS:                                                          # drop both bands, put the Due's own outline back
        old = re.sub(r'\n\t\(zone\n(?:(?!\n\t\)\n).)*?\(name "%s"\).*?\n\t\)\n' % name, '\n', old, count=1, flags=re.S)
        assert f'(name "{name}")' not in old
    dy0, dy1 = O.sheet(0, L.DUE_RECT[1])[1], O.sheet(0, L.DUE_RECT[3])[1]
    ys = {O.fmt(O.sheet(0, L.BOARD_RECT[1])[1]): O.fmt(dy0), O.fmt(O.sheet(0, L.BOARD_RECT[3])[1]): O.fmt(dy1)}
    for s_, e_, blk in reversed(O._edge_blocks(old)):
        for new_y, old_y in ys.items():
            blk = blk.replace(' %s)' % new_y, ' %s)' % old_y)
        old = old[:s_] + blk + old[e_:]
    assert due_rect_of_edge_cuts(old)[:4] == L.DUE_RECT
    once = O.apply_outline(old)
    assert once.count('(name "') >= 2 and O.apply_outline(once) == once
    assert re.sub(r'\n\t\(zone\n.*?\n\t\)(?=\n)', '', once, flags=re.S) == re.sub(r'\n\t\(zone\n.*?\n\t\)(?=\n)', '', t, flags=re.S)   # outside the zones, byte equal
    pro = json.loads(PRO.read_text())
    stale = json.loads(json.dumps(pro))
    stale['board']['design_settings']['rules']['min_copper_edge_clearance'] = 0.2
    assert O.apply_pro(stale) == pro and O.apply_pro(pro) == pro


# ------------------------------------------------------------------------------------------------ the real board: nothing in the band
pcbnew_mark = pytest.mark.pcbnew


@pcbnew_mark
def test_the_band_of_the_integrated_board_holds_no_copper(pcbnew_required):
    b = boardio.read_board(BOARD)
    for _, band in L.KEEPOUTS:
        assert band_copper(b, band) == []
    assert b.z_keepout.sum() == 3 and (b.outline[:, 1].min(), b.outline[:, 1].max()) == pytest.approx((L.BOARD_RECT[1], L.BOARD_RECT[3]), abs=1e-5)   # two bands + the unnamed 5V_F rule area


@pcbnew_mark
def test_copper_in_the_band_is_found_and_kicad_calls_it_a_violation(pcbnew_required, tmp_path):
    """broken once: a track and a via put in the band must be reported by the band check and by KiCad's DRC (items_not_allowed)"""
    from pcbtools.editor import edit
    p = tmp_path / 'b.kicad_pcb'
    shutil.copy(BOARD, p)
    ys = [(lo + hi) / 2 for _, (_, lo, _, hi) in L.KEEPOUTS]                           # the middle of each band
    with edit(p) as e:
        for k, y in enumerate(ys):
            e.add_tracks('/GND', 'F', 40.0, y, 44.0, y, 0.2)
            e.add_vias('/GND', 60.0, y, 0.6, 0.3)
    for _, band in L.KEEPOUTS:
        hit = band_copper(boardio.read_board(p), band)
        assert any(h.startswith('track') for h in hit) and any(h.startswith('via') for h in hit), hit
    if not shutil.which('kicad-cli'):
        pytest.skip('no kicad-cli')
    out = tmp_path / 'drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(out), str(p)], capture_output=True)
    types = [v['type'] for v in json.loads(out.read_text())['violations']]
    assert types.count('items_not_allowed') == 2 * len(L.KEEPOUTS), types


@pcbnew_mark
def test_the_bottom_ground_plane_fills_both_bands_and_is_not_a_keepout(pcbnew_required, tmp_path):
    """the bottom layer is free in the bands: the real board's B.Cu fill reaches into each band (but not to the edge, 0.45 mm), and a B.Cu
    track put in a band is neither counted by the top-only band check nor reported by KiCad's DRC as not allowed"""
    from pcbtools.editor import edit
    b = boardio.read_board(BOARD)
    bz = np.flatnonzero((b.z_layer == 1) & b.z_filled & ~b.z_keepout)
    assert len(bz) == 1
    v0, v1 = b.z_vert_off[b.z_ring_off[bz[0]]], b.z_vert_off[b.z_ring_off[bz[0] + 1]]
    ys = b.z_xy[v0:v1, 1]
    edge = 0.45
    assert ys.min() == pytest.approx(L.BOARD_RECT[1] + edge, abs=0.02) and ys.max() == pytest.approx(L.BOARD_RECT[3] - edge, abs=0.02), (ys.min(), ys.max())
    p = tmp_path / 'b.kicad_pcb'
    shutil.copy(BOARD, p)
    y = (L.KEEPOUTS[0][1][1] + L.KEEPOUTS[0][1][3]) / 2
    with edit(p) as e:
        e.add_tracks('/GND', 'B', 40.0, y, 44.0, y, 0.2)
    assert band_copper(boardio.read_board(p), L.KEEPOUTS[0][1]) == []
    if shutil.which('kicad-cli'):
        out = tmp_path / 'drc.json'
        subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(out), str(p)], capture_output=True)
        assert 'items_not_allowed' not in [v['type'] for v in json.loads(out.read_text())['violations']]
