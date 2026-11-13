"""The Due's own pin names, printed on the shield's overhang bands (LR-11, owner 2026-11-13).

The shield covers the Due's silkscreen, so a user adding a jumper wire to a socket cannot read which pin it is. Each socket of the
board's edge rows gets the label the Due prints for that pin, on top silk, in the overhang band on its side of the board.

Built once and driven by the board config (see boards/v2_layout.py), so another board reuses it::

    python3 -m pcbtools.pinlabels BOARD.kicad_pcb --config v2_layout [--write [OUT]] [--check] [--list]

    pinlabels.parse_header_table(path, refs)  -> {header: {pin: Label(text, check)}}     the Due's names, parsed from the table
    pinlabels.plan_labels(b, cfg)             -> [Planned]                               where each label goes (BoardArrays + config)
    pinlabels.apply_labels(text, planned, cfg) -> text                                   the board text with the labels spliced in
    pinlabels.findings(b, cfg)                -> [str]                                   what is wrong with the board's labels (LR-11)

Config fields (all read from `cfg`, none is typed here): EDGE_SOCKETS {socket ref: Due header ref in the table}, PIN_TABLE (repo
relative path of docs/due-header-table.md), BOARD_RECT, KEEPOUTS (the bands), PIN_LABEL_H / _W / _THICK /
_EDGE_MARGIN / _PAD_GAP / _ALIASES / _POS_TOL / _FUNCTION_HEADERS, DESIGNATOR_GAP_ONE_LABEL (the gap two labels must keep), DESIGNATOR_ADVANCE and
DESIGNATOR_INK_H (the designators' boxes, which labels keep clear of), PIN_LABEL_INK {name: ink length} and PIN_LABEL_INK_H (from
INK_FILE), OVERHANG (derived from them by required_overhang).

The names are the table's "Arduino" or "Due label" column: the cell without its `*(check)*` mark and its parenthesis, mapped through
PIN_LABEL_ALIASES when the whole cell is a key ("3.3 V" -> "3V3"), else its first word; for a header in PIN_LABEL_FUNCTION_HEADERS the
word that is not the Dnn number ("D14 TX3" -> "TX3"), and a cell with no such word keeps the number, marked (check). A cell the table marks
`*(check)*` (or whose column header is marked) keeps the mark in `Label.check`, and the plan, the CLI listing and the board's data
comment carry it: the name is the table's inference, not a read-off from the Due.

Placement. Every label is turned 90 degrees (reading bottom to top, on both bands), exactly PIN_LABEL_H (1.0 mm, the board house's minimum)
high and PIN_LABEL_W wide (the stroke font's default width at that height), one size for every name. A label starts at the band's outer
edge (PIN_LABEL_EDGE_MARGIN in) and runs inward, so it may enter the copper-free strip between the band and the socket pads, never closer
than PIN_LABEL_PAD_GAP to a pad. Nothing is narrowed or shrunk: the overhang is what is sized, to fit the longest name
(required_overhang()), from lengths measured in KiCad's stroke font (measure(), stored in pinlabel_ink.json, which a test re-measures).
"""
from __future__ import annotations

import dataclasses
import importlib
import os
import re
import sys
import uuid

import numpy as np

SHEET_X, SHEET_Y = 50.0, 150.0                       # Due mm -> KiCad sheet mm: x + 50, 150 - y (as v2/layout/outline_overhang.py)
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))


@dataclasses.dataclass(frozen=True)
class Label:
    text: str
    check: bool            # the table marks it *(check)*: an inference, not read off the Due


@dataclasses.dataclass(frozen=True)
class Planned:
    ref: str               # the socket on the shield
    pin: str
    text: str
    x: float               # Due mm, y up; the text is centred on (x, y)
    y: float
    angle: float           # degrees, 0 or 90 (KiCad: counter-clockwise on screen)
    w: float               # character width in mm
    h: float
    length: float          # the text box along its baseline
    check: bool
    band: str


