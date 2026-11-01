#!/usr/bin/env python3
"""Check source correspondence with KiCad 10's bundled pcbnew Python."""
import hashlib
import importlib.util
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
    path = ROOT / 'Arduino-DUE-V03.kicad_pcb'
    assert '(layer "UNDEFINED")' not in path.read_text()
    project_path = path.with_suffix('.kicad_pro')
    project_settings = None
    if project_path.exists():
        project_data = json.loads(project_path.read_text())
        assert project_data['meta']['filename'] == project_path.name
        settings = pcbnew.GetSettingsManager()
        assert settings.LoadProject(str(project_path)), 'Native project load failed.'
        project_settings = {'file': project_path.name, 'native_load': 'passed'}
    board = pcbnew.LoadBoard(str(path))
    assert board is not None, 'Native board load failed.'
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    source = ET.parse(ROOT / 'source/Arduino-DUE-V03.brd')
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
    model_record = ROOT / 'models-3d.json'
    if model_record.exists():
        assignment_record = json.loads(model_record.read_text())
        spec = importlib.util.spec_from_file_location('attach_models', ROOT / 'attach-models.py')
        attachment = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(attachment)
        prepared, _ = attachment.prepared_assignments()
        assert models == len(assignment_record['assignments']) == len(prepared)
        assert sorted(prepared) == assignment_record['assignments']
        for assignment in prepared.values():
            fp = footprints[assignment['reference']]
            actual_models = list(fp.Models())
            assert len(actual_models) == 1
            expected = '${KIPRJMOD}/../models/' + assignment['file']
            assert actual_models[0].m_Filename == expected
            for field, expected_values in [('m_Offset', (0,0,0)), ('m_Rotation', (0,0,0)),
                                            ('m_Scale', (1,1,1))]:
                vector = getattr(actual_models[0], field)
                assert tuple(getattr(vector, axis) for axis in ('x','y','z')) == expected_values
            asset = ROOT.parent / 'models' / assignment['file']
            assert hashlib.sha256(asset.read_bytes()).hexdigest() == assignment['sha256']
    drawings = {name: sum(item.GetLayerName() == name for item in board.GetDrawings())
                for name in ('User.1', 'User.2')}
    assert drawings == {'User.1': 5, 'User.2': 5}, drawings
    assert board.GetCopperLayerCount() == 2
    report = json.loads((ROOT / 'import-report.json').read_text())
    assert not report['errors'] and not report['warnings']
    assert len(footprints) == report['statistics']['footprints']
    tracks = list(board.GetTracks())
    vias = sum(isinstance(t, pcbnew.PCB_VIA) for t in tracks)
    assert len(tracks) - vias == report['statistics']['tracks']
    assert vias == report['statistics']['vias']
    assert len(board.Zones()) == report['statistics']['zones']

    with tempfile.TemporaryDirectory(prefix='due-v03-check-') as tmp:
        if project_settings is not None:
            project_copy = Path(tmp) / project_path.name
            settings.SaveProjectCopy(str(project_copy))
            assert project_copy.exists(), 'Native project save-copy failed.'
            assert isinstance(json.loads(project_copy.read_text())['board'], dict)
            project_settings['native_save_copy'] = 'passed'
        saved = Path(tmp) / path.name
        assert pcbnew.SaveBoard(str(saved), board)
        reloaded = pcbnew.LoadBoard(str(saved))
        assert snapshot(reloaded) == snapshot(board)
        assert sorted((fp.GetReference(), model.m_Filename)
                      for fp in reloaded.GetFootprints() for model in fp.Models()) == sorted(
                          (fp.GetReference(), model.m_Filename)
                          for fp in board.GetFootprints() for model in fp.Models())
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
        'project_settings': project_settings,
        'native_load_save_reload': 'passed',
        'top_svg_export': 'passed',
        'top_svg_bytes': svg_bytes,
        'scope': 'Source correspondence and native read/export only; not a fabrication or physical-board qualification. No native KiCad schematic conversion.',
    }
    (ROOT / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
