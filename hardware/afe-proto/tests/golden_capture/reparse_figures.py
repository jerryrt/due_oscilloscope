"""Re-derive the `figures` of the OLD tools' goldens from their raw text with the current parser (capture_old.figures).
The raw text and every other field are kept; each rewritten file gets "figures_reparsed": true. Idempotent. No pcbnew.

    python tests/golden_capture/reparse_figures.py [--src DIR] [--out DIR | --into-golden]

Reads --src (default: the committed tests/golden/v2-8a1f7ac, read only) and writes the files to the output folder.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
import capture_old as CO  # noqa: E402


def main(argv=None):
    out_dir, a = C.parse_out(__doc__, argv, extra=lambda ap: ap.add_argument('--src', default=C.GOLDEN_V2))
    n = 0
    for f in sorted(glob.glob(os.path.join(a.src, '*lr_check*.json')) + glob.glob(os.path.join(a.src, '*.cap.json'))):
        d = json.load(open(f))
        for r in d['rows']:
            r['figures'] = CO.figures(r['detail']) if 'detail' in r else CO.figures(r.get('line', ''))
        d['figures_reparsed'] = True
        json.dump(d, open(os.path.join(out_dir, os.path.basename(f)), 'w'), indent=1, sort_keys=True)
        n += 1
    print('reparsed', n, 'files into', out_dir)
    C.done(a)


if __name__ == '__main__':
    main()