# ------------------------------------------------------------------------------------------------ the table
def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def clean(cell, aliases=None, function=False):
    """the Due's name in one table cell. function=True (a header in PIN_LABEL_FUNCTION_HEADERS): the cell's word that is not the Dnn
    number ("D14 TX3" -> "TX3"); a cell with only the number keeps it, and the caller marks it (check)."""
    s = re.sub(r'\*\(check\)\*', '', cell)
    s = re.sub(r'\([^)]*\)', '', s).strip()
    if aliases and s in aliases:
        return aliases[s]
    words = s.split()
    if function:
        named = [w for w in words if not re.fullmatch(r'D\d+', w)]
        if named:
            return named[0]
    return words[0] if words else ''


def parse_header_table(path, refs, aliases=None, function_headers=()):
    """{header ref: {pin number (str): Label}} for each header in `refs`, read from the markdown tables whose header row has a cell
    `<REF> pin` followed by a column called Arduino or Due label. Tables with two headers side by side (ADCL0 | ADCH0) are split. A
    header that is not found is an error: the label set must not shrink silently."""
    lines = open(path, encoding='utf-8').read().split('\n')
    out = {}
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith('|') and not set(ln) <= set('|- '):
            head = _cells(ln)
            groups = [(k, m.group(1)) for k, c in enumerate(head) if (m := re.fullmatch(r'(\S+) pin', c))]
            if groups and any(r in refs and r not in out for _, r in groups):
                cols = {}
                for gi, (k, ref) in enumerate(groups):
                    end = groups[gi + 1][0] if gi + 1 < len(groups) else len(head)
                    lab = [j for j in range(k + 1, end) if head[j].startswith(('Arduino', 'Due label'))]
                    if lab:
                        cols[ref] = (k, lab[0], '(check)' in head[lab[0]])
                j = i + 2                                           # the header, the |---| line, then the rows
                rows = {r: {} for r in cols if r in refs and r not in out}
                while j < len(lines) and lines[j].startswith('|'):
                    c = _cells(lines[j])
                    for ref, (pk, lk, hchk) in cols.items():
                        if ref in rows and pk < len(c) and lk < len(c) and c[pk].isdigit() and c[lk]:
                            fn = ref in function_headers
                            txt = clean(c[lk], aliases, fn)
                            rows[ref][c[pk]] = Label(txt, hchk or '(check)' in c[lk] or (fn and re.fullmatch(r'D\d+', txt) is not None))
                    j += 1
                out.update({r: v for r, v in rows.items() if v})
                i = j
                continue
        i += 1
    missing = sorted(set(refs) - set(out))
    if missing:
        raise ValueError(f'{path}: no pin table found for {missing}')
    return out


# ------------------------------------------------------------------------------------------------ the plan
def _box(cx, cy, length, height, ang):
    c, s = np.cos(np.radians(ang)), np.sin(np.radians(ang))
    u, v = np.array([c, s]) * length / 2, np.array([-s, c]) * height / 2
    p = np.array([cx, cy])
    return np.array([p + u + v, p - u + v, p - u - v, p + u - v])


def socket_pads(b, cfg):
    """[(ref, pin, header ref, row of pad box (x0, y0, x1, y1))] of every pad of every edge-row socket, in the board's pad order"""
    refs = list(b.fp_ref)
    out = []
    for sock, hdr in cfg.EDGE_SOCKETS.items():
        if sock not in refs:
            raise ValueError(f'{sock} (EDGE_SOCKETS) is not on the board')
        fi = refs.index(sock)
        for j in np.flatnonzero(b.p_fp.astype(int) == fi):
            out.append((sock, str(b.p_pin[j]), hdr, (float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j])),
                        float(b.p_x[j]), float(b.p_y[j])))
    return out


def label_table(cfg):
    path = cfg.PIN_TABLE if os.path.isabs(cfg.PIN_TABLE) else os.path.join(REPO, cfg.PIN_TABLE)
    return parse_header_table(path, sorted(set(cfg.EDGE_SOCKETS.values())), getattr(cfg, 'PIN_LABEL_ALIASES', None),
                             getattr(cfg, 'PIN_LABEL_FUNCTION_HEADERS', ()))


