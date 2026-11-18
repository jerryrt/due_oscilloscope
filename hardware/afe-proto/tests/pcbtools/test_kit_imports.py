"""The AFE imports pcbkit directly and names its coordinate frame at every call. Three guards, each broken on purpose when written:
  * the bindings that used to stand between them (pcbtools.boardio, geom and shapes) are gone, and nothing imports them;
  * every call of pcbkit.board's readers and transforms in AFE code passes a frame (there is no default: pcbkit.board raises
    without one, and this scan finds the call that would);
  * no AFE function takes the frame as a defaulted parameter, or binds it with functools.partial: that is the hidden default again, one level up."""
import ast
import os

import pytest

AFE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))       # hardware/afe-proto
REMOVED = ('boardio', 'geom', 'shapes')
FRAMED = {'read_board': 2, 'read_board_retry': 2, 'to_frame': 3, 'from_frame': 3}        # name -> positional arguments that include the frame


def sources():
    out = []
    for d, ds, fs in os.walk(AFE):
        ds[:] = [x for x in ds if x not in ('fixtures', '.scratch', '__pycache__', 'golden_capture') and not x.startswith('.')]
        out += [os.path.join(d, f) for f in fs if f.endswith('.py')]
    return sorted(out)


def parse(path):
    return ast.parse(open(path).read(), path)


def imports_of_removed(tree):
    """(line, text) of every import of pcbtools.boardio / geom / shapes, in any form"""
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ''
            if n.level and mod in REMOVED or mod in ['pcbtools.' + r for r in REMOVED]:
                bad.append((n.lineno, mod))
            if (n.level and not mod) or mod == 'pcbtools':
                bad += [(n.lineno, a.name) for a in n.names if a.name in REMOVED]
        elif isinstance(n, ast.Import):
            bad += [(n.lineno, a.name) for a in n.names if a.name in ['pcbtools.' + r for r in REMOVED]]
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == '__import__' and n.args \
                and isinstance(n.args[0], ast.Constant) and n.args[0].value in ['pcbtools.' + r for r in REMOVED]:
            bad.append((n.lineno, n.args[0].value))
    return bad


def unframed_calls(tree):
    """(line, name) of a call of read_board, read_board_retry, to_frame or from_frame that passes no frame. Only pcbkit.board's are meant: KB.x / K.x / board.x / B.x,
    and a bare name the file imported from pcbkit.board (v2/bom/order.py has a read_board of its own, a BOM reader)"""
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == 'pcbkit.board' for a in n.names}
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if name in FRAMED and not (len(n.args) >= FRAMED[name] or any(k.arg in ('cfg', 'frame') for k in n.keywords) or any(isinstance(a, ast.Starred) for a in n.args)):
                if (isinstance(f, ast.Name) and name in imported) or (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ('KB', 'K', 'B', 'board')):
                    bad.append((n.lineno, name))
    return bad


def _is_frame(node):
    return (isinstance(node, ast.Name) and node.id == 'FRAME') or (isinstance(node, ast.Attribute) and node.attr == 'FRAME')


def hidden_frame_defaults(tree):
    """(line, what) of a function parameter whose default is FRAME, or of a functools.partial that binds FRAME"""
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            bad += [(n.lineno, 'default') for d in [*n.args.defaults, *n.args.kw_defaults] if d is not None and _is_frame(d)]
        elif isinstance(n, ast.Call) and (getattr(n.func, 'attr', None) == 'partial' or getattr(n.func, 'id', None) == 'partial'):
            if any(_is_frame(a) for a in [*n.args, *[k.value for k in n.keywords]]):
                bad.append((n.lineno, 'partial'))
    return bad


def test_the_scan_looks_at_the_tree():
    assert len(sources()) > 100                       # a floor: the walk must have found the AFE's code


def test_the_removed_bindings_are_gone():
    for r in REMOVED:
        assert not os.path.exists(os.path.join(AFE, 'pcbtools', r + '.py')), r


def test_nothing_imports_a_removed_binding():
    found = {os.path.relpath(p, AFE): imports_of_removed(parse(p)) for p in sources()}
    assert {k: v for k, v in found.items() if v} == {}


def test_every_reader_and_transform_call_passes_a_frame():
    found = {os.path.relpath(p, AFE): unframed_calls(parse(p)) for p in sources()}
    assert {k: v for k, v in found.items() if v} == {}


def test_no_function_defaults_or_binds_the_frame():
    found = {os.path.relpath(p, AFE): hidden_frame_defaults(parse(p)) for p in sources()}
    assert {k: v for k, v in found.items() if v} == {}


@pytest.mark.parametrize('text, scan, hit', [
    ('from pcbtools import boardio, rules\n', imports_of_removed, True),
    ('from . import geom\n', imports_of_removed, True),
    ('from pcbtools.shapes import Copper\n', imports_of_removed, True),
    ("x = __import__('pcbtools.boardio', fromlist=['x'])\n", imports_of_removed, True),
    ('from pcbtools import rules\nfrom pcbkit import geom\n', imports_of_removed, False),
    ('b = KB.read_board(path)\n', unframed_calls, True),
    ('b = KB.read_board_retry(path)\n', unframed_calls, True),
    ('x, y = KB.to_frame(a, b)\n', unframed_calls, True),
    ('b = KB.read_board(path, FRAME)\n', unframed_calls, False),
    ('x, y = KB.from_frame(a, b, FRAME)\n', unframed_calls, False),
    ('b = read_board(path)\n', unframed_calls, False),                     # a bare name that pcbkit.board did not supply is another function
    ('from pcbkit.board import read_board\nb = read_board(path)\n', unframed_calls, True),
    ('def read_board(path, frame=FRAME):\n    return path\n', hidden_frame_defaults, True),
    ('def f(a, *, frame=KB.FRAME):\n    return a\n', hidden_frame_defaults, True),
    ('r = functools.partial(KB.read_board, frame=FRAME)\n', hidden_frame_defaults, True),
    ('def to_due(p, origin):\n    return p\n', hidden_frame_defaults, False)])
def test_each_scan_fires_on_the_thing_it_guards(text, scan, hit):
    assert bool(scan(ast.parse(text))) is hit
