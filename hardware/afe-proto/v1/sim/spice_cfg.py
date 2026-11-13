"""v1's configuration for pcbtools.spicecmp (same names as pcbtools/boards/v2_checks.py): how each study netlist is reduced.
Every dropped element has its reason; an element the rules do not know fails the comparison (spicecmp.read_spice)."""
SPICE_IGNORE_LIBS = ('Conn_Coaxial', 'TestPoint')
SPICE_IGNORE_VALUES = ('KH-BNC50-3511',)
DIODE_PAIR_LIBS = {'BAT54S': dict(value='BAV99', model='DBAV99', first=('1', '3'), second=('3', '2'))}
AMP_LIBS = {'TPH2502': dict(halves='AB', roles={'inp': '+IN{h}', 'inn': '-IN{h}', 'out': 'OUT{h}'}, shared={'vp': 'V+', 'vn': 'V-'})}
# 0 ohm parts are shorts that merge two nets (spicecmp takes startswith(tuple)): the wall / corridor bridges and R108 (below)
BRIDGE_PREFIX = None          # filled by compare.py from the schematic: every part whose value is 0 ohm
SPICE_BLOCKS = {'scope': {'ch1', 'ch2'}, 'awg': {'awg'}}
SPICE_RULES = {
    'scope': dict(
        # the 0R bridges merge VREF with AREF and +3V3A with P33_U; spicecmp names a merged net by its shortest name
        anchors={'0': 'GND', 'vccl': 'SC_VCC', 'vclp': '+3V3A', 'ref': 'AREF'},
        drop={
            'Vcc': 'rail source', 'Rvc': 'rail source impedance', 'Lvc': 'rail lead inductance',
            'Vr': 'reference source', 'Rvr': 'reference output impedance',
            'Cr1u': 'REF3030E output capacitor (the power / REFCAL block, not the scope block)', 'Rcr1': 'its ESR',
            'Cr100': 'REF3030E output 100 nF (REFCAL block)', 'Rcr2': 'its ESR',
            'Vsa': 'signal source', 'Vsb': 'signal source', 'Rsa': 'source impedance', 'Rsb': 'source impedance',
            'Cwa': 'cable / BNC stray (the extracted IN stray plus the BNC)', 'Cwb': 'cable / BNC stray',
            'Cr1a': 'stray across R1', 'Cr1b': 'stray across R1',
            'Cnpa': 'stray at N (the extracted figure)', 'Cnpb': 'stray at N',
            'Cfba': 'stray at the inverting pin', 'Cfbb': 'stray at the inverting pin',
            'Cpina': 'ADC pin capacitance', 'Cpinb': 'ADC pin capacitance',
            'Cxn': 'extracted N-N stray', 'Cxi': 'extracted IN-IN stray', 'Cxp': 'extracted NP-NP stray',
        },
        short=['Vfba', 'Vfbb'],
        esr=[('Cdc1', 'Rdc1'), ('Cdc2', 'Rdc2')],
        subckt_models={'TPH2501_simplify': 'OA', 'TPH2502': 'OA', 'TPH2502_SAT': 'OA'}),
    'awg': dict(
        anchors={'0': 'GND', 'vcc': '+3V3A', 'vee': 'VNEG', 'vrf0': 'AREF', 'dac': 'DAC0'},
        drop={
            'Vvp': 'rail source', 'Vvn': 'rail source', 'Rvp': 'rail source impedance', 'Rvn': 'rail source impedance',
            'Vdac': 'DAC source', 'Rdacs': 'DAC source impedance',
            'Vrf': 'reference source', 'Rzr': 'reference output impedance', 'Czr': 'REF3030E output capacitor (REFCAL block)',
            'Cfb': 'stray at the inverting node (the extracted figure)',
            'Rl': 'load', 'Cl': 'load capacitance',
        },
        short=[], esr=[],
        subckt_models={'TPH2501_simplify': 'OA', 'TPH2502': 'OA', 'TPH2502_SAT': 'OA'}),
}
