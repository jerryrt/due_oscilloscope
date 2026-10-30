#!/usr/bin/env python3
"""Visible review questions on User.5; never changes copper or pad nets."""
import csv
import json
from pathlib import Path

import pcbnew as pcb

ROOT = Path(__file__).resolve().parent
OFFSET = 80.0
GROUP = 'Carrier review questions R2'
LAYER = pcb.User_5


def target(id, at, source, side='either'):
    return dict(id=id, at=list(at), source=source, side=side)


QUESTIONS = [{'id': 'Q01',
  'title': 'Corner contacts now exposed',
  'question': 'PHOTO RESOLVED: J9 1=+5V, 2=D50, 3=D51, 4=D52, 5=GND, 6=RESET. '
              'Pad 1 reaches +5V through the R1-left / R2-right copper link. Confirm by meter.',
  'sources': ['J9.2 / SPI50-F',
              'J9.3 / SPI51-F',
              'J9.4 / SPI52-F',
              'J9.6 / CORNER-SW-B',
              'J9.1 / +5V via R1-R2-SUPPLY'],
  'targets': [{'id': 'A', 'at': [2, 4.34], 'source': 'J9.2 / SPI50-F', 'side': 'front'},
              {'id': 'B', 'at': [4.54, 1.8], 'source': 'J9.3 / SPI51-F', 'side': 'front'},
              {'id': 'C', 'at': [4.54, 4.34], 'source': 'J9.4 / SPI52-F', 'side': 'front'},
              {'id': 'D', 'at': [7.08, 4.34], 'source': 'J9.6 / CORNER-SW-B', 'side': 'back'},
              {'id': 'E', 'at': [2, 1.8], 'source': 'J9.1 / +5V via R1-R2-SUPPLY', 'side': 'front'}]},
 {'id': 'Q02',
  'title': 'Confirmed: J9 to J10 ground',
  'question': 'OWNER CONFIRMED: J9.5 reaches J10.2 / GND. The trace bypasses AREF. '
              'Bends under plastic are estimated; no resistance value was supplied.',
  'sources': ['J9.5 / CORNER-HEADER-B', 'J10.2 / GND (owner confirmed)'],
  'targets': [{'id': 'A', 'at': [7.08, 1.8], 'source': 'J9.5 / CORNER-HEADER-B', 'side': 'back'},
              {'id': 'B', 'at': [22.876, 1.46], 'source': 'J10.2 / GND (owner confirmed)', 'side': 'back'}]},
 {'id': 'Q03',
  'title': 'Back: long left-edge ground',
  'question': 'PHOTO RESOLVED: A/B join corner GND to LED GND along the back edge. Confirm continuity and '
              'via details.',
  'sources': ['VCORNER / CORNER-GND-B', 'VLED / CORNER-GND-B'],
  'targets': [{'id': 'A', 'at': [9.3, 4.3], 'source': 'VCORNER / CORNER-GND-B', 'side': 'back'},
              {'id': 'B', 'at': [2.5, 51.14], 'source': 'VLED / CORNER-GND-B', 'side': 'back'}]},
 {'id': 'Q04',
  'title': 'Complete D13 / STAT return',
  'question': 'PHOTO RESOLVED: back D13 trace starts at inner J1.3, not outer J10.3, then reaches R3 right. '
              'The J1/J10 pair is linked on the front. Confirm by meter.',
  'sources': ['STAT-B upper dogleg', 'STAT-B lower dogleg', 'VSTAT'],
  'targets': [{'id': 'A', 'at': [22.3, 49.8], 'source': 'STAT-B upper dogleg', 'side': 'back'},
              {'id': 'B', 'at': [20.9, 51.2], 'source': 'STAT-B lower dogleg', 'side': 'back'},
              {'id': 'C', 'at': [14.7, 53.82], 'source': 'VSTAT', 'side': 'either'}]},
 {'id': 'Q05',
  'title': 'R1/R2: front supply link',
  'question': 'PHOTO RESOLVED: R1 left joins R2 right by a front diagonal, establishing +5V at R1 left and J9.1. '
              'R1 right remains RESET. Confirm the copper link by meter.',
  'sources': ['R1.1 left land', 'R1.2 right land', 'SW1.1 / PULLUP-RIGHT'],
  'targets': [{'id': 'A', 'at': [9.9, 47.4], 'source': 'R1.1 left land', 'side': 'front'},
              {'id': 'B', 'at': [11.9, 47.4], 'source': 'R1.2 right land', 'side': 'front'},
              {'id': 'C', 'at': [17.95, 48.5], 'source': 'SW1.1 / PULLUP-RIGHT', 'side': 'front'}]},
 {'id': 'Q06',
  'title': 'R2: middle 102 resistor',
  'question': 'PHOTO RESOLVED: R2 right reaches power-header +5V via the exposed lower dogleg. Confirm R2.2 '
              'to J4.3.',
  'sources': ['R2.2 right land', 'PWR-RES-RIGHT dogleg'],
  'targets': [{'id': 'A', 'at': [11.9, 50.5], 'source': 'R2.2 right land', 'side': 'front'},
              {'id': 'B', 'at': [27.5, 52.6], 'source': 'PWR-RES-RIGHT dogleg', 'side': 'front'}]},
 {'id': 'Q07',
  'title': 'LED common rail is ground',
  'question': 'PHOTO RESOLVED: left LED rail joins SW1.3/4 and power-header GND. Lower switch pads are NOT '
              'reset. Confirm by meter.',
  'sources': ['VLED / common-rail spur', 'LED-COMMON-RIGHT bend', 'SW1.3 / ground bar'],
  'targets': [{'id': 'A', 'at': [2.5, 51.14], 'source': 'VLED / common-rail spur', 'side': 'front'},
              {'id': 'B', 'at': [17.05, 52.1], 'source': 'LED-COMMON-RIGHT bend', 'side': 'front'},
              {'id': 'C', 'at': [17.95, 53], 'source': 'SW1.3 / ground bar', 'side': 'front'}]},
 {'id': 'Q08',
  'title': 'STAT rounded transition',
  'question': 'PHOTO RESOLVED: old UB-03 belongs to D13/STAT, now copper. Confirm the rounded VSTAT feature '
              'and its connection to R3.2.',
  'sources': ['VSTAT rounded feature', 'STAT-B former UB-03 segment'],
  'targets': [{'id': 'A', 'at': [14.7, 53.82], 'source': 'VSTAT rounded feature', 'side': 'back'},
              {'id': 'B', 'at': [16.2, 51.2], 'source': 'STAT-B former UB-03 segment', 'side': 'back'}]},
 {'id': 'Q09',
  'title': 'Photo specimen: crack near J9',
  'question': 'Crack confirmed on the stripped photo specimen. Check its marked SPI/reset routes. '
              'Other boards are not assessed for this damage.',
  'sources': ['SPI51 surface-line crossing',
              'SPI52 surface-line crossing',
              'SPI50 surface-line crossing',
              'RESET surface-line vicinity'],
  'targets': [{'id': 'A', 'at': [12.6, 6.5], 'source': 'SPI51 surface-line crossing', 'side': 'front'},
              {'id': 'B', 'at': [12.6, 9.57], 'source': 'SPI52 surface-line crossing', 'side': 'front'},
              {'id': 'C', 'at': [12.6, 12.1], 'source': 'SPI50 surface-line crossing', 'side': 'front'},
              {'id': 'D', 'at': [12.69, 5.8], 'source': 'RESET surface-line vicinity', 'side': 'back'}]},
 {'id': 'Q10',
  'title': 'LED polarity',
  'question': 'For D1/PWR and D2/STAT identify anode and cathode. Left/right are physical coordinates, not '
              'measured polarity.',
  'sources': ['D1 PWR LED', 'D2 STAT LED'],
  'targets': [{'id': 'A', 'at': [5.05, 48.9], 'source': 'D1 PWR LED', 'side': 'front'},
              {'id': 'B', 'at': [5.05, 53.9], 'source': 'D2 STAT LED', 'side': 'front'}]},
 {'id': 'Q11',
  'title': 'SPI transition vias',
  'question': 'Confirm A/V50 reaches D50 and B/V51 reaches D51. Confirm the middle long path reaches D52.',
  'sources': ['V50 / apparent D50 transition', 'V51 / apparent D51 transition'],
  'targets': [{'id': 'A', 'at': [85.9, 43], 'source': 'V50 / apparent D50 transition', 'side': 'either'},
              {'id': 'B', 'at': [87.2, 36.75], 'source': 'V51 / apparent D51 transition', 'side': 'either'}]},
 {'id': 'Q12',
  'title': 'Mechanical estimates',
  'question': 'Check hole positions, grid/header registration, 4.064 mm paired-row gap, pad/drill sizes and '
              'board thickness. Fit is photo-derived.',
  'sources': ['H1 position / diameter', 'H2 position / diameter', 'PG1.R01C01 registration'],
  'targets': [{'id': 'A', 'at': [15.4, 4], 'source': 'H1 position / diameter', 'side': 'either'},
              {'id': 'B', 'at': [91.9, 50.5], 'source': 'H2 position / diameter', 'side': 'either'},
              {'id': 'C', 'at': [3.8, 8.3], 'source': 'PG1.R01C01 registration', 'side': 'either'}]}]


