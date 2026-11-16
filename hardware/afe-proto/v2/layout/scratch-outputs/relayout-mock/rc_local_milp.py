import sys, math, json, pickle
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP, scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
DN, PN = RP.load(R + 'dump_new.json'); D0, P0 = RP.load(R + 'dump_all.json')
C = pickle.load(open(R + 'rc_local.pkl', 'rb')); parts = sorted(C)
def disp(c): p = PN[c[0]]; return math.hypot(c[3] - p['x'], c[4] - p['y'])
off = {}; n = 0
for r in parts: off[r] = n; n += len(C[r])
def OV2(A, B, g): return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
def arr(p, i): return np.array([c[i] for c in C[p]])
rows, cols = [], []; nrow = 0
for i, p in enumerate(parts):
    for q in parts[i + 1:]:
        bad = OV2(arr(p, 5), arr(q, 5), 0.02) | OV2(arr(p, 6), arr(q, 5), 0) | OV2(arr(p, 5), arr(q, 6), 0) | OV2(arr(p, 7), arr(q, 7), 0.5)
        ii, jj = np.nonzero(bad)
        rows += list(np.repeat(np.arange(nrow, nrow + len(ii)), 2)); cols += [v for a_, b_ in zip(ii, jj) for v in (off[p] + a_, off[q] + b_)]; nrow += len(ii)
A = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(nrow, n))
r2, c2 = [], []
for k_, p in enumerate(parts):
    for j in range(len(C[p])): r2.append(k_); c2.append(off[p] + j)
A1 = sp.csr_matrix((np.ones(len(r2)), (r2, c2)), shape=(len(parts), n))
cost = np.array([disp(c) + (100.0 if c[2] >= 10 else 0.0) for p in parts for c in C[p]])
res = milp(cost, constraints=[LinearConstraint(A1, 1, 1), LinearConstraint(A, -np.inf, 1)], integrality=np.ones(n), bounds=Bounds(0, 1), options=dict(time_limit=300, mip_rel_gap=0.0))
print('MILP status', res.status, res.message, 'gap', getattr(res, 'mip_gap', None), 'bound', getattr(res, 'mip_dual_bound', None), 'obj', res.fun)
if res.x is not None:
    ch = [C[p][int(np.argmax(res.x[off[p]:off[p] + len(C[p])]))] for p in parts]
    print('beside', [c[0] for c in ch if c[2] >= 10])
    st = {c[0]: [c[3], c[4], ((round(P0[c[0]]['rot']) + 90 * c[1] + 180) % 360) - 180, c[2]] for c in ch}
    st['U301'] = [76.56, 9.71, 90.0, 0]
    json.dump(dict(st=st), open(R + 'rc_local_place.json', 'w')); print(st)
