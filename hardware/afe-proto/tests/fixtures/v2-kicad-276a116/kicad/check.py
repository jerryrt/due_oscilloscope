"""Validate the version 2 schematic, through KiCad's own reading of it, and break every check on purpose.

    python3 -I hardware/afe-proto/v2/kicad/check.py            # all checks and all mutation arms
    python3 -I hardware/afe-proto/v2/kicad/check.py --fast     # checks only, no mutation arms

Checks (each reads the file through kicad-cli, never through the generator's idea of what it wrote):

  S1  ERC: nothing live but the one documented exclusion (the LM27762's PGOOD tied to ground)
  S2  the exported netlist equals design.py, net for net and pin for pin
  S3  every symbol's value, footprint, LCSC, Sim and Block field equals design.py
  E1  every pin of every part is connected or explicitly declared NC, and a declared NC is unconnected
  E2  no net has a single pin
  E3  every fitted part has a value, a footprint that exists in a library, and an LCSC number
  E4  the datasheet pin names of the TPH2502, ADS1115 and LM27762 symbols (an independent table below)
  B1  every part's value and LCSC equal its study's parts.csv row, the counts equal the rows' quantities,
      and every row is placed (scope, awg, powercal)
  N1  the scope block is the circuit of sim/scope/scope_v2.cir (spicecmp.py: what is reduced, what is compared)
  N2  the AWG block is the circuit of sim/awg/awg.cir
  C1  rails: the LM27762 feedback networks, read from the netlist, give +3.318 V and -2.003 V
  C2  the six-rung ladder: series chain ground to the reference, six equal rungs, taps on A2..A7 and the
      ADS1115's 2/3-tap input
  C3  the sense divider: k = 0.4, default tie to the reference, ADS inputs AIN2 / AIN3 through 3.9k and 10k, input
      source impedances matched, the pair AIN2 - AIN3 a valid ADS1115 differential pair
  C4  the CAL header: 1x3, TAP4 (2/3 tap) | B | TAP3 (1/2 tap), the states, B touches only the sense divider, the shunt is listed
  C5  rules: no scope part touches the negative rail; no scope or AWG net but the pins' own reaches the ladder
  C6  the bridges join what they must; the CH2 clamp D201 sits on the dual side of both bridges
  D1  every designator's hundreds digit is its block (1 CH1, 2 CH2, 3 AWG, 4 POWER, 5 REFCAL, 6 EDGE)
  D2  each block holds exactly its key part list (KEY_PARTS); block_of_parts() gives ref -> block for the layout
  H1  the Due headers carry exactly the pins of the header-pin table below, on the V03 header names

Each check is broken on purpose before it is believed (mutation arms at the end): a mutated design, or a
mutated SPICE netlist, must make the named check fail.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.setdefault('PCBTOOLS_ROOT', os.path.normpath(os.path.join(HERE, '..', '..')))   # hardware/afe-proto; scratch copies inherit it
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import design                                   # noqa: E402
import spicecmp                                 # noqa: E402
from pcbtools.sexpr import parse, find, first            # noqa: E402

SCH = os.path.join(HERE, 'afe-v2.kicad_sch')
SIM = os.path.join(HERE, '..', 'sim')
KIFP = os.environ.get('KICAD_FOOTPRINT_DIR', '/usr/share/kicad/footprints')
RESULTS = []


def row(cid, ok, detail):
    RESULTS.append((cid, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {cid}: {detail}")
    return ok


def cli(*args):
    r = subprocess.run(['kicad-cli', *args], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        raise RuntimeError(f'kicad-cli {args}: {r.returncode}\n{r.stdout}\n{r.stderr}')
    return r


# ----------------------------------------------------------------------------- reading KiCad's output
def erc(sch):
    out = os.path.join(tempfile.mkdtemp(prefix='afe2-erc-'), 'erc.json')
    cli('sch', 'erc', '--format', 'json', '--severity-all', '-o', out, sch)
    d = json.load(open(out))
    live, excl = [], []
    for s in d['sheets']:
        for v in s['violations']:
            (excl if v.get('excluded') else live).append(f"{v['type']}: " + '; '.join(i['description'] for i in v['items']))
    return live, excl


def netlist(sch):
    """comps: ref -> value, footprint, fields, part (library symbol name); nets: name -> [(ref, pin, pin function)]."""
    out = os.path.join(tempfile.mkdtemp(prefix='afe2-net-'), 'net.net')
    cli('sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out, sch)
    n = parse(open(out).read())
    comps = {}
    for c in find(first(n, 'components'), 'comp'):
        ref = first(c, 'ref')[1]
        f = {first(x, 'name')[1]: x[2] for x in find(first(c, 'fields') or [], 'field') if len(x) > 2}
        comps[ref] = dict(value=first(c, 'value')[1], footprint=(first(c, 'footprint') or [None, ''])[1], fields=f,
                          part=first(first(c, 'libsource'), 'part')[1])
    nets = {}
    for e in find(first(n, 'nets'), 'net'):
        name = first(e, 'name')[1]
        nodes = []
        for x in find(e, 'node'):
            pin = first(x, 'pin')[1]
            fn = (first(x, 'pinfunction') or [None, ''])[1]
            if fn.endswith('_' + pin):
                fn = fn[:-len(pin) - 1]
            nodes.append((first(x, 'ref')[1], pin, fn))
        nets[name] = sorted(nodes)
    return comps, nets


def real_nets(nets):
    """Design nets only: KiCad's own 'unconnected-' nets and the PWR_FLAG symbols dropped, the leading / removed."""
    out = {}
    for k, v in nets.items():
        if k.startswith('unconnected-'):
            continue
        v = [x for x in v if not x[0].startswith('#')]
        if v:
            out[k.lstrip('/')] = v
    return out


