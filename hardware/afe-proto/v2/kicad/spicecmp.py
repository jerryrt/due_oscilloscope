"""Compare a block of the schematic, as KiCad exports it, with a study's SPICE netlist.

The two are different drawings of one circuit: the SPICE file has the simulation's sources, strays, loads and
ESRs in it, the schematic has the connectors, the dual's two halves in one package and the two 100 ohm
back-termination parts the simulation merged into one 50 ohm.  The comparison therefore has two sides with an
explicit, documented reduction on each, and then asks whether the remaining circuits are isomorphic:

  * the SPICE side drops the elements named in RULES[...]['drop'] (each with its reason), shorts the
    0 V ammeters, and collapses a capacitor with its series ESR into the capacitor;
  * the schematic side takes the parts whose `Block` field names the block, expands the BAV99 into its two
    diodes and the TPH2502 into its two amplifiers (from the pin *names* in KiCad's netlist, so the symbol
    is the authority for which pin is which), and folds resistors in parallel across the same two nets
    into one (the AWG's two 100 ohm 1206 parts);
  * every element is then (kind, value) with named pin roles, every net is a node, a few nets are anchored by
    name on both sides (ground, the +3.3 V_A rail, the reference output, the negative rail, the DAC pin), and
    a colour refinement (1-dimensional Weisfeiler-Leman) over the bipartite graph must give the same
    multiset of colours on both sides.  Element designators and net names do not enter it except the anchors:
    it compares topology and values, which is what a swapped pin, a missing connection or a changed value
    breaks.

An SPICE element that is neither dropped, shorted nor collapsed stays in the graph, so a new element in a
study's netlist that this file does not know about fails the comparison instead of being ignored.  A rule
naming an element the netlist no longer has fails too (a stale rule would otherwise hide a change).

Own work, CC BY-SA 4.0.
"""
import hashlib
import re
from collections import Counter, defaultdict

