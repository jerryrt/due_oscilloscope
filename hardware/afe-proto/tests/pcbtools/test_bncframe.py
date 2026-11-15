"""pcbtools.bncframe: the BNCs' designators and function labels at one offset in each frame (D30 (2)); J605's designator held at its place. Pure text."""
import pathlib
import re
import types

from pcbtools import bncframe as F
from pcbtools import silkapply as A
from pcbtools.boards import v2_layout as C

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
CFG = types.SimpleNamespace(BNC_LABELS=C.BNC_LABELS, BNC_LABEL_OFFSET=C.BNC_LABEL_OFFSET, DESIGNATOR_AT=C.DESIGNATOR_AT)


def offsets(text):
    out = {}
    for ref, word in C.BNC_LABELS.items():
        ox, oy, _ = F._origin(text, ref)
        m = F._label(text, word)
        out[ref] = (round(float(m.group(1)) - 50 - ox, 3), round(150 - float(m.group(2)) - oy, 3), tuple(round(v, 3) for v in F._designator_offset(text, ref)))
    return out


def test_every_bnc_has_the_first_ones_offsets_and_a_second_pass_changes_nothing():
    new = F.apply(BOARD.read_text(), CFG)
    o = offsets(new)
    assert len({v for v in o.values()}) == 1, o
    assert F.apply(new, CFG) == new


def test_the_check_has_teeth_a_label_moved_off_its_offset_is_seen_by_the_comparison():
    new = F.apply(BOARD.read_text(), CFG)
    m = F._label(new, 'CH2 IN')
    bad = new.replace(m.group(0), m.group(0).replace(f'(at {m.group(1)} {m.group(2)}', f'(at {float(m.group(1)) + 0.2:g} {m.group(2)}', 1), 1)
    assert len({v for v in offsets(bad).values()}) == 2
