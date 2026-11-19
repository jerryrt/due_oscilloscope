import sys, collections
sys.path[:0] = ["../pcbkit", "."]
from pcbkit import board as kb, rules
from pcbtools.frame import FRAME
import importlib
cfg = importlib.import_module('pcbtools.boards.' + sys.argv[1])
c = {k: getattr(cfg, k) for k in dir(cfg) if k.startswith(("FILL_", "GND"))}
c["GND"] = "/GND"
for path in sys.argv[2:]:
    b = kb.read_board(path, {"FRAME": FRAME})
    parts, figs = rules.fill_quality_parts(b, c)
    print(path, len(parts), dict(collections.Counter(p[0] for p in parts)))
    for p in parts[:int(__import__('os').environ.get('N', 12))]:
        print("  ", p[0], p[1][:200], round(p[2], 1), round(p[3], 1))
