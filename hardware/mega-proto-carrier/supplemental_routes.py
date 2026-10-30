"""P3 trace inventory including stripped-board photos, in top-view board mm.

An occluded contact is never equated with a particular hidden connector pin.
Closed routes have named terminals; open copper ends have an explicit reason.
Unclassified fragments remain on User.3 (front) / User.4 (back), not a net.
"""


def reconstruct(devices):
    byref = {d['ref']: d for d in devices}
    digital_y = byref['J7']['y']
    last_breakout_y = byref['J8']['y'] + 19 * 2.54
    routes = []
    fragments = []
    vias = [
        dict(id='V50', at=[85.9, 43.0], net='DUE_D50', source='IMG_2138/2141: lower SPI transition'),
        dict(id='V51', at=[87.2, 36.75], net='DUE_D51', source='IMG_2138/2141: upper SPI transition'),
        dict(id='VSTAT', at=[14.7, 53.82], net='DUE_D13', source='IMG_2136/2140: STAT resistor return'),
        dict(id='VLED', at=[2.5, 51.14], net='LED_COMMON', source='IMG_2136/2140: common LED rail spur'),
        dict(id='VCORNER', at=[9.3, 4.3], net='LED_COMMON', source='IMG_2137/2139: corner ground transition'),
    ]

    def add(id, a, b, layer, points=(), note='', evidence='IMG_2135.jpeg - IMG_2141.jpeg; earlier IMG_2133/2134'):
        routes.append(dict(id=id, a=a, b=b, layer=layer, points=list(points),
                           note=note, evidence=evidence,
                           status='visually_traced_not_meter_verified'))

    def fragment(id, side, points, description):
        fragments.append(dict(id=id, side=side, points=list(points), description=description,
                              evidence='IMG_2134.jpeg' if side == 'front' else 'IMG_2133.jpeg',
                              status='visible_path_hidden_contact_unassigned'))

    # One-to-one spokes between the six paired header rows. Function names
    # come from the photographed printing; meter verification remains pending.
    for j, n in ((1, 8), (2, 8), (3, 8), (4, 6), (5, 8), (6, 8)):
        for pin in range(1, n + 1):
            add(f'H{j}-{pin:02}', f'J{j}.{pin}', f'J{j+9}.{pin}', 'F.Cu',
                note='Visible short spoke between corresponding header/breakout contacts.')

    # 16 digital pairs: front fans out to the inner bare column, back to
    # the outer bare column. The lane detours preserve pad clearances in
    # the provisional geometry rather than running through another contact.
    for r in range(1, 17):
        y = digital_y + r * 2.54
        odd, even = 2 * r + 1, 2 * r + 2
        add(f'D{22+2*(r-1)}', f'J7.{odd}', f'J8.{odd}', 'F.Cu',
            [(byref['J7']['x'] + 1.27, y + 1.27), (byref['J8']['x'] - 1.27, y + 1.27)],
            'Front dogleg to corresponding inner-column digital breakout.')
        add(f'D{23+2*(r-1)}', f'J7.{even}', f'J8.{even}', 'B.Cu',
            [(byref['J7']['x'] + 3.81, y - 1.27), (byref['J8']['x'] + 1.27, y - 1.27)],
            'Back dogleg to corresponding outer-column digital breakout.')

    for id, a, b in [
        ('5V-TOP-1', 'J7.1', 'J7.2'), ('5V-TOP-2', 'J7.2', 'J8.1'),
        ('5V-TOP-3', 'J8.1', 'J8.2'),
        ('GND-DIG-1', 'J7.35', 'J7.36'), ('GND-DIG-2', 'J7.36', 'J8.35'),
        ('GND-DIG-3', 'J8.35', 'J8.36'), ('GND-DIG-4', 'J8.36', 'J8.38'),
        ('GND-DIG-5', 'J8.38', 'J8.37'),
    ]:
        add(id, a, b, 'F.Cu', note='Visible power/ground crossbar at the ends of the digital field.')
    add('5V-BOTTOM', 'J8.39', 'J8.40', 'B.Cu',
        note='Bottom 5V pair is joined on BACK copper only; remove the incorrect front bar.',
        evidence='IMG_2138.jpeg: no front bar; IMG_2141.jpeg: visible back bar')
    add('5V-PERIMETER', 'J13.3', 'J8.39', 'B.Cu',
        [(35.8, 48.2), (94.4, 48.2)],
        'Back lower-edge +5V feed from power-header breakout to the left contact of the bottom 5V pair.',
        evidence='IMG_2140.jpeg: power-header +5V departure; IMG_2141.jpeg: back lower-edge arrival')
    add('5V-EDGE', 'J8.2', 'J8.40', 'B.Cu',
        [(100.5, digital_y + 1.8), (100.5, last_breakout_y - 2.04)],
        'Back-side outer-edge supply return, joining the top and bottom 5V pairs.')
    # Owner review: keep the perimeter away from the parallel socket pads.
    # Leave J13.4 vertically, chamfer into a lane 1 mm farther from them,
    # then use a 45-degree approach to the digital ground contact.
    ground_lane_y = 47.2
    ground_start_x = byref['J13']['x'] + 3 * 2.54
    ground_end_y = digital_y + 17 * 2.54
    add('GND-PERIMETER', 'J13.4', 'J7.35', 'F.Cu',
        [(ground_start_x, ground_lane_y + 0.5), (ground_start_x + 0.5, ground_lane_y),
         (byref['J7']['x'] - (ground_lane_y - ground_end_y), ground_lane_y)],
        'Owner-corrected ground route: horizontal lane moved 1 mm away from socket row; vertical departure from J13.4 and 45-degree arrival at J7.35.',
        evidence='Owner socket-clearance correction, 2026-10-30; IMG_2135/2138 placement reference')
    routes[-1]['status'] = 'owner_corrected_geometry_not_meter_verified'

    # Removed J9 plastic resolves all three starts directly (IMG_2137).
    # Pad numbers are model coordinates, not a standard ISP pin convention.
    add('SPI50-F', 'J9.2', 'V50', 'F.Cu',
        [(2.0, 11.5), (2.6, 12.1), (83.6, 12.1),
         (84.9, 13.4), (84.9, 42.0)],
        'Exposed bottom-left corner pad -> lower long path -> D50 transition.')
    d50_y = digital_y + 15 * 2.54
    lane_above_d50 = d50_y - 1.27
    # Canonical coordinates are top view. The owner is checking the flipped
    # B.Cu view: its right edge is the pad's left edge in these coordinates.
    # Keep a 45-degree run from V50, then enter the pad horizontally at mid-height.
    v50_x, v50_y = next(v['at'] for v in vias if v['id'] == 'V50')
    add('SPI50-B', 'V50', 'J7.31', 'B.Cu', [(v50_x + v50_y - d50_y, d50_y)],
        'Owner-corrected D50 approach: horizontal into the middle-right of J7.31 in flipped B.Cu view (left in canonical top view).',
        evidence='Owner geometry correction, 2026-10-30; IMG_2141.jpeg reverse-side route')
    routes[-1]['status'] = 'owner_corrected_geometry_not_meter_verified'
    add('SPI51-F', 'J9.3', 'V51', 'F.Cu',
        [(5.8, 3.1), (5.8, 5.3), (7.0, 6.5), (17.0, 6.5), (19.0, 8.5),
         (85.9, 8.5), (87.2, 9.8)],
        'Exposed top-middle corner pad -> upper long path -> D51 transition.')
    add('SPI51-B', 'V51', 'J7.32', 'B.Cu',
        [(88.7, lane_above_d50), (91.71, lane_above_d50)],
        'Upper via-to-D51 continuation visible on the reverse photograph.')
    add('SPI52-F', 'J9.4', 'J7.33', 'F.Cu',
        [(4.54, 6.77), (5.07, 7.3), (5.07, 9.57), (84.8, 9.57),
         (86.1, 10.87), (86.1, 38.2)],
        'Exposed bottom-middle corner pad -> middle long path -> D52.')

    stat_x = byref['J1']['x'] + 2 * 2.54
    add('STAT-B', 'J1.3', 'VSTAT', 'B.Cu',
        [(stat_x, 42.8), (22.3, 45.89), (22.3, 49.8),
         (20.9, 51.2), (16.2, 51.2), (14.7, 52.7)],
        'D13 starts at the INNER bare contact J1.3, not outer J10.3. The J1/J10 link remains front copper only.',
        evidence='IMG_2139.jpeg: trace departs inner bare D13 pad; IMG_2140.jpeg: control-area continuation')
    add('STAT-F', 'VSTAT', 'R3.2', 'F.Cu', note='Short front spur from the STAT transition to the 102-marked resistor.')
    add('RESET-F', 'J13.1', 'SW1.2', 'F.Cu', [(28.25, 48.5)],
        'Visible front reset-header route into the upper-right switch lead.')
    add('RESET-TOP-BAR', 'SW1.1', 'SW1.2', 'F.Cu',
        note='Bare pads reveal the upper pair is permanently joined by FRONT copper.')
    add('GND-BOTTOM-BAR', 'SW1.3', 'SW1.4', 'B.Cu',
        note='Bare pads reveal the lower pair is permanently joined by BACK copper.')
    add('SW-GND-B', 'SW1.4', 'J4.4', 'B.Cu', [(26.15, 54.7), (35.9, 54.7)],
        'Corrects P2.1 RESET-B: the lower-right switch pad reaches GND, NOT reset.')
    add('POWER-GND-BAR', 'J4.4', 'J4.5', 'F.Cu',
        note='Exposed lower power row has a front copper bar between its two GND pads.')
    add('CORNER-SW-B', 'J9.6', 'SW1.1', 'B.Cu',
        [(8.32, 3.02), (10.92, 3.02), (12.69, 4.79),
         (12.69, 44.8), (16.39, 48.5)],
        'Exposed bottom-right corner pad reaches the upper-left RESET pad on the back.')

    # The light sources have two horizontal lands; pin 1 means left land,
    # not a measured LED anode/cathode identity.
    add('PWR-SERIES', 'D1.2', 'R2.1', 'F.Cu', [(7.2, 48.9), (8.8, 50.5)],
        'Visible PWR LED / 102 resistor series connection; LED polarity unassigned.')
    add('STAT-SERIES', 'D2.2', 'R3.1', 'F.Cu',
        note='Visible STAT LED / 102 resistor series connection; LED polarity unassigned.')
    add('LED-COMMON', 'D1.1', 'D2.1', 'F.Cu',
        note='Visible common left-hand LED rail, now traced to ground through the exposed lower switch pads.')
    add('LED-SPUR', 'D1.1', 'VLED', 'F.Cu', [(4.275, 51.14)],
        'Via/spur visible at the common LED rail.')
    add('PULLUP-LEFT', 'R1.1', 'J9.1', 'F.Cu',
        [(8.4, 45.9), (2.3, 45.9), (0.7, 44.3), (0.7, 3.1)],
        '103 resistor left land reaches corner pad 1; the newly traced R1/R2 link establishes +5V.')
    add('R1-R2-SUPPLY', 'R1.1', 'R2.2', 'F.Cu', [(9.9, 48.5)],
        'Front trace leaves the LEFT pad of R1 downward, then diagonally reaches the RIGHT pad of R2 / +5V.',
        evidence='IMG_2136.jpeg: exposed R1-left to R2-right diagonal trace')
    add('PULLUP-RIGHT', 'R1.2', 'SW1.1', 'F.Cu', [(16.85, 47.4)],
        'Exposed 103 resistor right land joins upper-left RESET pad.')
    add('PWR-RES-RIGHT', 'R2.2', 'J4.3', 'F.Cu',
        [(25.4, 50.5), (27.5, 52.6), (27.5, 54.7), (33.36, 54.7)],
        'Exposed middle 102 resistor feed bypasses the switch and reaches +5V, power-header pin 3.')
    add('LED-COMMON-RIGHT', 'D1.1', 'SW1.3', 'F.Cu',
        [(4.275, 52.1), (17.05, 52.1)],
        'Resolves UF-01: common LED rail reaches the exposed lower-left ground pad.')
    add('CORNER-GND-F', 'J9.5', 'VCORNER', 'F.Cu', [(8.0, 1.8), (9.3, 3.1)],
        'Exposed top-right corner pad joins the rounded front transition feature.')
    add('CORNER-GND-B', 'VCORNER', 'VLED', 'B.Cu',
        [(9.3, 5.5), (8.3, 6.5), (2.4, 6.5), (1.4, 7.5), (1.4, 50.04)],
        'Resolves UB-02: paired rounded features connect corner ground to LED ground along the back left edge.')
    add('CORNER-HEADER-B', 'J9.5', 'J10.2', 'B.Cu',
        [(17.8, 1.8), (19.3, 0.3), (21.716, 0.3)],
        'Owner confirmed J10.2 / GND as the endpoint. Final bends beneath plastic are estimated; route passes above AREF without joining it.',
        evidence='IMG_2139.jpeg plus owner endpoint confirmation, 2026-10-30')
    routes[-1]['status'] = 'owner_confirmed_endpoint_geometry_estimated'
    routes[-1]['measurement'] = 'No resistance value supplied; endpoint confirmation is not a meter reading.'

    # Union only routes whose two known terminals establish a connection.
    # Via names act as observed transition nodes, not additional components.
    parents = {}

    def find(s):
        parents.setdefault(s, s)
        if parents[s] != s:
            parents[s] = find(parents[s])
        return parents[s]

    def union(a, b):
        parents[find(b)] = find(a)

    labels = {}
    for d in devices:
        for n, net in zip(d['numbers'], d['nets']):
            contact = d['ref'] + '.' + n
            find(contact)
            labels[contact] = net
    for via in vias:
        find(via['id'])
        labels[via['id']] = via['net']
    # Preserve existing same-net identifications, including the 28 fanouts.
    first_by_net = {}
    for contact, net in labels.items():
        if net in first_by_net:
            union(first_by_net[net], contact)
        else:
            first_by_net[net] = contact
    for route in routes:
        if route['a'] and route['b']:
            union(route['a'], route['b'])
    groups = {}
    for contact, net in labels.items():
        groups.setdefault(find(contact), set()).add(net)

    def choose(names):
        preferred = sorted(n for n in names if n.startswith('DUE_'))
        if len(preferred) > 1:
            raise ValueError(f'Photo interpretation shorts named Due nets: {preferred}')
        if preferred:
            return preferred[0]
        if 'LED_COMMON' in names:
            return 'LED_COMMON'
        return sorted(names)[0]

    canonical = {key: choose(names) for key, names in groups.items()}
    for d in devices:
        d['nets'] = [canonical[find(d['ref'] + '.' + n)] for n in d['numbers']]
        if d['ref'] in {f'J{n}' for n in range(10, 16)}:
            d['value'] = d['value'].replace('(verify links)', '(visually linked)')
        if d['ref'] == 'J8':
            d['value'] = 'Outer 2x20 digital/power field (visually linked)'
    for via in vias:
        via['net'] = canonical[find(via['id'])]
    for route in routes:
        route['net'] = canonical[find(route['a'] or route['b'])]
        if route['a'] is None or route['b'] is None:
            route['status'] = 'visible_copper_with_occluded_terminal'
    return dict(routes=routes, fragments=fragments, vias=vias)
