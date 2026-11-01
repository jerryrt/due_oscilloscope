#!/usr/bin/env python3
"""Import the retained V03 EAGLE board without changing the V02g reference."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
CLI = (os.environ.get('KICAD_CLI') or shutil.which('kicad-cli')
       or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')


def digest(path):
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def main():
    version = subprocess.check_output([CLI, 'version'], text=True).strip()
    if not version.startswith('10.'):
        raise SystemExit('Use KiCad 10.x for this conversion.')
    source_dir = ROOT / 'source'
    source_dir.mkdir(exist_ok=True)
    previous_path = ROOT / 'sources.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    for name in ('Arduino-DUE-V03.brd', 'Arduino-DUE-V03.sch'):
        retained = source_dir / name
        if not retained.is_file():
            raise SystemExit(f'Missing retained EAGLE source: {retained}')
        expected = previous.get('files', {}).get('source/' + name)
        if expected and digest(retained) != expected:
            raise SystemExit(f'Retained source differs from its provenance record: {retained}')
    source = source_dir / 'Arduino-DUE-V03.brd'
    board = ROOT / 'Arduino-DUE-V03.kicad_pcb'
    subprocess.run([
        CLI, 'pcb', 'import', '--format', 'eagle', '--report-format', 'json',
        '--report-file', str(ROOT / 'import-report.json'),
        '--output', str(board), str(source),
    ], check=True)
    report = json.loads((ROOT / 'import-report.json').read_text())
    if report['errors'] or report['warnings']:
        raise SystemExit('Inspect the import report before accepting this board.')
    rules = source_dir / 'Arduino-DUE-V03.kicad_dru'
    if rules.exists():
        rules.replace(ROOT / rules.name)

    # 10.0.6 puts seven unique restriction-line geometries on UNDEFINED.
    # Three are shared by front/back source layers. Restore those duplicates
    # as separate reference drawings; these lines do NOT enforce keepouts.
    source_lines = [e for e in ET.parse(source).findall('.//board/plain/wire')
                    if e.get('layer') in {'41', '42'}]
    counts = {'User.1': 0, 'User.2': 0}
    recovered = set()
    unknown = 0

    def recover(match):
        nonlocal unknown
        graphic = match[0]
        if '(layer "UNDEFINED")' not in graphic:
            return graphic
        if match[1] != 'gr_line':
            raise ValueError('Unexpected undefined-layer graphic')
        unknown += 1
        start = tuple(map(float, re.search(r'\(start ([\d.-]+) ([\d.-]+)', graphic).groups()))
        end = tuple(map(float, re.search(r'\(end ([\d.-]+) ([\d.-]+)', graphic).groups()))
        width = float(re.search(r'\(width ([\d.-]+)', graphic)[1])
        matches = []
        for index, line in enumerate(source_lines):
            expected = (float(line.get('x1')), -float(line.get('y1')),
                        float(line.get('x2')), -float(line.get('y2')),
                        float(line.get('width')))
            if all(abs(a - b) < 1e-5 for a, b in zip((*start, *end, width), expected)):
                layer = {'41': 'User.1', '42': 'User.2'}[line.get('layer')]
                # Copied geometry must have a distinct UUID in KiCad.
                mapped = graphic.replace('(layer "UNDEFINED")', f'(layer "{layer}")')
                mapped = re.sub(r'\(uuid "[^"]+"\)', f'(uuid "{uuid.uuid4()}")', mapped)
                matches.append(mapped)
                counts[layer] += 1
                recovered.add(index)
        if not matches:
            raise ValueError('No source restriction line matches imported graphic')
        return ''.join(matches)

    text = re.sub(r'\n\t\((gr_\w+)[\s\S]*?(?=\n\t\(|\n\))', recover, board.read_text())
    if '(layer "UNDEFINED")' in text or len(recovered) != len(source_lines):
        raise SystemExit('Restriction drawing recovery is incomplete.')
    board.write_text(text)
    if (ROOT.parent / 'models/alignment.json').exists():
        runpy.run_path(str(ROOT / 'attach-models.py'))['attach_models']()
    provenance = {
        'board_revision': 'Arduino-DUE-V03',
        'source_note': 'Original extracted Arduino V03 EAGLE files retained; ZIP archives intentionally omitted.',
        'kicad_version': version,
        'undefined_imported_lines_recovered': unknown,
        'restriction_reference_drawings': counts,
        'restriction_note': 'User.1: front restriction lines; User.2: back restriction lines. Reference drawings only, not enforced copper keepouts. Imported circular rule areas are separate.',
        'files': {str(p.relative_to(ROOT)): digest(p) for p in (
            source, source_dir / 'Arduino-DUE-V03.sch', board,
            ROOT / 'Arduino-DUE-V03.kicad_dru')},
    }
    if 'original_archive' in previous:
        provenance['original_archive'] = previous['original_archive']
    if (ROOT / 'models-3d.json').exists():
        provenance['component_models'] = 'models-3d.json'
    (ROOT / 'sources.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'KiCad {version}; recovered restriction drawings: {counts}')


if __name__ == '__main__':
    main()
