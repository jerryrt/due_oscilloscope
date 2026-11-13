"""Put the board's identity on the v2 silk from the configuration (pcbtools/boards/v2.py: NAME, ID_LINE, SN_LABEL, JLC_ORDER_TEXT, IDENT):
the name, the model and revision line, the S/N label and its filled box on F.SilkS, the board house's order-number text mirrored on B.SilkS.

    python3 v2/layout/place_identity.py BOARD.kicad_pcb [--write OUT.kicad_pcb] [--check]

Pure text splice, no pcbnew (the board is not rewritten): identity items already on the board are removed and the configured ones appended
with deterministic uuids, so the script is idempotent and a board that already has them is written back unchanged. Exit 1 on --check when
the board still needs it.
"""
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from pcbtools.boards import v2 as cfg  # noqa: E402

NS = uuid.UUID('6f1f6d0e-3b1a-4c5e-9b1f-0a1d2c3b4a59')


def sheet(x, y):
    return x + 50.0, 150.0 - y


def f(v):
    return ('%.6f' % v).rstrip('0').rstrip('.')


def _text(word, x, y, h, layer):
    sx, sy = sheet(x, y)
    mir = '\n\t\t\t(justify mirror)' if layer.startswith('B.') else ''
    t = f(round(h * 0.15, 4))
    return (f'\t(gr_text "{word}"\n\t\t(at {f(sx)} {f(sy)} 0)\n\t\t(layer "{layer}")\n\t\t(uuid "{uuid.uuid5(NS, word + layer)}")\n'
            f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {f(h)} {f(h)})\n\t\t\t\t(thickness {t})\n\t\t\t){mir}\n\t\t)\n\t)\n')


def _box(x0, y0, x1, y1):
    ax, ay = sheet(x0, y1)
    bx, by = sheet(x1, y0)
    return (f'\t(gr_rect\n\t\t(start {f(ax)} {f(ay)})\n\t\t(end {f(bx)} {f(by)})\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type solid)\n\t\t)\n'
            f'\t\t(fill yes)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{uuid.uuid5(NS, "snbox")}")\n\t)\n')


def items():
    I = cfg.IDENT
    return [_text(cfg.NAME, *I['name'], 'F.SilkS'), _text(cfg.ID_LINE, *I['line'], 'F.SilkS'), _text(cfg.SN_LABEL, *I['sn_label'], 'F.SilkS'),
            _box(*I['sn_box']), _text(cfg.JLC_ORDER_TEXT, *I['jlc'], 'B.SilkS')]


def apply(text):
    words = {cfg.NAME, cfg.ID_LINE, cfg.SN_LABEL, cfg.JLC_ORDER_TEXT}
    def drop(m):
        b = m.group(0)
        if b.startswith('\n\t(gr_text'):
            w = re.match(r'\n\t\(gr_text "([^"]*)"', b).group(1)
            return '' if w in words or re.search(r'\bREV [A-Z]\b', w) else b
        return '' if '(fill yes)' in b and '(layer "F.SilkS")' in b else b
    text = re.sub(r'\n\t\((?:gr_text|gr_rect)\n?[^\n]*(?:\n\t\t[^\n]*)*\n\t\)', drop, text)
    i = text.rfind('\n\t(embedded_fonts')                  # inside the file's last items, before the trailer, as KiCad writes graphics
    if i < 0:
        i = text.rindex(')')
    return text[:i].rstrip('\n') + '\n' + ''.join(items()).rstrip('\n') + '\n' + text[i:].lstrip('\n') if i == text.rindex(')') else text[:i] + '\n' + ''.join(items()).rstrip('\n') + text[i:]


if __name__ == '__main__':
    a = sys.argv[1:]
    src = open(a[0]).read()
    out = apply(src)
    if '--check' in a:
        sys.exit(0 if out == src else 1)
    open(a[a.index('--write') + 1] if '--write' in a else a[0], 'w').write(out)
