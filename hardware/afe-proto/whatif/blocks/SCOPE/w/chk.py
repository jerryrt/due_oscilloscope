import sys
from pcbtools import boardio, fence
from pcbtools.boards import v1
base = boardio.read_board('whatif/blocks/base.kicad_pcb'); blk = boardio.read_board(sys.argv[1])
r = fence.check_fence(base, blk, 'SCOPE', v1)
print('fence ok', r.ok); [print(' ', v) for v in r.violations[:20]]
