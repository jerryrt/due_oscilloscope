#!/usr/bin/env python3
"""Check internal consistency; this does not verify the physical PCB."""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import pcbnew as pcb
import build_model as model
from review_notes import QUESTIONS, GROUP

root = Path(__file__).resolve().parent
cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli')
if not cli:
    cli = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
version = subprocess.check_output([cli, 'version'], text=True).strip()
if not version.startswith('10.') or not pcb.Version().startswith('10.'):
    raise SystemExit('Both CLI and Python must come from KiCad 10.x.')

board = pcb.LoadBoard(str(root / (model.NAME + '.kicad_pcb')))
assert board is not None
footprints = {f.GetReference(): f for f in board.GetFootprints()}
assert set(footprints) == {d['ref'] for d in model.devices} | {'H1', 'H2'}
grid = footprints['PG1']
expected_grid = {f'R{r:02}C{c:02}' for r in range(1, 16) for c in model.grid_columns(r)}
assert {p.GetNumber() for p in grid.Pads()} == expected_grid
assert len(expected_grid) == 341
fanout = {link['grid']: '/' + link['net'] for link in model.fanout_links}
for pad in grid.Pads():
    assert pad.GetNetname() == fanout.get(pad.GetNumber(), ''), pad.GetNumber()
assert len(model.fanout_links) == 28
vias = [t for t in board.GetTracks() if isinstance(t, pcb.PCB_VIA)]
tracks = [t for t in board.GetTracks() if not isinstance(t, pcb.PCB_VIA)]
assert len(vias) == len(model.supplemental['vias']) == 5
fanout_tracks = [t for t in tracks if t.GetNetname() in set(fanout.values())]
assert len(fanout_tracks) == 98
assert {t.GetNetname() for t in fanout_tracks} == set(fanout.values())
assert len(list(footprints['J8'].Pads())) == 40
# P3 exposed pads supersede P2.1: digital 5V aligns with J12, but J3 is
# 4.064 mm below it, between the D22 and D24 rows. Lower 5V aligns to J15.
def pad_of(ref, number):
    return next(p for p in footprints[ref].Pads() if p.GetNumber() == number)

def aligned_y(a, b):
    assert abs(a.GetPosition().y - b.GetPosition().y) <= 2

aligned_y(pad_of('J7', '1'), pad_of('J12', '1'))
aligned_y(pad_of('J8', '1'), pad_of('J12', '1'))
assert pad_of('J7', '3').GetPosition().y < pad_of('J3', '1').GetPosition().y < pad_of('J7', '5').GetPosition().y
for ref in range(1, 7):
    gap = pcb.ToMM(pad_of('J'+str(ref), '1').GetPosition().y - pad_of('J'+str(ref+9), '1').GetPosition().y)
    assert abs(gap - 4.064) < 2e-6, (ref, gap)
assert abs(pcb.ToMM(pad_of('J8', '39').GetPosition().y - pad_of('J15', '1').GetPosition().y)) < 0.3
assert abs(pcb.ToMM(pad_of('J7', '1').GetPosition().x - pad_of('J3', '8').GetPosition().x) - 7.62) < 2e-6
# Meaningful regressions from stripped photos: the old lower-switch RESET
# assignment must not reappear, and the three corner SPI starts must match.
for contacts, expected in [([('SW1','1'),('SW1','2'),('J9','6')], '/DUE_RESET'),
                           ([('SW1','3'),('SW1','4'),('D1','1'),('D2','1'),('J9','5')], '/DUE_GND'),
                           ([('R2','2'),('R1','1'),('J9','1'),('J8','39'),('J8','40')], '/DUE_+5V'),
                           ([('J9','2')], '/DUE_D50'),([('J9','3')], '/DUE_D51'),
                           ([('J9','4')], '/DUE_D52')]:
    assert all(pad_of(*c).GetNetname() == expected for c in contacts), (contacts, expected)
bottom_pair = {tuple(pad_of('J8', n).GetPosition()) for n in ('39', '40')}
bars = [t for t in tracks if {tuple(t.GetStart()), tuple(t.GetEnd())} == bottom_pair]
assert len(bars) == 1 and bars[0].GetLayer() == pcb.B_Cu, 'Bottom 5V crossbar belongs only on B.Cu'
assert not footprints['SW1'].IsDNP() and not footprints['J9'].IsDNP()
assert all(not footprints['J'+str(n)].IsDNP() for n in range(1,7))
# IMG_2139: D13 departs inner J1.3; no back track leaves outer J10.3.
stat_start = pad_of('J1', '3').GetPosition()
assert any(t.GetLayer() == pcb.B_Cu and (t.GetStart() == stat_start or t.GetEnd() == stat_start)
           for t in tracks)
outer_stat = pad_of('J10', '3').GetPosition()
assert not any(t.GetLayer() == pcb.B_Cu and (t.GetStart() == outer_stat or t.GetEnd() == outer_stat)
               for t in tracks)
