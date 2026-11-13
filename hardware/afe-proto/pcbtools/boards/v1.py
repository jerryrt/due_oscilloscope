"""BoardConfig of the AFE v1 board: the tables fence.py (and, as they are ported, the rules) read, as module-level names so a
test can build a config from plain values (a types.SimpleNamespace with the same names works).

Values that already exist in design.py / floorplan.py / layout.py are imported from them, not copied: `_load_sources()` is
the ONE place that knows where those files are (the frozen fixture folder of commit 34b2e51, relative to this package); it
will switch to the live v1 files when v1's layout reaches main through review. The tables that lived only inside the old
fence_check.py are written here, each with its origin.
"""
import importlib.util
import os
import sys

NAME = 'v1'
HERE = os.path.dirname(os.path.abspath(__file__))
# pcbtools/boards -> pcbtools -> hardware/afe-proto
SOURCE_DIR = os.path.normpath(os.path.join(HERE, '..', '..', 'tests', 'fixtures', 'v1-34b2e51', 'kicad'))


def _load_sources():
    """import design, floorplan and layout from SOURCE_DIR under private names (nothing is put on sys.path)"""
    mods = {}
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True               # the fixture folder is frozen: importing it must not leave __pycache__ in it
    added = SOURCE_DIR not in sys.path
    if added:
        sys.path.insert(0, SOURCE_DIR)           # design.py imports its siblings by plain name; undone below
    try:
        for name in ('design', 'floorplan', 'layout'):
            spec = importlib.util.spec_from_file_location(f'_pcbtools_v1_{name}', os.path.join(SOURCE_DIR, name + '.py'))
            m = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = m
            spec.loader.exec_module(m)
            mods[name] = m
    finally:
        sys.dont_write_bytecode = keep
        if added:
            sys.path.remove(SOURCE_DIR)
    return mods['design'], mods['floorplan'], mods['layout']


_design, _floorplan, _layout = _load_sources()

BOARD = None                                  # default board path: the caller names it
PARTS = _design.PARTS
PLACE = dict(_layout.PLACE)
FENCES = {b: list(rs) for b, rs in _floorplan.FENCES.items()}           # floorplan.py: POWER, REFCAL, AWG, SCOPE
# fence_check.py CONFIG (34b2e51): hundreds digit of a designator -> block; SCOPE owns 1xx and 2xx; 6xx is nobody's
HUNDREDS = {'1': 'SCOPE', '2': 'SCOPE', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': None}
OWNER_OVERRIDE = {}                           # none for v1: the bridges already carry their block's digit
TOL_MM = 0.001                                # position tolerance of the fence rule
