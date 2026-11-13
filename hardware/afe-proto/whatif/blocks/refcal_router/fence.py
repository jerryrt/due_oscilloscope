import sys
from pcbtools import boardio, fence
from pcbtools.boards import v1
base = boardio.read_board('kicad/wip/v1_merge4.kicad_pcb'); blk = boardio.read_board(sys.argv[1])
r = fence.check_fence(base, blk, 'REFCAL', v1)
print('fence ok', r.ok); [print(' ', v) for v in r.violations[:20]]
