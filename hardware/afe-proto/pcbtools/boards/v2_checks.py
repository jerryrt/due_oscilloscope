"""The AFE v2 schematic's checks: v2's own rows and arms (the part of the old check.py that was not generic), and the
configuration the generic rows (schematic_rows.py, schematic_check.py, spicecmp.py) read. This module IS the config: the names in
the first half are what those modules ask a board for; the second half is v2's rows C1..C5, B1, and its mutation arms.

    python -m pcbtools.boards.v2_checks [--project DIR] [--arms]     rows of the old check.py (and with --arms its 24 arms)
    python -m pcbtools.boards.v2_checks --build OUT                  write the project (schematic, .kicad_pro, tables, lib)

(schematic_check's CLI takes a board by name and runs its S/P rows; v2 has no PCB yet and runs the rows below, so its CLI is
here.) Rows, in the old order: S1 S2 S3 E1 E2 E3 E4 B1 N1 N2 D1 D2 C1 C2 C3 C4 C5 C6 H1; each is the old row's verdict and text.

Arms are FlipArms: each names the rows that must go from PASS (on the unchanged regenerated project) to FAIL (on the changed
one). An arm whose named row already fails on the clean board is NOT TESTABLE and counts against the M* row.
"""
import copy
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

from .. import schematic as sch
from .. import schematic_rows as sr
from .. import spicecmp
from ..schematic_check import Row
from .v2_sch import (AFE, BLOCK_ORDER, FOOTPRINT_DIR, HAND_FITTED, NOT_A_SYMBOL, PARTS, PROJECT, PROJECT_DIR,  # noqa: F401
                     PROJECT_LIB_NAME, PWR_FLAG_NETS, SIM_DIR, sch_cfg)

NAME = 'v2'
CFG = sys.modules[__name__]

# ------------------------------------------------------------------------------------------------ the generic rows' config
ERC_EXCLUDED = 1                          # the LM27762 PGOOD tied to ground, the one documented exclusion
MIN_NETS, MIN_COMPS, MIN_SPICE_ELEMENTS = 40, 90, 10      # floors: a check that examined fewer items than this did not run
COMPARE_FIELDS = (('Sim', 'sim'), ('Block', 'block'))      # S3 holds these fields to the part list besides value, footprint, LCSC
FITTED_BY_BOARD_HOUSE = 'JLC'
ROW_IDS = {'numbering': ('D1', 'D2'), 'bridge': 'C6'}      # the old check.py's ids of the numbering and bridge rows

# TPH2502 datasheet "Pin Configuration (Top View)", 8-pin SOP; TI SBAS444E table 4-1 (ADS1115, DGS); LM27762 SNVSAF7C table 4-1
# (WSON-12, DSS). Written from the datasheets, not from the symbols.
DATASHEET_PINS = {
    'TPH2502': {'1': 'OUTA', '2': '-INA', '3': '+INA', '4': 'V-', '5': '+INB', '6': '-INB', '7': 'OUTB', '8': 'V+'},
    'ADS1115': {'1': 'ADDR', '2': 'ALERT/RDY', '3': 'GND', '4': 'AIN0', '5': 'AIN1', '6': 'AIN2', '7': 'AIN3',
                '8': 'VDD', '9': 'SDA', '10': 'SCL'},
    'LM27762': {'1': 'PGOOD', '2': 'FB+', '3': 'VIN', '4': 'GND', '5': 'CP', '6': 'OUT-', '7': 'FB-', '8': 'EN-',
                '9': 'C-', '10': 'C+', '11': 'OUT+', '12': 'EN+', '13': 'PAD'},
}
# ADS1115 differential pairs the multiplexer can select (SBAS444E MUX[2:0]): (AINP, AINN)
ADS_DIFF = {(0, 1), (0, 3), (1, 3), (2, 3)}

# LR-11: the hundreds digit of a designator is its block. The key part list of each block is written out here and not derived from
# design.py: a block outline on the board contains exactly these parts. U101 is the dual both channels share and sits in CH1.
BLOCKDIGIT = {'CH1': 1, 'CH2': 2, 'AWG': 3, 'POWER': 4, 'REFCAL': 5, 'EDGE': 6}


def _rng(prefix, a, b):
    return {f'{prefix}{k}' for k in range(a, b + 1)}


