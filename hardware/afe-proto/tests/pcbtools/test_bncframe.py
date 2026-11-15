"""pcbtools.bncframe: the BNCs' designators and function labels at one offset in each frame (D30 (2)); J605's designator held at its place. Pure text."""
import pathlib
import re
import types

from pcbtools import bncframe as F
from pcbtools import silkapply as A
from pcbtools.boards import v2_layout as C

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
CFG = types.SimpleNamespace(BNC_LABELS=C.BNC_LABELS, BNC_LABEL_OFFSET=C.BNC_LABEL_OFFSET, BNC_DESIGNATOR_OFFSET=C.BNC_DESIGNATOR_OFFSET, DESIGNATOR_AT=C.DESIGNATOR_AT)


def offsets(text):
    out = {}
    for ref, word in C.BNC_LABELS.items():
        ox, oy, _ = F._origin(text, ref)
        m = F._label(text, word)
        out[ref] = (round(float(m.group(1)) - 50 - ox, 3), round(150 - float(m.group(2)) - oy, 3))
    return out


def test_every_bnc_has_the_first_ones_offsets_and_a_second_pass_changes_nothing():
    new = F.apply(BOARD.read_text(), CFG)
    o = offsets(new)
    assert len({v for v in o.values()}) == 1, o
    assert F.apply(new, CFG) == new


def test_the_three_bnc_designators_are_on_the_bottom_silk_mirrored_at_one_offset_and_J605s_is_not():
    new = F.apply(BOARD.read_text(), CFG)
    seen = set()
    for ref, layer, mirrored in (('J101', 'B.SilkS', True), ('J201', 'B.SilkS', True), ('J301', 'B.SilkS', True), ('J605', 'F.SilkS', False)):
        s, e = A._span(new, ref)
        m = re.search(r'\(property "Reference" "%s"\n\t\t\t\(at ([-\d.]+) ([-\d.]+)[^)]*\)\n\t\t\t\(layer "%s"\)(.*?)\n\t\t\)' % (ref, layer), new[s:e], re.S)
        assert m, ref
        assert ('(justify mirror)' in m.group(3)) == mirrored, ref
        if layer == 'B.SilkS':
            seen.add((m.group(1), m.group(2)))
    assert len(seen) == 1, seen                                                              # the same offset in each (equally turned) frame


def test_the_check_has_teeth_a_label_moved_off_its_offset_is_seen_by_the_comparison():
    new = F.apply(BOARD.read_text(), CFG)
    m = F._label(new, 'CH2 IN')
    bad = new.replace(m.group(0), m.group(0).replace(f'(at {m.group(1)} {m.group(2)}', f'(at {float(m.group(1)) + 0.2:g} {m.group(2)}', 1), 1)
    assert len({v for v in offsets(bad).values()}) == 2
