#!/usr/bin/env python3
"""Rebuild the photo-derived carrier model. Run with KiCad 10's Python.

Outputs are editable KiCad files. Rebuilding replaces edits to those files;
update this source only when deliberately revising the carrier baseline.
"""
import csv
import hashlib
import json
from pathlib import Path
import uuid

import pcbnew as pcb
from supplemental_routes import reconstruct
from review_notes import add_review_layer, save_review_board
from models_3d import attach_models

ROOT = Path(__file__).resolve().parent
NAME = 'mega-proto-carrier'
LIB = 'Carrier'
PITCH = 2.54
ORIGIN = (80.0, 80.0)  # CAD page offset; all worksheets use board-local mm.
WIDTH, HEIGHT = 103.0, 55.0  # Measured by the owner, 2026-10-30.
GRID_X, GRID_Y = 3.8, 8.3  # P3 projective photo registration; physical fit pending.
HEADER_ROW_GAP = 4.064  # Exposed parallel rows, not the 2.54 mm along-row pitch.
NS = uuid.UUID('13fb6c83-e2a4-43b8-9e6b-9fd739ebedb5')


def uid(name):
    return str(uuid.uuid5(NS, name))


def q(value):
    return json.dumps(str(value))


def mm(x, y):
    return pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))


def local(x, y):
    return mm(x + ORIGIN[0], y + ORIGIN[1])


def grid_columns(row):
    if row in (1, 2):
        return range(1, 7)
    if row in (3, 4):
        return range(1, 22)
    if row == 5 or row in (11, 12, 13, 14):
        return range(1, 33)
    if row in (6, 7, 8, 9, 10):
        return range(9, 33)
    return (1, 2, 3, 4, 5, 6, 10)


def row_points(count):
    return [(str(n + 1), n * PITCH, 0) for n in range(count)]


def dual_points(rows):
    return [(str(2 * r + c + 1), c * PITCH, r * PITCH)
            for r in range(rows) for c in range(2)]


def make_footprint(name, points, kind='through', body=None):
    pads = []
    for number, x, y in points:
        if kind == 'through':
            shape = 'circle' if name.startswith(('Header_', 'Corner_')) and number != '1' else 'rect'
            pads.append(f'(pad {q(number)} thru_hole {shape} (at {x} {y}) '
                        '(size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))')
        elif kind == 'smd':
            pads.append(f'(pad {q(number)} smd rect (at {x} {y}) '
                        '(size 0.55 1.65) (layers "F.Cu" "F.Paste" "F.Mask"))')
        elif kind == 'passive':
            pads.append(f'(pad {q(number)} smd rect (at {x} {y}) '
                        '(size 1.1 1.4) (layers "F.Cu" "F.Paste" "F.Mask"))')
        else:
            pads.append(f'(pad "" np_thru_hole circle (at {x} {y}) '
                        '(size 1.6 1.6) (drill 1.6) (layers "*.Cu" "*.Mask"))')
    drawing = ''
    if body:
        x1, y1, x2, y2 = body
        drawing = (f'(fp_rect (start {x1} {y1}) (end {x2} {y2}) '
                   '(stroke (width 0.15) (type default)) (fill none) (layer "F.Fab"))')
    attribute = 'smd' if kind in ('smd', 'passive') else 'through_hole'
    text = f'''(footprint {q(name)} (version 20260206) (generator "pcbnew")
      (layer "F.Cu")
      (descr "Photo-derived carrier geometry; dimensions other than outline are provisional")
      (attr {attribute})
      (fp_text reference "REF**" (at 0 -2) (layer "F.Fab")
        (effects (font (size 0.8 0.8) (thickness 0.12))))
      (fp_text value {q(name)} (at 0 2) (layer "F.Fab") hide
        (effects (font (size 0.8 0.8) (thickness 0.12))))
      {drawing} {' '.join(pads)})'''
    (ROOT / 'Carrier.pretty' / f'{name}.kicad_mod').write_text(text)


