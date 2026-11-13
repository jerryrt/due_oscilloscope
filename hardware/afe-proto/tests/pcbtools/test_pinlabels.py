"""The Due's pin names on the overhang bands (pcbtools/pinlabels.py, LR-11): the table parser on hand-built tables (numpy and text only),
and the integrated v2 board: every edge-row socket pad has exactly one label, its text is the table's, it is on top silk at the planned
place and height, DRC reports no silk problem, and each way of breaking it is caught (broken once on purpose, kept as tests)."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from pcbtools import boardio, pinlabels as PL, rules as R
from pcbtools.boards import v2_layout as L

REPO = pathlib.Path(__file__).resolve().parents[4]
BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
TABLE = REPO / L.PIN_TABLE

pcbnew_mark = pytest.mark.pcbnew

SYNTH = """\
| ADCL0 pin | x | net | Arduino | | ADCH0 pin | x | net | Arduino |
|---|---|---|---|---|---|---|---|---|
| 1 | 50.80 | AD0 | A7 | | 1 | 73.66 | AD8 | A8 *(check)* |
| 2 | 53.34 | AD1 | A6 | | 2 | 76.20 | AD9 | DAC0 |

| POWER0 pin | x | net | Due label |
|---|---|---|---|
| 1 | 27.94 | (no net) | NC |
| 2 | 30.48 | +3V3 | IOREF (tied to +3V3) |
| 4 | 35.56 | +3V3 | 3.3 V |

| COMMUNICATION0 pin | x | net | Arduino *(check)* |
|---|---|---|---|
| 1 | 68.58 | TXD0 | D14 TX3 |
| 7 | 83.82 | SDA0-3 | D20 SDA (net also on RN5.8, 1.5 k to 3V3) |

