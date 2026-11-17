"""AFE-2 board data for pf.py (the generic router core). Another board supplies its own module of the same names and runs
`PF_CFG=<module> python3 pf.py ...` with the module on the path. Everything here is data; pf.py has no board knowledge."""
# coordinate frame: user mm = board mm - ORIGIN_X in x, ORIGIN_Y - board mm in y (the Due frame, y up)
ORIGIN_X, ORIGIN_Y = 50.0, 150.0
# routing area in user mm (grid extent) and the hard limits inside it
GRID = (16.0, -5.0, 118.0, 58.5)
EDGE_BOX = (17.0 + 0.65, -4.5 + 0.65, 117.0 - 0.65, 53.34 - 0.2)      # tracks stay inside: board edge 0.45 + margin, the far-edge keep-out band at y 53.34
# clearances, mm: track to track centre distance is 2*INFL-ish (see pf.py), track centre to a pad edge INFL_PAD, to a hi-Z track INFL_HIZ
INFL, INFL_PAD, INFL_HIZ = 0.355, 0.26, 0.9
TRACK_W = 0.2
# nets (names as the board has them)
HIZ = {'/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP', '/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP'}      # tracks keep INFL_HIZ from everything else
SENS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/CH1_N', '/CH2_N')           # name prefixes kept SENS_KEEP_MM from SENS_FROM
SENS_FROM, SENS_KEEP_MM = ('U401', 'C409'), 10.0
DIGITAL = ('/SDA', '/SCL')                                       # kept out of the courtyards of ANALOG_REFS (except parts on the net itself)
ANALOG_REFS = ['C101', 'C102', 'C103', 'C104', 'C105', 'C201', 'C202', 'C203', 'C301', 'C303', 'C304', 'C305', 'C306', 'C501', 'C502', 'C503', 'D101', 'D201', 'R101', 'R102', 'R103', 'R104', 'R105', 'R106', 'R107', 'R108', 'R201', 'R202', 'R203', 'R204', 'R205', 'R206', 'R207', 'R208', 'R301', 'R302', 'R303', 'R304', 'R305', 'R306', 'R307', 'R308', 'R309', 'R501', 'R502', 'R503', 'R504', 'R505', 'R506', 'R507', 'R508', 'R509', 'R510', 'R511', 'R512', 'R513', 'R514', 'U101', 'U301', 'U501', 'U502']
SKIP_NETS = ('/GND',)                                            # not routed (vias and stubs are fixed copper or added by the GND via pass)
GND_NET = '/GND'
GND_VIA_RADIUS_MM = 3.0                                          # a GND SMD pad needs a via of its own within this distance (rules.lr1), greedy in (ref, pin) order
# supply stars (LR-6): the star pads are joined by their own job, each consumer group is a separate pseudo net that reaches any star pad
STAR = {'/+3V3A': ['U401.11', 'C405.1', 'C406.1', 'R401.1', 'TP401.1', 'R407.1'], '/VNEG': ['U401.6', 'C407.1', 'C408.1', 'R403.1']}
GROUPS = {'/+3V3A': {'scope': ['U101.8', 'C104.1', 'C105.1', 'D201.2', 'D101.2'], 'awg': ['U301.8', 'C305.1'],
                     'adc': ['U501.1', 'C502.1', 'U502.8', 'C503.1', 'R512.1', 'R513.1']},
          '/VNEG': {'awg': ['U301.4', 'C306.1'], 'tp': ['TP402.1']}}
# the reference (LR-8): source pads joined by their own job, one pseudo net per branch
KELVIN = {'/VREF': dict(src=['U501.2', 'C501.1'], groups=[['J602.1', 'R506.2'], ['U502.4'], ['R514.1'], ['TP501.1'], ['R305.1'], ['R106.2', 'R509.2', 'R206.2']])}
