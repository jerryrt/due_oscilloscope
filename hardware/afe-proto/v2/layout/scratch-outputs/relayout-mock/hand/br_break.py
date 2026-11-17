"""LR-6 / LR-8 on the bridge-free board: the checks as they stand, then with the two config keys a merge forces (monkeypatched here, no file edited),
then the break-on-purpose arms. python3 br_break.py"""
import sys, types, subprocess, shutil, os
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.insert(0, '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand')
from pcbtools import boardio, rules
from pcbtools.boards import v2_layout as C
H = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/'
def splice(spec, out):
    subprocess.run(['python3', H + 'hr.py', H + 'nobr.kicad_pcb', out, spec], check=True, capture_output=True)
    shutil.copy(H + 'nobr.kicad_pro', out.replace('.kicad_pcb', '.kicad_pro'))
def cfgp(patched):
    c = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith('__')})
    if patched:
        c.GROUPS = dict(c.GROUPS); c.STAR = dict(c.STAR)
        c.GROUPS['/VNEG'] = c.GROUPS.pop('/VNEG_G'); c.STAR['/VNEG'] = c.STAR.pop('/VNEG_G')
        c.VREF_BRANCHES = [b for b in c.VREF_BRANCHES if ('R106', '2') not in b] + [[('R106', '2'), ('R509', '2'), ('R206', '2')]]
    return c
def run(tag, spec, patched):
    out = H + 'brk_%s.kicad_pcb' % tag; splice(spec, out)
    b = boardio.read_board_retry(out); c = cfgp(patched)
    for nm, fn in (('LR-6', rules.lr6), ('LR-8', rules.lr8)):
        r = fn(b, c); print(tag, 'patched' if patched else 'as-is', nm, 'PASS' if r.ok else 'FAIL', '|', r.detail[:420].replace(';', '\n     '))
def w(path, name, routes):
    open(path, 'w').write('ROUTES = %r\nVIAS = []\n' % routes)
N = '/+3V3A'; V = '/VREF'; W = 0.2
star = [(N, 'F', [(32.6, 14.7), (34.75, 14.7)], W), (N, 'F', [(34.0, 14.7), (34.0, 12.8)], W), (N, 'F', [(34.75, 14.7), (34.9, 15.9), (35.2, 15.9)], W),
        (N, 'F', [(34.75, 14.7), (34.75, 19.0), (34.3, 19.0)], W), (N, 'F', [(33.9, 19.3), (33.9, 20.3), (42.3, 20.3), (42.3, 22.8)], W)]
adc = [(N, 'F', [(42.6, 23.0), (43.3, 22.45), (47.95, 22.45)], W), (N, 'F', [(48.7, 22.45), (49.2, 22.8), (50.875, 22.8), (50.875, 22.1)], W),
       (N, 'F', [(45.0, 22.45), (45.0, 8.1), (46.1, 8.1)], W), (N, 'F', [(45.5, 22.45), (45.5, 37.2), (41.0, 37.2), (41.0, 38.6)], W),
       (N, 'F', [(45.5, 32.0), (47.9, 32.0), (47.9, 33.3)], W)]
awg = [(N, 'F', [(34.75, 14.7), (37.4, 14.7), (37.4, 5.0), (47.6, 5.0), (47.6, 0.95), (70.2, 0.95), (70.2, 5.0), (69.66, 5.6), (69.66, 11.0), (72.0, 11.0), (72.0, 11.8)], W),
       (N, 'F', [(72.4, 12.2), (74.5, 12.2)], W)]
w(H + 'brk_a.py', None, star + adc + awg)
w(H + 'brk_b.py', None, star + adc + awg + [(N, 'F', [(46.1, 8.1), (46.1, 5.0)], W)])      # joins the ADC leg (R513.1) to the awg leg
print('--- LR-6 on the bridge-free board with the star, ADC and awg copper')
run('a', H + 'brk_a.py', False); run('a', H + 'brk_a.py', True)
print('--- break on purpose: one track joins the ADC leg to the awg leg')
run('b', H + 'brk_b.py', True)
# LR-8: VREF source U501.2/C501.1, branches J602.1, U502.4, R514.1, TP501.1, R305.1 and the shared centring leg R106.2/R509.2/R206.2 (straight tracks: a logic test, not a layout)
pts = {'U501.2': (52.6, 13.2), 'C501.1': (54.8, 14.2), 'J602.1': (50.8, 2.5), 'U502.4': (51.4, 17.2), 'R514.1': (47.9, 19.1), 'TP501.1': (54.4, 38.2), 'R305.1': (63.1, 14.2),
       'R509.2': (43.4, 35.5), 'R106.2': (89.5, 43.3), 'R206.2': (75.1, 21.0)}
def seg(a, b): return (V, 'F', [pts[a], pts[b]], W)
base = [seg('U501.2', 'C501.1')] + [seg('U501.2', k) for k in ('J602.1', 'U502.4', 'R514.1', 'TP501.1', 'R305.1')] + [seg('TP501.1', 'R509.2'), seg('R509.2', 'R106.2'), seg('R106.2', 'R206.2')]
# the shared leg must reach the source: it hangs off the source pad through TP501's copper? no: give it its own track to the source
base2 = [s for s in base if not (s[2][0] == pts['U501.2'] and s[2][1] == pts['TP501.1'])] + [seg('U501.2', 'R509.2')]
w(H + 'brk_c.py', None, base2)
w(H + 'brk_d.py', None, base2 + [seg('R206.2', 'U502.4')])                               # joins the shared centring leg to the ADC leg
print('--- LR-8: source, branches, one shared centring leg (R106.2, R509.2, R206.2)')
run('c', H + 'brk_c.py', False); run('c', H + 'brk_c.py', True)
print('--- break on purpose: R206.2 joined to the ADC leg U502.4')
run('d', H + 'brk_d.py', True)