# Each duplicate header has separate nets until continuity establishes links.
# Pin functions on main headers come from printed labels interpreted for Due.
headers = [
    ('J1', 'DIGITAL 8-13 / AREF', 20.336, 5.524,
     ['AREF', 'GND', 'D13', 'D12', 'D11', 'D10', 'D9', 'D8']),
    ('J2', 'DIGITAL 0-7', 42.18, 5.524,
     ['D7', 'D6', 'D5', 'D4', 'D3', 'D2', 'D1_TX0', 'D0_RX0']),
    ('J3', 'COMMUNICATION 14-21', 65.04, 5.524,
     ['D14_TX3', 'D15_RX3', 'D16_TX2', 'D17_RX2', 'D18_TX1', 'D19_RX1', 'D20_SDA', 'D21_SCL']),
    ('J4', 'POWER (6 positions)', 29.48, 53.5,
     ['RESET', '+3V3', '+5V', 'GND', 'GND', 'VIN']),
    ('J5', 'ANALOG A0-A7', 47.26, 53.5, [f'A{i}' for i in range(8)]),
    ('J6', 'Due A8-A11 / DAC / CAN', 70.12, 53.5,
     ['A8', 'A9', 'A10', 'A11', 'DAC0', 'DAC1', 'CANRX0', 'CANTX0']),
]
devices = []
for ref, value, x, y, names in headers:
    devices.append(dict(ref=ref, value=value, x=x, y=y,
                        footprint=f'Header_1x{len(names):02}',
                        numbers=[str(i + 1) for i in range(len(names))],
                        nets=['DUE_' + n for n in names], columns=1,
                        assembly='Fitted in normal populated boards',
                        photo_specimen='Front female socket removed for routing photography; reverse male pins retained'))
    dup = 'J' + str(int(ref[1:]) + 9)
    devices.append(dict(ref=dup, value=f'Breakout beside {ref} (verify links)',
                        x=x, y=y - HEADER_ROW_GAP,
                        footprint=f'Header_1x{len(names):02}',
                        numbers=[str(i + 1) for i in range(len(names))],
                        nets=[f'{dup}_{i + 1}_{n}' for i, n in enumerate(names)], columns=1))

digital = ['+5V', '+5V'] + [f'D{i}' for i in range(22, 54)] + ['GND', 'GND']
# IMG_2135/2138 expose the two parallel rows: J12 aligns to digital 5V,
# but J3 is 4.064 mm below J12, BETWEEN D22/D23 and D24/D25.
# This supersedes P2.1's incorrect claim that J3 aligned to D22/D23.
digital_y = next(d['y'] for d in devices if d['ref'] == 'J12')
devices.append(dict(ref='J7', value='Main 2x18 digital header', x=90.44, y=digital_y,
                    footprint='Header_2x18', numbers=[str(i + 1) for i in range(36)],
                    nets=['DUE_' + n for n in digital], columns=2,
                    assembly='Fitted in normal populated boards',
                    photo_specimen='Partly stripped for routing photography'))
devices.append(dict(ref='J8', value='Outer 2x20 breakout (visually linked)', x=95.92, y=digital_y,
                    footprint='Header_2x20', numbers=[str(i + 1) for i in range(40)],
                    nets=[f'J8_{i + 1}_{n}' for i, n in enumerate(digital + ['GND', 'GND', '+5V', '+5V'])],
                    columns=2))
devices.append(dict(ref='J9', value='Corner header fitted; photo-traced contact mapping', x=2.0, y=1.8,
                    footprint='Corner_3x02', numbers=[str(i + 1) for i in range(6)],
                    nets=['CORNER_SUPPLY_UNVERIFIED'] + [f'ICSP_UNKNOWN_{i}' for i in range(2, 7)],
                    columns=2, dnp=False, assembly='Fitted in normal populated boards',
                    photo_specimen='Removed only for routing photography; bare pads exposed'))

# Empty SOIC-style land pattern, not an installed IC or a confirmed pinout.
devices.append(dict(ref='TP1', value='EMPTY 28-land breakout: T/B are coordinate IDs',
                    x=4.9, y=21.5, footprint='Empty_SMD28',
                    numbers=[f'T{i:02}' for i in range(1, 15)] + [f'B{i:02}' for i in range(1, 15)],
                    nets=[f'BREAKOUT_{side}{i:02}' for side in 'TB' for i in range(1, 15)], columns=2))

