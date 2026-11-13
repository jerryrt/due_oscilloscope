"""A schematic_rows.Project built from a part list alone: no kicad-cli, no files. It is what KiCad's netlist export would hold for
a project generated from the parts (value, footprint and the hidden fields as symbol fields, one net per design net, a pin
function from the datasheet table for the parts that have one, one 'unconnected-' net per declared NC pin), so every row but the
ERC one can be run, and broken, in milliseconds."""
import os

from pcbtools import schematic_rows as sr


def project_from_parts(parts, datasheet_pins, directory=''):
    comps, nets = {}, {}
    for p in parts:
        part = p['sym'].split(':')[1]
        comps.setdefault(p['ref'], dict(value=p['value'], footprint=p['fp'], part=part,
                               fields={'LCSC': p['lcsc'], 'Sim': p.get('sim', ''), 'Block': p['block'], 'Fitted by': p['fitted_by'],
                                       'Note': p.get('note', '')}))      # a duplicate designator: the first one wins
        fn = datasheet_pins.get(part, {})
        for pin, net in p['pins'].items():
            nets.setdefault(net, []).append((p['ref'], pin, fn.get(pin, '')))
        for pin in (p.get('nc') or ()) if p.get('nc') != 'rest' else ():
            nets[f"unconnected-({p['ref']}-Pad{pin})"] = [(p['ref'], pin, fn.get(pin, ''))]
    return sr.Project('', parts, comps, {k: sorted(v) for k, v in nets.items()}, directory or os.getcwd())
