"""v1's scope and AWG models: v2's harnesses (v2/sim/scope, v2/sim/awg) with the v1 BOARD's values, as thin patches.

Nothing in v2/ or simtools/ is edited.  The v1 parameter table is PARAMS below, every value with its place in
kicad/design.py.  Two text patches per harness make the netlist the board's circuit instead of v2's wiring (each is listed
in README.md "Differences from v2's netlist" and is held by compare.py):
  scope: R3 is ONE 330k part to VREF (v2: a series pair); the supply decoupling is 100 nF + 10 uF (v2: 100 nF + 1 uF);
         the clamp's upper diodes return to P33_U through R108 1 ohm from the supply pin (v2: the same node)
  awg:   no 1 ohm Rb between the amplifier output and the feedback / output node (v2 has it); C304 10 pF across Rbin (v2: none);
         the divider's lower arm is two parts, R308 51k + R301 75k, with the node between them (v2: one 126k)
"""
import os, sys

AFE = os.environ.get('V1_AFE') or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

# ---- v1 parameter table: name -> (value, where it comes from in kicad/design.py)
PARAMS = {
    'R1 (R101)':   ((470e3, 300e3), 'SC[CH1/CH2][0]: R102+R103 / R202+R203, 470k + 300k, IN - N'),
    'R2 (R201)':   ((470e3, 330e3), 'SC[..][1]: R105+R101 / R205+R201, 470k + 330k, N - GND'),
    'R3':          ((330e3,),       'SC[..][2]: R104 / R204, one 330k, N - VREF'),
    'C1 (C101)':   (12e-12,  'C101 / C201 across R101, 12p C0G'),
    'Cn (C201)':   (30e-12,  'C102 / C202 from N to GND, 30p C0G'),
    'Rnp':         (680.0,   'R106 / R206, N - NP'),
    'Cpx (Cnp)':   (10e-12,  'C105 / C203, NP - GND, 10p C0G'),
    'Riso':        (22.0,    'R107 / R207, OUT - ADC pin'),
    'clamp':       ('BAV99', 'D101 / D201 (BAT54S symbol, value BAV99): GND / pin / P33_U'),
    'Cvcc':        ((100e-9, 10e-6), 'C103 100n + C104 10u on SC_VCC ; R108 1R SC_VCC - P33_U feeds the clamps'),
    'AWG Rf':      (3300.0,  'R303 3.3k, AWG_OUT - AWG_INV'),
    'AWG Cf':      (10e-12,  'C301 10p across Rf'),
    'AWG Rg2':     (4990.0,  'R302 4.99k, AWG_INV - AWG_X'),
    'AWG Rbin':    (51e3,    'R305 51k, DAC0 - AWG_BIN'),
    'AWG Cbin':    (10e-12,  'C304 10p C0G across Rbin (DAC0 - AWG_BIN)'),
    'AWG Rbpl':    ((51e3, 75e3), 'R308 51k + R301 75k, AWG_BIN - GND'),
    'AWG Rvr':     (100.0,   'R307 100, VREF - AWG_X'),
    'AWG Cvr':     (20e-6,   'C305 + C306, 10u X5R each, AWG_X - GND (nominal; v2 derated to 14 uF effective)'),
    'AWG Rout':    (50.0,    'R304 || R306, two 100 1206, AWG_OUT - AWG_BNC'),
}

# ---- the extracted strays and the cases (definition: v2/sim/scope/sensitivity_n_stray.json "cases"), pF.  Values: README.md
# top of the error bar of cap.py --converge on kicad/wip/v1_merge5.kicad_pcb (results/cap_converge.txt)
STRAYS = dict(N_top=0.83, IN_top=2.57, NN=0.00005, PADPAD=0.00062, ININ=0.00005, AWG_INV_top=0.61)
CASES = {   # Cn_par, Cx, Cxp, Cxin, Cwire  (pF)
    'baseline': (3.5, 0.0, 0.0, 0.0, 4.0),                                         # v2's assumptions: 3.5 pF at N, 4 pF BNC + trace
    'A': (3.5 + STRAYS['N_top'], STRAYS['NN'], STRAYS['PADPAD'], STRAYS['ININ'], 4.0 + STRAYS['IN_top']),   # extraction ADDED
    'B': (STRAYS['N_top'], STRAYS['NN'], STRAYS['PADPAD'], STRAYS['ININ'], STRAYS['IN_top']),               # extraction REPLACES
}
AWG_CASES = {'baseline_2pF': 2.0, 'A_2pF_plus_top': 2.0 + STRAYS['AWG_INV_top'], 'B_top_only': STRAYS['AWG_INV_top'],
             'budget_10pF': 10.0, 'budget_30pF': 30.0, 'fail_60pF': 60.0}


