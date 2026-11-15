"""D29's identity block keeps clear of drills (spec lead, 2026-11-15): no via within 0.3 mm of the S/N box or of the name, model-and-revision and
S/N-label text boxes, on both boards. The rule is broken on purpose in a synthetic case and on the real boards (a via put into the box)."""
import pathlib
import types

import pytest

from pcbtools import boardio, identity

HERE = pathlib.Path(__file__).resolve().parents[2]
CFG = types.SimpleNamespace(NAME='NAME', ID_LINE='MODEL  REV A', SN_LABEL='S/N',
                            IDENT=dict(name=(0, 0, 2.0), line=(0, -3, 1.2), sn_label=(-4, -6, 1.0), sn_box=(-1.0, -8.0, 9.0, -5.0)))


def test_a_via_near_the_box_or_a_text_is_found_and_a_far_one_is_not():
    assert identity.via_findings([(20.0, 20.0, 0.6)], CFG) == []
    assert any('S/N box' in x for x in identity.via_findings([(4.0, -6.0, 0.6)], CFG))               # inside the box
    assert any('S/N box' in x for x in identity.via_findings([(9.5, -6.5, 0.6)], CFG))               # 0.2 mm from its edge
    assert identity.via_findings([(10.0, -6.5, 0.6)], CFG) == []                                   # 0.7 mm from it
    assert any('name' in x for x in identity.via_findings([(0.0, 0.0, 0.6)], CFG))                  # under a letter
    assert any('model and revision' in x for x in identity.via_findings([(0.0, -3.2, 0.6)], CFG))


@pytest.mark.pcbnew
@pytest.mark.parametrize('rel,cfgname', [('kicad/afe-proto.kicad_pcb', 'v1'), ('v2/layout/integrated/afe-v2-integrated.kicad_pcb', 'v2')])
def test_the_identity_block_is_clear_of_every_via(rel, cfgname):
    import importlib
    cfg = importlib.import_module(f'pcbtools.boards.{cfgname}')
    b = boardio.read_board(str(HERE / rel))
    vias = list(zip(map(float, b.v_x), map(float, b.v_y), map(float, b.v_dia)))
    assert identity.via_findings(vias, cfg) == []
    inside = vias + [(sum(cfg.IDENT['sn_box'][0::2]) / 2, sum(cfg.IDENT['sn_box'][1::2]) / 2, 0.6)]
    assert identity.via_findings(inside, cfg), 'a via put into the S/N box must be found'