# Owner-confirmed ground arrival must reach J10.2, with AREF on a separate net.
assert pad_of('J9','5').GetNetname() == pad_of('J10','2').GetNetname() == '/DUE_GND'
assert pad_of('J10','1').GetNetname() == '/DUE_AREF'
corner_route = next(r for r in model.supplemental['routes'] if r['id'] == 'CORNER-HEADER-B')
assert (corner_route['a'], corner_route['b'], corner_route['layer']) == ('J9.5', 'J10.2', 'B.Cu')
assert all(r['a'] and r['b'] for r in model.supplemental['routes']), 'No unresolved open route remains'
# In flipped B.Cu view, D50 must enter the middle-right of J7.31.
# The horizontal approach is from canonical left because the view is mirrored.
d50_target = pad_of('J7', '31').GetPosition()
assert any(t.GetLayer() == pcb.B_Cu and t.GetNetname() == '/DUE_D50'
           and t.GetEnd() == d50_target
           and t.GetStart().y == d50_target.y and t.GetStart().x < d50_target.x
           for t in tracks), 'J7.31 must have a horizontal right-edge entry in flipped B.Cu view'
# Every copper chain must connect exactly its one land and one grid hole,
# with no branch or dead end. This checks the model, not the photograph.
lands = {p.GetNumber(): p for p in footprints['TP1'].Pads()}
holes = {p.GetNumber(): p for p in grid.Pads()}
for link in model.fanout_links:
    net = '/' + link['net']
    degree = collections.Counter()
    for track in fanout_tracks:
        if track.GetNetname() == net:
            for p in (track.GetStart(), track.GetEnd()):
                degree[(p.x, p.y)] += 1
    terminals = {xy for xy, n in degree.items() if n == 1}
    assert all(n in (1, 2) for n in degree.values())
    assert terminals == {(p.GetPosition().x, p.GetPosition().y)
                         for p in (lands[link['land']], holes[link['grid']])}, link

# Every recorded visible polyline must survive in the native board on its
# recorded layer/net. Open ends are deliberately retained at occlusions.
evidence = json.loads((root / 'wiring-evidence.json').read_text())
native_edges = collections.Counter()
def edge_key(a, b, layer, net):
    # KiCad's integer-mm conversion can round a serialized coordinate by
    # one nanometre; 10 nm bins preserve topology without spurious failures.
    return tuple(round(v / 10) for v in (a.x, a.y, b.x, b.y)) + (layer, net)

for track in tracks:
    a, b = track.GetStart(), track.GetEnd()
    native_edges[edge_key(a, b, track.GetLayer(), track.GetNetname())] += 1
for route in evidence['copper_routes']:
    points = [model.local(*p) for p in route['model_polyline_mm']]
    layer = pcb.F_Cu if route['layer'] == 'F.Cu' else pcb.B_Cu
    for a, b in zip(points, points[1:]):
        if a == b:
            continue
        key = edge_key(a, b, layer, '/' + route['net'])
        assert native_edges[key] > 0, route['id']
        native_edges[key] -= 1
for fragment in evidence['unclassified_fragments']:
    layer = pcb.User_3 if fragment['side'] == 'front' else pcb.User_4
    drawings = [s for s in board.GetDrawings() if s.GetLayer() == layer and isinstance(s, pcb.PCB_SHAPE)]
    assert any(s.GetStart() == model.local(*fragment['points'][0]) for s in drawings), fragment['id']
for f in footprints.values():
    assert f.IsLocked()
    for pad in f.Pads():
        x = pcb.ToMM(pad.GetPosition().x) - model.ORIGIN[0]
        y = pcb.ToMM(pad.GetPosition().y) - model.ORIGIN[1]
        assert 0 < x < model.WIDTH and 0 < y < model.HEIGHT, (f.GetReference(), x, y)
edges = [s for s in board.GetDrawings() if s.GetLayer() == pcb.Edge_Cuts]
assert len(edges) == 4
xs = [pcb.ToMM(p.x) for s in edges for p in (s.GetStart(), s.GetEnd())]
ys = [pcb.ToMM(p.y) for s in edges for p in (s.GetStart(), s.GetEnd())]
assert abs(max(xs) - min(xs) - 103) < 1e-6
assert abs(max(ys) - min(ys) - 55) < 1e-6
# Every review location must have a visible, non-copper native circle.
circles = [s for s in board.GetDrawings() if isinstance(s, pcb.PCB_SHAPE)
           and s.GetLayer() == pcb.User_5 and s.GetShape() == pcb.SHAPE_T_CIRCLE]
for question in QUESTIONS:
    for target in question['targets']:
        assert any(s.GetStart() == model.local(*target['at']) for s in circles), (question['id'], target)
review_groups = [g for g in board.Groups() if g.GetName() == GROUP]
assert len(review_groups) == 1
assert all(item.GetLayer() == pcb.User_5 for item in review_groups[0].GetItems())
# The populated assembly needs actual project-local 3D bodies, while the
# bare prototyping/breakout fields must stay empty in the 3D viewer.
models_3d = {ref:list(f.Models()) for ref,f in footprints.items() if list(f.Models())}
assert len(models_3d) == 20
assert all(ref not in models_3d for ref in ('J8','PG1','TP1','H1','H2'))
assert all(ref in models_3d for ref in ('SW1','D1','D2','R1','R2','R3','J7','J9'))
for ref, models in models_3d.items():
    assert len(models) == 1, ref
    for item in models:
        assert item.m_Show and item.m_Filename.startswith('${KIPRJMOD}/models/kicad/'), ref
        path = root / item.m_Filename.replace('${KIPRJMOD}/','',1)
        assert path.is_file() and path.stat().st_size > 0, (ref,path)

