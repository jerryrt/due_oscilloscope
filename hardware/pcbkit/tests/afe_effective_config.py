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

# the typo guard on every AFE configuration: nothing may raise, and the names no pcbkit module declares are listed (informational)
import importlib                          # noqa: E402
from pcbkit import config as KC          # noqa: E402

print('\ndeclared names:', len(KC.DECLARED), '; declared pairs near each other:', KC.declared_pairs_near())
for name in ('v2_layout', 'v2', 'v1', 'v1r', 'v1_frozen'):
    cfg = importlib.import_module('pcbtools.boards.' + name)
    unknown = KC.check_names(cfg)
    kit = R.kit_cfg_lr1(cfg) if hasattr(cfg, 'ANALOG_FENCE') else None
    print(f'{name}: {len(KC.config_names(cfg))} upper-case names, {len(unknown)} unrecognised, no near-miss raised')
    if name in ('v2_layout', 'v1'):
        print('  unrecognised:', ', '.join(unknown))