KEY_PARTS = {
    'CH1': {'J101', 'U101', 'D101', 'TP101', 'BR101'} | _rng('R', 101, 108) | _rng('C', 101, 105),
    'CH2': {'J201', 'D201', 'TP201', 'BR201'} | _rng('R', 201, 208) | _rng('C', 201, 203),
    'AWG': {'U301', 'J301', 'C301', 'TP301'} | _rng('R', 301, 309) | _rng('C', 303, 306),
    'POWER': {'U401'} | _rng('R', 401, 407) | _rng('C', 401, 409) | _rng('TP', 401, 404),
    'REFCAL': {'U501', 'U502', 'J501', 'TP501'} | _rng('R', 501, 514) | _rng('C', 501, 503),
    'EDGE': _rng('J', 601, 607) | {'MH601', 'MH602'},
}

# the bridges (placeholders until the layout names the nets): BR101 from the +3V3A rail (the LM27762's OUT+) to the dual's V+
# segment, BR201 from CH2's Riso / clamp side to the Due A0 pin; the CH2 clamp D201 sits on the dual side of both
BRIDGE_JOINS = {'BR101': (('fn', 'U401', 'OUT+'), ('fn', 'U101', 'V+')), 'BR201': (('pin', 'R208', '2'), ('pin', 'J602', '8'))}
BRIDGE_SIDES = [(('pin', 'D201', '3'), ('pin', 'R208', '2')), (('pin', 'D201', '2'), ('fn', 'U101', 'V+'))]
BRIDGE_TEXT = 'the CH2 clamp D201 sits on the dual side of both'

# The Due header-pin table (docs/due-header-table.md, V03): header -> {pin: net}. Everything else passes through. The AFE's SDA/SCL are
# the SAM3X's TWI0 on PWMH0.9 / .10 (labelled SDA1 / SCL1 on the header, no on-board pull-ups there; TWI1 is D20/D21).
HEADER_TABLE = {
    'POWER0': {'5': '+5V_DUE', '6': 'GND', '7': 'GND'},
    'ADCL0': {'1': 'VREF', '2': 'TAP5', '3': 'TAP4', '4': 'TAP3', '5': 'TAP2', '6': 'TAP1', '7': 'A1', '8': 'A0'},
    'ADCH0': {'5': 'DAC0'},
    'PWMH0': {'7': 'GND', '8': 'AREF', '9': 'SDA', '10': 'SCL'},
    'XIO0': {'35': 'GND', '36': 'GND'},
    'PWML0': {}, 'COMMUNICATION0': {},
}
HEADER_BLOCK, HEADER_PART_PREFIX, HEADER_LABEL = 'EDGE', 'Conn_0', 'Due'

