"""Board renders that refuse to run while any 3D model file is missing.

    python3 -m pcbkit.render BOARD OUT.png [--side top|bottom] [--width 4800] [--height 2800] [--quality basic]

${KIPRJMOD} is the directory of the board; a missing model (a board rendered from a scratch copy with no model library beside it) fails loudly instead of rendering a bare
footprint. Other ${VAR} references are read from the environment; one that stays unresolved is reported and not checked. Needs pcbnew and kicad-cli (the PCB image)."""
import os, re, subprocess, sys
sys.path.append('/usr/lib/python3/dist-packages')


def check_models(board):
    """(models checked, [(ref, filename) missing], [(ref, filename) unresolved variable]) for every footprint model of `board`"""
    import pcbnew
    d = os.path.dirname(os.path.abspath(board))
    bd = pcbnew.LoadBoard(board)
    missing, unresolved, n = [], [], 0
    for fp in bd.GetFootprints():
        for m in fp.Models():
            n += 1
            f = m.m_Filename
            g = f.replace('${KIPRJMOD}', d)
            if '${' in g:
                g = re.sub(r'\$\{([^}]+)\}', lambda q: os.environ.get(q.group(1), q.group(0)), g)
                if '${' in g:
                    unresolved.append((fp.GetReference(), f))
                    continue
            if not os.path.isfile(g):
                missing.append((fp.GetReference(), f))
    return n, missing, unresolved


def render(board, out, side='top', width=4800, height=2800, quality='basic'):
    """check the models, then render; raises SystemExit naming the missing files instead of rendering"""
    board = os.path.abspath(board)
    n, missing, unresolved = check_models(board)
    for r, f in unresolved:
        print('unresolved variable (not checked):', r, f)
    print('models checked', n, 'missing', len(missing))
    if missing:
        for r, f in missing:
            print('MISSING MODEL', r, f)
        raise SystemExit('refusing to render: %d 3D model files missing (is the model library beside the board?)' % len(missing))
    subprocess.run(['kicad-cli', 'pcb', 'render', '--side', side, '--quality', quality, '--width', str(width), '--height', str(height), '-o', out, board], check=True, capture_output=True)
    print('rendered', out)
    return out


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='python3 -m pcbkit.render')
    ap.add_argument('board'); ap.add_argument('out')
    ap.add_argument('--side', default='top'); ap.add_argument('--width', type=int, default=4800); ap.add_argument('--height', type=int, default=2800); ap.add_argument('--quality', default='basic')
    a = ap.parse_args(argv)
    render(a.board, a.out, a.side, a.width, a.height, a.quality)


if __name__ == '__main__':
    main(sys.argv[1:])