with tempfile.TemporaryDirectory(prefix='carrier-check-') as work:
    temp = Path(work)
    schematic = str(root / (model.NAME + '.kicad_sch'))
    subprocess.run([cli, 'sch', 'erc', '--format', 'json', '-o', str(temp / 'erc.json'),
                    schematic], check=True)
    erc = json.loads((temp / 'erc.json').read_text())
    issues = [v for s in erc['sheets'] for v in s['violations']]
    unexpected = [v for v in issues if v['severity'] == 'error' or v['type'] != 'isolated_pin_label']
    assert not unexpected, unexpected
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                    '-o', str(temp / 'net.xml'), schematic], check=True)
    netlist = ET.parse(temp / 'net.xml')
    sch_nets = {(p.get('ref'), p.get('pin')): n.get('name')
                for n in netlist.findall('./nets/net') for p in n.findall('node')}
    pcb_nets = {(f.GetReference(), p.GetNumber()): p.GetNetname()
                for f in footprints.values() if f.GetReference() not in {'H1', 'H2'}
                for p in f.Pads() if p.GetNetCode() != 0}
    assert sch_nets == pcb_nets, (set(sch_nets.items()) - set(pcb_nets.items()),
                                  set(pcb_nets.items()) - set(sch_nets.items()))
    subprocess.run([cli, 'pcb', 'export', 'svg', '--layers', 'F.Cu,Edge.Cuts,User.1,User.2',
                    '--page-size-mode', '2', '--exclude-drawing-sheet', '--mode-single',
                    '-o', str(temp / 'board.svg'), str(root / (model.NAME + '.kicad_pcb'))], check=True)

report = {'kicad_version': version, 'native_board_reload': 'passed',
          'outline_mm': [103, 55], 'grid_pad_count': len(expected_grid),
          'schematic_contact_count': len(sch_nets), 'schematic_pcb_pad_nets': 'match',
          'erc_errors': 0, 'erc_warnings': dict(collections.Counter(v['type'] for v in issues)),
          'track_count': len(tracks), 'via_count': len(vias), 'all_pad_centres_inside_outline': True,
          'board_svg_export': 'passed',
          'visually_traced_connections': 28, 'fanout_chain_endpoints': 'passed',
          'supplemental_route_count': len(evidence['copper_routes']),
          'unclassified_fragment_count': len(evidence['unclassified_fragments']),
          'recorded_routes_present_in_board': 'passed',
          'physical_fit': 'not verified', 'hidden_copper': 'not verified',
          'digital_header_row_alignment': '5V row = J12; J3 lies between D22/D23 and D24/D25; bottom bare 5V row near J15 (0.284 mm)',
          'parallel_header_row_gap_mm': 4.064,
          'stripped_photo_net_regressions': 'passed',
          'power_routing_regressions': 'R1-left/R2-right/J9.1 = +5V; J8 bottom crossbar only on B.Cu',
          'owner_confirmed_ground_endpoint': 'J9.5 -> J10.2 on B.Cu; final bends estimated',
          'open_route_endpoints': 0,
          'component_3d_body_count': len(models_3d),
          'project_local_3d_models': 'all paths resolve',
          'scope': 'Internal consistency of photo-derived model only; not fabrication approval.'}
(root / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
(root / 'review-validation.json').write_text(json.dumps({
    'revision': 'R2 / P3.5', 'question_count': len(QUESTIONS),
    'target_count': sum(len(q['targets']) for q in QUESTIONS),
    'native_target_circles': 'all present', 'native_group': GROUP,
    'review_items_non_copper': True,
    'scope': 'P3 baseline changes copper intentionally; review drawings themselves occupy only User.5.',
}, indent=2)+'\n')
(root / 'header-alignment-validation.json').write_text(json.dumps({
    'revision': 'P3.5', 'supersedes': 'P2.1 (archived in evidence/header-alignment-P2.1.json)',
    'source': 'IMG_2135/2138 exposed parallel header rows',
    'upper_main_y_mm': 5.524, 'upper_breakout_y_mm': 1.46,
    'lower_main_y_mm': 53.5, 'lower_breakout_y_mm': 49.436,
    'digital_first_row_y_mm': 1.46, 'digital_D22_D23_y_mm': 4.0,
    'digital_D24_D25_y_mm': 6.54, 'parallel_header_gap_mm': 4.064,
    'correction': 'J3 lies between D22/D23 and D24/D25, not aligned to D22/D23.',
    'photo_fit': 'approximate; native assertions passed; physical fit pending',
}, indent=2)+'\n')
print(json.dumps(report, indent=2))
