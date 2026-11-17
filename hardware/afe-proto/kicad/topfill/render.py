"""render.py BOARD OUT.png: render the top of a board from the project directory it lives in, after checking that every footprint's 3D model file exists.
${KIPRJMOD} is the directory of the board; a missing model (the board rendered from a scratch copy with no lib/ beside it) fails loudly instead of rendering a bare footprint."""
import sys, os, re, subprocess
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
board, out = os.path.abspath(sys.argv[1]), sys.argv[2]
d = os.path.dirname(board); bd = pcbnew.LoadBoard(board); missing = []; n = 0
for fp in bd.GetFootprints():
    for m in fp.Models():
        n += 1; f = m.m_Filename
        g = f.replace('${KIPRJMOD}', d)
        if '${' in g:
            g = re.sub(r'\$\{([^}]+)\}', lambda q: os.environ.get(q.group(1), q.group(0)), g)
            if '${' in g: print('unresolved variable (not checked):', fp.GetReference(), f); continue
        if not os.path.isfile(g): missing.append((fp.GetReference(), f))
print('models checked', n, 'missing', len(missing))
if missing:
    for r, f in missing: print('MISSING MODEL', r, f)
    sys.exit('refusing to render: %d 3D model files missing (is lib/ beside the board?)' % len(missing))
subprocess.run(['kicad-cli', 'pcb', 'render', '--side', 'top', '--quality', 'basic', '--width', '4800', '--height', '2800', '-o', out, board], check=True, capture_output=True)
print('rendered', out)