# ------------------------------------------------------------------------------------------------ the SPICE comparison's config
BRIDGE_PREFIX = 'BR'
DIODE_PAIR_LIBS = {'BAT54S': dict(value='BAV99', model='DBAV99', first=('1', '3'), second=('3', '2'))}
# SOT-23 BAV99 drawn with the series-pair symbol: 1 anode of D1, 2 cathode of D2, 3 cathode of D1 and anode of D2
AMP_LIBS = {'TPH2502': dict(halves='AB', roles={'inp': '+IN{h}', 'inn': '-IN{h}', 'out': 'OUT{h}'}, shared={'vp': 'V+', 'vn': 'V-'})}
SPICE_IGNORE_LIBS = ('Conn_Coaxial', 'TestPoint')
SPICE_IGNORE_VALUES = ('KH-BNC50-3511',)
SPICE_BLOCKS = {'scope': {'CH1', 'CH2'}, 'awg': {'AWG'}}      # the Block fields each study's circuit spans
SPICE_ROWS = (('N1', 'scope', os.path.join('scope', 'scope_v2.cir')), ('N2', 'awg', os.path.join('awg', 'awg.cir')))
SPICE_RULES = {
    'scope': dict(
        anchors={'0': 'GND', 'vccl': '+3V3A', 'ref': 'VREF'},
        drop={
            'Vcc': 'rail source', 'Rvc': 'rail source impedance', 'Lvc': 'rail lead inductance',
            'Vr': 'reference source', 'Rvr': 'reference output impedance',
            'Cr1u': 'REF3030E output capacitor model (1 uF): the power block\'s C410',
            'Rcr1': 'its ESR', 'Cr100': 'REF3030E output 100 nF in the study; the final powercal parts.csv puts the '
                                      '100 nF at the reference INPUT (C411): a recorded difference of the studies',
            'Rcr2': 'its ESR',
            'Vsa': 'signal source', 'Vsb': 'signal source', 'Rsa': 'source impedance', 'Rsb': 'source impedance',
            'Cwa': 'cable / BNC stray', 'Cwb': 'cable / BNC stray',
            'Cr1a': 'stray across R1 (100 fF)', 'Cr1b': 'stray across R1 (100 fF)',
            'Cnpa': 'stray at N (3.5 pF)', 'Cnpb': 'stray at N (3.5 pF)',
            'Cfba': 'stray at the inverting pin', 'Cfbb': 'stray at the inverting pin',
            'Cpina': 'ADC pin capacitance', 'Cpinb': 'ADC pin capacitance',
        },
        short=['Vfba', 'Vfbb'],                  # 0 V ammeters in the feedback wire
        esr=[('Cdc1', 'Rdc1'), ('Cdc2', 'Rdc2')],
        subckt_models={'TPH2501_simplify': 'OA', 'TPH2502': 'OA', 'TPH2502_SAT': 'OA'}),
    'awg': dict(
        anchors={'0': 'GND', 'vcc': '+3V3A', 'vee': 'VNEG', 'vrf0': 'VREF', 'dac': 'DAC0'},
        drop={
            'Vvp': 'rail source', 'Vvn': 'rail source', 'Rvp': 'rail source impedance', 'Rvn': 'rail source impedance',
            'Vdac': 'DAC source', 'Rdacs': 'DAC source impedance',
            'Vrf': 'reference source', 'Rzr': 'reference output impedance',
            'Czr': 'REF3030E output capacitor model: the power block\'s C410',
            'Cfb': 'stray at the inverting node', 'Cpv': 'stray at the + input',
            'Rl': 'load', 'Cl': 'load capacitance',
        },
        short=[], esr=[],
        # the study models the two 10 uF X5R 0805 filter capacitors as 14 uF "effective at 3 V bias" (parts.csv, C3 C4)
        derate={'Cvr': (0.7, 'two 10 uF X5R at 3 V bias: 14 uF effective against 20 uF nominal')},
        subckt_models={'TPH2501_simplify': 'OA', 'TPH2502': 'OA', 'TPH2502_SAT': 'OA'}),
}


def spice_texts(sim_dir=SIM_DIR):
    return {block: open(os.path.join(sim_dir, rel)).read() for _, block, rel in SPICE_ROWS}


# ------------------------------------------------------------------------------------------------ B1: the studies' parts.csv
def csv_rows(path):
    return list(csv.DictReader(open(path)))


def expand_refs(s):
    """'R1,R2 (parallel)' -> [R1, R2]; 'R_L1..R_L6' -> [R_L1 .. R_L6]; 'C_IN1,C_IN2' -> two."""
    s = re.sub(r'\(.*?\)', '', s)
    out = []
    for t in (x.strip() for x in s.split(',')):
        m = re.match(r'^(.*?)(\d+)\.\.(.*?)(\d+)$', t)
        if m and m.group(1) == m.group(3):
            out += [f'{m.group(1)}{k}' for k in range(int(m.group(2)), int(m.group(4)) + 1)]
        elif t:
            out.append(t)
    return out


def csv_value(s):
    m = re.match(r'^\s*([0-9]*\.?[0-9]+)\s*(p|n|u|k|M)?\s*(?:F|ohm|R)\b', s) or re.match(r'^\s*([0-9]*\.?[0-9]+)\s*(p|n|u|k|M)\b', s)
    if not m:
        return None
    return spicecmp.sig(float(m.group(1)) * (spicecmp.SI[m.group(2)] if m.group(2) else 1))


def study_rows(sim_dir=SIM_DIR):
    """Sim key -> (expected count, value text, lcsc)."""
    want = {}
    rows = csv_rows(os.path.join(sim_dir, 'scope', 'parts.csv'))
    dup = {}
    for r in rows:
        dup[r['refdes_per_channel']] = dup.get(r['refdes_per_channel'], 0) + 1
    for r in rows:
        ref = r['refdes_per_channel']
        key = 'scope.' + ref + (' ' + r['value'].split()[0] if dup[ref] > 1 else '')
        want[key] = (int(r['qty_per_board']), r['value'], r['lcsc'])
    for study, tag in (('awg', 'awg'), ('powercal', 'pc')):
        for r in csv_rows(os.path.join(sim_dir, study, 'parts.csv')):
            refs = expand_refs(r['refs'])
            per = int(r['qty']) if len(refs) == 1 else 1
            for ref in refs:
                want[f'{tag}.{ref}'] = (per, r['value'], r['lcsc'])
    return want