| PWMH0 pin | x | net | Arduino | | PWML0 pin | x | net | Arduino |
|---|---|---|---|---|---|---|---|---|
| 9 | 21.336 | SDA1 | SDA1 (D70) *(check)* | | 1 | 63.50 | RX | D0 |
"""


def test_the_parser_takes_the_dues_name_from_each_kind_of_cell(tmp_path):
    p = tmp_path / 't.md'
    p.write_text(SYNTH)
    refs = ['ADCL0', 'ADCH0', 'POWER0', 'COMMUNICATION0', 'PWMH0', 'PWML0']
    t = PL.parse_header_table(p, refs, L.PIN_LABEL_ALIASES)
    assert t['ADCL0'] == {'1': PL.Label('A7', False), '2': PL.Label('A6', False)}                # two headers side by side are split
    assert t['ADCH0'] == {'1': PL.Label('A8', True), '2': PL.Label('DAC0', False)}               # the cell's own *(check)* mark is kept
    assert t['POWER0'] == {'1': PL.Label('NC', False), '2': PL.Label('IOREF', False), '4': PL.Label('3V3', False)}   # parenthesis dropped, alias
    assert t['COMMUNICATION0']['1'] == PL.Label('D14', True)                                      # a marked column header marks every cell
    assert t['COMMUNICATION0']['7'] == PL.Label('D20', True)                                      # first word, comment in parentheses dropped
    assert t['PWMH0']['9'] == PL.Label('SDA1', True) and t['PWML0']['1'] == PL.Label('D0', False)


def test_a_header_that_the_table_lacks_is_an_error_not_a_smaller_label_set(tmp_path):
    p = tmp_path / 't.md'
    p.write_text(SYNTH)
    with pytest.raises(ValueError, match='NOSUCH0'):
        PL.parse_header_table(p, ['ADCL0', 'NOSUCH0'])


def test_the_real_table_gives_every_edge_header_its_pins():
    t = PL.parse_header_table(TABLE, sorted(set(L.EDGE_SOCKETS.values())), L.PIN_LABEL_ALIASES)
    want = {'POWER0': 8, 'ADCL0': 8, 'ADCH0': 8, 'PWMH0': 10, 'PWML0': 8, 'COMMUNICATION0': 8}      # the 1xN headers' own pin counts (the table, section 2)
    assert {k: len(v) for k, v in t.items()} == want
    assert all(lab.text and ' ' not in lab.text for h in t.values() for lab in h.values())


def test_the_config_names_the_edge_sockets_and_not_the_xio_socket():
    assert 'J605' not in L.EDGE_SOCKETS and set(L.EDGE_SOCKETS) == {'J601', 'J602', 'J603', 'J604', 'J606', 'J607'}


# ------------------------------------------------------------------------------------------------ the board file
def file_labels(text):
    """{(x, y): (text, angle, layer, height, width)} of every board-level gr_text, parsed from the board file (sheet mm -> Due mm)"""
    out = []
    for m in re.finditer(r'\n\t\(gr_text "([^"]*)"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)\n\t\t\(layer "([^"]+)"\).*?\(size ([-\d.]+) ([-\d.]+)\)', text, re.S):
        out.append((m.group(1), round(float(m.group(2)) - 50, 3), round(150 - float(m.group(3)), 3), float(m.group(4)), m.group(5),
                    float(m.group(6)), float(m.group(7))))
    return out


@pcbnew_mark
def test_every_edge_socket_pad_has_exactly_one_label_equal_to_the_table(pcbnew_required):
    b = boardio.read_board(BOARD)
    table = PL.label_table(L)
    pads = PL.socket_pads(b, L)
    assert len(pads) == 50                                                                      # 8 + 8 + 8 + 10 + 8 + 8 pads on the six sockets
    labels = file_labels(BOARD.read_text())
    plan = {(p.ref, p.pin): p for p in PL.plan_labels(b, L)}
    for sock, pin, hdr, _, px, py in pads:
        want = table[hdr][pin].text
        p = plan[(sock, pin)]
        hit = [t for t in labels if abs(t[1] - p.x) < 0.01 and abs(t[2] - p.y) < 0.01]
        assert len(hit) == 1, (sock, pin, hit)
        text, x, y, ang, layer, h, w = hit[0]
        assert text == want, (sock, pin)
        assert layer == 'F.SilkS' and h >= 1.0 and ang == p.angle and L.PIN_LABEL_MIN_W <= w <= L.PIN_LABEL_W, (sock, pin, hit[0])
        assert abs(x - px) < 0.01                                                               # centred on its pad column
    in_bands = [t for t in labels if any(x0 <= t[1] <= x1 and y0 <= t[2] <= y1 for _, (x0, y0, x1, y1) in L.KEEPOUTS)]
    assert len(in_bands) == len(pads)                                                          # and nothing else is in a band


@pcbnew_mark
def test_the_board_labels_pass_the_rule_and_the_rule_reports_each_way_to_break_them(pcbnew_required, tmp_path):
    """broken once on purpose, each by editing the board text: a renamed label, a missing label, a label moved onto a pad, a label under the
    minimum height, two labels run together, a stray text in a band. Each must make findings() (LR-11) report it; the clean board reports none."""
    b = boardio.read_board(BOARD)
    assert PL.findings(b, L) == []
    text = BOARD.read_text()
    blocks = list(re.finditer(r'\n\t\(gr_text "([^"]*)"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)(.*?)\n\t\)(?=\n)', text, re.S))
    lab = [m for m in blocks if m.group(1) == 'A3'][0]                                          # A3 on J602 pin 5

    def run(new, name):
        p = tmp_path / (name + '.kicad_pcb')
        p.write_text(new)
        return PL.findings(boardio.read_board(p), L)
    cut = lambda m, repl: text[:m.start()] + repl + text[m.end():]  # noqa: E731
    r = run(cut(lab, lab.group(0).replace('"A3"', '"A9"', 1)), 'renamed')
    assert any('"A3"' in s for s in r), r
    r = run(cut(lab, ''), 'missing')
    assert any('0 label(s) "A3"' in s for s in r), r
    r = run(cut(lab, lab.group(0).replace(lab.group(3), '147.3', 1)), 'ontopad')                  # y 147.3 = Due y 2.7: on the pad row
    assert r, r
    r = run(cut(lab, lab.group(0).replace('(size 1 0.8)', '(size 0.8 0.8)', 1)), 'short')
    assert any('mm high' in s for s in r), r
    nb = [m for m in blocks if m.group(1) == 'A2'][0]
    moved = lab.group(0).replace(lab.group(2), str(float(lab.group(2)) + 1.0), 1).replace('"A3"', '"A3"')
    two = text[:lab.start()] + moved + text[lab.end():]
    r = run(two, 'runtogether')
    assert r, r
    stray = lab.group(0).replace('"A3"', '"STRAY"').replace(lab.group(2), '100', 1).replace(lab.group(3), '152', 1).replace('9f', '9f')
    stray = re.sub(r'\(uuid "[^"]+"\)', '(uuid "00000000-0000-4000-8000-000000000001")', stray)
    r = run(text[:lab.end()] + stray + text[lab.end():], 'stray')
    assert any('STRAY' in s for s in r), r


@pcbnew_mark
def test_lr11_fails_when_a_pin_label_is_missing(pcbnew_required, tmp_path):
    text = BOARD.read_text()
    m = [m for m in re.finditer(r'\n\t\(gr_text "A3"\n.*?\n\t\)(?=\n)', text, re.S)][0]
    p = tmp_path / 'b.kicad_pcb'
    p.write_text(text[:m.start()] + text[m.end():])
    r = R.lr11(boardio.read_board(p), L)
    assert not r.ok and 'A3' in r.detail
    assert R.lr11(boardio.read_board(BOARD), L).ok


@pcbnew_mark
def test_the_labels_are_spliced_in_idempotently_and_touch_nothing_else(pcbnew_required):
    b = boardio.read_board(BOARD)
    plan = PL.plan_labels(b, L)
    text = BOARD.read_text()
    ids = [(s, pin) for s, pin, *_ in PL.socket_pads(b, L)]
    assert PL.apply_labels(text, plan, L, ids) == text                                          # already applied: unchanged
    bare = PL.apply_labels(text, [], L, ids)                                                    # drop every label ...
    assert bare != text and len(file_labels(bare)) == len(file_labels(text)) - 50
    assert PL.apply_labels(bare, plan, L, ids) == text                                          # ... and put them back: byte for byte


@pcbnew_mark
def test_kicad_drc_has_no_silk_finding_on_the_labels(pcbnew_required, tmp_path):
    if not shutil.which('kicad-cli'):
        pytest.skip('no kicad-cli')
    d = tmp_path / 'p'
    d.mkdir()
    for f in BOARD.parent.iterdir():
        if f.is_file():
            shutil.copy(f, d / f.name)
    out = tmp_path / 'drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(out), str(d / BOARD.name)], capture_output=True)
    v = json.loads(out.read_text())['violations']
    silk = [x for x in v if x['type'] in ('silk_overlap', 'silk_edge_clearance', 'silk_over_copper', 'text_height', 'text_thickness')]
    assert silk == [], [(x['type'], [i['description'] for i in x['items']]) for x in silk]
