"""AWG block, rows first: U301 fixed where it is (label above), every other part in a row of horizontal passives (rows y_a, y_b, y_c, and a column west of the A1 lane),
chosen by a depth-first search over discrete slots; every hard row and the lanes are checked exactly (relayout_place's own functions)."""
import sys, math, json, random, itertools
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json')
U = (76.56, 9.71)                                              # U301 stays where it is
POCKET = ('C303', 'C304', 'R305', 'TP301')
PARTS = ['C306', 'C305', 'R304', 'R303', 'C301', 'R306', 'R307', 'R308', 'R309', 'R301', 'R302', 'TP301', 'C303', 'C304', 'R305']
ROWS = [7.235, 12.185, 16.15]
POCKET_X, POCKET_ROWS = 62.3, [8.1, 11.6, 15.1]
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 1e-6 and min(a[3], b[3]) - max(a[1], b[1]) + g > 1e-6
reg = RP.REGIONS['AWG']; mext, mlab = RP.Mask(reg, 0.2), RP.Mask(reg, 0.4)
lanes = RP.LANES
g = RP.part_geom(P0['U301']); ux, uy = U
U_ext = (g['ext'][0]+ux, g['ext'][1]+uy, g['ext'][2]+ux, g['ext'][3]+uy)
U_lab = (g['lab'][0]+ux, g['lab'][1]+uy, g['lab'][2]+ux, g['lab'][3]+uy); U_zone = (g['zone'][0]+ux, g['zone'][1]+uy, g['zone'][2]+ux, g['zone'][3]+uy)
fixed_ext = [U_ext]; fixed_zone = [U_zone]; fixed_lab = [U_lab]
# fixed header labels / names near the block
nb = RP.name_box('AWG', P0, {r: RP.part_geom(p) for r, p in P0.items()}, None); fixed_lab.append(nb)
for r in ('J602', 'J603'):
    c = RP.header_label(P0[r]); w, h = RP.LAB_W * 4, RP.LAB_H
    fixed_lab.append((c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2))
for r in ('J301', 'J605', 'MH601'):
    c = P0[r]['cy']; fixed_ext.append(tuple(c))
fixed_ext += [(P0[r]['silk'] or P0[r]['cy']) for r in ('J602', 'J603')]
HARD = [h for h in RP.hard_constraints(P0) if any(r in PARTS for r in h['refs'])]
def orient0(ref): return [k for k in range(4) if RP.orient(P0[ref], k) == 0]
def cand(ref):
    out = []
    spec = ref
    for k in range(4):
        for ls in (0,):
            gg = RP.part_geom(P0[ref], k, ls)
            rows = [round(v,3) for v in np.arange(5.0, 17.6, 0.1)]
            xs = np.arange(70.0, 84.5, 0.1)
            for y in rows:
                for x in xs:
                    x = round(float(x), 2); y = round(float(y), 3)
                    e = (gg['ext'][0]+x, gg['ext'][1]+y, gg['ext'][2]+x, gg['ext'][3]+y)
                    z = (gg['zone'][0]+x, gg['zone'][1]+y, gg['zone'][2]+x, gg['zone'][3]+y)
                    lb = (gg['lab'][0]+x, gg['lab'][1]+y, gg['lab'][2]+x, gg['lab'][3]+y)
                    if mext.bad(e) > 0 or mlab.bad(lb) > 0: continue
                    if any(ov(e, f, 0.02) for f in fixed_ext) or any(ov(z, f, 0) for f in fixed_ext) or any(ov(e, f, 0) for f in fixed_zone) or any(ov(lb, f, 0.5) for f in fixed_lab): continue
                    if any(ov(e, l, 0) or ov(z, l, 0) for l in lanes): continue
                    out.append((ref, k, ls, x, y, e, z, lb))
    return out
def pad_abs(ref, k, x, y, n):
    c, s_ = RP.COS[k], RP.SIN[k]
    q = [q for q in P0[ref]['pads'] if q['n'] == n][0]
    o = (q['c'][0] - P0[ref]['x'], q['c'][1] - P0[ref]['y']); o = (o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c)
    return (x + o[0], y + o[1])
