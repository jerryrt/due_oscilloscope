import sys
sys.path.insert(0,'/work/hardware/afe-proto')
from pcbtools import boardio, rules
from pcbtools.boards import v2_layout as C
b=boardio.read_board_retry('/work/hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb')
r=rules.lr8(b,C); print('LR-8', 'PASS' if r.ok else 'FAIL', '|', r.detail)