def add_review_layer(board):
    # Existing review groups are stripped from the serialized input by the
    # standalone entry point; deleting SWIG group members in-place is unsafe
    # in the KiCad 10 Python binding. A fresh baseline has no such group.
    if any(g.GetName() == GROUP for g in board.Groups()):
        raise ValueError('Load input through strip_review_text before refreshing review drawings.')
    group = pcb.PCB_GROUP(board)
    group.SetName(GROUP)
    board.Add(group)

    def mm(x, y):
        return pcb.VECTOR2I(pcb.FromMM(x + OFFSET), pcb.FromMM(y + OFFSET))

    def put(item):
        item.SetLayer(LAYER)
        item.SetLocked(True)
        board.Add(item)
        group.AddItem(item)

    def line(a, b, width=0.12):
        shape = pcb.PCB_SHAPE(board)
        shape.SetShape(pcb.SHAPE_T_SEGMENT)
        shape.SetStart(mm(*a))
        shape.SetEnd(mm(*b))
        shape.SetWidth(pcb.FromMM(width))
        put(shape)

    def rect(a, b, width=0.16):
        shape = pcb.PCB_SHAPE(board)
        shape.SetShape(pcb.SHAPE_T_RECT)
        shape.SetStart(mm(*a))
        shape.SetEnd(mm(*b))
        shape.SetWidth(pcb.FromMM(width))
        put(shape)

    def circle(at, radius=0.7, width=0.22):
        shape = pcb.PCB_SHAPE(board)
        shape.SetShape(pcb.SHAPE_T_CIRCLE)
        shape.SetStart(mm(*at))
        shape.SetEnd(mm(at[0] + radius, at[1]))
        shape.SetWidth(pcb.FromMM(width))
        put(shape)

    def text(value, x, y, size=1.0, bold=False):
        item = pcb.PCB_TEXT(board)
        item.SetText(value)
        item.SetPosition(mm(x, y))
        item.SetTextSize(pcb.VECTOR2I(pcb.FromMM(size), pcb.FromMM(size)))
        item.SetTextThickness(pcb.FromMM(0.16 if bold else 0.12))
        item.SetBold(bold)
        item.SetHorizJustify(pcb.GR_TEXT_H_ALIGN_LEFT)
        put(item)

    def point(at):
        return (pcb.ToMM(at.x) - OFFSET, pcb.ToMM(at.y) - OFFSET)

    # Drawing-only magnifications make the dense control and ICSP regions
    # reviewable without putting large labels across the actual copper.
    def inset(bounds, origin, scale, title):
        x0, y0, x1, y1 = bounds
        ox, oy = origin
        tx = lambda p: (ox + (p[0] - x0) * scale, oy + (p[1] - y0) * scale)
        rect((ox - 2, oy - 4), (ox + (x1-x0)*scale + 2, oy + (y1-y0)*scale + 3))
        text(title, ox, oy - 7, 1.3, True)

        def clip(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            lo, hi = 0.0, 1.0
            for p, q in ((-dx, a[0]-x0), (dx, x1-a[0]), (-dy, a[1]-y0), (dy, y1-a[1])):
                if p == 0:
                    if q < 0:
                        return None
                elif p < 0:
                    lo = max(lo, q/p)
                else:
                    hi = min(hi, q/p)
            if lo > hi:
                return None
            return (a[0] + lo*dx, a[1] + lo*dy), (a[0] + hi*dx, a[1] + hi*dy)

        for track in board.GetTracks():
            if isinstance(track, pcb.PCB_VIA):
                x, y = point(track.GetPosition())
                if x0 <= x <= x1 and y0 <= y <= y1:
                    circle(tx((x, y)), pcb.ToMM(track.GetWidth(pcb.F_Cu)) * scale / 2, 0.08)
                continue
            segment = clip(point(track.GetStart()), point(track.GetEnd()))
            if segment:
                line(tx(segment[0]), tx(segment[1]), 0.10)
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                x, y = point(pad.GetPosition())
                if x0 <= x <= x1 and y0 <= y <= y1:
                    w, h = pcb.ToMM(pad.GetSize().x) * scale, pcb.ToMM(pad.GetSize().y) * scale
                    cx, cy = tx((x, y))
                    if pad.GetShape() == pcb.PAD_SHAPE_CIRCLE:
                        circle((cx, cy), w/2, 0.07)
                    else:
                        rect((cx-w/2, cy-h/2), (cx+w/2, cy+h/2), 0.07)
        return tx

    text('REVIEW R2 - P3.5 PHOTO CORRECTIONS / Q01-Q12', 0, -17, 2.0, True)
    text('User.5 overlay only. Circles mark locations; letters identify probe points.', 0, -13, 1.1)
    text('All copper is photo-derived. Numbers do not mean confirmed electrical connections.', 0, -10.5, 1.0)
    rect((-1, -1), (104, 56), 0.22)
    for question in QUESTIONS:
        for t in question['targets']:
            circle(t['at'], 0.65, 0.16)
    # Main-board labels concentrate on the less crowded right/top regions.
    for qid, labels in {
        'Q11': [(105, 43.0), (105, 36.75)],
        'Q12': [(16.5, 0), (94, 55), (-7, 9.08)],
    }.items():
        question = next(q for q in QUESTIONS if q['id'] == qid)
        for t, label in zip(question['targets'], labels):
            line(t['at'], label, 0.15)
            text(qid + t['id'], *label, 0.9, True)
    text('Q01-Q03 + Q09: corner detail below', 0, 61, 1.1, True)
    text('Q04-Q08 + Q10: control detail below', 0, 64, 1.1, True)

    controls = inset((0, 44, 33, 55), (0, 83), 3.2,
                     'CONTROL DETAIL - 3.2x - TOP VIEW')
    # Labels around the magnified region are deliberately separated from
    # the dense probe points; leaders indicate the exact target circle.
    labels = {
        'Q04': [(106, 88), (106, 99), (78, 127)],
        'Q05': [(30, 79), (43, 79), (62, 79)],
        'Q06': [(30, 118), (51, 118)],
        'Q07': [(0, 123), (51, 129), (73, 120)],
        'Q08': [(29, 129), (86, 113)],
        'Q10': [(-9, 94), (-9, 113)],
    }
    for qid, positions in labels.items():
        question = next(q for q in QUESTIONS if q['id'] == qid)
        for t, label in zip(question['targets'], positions):
            actual = controls(t['at'])
            circle(actual, 1.1, 0.25)
            line(actual, label, 0.16)
            text(qid + t['id'], *label, 1.1, True)

    corner = inset((0, 0, 25, 14), (0, 147), 3.2,
                   'ICSP / BACK-EDGE DETAIL - 3.2x - TOP VIEW')
    corner_labels = {
        'Q01': [(-8, 167), (26, 171), (4, 177), (38, 163), (-8, 184)],
        'Q02': [(22, 142), (59, 143)],
        'Q03': [(48, 174), (82, 183)],
        'Q09': [(76, 163), (76, 177), (76, 189), (55, 154)],
    }
    for qid, positions in corner_labels.items():
        question = next(q for q in QUESTIONS if q['id'] == qid)
        for t, label in zip(question['targets'], positions):
            # UB-02's far terminal is shown on the actual board / control
            # area rather than being falsely projected into this inset.
            actual = corner(t['at']) if t['at'][1] <= 14 else controls(t['at'])
            if t['at'][1] > 14:
                label = (-9, 106)
            circle(actual, 1.1, 0.25)
            line(actual, label, 0.16)
            text(qid + t['id'], *label, 1.1, True)
    for n in range(1, 7):
        at = (2.0 + ((n-1)//2)*2.54, 1.8 + ((n-1)%2)*2.54)
        x, y = corner(at)
        text(str(n), x-0.5, y, 0.95, True)
    text('J9 pad numbers are model coordinates, not an assumed standard ICSP pinout.',
         0, 198, 1.0)
    text('SW1: 1 upper left / 2 upper right / 3 lower left / 4 lower right.',
         0, 201, 1.0)
    text('Meter checks: board removed and unpowered. Reply with Q number + point letter.',
         0, 204, 1.0, True)

    import textwrap
    for i, question in enumerate(QUESTIONS):
        x, y = 121, -5 + i * 16.8
        rect((x-2, y-3.0), (221, y+11.6))
        text(question['id'] + '  ' + question['title'], x, y, 1.5, True)
        for j, wrapped in enumerate(textwrap.wrap(question['question'], 95)):
            text(wrapped, x, y + 3.1 + j*2.2, 1.2)

    # Keep this explicit rather than relying on per-machine layer presets.
    visible = board.GetVisibleLayers()
    visible.AddLayer(LAYER)
    board.SetVisibleLayers(visible)
    write_checklist()
    return len(list(group.GetItems()))


def write_checklist():
    (ROOT / 'review-questions.json').write_text(json.dumps({
        'revision': 'R2', 'layer': 'User.5', 'group': GROUP,
        'orientation': 'Top view; coordinates relative to upper-left board corner in mm.',
        'questions': QUESTIONS,
    }, indent=2) + '\n')
    destination = ROOT / 'review-checks.csv'
    old = {}
    if destination.exists():
        with destination.open() as f:
            old = {r['point_id']: r for r in csv.DictReader(f)}
    with destination.open('w', newline='') as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(['question_id', 'point_id', 'source', 'board_x_mm', 'board_y_mm',
                         'side', 'check', 'result', 'notes'])
        for question in QUESTIONS:
            for t in question['targets']:
                key = question['id'] + t['id']
                previous = old.get(key, {})
                writer.writerow([question['id'], key, t['source'], *t['at'], t['side'],
                                 question['question'], previous.get('result', ''), previous.get('notes', '')])
    paragraphs = ['# Checks marked in KiCad', '',
                  'Enable **User.5** in the PCB Editor. The **Carrier review questions R2** group contains',
                  'the circles, enlarged detail views and Q01-Q12 question cards. This layer adds no copper.', '',
                  'Use the point letters beside the circles when replying, for example:',
                  '`Q04: A and B are continuous; R3 right land connects to D13.`', '',
                  'All coordinates use the top view, with the small corner header at the upper left.',
                  'The enlarged views are drawing-only copies; they are not extra physical board parts.', '',
                  '| ID | What to check | Marked points |', '|---|---|---|']
    for question in QUESTIONS:
        points = '; '.join(t['id'] + ': ' + t['source'] for t in question['targets'])
        paragraphs.append('| ' + question['id'] + ' | ' + question['question'] + ' | ' + points + ' |')
    paragraphs += ['', 'Enter measurements in [review-checks.csv](review-checks.csv), or report the Q IDs in chat.',
                   'There are no inferred passes in the checklist. A question can be answered independently.',
                   'For resistance/continuity checks, remove the board from the Due and disconnect power.', '']
    (ROOT / 'REVIEW-CHECKS.md').write_text('\n'.join(paragraphs))


def save_review_board(board, path):
    # KiCad 10's Python binding does not expose PAGE_INFO construction.
    # Serialize the native page token after saving; copper is untouched.
    import re
    pcb.SaveBoard(str(path), board)
    text = path.read_text()
    text, count = re.subn(r'\(paper "[^"]+"\)', '(paper "A3")', text, count=1)
    if count != 1:
        raise ValueError('Expected one native page token.')
    path.write_text(text)


def strip_review_text(text):
    """Remove only owned graphic UUIDs, preserving other User.5 drawings."""
    import re
    blocks = []
    for match in re.finditer(r'\n\t\((?:gr_\w+|group)\b', text):
        start = match.start() + 2
        depth, quoted, escaped = 0, False, False
        for i in range(start, len(text)):
            char = text[i]
            if quoted:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    blocks.append((start, i + 1, text[start:i+1]))
                    break
    groups = [b for b in blocks if b[2].startswith('(group ' + json.dumps(GROUP))]
    if not groups:
        return text
    assert len(groups) == 1
    owner = groups[0]
    members = set(re.findall(r'"([0-9a-f-]{36})"', owner[2].split('(members', 1)[1]))
    removed = []
    for block in blocks:
        match = re.search(r'\(uuid "([0-9a-f-]{36})"\)', block[2])
        if block == owner or (match and match[1] in members):
            if block != owner:
                assert block[2].startswith('(gr_') and '(layer "User.5")' in block[2]
            removed.append(block)
    missing = members - {re.search(r'\(uuid "([0-9a-f-]{36})"\)', b[2])[1]
                         for b in removed if b != owner}
    # Older exports may retain a dangling group member for a zero-radius
    # drawing. It has no serialized item to remove; preserve every other
    # object and drop that obsolete reference with the owned group.
    assert all(text.count(m) == 1 for m in missing), missing
    for start, end, _ in sorted(removed, reverse=True):
        text = text[:start] + text[end:]
    return text


if __name__ == '__main__':
    import tempfile
    board_path = ROOT / 'mega-proto-carrier.kicad_pcb'
    with tempfile.TemporaryDirectory(prefix='carrier-review-') as work:
        scratch = Path(work) / board_path.name
        scratch.write_text(strip_review_text(board_path.read_text()))
        board = pcb.LoadBoard(str(scratch))
        count = add_review_layer(board)
        save_review_board(board, board_path)
    print(f'Added {count} review drawings on User.5; copper and net assignments retained.')
