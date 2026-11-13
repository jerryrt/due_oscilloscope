"""The committed v2 board carries the identity its configuration states (pcbtools/identity.py is the checker; the numbers are boards/v2.py's),
and the file names the order, fab and package files carry are built from the same fields."""
import pathlib
import re

from pcbtools import identity
from pcbtools.boards import v2

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
TXT = BOARD.read_text()


def test_the_config_says_what_the_owner_ruled():
    assert (v2.NAME, v2.MODEL, v2.REV) == ('COPPIA', 'AFE-2', 'A')
    assert v2.ID_LINE == 'AFE-2  REV A' and v2.FILE_STEM == 'COPPIA-AFE-2-REVA'
    assert v2.IDENT['name'][2] == 2.0 and v2.IDENT['line'][2] == 1.2 and v2.IDENT['sn_label'][2] == 1.0 and v2.IDENT['jlc'][2] == 1.0
    assert set('IOQSXZ').isdisjoint(v2.REV)


def test_the_board_carries_exactly_the_configured_identity():
    assert identity.findings(TXT, v2) == []
    top = [m.group(1) for m in re.finditer(r'\(gr_text "([^"]*)"[^\n]*\n[^\n]*\n\t\t\(layer "F.SilkS"', TXT)]
    assert top.count(v2.NAME) == 1 and top.count(v2.ID_LINE) == 1 and top.count(v2.SN_LABEL) == 1
    assert [t for t in top if 'REV' in t] == [v2.ID_LINE]


def test_the_serial_box_and_the_bottom_marker_exist():
    assert re.search(r'\(gr_text "JLCJLCJLCJLC"\n[^\n]*\n\t\t\(layer "B.SilkS"', TXT)
    assert '(fill yes)' in TXT


def test_the_identity_breaks_when_the_silk_text_changes():
    assert identity.findings(TXT.replace('"COPPIA"', '"COPPIX"', 1), v2)
    assert identity.findings(TXT.replace('"AFE-2  REV A"', '"AFE-2  REV B"', 1), v2)


def test_the_placer_is_idempotent_on_the_board():
    import sys
    sys.path.insert(0, str(BOARD.parents[1]))
    import place_identity
    assert place_identity.apply(TXT) == TXT
