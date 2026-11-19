"""The track-geometry and fill-quality rules (pcbkit.rules) on the AFE boards: every finding, by kind, with its place, and the counts.

Run in the PCB image from hardware/afe-proto:   python3 pcbkit_regress/geometry.py v1|v2 [FILE.kicad_pcb]      (prints the report; exit 1 when there are findings)
The AFE's side: the net name and the frame are the AFE's; every limit and exception is in the board configuration (boards/v1_layout, v2_layout). pcbkit itself imports nothing from here."""
import sys, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
from pcbkit import board as kb, rules

FRAME = (50.0, 150.0)
BOARDS = {'v1': 'kicad/afe-proto.kicad_pcb', 'v2': 'v2/layout/integrated/afe-v2-integrated.kicad_pcb'}
CONFIGS = {'v1': 'v1_layout', 'v2': 'v2_layout'}      # the board configurations carry every geometry and fill setting the boards are judged by


def report(path, which='v1'):
    import importlib
    mod = importlib.import_module('pcbtools.boards.' + CONFIGS[which])
    names = [n.key for n in rules.TRACK_GEOMETRY_NAMES + rules.FILL_QUALITY_NAMES]          # only the names these two rules declare: the whole module carries others (KEEPOUT) the typo guard rejects
    CFG = {k: getattr(mod, k) for k in names if hasattr(mod, k)}
    b = kb.read_board(path, {'FRAME': FRAME})
    rows = []
    text = []
    tg = rules.track_geometry_parts(b, CFG, rows)
    fq, figs = rules.fill_quality_parts(b, CFG, rows)
    from pcbkit.config import format_report
    text.append(format_report(rows, 'track_geometry and fill_quality'))
    text.append('segments %d  arcs %d' % (len(b.s_idx), len(b.a_idx)))
    text.append('track_geometry %s' % dict(sorted(collections.Counter(k for k, *_ in tg).items())))
    text.append('fill_quality   %s  %s' % (dict(sorted(collections.Counter(k for k, *_ in fq).items())), {k: round(v, 1) for k, v in sorted(figs.items())}))
    for kind in ('stale_exception', 'arc', 'angle', 'jog', 'entry', 'over_pad', 'detour', 'stair', 'dangling', 'tspur', 'wide', 'narrow', 'dead_end', 'notch', 'pourrect', 'rough', 'shell', 'gndpad', 'thermal', 'solid'):
        for k, t, x, y in sorted((p for p in tg + fq if p[0] == kind), key=lambda p: (p[2], p[3])):
            text.append('%-8s %-7.2f %-7.2f %s' % (kind, x, y, t))
    return '\n'.join(text), len(tg) + len(fq)


if __name__ == '__main__':
    text, n = report(sys.argv[2] if len(sys.argv) > 2 else BOARDS[sys.argv[1]], sys.argv[1])
    print(text)
    sys.exit(1 if n else 0)