# Backlit IMG_2134 resolves the alternating two-row fanout. These are
# visual identifications, not meter-verified connections. T/B remain
# coordinate names and do not assert a manufacturer's IC pin numbering.
fanout_links = []
for side in 'TB':
    for n in range(1, 15):
        row = (5 if n % 2 else 4) if side == 'T' else (11 if n % 2 else 12)
        column = (n + 1) // 2
        fanout_links.append(dict(land=f'{side}{n:02}', grid=f'R{row:02}C{column:02}',
                                 row=row, column=column, net=f'BREAKOUT_{side}{n:02}',
                                 evidence='IMG_2134.jpeg: visible SMD fanout',
                                 status='visually_traced_not_meter_verified'))
devices.append(dict(ref='PG1', value='Grid fanout contacts (other holes: PCB geometry)',
                    x=GRID_X, y=GRID_Y, footprint='Grid_32x15_irregular',
                    numbers=[c['grid'] for c in fanout_links],
                    nets=[c['net'] for c in fanout_links], columns=2))
devices.append(dict(ref='SW1', value='Reset switch fitted; upper RESET / lower GND pads',
                    x=21.2, y=50.75, footprint='Switch_6mm_estimate',
                    numbers=['1', '2', '3', '4'], nets=[f'SW_UNKNOWN_{i}' for i in range(1, 5)],
                    columns=2, dnp=False, assembly='Fitted in normal populated boards',
                    photo_specimen='Removed only for routing photography; bare pads exposed'))
for ref, value, x, y in [('D1', 'PWR LED; polarity unverified', 5.05, 48.9),
                         ('D2', 'STAT LED; polarity unverified', 5.05, 53.9),
                         ('R1', '103 marking (10k)', 10.9, 47.4),
                         ('R2', '102 marking (1k)', 10.9, 50.5),
                         ('R3', '102 marking (1k)', 11.05, 53.8)]:
    devices.append(dict(ref=ref, value=value, x=x, y=y, footprint='Passive_estimate',
                        numbers=['1', '2'], nets=[f'{ref}_UNKNOWN_{i}' for i in (1, 2)], columns=1))
    if ref.startswith('D'):
        devices[-1]['footprint'] = 'LED_estimate'

supplemental = reconstruct(devices)


def symbol_definition(d, embedded=False):
    name = d['ref'] + '_contacts'
    numbers = d['numbers']
    cols = d['columns']
    rows = (len(numbers) + cols - 1) // cols
    half = (rows + 1) * PITCH / 2
    pins = []
    for i, number in enumerate(numbers):
        row, side = (i, 0) if cols == 1 else divmod(i, 2)
        x, angle = (-7.62, 0) if side == 0 else (7.62, 180)
        y = (rows - 1) * PITCH / 2 - row * PITCH
        pins.append(f'''(pin passive line (at {x} {y} {angle}) (length 2.54)
          (name {q(number)} (effects (font (size 0.8 0.8))))
          (number {q(number)} (effects (font (size 0.8 0.8)))))''')
    prefix = LIB + ':' if embedded else ''
    return f'''(symbol {q(prefix + name)} (pin_names (offset 0.6) hide)
      (in_bom yes) (on_board yes)
      (property "Reference" {q(d['ref'].rstrip('0123456789'))} (at 0 {half + 2} 0)
        (effects (font (size 1 1))))
      (property "Value" {q(name)} (at 0 {-half - 2} 0)
        (effects (font (size 1 1))))
      (property "Footprint" {q(LIB + ':' + d['footprint'])} (at 0 0 0)
        (effects (font (size 1 1)) hide))
      (symbol {q(name + '_0_1')}
        (rectangle (start -5.08 {half}) (end 5.08 {-half})
          (stroke (width 0.254) (type default)) (fill (type background))))
      (symbol {q(name + '_1_1')} {' '.join(pins)}))'''


