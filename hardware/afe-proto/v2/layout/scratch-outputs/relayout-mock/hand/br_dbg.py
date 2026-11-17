import sys
sys.argv = ['x']
exec(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/br_break2.py').read().split("# state X")[0])
H = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/'
b = boardio.read_board_retry(H + 'brk_x.kicad_pcb'); c = cfgp(True)
print([sorted(p)[:8] for p in rules.pieces(b, c, c.VREF_NET, set(tuple(k) for k in c.VREF_SOURCE))])
