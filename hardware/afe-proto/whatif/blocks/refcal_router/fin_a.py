"""fin_a.py ROUTED_WITH_KEEPOUTS OUT : drop the helper rule areas, bring every track under 0.2 mm to 0.2, refill the zones"""
import sys
from pcbtools.editor import edit
src, out = sys.argv[1:3]
with edit(src, out) as e:
    pc = e.pcb
    kos = [z for z in e.b.Zones() if z.GetIsRuleArea() and str(z.GetZoneName()).startswith('ko_')]
    for z in kos:
        e.b.RemoveNative(z)
    n = 0
    for t in e.b.GetTracks():
        if t.GetClass() != 'PCB_VIA' and t.GetWidth() < pc.FromMM(0.2) - 10:
            t.SetWidth(pc.FromMM(0.2)); n += 1
    print('removed keepouts', len(kos), 'widened', n)
    e.fill_zones()
