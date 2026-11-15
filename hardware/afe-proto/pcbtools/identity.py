"""The board's printed identity (docs/afe.md D29): the silk must carry exactly NAME, ID_LINE (MODEL and REV) and the S/N label from the
config, once each, an S/N box, and on the bottom the board house's order-number text.  Reads the .kicad_pcb text, no pcbnew."""
import re


def _texts(txt):
    """[(text, layer, height)] of the board-level texts"""
    out = []
    for m in re.finditer(r'\(gr_text "([^"]*)"(.*?)\n\t\)', txt, re.S):
        lay = re.search(r'\(layer "([^"]+)"', m.group(2))
        siz = re.search(r'\(size ([\d.]+) ', m.group(2))
        out.append((m.group(1), lay.group(1) if lay else '', float(siz.group(1)) if siz else 0.0))
    return out


def _boxes(txt):
    """[(w, h)] of the filled rectangles on F.SilkS"""
    out = []
    for m in re.finditer(r'\(gr_rect(.*?)\n\t\)', txt, re.S):
        b = m.group(1)
        if '(fill yes)' in b and '(layer "F.SilkS")' in b:
            s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', b)
            e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', b)
            out.append((abs(float(e.group(1)) - float(s.group(1))), abs(float(e.group(2)) - float(s.group(2)))))
    return out


def findings(txt, cfg):
    """the reasons the identity is wrong (empty = right)"""
    bad = []
    T = _texts(txt)
    for what, word, layer, h in (('name', cfg.NAME, 'F.SilkS', cfg.IDENT['name'][2]), ('model and revision', cfg.ID_LINE, 'F.SilkS', cfg.IDENT['line'][2]),
                                 ('S/N label', cfg.SN_LABEL, 'F.SilkS', cfg.IDENT['sn_label'][2]), ('order number', cfg.JLC_ORDER_TEXT, 'B.SilkS', cfg.IDENT['jlc'][2])):
        hit = [t for t in T if t[0] == word and t[1] == layer]
        if len(hit) != 1:
            bad.append(f'{what} {word!r}: {len(hit)} on {layer}, wanted exactly 1')
        elif abs(hit[0][2] - h) > 1e-6:
            bad.append(f'{what} {word!r} is {hit[0][2]} mm high, the config says {h}')
    # nothing else on the top silk that reads as a name, model or revision
    for t, lay, h in T:
        if lay == 'F.SilkS' and re.search(r'\bREV\b', t) and t != cfg.ID_LINE:
            bad.append(f'a revision line {t!r} other than {cfg.ID_LINE!r}')
    x0, y0, x1, y1 = cfg.IDENT['sn_box']
    if not any(abs(w - (x1 - x0)) < 1e-6 and abs(h - (y1 - y0)) < 1e-6 for w, h in _boxes(txt)):
        bad.append(f'no filled S/N box of {x1 - x0:g} x {y1 - y0:g} mm on F.SilkS')
    return bad


TEXT_ADVANCE = 1.0      # mm per character per mm of height: a generous extent for the name and the model line (the board house's stroke font is narrower)


def via_findings(vias, cfg, clear=0.3):
    """the vias that lie within `clear` mm (edge to edge) of the S/N box or of the name, model-and-revision or S/N-label text boxes of the top silk: the board house clips
    silk over a drill, so the filled box would print with holes and a letter with a gap. `vias`: [(x, y, diameter)] in Due mm; `cfg.IDENT` as above"""
    I = cfg.IDENT
    boxes = {'S/N box': tuple(I['sn_box'])}
    for what, word, key in (('name', cfg.NAME, 'name'), ('model and revision', cfg.ID_LINE, 'line'), ('S/N label', cfg.SN_LABEL, 'sn_label')):
        x, y, h = I[key]
        w = len(word) * TEXT_ADVANCE * h
        boxes[what] = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    bad = []
    for what, (x0, y0, x1, y1) in boxes.items():
        for vx, vy, d in vias:
            dx = max(x0 - vx, 0.0, vx - x1)
            dy = max(y0 - vy, 0.0, vy - y1)
            gap = (dx * dx + dy * dy) ** 0.5 - d / 2
            if gap < clear:
                bad.append(f'via at ({vx:.2f}, {vy:.2f}) is {max(gap, 0.0):.2f} mm from the {what}, under {clear}')
    return bad
