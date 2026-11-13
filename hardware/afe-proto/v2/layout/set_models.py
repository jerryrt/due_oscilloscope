"""Point each footprint named in boards/v2_layout.py MODEL_BY_REF at its 3D model file, by text splice (no KiCad needed; idempotent).

    python3 v2/layout/set_models.py BOARD.kicad_pcb [--write OUT.kicad_pcb]

Only the quoted path of the footprint's (model ...) entry changes; its offset, scale and rotation, and every other byte of the board, stay.
A reference with no (model ...) entry is an error (nothing is added). The project file is not touched.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from pcbtools.boards import v2_layout as cfg  # noqa: E402


def set_models(text, table=None):
    """(new text, [refs changed])"""
    table = cfg.MODEL_BY_REF if table is None else table
    changed = []
    for ref, path in table.items():
        for m in re.finditer(r'\n\t\(footprint "[^"]*"\n', text):
            end = text.find('\n\t(footprint ', m.end())
            end = len(text) if end < 0 else end
            if re.search(r'\(property "Reference" "%s"' % re.escape(ref), text[m.start():end]):
                break
        else:
            raise KeyError(ref)
        blk = text[m.start():end]
        pat = re.compile(r'(\n\t\t\(model ")[^"]*(")')
        assert len(pat.findall(blk)) == 1, f'{ref}: expected exactly one (model ...) entry'
        new = pat.sub(lambda mm: mm.group(1) + path + mm.group(2), blk)
        if new != blk:
            changed.append(ref)
            text = text[:m.start()] + new + text[end:]
    return text, changed


def main(argv):
    with open(argv[1]) as fh:
        text = fh.read()
    new, changed = set_models(text)
    print('models set:', changed or 'already as configured')
    if '--write' in argv:
        with open(argv[argv.index('--write') + 1], 'w') as fh:
            fh.write(new)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