def b1_row(parts, sim_dir, tag=''):
    want_rows = study_rows(sim_dir)
    d1 = []
    cnt = {}
    for p in parts:
        if p['sim']:
            cnt[p['sim']] = cnt.get(p['sim'], 0) + 1
            if p['sim'] not in want_rows:
                d1.append(f"{p['ref']} Sim {p['sim']!r} is in no parts.csv")
                continue
            n, v, lc = want_rows[p['sim']]
            if p['lcsc'] != lc:
                d1.append(f"{p['ref']} LCSC {p['lcsc']} != {lc} ({p['sim']})")
            a, b = spicecmp.parse_value(p['value']) if not re.match(r'^[A-Za-z]', p['value']) else None, csv_value(v)
            if a is not None or b is not None:
                if a is None or b is None or spicecmp.sig(a) != b:
                    d1.append(f"{p['ref']} value {p['value']!r} != {v!r} ({p['sim']})")
    for k, (n, v, lc) in want_rows.items():
        if k in NOT_A_SYMBOL:          # a loose part: it must be on the hand-fitted list instead
            if not any(NOT_A_SYMBOL[k] in h and k.split('.')[1] in h for h in HAND_FITTED):
                d1.append(f'{k} is not a symbol and not on the hand-fitted list')
            continue
        if cnt.get(k, 0) != n:
            d1.append(f'{k}: {cnt.get(k, 0)} placed, parts.csv says {n}')
    return Row('B1' + tag, not d1 and len(cnt) >= 50, f'{len(cnt)} studied parts against {len(want_rows)} parts.csv keys{sr.tail(d1)}')


def block_of_parts(parts=None):
    """ref -> block for every part, for the layout's containment check: a block's outline must contain exactly these"""
    return {p['ref']: p['block'] for p in (PARTS if parts is None else parts)}


# ------------------------------------------------------------------------------------------------ C1..C5: the power / calibration block
def _c1(p, tag):
    pf = p.pf
    R = sr.rmap(p)
    real = p.real
    u = [r for r, c in p.comps.items() if c['part'] == 'LM27762'][0]
    n = lambda fn: pf[(u, fn)]      # noqa: E731
    r1, r2 = sr.chain(R, n('OUT+'), n('FB+'), real), sr.chain(R, n('FB+'), 'GND', real)
    r3, r4 = sr.chain(R, n('OUT-'), n('FB-'), real), sr.chain(R, n('FB-'), 'GND', real)
    msg, good = '', False
    if None not in (r1, r2, r3, r4):
        vp, vn = 1.2 * (r1 + r2) / r2, -1.22 * (r3 + r4) / r4
        good = abs(vp - 3.318) < 0.002 and abs(vn + 2.003) < 0.002 and r2 >= 50e3 and r4 >= 50e3
        msg = f'V+ = {vp:.4f} V (R1 {r1:g}, R2 {r2:g}), V- = {vn:.4f} V (R3 {r3:g}, R4 {r4:g}); expect 3.318 and -2.003'
    # the enables: tied straight to VIN, no net of their own (SNVSAF7C section 6.1: "Enable inputs can be also shorted together and
    # connected to VIN"; abs max EN pins GND - 0.3 V to VIN, VIH 1.2 V; no series resistor is required)
    en_ok = pf[(u, 'EN+')] == pf[(u, 'EN-')] == pf[(u, 'VIN')]
    good = good and en_ok
    msg += f'; EN+ and EN- on the VIN net {pf[(u, "VIN")]}: {en_ok}'
    return Row('C1' + tag, good, msg or 'feedback networks not found as series chains')