def write_schematic():
    root_id = uid('schematic')
    items = []
    # Readable inventory arranged in four columns. Main headers, duplicates,
    # long digital headers and auxiliary lands occupy distinct groups.
    places = {}
    for i in range(6):
        places[f'J{i+1}'] = (54, 48 + i * 35)
        places[f'J{i+10}'] = (151, 48 + i * 35)
    places.update({'J7': (251, 66), 'J8': (351, 66), 'J9': (251, 112),
                   'TP1': (260, 170), 'SW1': (350, 119),
                   'D1': (350, 150), 'D2': (350, 178),
                   'PG1': (350, 224),
                   'R1': (235, 218), 'R2': (285, 218), 'R3': (235, 239)})
    for d in devices:
        cx, cy = [round(v / 1.27) * 1.27 for v in places[d['ref']]]
        rows = (len(d['numbers']) + d['columns'] - 1) // d['columns']
        half = (rows + 1) * PITCH / 2
        instance = uid(d['ref'])
        items.append(f'''(symbol (lib_id {q(LIB + ':' + d['ref'] + '_contacts')})
          (at {cx} {cy} 0) (unit 1) (in_bom yes) (on_board yes) (dnp {'yes' if d.get('dnp') else 'no'})
          (uuid {q(instance)})
          (property "Reference" {q(d['ref'])} (at {cx} {cy-half-4.5} 0)
            (effects (font (size 1.1 1.1))))
          (property "Value" {q(d['value'])} (at {cx} {cy-half-1.8} 0)
            (effects (font (size 0.75 0.75))))
          (property "Footprint" {q(LIB + ':' + d['footprint'])} (at {cx} {cy} 0)
            (effects (font (size 1 1)) hide))
          (instances (project {q(NAME)}
            (path {q('/' + root_id)} (reference {q(d['ref'])}) (unit 1)))))''')
        for i, (number, net) in enumerate(zip(d['numbers'], d['nets'])):
            row, side = (i, 0) if d['columns'] == 1 else divmod(i, 2)
            y = cy - ((rows - 1) * PITCH / 2 - row * PITCH)
            x = cx + (-7.62 if side == 0 else 7.62)
            ex = x + (-2.54 if side == 0 else 2.54)
            items.append(f'''(wire (pts (xy {x} {y}) (xy {ex} {y}))
              (stroke (width 0) (type default)) (uuid {q(uid(d['ref'] + number + 'wire'))}))''')
            justify = 'right' if side == 0 else 'left'
            items.append(f'''(label {q(net)} (at {ex} {y} 0)
              (effects (font (size 0.85 0.85)) (justify {justify} bottom))
              (uuid {q(uid(d['ref'] + number + 'label'))}))''')
    notes = [
        (15, 15, 'PHOTO-DERIVED CARRIER / contact inventory / KiCad 10'),
        (15, 22, 'P3.5: stripped-board photos resolve switch/corner routes; parallel header rows are 4.064 mm apart.'),
        (15, 27, 'Open copper ends stop at occlusions. User.3/front and User.4/back preserve fragments without known contacts.'),
        (15, 255, 'TP1 is EMPTY: T01-T14 and B01-B14 identify left-to-right top and bottom pad rows, not IC pin numbers.'),
        (15, 261, 'PG1 shows the 28 fanout contacts; 313 other grid holes have no assigned net. R01/C01 start at the top left.'),
        (15, 267, 'Main header labels use Due names. Mega A12/A13/A14/A15 become DAC0/DAC1/CANRX0/CANTX0.'),
        (15, 273, 'Check mechanical fit, power isolation and continuity.csv before using this model to plan powered assembly.'),
    ]
    for x, y, note in notes:
        items.append(f'''(text {q(note)} (at {x} {y} 0)
          (effects (font (size 1.1 1.1)) (justify left bottom))
          (uuid {q(uid(note))}))''')
    libraries = '\n'.join(symbol_definition(d, True) for d in devices)
    text = f'''(kicad_sch (version 20250114) (generator "eeschema")
      (uuid {q(root_id)}) (paper "A3")
      (title_block (title "Mega PrototypeShield V3: photo-derived carrier")
        (rev "P3.5")
        (comment 1 "Visual trace inventory. Obscured contacts unassigned; meter confirmation pending."))
      (lib_symbols {libraries}) {' '.join(items)} (embedded_fonts no))\n'''
    (ROOT / f'{NAME}.kicad_sch').write_text(text)
    symbols = '\n'.join(symbol_definition(d) for d in devices)
    (ROOT / 'Carrier.kicad_sym').write_text(
        f'(kicad_symbol_lib (version 20250114) (generator "kicad_symbol_editor") {symbols})\n')


