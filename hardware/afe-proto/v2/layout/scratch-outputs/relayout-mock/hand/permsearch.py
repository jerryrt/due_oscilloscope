"""python3 permsearch.py BASE.kicad_pcb ITER NAME=SPEC [NAME=SPEC ...]: build each ladder slot permutation (permute.py), run pf.py and print METRIC. Two at a time."""
import subprocess, sys, re
from concurrent.futures import ThreadPoolExecutor
base, it, *items = sys.argv[1:]
def run(item):
    name, spec = item.split('=', 1)
    brd = 'ps_%s.kicad_pcb' % name
    subprocess.run(['python3', 'permute.py', base, brd, spec], capture_output=True)
    subprocess.run(['cp', base.replace('.kicad_pcb', '.kicad_pro'), brd.replace('.kicad_pcb', '.kicad_pro')])
    out = subprocess.run(['python3', '-u', 'pf.py', brd, 'ps_%s_spec.py' % name, it, '600'], capture_output=True, text=True).stdout
    m = re.search(r'METRIC conflict_segments (\d+) distinct_clusters (\d+)', out)
    open('ps_%s.txt' % name, 'w').write(out)
    return name, (int(m.group(1)), int(m.group(2))) if m else None
with ThreadPoolExecutor(2) as ex:
    for name, met in ex.map(run, items):
        print('PERM', name, met, flush=True)
