"""Loading a board config must leave no plain-named module of that board in sys.modules and nothing on sys.path: two boards
loaded in one process each see their own floorplan, and a later plain `import floorplan` is not served from a fixture."""
import pathlib
import subprocess
import sys

pcbtools_root = pathlib.Path(__file__).resolve().parents[2]

PLAIN = ('design', 'floorplan', 'layout', 'sexpr', 'build_sch', 'build_pcb')

CODE = r'''
import sys, pathlib
sys.dont_write_bytecode = True
sys.path.insert(0, {root!r})
before = list(sys.path)
from pcbtools.boards import v1, v2
assert sys.path == before, 'a board config changed sys.path'
fx = [k for k in PLAIN if k in sys.modules and 'fixtures' in (getattr(sys.modules[k], '__file__', '') or '')]
assert not fx, f'plain-named fixture modules left in sys.modules: {{fx}}'
assert v1._floorplan is not v2._floorplan and v1._floorplan.__file__ != v2._floorplan.__file__
from pcbtools.boards import v1_frozen
assert v1._floorplan.__file__.replace('\\\\', '/').endswith('kicad/floorplan.py') and 'v2-8a1f7ac' in v2._floorplan.__file__
assert 'v1-34b2e51' in v1_frozen._floorplan.__file__ and v1_frozen._floorplan is not v1._floorplan       # live and frozen v1 side by side
assert v1.FENCES != v2.FENCES
assert v1._layout.__name__.startswith('pcbtools._fixture_v1.') and 'v1' not in v2._layout.__file__
try:
    import floorplan
except ImportError:
    pass
else:
    raise AssertionError('a plain "import floorplan" found ' + floorplan.__file__)
print('ok')
'''.replace('PLAIN', repr(PLAIN))


def run(root, extra=''):
    return subprocess.run([sys.executable, '-c', CODE.format(root=str(root)).replace("print('ok')", extra + "\nprint('ok')")],
                          capture_output=True, text=True)


def test_two_boards_in_one_process_do_not_see_each_other():
    r = run(pcbtools_root)
    assert r.returncode == 0 and r.stdout.strip() == 'ok', r.stderr[-600:]


def test_building_the_cfgs_leaves_no_plain_modules_either():
    code = r"""
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, %r)
from pcbtools.boards import v1
v1.sch_cfg(); v1.pcb_cfg(); v1.pcb_place()
left = [k for k in ('design', 'sexpr', 'build_sch', 'layout', 'floorplan') if k in sys.modules]
assert not left, left
print('ok')
""" % str(pcbtools_root)
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == 'ok', r.stderr[-600:]