def plan_labels(b, cfg):
    """[Planned] one per pad of the edge-row sockets, all turned 90 degrees (reading bottom to top on both bands), all PIN_LABEL_H high and
    PIN_LABEL_W wide, each starting at its band's outer edge (PIN_LABEL_EDGE_MARGIN in) and running inward by its measured ink length
    (cfg.PIN_LABEL_INK). Returns what the config and the table say; the board's own silk is not read."""
    table = label_table(cfg)
    bands = [(n, r) for n, r in cfg.KEEPOUTS]
    out = []
    for sock, pin, hdr, (bx0, by0, bx1, by1), px, py in socket_pads(b, cfg):
        lab = table[hdr].get(pin)
        if lab is None:
            raise ValueError(f'{sock}.{pin}: the table has no pin {pin} for {hdr}')
        if lab.text not in cfg.PIN_LABEL_INK:
            raise ValueError(f'{lab.text!r} has no measured ink length: run python3 -m pcbtools.pinlabels --measure in the PCB image')
        name, (rx0, ry0, rx1, ry1) = min(bands, key=lambda nr: abs(py - (nr[1][1] + nr[1][3]) / 2))
        south = (ry0 + ry1) / 2 < py                                  # the band lies on the low-y side of the pad
        outer = (ry0 + cfg.PIN_LABEL_EDGE_MARGIN) if south else (ry1 - cfg.PIN_LABEL_EDGE_MARGIN)
        length = cfg.PIN_LABEL_INK[lab.text]
        cy = outer + length / 2 if south else outer - length / 2
        out.append(Planned(sock, pin, lab.text, round(px, 3), round(cy, 3), 90.0, cfg.PIN_LABEL_W, cfg.PIN_LABEL_H, round(length, 3), lab.check, name))
    return out


# ------------------------------------------------------------------------------------------------ measuring, and the overhang that follows
INK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pinlabel_ink.json')


def label_names(path, refs, aliases=None, function_headers=()):
    """the sorted set of names the table gives the headers in `refs`"""
    t = parse_header_table(path, refs, aliases, function_headers)
    return sorted({lab.text for h in t.values() for lab in h.values()})


def measure(names, h, w, thick):
    """{name: ink length along the baseline, in mm} and the ink height across it, as KiCad's stroke font draws them at h x w with the given
    stroke: the bounding box of GetEffectiveTextShape() plus one stroke width. Needs pcbnew (the PCB image)."""
    import pcbnew
    b = pcbnew.BOARD()
    ink, across = {}, 0.0
    for n in names:
        t = pcbnew.PCB_TEXT(b)
        t.SetText(n)
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(int(round(w * 1e6)), int(round(h * 1e6))))
        t.SetTextThickness(int(round(thick * 1e6)))
        t.SetPosition(pcbnew.VECTOR2I(0, 0))
        bb = t.GetEffectiveTextShape().BBox()
        ink[n] = round(bb.GetWidth() / 1e6 + thick, 3)
        across = max(across, round(bb.GetHeight() / 1e6 + thick, 3))
    return ink, across


def pad_edge(b, cfg):
    """how far the nearest pad of an edge-row socket lies from the Due's own edge on its side, in mm (the same for every socket row)"""
    dx0, dy0, dx1, dy1 = cfg.DUE_RECT
    d = []
    for sock, pin, hdr, (bx0, by0, bx1, by1), px, py in socket_pads(b, cfg):
        d.append(by0 - dy0 if py < (dy0 + dy1) / 2 else dy1 - by1)
    return round(min(d), 3)


def required_overhang(ink_max, pad_edge_mm, pad_gap, edge_margin, step):
    """the overhang that fits the longest name: from the board edge, edge_margin + the ink + pad_gap reach the pads, which lie pad_edge_mm
    inside the Due's edge; rounded UP to the next `step` mm"""
    import math
    need = edge_margin + ink_max + pad_gap - pad_edge_mm
    return math.ceil(round(need / step, 9)) * step


