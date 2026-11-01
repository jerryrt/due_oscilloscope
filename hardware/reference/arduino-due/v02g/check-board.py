#!/usr/bin/env python3
"""Check source correspondence with KiCad 10's bundled pcbnew Python."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import pcbnew

ROOT = Path(__file__).resolve().parent
CLI = (os.environ.get('KICAD_CLI') or shutil.which('kicad-cli')
       or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')


def snapshot(board):
    """Electrical/placement state independent of item iteration order."""
    return sorted((fp.GetReference(), fp.GetPosition().x, fp.GetPosition().y,
                   fp.GetOrientationDegrees(),
                   sorted((pad.GetNumber(), pad.GetNetname(),
                           pad.GetPosition().x, pad.GetPosition().y)
                          for pad in fp.Pads()))
                  for fp in board.GetFootprints())


def main():
    version = pcbnew.GetBuildVersion()
    assert version.startswith('10.'), 'Use KiCad 10.x.'
    path = ROOT / 'DUE_V02g.kicad_pcb'
    assert '(layer "UNDEFINED")' not in path.read_text()
    board = pcbnew.LoadBoard(str(path))
    assert board is not None, 'Native board load failed.'
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    source = ET.parse(ROOT / 'source/DUE_V02g.brd')
    elements = source.findall('.//board/elements/element')
    renames = {}
    max_delta = 0.0
    for element in elements:
        ref = element.get('name')
        actual = ref if ref in footprints else ref + '0'
        assert actual in footprints, f'Missing {ref}'
        if actual != ref:
            renames[ref] = actual
        fp = footprints[actual]
        delta = max(abs(pcbnew.ToMM(fp.GetPosition().x) - float(element.get('x'))),
                    abs(pcbnew.ToMM(fp.GetPosition().y) + float(element.get('y'))))
        max_delta = max(max_delta, delta)
        assert delta <= 0.000002, (ref, delta)

    connections = 0
    for signal in source.findall('.//board/signals/signal'):
        for contact in signal.findall('contactref'):
            ref = contact.get('element')
            fp = footprints[renames.get(ref, ref)]
            pads = [pad for pad in fp.Pads() if pad.GetNumber() == contact.get('pad')]
            assert len(pads) == 1, (ref, contact.get('pad'), len(pads))
            assert pads[0].GetNetname() == signal.get('name'), (
                ref, contact.get('pad'), pads[0].GetNetname(), signal.get('name'))
            connections += 1

    extras = sorted(set(footprints) - {renames.get(e.get('name'), e.get('name'))
                                     for e in elements})
    assert len(extras) == len(source.findall('.//board/plain/hole'))
    assert all(ref.startswith('UNK_HOLE_') for ref in extras)
    models = sum(len(fp.Models()) for fp in board.GetFootprints())
    drawings = {name: sum(item.GetLayerName() == name for item in board.GetDrawings())
                for name in ('User.1', 'User.2')}
    assert drawings == {'User.1': 139, 'User.2': 1}, drawings
    assert board.GetCopperLayerCount() == 2
    report = json.loads((ROOT / 'import-report.json').read_text())
    assert not report['errors'] and not report['warnings']
    assert len(footprints) == report['statistics']['footprints']
    tracks = list(board.GetTracks())
    vias = sum(isinstance(t, pcbnew.PCB_VIA) for t in tracks)
    assert len(tracks) - vias == report['statistics']['tracks']
    assert vias == report['statistics']['vias']
    assert len(board.Zones()) == report['statistics']['zones']

    with tempfile.TemporaryDirectory(prefix='due-v02g-check-') as tmp:
        saved = Path(tmp) / path.name
        assert pcbnew.SaveBoard(str(saved), board)
        reloaded = pcbnew.LoadBoard(str(saved))
        assert snapshot(reloaded) == snapshot(board)
        assert len(list(reloaded.GetTracks())) == len(tracks)
        assert len(reloaded.Zones()) == len(board.Zones())
        svg = Path(tmp) / 'top.svg'
        subprocess.run([
            CLI, 'pcb', 'export', 'svg', '--layers', 'F.Cu,F.Silkscreen,Edge.Cuts',
            '--mode-single', '--page-size-mode', '2', '--exclude-drawing-sheet',
            '--output', str(svg), str(path),
        ], check=True)
        assert ET.parse(svg).getroot().tag.endswith('svg')
        svg_bytes = svg.stat().st_size
        assert svg_bytes > 1000

    result = {
        'kicad_version': version,
        'source_components': len(elements),
        'imported_footprints': len(footprints),
        'extra_hole_footprints': extras,
        'reference_renames': renames,
        'maximum_component_position_delta_mm': max_delta,
        'component_position_tolerance_mm': 0.000002,
        'verified_pad_net_connections': connections,
        'copper_layers': board.GetCopperLayerCount(),
        'tracks_including_vias': len(tracks),
        'vias': vias,
        'zones_including_rule_areas': len(board.Zones()),
        'restriction_reference_drawings': drawings,
        'assigned_3d_models': models,
        'native_load_save_reload': 'passed',
        'top_svg_export': 'passed',
        'top_svg_bytes': svg_bytes,
        'scope': 'Source correspondence and native read/export only; not a fabrication or physical-board qualification. No native KiCad schematic conversion.',
    }
    (ROOT / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
