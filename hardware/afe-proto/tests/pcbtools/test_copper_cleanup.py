"""The AFE-2 copper cleanup (v2/layout/copper_cleanup): its input of record, its hand edits as data, and what the rebuilt board leaves.

  * the board of record is held by hash (the tool's input is exactly what it was written against);
  * every polyline the hand edits add runs on the angle step (0, 45, 90 degrees, 0.5 degrees of tolerance) and no edit data names a net the board has not;
  * the committed integrated board has no track_geometry or fill_quality finding but the named exceptions of the board configuration (each with its reason, each matching one finding), and a stale exception row fails (pcbnew tier).
Broken on purpose: a 133 degree polyline in the data, a changed byte in the board of record, a finding added to the board and a stale exception row each fail the matching test."""
import hashlib
import math
import pathlib
import sys

import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]
CC = AFE / 'v2' / 'layout' / 'copper_cleanup'
BOARD = AFE / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
BEFORE_SHA256 = '00a2eb855b53622431c9f387ab6d1fdf7dc77ae676394953b5b90b23033962c7'
FRAME = (50.0, 150.0)
def off_step(polyline):
    """[(i, angle)] of the segments of a polyline not on a multiple of 45 degrees (0.5 degrees of tolerance)"""
    out = []
    for i in range(len(polyline) - 1):
        (x0, y0), (x1, y1) = polyline[i], polyline[i + 1]
        a = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 45.0
        if min(a, 45.0 - a) > 0.5:
            out.append((i, round(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180, 1)))
    return out


def edit_polylines():
    sys.path.insert(0, str(CC))
    import cc_edits, cc_fix_data
    for mod in (cc_edits, cc_fix_data):
        for net, kill, adds in mod.OPS:
            for pl, w in adds:
                yield net, pl


def test_the_board_of_record_is_held_by_hash():
    assert hashlib.sha256((CC / 'afe-v2-integrated.before.kicad_pcb').read_bytes()).hexdigest() == BEFORE_SHA256


def test_every_hand_edit_polyline_is_on_the_angle_step():
    n = 0
    for net, pl in edit_polylines():
        assert off_step(pl) == [], (net, pl)
        n += 1
    assert n > 20                                                  # a floor: the data must have been read


def test_the_angle_check_fires_on_a_133_degree_segment():
    a = math.radians(133)
    assert off_step([(0.0, 0.0), (math.cos(a), math.sin(a))]) == [(0, 133.0)]
    assert off_step([(0, 0), (1, 1), (1, 2), (0, 2)]) == []


def geometry_cfg(extra=()):
    from pcbkit import rules
    from pcbtools.boards import v2_layout as L
    cfg = {k: getattr(L, k) for k in [n.key for n in rules.TRACK_GEOMETRY_NAMES + rules.FILL_QUALITY_NAMES] if hasattr(L, k)}
    cfg['GEOMETRY_EXCEPTIONS'] = list(cfg['GEOMETRY_EXCEPTIONS']) + list(extra)
    return cfg


@pytest.mark.pcbnew
def test_the_rebuilt_board_has_no_geometry_finding_but_the_named_exceptions(pcbnew_required):
    from pcbkit import board, rules
    b = board.read_board(str(BOARD), FRAME)
    parts = rules.track_geometry_parts(b, geometry_cfg())
    assert list(parts) == [], list(parts)                        # nothing left, and no stale exception
    from pcbtools.boards import v2_layout as L
    assert sorted((e[0], e[1]) for e, f in parts.waived) == sorted((e[0], e[1]) for e in L.GEOMETRY_EXCEPTIONS) and len(L.GEOMETRY_EXCEPTIONS) >= 4        # every row waives exactly one finding
    assert all(len(e[3]) > 40 for e in L.GEOMETRY_EXCEPTIONS)        # and carries its reason
    assert L.TRACK_BREAKOUT_REACH == 0.8


@pytest.mark.pcbnew
def test_the_rebuilt_board_has_no_fill_finding_but_the_named_exceptions(pcbnew_required):
    """the pour: no narrow piece, dead end, row of arcs, no connector GND pin or SMD GND pad lost from the top pour, except the named shell and GND pad exceptions of the configuration (each matching one finding)"""
    from pcbkit import board, rules
    from pcbtools.boards import v2_layout as L
    b = board.read_board(str(BOARD), FRAME)
    cfg = geometry_cfg()
    parts, figs = rules.fill_quality_parts(b, cfg)
    assert list(parts) == [], list(parts)
    assert figs['F_shell_pins'] >= 14 and len(L.FILL_SHELL_EXCEPTIONS) == 3 and all(len(e[2]) > 40 for e in L.FILL_SHELL_EXCEPTIONS)


@pytest.mark.pcbnew
def test_a_shell_pin_exception_that_matches_nothing_fails(pcbnew_required):
    from pcbkit import board, rules
    b = board.read_board(str(BOARD), FRAME)
    cfg = geometry_cfg()
    cfg['FILL_SHELL_EXCEPTIONS'] = list(cfg['FILL_SHELL_EXCEPTIONS']) + [('J101', '2', 'a pin that has pour round it: this row matches no finding')]
    parts, figs = rules.fill_quality_parts(b, cfg)
    assert any(p[0] in ('stale_exception', 'shell') for p in parts)


@pytest.mark.pcbnew
def test_the_cleanup_did_not_lengthen_a_protected_net(pcbnew_required):
    """the cleanup is cosmetic and spends no electrical margin: every net whose track length an LR row reads or limits (AWG_FB, CH1_OUT, CH2_OUT, A0, A1, the divider nodes) is no longer than on
    the board of record, unrounded, to float noise (1e-9 mm) and nothing larger"""
    sys.path.insert(0, str(CC))
    import cc_check
    a, z = cc_check.lengths(str(CC / 'afe-v2-integrated.before.kicad_pcb')), cc_check.lengths(str(BOARD))
    assert len(a) == 7 and set(a) == set(z)
    assert [n for n in a if z[n] > a[n] + cc_check.TOL] == []


@pytest.mark.pcbnew
def test_a_stale_exception_row_fails_the_check(pcbnew_required):
    from pcbkit import board, rules
    b = board.read_board(str(BOARD), FRAME)
    parts = rules.track_geometry_parts(b, geometry_cfg([('angle', '/AWG_FB', (10.0, 10.0), 'a row that matches nothing')]))
    assert [f[0] for f in parts] == ['stale_exception']