def load_ink(path=INK_FILE):
    import json
    return json.load(open(path))


def planned_boxes(plan, cfg):
    return [_box(p.x, p.y, p.length, cfg.PIN_LABEL_INK_H, p.angle) for p in plan]


# ------------------------------------------------------------------------------------------------ the findings (LR-11)
def _gap(P, Q):
    from .rules import _convex_gap
    return float(_convex_gap(P, Q))


def file_texts(text):
    """[(text, x, y, angle, layer, height, width)] of every board-level gr_text in a board file (Due mm; the file's `(size H W)`)"""
    out = []
    for m in re.finditer(r'\n\t\(gr_text "([^"]*)"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)\n\t\t\(layer "([^"]+)"\).*?\(size ([-\d.]+) ([-\d.]+)\)', text, re.S):
        out.append((m.group(1), float(m.group(2)) - SHEET_X, SHEET_Y - float(m.group(3)), float(m.group(4)), m.group(5), float(m.group(6)), float(m.group(7))))
    return out


def _file_findings(b, plan, cfg):
    """what the arrays cannot see, read from the board file when it is there: every label on F.SilkS, turned as planned and of the one
    planned height and width (a label rotated or sized differently from the rest is the finding)"""
    path = getattr(b, 'path', '')
    if not path or not os.path.isfile(path) or not str(path).endswith('.kicad_pcb'):
        return []
    texts = file_texts(open(path).read())
    bad = []
    for p in plan:
        hit = [t for t in texts if t[0] == p.text and abs(t[1] - p.x) <= cfg.PIN_LABEL_POS_TOL and abs(t[2] - p.y) <= cfg.PIN_LABEL_POS_TOL]
        if len(hit) != 1:
            continue                                                  # a missing or doubled label is already reported from the arrays
        _, _, _, ang, layer, h, w = hit[0]
        if layer != 'F.SilkS':
            bad.append(f'{p.ref}.{p.pin}: label "{p.text}" is on {layer}, not F.SilkS')
        if abs(((ang - p.angle + 180) % 360) - 180) > 0.01:
            bad.append(f'{p.ref}.{p.pin}: label "{p.text}" is turned {ang:g} degrees, every label is {p.angle:g}')
        if abs(h - p.h) > 1e-6 or abs(w - p.w) > 1e-6:
            bad.append(f'{p.ref}.{p.pin}: label "{p.text}" is {h:g} x {w:g} mm, every label is {p.h:g} x {p.w:g}')
    return bad


