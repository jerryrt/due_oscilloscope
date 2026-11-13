"""BoardConfig of the AFE v1 board: the tables fence.py (and, as they are ported, the rules) read, as module-level names so a
test can build a config from plain values (a types.SimpleNamespace with the same names works).

Values that already exist in design.py / floorplan.py / layout.py are imported from them, not copied: `_load_sources()` is
the ONE place that knows where those files are (the frozen fixture folder of commit 34b2e51, relative to this package); it
will switch to the live v1 files when v1's layout reaches main through review. The tables that lived only inside the old
fence_check.py are written here, each with its origin.
"""
import importlib.util
import os
import sys

NAME = 'v1'
HERE = os.path.dirname(os.path.abspath(__file__))
# pcbtools/boards -> pcbtools -> hardware/afe-proto
FIXTURE_DIR = os.path.normpath(os.path.join(HERE, '..', '..', 'tests', 'fixtures', 'v1-34b2e51', 'kicad'))
# The frozen fixture is the default: the equivalence tests and the goldens are about 34b2e51. PCBTOOLS_V1_SOURCE names the folder of
# the LIVE v1 data (design.py, floorplan.py, layout.py: hardware/afe-proto/kicad) for the layout restart, where the design has moved on
SOURCE_DIR = os.path.normpath(os.environ.get('PCBTOOLS_V1_SOURCE') or FIXTURE_DIR)


def _load_sources():
    """import design, floorplan and layout from SOURCE_DIR under namespaced names (pcbtools._fixture_v1.<name>): nothing is
    put on sys.path and no plain name ('floorplan', 'layout') is left in sys.modules for another board's code to pick up.
    The three files import nothing of each other, which is why no path is needed."""
    mods = {}
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True               # the fixture folder is frozen: importing it must not leave __pycache__ in it
    try:
        for name in ('design', 'floorplan', 'layout'):
            spec = importlib.util.spec_from_file_location(f'pcbtools._fixture_v1.{name}', os.path.join(SOURCE_DIR, name + '.py'))
            m = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = m
            spec.loader.exec_module(m)
            mods[name] = m
    finally:
        sys.dont_write_bytecode = keep
    return mods['design'], mods['floorplan'], mods['layout']


_design, _floorplan, _layout = _load_sources()

