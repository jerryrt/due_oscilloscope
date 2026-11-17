"""local_eval.py CAND_FIXED BASE_FIXED BASE_ROUTED OPEN_NETS MOVED_REFS WINDOW(x0,y0,x1,y1) [ITER]
Keep the baseline pf copper of every net NOT in OPEN_NETS (and not touching a moved part) as fixed copper on the candidate board, run pf1 on
the open nets only, print: LOCAL clusters_total / clusters_in_window / failed / pad_hits."""
import sys, math, subprocess, re, os
sys.path.insert(0, 'whatif/_scratch')
from pcbtools import boardio
import route_lib as R
cand, basef, baser, openn, moved, win = sys.argv[1:7]
ITER = sys.argv[7] if len(sys.argv) > 7 else '12'
openn = set(openn.split(',')) if openn else set(); moved = set(moved.split(',')) if moved else set()
wx0, wy0, wx1, wy1 = map(float, win.split(','))
bf, br, bc = boardio.read_board(basef), boardio.read_board(baser), boardio.read_board(cand)
def trk(b):
    return {(b.nets[int(b.s_net[k])], round(float(b.s_x0[k]), 2), round(float(b.s_y0[k]), 2), round(float(b.s_x1[k]), 2), round(float(b.s_y1[k]), 2)) for k in range(len(b.s_idx)) if int(b.s_layer[k]) == 0}
fixed0 = trk(bf)
# nets touching a moved part are open too
for j in range(len(bc.p_fp)):
    if bc.fp_ref[int(bc.p_fp[j])] in moved:
        openn.add(bc.nets[int(bc.p_net[j])])
B = R.Board(cand)
segs = []
for k in range(len(br.s_idx)):
    if int(br.s_layer[k]) != 0: continue
    t = (br.nets[int(br.s_net[k])], round(float(br.s_x0[k]), 2), round(float(br.s_y0[k]), 2), round(float(br.s_x1[k]), 2), round(float(br.s_y1[k]), 2))
    if t in fixed0 or t[0] in openn or t[0] == '/GND': continue
    segs.append((t[0], 0, (float(br.s_x0[k]), float(br.s_y0[k])), (float(br.s_x1[k]), float(br.s_y1[k])), float(br.s_w[k]), 'keep'))
B.add(segs, [])
B.save('whatif/_scratch/cand_local.kicad_pcb')
env = dict(os.environ, INFL_HIZ='0.85')
out = subprocess.run([sys.executable, 'whatif/_scratch/pf1.py', 'whatif/_scratch/cand_local.kicad_pcb', 'whatif/_scratch/cand_routed.kicad_pcb', ITER, '300'], env=env, capture_output=True, text=True).stdout
tot = wincl = 0; failed = []
for ln in out.splitlines():
    if ln.startswith('METRIC'): tot = int(ln.split()[-1])
    m = re.match(r'CLUSTER \(([-\d.]+), ([-\d.]+)\)', ln)
    if m and wx0 <= float(m.group(1)) <= wx1 and wy0 <= float(m.group(2)) <= wy1: wincl += 1
    if ln.startswith('iter'): last = ln
    m = re.search(r"failed (\[.*?\])", ln)
    if m: failed = m.group(1)
# pads of moved parts against fixed copper of other nets (0.2 clearance + half track)
bo = boardio.read_board('whatif/_scratch/cand_local.kicad_pcb')
hits = 0
for j in range(len(bo.p_fp)):
    if bo.fp_ref[int(bo.p_fp[j])] not in moved: continue
    pn = bo.nets[int(bo.p_net[j])]
    for k in range(len(bo.s_idx)):
        if bo.nets[int(bo.s_net[k])] == pn or int(bo.s_layer[k]) != 0: continue
        x0, x1 = sorted((bo.s_x0[k], bo.s_x1[k])); y0, y1 = sorted((bo.s_y0[k], bo.s_y1[k])); m_ = bo.s_w[k] / 2 + 0.2
        if bo.p_bx1[j] + m_ > x0 and bo.p_bx0[j] - m_ < x1 and bo.p_by1[j] + m_ > y0 and bo.p_by0[j] - m_ < y1:
            # exact distance pad box to segment, sampled
            for t in [i / 10 for i in range(11)]:
                px = bo.s_x0[k] + t * (bo.s_x1[k] - bo.s_x0[k]); py = bo.s_y0[k] + t * (bo.s_y1[k] - bo.s_y0[k])
                if bo.p_bx0[j] - m_ < px < bo.p_bx1[j] + m_ and bo.p_by0[j] - m_ < py < bo.p_by1[j] + m_: hits += 1; break
print('LOCAL clusters_total', tot, 'in_window', wincl, 'failed', failed, 'pad_hits', hits, '|', last[:80])
