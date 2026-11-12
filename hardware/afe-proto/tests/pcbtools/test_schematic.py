"""schematic.py is checked against the OLD builder (the frozen v1 build_sch.py at 34b2e51): same design in, byte-identical
files out. The pure helpers are tested with known answers and need no KiCad."""
import importlib.util
import math
import os
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

from pcbtools import schematic as sch
from pcbtools import sexpr as sx

FIX = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'v1-34b2e51' / 'kicad'
SYMDIR = os.environ.get('KICAD_SYMBOL_DIR', '/usr/share/kicad/symbols')


# ------------------------------------------------------------------------------------------------ pure helpers
def test_rot_quarter_turns():
    assert sch.rot(1.0, 0.0, 0) == (1.0, 0.0)
    assert sch.rot(1.0, 0.0, 90) == (0.0, -1.0)
    assert sch.rot(0.0, 1.0, 90) == (-1.0, 0.0)      # library y up -> screen y down, then a quarter turn counter-clockwise on screen
    assert tuple(abs(v) for v in sch.rot(1.0, 0.0, 180)) == (1.0, 0.0) and sch.rot(1.0, 0.0, 180)[0] == -1.0


@pytest.mark.parametrize('angle,r,want', [(0, 0, (-1, 0)), (180, 0, (1, 0)), (90, 0, (0, 1)), (270, 0, (0, -1)),
                                          (0, 90, (0, 1))])
def test_out_dir(angle, r, want):
    got = sch.out_dir(angle, r)
    assert (round(got[0]), round(got[1])) == want


def test_snap_and_label_len():
    assert sch.snap(2.6) == pytest.approx(2.54) and sch.snap(1.2) == pytest.approx(0.0) and sch.snap(1.3) == pytest.approx(2.54)
    assert sch.label_len('GND') == 5.0


def test_uid_is_deterministic_and_keyed():
    ns = '6f1f0d3e-4a52-4c1b-9a4e-0ad5e0a1f001'
    assert sch.make_uid(ns, 'sym', 'R1', 1) == sch.make_uid(ns, 'sym', 'R1', 1)
    assert sch.make_uid(ns, 'sym', 'R1', 1) != sch.make_uid(ns, 'sym', 'R2', 1)


def test_box_symbol_geometry():
    s = sch.box_symbol('X', [('1', 'A', 'input', 'L', 0), ('2', 'B', 'output', 'R', 1), ('3', 'C', 'power_in', 'T', 0)],
                       width=10.16)
    pins = [x for x in sx.find(s[-1], 'pin')]
    assert len(pins) == 3
    ats = {sx.first(p, 'number')[1]: [float(v) for v in sx.first(p, 'at')[1:]] for p in pins}
    hw = 10.16 / 2
    assert ats['1'][0] == pytest.approx(-hw - 2 * sch.G) and ats['1'][2] == 0           # left pin points right (angle 0)
    assert ats['2'][0] == pytest.approx(hw + 2 * sch.G) and ats['2'][2] == 180
    assert ats['3'][2] == 270
    body = sx.find(s[-2], 'rectangle')[0]
    assert float(sx.first(body, 'start')[1]) == pytest.approx(-hw)


def test_rename_sub_requires_the_old_prefix():
    assert sch.rename_sub(['symbol', sx.Q('A_1_1')], 'A', 'B')[1] == 'B_1_1'
    with pytest.raises(ValueError):
        sch.rename_sub(['symbol', sx.Q('C_1_1')], 'A', 'B')


def test_a_cell_lays_pins_out_around_the_origin(tmp_path):
    lib = tmp_path / 'p.kicad_sym'
    lib.write_text(sch.project_lib_text([sch.box_symbol('Q', [('1', 'A', 'input', 'L', 0), ('2', 'B', 'output', 'R', 0)], 7.62)]))
    library = sch.Library(str(tmp_path), str(lib))
    c = sch.Cell(dict(sym='afe:Q', pins={'1': 'IN', '2': 'OUT'}), library)
    assert c.units == [1] and c.minx < 0 < c.maxx and c.w > 0 and c.h > 0
    (u, dx, pl), = c.items
    assert {q[0] for q in pl} == {'1', '2'} and {q[5] for q in pl} == {'IN', 'OUT'}


# ------------------------------------------------------------------------------------------------ equivalence with the old builder
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.pcbnew
def test_byte_identical_to_the_old_builder_on_the_v1_design(tmp_path):
    if not os.path.isdir(SYMDIR):
        pytest.skip(f'no KiCad symbol libraries at {SYMDIR}')
    old_dir = tmp_path / 'old'
    shutil.copytree(FIX, old_dir)
    for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table', 'lib/afe.kicad_sym'):
        (old_dir / f).unlink(missing_ok=True)
    r = subprocess.run([sys.executable, '-I', str(old_dir / 'build_sch.py')], cwd=old_dir, capture_output=True, text=True,
                       env=dict(os.environ, KICAD_SYMBOL_DIR=SYMDIR))
    assert r.returncode == 0, r.stderr[-400:]
    sys.path.insert(0, str(old_dir))
    try:
        design = _load('v1_design_fixture', old_dir / 'design.py')
        oldmod = _load('v1_build_sch_fixture', old_dir / 'build_sch.py')
    finally:
        sys.path.remove(str(old_dir))

    def exclusions(pin_at, uid, root):
        pg = pin_at[('U401', '1')]
        return [[f"pin_to_pin|{round(pg[0] * 1e4)}|{round(pg[1] * 1e4)}|{uid('pin', 'U401', 1, '1')}|{uid('pin', '#FLG01', 1, '1')}"
                 f"|/{root}|/{root}|/{root}", 'PGOOD unused, tied to GND per SNVSAF7C; GND carries the PWR_FLAG']]
    tmux = sch.box_symbol('TMUX1119', [
        ('4', 'S1', 'passive', 'L', 0), ('6', 'S2', 'passive', 'L', 2), ('1', 'SEL', 'input', 'L', 4),
        ('5', 'D', 'passive', 'R', 1), ('2', 'VDD', 'power_in', 'T', 1), ('3', 'GND', 'power_in', 'B', 1)],
        width=10.16, fp=design.SC706, ds='https://www.ti.com/lit/ds/symlink/tmux1119.pdf',
        desc='SPDT 5 V analog switch, SC70-6 (SCDS401C table 4-1): SEL low = S1-D')
    cfg = types.SimpleNamespace(
        PROJECT='afe-proto', NS=str(oldmod.NS), BLOCK_ORDER=oldmod.ORDER, BLOCK_TITLE=oldmod.BLOCK_TITLE,
        PWR_FLAG_NETS=oldmod.PWR_FLAG_NETS, TITLE='AFE full range design 01: AFE shield for the Arduino Due', REV='FR-01',
        COMMENTS=['Generated by hardware/afe-proto/kicad/build_sch.py from design.py: edit those, not this file',
                  'Values and parts: whatif/bom.txt. Connectivity: the simulated circuit (docs/architecture.md)',
                  'Own work, CC BY-SA 4.0'],
        PROJECT_SYMBOLS=[tmux], ERC_EXCLUSIONS=exclusions, SYMBOL_DIR=SYMDIR)
    new_dir = tmp_path / 'new'
    sch.write_all(design.PARTS, cfg, str(new_dir))
    for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table', 'lib/afe.kicad_sym'):
        assert (new_dir / f).read_bytes() == (old_dir / f).read_bytes(), f