def scope_setup(case, out_dir, work=None):
    """import v2's scope harness, patch it to v1's circuit, return (R, NL).  case: a key of CASES"""
    sys.path.insert(0, AFE)
    sys.path.insert(0, os.path.join(AFE, 'v2', 'sim', 'scope'))
    import run as R
    import netlib as NL
    cn_par, cx, cxp, cxin, cwire = (x * 1e-12 for x in CASES[case])
    NL.P0.update(R1=PARAMS['R1 (R101)'][0], R2=PARAMS['R2 (R201)'][0], R3=(330e3, 0.0), C1=PARAMS['C1 (C101)'][0],
                 Cn=PARAMS['Cn (C201)'][0], Rnp=PARAMS['Rnp'][0], Cpx=PARAMS['Cpx (Cnp)'][0], Riso=PARAMS['Riso'][0],
                 Cn_par=cn_par, Cx=cx, Cxp=cxp, Cxin=cxin, Cwire=cwire)
    chan0, rails0 = NL.chan, NL.rails

    def chan(p, k, **kw):          # R3 is one part: drop the second half of v2's series pair, the first goes to REF
        t = chan0(p, k, **kw)
        out = []
        for ln in t.split('\n'):
            if ln.startswith(f'R3b{k} '):
                continue
            if ln.startswith(f'R3a{k} '):
                ln = f'R3a{k} {k}n ref {p["R3"][0]:.6g}'
            if ln.startswith(f'Dpb{k} '):          # the clamp's upper diode returns to P33_U, behind R108 (1 ohm) from the supply pin
                ln = ln.replace(' vccl ', ' vclp ')
            out.append(ln)
        return '\n'.join(out)

    def rails(p, ac_vcc=False):     # 100 nF + 10 uF at the supply pin (v2: 1 uF)
        t = rails0(p, ac_vcc)
        assert 'Cdc2 vccl cd2 1u' in t
        return t.replace('Cdc2 vccl cd2 1u', 'Cdc2 vccl cd2 10u') + 'R108 vccl vclp 1\n'
    NL.chan, NL.rails = chan, rails
    R.chan, R.rails = chan, rails        # run.py did `from netlib import *`
    NL.set_workdir(work)
    R.set_out(out_dir)
    return R, NL


def scope_netlist(R, NL):
    """the circuit as one text, both channels, the way v2's sec_netlist writes it (nominal strays of the chosen case)"""
    p = R.pp()
    return (NL.header('v1_scope') + NL.rails(p) + 'Vsa asrc 0 dc 1.0 ac 1\nVsb bsrc 0 dc 1.0\n' + NL.chan(p, 'a') + NL.chan(p, 'b')
            + NL.coupling(p) + '.end\n')


def awg_setup(work=None):
    """import v2's AWG harness, patch it to v1's circuit, return core (v2/sim/awg/netlist.py); core.V1 is the parameter set"""
    sys.path.insert(0, os.path.join(AFE, 'v2', 'sim', 'awg'))
    sys.path.insert(0, AFE)
    import netlist as core
    import tempfile
    core.set_workdir(work or tempfile.mkdtemp(prefix='v1-awg-'))
    build0 = core.build
    core.V1 = dict(Rf=PARAMS['AWG Rf'][0], Rg2=PARAMS['AWG Rg2'][0], Cf=PARAMS['AWG Cf'][0], Rbin=PARAMS['AWG Rbin'][0],
                   Rbpl=sum(PARAMS['AWG Rbpl'][0]), Rvr=PARAMS['AWG Rvr'][0], Cvr=PARAMS['AWG Cvr'][0], Rout=PARAMS['AWG Rout'][0],
                   topo='Single', Cout=0.0, Rb=1.0)
    core.CBIN = [PARAMS['AWG Cbin'][0]]      # a list so a driver can switch C304 off for the with/without comparison

    def build(p=None, **kw):
        t = build0(p, **kw)
        out = []
        for ln in t.split('\n'):
            if ln.startswith('Rba oa vo '):      # v2's 1 ohm between the amplifier and its feedback / output node: not on the board
                continue
            if ln.startswith('XA bin') or ln.startswith('XB bin'):
                ln = ln.replace(' oa ', ' vo ').replace(' ob ', ' vo ')
            if ln.startswith('Rbpl bin 0 '):         # R308 + R301 with the node between them
                a, b = PARAMS['AWG Rbpl'][0]
                ln = f'Rbpl1 bin bpl {a:.6g}\nRbpl2 bpl 0 {b:.6g}'
            out.append(ln)
        t = '\n'.join(out)
        if core.CBIN[0]:
            head, sep, tail = t.rpartition('\n.end\n')       # the last .end: the model text above has '.ends' lines
            assert sep, 'no .end in the AWG netlist'
            t = head + f'\nCbin dac bin {core.CBIN[0]:.6g}' + sep + tail
        return t
    core.build = build
    return core