SI = {'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'k': 1e3, 'M': 1e6, 'G': 1e9}


def parse_value(s):
    """'510k 1%' -> 510000.0, '22p C0G' -> 2.2e-11, '1Meg' / '2.2e-11' (SPICE) too; None if it has no number."""
    m = re.match(r'^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*(Meg|meg|MEG|[fpnumkMG])?', s)
    if not m:
        return None
    v = float(m.group(1))
    suf = m.group(2)
    if suf:
        v *= 1e6 if suf.lower() == 'meg' else SI[suf]
    return v


def sig(v):
    return float(f'{v:.6g}')


# ----------------------------------------------------------------------------- the reductions, with reasons
BLOCKS = {'scope': {'CH1', 'CH2'}, 'awg': {'AWG'}}      # the Block fields each study's circuit spans

RULES = {
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


# ----------------------------------------------------------------------------- SPICE side
def read_spice(text, rules):
    """-> list of elements {kind, value, pins:[(role, node)], name}, with the reductions applied."""
    els = []
    skip = None          # inside a .subckt (the vendor model wrappers) or a .control block: not part of the circuit
    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        if skip:
            if low.startswith(skip):
                skip = None
            continue
        if low.startswith('.subckt'):
            skip = '.ends'; continue
        if low.startswith('.control'):
            skip = '.endc'; continue
        if not line or line[0] in '*.;':
            continue
        t = line.split()
        name, k = t[0], t[0][0].upper()
        if k in 'RCLV':
            els.append(dict(name=name, kind=k, value=t[3] if k == 'V' else t[3], nodes=t[1:3]))
        elif k == 'D':
            els.append(dict(name=name, kind='D', value=t[3], nodes=t[1:3]))       # anode, cathode, model
        elif k == 'X':
            model = t[-1]
            if model not in rules['subckt_models']:
                raise ValueError(f'unknown subcircuit {model} in {line!r}')
            els.append(dict(name=name, kind='OA', value=model, nodes=t[1:-1]))     # inp inn vp vn out
        else:
            raise ValueError(f'unclassified SPICE line {line!r}')
    names = {e['name'] for e in els}
    for n in list(rules['drop']) + list(rules['short']) + [x for pair in rules['esr'] for x in pair]:
        if n not in names:
            raise ValueError(f'rule names {n}, which the netlist no longer has')
    # 0 V ammeters: merge their two nodes
    alias = {}

    def root(n):
        while n in alias:
            n = alias[n]
        return n
    for e in els:
        if e['name'] in rules['short']:
            a, b = root(e['nodes'][0]), root(e['nodes'][1])
            if a != b:
                alias[b] = a
    byname = {e['name']: e for e in els}
    out = []
    drop = set(rules['drop']) | set(rules['short'])
    esr = {r: c for c, r in rules['esr']}
    for c, r in rules['esr']:
        ce, re_ = byname[c], byname[r]
        shared = set(ce['nodes']) & set(re_['nodes'])
        if len(shared) != 1:
            raise ValueError(f'{c} and {r} are not in series')
        s = shared.pop()
        if sum(s in e['nodes'] for e in els) != 2:
            raise ValueError(f'ESR junction {s} has other connections')
        ce['nodes'] = [n for n in ce['nodes'] if n != s] + [[n for n in re_['nodes'] if n != s][0]]
    for e in els:
        if e['name'] in drop or e['name'] in esr:
            continue
        nodes = [root(n) for n in e['nodes']]
        if e['kind'] == 'OA':
            pins = list(zip(('inp', 'inn', 'vp', 'vn', 'out'), nodes))
            val = 'OA'
        elif e['kind'] == 'D':
            pins = list(zip(('A', 'K'), nodes)); val = e['value']
        else:
            pins = [('p', nodes[0]), ('p', nodes[1])]; val = sig(parse_value(e['value']))
        if e['kind'] == 'C' and e['name'] in rules.get('derate', {}):
            val = sig(val / rules['derate'][e['name']][0])        # compare at the nominal value the board carries
        out.append(dict(name=e['name'], kind=e['kind'], value=val, pins=pins))
    return out


def fold(els):
    """Resistors in parallel across one net pair become their parallel resistance, capacitors their sum.  Applied to
    both sides: the AWG's two 100 ohm 1206 parts against the study's one 50 ohm, the two 10 uF filter capacitors
    against the study's one, the scope's 100 nF and 1 uF supply capacitors against the study's two."""
    groups = defaultdict(list)
    keep = []
    for e in els:
        if e['kind'] in ('R', 'C'):
            groups[(e['kind'], frozenset(n for _, n in e['pins']))].append(e)
        else:
            keep.append(e)
    for (kind, key), g in groups.items():
        if len(g) == 1 or len(key) < 2:
            keep += g
        else:
            v = 1 / sum(1 / x['value'] for x in g) if kind == 'R' else sum(x['value'] for x in g)
            keep.append(dict(name='+'.join(x['name'] for x in g), kind=kind, value=sig(v), pins=g[0]['pins']))
    return keep


# ----------------------------------------------------------------------------- schematic side
PIN_ROLES_OA = {'+INA': 'inp', '-INA': 'inn', 'OUTA': 'out', '+INB': 'inp', '-INB': 'inn', 'OUTB': 'out',
                'V+': 'vp', 'V-': 'vn'}


def schematic_elements(comps, nets, block):
    """Elements of the parts whose Block field is `block`, from KiCad's own netlist (comps, nets as check.netlist)."""
    # the 0 ohm bridges (BR parts) join two segment names of one electrical net: merge them, shortest name wins
    # (so +3V3A, not +3V3A_U, is the net the anchor names)
    alias = {}

    def root(n):
        while n in alias:
            n = alias[n]
        return n
    for ref, c in comps.items():
        if ref.startswith('BR'):
            if c['part'] != 'R' or parse_value(c['value']) != 0:
                raise ValueError(f'{ref}: a bridge must be a 0 ohm resistor, it is {c["value"]!r}')
            ends = [net.lstrip('/') for net, nodes in nets.items() for (r, p, f) in nodes if r == ref]
            a, b = sorted((root(ends[0]), root(ends[1])), key=lambda x: (len(x), x))
            if a != b:
                alias[b] = a
    pinnet = {}
    for net, nodes in nets.items():
        for ref, pin, fn in nodes:
            pinnet[(ref, pin)] = (root(net.lstrip('/')), fn)
    out = []
    for ref, c in sorted(comps.items()):
        if c['fields'].get('Block') not in BLOCKS[block] or ref.startswith('#'):
            continue
        pins = {pin: v for (r, pin), v in pinnet.items() if r == ref}
        lib = c['part']
        if lib in ('R', 'C'):
            out.append(dict(name=ref, kind=lib, value=sig(parse_value(c['value'])),
                            pins=[('p', pins['1'][0]), ('p', pins['2'][0])]))
        elif lib == 'BAT54S':
            if c['value'] != 'BAV99':
                raise ValueError(f'{ref}: the series-pair symbol carries {c["value"]!r}, expected BAV99')
            # SOT-23 BAV99: 1 anode of D1, 2 cathode of D2, 3 cathode of D1 and anode of D2
            out.append(dict(name=ref + 'a', kind='D', value='DBAV99', pins=[('A', pins['1'][0]), ('K', pins['3'][0])]))
            out.append(dict(name=ref + 'b', kind='D', value='DBAV99', pins=[('A', pins['3'][0]), ('K', pins['2'][0])]))
        elif lib == 'TPH2502':
            by = {fn: net for (net, fn) in pins.values()}
            for half in 'AB':
                out.append(dict(name=ref + half, kind='OA', value='OA', pins=[
                    ('inp', by[f'+IN{half}']), ('inn', by[f'-IN{half}']), ('vp', by['V+']), ('vn', by['V-']),
                    ('out', by[f'OUT{half}'])]))
        elif c['value'] == 'KH-BNC50-3511' or lib in ('Conn_Coaxial', 'TestPoint'):
            continue          # a connector: its nets exist, the simulation's source and load stand in for it
        else:
            raise ValueError(f'{ref}: part {lib!r} in block {block!r} has no SPICE counterpart rule')
    return fold(out)


# ----------------------------------------------------------------------------- the comparison
ROLED = ('OA', 'D')       # kinds whose pins are distinguishable; resistors and capacitors are symmetric


def _h(*a):
    return hashlib.sha1(repr(a).encode()).hexdigest()[:16]


def colours(els, anchors):
    """Colour refinement; returns (sorted element colours, sorted net colours)."""
    net_el = defaultdict(list)
    for i, e in enumerate(els):
        for role, n in e['pins']:
            net_el[n].append((role if e['kind'] in ROLED else 'p', i))
    ecol = [_h('E', e['kind'], e['value']) for e in els]
    ncol = {n: _h('N', anchors.get(n, '')) for n in net_el}
    for _ in range(max(6, len(els))):
        new_e = [_h(ecol[i], sorted((role if e['kind'] in ROLED else 'p', ncol[n]) for role, n in e['pins']))
                 for i, e in enumerate(els)]
        new_n = {n: _h(ncol[n], sorted((role, new_e[i]) for role, i in v)) for n, v in net_el.items()}
        if len(set(new_e)) == len(set(ecol)) and len(set(new_n.values())) == len(set(ncol.values())):
            ecol, ncol = new_e, new_n
            break
        ecol, ncol = new_e, new_n
    return sorted(ecol), sorted(ncol.values())


def describe(els):
    c = Counter((e['kind'], e['value']) for e in els)
    return c


def compare(block, spice_text, comps, nets):
    """Return a list of differences (empty = the schematic block and the SPICE netlist are the same circuit)."""
    rules = RULES[block]
    sp = fold(read_spice(spice_text, rules))
    sc = schematic_elements(comps, nets, block)
    diff = []
    a, b = describe(sp), describe(sc)
    for k in sorted(set(a) | set(b), key=str):
        if a[k] != b[k]:
            diff.append(f'{k[0]} {k[1]}: SPICE {a[k]}, schematic {b[k]}')
    sch_anchors = {v: v for v in rules['anchors'].values()}
    csp = colours(sp, rules['anchors'])
    csc = colours(sc, sch_anchors)
    if not diff and csp != csc:
        diff.append('same elements and values, different connectivity (graph colours differ)')
    return diff, len(sp), len(sc)
