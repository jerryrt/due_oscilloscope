import sys
from pcbtools import boardio
from pcbtools.boards import v1 as C
b = boardio.read_board(sys.argv[1])
out = []
for n in C.HIZ:
    xs = [(float(b.p_x[j]), float(b.p_y[j])) for j in range(len(b.p_fp)) if b.nets[int(b.p_net[j])] == n]
    if xs:
        X = [x for x, _ in xs]; Y = [y for _, y in xs]
        out.append('%s %.2f' % (n[1:], (max(X) - min(X)) + (max(Y) - min(Y))))
print('HPWL', ' '.join(out))
