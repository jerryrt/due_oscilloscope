"""Print the effective configuration of pcbkit's LR-1 rules for the AFE's v2_layout configuration (run in the image from the repository
root with PYTHONPATH=hardware/afe-proto)."""
import sys

sys.path.append('/usr/lib/python3/dist-packages')
from pcbtools import rules as R          # noqa: E402  (importing pcbtools registers pcbkit)
from pcbkit import rules as K            # noqa: E402
from pcbtools.boards import v2_layout as C   # noqa: E402

kc = R.kit_cfg_lr1(C)
for rule in ('ground_plane', 'bottom_hops'):
    print(K.effective_config(kc, rule))
rep = []
R.lr1(__import__('pcbtools.boardio', fromlist=['x']).read_board('hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb'), C, rep)
print('\nreport carried by one lr1 run on the integrated board: %d rows (ground_plane then bottom_hops)' % len(rep))
