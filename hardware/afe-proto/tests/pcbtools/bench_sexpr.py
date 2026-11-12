"""One step for the budget runner: parse the frozen v1 board N times and print the fastest as JSON. Run as a child process
under the cap (tests/pcbtools/test_budgets.py); the budget is the median of the image's measurements times a stated margin,
and the figure compared is the MINIMUM of the repeats, which is far steadier than one sample."""
import json
import pathlib
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from pcbtools import sexpr  # noqa: E402

text = (pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'v1-34b2e51' / 'kicad' / 'afe-proto.kicad_pcb').read_text()
n = int(sys.argv[1]) if len(sys.argv) > 1 else 7
best = min((lambda t0: (sexpr.parse(text), time.perf_counter() - t0)[1])(time.perf_counter()) for _ in range(n))
print(json.dumps({'step': 'sexpr_parse', 'repeats': n, 'best_s': round(best, 4), 'bytes': len(text)}))
