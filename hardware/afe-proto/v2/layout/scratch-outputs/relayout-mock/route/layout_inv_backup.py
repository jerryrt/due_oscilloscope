# hand pre-routes for the relayout: AWG_FB, CH1_N, CH2_N (hand/routes_inv.py); the router completes the rest around them
import os
_ns = {}
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hand', 'routes_inv.py')).read(), _ns)
PREROUTE = _ns['ROUTES']
PREEND = []
PREVIA = []
BRIDGE_PADS = []
PSEUDO_PRE = False