def _c2(p, tag):
    pn, pf = p.pn, p.pf
    R = sr.rmap(p)
    comps = p.comps
    rungs = sorted((r for r, c in comps.items() if (c['fields'].get('Sim') or '').startswith('pc.R_L')),
                   key=lambda r: comps[r]['fields']['Sim'])
    msg, good = '', False
    if len(rungs) == 6:
        cur, taps, vals = 'GND', [], []
        left = set(rungs)
        while left:
            nxt = [r for r in left if cur in R[r][1:]]
            if len(nxt) != 1:
                break
            r = nxt[0]
            left.discard(r)
            vals.append(R[r][0])
            cur = R[r][2] if R[r][1] == cur else R[r][1]
            taps.append(cur)
        top_ok = (not left and taps and taps[-1] == 'VREF' and len(set(vals)) == 1)
        tapnames = dict(zip(range(1, 7), taps))
        due = {pin: pn.get(('J602', pin)) for pin in '12345678'}
        want_due = {str(7 - k): tapnames[k] for k in range(1, 7)}       # tap k on A(k+1) = ADCL0 pin 7-k; top = pin 1
        ads = [r for r, c in comps.items() if c['part'] == 'ADS1115'][0]
        two_thirds_ok = pf[(ads, 'AIN1')] == tapnames[4]
        due_ok = all(due[q] == want_due[q] for q in want_due)
        good = bool(top_ok and due_ok and two_thirds_ok)
        msg = (f'{len(vals)} rungs of {sorted(set(vals))}, taps {taps}, Due A2..A7 on taps {due_ok}, '
               f'ADS1115 AIN1 on the 2/3 tap {two_thirds_ok}')
    return Row('C2' + tag, good, msg or 'ladder rungs not found')


def _c3(p, tag):
    pn, pf, comps = p.pn, p.pf, p.comps
    R = sr.rmap(p)
    by_sim = lambda s: sr.by_field(p, 'Sim', s)      # noqa: E731
    g = lambda s: R[by_sim(s)[0]]      # noqa: E731
    rt, rb, rd, rs, rm = (g('pc.R_SRT'), g('pc.R_SRB'), g('pc.R_SRD'), g('pc.R_SRS'), g('pc.R_SRM'))
    ads = [r for r, c in comps.items() if c['part'] == 'ADS1115'][0]
    awg = pn[('J301', '1')]
    t0 = (set(rt[1:]) - {awg}).pop() if awg in rt[1:] else None
    b = (set(rd[1:]) - {'VREF'}).pop() if 'VREF' in rd[1:] else None
    ain_of = lambda rr: next((int(fn[3]) for (r_, fn), net in pf.items() if r_ == ads and fn.startswith('AIN') and net in rr[1:]      # noqa: E731
                              and net not in (t0, b)), -1)
    k = rb[0] / (rt[0] + rb[0])
    parallel = rt[0] * rb[0] / (rt[0] + rb[0])
    conds = {
        'Rt from the AWG BNC node to T0': t0 is not None,
        'Rb between T0 and B': set(rb[1:]) == {t0, b},
        'Rd from B to the reference (permanent tie)': b is not None,
        'k = 0.4': abs(k - 0.4) < 1e-9,
        'AIN2 = T0 through Rs': pf[(ads, 'AIN2')] in rs[1:] and t0 in rs[1:],
        'AIN3 = B through Rm': pf[(ads, 'AIN3')] in rm[1:] and b in rm[1:],
        'Rm matches Rs + Rt||Rb within 2 %': abs(rm[0] - (rs[0] + parallel)) / rm[0] < 0.02,
        'AIN0 = reference': pf[(ads, 'AIN0')] == 'VREF',
        'the pair (T0 input, B input) is a valid mux setting': (ain_of(rs), ain_of(rm)) in ADS_DIFF,
        'J501 pin 2 = B': pn[('J501', '2')] == b,
        'no clamp diode on the sense inputs': not [r for r, c in comps.items() if c['part'] == 'BAT54S'
                                                   and any(pn.get((r, q)) in (t0, b) for q in '123')],
    }
    bad = [k_ for k_, v in conds.items() if not v]
    return Row('C3' + tag, not bad, f'k = {k:.3f}, Rm {rm[0]:g} vs Rs + Rt||Rb {rs[0] + parallel:g}'
               + (': failed ' + '; '.join(bad) if bad else ''))


def _c4(p, tag):
    pn, comps = p.pn, p.comps
    # the calibration header: 1x3 "CAL", pin 1 TAP4 (2/3 tap, 2.0 V) | pin 2 B | pin 3 TAP3 (1/2 tap, 1.5 V)
    hdr = {q: pn.get(('J501', q)) for q in '123'}
    b = hdr['2']
    on_b = {r for (r, q), net in pn.items() if net == b and r != 'J501'}
    nj = [r for r, c in comps.items() if r == 'J501' and c['part'] == 'Conn_01x03']
    states = {'no shunt (default tie)': b, 'shunt 2-3 (calibrate)': f'B = {hdr["3"]}', 'shunt 1-2 (slip)': f'B = {hdr["1"]}'}
    return Row('C4' + tag, len(nj) == 1 and hdr['1'] == 'TAP4' and hdr['3'] == 'TAP3' and
               all(comps[r]['fields'].get('Sim', '').startswith('pc.R_SR') for r in on_b) and
               any('shunt' in h for h in HAND_FITTED),
               f'J501 is 1x3: pin 1 {hdr["1"]} (2/3 tap) | pin 2 B | pin 3 {hdr["3"]} (1/2 tap); B touches {sorted(on_b)} only; '
               f'states {states}; the shunt is on the hand-fitted list')