pinU = {n: [q['c'] for q in P0['U301']['pads'] if q['n'] == n][0] for n in '12345678'}
# U301's pads in the board are at U (76.56, 9.71); the dump is main's: shift
dxU, dyU = U[0] - P0['U301']['x'], U[1] - P0['U301']['y']
pinU = {n: (c[0] + dxU, c[1] + dyU) for n, c in pinU.items()}
def ok_local(c):
    ref, k, ls, x, y = c[:5]
    if ref == 'C305':
        return math.hypot(*(np.array(pad_abs(ref, k, x, y, '1')) - np.array(pinU['8']))) <= 2.79
    if ref == 'C306':
        return math.hypot(*(np.array(pad_abs(ref, k, x, y, '1')) - np.array(pinU['4']))) <= 2.79
    if ref in ('R301', 'R302'):
        return math.hypot(x - 102.0, y - 8.89) <= 15.99
    if ref == 'R306':
        d0 = [q['c'] for q in P0['J603']['pads'] if q['n'] == '5'][0]; p = pad_abs(ref, k, x, y, '1')
        return abs(p[0] - d0[0]) + abs(p[1] - d0[1]) <= 11.49
    return True

def comp(a, b):
    return not (ov(a[5], b[5], 0.02) or ov(a[6], b[5], 0) or ov(b[6], a[5], 0) or ov(a[7], b[7], 0.5))
FB=['R304','R303','C301']
def fbpad(c):
    ref=c[0]; n={'R304':'1','R303':'2','C301':'2'}[ref]
    return pad_abs(ref,c[1],c[3],c[4],n)
p2=pinU['2']; p6=pinU['6']
Cs={}
for r in FB:
    L=[]
    for c in cand(r):
        p=fbpad(c); d=min(abs(p[0]-p2[0])+abs(p[1]-p2[1]),abs(p[0]-p6[0])+abs(p[1]-p6[1]))
        if d<=(4.5 if r=='R304' else 6.0): L.append((c,p))
    Cs[r]=L; print(r,len(L),flush=True)
def mst(pts):
    n=len(pts); inT={0}; L=0
    while len(inT)<n:
        d,j=min((abs(pts[i][0]-pts[j][0])+abs(pts[i][1]-pts[j][1]),j) for i in inT for j in range(n) if j not in inT); L+=d; inT.add(j)
    return L

dd=lambda p,q:abs(p[0]-q[0])+abs(p[1]-q[1])
base=dd(p2,p6)
A=[(c,p) for c,p in Cs['R304'] if base+min(dd(p,p2),dd(p,p6))<=17.1]
B=[(c,p) for c,p in Cs['R303'] if base+min(dd(p,p2),dd(p,p6),min(dd(p,q) for _,q in A))<=17.1]
Cc=[(c,p) for c,p in Cs['C301'] if base+min(dd(p,p2),dd(p,p6),min(dd(p,q) for _,q in A))<=17.1]
print(len(A),len(B),len(Cc),flush=True)
Cp=np.array([p for c,p in Cc])
res=[]
for a,pa in A:
    da=min(dd(pa,p2),dd(pa,p6))
    for b,pb in B:
        if not comp(a,b): continue
        db=min(dd(pb,p2),dd(pb,p6),dd(pb,pa))
        if base+da+db>17.0: continue
        pts=np.array([p2,p6,pa,pb])
        dc=np.abs(Cp[:,None,:]-pts[None,:,:]).sum(2).min(1)
        idx=np.nonzero(base+da+db+dc<=17.0+1e-9)[0]
        for i in idx:
            c,pc=Cc[i]
            if not comp(a,c) or not comp(b,c): continue
            t=mst([p2,p6,pa,pb,pc])
            if t<=17.0: res.append((t,a[:5],b[:5],c[:5]))
print('N',len(res))
res.sort(key=lambda r:r[0])
for r in res[:15]: print(r)
import pickle; pickle.dump(res,open(R+'fb_triples.pkl','wb'))
