"""The committed v1 board carries the identity its configuration states (pcbtools/identity.py is the checker; the numbers are boards/v1.py's),
the live config switches the identity and arrow rules on and the frozen one leaves them off."""
import pathlib
import re

from pcbtools import identity, silkarrows
from pcbtools.boards import v1, v1_frozen

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'kicad' / 'afe-proto.kicad_pcb'
TXT = BOARD.read_text()


def test_the_config_says_what_the_owner_ruled():
    assert (v1.NAME, v1.MODEL, v1.REV) == ('COPPIA', 'AFE-1', 'A')
    assert v1.ID_LINE == 'AFE-1  REV A' and v1.FILE_STEM == 'COPPIA-AFE-1-REVA'
    assert v1.IDENT['name'][2] == 2.0 and v1.IDENT['line'][2] == 1.2 and v1.IDENT['sn_label'][2] == 1.0 and v1.IDENT['jlc'][2] == 1.0
    assert set('IOQSXZ').isdisjoint(v1.REV) and f'(rev "{v1.REV}")' in TXT      # the title block reads it too


def test_the_board_carries_exactly_the_configured_identity_and_no_arrow():
    assert identity.findings(TXT, v1) == []
    top = [m.group(1) for m in re.finditer(r'\(gr_text "([^"]*)"[^\n]*\n[^\n]*\n\t\t\(layer "F.SilkS"', TXT)]
    assert top.count(v1.NAME) == 1 and top.count(v1.ID_LINE) == 1 and top.count(v1.SN_LABEL) == 1
    assert [t for t in top if 'REV' in t] == [v1.ID_LINE]
    assert silkarrows.arrowheads(silkarrows.silk_segments(TXT)) == [] and v1.ARROWS == []


def test_the_identity_breaks_when_the_silk_text_changes():
    assert identity.findings(TXT.replace('"COPPIA"', '"COPPIX"', 1), v1)
    assert identity.findings(TXT.replace('"AFE-1  REV A"', '"AFE-1  REV B"', 1), v1)


def test_the_live_config_switches_the_rule_on_and_the_frozen_one_does_not():
    assert v1.IDENTITY_CHECK is True and v1_frozen.IDENTITY_CHECK is False
    assert {v1.NAME, v1.ID_LINE, v1.SN_LABEL} <= set(v1.SILK_WORDS) and v1.NAME not in v1_frozen.SILK_WORDS