def _c5(p, tag):
    pn, comps = p.pn, p.comps
    scope = {r for r, c in comps.items() if c['fields'].get('Block') in ('CH1', 'CH2')}
    on_neg = sorted(r for (r, q), net in pn.items() if net == 'VNEG' and r in scope)
    ref_users = sorted(r for (r, q), net in pn.items() if net == 'VREF' and comps[r]['fields'].get('Block') in ('CH1', 'CH2', 'AWG')
                       and comps[r]['part'] == 'R')
    return Row('C5' + tag, not on_neg and len(ref_users) == 3,
               f'scope parts on the negative rail: {on_neg or "none"}; reference loaded by {ref_users} (R3b of both channels, Rg2)')


def computed_rows(p, tag=''):
    """C1..C5; a row whose inputs are missing fails with the exception, it does not stop the others"""
    out = []
    for f, cid in ((_c1, 'C1'), (_c2, 'C2'), (_c3, 'C3'), (_c4, 'C4'), (_c5, 'C5')):
        try:
            out.append(f(p, tag))
        except Exception as e:
            out.append(Row(cid + tag, False, f'{type(e).__name__}: {e}'))
    return out


# ------------------------------------------------------------------------------------------------ all rows
def all_rows(sch_path, parts, spice, tag='', sim_dir=SIM_DIR):
    """every row of the old check.py on one schematic file, in the old order"""
    p = sr.Project.read(sch_path, parts)
    rows = [sr.s1_row(sch_path, CFG, tag), sr.s2_row(p, CFG, tag), sr.s3_row(p, CFG, tag), sr.e1_row(p, CFG, tag),
            sr.e2_row(p, CFG, tag), sr.e3_row(p, CFG, tag), sr.e4_row(p, CFG, tag), b1_row(parts, sim_dir, tag)]
    rows += [sr.spice_row(p, CFG, cid, block, spice[block], tag) for cid, block, _ in SPICE_ROWS]
    rows += sr.d_rows(p, CFG, tag)
    rows += computed_rows(p, tag)
    rows += [sr.bridge_row(p, CFG, tag), sr.header_row(p, CFG, tag)]
    return rows


# ------------------------------------------------------------------------------------------------ mutation arms
def P(parts, ref):
    return next(p for p in parts if p['ref'] == ref)


def arm_value_scope(parts):
    P(parts, 'R101')['value'] = '51k 1%'                          # the scope's first R1 part, 510k -> 51k


def arm_value_awg(parts):
    P(parts, 'R303')['value'] = '4.7k 1%'                         # Rf, 3k -> 4.7k


def arm_swap_scope(parts):
    p = P(parts, 'U101')
    p['pins']['2'], p['pins']['3'] = p['pins']['3'], p['pins']['2']   # -INA and +INA exchanged


def arm_swap_awg(parts):
    p = P(parts, 'U301')
    p['pins']['5'] = 'AWG_FB'
    p['pins']['6'] = 'AWG_BIN'                                    # half B's inputs exchanged


def arm_delete_conn_awg(parts):
    P(parts, 'R304')['pins']['2'] = 'ORPHAN'                      # Rg2 no longer reaches the filter node


def arm_delete_conn_scope(parts):
    P(parts, 'C203')['pins']['2'] = 'ORPHAN'                      # CH2's Cpx no longer reaches ground


def arm_omit_pin(parts):
    del P(parts, 'R306')['pins']['2']                             # a pin silently left out: no NC declared


def arm_rail(parts):
    P(parts, 'R401')['value'] = '150k 1%'                         # +rail feedback top


def arm_ads_pair(parts):
    p = P(parts, 'U502')
    p['pins']['6'], p['pins']['7'] = p['pins']['7'], p['pins']['6']   # AIN2 <-> AIN3: the pair (3, 2) is no mux setting


def arm_lcsc(parts):
    P(parts, 'R401')['lcsc'] = 'C25804'