def unconnected(nets):
    return {(r, p) for k, v in nets.items() if k.startswith('unconnected-') for (r, p, _) in v if not r.startswith('#')}


def pin_net(nets):
    return {(r, p): k for k, v in real_nets(nets).items() for (r, p, _) in v}


def pin_fn_net(nets):
    return {(r, fn): k for k, v in real_nets(nets).items() for (r, _, fn) in v if fn}


# ----------------------------------------------------------------------------- independent tables
# TPH2502 datasheet "Pin Configuration (Top View)", 8-pin SOP; TI SBAS444E table 4-1 (ADS1115, DGS);
# LM27762 SNVSAF7C table 4-1 (WSON-12, DSS).  Written from the datasheets, not from the symbols.
DATASHEET_PINS = {
    'TPH2502': {'1': 'OUTA', '2': '-INA', '3': '+INA', '4': 'V-', '5': '+INB', '6': '-INB', '7': 'OUTB', '8': 'V+'},
    'ADS1115': {'1': 'ADDR', '2': 'ALERT/RDY', '3': 'GND', '4': 'AIN0', '5': 'AIN1', '6': 'AIN2', '7': 'AIN3',
                '8': 'VDD', '9': 'SDA', '10': 'SCL'},
    'LM27762': {'1': 'PGOOD', '2': 'FB+', '3': 'VIN', '4': 'GND', '5': 'CP', '6': 'OUT-', '7': 'FB-', '8': 'EN-',
                '9': 'C-', '10': 'C+', '11': 'OUT+', '12': 'EN+', '13': 'PAD'},
}
# ADS1115 differential pairs the multiplexer can select (SBAS444E MUX[2:0]): (AINP, AINN)
ADS_DIFF = {(0, 1), (0, 3), (1, 3), (2, 3)}
# The Due header-pin table (docs/due-header-table.md, V03; afe.md MC-5): header -> {pin: net}.  Everything else passes
# through.  The AFE's SDA/SCL are the SAM3X's TWI0 on PWMH0.9 / .10 (labelled SDA1 / SCL1 on the header, no on-board pull-ups there; TWI1 is D20/D21).
DUE_TABLE = {
    'POWER0': {'5': '+5V_DUE', '6': 'GND', '7': 'GND'},
    'ADCL0': {'1': 'VREF', '2': 'TAP5', '3': 'TAP4', '4': 'TAP3', '5': 'TAP2', '6': 'TAP1', '7': 'A1', '8': 'A0'},
    'ADCH0': {'5': 'DAC0'},
    'PWMH0': {'7': 'GND', '8': 'AREF', '9': 'SDA', '10': 'SCL'},
    'XIO0': {'35': 'GND', '36': 'GND'},
    'PWML0': {}, 'COMMUNICATION0': {},
}


# ----------------------------------------------------------------------------- schematic checks
def compare_nets(want, got):
    diff = []
    ws = {frozenset(v): k for k, v in want.items()}
    gs = {frozenset(v): k for k, v in got.items()}
    for s, k in ws.items():
        if s not in gs:
            diff.append(f'design net {k} {sorted(s)} not in KiCad')
        elif gs[s] != k:
            diff.append(f'net {k} is named {gs[s]} in KiCad')
    for s, k in gs.items():
        if s not in ws:
            diff.append(f'KiCad net {k} {sorted(s)} not in the design')
    return diff


