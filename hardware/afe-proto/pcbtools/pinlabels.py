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
relative path of docs/due-header-table.md), BOARD_RECT, KEEPOUTS (the bands), PIN_LABEL_H / _W / _MIN_W / _THICK / _ADVANCE / _INK_PAD /
_EDGE_MARGIN / _PAD_GAP / _ALIASES / _POS_TOL, DESIGNATOR_GAP_ONE_LABEL (the gap two labels must keep), DESIGNATOR_ADVANCE and
DESIGNATOR_INK_H (the designators' boxes, which labels keep clear of).

The names are the table's "Arduino" or "Due label" column: the cell without its `*(check)*` mark and its parenthesis, mapped through
PIN_LABEL_ALIASES when the whole cell is a key ("3.3 V" -> "3V3"), else its first word ("D14 TX3" -> "D14"). A cell the table marks
`*(check)*` (or whose column header is marked) keeps the mark in `Label.check`, and the plan, the CLI listing and the board's data
comment carry it: the name is the table's inference, not a read-off from the Due.

Placement. Labels of up to two characters are horizontal, centred on their pad; longer ones are turned 90 degrees (the name does not fit
the pitch with the gap two labels must keep) and run from the band's outer edge inward, so the label starts in the band and may enter the
copper-free strip between the band and the socket pads, never reaching a pad. A turned label that would reach a pad is narrowed down to
PIN_LABEL_MIN_W before it is reported. Text height is PIN_LABEL_H (the board house's 1.0 mm minimum).
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


def clean(cell, aliases=None):
    """the Due's name in one table cell"""
    s = re.sub(r'\*\(check\)\*', '', cell)
    s = re.sub(r'\([^)]*\)', '', s).strip()
    if aliases and s in aliases:
        return aliases[s]
    return s.split()[0] if s else ''


def parse_header_table(path, refs, aliases=None):
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
                            rows[ref][c[pk]] = Label(clean(c[lk], aliases), hchk or '(check)' in c[lk])
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


def _length(n, w, cfg):
    return n * cfg.PIN_LABEL_ADVANCE * w + cfg.PIN_LABEL_INK_PAD


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
    return parse_header_table(path, sorted(set(cfg.EDGE_SOCKETS.values())), getattr(cfg, 'PIN_LABEL_ALIASES', None))


def plan_labels(b, cfg):
    """[Planned] one per pad of the edge-row sockets. Returns what the config and the table say; the board's own silk is not read."""
    table = label_table(cfg)
    bands = [(n, r) for n, r in cfg.KEEPOUTS]
    out = []
    for sock, pin, hdr, (bx0, by0, bx1, by1), px, py in socket_pads(b, cfg):
        lab = table[hdr].get(pin)
        if lab is None:
            raise ValueError(f'{sock}.{pin}: the table has no pin {pin} for {hdr}')
        name, (rx0, ry0, rx1, ry1) = min(bands, key=lambda nr: abs(py - (nr[1][1] + nr[1][3]) / 2))
        south = (ry0 + ry1) / 2 < py                                  # the band lies on the low-y side of the pad
        n = len(lab.text)
        w = cfg.PIN_LABEL_W
        h = cfg.PIN_LABEL_H
        outer = (ry0 + cfg.PIN_LABEL_EDGE_MARGIN) if south else (ry1 - cfg.PIN_LABEL_EDGE_MARGIN)      # where the ink starts, at the band's outer edge
        inner = (by0 - cfg.PIN_LABEL_PAD_GAP) if south else (by1 + cfg.PIN_LABEL_PAD_GAP)             # the nearest a label may reach to the pad
        ink_h = h + cfg.PIN_LABEL_THICK
        if _length(n, w, cfg) <= _pitch(b, cfg, sock) - cfg.DESIGNATOR_GAP_ONE_LABEL:
            ang, length = 0.0, _length(n, w, cfg)
            cy = outer + ink_h / 2 if south else outer - ink_h / 2
            cx = px
        else:
            avail = abs(inner - outer)
            while _length(n, w, cfg) > avail and w > cfg.PIN_LABEL_MIN_W + 1e-9:
                w = max(cfg.PIN_LABEL_MIN_W, round(w - 0.01, 3))
            ang, length = 90.0, _length(n, w, cfg)
            cx = px
            cy = outer + length / 2 if south else outer - length / 2
        out.append(Planned(sock, pin, lab.text, round(cx, 3), round(cy, 3), ang, w, h, round(length, 3), lab.check, name))
    return out


def _pitch(b, cfg, sock):
    """the pad pitch of a socket's row: the smallest distance between two of its pads"""
    refs = list(b.fp_ref)
    j = np.flatnonzero(b.p_fp.astype(int) == refs.index(sock))
    xs = np.sort(b.p_x[j])
    return float(np.diff(xs).min()) if len(xs) > 1 else 2.54


def planned_boxes(plan, cfg):
    out = []
    for p in plan:
        ink_h = p.h + cfg.PIN_LABEL_THICK
        out.append(_box(p.x, p.y, p.length, ink_h, p.angle))
    return out


# ------------------------------------------------------------------------------------------------ the findings (LR-11)
def _gap(P, Q):
    from .rules import _convex_gap
    return float(_convex_gap(P, Q))


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
        if th[hit[0]] + 1e-6 < cfg.PIN_LABEL_H:
            bad.append(f'{p.ref}.{p.pin}: label "{p.text}" is {th[hit[0]]:.2f} mm high, under {cfg.PIN_LABEL_H}')
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
        if B[:, 1].min() < ry0 + m - 0.1 or B[:, 1].max() > ry1 - m + 0.1 or B[:, 0].min() < rx0 + m or B[:, 0].max() > rx1 - m:
            bad.append(f'{p.ref}.{p.pin}: "{p.text}" is within {m} mm of the board edge')
        near = np.flatnonzero((b.p_bx1 >= B[:, 0].min()) & (b.p_bx0 <= B[:, 0].max()) & (b.p_by1 >= B[:, 1].min()) & (b.p_by0 <= B[:, 1].max()))
        refs = list(b.fp_ref)
        for j in near:
            if _gap(B, np.array([[b.p_bx0[j], b.p_by0[j]], [b.p_bx1[j], b.p_by0[j]], [b.p_bx1[j], b.p_by1[j]], [b.p_bx0[j], b.p_by1[j]]])) <= 0:
                bad.append(f'{p.ref}.{p.pin}: "{p.text}" lies over pad {refs[int(b.p_fp[j])]}.{b.p_pin[j]}')
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
    a = ap.parse_args(argv)
    cfg = importlib.import_module('pcbtools.boards.' + a.config)
    b = boardio.read_board_retry(a.board)
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
