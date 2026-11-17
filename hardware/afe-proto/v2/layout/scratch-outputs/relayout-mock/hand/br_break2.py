import sys
sys.argv = ['x']
exec(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/br_break.py').read().split("print('--- LR-6 on the bridge-free")[0])
V = '/VREF'
pts = {'U501.2': (52.6, 13.2), 'U502.4': (51.4, 17.2), 'R206.2': (75.1, 21.0), 'R106.2': (89.5, 43.3), 'R509.2': (43.4, 35.5)}
def seg(a, b): return (V, 'F', [pts[a], pts[b]], 0.2)
H = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/'
def show(tag, spec, patched):
    out = H + 'brk_%s.kicad_pcb' % tag; splice(spec, out)
    b = boardio.read_board_retry(out); c = cfgp(patched); c.VREF_BRANCHES = [[('U502', '4')], [('R106', '2'), ('R509', '2')] + ([('R206', '2')] if patched else [('BR503', '1')])]; r = rules.lr8(b, c)
    msgs = [m.strip() for m in r.detail.split(';')]
    print(tag, 'patched' if patched else 'as-is', '->', 'PASS' if r.ok else 'FAIL', '| share-copper messages:', [m for m in msgs if 'share copper' in m] or 'NONE')
# state X: the ADC leg U502.4 reaches the source, and the CH2 centring resistor's pad R206.2 is joined to the ADC leg (R106/R509 not in the copper)
w(H + 'brk_x.py', None, [seg('U501.2', 'U502.4'), seg('U502.4', 'R206.2')])
show('x', H + 'brk_x.py', False); show('x', H + 'brk_x.py', True)
# state Y: the shared centring leg alone on its own copper (R106.2, R509.2, R206.2), the ADC leg separate
w(H + 'brk_y.py', None, [seg('U501.2', 'U502.4'), seg('R509.2', 'R106.2'), seg('R106.2', 'R206.2')])
show('y', H + 'brk_y.py', False); show('y', H + 'brk_y.py', True)
# state Z: the shared leg joined to the ADC leg through R509.2 (the break the ruling names)
w(H + 'brk_z.py', None, [seg('U501.2', 'U502.4'), seg('R509.2', 'R106.2'), seg('R106.2', 'R206.2'), seg('R206.2', 'U502.4')])
show('z', H + 'brk_z.py', False); show('z', H + 'brk_z.py', True)
