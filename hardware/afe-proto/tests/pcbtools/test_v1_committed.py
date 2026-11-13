"""The committed v1 schematic, project and tables (hardware/afe-proto/kicad) are the generator's output for the LIVE design: regenerated from
boards/v1.py with PCBTOOLS_V1_SOURCE=kicad they are byte-identical. The guard against a committed file that disagrees with the design (the
schematic had old designators; v2's project file was stale in the same way). The arm: a changed part value must change the schematic."""
import copy
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.pcbnew

AFE = pathlib.Path(__file__).resolve().parents[2]
FILES = ('afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table', 'lib/afe.kicad_sym')

SCRIPT = '''
import copy, json, subprocess, sys
from pcbtools import schematic as sch
from pcbtools.boards import v1
out, change = sys.argv[1], sys.argv[2] == "change"
parts = copy.deepcopy(v1.PARTS)
if change:
    next(p for p in parts if p["value"] == "22 1%")["value"] = "22R 1%"
sch.write_all(parts, v1.sch_cfg(), out)
subprocess.run(["kicad-cli", "sch", "upgrade", out + "/afe-proto.kicad_sch"], capture_output=True, check=True)
'''


def _generate(out, change):
    env = dict(os.environ, PCBTOOLS_V1_SOURCE=str(AFE / 'kicad'))
    r = subprocess.run([sys.executable, '-c', SCRIPT, str(out), 'change' if change else 'same'], cwd=AFE, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]


def test_the_committed_v1_schematic_is_the_live_designs_output(tmp_path):
    if not shutil.which('kicad-cli') or not os.path.isdir('/usr/share/kicad/symbols'):
        pytest.skip('no kicad-cli or KiCad symbol libraries')
    _generate(tmp_path / 'a', False)
    for f in FILES:
        assert (tmp_path / 'a' / f).read_bytes() == (AFE / 'kicad' / f).read_bytes(), f
    _generate(tmp_path / 'b', True)                                                        # the arm: one changed value shows
    assert (tmp_path / 'b' / 'afe-proto.kicad_sch').read_bytes() != (AFE / 'kicad' / 'afe-proto.kicad_sch').read_bytes()


def test_the_bnc_pitches():
    """owner ruling 2026-11-13: the scope BNCs SCOPE_PITCH (17.78 mm) apart and the AWG BNC at least SCOPE_PITCH + 1.0 mm below J201, on the config and on the committed board; the same positions as v2"""
    import re
    from pcbtools.boards import v1
    ys = [v1.BNCS[r] for r in ('J101', 'J201', 'J301')]
    assert abs((ys[0] - ys[1]) - v1.SCOPE_PITCH) < 1e-9 and (ys[1] - ys[2]) >= v1.AWG_BNC_GAP_MIN - 1e-9
    txt = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'kicad', 'afe-proto.kicad_pcb')).read()
    got = {}
    for ref in v1.BNCS:
        k = txt.index('(property "Reference" "%s"' % ref)
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+)', txt[txt.rfind('(footprint ', 0, k):k])
        got[ref] = 150.0 - float(at.group(2))                       # KiCad y -> Due y
    assert {k: round(v, 3) for k, v in got.items()} == {k: round(v, 3) for k, v in v1.BNCS.items()}, got


def test_the_bnc_gap_rule_fails_when_the_awg_is_too_close():
    """broken on purpose: J301 moved up to 24.13 - 17.78 + 0.5 would sit inside the rule"""
    from pcbtools.boards import v1
    assert (v1.BNCS['J201'] - 18.0) < v1.AWG_BNC_GAP_MIN - 1e-9 and (v1.BNCS['J201'] - v1.BNCS['J301']) >= v1.AWG_BNC_GAP_MIN
