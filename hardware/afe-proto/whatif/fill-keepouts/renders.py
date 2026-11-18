"""renders.py BOARD LABEL OUTDIR: the top copper of a board at 40 px/mm (kicad-cli SVG, rsvg-convert) and its 3D top, for before/after pictures. Run in the PCB image, from the repository
root holding the board in its own project directory (the 3D models are found from there). Writes OUTDIR/LABEL-top.png (full board, 40 px/mm) and OUTDIR/LABEL-3d.png.
The page is the board's rectangle (BOARD_RECT, Due mm, y up from its south edge), so pixel (x - X0) * 40, (Y1 - y) * 40 is a point of the board."""
import os, subprocess, sys
sys.path.insert(0, 'hardware/pcbkit')
board, label, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
svg = os.path.join(out, label + '-top.svg')
env = dict(os.environ, KICAD10_3DMODEL_DIR='/usr/share/kicad/3dmodels')
subprocess.run(['kicad-cli', 'pcb', 'export', 'svg', '--layers', 'F.Cu,Edge.Cuts', '--mode-single', '--exclude-drawing-sheet', '--page-size-mode', '2', '-o', svg, board], check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(['rsvg-convert', '-d', '1016', '-p', '1016', '-b', 'white', '-o', os.path.join(out, label + '-top.png'), svg], check=True)
os.remove(svg)
if '--no-3d' not in sys.argv:
    from pcbkit.render import render
    render(board, os.path.join(out, label + '-3d.png'))
