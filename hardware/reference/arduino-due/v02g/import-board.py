#!/usr/bin/env python3
"""Recreate the KiCad reference PCB from the retained official EAGLE board."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parent
cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli')
if not cli:
    cli = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
version = subprocess.check_output([cli, 'version'], text=True).strip()
if not version.startswith('10.'):
    raise SystemExit('Use KiCad 10.x for this conversion.')
board = root / 'DUE_V02g.kicad_pcb'
subprocess.run([
    cli, 'pcb', 'import', '--format', 'eagle', '--report-format', 'json',
    '--report-file', str(root / 'import-report.json'),
    '--output', str(board), str(root / 'source/DUE_V02g.brd'),
], check=True)
rules = root / 'source/DUE_V02g.kicad_dru'
if rules.exists():
    rules.replace(root / 'DUE_V02g.kicad_dru')

# KiCad 10.0.6 leaves these plain-board graphics on UNDEFINED layers.
# Recover their source layer using their position, preserving every object.
source = ET.parse(root / 'source/DUE_V02g.brd').getroot()
plain = source.findall('.//board/plain/*')
counts = {'User.1': 0, 'User.2': 0}


def map_graphic(match):
    graphic = match[0]
    if '(layer "UNDEFINED")' not in graphic:
        return graphic
    position = re.search(r'\((?:start|center|at) ([\d.-]+) ([\d.-]+)', graphic)
    x, y = map(float, position.groups())
    layers = {
        item.get('layer') for item in plain
        if abs(float(item.get('x', item.get('x1', 'nan'))) - x) < 1e-5
        and abs(float(item.get('y', item.get('y1', 'nan'))) + y) < 1e-5
    }
    # Layer 114 is test-probe annotation. The layer-42 line is retained
    # as a reference drawing, NOT an enforced bottom-copper keepout.
    mapping = {frozenset({'114'}): 'User.1', frozenset({'42'}): 'User.2'}
    layer = mapping[frozenset(layers)]
    counts[layer] += 1
    return graphic.replace('(layer "UNDEFINED")', f'(layer "{layer}")')


text = re.sub(r'\n\t\((gr_\w+)[\s\S]*?(?=\n\t\(|\n\))',
              map_graphic, board.read_text())
if '(layer "UNDEFINED")' in text:
    raise SystemExit('Unmapped layers remain; inspect this importer version.')
board.write_text(text)
print(f'KiCad {version}; recovered drawing layers: {counts}')