def fp_exists(fp):
    lib, name = fp.split(':')
    d = os.path.join(HERE, 'lib', 'afe.pretty') if lib == 'afe' else os.path.join(KIFP, lib + '.pretty')
    return os.path.exists(os.path.join(d, name + '.kicad_mod'))


def csv_rows(path):
    import csv
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


def study_rows():
    """Sim key -> (expected count, value text, lcsc)."""
    want = {}
    rows = csv_rows(os.path.join(SIM, 'scope', 'parts.csv'))
    dup = {}
    for r in rows:
        dup[r['refdes_per_channel']] = dup.get(r['refdes_per_channel'], 0) + 1
    for r in rows:
        ref = r['refdes_per_channel']
        key = 'scope.' + ref + (' ' + r['value'].split()[0] if dup[ref] > 1 else '')
        want[key] = (int(r['qty_per_board']), r['value'], r['lcsc'])
    for study, tag in (('awg', 'awg'), ('powercal', 'pc')):
        for r in csv_rows(os.path.join(SIM, study, 'parts.csv')):
            refs = expand_refs(r['refs'])
            per = int(r['qty']) if len(refs) == 1 else 1
            for ref in refs:
                want[f'{tag}.{ref}'] = (per, r['value'], r['lcsc'])
    return want


def schematic_checks(sch, parts, spice, tag='', quick=False):
    ok = True
    live, excl = erc(sch)
    ok &= row('S1' + tag, not live and len(excl) == 1,
              f'ERC {len(live)} live, {len(excl)} excluded' + (': ' + ' | '.join(live[:3]) if live else ''))
    comps, nets = netlist(sch)
    got = {k: [(r, p) for (r, p, _) in v] for k, v in real_nets(nets).items()}
    want = design.nets(parts)
    d = compare_nets(want, got)
    ok &= row('S2' + tag, not d and len(want) >= 40, f'{len(want)} design nets, {len(got)} KiCad nets'
              + (': ' + ' | '.join(d[:3]) if d else ''))
    dp = []
    byref = {p['ref']: p for p in parts}
    for ref in sorted(set(byref) | {r for r in comps if not r.startswith('#')}):
        if ref not in comps or ref not in byref:
            dp.append(f'{ref} in only one of design / KiCad'); continue
        p, c = byref[ref], comps[ref]
        for k, a, b in (('value', c['value'], p['value']), ('footprint', c['footprint'], p['fp']),
                        ('LCSC', c['fields'].get('LCSC', ''), p['lcsc']), ('Sim', c['fields'].get('Sim', ''), p['sim']),
                        ('Block', c['fields'].get('Block', ''), p['block'])):
            if a != b:
                dp.append(f'{ref} {k} {a!r} != {b!r}')
    ok &= row('S3' + tag, not dp and len(comps) >= 90, f'{len(comps)} symbols' + (': ' + ' | '.join(dp[:3]) if dp else ''))

    # E1 / E2
    unc = unconnected(nets)
    bad = []
    for p in parts:
        declared = {(p['ref'], n) for n in (p['nc'] if p['nc'] != 'rest' else ())}
        have = {(r, n) for (r, n) in unc if r == p['ref']}
        if p['nc'] == 'rest':
            if any(pin in p['pins'] for (_, pin) in have):
                bad.append(f"{p['ref']}: a connected pin is NC in KiCad")
        elif have != declared:
            bad.append(f"{p['ref']}: KiCad NC pins {sorted(x[1] for x in have)} != declared {sorted(x[1] for x in declared)}")
    ok &= row('E1' + tag, not bad, f'{len(unc)} NC pins, every one declared; every other pin connected'
              + (': ' + ' | '.join(bad[:3]) if bad else ''))
    single = sorted(k for k, v in got.items() if len(v) < 2)
    ok &= row('E2' + tag, not single, f'{len(got)} nets, none with a single pin' + (': ' + ', '.join(single[:6]) if single else ''))
    # E3
    miss = []
    for ref, c in comps.items():
        if ref.startswith('#'):
            continue
        f = c['fields']
        if not c['value'] or not c['footprint']:
            miss.append(f'{ref} lacks value or footprint')
        elif not fp_exists(c['footprint']):
            miss.append(f"{ref} footprint {c['footprint']} not in any library")
        if f.get('Fitted by') == 'JLC' and not f.get('LCSC'):
            miss.append(f'{ref} is fitted by the board house with no LCSC number')
        if f.get('Fitted by') == 'JLC' and not re.match(r'^C\d{3,}$', f.get('LCSC', '')):
            miss.append(f"{ref} LCSC {f.get('LCSC')!r} is not a Cnnn code")
    ok &= row('E3' + tag, not miss, f'{len(comps)} symbols carry value, footprint, LCSC' + (': ' + ' | '.join(miss[:3]) if miss else ''))
    # E4
    pf = pin_fn_net(nets)
    d4 = []
    for ref, c in comps.items():
        tbl = DATASHEET_PINS.get(c['part'])
        if not tbl:
            continue
        seen = {pin: fn for k, v in nets.items() for (r, pin, fn) in v if r == ref}
        if seen != tbl:
            d4.append(f'{ref} ({c["part"]}): pins {sorted(set(seen.items()) ^ set(tbl.items()))[:4]}')
    ok &= row('E4' + tag, not d4 and any(c['part'] in DATASHEET_PINS for c in comps.values()),
              'TPH2502, ADS1115, LM27762 pin names equal the datasheet tables' + (': ' + ' | '.join(d4[:3]) if d4 else ''))

    # B1
    want_rows = study_rows()
    d1 = []
    cnt = {}
    for p in parts:
        if p['sim']:
            cnt[p['sim']] = cnt.get(p['sim'], 0) + 1
            if p['sim'] not in want_rows:
                d1.append(f"{p['ref']} Sim {p['sim']!r} is in no parts.csv"); continue
            n, v, lc = want_rows[p['sim']]
            if p['lcsc'] != lc:
                d1.append(f"{p['ref']} LCSC {p['lcsc']} != {lc} ({p['sim']})")
            a, b = spicecmp.parse_value(p['value']) if not re.match(r'^[A-Za-z]', p['value']) else None, csv_value(v)
            if a is not None or b is not None:
                if a is None or b is None or spicecmp.sig(a) != b:
                    d1.append(f"{p['ref']} value {p['value']!r} != {v!r} ({p['sim']})")
    for k, (n, v, lc) in want_rows.items():
        if k in design.NOT_A_SYMBOL:          # a loose part: it must be on the hand-fitted list instead
            if not any(design.NOT_A_SYMBOL[k] in h and k.split('.')[1] in h for h in design.HAND_FITTED):
                d1.append(f'{k} is not a symbol and not on the hand-fitted list')
            continue
        if cnt.get(k, 0) != n:
            d1.append(f'{k}: {cnt.get(k, 0)} placed, parts.csv says {n}')
    ok &= row('B1' + tag, not d1 and len(cnt) >= 50, f'{len(cnt)} studied parts against {len(want_rows)} parts.csv keys'
              + (': ' + ' | '.join(d1[:3]) if d1 else ''))

    # N1 / N2
    for cid, block, text in (('N1', 'scope', spice['scope']), ('N2', 'awg', spice['awg'])):
        try:
            d, ns, nc_ = spicecmp.compare(block, text, comps, nets)
        except Exception as e:      # a stale rule, an unclassified element, a part with no counterpart
            d, ns, nc_ = [f'{type(e).__name__}: {e}'], 0, 0
        ok &= row(cid + tag, not d and ns >= 10, f'{block}: {ns} SPICE elements after reduction, {nc_} schematic elements'
                  + (': ' + ' | '.join(d[:3]) if d else ''))
    ok &= block_checks(comps, tag)
    ok &= computed_checks(comps, nets, parts, tag)
    return ok


