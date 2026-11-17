import os
_ns = {}
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hand', 'routes_pre.py')).read(), _ns)
PREROUTE = _ns['ROUTES']
PREEND = []
PREVIA = []
BRIDGE_PADS = []
PSEUDO_PRE = False
