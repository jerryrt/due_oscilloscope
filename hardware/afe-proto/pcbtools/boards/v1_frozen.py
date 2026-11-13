"""The FROZEN v1 config: boards/v1.py evaluated on the 34b2e51 inputs under tests/fixtures (the data the old tools' goldens were taken on),
for the equivalence tests against those tools. `boards/v1.py` itself is the live design (kicad/design.py, floorplan.py, layout.py)."""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SAVED = os.environ.get('PCBTOOLS_V1_SOURCE')
os.environ['PCBTOOLS_V1_SOURCE'] = os.path.normpath(os.path.join(_HERE, '..', '..', 'tests', 'fixtures', 'v1-34b2e51', 'kicad'))
try:
    with open(os.path.join(_HERE, 'v1.py')) as _f:
        exec(compile(_f.read(), os.path.join(_HERE, 'v1.py'), 'exec'), globals())      # noqa: S102  (the same module text, other inputs)
finally:
    if _SAVED is None:
        os.environ.pop('PCBTOOLS_V1_SOURCE', None)
    else:
        os.environ['PCBTOOLS_V1_SOURCE'] = _SAVED

# The 34b2e51 board predates the Due's pin names on the bands: the frozen config does not name its edge sockets, so LR-11 does not look for labels
# on it (rules.lr11 runs the pin-label check only for a config that defines EDGE_SOCKETS).
del EDGE_SOCKETS  # noqa: F821

# the 34b2e51 files carry the title-block revision 'FR-01'; the live config prints the board's REV (docs/afe.md D29)
REV = 'FR-01'  # noqa: F811

# the 34b2e51 board has J201 at Due y 24.13; the live config puts the three BNCs on one 18.525 mm pitch
BNCS = {'J101': 44.45, 'J201': 24.13, 'J301': 7.4}

# the 34b2e51 board carries no identity block: the live rule's extras stay off for it
IDENTITY_CHECK = False
SILK_WORDS = ('CH1', 'CH2', 'AWG', 'POWER', 'REF/CAL', 'ON')