def arm_due(parts):
    p = P(parts, 'J604')
    p['pins']['9'], p['pins']['10'] = p['pins']['10'], p['pins']['9']


def arm_cal_header(parts):
    P(parts, 'J501')['pins']['3'] = 'TAP2'                         # the calibration pin moved to the 1/3 tap


def arm_block_field(parts):
    P(parts, 'R306')['block'] = 'POWER'                           # an AWG part claimed by another block


def arm_designator(parts):
    P(parts, 'R405')['ref'] = 'R505'                              # renumbered into the wrong hundred (nets follow by ref)


def arm_bridge_value(parts):
    P(parts, 'BR101')['value'] = '1k 1%'                          # a bridge that is not 0 ohm


def arm_bridge_open(parts):
    P(parts, 'BR201')['pins']['2'] = 'ORPHAN'                     # a bridge that no longer reaches the pin


def arm_enable(parts):
    P(parts, 'U401')['pins']['8'] = 'EN_LONG'                      # EN- on a net of its own: the long enable net the layout wants gone


def arm_ladder(parts):
    P(parts, 'R503')['value'] = '470R 1%'                         # one rung unequal


def arm_scope_neg(parts):
    P(parts, 'U101')['pins']['4'] = 'VNEG'                          # the scope dual's V- on the negative rail


def spice_scope_conn(t):
    t['scope'] = t['scope'].replace('Cpxa an anp', 'Cpxa an 0') if 'Cpxa an anp' in t['scope'] else t['scope'].replace('Cpxa anp 0', 'Cpxa an 0')


def spice_awg_value(t):
    s = t['awg'].replace('Rf vo fb 3000.0', 'Rf vo fb 3100.0')
    assert s != t['awg']
    t['awg'] = s


def spice_scope_value(t):
    s = t['scope'].replace('Cna an 0 1.2e-11', 'Cna an 0 1.5e-11')
    assert s != t['scope']
    t['scope'] = s


def spice_unknown_element(t):
    t['awg'] = t['awg'].replace('.op', 'Rextra bnc 0 1k\n.op')


ARM_NO_FLAG = 'GND'                                              # the PWR_FLAG net whose flag is removed


def flip_arms():
    """the 24 arms of the old check.py, in its order, as FlipArms"""
    A = sr.FlipArm
    arms = [A('scope value', ('N1', 'B1'), arm_value_scope), A('awg value', ('N2', 'B1'), arm_value_awg),
            A('scope pin swap', ('N1',), arm_swap_scope), A('awg pin swap', ('N2',), arm_swap_awg),
            A('awg connection deleted', ('N2', 'E2'), arm_delete_conn_awg),
            A('scope connection deleted', ('N1', 'E2'), arm_delete_conn_scope),
            A('pin left out without NC', (), arm_omit_pin),
            A('rail feedback value', ('C1', 'B1'), arm_rail), A('ADS1115 pair', ('C3',), arm_ads_pair),
            A('LCSC changed', ('B1',), arm_lcsc), A('Due SDA/SCL swapped', ('H1',), arm_due),
            A('ladder rung', ('C2',), arm_ladder), A('LM27762 EN- off VIN', ('C1',), arm_enable),
            A('bridge not 0 ohm', ('N1',), arm_bridge_value), A('bridge open', ('C6', 'E2'), arm_bridge_open),
            A('block field', ('D1', 'D2'), arm_block_field), A('designator out of its block', ('D1', 'D2'), arm_designator),
            A('CAL header TAP_on', ('C4',), arm_cal_header), A('scope V- on the negative rail', ('C5', 'N1'), arm_scope_neg),
            A('SPICE scope connection', ('N1',), mut_spice=spice_scope_conn), A('SPICE awg value', ('N2',), mut_spice=spice_awg_value),
            A('SPICE scope value', ('N1',), mut_spice=spice_scope_value),
            A('SPICE new element', ('N2',), mut_spice=spice_unknown_element),
            A('GND flag removed', ('S1',), flag_nets=[n for n in PWR_FLAG_NETS if n != ARM_NO_FLAG])]
    return arms


