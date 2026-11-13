"""Planarity inputs for the v2 board: the protected-net patterns (montreal5's rule (a): a 0603 0R bridge may be added inside a
block when the crossed net is not an ADC line, a divider node or a VREF branch). A BoardConfig does not carry them, so
`planar.from_board` reads PROTECTED_NETS from the cfg when it has one and this table otherwise; tests pass it explicitly.
The edge points of v2 come from the as-built tracks (`planar.from_board` with no `edge_points`), which is what the consistency
test uses; the planned contract rows are floorplan.py's `C` in the frozen v2 fixture, whose net column is descriptive text and
so is not turned into data here.
"""
PROTECTED_NETS = ('/A0', '/A1',                       # the ADC lines
                  '/CH?_N', '/CH?_NP', '/CH?_IN',     # the divider nodes (N / NP / IN of both channels)
                  '/VREF*')                           # the VREF branches (VREF, VREF_M, VREF_P, ...)
