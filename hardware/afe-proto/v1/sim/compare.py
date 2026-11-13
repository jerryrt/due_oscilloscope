#!/usr/bin/env python3
"""Compare each v1 harness netlist with v1's schematic (pcbtools.spicecmp).  Run in the image from the afe-proto directory:
    PCBTOOLS_V1_SOURCE=/work/hardware/afe-proto/kicad python3 v1/sim/compare.py [--mutate] > results/spicecmp.txt
The schematic is generated from v1's design data (boards/v1.py: PARTS, sch_cfg) into a temporary directory and exported by
kicad-cli, so no committed schematic file is trusted.  --mutate also changes one value in each netlist and shows the comparison fail."""
import os, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model
sys.path.insert(0, model.AFE)
from pcbtools import schematic as sch, schematic_rows as sr, spicecmp
from pcbtools.boards import v1
import spice_cfg


TPH2502_PINS = {'1': 'OUTA', '2': '-INA', '3': '+INA', '4': 'V-', '5': '+INB', '6': '-INB', '7': 'OUTB', '8': 'V+'}


def schematic():
    d = tempfile.mkdtemp(prefix='v1-sch-')
    sch.write_all(v1.PARTS, v1.sch_cfg(), d)
    comps, nets = sr.netlist_full(os.path.join(d, v1.PROJECT + '.kicad_sch'))
    for q in v1.PARTS:        # v1's schematic carries no Block field: the design data's block of each part stands in for it
        comps[q['ref']]['fields']['Block'] = q['block']
    # v1 draws the TPH2502 with the LM358 symbol (same SOP-8 numbering): name its pins from the 3PEAK datasheet's pin table
    # (the one pcbtools/boards/v2_checks.py DATASHEET_PINS holds), not from the stand-in symbol
    for ref in ('U101', 'U301'):
        assert comps[ref]['value'].startswith('TPH2502')
        comps[ref]['part'] = 'TPH2502'
    for net, nodes in nets.items():
        nets[net] = [(r, p, TPH2502_PINS[p] if r in ('U101', 'U301') else fn) for (r, p, fn) in nodes]
    return comps, nets


def cfg_for(comps):
    zero = tuple(r for r, c in comps.items() if c['part'] == 'R' and spicecmp.parse_value(c['value']) == 0)
    c = types.SimpleNamespace(**{k: getattr(spice_cfg, k) for k in dir(spice_cfg) if k.isupper()})
    c.BRIDGE_PREFIX = zero
    return c


def texts():
    R, NL = model.scope_setup('A', os.path.join(tempfile.mkdtemp(prefix='v1-cmp-'), 'o'), tempfile.mkdtemp(prefix='v1-w-'))
    scope = model.scope_netlist(R, NL)
    core = model.awg_setup()
    awg = core.build(dict(core.V1, rails='nom', cfb=2e-12, model='vendor', load='hiz'), analysis='.op')
    return {'scope': scope, 'awg': awg}


def main(argv):
    comps, nets = schematic()
    cfg = cfg_for(comps)
    tx = texts()
    bad = 0
    for block in ('scope', 'awg'):
        diff, ns, nc = spicecmp.compare(block, tx[block], comps, nets, cfg)
        print(f'{block}: {ns} SPICE elements after reduction, {nc} schematic elements: ' + ('SAME CIRCUIT' if not diff else 'DIFFERENT'))
        for d in diff:
            print('   ', d)
        bad += bool(diff)
    if '--mutate' in argv:
        t = tx['scope']
        m = t.replace('R1aa ain am1 470000', 'R1aa ain am1 480000')
        assert m != t
        d, *_ = spicecmp.compare('scope', m, comps, nets, cfg)
        print('mutant scope (R1aa 470k -> 480k):', 'FAILS as it must' if d else 'PASSED (the check is blind)')
        t = tx['awg']
        m = t.replace('Cbin dac bin 1e-11', 'Cbin dac bin 2e-11'); assert m != t
        d, *_ = spicecmp.compare('awg', m, comps, nets, cfg)
        print('mutant awg (C304 10p -> 20p):', 'FAILS as it must' if d else 'PASSED (blind)')
        m = tx['awg'].replace('Cbin dac bin 1e-11\n', ''); assert m != tx['awg']
        d, *_ = spicecmp.compare('awg', m, comps, nets, cfg)
        print('mutant awg (C304 removed from the netlist):', 'FAILS as it must' if d else 'PASSED (blind)')
        m = tx['scope'].replace('Rnpa an anp 680', 'Rnpa an bnp 680'); assert m != tx['scope']
        d, *_ = spicecmp.compare('scope', m, comps, nets, cfg)
        print('mutant scope (Rnp of CH1 wired to the other channel):', 'FAILS as it must' if d else 'PASSED (blind)')
    return bad


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