def findings(b, cfg):
    """what is wrong with the board's pin labels, each a short string: [] when every edge-row socket pad has exactly one label equal to
    the table's, at its planned place and height, no label closer than DESIGNATOR_GAP_ONE_LABEL to another label or a designator, none
    over a pad or within PIN_LABEL_EDGE_MARGIN of the board edge, and no silk text in a band that the plan does not account for"""
    bad = []
    plan = plan_labels(b, cfg)
    tx, ty, th = np.asarray(b.t_x, float), np.asarray(b.t_y, float), np.asarray(b.t_h, float)
    texts = list(b.t_text)
    used = set()
    tol = cfg.PIN_LABEL_POS_TOL
    for p in plan:
        hit = [i for i in range(len(texts)) if texts[i] == p.text and abs(tx[i] - p.x) <= tol and abs(ty[i] - p.y) <= tol]
        if len(hit) != 1:
            near = [texts[i] for i in range(len(texts)) if abs(tx[i] - p.x) <= tol and abs(ty[i] - p.y) <= tol]
            bad.append(f'{p.ref}.{p.pin}: {len(hit)} label(s) "{p.text}" at ({p.x}, {p.y})' + (f', found {near}' if near else ''))
            continue
        used.add(hit[0])
        if abs(th[hit[0]] - cfg.PIN_LABEL_H) > 1e-6:
            bad.append(f'{p.ref}.{p.pin}: label "{p.text}" is {th[hit[0]]:.2f} mm high, every label is {cfg.PIN_LABEL_H}')
    bad += _file_findings(b, plan, cfg)
    bands = [r for _, r in cfg.KEEPOUTS]
    for i, t in enumerate(texts):
        if i in used:
            continue
        for x0, y0, x1, y1 in bands:
            if x0 <= tx[i] <= x1 and y0 <= ty[i] <= y1:
                bad.append(f'silk text "{t}" in a band is not a planned pin label')
    boxes = planned_boxes(plan, cfg)
    rx0, ry0, rx1, ry1 = cfg.BOARD_RECT
    m = cfg.PIN_LABEL_EDGE_MARGIN
    for k, (p, B) in enumerate(zip(plan, boxes)):
        if B[:, 1].min() < ry0 + m - 0.06 or B[:, 1].max() > ry1 - m + 0.06 or B[:, 0].min() < rx0 + m or B[:, 0].max() > rx1 - m:
            bad.append(f'{p.ref}.{p.pin}: "{p.text}" is within {m} mm of the board edge')
        g_ = cfg.PIN_LABEL_PAD_GAP
        near = np.flatnonzero((b.p_bx1 >= B[:, 0].min() - g_) & (b.p_bx0 <= B[:, 0].max() + g_) & (b.p_by1 >= B[:, 1].min() - g_) & (b.p_by0 <= B[:, 1].max() + g_))
        refs = list(b.fp_ref)
        for j in near:
            if _gap(B, np.array([[b.p_bx0[j], b.p_by0[j]], [b.p_bx1[j], b.p_by0[j]], [b.p_bx1[j], b.p_by1[j]], [b.p_bx0[j], b.p_by1[j]]])) < cfg.PIN_LABEL_PAD_GAP - 0.01:
                bad.append(f'{p.ref}.{p.pin}: "{p.text}" lies over or within {cfg.PIN_LABEL_PAD_GAP} mm of pad {refs[int(b.p_fp[j])]}.{b.p_pin[j]}')
        for p2, B2 in zip(plan[k + 1:], boxes[k + 1:]):
            g = _gap(B, B2)
            if g < cfg.DESIGNATOR_GAP_ONE_LABEL:
                bad.append(f'labels "{p.text}" ({p.ref}.{p.pin}) and "{p2.text}" ({p2.ref}.{p2.pin}) are {g:.2f} mm apart, under {cfg.DESIGNATOR_GAP_ONE_LABEL}')
    from .rules import _label_boxes
    for ref, D in _label_boxes(b, cfg).items():
        for p, B in zip(plan, boxes):
            g = _gap(B, D)
            if g < cfg.DESIGNATOR_GAP_ONE_LABEL:
                bad.append(f'label "{p.text}" ({p.ref}.{p.pin}) is {g:.2f} mm from designator {ref}, under {cfg.DESIGNATOR_GAP_ONE_LABEL}')
    return bad


# ------------------------------------------------------------------------------------------------ the board file
def _sheet(x, y):
    return round(x + SHEET_X, 6), round(SHEET_Y - y, 6)


def _fmt(v):
    return ('%.6f' % v).rstrip('0').rstrip('.')


def label_uuid(ref, pin):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'afe-pinlabel/{ref}.{pin}'))


def label_block(p):
    x, y = _sheet(p.x, p.y)
    return (f'\t(gr_text "{p.text}"\n\t\t(at {_fmt(x)} {_fmt(y)} {_fmt(p.angle)})\n\t\t(layer "F.SilkS")\n\t\t(uuid "{label_uuid(p.ref, p.pin)}")\n'
            f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {_fmt(p.h)} {_fmt(p.w)})\n\t\t\t\t(thickness {{t}})\n\t\t\t)\n\t\t)\n\t)\n')