def variant_rows(parts, spice, flag_nets, work, tag, project_dir=PROJECT_DIR, sim_dir=SIM_DIR):
    """a changed copy of the project is generated into a scratch folder and every row is run on it (sch.SchematicError when the
    generator refuses the part list)"""
    tmp = tempfile.mkdtemp(prefix='afe2-mut-', dir=work)
    shutil.copytree(os.path.join(project_dir, 'lib', PROJECT_LIB_NAME + '.pretty'), os.path.join(tmp, 'lib', PROJECT_LIB_NAME + '.pretty'))
    over = {} if flag_nets is None else {'PWR_FLAG_NETS': flag_nets}
    sch.write_all(parts, sch_cfg(**over), tmp)
    try:
        return all_rows(os.path.join(tmp, PROJECT + '.kicad_sch'), parts, spice, tag, sim_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_arms(work, arms=None, project_dir=PROJECT_DIR, sim_dir=SIM_DIR):
    """-> rows: one per arm, then M*. Each arm is judged against the regenerated unchanged project (the clean baseline), so an
    arm is caught only by a row that went from PASS to FAIL"""
    arms = flip_arms() if arms is None else arms
    spice0 = spice_texts(sim_dir)
    clean_rows = variant_rows(copy.deepcopy(PARTS), spice0, None, work, '~clean', project_dir, sim_dir)
    clean = {r.id.split('~')[0]: r.ok for r in clean_rows}
    out = []
    for a in arms:
        parts = copy.deepcopy(PARTS)
        if a.mut_parts:
            a.mut_parts(parts)
        spice = dict(spice0)
        if a.mut_spice:
            a.mut_spice(spice)
        try:
            rows = variant_rows(parts, spice, a.flag_nets, work, '~' + a.why, project_dir, sim_dir)
        except sch.SchematicError as e:
            out.append(Row('M-' + a.why, 'neither connected nor declared NC' in str(e) or 'declared NC and connected' in str(e),
                           f'the generator refuses: {e}'))
            continue
        failed = {r.id.split('~')[0] for r in rows if not r.ok}
        out.append(sr.flip_row(a.why, a.expect, clean, failed))
    return sr.finish_arms(out)


# ------------------------------------------------------------------------------------------------ command line
def build(out_dir, comments=None):
    """write the project into out_dir and put the schematic in KiCad 10's format exactly as eeschema writes it"""
    os.makedirs(out_dir, exist_ok=True)
    over = {} if comments is None else {'COMMENTS': comments}
    info = sch.write_all(PARTS, sch_cfg(**over), out_dir)
    subprocess.run(['kicad-cli', 'sch', 'upgrade', os.path.join(out_dir, PROJECT + '.kicad_sch')], check=True)
    return info


def main(argv=None):
    """python -m pcbtools.boards.v2_checks [--project DIR] [--arms] | --build OUT. Exit 0 only if every row passed, 1 otherwise,
    2 on bad input. The project is read on a copy."""
    import argparse
    ap = argparse.ArgumentParser(prog='python -m pcbtools.boards.v2_checks')
    ap.add_argument('--project', default=PROJECT_DIR, help='folder holding afe-v2.kicad_sch and lib/ (default: the live v2/kicad)')
    ap.add_argument('--sim', default=SIM_DIR, help='folder holding the studies (scope, awg, powercal)')
    ap.add_argument('--arms', action='store_true', help='also run the mutation arms')
    ap.add_argument('--pcb', action='store_true', help='refused: v2 has no PCB in this project yet')
    ap.add_argument('--build', metavar='OUT', help='write the project into OUT instead of checking')
    a = ap.parse_args(argv)
    if a.pcb:
        print('v2 has no PCB in this project yet: the P rows are v1 and the block boards\' (pcbtools.rules)', file=sys.stderr)
        return 2
    if a.build:
        info = build(os.path.abspath(a.build))
        print(f"{info['cells']} cells, {len(info['lib_ids'])} library symbols, sheet {info['size'][0]:.0f} x {info['size'][1]:.0f} mm")
        return 0
    work = tempfile.mkdtemp(prefix='pcbtools-v2check-')
    proj = os.path.join(work, 'project')
    shutil.copytree(a.project, proj, ignore=shutil.ignore_patterns('3d', '__pycache__', 'render', '*.kicad_prl', '~*'))
    s = os.path.join(proj, PROJECT + '.kicad_sch')
    if not os.path.exists(s):
        print(f'no {s}', file=sys.stderr)
        return 2
    rows = all_rows(s, PARTS, spice_texts(a.sim), '', a.sim)
    if a.arms:
        rows += run_arms(work, project_dir=proj, sim_dir=a.sim)
    print('\n'.join(r.line() for r in rows))
    ok = all(r.ok for r in rows)
    print('ALL PASS' if ok else 'FAIL: ' + ', '.join(r.id for r in rows if not r.ok))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