# ----------------------------------------------------------------------------- blocks (LR-11)
BLOCKDIGIT = {'CH1': 1, 'CH2': 2, 'AWG': 3, 'POWER': 4, 'REFCAL': 5, 'EDGE': 6}


def _rng(prefix, a, b):
    return {f'{prefix}{k}' for k in range(a, b + 1)}


# The key part list of each block, written out here and not derived from design.py: a block outline on the board
# contains exactly these parts.  U101 is the dual both channels share and sits in CH1.
KEY_PARTS = {
    'CH1': {'J101', 'U101', 'D101', 'TP101', 'BR101'} | _rng('R', 101, 108) | _rng('C', 101, 105),
    'CH2': {'J201', 'D201', 'TP201', 'BR201'} | _rng('R', 201, 208) | _rng('C', 201, 203),
    'AWG': {'U301', 'J301', 'C301', 'TP301'} | _rng('R', 301, 309) | _rng('C', 303, 306),
    'POWER': {'U401'} | _rng('R', 401, 407) | _rng('C', 401, 409) | _rng('TP', 401, 404),
    'REFCAL': {'U501', 'U502', 'J501', 'TP501'} | _rng('R', 501, 514) | _rng('C', 501, 503),
    'EDGE': _rng('J', 601, 607) | {'MH601', 'MH602'},
}


