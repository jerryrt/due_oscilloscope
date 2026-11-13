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
