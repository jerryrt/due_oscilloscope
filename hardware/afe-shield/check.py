#!/usr/bin/env python3
"""Check schematic ERC and critical Due/AFE connectivity; not a PCB release gate."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent / 'sim'))
from run import kicad_cli

root = Path(__file__).resolve().parent
try:
    cli = kicad_cli()
except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
    sys.exit(str(exc))
with tempfile.TemporaryDirectory(prefix='afe-check-') as temp:
    temp = Path(temp)
    subprocess.run([cli, 'sch', 'erc', '--format', 'json', '-o', str(temp/'erc.json'),
                    str(root/'afe-shield.kicad_sch')], check=True)
    report = json.loads((temp/'erc.json').read_text())
    issues = [i for sheet in report['sheets'] for i in sheet['violations']]
    unexpected = [i for i in issues if i['severity'] == 'error' or i['type'] != 'isolated_pin_label']
    if unexpected:
        sys.exit(json.dumps(unexpected, indent=2))
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                    '-o', str(temp/'net.xml'), str(root/'afe-shield.kicad_sch')], check=True)
    tree = ET.parse(temp/'net.xml')
    components = {c.attrib['ref']: c for c in tree.findall('./components/comp')}
    required_fields = {
        'D1': {'MPN': 'LM4040AIM3-3.0/NOPB'},
        'U1': {'MPN': 'MCP6024-E/SL'},
        'R3': {'Tolerance': '0.1%'}, 'R4': {'Tolerance': '0.1%'},
        **{ref: {'Tolerance': '1%'} for ref in ('R5', 'R6', 'R7')},
        **{ref: {'Tolerance': '5%', 'Dielectric': 'C0G/NP0'}
           for ref in ('C5', 'C6', 'C7')},
    }
    for ref, required in required_fields.items():
        component = components.get(ref)
        if component is None:
            sys.exit(f'Missing BOM component: {ref}')
        fields = {f.attrib['name']: f.text for f in component.findall('./fields/field')}
        for name, value in required.items():
            if fields.get(name) != value:
                sys.exit(f'{ref} {name}: expected {value!r}, got {fields.get(name)!r}')
        if ref.startswith('R') and 'Dielectric' in fields:
            sys.exit(f'{ref}: capacitor dielectric field belongs on a capacitor')
    nets = {n.attrib['name']: {(p.attrib['ref'], p.attrib['pin']) for p in n.findall('node')}
            for n in tree.findall('./nets/net')}
    expected = {
        '/DAC0': {('J5','5'),('U1','10')},
        '/DAC1': {('J5','6'),('U1','12')},
        '/CANRX0': {('J5','7')}, '/CANTX0': {('J5','8')},
        '/SCL1': {('J2','1')}, '/SDA1': {('J2','2')},
        '/SDA/20': {('J6','7')}, '/SCL/21': {('J6','8')},
        '/AREF': {('J2','3'),('JP1','2')},
        '/reference/VREF3V0': {('U1','1'),('U1','2'),('JP1','1'),('R3','1')},
        '/VREF1V5': {('U1','6'),('U1','7'),('R7','1')},
        '/A0': {('J3','1'),('R5','2'),('C5','1')},
        '/A1': {('J3','2'),('R6','2'),('C6','1')},
        '/A2': {('J3','3'),('R7','2'),('C7','1')},
    }
    for name, pins in expected.items():
        if nets.get(name) != pins:
            sys.exit(f'{name}: expected {sorted(pins)}, got {sorted(nets.get(name, set()))}')
    for name, pins in [('GND',{('D1','2'),('U1','11')}),('+3V3',{('U1','4'),('R1','1')})]:
        if not pins <= nets[name]:
            sys.exit(f'Missing power connections on {name}')
    print(f'PASS: no ERC errors; {len(issues)} isolated unused-header label warnings; '
          'critical nets and BOM fields match.')
