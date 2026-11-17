"""python3 rowcheck.py BOARD [rows...]   (in the image, cwd hardware/afe-proto): the LR rows with the scratch outline table (hand/outlines_new.py) in place of v2/layout/outlines.py, which stays untouched."""
import sys, types, importlib, importlib.util
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools.boards import v2_layout as C
spec = importlib.util.spec_from_file_location('outl_new', '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/outlines_new.py'); t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
m = types.ModuleType('pcbtools.boards.v2s')
m.__dict__.update({k: getattr(C, k) for k in dir(C) if not k.startswith('__')})
m.OUTLINE = {k: list(v) for k, v in t.RECTS.items()}
m.BNC_X = t.BNC_X; m.SHARED_PARTS = dict(t.SHARED_PARTS)
sys.modules['pcbtools.boards.v2s'] = m
from pcbtools import check as CK
sys.exit(CK.main([sys.argv[1], '--config', 'v2s', '--no-drc'] + (['--rows'] + sys.argv[2:] if len(sys.argv) > 2 else [])))
