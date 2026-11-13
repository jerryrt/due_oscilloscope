"""The committed gate-3 packages (v1 and v2) hold no failed broken-once arm.

37da1472 committed a v1 package whose section 5.1 had one arm at NO (agree false in data/proof5v.json), and the full gate stayed green: nothing
read the committed data. This reads it. For each board: every arm the design's PROOF table lists is in data/proof5v.json and in the GATE3.md
table, and none of them is NO. Pure text and JSON; broken on purpose below (a NO, a missing arm, and 37da1472's own proof5v.json)."""
import json
import pathlib
import re

import pytest

from pcbtools.boards import gate3_v1, gate3_v2

P = pathlib.Path(__file__).resolve().parents[2]
PACKAGES = {'v1': (P / 'kicad' / 'gate3', gate3_v1), 'v2': (P / 'v2' / 'layout' / 'gate3', gate3_v2)}


def problems(data, md, proof):
    """[what is wrong] with a package's broken-once arms: data is proof5v.json's arms, md the GATE3.md text, proof the table's PROOF"""
    want = [a[0] for a in proof['arms']]
    assert want, 'the table lists no arm: the check would look at nothing'
    out = []
    got = {a['label']: a for a in data['arms']}
    for label in want:
        if label not in got:
            out.append(f'arm {label!r} is not in proof5v.json')
        elif not got[label]['agree']:
            out.append(f'arm {label!r} has agree false in proof5v.json')
        elif not got[label]['removed_from_text'] == 1:
            out.append(f'arm {label!r} cut {got[label]["removed_from_text"]} tracks')
    out += [f'proof5v.json holds an arm the table does not list: {k!r}' for k in got if k not in want]
    rows = {m.group(1): m.group(2) for m in re.finditer(r'^\| ([^|]+?) \| [^|]*\|[^\n]*\| (yes|\*\*NO\*\*) \|$', md, re.M) if m.group(1) in want}
    for label in want:
        if label not in rows:
            out.append(f'arm {label!r} is not in the GATE3.md table')
        elif rows[label] != 'yes':
            out.append(f'arm {label!r} reads NO in GATE3.md')
    return out


def _load(design):
    d, T = PACKAGES[design]
    return json.loads((d / 'data' / 'proof5v.json').read_text()), (d / 'GATE3.md').read_text(), T.PROOF


@pytest.mark.parametrize('design', sorted(PACKAGES))
def test_the_committed_package_has_every_arm_and_none_failed(design):
    assert problems(*_load(design)) == []


@pytest.mark.parametrize('design', sorted(PACKAGES))
def test_broken_once_a_failed_arm_is_caught(design):
    data, md, proof = _load(design)
    data['arms'][-1]['agree'] = False
    got = problems(data, md, proof)
    assert len(got) == 1 and 'agree false' in got[0], got
    bad = re.sub(r'\| yes \|$', '| **NO** |', md, count=0, flags=re.M)
    assert any('reads NO' in x for x in problems(*_load(design)[:1], bad, proof))


@pytest.mark.parametrize('design', sorted(PACKAGES))
def test_broken_once_a_missing_arm_is_caught(design):
    data, md, proof = _load(design)
    gone = data['arms'].pop(0)
    assert problems(data, md, proof) == [f'arm {gone["label"]!r} is not in proof5v.json']
    data, md, proof = _load(design)
    data['arms'].append(dict(data['arms'][0], label='an arm nobody asked for'))
    assert 'an arm nobody asked for' in problems(data, md, proof)[0]
