"""BoardConfig of the AFE v2 board: every table the layout rules (lr_check, LR-1..LR-12) and fence_check read, as
module-level names so a test can build a config from plain values (a types.SimpleNamespace with the same names works).

Values that already exist in design.py / floorplan.py / layout.py are imported from them, not copied: `_load_sources()` is
the ONE place that knows where those files are (the frozen fixture folder of commit 8a1f7ac, relative to this package);
it will switch to the live v2/kicad files later. The tables that lived only inside lr_check.py / fence_check.py / route.py
are written here, each with its origin.
"""
import importlib.util
import os
import sys

NAME = 'v2'
HERE = os.path.dirname(os.path.abspath(__file__))
# pcbtools/boards -> pcbtools -> hardware/afe-proto
SOURCE_DIR = os.path.normpath(os.path.join(HERE, '..', '..', 'tests', 'fixtures', 'v2-8a1f7ac'))


def _load_sources():
    """import design, floorplan and layout from SOURCE_DIR under private module names (nothing is put on sys.path)"""
    mods = {}
    for name in ('design', 'floorplan', 'layout'):
        spec = importlib.util.spec_from_file_location(f'_pcbtools_v2_{name}', os.path.join(SOURCE_DIR, name + '.py'))
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        mods[name] = m
    return mods['design'], mods['floorplan'], mods['layout']


_design, _floorplan, _layout = _load_sources()

BOARD = None                                  # default board path: the caller names it
ZONE_PAD = 0.3
HOP_MAX = 3.0                                 # LR-1: a bottom hop is at most 3 mm and 2 vias; no exemption for anything
HOP_MAX_VIAS = 2
KEEPOUT = 10.0                                # LR-5, LR-2
FB_MAX = 14.0                                 # LR-4
GEN = ('U401', 'C409')                        # the generator: charge pump and flying capacitor
INV_MAX = 5.0                                 # LR-4 (row 'LR-4 INV_MAX')
DECOUP_MAX = 3.0                              # LR-12
# cap ref -> (IC ref, supply pin), from lr_check.py
DECOUP = {'C104': ('U101', '8'), 'C105': ('U101', '8'), 'C305': ('U301', '8'), 'C306': ('U301', '4'),
          'C502': ('U501', '1'), 'C501': ('U501', '2'), 'C503': ('U502', '8')}

BLOCK = {p['ref']: _layout.BLOCK_OVERRIDE.get(p['ref'], p['block']) for p in _design.PARTS}      # ref -> block
BLOCK.update({r: v[2] for r, v in _layout.EXTRA.items()})
BLOCK_OVERRIDE = dict(_layout.BLOCK_OVERRIDE)
ANALOG_BLOCKS = ('CH1', 'CH2', 'AWG', 'REFCAL')
ANALOG_REFS = {p['ref'] for p in _design.PARTS if p['block'] in ANALOG_BLOCKS and not p['ref'].startswith(('J', 'TP', 'MH'))}
ANALOG_REFS |= {r for r, v in _layout.EXTRA.items() if v[2] in ANALOG_BLOCKS}
ANALOG_REFS = frozenset(ANALOG_REFS)
GENERATOR_BLOCK = frozenset(p['ref'] for p in _design.PARTS if p['block'] == 'POWER')
ANALOG_FENCE = ('CH1', 'CH2', 'AWG')          # LR-1: layout.OUTLINE rectangles of these blocks
OUTLINE = {k: list(v) for k, v in _layout.OUTLINE.items()}                         # LR-11 (silk outlines)
BRIDGE_PADS = list(_layout.BRIDGE_PADS)       # (ref, pin, ref, pin): the part joins its two pads (LR-6, LR-8)

XSENS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/AREF', '/AWG_FB', '/AWG_BIN', '/CH1_NP', '/CH2_NP',
         '/CH1_N', '/CH2_N', '/CH1_M', '/CH2_M', '/CH1_IN', '/CH2_IN')               # LR-1: bottom copper forbidden under
INV_NODES = ('/AWG_FB', '/CH1_N', '/CH2_N')   # LR-4: no via, no bottom copper
INV_LEN_NODES = ('/AWG_FB', '/CH1_OUT', '/CH2_OUT')   # LR-4 INV_MAX
SENSITIVE = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/CH1_N', '/CH2_N')   # LR-5
HIZ = ('CH1_N', 'CH1_M1', 'CH1_M2', 'CH1_M3', 'CH1_NP', 'CH2_N', 'CH2_M1', 'CH2_M2', 'CH2_M3', 'CH2_NP')   # LR-3
DIGITAL = ('/SDA', '/SCL')                    # LR-9
GROUPS = {'/+3V3A': {'scope': {'U101', 'C104', 'C105', 'BR101', 'BR102', 'D201', 'D101'},
                     'awg': {'U301', 'C305'}, 'adc': {'U501', 'C502', 'U502', 'C503', 'R512', 'R513', 'BR507'}},
          '/VNEG_G': {'awg': {'U301', 'C306', 'BR401'}}}                               # LR-6 consumer groups
STAR = {'/+3V3A': [('U401', '11'), ('C405', '1'), ('C406', '1'), ('R401', '1'), ('TP401', '1'), ('R407', '1')],
        '/VNEG_G': [('U401', '6'), ('C407', '1'), ('C408', '1'), ('R403', '1')]}      # LR-6 star pads, cut out
# LR-8: route.KELVIN['VREF'] of commit 8a1f7ac (route.py imports pcbnew, so it cannot be imported here): the source pads cut
# out of the VREF net, and the named branches, each a list of 'REF.PIN'
VREF_SOURCE = ['U501.2', 'C501.1']
VREF_BRANCHES = [['J602.1'], ['U502.4'], ['R514.1'], ['TP501.1'], ['R305.1'], ['R106.2', 'R509.2', 'BR503.1']]
# LR-11
LR_HUNDREDS = {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': 'EDGE'}
TEST_BLOCKS = ('CH1', 'CH2', 'AWG', 'POWER', 'REFCAL')
TP_NETS = {'TP101': '/A1', 'TP201': '/A0', 'TP301': '/AWG_VO', 'TP401': '/+3V3A', 'TP402': '/VNEG', 'TP403': '/+5V_F',
           'TP404': '/GND', 'TP501': '/VREF'}
SILK_WORDS = ('CH1', 'CH2', 'AWG', 'POWER', 'REF / CAL', 'CAL', 'ON')
DESIGNATOR_MIN_H = 0.79
# LR-2 / LR-7 constants of the old tool
CHANNELS = ((1, 100, 'J101', '7'), (2, 200, 'J201', '8'))        # channel, ref base, BNC, ADC header pin on J602
DIVIDER_X_MAX = 91.0

# fence_check
FENCES = {k: list(v) for k, v in _floorplan.FENCES.items()}
HUNDREDS = {'1': 'SCOPE', '2': 'SCOPE', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': None}    # fence ownership by digit
OWNER_OVERRIDE = {}
TOL_MM = 0.001
