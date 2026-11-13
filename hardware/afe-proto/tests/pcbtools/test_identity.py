"""pcbtools.identity on a synthetic board text and config (no board of either AFE version): exactly the config's name, model and
revision line, S/N label and order-number text, an S/N box; each property broken once on purpose."""
import types

import pytest

from pcbtools import identity

CFG = types.SimpleNamespace(
    NAME='NAME', ID_LINE='MODEL  REV A', SN_LABEL='S/N', JLC_ORDER_TEXT='JLCJLCJLCJLC',
    IDENT=dict(name=(0, 0, 2.0), line=(0, 0, 1.2), sn_label=(0, 0, 1.0), sn_box=(0, 0, 10.0, 3.0), jlc=(0, 0, 1.0)))


def _text(s, layer, h):
    return f'\t(gr_text "{s}"\n\t\t(at 1 1 0)\n\t\t(layer "{layer}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {h} {h})\n\t\t\t)\n\t\t)\n\t)\n'


GOOD = ('(kicad_pcb\n' + _text('NAME', 'F.SilkS', 2) + _text('MODEL  REV A', 'F.SilkS', 1.2) + _text('S/N', 'F.SilkS', 1)
        + _text('JLCJLCJLCJLC', 'B.SilkS', 1)
        + '\t(gr_rect\n\t\t(start 0 0)\n\t\t(end 10 3)\n\t\t(fill yes)\n\t\t(layer "F.SilkS")\n\t)\n)\n')


def test_the_good_board_has_no_findings():
    assert identity.findings(GOOD, CFG) == []


@pytest.mark.parametrize('old,new,reason', [
    ('"NAME"', '"NAMX"', "name 'NAME': 0"),
    ('"MODEL  REV A"', '"MODEL  REV B"', "model and revision 'MODEL  REV A': 0"),
    ('"S/N"', '"SN"', "S/N label 'S/N': 0"),
    ('"JLCJLCJLCJLC"', '"JLCJLC"', 'order number'),
    ('(fill yes)', '(fill no)', 'no filled S/N box'),
    ('"B.SilkS"', '"F.SilkS"', 'order number'),
    ('(size 2 2)', '(size 1.5 1.5)', 'mm high'),
])
def test_each_property_fails_when_broken(old, new, reason):
    assert old in GOOD
    assert any(reason in b for b in identity.findings(GOOD.replace(old, new, 1), CFG)), old


def test_a_second_name_or_revision_line_fails():
    assert any('2 on F.SilkS' in b for b in identity.findings(GOOD.replace('(kicad_pcb\n', '(kicad_pcb\n' + _text('NAME', 'F.SilkS', 2)), CFG))
    assert any('other than' in b for b in identity.findings(GOOD.replace('(kicad_pcb\n', '(kicad_pcb\n' + _text('X REV C', 'F.SilkS', 1)), CFG))