def add_text(board, text, x, y, layer=pcb.User_1, size=0.8, angle=0):
    item = pcb.PCB_TEXT(board)
    item.SetText(text)
    item.SetPosition(local(x, y))
    item.SetLayer(layer)
    item.SetTextSize(mm(size, size))
    item.SetTextThickness(pcb.FromMM(0.12))
    item.SetTextAngle(pcb.EDA_ANGLE(angle, pcb.DEGREES_T))
    board.Add(item)


def build():
    if not pcb.Version().startswith('10.'):
        raise SystemExit('Use KiCad 10.x Python.')
    (ROOT / 'Carrier.pretty').mkdir(exist_ok=True)
    for n in (6, 8):
        make_footprint(f'Header_1x{n:02}', row_points(n))
    for n in (18, 20):
        make_footprint(f'Header_2x{n}', dual_points(n))
    make_footprint('Corner_3x02', [(str(i + 1), (i // 2) * PITCH, (i % 2) * PITCH) for i in range(6)])
    smd_points = [(f'{side}{i+1:02}', i * 1.27, y)
                  for side, y in [('T', 0), ('B', 9.525)] for i in range(14)]
    make_footprint('Empty_SMD28', smd_points, 'smd', (-0.6, 1.1, 17.1, 8.4))
    make_footprint('Switch_6mm_estimate', [('1', -3.25, -2.25), ('2', 3.25, -2.25),
                                        ('3', -3.25, 2.25), ('4', 3.25, 2.25)],
                   body=(-3, -3, 3, 3))
    make_footprint('Passive_estimate', [('1', -1, 0), ('2', 1, 0)], 'passive', (-1, -0.65, 1, 0.65))
    make_footprint('LED_estimate', [('1', -0.775, 0), ('2', 0.775, 0)], 'passive', (-0.8, -0.65, 0.8, 0.65))
    grid = [(f'R{r:02}C{c:02}', (c - 1) * PITCH, (r - 1) * PITCH)
            for r in range(1, 16) for c in grid_columns(r)]
    make_footprint('Grid_32x15_irregular', grid)
    make_footprint('Hole_estimate_1.6mm', [('', 0, 0)], 'hole')
    board = pcb.BOARD()
    board.SetCopperLayerCount(2)
    title = board.GetTitleBlock()
    title.SetTitle('103 x 55 mm Mega PrototypeShield V3 - photo-derived carrier')
    title.SetRevision('P3.5 - GROUND ROUTE SOCKET CLEARANCE CORRECTED')
    nets = {}
    records = []
    root_id = uid('schematic')
    for d in devices:
        f = pcb.FootprintLoad(str(ROOT / 'Carrier.pretty'), d['footprint'])
        f.SetFPID(pcb.LIB_ID(LIB, d['footprint']))
        f.SetReference(d['ref'])
        f.SetValue(d['value'])
        f.SetPosition(local(d['x'], d['y']))
        path = pcb.KIID_PATH()
        path.push_back(pcb.KIID(root_id))
        path.push_back(pcb.KIID(uid(d['ref'])))
        f.SetPath(path)
        f.SetLocked(True)
        f.SetDNP(d.get('dnp', False))
        if d['ref'] == 'PG1':
            f.SetExcludedFromBOM(True)
            f.SetExcludedFromPosFiles(True)
        f.Reference().SetVisible(False)
        f.Value().SetVisible(False)
        board.Add(f)
        bynumber = {p.GetNumber(): p for p in f.Pads()}
        for number, net in zip(d['numbers'], d['nets']):
            if net not in nets:
                nets[net] = pcb.NETINFO_ITEM(board, '/' + net)
                board.Add(nets[net])
            pad = bynumber[number]
            pad.SetNet(nets[net])
            x = pcb.ToMM(pad.GetPosition().x) - ORIGIN[0]
            y = pcb.ToMM(pad.GetPosition().y) - ORIGIN[1]
            connected = {r[k] for r in supplemental['routes'] for k in ('a', 'b') if r[k]}
            status = ('photo-traced connection; meter verification pending'
                      if d['ref'] in ('PG1', 'TP1') or d['ref'] + '.' + number in connected else
                      'photo geometry; contact identity only; hidden links unassigned')
            records.append([d['ref'], number, net, round(x, 4), round(y, 4), status])
        if d['ref'] == 'PG1':
            for pad in f.Pads():
                if pad.GetNumber() not in d['numbers']:
                    records.append(['PG1', pad.GetNumber(), '',
                                    round(pcb.ToMM(pad.GetPosition().x) - ORIGIN[0], 4),
                                    round(pcb.ToMM(pad.GetPosition().y) - ORIGIN[1], 4),
                                    'pad visible; isolation / hidden connections unverified'])
        label_y = d['y'] - 1.3
        add_text(board, d['ref'], d['x'], max(0.6, label_y), pcb.User_2, 0.8)
    for ref, name, x, y in [('H1', 'Hole_estimate_1.6mm', 15.4, 4.0),
                            ('H2', 'Hole_estimate_1.6mm', 91.9, 50.5)]:
        f = pcb.FootprintLoad(str(ROOT / 'Carrier.pretty'), name)
        f.SetFPID(pcb.LIB_ID(LIB, name))
        f.SetReference(ref)
        f.SetValue(name)
        f.SetPosition(local(x, y))
        f.SetBoardOnly(True)
        f.SetExcludedFromBOM(True)
        f.SetExcludedFromPosFiles(True)
        f.SetLocked(True)
        f.Reference().SetVisible(False)
        f.Value().SetVisible(False)
        board.Add(f)
    fp_by_ref = {f.GetReference(): f for f in board.GetFootprints()}
    land_pads = {p.GetNumber(): p for p in fp_by_ref['TP1'].Pads()}
    grid_pads = {p.GetNumber(): p for p in fp_by_ref['PG1'].Pads()}
    for link in fanout_links:
        # Preserve the observed topology; geometric waypoints and 0.2 mm
        # width are estimates, not recovered photoplot/manufacturing data.
        n = int(link['land'][1:])
        sx = 4.9 + (n - 1) * 1.27
        sy = 21.5 if link['land'][0] == 'T' else 31.025
        gx = GRID_X + (link['column'] - 1) * PITCH
        gy = GRID_Y + (link['row'] - 1) * PITCH
        if link['land'][0] == 'T':
            if n % 2:
                points = [(gx, gy), (gx, 19.52), (sx, 20.54), (sx, sy)]
            else:
                points = [(gx, gy), (gx + 1.27, 17.19), (gx + 1.27, 19.72),
                          (sx, 20.74), (sx, sy)]
        elif n % 2:
            points = [(sx, sy), (sx, 31.8), (gx, 32.82), (gx, gy)]
        else:
            points = [(sx, sy), (sx, 31.5), (gx + 1.27, 32.52),
                      (gx + 1.27, 35.0), (gx, gy)]
        terminal_pads = [grid_pads[link['grid']], land_pads[link['land']]]
        if link['land'][0] == 'B':
            terminal_pads.reverse()
        for i, (start, end) in enumerate(zip(points, points[1:])):
            track = pcb.PCB_TRACK(board)
            track.SetStart(terminal_pads[0].GetPosition() if i == 0 else local(*start))
            track.SetEnd(terminal_pads[1].GetPosition() if i == len(points) - 2 else local(*end))
            track.SetLayer(pcb.F_Cu)
            track.SetWidth(pcb.FromMM(0.2))
            track.SetNet(nets[link['net']])
            board.Add(track)
    # Supplemental copper includes every identifiable visible route, with
    # explicit open ends at occlusions rather than guessed hidden joins.
    via_positions = {}
    for item in supplemental['vias']:
        if item['net'] not in nets:
            nets[item['net']] = pcb.NETINFO_ITEM(board, '/' + item['net'])
            board.Add(nets[item['net']])
        via = pcb.PCB_VIA(board)
        via.SetPosition(local(*item['at']))
        via.SetViaType(pcb.VIATYPE_THROUGH)
        via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
        via.SetWidth(pcb.FromMM(0.65))
        via.SetDrill(pcb.FromMM(0.3))
        via.SetNet(nets[item['net']])
        board.Add(via)
        via_positions[item['id']] = via.GetPosition()
    pads = {f.GetReference() + '.' + p.GetNumber(): p
            for f in board.GetFootprints() for p in f.Pads()}

    def position(contact):
        return via_positions[contact] if contact in via_positions else pads[contact].GetPosition()

    open_end_number = 0
    for route in supplemental['routes']:
        points = [local(*p) for p in route['points']]
        if route['a']:
            points.insert(0, position(route['a']))
        if route['b']:
            points.append(position(route['b']))
        route['model_polyline_mm'] = [
            [round(pcb.ToMM(p.x) - ORIGIN[0], 6), round(pcb.ToMM(p.y) - ORIGIN[1], 6)]
            for p in points]
        for start, end in zip(points, points[1:]):
            if start == end:
                continue
            track = pcb.PCB_TRACK(board)
            track.SetStart(start)
            track.SetEnd(end)
            track.SetLayer(pcb.F_Cu if route['layer'] == 'F.Cu' else pcb.B_Cu)
            track.SetWidth(pcb.FromMM(0.2))
            track.SetNet(nets[route['net']])
            board.Add(track)
        if route['a'] is None or route['b'] is None:
            tip = points[0] if route['a'] is None else points[-1]
            x, y = pcb.ToMM(tip.x) - ORIGIN[0], pcb.ToMM(tip.y) - ORIGIN[1]
            open_end_number += 1
            route['open_end_marker'] = f'O{open_end_number:02}'
            layer = pcb.User_3 if route['layer'] == 'F.Cu' else pcb.User_4
            add_text(board, route['open_end_marker'], x + 0.8, y + 0.7, layer, 0.45)
    for fragment in supplemental['fragments']:
        layer = pcb.User_3 if fragment['side'] == 'front' else pcb.User_4
        for start, end in zip(fragment['points'], fragment['points'][1:]):
            graphic = pcb.PCB_SHAPE(board)
            graphic.SetShape(pcb.SHAPE_T_SEGMENT)
            graphic.SetStart(local(*start))
            graphic.SetEnd(local(*end))
            graphic.SetWidth(pcb.FromMM(0.25))
            graphic.SetLayer(layer)
            board.Add(graphic)
        x, y = fragment['points'][0]
        add_text(board, fragment['id'], x + 1.8, y, layer, 0.65)
    for a, b in [((0, 0), (WIDTH, 0)), ((WIDTH, 0), (WIDTH, HEIGHT)),
                 ((WIDTH, HEIGHT), (0, HEIGHT)), ((0, HEIGHT), (0, 0))]:
        line = pcb.PCB_SHAPE(board)
        line.SetShape(pcb.SHAPE_T_SEGMENT)
        line.SetStart(local(*a))
        line.SetEnd(local(*b))
        line.SetWidth(pcb.FromMM(0.05))
        line.SetLayer(pcb.Edge_Cuts)
        board.Add(line)
    for c in range(1, 33):
        add_text(board, str(c), GRID_X + (c - 1) * PITCH, 7.0, size=0.7)
    for r in range(1, 16):
        add_text(board, f'R{r:02}', 1.7, GRID_Y + (r - 1) * PITCH, size=0.65)
    # Due names alongside the two analog rows avoid Mega A12-A15 ambiguity.
    for ref in ('J5', 'J6'):
        d = next(d for d in devices if d['ref'] == ref)
        for i, net in enumerate(d['nets']):
            add_text(board, net[4:], d['x'] + i * PITCH, 46.8, pcb.User_2, 0.65, 90)
    for text, x, y in [
        ('PHOTO MODEL P3.5 / 103 x 55 mm / top view', 51.5, -7),
        ('Both-face trace inventory / owner-confirmed ground endpoint / geometry provisional', 51.5, -4.5),
        ('EMPTY 28-land breakout', 13.8, 26.5),
        ('No installed AFE parts observed', 51.5, 59),
        ('User.1 grid / User.2 labels / User.3 front fragments / User.4 back fragments', 51.5, 61.5),
    ]:
        add_text(board, text, x, y, pcb.User_2, 1.0)
    attach_models(board)
    add_review_layer(board)
    save_review_board(board, ROOT / f'{NAME}.kicad_pcb')
    write_schematic()
    (ROOT / 'fp-lib-table').write_text(
        '(fp_lib_table (version 7) (lib (name "Carrier") (type "KiCad") '
        '(uri "${KIPRJMOD}/Carrier.pretty") (options "") (descr "Photo-derived carrier footprints")))\n')
    (ROOT / 'sym-lib-table').write_text(
        '(sym_lib_table (version 7) (lib (name "Carrier") (type "KiCad") '
        '(uri "${KIPRJMOD}/Carrier.kicad_sym") (options "") (descr "Carrier contact inventory")))\n')
    # Keep the user's saved display, 3D and project preferences on rebuild.
    project_path = ROOT / f'{NAME}.kicad_pro'
    if not project_path.exists():
        project_path.write_text(json.dumps({
            'meta': {'filename': NAME + '.kicad_pro', 'version': 1},
            'text_variables': {'MODEL_STATUS': 'PHOTO RECONSTRUCTION - CHECK FIT AND CONTINUITY'},
            'net_settings': {'classes': [{'name': 'Default', 'clearance': 0.2,
                                        'track_width': 0.25, 'via_diameter': 0.6,
                                        'via_drill': 0.3}], 'meta': {'version': 3}},
        }, indent=2) + '\n')
    with (ROOT / 'pad-map.csv').open('w', newline='') as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(['reference', 'pad', 'net_identity', 'board_x_mm', 'board_y_mm', 'evidence'])
        writer.writerows(sorted(records))
    evidence = []
    for name in [f'IMG_{i}.jpeg' for i in range(2131, 2142)]:
        relative = '../afe-shield/' + name if int(name[4:8]) < 2135 else 'photo/' + name
        p = ROOT / relative
        evidence.append({'path': relative,
                         'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    (ROOT / 'model-evidence.json').write_text(json.dumps({
        'revision': 'P3.5', 'date': '2026-10-30', 'kicad_version': pcb.Version(),
        'outline_mm': {'length': WIDTH, 'width': HEIGHT, 'evidence': 'owner measurement'},
        'photos': evidence, 'grid_rows': 15, 'grid_columns_max': 32, 'grid_pads': len(grid),
        'registration': 'estimated from photos and nominal Due header positions; fit not verified',
        'digital_header_alignment': {
            'source': 'IMG_2135.jpeg / IMG_2138.jpeg exposed upper-right pads; supersedes P2.1',
            'J7_J8_first_row_y_mm': digital_y,
            'J7_J8_second_row_y_mm': digital_y + PITCH,
            'first_row_aligned_to': 'J12 breakout row',
            'main_J3_y_mm': next(d['y'] for d in devices if d['ref'] == 'J3'),
            'parallel_header_row_gap_mm': HEADER_ROW_GAP,
            'J3_relation': 'between D22/D23 and D24/D25, not aligned with either',
        },
        'model_represents': 'Normal populated carrier; stripped/cracked specimen is routing evidence only',
        'assembly': {d['ref']: d['assembly'] for d in devices if d.get('assembly')},
        'photo_specimen': {
            'purpose': 'Parts removed solely to expose copper for backlit routing photographs',
            'components': {d['ref']: d['photo_specimen'] for d in devices if d.get('photo_specimen')},
            'crack_near_J9': 'Confirmed on the photo specimen; other boards not assessed for this damage',
        },
        'photo_registration': 'photo-registration.json; manual projective landmarks, not measured fit',
        'owner_observations': json.loads((ROOT / 'owner-observations.json').read_text()),
        'hole_and_pad_sizes': 'estimates, not manufacturing dimensions',
        'visually_traced_fanout_connections': len(fanout_links),
        'copper_track_segments': sum(not isinstance(t, pcb.PCB_VIA) for t in board.GetTracks()),
        'supplemental_copper_routes': len(supplemental['routes']),
        'unclassified_fragments': len(supplemental['fragments']),
        'observed_via_features': len(supplemental['vias']),
        'trace_geometry': 'Both backlit faces interpreted; widths, exact bends, via drill sizes and hidden contacts remain provisional',
        'authoritative_for': 'physical inventory and placement planning only',
    }, indent=2) + '\n')
    (ROOT / 'wiring-evidence.json').write_text(json.dumps({
        'revision': 'P3.5', 'connections': fanout_links,
        'copper_routes': supplemental['routes'],
        'unclassified_fragments': supplemental['fragments'],
        'observed_vias': supplemental['vias'],
        'verification': 'Visual interpretation only. No physical continuity measurements supplied.',
    }, indent=2) + '\n')
    print(f'Created {NAME}: {len(devices)} schematic items, {len(grid)} grid pads; '
          f'{len(fanout_links)} SMD fanouts, {len(supplemental["routes"])} supplemental '
          f'routes, {len(supplemental["fragments"])} unclassified visible fragments.')


if __name__ == '__main__':
    build()
