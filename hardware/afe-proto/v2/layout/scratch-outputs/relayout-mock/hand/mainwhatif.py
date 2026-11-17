"""in the image, cwd hand/: python3 mainwhatif.py -> mw_<name>_<rounds>.txt and the METRIC lines. Baseline and the three clusters at main's placement, 3 round counts each."""
import subprocess, re
from concurrent.futures import ThreadPoolExecutor
COM = '/work/hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb'
CL = {'refcal': 'C501 C502 C503 J501 R501 R502 R503 R504 R505 R506 R507 R508 R509 R510 R511 R512 R513 R514 TP501 U501 U502'.split(),
      'power': 'C401 C402 C403 C404 C405 C406 C407 C408 C409 R401 R402 R403 R404 R405 R406 R407 TP401 TP402 TP403 TP404 U401'.split(),
      'awg': 'C301 C303 C304 C305 C306 R301 R302 R303 R304 R305 R306 R307 R308 R309 TP301 U301'.split()}
def sh(c): return subprocess.run(c, capture_output=True, text=True).stdout
for nofb in (0, 1):
    spec = 'fixed_noGND_noFB.py' if nofb else 'fixed_noGND.py'
    sh(['python3', 'hr.py', COM, 'mw_base%d.kicad_pcb' % nofb, spec]); sh(['cp', 'fixed.kicad_pro', 'mw_base%d.kicad_pro' % nofb])
jobs = []
for rounds in (8, 10, 12):
    jobs.append(('base0', 'mw_base0.kicad_pcb', rounds)); jobs.append(('base1', 'mw_base1.kicad_pcb', rounds))
for name, refs in CL.items():
    nofb = 1 if name == 'awg' else 0
    brd = 'mw_%s.kicad_pcb' % name
    sh(['python3', 'setpos.py', 'mw_base%d.kicad_pcb' % nofb, brd, 'main_vs_cur.json'] + refs); sh(['cp', 'fixed.kicad_pro', brd.replace('.kicad_pcb', '.kicad_pro')])
    for rounds in (8, 10, 12):
        jobs.append((name, brd, rounds))
def run(j):
    name, brd, rounds = j
    out = sh(['python3', '-u', 'pf.py', brd, 'mw_%s_%d_spec.py' % (name, rounds), str(rounds), '600'])
    open('mw_%s_%d.txt' % (name, rounds), 'w').write(out)
    m = re.search(r'METRIC conflict_segments (\d+) distinct_clusters (\d+)', out)
    return name, rounds, (int(m.group(1)), int(m.group(2))) if m else None
with ThreadPoolExecutor(2) as ex:
    for r in ex.map(run, jobs):
        print('MW', *r, flush=True)
