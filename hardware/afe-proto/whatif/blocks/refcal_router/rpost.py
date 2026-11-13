"""rpost.py ROUTE.kicad_pcb SES OUT.kicad_pcb : import the session, report unconnected, save"""
import sys, pcbnew
rk, ses, out = sys.argv[1:4]
b = pcbnew.LoadBoard(rk)
b.BuildConnectivity(); u0 = b.GetConnectivity().GetUnconnectedCount(False)
ok = pcbnew.ImportSpecctraSES(b, ses)
b.BuildConnectivity(); u1 = b.GetConnectivity().GetUnconnectedCount(False)
print('import', ok, 'unconnected before', u0, 'after', u1, 'tracks', len(list(b.GetTracks())))
pcbnew.SaveBoard(out, b)
