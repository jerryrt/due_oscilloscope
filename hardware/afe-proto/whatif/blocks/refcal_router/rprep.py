"""rprep.py IN.kicad_pcb OUT_ROUTE.kicad_pcb OUT.dsn : add the helper keepouts to a copy and export the Specctra DSN"""
import sys, pcbnew
from pcbtools.editor import edit
src, rk, dsn = sys.argv[1:4]
F = (44.5, 4.6, 64.5, 36.0)
with edit(src, rk) as e:
    for name, r in (('ko_w', (10, -10, F[0], 60)), ('ko_e', (F[2], -10, 125, 60)), ('ko_s', (F[0], -10, F[2], F[1])), ('ko_n', (F[0], F[3], F[2], 60))):
        e.keepout(r, name=name, tracks=True, vias=True, pour=True, layers='all')
    e.keepout(F, name='ko_bot', tracks=True, vias=False, pour=False, layers='B')
b = pcbnew.LoadBoard(rk)
ok = pcbnew.ExportSpecctraDSN(b, dsn)
print('dsn', ok)