def block_of_parts(parts=None):
    """ref -> block (CH1, CH2, AWG, POWER, REFCAL, EDGE) for every part of design.py, for the layout's lr_check:
    a block's outline must contain exactly the parts this returns for it."""
    return {p['ref']: p['block'] for p in (design.PARTS if parts is None else parts)}


def block_checks(comps, tag):
    got = {r: c['fields'].get('Block', '') for r, c in comps.items() if not r.startswith('#')}
    bad = [f'{r} ({b or "no block"})' for r, b in sorted(got.items())
           if b not in BLOCKDIGIT or int(re.sub(r'\D', '', r)) // 100 != BLOCKDIGIT[b]]
    ok = row('D1' + tag, not bad and len(got) >= 90,
             f'{len(got)} designators: hundreds digit = block' + (': ' + ', '.join(bad[:4]) if bad else ''))
    have = {b: {r for r, bb in got.items() if bb == b} for b in BLOCKDIGIT}
    d = [f'{b}: missing {sorted(KEY_PARTS[b] - have[b])[:3]} extra {sorted(have[b] - KEY_PARTS[b])[:3]}'
         for b in BLOCKDIGIT if have[b] != KEY_PARTS[b]]
    ok &= row('D2' + tag, not d, 'each block holds exactly its key part list: '
              + ', '.join(f'{b} {len(KEY_PARTS[b])}' for b in BLOCKDIGIT) + (' | ' + ' | '.join(d) if d else ''))
    return ok


# ----------------------------------------------------------------------------- the calibration/power block
def rmap(comps, nets):
    """ref -> (ohms, net1, net2) for every resistor, from KiCad's netlist."""
    pn = pin_net(nets)
    return {r: (spicecmp.parse_value(c['value']), pn.get((r, '1')), pn.get((r, '2')))
            for r, c in comps.items() if c['part'] == 'R'}


def by_sim(comps, sim):
    return [r for r, c in comps.items() if c['fields'].get('Sim') == sim]


def chain(R, a, b, nets_nodes):
    """Resistance of the series path from net a to net b whose intermediate nets carry exactly two pins."""
    total, cur, seen = 0.0, a, set()
    while cur != b:
        step = [(r, v) for r, v in R.items() if cur in v[1:] and r not in seen]
        nxt = None
        for want_b in (True, False):       # a resistor straight to b wins over one into an intermediate net
            for r, (ohm, n1, n2) in step:
                other = n2 if n1 == cur else n1
                if (want_b and other == b) or (not want_b and len(nets_nodes.get(other, [])) == 2 and other != a):
                    nxt = (r, ohm, other); break
            if nxt:
                break
        if nxt is None:
            return None
        seen.add(nxt[0]); total += nxt[1]; cur = nxt[2]
    return total


def computed_checks(comps, nets, parts, tag):
    ok = True
    real = real_nets(nets)
    R = rmap(comps, nets)
    pf = pin_fn_net(nets)
    pn = pin_net(nets)
    # C1: rails
    u = [r for r, c in comps.items() if c['part'] == 'LM27762'][0]
    n = lambda fn: pf[(u, fn)]
    r1, r2 = chain(R, n('OUT+'), n('FB+'), real), chain(R, n('FB+'), 'GND', real)
    r3, r4 = chain(R, n('OUT-'), n('FB-'), real), chain(R, n('FB-'), 'GND', real)
    msg, good = '', False
    if None not in (r1, r2, r3, r4):
        vp, vn = 1.2 * (r1 + r2) / r2, -1.22 * (r3 + r4) / r4
        good = abs(vp - 3.318) < 0.002 and abs(vn + 2.003) < 0.002 and r2 >= 50e3 and r4 >= 50e3
        msg = f'V+ = {vp:.4f} V (R1 {r1:g}, R2 {r2:g}), V- = {vn:.4f} V (R3 {r3:g}, R4 {r4:g}); expect 3.318 and -2.003'
    # the enables: tied straight to VIN, no net of their own (SNVSAF7C section 6.1: "Enable inputs can be also shorted
    # together and connected to VIN"; abs max EN pins GND - 0.3 V to VIN, VIH 1.2 V; no series resistor is required)
    en_ok = pf[(u, 'EN+')] == pf[(u, 'EN-')] == pf[(u, 'VIN')]
    good = good and en_ok
    msg += f'; EN+ and EN- on the VIN net {pf[(u, "VIN")]}: {en_ok}'
    ok &= row('C1' + tag, good, msg or 'feedback networks not found as series chains')
    # C2: ladder
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
            r = nxt[0]; left.discard(r); vals.append(R[r][0])
            cur = R[r][2] if R[r][1] == cur else R[r][1]
            taps.append(cur)
        top_ok = (not left and taps and taps[-1] == 'VREF' and len(set(vals)) == 1)
        tapnames = dict(zip(range(1, 7), taps))
        due = {pin: pn.get(('J602', pin)) for pin in '12345678'}
        want_due = {str(7 - k): tapnames[k] for k in range(1, 7)}       # tap k on A(k+1) = ADCL0 pin 7-k; top = pin 1
        ads = [r for r, c in comps.items() if c['part'] == 'ADS1115'][0]
        two_thirds_ok = pf[(ads, 'AIN1')] == tapnames[4]
        due_ok = all(due[p] == want_due[p] for p in want_due)
        good = bool(top_ok and due_ok and two_thirds_ok)
        msg = (f'{len(vals)} rungs of {sorted(set(vals))}, taps {taps}, Due A2..A7 on taps {due_ok}, '
               f'ADS1115 AIN1 on the 2/3 tap {two_thirds_ok}')
    ok &= row('C2' + tag, good, msg or 'ladder rungs not found')
    # C3: sense divider
    try:
        g = lambda s: R[by_sim(comps, s)[0]]
        rt, rb, rd, rs, rm = (g('pc.R_SRT'), g('pc.R_SRB'), g('pc.R_SRD'), g('pc.R_SRS'), g('pc.R_SRM'))
        ads = [r for r, c in comps.items() if c['part'] == 'ADS1115'][0]
        awg = pn[('J301', '1')]
        t0 = (set(rt[1:]) - {awg}).pop() if awg in rt[1:] else None
        b = (set(rd[1:]) - {'VREF'}).pop() if 'VREF' in rd[1:] else None
        ain_of = lambda rr: next((int(fn[3]) for (r_, fn), net in pf.items() if r_ == ads and fn.startswith('AIN') and net in rr[1:]
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
                                                       and any(pn.get((r, p)) in (t0, b) for p in '123')],
        }
        bad = [k_ for k_, v in conds.items() if not v]
        ok &= row('C3' + tag, not bad, f'k = {k:.3f}, Rm {rm[0]:g} vs Rs + Rt||Rb {rs[0] + parallel:g}'
                  + (': failed ' + '; '.join(bad) if bad else ''))
    except Exception as e:
        ok &= row('C3' + tag, False, f'{type(e).__name__}: {e}')
    # C4: the calibration header: 1x3 "CAL", pin 1 TAP4 (2/3 tap, 2.0 V) | pin 2 B | pin 3 TAP3 (1/2 tap, 1.5 V)
    hdr = {p: pn.get(('J501', p)) for p in '123'}
    b = hdr['2']
    on_b = {r for (r, p), net in pn.items() if net == b and r != 'J501'}
    nj = [r for r, c in comps.items() if r == 'J501' and c['part'] == 'Conn_01x03']
    states = {'no shunt (default tie)': b, 'shunt 2-3 (calibrate)': f'B = {hdr["3"]}', 'shunt 1-2 (slip)': f'B = {hdr["1"]}'}
    ok &= row('C4' + tag, len(nj) == 1 and hdr['1'] == 'TAP4' and hdr['3'] == 'TAP3' and
              all(comps[r]['fields'].get('Sim', '').startswith('pc.R_SR') for r in on_b) and
              any('shunt' in h for h in design.HAND_FITTED),
              f'J501 is 1x3: pin 1 {hdr["1"]} (2/3 tap) | pin 2 B | pin 3 {hdr["3"]} (1/2 tap); B touches {sorted(on_b)} only; '
              f'states {states}; the shunt is on the hand-fitted list')
    # C5: rules
    scope = {r for r, c in comps.items() if c['fields'].get('Block') in ('CH1', 'CH2')}
    on_neg = sorted(r for (r, p), net in pn.items() if net == 'VNEG' and r in scope)
    ref_users = sorted(r for (r, p), net in pn.items() if net == 'VREF' and comps[r]['fields'].get('Block') in ('CH1', 'CH2', 'AWG')
                       and comps[r]['part'] == 'R')
    ok &= row('C5' + tag, not on_neg and len(ref_users) == 3,
              f'scope parts on the negative rail: {on_neg or "none"}; reference loaded by {ref_users} (R3b of both channels, Rg2)')
    # C6: the bridges join what they must (placeholder nets, see the README): BR101 from the +3V3A rail to the dual's V+
    # segment, BR201 from CH2's Riso / clamp side to the Due A0 pin
    def ends(ref):
        return {pn.get((ref, '1')), pn.get((ref, '2'))}
    br = ends('BR101') == {pf[(u, 'OUT+')], pf[('U101', 'V+')]} and ends('BR201') == {pn.get(('R208', '2')), pn.get(('J602', '8'))}
    ok &= row('C6' + tag, br and pn.get(('D201', '3')) == pn.get(('R208', '2')) and pn.get(('D201', '2')) == pf[('U101', 'V+')],
              f'BR101 joins {sorted(ends("BR101"), key=str)}, BR201 joins {sorted(ends("BR201"), key=str)}; the CH2 clamp D201 sits on the dual side of both')
    # H1: Due headers
    d = []
    byname = {c['value']: r for r, c in comps.items() if c['fields'].get('Block') == 'EDGE' and c['part'].startswith('Conn_0')}
    for hname, tbl in DUE_TABLE.items():
        ref = byname.get(hname)
        if ref is None:
            d.append(f'{hname} missing'); continue
        have = {p: net for (r, p), net in pn.items() if r == ref}
        if have != tbl:
            d.append(f'{hname}: {sorted(set(have.items()) ^ set(tbl.items()))[:4]}')
    ok &= row('H1' + tag, not d, f'{len(DUE_TABLE)} Due headers carry exactly the header-pin table' + (': ' + ' | '.join(d[:3]) if d else ''))
    return ok


# ----------------------------------------------------------------------------- mutation arms
def spice_texts():
    return {'scope': open(os.path.join(SIM, 'scope', 'scope_v2.cir')).read(),
            'awg': open(os.path.join(SIM, 'awg', 'awg.cir')).read()}


def variant(mut_parts=None, mut_spice=None, flag_nets=None, expect=(), why=''):
    """Build a changed copy of the project, run every check on it, and require the named checks to FAIL."""
    import build_sch
    parts = copy.deepcopy(design.PARTS)
    if mut_parts:
        mut_parts(parts)
    spice = spice_texts()
    if mut_spice:
        mut_spice(spice)
    tmp = tempfile.mkdtemp(prefix='afe2-mut-')
    shutil.copytree(os.path.join(HERE, 'lib', 'afe.pretty'), os.path.join(tmp, 'lib', 'afe.pretty'))
    before = len(RESULTS)
    try:
        build_sch.build(parts, tmp, flag_nets)
    except SystemExit as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return row('M-' + why, 'neither connected nor declared NC' in str(e) or 'declared NC and connected' in str(e),
                   f'the generator refuses: {e}')
    print(f'  -- arm "{why}": expecting {", ".join(expect)} to FAIL')
    schematic_checks(os.path.join(tmp, 'afe-v2.kicad_sch'), parts, spice, tag='~' + why)
    failed = {c.split('~')[0] for c, ok, _ in RESULTS[before:] if not ok}
    del RESULTS[before:]
    shutil.rmtree(tmp, ignore_errors=True)
    return row('M-' + why, set(expect) <= failed, f'{sorted(failed)} failed; wanted {list(expect)}')


def P(parts, ref):
    return next(p for p in parts if p['ref'] == ref)


def arm_value_scope(parts):
    P(parts, 'R101')['value'] = '51k 1%'                          # the scope's first R1 part, 510k -> 51k


def arm_value_awg(parts):
    P(parts, 'R303')['value'] = '4.7k 1%'                         # Rf, 3k -> 4.7k


def arm_swap_scope(parts):
    p = P(parts, 'U101'); p['pins']['2'], p['pins']['3'] = p['pins']['3'], p['pins']['2']   # -INA and +INA exchanged


def arm_swap_awg(parts):
    p = P(parts, 'U301'); p['pins']['5'] = 'AWG_FB'; p['pins']['6'] = 'AWG_BIN'            # half B's inputs exchanged


def arm_delete_conn_awg(parts):
    P(parts, 'R304')['pins']['2'] = 'ORPHAN'                      # Rg2 no longer reaches the filter node


def arm_delete_conn_scope(parts):
    P(parts, 'C203')['pins']['2'] = 'ORPHAN'                      # CH2's Cpx no longer reaches ground


def arm_omit_pin(parts):
    del P(parts, 'R306')['pins']['2']                             # a pin silently left out: no NC declared


def arm_rail(parts):
    P(parts, 'R401')['value'] = '150k 1%'                         # +rail feedback top


def arm_ads_pair(parts):
    p = P(parts, 'U502'); p['pins']['6'], p['pins']['7'] = p['pins']['7'], p['pins']['6']  # AIN2 <-> AIN3: the pair (3, 2) is no mux setting


def arm_lcsc(parts):
    P(parts, 'R401')['lcsc'] = 'C25804'


def arm_due(parts):
    p = P(parts, 'J604'); p['pins']['9'], p['pins']['10'] = p['pins']['10'], p['pins']['9']


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
    s = t['awg'].replace('Rf vo fb 3000.0', 'Rf vo fb 3100.0'); assert s != t['awg']; t['awg'] = s


def spice_scope_value(t):
    s = t['scope'].replace('Cna an 0 1.2e-11', 'Cna an 0 1.5e-11'); assert s != t['scope']; t['scope'] = s


def spice_unknown_element(t):
    t['awg'] = t['awg'].replace('.op', 'Rextra bnc 0 1k\n.op')


def mutation_arms():
    bad = 0
    arms = [
        (arm_value_scope, None, ('N1', 'B1'), 'scope value'),
        (arm_value_awg, None, ('N2', 'B1'), 'awg value'),
        (arm_swap_scope, None, ('N1',), 'scope pin swap'),
        (arm_swap_awg, None, ('N2',), 'awg pin swap'),
        (arm_delete_conn_awg, None, ('N2', 'E2'), 'awg connection deleted'),
        (arm_delete_conn_scope, None, ('N1', 'E2'), 'scope connection deleted'),
        (arm_omit_pin, None, (), 'pin left out without NC'),
        (arm_rail, None, ('C1', 'B1'), 'rail feedback value'),
        (arm_ads_pair, None, ('C3',), 'ADS1115 pair'),
        (arm_lcsc, None, ('B1',), 'LCSC changed'),
        (arm_due, None, ('H1',), 'Due SDA/SCL swapped'),
        (arm_ladder, None, ('C2',), 'ladder rung'),
        (arm_enable, None, ('C1',), 'LM27762 EN- off VIN'),
        (arm_bridge_value, None, ('N1',), 'bridge not 0 ohm'),
        (arm_bridge_open, None, ('C6', 'E2'), 'bridge open'),
        (arm_block_field, None, ('D1', 'D2'), 'block field'),
        (arm_designator, None, ('D1', 'D2'), 'designator out of its block'),
        (arm_cal_header, None, ('C4',), 'CAL header TAP_on'),
        (arm_scope_neg, None, ('C5', 'N1'), 'scope V- on the negative rail'),
    ]
    for mp, ms, exp, why in arms:
        bad += variant(mp, ms, expect=exp, why=why)
    for ms, exp, why in ((spice_scope_conn, ('N1',), 'SPICE scope connection'), (spice_awg_value, ('N2',), 'SPICE awg value'),
                         (spice_scope_value, ('N1',), 'SPICE scope value'), (spice_unknown_element, ('N2',), 'SPICE new element')):
        bad += variant(None, ms, expect=exp, why=why)
    bad += variant(None, None, flag_nets=['+5V_DUE', '+5V_F', '+3V3A_U'], expect=('S1',), why='GND flag removed')
    return bad, len(arms) + 4 + 1


if __name__ == '__main__':
    ok = schematic_checks(SCH, design.PARTS, spice_texts())
    if '--fast' not in sys.argv:
        bad, n = mutation_arms()
        ok &= row('M*', bad == n, f'{bad} of {n} mutation arms failed the way they must')
    print('ALL PASS' if ok else 'FAILED')
    sys.exit(0 if ok else 1)
