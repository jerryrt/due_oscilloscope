"""Every per-capacitor record key names a capacitor on the AFE-2 board, so a renumbering that does not remap the records fails here
(POWER is to be renumbered once, with the inverse map; a silent mislabel of C403/C404/C407/C408 would otherwise carry measured distances to the wrong part)."""
import pathlib
import re
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[2]
BOARD = HERE / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'


def board_refs(text):
    return set(re.findall(r'\(property "Reference" "([A-Z]+\d+)"', text))


def record_keys():
    sys.path.insert(0, str(HERE))
    from pcbtools.boards import gate3_v2
    from simtools import pw2
    keys = {'gate3_v2.POWER_CAPS': set(gate3_v2.POWER_CAPS['caps']), 'pw2.DIST_MM': set(pw2.DIST_MM)}
    for _, caps in pw2.GROUPS.values():
        keys.setdefault('pw2.GROUPS', set()).update(caps)
    src = (HERE / 'v2' / 'sim' / 'powercal' / 'pw2_ac' / 'pw2_ac.py').read_text()
    for name in ('DIST_MM', 'VIA_COUNT'):
        m = re.search(r'^%s = \{(.*?)\}' % name, src, re.S | re.M)
        keys['pw2_ac.' + name] = set(re.findall(r'"([A-Z]+\d+)"', m.group(1)))
    return keys


def missing(keys, refs):
    return {k: sorted(v - refs) for k, v in keys.items() if v - refs}


def test_every_per_capacitor_record_key_is_on_the_board():
    keys = record_keys()
    assert sum(len(v) for v in keys.values()) >= 30, keys                                  # a floor: the lists were read, not empty
    assert missing(keys, board_refs(BOARD.read_text())) == {}


def test_the_check_fails_when_a_record_names_a_capacitor_the_board_lacks():
    refs = board_refs(BOARD.read_text()) - {'C404'}
    assert missing(record_keys(), refs) != {}
