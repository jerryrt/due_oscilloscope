import pickle, numpy as np, sys
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
C = pickle.load(open(R + 'rc_sel.pkl', 'rb'))
parts = [r for r in sorted(C) if r not in ('U501', 'U502')]
def OV2(A, B, g): return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
def arr(p, i): return np.array([c[i] for c in C[p]])
dead = []
for p in parts:
    for q in parts:
        if p >= q: continue
        CY1, Z1, L1, E1 = arr(p, 5), arr(p, 6), arr(p, 7), arr(p, 8); CY2, Z2, L2, E2 = arr(q, 5), arr(q, 6), arr(q, 7), arr(q, 8)
        a1 = E1 if p == 'J501' else CY1; a2 = E2 if q == 'J501' else CY2
        bad = OV2(a1, a2, 0.02) | OV2(Z1, a2, 0) | OV2(a1, Z2, 0) | OV2(L1, L2, 0.5)
        if (~bad).sum() == 0: dead.append((p, q))
        elif (~bad).any(1).sum() < 3 or (~bad).any(0).sum() < 3: dead.append((p, q, 'tight', int((~bad).any(1).sum()), int((~bad).any(0).sum())))
print('no compatible pair:', dead[:30])
for p in parts:
    c = C[p]; print(p, len(c), 'beside', sum(1 for x in c if x[2] >= 10), 'x', round(min(x[3] for x in c), 1), round(max(x[3] for x in c), 1), 'y', round(min(x[4] for x in c), 1), round(max(x[4] for x in c), 1))
