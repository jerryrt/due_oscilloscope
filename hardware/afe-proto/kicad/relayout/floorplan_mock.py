"""Step-1 mock-up for the AWG / REFCAL / CH2-divider re-placement: today vs proposed, Due mm, y up."""
import sys, subprocess
S = 14.0; X0, X1, Y0, Y1 = 17.0, 117.0, 0.0, 53.34
def px(x, y): return (x - X0 + 2) * S, (Y1 - y + 2) * S
def panel(oy, title, rects, lanes, notes):
    o = []
    def R(a, b, c, d, **k):
        x0, y1 = px(a, b); x1, y0 = px(c, d)
        at = ' '.join(f'{kk.replace("_","-")}="{v}"' for kk, v in k.items())
        o.append(f'<rect x="{x0:.1f}" y="{y0+oy:.1f}" width="{x1-x0:.1f}" height="{y1-y0:.1f}" {at}/>')
    def T(x, y, t, s=12, f='#000', w='normal'):
        a, b = px(x, y); o.append(f'<text x="{a:.1f}" y="{b+oy:.1f}" font-size="{s}" fill="{f}" font-weight="{w}">{t}</text>')
    R(X0, Y0, X1, Y1, fill='#f4f4f0', stroke='#000', stroke_width=2)
    R(31.2-10, 7.5-10, 38.2+10, 12.2+10, fill='#d9822b', fill_opacity='0.08', stroke='#d9822b', stroke_dasharray='6 4', rx=140)
    for x in (66.04, 68.58):   # A1 / A0 hi-Z wall tracks
        R(x-0.3, 2.54, x+0.3, 38.0, fill='#222')
    R(65.2, 2.54, 69.4, 38.0, fill='none', stroke='#555', stroke_dasharray='2 3')
    T(61.0, 39.6, 'A1/A0 wall (y 2.5-38)', 10, '#333')
    for (a, b, c, d, col, name) in rects:
        R(a, b, c, d, fill=col, fill_opacity='0.18', stroke=col, stroke_width=2); T(a+0.4, d-1.4, name, 11, col, 'bold')
    for (a, b, c, d, col, name) in lanes:
        R(a, b, c, d, fill=col, fill_opacity='0.7'); T(a+0.3, d+0.9, name, 9, col)
    for name, x, y in (('J301 BNC',102,7.4),('J201 BNC',102,26.67),('J101 BNC',102,44.45),('J602',50.8,2.54),('J603',73.66,2.54)):
        a, b = px(x, y); o.append(f'<circle cx="{a:.1f}" cy="{b+oy:.1f}" r="5" fill="#c00"/>'); T(x+0.8, y+0.4, name, 10, '#c00')
    T(X0+0.5, Y1+1.3, title, 14, '#000', 'bold')
    for i, n in enumerate(notes): T(X0+1, 3 - 0 + 0, '', 1)
    return o
P='#d9822b'; Rc='#2a9d8f'; Sc='#3a6ea5'; Aw='#8a4fa8'; Rd='#e63946'
today_r = [(19.4,4.8,44.5,31.8,P,'POWER (unchanged)'),(44.7,5.4,65.15,39.45,Rc,'REFCAL/ADS'),
           (64.65,26.07,92.25,47.8,Sc,'SCOPE CH1'),(72.0,21.4,92.25,29.5,Sc,'CH2 divider'),(98.5,16.5,116.4,50.0,Sc,'CH1/CH2 BNC end'),
           (70.1,4.7,92.3,21.4,Aw,'AWG'),(98.5,0.6,116.4,15.5,Aw,'AWG BNC end')]
today_l = [(44,0.5,76,1.4,'#444','strip: +3V3A/VNEG/VREF (AWG)'),(44.0,24.0,63.6,25.0,Rd,'SCOPE +3V3A branch, around REFCAL'),
           (62.0,36.0,63.0,47.2,Rd,'QUIET VREF trunk'),(63.0,46.2,76,47.2,Rd,'')]
prop_r = [(19.4,4.8,44.5,31.8,P,'POWER (unchanged)'),(44.7,5.4,64.0,36.5,Rc,'REFCAL/ADS (re-placed, J602 taps south)'),
          (57.0,2.9,64.0,10.5,Rc,'U502 VREF source at the gate'),
          (64.65,26.07,92.25,47.8,Sc,'SCOPE CH1 (unchanged)'),(73.0,21.8,83.0,30.6,Sc,'CH2 divider (3x2 template)'),(98.5,16.5,116.4,50.0,Sc,'CH1/CH2 BNC end'),
          (73.0,4.7,92.3,21.0,Aw,'AWG (shifted east 3 mm)'),(98.5,0.6,116.4,15.5,Aw,'AWG BNC end')]
prop_l = [(44,0.5,76,1.4,'#444','gate strip (below the pins, no A0/A1 crossing)'),(69.9,1.4,70.5,24.0,'#444',''),(70.5,1.4,71.1,36.0,'#444',''),(71.1,1.4,71.7,26.0,'#444','east bus +3V3A/VNEG/VREF x 69.9-71.7')]
w = (X1-X0+4)*S; h = (Y1+4)*S
o = panel(0, 'TODAY: supply/VREF/sense reach SCOPE+AWG by 9 legs (the long ones around the north of REFCAL)', today_r, today_l, [])
o2 = panel((Y1+4)*S, 'PROPOSED: one gate under the pins, one east bus on the wall; only AWG_S (R501 east edge, R309) crosses the wall by a bridge', prop_r, prop_l, [])
open('/tmp/fpm.svg','w').write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{2*h:.0f}" font-family="sans-serif"><rect width="100%" height="100%" fill="#fff"/>'+'\n'.join(o+o2)+'</svg>')
subprocess.run(['convert','-density','144','/tmp/fpm.svg',sys.argv[1] if len(sys.argv)>1 else '/tmp/fpm.png'],check=True)
