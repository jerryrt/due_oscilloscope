"""python3 subgroups.py HOPS.txt : the bridge-only gaps of a hops2.py list, sorted into the AWG and REFCAL sub-groups (inside one / between two)."""
import sys, re, collections
SG = {}
for r in ('U301', 'C305', 'C306', 'R307', 'R306'): SG[r] = 'AWG:op-amp'
for r in ('R303', 'R304', 'C301', 'R305', 'C303', 'C304'): SG[r] = 'AWG:feedback/half-rail'
for r in ('R301', 'R302', 'R308', 'R309', 'TP301'): SG[r] = 'AWG:output/back-termination'
for r in ('U501', 'C501', 'C502', 'R514', 'TP501'): SG[r] = 'REF:VREF source'
for r in ('R502', 'R503', 'R504', 'R505', 'R506', 'R501', 'J501', 'J602'): SG[r] = 'REF:tap ladder/connectors'
for r in ('U502', 'C503', 'R512', 'R513', 'R511'): SG[r] = 'REF:ADS'
for r in ('R507', 'R508', 'R509', 'R510'): SG[r] = 'REF:sense divider'
inside, between, other = collections.Counter(), collections.Counter(), []
for l in open(sys.argv[1]):
    if not l.startswith('GAP') or 'BRIDGE-ONLY' not in l: continue
    m = re.match(r'GAP (\S+) (\S+) (\S+) -> (\S+) gap ([\d.]+)', l)
    if not m: continue
    blk, net, a, b, d = m.groups(); ga = SG.get(a.split('.')[0]); gb = SG.get(b.split('.')[0])
    if ga and gb and ga[:3] == gb[:3]:
        if ga == gb: inside[ga] += 1
        else: between[tuple(sorted((ga, gb)))] += 1
    else: other.append((net, a, b, d))
print('INSIDE a sub-group:', dict(inside), 'total', sum(inside.values()))
print('BETWEEN sub-groups of one block:', {' / '.join(k): v for k, v in between.items()}, 'total', sum(between.values()))
print('other (a loose track end, a part outside the two blocks, or crossing AWG/REFCAL):', len(other), other)
