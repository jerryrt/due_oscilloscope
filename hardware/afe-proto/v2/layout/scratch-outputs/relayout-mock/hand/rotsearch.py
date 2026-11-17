"""python3 rotsearch.py BASE.kicad_pcb ITER REF [REF ...]   (in the image, cwd hand/): for each ref, turn it 180 degrees in place on a scratch copy, run pf.py
(ITER iterations) and print the METRIC line; '-' is the unturned baseline. Two runs at a time."""
import subprocess, sys, os, re
from concurrent.futures import ThreadPoolExecutor
base, it, *refs = sys.argv[1:]
def run(ref):
    tag = ref.replace('+', '_')
    brd = 'rs_%s.kicad_pcb' % tag
    if ref == '-':
        subprocess.run(['cp', base, brd]); subprocess.run(['cp', base.replace('.kicad_pcb', '.kicad_pro'), brd.replace('.kicad_pcb', '.kicad_pro')])
    else:
        subprocess.run(['python3', 'rot180.py', base, brd] + ref.split('+'), capture_output=True)
    out = subprocess.run(['python3', '-u', 'pf.py', brd, 'rs_%s_spec.py' % tag, it, '600'], capture_output=True, text=True).stdout
    m = re.search(r'METRIC conflict_segments (\d+) distinct_clusters (\d+)', out)
    return ref, (int(m.group(1)), int(m.group(2))) if m else None, re.findall(r'^iter.*$', out, re.M)[-1:]
with ThreadPoolExecutor(2) as ex:
    for ref, met, last in ex.map(run, refs):
        print('ROT', ref, met, last, flush=True)
