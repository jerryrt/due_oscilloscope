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
from pcbtools.boards import v1_build as v1b

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
    """import a module from a COPY of the fixture in a temp dir, without writing bytecode anywhere"""
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode = old
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
    parts, cfg = v1b.sch_inputs(str(old_dir))
    new_dir = tmp_path / 'new'
    sch.write_all(parts, cfg, str(new_dir))
    for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table', 'lib/afe.kicad_sym'):
        assert (new_dir / f).read_bytes() == (old_dir / f).read_bytes(), f
