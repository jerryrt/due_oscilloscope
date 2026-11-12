from types import SimpleNamespace as NS

import pytest

from pcbtools import floorplan as fp


def data(**kw):
    d = NS(X0=0.0, X1=100.0, Y0=0.0, Y1=50.0,
           FENCES={'A': [(5.0, 5.0, 30.0, 45.0)], 'B': [(40.0, 5.0, 90.0, 45.0)]},
           CORRIDORS={'wall': (30.0, 0.0, 40.0, 50.0)}, KEEPOUT=[(10.0, 10.0, 12.0, 12.0)], KEEP_R=5.0,
           FIXED=[('J1', 95.0, 25.0, 'bnc')], HEADERS=[('H1', 10.0, 2.5, 20.0)], COL={'A': '#111111', 'B': '#222222'},
           C=[('VCC', 'A', 'B', (30.0, 20.0), 'F 0.3', 'BR1', 'A', 'rail'),
              ('IN', 'EDGE', 'A', (5.0, 25.0), 'F 0.2', '', 'A', ''),
              ('GND', 'all', 'all', 'plane', 'B.Cu', '', 'integrator', 'plane'),
              ('X', 'A', 'A', ('inside',), 'F 0.2', '', 'A', '')],
           BRIDGES=[('BR1', 'VCC / VCC_B', (35.0, 20.0), 'the wall'), ('BR2', 'N / M', ('B',), 'a leg')],
           NOTES=['- a note'], TITLE='test floorplan')
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_table_has_one_row_per_contract_row_and_bridge():
    t = fp.table_md(data()).splitlines()
    rows = [x for x in t if x.startswith('| ') and x[2].isdigit()]
    assert len(rows) == 4
    assert '| 1 | VCC | A -> B | (30.0, 20.0) | F 0.3 | BR1 | A | rail |' in t
    assert '| 3 | GND | all -> all | plane | B.Cu |  | integrator | plane |' in t
    assert '| 4 | X | A -> A | inside the fence | F 0.2 |  | A |  |' in t
    assert '| BR1 | VCC / VCC_B | (35.0, 20.0) | the wall |' in t
    assert '| BR2 | N / M | in B, to be placed | a leg |' in t
    assert t[-1] == '- a note'


def test_svg_draws_every_fence_edge_point_and_bridge():
    s = fp.svg(data())
    assert s.count('<rect') == 1 + 1 + 1 + 2 + 1 + 1 + 1       # board, keepout, corridor, 2 fences, header, bridge BR1 (numeric only)
    assert s.count('<circle') == 1 + 2                          # fixed part J1 + two numeric edge points
    assert 'test floorplan' in s and s.startswith('<svg') and s.rstrip().endswith('</svg>')


def test_validate_clean_data_has_no_findings():
    assert fp.validate(data()) == []


def test_validate_finds_each_defect():
    assert any('empty' in x for x in fp.validate(data(FENCES={'A': [(5, 5, 5, 45)], 'B': []})))
    assert any('outside the board' in x for x in fp.validate(data(FENCES={'A': [(5, 5, 130, 45)], 'B': []})))
    assert any('overlap' in x for x in fp.validate(data(FENCES={'A': [(5, 5, 50, 45)], 'B': [(40, 5, 90, 45)]})))
    assert any('listed twice' in x for x in fp.validate(data(BRIDGES=[('BR1', '', (1, 1), ''), ('BR1', '', (2, 2), '')])))
    far = data(C=[('VCC', 'A', 'B', (35.0, 20.0), 'F', '', 'A', '')])        # 5 mm from A's east edge and 5 mm from B's west edge
    assert any('row 1 VCC' in x for x in fp.validate(far))
    assert fp.validate(far, tol=5.1) == []


def test_edge_and_all_rows_are_not_checked():
    assert fp.validate(data(C=[('IN', 'EDGE', 'EDGE', (999.0, 999.0), 'F', '', '', '')])) == []


@pytest.mark.parametrize('p,r,want', [((0.0, 5.0), (0, 0, 10, 10), 0.0), ((5.0, 5.0), (0, 0, 10, 10), 5.0),
                                       ((13.0, 14.0), (0, 0, 10, 10), 5.0), ((-2.0, 5.0), (0, 0, 10, 10), 2.0)])
def test_dist_to_rect_boundary(p, r, want):
    assert fp.dist_to_rect_boundary(p, r) == pytest.approx(want)
