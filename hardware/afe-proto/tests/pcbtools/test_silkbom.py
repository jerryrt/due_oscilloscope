"""pcbtools.silkbom: the dense blocks' leftover labels, re-placed inside their block or left to the BOM, by the config. Real board text (pcbnew reads it)."""
import pathlib
import types

import pytest

from pcbtools import silkbom
from pcbtools.boards import v2_layout as C

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
pytestmark = pytest.mark.pcbnew


def cfg(**kw):
    d = {k: getattr(C, k) for k in dir(C) if k.isupper()}
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_the_board_of_record_has_nothing_more_to_do_and_a_second_run_is_idempotent():
    text = BOARD.read_text()
    new, replaced, hid, left = silkbom.run(text, cfg())
    assert new == text and replaced == [] and hid == {}
    assert sorted(x.split(':')[0] for x in left) == ['R208', 'U502']   # the two must-label parts with no place that meets the rule (named in the config); C104 and BR101 are SILK_EXEMPT


def test_the_check_has_teeth_a_part_taken_off_the_list_is_found_again():
    text = BOARD.read_text()
    bom = dict(C.SILK_TO_BOM)
    bom.pop('R302')                                          # R302's label is on its own body: off the list it is hidden again, or re-placed
    new, replaced, hid, left = silkbom.run(text, cfg(SILK_TO_BOM=bom))
    assert new != text or hid or replaced
