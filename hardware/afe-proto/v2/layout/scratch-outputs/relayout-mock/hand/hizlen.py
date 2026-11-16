import sys, re, math
s = open(sys.argv[1]).read()
L = {}
for m in re.finditer(r'\n\t\(segment\n\t\t\(start ([\d.-]+) ([\d.-]+)\)\n\t\t\(end ([\d.-]+) ([\d.-]+)\)\n\t\t\(width [\d.]+\)\n\t\t\(layer "(\w)\.Cu"\)\n\t\t\(net "([^"]*)"\)', s):
    x0, y0, x1, y1, l, n = m.groups(); L[n] = L.get(n, 0) + math.hypot(float(x1) - float(x0), float(y1) - float(y0))
hz = ['/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP', '/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP']
print(' '.join('%s=%.1f' % (n[1:], L.get(n, 0)) for n in hz), 'MAX=%.1f' % max(L.get(n, 0) for n in hz), 'OUT: %.1f %.1f' % (L.get('/CH1_OUT', 0), L.get('/CH2_OUT', 0)))
