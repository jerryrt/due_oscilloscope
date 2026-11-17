import pickle, numpy as np
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
C = pickle.load(open(R + 'rc_sel_m2.pkl', 'rb'))
def arr(p, i): return np.array([c[i] for c in C[p]])
p, q = 'R503', 'R511'
CY1, CY2 = arr(p, 5), arr(q, 5)
print('skip?', CY1[:, 2].min() + 9 < CY2[:, 0].min(), CY2[:, 2].min() + 9 < CY1[:, 0].min(), CY1[:, 3].min() + 9 < CY2[:, 1].min(), CY2[:, 3].min() + 9 < CY1[:, 1].min())
print(CY1[:, 2].min(), CY2[:, 0].min(), CY2[:, 2].min(), CY1[:, 0].min(), CY1[:, 3].min(), CY2[:, 1].min(), CY2[:, 3].min(), CY1[:, 1].min())