BOARD = None                                  # default board path: the caller names it
PARTS = _design.PARTS
PLACE = dict(_layout.PLACE)
FENCES = {b: list(rs) for b, rs in _floorplan.FENCES.items()}           # floorplan.py: POWER, REFCAL, AWG, SCOPE
# fence_check.py CONFIG (34b2e51): hundreds digit of a designator -> block; SCOPE owns 1xx and 2xx; 6xx is nobody's
HUNDREDS = {'1': 'SCOPE', '2': 'SCOPE', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': None}
OWNER_OVERRIDE = {}                           # none for v1: the bridges already carry their block's digit
TOL_MM = 0.001                                # position tolerance of the fence rule


# ------------------------------------------------------------------------------------------------ build data
# What the old build_sch.py / build_pcb.py kept as module constants, now data. Positions are Due mm (x right, y up).
from .. import schematic as _sch          # noqa: E402  (after the loader above: the box symbol needs design.SC706)

PROJECT = 'afe-proto'
TITLE = 'AFE full range design 01'
REV = 'FR-01'
NS = '6f1f0d3e-4a52-4c1b-9a4e-0ad5e0a1f001'                  # uuid namespace of every generated id
BLOCK_ORDER = ['power', 'ch1', 'ch2', 'awg', 'cal', 'due']
BLOCK_TITLE = {
    'power': 'POWER: 5 V feed (take only), LM27762 +3.3 V_A / -2.07 V, bleed',
    'ch1': 'SCOPE CH1 (A1): 1 Mohm compensated divider centred from the REF3030E, TPH2502 follower (shared dual), ADC-pin clamp',
    'ch2': 'SCOPE CH2 (A0): as CH1, on the dual\'s half B',
    'awg': 'AWG: TPH2502 (DAC0 buffer + gain stage), attenuator, own Vmid (TLV9062), 50 ohm out',
    'cal': 'CALIBRATION: REF3030E, ladder (A2..A7), ADS1115 on I2C, AWG-sense divider and ratio switch',
    'due': 'DUE HEADERS (V03 positions), mounting, test points',
}
PWR_FLAG_NETS = ['GND', '+5V_DUE', '+5V_F', 'SC_VCC', 'P33_R']
SCH_COMMENTS = ['Generated from design.py by pcbtools.schematic: edit design.py, not this file',
                'Values and parts: whatif/bom.txt. Connectivity: the simulated circuit (docs/architecture.md)',
                'Own work, CC BY-SA 4.0']
PCB_COMMENTS = ['Generated from design.py by pcbtools.build; not routed', 'Own work, CC BY-SA 4.0']
SYMBOL_DIR = os.environ.get('KICAD_SYMBOL_DIR', '/usr/share/kicad/symbols')
FOOTPRINT_DIR = os.environ.get('KICAD_FOOTPRINT_DIR', '/usr/share/kicad/footprints')

# board geometry
BOARD_RECT = (17.0, 0.0, 117.0, 53.34)                          # the shield's rectangle
REFERENCE_OUTLINE = [(1, 0), (98.06, 0), (99.06, 1), (99.06, 2.54), (101.6, 5.08), (101.6, 37.846), (99.06, 40.386),
                     (99.06, 51.816), (97.536, 53.34), (1, 53.34), (0, 52.34), (0, 1), (1, 0)]   # the Due's own outline (V03)
# header: (pin-1 x, pin-1 y, direction of rising pin numbers), due-header-table.md section 2
HEADERS = {'J601': (27.94, 2.54, '+x'), 'J602': (50.80, 2.54, '+x'), 'J603': (73.66, 2.54, '+x'),
           'J604': (63.50, 50.80, '-x'), 'J605': (68.58, 50.80, '+x'), 'J606': (41.656, 50.80, '-x')}
XIO = (93.98, 50.80)          # J607 pin 1; odd pins at x 93.98, even at 96.52, rows step down 2.54
HEADER_ROT = {'+x': 90.0, '-x': -90.0}
BNCS = {'J101': 44.45, 'J201': 24.13, 'J301': 7.4}           # y of each BNC centre pin: CH1, CH2, AWG
BNC_X = 102.0
MH = (96.52, 2.54)
MH602 = (90.17, 50.8)
MODEL_OVERRIDE = {'Package_QFP:TQFP-32_5x5mm_P0.5mm': ('LQFP-32_5x5mm_P0.5mm.step',
                                                       '9f2be83a713ff62d2355f91718245c4e93f9a75ac14a804dc68810514dd9a3a3')}
PROJECT_LIB_DIR = os.path.join(SOURCE_DIR, 'lib', 'afe.pretty')
MODELS_DIR = os.path.join(SOURCE_DIR, '3d')

# the checks (schematic_check.py): what the old check.py kept at module level
BOM_PATH = os.path.normpath(os.path.join(SOURCE_DIR, '..', 'whatif', 'bom.txt'))
BOM_DELTAS = {}               # parts on the board that bom.txt does not list, each with its reason
ERC_EXCLUDED = 1              # exactly one documented ERC exclusion (U401 PGOOD)
MIN_NETS, MIN_COMPS, MIN_BOM, MIN_PADS = 40, 90, 90, 250       # floors: a check that examined fewer items than this did not run
HEADER_PINS = {}              # (ref, pin) -> (x, y) of every Due header pin, the V03 positions
for _ref, (_x, _y, _d) in {'J601': (27.94, 2.54, 1), 'J602': (50.80, 2.54, 1), 'J603': (73.66, 2.54, 1),
                           'J604': (63.50, 50.80, -1), 'J605': (68.58, 50.80, 1), 'J606': (41.656, 50.80, -1)}.items():
    for _k in range(10 if _ref == 'J606' else 8):
        HEADER_PINS[(_ref, str(_k + 1))] = (_x + _d * 2.54 * _k, _y)
for _k in range(36):
    HEADER_PINS[('J607', str(_k + 1))] = (93.98 if _k % 2 == 0 else 96.52, 50.80 - 2.54 * (_k // 2))
HEADER_TOL_MM = 0.01
SILK_EDGE_ALLOWED = ('J101', 'J201', 'J301')                 # the BNCs overhang the right edge by design


def _erc_exclusions(pin_at, uid, root):
    pg = pin_at[('U401', '1')]
    return [[f"pin_to_pin|{round(pg[0] * 1e4)}|{round(pg[1] * 1e4)}|{uid('pin', 'U401', 1, '1')}|{uid('pin', '#FLG01', 1, '1')}"
             f"|/{root}|/{root}|/{root}", 'PGOOD unused, tied to GND per SNVSAF7C; GND carries the PWR_FLAG']]


def sch_cfg(**over):
    """the namespace schematic.write_all(PARTS, cfg, out_dir) takes; keyword arguments replace a field (the check's mutation arms)"""
    import types
    tmux = _sch.box_symbol('TMUX1119', [
        ('4', 'S1', 'passive', 'L', 0), ('6', 'S2', 'passive', 'L', 2), ('1', 'SEL', 'input', 'L', 4),
        ('5', 'D', 'passive', 'R', 1), ('2', 'VDD', 'power_in', 'T', 1), ('3', 'GND', 'power_in', 'B', 1)],
        width=10.16, fp=_design.SC706, ds='https://www.ti.com/lit/ds/symlink/tmux1119.pdf',
        desc='SPDT 5 V analog switch, SC70-6 (SCDS401C table 4-1): SEL low = S1-D')
    cfg = types.SimpleNamespace(
        PROJECT=PROJECT, NS=NS, BLOCK_ORDER=list(BLOCK_ORDER), BLOCK_TITLE=dict(BLOCK_TITLE), PWR_FLAG_NETS=list(PWR_FLAG_NETS),
        TITLE=TITLE + ': AFE shield for the Arduino Due', REV=REV, COMMENTS=list(SCH_COMMENTS), PROJECT_SYMBOLS=[tmux],
        ERC_EXCLUSIONS=_erc_exclusions, SYMBOL_DIR=SYMBOL_DIR)
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def pcb_place():
    """the placement build_board takes: the layout's own, then the fixed header, BNC and mounting-hole positions"""
    place = {ref: tuple(v) for ref, v in PLACE.items()}
    for ref, (x, y, d) in HEADERS.items():
        place[ref] = (x, y, HEADER_ROT[d], True)
    place['J607'] = (XIO[0] + 2.54, XIO[1], 0, True)
    for ref, y in BNCS.items():
        place[ref] = (BNC_X, y, -90)
    place['MH601'] = (*MH, 0, True)
    place['MH602'] = (*MH602, 0, True)
    return place


ANCHORS = frozenset(set(HEADERS) | set(BNCS) | {'J607', 'MH601', 'MH602'})      # parts the legaliser never moves


def pcb_cfg(**over):
    import types
    cfg = types.SimpleNamespace(
        PROJECT=PROJECT, NS=NS, OUTLINE=BOARD_RECT, REFERENCE_OUTLINE=list(REFERENCE_OUTLINE),
        TITLE=TITLE + ': AFE shield for the Arduino Due, placement', REV=REV, COMMENTS=list(PCB_COMMENTS),
        FOOTPRINT_DIR=FOOTPRINT_DIR, PROJECT_LIB_DIR=PROJECT_LIB_DIR, MODEL_OVERRIDE=dict(MODEL_OVERRIDE), MODELS_DIR=MODELS_DIR)
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


# the mutation arms of schematic_check: what each one breaks
ARM_SWAP_PINS = 'R104'                  # a two-pin part whose pins are exchanged in the design
ARM_LCSC = ('R503', 'C2984375')         # a part given another resistor's code
ARM_BOM_DROP = 'C503'                   # a fitted part dropped from bom.txt
ARM_NO_FLAG = 'GND'                     # the PWR_FLAG net whose flag is removed
ARM_NET_SWAP = 'R303'                   # two-pad part whose pad nets are exchanged on the board
ARM_OVERLAP = ('R102', 'R103')          # the first dropped onto the second
ARM_HEADER = ('J602', '1')              # header pin shifted 0.2 mm


# ---------------------------------------------------------------------------------------------------------------- layout rules
# The LR-1..LR-12 fields in the shapes of pcbtools/CONFIG_FIELDS.md (v2's are canonical). Values are the old v1 lr_check.py's
# tables (frozen at 34b2e51, tests/fixtures/v1-34b2e51/kicad/lr_check.py), written once here. What design.py already says
# (blocks, pins, nets) is read from it, not copied. Net names carry the leading '/', as KiCad writes them.
def _n(name):
    return '/' + name


_BLK = {'power': 'POWER', 'ch1': 'SCOPE', 'ch2': 'SCOPE', 'awg': 'AWG', 'cal': 'REFCAL', 'due': 'EDGE'}
# v1 has ONE fence for both channels (floorplan.FENCES['SCOPE']), so CH1 and CH2 are one block here: the old tool's per-channel
# test-point rule is carried by TP_NETS (a test point per net), and the hundreds digits 1 and 2 both name SCOPE.
GND = '/GND'
BLOCK = {p['ref']: _BLK[p['block']] for p in PARTS}
BLOCK_OVERRIDE = {}
EDGE_BLOCK = 'EDGE'
ANALOG_BLOCKS = ('SCOPE', 'AWG', 'REFCAL')
ANALOG_REFS = frozenset(r for r, k in BLOCK.items() if k in ANALOG_BLOCKS and not r.startswith(('J', 'TP', 'MH')))
GENERATOR_BLOCK = frozenset(r for r, k in BLOCK.items() if k == 'POWER')
ANALOG_FENCE = ('REFCAL', 'AWG', 'SCOPE')       # LR-1: no bottom copper in these fences (old NO_BOTTOM_FENCES)
BRIDGE_TOL = 0.5                                # mm: a bridge counts as inside its block when within this of its floorplan point
OUTLINE = {k: list(v) for k, v in FENCES.items()}
for _name, _nets, _at, _x in _floorplan.BRIDGES:                 # the six 0603 bridges straddle the wall, outside every fence:
    _r = _name[_name.index('(') + 1:_name.index(')')]            # each is inside its block's outline at its floorplan point
    OUTLINE[BLOCK[_r]].append((_at[0] - BRIDGE_TOL, _at[1] - BRIDGE_TOL, _at[0] + BRIDGE_TOL, _at[1] + BRIDGE_TOL))
for _r in ('R411', 'R412', 'R413'):             # the corridor bridges (POWER parts) lie outside every fence: inside POWER's outline at their placed point
    if _r in PLACE:
        OUTLINE['POWER'].append((PLACE[_r][0] - 1.5, PLACE[_r][1] - 1.5, PLACE[_r][0] + 1.5, PLACE[_r][1] + 1.5))
LR_HUNDREDS = {'1': 'SCOPE', '2': 'SCOPE', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': 'EDGE'}
TEST_BLOCKS = ('SCOPE', 'AWG', 'POWER', 'REFCAL')
TP_NETS = {p['ref']: _n(p['pins']['1']) for p in PARTS if p['ref'].startswith('TP')}
SILK_WORDS = ('CH1', 'CH2', 'AWG', 'POWER', 'REF/CAL', 'ON')
DESIGNATOR_MIN_H = 1.0                          # the board house's minimum text height (docs/jlcpcb.md)
TP_PREFIX, TP_PIN = 'TP', '1'

ZONE_PAD = 0.3
HOP_MAX, HOP_MAX_VIAS = 3.0, 2
KEEPOUT = 10.0
INV_MAX = 5.0
FB_MAX = 5.0                                    # LR-4: the inverting node (AWG_INV) is the shortest trace of its stage
DECOUP_MAX = 3.0
DIVIDER_X_MAX = 99.0                            # the BNC pads (x 102) are not divider pads
GEN = ('U401', 'C402')                          # LM27762 and its flying capacitor

ADC_NETS = ('/A0', '/A1')
XSENS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/AWG_S', '/AWG_I', '/AWG_INV', '/AWG_BIN', '/AREF', '/CH1_', '/CH2_')
SENSITIVE = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/AREF', '/CH1_N', '/CH2_N')
INV_NODES = ('/AWG_INV',)
INV_LEN_NODES = ('/AWG_INV',)
POUR_NODES = ('/AWG_INV',)
POUR_INFO_NODES = ()
HIZ = tuple(_n(x) for x in ('CH1_N', 'CH1_NP', 'CH1_R1A', 'CH1_R2A', 'CH2_N', 'CH2_NP', 'CH2_R1A', 'CH2_R2A'))
DIGITAL = ('/SDA1', '/SCL1')


def _pad_on(ref, net):
    p = next(q for q in PARTS if q['ref'] == ref)
    return [(ref, k) for k, v in p['pins'].items() if v == net]


def _channel(n, bnc, r1, rnp, riso, adc, a):
    ch = f'CH{n}'
    return dict(name=ch, bnc=(bnc, '1'), prot=r1, rnp=rnp, opamp='U101', riso=riso, out_pin=_pad_on('U101', f'{ch}_OUT')[0],
                adc_pad=('J602', adc), out_nets=(a, _n(f'{ch}_OUT')),
                hiz_nets=tuple(_n(f'{ch}_{x}') for x in ('N', 'NP', 'R1A', 'R2A')))


CHANNELS = (_channel(1, 'J101', 'R102', 'R106', 'R107', '7', '/A1'), _channel(2, 'J201', 'R202', 'R206', 'R207', '8', '/A0'))
DIVIDER_GROUPS = tuple(tuple(_n(f'CH{n}_{x}') for x in ('N', 'NP', 'R1A', 'R2A')) for n in (1, 2))
CH_FLOW_TEXT = 'BNC > R1 > Rnp > U101 > Riso > ADC pad'
AWG = dict(name='AWG', dac_net='/DAC0', fb_net='/AWG_INV', back_term=('R304', 'R306'), bnc='J301', shell_pin='2')
FEED_PAD = ('J601', '5')
BNC_REFS = ('J101', 'J201', 'J301')
QUIET_REFS = ('U501', 'U502', 'R503', 'R504', 'R505', 'R506', 'R507', 'R508')

# a 100 nF at each supply pin, named per pin (the old tool searched for the nearest 100 nF; this names it)
DECOUP = [('C103', 'U101', '8'), ('C302', 'U301', '8'), ('C303', 'U301', '4'), ('C502', 'U502', '8'), ('C501', 'U501', '1')]
SUPPLY_CAPS = list(DECOUP)

RAILS = ('/+3V3A', '/VNEG')
_CONSUMER = {'AWG': 'AWG', 'SCOPE': 'SCOPE', 'REFCAL': 'REF/ADS'}
# the 0 ohm bridges that split a rail: (ref, net on pad 1, net on pad 2) from the design (R410: VNEG | VNEG_O; R411-R413: +3V3A | P33_G, P33_RN, P33_SC)
_RAIL_BRIDGES = [(q['ref'], '/' + q['pins']['1'], '/' + q['pins']['2']) for q in PARTS
                 if q['ref'] in ('R410', 'R411', 'R412', 'R413') and q['pins']['1'] != q['pins']['2']]
_FAMILY = {_r: {_r[1:]} | {n[1:] for _, a_, b_ in _RAIL_BRIDGES for n in (a_, b_) if _r in (a_, b_)} for _r in RAILS}
GROUPS = {}
for _rail in RAILS:
    GROUPS[_rail] = {}
    for _p in PARTS:
        if _FAMILY[_rail] & set(_p['pins'].values()) and BLOCK[_p['ref']] in _CONSUMER:
            GROUPS[_rail].setdefault(_CONSUMER[BLOCK[_p['ref']]], set()).add(_p['ref'])
STAR = {'/+3V3A': [('U401', '11'), ('C407', '1'), ('C408', '1')], '/VNEG': [('U401', '6'), ('C409', '1'), ('C410', '1')]}
BRIDGES = list(_RAIL_BRIDGES)
BRIDGE_PADS = []
RAIL_TEXT = '+3V3A and VNEG'
VREF_NET = '/VREF'
VREF_SOURCE = [('U501', '2'), ('C504', '1')]
VREF_BRANCHES = [sum((_pad_on(r, 'VREF') for r in rs), []) for rs in (('J602', 'R508'), ('U502', 'C503'), ('R307',), ('R512', 'R515'))]
CAP_PAIRS = ()
CAP_SELF = ()
DRC_ARM = dict(ref='R102', pin='1', net='/CH1_N')