def apply_labels(text, plan, cfg, all_ids=None):
    """the board text with one gr_text per planned label and no stale one: a block whose uuid is one a label of this config can have
    (all_ids: every (ref, pin) of the edge sockets, so a label dropped from the table goes too) is removed and the planned ones are
    inserted after the last existing board-level text. Nothing else is touched; running it again changes nothing."""
    ids = {label_uuid(r, p) for r, p in (all_ids or [(p.ref, p.pin) for p in plan])}
    blk = re.compile(r'\n\t\(gr_text .*?\n\t\)(?=\n)', re.S)
    text = blk.sub(lambda m: '' if any(f'(uuid "{u}")' in m.group(0) for u in ids) else m.group(0), text)
    last = None
    for m in re.finditer(r'\n\t\(gr_text .*?\n\t\)(?=\n)', text, re.S):
        last = m
    blocks = ''.join(label_block(p).replace('{t}', _fmt(cfg.PIN_LABEL_THICK)) for p in plan)
    at = last.end() + 1 if last else text.index('\n\t(gr_line\n') + 1
    return text[:at] + blocks + text[at:]


# ------------------------------------------------------------------------------------------------ command line
def main(argv):
    import argparse
    from . import boardio
    ap = argparse.ArgumentParser(prog='python -m pcbtools.pinlabels', description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', required=True, help='a module of pcbtools.boards (v2_layout)')
    ap.add_argument('--write', nargs='?', const='', default=None, help='write the labels into the board text (in place, or to OUT)')
    ap.add_argument('--check', action='store_true', help='exit 1 unless the board already carries the planned labels and findings() is empty')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--measure', action='store_true', help='re-measure the stroke font in the PCB image and write pcbtools/pinlabel_ink.json (--check compares instead)')
    a = ap.parse_args(argv)
    cfg = importlib.import_module('pcbtools.boards.' + a.config)
    b = boardio.read_board_retry(a.board)
    if a.measure:
        import json
        names = label_names(os.path.join(REPO, cfg.PIN_TABLE), sorted(set(cfg.EDGE_SOCKETS.values())), cfg.PIN_LABEL_ALIASES, cfg.PIN_LABEL_FUNCTION_HEADERS)
        ink, across = measure(names, cfg.PIN_LABEL_H, cfg.PIN_LABEL_W, cfg.PIN_LABEL_THICK)
        data = dict(h=cfg.PIN_LABEL_H, w=cfg.PIN_LABEL_W, thick=cfg.PIN_LABEL_THICK, ink_h=across, pad_edge=pad_edge(b, cfg), ink=ink,
                    note='ink length = the bounding box of KiCad stroke-font text (pcbnew GetEffectiveTextShape) plus one stroke width; pad_edge = pad box to the Due edge')
        if a.check:
            old = load_ink()
            print('pinlabel_ink.json is current' if old == data else 'pinlabel_ink.json is STALE')
            return 0 if old == data else 1
        json.dump(data, open(INK_FILE, 'w'), indent=1, sort_keys=True)
        print(f'wrote {INK_FILE}: {len(ink)} names, longest {max(ink, key=ink.get)} {max(ink.values())} mm, pad edge {data["pad_edge"]} mm')
        return 0
    plan = plan_labels(b, cfg)
    if a.list:
        for p in plan:
            print(f'{p.ref}.{p.pin:>2} {p.text:<6} {"turned" if p.angle else "flat  "} w {p.w:.2f} at ({p.x:.2f}, {p.y:.2f}) {p.band}' + ('  *(check)*' if p.check else ''))
    text = open(a.board).read()
    ids = [(r, str(pn)) for r, pn in ((s, pin) for s, pin, *_ in socket_pads(b, cfg))]
    new = apply_labels(text, plan, cfg, ids)
    if a.check:
        bad = findings(b, cfg)
        for s in bad:
            print('FAIL', s)
        return 1 if (new != text or bad) else 0
    if a.write is not None:
        out = a.write or a.board
        open(out, 'w').write(new)
        print('changed' if new != text else 'already applied', f'({len(plan)} labels)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
