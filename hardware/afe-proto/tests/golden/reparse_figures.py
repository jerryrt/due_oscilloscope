"""Re-derive the `figures` of the OLD tools' goldens from their raw text with the current parser (capture_old.figures).
The raw text and every other field are kept; each rewritten file gets "figures_reparsed": true. Idempotent.
    python tests/golden/reparse_figures.py        (no pcbnew; plain json)"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('OLD_TOOLS_DIR', '.')      # capture_old reads it at import; the parser needs none
import capture_old as C   # noqa: E402

n = 0
for f in sorted(sorted(glob.glob(os.path.join(HERE, 'v2-8a1f7ac', '*lr_check*.json')) + glob.glob(os.path.join(HERE, 'v2-8a1f7ac', '*.cap.json')))):
    d = json.load(open(f))
    for r in d['rows']:
        r['figures'] = C.figures(r['detail']) if 'detail' in r else C.figures(r.get('line', ''))
    d['figures_reparsed'] = True
    json.dump(d, open(f, 'w'), indent=1, sort_keys=True)
    n += 1
print('reparsed', n, 'files')
